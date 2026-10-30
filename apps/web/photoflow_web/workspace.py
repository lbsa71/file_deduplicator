"""Private saved queries and explicit, revision-bound batch work.

Saved queries are library authority. Selections and plans are short-lived intent
files: they freeze identities/revisions, never rerun a query during execution.
An interrupted running plan cannot be replayed; create a fresh reviewed plan.
"""

import copy
import re
import time
import uuid
from datetime import datetime
from pathlib import PurePosixPath

from photoflow.metadata import resolve
from photoflow.model import Record, encoded
from .core import Conflict, atomic, digest, load

LABELS = {"people", "albums", "tags"}
FIELDS = LABELS | {
    "title",
    "description",
    "favorite",
    "capture_time",
    "display_rotation",
}
TTL = 1800
MAX_TARGETS = 50000


def normalize_scope(value):
    from .query import normalize_filters

    if not isinstance(value, dict) or set(value) - {
        "q",
        "folder",
        "duplicates",
        "favorite",
        "trash",
        "filters",
    }:
        raise ValueError("Invalid query scope")
    result = {
        "q": "",
        "folder": None,
        "duplicates": False,
        "favorite": False,
        "trash": False,
    }
    result.update(copy.deepcopy(value))
    if not isinstance(result["q"], str) or len(result["q"]) > 2048:
        raise ValueError("Invalid search text")
    for key in ("duplicates", "favorite", "trash"):
        if type(result[key]) is not bool:
            raise ValueError("Invalid query flag")
    folder = result["folder"]
    if folder is not None:
        if (
            not isinstance(folder, str)
            or not folder
            or len(folder) > 4096
            or "\\" in folder
            or "\0" in folder
            or PurePosixPath(folder).is_absolute()
            or ".." in PurePosixPath(folder).parts
            or ".photoflow" in PurePosixPath(folder).parts
        ):
            raise ValueError("Invalid folder query")
        result["folder"] = folder.rstrip("/")
    result["filters"] = normalize_filters(result.get("filters", {}))
    return result


def labels(value):
    if (
        not isinstance(value, list)
        or len(value) > 256
        or any(not isinstance(x, str) or not x.strip() or len(x) > 256 for x in value)
    ):
        raise ValueError("Labels must be nonempty strings")
    return list(dict.fromkeys(value))


