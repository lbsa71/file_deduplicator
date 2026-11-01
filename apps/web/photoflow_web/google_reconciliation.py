"""Read-only preparation and hash-bound, resumable execution of finite Google plans.

Pilot cleanup is deliberately distinct from production retention approval. A
publication port must prove absence and own its upload/unknown-outcome journal.
"""

import hashlib
import json
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from .core import Conflict, atomic, digest, load
from .google_contracts import JOB_SPECS, photo_key
from .google_identity import associations
from .jobs import (
    Deferred,
    JobCoordinator,
    JobStore,
    PartialResult,
    ReconciliationRequired,
)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def manifest_hash(value):
    return digest(canonical({k: v for k, v in value.items() if k != "sha256"}))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def photo_url(key):
    return "https://photos.google.com/photo/" + key


class Reconciliation:
    def __init__(
        self,
        library,
        remote,
        now=time.time,
        authorize=lambda owner: True,
        wake=lambda: None,
        publisher=None,
    ):
        self.library, self.remote, self.now = library, remote, now
        self.authorize, self.wake, self.publisher = authorize, wake, publisher
        self.directory = library.state / "google-reconciliation"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(
            self.directory.stat().st_mode & 0o077 == 0,
            "Reconciliation state must be private",
        )
        self.jobs = JobStore(self.directory, library.id, clock=now)
        with self.jobs.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS worker_requests(job TEXT,name TEXT,attempt INTEGER,request_key TEXT NOT NULL,PRIMARY KEY(job,name,attempt))"
            )
        self.remote.retention_check = self.retention_check
        self.runner = JobCoordinator(
            self.jobs,
            self.execute,
            lambda job: authorize(job["owner"]),
            library.available,
        )

    def close(self):
        self.runner.close()

    def account(self, owner):
        value = self.remote.status(owner)["account"]
        require(value is not None, "Pair a Google account before preparing a plan")
        return value

    def options(self, options):
        require(
            isinstance(options, dict)
            and set(options) <= {"photoUrls", "nonVital", "reserveBytes"},
            "Unsupported preparation options",
        )
        urls = options.get("photoUrls", [])
        require(
            isinstance(urls, list) and len(urls) <= 100,
            "Select up to 100 photo URLs, or leave empty for full inventory",
        )
        keys = [photo_key(url) for url in urls]
        require(len(keys) == len(set(keys)), "Duplicate selected targets")
        non_vital = options.get("nonVital", False)
        require(
            type(non_vital) is bool and (not non_vital or bool(keys)),
            "Non-vital pilots require explicit photo targets",
        )
        reserve = options.get("reserveBytes", 256 * 1024**2)
        require(
            type(reserve) is int and 0 <= reserve <= 1024**4, "Invalid quota reserve"
        )
        return {
            "photoUrls": sorted(photo_url(key) for key in keys),
            "nonVital": non_vital,
            "reserveBytes": reserve,
        }

    def prepare(self, owner, options):
        require(self.authorize(owner), "Administrator authority required")
        value = self.options(options)
        return self.runner.enqueue(
            owner,
            "google.prepare",
            {"account": self.account(owner), "options": value},
            private=True,
        )

    def retention_check(self, owner, account, scope):
        from .google_takeout import PURPOSE, verify_copy

        value = self.manifest(owner, scope["manifestId"])
        require(
            value["sha256"] == scope["manifestSha256"]
            and value["account"] == account
            and value["libraryId"] == self.library.id,
            "Retention manifest identity changed",
        )
        require(
            value["capabilities"]["productionRetention"] is True
            and self.now() < value["expiresAt"]
            and self.authorize(owner)
            and self.library.available(),
            "Retention authority expired or revoked",
        )
        matches = [
            op
            for op in value["operations"]
            if op.get("expect", {}).get("mediaKey") == scope["photoKey"]
        ]
        require(len(matches) == 1, "Retention target must be unique")
        op = matches[0]
        require(
            op["authority"] == PURPOSE
            and op["operation"] == "trash"
            and op["expect"]["dedupKey"] == scope["dedupKey"]
            and op["localEvidence"]["sha256"] == scope["localSha256"],
            "Retention evidence changed",
        )
        verify_copy(self.library, op["localEvidence"], scope["photoKey"])
        return True

    def prepare_takeout(self, owner, ident):
        require(self.authorize(owner), "Administrator authority required")
        source = self.manifest(owner, ident)
        require(
            source["inventoryScope"] == "account"
            and source["inventoryComplete"] is True,
            "Complete account inventory required",
        )
        require(
            not source["capabilities"]["productionRetention"],
            "Select the source inventory",
        )
        require(source["account"] == self.account(owner), "Google account changed")
        require(
            self.remote.status(owner).get("pilotTargetPolicy") == "selected",
            "Owner account authorization required",
        )
        return self.runner.enqueue(
            owner,
            "google.prepare-takeout",
            {
                "account": source["account"],
                "sourceManifestId": ident,
                "sourceSha256": source["sha256"],
            },
            key="takeout:" + ident,
            private=True,
        )

    def path(self, ident):
        require(
            isinstance(ident, str)
            and len(ident) == 32
            and all(c in "0123456789abcdef" for c in ident),
            "Invalid manifest identifier",
        )
        return self.directory / (ident + ".json")

    def manifest(self, owner, ident):
        value = load(self.path(ident))
        if not value or value["owner"] != owner:
            raise KeyError(ident)
        if value.get("sha256") != manifest_hash(value):
            raise Conflict("Manifest changed or is corrupt; prepare again")
        return value

    def validate(self, owner, value, expiration=True):
        if value["libraryId"] != self.library.id or value["account"] != self.account(
            owner
        ):
            raise Conflict("Library or Google account changed; prepare again")
        if expiration and self.now() > value["expiresAt"]:
            if value.get("capabilities", {}).get("productionRetention"):
                raise Conflict(
                    "Manifest expired; reconcile any unknown write, then prepare a fresh full inventory and Takeout Trash sweep. Completed Trash items are excluded from the library inventory."
                )
            raise Conflict("Manifest expired; prepare again")
        if not self.library.available():
            raise OSError("Library storage is unavailable")
        for item in value["local"]:
            try:
                record, _ = self.library.checked(item["recordId"], item["revision"])
                current = self.library.fs.stat(
                    record["file"]["relative_path"]
                ).to_dict()
                if current != item["fingerprint"]:
                    raise Conflict("Local content revision changed; prepare again")
            except (KeyError, FileNotFoundError):
                raise Conflict("Local record is unavailable; prepare again") from None

    def commit(self, owner, ident, expected_hash):
        require(self.authorize(owner), "Administrator authority required")
        value = self.manifest(owner, ident)
        if value["sha256"] != expected_hash:
            raise Conflict("Reviewed manifest hash does not match")
        key = "commit:" + ident + ":" + expected_hash[:32]
        with self.jobs.db() as db:
            previous = db.execute(
                "SELECT data FROM commands WHERE owner=? AND request_key=?",
                (owner, key),
            ).fetchone()
        if previous:
            # Repeated approval returns the original execution receipt. Local
            # ingestion may legitimately have enriched sidecars during that run.
            return json.loads(previous[0])
        self.validate(owner, value)
        if value["options"]["nonVital"]:
            require(
                self.remote.status(owner).get("pilotTargetPolicy") == "selected",
                "Selected-target account authorization is required for this pilot",
            )
        return self.runner.enqueue(
            owner,
            "google.commit",
            {
                "account": value["account"],
                "manifestId": ident,
                "sha256": expected_hash,
                "expiresAt": value["expiresAt"],
            },
            key=key,
            private=True,
        )

    def resume(self, owner, ident):
        require(self.authorize(owner), "Administrator authority required")
        job = self.jobs.get(ident)
        if job["owner"] != owner:
            raise KeyError(ident)
        if job["action"] in ("google.prepare", "google.prepare-takeout"):
            if self.account(owner) != job["params"]["account"]:
                raise Conflict("Google account changed; prepare again")
            if self.now() > job["created"] + 86400:
                raise Conflict("Preparation expired; prepare again")
            if not self.library.available():
                raise OSError("Library storage is unavailable")
        else:
            require(
                job["action"] == "google.commit", "Unsupported reconciliation command"
            )
            if (job.get("result") or {}).get("deferred"):
                raise Conflict("Deferred uploads belong to a new preparation run")
            manifest = self.manifest(owner, job["params"]["manifestId"])
            self.validate(owner, manifest)
        value = self.jobs.retry(ident)
        if self.runner.started:
            self.runner.wake()
        return value

    def _remote(
        self,
        job,
        context,
        name,
        operation,
        value,
        confirmed=False,
        retention_scope=None,
    ):
        def work():
            if self.account(job["owner"]) != job["params"]["account"]:
                raise Conflict("Google account changed")
            if not retention_scope:
                context.checkpoint(stage=name)
            key = job["id"] + ":" + digest(name.encode())[:32]
            # Explicit read-only preparation retries keep completed steps and
            # failed worker receipts. Commit intents keep their original key.
            if job["action"] == "google.prepare":
                require(
                    JOB_SPECS[operation]["effect"] == "read",
                    "Preparation must remain read-only",
                )
                if job["attempt"] > 1:
                    key += ":read-retry:" + str(job["attempt"])
            with self.jobs.db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO worker_requests VALUES(?,?,?,?)",
                    (job["id"], name, job["attempt"], key),
                )
            state = self.remote.enqueue_once(
                job["owner"],
                key,
                operation,
                value,
                confirmed,
                not_after=job["params"].get("expiresAt", job["created"] + 86400),
                **({"retention_scope": retention_scope} if retention_scope else {}),
            )
            self.wake()
            if state["state"] in ("queued", "running"):
                raise Deferred(
                    "waiting_for_google_worker", retry_after=1 if retention_scope else 5
                )
            if state["state"] == "unknown":
                raise ReconciliationRequired(
                    "Google outcome is unknown; reconcile the original job before proceeding"
                )
            if state["state"] != "succeeded":
                raise ValueError(
                    "Google operation stopped: "
                    + str(state.get("error") or state["state"])
                )
            result = self.remote.result(job["owner"], state["id"])["result"]
            JOB_SPECS[operation]["validate_result"](result)
            return result

        # Repeating this step only looks up the exact stable worker job; it never
        # creates another remote intent after success, disconnect or unknown outcome.
        return context.step(name, work, replay_safe=True)

    def pages(self, job, context, operation, extra=None):
        result = []
        cursor = None
        seen = set()
        identities = set()
        for index in range(10000):
            value = {**(extra or {}), "cursor": cursor}
            label = (
                operation
                + ":"
                + str((extra or {}).get("albumId", ""))
                + ":"
                + str(index)
            )
            page = self._remote(job, context, label, operation, value)
            for item in page["items"]:
                key = item.get("mediaKey", item.get("albumId"))
                require(key not in identities, "Repeated identity in remote inventory")
                identities.add(key)
                result.append(item)
            require(len(result) <= 1000000, "Remote inventory exceeds run limit")
            if page["next"] is None:
                return result
            require(page["next"] not in seen, "Repeated remote pagination cursor")
            seen.add(page["next"])
            cursor = page["next"]
        raise ValueError("Remote inventory exceeds page limit")

    def local(self):
        def records():
            # Stream the large portable sidecars from the catalog. The run keeps
            # compact evidence summaries, not a second full collection in memory.
            with self.library.db() as db:
                yield from db.execute("SELECT id,revision,data FROM photos ORDER BY id")

        result = []
        for row in records():
            record = json.loads(row["data"])
            if record.get("lifecycle") == "trashed":
                continue
            references = set()
            documents = []
            for source in record["sources"]:
                for doc in source.get("documents", []):
                    url = doc.get("document", {}).get("url")
                    if isinstance(url, str):
                        try:
                            references.add(photo_key(url))
                        except ValueError:
                            continue
                        documents.append(
                            {
                                "sha256": doc.get("sha256"),
                                "path": doc.get("relative_path"),
                            }
                        )
            verified = [
                {"account": a, "mediaKey": m, "dedupKey": d, "sha256": s}
                for a, m, d, s in sorted(associations(record))
            ]
            # A preparation snapshot may include unavailable records, but it never
            # silently upgrades them to verified originals or deletion permission.
            try:
                fingerprint = self.library.fs.stat(
                    record["file"]["relative_path"]
                ).to_dict()
            except OSError:
                fingerprint = None
            result.append(
                {
                    "recordId": row["id"],
                    "revision": row["revision"],
                    "path": record["file"]["relative_path"],
                    "sha256": record["file"].get("sha256"),
                    "size": record["file"].get("size_bytes"),
                    "fingerprint": fingerprint,
                    "favorite": record.get("resolved", {}).get("favorite") is True,
                    "curated": bool(record.get("overrides", {}).get("albums")),
                    "references": sorted(references),
                    "associations": verified,
                    "metadataEvidence": documents,
                }
            )
        return result

    def execute(self, job, context):
        if job["action"] == "google.prepare-takeout":
            from .google_takeout import prepare_sweep

            return prepare_sweep(self, job, context)
        if job["action"] == "google.prepare":
            return self._prepare(job, context)
        if job["action"] == "google.commit":
            return self._commit(job, context)
        raise ValueError("Unsupported reconciliation command")

    def _prepare(self, job, context):
        options = job["params"]["options"]
        selected = {photo_key(url) for url in options["photoUrls"]}
        selected_details = []
        if selected:
            for key in sorted(selected):
                selected_details.append(
                    self._remote(
                        job,
                        context,
                        "prepare-detail:" + key,
                        "photo-details",
                        {"photoUrl": photo_url(key)},
                    )["photo"]
                )
            fields = (
                "namespace",
                "mediaKey",
                "dedupKey",
                "favorite",
                "trashTimestamp",
                "companion",
            )
            inventory = [
                {field: photo[field] for field in fields} for photo in selected_details
            ]
        else:
            inventory = self.pages(job, context, "library-page")
        favorites = self.pages(job, context, "favorites-page")
        albums = self.pages(job, context, "albums-page")
        memberships = defaultdict(list)
        if selected:
            # Detail results are exact-target observations, not a complete account
            # inventory or absence proof. Unknown membership blocks pilot writes.
            for photo in selected_details:
                for album in photo.get("albums") or []:
                    memberships[photo["dedupKey"]].append(album["albumId"])
        else:
            for album in albums:
                for member in self.pages(
                    job, context, "album-members", {"albumId": album["albumId"]}
                ):
                    memberships[member["dedupKey"]].append(album["albumId"])
        local = self.local()
        account = job["params"]["account"]
        favorites = {item["mediaKey"] for item in favorites}
        by_reference = defaultdict(list)
        for item in local:
            for key in set(item["references"]) | {
                a["mediaKey"] for a in item["associations"] if a["account"] == account
            }:
                by_reference[key].append(item)
        remote_keys = {item["mediaKey"] for item in inventory}
        require(
            selected <= remote_keys,
            "Selected photo is not in the complete remote inventory",
        )
        items = []
        cleanup = []
        downloads = []
        uploads = []
        for remote in sorted(inventory, key=lambda item: item["mediaKey"]):
            key = remote["mediaKey"]
            matches = by_reference.get(key, [])
            protected = (
                key in favorites
                or remote.get("favorite") is True
                or bool(memberships.get(remote["dedupKey"]))
                or any(m["favorite"] or m["curated"] for m in matches)
            )
            item = {
                "namespace": "library-media",
                "mediaKey": key,
                "dedupKey": remote["dedupKey"],
                "localRecordIds": [m["recordId"] for m in matches],
                "albumIds": sorted(memberships.get(remote["dedupKey"], [])),
                "remoteFavorite": key in favorites or remote.get("favorite") is True,
                "companion": remote.get("companion"),
            }
            if protected:
                item.update(
                    action="keep",
                    reason="Favorite or album membership protects this item",
                )
            elif options["nonVital"] and key in selected:
                detail = self._remote(
                    job,
                    context,
                    "prepare-detail:" + key,
                    "photo-details",
                    {"photoUrl": photo_url(key)},
                )["photo"]
                require(
                    detail["dedupKey"] == remote["dedupKey"],
                    "Selected photo identity changed",
                )
                require(
                    detail.get("favorite") is False
                    and detail.get("albums") == []
                    and detail.get("companion") is not True,
                    "Non-vital cleanup target must have known unprotected standalone state",
                )
                item.update(
                    action="pilot-trash",
                    reason="Explicit non-vital target; qualification pilot, not production retention proof",
                )
                cleanup.append(
                    {
                        "phase": "cleanup",
                        "operation": "photo-details",
                        "input": {"photoUrl": photo_url(key)},
                        "expect": {"mediaKey": key, "dedupKey": remote["dedupKey"]},
                    }
                )
                cleanup.append(
                    {
                        "phase": "cleanup",
                        "operation": "trash",
                        "input": {"photoUrl": photo_url(key)},
                        "authority": "explicit-non-vital-pilot",
                    }
                )
            elif key in selected:
                detail = self._remote(
                    job,
                    context,
                    "prepare-detail:" + key,
                    "photo-details",
                    {"photoUrl": photo_url(key)},
                )["photo"]
                name = detail["filename"]
                supported = (
                    Path(name).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                    and 0 < detail["size"] <= 16 * 1024**2
                    and detail.get("companion") is not True
                )
                item.update(
                    action=(
                        ("verify-original" if matches else "download")
                        if supported
                        else "unsupported"
                    ),
                    reason=(
                        (
                            "Verify Google bytes and attach an account-bound association"
                            if matches
                            else "Preserve selected remote-only original"
                        )
                        if supported
                        else "Original exceeds qualified transfer coverage"
                    ),
                )
                if supported:
                    downloads.append(
                        {
                            "phase": "preserve",
                            "operation": "download-original",
                            "input": {"photoUrl": photo_url(key)},
                        }
                    )
            elif matches:
                item.update(
                    action="review-trash",
                    reason="Candidate association only; fresh remote bytes, ownership and metadata evidence are required; owner accepts the Takeout backup without verification",
                    blocked=True,
                )
            else:
                item.update(
                    action="keep",
                    reason="No verified local original; retain in Google",
                    blocked=True,
                )
            items.append(item)
        for item in local:
            if any(key in remote_keys for key in item["references"]) or any(
                a["account"] == account and a["mediaKey"] in remote_keys
                for a in item["associations"]
            ):
                continue
            value = {
                "recordId": item["recordId"],
                "action": "publication-candidate",
                "reason": "Remote absence is unproved; metadata absence is not permission to upload",
                "blocked": True,
            }
            # Only an injected, qualified publisher may establish absence. The
            # production default has no uploader and explicitly defers this work.
            if self.publisher and self.publisher.inspect(item, account) is True:
                value.update(
                    action="upload",
                    reason="Qualified publisher verified local revision and remote absence",
                    blocked=False,
                )
                uploads.append(
                    {
                        "phase": "publish",
                        "operation": "upload-image",
                        "input": {
                            "recordId": item["recordId"],
                            "revision": item["revision"],
                            "sha256": item["sha256"],
                            "size": item["size"],
                        },
                    }
                )
            items.append(value)
        cleaned_records = {
            ident
            for item in items
            if item["action"] == "pilot-trash"
            for ident in item.get("localRecordIds", [])
        }
        cleaned_hashes = {
            item["sha256"]
            for item in local
            if item["recordId"] in cleaned_records and item["sha256"]
        }
        require(
            not cleaned_hashes.intersection(
                operation["input"]["sha256"] for operation in uploads
            ),
            "Conflicting cleanup and publication of identical content",
        )
        now = self.now()
        ident = job["id"]
        operations = (
            downloads
            + cleanup
            + [{"phase": "capacity", "operation": "storage-quota", "input": {}}]
            + uploads
        )
        for index, operation in enumerate(operations):
            operation["seq"] = index + 1
        with self.jobs.db() as db:
            observations = [
                {
                    "step": row["name"],
                    "workerRequestKey": (
                        db.execute(
                            "SELECT request_key FROM worker_requests WHERE job=? AND name=? ORDER BY attempt DESC LIMIT 1",
                            (job["id"], row["name"]),
                        ).fetchone()
                        or [job["id"] + ":" + digest(row["name"].encode())[:32]]
                    )[0],
                    "resultSha256": digest(canonical(json.loads(row["result"]))),
                }
                for row in db.execute(
                    "SELECT name,result FROM steps WHERE job=? AND state='done' ORDER BY name",
                    (job["id"],),
                )
            ]
        manifest = {
            "schemaVersion": 1,
            "id": ident,
            "owner": job["owner"],
            "libraryId": self.library.id,
            "account": account,
            "createdAt": now,
            "expiresAt": now + 86400,
            "options": options,
            "retentionPolicy": {
                "version": "keep-starred-album-or-no-verified-local-v1",
                "keep": ["starred", "any-album", "no-verified-local-original"],
                "backupRequirement": "owner-asserted-takeout",
                "backupVerified": False,
                "cleanup": "reviewed-reversible-trash-only",
            },
            "inventoryComplete": True,
            "inventoryScope": "selected" if selected else "account",
            "observations": observations,
            "counts": {
                "remote": len(inventory),
                "local": len(local),
                "albums": len(albums),
                "actions": dict(Counter(i["action"] for i in items)),
            },
            "local": local,
            "items": items,
            "operations": operations,
            "capabilities": {
                "productionRetention": False,
                "imagePublication": self.publisher is not None,
                "permanentDelete": False,
            },
            "limitations": [
                "Legacy Takeout URLs are candidates, not verified current remote bytes.",
                "Production retention and arbitrary-image publication remain blocked pending qualified evidence/adapters.",
            ],
        }
        manifest["sha256"] = manifest_hash(manifest)
        self.validate(job["owner"], manifest)
        existing = load(self.path(ident))
        if existing:
            # Recovery after publishing the immutable manifest keeps its original
            # timestamps and digest; never replace a reviewed plan during replay.
            return {
                "manifestId": ident,
                "sha256": self.manifest(job["owner"], ident)["sha256"],
                "counts": existing["counts"],
            }
        atomic(self.path(ident), manifest)
        return {
            "manifestId": ident,
            "sha256": manifest["sha256"],
            "counts": manifest["counts"],
        }

    def _commit(self, job, context):
        manifest = self.manifest(job["owner"], job["params"]["manifestId"])
        if manifest["sha256"] != job["params"]["sha256"]:
            raise Conflict("Manifest changed")
        # Completed steps may legitimately change local associations. Validate the
        # frozen starting revision only before this commit's first remote effect.
        context.step(
            "validate-manifest",
            lambda: self.validate(job["owner"], manifest) or True,
            replay_safe=False,
        )
        if self.now() > manifest["expiresAt"]:
            raise Conflict("Manifest expired; prepare again")
        if self.account(job["owner"]) != manifest["account"]:
            raise Conflict("Google account changed")
        completed = []
        deferred = []
        capacity = None
        with self.jobs.db() as db:
            done = {
                r["name"]: json.loads(r["result"])
                for r in db.execute(
                    "SELECT name,result FROM steps WHERE job=? AND state='done'",
                    (job["id"],),
                )
            }
        for operation in manifest["operations"]:
            name = "commit:" + str(operation["seq"]) + ":" + operation["operation"]
            if (
                name in done
                and operation.get("authority") == "owner-authorized-takeout-retention"
            ):
                completed.append(
                    {
                        "seq": operation["seq"],
                        "operation": operation["operation"],
                        "outcome": done[name].get("outcome"),
                    }
                )
                if operation["operation"] == "storage-quota":
                    capacity = done[name]
                continue
            context.checkpoint(
                stage=name, completed=len(completed), total=len(manifest["operations"])
            )
            retention_scope = None
            if operation.get("authority") == "owner-authorized-takeout-retention":
                from .google_takeout import verify_copy

                require(
                    manifest["capabilities"]["productionRetention"] is True
                    and operation["operation"] == "trash",
                    "Production Trash authority required",
                )
                context.step(
                    "local:" + name,
                    lambda op=operation: verify_copy(
                        self.library, op["localEvidence"], op["expect"]["mediaKey"]
                    ),
                    replay_safe=True,
                )
                retention_scope = {
                    "purpose": operation["authority"],
                    "manifestId": manifest["id"],
                    "manifestSha256": manifest["sha256"],
                    "photoKey": operation["expect"]["mediaKey"],
                    "dedupKey": operation["expect"]["dedupKey"],
                    "localSha256": operation["localEvidence"]["sha256"],
                }
            if operation["operation"] == "upload-image":
                size = operation["input"]["size"]
                reserve = manifest["options"]["reserveBytes"]
                if (
                    capacity is None
                    or capacity["total"] - capacity["used"] < size + reserve
                ):
                    deferred.append(
                        {"seq": operation["seq"], "reason": "INSUFFICIENT_QUOTA"}
                    )
                    continue
                if self.publisher is None:
                    deferred.append(
                        {
                            "seq": operation["seq"],
                            "reason": "UPLOAD_ADAPTER_UNAVAILABLE",
                        }
                    )
                    continue
                key = job["id"] + ":" + str(operation["seq"])
                result = context.step(
                    name,
                    lambda op=operation: self.publisher.publish(
                        key, manifest["account"], op["input"]
                    ),
                    recover=lambda: self.publisher.receipt(key),
                    replay_safe=False,
                )
                require(
                    isinstance(result, dict) and result.get("verified") is True,
                    "Upload was not verified",
                )
                capacity = {**capacity, "used": capacity["used"] + size}
            else:
                result = self._remote(
                    job,
                    context,
                    name,
                    operation["operation"],
                    operation["input"],
                    operation["operation"] == "trash",
                    retention_scope=retention_scope,
                )
                if operation["operation"] == "photo-details" and operation.get(
                    "expect"
                ):
                    photo = result["photo"]
                    expect = operation["expect"]
                    require(
                        all(photo[k] == v for k, v in expect.items())
                        and photo.get("favorite") is False
                        and photo.get("albums") == []
                        and photo.get("companion") is not True,
                        "Cleanup preconditions changed; prepare another manifest",
                    )
                if operation["operation"] == "storage-quota":
                    capacity = result
            completed.append(
                {
                    "seq": operation["seq"],
                    "operation": operation["operation"],
                    "outcome": result.get("outcome"),
                }
            )
        result = {
            "manifestId": manifest["id"],
            "completed": completed,
            "deferred": deferred,
            "quota": capacity,
            "held": sum(
                1
                for item in manifest["items"]
                if item.get("blocked") or item["action"] == "unsupported"
            ),
        }
        if deferred:
            raise PartialResult(result)
        return result


