"""Regression contracts for steep exits, junction wedges and exact surface QA."""
import copy
import math
import unittest

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from akadem_maps.core import road_geometry as geometry, surface_audit as audit


def road(name, points, width=4., rank=2, nodes=('join',), level=(0, False, False)):
    return {'lane': name, 'points': points, 'width': width,
            'topology': {'rank': rank, 'nodes': list(nodes), 'ways': [name], 'levels': [list(level)]}}


def as_world(strips):
    return {'road_strips': [{**r, 'points': [audit.world(p) for p in r['points']],
                             **({'triangles': [[audit.world(p) for p in t] for t in r['triangles']]} if 'triangles' in r else {})}
                            for r in strips]}


class SurfaceAuditTests(unittest.TestCase):
    def test_absolute_grade_and_full_width_are_audited(self):
        r = road('a',[(0,0,0),(20,0,2)])
        lane = {'id':'a','width':4.,'points':[audit.world(p) for p in r['points']]}
        report = audit.audit({'lanes':[lane],'road_elevation':{'version':1}},[as_world([r])])
        self.assertGreater(report['absolute_grade']['over_limit'],0)
        self.assertEqual(report['profile_smooth']['over_2pct'],0)
        self.assertGreater(report['cross_section']['samples'],0)
        self.assertEqual(report['cross_section']['missing_surface'],0)

    def test_known_step_and_touching_edge_without_overlap(self):
        for y in (0, 4):
            strips = [road('a', [(0, 0, 0), (10, 0, 0)]), road('b', [(0, y, .7), (10, y, .7)])]
            report = audit.audit({'lanes': []}, [as_world(strips)])
            self.assertGreater(report['steps']['connected']['over_60cm'], 0)
            self.assertEqual(report['acceptance'], 'blocked')
            self.assertTrue(any(r['contact'] == ('overlap' if y == 0 else 'edge') for r in report['contacts']))

    def test_overpass_and_tunnel_are_not_height_thresholds(self):
        for level, z in [((1, True, False), .7), ((-1, False, True), -.7)]:
            strips = [road('ground', [(0, 0, 0), (10, 0, 0)], nodes=('a',)),
                      road('structure', [(5, -10, z), (5, 10, z)], nodes=('b',), level=level)]
            report = audit.audit({'lanes': []}, [as_world(strips)])
            self.assertEqual(report['steps']['connected']['contacts'], 0)
            self.assertGreater(report['steps']['grade_separated']['over_60cm'], 0)

    def test_unconnected_same_level_is_ambiguous(self):
        a = {'nodes': ['a'], 'levels': [[0, False, False]]}
        b = {'nodes': ['b'], 'levels': [[0, False, False]]}
        self.assertEqual(audit.relationship(a, b), 'ambiguous')
        b['levels'] = [[1, True, False]]
        b['nodes'] = ['a']
        self.assertEqual(audit.relationship(a, b), 'ambiguous')

    def test_internal_lane_grade_is_audited(self):
        lane = {'id': ':turn', 'internal': True, 'points': [[0, 0, 0], [2, 0, 0], [4, .4, 0]]}
        report = audit.audit({'lanes': [lane]}, [])
        self.assertEqual(report['profile_smooth']['over_5pct'], 1)
        # Missing pavement must not masquerade as measured surface smoothness.
        self.assertEqual(report['smooth']['over_5pct'], 0)


