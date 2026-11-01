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

    def worker_auth(self):
        store = self.app.state.google_workers
        pair = store.pair(store.pairing("alice", "google-a")["code"], "google-a")
        return {
            "type": "auth",
            "token": pair["token"],
            "account": "google-a",
            "protocol": JOB_PROTOCOL_VERSION,
            "capabilities": [
                {"operation": name, "version": spec["version"]}
                for name, spec in JOB_SPECS.items()
            ],
        }

    def test_idle_transport_close_preserves_pairing_and_allows_reconnection(self):
        import asyncio
        from unittest.mock import patch
        from starlette.websockets import WebSocketDisconnect

        auth = self.worker_auth()
        original = asyncio.wait

        async def idle(tasks, **kwargs):
            if kwargs.get("timeout") == 45:
                return set(), set(tasks)
            return await original(tasks, **kwargs)

        with patch("photoflow_web.google_workers.asyncio.wait", idle):
            with self.client.websocket_connect(
                "/api/v1/google/worker", headers={"Origin": self.extension}
            ) as ws:
                ws.send_json(auth)
                self.assertEqual(ws.receive_json()["type"], "welcome")
                with self.assertRaises(WebSocketDisconnect) as stopped:
                    ws.receive_json()
                self.assertEqual(stopped.exception.code, 1001)
        self.assertEqual(
            self.app.state.google_workers.authenticate(auth["token"], "google-a")[
                "owner"
            ],
            "alice",
        )
        with self.client.websocket_connect(
            "/api/v1/google/worker", headers={"Origin": self.extension}
        ) as ws:
            ws.send_json(auth)
            self.assertEqual(ws.receive_json()["type"], "welcome")

    def test_disconnected_peer_is_not_closed_again_or_reported_as_bad_pairing(self):
        from unittest.mock import patch, AsyncMock
        from threading import Event

        disconnected = Event()
        store = self.app.state.google_workers
        original = store.disconnect

        def disconnect(ident):
            original(ident)
            disconnected.set()

        with (
            patch.object(store, "disconnect", disconnect),
            patch(
                "starlette.websockets.WebSocket.close", new_callable=AsyncMock
            ) as close,
        ):
            with self.client.websocket_connect(
                "/api/v1/google/worker", headers={"Origin": self.extension}
            ) as ws:
                ws.send_json(self.worker_auth())
                self.assertEqual(ws.receive_json()["type"], "welcome")
                ws.send({"type": "websocket.disconnect", "code": 1006})
                self.assertTrue(disconnected.wait(timeout=2))
            close.assert_not_awaited()

    def test_invalid_worker_protocol_still_closes_with_policy_error(self):
        from starlette.websockets import WebSocketDisconnect

        auth = self.worker_auth()
        auth["protocol"] = 0
        with self.client.websocket_connect(
            "/api/v1/google/worker", headers={"Origin": self.extension}
        ) as ws:
            ws.send_json(auth)
            with self.assertRaises(WebSocketDisconnect) as stopped:
                ws.receive_json()
            self.assertEqual(stopped.exception.code, 1008)

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


class StableWorkerRequestTests(unittest.TestCase):
    def test_request_key_survives_completion_and_cannot_describe_another_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkerStore(directory)
            pair = store.pair(store.pairing("alice", "a")["code"], "a")
            first = store.enqueue_once(
                "alice", "manifest:operation", "storage-quota", {}
            )
            claimed = store.claim(pair["worker_id"])
            result = {"used": 1, "total": 100, "photosUsed": 1, "retentionReady": False}
            store.finish(pair["worker_id"], claimed["id"], claimed["lease"], result)
            self.assertEqual(
                store.enqueue_once("alice", "manifest:operation", "storage-quota", {})[
                    "id"
                ],
                first["id"],
            )
            with self.assertRaises(ValueError):
                store.enqueue_once("alice", "manifest:operation", "library-page", {})


