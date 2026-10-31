import io, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from photoflow_web.core import Library, atomic, load
from photoflow_web.google_downloads import OriginalImporter
from photoflow_web.google_workers import WorkerStore
from photoflow_web.google_reconciliation import ReconciliationReviews


class ReconciliationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "library"
        (self.root / ".photoflow").mkdir(parents=True)
        atomic(self.root / ".photoflow/library.json", {"schema_version": 2, "library_id": "test"})
        self.library = Library(self.root, Path(self.temp.name) / "state")
        self.now = 1000
        self.store = WorkerStore(self.library.state, now=lambda: self.now)
        pair = self.store.pair(self.store.pairing("alice", "google-a")["code"], "google-a")
        self.worker = self.store.authenticate(pair["token"], "google-a")["id"]
        output = io.BytesIO()
        Image.new("RGB", (3, 2), "red").save(output, "PNG")
        self.raw = output.getvalue()
        self.photo = {"namespace": "library-media", "mediaKey": "media-a", "dedupKey": "dedup-a",
                      "favorite": True, "trashTimestamp": None, "companion": False,
                      "filename": "original.png", "size": len(self.raw), "albums": []}
        receipt = OriginalImporter(self.library, lambda url: (self.raw, "image/png")).import_one(
            "alice", "google-a", "download-a", self.photo, "https://lh3.googleusercontent.com/private")
        self.ident = receipt["recordId"]
        self.url = "https://photos.google.com/photo/media-a"
        self.reviews = ReconciliationReviews(self.library, self.store, now=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, urls=None):
        return self.reviews.create("alice", "google-a", urls or [self.url])

    def finish(self, photo=None, error=None):
        job = self.store.claim(self.worker)
        self.assertEqual(job["operation"], "photo-details")
        self.store.finish(self.worker, job["id"], job["lease"],
                          None if error else {"photo": photo or self.photo, "retentionReady": False}, error)
        return job

    def test_selected_reads_form_portable_account_bound_review_without_mutations(self):
        review = self.create()
        self.assertEqual(review["state"], "collecting")
        self.finish()
        report = self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(report["state"], "review-ready")
        self.assertFalse(report["retentionReady"])
        self.assertTrue(report["readOnly"])
        self.assertFalse(report["collectionComplete"])
        item = report["items"][0]
        self.assertEqual(item["remote"]["photo"], self.photo)
        self.assertEqual(item["remote"]["observedAt"], 1000)
        self.assertEqual(item["local"]["state"], "verified-local")
        self.assertEqual(item["localRecords"][0]["recordId"], self.ident)
        self.assertIn("remote-favorite", item["protections"])
        for reason in ["independent-backup-unverified", "takeout-roundtrip-unverified", "current-remote-bytes-unverified", "album-intent-unclassified"]:
            self.assertIn(reason, item["blockedBy"])
        self.assertIsNone(self.store.claim(self.worker))
        persisted = load(self.reviews.path(review["id"]))
        self.assertEqual(persisted["items"][0]["remote"]["photo"], self.photo)
        self.assertEqual(self.reviews.path(review["id"]).stat().st_mode & 0o777, 0o600)

    def test_restart_and_refresh_preserve_observation_time_and_detect_local_changes(self):
        review = self.create()
        self.finish()
        self.reviews.refresh("alice", "google-a", review["id"])
        self.store = WorkerStore(self.library.state, now=lambda: self.now)
        self.reviews = ReconciliationReviews(self.library, self.store, now=lambda: self.now)
        path = self.library.path(self.library.get(self.ident)["file"]["relative_path"])
        path.write_bytes(b"x" * len(self.raw))
        self.now += 20
        result = self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(result["items"][0]["local"]["state"], "local-content-changed")
        self.assertIn("local-original-unverified", result["items"][0]["blockedBy"])
        self.assertEqual(result["items"][0]["remote"]["observedAt"], 1000)
        self.assertIsNone(self.store.claim(self.worker))
        self.now += 601
        self.assertEqual(self.reviews.get("alice", "google-a", review["id"])["state"], "stale")
        self.assertFalse(self.reviews.refresh("alice", "google-a", review["id"])["remoteFresh"])

    def test_partial_failure_and_unknown_fields_remain_explicit(self):
        review = self.create([self.url, "https://photos.google.com/photo/media-b"])
        self.finish()
        partial = self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(partial["state"], "collecting")
        self.assertEqual(partial["summary"]["observed"], 1)
        self.finish(error="SESSION")
        failed = self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(failed["state"], "incomplete")
        self.assertEqual(failed["items"][1]["remote"]["state"], "failed")
        self.assertIsNone(failed["items"][1]["local"])
        self.assertIn("remote-observation-failed", failed["items"][1]["blockedBy"])
        self.assertFalse(failed["retentionReady"])

    def test_unknown_favorite_albums_and_unmapped_photo_are_not_negative_facts(self):
        review = self.create()
        self.finish({**self.photo, "favorite": None, "albums": None, "dedupKey": "changed"})
        result = self.reviews.refresh("alice", "google-a", review["id"])
        item = result["items"][0]
        self.assertEqual(item["local"]["state"], "remote-details-changed")
        self.assertIn("remote-favorite-unknown", item["blockedBy"])
        self.assertIn("remote-albums-unknown", item["blockedBy"])
        self.assertEqual(item["protections"], [])

    def test_targets_owners_accounts_and_library_identity_cannot_be_substituted(self):
        for urls in [[], [self.url] * 2, [self.url] * 21,
                     ["https://photos.google.com/album/a/photo/media-a"], ["https://evil.invalid/photo/media-a"]]:
            with self.assertRaises(ValueError):
                self.reviews.create("alice", "google-a", urls)
        with self.assertRaises(ValueError):
            self.reviews.create("alice", "google-b", [self.url])
        review = self.create()
        for owner, account in [("bob", "google-a"), ("alice", "google-b")]:
            with self.assertRaises(KeyError):
                self.reviews.get(owner, account, review["id"])
        with self.assertRaises(ValueError):
            self.reviews.get("alice", "google-a", "../outside")
        atomic(self.root / ".photoflow/library.json", {"schema_version": 2, "library_id": "different"})
        with self.assertRaises(OSError):
            self.reviews.refresh("alice", "google-a", review["id"])

    def test_crash_before_job_binding_recovers_same_finite_read_jobs(self):
        original = self.store.observation_jobs
        def stop(*args):
            original(*args)
            raise OSError("stopped after enqueue")
        with patch.object(self.store, "observation_jobs", side_effect=stop):
            with self.assertRaises(OSError):
                self.create()
        review = self.reviews.list("alice", "google-a")["items"][0]
        self.reviews.refresh("alice", "google-a", review["id"])
        self.finish()
        self.assertIsNone(self.store.claim(self.worker), "recovery must not duplicate reads")
        result = self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(result["state"], "review-ready")

    def test_completed_portable_observation_survives_worker_database_loss(self):
        review = self.create()
        self.finish()
        self.reviews.refresh("alice", "google-a", review["id"])
        self.store.path.unlink()
        self.store = WorkerStore(self.library.state, now=lambda: self.now)
        self.reviews = ReconciliationReviews(self.library, self.store, now=lambda: self.now)
        # Class can inspect portable evidence; HTTP still requires a matching paired account.
        result = self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(result["items"][0]["local"]["state"], "verified-local")
        self.assertEqual(result["items"][0]["remote"]["photo"], self.photo)

    def test_pending_job_loss_is_unavailable_and_does_not_enqueue_a_replacement(self):
        review = self.create()
        self.store.path.unlink()
        self.store = WorkerStore(self.library.state, now=lambda: self.now)
        self.reviews = ReconciliationReviews(self.library, self.store, now=lambda: self.now)
        result = self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual(result["items"][0]["remote"]["state"], "unavailable")
        self.assertIsNone(result["items"][0]["local"])
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_hash_budget_defers_local_proof_without_changing_remote_evidence(self):
        review = self.create()
        self.finish()
        self.reviews.matches.byte_budget = 1
        result = self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(result["items"][0]["local"]["state"], "verification-deferred")
        self.assertEqual(result["summary"]["localVerified"], 0)
        self.assertFalse(result["retentionReady"])
        self.assertIn("local-original-unverified", result["items"][0]["blockedBy"])

    def test_misbound_worker_result_cannot_become_observation_evidence(self):
        review = self.create()
        self.finish()
        with self.store.db() as db:
            db.execute("UPDATE jobs SET account='google-b'")
        with self.assertRaises(ValueError):
            self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(load(self.reviews.path(review["id"]))["items"], [])

    def test_changed_local_revision_between_verification_and_review_publication_stops(self):
        review = self.create()
        self.finish()
        original = self.reviews.matches.check
        def changed(*args):
            result = original(*args)
            record = self.library.get(self.ident)
            from photoflow.model import SIDECAR
            path = self.library.path(record["file"]["relative_path"] + SIDECAR)
            record.pop("revision")
            record["resolved"]["title"] = "changed after hashing"
            atomic(path, record)
            self.library.put_index(record, path)
            return result
        with patch.object(self.reviews.matches, "check", side_effect=changed):
            with self.assertRaises(ValueError):
                self.reviews.refresh("alice", "google-a", review["id"])
        self.assertEqual(load(self.reviews.path(review["id"]))["items"], [])


