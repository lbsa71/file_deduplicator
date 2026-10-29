"""Debounced reconciliation; events remain hints backed by periodic inventory."""

import json
import threading
import time
from pathlib import Path
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class Reconciler(FileSystemEventHandler):
    def __init__(self, library, submit):
        self.library = library
        self.submit = submit
        self.changed = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.last_scan = time.monotonic()
        self.active = None
        self.observer = Observer()
        self.observer.schedule(self, str(library.root), recursive=True)

    def on_any_event(self, event):
        if (
            event.event_type not in ("modified", "created", "deleted", "moved")
            or event.is_directory
        ):
            return
        for candidate in (event.src_path, getattr(event, "dest_path", None)):
            if not candidate:
                continue
            path = Path(candidate)
            try:
                relative = str(path.relative_to(self.library.root))
            except ValueError:
                continue
            if relative.startswith(".photoflow/") or "/.takeout-extract/" in relative:
                continue
            with self.lock:
                self.changed[relative] = time.monotonic()

    def meaningful(self, path):
        p = self.library.path(path)
        if path.endswith(".photo.json"):
            with self.library.db() as db:
                row = db.execute(
                    "SELECT stamp FROM photos WHERE path=?", (path[:-11],)
                ).fetchone()
            if not p.exists():
                return row is not None
            if row:
                stat = p.stat()
                return row[0] != str(stat.st_mtime_ns) + ":" + str(stat.st_size)
        elif not path.endswith(".json"):
            with self.library.db() as db:
                row = db.execute(
                    "SELECT data FROM photos WHERE path=?", (path,)
                ).fetchone()
            if not p.exists():
                return row is not None
            if row:
                signature = json.loads(row[0])["file"].get("fingerprint")
                return signature != self.library.fs.stat(path).to_dict()
        return True

    def start(self):
        self.observer.start()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.observer.stop()
        self.observer.join()
        self.thread.join(timeout=3)

    def run(self):
        while not self.stop.wait(2):
            try:
                if self.active:
                    with self.library.db() as db:
                        state = db.execute(
                            "SELECT state FROM jobs WHERE id=?", (self.active,)
                        ).fetchone()
                    if state and state[0] in ("queued", "running"):
                        continue
                    self.active = None
                now = time.monotonic()
                with self.lock:
                    ready = bool(self.changed) and (
                        now - max(self.changed.values()) >= 60
                        or now - min(self.changed.values()) >= 300
                    )
                    paths = list(self.changed) if ready else []
                    if ready:
                        self.changed.clear()
                if (
                    ready and any(self.meaningful(p) for p in paths)
                ) or now - self.last_scan >= 86400:
                    response = self.submit()
                    self.active = json.loads(response.body)["job_id"]
                    self.last_scan = now
            except Exception:
                # A periodic full inventory remains due after a watcher/volume failure.
                self.last_scan = 0
