import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from photoflow.adapters import LocalFileSystem
from photoflow.model import MARKER
from photoflow.runner import Config, Runner
from tests.fakes import FakeClock, FakeIds, MemoryFS, MetadataReader


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.fs = MemoryFS()
        self.fs.put(MARKER, json.dumps({'schema_version': 1, 'library_id': 'cleanup-test'}).encode())
        self.reader = MetadataReader()

    def run_pass(self, **options):
        return Runner(self.fs, FakeClock(datetime.now(timezone.utc)), FakeIds(),
                      self.reader, Config(settle_seconds=0, **options)).run()

    def test_success_prunes_empty_ancestors_across_the_library(self):
        self.fs.put('inbox/old/day/photo.jpg', b'photo')
        self.fs.mkdir('photos/1999/01')
        self.fs.mkdir('elsewhere/empty')
        self.fs.mkdir('inbox/.takeout-extract/empty')
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertEqual(set(result.removed_directories), {
            'inbox/old/day', 'inbox/old', 'photos/1999/01', 'photos/1999',
            'photos', 'elsewhere/empty', 'elsewhere'})
        self.assertIn('inbox', self.fs.directories)
        self.assertIn('inbox/.takeout-extract/empty', self.fs.directories)
        self.assertEqual(self.fs.list_files('.photoflow/pending'), ())

    def test_nonempty_source_folders_and_later_arrivals_survive(self):
        self.fs.put('inbox/album/photo.jpg', b'photo')
        self.fs.put('inbox/album/photo.jpg.json', b'{}')
        self.fs.put('finder/.DS_Store', b'finder')
        self.reader.on_read = lambda: self.fs.mkdir('inbox/new-upload/empty')
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertIn('inbox/album', self.fs.directories)
        self.assertIn('finder', self.fs.directories)
        self.assertIn('inbox/new-upload/empty', self.fs.directories)
        self.assertEqual(result.removed_directories, [])

    def test_preview_and_metadata_only_passes_leave_empty_directories(self):
        self.fs.mkdir('inbox/empty')
        for options in ({'dry_run': True}, {'move_files': False}):
            with self.subTest(options=options):
                result = self.run_pass(**options)
                self.assertFalse(result.errors, result.errors)
                self.assertIn('inbox/empty', self.fs.directories)
                self.assertEqual(result.removed_directories, [])

    def test_failed_or_deferred_pass_does_not_prune(self):
        self.fs.mkdir('inbox/empty')
        self.fs.put('inbox/photo.jpg', b'photo')
        self.fs.on_read = lambda path: self.fs.put(path, b'changed')
        deferred = self.run_pass()
        self.assertEqual(deferred.deferred, 1)
        self.assertIn('inbox/empty', self.fs.directories)
        self.fs.put('inbox/photo.jpg.photo.json', b'invalid')
        failed = self.run_pass()
        self.assertTrue(failed.errors)
        self.assertIn('inbox/empty', self.fs.directories)

    def test_cleanup_failure_is_reported_without_losing_completed_work(self):
        self.fs.mkdir('old/empty')
        def deny(operation, path):
            if operation == 'rmdir':
                raise PermissionError('directory is protected')
        self.fs.fail_on = deny
        result = self.run_pass()
        self.assertFalse(result.errors, result.errors)
        self.assertTrue(any('empty_directory_cleanup_failed: old/empty' in w for w in result.warnings))
        self.assertIn('old/empty', self.fs.directories)


class DirectoryContracts(unittest.TestCase):
    def test_enumeration_and_atomic_empty_removal_on_fake_and_real_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            for fs in (MemoryFS(), LocalFileSystem(directory)):
                with self.subTest(adapter=type(fs).__name__):
                    for path in ('inbox/old/empty', '.photoflow/pending',
                                 'inbox/.takeout-extract/empty', 'finder/.AppleDouble/empty'):
                        if isinstance(fs, MemoryFS):
                            fs.mkdir(path)
                        else:
                            fs.native_path(path).mkdir(parents=True, exist_ok=True)
                    self.assertEqual(set(fs.list_directories()), {'inbox', 'inbox/old', 'inbox/old/empty', 'finder'})
                    # An uploader can create a file after enumeration.
                    fs.atomic_write('inbox/old/empty/arrived.jpg', b'new')
                    self.assertFalse(fs.remove_empty_directory('inbox/old/empty'))
                    self.assertEqual(fs.read_bytes('inbox/old/empty/arrived.jpg'), b'new')
                    fs.remove('inbox/old/empty/arrived.jpg')
                    self.assertTrue(fs.remove_empty_directory('inbox/old/empty'))
                    self.assertFalse(fs.remove_empty_directory('inbox/old/empty'))
                    with self.assertRaises(ValueError):
                        fs.remove_empty_directory('.photoflow/pending')
                    with self.assertRaises(ValueError):
                        fs.remove_empty_directory('../outside')

    def test_directory_enumeration_never_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            (Path(directory) / 'link').symlink_to(outside, target_is_directory=True)
            fs = LocalFileSystem(directory)
            self.assertEqual(fs.list_directories(), ())
            with self.assertRaises(ValueError):
                fs.remove_empty_directory('link')
            self.assertTrue(Path(outside).is_dir())
