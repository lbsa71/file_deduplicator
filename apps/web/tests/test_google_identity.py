import io, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from photoflow.model import SIDECAR
from photoflow_web.core import Library, atomic
from photoflow_web.google_downloads import OriginalImporter
from photoflow_web.google_identity import LocalGoogleMatches


class LocalGoogleMatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / "library"
        (root / ".photoflow").mkdir(parents=True)
        atomic(root / ".photoflow/library.json", {"schema_version": 2, "library_id": "test"})
        self.library = Library(root, Path(self.temp.name) / "state")
        image = io.BytesIO()
        Image.new("RGB", (3, 2), "red").save(image, "PNG")
        self.raw = image.getvalue()
        self.photo = {"mediaKey": "media-a", "dedupKey": "dedup-a", "filename": "original.png", "size": len(self.raw)}
        receipt = OriginalImporter(self.library, lambda url: (self.raw, "image/png")).import_one(
            "alice", "google-a", "job-a", self.photo, "https://lh3.googleusercontent.com/private")
        self.ident = receipt["recordId"]
        self.record = self.library.get(self.ident)
        self.path = self.library.path(self.record["file"]["relative_path"])
        self.sidecar = self.path.with_name(self.path.name + SIDECAR)
        self.matches = LocalGoogleMatches(self.library)
        self.target = {"namespace": "library-media", "mediaKey": "media-a"}

    def tearDown(self):
        self.temp.cleanup()

    def check(self, account="google-a", **target):
        result = self.matches.check(account, [{**self.target, **target}])
        self.assertFalse(result["retentionReady"])
        self.assertFalse(result["absenceProven"])
        self.assertIsNone(result["remoteBytesEqual"])
        return result["items"][0]

    def test_checks_account_bound_bytes_without_walking_the_library(self):
        with patch("os.walk", side_effect=AssertionError("must use identity index")), patch.object(self.library.fs, "list_files", side_effect=AssertionError("must not scan")):
            result = self.check()
            self.assertEqual(result["state"], "verified-local")
            self.assertEqual(result["recordIds"], [self.ident])
            self.assertEqual(self.check("google-b")["state"], "unmapped")
            self.assertEqual(self.check(mediaKey="unknown")["state"], "unmapped")

    def test_byte_changes_and_stale_sidecars_do_not_verify(self):
        self.path.write_bytes(b"x" * len(self.raw))
        self.assertEqual(self.check()["state"], "local-content-changed")
        self.path.write_bytes(self.raw)
        record = json.loads(self.sidecar.read_bytes())
        record["google_originals"] = []
        atomic(self.sidecar, record)
        self.assertEqual(self.check()["state"], "stale-local-metadata")
        self.library.rebuild()
        self.assertEqual(self.check()["state"], "unmapped")

    def test_trash_is_distinct_from_an_active_original_and_restore_rechecks_bytes(self):
        self.library.trash(self.ident, self.record["revision"], "alice")
        self.assertEqual(self.check()["state"], "local-trash")
        self.library.restore(self.ident, self.library.get(self.ident)["revision"], "alice")
        self.assertEqual(self.check()["state"], "verified-local")

    def test_changed_remote_details_and_conflicting_mappings_are_explicit(self):
        self.assertEqual(self.check(dedupKey="other")["state"], "remote-details-changed")
        self.assertEqual(self.check(size=len(self.raw) + 1)["state"], "remote-details-changed")
        record = json.loads(self.sidecar.read_bytes())
        record["google_originals"].append({**record["google_originals"][0], "sha256": "a" * 64})
        atomic(self.sidecar, record)
        self.library.put_index(record, self.sidecar)
        self.assertEqual(self.check()["state"], "ambiguous")

    def test_mapping_survives_disposable_catalog_loss(self):
        self.library.dbpath.unlink()
        self.library = Library(self.library.root, self.library.state)
        self.library.rebuild()
        self.matches = LocalGoogleMatches(self.library)
        self.assertEqual(self.check()["recordIds"], [self.ident])

    def test_budget_and_storage_failures_are_never_absence(self):
        self.matches = LocalGoogleMatches(self.library, byte_budget=1)
        self.assertEqual(self.check()["state"], "verification-deferred")
        self.matches = LocalGoogleMatches(self.library)
        self.path.unlink()
        self.assertEqual(self.check()["state"], "local-unavailable")
        (self.library.root / ".photoflow/library.json").unlink()
        with self.assertRaises(OSError):
            self.check()

    def test_invalid_targets_are_rejected_before_reading_files(self):
        for targets in [[], [self.target] * 101, [self.target] * 2,
                        [{**self.target, "namespace": "album-item"}],
                        [{**self.target, "size": True}], [{**self.target, "extra": "ignored?"}]]:
            with self.assertRaises(ValueError):
                self.matches.check("google-a", targets)
        with self.assertRaises(ValueError):
            self.matches.check("", [self.target])

    def test_legacy_urls_are_not_account_attribution_and_malformed_mappings_fail(self):
        record = json.loads(self.sidecar.read_bytes())
        del record["google_originals"]
        record["sources"][0]["documents"] = [{"url": "https://photos.google.com/photo/media-a"}]
        atomic(self.sidecar, record)
        self.library.put_index(record, self.sidecar)
        self.assertEqual(self.check()["state"], "unmapped")
        record["google_originals"] = [{"account": "google-a", "mediaKey": "media-a"}]
        atomic(self.sidecar, record)
        with self.assertRaises(ValueError):
            self.library.put_index(record, self.sidecar)

    def test_sidecar_changed_during_hashing_cannot_verify(self):
        from photoflow_web.google_downloads import file_sha
        def changed(path):
            sha = file_sha(path)
            record = json.loads(self.sidecar.read_bytes())
            record["google_originals"] = []
            atomic(self.sidecar, record)
            return sha
        with patch("photoflow_web.google_identity.file_sha", side_effect=changed):
            self.assertEqual(self.check()["state"], "stale-local-metadata")

    def test_one_verified_copy_is_reported_even_when_another_copy_changed(self):
        import copy
        record = copy.deepcopy(self.record)
        record.pop("revision")
        record["record_id"] = "second-copy"
        record["file"]["relative_path"] = "second.png"
        second = self.library.path("second.png")
        second.write_bytes(self.raw)
        sidecar = self.library.path("second.png" + SIDECAR)
        atomic(sidecar, record)
        self.library.put_index(record, sidecar)
        self.path.write_bytes(b"x" * len(self.raw))
        result = self.check()
        self.assertEqual(result["state"], "verified-local")
        self.assertEqual(result["recordIds"], ["second-copy"])
        self.assertEqual({c["state"] for c in result["candidates"]}, {"verified-local", "local-content-changed"})
        second.unlink()
        sidecar.unlink()
        self.library.rebuild()
        self.assertEqual(self.check()["state"], "local-content-changed")

    def test_library_identity_change_during_verification_stops_the_result(self):
        from photoflow_web.google_downloads import file_sha
        def replaced(path):
            sha = file_sha(path)
            atomic(self.library.root / ".photoflow/library.json", {"schema_version": 2, "library_id": "other"})
            return sha
        with patch("photoflow_web.google_identity.file_sha", side_effect=replaced):
            with self.assertRaises(OSError):
                self.check()


