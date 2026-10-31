import tempfile, threading, time, unittest
from pathlib import Path
from photoflow_web.jobs import JobCoordinator, JobStore, Cancelled


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = JobStore(Path(self.temp.name), 'library-a')
        self.allowed = True
        self.available = True
        self.effects = []
        def execute(job, context):
            return [context.step(str(index), lambda index=index: self.effects.append(index) or index,
                                 replay_safe=True) for index in job['params']['items']]
        self.execute = execute
        self.runner = JobCoordinator(self.store, execute, lambda job: self.allowed,
                                     lambda: self.available)
        self.addCleanup(self.runner.close)

    def test_queued_commands_and_results_survive_a_new_coordinator(self):
        job = self.runner.enqueue('alice', 'test', {'items':[0,1]})
        self.assertEqual(self.effects, [])
        reopened = JobStore(Path(self.temp.name), 'library-a')
        next_runner = JobCoordinator(reopened, self.execute, lambda job: True, lambda: True)
        self.addCleanup(next_runner.close)
        self.assertTrue(next_runner.run_once())
        result = reopened.get(job['id'])
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(result['result'], [0,1])
        self.assertEqual(self.effects, [0,1])
        self.assertFalse(next_runner.run_once())

    def test_cancel_queued_job_has_no_effect_and_retry_preserves_identity(self):
        job = self.runner.enqueue('alice', 'test', {'items':[0,1]})
        self.store.cancel(job['id'])
        self.assertFalse(self.runner.run_once())
        self.assertEqual(self.effects, [])
        retried = self.store.retry(job['id'])
        self.assertEqual(retried['id'], job['id'])
        self.assertEqual(retried['attempt'], 2)
        self.runner.run_once()
        self.assertEqual(self.effects, [0,1])

    def test_running_cancellation_commits_one_step_and_retry_only_runs_remaining_steps(self):
        entered, release = threading.Event(), threading.Event()
        def execute(job, context):
            def first():
                self.effects.append(0); entered.set(); release.wait(5); return 0
            return [context.step('0', first, replay_safe=True),
                    context.step('1', lambda: self.effects.append(1) or 1, replay_safe=True)]
        self.runner.execute = execute
        job = self.runner.enqueue('alice', 'test', {'items':[0,1]})
        thread = threading.Thread(target=self.runner.run_once)
        thread.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.store.cancel(job['id'])['state'], 'cancelling')
        release.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.store.get(job['id'])['state'], 'cancelled')
        self.assertEqual(self.effects, [0])
        self.store.retry(job['id']); self.runner.run_once()
        self.assertEqual(self.effects, [0,1])
        self.assertEqual(self.store.get(job['id'])['result'], [0,1])

    def test_revoked_authority_and_missing_storage_never_execute(self):
        job = self.runner.enqueue('alice', 'test', {'items':[0]})
        self.allowed = False
        self.runner.run_once()
        self.assertEqual(self.store.get(job['id'])['error_code'], 'AUTHORITY_REVOKED')
        self.assertEqual(self.effects, [])
        self.allowed = True
        self.store.retry(job['id'])
        self.available = False
        self.runner.run_once()
        value = self.store.get(job['id'])
        self.assertEqual(value['state'], 'queued')
        self.assertEqual(value['waiting_reason'], 'waiting_for_storage')
        self.assertEqual(self.effects, [])

    def test_same_idempotency_key_reuses_command_and_rejects_different_intent(self):
        first = self.runner.enqueue('alice', 'test', {'items':[0]}, key='request-a')
        same = self.runner.enqueue('alice', 'test', {'items':[0]}, key='request-a')
        self.assertEqual(first['id'], same['id'])
        with self.assertRaises(ValueError):
            self.runner.enqueue('alice', 'test', {'items':[1]}, key='request-a')
        self.runner.run_once()
        self.assertEqual(self.effects, [0])

    def test_interrupted_step_requires_reconciliation_before_replay(self):
        job = self.runner.enqueue('alice', 'test', {'items':[0]})
        claimed = self.store.claim()
        self.store.start_step(job['id'], '0')
        self.store.recover()
        self.runner.execute = lambda job, context: context.step('0', lambda: self.effects.append(0))
        self.runner.run_once()
        self.assertEqual(self.effects, [])
        self.assertEqual(self.store.get(job['id'])['error_code'], 'RECONCILIATION_REQUIRED')
        self.store.retry(job['id'])
        self.runner.execute = lambda job, context: context.step('0', lambda: self.effects.append(0), recover=lambda: (True, 'already-committed'))
        self.runner.run_once()
        self.assertEqual(self.store.get(job['id'])['result'], 'already-committed')
        self.assertEqual(self.effects, [])

    def test_events_are_atomic_replayable_and_hide_other_users_private_work(self):
        self.runner.enqueue('alice', 'export', {'items':[]}, private=True)
        public = self.runner.enqueue('alice', 'test', {'items':[]})
        events = self.store.events('bob', False, 0)
        self.assertEqual([item['data']['job_id'] for item in events['items']], [public['id']])
        self.assertEqual(len(self.store.events('alice', False, 0)['items']), 2)
        self.assertEqual(len(self.store.events('bob', True, 0)['items']), 2)
