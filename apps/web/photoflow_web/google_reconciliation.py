"""Portable evidence for a finite read-only reconciliation review.

This assembles observations, not retention decisions or executable cloud plans.
The worker owns remote job execution; local matching owns byte verification.
"""

import asyncio, copy, math, re, secrets, time
from fastapi import HTTPException, Request
from .core import atomic, load
from .google_contracts import JOB_SPECS, check, photo_key
from .google_identity import LocalGoogleMatches, account_value

TTL = 600
MAX_REVIEWS = 200
REQUIRED_EVIDENCE = [
    "current-remote-bytes-unverified", "takeout-roundtrip-unverified",
    "independent-backup-unverified", "companion-preservation-unverified",
    "album-intent-unclassified", "remote-ownership-unverified",
    "collection-inventory-incomplete",
]


def targets_for(photo_urls):
    check(isinstance(photo_urls, list) and 0 < len(photo_urls) <= 20)
    targets = [{"namespace": "library-media", "mediaKey": photo_key(url), "photoUrl": url, "jobId": None} for url in photo_urls]
    check(len({target["mediaKey"] for target in targets}) == len(targets))
    return targets


class ReconciliationReviews:
    def __init__(self, library, workers, now=time.time):
        self.library, self.workers, self.now = library, workers, now
        self.matches = LocalGoogleMatches(library)
        self.directory = library.path(".photoflow/google-reconciliation")
        self.directory.mkdir(mode=0o700, exist_ok=True)
        check(self.directory.stat().st_mode & 0o077 == 0)

    def path(self, ident):
        check(isinstance(ident, str) and re.fullmatch(r"[a-f0-9]{32}", ident))
        return self.library.path(f".photoflow/google-reconciliation/{ident}.json")

    def save(self, review):
        if not self.library.available():
            raise OSError("Storage unavailable")
        review["updatedAt"] = self.now()
        path = self.path(review["id"])
        atomic(path, review)
        path.chmod(0o600)

    def read(self, owner, account, ident):
        if not self.library.available():
            raise OSError("Storage unavailable")
        review = load(self.path(ident))
        if not review or review.get("owner") != owner or review.get("account") != account or review.get("libraryId") != self.library.id:
            raise KeyError("Review not found")
        check(review.get("schemaVersion") == 1 and review.get("id") == ident
              and review.get("readOnly") is True and review.get("retentionReady") is False
              and review.get("collectionComplete") is False)
        targets = review.get("targets")
        check(isinstance(targets, list))
        normalized = targets_for([target["photoUrl"] for target in targets])
        for target, expected in zip(targets, normalized):
            check(set(target) == set(expected) and target["namespace"] == expected["namespace"] and target["mediaKey"] == expected["mediaKey"])
            check(target["jobId"] is None or isinstance(target["jobId"], str) and re.fullmatch(r"[a-f0-9]{32}", target["jobId"]))
        items = review.get("items")
        check(isinstance(items, list) and len(items) <= len(targets))
        check(len({item["mediaKey"] for item in items}) == len(items))
        for item in items:
            target = next((t for t in targets if t["mediaKey"] == item["mediaKey"]), None)
            check(target and item["remote"]["jobId"] == target["jobId"])
            if item["remote"]["state"] == "observed":
                remote = item["remote"]
                JOB_SPECS["photo-details"]["validate_result"]({"photo": remote["photo"], "retentionReady": False})
                check(remote["photo"]["mediaKey"] == target["mediaKey"])
                check(type(remote["observedAt"]) in (int, float) and math.isfinite(remote["observedAt"])
                      and review["createdAt"] <= remote["observedAt"] <= self.now())
        return review

    def view(self, review):
        result = copy.deepcopy(review)
        observed = [item["remote"] for item in result["items"] if item["remote"]["state"] == "observed"]
        fresh = len(observed) == len(result["targets"]) and all(0 <= self.now() - item["observedAt"] <= TTL for item in observed)
        result["remoteFresh"] = fresh
        if result["state"] == "review-ready" and not fresh:
            result["state"] = "stale"
        for item in result["items"]:
            remote = item["remote"]
            if remote["state"] == "observed" and self.now() - remote["observedAt"] > TTL:
                item["blockedBy"].append("remote-observation-stale")
        return result

    def get(self, owner, account, ident):
        with self.library.mutex:
            return self.view(self.read(owner, account, ident))

    def list(self, owner, account):
        account_value(account)
        if not self.library.available():
            raise OSError("Storage unavailable")
        items = []
        with self.library.mutex:
            for path in self.directory.glob("*.json"):
                data = load(self.path(path.stem))
                if data.get("owner") == owner and data.get("account") == account:
                    review = self.get(owner, account, path.stem)
                    items.append({key: review[key] for key in ("id", "state", "createdAt", "summary", "remoteFresh")})
        return {"items": sorted(items, key=lambda item: (item["createdAt"], item["id"]), reverse=True)[:20]}

    def bind_jobs(self, review):
        if any(target["jobId"] is None for target in review["targets"]):
            jobs = self.workers.observation_jobs(review["owner"], review["account"], review["id"], [target["photoUrl"] for target in review["targets"]])
            for target, job in zip(review["targets"], jobs):
                target["jobId"] = job["id"]
            self.save(review)

    def create(self, owner, account, photo_urls):
        account_value(account)
        targets = targets_for(photo_urls)
        check(self.workers.status(owner)["account"] == account)
        with self.library.writer():
            check(sum(1 for _ in self.directory.glob("*.json")) < MAX_REVIEWS)
            review = {"schemaVersion": 1, "id": secrets.token_hex(16), "owner": owner,
                      "libraryId": self.library.id, "account": account, "createdAt": self.now(),
                      "state": "collecting", "scope": "selected-library-media", "targets": targets,
                      "items": [], "summary": {"selected": len(targets), "observed": 0, "localVerified": 0, "failed": 0},
                      "readOnly": True, "retentionReady": False, "collectionComplete": False}
            self.save(review)  # Durable finite selection before enqueueing any read.
            self.bind_jobs(review)
            return self.view(review)


    def observe(self, review, target, previous):
        if previous and previous["remote"]["state"] == "observed":
            return previous["remote"]  # Retain dated evidence even if disposable job storage is lost.
        job = self.workers.observation_job(review["owner"], review["account"], review["id"], target["jobId"], target["photoUrl"])
        if job["state"] != "succeeded":
            return {"jobId": target["jobId"], "state": job["state"], "error": job.get("error")}
        check(type(job["started"]) in (float, int) and review["createdAt"] <= job["started"] <= self.now())
        return {"state": "observed", "jobId": target["jobId"], "observedAt": job["started"],
                "recordedAt": self.now(), "photo": job["result"]["photo"]}

    def refresh(self, owner, account, ident):
        with self.library.writer():
            review = self.read(owner, account, ident)
            self.bind_jobs(review)
            previous = {item["mediaKey"]: item for item in review["items"]}
            items = []
            for target in review["targets"]:
                remote = self.observe(review, target, previous.get(target["mediaKey"]))
                items.append({"mediaKey": target["mediaKey"], "remote": remote, "local": None,
                              "localRecords": [], "localCheckedAt": None, "blockedBy": list(REQUIRED_EVIDENCE), "protections": []})
            verified_targets = [{"namespace": "library-media", "mediaKey": item["mediaKey"], "dedupKey": item["remote"]["photo"]["dedupKey"], "size": item["remote"]["photo"]["size"]}
                                for item in items if item["remote"]["state"] == "observed" and item["remote"]["photo"]["size"] > 0]
            local = {item["mediaKey"]: item for item in self.matches.check(account, verified_targets)["items"]} if verified_targets else {}
            for item in items:
                remote = item["remote"]
                if remote["state"] != "observed":
                    item["blockedBy"].append("remote-observation-pending" if remote["state"] in ("queued", "running") else "remote-observation-failed")
                    continue
                photo = remote["photo"]
                item["local"] = local.get(item["mediaKey"])
                item["localCheckedAt"] = self.now()
                if not item["local"] or item["local"]["state"] != "verified-local":
                    item["blockedBy"].append("local-original-unverified")
                else:
                    for record_id in item["local"]["recordIds"]:
                        proof = next(candidate for candidate in item["local"]["candidates"] if candidate["recordId"] == record_id)
                        record, _ = self.library.checked(record_id, proof["revision"])
                        item["localRecords"].append({"recordId": record_id, "revision": proof["revision"], "sha256": proof["sha256"]})
                        if record.get("resolved", {}).get("favorite") is True:
                            item["protections"].append("local-favorite")
                if photo["favorite"] is True:
                    item["protections"].append("remote-favorite")
                if photo["favorite"] is None:
                    item["blockedBy"].append("remote-favorite-unknown")
                if photo.get("albums") is None:
                    item["blockedBy"].append("remote-albums-unknown")
                if photo["trashTimestamp"]:
                    item["protections"].append("remote-in-trash")
                item["protections"] = sorted(set(item["protections"]))
            pending = any(item["remote"]["state"] in ("queued", "running") for item in items)
            failed = sum(item["remote"]["state"] not in ("observed", "queued", "running") for item in items)
            review.update(items=items, state="collecting" if pending else "incomplete" if failed else "review-ready",
                          summary={"selected": len(items), "observed": sum(item["remote"]["state"] == "observed" for item in items),
                                   "localVerified": sum(bool(item["local"] and item["local"]["state"] == "verified-local") for item in items), "failed": failed})
            self.save(review)
            return self.view(review)


