"""PROPS package tests: gltf dependency validator and pinned manifest.
No network: validator cases use local fixtures; the Godot smoke runs the
manifest-driven loader headless against the already-installed packs.
"""
import json
import os
import subprocess
import tempfile
import uuid
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fetch_visual_assets as fva
import runtime

try:
    GODOT = runtime.godot_binary()
except FileNotFoundError:
    GODOT = ROOT / ".tools" / "Godot_v4.6-stable_linux.x86_64"
PROJECT = ROOT / "game"


class GltfDependencyValidatorTests(unittest.TestCase):
    def _pack(self, files: dict, gltf_uri_map=None):
        """Temporary pack folder + files_spec fixture.
        files: {'rel/path': b'bytes'} already on disk.
        gltf_uri_map: {'buffers': [uri...], 'images': [uri...]} -> gltf.json.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        for rel, data in files.items():
            p = folder / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        uris = gltf_uri_map or {}
        gltf = {"asset": {"version": "2.0"},
                "buffers": [{"uri": u} for u in uris.get("buffers", [])],
                "images": [{"uri": u} for u in uris.get("images", [])]}
        (folder / "m.gltf").write_text(json.dumps(gltf))
        spec = {name: {} for name in files}
        spec["m.gltf"] = {}
        return folder, spec

    def test_valid_relative_deps_pass(self):
        folder, spec = self._pack(
            {"m.bin": b"x", "textures/t x.jpg": b"y"},
            {"buffers": ["m.bin"], "images": ["textures/t%20x.jpg"]})
        self.assertEqual(fva.validate_gltf_dependencies(folder, "m.gltf", spec), [])

    def test_data_uris_are_embedded(self):
        folder, spec = self._pack(
            {},
            {"buffers": ["data:application/octet-stream;base64,AAAA"],
             "images": ["data:image/jpeg;base64,AAAA"]})
        self.assertEqual(fva.validate_gltf_dependencies(folder, "m.gltf", spec), [])

    def test_no_dependencies_is_fine(self):
        folder, spec = self._pack({})
        self.assertEqual(fva.validate_gltf_dependencies(folder, "m.gltf", spec), [])

    def test_missing_dependency_reported(self):
        folder, spec = self._pack({"m.bin": b"x"},
                                  {"buffers": ["m.bin", "nope.bin"]})
        problems = fva.validate_gltf_dependencies(folder, "m.gltf", spec)
        self.assertEqual(len(problems), 1)
        self.assertIn("nope.bin", problems[0])

    def test_dependency_not_in_manifest_reported(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        (folder / "m.bin").write_bytes(b"x")
        (folder / "stray.bin").write_bytes(b"z")  # on disk, but not in files_spec
        gltf = {"asset": {"version": "2.0"},
                "buffers": [{"uri": "stray.bin"}], "images": []}
        (folder / "m.gltf").write_text(json.dumps(gltf))
        spec = {"m.bin": {}, "m.gltf": {}}
        problems = fva.validate_gltf_dependencies(folder, "m.gltf", spec)
        self.assertEqual(len(problems), 1)
        self.assertIn("absent from manifest", problems[0])

    def test_path_escape_rejected(self):
        for uri in ["../evil.bin", "textures/../../evil.jpg"]:
            folder, spec = self._pack({"m.bin": b"x"},
                                      {"buffers": [uri]})
            problems = fva.validate_gltf_dependencies(folder, "m.gltf", spec)
            self.assertEqual(len(problems), 1, uri)
            self.assertIn("rejected dependency", problems[0])

    def test_absolute_and_url_rejected(self):
        for uri in ["/etc/passwd", "C:/x.bin", "https://evil/x.bin", "file:///x"]:
            folder, spec = self._pack({"m.bin": b"x"},
                                      {"buffers": [uri]})
            problems = fva.validate_gltf_dependencies(folder, "m.gltf", spec)
            self.assertEqual(len(problems), 1, uri)
            self.assertIn("rejected dependency", problems[0])

    def test_unreadable_gltf_reported(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        (folder / "m.gltf").write_text("{not json")
        problems = fva.validate_gltf_dependencies(folder, "m.gltf", {})
        self.assertEqual(len(problems), 1)
        self.assertIn("cannot parse gltf", problems[0])

    def test_safe_relative(self):
        for bad in ["../x.bin", "/etc/passwd", "http://x/y", "textures\\x.jpg", "a:/x", ""]:
            self.assertFalse(fva.safe_relative(bad))
        for ok in ["x.bin", "textures/a b.jpg", "./x.bin", "textures/a%20b.jpg"]:
            self.assertTrue(fva.safe_relative(ok))


class ManifestSchemaTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / 'config/visuals/downloads.json').read_text())
        self.packs = self.cfg['packs']

    def test_every_pack_has_slot_license_and_pins(self):
        self.assertTrue(self.packs)
        for name, pack in self.packs.items():
            self.assertIsInstance(pack.get('slot'), str)
            self.assertTrue(pack['slot'])
            self.assertEqual(pack.get('license'), 'CC0-1.0')
            has_gltf = False
            for relative, spec in pack['files'].items():
                self.assertNotIn('..', Path(relative).parts)
                self.assertEqual(len(spec['sha256']), 64)
                self.assertGreater(spec['size'], 0)
                self.assertTrue(fva.safe_relative(relative))
                if relative.endswith('.gltf'):
                    has_gltf = True
            self.assertTrue(has_gltf, name)

    def test_urls_only_polyhaven_cdn(self):
        for pack in self.packs.values():
            for spec in pack['files'].values():
                self.assertEqual(fva.urlparse(spec['url']).hostname, 'dl.polyhaven.org')


@unittest.skipIf(not GODOT.exists(), "Godot binary not found")
class AssetPropsGodotSmoke(unittest.TestCase):
    """Headless: manifest-driven loader initialises, deterministic variants resolve,
    gltf delays fall back to procedural props (no engine error spam expected)."""

    @classmethod
    def setUpClass(cls):
        cls.skipped = not GODOT.exists()

    def test_loader_and_variants(self):
        if not GODOT.exists():
            raise unittest.SkipTest("no Godot")
        script = '''
extends SceneTree
const Assets = preload("res://visuals/assets.gd")
func _initialize() -> void:
	var ok := true
	Assets.init()
	# Procedural fallbacks still resolve for every street kind.
	for kind in ["lamp", "lamp_modern", "bench", "bin", "planter", "cabinet", "bollard"]:
		if Assets.resolve_prop(kind, 0).is_empty():
			ok = false
	if str(Assets.manifest.get("api_credit", "")) == "":
		ok = false
	# Clean checkouts may lack the downloaded packs: the manifest lists them but
	# only assertion is unresolved-slots. Add a pack to check.
	var last_slot := ""
	for slot in ["bin", "planter"]:
		if Assets.slot_variants.has(slot) and not Assets.slot_variants[slot].is_empty():
			last_slot = slot
			var resolved: Array = Assets.resolve_prop(slot, 0)
			if resolved.is_empty() or not resolved[0].has("mesh") or resolved[0].mesh == null:
				print("FAIL resolve_prop returned fallback for ", slot)
				ok = false
				continue
			var first_mesh = Assets.slot_variants[slot][0][0].mesh
			if resolved[0].mesh.get_instance_id() != first_mesh.get_instance_id():
				print("FAIL resolved variant is not the external one for ", slot)
				ok = false
			for parts in Assets.slot_variants[slot]:
				for part in parts:
					var s: Vector3 = part.mesh.get_aabb().size
					if s.x < 0.05 or s.y < 0.05 or s.z < 0.05 or s.x > 4.0 or s.y > 4.0 or s.z > 4.0:
						print("FAIL unreasonable bounds in ", slot, " size=", s)
						ok = false
	# resolve_prop stays deterministic with repeated seeds.
	if Assets.resolve_prop("bin", 3).size() != Assets.resolve_prop("bin", 3).size():
		ok = false
	print("ASSET_PROPS_SMOKE passed=", ok, " external_slots=", Assets.slot_variants.size(), " checked=", last_slot)
	quit(0 if ok else 1)
'''
        # Unique temp name (never a fixed developer file), always cleaned up.
        smoke = PROJECT / "scripts" / ("validate_asset_props_smoke_%s.gd" % uuid.uuid4().hex)
        smoke.write_text(script)
        try:
            env = os.environ.copy()
            env["XDG_DATA_HOME"] = str(ROOT / ".cache" / "data")
            env["XDG_CONFIG_HOME"] = str(ROOT / ".cache" / "config")
            env["XDG_CACHE_HOME"] = str(ROOT / ".cache")
            proc = subprocess.run(
                [str(GODOT), "--headless", "--path", str(PROJECT),
                 "--script", "res://scripts/" + smoke.name],
                capture_output=True, text=True, timeout=60, env=env, cwd=str(PROJECT))
            stdout = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, "Godot exit %d\n%s" % (proc.returncode, stdout))
            self.assertIn("ASSET_PROPS_SMOKE passed=true", stdout)
        finally:
            if smoke.exists():
                smoke.unlink()


if __name__ == '__main__':
    unittest.main()