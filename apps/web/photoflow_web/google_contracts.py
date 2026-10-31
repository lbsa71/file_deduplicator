"""Runtime validation for the mirrored, versioned Google job catalogue."""

import json, re
from pathlib import Path
from urllib.parse import urlsplit


def check(ok):
    if not ok:
        raise ValueError("Google job contract could not be verified")


def photo_key(value):
    check(isinstance(value, str) and len(value) <= 4096)
    u = urlsplit(value)
    match = re.fullmatch(r"/(?:u/\d+/)?photo/([A-Za-z0-9_-]+)", u.path)
    check(
        u.scheme == "https"
        and u.netloc == "photos.google.com"
        and not u.query
        and not u.fragment
        and match
    )
    return match[1]


def field(kind, value):
    optional = kind.endswith("?")
    kind = kind.rstrip("?")
    if optional and value is None:
        return
    if kind == "photoUrl":
        photo_key(value)
        return
    if kind == "id":
        check(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value))
    elif kind == "cursor":
        check(
            isinstance(value, str)
            and 0 < len(value) <= 4096
            and not re.search(r"[\s\x00-\x1f]", value)
        )
    elif kind == "bool":
        check(type(value) is bool)
    elif kind == "text":
        check(
            isinstance(value, str)
            and len(value) <= 2048
            and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value)
        )
    elif kind == "title":
        check(
            isinstance(value, str)
            and value.startswith("PhotoFlow test ")
            and len(value) <= 200
        )
    elif kind in ("epoch", "timezone", "scale"):
        limits = {
            "epoch": (-2208988800, 4102444800),
            "timezone": (-50400, 50400),
            "scale": (0, 25),
        }
        low, high = limits[kind]
        check(type(value) is int and low <= value <= high)
    elif kind == "coordinates":
        check(
            isinstance(value, list)
            and len(value) == 2
            and all(type(v) is int for v in value)
            and abs(value[0]) <= 900000000
            and abs(value[1]) <= 1800000000
        )
    elif kind == "hashes":
        check(
            isinstance(value, list)
            and 0 < len(value) <= 20
            and all(
                isinstance(v, str)
                and 0 < len(v) <= 256
                and not re.search(r"[\s\x00-\x1f]", v)
                for v in value
            )
        )
        check(len(set(value)) == len(value))
    else:
        check(False)


def validate_input(spec, value):
    check(
        isinstance(value, dict)
        and set(value) <= set(spec["fields"])
        and len(json.dumps(value, ensure_ascii=False).encode()) <= 8192
    )
    for name, kind in spec["fields"].items():
        field(kind, value.get(name))


def integer(value, low=0, high=1000000):
    check(type(value) is int and low <= value <= high)


def album(value):
    check(
        isinstance(value, dict)
        and set(value) == {"namespace", "albumId", "title", "itemCount", "shared"}
        and value["namespace"] == "album"
    )
    field("id", value["albumId"])
    check(isinstance(value["title"], str) and len(value["title"]) <= 8192)
    integer(value["itemCount"])
    check(value["shared"] is None or type(value["shared"]) is bool)


def media(value, namespace=None):
    check(
        isinstance(value, dict)
        and set(value)
        == {
            "namespace",
            "mediaKey",
            "dedupKey",
            "favorite",
            "trashTimestamp",
            "companion",
        }
    )
    check(
        value["namespace"] in ("library-media", "album-item")
        and (namespace is None or value["namespace"] == namespace)
    )
    field("id", value["mediaKey"])
    field("id", value["dedupKey"])
    for name in ("favorite", "companion"):
        check(value[name] is None or type(value[name]) is bool)
    if value["trashTimestamp"] is not None:
        integer(value["trashTimestamp"], 0, 9007199254740991)


