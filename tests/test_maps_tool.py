import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import maps
import generate_map as gm


def checkout(root):
    (root/'game').mkdir(parents=True)
    (root/'game/project.godot').write_text('', encoding='utf8')
    for mid in ('town', 'town_2'):
        (root/'game/data'/mid/'tiles').mkdir(parents=True)
        (root/'data/build'/mid).mkdir(parents=True)
        (root/'data/build'/mid/'network.net.xml').write_text('<net/>', encoding='utf8')
    generated = root/'out/generated'
    for name in ('town', 'town_godot', 'town.logs', 'town-20261006120000', 'town-20261006120000_godot',
                 'town_2', 'town_2_godot', 'townhall'):
        (generated/name).mkdir(parents=True)
    (generated/'.akadem-inputs/snapshots/abc').mkdir(parents=True)
    (generated/'.akadem-inputs/town.osm').write_text('<osm/>', encoding='utf8')
    exports = root/'out/beamng'
    for run, mid in (('town-20261006-120000-0123abcd', 'town'), ('town-20261006-130000-89abcdef', 'other'),
                     ('town_2-20261006-120000-0123abcd', 'town_2')):
        (exports/run).mkdir(parents=True)
        (exports/run/'artifact.json').write_text(json.dumps({'map': mid}), encoding='utf8')
    mods = root/'BeamNG/mods'
    mods.mkdir(parents=True)
    for name in ('earth2road_town.zip', 'akadem_drive_town.zip', 'earth2road_town_2.zip', 'other.zip'):
        (mods/name).write_bytes(b'PK')
    (root/'game/data/active_map').write_text('town\n', encoding='utf8')
    return exports, mods


class DeleteTest(unittest.TestCase):
    def test_deletes_only_the_map_and_frees_its_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exports, mods = checkout(root)
            result = maps.delete('town', root, current='town_2', mods_dir=mods, exports_dir=exports)
            self.assertEqual(result['failed'], [])
            for gone in ('game/data/town', 'data/build/town', 'out/generated/town', 'out/generated/town_godot',
                         'out/generated/town.logs', 'out/generated/town-20261006120000_godot',
                         'out/generated/.akadem-inputs/town.osm', 'out/beamng/town-20261006-120000-0123abcd',
                         'BeamNG/mods/earth2road_town.zip', 'BeamNG/mods/akadem_drive_town.zip', 'game/data/active_map'):
                self.assertFalse((root/gone).exists(), gone)
            for kept in ('game/data/town_2', 'data/build/town_2', 'out/generated/town_2', 'out/generated/town_2_godot',
                         'out/generated/townhall', 'out/generated/.akadem-inputs/snapshots/abc',
                         'out/beamng/town-20261006-130000-89abcdef', 'out/beamng/town_2-20261006-120000-0123abcd',
                         'BeamNG/mods/earth2road_town_2.zip', 'BeamNG/mods/other.zip'):
                self.assertTrue((root/kept).exists(), kept)
            self.assertEqual(gm.free_id('town', root), 'town')

    def test_refuses_bad_ids_the_loaded_map_and_foreign_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkout(root)
            for mid in ('../town', 'Town', '', 'town/..'):
                with self.assertRaises(ValueError):
                    maps.delete(mid, root)
            with self.assertRaises(ValueError):
                maps.delete('town', root, current='town')
            self.assertTrue((root/'game/data/town').exists())
            with self.assertRaises(ValueError):
                maps.delete('town', root/'game')

    @unittest.skipUnless(os.name == 'nt', 'directory junctions are Windows-only')
    def test_a_junction_is_unlinked_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkout(root)
            outside = root/'outside'
            outside.mkdir()
            (outside/'keep.txt').write_text('x', encoding='utf8')
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(root/'game/data/linked'), str(outside)],
                           check=True, capture_output=True)
            maps.delete('linked', root)
            self.assertFalse(os.path.lexists(root/'game/data/linked'))
            self.assertTrue((outside/'keep.txt').exists())

    def test_cli_prints_json(self):
        out = subprocess.run([sys.executable, str(ROOT/'tools/maps.py'), 'delete', '--id', 'Bad!'],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        self.assertIn('error', json.loads(out.stdout))


if __name__ == '__main__':
    unittest.main()
