import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from beamng_corridors import bridge_rail_objects, edge_sections
from export_beamng import prop, shift_object, apply_overrides
from beamng_network import ai_spacing, carriageway_pairs, stable_id, road_network, RoadSurfaces
from road_profiles import profile_z, write_types
from beamng_road_audit import SurfaceIndex
from test_beamng_export import fixture


DOUBLE_ALLEY_NET = '''<net><location projParameter="+proj=utm +zone=36" netOffset="0,0"/>
  <edge id="up" from="j0" to="j1" type="highway.service" shape="0,0 0,120">
    <lane id="up_0" allow="passenger" width="3.2" speed="8.33"/></edge>
  <edge id="down" from="j0" to="j1" type="highway.service" shape="0,0 0,120">
    <lane id="down_0" allow="passenger" width="3.2" speed="8.33"/></edge>
  <edge id="flyover" from="j0" to="j1" type="highway.primary" shape="0,0 0,120">
    <lane id="flyover_0" allow="passenger" width="3.2" speed="22.22"/></edge>
  <junction id="j0" x="0" y="0"/><junction id="j1" x="0" y="121"/>
  </net>'''


class RoadRegressionTests(unittest.TestCase):
    def test_surface_sampling_selects_own_road_and_junction(self):
        ground = {'lane':'low', 'points':[[0,0,0],[0,2,-100]], 'width':8}
        bridge = {'lane':'high', 'points':[[0,8,0],[0,8,-100]], 'width':8}
        sampler = RoadSurfaces([('a',{'road_strips':[ground,bridge]})])
        surface = sampler.for_edge({'from':'a','to':'b','lanes':[{'id':'low'}]},None)
        self.assertTrue(surface.hits(0,50))
        self.assertTrue(all(abs(z-1)<1e-8 for z,_ in surface.hits(0,50)))

    def test_v2_navigation_keeps_height_stations_without_radius_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            index, net = fixture(Path(tmp))
            old,*_ = road_network(index,net)
            index['road_elevation'] = {'version':1}
            new,*_ = road_network(index,net)
            self.assertEqual(len(old),len(new))
            self.assertGreater(sum(len(r['nodes']) for r in new),sum(len(r['nodes']) for r in old))
            for before,after in zip(old,new):
                self.assertEqual(before['nodes'][0],after['nodes'][0])
                self.assertEqual(before['nodes'][-1],after['nodes'][-1])
                for a,b in zip(after['nodes'],after['nodes'][1:]):
                    self.assertGreater(math.dist(a[:2],b[:2]),a[3]/2)

    def rails(self, strips, walks=()):
        return bridge_rail_objects([('0', {'road_strips': strips, 'sidewalks': walks})], prop, 'rail.dae', stable_id)

    def strip(self, x, z=0, width=3.2):
        return {'points': [[x,z,0],[x,z,-50]], 'width': width, 'bridge': True}

    def test_no_guardrail_between_lanes_or_at_tile_boundary(self):
        tiles = [('a', {'road_strips':[self.strip(-1.6)]}), ('b', {'road_strips':[self.strip(1.6)]})]
        rails = bridge_rail_objects(tiles,prop,'rail.dae',stable_id)
        self.assertTrue(rails)
        self.assertTrue(all(abs(r['position'][0])>3.2 for r in rails))

    def test_rail_follows_outer_sidewalk_and_preserves_lower_road(self):
        rails = self.rails([self.strip(0),self.strip(0,-6)], [self.strip(2.6,width=2)])
        self.assertTrue(any(r['position'][0]>3.6 for r in rails))
        self.assertFalse(any(1 < r['position'][0]<3.6 and r['position'][2]>0 for r in rails))
        self.assertTrue(any(r['position'][2]<0 for r in rails))

    def test_sections_do_not_backtrack_on_short_segments(self):
        sections=list(edge_sections([(0,0,0),(0,1,0),(0,2,0),(0,7,0)]))
        self.assertEqual(len(sections),2)
        self.assertAlmostEqual(sections[0][0][1],0)
        self.assertAlmostEqual(sections[1][0][1],2.42)

    def test_rail_pitch_matches_grade(self):
        rails=self.rails([{'points':[[0,0,0],[0,3,-50]],'width':3.2,'bridge':True}])
        self.assertGreater(abs(rails[0]['rotationMatrix'][6]),.05)

    def test_straight_edges_without_shape_are_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            index,net=fixture(Path(tmp))
            text=net.read_text().replace('shape="0,122 0,150"','')
            net.write_text(text)
            roads,*_=road_network(index,net)
            self.assertEqual(len(roads),2)
            self.assertTrue(all(not r['useSubdivisions'] for r in roads))

    def test_sloping_bend_preserves_drivable_centre_height(self):
        tile={'road_strips':[{'points':[[0,0,0],[0,1,-10],[7,1.2,-15]],'width':7}]}
        surface=SurfaceIndex([tile])
        for t in (.1,.3,.5,.8):
            self.assertLess(min(abs(z-t) for z,_ in surface.heights(0,t*10)),1e-6)

    def test_profile_is_smooth_and_does_not_overshoot(self):
        pts=[(0,0,0),(10,0,1),(20,0,1.3),(30,0,.5)]
        for i in range(3):
            zs=[profile_z(pts,i,t/100) for t in range(101)]
            self.assertGreaterEqual(min(zs),min(pts[i][2],pts[i+1][2])-1e-9)
            self.assertLessEqual(max(zs),max(pts[i][2],pts[i+1][2])+1e-9)
        left=(profile_z(pts,0,1)-profile_z(pts,0,.999))/0.01
        right=(profile_z(pts,1,.001)-profile_z(pts,1,0))/0.01
        self.assertAlmostEqual(left,right,places=3)

    def test_ai_nodes_are_never_closer_than_their_navigation_radius(self):
        # BeamNG welds nodes closer than half the road width, so a 21 m carriageway
        # described every 5 m collapses into one graph node.
        dense = [(0, y) for y in range(0, 205, 5)]
        thinned = ai_spacing(dense, 21.0)
        self.assertEqual(thinned[0], dense[0])
        self.assertEqual(thinned[-1], dense[-1])
        for a, b in zip(thinned, thinned[1:]):
            self.assertGreater(math.dist(a, b), 21.0/2)

    def test_thinning_keeps_both_ends_of_a_short_road(self):
        short = [(0, 0), (0, 1.5), (0, 3)]
        self.assertEqual(ai_spacing(short, 21.0), [(0, 0), (0, 3)])

    def test_exported_roads_keep_their_junction_ends(self):
        # A road shorter than one navigation radius keeps both ends and is left for
        # the engine to weld into a junction node; anything longer must not overlap.
        with tempfile.TemporaryDirectory() as tmp:
            index, net = fixture(Path(tmp))
            roads, *_ = road_network(index, net)
            for road in roads:
                nodes = road['nodes']
                self.assertGreaterEqual(len(nodes), 2)
                if math.dist(nodes[0][:2], nodes[-1][:2]) <= max(2.0, nodes[0][3]*0.625):
                    continue
                for a, b in zip(nodes, nodes[1:]):
                    self.assertGreater(math.dist(a[:2], b[:2]), max(a[3], b[3])/2)

    def test_split_ways_pair_into_one_two_way_road(self):
        # SUMO numbers the halves of a split way independently, so 'w#0' and '-w#1'
        # are the two carriageways of one street although neither negates the other.
        edges = {'w#0': {'from': 'a', 'to': 'b', 'shape': [(0, 0), (0, 50)]},
                 '-w#1': {'from': 'b', 'to': 'a', 'shape': [(0, 50), (0, 0)]},
                 'elsewhere': {'from': 'b', 'to': 'c', 'shape': [(0, 50), (30, 50)]}}
        pairs = carriageway_pairs(edges)
        self.assertEqual(pairs['w#0'], '-w#1')
        self.assertEqual(pairs['-w#1'], 'w#0')
        self.assertNotIn('elsewhere', pairs)

    def test_one_navigation_road_per_welded_junction_pair(self):
        # Two same-direction alleys between one junction pair collapse to a single
        # navigation road; a flyover 8 m above the same pair welds nowhere and stays.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root/'game/data/test'
            build = root/'data/build/test'
            data.mkdir(parents=True)
            build.mkdir(parents=True)
            net = build/'network.net.xml'
            net.write_text(DOUBLE_ALLEY_NET, encoding='utf8')
            lanes = [{'id': 'up_0', 'edge': 'up', 'points': [[0, 0, 0], [0, 0, -120]],
                      'width': 3.2, 'speed': 8.33, 'internal': False},
                     {'id': 'down_0', 'edge': 'down', 'points': [[0, 0, 0], [0, 0, -120]],
                      'width': 3.2, 'speed': 8.33, 'internal': False},
                     {'id': 'flyover_0', 'edge': 'flyover', 'points': [[0, 8, 0], [0, 8, -120]],
                      'width': 3.2, 'speed': 22.22, 'internal': False}]
            index = {'network_sha256': 'x', 'version': 2, 'name': 'Test', 'offset': [0, 0],
                     'base_height': 150, 'bbox': [30, 50, 31, 51], 'tile_size': 500,
                     'tiles': {'0_0': [0, 0]}, 'lanes': lanes, 'signals': [], 'tls': [],
                     'spawn': {'position': [0, 0, 0], 'angle': 0}, 'attribution': 'test'}
            roads, _lanes, _location, stats, _elevation = road_network(index, net)
            self.assertEqual(len(roads), 2)
            self.assertEqual(stats['roads_duplicate_skipped'], 1)
            self.assertEqual({round(r['nodes'][0][2]) for r in roads}, {0, 8})

    def test_datum_shift_keeps_navigation_and_manual_edits_together(self):
        obj={'name':'road','class':'DecalRoad','position':[0,0,-12],'nodes':[[0,0,-12,7],[0,10,-13,7]]}
        shift_object(obj,200)
        self.assertEqual(obj['position'][2],188)
        self.assertEqual(obj['nodes'][1][2],187)
        merged,_=apply_overrides([obj],{'objects':{'road':{'base':{},'edited':{'name':'road','class':'TSStatic','position':[1,2,5]}}}}, {'vertical_offset':200})
        self.assertEqual(merged[0]['position'],[1,2,205])

    def test_datum_shift_lifts_the_fog_column_with_the_ground(self):
        # fogAtmosphereHeight is absolute; leaving it behind buries the level in haze.
        sky={'name':'theLevelInfo','class':'LevelInfo','fogAtmosphereHeight':700,'fogDensity':9e-05}
        shift_object(sky,200)
        self.assertEqual(sky['fogAtmosphereHeight'],900)
        self.assertEqual(sky['fogDensity'],9e-05)


if __name__ == '__main__':
    unittest.main()