def install_reconciliation_routes(app, library, remote, session, authorize, wake):
    from fastapi import Request
    from fastapi.responses import JSONResponse, FileResponse

    def wake_worker():
        loop = getattr(app.state, "event_loop", None)
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(wake)

    service = Reconciliation(library, remote, authorize=authorize, wake=wake_worker)
    app.state.google_reconciliation = service
    base = "/api/v1/google/reconciliation"

    def owned(req, ident):
        owner = session(req, 3)["username"]
        job = service.jobs.get(ident)
        if job["owner"] != owner:
            raise KeyError(ident)
        return job

    @app.get(base)
    def listing(req: Request):
        return service.jobs.listing(session(req, 3)["username"])

    @app.post(base + "/prepare")
    def prepare(req: Request, body: dict):
        job = service.prepare(session(req, 3, True)["username"], body)
        return JSONResponse(job, status_code=202, headers={"Cache-Control": "no-store"})

    @app.get(base + "/jobs/{ident}")
    def status(ident: str, req: Request):
        return JSONResponse(owned(req, ident), headers={"Cache-Control": "no-store"})

    @app.post(base + "/jobs/{ident}/resume")
    def resume(ident: str, req: Request):
        owner = session(req, 3, True)["username"]
        return JSONResponse(
            service.resume(owner, ident),
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )

    @app.post(base + "/manifests/{ident}/takeout-sweep")
    def takeout_sweep(ident: str, req: Request):
        return JSONResponse(
            service.prepare_takeout(session(req, 3, True)["username"], ident),
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )

    @app.get(base + "/manifests/{ident}")
    def manifest(ident: str, req: Request):
        value = service.manifest(session(req, 3)["username"], ident)
        return JSONResponse(
            value,
            headers={"ETag": '"' + value["sha256"] + '"', "Cache-Control": "no-store"},
        )

    @app.get(base + "/manifests/{ident}/download")
    def download(ident: str, req: Request):
        value = service.manifest(session(req, 3)["username"], ident)
        return FileResponse(
            service.path(ident),
            media_type="application/json",
            filename="photoflow-reconciliation-" + ident + ".json",
            headers={"Cache-Control": "no-store", "ETag": '"' + value["sha256"] + '"'},
        )

    @app.post(base + "/manifests/{ident}/commit")
    def commit(ident: str, req: Request, body: dict):
        owner = session(req, 3, True)["username"]
        require(set(body) == {"sha256"}, "Supply only the reviewed manifest hash")
        return JSONResponse(
            service.commit(owner, ident, body["sha256"]),
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )

    return service
