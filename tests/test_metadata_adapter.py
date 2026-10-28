import subprocess
import unittest
from unittest.mock import patch

from photoflow.adapters import ExifToolReader


class FakePaths:
    def native_path(self, path):
        return '/library/' + path


class ExifToolTests(unittest.TestCase):
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