class ReconciliationHTTPTests(unittest.TestCase):
    def test_default_app_wires_private_account_bound_csrf_protected_review_reads(self):
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "library"
            (root / ".photoflow").mkdir(parents=True)
            atomic(root / ".photoflow/library.json", {"schema_version": 2, "library_id": "test"})
            roles = {"alice": 3, "bob": 3}
            app = create_app(root, Path(temp) / "state", auth=lambda d: {"ok": True, "uid": 123}, role_resolver=lambda n: roles[n])
            endpoint = "/api/v1/google/reconciliation/reviews"
            body = {"account": "google-a", "photoUrls": ["https://photos.google.com/photo/media-a"]}
            store = app.state.google_workers
            paired = store.pair(store.pairing("alice", "google-a")["code"], "google-a")
            with TestClient(app, base_url="https://testserver") as client:
                self.assertEqual(client.post(endpoint, json=body).status_code, 401)
                response = client.post("/api/v1/auth/login", headers={"Origin": "https://testserver"}, json={"username": "alice", "password": "secret"})
                headers = {"Origin": "https://testserver", "X-CSRF-Token": response.json()["csrf"]}
                self.assertEqual(client.post(endpoint, json=body).status_code, 403)
                self.assertEqual(client.post(endpoint, json={**body, "account": "wrong"}, headers=headers).status_code, 409)
                response = client.post(endpoint, json=body, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                review = response.json()
                self.assertFalse(review["retentionReady"])
                target = endpoint + "/" + review["id"]
                self.assertEqual(client.get(target, params={"account": "google-a"}).status_code, 200)
                response = client.get(endpoint, params={"account": "google-a"})
                self.assertEqual(response.json()["items"][0]["id"], review["id"])
                self.assertEqual(client.post(target + "/refresh", json={"account": "google-a"}).status_code, 403)
                response = client.post(target + "/refresh", json={"account": "google-a"}, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["state"], "collecting")
                roles["alice"] = 1
                self.assertEqual(client.get(target, params={"account": "google-a"}).status_code, 403)
                roles["alice"] = 3
                store.revoke("alice")
                self.assertEqual(client.get(target, params={"account": "google-a"}).status_code, 409)
                store.pair(store.pairing("bob", "google-a")["code"], "google-a")
                response = client.post("/api/v1/auth/login", headers={"Origin": "https://testserver"}, json={"username": "bob", "password": "secret"})
                self.assertEqual(client.get(target, params={"account": "google-a"}).status_code, 404)
