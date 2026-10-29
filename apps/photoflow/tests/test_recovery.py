import json
import unittest

from photoflow.model import PENDING, SIDECAR
from tests import test_service as service_tests


class JournalTests(unittest.TestCase):
    def harness(self):
        harness = service_tests.ServiceTests()
        harness.setUp()
        return harness

    def test_each_move_boundary_recovers_with_one_completion_event(self):
        for boundary in ('journal', 'linked', 'moved', 'new-sidecar', 'old-sidecar', 'complete'):
            with self.subTest(boundary=boundary):
                h = self.harness()
                h.fs.put('inbox/a.jpg', b'photo')
                fired = []

                def fail(operation, path):
                    hit = ((boundary == 'journal' and operation == 'move')
                        or (boundary == 'linked' and operation == 'linked')
                        or (boundary == 'moved' and operation == 'moved')
                        or (boundary == 'new-sidecar' and operation == 'write' and path.startswith('undated/'))
                        or (boundary == 'old-sidecar' and operation == 'remove' and path == 'inbox/a.jpg' + SIDECAR)
                        or (boundary == 'complete' and operation == 'remove' and path.startswith(PENDING)))
                    if hit and not fired:
                        fired.append(True)
                        raise OSError('simulated power loss')

                h.fs.fail_on = fail
                failed = h.run_pass()
                self.assertTrue(failed.errors)
                self.assertTrue(h.fs.list_files(PENDING))
                h.fs.fail_on = None
                recovered = h.run_pass()
                self.assertFalse(recovered.errors, recovered.errors)
                self.assertEqual(recovered.recovered, 1)
                record, = h.records()
                self.assertEqual(sum(e['type'] == 'moved' for e in record['history']), 1)
                self.assertEqual(sum(data == b'photo' for data in h.fs.data.values()), 1)
                self.assertFalse(h.fs.list_files(PENDING))
                self.assertEqual(h.run_pass().moved, 0)

    def test_recovery_keeps_conflicting_destination_and_journal(self):
        h = self.harness()
        h.fs.put('inbox/a.jpg', b'photo')
        def fail(operation, path):
            if operation == 'move':
                raise OSError('stop after intent')
        h.fs.fail_on = fail
        h.run_pass()
        h.fs.fail_on = None
        journal, = h.fs.list_files(PENDING)
        intent = json.loads(h.fs.data[journal])
        h.fs.put(intent['target'], b'foreign photo')
        result = h.run_pass()
        self.assertTrue(result.errors)
        self.assertIn(journal, h.fs.data)
        self.assertEqual(h.fs.data[intent['target']], b'foreign photo')
        self.assertEqual(h.fs.data['inbox/a.jpg'], b'photo')

    def test_readonly_preview_does_not_recover_or_mutate_pending_operations(self):
        h = self.harness()
        h.fs.put('inbox/a.jpg', b'photo')
        h.fs.fail_on = lambda op, path: (_ for _ in ()).throw(OSError('stop')) if op == 'move' else None
        h.run_pass()
        h.fs.fail_on = None
        before = dict(h.fs.data)
        result = h.run_pass(dry_run=True)
        self.assertTrue(result.errors)
        self.assertEqual(before, h.fs.data)

    def test_metadata_only_run_requires_explicit_move_recovery(self):
        h = self.harness()
        h.fs.put('inbox/a.jpg', b'photo')
        def stop(operation, path):
            if operation == 'move':
                raise OSError('stop after intent')
        h.fs.fail_on = stop
        h.run_pass()
        h.fs.fail_on = None
        before = dict(h.fs.data)
        result = h.run_pass(move_files=False)
        self.assertTrue(result.errors)
        self.assertEqual(before, h.fs.data)
