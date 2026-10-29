import json
import shutil
import stat
import tempfile
import unittest
import zipfile
import warnings
from pathlib import Path
from unittest.mock import patch

from scripts.extract_takeout import ExtractionError, extract_archive, extract_legacy_archive
from photoflow.adapters import _rename_no_replace

NAME = 'takeout-20261028T123735Z-1-001.zip'
SECOND = 'takeout-20261028T123735Z-1-002.zip'


class TakeoutExtractionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def archive(self, name=NAME, entries=None):
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.root / name, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, content in entries or [('Takeout/Google Photos/Alma/photo.jpg', b'photo')]:
                archive.writestr(path, content)
        return self.root / name

    def test_success_verifies_outputs_and_remembers_deleted_archive(self):
        self.archive(entries=[('Takeout/Google Photos/Alma/photo.jpg', b'photo'),
                              ('Takeout/Google Photos/Alma/photo.jpg.json', b'{"people":[{"name":"Alma"}]}')])
        report = extract_archive(self.root, NAME, delete=True)
        self.assertEqual(report['status'], 'completed')
        self.assertTrue(report['archive_deleted'])
        self.assertEqual(len(report['entries']), 2)
        self.assertFalse((self.root / NAME).exists())
        self.assertEqual((self.root / 'Takeout/Google Photos/Alma/photo.jpg').read_bytes(), b'photo')
        saved = json.loads((self.root / '.takeout-extract/completed/001.json').read_text())
        self.assertEqual(saved['archive_sha256'], report['archive_sha256'])
        self.assertTrue(saved['archive_deleted'])

    def test_keep_mode_leaves_verified_zip(self):
        self.archive()
        report = extract_archive(self.root, NAME)
        self.assertFalse(report['archive_deleted'])
        self.assertTrue((self.root / NAME).is_file())

    def test_identical_overlap_is_verified_and_different_overlap_is_preserved(self):
        self.archive()
        extract_archive(self.root, NAME, delete=True)
        self.archive(SECOND)
        report = extract_archive(self.root, SECOND, delete=True)
        self.assertEqual(report['existing_files'], 1)
        self.archive(NAME, [('Takeout/Google Photos/Alma/photo.jpg', b'different')])
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertTrue((self.root / NAME).is_file())
        self.assertEqual((self.root / 'Takeout/Google Photos/Alma/photo.jpg').read_bytes(), b'photo')

    def test_unsafe_entries_are_rejected_before_any_extraction(self):
        for member in ('../outside.jpg', '/absolute.jpg', 'C:/absolute.jpg', 'folder\\file.jpg',
                       '.takeout-extract/override', NAME, 'folder/../escape.jpg'):
            with self.subTest(member=member):
                self.archive(entries=[('safe.jpg', b'safe'), (member, b'unsafe')])
                with self.assertRaises(ExtractionError):
                    extract_archive(self.root, NAME, delete=True)
                self.assertFalse((self.root / 'safe.jpg').exists())
                self.assertTrue((self.root / NAME).exists())

    def test_symlink_archive_entry_is_rejected(self):
        with zipfile.ZipFile(self.root / NAME, 'w') as archive:
            info = zipfile.ZipInfo('link')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '../outside')
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertFalse((self.root / 'link').exists())

    def test_existing_symlink_is_not_followed(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'Takeout').symlink_to(outside, target_is_directory=True)
        self.archive()
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_existing_partial_file_is_never_overwritten(self):
        self.archive()
        output = self.root / 'Takeout/Google Photos/Alma/photo.jpg'
        output.parent.mkdir(parents=True)
        output.write_bytes(b'partial')
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertEqual(output.read_bytes(), b'partial')
        self.assertTrue((self.root / NAME).exists())

    def test_corrupt_archive_is_retained(self):
        (self.root / NAME).write_bytes(b'not a zip')
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertTrue((self.root / NAME).exists())

    def test_interruption_before_deletion_can_be_retried(self):
        self.archive()
        with patch('scripts.extract_takeout._remove_archive', side_effect=OSError('interrupted')):
            with self.assertRaises(ExtractionError):
                extract_archive(self.root, NAME, delete=True)
        self.assertTrue((self.root / NAME).exists())
        self.assertTrue((self.root / '.takeout-extract/completed/001.json').exists())
        report = extract_archive(self.root, NAME, delete=True)
        self.assertTrue(report['archive_deleted'])

    def test_changed_completed_output_prevents_zip_deletion(self):
        self.archive()
        extract_archive(self.root, NAME)
        (self.root / 'Takeout/Google Photos/Alma/photo.jpg').write_bytes(b'changed')
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertTrue((self.root / NAME).exists())

    def test_same_named_replacement_archive_is_not_deleted_from_old_completion(self):
        self.archive()
        extract_archive(self.root, NAME)
        self.archive(entries=[('new.jpg', b'new')])
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertTrue((self.root / NAME).exists())
        self.assertFalse((self.root / 'new.jpg').exists())

    def test_transferring_name_and_out_of_range_number_are_rejected(self):
        for name in (NAME + '.transferring', '../' + NAME, NAME.replace('001', '026')):
            with self.subTest(name=name), self.assertRaises(ExtractionError):
                extract_archive(self.root, name, delete=True)

    def test_bad_member_crc_never_publishes_its_output_or_removes_zip(self):
        payload = b'unique-payload-for-crc-test'
        with zipfile.ZipFile(self.root / NAME, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('photo.jpg', payload)
        raw = (self.root / NAME).read_bytes()
        position = raw.index(payload)
        (self.root / NAME).write_bytes(raw[:position] + b'X' + raw[position + 1:])
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertTrue((self.root / NAME).exists())
        self.assertFalse((self.root / 'photo.jpg').exists())

    def test_duplicate_member_names_require_matching_complete_bytes(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            self.archive(entries=[('same.jpg', b'photo'), ('same.jpg', b'photo')])
        result = extract_archive(self.root, NAME)
        self.assertEqual(len(result['entries']), 1)
        self.assertEqual(result['existing_files'], 1)
        other = self.root / SECOND
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(other, 'w') as archive:
                archive.writestr('different.jpg', b'first')
                archive.writestr('different.jpg', b'second')
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, SECOND, delete=True)
        self.assertTrue(other.exists())
        self.assertEqual((self.root / 'different.jpg').read_bytes(), b'first')

    def test_file_directory_conflict_is_rejected_during_preflight(self):
        self.archive(entries=[('folder', b'file'), ('folder/photo.jpg', b'photo')])
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertFalse((self.root / 'folder').exists())

    def test_interruption_after_staging_archive_is_recoverable(self):
        self.archive()
        def stop_after_staging(source, destination):
            _rename_no_replace(source, destination)
            if Path(source) == self.root / NAME:
                raise SystemExit('abrupt process exit after staging')
        with patch('scripts.extract_takeout._rename_no_replace', side_effect=stop_after_staging):
            with self.assertRaises(SystemExit):
                extract_archive(self.root, NAME, delete=True)
        self.assertFalse((self.root / NAME).exists())
        saved = json.loads((self.root / '.takeout-extract/completed/001.json').read_text())
        self.assertTrue((self.root / saved['staged_archive']).exists())
        report = extract_archive(self.root, NAME, delete=True)
        self.assertTrue(report['archive_deleted'])
        self.assertIsNone(report['staged_archive'])

    def test_archive_path_replacement_during_deletion_is_preserved(self):
        self.archive()
        replacement = b'a different concurrently arriving archive'
        def replace_during_staging(source, destination):
            if Path(source) == self.root / NAME:
                incoming = self.root / 'incoming'
                incoming.write_bytes(replacement)
                incoming.replace(source)
            _rename_no_replace(source, destination)
        with patch('scripts.extract_takeout._rename_no_replace', side_effect=replace_during_staging):
            with self.assertRaises(ExtractionError):
                extract_archive(self.root, NAME, delete=True)
        self.assertEqual((self.root / NAME).read_bytes(), replacement)

    def test_truncated_completion_cannot_skip_output_verification(self):
        self.archive(entries=[('one.jpg', b'one'), ('two.jpg', b'two')])
        extract_archive(self.root, NAME)
        completion = self.root / '.takeout-extract/completed/001.json'
        saved = json.loads(completion.read_text())
        saved['entries'] = saved['entries'][:1]
        completion.write_text(json.dumps(saved))
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertTrue((self.root / NAME).exists())

    def test_directory_payload_is_rejected_before_extraction(self):
        self.archive(entries=[('folder/', b'not a directory payload')])
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertFalse((self.root / 'folder').exists())
        self.assertTrue((self.root / NAME).exists())

    def test_reappeared_input_does_not_strand_a_staged_archive(self):
        self.archive()
        def stop_after_staging(source, destination):
            _rename_no_replace(source, destination)
            if Path(source) == self.root / NAME:
                raise SystemExit('abrupt process exit after staging')
        with patch('scripts.extract_takeout._rename_no_replace', side_effect=stop_after_staging):
            with self.assertRaises(SystemExit):
                extract_archive(self.root, NAME, delete=True)
        completion = self.root / '.takeout-extract/completed/001.json'
        staged = self.root / json.loads(completion.read_text())['staged_archive']
        shutil.copyfile(staged, self.root / NAME)
        report = extract_archive(self.root, NAME, delete=True)
        self.assertTrue(report['archive_deleted'])
        self.assertFalse(staged.exists())
        self.assertFalse((self.root / NAME).exists())

    def test_staged_archive_cannot_be_deleted_using_truncated_completion(self):
        self.archive(entries=[('one.jpg', b'one'), ('two.jpg', b'two')])
        def stop_after_staging(source, destination):
            _rename_no_replace(source, destination)
            if Path(source) == self.root / NAME:
                raise SystemExit('stop after staging')
        with patch('scripts.extract_takeout._rename_no_replace', side_effect=stop_after_staging):
            with self.assertRaises(SystemExit):
                extract_archive(self.root, NAME, delete=True)
        completion = self.root / '.takeout-extract/completed/001.json'
        saved = json.loads(completion.read_text())
        staged = self.root / saved['staged_archive']
        saved['entries'] = saved['entries'][:1]
        completion.write_text(json.dumps(saved))
        with self.assertRaises(ExtractionError):
            extract_archive(self.root, NAME, delete=True)
        self.assertTrue(staged.is_file())

    def test_legacy_nested_zip_extracts_beneath_explicit_prefix(self):
        name = 'inbox/Old family export.zip'
        self.archive(name, [('Family/photo.jpg', b'photo')])
        result = extract_legacy_archive(self.root, name, archive_number=1,
            output_prefix='_expanded/Old family export', delete=True)
        self.assertTrue(result['archive_deleted'])
        self.assertEqual(result['archive_relative_path'], name)
        self.assertEqual(result['output_prefix'], '_expanded/Old family export')
        self.assertEqual((self.root / '_expanded/Old family export/Family/photo.jpg').read_bytes(), b'photo')
        self.assertFalse((self.root / name).exists())

    def test_legacy_split_parts_share_one_output_group_and_keep_companions_adjacent(self):
        prefix = '_expanded/Google Photos-export'
        self.archive('part1.zip', [('Photos/photo.jpg', b'photo')])
        self.archive('part2.zip', [('Photos/photo.jpg', b'photo'), ('Photos/photo.jpg.json', b'{"people":[]}')])
        extract_legacy_archive(self.root, 'part1.zip', archive_number=1, output_prefix=prefix, delete=True)
        second = extract_legacy_archive(self.root, 'part2.zip', archive_number=2, output_prefix=prefix, delete=True)
        self.assertEqual(second['existing_files'], 1)
        self.assertTrue((self.root / prefix / 'Photos/photo.jpg').exists())
        self.assertTrue((self.root / prefix / 'Photos/photo.jpg.json').exists())
        self.assertFalse((self.root / 'part1.zip').exists())
        self.assertFalse((self.root / 'part2.zip').exists())

    def test_legacy_distinct_groups_preserve_differing_same_named_members(self):
        self.archive('one.zip', [('photo.jpg', b'one')])
        self.archive('two.zip', [('photo.jpg', b'two')])
        extract_legacy_archive(self.root, 'one.zip', archive_number=1, output_prefix='_expanded/one', delete=True)
        extract_legacy_archive(self.root, 'two.zip', archive_number=2, output_prefix='_expanded/two', delete=True)
        self.assertEqual((self.root / '_expanded/one/photo.jpg').read_bytes(), b'one')
        self.assertEqual((self.root / '_expanded/two/photo.jpg').read_bytes(), b'two')

    def test_legacy_prefix_change_on_retry_is_rejected(self):
        self.archive('old.zip', [('photo.jpg', b'photo')])
        extract_legacy_archive(self.root, 'old.zip', archive_number=1, output_prefix='_expanded/one')
        with self.assertRaises(ExtractionError):
            extract_legacy_archive(self.root, 'old.zip', archive_number=1, output_prefix='_expanded/two', delete=True)
        self.assertTrue((self.root / 'old.zip').exists())
        self.assertFalse((self.root / '_expanded/two').exists())

    def test_legacy_prefix_change_is_rejected_even_after_input_was_deleted(self):
        self.archive('old.zip', [('photo.jpg', b'photo')])
        extract_legacy_archive(self.root, 'old.zip', archive_number=1, output_prefix='_expanded/one', delete=True)
        with self.assertRaises(ExtractionError):
            extract_legacy_archive(self.root, 'old.zip', archive_number=1, output_prefix='_expanded/two', delete=True)

    def test_legacy_output_cannot_alias_its_archive_input(self):
        name = '_expanded/archive.zip'
        self.archive(name, [('archive.zip', b'payload')])
        with self.assertRaises(ExtractionError):
            extract_legacy_archive(self.root, name, archive_number=1, output_prefix='_expanded', delete=True)
        self.assertTrue((self.root / name).exists())

    def test_legacy_only_removes_the_working_copy_archive(self):
        original = self.archive('originals/archive.zip', [('photo.jpg', b'photo')])
        original_bytes = original.read_bytes()
        working = self.root / 'working'
        working.mkdir()
        shutil.copyfile(original, working / 'archive.zip')
        extract_legacy_archive(working, 'archive.zip', archive_number=1, output_prefix='_expanded/archive', delete=True)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertFalse((working / 'archive.zip').exists())
        self.assertEqual((working / '_expanded/archive/photo.jpg').read_bytes(), b'photo')

    def test_legacy_input_and_prefix_are_safe_relative_paths(self):
        for name, prefix in (('../archive.zip', '_expanded/one'), ('archive.zip.transferring', '_expanded/one'),
                             ('archive.zip', '../outside'), ('archive.zip', '.')):
            with self.subTest(name=name, prefix=prefix), self.assertRaises(ExtractionError):
                extract_legacy_archive(self.root, name, archive_number=1, output_prefix=prefix, delete=True)

    def test_legacy_prefixed_directories_and_staged_retry_keep_membership(self):
        name = 'inbox/archive.zip'
        prefix = '_expanded/family'
        self.archive(name, [('Family/', b''), ('Family/photo.jpg', b'photo')])
        def stop_after_staging(source, destination):
            _rename_no_replace(source, destination)
            if Path(source) == self.root / name:
                raise SystemExit('stop after staging')
        with patch('scripts.extract_takeout._rename_no_replace', side_effect=stop_after_staging):
            with self.assertRaises(SystemExit):
                extract_legacy_archive(self.root, name, archive_number=4, output_prefix=prefix, delete=True)
        result = extract_legacy_archive(self.root, name, archive_number=4, output_prefix=prefix, delete=True)
        self.assertTrue(result['archive_deleted'])
        self.assertEqual(result['directories'], ['_expanded/family/Family'])
        self.assertEqual(result['entries'][0]['path'], '_expanded/family/Family/photo.jpg')

    def test_legacy_conflicting_shared_group_never_overwrites_or_deletes_second_zip(self):
        self.archive('part1.zip', [('photo.jpg', b'one')])
        self.archive('part2.zip', [('photo.jpg', b'two')])
        prefix = '_expanded/group'
        extract_legacy_archive(self.root, 'part1.zip', archive_number=1, output_prefix=prefix, delete=True)
        with self.assertRaises(ExtractionError):
            extract_legacy_archive(self.root, 'part2.zip', archive_number=2, output_prefix=prefix, delete=True)
        self.assertTrue((self.root / 'part2.zip').exists())
        self.assertEqual((self.root / prefix / 'photo.jpg').read_bytes(), b'one')


if __name__ == '__main__':
    unittest.main()
