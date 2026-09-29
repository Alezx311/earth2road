import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import generate_map as gm
from akadem_maps.cli import Events


class BboxTest(unittest.TestCase):
    def test_square_at_50n(self):
        w, s, e, n = gm.bbox_around(50.0, 30.0, 1.5)
        self.assertAlmostEqual(n - s, 1.5 / 110.574, places=5)
        self.assertAlmostEqual(e - w, 0.02101, places=4)   # 1.5 km / (111.32 km · cos 50°)
        self.assertAlmostEqual((w + e) / 2, 30.0, places=6)
        self.assertAlmostEqual((s + n) / 2, 50.0, places=6)

    def test_rejects_polar_antimeridian_and_bad_size(self):
        with self.assertRaises(ValueError):
            gm.bbox_around(84.999, 0.0, 1.0)
        with self.assertRaises(ValueError):
            gm.bbox_around(-84.999, 0.0, 1.0)
        with self.assertRaises(ValueError):
            gm.bbox_around(0.0, 179.999, 1.0)
        with self.assertRaises(ValueError):
            gm.bbox_around(0.0, -179.999, 1.0)
        with self.assertRaises(ValueError):
            gm.bbox_around(10.0, 10.0, 50.0)
        with self.assertRaises(ValueError):
            gm.bbox_around(float('nan'), 10.0, 1.0)


class IdTest(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(gm.slug('Lviv — Rynok Square', 49.8, 24.0), 'lviv_rynok_square')
        self.assertEqual(gm.slug('São Paulo', -23.5, -46.6), 'sao_paulo')
        # Cyrillic has no ASCII decomposition: fall back to the coordinates.
        self.assertEqual(gm.slug('Львів', 49.84192, 24.03161), 'geo_49_8419_24_0316')
        self.assertEqual(gm.slug('', -33.8688, -151.2093), 'geo_m33_8688_m151_2093')
        self.assertEqual(gm.slug('123 Main', 1.0, 2.0), 'geo_1_0000_2_0000')

    def test_free_id_never_reuses_an_installed_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(gm.free_id('town', root), 'town')
            (root/'game/data/town').mkdir(parents=True)
            (root/'data/build/town_2').mkdir(parents=True)
            self.assertEqual(gm.free_id('town', root), 'town_3')

    def test_free_id_skips_a_leftover_input_cache(self):
        # A deleted map's cached OSM is looked up by id and would stand in for a new area.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'out/generated/.akadem-inputs').mkdir(parents=True)
            (root/'out/generated/.akadem-inputs/town.osm').write_text('<osm/>', encoding='utf8')
            self.assertEqual(gm.free_id('town', root), 'town_2')

    def test_ukraine_box(self):
        self.assertTrue(gm.in_ukraine_box(50.45, 30.52))
        self.assertFalse(gm.in_ukraine_box(48.85, 2.35))


class PipelineTest(unittest.TestCase):
    def test_events_and_steps_with_a_fake_pipeline(self):
        calls = []
        def build(cfg, world, *, config_root, emit):
            calls.append(('build', cfg, world))
            emit('stage', stage='download', progress=0.5)
            emit('result', output=str(world))
        def export(world, export, *, offline):
            calls.append(('export', world, export))
        def install(export, root, *, replace, activate):
            calls.append(('install', replace, activate))
            return {'installed': ['x']}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'game/data/lviv').mkdir(parents=True)
            log = root/'events.jsonl'
            events = Events(str(log))
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                result = gm.generate(49.84, 24.03, 1.0, 'Lviv', events, root=root,
                                     pipeline={'build': build, 'export': export, 'install': install})
            finally:
                sys.stderr = stderr
                events.close()
            records = [json.loads(line) for line in log.read_text(encoding='utf8').splitlines()]
        self.assertEqual(result['id'], 'lviv_2')
        self.assertEqual(result['region_profile'], 'ukraine')
        cfg = calls[0][1]
        self.assertEqual(cfg['id'], 'lviv_2')
        self.assertEqual(cfg['bbox'], gm.bbox_around(49.84, 24.03, 1.0))
        self.assertEqual(cfg['overpass_maxsize'], 256 * 1024 * 1024)
        self.assertEqual([cfg['overpass']] + cfg['overpass_mirrors'], gm.OVERPASS)
        self.assertEqual(calls[0][2], root/'out/generated/lviv_2')
        self.assertEqual(calls[2], ('install', False, True))
        self.assertEqual([r['event'] for r in records].count('result'), 0)   # main() emits the one result
        self.assertIn('step', [r['event'] for r in records])
        progress = [r['progress'] for r in records if r['event'] == 'stage']
        self.assertEqual(progress, sorted(progress))
        self.assertIn({'phase': 'build', 'stage': 'download', 'progress': 0.4},
                      [{k: r[k] for k in ('phase', 'stage', 'progress')} for r in records if r['event'] == 'stage'])


class WatchParentTest(unittest.TestCase):
    def test_cancels_once_the_parent_is_gone(self):
        parents = iter([100, 100, 1])      # reparented to init: the game exited
        stopped = []
        stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            gm.watch_parent(100, poll=0.001, getppid=lambda: next(parents, 1),
                            stop=lambda: stopped.append(True)).join(timeout=5)
        finally:
            sys.stderr = stderr
        self.assertEqual(stopped, [True])


if __name__ == '__main__':
    unittest.main()
