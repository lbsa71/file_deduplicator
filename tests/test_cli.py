import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from photoflow.cli import main
from photoflow.model import MARKER


class CliTests(unittest.TestCase):
    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_init_preview_run_search_and_identity_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = root / 'Christmas at Grandma.jpg'
            photo.write_bytes(b'photo')
            self.assertEqual(self.invoke('run', directory)[0], 1)
            self.assertFalse((root / MARKER).exists())
            code, output, _ = self.invoke('init', directory, '--library-id', 'family-photos')
            self.assertEqual(code, 0, output)
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            code, output, _ = self.invoke('run', directory, '--dry-run', '--settle-seconds', '0')
            self.assertEqual(code, 0, output)
            after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(self.invoke('run', directory, '--expect-library-id', 'wrong')[0], 1)
            code, output, _ = self.invoke('run', directory, '--settle-seconds', '0')
            self.assertEqual(code, 0, output)
            self.assertEqual(json.loads(output)['moved'], 1)
            code, output, _ = self.invoke('search', directory, 'christmas')
            self.assertEqual(code, 0, output)
            self.assertEqual(json.loads(output)[0]['original_filenames'], ['Christmas at Grandma.jpg'])

    def test_metadata_only_run_creates_records_without_moving_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'photo.jpg').write_bytes(b'photo')
            self.invoke('init', directory)
            code, output, _ = self.invoke('run', directory, '--no-move', '--settle-seconds', '0')
            self.assertEqual(code, 0, output)
            self.assertTrue((root / 'photo.jpg').exists())
            self.assertTrue((root / 'photo.jpg.photo.json').exists())

    def test_repeated_init_never_replaces_an_existing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.invoke('init', directory, '--library-id', 'original')[0], 0)
            self.assertEqual(self.invoke('init', directory, '--library-id', 'different')[0], 2)
            self.assertEqual(json.loads((Path(directory) / MARKER).read_text())['library_id'], 'original')

    def test_json_cannot_be_selected_as_media(self):
        with tempfile.TemporaryDirectory() as directory:
            self.invoke('init', directory)
            source = Path(directory) / 'photo.jpg.json'
            source.write_text('{"people":[{"name":"Alma"}]}')
            code, _, _ = self.invoke('run', directory, '--extensions', 'json', '--settle-seconds', '0')
            self.assertEqual(code, 2)
            self.assertTrue(source.exists())
