"""A sync pass observes current state; interrupted passes need no per-write repair."""

import unittest
import test_google_takeout_sweep as takeout


class GoogleSyncTests(unittest.TestCase):
    setUp = takeout.TakeoutSweepTests.setUp
    local_photo = takeout.TakeoutSweepTests.local_photo
    candidate = takeout.TakeoutSweepTests.candidate
    prepare = takeout.TakeoutSweepTests.prepare
    sweep = takeout.TakeoutSweepTests.sweep

    def configure(self):
        enqueue = self.remote.enqueue_once
        self.remote.enqueue_once = lambda *args, retention_scope=None, **kwargs: (
            enqueue(*args, **kwargs)
        )
        self.remote.sweep_counts = lambda owner, ident: {
            "processed": 0,
            "trashed": 0,
            "kept": 0,
            "active": 0,
        }

    def drain(self, ident):
        for _ in range(20):
            if not self.service.runner.run_once():
                self.now += 2
            job = self.service.jobs.get(ident)
            if job["state"] in ("succeeded", "failed", "partial"):
                return job
        self.fail("Preparation did not finish")

    def test_prepare_sync_automatically_builds_review_without_google_writes(self):
        self.configure()
        self.candidate()
        command = self.service.sync.prepare("alice")
        self.assertEqual(self.service.sync.prepare("alice")["id"], command["id"])
        self.assertEqual(self.drain(command["id"])["state"], "succeeded")
        view = self.service.sync.status("alice")
        self.assertEqual(view["state"], "review")
        self.assertEqual(view["review"]["trash"], 1)
        self.assertEqual(view["review"]["keep"], 0)
        self.assertTrue(all(op != "trash" for op, _, _ in self.remote.calls))
        self.assertEqual(
            view["review"]["sha256"],
            self.service.manifest("alice", view["review"]["manifestId"])["sha256"],
        )
        self.now = view["review"]["expiresAt"] + 1
        self.assertEqual(self.service.sync.status("alice")["state"], "expired")

    def test_unknown_history_does_not_block_fresh_read_only_preparation(self):
        self.configure()
        self.candidate()
        manifest = self.sweep(self.prepare())
        self.remote.fail = "trash"
        old = self.service.commit("alice", manifest["id"], manifest["sha256"])
        self.service.runner.run_once()
        self.assertEqual(self.service.jobs.get(old["id"])["state"], "partial")
        self.remote.fail = None
        before = len([op for op, _, _ in self.remote.calls if op == "trash"])
        job = self.service.sync.prepare("alice")
        self.assertEqual(self.drain(job["id"])["state"], "succeeded")
        self.assertEqual(self.service.sync.status("alice")["state"], "review")
        self.assertEqual(sum(op == "trash" for op, _, _ in self.remote.calls), before)
        self.assertTrue(any(j["state"] == "unknown" for j in self.remote.jobs.values()))

    def test_existing_production_run_is_visible_with_actual_trash_and_keep_counts(self):
        self.configure()
        self.candidate()
        manifest = self.sweep(self.prepare())
        run = self.service.commit("alice", manifest["id"], manifest["sha256"])
        self.remote.sweep_counts = lambda owner, ident: {
            "processed": 1,
            "trashed": 0,
            "kept": 1,
            "active": 0,
        }
        view = self.service.sync.status("alice")
        self.assertEqual(view["state"], "running")
        self.assertEqual(view["jobId"], run["id"])
        self.assertEqual(view["progress"]["processed"], 1)
        self.assertEqual(view["totals"]["retained"], 1)
        self.assertEqual(view["totals"]["trashed"], 0)

    def test_sync_commands_require_owner_authority(self):
        self.configure()
        self.service.authorize = lambda owner: False
        with self.assertRaises(ValueError):
            self.service.sync.prepare("alice")

    def test_explicit_pause_is_durable_and_does_not_issue_the_pending_removal(self):
        self.configure()
        self.candidate()
        manifest = self.sweep(self.prepare())
        enqueue = self.remote.enqueue_once
        self.remote.enqueue_once = lambda *args, retention_scope=None, **kwargs: (
            enqueue(*args, **kwargs)
        )
        run = self.service.commit("alice", manifest["id"], manifest["sha256"])
        self.service.pause("alice", run["id"])
        self.service.runner.run_once()
        paused = self.service.jobs.get(run["id"])
        self.assertEqual(paused["state"], "partial")
        self.assertTrue(paused["sync_paused"])
        self.assertFalse(any(op == "trash" for op, _, _ in self.remote.calls))
        fresh = self.service.sync.prepare("alice")
        self.assertEqual(self.drain(fresh["id"])["state"], "succeeded")
        self.assertEqual(self.service.jobs.get(run["id"])["state"], "partial")
        self.assertFalse(any(op == "trash" for op, _, _ in self.remote.calls))

    def test_unverified_local_candidates_are_counted_as_retained(self):
        self.configure()
        self.local_photo(references=["https://photos.google.com/photo/photo-a"])
        job = self.service.sync.prepare("alice")
        self.assertEqual(self.drain(job["id"])["state"], "succeeded")
        view = self.service.sync.status("alice")
        self.assertEqual(view["review"]["trash"], 0)
        self.assertEqual(view["review"]["keep"], 1)

    def test_only_one_reviewed_production_pass_can_run_at_a_time(self):
        self.configure()
        self.candidate()
        first = self.sweep(self.prepare())
        second = self.sweep(self.prepare())
        run = self.service.commit("alice", first["id"], first["sha256"])
        self.assertEqual(
            self.service.commit("alice", first["id"], first["sha256"])["id"], run["id"]
        )
        with self.assertRaises(ValueError):
            self.service.commit("alice", second["id"], second["sha256"])
        with self.assertRaises(ValueError):
            self.service.sync.prepare("alice")

    def test_missing_local_original_does_not_block_fresh_inventory_and_is_kept(self):
        self.configure()
        record = self.candidate()
        (self.library.root / record["file"]["relative_path"]).unlink()
        job = self.service.sync.prepare("alice")
        self.assertEqual(self.drain(job["id"])["state"], "succeeded")
        view = self.service.sync.status("alice")
        self.assertEqual(view["review"]["trash"], 0)
        self.assertEqual(view["review"]["keep"], 1)
        self.assertFalse(any(op == "trash" for op, _, _ in self.remote.calls))

    def test_legacy_queued_production_plan_migrates_to_paused_without_dispatch(self):
        self.configure()
        self.candidate()
        manifest = self.sweep(self.prepare())
        run = self.service.commit("alice", manifest["id"], manifest["sha256"])
        params = dict(run["params"])
        params.pop("passVersion")
        self.service.jobs.update(run["id"], params=params)
        self.service.runner.run_once()
        self.assertEqual(self.service.jobs.get(run["id"])["state"], "partial")
        self.assertEqual(self.service.sync.status("alice")["state"], "paused")
        self.assertTrue(self.service.sync.status("alice")["paused"])
        self.assertFalse(any(op == "trash" for op, _, _ in self.remote.calls))
