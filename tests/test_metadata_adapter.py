import subprocess
import json
import unittest
from unittest.mock import patch

from photoflow.adapters import ExifToolReader


class FakePaths:
    def __init__(self):
        self.signatures = {}

    def native_path(self, path):
        return '/library/' + path

    def stat(self, path):
        return self.signatures.get(path, 'unchanged')


class ExifToolTests(unittest.TestCase):
    @patch('photoflow.adapters.subprocess.run')
    def test_prepared_batch_reuses_one_tool_process_for_multiple_reads(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, '13.0\n'),
            subprocess.CompletedProcess([], 0, json.dumps([
                {'SourceFile': '/library/Alma/a.jpg', 'Unknown:Field': 1},
                {'SourceFile': '/library/Alma/b.jpg', 'Unknown:Field': 2}]))]
        reader = ExifToolReader(FakePaths())
        reader.prepare(['Alma/a.jpg', 'Alma/b.jpg'])
        self.assertEqual(reader.read('Alma/a.jpg'), {'Unknown:Field': 1})
        self.assertEqual(reader.read('Alma/b.jpg'), {'Unknown:Field': 2})
        self.assertEqual(run.call_count, 2)
        self.assertIn('/library/Alma/a.jpg', run.call_args.kwargs['input'])

    @patch('photoflow.adapters.subprocess.run')
    def test_bad_file_in_batch_does_not_hide_good_file(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, '13.0\n'),
            subprocess.CompletedProcess([], 1, json.dumps([
                {'SourceFile': '/library/good.jpg', 'Unknown:Field': 1},
                {'SourceFile': '/library/bad.jpg', 'ExifTool:Error': 'corrupt media'}]))]
        reader = ExifToolReader(FakePaths())
        reader.prepare(['good.jpg', 'bad.jpg'])
        self.assertEqual(reader.read('good.jpg'), {'Unknown:Field': 1})
        with self.assertRaisesRegex(ValueError, 'corrupt media'):
            reader.read('bad.jpg')

    @patch('photoflow.adapters.subprocess.run')
    def test_changed_file_discards_prepared_metadata(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, '13.0\n'),
            subprocess.CompletedProcess([], 0, '[{"SourceFile":"/library/a.jpg","Value":1}]'),
            subprocess.CompletedProcess([], 0, '[{"SourceFile":"/library/a.jpg","Value":2}]')]
        fs = FakePaths()
        reader = ExifToolReader(fs)
        reader.prepare(['a.jpg'])
        fs.signatures['a.jpg'] = 'changed'
        self.assertEqual(reader.read('a.jpg'), {'Value': 2})
        self.assertEqual(run.call_count, 3)

    @patch('photoflow.adapters.subprocess.run')
    def test_batch_failure_falls_back_to_individual_read(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, '13.0\n'),
            subprocess.TimeoutExpired(['exiftool'], 60),
            subprocess.CompletedProcess([], 0, '[{"SourceFile":"/library/a.jpg","Value":1}]')]
        reader = ExifToolReader(FakePaths())
        reader.prepare(['a.jpg'])
        self.assertEqual(reader.read('a.jpg'), {'Value': 1})

    @patch('photoflow.adapters.subprocess.run')
    def test_filename_newline_is_never_interpreted_as_batch_arguments(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, '13.0\n'),
            subprocess.CompletedProcess([], 0, '[{"Value":1}]')]
        reader = ExifToolReader(FakePaths())
        reader.prepare(['odd\n-execute.jpg'])
        self.assertEqual(reader.read('odd\n-execute.jpg'), {'Value': 1})
        self.assertEqual(run.call_args.args[0][-1], '/library/odd\n-execute.jpg')

    @patch('photoflow.adapters.subprocess.run')
    def test_grouped_output_is_retained_without_machine_specific_source_path(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, '13.0\n'),
            subprocess.CompletedProcess([], 0,
                '[{"SourceFile":"/library/a.jpg","ExifIFD:DateTimeOriginal":"2018:12:24 12:00:00","Unknown:Field":42}]')]
        reader = ExifToolReader(FakePaths())
        result = reader.read('a.jpg')
        self.assertNotIn('SourceFile', result)
        self.assertEqual(result['Unknown:Field'], 42)
        self.assertEqual(reader.version, 'exiftool-v1:13.0')

    @patch('photoflow.adapters.subprocess.run')
    def test_subprocess_failures_are_application_level_metadata_errors(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, '13.0\n'),
                           subprocess.CalledProcessError(1, ['exiftool'])]
        reader = ExifToolReader(FakePaths())
        with self.assertRaises(ValueError):
            reader.read('corrupt.jpg')
