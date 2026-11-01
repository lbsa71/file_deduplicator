import copy, hashlib, json, unittest
import test_google_reconciliation as fixtures
from photoflow_web.core import atomic


class TakeoutSweepTests(unittest.TestCase):
    setUp = fixtures.ReconciliationTests.setUp
    local_photo = fixtures.ReconciliationTests.local_photo
    prepare = fixtures.ReconciliationTests.prepare

    def candidate(self):
        record = self.local_photo(
            references=["https://photos.google.com/photo/photo-a"]
        )
        doc = {
            "url": "https://photos.google.com/photo/photo-a",
            "title": "original.jpg",
        }
        raw = json.dumps(doc).encode()
        path = self.library.root / "inbox/takeout.json"
        path.write_bytes(raw)
        source = record["sources"][0]
        source["original_filename"] = "original.jpg"
        source["documents"] = [
            {
                "document": doc,
                "relative_path": "inbox/takeout.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ]
        sidecar = self.library.root / (record["file"]["relative_path"] + ".photo.json")
        atomic(sidecar, record)
        self.library.put_index(record, sidecar)
        return record

    def sweep(self, source):
        job = self.service.prepare_takeout("alice", source["id"])
        self.service.runner.run_once()
        done = self.service.jobs.get(job["id"])
        self.assertEqual(done["state"], "succeeded", done)
        return self.service.manifest("alice", job["id"])

    def test_exact_verified_takeout_candidate_can_execute_with_distinct_authority(self):
        self.candidate()
        source = self.prepare()
        sweep = self.sweep(source)
        self.assertEqual(sweep["counts"]["actions"]["takeout-trash"], 1)
        self.assertTrue(sweep["capabilities"]["productionRetention"])
        self.assertFalse(sweep["retentionPolicy"]["backupVerified"])
        self.assertEqual(
            sweep["operations"][0]["authority"], "owner-authorized-takeout-retention"
        )
        original = self.remote.enqueue_once
        scopes = []

        def enqueue(*args, retention_scope=None, **kwargs):
            scopes.append(retention_scope)
            return original(*args, **kwargs)

        self.remote.enqueue_once = enqueue
        job = self.service.commit("alice", sweep["id"], sweep["sha256"])
        self.service.runner.run_once()
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "succeeded")
        self.assertEqual(scopes[0]["manifestSha256"], sweep["sha256"])

    def test_remote_only_and_motion_and_ambiguous_are_retained(self):
        self.assertEqual(self.sweep(self.prepare())["operations"], [])
        self.candidate()
        self.remote.photo["companion"] = True
        self.assertEqual(self.sweep(self.prepare())["operations"], [])

    def test_local_corruption_cannot_authorize_or_execute(self):
        record = self.candidate()
        source = self.prepare()
        path = self.library.root / record["file"]["relative_path"]
        path.write_bytes(b"bad")
        self.assertEqual(self.sweep(source)["operations"], [])

    def test_preserved_document_required(self):
        self.candidate()
        source = self.prepare()
        (self.library.root / "inbox/takeout.json").unlink()
        self.assertEqual(self.sweep(source)["operations"], [])

    def test_changed_bytes_after_review_stop_before_trash(self):
        record = self.candidate()
        sweep = self.sweep(self.prepare())
        job = self.service.commit("alice", sweep["id"], sweep["sha256"])
        (self.library.root / record["file"]["relative_path"]).write_bytes(b"bad")
        self.service.runner.run_once()
        self.assertNotEqual(self.service.jobs.get(job["id"])["state"], "succeeded")
        self.assertFalse(any(op == "trash" for op, _, _ in self.remote.calls))

    def test_ambiguous_local_copies_are_kept(self):
        self.candidate()
        self.local_photo(
            "different",
            b"different",
            references=["https://photos.google.com/photo/photo-a"],
        )
        self.assertEqual(self.sweep(self.prepare())["operations"], [])

    def test_local_filename_and_document_title_must_be_present(self):
        record = self.candidate()
        source = record["sources"][0]
        source["original_filename"] = ""
        source["documents"][0]["document"]["title"] = ""
        raw = json.dumps(source["documents"][0]["document"]).encode()
        (self.library.root / "inbox/takeout.json").write_bytes(raw)
        source["documents"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
        sidecar = self.library.root / (record["file"]["relative_path"] + ".photo.json")
        atomic(sidecar, record)
        self.library.put_index(record, sidecar)
        self.assertEqual(self.sweep(self.prepare())["operations"], [])

    def test_dispatch_rechecks_reviewed_manifest_and_current_original(self):
        record = self.candidate()
        sweep = self.sweep(self.prepare())
        op = sweep["operations"][0]
        scope = {
            "purpose": op["authority"],
            "manifestId": sweep["id"],
            "manifestSha256": sweep["sha256"],
            "photoKey": op["expect"]["mediaKey"],
            "dedupKey": op["expect"]["dedupKey"],
            "localSha256": op["localEvidence"]["sha256"],
        }
        self.assertTrue(self.service.retention_check("alice", "account-a", scope))
        with self.assertRaises(ValueError):
            self.service.retention_check("alice", "wrong-account", scope)
        (self.library.root / record["file"]["relative_path"]).write_bytes(b"bad")
        with self.assertRaises(ValueError):
            self.service.retention_check("alice", "account-a", scope)

    def test_expired_sweep_resume_requires_fresh_inventory_without_replaying_writes(
        self,
    ):
        self.candidate()
        sweep = self.sweep(self.prepare())
        enqueue = self.remote.enqueue_once

        def remote(*args, retention_scope=None, **kwargs):
            return enqueue(*args, **kwargs)

        self.remote.enqueue_once = remote
        self.remote.fail = "trash"
        job = self.service.commit("alice", sweep["id"], sweep["sha256"])
        self.service.runner.run_once()
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "partial")
        calls = copy.deepcopy(self.remote.calls)
        self.now = sweep["expiresAt"] + 1
        with self.assertRaisesRegex(ValueError, "fresh full inventory"):
            self.service.resume("alice", job["id"])
        self.assertEqual(self.remote.calls, calls)
        self.assertEqual(self.service.jobs.get(job["id"])["state"], "partial")
