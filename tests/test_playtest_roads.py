"""Playtest 2026-10-06 notes 1 and 8: unnamed divided roads pair up; minor roads level out at a major road's mouth."""
import unittest

import numpy as np

from akadem_maps.core import road_elevation as re_


class PairingTests(unittest.TestCase):
    def test_pair_key_falls_back_to_ref_then_main_class(self):
        self.assertEqual(re_.pair_key({'name': 'A', 'ref': 'M06', 'highway': 'trunk'}), ('name', 'A'))
        self.assertEqual(re_.pair_key({'ref': 'M06', 'highway': 'trunk'}), ('ref', 'M06'))
        self.assertEqual(re_.pair_key({'highway': 'trunk'}), ('class', 'trunk'))
        self.assertIsNone(re_.pair_key({'highway': 'residential'}))

    def test_unnamed_trunk_carriageways_share_profile_and_get_a_median(self):
        def way(y, z, reverse):
            xs = np.arange(0., 201., 2.)
            if reverse:
                xs = xs[::-1]
            pts = [(float(x), y, z) for x in xs]
            along = np.r_[0., np.cumsum([2.]*(len(pts)-1))]
            return {'points': pts, 'stations': along.copy(), 'along': along, 'node_z': np.full(len(pts), z)}
        profiles = {'a': way(0., 10., False), 'b': way(20., 12., True)}
        tags = {'a': {'highway': 'trunk', 'oneway': 'yes'}, 'b': {'highway': 'trunk', 'oneway': 'yes'}}
        medians = []
        self.assertEqual(sorted(re_.pair_carriageways(profiles, tags, medians)), ['a', 'b'])
        za = profiles['a']['points'][50][2]
        zb = profiles['b']['points'][50][2]
        self.assertAlmostEqual(za, zb, places=6)
        self.assertEqual(len(medians), 1)
        self.assertTrue(all(abs(y-10.) < 1e-6 for _, y in medians[0]['points']))


class MouthTests(unittest.TestCase):
    def test_minor_road_meets_major_at_node_height_over_its_half_width(self):
        profiles = {'main': {'refs': ['n', 'm']}, 'svc': {'refs': ['n', 's']}}
        tags = {'main': {'highway': 'primary', 'lanes': '4', 'oneway': 'yes'}, 'svc': {'highway': 'service'}}
        (k, reach), = re_.mouths(profiles, tags)['svc']
        self.assertEqual(k, 0)
        self.assertAlmostEqual(reach, 4*re_.LANE_WIDTH/2+re_.MOUTH_MARGIN)
        self.assertNotIn('main', re_.mouths(profiles, tags))
        s = np.arange(0., 101., 1.)
        z = 14.4+0.05*s                                  # climbs 5% away from the junction
        out = re_.plateau(s, z, [(0., 14.4, reach)])
        self.assertTrue(np.allclose(out[s <= reach], 14.4))
        # Own grade plus at most the smoothstep peak of the mouth fade.
        self.assertLessEqual(float(np.diff(out).max()), 0.05+1.5*re_.MOUTH_GRADE+1e-9)
        self.assertAlmostEqual(out[-1], z[-1], places=6)


class SidewalkTests(unittest.TestCase):
    def test_sidewalk_follows_but_never_crosses_the_carriageway(self):
        from shapely.geometry import box
        from akadem_maps.core import roadgen
        road = box(0, 0, 100, 7)                     # carriageway 0 <= y <= 7
        slip = box(40, 7, 60, 12)                    # a slip road merging from above
        along = {'points': [(0, 8.0, 0), (100, 8.0, 0)], 'width': 2.0}   # 1 m kerb band beside the road
        strips, areas, report = roadgen.clear_sidewalks([along], [], road.union(slip))
        runs = sorted((min(p[0] for p in s['points']), max(p[0] for p in s['points'])) for s in strips)
        self.assertEqual(len(runs), 2)
        self.assertLessEqual(runs[0][1], 40.0)
        self.assertGreaterEqual(runs[1][0], 60.0)
        sliver = {'triangles': [[(0, 20, 0), (3, 20, 0), (0, 20.3, 0)]], 'rings': [[(0, 20, 0), (3, 20, 0), (0, 20.3, 0)]]}
        _, areas, report = roadgen.clear_sidewalks([], [sliver], road)
        self.assertEqual((areas, report['walking_slivers_dropped']), ([], 1))


if __name__ == '__main__':
    unittest.main()
