"""Durable local commands, safe-boundary control, and a transactional event outbox."""

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .core import Conflict
from .job_context import operation_id


class Cancelled(Exception):
    pass


class Stopping(Exception):
    pass


class Deferred(Exception):
    def __init__(self, reason):
        self.reason = reason


class ReconciliationRequired(Exception):
    pass


TERMINAL = {"succeeded", "partial", "failed", "cancelled"}


class JobStore:
    def __init__(self, directory, library_id, clock=time.time):
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / "operations.sqlite"
        self.path.touch(mode=0o600, exist_ok=True)
        self.library_id, self.clock = library_id, clock
        with self.db(True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS commands(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,
                    owner TEXT NOT NULL,state TEXT NOT NULL,available REAL NOT NULL,
                    request_key TEXT,data TEXT NOT NULL,UNIQUE(owner,request_key));
                CREATE INDEX IF NOT EXISTS commands_ready ON commands(state,available,seq);
                CREATE TABLE IF NOT EXISTS steps(
                    job TEXT NOT NULL,name TEXT NOT NULL,state TEXT NOT NULL,result TEXT,
                    PRIMARY KEY(job,name));
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,created REAL NOT NULL,
                    owner TEXT,private INTEGER NOT NULL,name TEXT NOT NULL,data TEXT NOT NULL);
            """)

    @contextmanager
    def db(self, write=False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    def _get(self, db, ident):
        row = db.execute("SELECT data FROM commands WHERE id=?", (ident,)).fetchone()
        if not row:
            raise KeyError(ident)
        return json.loads(row[0])

    def _save(self, db, data):
        data["updated"] = self.clock()
        db.execute("UPDATE commands SET state=?,available=?,data=? WHERE id=?",
                   (data["state"], data.get("available", 0), json.dumps(data), data["id"]))
        self._event(db, "job.updated", {"job_id": data["id"], "state": data["state"],
                    "action": data["action"], "attempt": data["attempt"]},
                    data["owner"], data["private"])

    def _event(self, db, name, data, owner=None, private=False):
        db.execute("INSERT INTO events(created,owner,private,name,data) VALUES(?,?,?,?,?)",
                   (self.clock(), owner, int(private), name, json.dumps(data)))
        db.execute("DELETE FROM events WHERE created<?", (self.clock() - 900,))

    def event(self, name, data, owner=None, private=False):
        with self.db(True) as db:
            self._event(db, name, data, owner, private)

    def enqueue(self, owner, action, params, key=None, private=False, system=False):
        serialized = json.dumps(params, sort_keys=True, allow_nan=False)
        if len(serialized.encode()) > 256 * 1024 or not isinstance(params, dict):
            raise ValueError("Operation parameters exceed the request limit")
        if key is not None and (not isinstance(key, str) or not 0 < len(key) <= 128):
            raise ValueError("Invalid idempotency key")
        with self.db(True) as db:
            if key is not None:
                row = db.execute("SELECT data FROM commands WHERE owner=? AND request_key=?", (owner, key)).fetchone()
                if row:
                    previous = json.loads(row[0])
                    if previous["action"] != action or previous["params"] != params or previous["system"] != system:
                        raise Conflict("Idempotency key already describes another operation")
                    return previous
            data = {"schema_version": 1, "library_id": self.library_id,
                    "id": uuid.uuid4().hex, "owner": owner, "action": action,
                    "params": params, "private": private, "system": system,
                    "state": "queued", "attempt": 1, "created": self.clock(),
                    "available": 0, "cancel_requested": False, "progress": {}}
            db.execute("INSERT INTO commands(id,owner,state,available,request_key,data) VALUES(?,?,?,?,?,?)",
                       (data["id"], owner, "queued", 0, key, json.dumps(data)))
            self._save(db, data)
            return data

    def get(self, ident):
        with self.db() as db:
            return self._get(db, ident)

    def listing(self, actor, admin=False, before=None, limit=100):
        if not 1 <= limit <= 100 or (before is not None and before < 1):
            raise ValueError("Invalid job page")
        with self.db() as db:
            rows = db.execute("SELECT seq,data FROM commands WHERE (? IS NULL OR seq<?) ORDER BY seq DESC",
                              (before, before)).fetchall()
        items = []
        for row in rows:
            data = json.loads(row["data"])
            if not data["private"] or admin or data["owner"] == actor:
                items.append((row["seq"], data))
                if len(items) > limit:
                    break
        return {"items": [data for _, data in items[:limit]],
                "next_cursor": items[limit-1][0] if len(items) > limit else None}

    def recover(self):
        with self.db(True) as db:
            for row in db.execute("SELECT id FROM commands WHERE state IN ('running','cancelling')").fetchall():
                data = self._get(db, row["id"])
                data.update(state="queued", available=0, waiting_reason="recovering")
                self._save(db, data)

    def claim(self):
        with self.db(True) as db:
            row = db.execute("SELECT id FROM commands WHERE state='queued' AND available<=? ORDER BY seq LIMIT 1",
                             (self.clock(),)).fetchone()
            if not row:
                return None
            data = self._get(db, row[0])
            data.update(state="running", started=self.clock())
            data.pop("waiting_reason", None)
            self._save(db, data)
            return data

    def cancel(self, ident):
        with self.db(True) as db:
            data = self._get(db, ident)
            if data["state"] not in TERMINAL:
                data["cancel_requested"] = True
                data["state"] = "cancelled" if data["state"] == "queued" else "cancelling"
                if data["state"] == "cancelled":
                    data["finished"] = self.clock()
                self._save(db, data)
            return data

    def retry(self, ident):
        with self.db(True) as db:
            data = self._get(db, ident)
            if data["state"] not in {"failed", "partial", "cancelled"} or data.get("legacy"):
                raise Conflict("This operation cannot be retried in its current state")
            data.update(state="queued", attempt=data["attempt"] + 1, available=0, cancel_requested=False)
            for key in ("error", "error_code", "finished", "waiting_reason"):
                data.pop(key, None)
            self._save(db, data)
            return data

    def update(self, ident, **changes):
        with self.db(True) as db:
            data = self._get(db, ident)
            data.update(changes)
            # Progress updates must not overwrite a concurrent cancellation.
            self._save(db, data)
            return data

    def step(self, ident, name):
        with self.db() as db:
            row = db.execute("SELECT state,result FROM steps WHERE job=? AND name=?", (ident, name)).fetchone()
        return None if not row else {"state": row[0], "result": json.loads(row[1]) if row[1] is not None else None}

    def start_step(self, ident, name):
        if not isinstance(name, str) or not 0 < len(name) <= 256:
            raise ValueError("Invalid operation step")
        with self.db(True) as db:
            db.execute("INSERT INTO steps(job,name,state) VALUES(?,?,'started') ON CONFLICT(job,name) DO UPDATE SET state='started'",
                       (ident, name))

    def finish_step(self, ident, name, result):
        with self.db(True) as db:
            db.execute("UPDATE steps SET state='done',result=? WHERE job=? AND name=?",
                       (json.dumps(result, allow_nan=False), ident, name))

    def completed_steps(self, ident):
        with self.db() as db:
            return db.execute("SELECT count(*) FROM steps WHERE job=? AND state='done'", (ident,)).fetchone()[0]

    def events(self, actor, admin, after):
        with self.db() as db:
            latest = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
            latest = latest[0] if latest else 0
            oldest = db.execute("SELECT min(id) FROM events WHERE created>=?", (self.clock()-900,)).fetchone()[0]
            reset = after > latest or (after > 0 and after < (oldest or latest+1)-1)
            if reset:
                return {"reset_required": True, "cursor": latest, "items": []}
            rows = db.execute("SELECT * FROM events WHERE id>? AND created>=? ORDER BY id LIMIT 100",
                              (after, self.clock()-900)).fetchall()
        return {"reset_required": False, "cursor": rows[-1]["id"] if rows else max(after, latest),
                "items": [{"id": row["id"], "name": row["name"], "data": json.loads(row["data"])}
                          for row in rows if not row["private"] or admin or row["owner"] == actor]}

    def migrate_legacy(self, library):
        with library.db() as old:
            rows = old.execute("SELECT id,data FROM jobs").fetchall()
        with self.db(True) as db:
            for row in rows:
                if db.execute("SELECT 1 FROM commands WHERE id=?", (row["id"],)).fetchone():
                    continue
                data = json.loads(row["data"])
                data.update(schema_version=1, library_id=self.library_id, params={}, legacy=True,
                            system=data["owner"] == "system", private=data["action"] in ("export", "ingest"),
                            attempt=1, available=0, cancel_requested=False, progress={})
                if data["state"] in {"queued", "running"}:
                    data.update(state="failed", error_code="LEGACY_INTERRUPTED",
                                error="Interrupted legacy operation needs a fresh request", finished=self.clock())
                db.execute("INSERT INTO commands(id,owner,state,available,data) VALUES(?,?,?,?,?)",
                           (data["id"], data["owner"], data["state"], 0, json.dumps(data)))


class JobContext:
    def __init__(self, coordinator, job):
        self.coordinator, self.store, self.job = coordinator, coordinator.store, job
        self.last_progress = (None, 0)

    def checkpoint(self, stage=None, completed=None, total=None):
        current = self.store.get(self.job["id"])
        if current["cancel_requested"]:
            raise Cancelled()
        if self.coordinator.stopping.is_set():
            raise Stopping()
        if not self.coordinator.authorize(current):
            raise PermissionError("Authority revoked before the next operation step")
        if not self.coordinator.available():
            raise Deferred("waiting_for_storage")
        if stage is not None:
            now = time.monotonic()
            if stage != self.last_progress[0] or now-self.last_progress[1] >= .25 or completed == total:
                self.store.update(self.job["id"], progress={"stage": stage, "completed": completed, "total": total})
                self.last_progress = (stage, now)

    def step(self, name, work, recover=None, replay_safe=False):
        previous = self.store.step(self.job["id"], name)
        if previous and previous["state"] == "done":
            return previous["result"]
        if previous:
            outcome = recover() if recover is not None else None
            if outcome and outcome[0]:
                self.store.finish_step(self.job["id"], name, outcome[1])
                return outcome[1]
            if outcome is None and not replay_safe:
                raise ReconciliationRequired("Interrupted step must be reconciled before retry")
        self.checkpoint()
        self.store.start_step(self.job["id"], name)
        token = operation_id.set(self.job["id"] + ":" + name)
        try:
            result = work()
            self.store.finish_step(self.job["id"], name, result)
            return result
        finally:
            operation_id.reset(token)


class JobCoordinator:
    def __init__(self, store, execute, authorize, available):
        self.store, self.execute, self.authorize, self.available = store, execute, authorize, available
        self.stopping = threading.Event()
        self.condition = threading.Condition()
        self.thread = None
        self.started = False

    def enqueue(self, owner, action, params, **options):
        data = self.store.enqueue(owner, action, params, **options)
        if self.started:
            self.wake()
        return data

    def start(self):
        with self.condition:
            if not self.started:
                self.store.recover()
                self.started = True
                self.stopping.clear()
        self.wake()

    def wake(self):
        with self.condition:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._drain, daemon=True, name="photoflow-operations")
                self.thread.start()
            self.condition.notify_all()

    def _drain(self):
        while not self.stopping.is_set():
            if self.run_once():
                continue
            with self.condition:
                with self.store.db() as db:
                    queued = db.execute("SELECT 1 FROM commands WHERE state='queued' LIMIT 1").fetchone()
                if not queued:
                    self.thread = None
                    return
                self.condition.wait(timeout=1)

    def run_once(self):
        job = self.store.claim()
        if not job:
            return False
        context = JobContext(self, job)
        try:
            if job["library_id"] != self.store.library_id:
                raise ValueError("Operation belongs to another library")
            context.checkpoint()
            result = self.execute(job, context)
            self.store.update(job["id"], state="succeeded", result=result, finished=self.store.clock())
        except Cancelled:
            self.store.update(job["id"], state="cancelled", finished=self.store.clock(),
                              result={"completed_steps": self.store.completed_steps(job["id"])})
        except (Deferred, Stopping) as error:
            reason = error.reason if isinstance(error, Deferred) else "service_stopping"
            self.store.update(job["id"], state="queued", waiting_reason=reason, available=self.store.clock()+1)
        except Exception as error:
            code = ("AUTHORITY_REVOKED" if isinstance(error, PermissionError) else
                    "RECONCILIATION_REQUIRED" if isinstance(error, ReconciliationRequired) else
                    "CONFLICT" if isinstance(error, Conflict) else "OPERATION_FAILED")
            safe = str(error)[:2048] if isinstance(error, (ValueError, PermissionError, ReconciliationRequired, OSError)) else "Operation failed; inspect server diagnostics"
            self.store.update(job["id"], state="partial" if self.store.completed_steps(job["id"]) else "failed",
                              error=safe, error_code=code, finished=self.store.clock())
        return True

    def close(self):
        self.stopping.set()
        with self.condition:
            self.condition.notify_all()
            thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
