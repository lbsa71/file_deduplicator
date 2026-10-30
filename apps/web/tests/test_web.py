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

    def test_trashing_keeper_preserves_sources_without_copying_overrides(self):
        from PIL import Image
        from photoflow.adapters import NoEmbeddedMetadata, RandomIds, SystemClock
        from photoflow.runner import Runner, Config
        import json

        (self.root / "inbox").mkdir()
        for name, person in [("one.jpg", "One"), ("two.jpg", "Two")]:
            Image.new("RGB", (10, 10), "blue").save(self.root / "inbox" / name)
            (self.root / "inbox" / (name + ".supplemental-metadata.json")).write_text(
                json.dumps({"people": [{"name": person}]})
            )
        result = Runner(
            self.lib.fs,
            SystemClock(),
            RandomIds(),
            NoEmbeddedMetadata(),
            Config(settle_seconds=0),
        ).run()
        self.assertEqual(result.errors, [])
        self.lib.rebuild()
        canonical = self.lib.listing()["items"][0]
        keeper = self.lib.metadata(
            canonical["id"], canonical["revision"], {"favorite": True}, [], "test"
        )
        self.lib.trash(keeper["record_id"], keeper["revision"], "test")
        remaining = self.lib.listing()["items"][0]
        survivor = self.lib.get(remaining["id"])
        self.assertEqual(survivor["resolved"]["people"], ["One", "Two"])
        self.assertEqual(len(survivor["sources"]), 2)
        self.assertNotIn("favorite", survivor["overrides"])

    def test_watcher_ignores_completed_moves_but_not_missing_indexed_files(self):
        from photoflow_web.watch import Reconciler

        watcher = Reconciler(self.lib, lambda: None)
        self.assertFalse(watcher.meaningful("photos/already-moved.jpg"))
        self.assertFalse(watcher.meaningful("photos/already-moved.jpg.photo.json"))
        with self.lib.db() as db:
            db.execute(
                "INSERT INTO photos VALUES(?,?,?,?,?)",
                ("test", "photos/missing.jpg", "rev", "{}", "stamp"),
            )
        self.assertTrue(watcher.meaningful("photos/missing.jpg"))
        self.assertTrue(watcher.meaningful("photos/missing.jpg.photo.json"))

    def test_preview_allows_read_access_time_updates(self):
        import os, hashlib
        from PIL import Image
        from photoflow_web.media import Media

        source = self.root / "photo.jpg"
        Image.new("RGB", (100, 80), "blue").save(source)
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        os.utime(source, ns=(0, source.stat().st_mtime_ns))
        record = {
            "file": {
                "relative_path": "photo.jpg",
                "sha256": sha,
                "fingerprint": self.lib.fs.stat("photo.jpg").to_dict(),
            },
            "resolved": {},
        }
        media = Media(self.lib, self.root / "cache")
        target = media.cache / "aa" / "preview.webp"
        before = source.stat()
        media.render(record, 2048, target, "test")
        after = source.stat()
        self.assertNotEqual(before.st_atime_ns, after.st_atime_ns)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertTrue(target.exists(), media.failed)

    def test_preview_still_rejects_content_changes_during_decode(self):
        import hashlib
        from PIL import Image
        from unittest.mock import patch
        from photoflow_web.media import Media

        source = self.root / "photo.jpg"
        Image.new("RGB", (100, 80), "blue").save(source)
        record = {
            "file": {
                "relative_path": "photo.jpg",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "fingerprint": self.lib.fs.stat("photo.jpg").to_dict(),
            },
            "resolved": {},
        }
        media = Media(self.lib, self.root / "cache")
        target = media.cache / "aa" / "preview.webp"

        def changed(command, **kwargs):
            Image.new("RGB", (10, 10), "blue").save(
                str(command[-1]).split("[")[0], "WEBP"
            )
            source.write_bytes(b"new content")

        with patch("photoflow_web.media.subprocess.run", side_effect=changed):
            media.render(record, 2048, target, "test")
        self.assertFalse(target.exists())
        self.assertEqual(media.failed["test"], "ValueError")

    def test_bounded_heic_worker_produces_browser_preview(self):
        import subprocess, sys
        from PIL import Image
        import pillow_heif

        pillow_heif.register_heif_opener(decode_threads=1)
        source = self.root / "sample.heic"
        target = self.root / "preview.webp"
        Image.new("RGB", (128, 96), "blue").save(
            source,
            "HEIF",
            quality=60,
            enc_params={"x265:pools": "1", "x265:frame-threads": "1"},
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "photoflow_web.decoder",
                sys.executable,
                "-m",
                "photoflow_web.heic",
                str(source),
                "64",
                str(target),
            ],
            check=True,
            timeout=15,
            capture_output=True,
        )
        with Image.open(target) as result:
            self.assertEqual(result.format, "WEBP")
            self.assertEqual(result.size, (64, 48))
            self.assertFalse(result.getexif())
            self.assertFalse(result.info.get("icc_profile"))

    def test_export_allows_read_access_time_updates(self):
        import os, time
        from PIL import Image
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app
        from photoflow.adapters import NoEmbeddedMetadata, RandomIds, SystemClock
        from photoflow.runner import Runner, Config

        (self.root / "inbox").mkdir()
        Image.new("RGB", (100, 80), "blue").save(self.root / "inbox/photo.jpg")
        Runner(
            self.lib.fs,
            SystemClock(),
            RandomIds(),
            NoEmbeddedMetadata(),
            Config(settle_seconds=0),
        ).run()
        self.lib.rebuild()
        ident = self.lib.listing()["items"][0]["id"]
        record = self.lib.get(ident)
        source = self.root / record["file"]["relative_path"]
        os.utime(source, ns=(0, source.stat().st_mtime_ns))
        app = create_app(
            self.root,
            self.root / "state",
            auth=lambda d: {"ok": True, "uid": 123},
            role_resolver=lambda n: 1,
        )
        with TestClient(app, base_url="https://testserver") as client:
            response = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "https://testserver"},
                json={"username": "test", "password": "secret"},
            )
            response.raise_for_status()
            headers = {
                "Origin": "https://testserver",
                "X-CSRF-Token": response.json()["csrf"],
            }
            response = client.post(
                "/api/v1/exports", json={"ids": [ident]}, headers=headers
            )
            response.raise_for_status()
            for _ in range(100):
                status = client.get("/api/v1/jobs/" + response.json()["job_id"]).json()
                if status["state"] in ("failed", "succeeded"):
                    break
                time.sleep(0.01)
            self.assertEqual(status["state"], "succeeded", status)

    def test_ui_deep_links_serve_shell_without_masking_api_or_assets(self):
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app

        assets = self.root / "state/ui"
        assets.mkdir(parents=True)
        (assets / "index.html").write_text("<html>route-test-shell</html>")
        app = create_app(self.root, self.root / "state", static_root=assets)
        with TestClient(app, base_url="https://testserver") as client:
            for path in (
                "/photos",
                "/photos/99b8980a-6721-4641-b41c-3d81e81c3b5d",
                "/folders?path=photos%2F2000%2F09",
                "/favorites?q=Alma",
                "/trash",
                "/activity",
                "/duplicates",
                "/login?next=%2Ffavorites",
            ):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn("route-test-shell", response.text)
            for path in ("/api/v1/missing", "/assets/missing.js", "/unknown"):
                response = client.get(path)
                self.assertEqual(response.status_code, 404, path)
                self.assertNotIn("route-test-shell", response.text)
            self.assertEqual(client.head("/photos").status_code, 200)
