"""Account-bound original associations, projected from portable sidecars.

A verified local association proves local bytes at this check, not current Google
byte equality, inventory completeness, independent backup, or retention safety.
"""

import re
from .google_contracts import check, field
from .google_downloads import file_sha


def account_value(account):
    check(isinstance(account, str) and 0 < len(account) <= 4096
          and not re.search(r"[\s\x00-\x1f\x7f]", account))


def associations(record):
    entries = record.get("google_originals", [])
    check(isinstance(entries, list))
    result = set()
    for entry in entries:
        check(isinstance(entry, dict))
        account_value(entry.get("account"))
        field("id", entry.get("mediaKey"))
        field("id", entry.get("dedupKey"))
        check(isinstance(entry.get("sha256"), str)
              and re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]))
        result.add((entry["account"], entry["mediaKey"], entry["dedupKey"], entry["sha256"]))
    return result


def create_identity_index(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS google_identities(
            id TEXT, account TEXT, media_key TEXT, dedup_key TEXT, sha256 TEXT,
            PRIMARY KEY(id,account,media_key,dedup_key,sha256));
        CREATE INDEX IF NOT EXISTS google_identity_lookup ON google_identities(account,media_key,id);
    """)


def index_google_identities(db, record):
    entries = associations(record)  # Validate all entries before replacing anything.
    db.execute("DELETE FROM google_identities WHERE id=?", (record["record_id"],))
    db.executemany("INSERT INTO google_identities VALUES(?,?,?,?,?)",
                   [(record["record_id"], *entry) for entry in sorted(entries)])


class LocalGoogleMatches:
    def __init__(self, library, byte_budget=256 * 1024**2):
        self.library, self.byte_budget = library, byte_budget

    def check(self, account, targets):
        account_value(account)
        check(isinstance(targets, list) and 0 < len(targets) <= 100)
        seen = set()
        for target in targets:
            check(isinstance(target, dict) and {"namespace", "mediaKey"} <= set(target)
                  and set(target) <= {"namespace", "mediaKey", "dedupKey", "size"}
                  and target["namespace"] == "library-media")
            field("id", target["mediaKey"])
            if "dedupKey" in target:
                field("id", target["dedupKey"])
            if "size" in target:
                check(type(target["size"]) is int and target["size"] > 0)
            check(target["mediaKey"] not in seen)
            seen.add(target["mediaKey"])
        budget = [self.byte_budget]
        with self.library.mutex:
            if not self.library.available():
                raise OSError("Storage unavailable")
            items = [self.match(account, target, budget) for target in targets]
            if not self.library.available():
                raise OSError("Storage unavailable")
        return {"account": account, "items": items, "absenceProven": False,
                "remoteBytesEqual": None, "retentionReady": False}

    def match(self, account, target, budget):
        with self.library.db() as db:
            rows = db.execute(
                "SELECT * FROM google_identities WHERE account=? AND media_key=? ORDER BY id LIMIT 101",
                (account, target["mediaKey"])).fetchall()
        result = {**target, "state": "unmapped", "recordIds": [], "candidates": []}
        if not rows:
            return result
        identities = {(row["dedup_key"], row["sha256"]) for row in rows}
        if len(rows) > 100 or len(identities) != 1:
            result["state"] = "ambiguous"
            return result
        dedup, sha = next(iter(identities))
        if "dedupKey" in target and target["dedupKey"] != dedup:
            result["state"] = "remote-details-changed"
            return result
        for row in rows:
            state = self.verify(row, target, budget)
            result["candidates"].append({"recordId": row["id"], "state": state})
            if state == "verified-local":
                result["recordIds"].append(row["id"])
        if result["recordIds"]:
            result.update(state="verified-local", sha256=sha)
        else:
            states = {candidate["state"] for candidate in result["candidates"]}
            result["state"] = next(iter(states)) if len(states) == 1 else "needs-investigation"
        return result

    def verify(self, row, target, budget):
        from .core import Conflict, digest
        try:
            cached = self.library.get(row["id"])
            record, sidecar = self.library.checked(row["id"], cached["revision"])
            source = (row["account"], row["media_key"], row["dedup_key"], row["sha256"])
            if source not in associations(record):
                return "stale-local-metadata"
            if record.get("lifecycle") == "trashed":
                return "local-trash"
            path = self.library.path(record["file"]["relative_path"])
            before = path.stat()
            if "size" in target and before.st_size != target["size"]:
                return "remote-details-changed"
            if before.st_size > budget[0]:
                return "verification-deferred"
            budget[0] -= before.st_size
            sha = file_sha(path)
            if digest(sidecar.read_bytes()) != cached["revision"]:
                return "stale-local-metadata"
            after = path.stat()
            if any(getattr(before, key) != getattr(after, key) for key in
                   ("st_size", "st_mtime_ns", "st_ctime_ns", "st_ino", "st_dev")):
                return "local-content-changed"
            if sha != row["sha256"] or sha != record["file"].get("sha256"):
                return "local-content-changed"
            return "verified-local"
        except Conflict:
            return "stale-local-metadata"
        except (OSError, KeyError):
            return "local-unavailable"
        except ValueError:
            return "local-content-changed"
