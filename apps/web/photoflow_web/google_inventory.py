"""Portable, bounded full-account read inventories with explicit completeness.

Page traversal completeness is not an atomic provider snapshot or proof that an
unknown Google identifier is absent. Namespace boundaries are retained verbatim.
"""

import hashlib, json, re, secrets, time
from photoflow.model import encoded
from .core import Conflict, atomic, digest, load
from .google_contracts import JOB_SPECS, check
from .google_identity import account_value

COLLECTIONS = {"library": "library-page", "favorites": "favorites-page", "albums": "albums-page", "trash": "trash-page"}
TERMINAL = {"complete", "incomplete", "cancelled"}


class GoogleInventories:
    def __init__(self, library, workers, now=time.time, max_pages=10000, max_items=1000000):
        self.library, self.workers, self.now = library, workers, now
        self.max_pages, self.max_items = max_pages, max_items
        self.seen = {}  # Disposable traversal cache, rebuilt from checked page files.
        self.directory = library.path(".photoflow/google-inventories")
        self.directory.mkdir(mode=0o700, exist_ok=True)
        check(self.directory.stat().st_mode & 0o077 == 0)

    def path(self, ident):
        check(isinstance(ident, str) and re.fullmatch(r"[a-f0-9]{32}", ident))
        return self.library.path(f".photoflow/google-inventories/{ident}/manifest.json")

    def save(self, data):
        if not self.library.available():
            raise OSError("Storage unavailable")
        data["updatedAt"] = self.now()
        path = self.path(data["id"])
        path.parent.mkdir(mode=0o700, exist_ok=True)
        check(path.parent.stat().st_mode & 0o077 == 0)
        atomic(path, data)
        path.chmod(0o600)

    def read(self, owner, account, ident):
        if not self.library.available():
            raise OSError("Storage unavailable")
        data = load(self.path(ident))
        if not data or data.get("owner") != owner or data.get("account") != account or data.get("libraryId") != self.library.id:
            raise KeyError("Inventory not found")
        check(data.get("schemaVersion") == 1 and data.get("id") == ident
              and data.get("retentionReady") is False and data.get("state") in TERMINAL | {"running"}
              and data.get("complete") == (data["state"] == "complete"))
        return data

    def public(self, data):
        result = {key: data[key] for key in ("id", "account", "libraryId", "state", "createdAt", "updatedAt", "complete", "retentionReady", "error", "counts")}
        result["pages"] = sum(len(value["pages"]) for value in data["collections"])
        result["collections"] = [{key: collection[key] for key in ("name", "complete", "count")} for collection in data["collections"]]
        result["readOnly"] = True
        result["absenceProven"] = False
        return result

    def get(self, owner, account, ident):
        with self.library.mutex:
            return self.public(self.read(owner, account, ident))

    def list(self, owner, account):
        result = []
        with self.library.mutex:
            for path in self.directory.glob("*/manifest.json"):
                data = load(self.path(path.parent.name))
                if data.get("owner") == owner and data.get("account") == account:
                    result.append(self.public(self.read(owner, account, data["id"])))
        return {"items": sorted(result, key=lambda item: (item["createdAt"], item["id"]), reverse=True)[:20]}

    @staticmethod
    def collection(name, operation, album_id=None):
        return {"name": name, "operation": operation, "albumId": album_id, "cursor": None,
                "complete": False, "count": 0, "pages": [], "pending": None}

    def create(self, owner, account):
        account_value(account)
        check(self.workers.status(owner)["account"] == account)
        with self.library.writer():
            if any(item["state"] == "running" for item in self.list(owner, account)["items"]):
                raise Conflict("A full inventory is already running for this account")
            check(sum(1 for _ in self.directory.glob("*/manifest.json")) < 100)
            data = {"schemaVersion": 1, "id": secrets.token_hex(16), "owner": owner, "account": account,
                    "libraryId": self.library.id, "createdAt": self.now(), "state": "running", "error": None,
                    "complete": False, "retentionReady": False, "albumsExpanded": False,
                    "counts": {"library": 0, "favorites": 0, "albums": 0, "trash": 0, "albumMembers": 0},
                    "collections": [self.collection(name, operation) for name, operation in COLLECTIONS.items()]}
            self.save(data)
            return self.public(data)

    def page_path(self, data, collection, index):
        number = data["collections"].index(collection)
        return self.library.path(f".photoflow/google-inventories/{data['id']}/page-{number:06d}-{index:06d}.json")

    def page(self, data, collection, reference):
        path = self.page_path(data, collection, reference["index"])
        raw = path.read_bytes()
        check(digest(raw) == reference["sha256"])
        value = json.loads(raw)
        self.validate_page(data, collection, value)
        return value

    def validate_page(self, data, collection, value):
        check(value.get("inventoryId") == data["id"] and value.get("account") == data["account"]
              and value.get("libraryId") == self.library.id and value.get("collection") == collection["name"]
              and value.get("operation") == collection["operation"])
        JOB_SPECS[collection["operation"]]["validate_result"](value["result"])

    def seen_items(self, data, collection):
        key = (data["id"], collection["name"])
        stamp = (len(collection["pages"]), collection["pages"][-1]["sha256"] if collection["pages"] else None)
        cached = self.seen.get(key)
        if cached is not None and cached["stamp"] == stamp:
            return cached
        cached = {"stamp": stamp, "ids": set(), "cursors": set()}
        item_key = "albumId" if collection["operation"] == "albums-page" else "mediaKey"
        for reference in collection["pages"]:
            value = self.page(data, collection, reference)
            cached["cursors"].add(value["input"]["cursor"])
            cached["ids"].update(item[item_key] for item in value["result"]["items"])
        self.seen[key] = cached
        return cached

    def verify_complete(self, data):
        by_name = {}
        for collection in data["collections"]:
            check(collection["complete"] and collection["pending"] is None)
            cursor, ids = None, {}
            for index, reference in enumerate(collection["pages"]):
                check(reference["index"] == index and (index == 0 or cursor is not None))
                page = self.page(data, collection, reference)
                check(page["input"]["cursor"] == cursor)
                if collection["albumId"] is not None:
                    check(page["input"]["albumId"] == collection["albumId"])
                key = "albumId" if collection["operation"] == "albums-page" else "mediaKey"
                for item in page["result"]["items"]:
                    check(item[key] not in ids)
                    ids[item[key]] = item
                cursor = page["result"]["next"]
            check(collection["pages"] and cursor is None and len(ids) == collection["count"])
            by_name[collection["name"]] = ids
        for key, favorite in by_name["favorites"].items():
            if key not in by_name["library"] or favorite["dedupKey"] != by_name["library"][key]["dedupKey"]:
                return "INVENTORY_CHANGED"
        for album_id, album in by_name["albums"].items():
            if len(by_name.get("album:" + album_id, {})) != album["itemCount"]:
                return "ALBUM_COUNT_CHANGED"
        return None

    def items(self, owner, account, ident, name):
        # Snapshot metadata under the lock; immutable page files remain authoritative.
        with self.library.mutex:
            data = self.read(owner, account, ident)
        collection = next((value for value in data["collections"] if value["name"] == name), None)
        check(collection is not None)
        for reference in collection["pages"]:
            yield from self.page(data, collection, reference)["result"]["items"]

    def fail(self, data, code):
        data.update(state="incomplete", complete=False, error=code)
        self.save(data)
        return self.public(data)

    def advance(self, owner, account, ident):
        with self.library.writer():
            return self._advance(owner, account, ident)

    def _advance(self, owner, account, ident):
        data = self.read(owner, account, ident)
        if data["state"] in TERMINAL:
            return self.public(data)
        if self.workers.status(owner)["account"] != account:
            return self.fail(data, "ACCOUNT_CHANGED")
        collection = next((value for value in data["collections"] if not value["complete"]), None)
        if collection is None and not data["albumsExpanded"]:
            albums = next(value for value in data["collections"] if value["name"] == "albums")
            for reference in albums["pages"]:
                for album in self.page(data, albums, reference)["result"]["items"]:
                    data["collections"].append(self.collection("album:" + album["albumId"], "album-members", album["albumId"]))
            data["albumsExpanded"] = True
            collection = next((value for value in data["collections"] if not value["complete"]), None)
        if collection is None:
            error = self.verify_complete(data)
            if error:
                return self.fail(data, error)
            data.update(state="complete", complete=True, finishedAt=self.now())
            self.save(data)
            self.seen = {key: value for key, value in self.seen.items() if key[0] != ident}
            return self.public(data)
        if sum(len(value["pages"]) for value in data["collections"]) >= self.max_pages:
            return self.fail(data, "PAGE_LIMIT")
        pending = collection["pending"]
        if pending is None:
            pending = {"batch": secrets.token_hex(16), "jobId": None, "cursor": collection["cursor"]}
            collection["pending"] = pending
            self.save(data)  # Persist exact cursor before the remote read is admitted.
        request = {"cursor": pending["cursor"]}
        if collection["albumId"] is not None:
            request["albumId"] = collection["albumId"]
        if pending["jobId"] is None:
            jobs = self.workers.bound_read_jobs(owner, account, pending["batch"], [{"operation": collection["operation"], "input": request}])
            pending["jobId"] = jobs[0]["id"]
            self.save(data)
        index = len(collection["pages"])
        path = self.page_path(data, collection, index)
        if path.exists():
            value = load(path)  # Recover publication before a manifest checkpoint.
            self.validate_page(data, collection, value)
            check(value["jobId"] == pending["jobId"] and value["input"] == request)
        else:
            job = self.workers.bound_read_result(owner, account, pending["batch"], pending["jobId"], collection["operation"], request)
            if job["state"] in ("queued", "running"):
                return self.public(data)
            if job["state"] != "succeeded":
                return self.fail(data, "PAGE_" + (job.get("error") or job["state"]).upper())
            value = {"schemaVersion": 1, "inventoryId": ident, "libraryId": self.library.id, "account": account,
                     "collection": collection["name"], "operation": collection["operation"], "jobId": pending["jobId"],
                     "input": request, "observedAt": job["started"], "recordedAt": self.now(), "result": job["result"]}
        result = value["result"]
        seen = self.seen_items(data, collection)
        if result["next"] is not None and (result["next"] in seen["cursors"] or result["next"] == pending["cursor"]):
            return self.fail(data, "CURSOR_LOOP")
        key = "albumId" if collection["operation"] == "albums-page" else "mediaKey"
        incoming = [item[key] for item in result["items"]]
        if len(set(incoming)) != len(incoming) or seen["ids"].intersection(incoming):
            return self.fail(data, "DUPLICATE_ID")
        if sum(value["count"] for value in data["collections"]) + len(incoming) > self.max_items:
            return self.fail(data, "ITEM_LIMIT")
        if not path.exists():
            atomic(path, value)
            path.chmod(0o600)
        collection["pages"].append({"index": index, "sha256": digest(path.read_bytes())})
        collection.update(count=collection["count"] + len(incoming), cursor=result["next"], complete=result["complete"], pending=None)
        count_key = "albumMembers" if collection["albumId"] is not None else collection["name"]
        data["counts"][count_key] += len(incoming)
        self.save(data)
        seen["ids"].update(incoming)
        seen["cursors"].add(pending["cursor"])
        seen["stamp"] = (len(collection["pages"]), collection["pages"][-1]["sha256"])
        if not collection["complete"] and sum(len(value["pages"]) for value in data["collections"]) >= self.max_pages:
            return self.fail(data, "PAGE_LIMIT")
        # Admit at most one successor page; no work is widened after any error.
        return self._advance(owner, account, ident)

    def cancel(self, owner, account, ident):
        with self.library.writer():
            data = self.read(owner, account, ident)
            if data["state"] not in TERMINAL:
                data.update(state="cancelled", complete=False)
                self.save(data)
            return self.public(data)
