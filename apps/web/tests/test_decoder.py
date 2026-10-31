import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from photoflow_web import decoder


class DecoderTests(unittest.TestCase):
    def test_macos_worker_runs_a_command_without_unsupported_address_space_limit(self):
        if sys.platform != "darwin":
            self.skipTest("macOS integration")
        result = subprocess.run([sys.executable, "-m", "photoflow_web.decoder", sys.executable, "-c", "print('decoded')"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "decoded")

    def test_process_tree_memory_includes_descendants_only(self):
        self.assertEqual(decoder.tree_memory("10 1 100\n11 10 200\n12 11 300\n90 1 999\n", 10), 600 * 1024)
        with self.assertRaises(ValueError):
            decoder.tree_memory("unreadable process table", 10)

    def test_supervisor_kills_a_worker_exceeding_its_memory_budget(self):
        if sys.platform != "darwin":
            self.skipTest("macOS supervision integration")
        result = subprocess.run([sys.executable, "-c",
            "from photoflow_web.decoder import supervise; import sys; "
            "sys.exit(supervise([sys.executable, '-c', 'import time; data=bytearray(64*1024**2); time.sleep(5)'], memory_limit=32*1024**2, timeout=4))"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 137, result.stderr)

    def test_macos_still_applies_cpu_output_and_file_descriptor_limits(self):
        calls = []
        with patch.object(decoder.resource, "setrlimit", side_effect=lambda kind, value: calls.append((kind, value))):
            decoder.configure_limits("darwin")
        self.assertNotIn(decoder.resource.RLIMIT_AS, [kind for kind, _ in calls])
        for kind in (decoder.resource.RLIMIT_CPU, decoder.resource.RLIMIT_FSIZE, decoder.resource.RLIMIT_NOFILE):
            self.assertIn(kind, [key for key, _ in calls])