class ManifestDeadlineTests(unittest.TestCase):
    def test_an_expired_queued_manifest_cannot_dispatch_a_write_later(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000]
            store = WorkerStore(
                directory,
                now=lambda: now[0],
                pilot_account="a",
                target_policy="selected",
            )
            worker = store.pair(store.pairing("alice", "a")["code"], "a")
            job = store.enqueue_once(
                "alice",
                "manifest:cleanup",
                "trash",
                {"photoUrl": "https://photos.google.com/photo/a"},
                True,
                not_after=1001,
            )
            now[0] = 1002
            self.assertIsNone(store.claim(worker["worker_id"]))
            self.assertEqual(
                store.diagnostic("alice", job["id"])["job"]["state"], "blocked"
            )
            self.assertEqual(
                store.diagnostic("alice", job["id"])["job"]["error"], "EXPIRED"
            )


class ManifestReadRepairTests(unittest.TestCase):
    def test_same_account_repair_can_resume_a_read_but_never_an_old_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkerStore(directory, pilot_account="a", target_policy="selected")
            first = store.pair(store.pairing("alice", "a")["code"], "a")
            read = store.enqueue_once("alice", "read-key", "library-page", {})
            write = store.enqueue_once(
                "alice",
                "write-key",
                "trash",
                {"photoUrl": "https://photos.google.com/photo/a"},
                True,
            )
            second = store.pair(store.pairing("alice", "a")["code"], "a")
            resumed = store.enqueue_once("alice", "read-key", "library-page", {})
            self.assertEqual(resumed["id"], read["id"])
            self.assertEqual(resumed["state"], "queued")
            self.assertEqual(store.claim(second["worker_id"])["id"], read["id"])
            self.assertEqual(
                store.enqueue_once(
                    "alice",
                    "write-key",
                    "trash",
                    {"photoUrl": "https://photos.google.com/photo/a"},
                    True,
                )["state"],
                "failed",
            )


class TakeoutAuthorityTests(unittest.TestCase):
    def test_takeout_scope_is_distinct_target_bound_and_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkerStore(
                directory, pilot_account="a", target_policy="selected", now=lambda: 1000
            )
            worker = store.pair(store.pairing("alice", "a")["code"], "a")
            scope = {
                "purpose": "owner-authorized-takeout-retention",
                "manifestId": "b" * 32,
                "manifestSha256": "c" * 64,
                "localSha256": "d" * 64,
                "dedupKey": "dedup-a",
                "photoKey": "media-a",
            }
            job = store.enqueue_once(
                "alice",
                "sweep:1",
                "trash",
                {"photoUrl": "https://photos.google.com/photo/media-a"},
                True,
                not_after=2000,
                retention_scope=scope,
            )
            store.retention_check = lambda owner, account, scope: True
            claimed = store.claim(worker["worker_id"])
            self.assertNotIn("testScope", claimed)
            self.assertEqual(claimed["retentionScope"]["photoKey"], "media-a")
            self.assertEqual(claimed["retentionScope"]["jobId"], job["id"])
            with self.assertRaises(ValueError):
                store.enqueue_once(
                    "alice",
                    "sweep:1",
                    "trash",
                    {"photoUrl": "https://photos.google.com/photo/media-a"},
                    True,
                    not_after=2000,
                    retention_scope={**scope, "localSha256": "e" * 64},
                )
            with self.assertRaises(ValueError):
                store.enqueue_once(
                    "alice",
                    "sweep:2",
                    "trash",
                    {"photoUrl": "https://photos.google.com/photo/other"},
                    True,
                    retention_scope=scope,
                )

    def test_missing_current_local_authority_blocks_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkerStore(
                directory, pilot_account="a", target_policy="selected", now=lambda: 1000
            )
            worker = store.pair(store.pairing("alice", "a")["code"], "a")
            scope = {
                "purpose": "owner-authorized-takeout-retention",
                "manifestId": "b" * 32,
                "manifestSha256": "c" * 64,
                "localSha256": "d" * 64,
                "dedupKey": "dedup-a",
                "photoKey": "media-a",
            }
            job = store.enqueue_once(
                "alice",
                "sweep:1",
                "trash",
                {"photoUrl": "https://photos.google.com/photo/media-a"},
                True,
                not_after=2000,
                retention_scope=scope,
            )
            self.assertIsNone(store.claim(worker["worker_id"]))
            self.assertEqual(
                store.diagnostic("alice", job["id"])["job"]["state"], "blocked"
            )


