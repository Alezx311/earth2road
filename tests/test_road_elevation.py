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
        np.testing.assert_allclose(a['main']['points'],b['main']['points'],atol=1e-10)

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