def normalize_operation(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid batch operation")
    action = value.get("action")
    allowed = {
        "metadata": {"action", "set", "reset", "add", "remove"},
        "trash": {"action"},
        "restore": {"action"},
        "move": {"action", "folder_id"},
    }
    if (
        not isinstance(action, str)
        or action not in allowed
        or set(value) - allowed[action]
    ):
        raise ValueError("Invalid batch operation")
    result = copy.deepcopy(value)
    if action == "move":
        if not isinstance(value.get("folder_id"), str) or not value["folder_id"]:
            raise ValueError("Destination folder required")
    if action != "metadata":
        return result
    for key in ("set", "add", "remove"):
        result.setdefault(key, {})
        if not isinstance(result[key], dict):
            raise ValueError("Invalid metadata operation")
    result.setdefault("reset", [])
    if not isinstance(result["reset"], list) or any(
        not isinstance(x, str) for x in result["reset"]
    ):
        raise ValueError("Invalid reset fields")
    sets, resets, adds, removes = (result[k] for k in ("set", "reset", "add", "remove"))
    fields = set(sets) | set(resets) | set(adds) | set(removes)
    if (
        not fields
        or fields - FIELDS
        or (set(adds) | set(removes)) - LABELS
        or set(sets) & (set(resets) | set(adds) | set(removes))
        or set(resets) & (set(adds) | set(removes))
    ):
        raise ValueError("Conflicting or unsupported metadata operations")
    for key in ("add", "remove"):
        for field, values in result[key].items():
            result[key][field] = labels(values)
    for field in set(adds) & set(removes):
        if set(adds[field]) & set(removes[field]):
            raise ValueError("Cannot add and remove the same label")
    for field, data in sets.items():
        if field in LABELS:
            sets[field] = labels(data)
        elif field == "favorite" and type(data) is not bool:
            raise ValueError("Favorite must be boolean")
        elif field == "display_rotation" and (
            type(data) is not int or data not in (0, 90, 180, 270)
        ):
            raise ValueError("Invalid rotation")
        elif field in ("title", "description", "capture_time"):
            if data is not None and (not isinstance(data, str) or len(data) > 16384):
                raise ValueError("Invalid metadata text")
            if field == "capture_time" and data is not None:
                datetime.fromisoformat(data.replace("Z", "+00:00"))
    return result


class Workspace:
    def __init__(self, library, *, clock=time.time, new_id=lambda: str(uuid.uuid4())):
        self.library, self.clock, self.new_id = library, clock, new_id
        self.base = library.root / ".photoflow"

    def _owner_path(self, owner):
        if not isinstance(owner, str) or not owner or len(owner) > 256:
            raise ValueError("Invalid owner")
        return self.base / "views" / (digest(owner.encode()) + ".json")

    def _views(self, owner):
        result = load(
            self._owner_path(owner),
            {
                "schema_version": 1,
                "library_id": self.library.id,
                "owner": owner,
                "items": [],
            },
        )
        self._validate_owner(result, owner)
        return result

    def _validate_owner(self, data, owner):
        if (
            not data
            or data.get("library_id") != self.library.id
            or data.get("owner") != owner
        ):
            raise KeyError("Resource not found")

    def _version(self, data):
        return {**data, "revision": digest(encoded(data))}

    def list_views(self, owner):
        if not self.library.available():
            raise OSError("Storage unavailable")
        return {"items": [self._version(v) for v in self._views(owner)["items"]]}

    def _view_values(self, name, query):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise ValueError("View name must contain 1–120 characters")
        return {"name": name.strip(), "query": normalize_scope(query)}

    def create_view(self, owner, name, query):
        values = self._view_values(name, query)
        with self.library.writer():
            data = self._views(owner)
            if len(data["items"]) >= 200:
                raise ValueError("Saved view limit reached")
            view = {
                "id": self.new_id(),
                "created": self.clock(),
                "updated": self.clock(),
                **values,
            }
            data["items"].append(view)
            atomic(self._owner_path(owner), data)
        return self._version(view)

    def update_view(self, owner, ident, revision, name, query):
        values = self._view_values(name, query)
        with self.library.writer():
            data, view = self._checked_view(owner, ident, revision)
            view.update(values, updated=self.clock())
            atomic(self._owner_path(owner), data)
        return self._version(view)

    def _checked_view(self, owner, ident, revision):
        data = self._views(owner)
        view = next((v for v in data["items"] if v["id"] == ident), None)
        if view is None:
            raise KeyError(ident)
        if self._version(view)["revision"] != revision:
            raise Conflict("Saved view changed; refresh before saving")
        return data, view

    def delete_view(self, owner, ident, revision):
        with self.library.writer():
            data, view = self._checked_view(owner, ident, revision)
            data["items"].remove(view)
            atomic(self._owner_path(owner), data)
        return {"deleted": ident}

    def _path(self, kind, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9-]{36}", ident):
            raise KeyError("Resource not found")
        return self.base / kind / (ident + ".json")

    def _load(self, kind, owner, ident, *, expires=False):
        data = load(self._path(kind, ident))
        self._validate_owner(data, owner)
        if expires and data["expires"] <= self.clock():
            raise Conflict("Selection expired; select the photos again")
        return data

    def _targets(self, *, targets=None, query=None):
        if (targets is None) == (query is None):
            raise ValueError("Provide either targets or a query")
        if query is not None:
            targets = self.library.matching(**normalize_scope(query))
        if not isinstance(targets, list) or not targets or len(targets) > MAX_TARGETS:
            raise ValueError(f"Select between 1 and {MAX_TARGETS} photos")
        seen = set()
        result = []
        for target in targets:
            if (
                not isinstance(target, dict)
                or set(target) != {"id", "revision"}
                or not isinstance(target["id"], str)
                or not isinstance(target["revision"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", target["revision"])
            ):
                raise ValueError("Invalid photo selection")
            if target["id"] in seen:
                raise ValueError("Duplicate selected photo")
            seen.add(target["id"])
            result.append(dict(target))
        return result

    def create_selection(self, owner, *, targets=None, query=None):
        with self.library.writer():
            data = {
                "id": self.new_id(),
                "owner": owner,
                "library_id": self.library.id,
                "created": self.clock(),
                "expires": self.clock() + TTL,
                "targets": self._targets(targets=targets, query=query),
            }
            atomic(self._path("selections", data["id"]), data)
        return self._selection_summary(data)

    def _selection_summary(self, data):
        return {k: data[k] for k in ("id", "created", "expires")} | {
            "count": len(data["targets"])
        }

    def get_selection(self, owner, ident):
        return self._selection_summary(
            self._load("selections", owner, ident, expires=True)
        )

    def selection_targets(self, owner, ident):
        """Return a frozen selection to another authorized operation, e.g. export."""
        return copy.deepcopy(
            self._load("selections", owner, ident, expires=True)["targets"]
        )

    def _metadata(self, record, operation):
        sets = copy.deepcopy(operation["set"])
        for field in set(operation["add"]) | set(operation["remove"]):
            values = record.get("resolved", {}).get(field, [])
            removing = set(operation["remove"].get(field, []))
            sets[field] = labels(
                [
                    value
                    for value in dict.fromkeys(values + operation["add"].get(field, []))
                    if value not in removing
                ]
            )
        after = copy.deepcopy(record)
        after.pop("revision", None)
        after["overrides"].update(sets)
        for field in operation["reset"]:
            after["overrides"].pop(field, None)
        after["resolved"] = resolve(Record(after))
        Record.parse(encoded(after), self.library.id)
        fields = sorted(set(sets) | set(operation["reset"]))
        return (
            sets,
            {field: record["resolved"].get(field) for field in fields},
            {field: after["resolved"].get(field) for field in fields},
        )

    def create_plan(
        self, owner, operation, *, selection_id=None, targets=None, query=None
    ):
        operation = normalize_operation(operation)
        if selection_id is not None and (targets is not None or query is not None):
            raise ValueError("Use one selection source")
        with self.library.writer():
            destination = None
            if operation["action"] == "move":
                folder = self.library.folder(operation["folder_id"])
                if not folder:
                    raise ValueError("Destination folder missing")
                destination = {key: folder[key] for key in ("id", "revision", "path")}
            selected = (
                self._load("selections", owner, selection_id, expires=True)["targets"]
                if selection_id is not None
                else self._targets(targets=targets, query=query)
            )
            frozen, preview = [], []
            for target in selected:
                record = self.library.get(target["id"])
                if record["revision"] != target["revision"]:
                    raise Conflict("Selected photo changed; refresh the selection")
                trashed = record.get("lifecycle") == "trashed"
                if trashed != (operation["action"] == "restore"):
                    raise Conflict("Restore trashed photos before editing")
                item = dict(target)
                sample = {"id": target["id"], "path": record["file"]["relative_path"]}
                if operation["action"] == "metadata":
                    item["set"], sample["before"], sample["after"] = self._metadata(
                        record, operation
                    )
                elif operation["action"] == "move":
                    sample.update(
                        before={"folder": str(PurePosixPath(sample["path"]).parent)},
                        after={"folder": destination["path"]},
                    )
                else:
                    sample.update(
                        before={"lifecycle": "trashed" if trashed else "active"},
                        after={"lifecycle": "active" if trashed else "trashed"},
                    )
                frozen.append(item)
                if len(preview) < 5:
                    preview.append(sample)
            data = {
                "id": self.new_id(),
                "owner": owner,
                "library_id": self.library.id,
                "created": self.clock(),
                "expires": self.clock() + TTL,
                "state": "ready",
                "operation": operation,
                "destination": destination,
                "targets": frozen,
                "preview": preview,
            }
            atomic(self._path("batch-plans", data["id"]), data)
        return self._plan_summary(data)

    def _plan_summary(self, data):
        result = self._version(data)
        result["count"] = len(result.pop("targets"))
        result.pop("owner")
        result.pop("library_id")
        return result

    def get_plan(self, owner, ident):
        return self._plan_summary(self._load("batch-plans", owner, ident))

    def execute_plan(self, owner, ident, revision, authorize=None):
        with self.library.writer():
            data = self._load("batch-plans", owner, ident, expires=True)
            if data["state"] != "ready" or self._version(data)["revision"] != revision:
                raise Conflict(
                    "Batch already started or changed; create a fresh preview"
                )
            data["state"] = "running"
            atomic(self._path("batch-plans", ident), data)
        result = {
            "total": len(data["targets"]),
            "succeeded": 0,
            "conflicts": 0,
            "failed": 0,
            "items": [],
        }
        operation = data["operation"]
        revoked = False
        for target in data["targets"]:
            item = {"id": target["id"]}
            try:
                if revoked or (authorize is not None and not authorize()):
                    revoked = True
                    raise PermissionError("Authority revoked")
                action = operation["action"]
                if action == "metadata":
                    self.library.metadata(
                        target["id"],
                        target["revision"],
                        target["set"],
                        operation["reset"],
                        owner,
                    )
                elif action == "move":
                    self.library.move(
                        target["id"],
                        target["revision"],
                        operation["folder_id"],
                        owner,
                        expected_folder=data["destination"],
                    )
                else:
                    getattr(self.library, action)(
                        target["id"], target["revision"], owner
                    )
                item["state"] = "succeeded"
                result["succeeded"] += 1
            except (Conflict, KeyError) as error:
                item.update(state="conflict", error=str(error))
                result["conflicts"] += 1
            except Exception as error:
                item.update(state="failed", error=str(error))
                result["failed"] += 1
            result["items"].append(item)
        with self.library.writer():
            data.update(state="completed", finished=self.clock(), result=result)
            atomic(self._path("batch-plans", ident), data)
        return result
