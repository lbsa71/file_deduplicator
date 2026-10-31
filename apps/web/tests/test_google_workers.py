import tempfile, unittest
from pathlib import Path
from photoflow_web.google_workers import WorkerStore, JOB_PROTOCOL_VERSION, JOB_SPECS


class WorkerStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000
        self.store = WorkerStore(Path(self.tmp.name), now=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def pair(self):
        pending = self.store.pairing("alice", "google-a")
        return self.store.pair(pending["code"], "google-a")

    def test_pairing_is_single_use_expiring_and_account_bound(self):
        pending = self.store.pairing("alice", "google-a")
        with self.assertRaises(ValueError):
            self.store.pair(pending["code"], "wrong")
        paired = self.store.pair(pending["code"], "google-a")
        self.assertEqual(
            self.store.authenticate(paired["token"], "google-a")["owner"], "alice"
        )
        with self.assertRaises(ValueError):
            self.store.pair(pending["code"], "google-a")
        self.now += 301
        pending = self.store.pairing("bob", "google-b")
        self.now += 301
        with self.assertRaises(ValueError):
            self.store.pair(pending["code"], "google-b")

    def test_read_jobs_survive_restart_and_stale_results_cannot_complete(self):
        paired = self.pair()
        w = self.store.authenticate(paired["token"], "google-a")
        job = self.store.enqueue("alice")
        claimed = self.store.claim(w["id"])
        self.assertEqual(claimed["id"], job["id"])
        self.assertIsNone(self.store.claim(w["id"]))
        restarted = WorkerStore(Path(self.tmp.name), now=lambda: self.now)
        again = restarted.claim(w["id"])
        self.assertNotEqual(claimed["lease"], again["lease"])
        result = {
            "photos": 11,
            "favorites": 2,
            "albums": 1,
            "complete": True,
            "retentionReady": False,
        }
        with self.assertRaises(ValueError):
            restarted.finish(w["id"], job["id"], claimed["lease"], result)
        restarted.finish(w["id"], job["id"], again["lease"], result)
        self.assertEqual(restarted.status("alice")["jobs"][0]["result"], result)

    def test_unvalidated_results_and_revoked_workers_cannot_complete(self):
        paired = self.pair()
        w = self.store.authenticate(paired["token"], "google-a")
        self.store.enqueue("alice")
        job = self.store.claim(w["id"])
        for bad in [
            {"complete": True},
            {
                "photos": 1,
                "favorites": 2,
                "albums": 0,
                "complete": True,
                "retentionReady": False,
            },
        ]:
            with self.assertRaises(ValueError):
                self.store.finish(w["id"], job["id"], job["lease"], bad)
        self.store.revoke("alice")
        with self.assertRaises(ValueError):
            self.store.authenticate(paired["token"], "google-a")
        self.assertEqual(self.store.status("alice")["state"], "unpaired")

    def test_queue_is_owner_bound_deduplicated_and_expired_results_rejected(self):
        p = self.pair()
        w = self.store.authenticate(p["token"], "google-a")
        first = self.store.enqueue("alice")
        self.assertEqual(self.store.enqueue("alice")["id"], first["id"])
        with self.assertRaises(ValueError):
            self.store.enqueue("bob")
        job = self.store.claim(w["id"])
        self.now += 601
        with self.assertRaises(ValueError):
            self.store.finish(
                w["id"],
                job["id"],
                job["lease"],
                {
                    "photos": 1,
                    "favorites": 0,
                    "albums": 0,
                    "complete": True,
                    "retentionReady": False,
                },
            )


class WorkerHTTPTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app

        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / ".photoflow").mkdir()
        (root / ".photoflow/library.json").write_text(
            '{"schema_version":2,"library_id":"test"}'
        )
        self.app = create_app(
            root,
            root / "state",
            auth=lambda d: {"ok": True, "uid": 123},
            role_resolver=lambda n: 3,
        )
        self.client = TestClient(self.app, base_url="https://testserver")
        response = self.client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://testserver"},
            json={"username": "alice", "password": "secret"},
        )
        self.headers = {
            "Origin": "https://testserver",
            "X-CSRF-Token": response.json()["csrf"],
        }
        self.extension = "chrome-extension://" + "a" * 32

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_pair_requires_csrf_and_worker_session_requires_extension_origin(self):
        from starlette.websockets import WebSocketDisconnect

        self.assertEqual(
            self.client.post(
                "/api/v1/google/pairing", json={"account": "google-a"}
            ).status_code,
            403,
        )
        pending = self.client.post(
            "/api/v1/google/pairing", headers=self.headers, json={"account": "google-a"}
        ).json()
        self.assertEqual(
            self.client.post(
                "/api/v1/google/pair",
                headers={"Origin": "https://evil.invalid"},
                json={"code": pending["code"], "account": "google-a"},
            ).status_code,
            403,
        )
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/v1/google/worker", headers={"Origin": "https://evil.invalid"}
            ):
                pass

    def test_websocket_dispatches_persisted_read_job_and_rejects_stale_completion(self):
        pending = self.client.post(
            "/api/v1/google/pairing", headers=self.headers, json={"account": "google-a"}
        ).json()
        pair = self.client.post(
            "/api/v1/google/pair",
            headers={"Origin": self.extension},
            json={"code": pending["code"], "account": "google-a"},
        ).json()
        with self.client.websocket_connect(
            "/api/v1/google/worker", headers={"Origin": self.extension}
        ) as ws:
            ws.send_json(
                {
                    "type": "auth",
                    "token": pair["token"],
                    "account": "google-a",
                    "protocol": JOB_PROTOCOL_VERSION,
                    "capabilities": [
                        {"operation": name, "version": spec["version"]}
                        for name, spec in JOB_SPECS.items()
                    ],
                }
            )
            self.assertEqual(ws.receive_json()["type"], "welcome")
            job = ws.receive_json()
            self.assertEqual(job["operation"], "inventory-counts")
            result = {
                "photos": 11431,
                "favorites": 277,
                "albums": 15,
                "complete": True,
                "retentionReady": False,
            }
            ws.send_json(
                {
                    "type": "result",
                    "id": job["id"],
                    "lease": job["lease"],
                    "result": result,
                }
            )
            self.assertEqual(ws.receive_json()["type"], "receipt")
            ws.send_json({"type": "heartbeat", "account": "google-a", "ready": True})
            self.assertEqual(ws.receive_json()["type"], "heartbeat")
            status = self.client.get("/api/v1/google/status").json()
            self.assertEqual(status["state"], "connected")
            self.assertEqual(status["jobs"][0]["result"], result)
            queued = self.client.post(
                "/api/v1/google/jobs", headers=self.headers, json={}
            ).json()
            second = ws.receive_json()
            self.assertEqual(second["id"], queued["id"])
        status = self.client.get("/api/v1/google/status").json()
        self.assertEqual(status["state"], "offline")
        self.assertEqual(status["jobs"][0]["state"], "queued")

    def test_progress_is_owner_scoped_and_new_attempt_can_start_from_checking(self):
        paired = self.app.state.google_workers.pairing("alice", "google-a")
        token = self.app.state.google_workers.pair(paired["code"], "google-a")
        store = self.app.state.google_workers
        worker = store.authenticate(token["token"], "google-a")
        store.enqueue("alice")
        first = store.claim(worker["id"])
        store.progress(worker["id"], first["id"], first["lease"], "albums")
        with self.assertRaises(ValueError):
            store.progress(worker["id"], first["id"], first["lease"], "library")
        store.disconnect(worker["id"])
        again = store.claim(worker["id"])
        store.progress(worker["id"], again["id"], again["lease"], "checking")
        report = store.diagnostic("alice", again["id"])
        self.assertEqual(report["job"]["attempt"], 2)
        self.assertEqual(report["job"]["events"][-1]["phase"], "checking")
        with self.assertRaises(ValueError):
            store.diagnostic("bob", again["id"])

    def test_effect_classification_blocks_replay_of_uncertain_future_write(self):
        from photoflow_web.google_workers import JOB_SPECS

        store = self.app.state.google_workers
        code = store.pairing("alice", "google-a")
        paired = store.pair(code["code"], "google-a")
        w = store.authenticate(paired["token"], "google-a")
        store.enqueue("alice")
        store.claim(w["id"])
        old = JOB_SPECS["inventory-counts"]["effect"]
        try:
            JOB_SPECS["inventory-counts"]["effect"] = "write"
            store.disconnect(w["id"])
            self.assertEqual(store.status("alice")["jobs"][0]["state"], "unknown")
            with self.assertRaises(ValueError):
                store.enqueue("alice")
        finally:
            JOB_SPECS["inventory-counts"]["effect"] = old

    def test_repair_preserves_job_account_attribution_without_exporting_account(self):
        store = self.app.state.google_workers
        code = store.pairing("alice", "private-google-a")
        paired = store.pair(code["code"], "private-google-a")
        job = store.enqueue("alice")
        original = store.diagnostic("alice", job["id"])["job"]["account_ref"]
        self.assertTrue(original)
        code = store.pairing("alice", "private-google-b")
        store.pair(code["code"], "private-google-b")
        report = store.diagnostic("alice", job["id"])
        self.assertEqual(report["job"]["account_ref"], original)
        import json

        self.assertNotIn("private-google-a", json.dumps(report))