class SeamTests(unittest.TestCase):
    def test_opposite_directions_share_one_correction(self):
        from akadem_maps.core.scene import offset_line
        # Only the forward lane touches the main road; the reverse one must follow it.
        main = road('main', [(-30, -2, 0), (30, -2, 0)], width=4, rank=1)
        fwd = road('fwd', [(0, 0, 0), (15, 30, .8), (50, 100, 2)], width=3.2, rank=3)
        back = road('back', list(reversed(offset_line(fwd['points'], 3.2))), width=3.2, rank=3)
        fwd['topology']['edge'], back['topology']['edge'] = '77#0', '-77#0'
        geometry.align_strips([main, fwd, back])
        self.assertIn('_height', back)
        report = audit.audit({'lanes': []}, [as_world([main, fwd, back])])
        self.assertLess(report['steps']['connected']['max_m'], .05)

    def test_equal_rank_overlap_follows_earlier_road(self):
        first = road('a_first', [(-30, 0, 0), (30, 0, 0)], width=8, rank=2)
        later = road('b_later', [(0, 0, .6), (20, 25, .9), (60, 90, 1.5)], width=4, rank=2)
        original = copy.deepcopy(first)
        report = geometry.align_strips([first, later])
        self.assertEqual(first, original)
        self.assertEqual(report['counts']['aligned_strips'], 1)
        result = audit.audit({'lanes': []}, [as_world([first, later])])
        self.assertLess(result['steps']['connected']['max_m'], .05)

    def test_all_lanes_of_follower_use_one_correction_field(self):
        from akadem_maps.core.scene import offset_line
        main=road('main',[(-30,0,0),(30,0,0)],width=14,rank=1)
        a=road('side_0',[(0,0,0),(15,30,.6),(50,100,2)],width=3.52,rank=3)
        b=road('side_1',offset_line(a['points'],3.5),width=3.52,rank=3)
        a['topology']['edge']=b['topology']['edge']='side'
        geometry.align_strips([main,a,b])
        report=audit.audit({'lanes':[]},[as_world([main,a,b])])
        self.assertLess(report['steps']['connected']['max_m'],.05)

    def test_steep_exit_without_vertex_in_overlap_and_fixed_main(self):
        main = road('main', [(-30, 0, 0), (40, 0, .2)], width=14, rank=1)
        slip = road('slip', [(0, 0, 0), (15, 25, 1.5), (70, 110, 2)], rank=4)
        original = copy.deepcopy(main)
        before = copy.deepcopy(slip['points'])
        report = geometry.align_strips([main, slip])
        self.assertEqual(main, original)
        self.assertEqual(before, [(0, 0, 0), (15, 25, 1.5), (70, 110, 2)])
        self.assertEqual(report['counts']['aligned_strips'], 1)
        area = unary_union([Polygon([p[:2] for p in t]) for t in slip['triangles']])
        main_area = box(-30, -7, 40, 7)
        self.assertLess(area.intersection(main_area).area, 1e-8)
        self.assertLess(abs(slip['points'][-1][2]-2), 1e-8)
        result = audit.audit({'lanes': []}, [as_world([main, slip])])
        self.assertLessEqual(result['steps']['connected']['max_m'], .005)
        # No new abrupt grade change in the generated transition.
        grades = [(b[1][2]-a[1][2])/2 for a,b in zip(list(audit.stations(slip['points'])),list(audit.stations(slip['points']))[1:])]
        self.assertLess(max(abs(b-a) for a,b in zip(grades,grades[1:])), .05)

    def test_structure_or_missing_topology_prevents_flattening(self):
        for level, nodes in [((1, True, False), ('join',)), ((-1, False, True), ('join',)), ((0, False, False), ('unrelated',))]:
            main = road('main', [(-20,0,0),(20,0,0)], rank=1)
            slip = road('slip', [(0,0,.8),(10,30,1)], rank=3, nodes=nodes, level=level)
            original = copy.deepcopy(slip)
            geometry.align_strips([main,slip])
            self.assertEqual(slip, original)

    def test_junction_wedge_is_clipped_with_fixed_shared_edge(self):
        main = road('main', [(0,0,0),(30,0,.9)], width=10)
        original = copy.deepcopy(main)
        poly, tris, height = geometry.junction_surface(box(5,-3,25,12), [main], lambda x,y: 2.5)
        self.assertEqual(main, original)
        coverage = unary_union([Polygon([p[:2] for p in t]) for t in tris])
        self.assertLess(abs(coverage.area-poly.area), 1e-7)
        for t in tris:
            for x,y,z in t:
                if abs(y-5) < 1e-6:
                    self.assertAlmostEqual(z,.03*x,places=6)
        for x in (5, 13.5, 25):
            self.assertAlmostEqual(height(x,5),.03*x,places=5)

    def test_curve_has_fixed_endpoints_and_stays_in_corridor(self):
        from shapely.geometry import LineString
        points = [(0,0,0),(10,0,0),(15,5,0),(15,15,0)]
        curve = geometry.smooth_turn(points)
        self.assertEqual(curve[0],points[0])
        self.assertEqual(curve[-1],points[-1])
        self.assertTrue(LineString([p[:2] for p in points]).buffer(.300001).covers(LineString([p[:2] for p in curve])))

    def test_dash_phase_does_not_restart_at_virtual_points(self):
        pts = [(0,0,0),(2,0,0),(5,0,0),(10,0,0),(20,0,0)]
        parts = list(geometry.dash_parts(pts))
        self.assertEqual(len(parts),3)
        for part, (start,end) in zip(parts,[(0,3),(9,12),(18,20)]):
            self.assertAlmostEqual(part[0][0],start,places=6)
            self.assertAlmostEqual(part[-1][0],end,places=6)


if __name__ == '__main__':
    unittest.main()
