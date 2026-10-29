import tempfile, unittest
from pathlib import Path
from photoflow_web.core import Library, Conflict


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".photoflow").mkdir()
        (self.root / ".photoflow/library.json").write_text(
            '{"schema_version":2,"library_id":"test"}'
        )
        self.lib = Library(self.root, self.root / "state")

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths_cannot_escape(self):
        for path in ("../etc", "/etc", "a/../../b", ".photoflow/lock"):
            with self.assertRaises(ValueError):
                self.lib.user_path(path)

    def test_folders_survive_rebuild(self):
        folder = self.lib.create_folder(None, "Family", "test")
        self.lib.rebuild()
        self.assertTrue((self.root / folder["path"]).is_dir())
        self.assertEqual(self.lib.folders()[0]["id"], folder["id"])

    def test_folder_collision_does_not_merge(self):
        self.lib.create_folder(None, "Family", "test")
        with self.assertRaises(Conflict):
            self.lib.create_folder(None, "family", "test")

    def test_chunk_retry_and_conflict(self):
        up = self.lib.new_upload("stefan", "a.jpg", 3, None)
        self.assertEqual(self.lib.chunk(up["id"], "stefan", 0, b"abc"), 3)
        self.assertEqual(self.lib.chunk(up["id"], "stefan", 0, b"abc"), 3)
        with self.assertRaises(Conflict):
            self.lib.chunk(up["id"], "stefan", 0, b"xyz")

    def test_rename_folder_keeps_identity(self):
        f = self.lib.create_folder(None, "Family", "test")
        updated = self.lib.rename_folder(f["id"], f["revision"], "Alma", None, "test")
        self.assertEqual(updated["id"], f["id"])
        self.assertTrue((self.root / "folders/Alma").is_dir())

    def test_uncommitted_operation_recovers(self):
        from photoflow_web.core import atomic

        (self.root / "folders").mkdir()
        (self.root / "folders/a").write_bytes(b"original")
        atomic(
            self.lib.ops / "test.json",
            {
                "moves": [{"from": "folders/a", "to": "folders/b"}],
                "writes": {"folders/info.json": {"ok": True}},
            },
        )
        with self.lib.writer():
            pass
        self.assertEqual((self.root / "folders/b").read_bytes(), b"original")
        self.assertFalse((self.lib.ops / "test.json").exists())

    def test_http_requires_auth_and_csrf(self):
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app

        app = create_app(
            self.root,
            self.root / "state",
            auth=lambda d: {"ok": True, "uid": 123},
            role_resolver=lambda n: 2,
        )
        with TestClient(app, base_url="https://testserver") as client:
            self.assertEqual(client.get("/api/v1/photos").status_code, 401)
            self.assertEqual(
                client.post(
                    "/api/v1/auth/login",
                    json={"username": "test", "password": "secret"},
                ).status_code,
                403,
            )
            response = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "https://testserver"},
                json={"username": "test", "password": "secret"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                client.post("/api/v1/folders", json={"name": "test"}).status_code, 403
            )
            self.assertEqual(
                client.post(
                    "/api/v1/folders",
                    headers={
                        "Origin": "https://testserver",
                        "X-CSRF-Token": response.json()["csrf"],
                    },
                    json={"name": "test"},
                ).status_code,
                200,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/scans",
                    headers={
                        "Origin": "https://testserver",
                        "X-CSRF-Token": response.json()["csrf"],
                    },
                    json={},
                ).status_code,
                403,
            )

    def test_photo_edit_move_trash_restore_and_thumbnail(self):
        import time
        from PIL import Image
        from photoflow.adapters import NoEmbeddedMetadata, RandomIds, SystemClock
        from photoflow.runner import Runner, Config
        from photoflow_web.media import Media

        (self.root / "inbox").mkdir()
        Image.new("RGB", (800, 600), "blue").save(self.root / "inbox/photo.jpg")
        result = Runner(
            self.lib.fs,
            SystemClock(),
            RandomIds(),
            NoEmbeddedMetadata(),
            Config(settle_seconds=0),
        ).run()
        self.assertEqual(result.errors, [])
        self.lib.rebuild()
        item = self.lib.listing()["items"][0]
        ident = item["id"]
        d = self.lib.metadata(
            ident, item["revision"], {"people": ["Alma"], "favorite": True}, [], "test"
        )
        self.assertEqual(d["resolved"]["people"], ["Alma"])
        f = self.lib.create_folder(None, "Family", "test")
        d = self.lib.move(ident, d["revision"], f["id"], "test")
        path = self.root / d["file"]["relative_path"]
        original = path.read_bytes()
        result = Runner(
            self.lib.fs,
            SystemClock(),
            RandomIds(),
            NoEmbeddedMetadata(),
            Config(settle_seconds=0),
        ).run()
        self.assertEqual(result.moved, 0)
        media = Media(self.lib, self.root / "cache")
        p, status = media.variant(d, 256)
        for _ in range(100):
            if status != "pending":
                break
            time.sleep(0.05)
            p, status = media.variant(d, 256)
        self.assertEqual(status, "ready")
        with Image.open(p) as thumbnail:
            self.assertLessEqual(max(thumbnail.size), 256)
        self.lib.rebuild()
        d = self.lib.get(ident)
        self.lib.trash(ident, d["revision"], "test")
        self.lib.rebuild()
        self.assertEqual(self.lib.listing()["total"], 0)
        d = self.lib.get(ident)
        self.lib.restore(ident, d["revision"], "test")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.lib.get(ident)["resolved"]["people"], ["Alma"])

    def test_upload_finish_retries_same_identity(self):
        up = self.lib.new_upload("test", "photo.jpg", 3, None)
        self.lib.chunk(up["id"], "test", 0, b"abc")
        first = self.lib.finish_upload(up["id"], "test")
        second = self.lib.finish_upload(up["id"], "test")
        self.assertEqual(first["record_id"], second["record_id"])
        self.assertEqual((self.root / first["path"]).read_bytes(), b"abc")
        self.assertTrue((self.root / (first["path"] + ".photo.json")).exists())

    def test_folder_trash_restore_preserves_unknown_files(self):
        f = self.lib.create_folder(None, "Family", "test")
        (self.root / f["path"] / "notes.txt").write_text("keep")
        self.lib.trash_folder(f["id"], f["revision"], "test")
        self.assertFalse((self.root / f["path"]).exists())
        self.lib.restore_folder(f["id"], "test")
        self.assertEqual((self.root / f["path"] / "notes.txt").read_text(), "keep")

    def test_recovery_rejects_changed_media(self):
        from photoflow_web.core import atomic, digest

        (self.root / "folders").mkdir()
        (self.root / "folders/photo.jpg").write_bytes(b"changed")
        manifest = self.lib.ops / "conflict.json"
        atomic(
            manifest,
            {
                "moves": [
                    {
                        "from": "folders/photo.jpg",
                        "to": "folders/other.jpg",
                        "sha256": digest(b"original"),
                    }
                ],
                "writes": {},
            },
        )
        with self.assertRaises(ValueError):
            with self.lib.writer():
                pass
        self.assertEqual((self.root / "folders/photo.jpg").read_bytes(), b"changed")
        self.assertTrue(manifest.exists())

    def test_recovery_preserves_concurrent_metadata_change(self):
        from photoflow_web.core import atomic, digest

        (self.root / "folders").mkdir()
        p = self.root / "folders/info.json"
        p.write_bytes(b'{"new":true}')
        manifest = self.lib.ops / "conflict.json"
        atomic(
            manifest,
            {
                "moves": [],
                "writes": {"folders/info.json": {"planned": True}},
                "expected_writes": {"folders/info.json": digest(b'{"old":true}')},
            },
        )
        with self.assertRaises(ValueError):
            with self.lib.writer():
                pass
        self.assertEqual(p.read_bytes(), b'{"new":true}')
        self.assertTrue(manifest.exists())
