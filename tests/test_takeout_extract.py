import json
import shutil
import stat
import tempfile
import unittest
import zipfile
import warnings
from pathlib import Path
from unittest.mock import patch

from scripts.extract_takeout import ExtractionError, extract_archive
from photoflow.adapters import _rename_no_replace

NAME = 'takeout-20261028T123735Z-1-001.zip'
SECOND = 'takeout-20261028T123735Z-1-002.zip'


class TakeoutExtractionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def archive(self, name=NAME, entries=None):
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


if __name__ == '__main__':
    unittest.main()
