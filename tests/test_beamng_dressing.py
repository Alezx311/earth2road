"""Street dressing must stand beside the pavement: lamps and signal posts off lanes and
junctions, signal heads high over their lanes and facing the approaching drivers."""
from collections import Counter
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from beamng_corridors import Corridors
from beamng_network import stable_id
from export_beamng import SIGNAL_HEAD_HEIGHT, signal_masts, street_lights

WIDTH = 3.2


def godot(x, y, z=0.0):
    """BeamNG (x, y, z) -> the snapshot's Godot [x, z, -y]."""
    return [x, z, -y]


def approach():
    """Three lanes northbound (+y) at x = 6.4 (index 0, kerb side), 3.2 and 0, stop line
    at y = 100, then a junction square 100..130 and a crossing street along y = 115."""
    lanes = {f'e_{i}': {'id': f'e_{i}', 'edge': 'e', 'width': WIDTH,
                        'points': [godot(6.4 - i * WIDTH, 0), godot(6.4 - i * WIDTH, 50), godot(6.4 - i * WIDTH, 100)]}
             for i in range(3)}
    strips = [{'points': lane['points'], 'width': WIDTH, 'bridge': False} for lane in lanes.values()]
    strips.append({'points': [godot(-40, 115), godot(60, 115)], 'width': 7.0, 'bridge': False})
    square = [godot(-2, 100), godot(9, 100), godot(9, 130), godot(-2, 130)]
    junction = {'triangles': [[square[0], square[1], square[2]], [square[0], square[2], square[3]]]}
    return lanes, [('0_0', {'road_strips': strips, 'junctions': [junction]})]


def on_pavement(corridors, p):
    return corridors.occupied(p, margin=0.3, roads_only=True)


class CorridorTests(unittest.TestCase):
    def test_junction_pavement_counts_as_road(self):
        _lanes, tiles = approach()
        corridors = Corridors(tiles)
        self.assertTrue(on_pavement(corridors, (3.5, 125.0, 0.0)))    # inside the junction, off the strips
        self.assertFalse(on_pavement(corridors, (3.5, 125.0, 8.0)))   # far above it (an overpass level)
        self.assertFalse(on_pavement(corridors, (20.0, 125.0, 0.0)))


class LampTests(unittest.TestCase):
    def test_no_lamp_on_lanes_or_junctions(self):
        lanes, tiles = approach()
        corridors = Corridors(tiles)
        # A navigation road narrower than the real pavement, running straight through
        # the junction: its nominal lamp offset lands on neighbouring lanes.
        road = {'name': 'r', 'drivability': 1.0,
                'nodes': [[3.2, 0, 0, 3.2], [3.2, 130, 0, 3.2], [3.2, 200, 0, 3.2]]}
        counts = Counter()
        lamps = street_lights([road], corridors, counts)
        self.assertTrue(lamps)
        for lamp in lamps:
            self.assertFalse(corridors.occupied(lamp['position'], margin=0.5, roads_only=True), lamp['position'])
        self.assertGreater(counts['street_lamps_shifted'] + counts['street_lamps_dropped_on_pavement'], 0)


class SignalTests(unittest.TestCase):
    def masts(self):
        lanes, tiles = approach()
        sig = {'instances': [{'name': stable_id('kyiv_signal', lid)} for lid in ('e_0', 'e_1', 'e_2')]}
        counts = Counter()
        return lanes, Corridors(tiles), signal_masts(sig, lanes, Corridors(tiles), counts), counts

    def test_one_roadside_post_per_approach(self):
        _lanes, corridors, masts, counts = self.masts()
        self.assertEqual(len(masts), 1)
        _edge, post, top, clear, heads = masts[0]
        self.assertTrue(clear)
        self.assertFalse(on_pavement(corridors, post))
        self.assertGreater(post[0], 6.4 + WIDTH / 2)          # right of the kerb lane
        self.assertEqual(counts['signal_posts_on_pavement'], 0)
        self.assertGreater(top, max(h[1][2] for h in heads))

    def test_heads_hang_over_their_own_lanes_above_traffic(self):
        lanes, _corridors, masts, _counts = self.masts()
        heads = masts[0][4]
        self.assertEqual(len(heads), 3)
        for s, (x, y, z), _d in heads:
            lane = next(l for l in lanes.values() if stable_id('kyiv_signal', l['id']) == s['name'])
            self.assertAlmostEqual(x, lane['points'][-1][0], places=6)   # above the lane centre
            self.assertLess(y, 100)                                       # before the stop line
            self.assertGreaterEqual(z - 0.55, 4.7)                        # housing bottom clears trucks
            self.assertAlmostEqual(z, SIGNAL_HEAD_HEIGHT)

    def test_exported_head_faces_approaching_drivers_from_above(self):
        import json
        import tempfile
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from export_beamng import export_map
        from test_beamng_export import fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            export_map('test', root / 'out', source_root=root)
            level = root / 'out/levels/kyiv_test'
            head = json.loads((level / 'main/MissionGroup/KyivSignals/items.level.json')
                              .read_text(encoding='utf8').splitlines()[0])
            m = head['rotationMatrix']
            # Fixture lane a_0 runs +y in BeamNG; lenses sit on local -X (row-major image).
            self.assertAlmostEqual(-m[0], 0.0)
            self.assertAlmostEqual(-m[3], -1.0)
            self.assertGreater(head['position'][2], 4.7)
            self.assertAlmostEqual(head['position'][0], 0.0, places=3)   # above lane a_0 (x = 0)
            masts = [json.loads(line) for line in (level / 'main/MissionGroup/KyivProps/items.level.json')
                     .read_text(encoding='utf8').splitlines() if 'kyiv_signal_mast' in line]
            self.assertEqual(len(masts), 1)
            self.assertGreater(masts[0]['position'][0], 1.6)            # beside the 3.2 m lane

if __name__ == '__main__':
    unittest.main()
