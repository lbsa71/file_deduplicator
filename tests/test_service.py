import hashlib
import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from photoflow.model import SIDECAR
from photoflow.runner import Config, Runner
from tests.fakes import FakeClock, FakeIds, MemoryFS, MetadataReader


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.fs = MemoryFS()
        self.clock = FakeClock(datetime(2026, 10, 28, 12, tzinfo=timezone.utc))
        self.ids = FakeIds()
        self.reader = MetadataReader()
        self.fs.put('.photoflow/library.json', json.dumps({
            'schema_version': 1, 'library_id': 'test-library'}).encode())

    def run_pass(self, **kwargs):
        return Runner(self.fs, self.clock, self.ids, self.reader,
                      Config(settle_seconds=0, **kwargs)).run()

    def records(self):
        return [json.loads(data) for path, data in self.fs.data.items()
                if path.endswith(SIDECAR)]

    def test_new_file_has_identity_source_history_and_convergent_location(self):
        self.fs.put('inbox/Christmas at Grandma.jpg', b'photo')
        first = self.run_pass()
        second = self.run_pass()
        record, = self.records()
        self.assertEqual(first.moved, 1)
        self.assertEqual(second.moved, 0)
        self.assertEqual(second.hashed, 0)
        self.assertEqual(len(self.reader.calls), 1)
        self.assertEqual(record['sources'][0]['original_filename'], 'Christmas at Grandma.jpg')
        self.assertEqual(record['file']['relative_path'], f"undated/{record['record_id']}.jpg")
        self.assertEqual(record['file']['sha256'], hashlib.sha256(b'photo').hexdigest())
        self.assertEqual(sum(e['type'] == 'moved' for e in record['history']), 1)
        self.assertEqual(sum(e['type'] == 'processed' for e in record['history']), 1)

    def test_takeout_raw_people_album_and_date_survive(self):
        self.fs.put('inbox/Alma/IMG_0187.JPG', b'photo')
        raw = {'photoTakenTime': {'timestamp': '1545652800'},
               'people': [{'name': 'Alma'}], 'unknown': {'nested': [1, 2]}}
        self.fs.put('inbox/Alma/IMG_0187.JPG.supplemental-metadata.json', json.dumps(raw).encode())
        self.fs.put('inbox/Alma/metadata.json', b'{"title":"Family album"}')
        self.run_pass()
        record, = self.records()
        self.assertEqual(record['resolved']['people'], ['Alma'])
        self.assertEqual(record['resolved']['albums'], ['Family album'])
        self.assertTrue(record['file']['relative_path'].startswith('photos/2018/12/'))
        self.assertEqual(record['sources'][0]['documents'][0]['document'], raw)
        self.assertEqual(self.fs.data['inbox/Alma/metadata.json'], b'{"title":"Family album"}')

    def test_sidecar_puts_aggregated_metadata_before_sources_and_history(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.fs.put('inbox/a.jpg.json', b'{"people":[{"name":"Alma"}]}')
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        record, = self.records()
        keys = list(record)
        self.assertEqual(record['resolved']['people'], ['Alma'])
        self.assertLess(keys.index('resolved'), keys.index('sources'))
        self.assertEqual(keys[-1], 'history')

    def test_late_metadata_enriches_moved_file_without_reextracting(self):
        self.fs.put('inbox/IMG.jpg', b'photo')
        self.run_pass()
        self.fs.put('inbox/IMG.jpg.supplemental-metadata.json', b'{"people":[{"name":"Alma"}]}')
        result = self.run_pass()
        record, = self.records()
        self.assertEqual(record['resolved']['people'], ['Alma'])
        self.assertEqual(result.hashed, 0)
        self.assertEqual(len(self.reader.calls), 1)

    def test_new_duplicate_matches_cached_file_and_keeps_all_names(self):
        self.fs.put('inbox/IMG.jpg', b'photo')
        self.run_pass()
        original_id = self.records()[0]['record_id']
        self.fs.put('inbox/Christmas.jpg', b'photo')
        metadata = {'people': [{'name': 'Alma'}], 'unknown': {'retained': [1, 2, 3]}}
        self.fs.put('inbox/Christmas.jpg.supplemental-metadata.json', json.dumps(metadata).encode())
        result = self.run_pass()
        records = self.records()
        keeper = next(r for r in records if not r.get('duplicate_of'))
        duplicate = next(r for r in records if r.get('duplicate_of'))
        self.assertEqual(result.duplicates, 1)
        self.assertEqual(keeper['record_id'], original_id)
        self.assertEqual(keeper['resolved']['people'], ['Alma'])
        imported = [d['document'] for s in keeper['sources'] for d in s['documents']]
        self.assertIn(metadata, imported)
        self.assertEqual({s['original_filename'] for s in keeper['sources']}, {'IMG.jpg', 'Christmas.jpg'})
        self.assertTrue(duplicate['file']['relative_path'].startswith('review/duplicates/'))
        self.assertEqual(sum(data == b'photo' for data in self.fs.data.values()), 2)
        self.run_pass()
        self.assertEqual(len(next(r for r in self.records() if not r.get('duplicate_of'))['sources']), 2)

    def test_size_and_prefix_do_not_prove_equality(self):
        self.fs.put('inbox/a.jpg', b'x' * 1024 + b'A')
        self.fs.put('inbox/b.jpg', b'x' * 1024 + b'B')
        self.assertEqual(self.run_pass().duplicates, 0)
        self.assertTrue(all(not r.get('duplicate_of') for r in self.records()))

    def test_dry_run_writes_nothing(self):
        self.fs.put('inbox/a.jpg', b'photo')
        before = dict(self.fs.data)
        result = self.run_pass(dry_run=True)
        self.assertEqual(self.fs.data, before)
        self.assertEqual(len(result.proposals), 1)
        self.assertEqual(result.moved, 0)

    def test_files_arriving_during_extraction_wait_for_next_pass(self):
        self.fs.put('inbox/a.jpg', b'one')
        self.reader.on_read = lambda: self.fs.put('inbox/b.jpg', b'two')
        result = self.run_pass()
        self.assertEqual(result.discovered, 1)
        self.assertIn('inbox/b.jpg', self.fs.data)
        self.assertEqual(len(self.records()), 1)

    def test_file_changing_during_read_is_deferred(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.fs.on_read = lambda path: self.fs.put(path, b'changed') if path == 'inbox/a.jpg' else None
        result = self.run_pass()
        self.assertEqual(result.moved, 0)
        self.assertEqual(result.deferred, 1)
        self.assertIn('inbox/a.jpg', self.fs.data)

    def test_malformed_sidecar_is_not_replaced(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.fs.put('inbox/a.jpg' + SIDECAR, b'not-json')
        result = self.run_pass()
        self.assertTrue(result.errors)
        self.assertEqual(self.fs.data['inbox/a.jpg' + SIDECAR], b'not-json')
        self.assertEqual(result.moved, 0)

    def test_media_moved_alone_is_relinked_by_unique_hash(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        old, = self.records()
        self.fs.move_no_replace(old['file']['relative_path'], 'manual/renamed.jpg')
        result = self.run_pass()
        record, = self.records()
        self.assertFalse(result.errors)
        self.assertEqual(record['record_id'], old['record_id'])
        self.assertTrue(any(e['type'] == 'location_reconciled' for e in record['history']))

    def test_missing_media_keeps_its_sidecar(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        record, = self.records()
        path = record['file']['relative_path']
        self.fs.remove(path)
        result = self.run_pass()
        self.assertTrue(result.errors)
        self.assertIn(path + SIDECAR, self.fs.data)

    def test_ambiguous_repair_does_not_invent_new_records(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        record, = self.records()
        self.fs.remove(record['file']['relative_path'])
        self.fs.put('manual/a.jpg', b'photo')
        self.fs.put('manual/b.jpg', b'photo')
        result = self.run_pass()
        self.assertTrue(result.errors)
        self.assertEqual(len(self.records()), 1)
        self.assertIn('manual/a.jpg', self.fs.data)
        self.assertIn('manual/b.jpg', self.fs.data)

    def test_manual_overrides_survive_reinterpretation(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        record, = self.records()
        record['overrides'] = {'people': ['Stefan'], 'capture_time': '2020-01-02T03:04:05'}
        self.fs.put(record['file']['relative_path'] + SIDECAR, json.dumps(record).encode())
        self.fs.put('inbox/a.jpg.json', b'{"people":[{"name":"Alma"}]}')
        self.run_pass()
        record, = self.records()
        self.assertEqual(record['resolved']['people'], ['Stefan'])
        self.assertTrue(record['file']['relative_path'].startswith('photos/2020/01/'))

    def test_photo_and_sidecar_moved_together_keep_identity(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        old, = self.records()
        path = old['file']['relative_path']
        self.fs.move_no_replace(path, 'manual/renamed.jpg')
        self.fs.move_no_replace(path + SIDECAR, 'manual/renamed.jpg' + SIDECAR)
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        record, = self.records()
        self.assertEqual(record['record_id'], old['record_id'])

    def test_sidecar_moved_alone_is_restored(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        old, = self.records()
        path = old['file']['relative_path']
        self.fs.move_no_replace(path + SIDECAR, 'manual/orphan.jpg' + SIDECAR)
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertEqual(self.records()[0]['record_id'], old['record_id'])
        self.assertIn(path + SIDECAR, self.fs.data)

    def test_copied_record_ids_block_both_occurrences(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        record, = self.records()
        path = record['file']['relative_path']
        self.fs.put('copy.jpg', self.fs.data[path])
        self.fs.put('copy.jpg' + SIDECAR, self.fs.data[path + SIDECAR])
        before = dict(self.fs.data)
        result = self.run_pass()
        self.assertTrue(result.errors)
        self.assertEqual(result.moved, 0)
        self.assertEqual(before, self.fs.data)

    def test_same_original_name_different_media_never_collide(self):
        self.fs.put('one/IMG.jpg', b'one')
        self.fs.put('two/IMG.jpg', b'two')
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertEqual(result.moved, 2)
        self.assertEqual(len({r['file']['relative_path'] for r in self.records()}), 2)

    def test_destination_collision_preserves_foreign_media(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass(move_files=False)
        record, = self.records()
        target = f"undated/{record['record_id']}.jpg"
        self.fs.put(target, b'foreign')
        result = self.run_pass()
        self.assertTrue(result.errors)
        self.assertEqual(self.fs.data[target], b'foreign')
        self.assertEqual(self.fs.data['inbox/a.jpg'], b'photo')

    def test_verification_detects_content_changed_under_unchanged_stat(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        record, = self.records()
        path = record['file']['relative_path']
        self.fs.data[path] = b'other'
        self.assertEqual(self.run_pass().hashed, 0)
        verified = self.run_pass(verify=True)
        self.assertFalse(verified.errors, verified.errors)
        self.assertEqual(verified.hashed, 1)
        self.assertEqual(self.records()[0]['file']['sha256'], hashlib.sha256(b'other').hexdigest())
        self.assertEqual(len(self.reader.calls), 2)

    def test_mutation_during_embedded_extraction_defers_moves(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.reader.on_read = lambda: self.fs.put('inbox/a.jpg', b'changed')
        result = self.run_pass()
        self.assertEqual(result.deferred, 1)
        self.assertEqual(result.moved, 0)

    def test_people_are_not_inferred_from_folder_names(self):
        self.fs.put('Alma/IMG.jpg', b'photo')
        self.fs.put('Alma/metadata.json', b'{"title":"Alma"}')
        self.run_pass()
        record, = self.records()
        self.assertEqual(record['resolved']['people'], [])
        self.assertEqual(record['resolved']['albums'], ['Alma'])

    def test_document_revisions_are_preserved_but_latest_revision_is_resolved(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.fs.put('inbox/a.jpg.json', b'{"people":[{"name":"Alma"}],"unknown":1}')
        self.run_pass()
        self.fs.put('inbox/a.jpg.json', b'{"people":[{"name":"Stefan"}],"unknown":2}')
        self.run_pass()
        record, = self.records()
        self.assertEqual(record['resolved']['people'], ['Stefan'])
        self.assertEqual(len(record['sources'][0]['documents']), 2)
        enriched = [e for e in record['history'] if e['type'] == 'metadata_enriched']
        self.assertEqual(enriched[-1]['data']['changes']['people']['from'], ['Alma'])
        self.assertEqual(enriched[-1]['data']['changes']['people']['to'], ['Stefan'])

    def test_busy_library_skips_without_writes(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.fs.busy = True
        before = dict(self.fs.data)
        result = self.run_pass()
        self.assertTrue(result.locked)
        self.assertEqual(before, self.fs.data)

    def test_expected_library_identity_is_checked_before_writing(self):
        self.fs.put('inbox/a.jpg', b'photo')
        before = dict(self.fs.data)
        result = self.run_pass(expected_library_id='another-library')
        self.assertTrue(result.errors)
        self.assertEqual(before, self.fs.data)

    def test_recent_upload_is_deferred(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.fs.signatures['inbox/a.jpg'] = replace(self.fs.stat('inbox/a.jpg'),
            mtime_ns=int(self.clock.now().timestamp() * 1_000_000_000))
        result = Runner(self.fs, self.clock, self.ids, self.reader, Config(settle_seconds=30)).run()
        self.assertEqual(result.deferred, 1)
        self.assertEqual(result.moved, 0)

    def test_shared_album_document_is_read_once_per_batch(self):
        for number in range(10):
            self.fs.put(f'album/{number}.jpg', str(number).encode())
        self.fs.put('album/metadata.json', b'{"title":"Album"}')
        read = self.fs.read_bytes
        calls = []
        def counted(path):
            calls.append(path)
            return read(path)
        self.fs.read_bytes = counted
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertEqual(calls.count('album/metadata.json'), 1)

    def test_malformed_nested_checkpoint_does_not_crash_or_replace_sidecar(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        record, = self.records()
        record['stages']['embedded_metadata'] = []
        path = record['file']['relative_path'] + SIDECAR
        raw = json.dumps(record).encode()
        self.fs.put(path, raw)
        result = self.run_pass()
        self.assertTrue(result.errors)
        self.assertEqual(self.fs.data[path], raw)

    def test_existing_keeper_retains_identity_when_late_date_changes_its_layout(self):
        self.fs.put('inbox/old.jpg', b'photo')
        self.run_pass()
        original, = self.records()
        self.fs.put('inbox/old.jpg.json', b'{"photoTakenTime":{"timestamp":"1545652800"}}')
        self.fs.put('inbox/new.jpg', b'photo')
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        keeper = next(r for r in self.records() if not r.get('duplicate_of'))
        self.assertEqual(keeper['record_id'], original['record_id'])

    def test_embedded_capture_date_preserves_explicit_offset(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.reader.result = {'ExifIFD:DateTimeOriginal': '2018:12:24 19:04:00',
                              'ExifIFD:OffsetTimeOriginal': '+01:00'}
        self.run_pass()
        self.assertEqual(self.records()[0]['resolved']['capture_time'], '2018-12-24T19:04:00+01:00')

    def test_invalid_cached_field_shapes_are_reported_without_rewriting(self):
        self.fs.put('inbox/a.jpg', b'photo')
        self.run_pass()
        valid, = self.records()
        path = valid['file']['relative_path'] + SIDECAR
        for section, field, value in (
            ('resolved', 'capture_time', ['bad']),
            ('resolved', 'people', {}),
            ('file', 'sample_sha256', []),
        ):
            with self.subTest(field=field):
                record = copy.deepcopy(valid)
                record[section][field] = value
                raw = json.dumps(record).encode()
                self.fs.put(path, raw)
                result = self.run_pass()
                self.assertTrue(result.errors)
                self.assertEqual(raw, self.fs.data[path])


if __name__ == '__main__':
    unittest.main()
