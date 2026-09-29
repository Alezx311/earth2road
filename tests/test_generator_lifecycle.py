"""Real Windows processes: cancellation, abrupt owner death, descendant cleanup."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows job object integration')
class WindowsGeneratorTests(unittest.TestCase):
    def wait_for(self, predicate, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(0.05)
        self.fail('process lifecycle did not finish before timeout')

    def alive(self, pid):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)

    def run_case(self, action):
        with tempfile.TemporaryDirectory(prefix='generator with spaces ') as tmp:
            folder = Path(tmp)
            worker = folder/'worker.py'
            worker.write_text('''import json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from generator_lifecycle import watch_windows
p = Path(sys.argv[2])
done = watch_windows(int(sys.argv[3]), p/'cancel', grace=0.5)
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
(p/'ready').write_text(json.dumps([os.getpid(), child.pid]))
try:
    while True: time.sleep(0.05)
except KeyboardInterrupt:
    (p/'cleaned').write_text('yes')
finally:
    done.set()
''', encoding='utf8')
            if action == 'owner':
                owner = folder/'owner.py'
                owner.write_text('''import os, subprocess, sys, time
subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3], str(os.getpid())])
time.sleep(60)
''', encoding='utf8')
                cmd = [sys.executable, str(owner), str(worker), str(ROOT/'tools'), str(folder)]
            else:
                cmd = [sys.executable, str(worker), str(ROOT/'tools'), str(folder), '0']
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pids = []
            try:
                self.wait_for(lambda: (folder/'ready').exists() and (folder/'ready').stat().st_size > 0)
                pids = json.loads((folder/'ready').read_text())
                if action == 'cancel':
                    (folder/'cancel').touch()
                else:
                    process.kill()
                process.wait(timeout=12)
                self.wait_for(lambda: all(not self.alive(pid) for pid in pids))
                if action != 'kill':
                    self.assertTrue((folder/'cleaned').exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for pid in pids:
                    if self.alive(pid):
                        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)

    def test_cancel_cleans_up_and_reaps_children(self):
        self.run_case('cancel')

    def test_owner_death_cancels_generator_and_children(self):
        self.run_case('owner')

    def test_forced_generator_death_reaps_children(self):
        self.run_case('kill')