def install_review_routes(app, library, workers, session, wake):
    reviews = ReconciliationReviews(library, workers)
    app.state.google_reconciliation = reviews

    def paired(req, account, write=False):
        owner = session(req, 3, write)["username"]
        current = workers.status(owner)["account"]
        if not current or account != current:
            raise HTTPException(409, "Refresh the paired Google account before reviewing reconciliation")
        return owner

    @app.post("/api/v1/google/reconciliation/reviews")
    async def create_review(req: Request, body: dict):
        session(req, 3, True)
        check(set(body) == {"account", "photoUrls"})
        owner = paired(req, body["account"], True)
        result = await asyncio.to_thread(reviews.create, owner, body["account"], body["photoUrls"])
        wake()
        paired(req, body["account"], True)
        return result

    @app.get("/api/v1/google/reconciliation/reviews")
    async def list_reviews(req: Request, account: str):
        owner = paired(req, account)
        result = await asyncio.to_thread(reviews.list, owner, account)
        paired(req, account)
        return result

    @app.get("/api/v1/google/reconciliation/reviews/{ident}")
    async def get_review(ident: str, req: Request, account: str):
        owner = paired(req, account)
        result = await asyncio.to_thread(reviews.get, owner, account, ident)
        paired(req, account)
        return result

    @app.post("/api/v1/google/reconciliation/reviews/{ident}/refresh")
    async def refresh_review(ident: str, req: Request, body: dict):
        session(req, 3, True)
        check(set(body) == {"account"})
        owner = paired(req, body["account"], True)
        result = await asyncio.to_thread(reviews.refresh, owner, body["account"], ident)
        wake()
        paired(req, body["account"], True)
        return result

