"""Derived road signs: placement geometry, provenance, and what the generated map holds.

The pure tests use a hand-built straight lane, so they run without SUMO or a built map;
the generated-map tests check the real output the way tests/test_world.py does."""
import math
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import paths
import signs

MAP = os.environ.get('AKADEM_MAP', 'akadem')


def _to_segment(p, a, b):
    """Distance from a point to a segment: lane vertices are up to 10 m apart, so the
    nearest vertex is not the nearest point of the lane."""
    dx, dz = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dz * dz
    t = 0.0 if span == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / span))
    return math.dist(p, (a[0] + dx * t, a[1] + dz * t))

# A straight 100 m lane heading north (-Z in Godot space), 3.5 m wide.
LANE = {'id': 'e1_0', 'width': 3.5, 'service': False, 'internal': False,
        'points': [[0.0, 2.0, -float(i) * 10.0] for i in range(11)]}


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.shapes = signs.LaneShapes([LANE])

    def test_sign_stands_right_of_the_lane(self):
        record = signs.place(self.shapes, 'e1_0', 50.0, 'give_way', None, 'derived', 'net', 'e1')
        x, y, z = record['position']
        # North is -Z, so the right-hand kerb is +X.
        self.assertAlmostEqual(x, LANE['width'] / 2 + signs.LATERAL, places=3)
        self.assertAlmostEqual(z, -50.0, places=3)
        self.assertAlmostEqual(y, 2.0 + signs.PLATE_HEIGHT, places=3)

    def test_sign_faces_the_approaching_driver(self):
        record = signs.place(self.shapes, 'e1_0', 50.0, 'give_way', None, 'derived', 'net', 'e1')
        # The plate's +Z, rotated by yaw, must point back down the lane (towards +Z).
        facing = (math.sin(record['yaw']), math.cos(record['yaw']))
        self.assertAlmostEqual(facing[0], 0.0, places=3)
        self.assertAlmostEqual(facing[1], 1.0, places=3)

    def test_offset_is_clamped_to_the_lane(self):
        far = signs.place(self.shapes, 'e1_0', 10_000.0, 'stop', None, 'derived', 'net', 'e1')
        self.assertAlmostEqual(far['position'][2], -100.0, places=3)

    def test_length_matches_the_polyline(self):
        self.assertAlmostEqual(self.shapes.length('e1_0'), 100.0, places=6)


@unittest.skipUnless((paths.game_dir(MAP) / 'index.json').exists(), 'Generate map first')
class GeneratedMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = paths.load_world(MAP, tiles=True)
        cls.signs = cls.world.get('signs', [])
        cls.lanes = {lane['id']: lane for lane in cls.world['lanes']}

    def test_map_has_signs(self):
        self.assertGreater(len(self.signs), 50, 'run tools/prepare.py or tools/signs.py')

    def test_every_sign_declares_where_it_came_from(self):
        for record in self.signs:
            self.assertIn(record['kind'], signs.KINDS)
            self.assertIn(record['provenance'], ('osm', 'derived'))
            self.assertTrue(record['source'])

    def test_speed_limit_plates_are_osm_backed(self):
        """~84% of the speeds in the network are SUMO type defaults: a plate may only
        appear where OSM actually carries maxspeed."""
        for record in self.signs:
            if record['kind'] == 'speed_limit':
                self.assertEqual(record['provenance'], 'osm', record)
                self.assertTrue(5 <= record['value'] <= 130, record)

    def test_signs_sit_beside_their_own_lane(self):
        for record in self.signs[:500]:
            lane = self.lanes[record['lane']]
            x, _, z = record['position']
            closest = min(_to_segment((x, z), (a[0], a[2]), (b[0], b[2]))
                          for a, b in zip(lane['points'], lane['points'][1:]))
            self.assertLess(closest, lane['width'] / 2 + signs.LATERAL + 0.5, record)
            self.assertGreater(closest, lane['width'] / 2 - 0.5, record)

    def test_signs_are_not_on_junction_internal_lanes(self):
        for record in self.signs:
            self.assertFalse(record['lane'].startswith(':'), record)

    def test_traffic_light_programmes_are_exported_and_labelled(self):
        index_tls = self.world.get('tls', [])
        self.assertTrue(index_tls, 'index.json has no tls block')
        states = {s['tls']: s['index'] for s in self.world['signals']}
        for record in index_tls:
            self.assertEqual(record['provenance'], 'derived')
            self.assertIn(record['default_program'], record['programs'])
            phases = record['programs'][record['default_program']]
            self.assertTrue(phases)
            width = {len(state) for _, state in phases}
            self.assertEqual(len(width), 1, record['id'])
            if record['id'] in states:
                self.assertLess(states[record['id']], width.pop())


if __name__ == '__main__':
    unittest.main()
