import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from photoflow.cli import main
from photoflow.metrics import MeteredFileSystem
from tests.fakes import MemoryFS


class MetricsTests(unittest.TestCase):
    def test_reads_and_writes_are_counted_once_by_role(self):
        raw = MemoryFS()
        raw.put('photo.jpg', b'abcdef')
        raw.put('photo.jpg.json', b'{}')
        fs = MeteredFileSystem(raw)
        self.assertEqual(fs.read_bytes('photo.jpg.json'), b'{}')
        with fs.open_binary('photo.jpg') as stream:
            self.assertEqual(stream.read(2), b'ab')
            self.assertEqual(stream.read(), b'cdef')
            self.assertEqual(stream.read(), b'')
        fs.atomic_write('photo.jpg.photo.json', b'record')
        fs.stat('photo.jpg')
        fs.inventory()
        stats = fs.stats()
        self.assertEqual(stats['files']['source_json']['read_opens'], 1)
        self.assertEqual(stats['files']['source_json']['read_bytes'], 2)
        self.assertEqual(stats['files']['media']['read_opens'], 1)
        self.assertEqual(stats['files']['media']['read_calls'], 3)
        self.assertEqual(stats['files']['media']['read_bytes'], 6)
        self.assertEqual(stats['files']['sidecar']['atomic_writes'], 1)
        self.assertEqual(stats['files']['sidecar']['written_bytes'], 6)
        self.assertEqual(stats['operations']['inventory'], 1)
        self.assertEqual(stats['operations']['stat'], 1)

    def test_cli_stats_describe_a_normal_unchanged_writable_pass(self):
        def invoke(*args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(list(args))
            self.assertEqual(code, 0, out.getvalue())
            return json.loads(out.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'photo.jpg').write_bytes(b'photo')
            (root / 'photo.jpg.json').write_bytes(b'{}')
            invoke('init', directory)
            invoke('run', directory, '--settle-seconds', '0', '--stats')
            result = invoke('run', directory, '--settle-seconds', '0', '--stats')
            self.assertEqual(result['source_cache_hits'], 1)
            self.assertEqual(result['io']['operations']['inventory'], 1)
            self.assertEqual(result['io']['files'].get('sidecar', {}).get('atomic_writes', 0), 0)
            self.assertEqual(result['io']['files'].get('source_json', {}).get('read_opens', 0), 0)
            self.assertEqual(result['io']['files']['state']['atomic_writes'], 1)