class LocalMatchHTTPTests(unittest.TestCase):
    def test_auth_csrf_account_binding_and_default_wiring(self):
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "library"
            (root / ".photoflow").mkdir(parents=True)
            atomic(root / ".photoflow/library.json", {"schema_version": 2, "library_id": "test"})
            roles = {"alice": 3}
            app = create_app(root, Path(temp) / "state", auth=lambda d: {"ok": True, "uid": 123}, role_resolver=lambda n: roles[n])
            with TestClient(app, base_url="https://testserver") as client:
                body = {"account": "google-a", "photoUrls": ["https://photos.google.com/photo/media-a"]}
                endpoint = "/api/v1/google/local-matches"
                self.assertEqual(client.post(endpoint, json=body).status_code, 401)
                response = client.post("/api/v1/auth/login", headers={"Origin": "https://testserver"}, json={"username": "alice", "password": "secret"})
                headers = {"Origin": "https://testserver", "X-CSRF-Token": response.json()["csrf"]}
                self.assertEqual(client.post(endpoint, json=body).status_code, 403)
                self.assertEqual(client.post(endpoint, json=body, headers=headers).status_code, 409)
                store = app.state.google_workers
                store.pair(store.pairing("alice", "google-a")["code"], "google-a")
                response = client.post(endpoint, json=body, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["items"][0]["state"], "unmapped")
                self.assertEqual(client.post(endpoint, json={**body, "account": "google-b"}, headers=headers).status_code, 409)
                self.assertEqual(client.post(endpoint, json={**body, "photoUrls": ["https://photos.google.com/album/a/photo/media-a"]}, headers=headers).status_code, 422)
                roles["alice"] = 1
                self.assertEqual(client.post(endpoint, json=body, headers=headers).status_code, 403)
