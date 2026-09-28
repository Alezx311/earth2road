"""Subprocess Godot regression for Package C vehicle availability."""
import os
import subprocess
import sys
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import runtime
PROJECT = ROOT / "game"
TIMEOUT = 90

try:
    GODOT = runtime.godot_binary()
except FileNotFoundError:
    GODOT = ROOT / ".tools" / "Godot_v4.6-stable_linux.x86_64"


class VehicleAvailabilityGodotRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GODOT.exists():
            raise unittest.SkipTest("Godot binary not found at %s" % GODOT)

    def test_vehicle_availability(self):
        env = os.environ.copy()
        env["XDG_DATA_HOME"] = str(ROOT / ".cache" / "data")
        env["XDG_CONFIG_HOME"] = str(ROOT / ".cache" / "config")
        env["XDG_CACHE_HOME"] = str(ROOT / ".cache")

        proc = subprocess.run(
            [str(GODOT), "--headless", "--path", str(PROJECT),
             "--script", "res://scripts/validate_vehicle_availability.gd"],
            capture_output=True, text=True, timeout=TIMEOUT, env=env,
            cwd=str(PROJECT),
        )
        stdout = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0,
            "Godot exited with code %d\n%s" % (proc.returncode, stdout))
        self.assertIn("VEHICLE_VALIDATION", stdout,
            "No VEHICLE_VALIDATION marker in output\n%s" % stdout)
        # Parse the JSON marker (may span multiple lines) and assert passed=true
        start = next((i for i, l in enumerate(stdout.splitlines())
                      if l.startswith("VEHICLE_VALIDATION ")), None)
        self.assertIsNotNone(start, "No VEHICLE_VALIDATION marker in output\n%s" % stdout)
        lines = stdout.splitlines()[start:]
        brace_start = lines[0].index("{")
        json_text = lines[0][brace_start:]
        for l in lines[1:]:
            json_text += "\n" + l
            if "}" in l:
                break
        result = json.loads(json_text)
        self.assertTrue(result["passed"],
            "Vehicle validation failed: %s" % json.dumps(result, indent=2))


if __name__ == '__main__':
    unittest.main()
