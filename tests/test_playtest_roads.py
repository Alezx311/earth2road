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

    def test_local_area_windows_and_nearest_match_global_geometry(self):
        import random
        from shapely.geometry import Point, box
        from shapely.ops import nearest_points, unary_union
        from akadem_maps.core.osm_buildings import LocalArea
        random.seed(5)
        area = unary_union([box(i*90-3, 0, i*90+3, 700) for i in range(8)] + [box(0, 300, 700, 306)])
        local = LocalArea(area, cell=150)
        for _ in range(40):
            x, y, r = random.uniform(-50, 750), random.uniform(-50, 750), random.uniform(1, 120)
            window = box(x-r, y-r, x+r, y+r)
            self.assertAlmostEqual(local.within(*window.bounds).symmetric_difference(area.intersection(window)).area, 0, places=6)
            p = Point(x, y)
            self.assertAlmostEqual(local.nearest(p).distance(nearest_points(p, area)[1]), 0, places=6)
        self.assertIsNone(LocalArea(box(0, 0, 0, 0).buffer(-1)).nearest(Point(0, 0)))

    def test_local_clearance_matches_whole_carriageway_buffer(self):
        # Detroit 07.10.2026: buffering the whole city per sidewalk stalled the build.
        import math
        from shapely.geometry import box, LineString
        from shapely.ops import unary_union
        from akadem_maps.core import roadgen
        blocks, size = 8, 80.0                      # 640 m: crosses several clearance cells
        roads = unary_union([box(i*size-4, 0, i*size+4, blocks*size) for i in range(blocks+1)]
                            + [box(0, j*size-4, blocks*size, j*size+4) for j in range(blocks+1)]
                            + [LineString([(0, 0), (blocks*size, blocks*size)]).buffer(6)])
        strips = [{'points': [(i*size, j*size+5.2, 0), (i*size+40, j*size+5.5, 1), (i*size+80, j*size+5.2, 0)], 'width': w}
                  for i in range(blocks) for j in range(1, blocks) for w in (1.5, 3.0)]
        got, _, _ = roadgen.clear_sidewalks(strips, [], roads)
        core = roads.buffer(-roadgen.SIDEWALK_OVERLAP)
        want = [run for s in strips for run in roadgen._runs_clear_of(
            s['points'], core.buffer(s['width']/2), max(roadgen.SIDEWALK_MIN_RUN, s['width']))]
        self.assertEqual(len(got), len(want))
        for a, b in zip(got, want):
            self.assertEqual(len(a['points']), len(b))
            # GEOS buffer approximation differs by a few cm with input size; kerb tolerance is 15 cm.
            self.assertLess(max(math.dist(p, q) for p, q in zip(a['points'], b)), 0.1)


if __name__ == '__main__':
    unittest.main()
