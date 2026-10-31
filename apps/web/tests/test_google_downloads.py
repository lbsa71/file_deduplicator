import hashlib, io, json, tempfile, unittest
import httpx
import zipfile
import time
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from photoflow_web.core import Library
from photoflow_web.google_downloads import OriginalImporter, download_original


class OriginalDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / "library"
        (root / ".photoflow").mkdir(parents=True)
        (root / ".photoflow/library.json").write_text('{"schema_version":2,"library_id":"test"}')
        self.library = Library(root, Path(self.temp.name) / "state")
        output = io.BytesIO()
        Image.new("RGB", (3, 2), "red").save(output, "PNG")
        self.raw = output.getvalue()
        self.photo = {"mediaKey": "media-a", "dedupKey": "dedup-a", "filename": "original.png", "size": len(self.raw)}
        self.calls = 0
        def fetch(url):
            self.calls += 1
            return self.raw, "image/png"
        self.importer = OriginalImporter(self.library, fetch)

    def tearDown(self):
        self.temp.cleanup()

    def test_original_is_imported_once_and_duplicate_is_hash_verified(self):
        receipt = self.importer.import_one("alice", "google-a", "job-a", self.photo,
                                           "https://lh3.googleusercontent.com/private")
        self.assertEqual(receipt["outcome"], "imported")
        self.assertEqual(receipt["sha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(self.importer.import_one("alice", "google-a", "job-a", self.photo,
                                                "https://lh3.googleusercontent.com/private"), receipt)
        self.assertEqual(self.calls, 1)
        record = self.library.get(receipt["recordId"])
        self.assertEqual(self.library.path(record["file"]["relative_path"]).read_bytes(), self.raw)
        again = self.importer.import_one("alice", "google-a", "job-b", self.photo,
                                        "https://lh3.googleusercontent.com/private")
        self.assertEqual(again["recordId"], receipt["recordId"])
        self.assertEqual(again["outcome"], "already-present")
        self.assertEqual(self.calls, 2)
        self.assertNotIn("https://", json.dumps(record))

    def test_imported_original_is_immediately_renderable_without_a_rescan(self):
        from photoflow_web.media import Media
        result = self.importer.import_one("alice", "google-a", "preview-job", self.photo,
                                          "https://lh3.googleusercontent.com/private")
        record = self.library.get(result["recordId"])
        media = Media(self.library, self.library.state / "preview-cache")
        try:
            path, state = media.variant(record, 256)
            for _ in range(200):
                if state != "pending": break
                time.sleep(.05)
                path, state = media.variant(record, 256)
            self.assertEqual(state, "ready", media.failed)
            with Image.open(path) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (3, 2))
            self.assertEqual(hashlib.sha256(self.library.path(record["file"]["relative_path"]).read_bytes()).hexdigest(), result["sha256"])
        finally:
            media.pool.shutdown(wait=True)

    def test_interrupted_import_finalization_recovers_without_a_download_url_or_second_original(self):
        with patch.object(self.importer, "finalize", side_effect=OSError("process stopped after publication")):
            with self.assertRaises(OSError):
                self.importer.import_one("alice", "google-a", "recovery-job", self.photo,
                                          "https://lh3.googleusercontent.com/private")
        result = self.importer.import_one("alice", "google-a", "recovery-job", self.photo, None)
        self.assertEqual(self.calls, 1)
        record = self.library.get(result["recordId"])
        self.assertEqual(record["file"]["fingerprint"], self.library.fs.stat(record["file"]["relative_path"]).to_dict())
        self.assertEqual(len(self.library.listing()["items"]), 1)

    def test_same_bytes_with_different_google_identity_do_not_create_another_original(self):
        first = self.importer.import_one("alice", "google-a", "job-a", self.photo,
                                         "https://lh3.googleusercontent.com/private")
        second = self.importer.import_one("alice", "google-a", "job-b", {**self.photo, "mediaKey": "other"},
                                          "https://lh3.googleusercontent.com/private")
        self.assertEqual(first["recordId"], second["recordId"])
        self.assertEqual(second["outcome"], "already-present")

    def test_wrong_size_html_and_unsafe_urls_never_import(self):
        for photo, url in [({**self.photo, "size": len(self.raw)+1}, "https://lh3.googleusercontent.com/private"),
                           (self.photo, "https://evil.example/private"),
                           ({**self.photo, "filename": "../../secret.png"}, "https://lh3.googleusercontent.com/private")]:
            with self.assertRaises(ValueError):
                self.importer.import_one("alice", "google-a", "job-a", photo, url)
        self.assertEqual(len(self.library.listing()["items"]), 0)

    def test_anonymous_download_stops_at_redirects_and_never_sends_credentials(self):
        calls = []
        def handler(request):
            calls.append(request)
            self.assertNotIn("cookie", request.headers)
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(302, headers={"location": "https://evil.example/private"})
        with self.assertRaises(ValueError):
            download_original("https://lh3.googleusercontent.com/private", httpx.MockTransport(handler))
        self.assertEqual(len(calls), 1)

    def test_wrong_length_and_html_are_rejected_without_an_import(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-length": "99"}, content=b"short"))
        with self.assertRaises(ValueError):
            download_original("https://lh3.googleusercontent.com/private", transport)
        self.importer.fetch = lambda url: (b"<html>login</html>", "text/html")
        with self.assertRaises((ValueError, OSError)):
            self.importer.import_one("alice", "google-a", "job-a", {**self.photo, "size": 18}, "https://lh3.googleusercontent.com/private")
        self.assertEqual(len(self.library.listing()["items"]), 0)

    def test_google_single_original_zip_is_unwrapped_without_changing_original_bytes(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr(self.photo["filename"], self.raw)
        self.importer.fetch = lambda url: (archive.getvalue(), "application/zip")
        result = self.importer.import_one("alice", "google-a", "zip-job", self.photo, "https://lh3.googleusercontent.com/private")
        self.assertEqual(result["sha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(result["bytes"], len(self.raw))

    def test_multi_file_wrong_name_and_unsafe_archives_never_import(self):
        for entries in [[("original.png",self.raw),("second.png",self.raw)], [("../original.png",self.raw)], [("other.png",self.raw)]]:
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as output:
                for name, raw in entries: output.writestr(name, raw)
            self.importer.fetch = lambda url: (archive.getvalue(), "application/zip")
            with self.assertRaises(ValueError):
                self.importer.import_one("alice", "google-a", "zip-job", self.photo, "https://lh3.googleusercontent.com/private")
        self.assertEqual(len(self.library.listing()["items"]), 0)

    def test_transfer_requires_current_worker_account_job_lease_and_target(self):
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app
        app = create_app(self.library.root, self.library.state, auth=lambda d: {"ok":True,"uid":123}, role_resolver=lambda name: 3)
        app.state.google_originals.fetch = self.importer.fetch
        store = app.state.google_workers
        paired = store.pair(store.pairing("alice", "google-a")["code"], "google-a")
        worker = store.authenticate(paired["token"], "google-a")
        job = store.enqueue("alice", "download-original", {"photoUrl":"https://photos.google.com/photo/media-a"})
        job = store.claim(worker["id"])
        photo = {**self.photo, "namespace":"library-media", "favorite":None, "trashTimestamp":None, "companion":None}
        body = {"photo":photo,"url":"https://lh3.googleusercontent.com/private", "account":"google-a", "lease":job["lease"]}
        headers = {"Origin":"chrome-extension://" + "a" * 32, "Authorization":"Bearer " + paired["token"]}
        with TestClient(app, raise_server_exceptions=False) as client:
            for changed in [{"lease":"stale"}, {"account":"wrong"}, {"photo":{**photo, "mediaKey":"wrong"}}]:
                self.assertNotEqual(client.post("/api/v1/google/originals/" + job["id"], json={**body, **changed}, headers=headers).status_code, 200)
            self.assertEqual(self.calls, 0)
            response = client.post("/api/v1/google/originals/" + job["id"], json=body, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            store.finish(worker["id"], job["id"], job["lease"], response.json())
            self.assertEqual(store.status("alice")["jobs"][0]["state"], "succeeded")
            store.revoke("alice")
            self.assertNotEqual(client.post("/api/v1/google/originals/" + job["id"], json=body, headers=headers).status_code, 200)
