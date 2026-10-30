"""Filesystem authority, disposable read catalog, and serialized mutations."""

import hashlib, json, os, re, sqlite3, threading, time, uuid
from pathlib import Path
from contextlib import contextmanager
from photoflow.adapters import LocalFileSystem
from photoflow.model import Record, SIDECAR, encoded
from photoflow.metadata import resolve
from .query import Query, TABLES, ORDER, create_indexes, index_record


class Conflict(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path, default=None):
    return json.loads(path.read_bytes()) if path.exists() else default


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    try:
        with temp.open("xb") as f:
            f.write(encoded(value))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


class Library:
    def __init__(self, root, state):
        self.root = Path(root).resolve()
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.fs = LocalFileSystem(str(root))
        self.marker = load(self.root / ".photoflow/library.json")
        if not self.marker:
            raise ValueError("Library marker missing")
        self.id = self.marker["library_id"]
        self.mutex = threading.RLock()
        self.dbpath = self.state / "catalog.sqlite"
        self.registry = self.root / ".photoflow/folders.json"
        self.upload_dir = self.root / ".photoflow/uploads"
        self.ops = self.root / ".photoflow/web-operations"
        with self.db() as db:
            # Keep compatibility with the host SQLite. Rebuilds commit bounded
            # batches so rollback-journal readers wait for a batch, not a scan.
            if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                raise OSError("Could not initialize the web catalog journal")
            db.execute(
                "CREATE TABLE IF NOT EXISTS listing(id TEXT PRIMARY KEY,path TEXT,revision TEXT,metadata TEXT,search TEXT,duplicate INTEGER,trashed INTEGER,captured TEXT)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS listing_order ON listing(trashed,duplicate,captured DESC,id)"
            )
            db.executescript(
                "CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY,path TEXT,revision TEXT,data TEXT,stamp TEXT); CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT,state TEXT,data TEXT);"
            )
            create_indexes(db)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.dbpath, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def available(self):
        return (
            load(self.root / ".photoflow/library.json", {}).get("library_id") == self.id
        )

    @contextmanager
    def writer(self):
        with self.mutex:
            if not self.available():
                raise OSError("Storage unavailable")
            if load(self.root / ".photoflow/library.json")["schema_version"] != 2:
                raise Conflict("Library migration required")
            with self.fs.lock():
                self.recover()
                yield

    def path(self, value):
        if (
            not isinstance(value, str)
            or value.startswith("/")
            or "\\" in value
            or ".." in Path(value).parts
            or "\0" in value
        ):
            raise ValueError("Unsafe path")
        p = self.root / value
        if p.resolve() != self.root and self.root not in p.resolve().parents:
            raise ValueError("Unsafe path")
        for item in [p, *p.parents]:
            if item == self.root:
                break
            if item.is_symlink():
                raise ValueError("Symlink not allowed")
        return p

    def user_path(self, value):
        if not value.startswith("folders/") or value == "folders/":
            raise ValueError("Choose a user folder")
        return self.path(value)

    def folders(self):
        return load(self.registry, {"items": []})["items"]

    def folder(self, ident):
        return next((f for f in self.folders() if f["id"] == ident), None)

    def save_folders(self, items):
        atomic(
            self.registry, {"schema_version": 1, "library_id": self.id, "items": items}
        )

    def create_folder(self, parent, name, actor):
        if (
            not name
            or name in (".", "..")
            or re.search(r'[\x00-\x1f<>:"/\\|?*]', name)
            or name.endswith((".", " "))
        ):
            raise ValueError("Invalid folder name")
        with self.writer():
            folder = self.folder(parent) if parent else None
            if parent and not folder:
                raise ValueError("Parent missing")
            prefix = folder["path"] if folder else "folders"
            p = self.path(prefix)
            p.mkdir(exist_ok=True)
            if any(x.name.casefold() == name.casefold() for x in p.iterdir()):
                raise Conflict("Folder name exists")
            result = {
                "id": str(uuid.uuid4()),
                "path": prefix + "/" + name,
                "name": name,
                "parent_id": parent,
                "keep_empty": True,
                "revision": uuid.uuid4().hex,
            }
            self.path(result["path"]).mkdir()
            self.save_folders(self.folders() + [result])
            return result

    def recover(self):
        from photoflow.web_operations import recover

        recover(self.fs)

    def transaction(self, moves, writes, remove=()):
        for move in moves:
            source = self.path(move["from"])
            if source.is_file():
                before = source.stat()
                with source.open("rb") as stream:
                    move["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                if any(
                    getattr(before, key) != getattr(source.stat(), key)
                    for key in (
                        "st_size",
                        "st_mtime_ns",
                        "st_ctime_ns",
                        "st_ino",
                        "st_dev",
                    )
                ):
                    raise Conflict("Source changed during operation planning")
        expected_writes = {}
        for destination in writes:
            existing = self.path(destination)
            if not existing.exists():
                for move in moves:
                    if self.path(move["from"]).is_dir() and destination.startswith(
                        move["to"] + "/"
                    ):
                        existing = self.path(
                            move["from"] + destination[len(move["to"]) :]
                        )
                        break
            expected_writes[destination] = (
                digest(existing.read_bytes()) if existing.exists() else None
            )
        op = {
            "id": uuid.uuid4().hex,
            "moves": moves,
            "writes": writes,
            "expected_writes": expected_writes,
            "remove": list(remove),
        }
        atomic(self.ops / (op["id"] + ".json"), op)
        self.recover()

    def put_index(self, record, sidecar, connection=None):
        raw = sidecar.read_bytes()
        st = sidecar.stat()
        meta = {
            k: v for k, v in record.get("resolved", {}).items() if k != "provenance"
        }
        with (
            __import__("contextlib").nullcontext(connection)
            if connection is not None
            else self.db()
        ) as db:
            index_record(db, record)
            db.execute(
                "INSERT OR REPLACE INTO listing VALUES(?,?,?,?,?,?,?,?)",
                (
                    record["record_id"],
                    record["file"]["relative_path"],
                    digest(raw),
                    json.dumps(meta),
                    json.dumps(
                        [
                            meta,
                            record["file"]["relative_path"],
                            [s["original_filename"] for s in record["sources"]],
                        ],
                        ensure_ascii=False,
                    ).casefold(),
                    int(bool(record.get("duplicate_of"))),
                    int(record.get("lifecycle") == "trashed"),
                    meta.get("capture_time") or "",
                ),
            )
            db.execute(
                "INSERT OR REPLACE INTO photos VALUES(?,?,?,?,?)",
                (
                    record["record_id"],
                    record["file"]["relative_path"],
                    digest(raw),
                    json.dumps(record),
                    str(st.st_mtime_ns) + ":" + str(st.st_size),
                ),
            )

    def rebuild(self):
        if not self.available():
            raise OSError("Storage unavailable")
        seen = []
        connection = sqlite3.connect(self.dbpath, timeout=60)
        try:
            return self._rebuild(connection)
        finally:
            connection.close()

    def _rebuild(self, connection):
        seen = []

        def index(record, sidecar):
            self.put_index(record, sidecar, connection)
            seen.append(record["record_id"])
            if len(seen) % 64 == 0:
                connection.commit()

        for parent, dirs, files in os.walk(self.root):
            dirs[:] = [
                d
                for d in dirs
                if d not in (".photoflow", ".takeout-extract", "__MACOSX")
                and not (Path(parent) / d).is_symlink()
                and (Path(parent) / d).resolve() != self.state.resolve()
            ]
            for name in files:
                if not name.endswith(SIDECAR):
                    continue
                p = Path(parent) / name
                if p.is_symlink():
                    continue
                record = Record.parse(p.read_bytes(), self.id).data
                index(record, p)
        for p in (self.root / ".photoflow/trash").glob("*/record.json"):
            d = load(p)
            index(d, p)
        connection.commit()
        with self.db() as db:
            ids = {r[0] for r in db.execute("SELECT id FROM photos")}
            missing = sorted(ids - set(seen))
            for start in range(0, len(missing), 64):
                targets = [(ident,) for ident in missing[start : start + 64]]
                for table in ("photos", "listing", "query_labels", "query_properties"):
                    db.executemany(f"DELETE FROM {table} WHERE id=?", targets)
                db.commit()
        return len(seen)

    def get(self, ident):
        with self.db() as db:
            row = db.execute("SELECT * FROM photos WHERE id=?", (ident,)).fetchone()
        if not row:
            raise KeyError(ident)
        data = json.loads(row["data"])
        data["revision"] = row["revision"]
        return data

    def listing(
        self,
        q="",
        offset=0,
        limit=100,
        folder=None,
        duplicates=False,
        favorite=False,
        trash=False,
        filters=None,
    ):
        query = Query(q, folder, duplicates, favorite, trash, filters)
        where, params = query.where()
        with self.db() as db:
            db.execute("BEGIN")
            total = db.execute(
                f"SELECT count(*) FROM {TABLES} WHERE " + where, params
            ).fetchone()[0]
            rows = db.execute(
                f"SELECT l.* FROM {TABLES} WHERE "
                + where
                + f" ORDER BY {ORDER} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return {
            "items": [
                {
                    "id": r["id"],
                    "path": r["path"],
                    "revision": r["revision"],
                    "metadata": json.loads(r["metadata"]),
                    "duplicate_of": bool(r["duplicate"]),
                }
                for r in rows
            ],
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
        }

    def matching(
        self,
        q="",
        folder=None,
        duplicates=False,
        favorite=False,
        trash=False,
        filters=None,
    ):
        query = Query(q, folder, duplicates, favorite, trash, filters)
        with self.db() as db:
            return query.matching(db)

    def facets(
        self,
        q="",
        folder=None,
        duplicates=False,
        favorite=False,
        trash=False,
        filters=None,
    ):
        query = Query(q, folder, duplicates, favorite, trash, filters)
        with self.db() as db:
            db.execute("BEGIN")
            return query.facets(db)

    def checked(self, ident, revision):
        record = self.get(ident)
        record.pop("revision")
        path = self.path(record["file"]["relative_path"])
        sidecar = path.with_name(path.name + SIDECAR)
        if record.get("lifecycle") == "trashed":
            trash = load(self.root / ".photoflow/trash" / ident / "manifest.json")
            sidecar = self.path(trash["sidecar"])
        if digest(sidecar.read_bytes()) != revision:
            raise Conflict("Record changed; refresh before saving")
        return record, sidecar

    def event(self, d, actor, kind, **values):
        d["history"].append(
            {
                "seq": len(d["history"]) + 1,
                "event_id": str(uuid.uuid4()),
                "run_id": "web",
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "type": kind,
                "data": {"actor": actor, **values},
            }
        )

    def metadata(self, ident, revision, sets, resets, actor):
        allowed = {
            "title",
            "description",
            "people",
            "albums",
            "tags",
            "favorite",
            "location",
            "place",
            "display_rotation",
            "capture_time",
        }
        if (set(sets) | set(resets)) - allowed or set(sets) & set(resets):
            raise ValueError("Invalid metadata fields")
        for k, v in sets.items():
            if k in ("people", "albums", "tags", "place") and (
                not isinstance(v, list)
                or len(v) > 256
                or any(not isinstance(x, str) or len(x) > 256 for x in v)
            ):
                raise ValueError("Invalid labels")
            if (
                k in ("title", "description", "capture_time")
                and v is not None
                and (not isinstance(v, str) or len(v) > 16384)
            ):
                raise ValueError("Invalid text")
            if k == "favorite" and type(v) != bool:
                raise ValueError("Invalid favorite")
            if k == "display_rotation" and v not in (0, 90, 180, 270):
                raise ValueError("Invalid rotation")
        with self.writer():
            d, p = self.checked(ident, revision)
            if d.get("lifecycle") == "trashed":
                raise Conflict("Restore before editing")
            d["overrides"].update(sets)
            for k in resets:
                d["overrides"].pop(k, None)
            d["resolved"] = resolve(Record(d))
            self.event(d, actor, "metadata_edited", set=sets, reset=resets)
            Record.parse(encoded(d), self.id)
            atomic(p, d)
            self.put_index(d, p)
        return self.get(ident)

    def move(self, ident, revision, folder_id, actor, *, expected_folder=None):
        with self.writer():
            d, p = self.checked(ident, revision)
            folder = self.folder(folder_id)
            if expected_folder is not None and (
                not folder
                or any(
                    folder.get(key) != expected_folder.get(key)
                    for key in ("id", "revision", "path")
                )
            ):
                raise Conflict("Destination folder changed; create a fresh preview")
            if not folder:
                raise ValueError("Folder missing")
            old = d["file"]["relative_path"]
            target = folder["path"] + "/" + ident + Path(old).suffix
            d["placement"] = {
                "mode": "manual",
                "folder_id": folder_id,
                "folder_path": folder["path"],
            }
            d["file"]["relative_path"] = target
            self.event(d, actor, "moved", old_path=old, new_path=target)
            self.transaction(
                [] if old == target else [{"from": old, "to": target}],
                {target + SIDECAR: d},
                [] if old == target else [str(p.relative_to(self.root))],
            )
            d["file"]["fingerprint"] = self.fs.stat(target).to_dict()
            atomic(self.path(target + SIDECAR), d)
            self.put_index(d, self.path(target + SIDECAR))
        return self.get(ident)

    def trash(self, ident, revision, actor):
        with self.writer():
            d, p = self.checked(ident, revision)
            if d.get("lifecycle") == "trashed":
                return
            old = d["file"]["relative_path"]
            base = ".photoflow/trash/" + ident
            d["lifecycle"] = "trashed"
            self.event(d, actor, "trashed", path=old)
            # Relink active duplicate copies before removing their keeper.
            with self.db() as db:
                others = [
                    json.loads(r[0]) for r in db.execute("SELECT data FROM photos")
                ]
            copies = [
                x
                for x in others
                if x["record_id"] != ident
                and x.get("lifecycle") != "trashed"
                and x["file"].get("sha256") == d["file"].get("sha256")
            ]
            writes = {
                base + "/record.json": d,
                base
                + "/manifest.json": {
                    "original_path": old,
                    "media": base + "/original" + Path(old).suffix,
                    "sidecar": base + "/record.json",
                },
            }
            if copies and not d.get("duplicate_of"):
                keeper = min(copies, key=lambda x: x["record_id"])
                keeper.pop("duplicate_of", None)
                import copy

                by_source = {
                    source["source_id"]: source for source in keeper["sources"]
                }
                for source in d["sources"]:
                    if source["source_id"] not in by_source:
                        inherited = copy.deepcopy(source)
                        keeper["sources"].append(inherited)
                        by_source[source["source_id"]] = inherited
                    else:
                        existing = by_source[source["source_id"]]["documents"]
                        for document in source["documents"]:
                            if document not in existing:
                                existing.append(copy.deepcopy(document))
                keeper["resolved"] = resolve(Record(keeper))
                for x in copies:
                    if x is not keeper:
                        x["duplicate_of"] = {
                            "record_id": keeper["record_id"],
                            "sha256": d["file"]["sha256"],
                        }
                    self.event(x, actor, "keeper_promoted", keeper=keeper["record_id"])
                    writes[x["file"]["relative_path"] + SIDECAR] = x
            self.transaction(
                [{"from": old, "to": writes[base + "/manifest.json"]["media"]}],
                writes,
                [str(p.relative_to(self.root))],
            )
            self.put_index(d, self.path(base + "/record.json"))
            for x in copies:
                if x["file"]["relative_path"] + SIDECAR in writes:
                    self.put_index(x, self.path(x["file"]["relative_path"] + SIDECAR))

    def restore(self, ident, revision, actor):
        with self.writer():
            d, p = self.checked(ident, revision)
            base = ".photoflow/trash/" + ident
            manifest = load(self.path(base + "/manifest.json"))
            if not manifest:
                raise Conflict("Not in trash")
            target = manifest["original_path"]
            d["lifecycle"] = "active"
            self.event(d, actor, "restored", path=target)
            self.transaction(
                [{"from": manifest["media"], "to": target}],
                {target + SIDECAR: d},
                [manifest["sidecar"], base + "/manifest.json"],
            )
            d["file"]["fingerprint"] = self.fs.stat(target).to_dict()
            atomic(self.path(target + SIDECAR), d)
            self.put_index(d, self.path(target + SIDECAR))

    def new_upload(self, owner, name, size, folder):
        import shutil

        if not self.available():
            raise OSError("Storage unavailable")
        active = [load(p) for p in self.upload_dir.glob("*/manifest.json")]
        active = [d for d in active if d.get("state") == "uploading"]
        if sum(d["owner"] == owner for d in active) >= 2:
            raise Conflict("Two uploads already active; resume them first")
        usage = shutil.disk_usage(self.root)
        reserved = sum(d["size"] - d["offset"] for d in active)
        if usage.free - reserved - size < max(2 * 1024**3, usage.total // 50):
            raise OSError("Insufficient free space")
        if (
            size < 0
            or size > 20 * 1024**3
            or Path(name).name != name
            or not name
            or "\\" in name
        ):
            raise ValueError("Invalid upload")
        if folder and not self.folder(folder):
            raise ValueError("Folder missing")
        from photoflow.runner import MEDIA_EXTENSIONS

        if Path(name).suffix.lower() not in MEDIA_EXTENSIONS and not name.endswith(
            ".json"
        ):
            raise ValueError("Unsupported media")
        ident = uuid.uuid4().hex
        d = {
            "id": ident,
            "owner": owner,
            "name": name,
            "size": size,
            "offset": 0,
            "folder_id": folder,
            "state": "uploading",
            "chunks": {},
            "record_id": str(uuid.uuid4()),
        }
        atomic(self.upload_dir / ident / "manifest.json", d)
        return d

    def upload(self, ident, owner):
        if not re.fullmatch("[a-f0-9]{32}", ident):
            raise ValueError("Invalid upload ID")
        d = load(self.upload_dir / ident / "manifest.json")
        if not d or d["owner"] != owner:
            raise KeyError(ident)
        return d

    def chunk(self, ident, owner, offset, data):
        if not self.available():
            raise OSError("Storage unavailable")
        with self.mutex:
            d = self.upload(ident, owner)
            if d["state"] != "uploading":
                raise Conflict("Upload already finished")
            if offset != d["offset"]:
                if d["chunks"].get(str(offset)) == digest(data):
                    return d["offset"]
                raise Conflict("Upload offset conflict")
            if len(data) > 8 * 1024**2 or offset + len(data) > d["size"]:
                raise ValueError("Chunk too large")
            p = self.upload_dir / ident / "partial"
            with p.open("r+b" if p.exists() else "wb") as f:
                f.seek(offset)
                f.write(data)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
            d["chunks"][str(offset)] = digest(data)
            d["offset"] += len(data)
            atomic(p.parent / "manifest.json", d)
            return d["offset"]

    def finish_upload(self, ident, owner):
        with self.writer():
            d = self.upload(ident, owner)
            if d["state"] == "committed":
                return d
            if d["offset"] != d["size"]:
                raise Conflict("Incomplete upload")
            batch = "inbox/web/" + owner + "/" + d.get("batch_id", ident)
            name = d["name"]
            target = batch + "/" + name
            p = self.upload_dir / ident / "partial"
            if not p.exists():
                p.touch()
            writes = {}
            if name.endswith(".json"):
                if d["size"] > 32 * 1024**2 or not isinstance(load(p), dict):
                    raise ValueError("Metadata must be a JSON object under 32 MiB")
            else:
                record = Record.create(d["record_id"], self.id, target).data
                if d.get("folder_id"):
                    folder = self.folder(d["folder_id"])
                    if not folder:
                        raise Conflict("Destination folder no longer exists")
                    record["placement"] = {
                        "mode": "manual",
                        "folder_id": folder["id"],
                        "folder_path": folder["path"],
                    }
                self.event(record, owner, "uploaded", filename=name)
                writes[target + SIDECAR] = record
            d["state"] = "committed"
            d["path"] = target
            writes[
                str((self.upload_dir / ident / "manifest.json").relative_to(self.root))
            ] = d
            self.transaction(
                [{"from": str(p.relative_to(self.root)), "to": target}], writes
            )
            return d

    def rename_folder(self, ident, revision, name, parent_id, actor):
        with self.writer():
            f = self.folder(ident)
            if not f or f["revision"] != revision:
                raise Conflict("Folder changed")
            if (
                not name
                or re.search(r'[\x00-\x1f<>:"/\\|?*]', name)
                or name in (".", "..")
                or name.endswith((".", " "))
            ):
                raise ValueError("Invalid folder name")
            parent = self.folder(parent_id) if parent_id else None
            if parent_id and not parent:
                raise ValueError("Parent missing")
            old = f["path"]
            target = (parent["path"] if parent else "folders") + "/" + name
            if target.startswith(old + "/"):
                raise Conflict("Cannot move inside itself")
            if old == target:
                return f
            if any(
                p.name.casefold() == name.casefold()
                for p in self.path(str(Path(target).parent)).iterdir()
            ):
                raise Conflict("Destination occupied")
            registry = self.folders()
            writes = {}
            for entry in registry:
                if entry["path"] == old or entry["path"].startswith(old + "/"):
                    entry["path"] = target + entry["path"][len(old) :]
                    entry["revision"] = uuid.uuid4().hex
                    if entry["id"] == ident:
                        entry.update(name=name, parent_id=parent_id)
            with self.db() as db:
                records = [
                    json.loads(r[0]) for r in db.execute("SELECT data FROM photos")
                ]
            for d in records:
                path = d["file"]["relative_path"]
                if d.get("lifecycle") != "trashed" and path.startswith(old + "/"):
                    new = target + path[len(old) :]
                    d["file"]["relative_path"] = new
                    d["placement"]["folder_path"] = str(Path(new).parent)
                    self.event(d, actor, "folder_moved", old=old, new=target)
                    writes[new + SIDECAR] = d
            writes[".photoflow/folders.json"] = {
                "schema_version": 1,
                "library_id": self.id,
                "items": registry,
            }
            mapping = load(
                self.root / ".photoflow/source-relocations.json", {"items": []}
            )
            mapping["items"].append({"from": old, "to": target})
            writes[".photoflow/source-relocations.json"] = mapping
            self.transaction([{"from": old, "to": target}], writes)
            for path, d in writes.items():
                if path.endswith(SIDECAR):
                    self.put_index(d, self.path(path))
            return self.folder(ident)

    def trash_folder(self, ident, revision, actor):
        f = self.folder(ident)
        if not f or f["revision"] != revision:
            raise Conflict("Folder changed")
        with self.db() as db:
            records = [json.loads(r[0]) for r in db.execute("SELECT data FROM photos")]
        selected = [
            d
            for d in records
            if d.get("lifecycle") != "trashed"
            and d["file"]["relative_path"].startswith(f["path"] + "/")
        ]
        base = ".photoflow/trash-folders/" + ident
        snapshot = {
            "folder": f,
            "entries": [
                x
                for x in self.folders()
                if x["path"] == f["path"] or x["path"].startswith(f["path"] + "/")
            ],
            "records": [x["record_id"] for x in selected],
        }
        with self.writer():
            atomic(self.path(base + "/manifest.json"), snapshot)
        for d in selected:
            current = self.get(d["record_id"])
            self.trash(d["record_id"], current["revision"], actor)
        with self.writer():
            entries = [x for x in self.folders() if x not in snapshot["entries"]]
            self.transaction(
                [{"from": f["path"], "to": base + "/folder"}],
                {
                    ".photoflow/folders.json": {
                        "schema_version": 1,
                        "library_id": self.id,
                        "items": entries,
                    }
                },
            )
        return {"folder_trash_id": ident, "records": len(selected)}

    def restore_folder(self, ident, actor):
        base = ".photoflow/trash-folders/" + ident
        manifest = load(self.path(base + "/manifest.json"))
        if not manifest:
            raise KeyError(ident)
        with self.writer():
            if self.path(base + "/folder").exists():
                self.transaction(
                    [{"from": base + "/folder", "to": manifest["folder"]["path"]}], {}
                )
            entries = self.folders()
            known = {f["id"] for f in entries}
            entries.extend(f for f in manifest["entries"] if f["id"] not in known)
            self.save_folders(entries)
        for record_id in manifest["records"]:
            d = self.get(record_id)
            if d.get("lifecycle") == "trashed":
                self.restore(record_id, d["revision"], actor)
        with self.writer():
            self.path(base + "/manifest.json").unlink()
        return {"restored": ident}
