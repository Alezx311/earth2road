"""Platform binary resolution for Windows and Linux layouts."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import runtime


class RuntimeTests(unittest.TestCase):
    def test_venv_python_falls_back_when_venv_is_missing_or_a_stub(self):
        self.assertTrue(runtime.venv_python().exists() or runtime.venv_python() == Path(sys.executable))
        stub = runtime.ROOT / '.venv'
        if stub.exists() and not stub.is_dir():
            self.assertIsNone(runtime.venv_dir())
            self.assertEqual(runtime.venv_python(), Path(sys.executable))

    def test_sumo_binary_names_the_tool_when_missing(self):
        with mock.patch.object(runtime, 'venv_bin_dir', return_value=None), \
             mock.patch.object(runtime, '_sumo_home_bins', return_value=iter(())), \
             mock.patch('runtime.shutil.which', return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, 'netconvert'):
                runtime.sumo_binary('netconvert')

    def test_sumo_binary_prefers_venv_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp)
            exe = bindir / ('sumo.exe' if os.name == 'nt' else 'sumo')
            exe.write_text('', encoding='utf8')
            with mock.patch.object(runtime, 'venv_bin_dir', return_value=bindir), \
                 mock.patch.object(runtime, '_sumo_home_bins', return_value=iter(())):
                self.assertEqual(runtime.sumo_binary('sumo'), exe)

    def test_godot_names_match_the_host(self):
        names = runtime.godot_names()
        self.assertTrue(any('4.6' in n for n in names))
        if os.name == 'nt':
            self.assertTrue(any(n.endswith('.exe') for n in names))
        else:
            self.assertTrue(any('linux' in n for n in names))

    def test_godot_binary_missing_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(runtime, 'ROOT', Path(tmp)):
                with self.assertRaisesRegex(FileNotFoundError, 'Godot'):
                    runtime.godot_binary()


if __name__ == '__main__':
    unittest.main()
