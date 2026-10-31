import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from photoflow_web.core import Library, atomic, Conflict
from photoflow_web.google_reconciliation import Reconciliation, manifest_hash


class Remote:
    def __init__(self):
        self.account = "account-a"
        self.calls = []
        self.jobs = {}
        self.used = 90
        self.total = 100
        self.photo = {
            "namespace": "library-media",
            "mediaKey": "photo-a",
            "dedupKey": "dedup-a",
            "favorite": False,
            "trashTimestamp": None,
            "companion": False,
        }
        self.fail = None

    def status(self, owner):
        return {"account": self.account, "pilotTargetPolicy": "selected"}

    def enqueue_once(
        self, owner, key, operation, value, confirmed=False, *, not_after=None
    ):
        if key in self.jobs:
            return copy.deepcopy(self.jobs[key])
        self.calls.append((operation, copy.deepcopy(value), confirmed))
        page = {"items": [], "next": None, "complete": True, "retentionReady": False}
        if operation == "library-page":
            page["items"] = [self.photo]
        result = page
        if operation == "storage-quota":
            result = {
                "used": self.used,
                "total": self.total,
                "photosUsed": self.used,
                "retentionReady": False,
            }
        if operation == "photo-details":
            result = {
                "photo": {
                    **self.photo,
                    "filename": "unimportant.jpg",
                    "size": 10,
                    "albums": [],
                    "archived": False,
                    "description": "",
                    "timestampMs": 1000,
                    "timezoneMs": 0,
                },
                "retentionReady": False,
            }
        if operation == "download-original":
            result = self.download()
        if operation == "trash":
            result = {"verified": True, "outcome": "verified", "retentionReady": False}
        job = {
            "id": str(len(self.jobs)),
            "state": "unknown" if self.fail == operation else "succeeded",
            "result": result,
            "error": None,
        }
        self.jobs[key] = job
        return copy.deepcopy(job)

    def result(self, owner, ident):
        return {
            "result": next(j["result"] for j in self.jobs.values() if j["id"] == ident)
        }


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name) / "library"
        (root / ".photoflow").mkdir(parents=True)
        atomic(
            root / ".photoflow/library.json",
            {"schema_version": 2, "library_id": "library-a"},
        )
        self.library = Library(root, Path(self.temp.name) / "state")
        self.remote = Remote()
        self.now = 1000
        self.service = Reconciliation(self.library, self.remote, now=lambda: self.now)
        self.addCleanup(self.service.close)

    def prepare(self, **options):
        job = self.service.prepare("alice", options)
        self.service.runner.run_once()
        value = self.service.jobs.get(job["id"])
        self.assertEqual(value["state"], "succeeded", value)
        return self.service.manifest("alice", value["result"]["manifestId"])

    def test_preparation_is_read_only_and_manifest_is_inspectable_and_sealed(self):
        value = self.prepare()
        self.assertEqual(value["account"], "account-a")
        self.assertEqual(value["sha256"], manifest_hash(value))
        self.assertTrue(
            all(operation != "trash" for operation, _, _ in self.remote.calls)
        )
        self.assertEqual(value["counts"]["remote"], 1)
        self.assertEqual(list(self.library.root.glob("**/*.photo.json")), [])

    def test_owner_retention_policy_keeps_remote_only_photos_without_automatic_download_or_trash(self):
        manifest = self.prepare()
        self.assertEqual(manifest["retentionPolicy"]["backupRequirement"], "owner-asserted-takeout")
        self.assertFalse(manifest["retentionPolicy"]["backupVerified"])
        remote = next(i for i in manifest["items"] if i.get("mediaKey") == "photo-a")
        self.assertEqual(remote["action"], "keep")
        self.assertIn("local", remote["reason"])
        self.assertEqual([op["operation"] for op in manifest["operations"]], ["storage-quota"])

    def test_selected_preparation_is_bounded_and_explicit_about_inventory_scope(self):
        manifest = self.prepare(photoUrls=["https://photos.google.com/photo/photo-a"])
        self.assertEqual(manifest["inventoryScope"], "selected")
        self.assertFalse(
            any(operation == "library-page" for operation, _, _ in self.remote.calls)
        )
        self.assertEqual(manifest["counts"]["remote"], 1)

    def test_non_vital_pilot_requires_explicit_targets_and_orders_cleanup_before_quota(
        self,
    ):
        with self.assertRaises(ValueError):
            self.service.prepare("alice", {"nonVital": True})
        m = self.prepare(
            photoUrls=["https://photos.google.com/photo/photo-a"],
            nonVital=True,
            reserveBytes=0,
        )
        ops = [op["operation"] for op in m["operations"]]
        self.assertLess(ops.index("trash"), ops.index("storage-quota"))
        job = self.service.commit("alice", m["id"], m["sha256"])
        self.service.runner.run_once()
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "succeeded")
        effects = [operation for operation, _, _ in self.remote.calls]
        self.assertLess(effects.index("trash"), len(effects) - 1)
        self.assertEqual(effects[-1], "storage-quota")

    def test_tampering_changed_account_and_expiration_prevent_commit(self):
        m = self.prepare()
        with self.assertRaises(Conflict):
            self.service.commit("alice", m["id"], "0" * 64)
        self.remote.account = "other"
        with self.assertRaises(Conflict):
            self.service.commit("alice", m["id"], m["sha256"])
        self.remote.account = "account-a"
        self.now += 86401
        with self.assertRaises(Conflict):
            self.service.commit("alice", m["id"], m["sha256"])

    def test_manifest_is_owner_bound_and_repeated_commit_reuses_command(self):
        m = self.prepare()
        with self.assertRaises(KeyError):
            self.service.manifest("bob", m["id"])
        one = self.service.commit("alice", m["id"], m["sha256"])
        two = self.service.commit("alice", m["id"], m["sha256"])
        self.assertEqual(one["id"], two["id"])
        self.service.runner.run_once()
        count = len(self.remote.calls)
        self.service.commit("alice", m["id"], m["sha256"])
        self.service.runner.run_once()
        self.assertEqual(len(self.remote.calls), count)

    def test_uncertain_cleanup_blocks_all_subsequent_operations(self):
        m = self.prepare(
            photoUrls=["https://photos.google.com/photo/photo-a"], nonVital=True
        )
        self.remote.fail = "trash"
        job = self.service.commit("alice", m["id"], m["sha256"])
        before = len(self.remote.calls)
        self.service.runner.run_once()
        value = self.service.jobs.get(job["id"])
        self.assertEqual(value["state"], "partial")
        self.assertEqual(value["error_code"], "RECONCILIATION_REQUIRED")
        self.assertEqual(
            [x[0] for x in self.remote.calls[before:]], ["photo-details", "trash"]
        )

    def test_local_revision_changes_prevent_any_commit_effects(self):
        from photoflow.model import Record

        record = Record.create("record-a", "library-a", "inbox/a.jpg").data
        record["file"].update(size_bytes=3, sha256=hashlib.sha256(b"abc").hexdigest())
        path = self.library.path("inbox/a.jpg")
        path.parent.mkdir()
        path.write_bytes(b"abc")
        sidecar = self.library.path("inbox/a.jpg.photo.json")
        atomic(sidecar, record)
        self.library.put_index(record, sidecar)
        m = self.prepare()
        record["overrides"]["favorite"] = True
        atomic(sidecar, record)
        with self.assertRaises(Conflict):
            self.service.commit("alice", m["id"], m["sha256"])

    def local_photo(self, ident="local-a", raw=b"new", references=None):
        from photoflow.model import Record

        record = Record.create(ident, "library-a", "inbox/" + ident + ".jpg").data
        record["file"].update(
            size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
        )
        if references:
            record["sources"][0]["documents"] = [
                {"document": {"url": url}} for url in references
            ]
        path = self.library.path(record["file"]["relative_path"])
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        sidecar = self.library.path(record["file"]["relative_path"] + ".photo.json")
        atomic(sidecar, record)
        self.library.put_index(record, sidecar)
        return record

    def publisher(self):
        effects = []

        class Publisher:
            def inspect(self, item, account):
                return True

            def publish(self, key, account, value):
                effects.append((key, value["recordId"]))
                return {"verified": True}

            def receipt(self, key):
                return None

        self.service.publisher = Publisher()
        return effects

    def test_available_capacity_publishes_even_if_no_space_was_reclaimed(self):
        self.local_photo()
        effects = self.publisher()
        m = self.prepare(reserveBytes=0)
        job = self.service.commit("alice", m["id"], m["sha256"])
        self.service.runner.run_once()
        self.assertEqual(len(effects), 1)
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "succeeded")
        self.assertEqual(self.remote.used, 90)

    def test_full_capacity_defers_for_another_run_without_a_polling_loop(self):
        self.local_photo()
        effects = self.publisher()
        self.remote.used = 100
        m = self.prepare(reserveBytes=0)
        job = self.service.commit("alice", m["id"], m["sha256"])
        self.service.runner.run_once()
        result = self.service.jobs.get(job["id"])
        self.assertEqual(result["state"], "partial")
        self.assertEqual(
            result["result"]["deferred"][0]["reason"], "INSUFFICIENT_QUOTA"
        )
        self.assertEqual(effects, [])
        self.assertFalse(self.service.runner.run_once())
        self.remote.used = 90
        m2 = self.prepare(reserveBytes=0)
        again = self.service.commit("alice", m2["id"], m2["sha256"])
        self.service.runner.run_once()
        self.assertEqual(len(effects), 1)
        self.assertEqual(self.service.jobs.get(again["id"])["state"], "succeeded")

    def test_cleanup_precedes_publication_when_existing_capacity_is_sufficient(self):
        self.local_photo()
        effects = self.publisher()
        m = self.prepare(
            photoUrls=["https://photos.google.com/photo/photo-a"],
            nonVital=True,
            reserveBytes=0,
        )
        self.assertEqual(
            [op["operation"] for op in m["operations"]],
            ["photo-details", "trash", "storage-quota", "upload-image"],
        )
        job = self.service.commit("alice", m["id"], m["sha256"])
        self.service.runner.run_once()
        self.assertEqual(len(effects), 1)
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "succeeded")

    def test_conflicting_content_is_never_deleted_and_published_in_one_plan(self):
        self.local_photo(
            "same-a", references=["https://photos.google.com/photo/photo-a"]
        )
        self.local_photo("same-b")
        self.publisher()
        job = self.service.prepare(
            "alice",
            {
                "photoUrls": ["https://photos.google.com/photo/photo-a"],
                "nonVital": True,
            },
        )
        self.service.runner.run_once()
        value = self.service.jobs.get(job["id"])
        self.assertIn(value["state"], ("failed", "partial"))
        self.assertIn("Conflicting", value["error"])
        self.assertFalse(any(x[0] == "trash" for x in self.remote.calls))

    def test_cached_request_recovery_does_not_replay_a_completed_cleanup(self):
        m = self.prepare(
            photoUrls=["https://photos.google.com/photo/photo-a"],
            nonVital=True,
            reserveBytes=0,
        )
        job = self.service.commit("alice", m["id"], m["sha256"])
        original = self.service.jobs.finish_step
        crashed = [False]

        def interrupt(ident, name, result):
            if name.endswith(":trash") and not crashed[0]:
                crashed[0] = True
                raise OSError("simulated crash after remote acknowledgement")
            return original(ident, name, result)

        self.service.jobs.finish_step = interrupt
        self.service.runner.run_once()
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "partial")
        self.service.jobs.finish_step = original
        self.service.jobs.retry(job["id"])
        self.service.runner.run_once()
        self.assertEqual(sum(op == "trash" for op, _, _ in self.remote.calls), 1)
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "succeeded")

    def test_selected_takeout_reference_can_bootstrap_a_verified_association_without_cloud_writes(
        self,
    ):
        record = self.local_photo(
            "11111111-1111-4111-8111-111111111111",
            raw=b"abcdefghij",
            references=["https://photos.google.com/photo/photo-a"],
        )
        sidecar = self.library.path(record["file"]["relative_path"] + ".photo.json")

        def downloaded():
            updated = json.loads(sidecar.read_bytes())
            updated["google_originals"] = [
                {
                    "account": "account-a",
                    "mediaKey": "photo-a",
                    "dedupKey": "dedup-a",
                    "sha256": record["file"]["sha256"],
                }
            ]
            atomic(sidecar, updated)
            self.library.put_index(updated, sidecar)
            return {
                "mediaKey": "photo-a",
                "recordId": record["record_id"],
                "sha256": record["file"]["sha256"],
                "bytes": 10,
                "outcome": "already-present",
                "retentionReady": False,
            }

        self.remote.download = downloaded
        m = self.prepare(photoUrls=["https://photos.google.com/photo/photo-a"])
        self.assertEqual(m["items"][0]["action"], "verify-original")
        self.assertEqual(
            [op["operation"] for op in m["operations"]],
            ["download-original", "storage-quota"],
        )
        job = self.service.commit("alice", m["id"], m["sha256"])
        self.service.runner.run_once()
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "succeeded")
        self.assertEqual(
            self.service.commit("alice", m["id"], m["sha256"])["id"], job["id"]
        )
        self.assertFalse(any(op == "trash" for op, _, _ in self.remote.calls))

    def test_resuming_after_read_only_resolution_never_reissues_the_unknown_write(self):
        manifest = self.prepare(
            photoUrls=["https://photos.google.com/photo/photo-a"], nonVital=True
        )
        self.remote.fail = "trash"
        job = self.service.commit("alice", manifest["id"], manifest["sha256"])
        self.service.runner.run_once()
        for value in self.remote.jobs.values():
            if value["state"] == "unknown":
                value["state"] = "succeeded"
        self.remote.fail = None
        self.service.resume("alice", job["id"])
        self.service.runner.run_once()
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "succeeded")
        self.assertEqual(sum(op == "trash" for op, _, _ in self.remote.calls), 1)

    def test_modified_stored_manifest_cannot_be_committed(self):
        manifest = self.prepare()
        path = self.service.path(manifest["id"])
        changed = copy.deepcopy(manifest)
        changed["operations"].reverse()
        changed["owner"] = "someone-else"
        atomic(path, changed)
        with self.assertRaises((Conflict, KeyError)):
            self.service.commit("alice", manifest["id"], manifest["sha256"])

    def test_incomplete_or_looping_inventory_never_produces_a_manifest(self):
        original = self.remote.enqueue_once

        def looping(owner, key, operation, value, confirmed=False, **kwargs):
            result = original(owner, key, operation, value, confirmed, **kwargs)
            if operation == "library-page":
                self.remote.jobs[key]["result"] = {
                    "items": [],
                    "next": "loop",
                    "complete": False,
                    "retentionReady": False,
                }
            return result

        self.remote.enqueue_once = looping
        job = self.service.prepare("alice", {})
        self.service.runner.run_once()
        value = self.service.jobs.get(job["id"])
        self.assertIn("Repeated", value["error"])
        self.assertFalse(self.service.path(job["id"]).exists())

    def test_account_above_limit_is_observed_and_publication_is_deferred(self):
        self.local_photo()
        effects = self.publisher()
        self.remote.used = 120
        m = self.prepare(reserveBytes=0)
        job = self.service.commit("alice", m["id"], m["sha256"])
        self.service.runner.run_once()
        value = self.service.jobs.get(job["id"])
        self.assertEqual(value["state"], "partial", value)
        self.assertEqual(value["result"]["deferred"][0]["reason"], "INSUFFICIENT_QUOTA")
        self.assertEqual(effects, [])


