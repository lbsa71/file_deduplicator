"""Authenticated HTTP application; all library writes use the common coordinator."""

import concurrent.futures, grp, hashlib, json, os, pwd, secrets, socket, sqlite3, threading, time, uuid
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from .frontend import FrontendFiles
from .core import Library, Conflict, atomic, digest, load
from .media import Media
from .workspace import Workspace


def create_app(root=None, state=None, auth=None, role_resolver=None, static_root=None):
    library = Library(
        root or os.environ["PHOTOFLOW_LIBRARY"],
        state or os.environ.get("PHOTOFLOW_STATE", "/var/lib/photoflow-web"),
    )
    media = Media(library, library.state / "thumbnails")
    workspace = Workspace(library)
    sessions = {}
    attempts = {}
    executor = concurrent.futures.ThreadPoolExecutor(1)

    def broker(d):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(10)
            sock.connect("/run/photoflow-auth/auth.sock")
            sock.sendall(json.dumps(d).encode() + b"\n")
            return json.loads(sock.recv(4096))

    auth = auth or broker

    def role(name):
        if role_resolver:
            return role_resolver(name)
        user = pwd.getpwnam(name)
        groups = {grp.getgrgid(g).gr_name for g in os.getgrouplist(name, user.pw_gid)}
        return (
            3
            if "photoflow-admins" in groups
            else (
                2
                if "photoflow-editors" in groups
                else 1 if "photoflow-readers" in groups else 0
            )
        )

    def session(req, level=1, write=False):
        token = req.cookies.get("__Host-photoflow")
        d = sessions.get(token)
        if (
            not d
            or time.time() - d["last"] > 1800
            or time.time() - d["created"] > 43200
        ):
            raise HTTPException(401, "Login required")
        if time.time() - d["checked"] > 60:
            try:
                valid = auth({"username": d["username"], "uid": d["uid"]})["ok"]
            except Exception:
                raise HTTPException(503, "Authentication unavailable")
            if not valid:
                sessions.pop(token, None)
                raise HTTPException(401, "Account unavailable")
            d["checked"] = time.time()
        d["role"] = role(d["username"])
        d["last"] = time.time()
        if d["role"] < level:
            raise HTTPException(403, "Insufficient permission")
        if write:
            origin = req.headers.get("origin")
            if (
                origin != str(req.base_url).rstrip("/")
                or req.headers.get("x-csrf-token") != d["csrf"]
            ):
                raise HTTPException(403, "Invalid CSRF token/origin")
        return d

    def revision(req):
        value = req.headers.get("if-match")
        if not value:
            raise HTTPException(428, "If-Match required")
        return value.strip('"')

    def job(owner, action, fn):
        ident = uuid.uuid4().hex
        d = {
            "id": ident,
            "owner": owner,
            "action": action,
            "state": "queued",
            "created": time.time(),
        }

        def save():
            with library.db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO jobs VALUES(?,?,?,?)",
                    (ident, owner, d["state"], json.dumps(d)),
                )

        save()

        def run():
            try:
                if owner != "system" and role(owner) < (
                    3 if action == "scan" else 1 if action == "export" else 2
                ):
                    raise ValueError("Authority revoked")
                d["state"] = "running"
                save()
                result = fn()
                d.update(state="succeeded", result=result)
            except Exception as error:
                d.update(state="failed", error=str(error))
            finally:
                d["finished"] = time.time()
                save()

        executor.submit(run)
        return JSONResponse(
            {"job_id": ident, "state": "queued", "status_url": "/api/v1/jobs/" + ident},
            status_code=202,
        )

    def scan(mode="reconcile"):
        from photoflow.adapters import ExifToolReader, SystemClock, RandomIds
        from photoflow.runner import Runner, Config
        from photoflow.geocoder import ExifToolGeocoder

        with library.mutex:
            with library.writer():
                if mode == "metadata":
                    for path in library.fs.list_files():
                        if path.endswith(".photo.json"):
                            record = load(library.path(path))
                            record["stages"].pop("embedded_metadata", None)
                            atomic(library.path(path), record)
            if mode == "catalog":
                return {"records": library.rebuild()}
            if mode == "thumbnails":
                with library.db() as db:
                    records = [
                        json.loads(row[0])
                        for row in db.execute("SELECT data FROM photos")
                    ]
                for record in records:
                    if record.get("lifecycle") != "trashed":
                        for level in (64, 256, 512):
                            media.variant(record, level)
                return {"scheduled_records": len(records)}
            place_warning = None
            try:
                geocoder = ExifToolGeocoder(database=os.environ.get("PHOTOFLOW_GEODIR"))
            except (ValueError, OSError) as error:
                geocoder = None
                place_warning = str(error)
            result = Runner(
                library.fs,
                SystemClock(),
                RandomIds(),
                ExifToolReader(library.fs),
                Config(
                    settle_seconds=0,
                    verify=mode == "verify",
                    expected_library_id=library.id,
                ),
                geocoder=geocoder,
            ).run()
            if place_warning:
                result.warnings.append("place_enrichment: " + place_warning)
            library.rebuild()
            return result.to_dict()

    @asynccontextmanager
    async def lifespan(app):
        with library.writer():
            pass
        library.rebuild()
        with library.db() as db:
            for row in db.execute(
                "SELECT id,data FROM jobs WHERE state IN ('queued','running')"
            ).fetchall():
                d = json.loads(row["data"])
                d.update(
                    state="failed",
                    error="Service restarted; refresh resources and retry",
                )
                db.execute(
                    "UPDATE jobs SET state=?,data=? WHERE id=?",
                    ("failed", json.dumps(d), row["id"]),
                )
        from .watch import Reconciler

        watcher = Reconciler(library, lambda: job("system", "scan", scan))
        watcher.start()
        try:
            yield
        finally:
            watcher.close()

    app = FastAPI(title="PhotoFlow Web", lifespan=lifespan)

    @app.exception_handler(Conflict)
    async def conflict(req, e):
        return JSONResponse({"detail": str(e)}, 409)

    @app.exception_handler(ValueError)
    async def invalid(req, e):
        return JSONResponse({"detail": str(e)}, 422)

    @app.exception_handler(KeyError)
    async def missing(req, e):
        return JSONResponse({"detail": "Resource not found"}, 404)

    @app.exception_handler(OSError)
    async def unavailable(req, e):
        return JSONResponse(
            {"detail": "Storage unavailable; check Activity or server logs"}, 503
        )

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    def login(req: Request, body: dict):
        if req.headers.get("origin") != str(req.base_url).rstrip("/"):
            raise HTTPException(403, "Invalid origin")
        peer = req.client.host
        now = time.time()
        recent = [t for t in attempts.get(peer, []) if now - t < 60]
        attempts[peer] = recent
        if len(recent) >= 10:
            raise HTTPException(429, "Please wait before retrying")
        recent.append(now)
        name = body.get("username")
        password = body.get("password")
        if (
            not isinstance(name, str)
            or not isinstance(password, str)
            or len(name) > 256
            or len(password) > 1024
            or not password
        ):
            raise HTTPException(401, "Login failed")
        try:
            result = auth({"username": name, "password": password})
            access = role(name) if result["ok"] else 0
        except Exception:
            raise HTTPException(503, "Authentication unavailable")
        if not access:
            raise HTTPException(401, "Login failed")
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        sessions[token] = {
            "username": name,
            "uid": result["uid"],
            "role": access,
            "csrf": csrf,
            "last": now,
            "created": now,
            "checked": now,
        }
        response = JSONResponse({"username": name, "role": access, "csrf": csrf})
        response.set_cookie(
            "__Host-photoflow",
            token,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    @app.get("/api/v1/auth/session")
    def current(req: Request):
        d = session(req)
        return {k: d[k] for k in ("username", "role", "csrf")}

    @app.post("/api/v1/auth/logout")
    def logout(req: Request):
        session(req, write=True)
        sessions.pop(req.cookies.get("__Host-photoflow"), None)
        r = Response(status_code=204)
        r.delete_cookie("__Host-photoflow", secure=True)
        return r

    @app.get("/api/v1/library")
    def info(req: Request):
        session(req)
        return {
            "id": library.id,
            "available": library.available(),
            "folders": library.folders(),
            "thumbnail_levels": media.levels,
        }

    @app.get("/api/v1/photos")
    def photos(
        req: Request,
        q: str = "",
        offset: int = 0,
        limit: int = 100,
        folder: str | None = None,
        duplicates: bool = False,
        favorite: bool = False,
        trash: bool = False,
        filters: str = "{}",
    ):
        session(req)
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError("Invalid page")
        return library.listing(
            q,
            offset,
            limit,
            folder,
            duplicates,
            favorite,
            trash,
            filters=json.loads(filters),
        )

    @app.get("/api/v1/facets")
    def facets(
        req: Request,
        q: str = "",
        folder: str | None = None,
        duplicates: bool = False,
        favorite: bool = False,
        trash: bool = False,
        filters: str = "{}",
    ):
        session(req)
        return library.facets(
            q=q,
            folder=folder,
            duplicates=duplicates,
            favorite=favorite,
            trash=trash,
            filters=json.loads(filters),
        )

    @app.get("/api/v1/views")
    def views(req: Request):
        return workspace.list_views(session(req)["username"])

    @app.post("/api/v1/views")
    def create_view(req: Request, body: dict):
        user = session(req, 1, True)
        return workspace.create_view(
            user["username"], body.get("name"), body.get("query", {})
        )

    @app.patch("/api/v1/views/{ident}")
    def update_view(ident: str, req: Request, body: dict):
        user = session(req, 1, True)
        current = next(
            (
                v
                for v in workspace.list_views(user["username"])["items"]
                if v["id"] == ident
            ),
            None,
        )
        if current is None:
            raise KeyError(ident)
        return workspace.update_view(
            user["username"],
            ident,
            revision(req),
            body.get("name", current["name"]),
            body.get("query", current["query"]),
        )

    @app.delete("/api/v1/views/{ident}")
    def delete_view(ident: str, req: Request):
        user = session(req, 1, True)
        workspace.delete_view(user["username"], ident, revision(req))
        return {"deleted": True}

    @app.post("/api/v1/selections")
    def create_selection(req: Request, body: dict):
        user = session(req, 1, True)
        return workspace.create_selection(
            user["username"], query=body.get("query"), targets=body.get("targets")
        )

    @app.post("/api/v1/batch-plans")
    def create_plan(req: Request, body: dict):
        user = session(req, 2, True)
        return workspace.create_plan(
            user["username"],
            body.get("operation"),
            selection_id=body.get("selection_id"),
            targets=body.get("targets"),
            query=body.get("query"),
        )

    @app.post("/api/v1/batch-plans/{ident}/execute")
    def execute_plan(ident: str, req: Request):
        user = session(req, 2, True)
        rev = revision(req)
        plan = workspace.get_plan(user["username"], ident)
        if plan["revision"] != rev or plan["state"] != "ready":
            raise Conflict("Batch plan already used or changed; preview again")

        def authorized():
            if role(user["username"]) < 2:
                raise ValueError("Edit permission revoked")
            return True

        return job(
            user["username"],
            "batch",
            lambda: workspace.execute_plan(
                user["username"], ident, rev, authorize=authorized
            ),
        )

    @app.get("/api/v1/photos/{ident}")
    def photo(ident: str, req: Request):
        session(req)
        d = library.get(ident)
        return JSONResponse(d, headers={"ETag": '"' + d["revision"] + '"'})

    @app.patch("/api/v1/photos/{ident}/metadata")
    def metadata(ident: str, req: Request, body: dict):
        d = session(req, 2, True)
        rev = revision(req)
        return job(
            d["username"],
            "metadata",
            lambda: library.metadata(
                ident, rev, body.get("set", {}), body.get("reset", []), d["username"]
            ),
        )

    @app.post("/api/v1/photos/{ident}/placement")
    def placement(ident: str, req: Request, body: dict):
        d = session(req, 2, True)
        rev = revision(req)
        return job(
            d["username"],
            "move",
            lambda: library.move(ident, rev, body["folder_id"], d["username"]),
        )

    @app.delete("/api/v1/photos/{ident}")
    def trash_photo(ident: str, req: Request):
        d = session(req, 2, True)
        rev = revision(req)
        return job(
            d["username"], "trash", lambda: library.trash(ident, rev, d["username"])
        )

    @app.post("/api/v1/trash/{ident}/restore")
    def restore(ident: str, req: Request):
        d = session(req, 2, True)
        rev = revision(req)
        return job(
            d["username"], "restore", lambda: library.restore(ident, rev, d["username"])
        )

    def original_path(ident):
        d = library.get(ident)
        if d.get("lifecycle") == "trashed":
            raise HTTPException(409, "Restore this photo first")
        if not library.available():
            raise HTTPException(503, "Storage unavailable")
        return d, library.path(d["file"]["relative_path"])

    @app.api_route("/api/v1/photos/{ident}/original", methods=["GET", "HEAD"])
    def original(ident: str, req: Request, download: bool = False):
        session(req)
        d, p = original_path(ident)
        return FileResponse(
            p,
            filename=d["sources"][0]["original_filename"] if download else None,
            headers={"Cache-Control": "private, no-cache"},
            content_disposition_type="attachment" if download else "inline",
        )

    @app.get("/api/v1/photos/{ident}/sidecar")
    def sidecar(ident: str, req: Request):
        session(req)
        d = library.get(ident)
        return JSONResponse(
            d,
            headers={
                "Content-Disposition": f'attachment; filename="{ident}.photo.json"'
            },
        )

    @app.get("/api/v1/photos/{ident}/variants/{level}")
    def variant(ident: str, level: int, req: Request):
        session(req)
        d, p = original_path(ident)
        target, status = media.variant(d, level)
        if target:
            return FileResponse(
                target,
                media_type="image/webp",
                headers={"Cache-Control": "private, no-cache"},
            )
        return JSONResponse(
            {"state": status},
            status_code=202 if status == "pending" else 415,
            headers={"Retry-After": "2"},
        )

    @app.get("/api/v1/folders")
    def folders(req: Request, path: str = "."):
        session(req)
        p = library.path(path)
        if ".photoflow" in p.parts:
            raise HTTPException(403, "Protected state")
        if not p.is_dir():
            raise KeyError(path)
        children = [
            {
                "name": x.name,
                "path": str(x.relative_to(library.root)),
                "folder": next(
                    (
                        f
                        for f in library.folders()
                        if f["path"] == str(x.relative_to(library.root))
                    ),
                    None,
                ),
            }
            for x in p.iterdir()
            if x.is_dir() and not x.name.startswith(".") and not x.is_symlink()
        ]
        return {
            "path": path,
            "items": sorted(children, key=lambda x: x["name"].casefold()),
        }

    @app.post("/api/v1/folders")
    def create_folder(req: Request, body: dict):
        d = session(req, 2, True)
        return library.create_folder(body.get("parent_id"), body["name"], d["username"])

    @app.patch("/api/v1/folders/{ident}")
    def rename_folder(ident: str, req: Request, body: dict):
        d = session(req, 2, True)
        rev = revision(req)
        return job(
            d["username"],
            "folder",
            lambda: library.rename_folder(
                ident, rev, body["name"], body.get("parent_id"), d["username"]
            ),
        )

    @app.delete("/api/v1/folders/{ident}")
    def delete_folder(ident: str, req: Request):
        d = session(req, 2, True)
        rev = revision(req)
        return job(
            d["username"],
            "folder-trash",
            lambda: library.trash_folder(ident, rev, d["username"]),
        )

    @app.get("/api/v1/trash/folders")
    def folder_trash(req: Request):
        session(req)
        return {
            "items": [
                load(p)
                for p in (library.root / ".photoflow/trash-folders").glob(
                    "*/manifest.json"
                )
            ]
        }

    @app.post("/api/v1/trash/folders/{ident}/restore")
    def restore_folder(ident: str, req: Request):
        d = session(req, 2, True)
        return job(
            d["username"],
            "folder-restore",
            lambda: library.restore_folder(ident, d["username"]),
        )

    @app.post("/api/v1/uploads")
    def upload(req: Request, body: dict):
        d = session(req, 2, True)
        up = library.new_upload(
            d["username"], body["name"], body["size"], body.get("folder_id")
        )
        if body.get("batch_id"):
            if not __import__("re").fullmatch("[a-f0-9]{32}", body["batch_id"]):
                raise ValueError("Invalid batch")
            up["batch_id"] = body["batch_id"]
            atomic(library.upload_dir / up["id"] / "manifest.json", up)
        return up

    @app.get("/api/v1/uploads/{ident}")
    def upload_status(ident: str, req: Request):
        return library.upload(ident, session(req, 2)["username"])

    @app.put("/api/v1/uploads/{ident}/chunks")
    async def chunk(ident: str, req: Request):
        d = session(req, 2, True)
        if int(req.headers.get("content-length", 0)) > 8 * 1024**2:
            raise HTTPException(413, "Chunk too large")
        data = bytearray()
        async for piece in req.stream():
            data.extend(piece)
            if len(data) > 8 * 1024**2:
                raise HTTPException(413, "Chunk too large")
        return {
            "offset": library.chunk(
                ident, d["username"], int(req.headers["upload-offset"]), bytes(data)
            )
        }

    @app.post("/api/v1/uploads/{ident}/finish")
    def finish(ident: str, req: Request):
        return library.finish_upload(ident, session(req, 2, True)["username"])

    @app.post("/api/v1/upload-batches/{ident}/process")
    def process_uploads(ident: str, req: Request):
        d = session(req, 2, True)
        owned = any(
            up.get("batch_id") == ident and up["owner"] == d["username"]
            for up in (load(p) for p in library.upload_dir.glob("*/manifest.json"))
        )
        if not owned:
            raise KeyError(ident)
        return job(d["username"], "ingest", scan)

    @app.post("/api/v1/scans")
    def rescan(req: Request, body: dict):
        d = session(req, 3, True)
        mode = body.get("mode", "reconcile")
        if mode not in ("reconcile", "verify", "metadata", "catalog", "thumbnails"):
            raise ValueError("Invalid scan mode")
        return job(d["username"], "scan", lambda: scan(mode))

    @app.post("/api/v1/exports")
    def export(req: Request, body: dict):
        d = session(req, 1, True)
        ids = (
            [
                x["id"]
                for x in workspace.selection_targets(
                    d["username"], body["selection_id"]
                )
            ]
            if body.get("selection_id")
            else body.get("ids", [])
        )
        if not ids or len(ids) > 1000:
            raise ValueError("Select 1–1000 records")
        export_id = uuid.uuid4().hex

        def build():
            import zipfile

            records = [original_path(ident) for ident in ids]
            if sum(p.stat().st_size for _, p in records) > 20 * 1024**3:
                raise ValueError("Export exceeds 20 GiB")
            import shutil

            estimated = sum(p.stat().st_size for _, p in records)
            if shutil.disk_usage(library.state).free - estimated < 2 * 1024**3:
                raise OSError("Insufficient export disk space")
            base = library.state / "exports"
            base.mkdir(exist_ok=True)
            temporary = base / (export_id + ".partial")
            target = base / (export_id + ".zip")
            with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
                manifest = []
                for record, path in records:
                    name = Path(record["sources"][0]["original_filename"]).name
                    name = record["record_id"] + "-" + name.replace("\\", "_")
                    before = library.fs.stat(record["file"]["relative_path"])
                    archive.write(path, name)
                    if before != library.fs.stat(record["file"]["relative_path"]):
                        raise Conflict("Original changed during export")
                    if body.get("include_metadata"):
                        archive.writestr(
                            name + ".photo.json", json.dumps(record, ensure_ascii=False)
                        )
                    manifest.append(
                        {
                            "record_id": record["record_id"],
                            "name": name,
                            "sha256": record["file"]["sha256"],
                        }
                    )
                archive.writestr("manifest.json", json.dumps(manifest))
            os.replace(temporary, target)
            atomic(
                base / (export_id + ".json"),
                {"owner": d["username"], "created": time.time()},
            )
            return {"download_url": "/api/v1/exports/" + export_id + "/download"}

        return job(d["username"], "export", build)

    @app.get("/api/v1/exports/{ident}/download")
    def download_export(ident: str, req: Request):
        d = session(req)
        if not __import__("re").fullmatch("[a-f0-9]{32}", ident):
            raise ValueError("Invalid export")
        base = library.state / "exports"
        info = load(base / (ident + ".json"))
        if (
            not info
            or info["owner"] != d["username"]
            or time.time() - info["created"] > 86400
        ):
            raise KeyError(ident)
        return FileResponse(
            base / (ident + ".zip"),
            filename="PhotoFlow-export.zip",
            media_type="application/zip",
        )

    @app.get("/api/v1/jobs")
    def jobs(req: Request):
        session(req)
        with library.db() as db:
            return {
                "items": [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT data FROM jobs ORDER BY rowid DESC LIMIT 100"
                    )
                ]
            }

    @app.get("/api/v1/jobs/{ident}")
    def job_status(ident: str, req: Request):
        session(req)
        with library.db() as db:
            r = db.execute("SELECT data FROM jobs WHERE id=?", (ident,)).fetchone()
        if not r:
            raise KeyError(ident)
        return json.loads(r[0])

    static = Path(static_root) if static_root else Path(__file__).parent / "static"
    if static.exists():
        app.mount("/", FrontendFiles(directory=static, html=True), name="ui")
    app.state.library = library
    return app


def main():
    import uvicorn

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8090")),
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
