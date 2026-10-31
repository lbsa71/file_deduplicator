import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from photoflow_web.app import create_app


class SessionPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "library"
        (self.root / ".photoflow").mkdir(parents=True)
        (self.root / ".photoflow/library.json").write_text('{"schema_version":2,"library_id":"test"}')
        self.state = Path(self.temp.name) / "state"
        self.now = 1700000000
        self.account_valid = True
        self.calls = []
        self.clock = patch("photoflow_web.app.time.time", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def auth(self, request):
        self.calls.append(request.copy())
        return {"ok": self.account_valid, "uid": 123}

    def client(self):
        return TestClient(create_app(self.root, self.state, auth=self.auth, role_resolver=lambda name: 3), base_url="https://testserver")

    def login(self, client):
        response = client.post("/api/v1/auth/login", headers={"Origin": "https://testserver"},
                               json={"username": "alice", "password": "synthetic-password"})
        self.assertEqual(response.status_code, 200)
        return response.json()["csrf"]

    def test_restart_preserves_login_and_csrf_but_rechecks_account_and_logout_is_durable(self):
        with self.client() as first:
            csrf = self.login(first)
            cookies = dict(first.cookies)
        self.now += 1
        with self.client() as restarted:
            restarted.cookies.update(cookies)
            response = restarted.get("/api/v1/auth/session")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["csrf"], csrf)
            self.assertEqual(self.calls[-1], {"username": "alice", "uid": 123})
            self.assertEqual(restarted.post("/api/v1/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf}).status_code, 204)
        with self.client() as again:
            again.cookies.update(cookies)
            self.assertEqual(again.get("/api/v1/auth/session").status_code, 401)

    def test_restart_does_not_extend_idle_or_absolute_expiry(self):
        with self.client() as client:
            self.login(client)
            cookies = dict(client.cookies)
        self.now += 1801
        with self.client() as restarted:
            restarted.cookies.update(cookies)
            self.assertEqual(restarted.get("/api/v1/auth/session").status_code, 401)
            self.login(restarted)
            for _ in range(44):
                self.now += 1000
                response = restarted.get("/api/v1/auth/session")
            self.assertEqual(response.status_code, 401)

    def test_account_revocation_after_restart_rejects_persisted_session(self):
        with self.client() as client:
            self.login(client)
            cookies = dict(client.cookies)
        self.now += 1
        self.account_valid = False
        with self.client() as restarted:
            restarted.cookies.update(cookies)
            self.assertEqual(restarted.get("/api/v1/auth/session").status_code, 401)

    def test_private_store_contains_no_password_or_raw_session_token(self):
        with self.client() as client:
            self.login(client)
            token = client.cookies.get("__Host-photoflow")
        directory = self.state / "auth-sessions"
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        for path in directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            data = path.read_bytes()
            self.assertNotIn(token.encode(), data)
            self.assertNotIn(b"synthetic-password", data)

    def test_inflight_request_cannot_recreate_a_logged_out_session(self):
        from photoflow_web.auth_sessions import SessionStore
        with self.client() as client:
            self.login(client)
            token = client.cookies.get("__Host-photoflow")
        store = SessionStore(self.state / "auth-sessions", clock=lambda: self.now)
        in_flight = store.get(token)
        store.pop(token)
        self.assertFalse(store.touch(token, in_flight))
        self.assertIsNone(SessionStore(self.state / "auth-sessions", clock=lambda: self.now).get(token))