class ReconciliationHTTPTests(unittest.TestCase):
    def test_two_stage_api_requires_auth_csrf_exact_hash_and_owner(self):
        from fastapi.testclient import TestClient
        from photoflow_web.app import create_app

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "library"
            (root / ".photoflow").mkdir(parents=True)
            atomic(
                root / ".photoflow/library.json",
                {"schema_version": 2, "library_id": "test"},
            )
            app = create_app(
                root,
                Path(directory) / "state",
                auth=lambda d: {"ok": True, "uid": 123},
                role_resolver=lambda n: 3,
            )
            with TestClient(app, base_url="https://testserver") as client:
                service = app.state.google_reconciliation
                service.runner.close()
                service.runner.started = False
                service.runner.stopping.clear()
                service.remote = Remote()
                endpoint = "/api/v1/google/reconciliation"
                self.assertEqual(
                    client.post(endpoint + "/prepare", json={}).status_code, 401
                )
                login = client.post(
                    "/api/v1/auth/login",
                    headers={"Origin": "https://testserver"},
                    json={"username": "alice", "password": "secret"},
                ).json()
                headers = {
                    "Origin": "https://testserver",
                    "X-CSRF-Token": login["csrf"],
                }
                self.assertEqual(
                    client.post(endpoint + "/prepare", json={}).status_code, 403
                )
                response = client.post(endpoint + "/prepare", json={}, headers=headers)
                self.assertEqual(response.status_code, 202, response.text)
                job = response.json()
                service.runner.run_once()
                job = client.get(endpoint + "/jobs/" + job["id"]).json()
                ident = job["result"]["manifestId"]
                manifest = client.get(endpoint + "/manifests/" + ident)
                self.assertEqual(manifest.status_code, 200, manifest.text)
                self.assertEqual(manifest.headers["cache-control"], "no-store")
                download = client.get(endpoint + "/manifests/" + ident + "/download")
                self.assertEqual(download.status_code, 200, download.text)
                self.assertEqual(download.content, service.path(ident).read_bytes())

                self.assertEqual(
                    client.post(
                        endpoint + "/manifests/" + ident + "/commit",
                        json={"sha256": "0" * 64},
                        headers=headers,
                    ).status_code,
                    409,
                )
                accepted = client.post(
                    endpoint + "/manifests/" + ident + "/commit",
                    json={"sha256": manifest.json()["sha256"]},
                    headers=headers,
                )
                self.assertEqual(accepted.status_code, 202, accepted.text)
                self.assertFalse(
                    any(op == "trash" for op, _, _ in service.remote.calls)
                )
                client.post("/api/v1/auth/logout", headers=headers)
                client.post(
                    "/api/v1/auth/login",
                    headers={"Origin": "https://testserver"},
                    json={"username": "bob", "password": "secret"},
                )
                self.assertEqual(
                    client.get(endpoint + "/manifests/" + ident).status_code, 404
                )
