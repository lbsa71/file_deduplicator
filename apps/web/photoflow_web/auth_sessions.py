"""Private, restart-safe web sessions. Passwords and raw bearer tokens are not stored."""

import hashlib, json, os, sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

IDLE_SECONDS = 1800
MAX_SECONDS = 43200


class SessionStore:
    def __init__(self, directory, clock):
        self.directory, self.clock = Path(directory), clock
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_mode & 0o077:
            raise ValueError("Session directory must be private")
        self.path = self.directory / "sessions.sqlite"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_mode & 0o077:
                raise ValueError("Session database must be private")
        finally:
            os.close(fd)
        self.checked_here = set()
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (key TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL, last REAL NOT NULL)")

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            with db:
                yield db

    def key(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 256:
            return None
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token, default=None):
        key = self.key(token)
        if key is None:
            return default
        with self.db() as db:
            row = db.execute("SELECT data,created,last FROM sessions WHERE key=?", (key,)).fetchone()
            if not row:
                return default
            now = self.clock()
            if now - row[1] > MAX_SECONDS or now - row[2] > IDLE_SECONDS:
                db.execute("DELETE FROM sessions WHERE key=?", (key,))
                self.checked_here.discard(key)
                return default
        data = json.loads(row[0])
        if key not in self.checked_here:
            # Revalidate a persisted session against the account broker before
            # trusting it in this process, even immediately after a restart.
            data["checked"] = 0
        return data

    def validate(self, token, data):
        key = self.key(token)
        if key is None or set(data) != {"username", "uid", "role", "csrf", "last", "created", "checked"}:
            raise ValueError("Invalid session state")
        return key

    def create(self, token, data):
        key = self.validate(token, data)
        now = self.clock()
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE created<? OR last<?", (now - MAX_SECONDS, now - IDLE_SECONDS))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (key, json.dumps(data), data["created"], data["last"]))
        self.checked_here.add(key)

    def touch(self, token, data):
        key = self.validate(token, data)
        now = self.clock()
        with self.db() as db:
            updated = db.execute(
                "UPDATE sessions SET data=?,last=? WHERE key=? AND created=? AND created>=? AND last>=?",
                (json.dumps(data), data["last"], key, data["created"], now - MAX_SECONDS, now - IDLE_SECONDS),
            ).rowcount
        if updated:
            self.checked_here.add(key)
        return updated == 1

    def pop(self, token, default=None):
        key = self.key(token)
        if key is not None:
            with self.db() as db:
                db.execute("DELETE FROM sessions WHERE key=?", (key,))
            self.checked_here.discard(key)
        return default
