import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from photoflow.adapters import LocalFileSystem
from photoflow.model import MARKER, SIDECAR, encoded
from photoflow.ports import BusyError
from photoflow.runner import Config, Runner
from tests.fakes import FakeClock, FakeIds, MemoryFS, MetadataReader


class FileSystemContracts(unittest.TestCase):
    def test_inventory_ignores_finder_files_and_nested_application_state(self):
        with tempfile.TemporaryDirectory() as directory:
            for fs in (MemoryFS(), LocalFileSystem(directory)):
                with self.subTest(adapter=type(fs).__name__):
                    for path in ('photo.jpg', 'photo.jpg.json', '._photo.jpg',
                                 '._photo.jpg.photo.json', '.DS_Store',
                                 '__MACOSX/._photo.jpg', '.AppleDouble/photo.jpg',
                                 'inbox/.takeout-extract/completed/001.json',
                                 '.photoflow/pending/move.json',
                                 '.photoflow/pending/._move.json'):
                        fs.atomic_write(path, b'fixture', replace=False)
                    self.assertEqual(fs.list_files(), ('photo.jpg', 'photo.jpg.json'))
                    self.assertEqual(fs.list_files('.photoflow/pending'), ('.photoflow/pending/move.json',))

    def test_adapter_contract_on_fake_and_real_filesystems(self):
        with tempfile.TemporaryDirectory() as directory:
            for fs in (MemoryFS(), LocalFileSystem(directory)):
                with self.subTest(adapter=type(fs).__name__):
                    fs.atomic_write('inbox/a.jpg', b'photo', replace=False)
                    self.assertEqual(fs.read_bytes('inbox/a.jpg'), b'photo')
                    with self.assertRaises(FileExistsError):
                        fs.atomic_write('inbox/a.jpg', b'bad', replace=False)
                    fs.atomic_write('elsewhere/b.jpg', b'foreign', replace=False)
                    with self.assertRaises(FileExistsError):
                        fs.move_no_replace('inbox/a.jpg', 'elsewhere/b.jpg')
                    self.assertEqual(fs.read_bytes('elsewhere/b.jpg'), b'foreign')
                    fs.move_no_replace('inbox/a.jpg', 'photos/a.jpg')
                    self.assertFalse(fs.exists('inbox/a.jpg'))
                    self.assertEqual(fs.stat('photos/a.jpg').size, 5)
                    self.assertEqual(fs.read_bytes('photos/a.jpg'), b'photo')
                    fs.atomic_write(MARKER, b'{}', replace=False)
                    with fs.lock():
                        with self.assertRaises(BusyError):
                            with fs.lock():
                                self.fail('overlapping lock acquired')
                    self.assertNotIn(MARKER, fs.list_files())

    def test_local_adapter_rejects_symlinks_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            fs = LocalFileSystem(root)
            target = Path(outside) / 'precious.jpg'
            target.write_bytes(b'precious')
            (Path(root) / 'link').symlink_to(outside, target_is_directory=True)
            (Path(root) / 'photo.jpg').symlink_to(target)
            for path in ('../precious.jpg', '/absolute', 'link/new.jpg', 'photo.jpg'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    fs.atomic_write(path, b'bad')
            self.assertEqual(fs.list_files(), ())
            self.assertEqual(target.read_bytes(), b'precious')

    def test_real_service_moves_and_rescans_without_rehashing(self):
        with tempfile.TemporaryDirectory() as directory:
            fs = LocalFileSystem(directory)
            fs.atomic_write(MARKER, encoded({'schema_version': 1, 'library_id': 'real-test'}), replace=False)
            fs.atomic_write('inbox/Alma/IMG.JPG', b'photo', replace=False)
            fs.atomic_write('inbox/Alma/IMG.JPG.supplemental-metadata.json',
                            b'{"photoTakenTime":{"timestamp":"1545652800"},"people":[{"name":"Alma"}]}')
            reader = MetadataReader()
            runner = Runner(fs, FakeClock(datetime.now(timezone.utc)), FakeIds(), reader, Config(settle_seconds=0))
            first, second = runner.run(), runner.run()
            self.assertFalse(first.errors, first.errors)
            self.assertFalse(second.errors, second.errors)
            self.assertEqual((first.moved, second.moved, second.hashed), (1, 0, 0))
            records = [json.loads(fs.read_bytes(p)) for p in fs.list_files() if p.endswith(SIDECAR)]
            record, = records
            self.assertIn('photos/2018/12/', record['file']['relative_path'])
            self.assertEqual(len(reader.calls), 1)
