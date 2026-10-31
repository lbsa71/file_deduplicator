"""Owner-authorized Takeout evidence, independent of disposable pilot authority."""

import hashlib
import json
from collections import Counter
from photoflow.model import SIDECAR
from .google_contracts import photo_key
from .google_downloads import file_sha
from .core import Conflict, atomic

PURPOSE = "owner-authorized-takeout-retention"


def verify_copy(library, snapshot, media_key):
    """Hash current bytes and the preserved source document; never compare remote bytes."""
    fs = library.fs
    relative = snapshot["path"]
    before = fs.stat(relative).to_dict()
    if before != snapshot["fingerprint"]:
        raise Conflict("Local original changed")
    sidecar = fs.native_path(relative + SIDECAR)
    raw = sidecar.read_bytes()
    if hashlib.sha256(raw).hexdigest() != snapshot["revision"]:
        raise Conflict("Local sidecar changed")
    record = json.loads(raw)
    if (
        record["record_id"] != snapshot["recordId"]
        or record.get("lifecycle") == "trashed"
        or record["file"]["relative_path"] != relative
        or record["file"].get("sha256") != snapshot["sha256"]
        or record.get("resolved", {}).get("favorite") is True
        or record.get("overrides", {}).get("albums")
    ):
        raise Conflict("Local identity or protection changed")
    matched = False
    for source in record.get("sources", []):
        for evidence in source.get("documents", []):
            document = evidence.get("document", {})
            try:
                if (
                    photo_key(document.get("url")) != media_key
                    or not isinstance(document.get("title"), str)
                    or not document["title"]
                    or source.get("original_filename") != document["title"]
                ):
                    continue
                preserved = fs.native_path(evidence["relative_path"]).read_bytes()
                if (
                    hashlib.sha256(preserved).hexdigest() == evidence.get("sha256")
                    and json.loads(preserved) == document
                ):
                    matched = True
            except (OSError, ValueError, KeyError, TypeError):
                continue
    if not matched:
        raise Conflict("Exact preserved Takeout provenance unavailable")
    observed = file_sha(fs.native_path(relative))
    if (
        observed != snapshot["sha256"]
        or fs.stat(relative).to_dict() != before
        or hashlib.sha256(sidecar.read_bytes()).hexdigest() != snapshot["revision"]
    ):
        raise Conflict("Local original changed during verification")
    return {
        "recordId": snapshot["recordId"],
        "sha256": observed,
        "preservedTakeoutDocumentVerified": True,
        "remoteBytesCompared": False,
    }


def prepare_sweep(service, job, context):
    from .google_reconciliation import manifest_hash, require, photo_url

    owner = job["owner"]
    existing = service.path(job["id"])
    if existing.exists():
        value = service.manifest(owner, job["id"])
        return {
            "manifestId": value["id"],
            "sha256": value["sha256"],
            "counts": value["counts"],
        }
    source = service.manifest(owner, job["params"]["sourceManifestId"])
    require(
        source["sha256"] == job["params"]["sourceSha256"], "Source inventory changed"
    )
    require(
        source["inventoryScope"] == "account" and source["inventoryComplete"] is True,
        "Complete account inventory required",
    )
    require(
        source["account"] == service.account(owner)
        and source["libraryId"] == service.library.id,
        "Account/library changed",
    )
    require(service.now() < source["expiresAt"], "Source inventory expired")
    local = {i["recordId"]: i for i in source["local"]}
    items, operations, chosen = [], [], {}
    candidates = [i for i in source["items"] if i.get("mediaKey")]
    for index, item in enumerate(candidates):
        context.checkpoint(
            stage="verify-takeout-originals", completed=index, total=len(candidates)
        )
        value = {**item, "action": "keep", "blocked": False}
        evidence = None
        copies = [local[r] for r in item.get("localRecordIds", [])]
        hashes = {r.get("sha256") for r in copies}
        if (
            item["action"] == "review-trash"
            and item.get("companion") is not True
            and item.get("remoteFavorite") is False
            and item.get("albumIds") == []
            and len(hashes) == 1
            and None not in hashes
            and not any(r["favorite"] or r["curated"] for r in copies)
        ):
            for snapshot in copies:
                try:
                    evidence = context.step(
                        "takeout:" + item["mediaKey"] + ":" + snapshot["recordId"],
                        lambda s=snapshot: verify_copy(
                            service.library, s, item["mediaKey"]
                        ),
                        replay_safe=True,
                    )
                    chosen[snapshot["recordId"]] = snapshot
                    break
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        if evidence:
            value.update(
                action="takeout-trash",
                reason="Owner-authorized Takeout original with current local bytes and preserved exact URL/title document",
            )
            operations.append(
                {
                    "seq": len(operations) + 1,
                    "phase": "cleanup",
                    "operation": "trash",
                    "input": {"photoUrl": photo_url(item["mediaKey"])},
                    "authority": PURPOSE,
                    "expect": {
                        "mediaKey": item["mediaKey"],
                        "dedupKey": item["dedupKey"],
                    },
                    "localEvidence": chosen[evidence["recordId"]],
                }
            )
        else:
            value["reason"] = (
                "Retained: protected, known motion companion, or missing/ambiguous current Takeout original"
            )
        items.append(value)
    manifest = {
        **source,
        "id": job["id"],
        "sourceManifestId": source["id"],
        "sourceSha256": source["sha256"],
        "createdAt": service.now(),
        "local": list(chosen.values()),
        "items": items,
        "operations": operations,
        "retentionPolicy": {
            **source["retentionPolicy"],
            "version": "owner-takeout-exact-target-trash-v2",
            "localEvidence": "current-sha256-and-preserved-takeout-url-title-document",
            "remoteByteEqualityRequired": False,
            "knownMotionCompanions": "keep",
            "unknownCompanionMarker": "owner-accepts-takeout-original",
        },
        "counts": {
            **source["counts"],
            "actions": dict(Counter(i["action"] for i in items)),
        },
        "capabilities": {
            "productionRetention": True,
            "imagePublication": False,
            "permanentDelete": False,
        },
        "limitations": [
            "Takeout provenance and current local SHA-256 establish the owner's accepted local original; current remote byte equality is not asserted.",
            "Fresh identity, star and album checks precede every Trash; changed protections retain the target. Known motion photos remain kept.",
        ],
    }
    manifest["sha256"] = manifest_hash(manifest)
    atomic(service.path(job["id"]), manifest)
    return {
        "manifestId": manifest["id"],
        "sha256": manifest["sha256"],
        "counts": manifest["counts"],
    }
