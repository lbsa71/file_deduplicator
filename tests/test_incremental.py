import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from photoflow.model import MARKER, SIDECAR
from photoflow.runner import Config, Runner
from tests.fakes import FakeClock, FakeIds, MemoryFS, MetadataReader


class TrackingFS(MemoryFS):
    def __init__(self):
        super().__init__()
        self.reads, self.writes, self.scans = [], [], []

    def read_bytes(self, path):
        self.reads.append(path)
        return super().read_bytes(path)

    def atomic_write(self, path, data, *, replace=True):
        self.writes.append(path)
        return super().atomic_write(path, data, replace=replace)

    def inventory(self, prefix=''):
        self.scans.append(prefix)
        return super().inventory(prefix)


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.fs = TrackingFS()
        self.clock = FakeClock(datetime(2026, 10, 29, tzinfo=timezone.utc))
        self.ids, self.reader = FakeIds(), MetadataReader()
        self.source = 'inbox/album/photo.jpg.supplemental-metadata.json'
        self.fs.put(MARKER, b'{"schema_version":1,"library_id":"incremental-test"}')
        self.fs.put('inbox/album/photo.jpg', b'photo')
        self.fs.put(self.source, b'{"people":[{"name":"Alma"}],"unknown":[1,2]}')

    def run_pass(self, **options):
        return Runner(self.fs, self.clock, self.ids, self.reader,
                      Config(settle_seconds=0, **options)).run()

    def warm(self):
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.clock.value += timedelta(hours=1)
        self.fs.reads.clear(); self.fs.writes.clear(); self.fs.scans.clear()

    def record(self):
        path, = [p for p in self.fs.data if p.endswith(SIDECAR)]
        return path, json.loads(self.fs.data[path])

    def test_unchanged_writable_pass_does_not_rewrite_sidecars_or_reread_sources(self):
        self.warm()
        path, _ = self.record()
        before = self.fs.data[path]
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertEqual(self.fs.data[path], before)
        self.assertNotIn(self.source, self.fs.reads)
        self.assertEqual(self.fs.writes, ['.photoflow/last-run.json'])
        self.assertEqual((result.hashed, result.metadata_extracted, result.moved), (0, 0, 0))
        self.assertEqual((result.source_cache_hits, result.source_cache_misses), (1, 0))
        report = json.loads(self.fs.data['.photoflow/last-run.json'])
        self.assertEqual(report['processed'], 1)
        self.assertEqual(report['completed_at'], '2026-10-29T01:00:00Z')

    def test_one_combined_library_scan_includes_empty_directories(self):
        self.fs.mkdir('old/empty')
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertEqual(self.fs.scans.count(''), 1)
        self.assertIn('old/empty', result.removed_directories)
        self.assertIn('old', result.removed_directories)

    def test_changed_source_invalidates_only_its_metadata(self):
        self.warm()
        self.fs.put(self.source, b'{"people":[{"name":"Lisa"}],"unknown":[3,4]}')
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertEqual((result.hashed, result.metadata_extracted), (0, 0))
        self.assertEqual((result.source_cache_hits, result.source_cache_misses), (0, 1))
        _, record = self.record()
        self.assertEqual(record['resolved']['people'], ['Lisa'])
        self.assertEqual(len(record['sources'][0]['documents']), 2)

    def test_verify_bypasses_cache_even_with_unchanged_stat_information(self):
        self.warm()
        self.fs.data[self.source] = self.fs.data[self.source].replace(b'Alma', b'Lisa')
        result = self.run_pass(verify=True)
        self.assertFalse(result.errors, result.errors)
        self.assertIn(self.source, self.fs.reads)
        self.assertEqual(self.record()[1]['resolved']['people'], ['Lisa'])

    def test_corrupt_cache_is_rebuilt_from_original_json(self):
        self.warm()
        cache, = [p for p in self.fs.data if p.startswith('.photoflow/source-cache/')]
        self.fs.put(cache, b'invalid cache')
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertIn(self.source, self.fs.reads)
        self.assertEqual(self.record()[1]['resolved']['people'], ['Alma'])
        self.assertTrue(any('source_cache_ignored' in w for w in result.warnings))

    def test_bad_current_source_is_not_hidden_by_a_previous_good_cache(self):
        self.warm()
        self.fs.put(self.source, b'invalid current source')
        result = self.run_pass()
        self.assertTrue(result.errors)
        self.assertIn(self.source, self.fs.reads)

    def test_source_changed_while_loading_cache_is_deferred(self):
        self.warm()
        original = self.fs.read_bytes
        def change_after_cache_read(path):
            data = original(path)
            if path.startswith('.photoflow/source-cache/'):
                self.fs.put(self.source, b'{"people":[{"name":"Lisa"}]}')
            return data
        with patch.object(self.fs, 'read_bytes', side_effect=change_after_cache_read):
            result = self.run_pass()
        self.assertEqual(result.deferred, 1)
        self.assertEqual(result.moved, 0)

    def test_foreign_or_modified_cache_payload_never_supplies_annotations(self):
        self.warm()
        cache, = [p for p in self.fs.data if p.startswith('.photoflow/source-cache/')]
        valid = self.fs.data[cache]
        for corruption in ('library_id', 'document', 'nonfinite_document'):
            with self.subTest(corruption=corruption):
                value = json.loads(valid)
                if corruption == 'library_id':
                    value['library_id'] = 'another-library'
                elif corruption == 'document':
                    value['entries'][self.source]['document']['people'] = [{'name': 'wrong person'}]
                else:
                    value['entries'][self.source]['document']['unknown'] = float('nan')
                self.fs.put(cache, json.dumps(value).encode())
                self.fs.reads.clear()
                result = self.run_pass()
                self.assertFalse(result.errors, result.errors)
                self.assertIn(self.source, self.fs.reads)
                self.assertEqual(self.record()[1]['resolved']['people'], ['Alma'])

    def test_cold_preview_writes_neither_cache_nor_run_report(self):
        before = copy.deepcopy(self.fs.data)
        result = self.run_pass(dry_run=True)
        self.assertFalse(result.errors, result.errors)
        self.assertEqual(self.fs.data, before)
        self.assertEqual(self.fs.writes, [])

    def test_audit_every_scan_still_persists_requested_events(self):
        self.warm()
        path, before = self.record()
        result = self.run_pass(audit_every_scan=True)
        self.assertFalse(result.errors, result.errors)
        self.assertIn(path, self.fs.writes)
        self.assertEqual(sum(e['type'] == 'scanned' for e in self.record()[1]['history']),
                         sum(e['type'] == 'scanned' for e in before['history']) + 1)
