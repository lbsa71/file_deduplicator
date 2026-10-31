import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from photoflow_web.core import Library, atomic
from photoflow_web.google_workers import WorkerStore
from photoflow_web.google_inventory import GoogleInventories


def media(key):
    return {"namespace": "library-media", "mediaKey": key, "dedupKey": "dedup-" + key,
            "favorite": None, "trashTimestamp": None, "companion": None}


class GoogleInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / "library"
        (root / ".photoflow").mkdir(parents=True)
        atomic(root / ".photoflow/library.json", {"schema_version": 2, "library_id": "test"})
        self.library = Library(root, Path(self.temp.name) / "state")
        self.now = 1000
        self.workers = WorkerStore(self.library.state, now=lambda: self.now)
        paired = self.workers.pair(self.workers.pairing("alice", "google-a")["code"], "google-a")
        self.worker = self.workers.authenticate(paired["token"], "google-a")["id"]
        self.inventories = GoogleInventories(self.library, self.workers, now=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def page(self, operation, items, next_cursor=None):
        job = self.workers.claim(self.worker)
        self.assertEqual(job["operation"], operation)
        self.workers.finish(self.worker, job["id"], job["lease"], {
            "items": items, "next": next_cursor, "complete": next_cursor is None, "retentionReady": False})
        return job

    def create(self):
        result = self.inventories.create("alice", "google-a")
        self.ident = result["id"]
        self.inventories.advance("alice", "google-a", self.ident)
        return result

    def advance(self):
        return self.inventories.advance("alice", "google-a", self.ident)

    def test_complete_inventory_requires_every_terminal_page_and_album_members(self):
        self.create()
        self.page("library-page", [media("a")], "next-a")
        result = self.advance()
        self.assertFalse(result["complete"])
        self.page("library-page", [media("b")])
        self.advance()
        self.page("favorites-page", [{**media("b"), "favorite": True}])
        self.advance()
        album = {"namespace": "album", "albumId": "album-a", "title": "Family", "itemCount": 1, "shared": False}
        self.page("albums-page", [album])
        self.advance()
        self.page("trash-page", [])
        self.advance()
        self.page("album-members", [{**media("album-specific-key"), "namespace": "album-item", "dedupKey": "dedup-b"}])
        result = self.advance()
        self.assertEqual(result["state"], "complete")
        self.assertTrue(result["complete"])
        self.assertFalse(result["retentionReady"])
        self.assertEqual(result["counts"], {"library": 2, "favorites": 1, "albums": 1, "trash": 0, "albumMembers": 1})
        self.assertEqual([item["mediaKey"] for item in self.inventories.items("alice", "google-a", self.ident, "library")], ["a", "b"])
        members = list(self.inventories.items("alice", "google-a", self.ident, "album:album-a"))
        self.assertEqual(members[0]["namespace"], "album-item")
        self.assertIsNone(self.workers.claim(self.worker))

    def test_cursor_loops_and_duplicate_ids_fail_without_followup_pages(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                self.create()
                self.page("library-page", [media("a")], "cursor-a")
                self.advance()
                self.page("library-page", [media("a" if duplicate else "b")], "cursor-b" if duplicate else "cursor-a")
                result = self.advance()
                self.assertEqual(result["state"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertEqual(result["error"], "DUPLICATE_ID" if duplicate else "CURSOR_LOOP")
                self.assertIsNone(self.workers.claim(self.worker))

    def test_restart_reuses_exact_pending_read_and_preserves_completed_pages(self):
        self.create()
        self.page("library-page", [media("a")], "next-a")
        self.advance()
        pending = self.workers.claim(self.worker)
        self.workers = WorkerStore(self.library.state, now=lambda: self.now)
        self.inventories = GoogleInventories(self.library, self.workers, now=lambda: self.now)
        self.advance()
        retried = self.workers.claim(self.worker)
        self.assertEqual(retried["id"], pending["id"])
        self.assertNotEqual(retried["lease"], pending["lease"])
        self.assertEqual(list(self.inventories.items("alice", "google-a", self.ident, "library")), [media("a")])

    def test_failure_missing_storage_and_cancellation_do_not_complete_inventory(self):
        self.create()
        job = self.workers.claim(self.worker)
        self.workers.finish(self.worker, job["id"], job["lease"], error="SESSION")
        result = self.advance()
        self.assertEqual(result["state"], "incomplete")
        self.assertFalse(result["complete"])
        self.create()
        self.inventories.cancel("alice", "google-a", self.ident)
        result = self.advance()
        self.assertEqual(result["state"], "cancelled")
        self.assertFalse(result["complete"])

    def test_wrong_owner_account_and_library_are_rejected(self):
        self.create()
        for owner, account in [("bob", "google-a"), ("alice", "google-b")]:
            with self.assertRaises(KeyError):
                self.inventories.get(owner, account, self.ident)
        atomic(self.library.root / ".photoflow/library.json", {"schema_version": 2, "library_id": "other"})
        with self.assertRaises(OSError):
            self.advance()

    def test_page_limits_are_explicit_incomplete_and_never_ignored(self):
        self.inventories.max_pages = 1
        self.create()
        self.page("library-page", [media("a")], "next-a")
        result = self.advance()
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual(result["error"], "PAGE_LIMIT")
        self.assertIsNone(self.workers.claim(self.worker))

    def test_page_tampering_cannot_be_read_as_valid_evidence(self):
        self.create()
        self.page("library-page", [media("a")], "next-a")
        self.advance()
        path = next(self.inventories.path(self.ident).parent.glob("page-*.json"))
        raw = json.loads(path.read_text())
        raw["result"]["items"][0]["favorite"] = False
        atomic(path, raw)
        with self.assertRaises(ValueError):
            list(self.inventories.items("alice", "google-a", self.ident, "library"))

    def test_interrupted_page_publication_replays_without_another_google_read(self):
        self.create()
        self.page("library-page", [media("a")])
        original = self.inventories.save
        def fail(data):
            if data["collections"][0]["pages"]:
                raise OSError("stopped before manifest checkpoint")
            return original(data)
        with patch.object(self.inventories, "save", side_effect=fail):
            with self.assertRaises(OSError):
                self.advance()
        read = self.workers.bound_read_result
        def only_successor(*args):
            self.assertNotEqual(args[4], "library-page", "published page must recover without the old job result")
            return read(*args)
        with patch.object(self.workers, "bound_read_result", side_effect=only_successor):
            result = self.advance()
        self.assertEqual(result["counts"]["library"], 1)
        job = self.workers.claim(self.worker)
        self.assertEqual(job["operation"], "favorites-page")

    def test_page_integrity_work_is_linear_during_a_full_traversal(self):
        self.create()
        with patch.object(self.inventories, "page", wraps=self.inventories.page) as reads:
            for index in range(20):
                self.page("library-page", [media("photo-" + str(index))], "cursor-" + str(index) if index < 19 else None)
                self.advance()
            for operation in ("favorites-page", "albums-page", "trash-page"):
                self.page(operation, [])
                result = self.advance()
            self.assertTrue(result["complete"])
            self.assertLessEqual(reads.call_count, 100, "do not reread all previous pages for every cursor")


class GoogleInventoryHTTPTests(unittest.TestCase):
    def test_background_inventory_survives_browser_absence_and_requires_admin_csrf_account(self):
        import time
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "library"
            (root / ".photoflow").mkdir(parents=True)
            atomic(root / ".photoflow/library.json", {"schema_version": 2, "library_id": "test"})
            roles = {"alice": 3}
            app = create_app(root, Path(temp) / "state", auth=lambda d: {"ok": True, "uid": 123}, role_resolver=lambda n: roles[n])
            endpoint = "/api/v1/google/inventories"
            with TestClient(app, base_url="https://testserver") as client:
                self.assertEqual(client.post(endpoint, json={"account": "google-a"}).status_code, 401)
                response = client.post("/api/v1/auth/login", headers={"Origin": "https://testserver"}, json={"username": "alice", "password": "secret"})
                headers = {"Origin": "https://testserver", "X-CSRF-Token": response.json()["csrf"]}
                workers = app.state.google_workers
                pair = workers.pair(workers.pairing("alice", "google-a")["code"], "google-a")
                worker = workers.authenticate(pair["token"], "google-a")["id"]
                self.assertEqual(client.post(endpoint, json={"account": "google-a"}).status_code, 403)
                self.assertEqual(client.post(endpoint, headers=headers, json={"account": "wrong"}).status_code, 409)
                response = client.post(endpoint, headers=headers, json={"account": "google-a"})
                self.assertEqual(response.status_code, 200, response.text)
                ident = response.json()["id"]
                operations = []
                # No GET or refresh requests drive this run: the durable runtime does.
                for _ in range(400):
                    job = workers.claim(worker)
                    if job:
                        operations.append(job["operation"])
                        workers.finish(worker, job["id"], job["lease"], {"items": [], "next": None, "complete": True, "retentionReady": False})
                    if len(operations) == 4:
                        break
                    time.sleep(.02)
                for _ in range(100):
                    response = client.get(endpoint + "/" + ident, params={"account": "google-a"})
                    if response.json()["complete"]: break
                    time.sleep(.02)
                self.assertTrue(response.json()["complete"], response.text)
                self.assertEqual(operations, ["library-page", "favorites-page", "albums-page", "trash-page"])
                self.assertFalse(response.json()["retentionReady"])
                roles["alice"] = 1
                self.assertEqual(client.get(endpoint + "/" + ident, params={"account": "google-a"}).status_code, 403)