class RetentionPreflightRetryTests(unittest.TestCase):
    def test_explicit_preflight_retry_keeps_same_intent_and_archives_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkerStore(
                directory, pilot_account="a", target_policy="selected", now=lambda: 1000
            )
            store.retention_check = lambda *args: True
            worker = store.pair(store.pairing("alice", "a")["code"], "a")
            scope = {
                "purpose": "owner-authorized-takeout-retention",
                "manifestId": "b" * 32,
                "manifestSha256": "c" * 64,
                "localSha256": "d" * 64,
                "dedupKey": "dedup-a",
                "photoKey": "media-a",
            }
            job = store.enqueue_once(
                "alice",
                "sweep:1",
                "trash",
                {"photoUrl": "https://photos.google.com/photo/media-a"},
                True,
                not_after=2000,
                retention_scope=scope,
            )
            claim = store.claim(worker["worker_id"])
            store.progress(worker["worker_id"], job["id"], claim["lease"], "preflight")
            store.finish(
                worker["worker_id"], job["id"], claim["lease"], error="PROTOCOL"
            )
            self.assertTrue(
                store.diagnostic("alice", job["id"])["job"]["retry_preflight_allowed"]
            )
            with self.assertRaises(ValueError):
                store.retry_preflight("bob", job["id"])
            store.retry_preflight("alice", job["id"])
            again = store.claim(worker["worker_id"])
            self.assertEqual(again["id"], job["id"])
            self.assertEqual(again["attempt"], 2)
            self.assertNotEqual(again["lease"], claim["lease"])
            with store.db() as db:
                self.assertEqual(
                    db.execute(
                        "SELECT error FROM preflight_retries WHERE job=?", (job["id"],)
                    ).fetchone()[0],
                    "PROTOCOL",
                )
            store.progress(worker["worker_id"], job["id"], again["lease"], "sending")
            store.finish(
                worker["worker_id"], job["id"], again["lease"], error="PROTOCOL"
            )
            self.assertFalse(
                store.diagnostic("alice", job["id"])["job"]["retry_preflight_allowed"]
            )
            with self.assertRaises(ValueError):
                store.retry_preflight("alice", job["id"])

    def test_unknown_album_title_preserves_positive_membership_contract(self):
        from photoflow_web.google_contracts import album

        album(
            {
                "namespace": "album",
                "albumId": "shared-a",
                "title": None,
                "itemCount": 3,
                "shared": True,
            }
        )
        with self.assertRaises(ValueError):
            album(
                {
                    "namespace": "album",
                    "albumId": "shared-a",
                    "title": 12,
                    "itemCount": 3,
                    "shared": True,
                }
            )


class EventualRetentionTests(unittest.TestCase):
    def test_fresh_scoped_retention_pass_can_dispatch_with_old_unknown_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkerStore(
                directory, pilot_account="a", target_policy="selected", now=lambda: 1000
            )
            store.retention_check = lambda *args: True
            worker = store.pair(store.pairing("alice", "a")["code"], "a")
            scope = {
                "purpose": "owner-authorized-takeout-retention",
                "manifestId": "b" * 32,
                "manifestSha256": "c" * 64,
                "localSha256": "d" * 64,
                "dedupKey": "dedup-a",
                "photoKey": "media-a",
            }

            def enqueue(key, evidence):
                return store.enqueue_once(
                    "alice",
                    key,
                    "trash",
                    {"photoUrl": "https://photos.google.com/photo/media-a"},
                    True,
                    not_after=2000,
                    retention_scope=evidence,
                )

            old = enqueue("old-pass", scope)
            claimed = store.claim(worker["worker_id"])
            store.finish(
                worker["worker_id"],
                old["id"],
                claimed["lease"],
                error="UNKNOWN_OUTCOME",
            )
            with self.assertRaises(ValueError):
                store.enqueue(
                    "alice",
                    "trash",
                    {"photoUrl": "https://photos.google.com/photo/media-a"},
                    True,
                )
            fresh = enqueue("fresh-pass", {**scope, "manifestId": "e" * 32})
            self.assertEqual(store.claim(worker["worker_id"])["id"], fresh["id"])
            self.assertEqual(
                store.diagnostic("alice", old["id"])["job"]["state"], "unknown"
            )
