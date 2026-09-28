"""Physical acceptance tests for low continuous kerbs and exact road clearance."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from beamng_curbs import build_sidewalks, HEIGHT
from beamng_geometry import Mesh
from beamng_pavement import Pavement
from beamng_corridors import Corridors
from beamng_placement import audit_building
from shapely.geometry import Point, Polygon


def p(x,y,z=0):
    return [x,z,-y]


def street():
    return {'road_strips': [{'points': [p(0,0),p(0,20)], 'width': 6}],
            'sidewalks': [{'points': [p(4,0),p(4,20)], 'width': 2}]}


class LowKerbTests(unittest.TestCase):
    def test_continuous_top_and_collision_obey_four_centimetre_cap(self):
        mesh, audit = build_sidewalks([('a', street())])
        self.assertGreater(audit['curb_length_m'], 19)
        zs = [v[2] for faces in mesh.faces.values() for t in faces for v in t]
        self.assertLessEqual(max(zs), .04)
        self.assertGreater(max(zs), .03)
        for mat, faces in mesh.faces.items():
            for tri in faces:
                self.assertTrue(all(v[0] >= 3-1e-8 for v in tri))

    def test_no_internal_wall_at_tile_boundary(self):
        a,b = street(),street()
        a['sidewalks'][0]['points'] = [p(4,0),p(4,10)]
        b['sidewalks'][0]['points'] = [p(4,10),p(4,20)]
        b['road_strips'] = []
        mesh, audit = build_sidewalks([('a',a),('b',b)])
        self.assertEqual(audit['patches'],1)
        for tri in mesh.faces['kyiv_curb']:
            if all(abs(v[1]-10)<1e-8 for v in tri):
                self.fail('Internal vertical wall at the old tile boundary')

    def test_crossing_is_lowered_to_asphalt(self):
        tile = street()
        tile['markings'] = [{'points':[p(-3,10),p(5,10)],'width':3,'dash':[.5,.6]}]
        mesh, _ = build_sidewalks([('a',tile)])
        surface = Pavement(t for faces in mesh.faces.values() for t in faces)
        hit = surface.nearest((3.1,10,0),distance=.01)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit[1],0,delta=.005)
        self.assertGreaterEqual(min(v[2] for fs in mesh.faces.values() for t in fs for v in t),-1e-8)

    def test_overlapping_decks_are_not_unioned_even_with_legacy_missing_layer(self):
        tile=street()
        tile['sidewalks'].append({'points':[p(4,0,7),p(4,20,7)],'width':2})
        tile['road_strips'].append({'points':[p(0,0,7),p(0,20,7)],'width':6})
        mesh,audit=build_sidewalks([('a',tile)])
        self.assertEqual(audit['patches'],2)
        surface=Pavement(t for fs in mesh.faces.values() for t in fs)
        for base in (0,7):
            hit=surface.nearest((3.1,10,base),distance=.01)
            self.assertAlmostEqual(hit[1]-base,HEIGHT,delta=.001)

    def test_slope_kerb_is_relative_to_asphalt(self):
        tile=street()
        tile['road_strips'][0]['points']=[p(0,0,0),p(0,20,2)]
        tile['sidewalks'][0]['points']=[p(4,0,0),p(4,20,2)]
        mesh,_=build_sidewalks([('a',tile)])
        for fs in mesh.faces.values():
            for tri in fs:
                for x,y,z in tri:
                    self.assertLessEqual(z-y*.1,.040001)

    def test_curved_asphalt_is_not_covered_by_sidewalk(self):
        tile = {'road_strips':[{'points':[p(0,0),p(0,10),p(10,10)],'width':6}],
                'sidewalks':[{'points':[p(4,0),p(4,6),p(10,6)],'width':2}]}
        roads=Pavement.from_tiles([('a',tile)])
        mesh,_=build_sidewalks([('a',tile)],roads)
        for faces in mesh.faces.values():
            for tri in faces:
                pg=Polygon([v[:2] for v in tri])
                if pg.area<1e-10: continue
                for i in roads.tree.query(pg,predicate='intersects'):
                    self.assertLess(pg.intersection(roads.polygons[i]).area,1e-7)


class EnvelopeTests(unittest.TestCase):
    def test_building_conflicts_are_reported_without_modification(self):
        import copy
        building={'id':'osm123','height':6,'points':[p(0,0),p(4,0),p(4,4),p(0,4)]}
        original=copy.deepcopy(building)
        surface=Pavement([[(1,1,0),(10,1,0),(1,10,0)]])
        audit=[]
        self.assertEqual(audit_building(building,surface,audit),[original])
        self.assertEqual(building,original)
        self.assertEqual(audit[0]['action'],'deferred')

    def test_miter_corner_uses_visible_ribbon(self):
        tile={'road_strips':[{'points':[p(0,0),p(0,10),p(10,10)],'width':6}]}
        c=Corridors([('a',tile)])
        self.assertTrue(c.occupied((-2.5,12.5,0),roads_only=True))
        self.assertFalse(c.occupied((-2.5,12.5,8),roads_only=True))

    def test_tree_trunk_volume_can_intersect_a_higher_road(self):
        surface=Pavement([[(0,0,2),(10,0,2),(0,10,2)]])
        self.assertTrue(surface.intersects(Point(2,2).buffer(.4),0,6))
        self.assertFalse(surface.intersects(Point(2,2).buffer(.4),3,6))

    def test_slope_uses_intersection_height_not_triangle_extrema(self):
        surface=Pavement([[(0,0,0),(10,0,10),(0,10,0)]])
        self.assertFalse(surface.intersects(Point(1,1).buffer(.1),8,9))
        self.assertTrue(surface.intersects(Point(8,1).buffer(.1),7,9))


if __name__=='__main__': unittest.main()