def validate_result(operation, spec, result):
    check(
        isinstance(result, dict)
        and len(json.dumps(result, ensure_ascii=False).encode()) <= 240 * 1024
    )
    kind = spec["result"]
    if kind == "counts":
        check(
            set(result)
            == {"photos", "favorites", "albums", "complete", "retentionReady"}
            and result["complete"] is True
            and result["retentionReady"] is False
        )
        for name in ["photos", "favorites", "albums"]:
            integer(result[name])
        check(result["favorites"] <= result["photos"])
        return
    check(result.get("retentionReady") is False)
    if kind == "page":
        check(
            set(result) == {"items", "next", "complete", "retentionReady"}
            and isinstance(result["items"], list)
            and len(result["items"]) <= 500
            and type(result["complete"]) is bool
            and result["complete"] == (result["next"] is None)
        )
        field("cursor?", result["next"])
        for item in result["items"]:
            if operation == "albums-page":
                album(item)
            else:
                media(
                    item,
                    "album-item" if operation == "album-members" else "library-media",
                )
    elif kind == "detail":
        check(set(result) == {"photo", "retentionReady"})
        photo = result["photo"]
        extra = {
            "filename",
            "albums",
            "size",
            "archived",
            "description",
            "timestampMs",
            "timezoneMs",
            "locationE7",
            "manualLocationE7",
        }
        check(
            isinstance(photo, dict)
            and set(photo)
            <= extra
            | {
                "namespace",
                "mediaKey",
                "dedupKey",
                "favorite",
                "trashTimestamp",
                "companion",
            }
        )
        media({k: v for k, v in photo.items() if k not in extra}, "library-media")
        check(isinstance(photo.get("filename"), str) and len(photo["filename"]) <= 8192)
        integer(photo.get("size"), 0, 9007199254740991)
        if photo.get("albums") is not None:
            check(isinstance(photo["albums"], list) and len(photo["albums"]) <= 500)
            for a in photo["albums"]:
                album(a)
        for key in ["timestampMs", "timezoneMs"]:
            if photo.get(key) is not None:
                integer(photo[key], -9007199254740991, 9007199254740991)
        for key in ["locationE7", "manualLocationE7"]:
            if photo.get(key) is not None:
                field("coordinates", photo[key])
        check(photo.get("archived") is None or type(photo["archived"]) is bool)
        check(
            photo.get("description") is None
            or isinstance(photo["description"], str)
            and len(photo["description"]) <= 65536
        )
    elif kind == "quota":
        check(set(result) == {"used", "total", "photosUsed", "retentionReady"})
        for key in ["used", "total", "photosUsed"]:
            integer(result[key], 0, 9007199254740991)
        check(result["photosUsed"] <= result["used"] <= result["total"])
    elif kind == "matches":
        check(
            set(result) == {"items", "absenceProven", "retentionReady"}
            and result["absenceProven"] is False
            and isinstance(result["items"], list)
            and len(result["items"]) <= 100
        )
        for item in result["items"]:
            check(isinstance(item, dict))
            field("cursor", item.get("hash"))
            media({k: v for k, v in item.items() if k != "hash"}, "library-media")
    elif kind == "download":
        check(
            set(result) == {"mediaKey", "available", "retentionReady"}
            and result["available"] is True
        )
        field("id", result["mediaKey"])
    elif kind == "original":
        check(set(result) == {"mediaKey", "recordId", "sha256", "bytes", "outcome", "retentionReady"})
        field("id", result["mediaKey"])
        check(isinstance(result["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", result["sha256"]))
        check(isinstance(result["recordId"], str) and re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", result["recordId"]))
        integer(result["bytes"], 1, 16 * 1024**2)
        check(result["outcome"] in ("imported", "already-present"))
    elif kind == "mutation":
        check(
            set(result) <= {"verified", "outcome", "albumId", "retentionReady"}
            and result.get("verified") is True
            and result.get("outcome") in ("verified", "unchanged", "reconciled")
        )
        if operation == "album-create":
            field("id", result.get("albumId"))
        elif result.get("albumId") is not None:
            field("id", result["albumId"])
    elif kind == "reconciliation":
        check(
            set(result) <= {"verified", "originalJobId", "retentionReady", "albumId"}
            and result["verified"] is True
        )
        field("id", result["originalJobId"])
        if result.get("albumId") is not None:
            field("id", result["albumId"])
    else:
        check(False)


CATALOG = json.loads(Path(__file__).with_name("google_jobs.json").read_text())
PHASES = [
    "checking",
    "library",
    "favorites",
    "albums",
    "reading",
    "preflight",
    "sending",
    "verifying",
    "complete",
    "failed",
]
JOB_SPECS = {
    name: {
        **spec,
        "phases": PHASES,
        "validate_result": lambda value, n=name, s=spec: validate_result(n, s, value),
        "validate_input": lambda value, s=spec: validate_input(s, value),
    }
    for name, spec in CATALOG.items()
}


def summary(result):
    if result is None:
        return None
    if "photos" in result:
        return result
    return {
        k: v
        for k, v in {
            "itemCount": (
                len(result["items"]) if isinstance(result.get("items"), list) else None
            ),
            "complete": result.get("complete"),
            "verified": result.get("verified"),
            "outcome": result.get("outcome"),
            "retentionReady": False,
            "available": True,
        }.items()
        if v is not None
    }
