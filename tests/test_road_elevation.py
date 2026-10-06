import math
import unittest
import xml.etree.ElementTree as ET

import numpy as np

from akadem_maps.core import road_elevation as elevation, prepare, scene


def model(xs, sample, extra=()):
    root = ET.Element('osm')
    nodes = {str(i):(float(x), 0.) for i,x in enumerate(xs)}
    for wid, refs, tags in [('main', list(nodes), {'highway':'residential'}), *extra]:
        w = ET.SubElement(root, 'way', id=wid)
        for nid in refs:
            ET.SubElement(w, 'nd', ref=nid)
        for k,v in tags.items():
            ET.SubElement(w, 'tag', k=k, v=v)
    tags = lambda w:{t.get('k'):t.get('v') for t in w.findall('tag')}
    return elevation.ground_profiles(root,nodes,tags,prepare.drivable,lambda x,y:(x,y),sample)


class ElevationTests(unittest.TestCase):
    def test_fairing_removes_repeated_dem_waves_and_keeps_linear_grade(self):
        s = np.arange(0., 1002., 2.)
        trend = 10+.04*s
        wave = 2*np.sin(2*np.pi*s/100)
        result = elevation.fair_profile(s, trend+wave)
        self.assertLess(float(np.std((result-trend)[100:-100])), .15)
        for grade in (0., .04, -.15):
            raw = 17+grade*s
            np.testing.assert_allclose(elevation.fair_profile(s, raw), raw, atol=1e-8)

    def test_fairing_preserves_broad_terrain_and_distance_scale(self):
        s = np.arange(0., 2002., 2.)
        raw = 20*np.exp(-((s-1000)/350)**2)
        result = elevation.fair_profile(s, raw)
        self.assertGreater(result[500], 19.8)
        dense = np.arange(0., 2001., 1.)
        finer = elevation.fair_profile(dense, 20*np.exp(-((dense-1000)/350)**2))
        np.testing.assert_allclose(result, finer[::2], atol=.002)

    def test_fairing_matches_independent_dense_least_squares_solution(self):
        s = np.arange(21.)*2
        h = np.sin(s/7)+.1*s
        d = np.diff(np.eye(len(s)), n=2, axis=0)/4
        expected = np.linalg.solve(np.eye(len(s))+8**4*d.T@d, h)
        np.testing.assert_allclose(elevation.fair_profile(s, h, 8), expected, atol=1e-10)

    def test_fairing_validates_distance_samples(self):
        for s,h in (([0,2,5],[0,1,0]), ([0,0,0],[0,1,0]),
                    ([0,2,4],[0,float('nan'),0]), ([0,2,4],[0,1])):
            with self.assertRaises(ValueError):
                elevation.fair_profile(s,h)

    def test_switching_strokes_inside_one_way_has_no_height_step(self):
        root = ET.fromstring('<osm><way id="a"><nd ref="0"/><nd ref="1"/><nd ref="2"/>'
                             '<nd ref="3"/><tag k="highway" v="residential"/></way>'
                             '<way id="b"><nd ref="1"/><nd ref="4"/>'
                             '<tag k="highway" v="residential"/></way></osm>')
        nodes = {'0':(-100,0),'1':(0,0),'2':(0,5),'3':(0,100),'4':(100,0)}
        tags = lambda w:{t.get('k'):t.get('v') for t in w.findall('tag')}
        sample = lambda x,y: 3*math.exp(-(x/30)**2)+.01*y
        profiles,ground,_ = elevation.ground_profiles(root,nodes,tags,prepare.drivable,lambda x,y:(x,y),sample)
        final = elevation.constrained_profiles(profiles,ground,set())
        for wid,p in profiles.items():
            # Node synchronization must not undo the fade at the nearby (5 m)
            # unshared source node or create a new wiggle in the final profile.
            np.testing.assert_allclose(final[wid], p['points'], atol=1e-8)
            for nid,z in zip(p['refs'],p['node_z']):
                self.assertAlmostEqual(z, ground[nid])
        a = np.array(final['a'])
        ds = np.linalg.norm(np.diff(a[:,:2],axis=0),axis=1)
        self.assertLess(float(np.max(abs(np.diff(a[:,2])/ds))),.1)

    def test_small_closed_stroke_has_no_artificial_seam(self):
        root = ET.fromstring('<osm><way id="ring"><nd ref="0"/><nd ref="1"/><nd ref="2"/>'
                             '<nd ref="3"/><nd ref="0"/><tag k="highway" v="residential"/></way></osm>')
        nodes = {'0':(0,0),'1':(10,0),'2':(10,10),'3':(0,10)}
        tags = lambda w:{t.get('k'):t.get('v') for t in w.findall('tag')}
        profiles,_,_ = elevation.ground_profiles(root,nodes,tags,prepare.drivable,lambda x,y:(x,y),lambda x,y:.1*x)
        p = np.array(profiles['ring']['points'])
        self.assertAlmostEqual(p[0,2],p[-1,2])
        self.assertLess(abs((p[1,2]-p[0,2])-(p[-1,2]-p[-2,2])),.001)

    def test_side_driveway_does_not_pull_the_through_road_up(self):
        root = ET.fromstring('<osm><way id="a"><nd ref="0"/><nd ref="1"/><nd ref="2"/>'
                             '<tag k="highway" v="primary"/></way></osm>')
        nodes = {'0':(-200,0),'1':(0,0),'2':(200,0),'3':(0,40)}
        tags = lambda w:{t.get('k'):t.get('v') for t in w.findall('tag')}
        sample = lambda x,y: .02*x+2*math.exp(-(x/35)**2)+.03*y
        args = (nodes,tags,prepare.drivable,lambda x,y:(x,y),sample)
        base,_,_ = elevation.ground_profiles(root,*args)
        root.append(ET.fromstring('<way id="b"><nd ref="1"/><nd ref="3"/>'
                                 '<tag k="highway" v="service"/></way>'))
        joined,ground,_ = elevation.ground_profiles(root,*args)
        np.testing.assert_allclose(joined['a']['points'],base['a']['points'],atol=1e-9)
        self.assertAlmostEqual(joined['b']['points'][0][2],ground['1'])

    def test_inside_bend_has_one_surface_across_projection_bisector(self):
        pts = [(float(x),0.,x*.04) for x in range(-30,1,2)]
        pts += [(0.,float(y),y*.04) for y in range(2,32,2)]
        field = elevation.BendField(pts)
        self.assertEqual(len(field.bends),1)
        # Two nearest-source projections straddle the corner by four metres.
        a = field.height(-2,2-1e-5,-.08)
        b = field.height(-2,2+1e-5,.08)
        self.assertLess(abs(a-b),1e-5)
        self.assertEqual(field.height(-25,0,-1.),-1.)

    def test_roundabout_bends_blend_without_steps(self):
        # Every ring vertex is a bend; switching to the nearest bend's plane
        # stepped up to 0.25 m (Bilychi roundabout 1200327578).
        f = lambda x,y: .06*x+.004*y*y-.002*x*y
        ring = [(16*math.cos(2*math.pi*k/17),16*math.sin(2*math.pi*k/17)) for k in range(17)]
        field = elevation.BendField([(x,y,f(x,y)) for x,y in ring+ring[:1]])
        self.assertEqual(len(field.bends),17)
        for r in (13,16,19):
            hs = [field.height(r*math.cos(a),r*math.sin(a),f(r*math.cos(a),r*math.sin(a)))
                  for a in np.linspace(0,2*math.pi,3600)]
            self.assertLess(float(np.max(np.abs(np.diff(hs)))),.01)

    def test_constant_grade_and_endpoints_are_preserved(self):
        s = np.arange(0.,202.,2.)
        for grade in (0., .04, -.1):
            raw = 3+grade*s
            self.assertLess(float(np.max(np.abs(elevation.smooth(s,raw)-raw))),1e-9)

    def test_short_positive_and_negative_spikes_are_removed(self):
        s = np.arange(0.,202.,2.)
        for sign in (-1,1):
            raw = s*.03
            raw[49:52] += sign*3
            result = elevation.smooth(s,raw)
            self.assertLess(float(np.max(np.abs(result-s*.03))),.1)

    def test_broad_hill_is_retained(self):
        s = np.arange(0.,1002.,2.)
        raw = 10*np.exp(-((s-500)/150)**2)
        result = elevation.smooth(s,raw)
        self.assertGreater(result[250],9.9)
        self.assertLess(float(np.max(np.abs(result-raw))),.1)

    def test_osm_vertex_density_does_not_change_filter(self):
        sample = lambda x,y: .03*x+2*math.exp(-((x-100)/3)**2)
        a,_,_ = model([0,200],sample)
        b,_,_ = model([0,1,3,7,25,75,100,101,190,200],sample)
        aa,bb = np.array(a['main']['points']),np.array(b['main']['points'])
        np.testing.assert_allclose(aa[:,2],np.interp(aa[:,0],bb[:,0],bb[:,2]),atol=1e-10)

    def test_shared_nodes_are_exact_and_constraints_reach_dense_profile(self):
        profiles,ground,_ = model([0,30,100],lambda x,y:.03*x)
        heights = {**ground, '1': ground['1']+1}
        result = elevation.constrained_profiles(profiles,heights,set())['main']
        for x,nid in [(0,'0'),(30,'1'),(100,'2')]:
            self.assertAlmostEqual(next(p[2] for p in result if p[0]==x),heights[nid])
        self.assertLessEqual(max(math.dist(a[:2],b[:2]) for a,b in zip(result,result[1:])),2.000001)

    def test_filter_crosses_way_boundaries_but_not_disconnected_roads(self):
        root = ET.fromstring('<osm><way id="a"><nd ref="0"/><nd ref="1"/><tag k="highway" v="residential"/></way>'
                             '<way id="b"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>'
                             '<way id="c"><nd ref="3"/><nd ref="4"/><tag k="highway" v="residential"/></way></osm>')
        nodes = {'0':(0,0),'1':(100,0),'2':(200,0),'3':(0,1),'4':(200,1)}
        tags = lambda w:{t.get('k'):t.get('v') for t in w.findall('tag')}
        sample = lambda x,y:.03*x+10*y+3*math.exp(-((x-100)/2)**2)
        profiles,_,_ = elevation.ground_profiles(root,nodes,tags,prepare.drivable,lambda x,y:(x,y),sample)
        self.assertLess(abs(profiles['a']['points'][-1][2]-3),.1)
        self.assertAlmostEqual(profiles['a']['points'][-1][2],profiles['b']['points'][0][2])
        self.assertGreater(profiles['c']['points'][50][2],12.9)

    def test_straight_street_is_filtered_through_a_side_road_junction(self):
        # Chains that stopped at every branch bent straight streets at side roads.
        root = ET.fromstring('<osm><way id="a"><nd ref="0"/><nd ref="1"/><tag k="highway" v="residential"/></way>'
                             '<way id="b"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>'
                             '<way id="c"><nd ref="1"/><nd ref="3"/><tag k="highway" v="residential"/></way></osm>')
        nodes = {'0':(0,0),'1':(100,0),'2':(200,5),'3':(100,100)}
        tags = lambda w:{t.get('k'):t.get('v') for t in w.findall('tag')}
        sample = lambda x,y:.0015*(x-100)**2 if x > 100 else 0.
        profiles,_,_ = elevation.ground_profiles(root,nodes,tags,prepare.drivable,lambda x,y:(x,y),sample)
        a,b = [p[2] for p in profiles['a']['points']],[p[2] for p in profiles['b']['points']]
        self.assertAlmostEqual(a[-1],b[0])
        self.assertLess(abs((b[1]-b[0])/2-(a[-1]-a[-2])/2),.005)

    def test_structure_profile_does_not_reintroduce_dem_hump(self):
        profiles,_,_ = model([0,100],lambda x,y:8*math.exp(-((x-50)/20)**2))
        for height in (7.,-3.5):
            result = elevation.constrained_profiles(profiles,{'0':height,'1':height},{'main'})
            self.assertTrue(all(abs(p[2]-height)<1e-9 for p in result['main']))

    def test_node_correction_fades_instead_of_stopping_at_the_next_node(self):
        # A 0.5 m shared-node correction among OSM nodes 2 m apart used to be a
        # 2 m tent; now it fades over its own width, exact at shared nodes only.
        along = [0,2,4,6,8,10,60,100]
        deltas = [0,0,0,.5,0,0,0,0]
        fixed = [True,False,False,True,False,False,False,True]
        f = elevation.correction_field(along, deltas, fixed)
        self.assertEqual((f(0), f(6), f(100)), (0., .5, 0.))
        width = .5/elevation.CORRECTION_GRADE
        self.assertGreater(f(8), .45)
        self.assertAlmostEqual(f(6+width), 0., places=9)
        grades = [abs(f(s+.5)-f(s))/.5 for s in np.arange(6, 6+width, .5)]
        self.assertLess(max(grades), 1.6*elevation.CORRECTION_GRADE)
        # Between close exact nodes the correction blends from one to the other.
        g = elevation.correction_field([0,5,10], [.2,-.2,0], [True,True,True])
        self.assertAlmostEqual(g(2.5), 0., places=9)

    def test_untrusted_samples_under_a_bridge_are_bridged(self):
        # DEM under an overpass holds the deck and embankment: a 4 m hump over 60 m,
        # too wide for the robust filter to reject on its own.
        s = np.arange(0., 300., 2.)
        raw = .02*s+np.where(abs(s-150) < 30, 4., 0.)
        trusted = abs(s-150) >= 33
        filtered = elevation.smooth(s, raw, 50., trusted)
        self.assertLess(np.abs(filtered-.02*s).max(), .05)
        self.assertGreater(np.abs(elevation.smooth(s, raw, 50.)-.02*s).max(), .5)

    def test_main_roads_filter_with_a_longer_window(self):
        self.assertEqual(elevation._class_radius({'highway': 'trunk'}), elevation.CLASS_RADIUS['trunk'])
        self.assertEqual(elevation._class_radius({'highway': 'primary_link'}), elevation.CLASS_RADIUS['primary'])
        self.assertEqual(elevation._class_radius({'highway': 'residential'}), elevation.RADIUS)
        self.assertGreater(elevation.CLASS_RADIUS['trunk'], 2*elevation.RADIUS)

    def test_divided_road_carriageways_share_one_profile(self):
        def way(y, z, reverse=False):
            xs = np.arange(0., 402., 2.)
            pts = [(x, y, z+.01*x) for x in xs]
            pts = pts[::-1] if reverse else pts
            return {'points': pts, 'stations': np.arange(len(pts))*2., 'refs': ['a', 'b'],
                    'along': np.array([0., 400.]), 'node_z': np.array([pts[0][2], pts[-1][2]])}
        profiles = {'east': way(0., 0.), 'west': way(20., 1., reverse=True), 'other': way(200., 5.)}
        tags = {w: {'name': 'Main', 'oneway': 'yes', 'highway': 'trunk'} for w in profiles}
        tags['other']['name'] = 'Elsewhere'
        changed = elevation.pair_carriageways(profiles, tags)
        self.assertEqual(sorted(changed), ['east', 'west'])
        east, west = profiles['east']['points'], profiles['west']['points'][::-1]
        for (x, _, ze), (_, _, zw) in list(zip(east, west))[20:-20]:
            self.assertAlmostEqual(ze, zw, places=6)
            self.assertAlmostEqual(ze, .5+.01*x, places=6)
        self.assertEqual(profiles['other']['points'][10][2], 5.+.01*20)

    def test_bridge_deck_clears_the_road_beneath_between_nodes(self):
        deck = [(x, 0., 5.) for x in np.arange(-150., 151., 2.)]
        below = [(0., y, 0.) for y in np.arange(-100., 101., 2.)]
        profiles = {'bridge': list(deck), 'road': list(below)}
        report = elevation.deck_clearance(profiles, {'bridge': ['b1', 'b2'], 'road': ['r1', 'r2']},
                                          {'bridge': (1, True, False), 'road': (0, False, False)}, 6.5, .06)
        z = {round(x): h for x, _, h in profiles['bridge']}
        self.assertEqual(report['crossings'], 1)
        self.assertGreaterEqual(z[0], 6.5-.05)
        self.assertEqual((z[-150], z[150]), (5., 5.))
        # Crest curve: no grade above the ramp grade, no kink at the crest.
        grades = np.diff([h for _, _, h in profiles['bridge']])/2.
        self.assertLessEqual(np.abs(grades).max(), .06+1e-6)
        self.assertLess(np.abs(np.diff(grades)).max(), .01)

    def test_nonfinite_dem_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Non-finite'):
            elevation.smooth([0,2,4],[0,float('nan'),0])

    def test_ground_uses_surface_boundary_and_leaves_far_terrain(self):
        ground = scene.GroundField(lambda x,y:0,[(0,0,2),(100,0,2)],edges=[((0,0,2),(100,0,2))])
        self.assertEqual(ground(50,0),2)
        self.assertEqual(ground(50,30),0)
        self.assertGreater(ground(50,2),ground(50,4))


if __name__ == '__main__':
    unittest.main()
