"""Run with PHOTOFLOW_STORAGE_TEST_ROOT to exercise another mounted filesystem."""

import errno
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from photoflow.adapters import LocalFileSystem, _rename_no_replace
from photoflow.model import MARKER, PENDING, SIDECAR, encoded
from photoflow.runner import Config, Runner
from tests.fakes import FakeClock, FakeIds, MetadataReader


class StorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='.photoflow-storage-test-',
            dir=os.environ.get('PHOTOFLOW_STORAGE_TEST_ROOT'))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fs = LocalFileSystem(self.root)

    def runner(self, fs=None):
        return Runner(fs or self.fs, FakeClock(datetime.now(timezone.utc)),
                      FakeIds(), MetadataReader(), Config(settle_seconds=0))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux no-overwrite rename adapter')
    def test_creation_updates_and_moves_do_not_require_hard_links(self):
        with patch('photoflow.adapters.os.link', side_effect=OSError(errno.EOPNOTSUPP, 'no hard links')):
            self.fs.atomic_write('inbox/photo.jpg', b'photo', replace=False)
            self.fs.atomic_write('notes.json', b'old', replace=False)
            self.fs.atomic_write('notes.json', b'new')
            self.fs.move_no_replace('inbox/photo.jpg', 'photos/photo.jpg')
        self.assertEqual(self.fs.read_bytes('notes.json'), b'new')
        self.assertEqual(self.fs.read_bytes('photos/photo.jpg'), b'photo')
        self.assertFalse(self.fs.exists('inbox/photo.jpg'))

    def test_competing_creators_never_replace_each_others_file(self):
        def publish(payload):
            try:
                self.fs.atomic_write('shared/record.json', payload, replace=False)
                return payload
            except FileExistsError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, (b'first', b'second')))
        winners = [payload for payload in results if payload is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.fs.read_bytes('shared/record.json'), winners[0])
        self.assertFalse(list(self.root.rglob('.photoflow-tmp-*')))

    def test_existing_media_and_directories_are_not_overwritten(self):
        self.fs.atomic_write('source.jpg', b'original', replace=False)
        self.fs.atomic_write('destination.jpg', b'foreign', replace=False)
        with self.assertRaises(FileExistsError):
            self.fs.move_no_replace('source.jpg', 'destination.jpg')
        (self.root / 'directory.jpg').mkdir()
        with self.assertRaises(OSError):
            self.fs.move_no_replace('source.jpg', 'directory.jpg')
        self.assertEqual(self.fs.read_bytes('source.jpg'), b'original')
        self.assertEqual(self.fs.read_bytes('destination.jpg'), b'foreign')
        self.assertTrue((self.root / 'directory.jpg').is_dir())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux no-overwrite directory rename')
    def test_directory_publish_preserves_the_tree_and_rejects_existing_targets(self):
        self.fs.atomic_write('staging/album/photo.jpg', b'photo', replace=False)
        self.fs.atomic_write('inbox/existing/keep.jpg', b'keep', replace=False)
        with self.assertRaises(OSError):
            _rename_no_replace(self.root / 'staging', self.root / 'inbox/existing')
        self.assertEqual(self.fs.read_bytes('staging/album/photo.jpg'), b'photo')
        self.assertEqual(self.fs.read_bytes('inbox/existing/keep.jpg'), b'keep')
        _rename_no_replace(self.root / 'staging', self.root / 'inbox/published')
        self.fs._sync_dir(self.root)
        self.fs._sync_dir(self.root / 'inbox')
        self.assertFalse(self.fs.exists('staging'))
        self.assertEqual(self.fs.read_bytes('inbox/published/album/photo.jpg'), b'photo')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux no-overwrite rename adapter')
    def test_unsupported_no_overwrite_rename_fails_without_an_unsafe_fallback(self):
        self.fs.atomic_write('source.jpg', b'original', replace=False)
        def unsupported(*args):
            ctypes.set_errno(errno.EOPNOTSUPP)
            return -1
        with patch('photoflow.adapters._linux_renameat2', return_value=unsupported):
            with self.assertRaises(OSError) as move_error:
                self.fs.move_no_replace('source.jpg', 'destination.jpg')
            with self.assertRaises(OSError) as write_error:
                self.fs.atomic_write('record.json', b'new', replace=False)
        self.assertEqual(move_error.exception.errno, errno.EOPNOTSUPP)
        self.assertEqual(write_error.exception.errno, errno.EOPNOTSUPP)
        self.assertEqual(self.fs.read_bytes('source.jpg'), b'original')
        self.assertFalse(self.fs.exists('destination.jpg'))
        self.assertFalse(self.fs.exists('record.json'))
        self.assertFalse(list(self.root.rglob('.photoflow-tmp-*')))

    def test_real_filesystem_recovery_at_each_commit_boundary(self):
        for boundary in ('journal', 'moved', 'new-sidecar', 'old-sidecar', 'complete'):
            with self.subTest(boundary=boundary):
                root = self.root / boundary
                root.mkdir()

                class InterruptedFS(LocalFileSystem):
                    armed = True

                    def stop(self, phase):
                        if self.armed and phase == boundary:
                            self.armed = False
                            raise OSError('simulated process interruption')

                    def move_no_replace(self, source, target):
                        self.stop('journal')
                        super().move_no_replace(source, target)
                        self.stop('moved')

                    def atomic_write(self, path, data, *, replace=True):
                        if path.startswith('undated/') and path.endswith(SIDECAR):
                            self.stop('new-sidecar')
                        super().atomic_write(path, data, replace=replace)

                    def remove(self, path):
                        if path == 'inbox/a.jpg' + SIDECAR:
                            self.stop('old-sidecar')
                        if path.startswith(PENDING + '/'):
                            self.stop('complete')
                        super().remove(path)

                fs = InterruptedFS(root)
                fs.atomic_write(MARKER, encoded({'schema_version': 1, 'library_id': 'storage-test'}), replace=False)
                fs.atomic_write('inbox/a.jpg', b'photo', replace=False)
                runner = self.runner(fs)
                first = runner.run()
                self.assertTrue(first.errors, first.to_dict())
                self.assertTrue(fs.list_files(PENDING))
                recovered = runner.run()
                self.assertFalse(recovered.errors, recovered.to_dict())
                self.assertEqual(recovered.recovered, 1)
                record, = [json.loads(fs.read_bytes(path)) for path in fs.list_files() if path.endswith(SIDECAR)]
                self.assertEqual(sum(event['type'] == 'moved' for event in record['history']), 1)
                self.assertEqual(fs.read_bytes(record['file']['relative_path']), b'photo')
                self.assertFalse(fs.exists('inbox/a.jpg'))
                self.assertFalse(fs.list_files(PENDING))
                again = runner.run()
                self.assertEqual((again.moved, again.hashed, again.metadata_extracted), (0, 0, 0))

    def test_process_exit_after_media_move_is_recoverable(self):
        self.fs.atomic_write(MARKER, encoded({'schema_version': 1, 'library_id': 'storage-test'}), replace=False)
        self.fs.atomic_write('inbox/a.jpg', b'photo', replace=False)
        script = '''
import os, sys
from photoflow.adapters import LocalFileSystem, NoEmbeddedMetadata, RandomIds, SystemClock
from photoflow.runner import Config, Runner
class ExitAfterMove(LocalFileSystem):
    def move_no_replace(self, source, target):
        super().move_no_replace(source, target)
        os._exit(73)
Runner(ExitAfterMove(sys.argv[1]), SystemClock(), RandomIds(), NoEmbeddedMetadata(), Config(settle_seconds=0)).run()
'''
        process = subprocess.run([sys.executable, '-c', script, str(self.root)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 73, process.stderr)
        result = self.runner().run()
        self.assertFalse(result.errors, result.to_dict())
        self.assertEqual(result.recovered, 1)
        record, = [json.loads(self.fs.read_bytes(path)) for path in self.fs.list_files() if path.endswith(SIDECAR)]
        self.assertEqual(sum(event['type'] == 'moved' for event in record['history']), 1)
