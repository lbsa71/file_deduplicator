import json, subprocess, tempfile, unittest
from pathlib import Path
from photoflow_web.google_workers import WorkerStore


class JobTypesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000
        self.store = WorkerStore(
            Path(self.tmp.name), now=lambda: self.now, test_account="sandbox"
        )
        self.pair("sandbox")

    def tearDown(self):
        self.tmp.cleanup()

    def pair(self, account):
        code = self.store.pairing("alice", account)
        self.paired = self.store.pair(code["code"], account)
        self.worker = self.store.authenticate(self.paired["token"], account)

    def test_mirror_matches_the_javascript_contract_source(self):
        root = Path(__file__).resolve().parents[3]
        subprocess.run(
            ["node", "packages/google-photos/tools/sync-job-contracts.mjs", "--check"],
            cwd=root,
            check=True,
            capture_output=True,
        )

    def test_invalid_targets_operations_and_confirmation_never_queue(self):
        for operation, value in [
            ("photo-details", {"photoUrl": "https://evil.invalid/photo/x"}),
            ("location-set", {}),
            ("trash", {"photoUrl": "https://photos.google.com/photo/a"}),
        ]:
            with self.assertRaises(ValueError):
                self.store.enqueue("alice", operation, value)
        self.assertEqual(self.store.status("alice")["jobs"], [])
        with self.assertRaises(ValueError):
            self.store.enqueue("alice", "unknown", {})

    def test_batch_is_atomic_and_personal_accounts_remain_read_only(self):
        self.pair("personal")
        with self.assertRaises(ValueError):
            self.store.suite(
                "alice",
                [
                    {"operation": "storage-quota", "input": {}},
                    {
                        "operation": "trash",
                        "input": {"photoUrl": "https://photos.google.com/photo/a"},
                    },
                ],
                True,
            )
        self.assertEqual(self.store.status("alice")["jobs"], [])

    def test_batch_continues_independent_reads_and_blocks_dependent_writes(self):
        suite = self.store.suite(
            "alice",
            [
                {
                    "operation": "photo-details",
                    "input": {"photoUrl": "https://photos.google.com/photo/a"},
                },
                {
                    "operation": "favorite-set",
                    "input": {
                        "photoUrl": "https://photos.google.com/photo/a",
                        "value": True,
                    },
                },
                {"operation": "storage-quota", "input": {}},
            ],
            True,
        )
        first = self.store.claim(self.worker["id"])
        self.store.finish(
            self.worker["id"], first["id"], first["lease"], error="PROTOCOL"
        )
        second = self.store.claim(self.worker["id"])
        self.assertEqual(second["operation"], "storage-quota")
        self.assertEqual(self.store.status("alice")["jobs"][1]["state"], "blocked")

    def test_write_scope_is_exact_and_uncertainty_survives_repair(self):
        job = self.store.enqueue(
            "alice",
            "favorite-set",
            {"photoUrl": "https://photos.google.com/photo/a", "value": True},
            True,
        )
        dispatched = self.store.claim(self.worker["id"])
        self.assertEqual(dispatched["testScope"]["photoKey"], "a")
        self.assertEqual(dispatched["testScope"]["account"], "sandbox")
        self.store.disconnect(self.worker["id"])
        self.assertEqual(self.store.status("alice")["jobs"][0]["state"], "unknown")
        self.pair("sandbox")
        with self.assertRaises(ValueError):
            self.store.enqueue(
                "alice",
                "trash",
                {"photoUrl": "https://photos.google.com/photo/a"},
                True,
            )
        self.store.enqueue("alice", "reconcile-write", {"originalJobId": job["id"]})
        read = self.store.claim(self.worker["id"])
        self.assertEqual(read["operation"], "reconcile-write")
        self.store.finish(
            self.worker["id"],
            read["id"],
            read["lease"],
            {"originalJobId": job["id"], "verified": True, "retentionReady": False},
        )
        self.assertEqual(self.store.status("alice")["jobs"][1]["state"], "succeeded")

    def test_expired_write_never_becomes_retryable(self):
        self.store.enqueue(
            "alice", "trash", {"photoUrl": "https://photos.google.com/photo/a"}, True
        )
        self.store.claim(self.worker["id"])
        self.now += 601
        self.store.claim(self.worker["id"])
        self.assertEqual(self.store.status("alice")["jobs"][0]["state"], "unknown")

    def test_result_validation_and_diagnostics_do_not_expose_google_ids(self):
        self.store.enqueue("alice", "library-page", {})
        job = self.store.claim(self.worker["id"])
        item = {
            "namespace": "library-media",
            "mediaKey": "PRIVATE_ID",
            "dedupKey": "PRIVATE_DEDUP",
            "favorite": None,
            "trashTimestamp": None,
            "companion": None,
        }
        result = {
            "items": [item],
            "next": None,
            "complete": True,
            "retentionReady": False,
        }
        self.store.finish(self.worker["id"], job["id"], job["lease"], result)
        self.assertEqual(self.store.result("alice", job["id"])["result"], result)
        self.assertNotIn(
            "PRIVATE_", json.dumps(self.store.diagnostic("alice", job["id"]))
        )

    def test_duplicate_completion_is_idempotent_but_changed_results_are_rejected(self):
        self.store.enqueue("alice")
        job = self.store.claim(self.worker["id"])
        value = {
            "photos": 1,
            "favorites": 0,
            "albums": 0,
            "complete": True,
            "retentionReady": False,
        }
        self.store.finish(self.worker["id"], job["id"], job["lease"], value)
        self.store.finish(self.worker["id"], job["id"], job["lease"], value)
        with self.assertRaises(ValueError):
            self.store.finish(
                self.worker["id"], job["id"], job["lease"], {**value, "photos": 2}
            )
