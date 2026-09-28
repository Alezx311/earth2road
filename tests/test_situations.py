"""Road-situation commands and the click-to-lane index. Pure functions only: no SUMO
process is started here, the same way tests/test_traffic.py tests frame packing."""
import math
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import paths
import situations

MAP = os.environ.get('AKADEM_MAP', 'akadem')


class CommandTests(unittest.TestCase):
    def test_unknown_kind_is_rejected(self):
        self.assertIsNone(situations.parse_command(
            {'type': 'incident', 'action': 'add', 'kind': 'meteorite', 'p': [0, 0, 0]}))

    def test_point_or_edge_is_required(self):
        self.assertIsNone(situations.parse_command(
            {'type': 'incident', 'action': 'add', 'kind': 'jam'}))

    def test_duration_is_clamped(self):
        cmd = situations.parse_command({'type': 'incident', 'action': 'add', 'kind': 'jam',
                                        'p': [1, 2, 3], 'duration': 10 ** 6})
        self.assertEqual(cmd['duration'], situations.MAX_SECONDS)

    def test_non_finite_values_are_rejected(self):
        for bad in (float('nan'), float('inf')):
            self.assertIsNone(situations.parse_command(
                {'type': 'incident', 'action': 'add', 'kind': 'jam', 'p': [bad, 0, 0]}))
            self.assertIsNone(situations.parse_command(
                {'type': 'incident', 'action': 'add', 'kind': 'jam', 'p': [0, 0, 0],
                 'duration': bad}))

    def test_speed_limit_needs_a_plausible_value(self):
        self.assertIsNone(situations.parse_command(
            {'type': 'incident', 'action': 'add', 'kind': 'speed_limit', 'p': [0, 0, 0],
             'value_kmh': 500}))
        cmd = situations.parse_command(
            {'type': 'incident', 'action': 'add', 'kind': 'speed_limit', 'p': [0, 0, 0],
             'value_kmh': 30})
        self.assertEqual(cmd['value_kmh'], 30)

    def test_missing_id_is_generated(self):
        ids = iter(['inc7'])
        cmd = situations.parse_command({'type': 'incident', 'action': 'add', 'kind': 'jam',
                                        'p': [0, 0, 0]}, lambda: next(ids))
        self.assertEqual(cmd['id'], 'inc7')

    def test_tls_actions_are_whitelisted(self):
        self.assertIsNone(situations.parse_command(
            {'type': 'tls', 'action': 'explode', 'id': 'j1'}))
        self.assertIsNone(situations.parse_command(
            {'type': 'tls', 'action': 'program', 'id': 'j1'}))       # missing value
        self.assertEqual(situations.parse_command(
            {'type': 'tls', 'action': 'allred', 'id': 'j1'}),
            {'type': 'tls', 'action': 'allred', 'id': 'j1'})

    def test_unrelated_message_is_ignored(self):
        self.assertIsNone(situations.parse_command({'type': 'ego', 'position': [0, 0, 0]}))


class LaneIndexTests(unittest.TestCase):
    """A straight 100 m lane along -Z, one point every 10 m, 3.5 m wide."""

    def setUp(self):
        points = [[0.0, 0.0, -float(i) * 10.0] for i in range(11)]
        self.index = situations.LaneIndex([
            {'id': 'e1_0', 'points': points, 'internal': False},
            {'id': ':j_0_0', 'points': points, 'internal': True},
        ])

    def test_internal_lanes_are_not_clickable(self):
        self.assertEqual(list(self.index.lanes), ['e1_0'])

    def test_nearest_returns_offset_along_the_lane(self):
        lid, offset, distance = self.index.nearest([1.0, 0.0, -30.0])
        self.assertEqual(lid, 'e1_0')
        self.assertAlmostEqual(offset, 30.0, places=3)
        self.assertAlmostEqual(distance, 1.0, places=3)

    def test_far_point_has_no_lane(self):
        self.assertIsNone(self.index.nearest([500.0, 0.0, -30.0]))

    def test_point_at_interpolates_and_faces_along_the_lane(self):
        pos, heading = self.index.point_at('e1_0', 25.0)
        self.assertAlmostEqual(pos[2], -25.0, places=3)
        self.assertAlmostEqual(heading, 0.0, places=3)   # -Z is north in Godot space


@unittest.skipUnless((paths.game_dir(MAP) / 'index.json').exists(), 'Generate map first')
class GeneratedMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = paths.load_world(MAP)
        cls.index = situations.LaneIndex(cls.world['lanes'])

    def test_spawn_point_resolves_to_its_lane(self):
        spawn = self.world['spawn']
        hit = self.index.nearest(spawn['position'])
        self.assertIsNotNone(hit)
        lid, offset, distance = hit
        self.assertEqual(lid.rpartition('_')[0], spawn['edge'])
        self.assertLess(distance, 5.0)

    def test_every_indexed_lane_has_monotonic_offsets(self):
        for lid, (points, offsets) in list(self.index.lanes.items())[:2000]:
            self.assertEqual(len(points), len(offsets))
            self.assertTrue(all(b >= a for a, b in zip(offsets, offsets[1:])), lid)

    def test_lookup_is_fast_enough_for_a_bridge_tick(self):
        import time
        spawn = self.world['spawn']['position']
        start = time.perf_counter()
        for _ in range(200):
            self.index.nearest(spawn)
        per_call_ms = (time.perf_counter() - start) * 1000 / 200
        self.assertLess(per_call_ms, 5.0, f'{per_call_ms:.2f} ms per lookup')


if __name__ == '__main__':
    unittest.main()
