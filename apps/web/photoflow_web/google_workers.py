"""Private credentials and durable read-only jobs for paired desktop workers."""

import asyncio
import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect


def check(ok):
    if not ok:
        raise ValueError("Google worker request could not be verified")


def identifier(value):
    check(
        isinstance(value, str)
        and 0 < len(value) <= 4096
        and not re.search(r"[\s\x00-\x1f]", value)
    )
    return value


def hashed(value):
    return hashlib.sha256(identifier(value).encode()).hexdigest()


def validate_counts(result):
    check(
        isinstance(result, dict)
        and set(result)
        == {"photos", "favorites", "albums", "complete", "retentionReady"}
    )
    check(result["complete"] is True and result["retentionReady"] is False)
    check(
        all(
            type(result[k]) is int and 0 <= result[k] <= 1000000
            for k in ["photos", "favorites", "albums"]
        )
    )
    check(result["favorites"] <= result["photos"])


JOB_PROTOCOL_VERSION = 1
JOB_SPECS = {
    "inventory-counts": {
        "version": 1,
        "effect": "read",
        "validate_result": validate_counts,
        "phases": [
            "checking",
            "library",
            "favorites",
            "albums",
            "verifying",
            "complete",
            "failed",
        ],
    }
}


class WorkerStore:
    def __init__(self, directory, now=time.time):
        self.now = now
        directory = Path(directory) / "google-workers"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        check(directory.stat().st_mode & 0o077 == 0)
        self.path = directory / "workers.sqlite"
        self.path.touch(mode=0o600, exist_ok=True)
        with self.db() as db:
            db.executescript(
                """CREATE TABLE IF NOT EXISTS pairing(code TEXT PRIMARY KEY,owner TEXT,account TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY,owner TEXT UNIQUE,account TEXT UNIQUE,token TEXT,expires REAL,last_seen REAL,ready INTEGER);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT,worker TEXT,state TEXT,lease TEXT,started REAL,created REAL,result TEXT,error TEXT);"""
            )
            for name, definition in [
                ("operation", "TEXT NOT NULL DEFAULT 'inventory-counts'"),
                ("events", "TEXT NOT NULL DEFAULT '[]'"),
                ("attempt", "INTEGER NOT NULL DEFAULT 0"),
                ("account", "TEXT"),
            ]:
                if name not in {
                    row[1] for row in db.execute("PRAGMA table_info(jobs)")
                }:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            db.execute(
                "UPDATE jobs SET account=(SELECT account FROM workers WHERE workers.id=jobs.worker) WHERE account IS NULL"
            )
            # Only read jobs exist. Re-enumeration is safe; old leases never survive restart.
            for row in db.execute(
                "SELECT * FROM jobs WHERE state='running'"
            ).fetchall():
                safe = JOB_SPECS.get(row["operation"], {}).get("effect") == "read"
                db.execute(
                    "UPDATE jobs SET state=?,lease=NULL,error=? WHERE id=?",
                    (
                        "queued" if safe else "unknown",
                        None if safe else "UNKNOWN_OUTCOME",
                        row["id"],
                    ),
                )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def pairing(self, owner, account):
        identifier(account)
        code = secrets.token_urlsafe(32)
        expires = self.now() + 300
        with self.db() as db:
            db.execute(
                "DELETE FROM pairing WHERE owner=? OR expires<?", (owner, self.now())
            )
            db.execute(
                "INSERT INTO pairing VALUES(?,?,?,?)",
                (hashed(code), owner, account, expires),
            )
        return {"code": code, "expires_at": expires}

    def pair(self, code, account):
        identifier(account)
        token = secrets.token_urlsafe(48)
        ident = secrets.token_hex(16)
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM pairing WHERE code=?", (hashed(code),)
            ).fetchone()
            check(row and row["account"] == account and row["expires"] > self.now())
            old = db.execute(
                "SELECT * FROM workers WHERE owner=? OR account=?",
                (row["owner"], account),
            ).fetchall()
            check(all(w["owner"] == row["owner"] for w in old))
            for w in old:
                db.execute(
                    "UPDATE jobs SET state='failed',error='REPAIRED' WHERE worker=? AND state IN ('queued','running')",
                    (w["id"],),
                )
            db.execute("DELETE FROM workers WHERE owner=?", (row["owner"],))
            db.execute(
                "INSERT INTO workers VALUES(?,?,?,?,?,?,?)",
                (
                    ident,
                    row["owner"],
                    account,
                    hashed(token),
                    self.now() + 14 * 86400,
                    0,
                    0,
                ),
            )
            db.execute("DELETE FROM pairing WHERE code=?", (hashed(code),))
        return {"worker_id": ident, "account": account, "token": token}

    def authenticate(self, token, account):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM workers WHERE token=? AND account=? AND expires>?",
                (hashed(token), account, self.now()),
            ).fetchone()
        check(row)
        return dict(row)

    def touch(self, ident, ready):
        check(type(ready) is bool)
        with self.db() as db:
            db.execute(
                "UPDATE workers SET last_seen=?,ready=? WHERE id=?",
                (self.now(), int(ready), ident),
            )

    def enqueue(self, owner, operation="inventory-counts"):
        check(operation in JOB_SPECS)
        with self.db() as db:
            worker = db.execute(
                "SELECT * FROM workers WHERE owner=? AND expires>?", (owner, self.now())
            ).fetchone()
            check(worker)
            check(
                not db.execute(
                    "SELECT 1 FROM jobs WHERE worker=? AND state='unknown'",
                    (worker["id"],),
                ).fetchone()
            )
            row = db.execute(
                "SELECT * FROM jobs WHERE worker=? AND state IN ('queued','running')",
                (worker["id"],),
            ).fetchone()
            if not row:
                ident = secrets.token_hex(16)
                db.execute(
                    "INSERT INTO jobs(id,owner,worker,state,lease,started,created,result,error,operation,account) VALUES(?,?,?,'queued',NULL,NULL,?,NULL,NULL,?,?)",
                    (
                        ident,
                        owner,
                        worker["id"],
                        self.now(),
                        operation,
                        worker["account"],
                    ),
                )
                row = db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
        return self.public_job(row)

    def claim(self, worker):
        with self.db() as db:
            db.execute(
                "UPDATE jobs SET state='failed',error='TIMEOUT' WHERE worker=? AND state='running' AND started<?",
                (worker, self.now() - 600),
            )
            if db.execute(
                "SELECT 1 FROM jobs WHERE worker=? AND state='running'", (worker,)
            ).fetchone():
                return None
            row = db.execute(
                "SELECT * FROM jobs WHERE worker=? AND state='queued' ORDER BY created LIMIT 1",
                (worker,),
            ).fetchone()
            if not row:
                return None
            lease = secrets.token_hex(16)
            db.execute(
                "UPDATE jobs SET state='running',lease=?,started=?,attempt=attempt+1 WHERE id=?",
                (lease, self.now(), row["id"]),
            )
            account = db.execute(
                "SELECT account FROM workers WHERE id=?", (worker,)
            ).fetchone()
            check(account and account["account"] == row["account"])
            return {
                "type": "job",
                "id": row["id"],
                "lease": lease,
                "operation": row["operation"],
                "version": JOB_SPECS[row["operation"]]["version"],
                "input": {},
                "attempt": row["attempt"] + 1,
                "account": account["account"],
            }

    def progress(self, worker, ident, lease, phase):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND worker=? AND lease=? AND state='running' AND started>?",
                (ident, worker, lease, self.now() - 600),
            ).fetchone()
            check(row)
            phases = JOB_SPECS[row["operation"]]["phases"]
            check(phase in phases)
            events = json.loads(row["events"])
            check(
                not events
                or events[-1].get("attempt") != row["attempt"]
                or phases.index(phase) >= phases.index(events[-1]["phase"])
            )
            events = (
                events + [{"phase": phase, "at": self.now(), "attempt": row["attempt"]}]
            )[-32:]
            db.execute(
                "UPDATE jobs SET events=? WHERE id=?", (json.dumps(events), ident)
            )

    def diagnostic(self, owner, ident):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND owner=?", (ident, owner)
            ).fetchone()
        check(row)
        return {
            "schemaVersion": 1,
            "protocol": JOB_PROTOCOL_VERSION,
            "kind": "photoflow-worker-job",
            "job": self.public_job(row),
            "started": row["started"],
        }

    def finish(self, worker, ident, lease, result=None, error=None):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND worker=? AND lease=? AND state='running' AND started>?",
                (ident, worker, lease, self.now() - 600),
            ).fetchone()
            check(row)
            if error is None:
                JOB_SPECS[row["operation"]]["validate_result"](result)
            else:
                check(result is None)
                check(
                    error
                    in {
                        "ACCOUNT",
                        "SESSION",
                        "PROTOCOL",
                        "TRANSPORT",
                        "HTTP",
                        "SIZE",
                        "TIMEOUT",
                        "CIRCUIT_OPEN",
                        "INPUT",
                    }
                )
            db.execute(
                "UPDATE jobs SET state=?,result=?,error=? WHERE id=?",
                (
                    "failed" if error else "succeeded",
                    json.dumps(result) if result else None,
                    error,
                    ident,
                ),
            )
            db.execute(
                "UPDATE workers SET ready=? WHERE id=?", (int(error is None), worker)
            )

    def disconnect(self, worker):
        with self.db() as db:
            for row in db.execute(
                "SELECT * FROM jobs WHERE worker=? AND state='running'", (worker,)
            ).fetchall():
                safe = JOB_SPECS.get(row["operation"], {}).get("effect") == "read"
                db.execute(
                    "UPDATE jobs SET state=?,lease=NULL,error=? WHERE id=?",
                    (
                        "queued" if safe else "unknown",
                        None if safe else "UNKNOWN_OUTCOME",
                        row["id"],
                    ),
                )
            db.execute("UPDATE workers SET last_seen=0,ready=0 WHERE id=?", (worker,))

    def revoke(self, owner):
        with self.db() as db:
            db.execute(
                "UPDATE jobs SET state='failed',error='REVOKED' WHERE owner=? AND state IN ('queued','running')",
                (owner,),
            )
            db.execute("DELETE FROM workers WHERE owner=?", (owner,))
            db.execute("DELETE FROM pairing WHERE owner=?", (owner,))

    @staticmethod
    def public_job(row):
        return {
            "id": row["id"],
            "operation": row["operation"],
            "account_ref": (
                hashlib.sha256(row["account"].encode()).hexdigest()[:16]
                if row["account"]
                else None
            ),
            "version": JOB_SPECS[row["operation"]]["version"],
            "events": json.loads(row["events"]),
            "attempt": row["attempt"],
            "state": row["state"],
            "created": row["created"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "error": row["error"],
        }

    def status(self, owner):
        with self.db() as db:
            w = db.execute(
                "SELECT * FROM workers WHERE owner=? AND expires>?", (owner, self.now())
            ).fetchone()
            jobs = db.execute(
                "SELECT * FROM jobs WHERE owner=? ORDER BY created DESC,rowid DESC LIMIT 20",
                (owner,),
            ).fetchall()
        running = any(row["state"] == "running" for row in jobs)
        return {
            "state": (
                "unpaired"
                if not w
                else (
                    "offline"
                    if self.now() - w["last_seen"] > 45
                    else (
                        "connected"
                        if w["ready"]
                        else "checking" if running else "needs_login"
                    )
                )
            ),
            "account": w["account"] if w else None,
            "jobs": [self.public_job(row) for row in jobs],
        }


def install_worker_routes(app, library, session, authorized=lambda owner: True):
    store = WorkerStore(library.state)
    active = {}
    app.state.google_workers = store

    def extension(origin):
        return isinstance(origin, str) and re.fullmatch(
            r"chrome-extension://[a-p]{32}", origin
        )

    def wake():
        for event in active.values():
            event.set()

    @app.get("/api/v1/google/status")
    async def status(req: Request):
        return store.status(session(req, 3)["username"])

    @app.post("/api/v1/google/pairing")
    async def pairing(req: Request, body: dict):
        return store.pairing(session(req, 3, True)["username"], body.get("account"))

    @app.post("/api/v1/google/pair")
    async def pair(req: Request, body: dict):
        if not extension(req.headers.get("origin")):
            raise HTTPException(403, "Extension required")
        result = store.pair(body.get("code"), body.get("account"))
        worker = store.authenticate(result["token"], result["account"])
        store.enqueue(worker["owner"])
        wake()
        return result

    @app.delete("/api/v1/google/connection")
    async def revoke(req: Request):
        store.revoke(session(req, 3, True)["username"])
        wake()
        return {"ok": True}

    @app.post("/api/v1/google/jobs")
    async def enqueue(req: Request, body: dict):
        owner = session(req, 3, True)["username"]
        check(set(body) <= {"operation"})
        result = store.enqueue(owner, body.get("operation", "inventory-counts"))
        wake()
        return result

    @app.get("/api/v1/google/jobs/{ident}/diagnostics")
    async def diagnostics(ident: str, req: Request):
        return store.diagnostic(session(req, 3)["username"], ident)

    @app.websocket("/api/v1/google/worker")
    async def worker(ws: WebSocket):
        if not extension(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
        await ws.accept()
        ident = None
        receive = None
        signal = None
        event = asyncio.Event()

        async def message():
            raw = await ws.receive_text()
            check(len(raw) <= 4096)
            value = json.loads(raw)
            check(isinstance(value, dict))
            return value

        try:
            first = await asyncio.wait_for(message(), 10)
            check(
                first.get("type") == "auth"
                and type(first.get("protocol")) is int
                and first.get("protocol") == JOB_PROTOCOL_VERSION
                and first.get("capabilities")
                == [
                    {"operation": name, "version": spec["version"]}
                    for name, spec in JOB_SPECS.items()
                ]
            )
            token, account = first.get("token"), first.get("account")
            w = store.authenticate(token, account)
            check(authorized(w["owner"]))
            ident = w["id"]
            check(ident not in active)
            active[ident] = event
            store.touch(ident, False)
            await ws.send_json(
                {
                    "type": "welcome",
                    "worker_id": ident,
                    "account": account,
                    "protocol": JOB_PROTOCOL_VERSION,
                }
            )
            receive = asyncio.create_task(message())
            while True:
                check(
                    store.authenticate(token, account)["id"] == ident
                    and authorized(w["owner"])
                )
                job = store.claim(ident)
                if job:
                    await ws.send_json(job)
                signal = asyncio.create_task(event.wait())
                done, _ = await asyncio.wait(
                    [receive, signal], timeout=45, return_when=asyncio.FIRST_COMPLETED
                )
                signal.cancel()
                await asyncio.gather(signal, return_exceptions=True)
                signal = None
                event.clear()
                if not done:
                    break
                if receive in done:
                    m = receive.result()
                    kind = m.get("type")
                    if kind == "heartbeat":
                        check(m.get("account") == account)
                        store.touch(ident, m.get("ready"))
                        await ws.send_json({"type": "heartbeat"})
                    elif kind == "progress":
                        store.progress(
                            ident, m.get("id"), m.get("lease"), m.get("phase")
                        )
                    elif kind == "result":
                        store.finish(
                            ident,
                            m.get("id"),
                            m.get("lease"),
                            m.get("result"),
                            m.get("error"),
                        )
                        await ws.send_json(
                            {"type": "receipt", "id": m["id"], "lease": m["lease"]}
                        )
                    else:
                        check(False)
                    receive = asyncio.create_task(message())
        except (
            WebSocketDisconnect,
            ValueError,
            TypeError,
            KeyError,
            asyncio.TimeoutError,
        ):
            pass
        finally:
            for task in [receive, signal]:
                if task:
                    task.cancel()
            await asyncio.gather(
                *[t for t in [receive, signal] if t], return_exceptions=True
            )
            if ident and active.get(ident) is event:
                active.pop(ident, None)
                store.disconnect(ident)
            try:
                await ws.close(code=1008)
            except RuntimeError:
                pass
