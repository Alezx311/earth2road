"""Independent topology, boundary, fallback and offline integration contracts."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from akadem_maps.context import read_json, sha256
from akadem_maps.core import road_graph, roadgen, surface_audit as audit
from akadem_maps.core.roadgen_lab import fixture
from akadem_maps.world import build_world, validate_config


def synthetic(angles=(0,90,180), widths=None, slope=(.03,.01), length=80):
    """Analytic approaches independent of SUMO's fixture conversion."""
    arms, strips = [], {}
    for i, angle in enumerate(angles):
        u=(math.cos(math.radians(angle)),math.sin(math.radians(angle)))
        width=(widths or [7]*len(angles))[i]
        lid=str(i)
        pts=[(s*u[0],s*u[1],s*(slope[0]*u[0]+slope[1]*u[1])) for s in (4,length)]
        strips[lid]={'lane':lid,'points':pts,'width':width,'topology':{'edge':lid}}
        arms.append({'id':lid,'ways':[lid],'direction':u,'width':width,
                     'incoming':[lid],'outgoing':[lid],
                     'lanes':[{'lane':lid,'incoming':False,'edge':lid,'width':width}]})
    arms.sort(key=lambda a:math.atan2(a['direction'][1],a['direction'][0]))
    return {'id':'j','position':[0,0],'family':road_graph.classify(arms),
            'unmapped_ways':[],'levels':[[0,False,False]],'arms':arms},strips


class GraphTests(unittest.TestCase):
    def test_crossings_use_identity_and_keep_profiles(self):
        root=ET.fromstring('<osm><node id="a" lon="-1" lat="0"/><node id="b" lon="1" lat="0"/>'
                           '<node id="c" lon="0" lat="-1"/><node id="d" lon="0" lat="1"/>'
                           '<way id="1"><nd ref="a"/><nd ref="b"/><tag k="highway" v="residential"/></way>'
                           '<way id="2"><nd ref="c"/><nd ref="d"/><tag k="highway" v="residential"/>'
                           '<tag k="bridge" v="yes"/><tag k="layer" v="1"/></way></osm>')
        g=road_graph.source_graph(root,lambda t:'highway' in t)
        self.assertEqual(len(g['segments']),2)
        self.assertEqual(len(g['nodes']),4)
        self.assertEqual(g['ways']['2']['structure'],[1,True,False])
        self.assertEqual(g,road_graph.source_graph(root,lambda t:'highway' in t))

    def test_shared_middle_node_splits_ways(self):
        root=ET.fromstring('<osm><node id="a" lon="0" lat="0"/><node id="b" lon="1" lat="0"/>'
                           '<node id="c" lon="2" lat="0"/><node id="d" lon="1" lat="1"/>'
                           '<way id="1"><nd ref="a"/><nd ref="b"/><nd ref="c"/></way>'
                           '<way id="2"><nd ref="b"/><nd ref="d"/></way></osm>')
        self.assertEqual(len(road_graph.source_graph(root,lambda t:True)['segments']),3)

    def test_family_direction_and_angle(self):
        for angles,family in [((0,90,180),'T'),((0,120,240),'Y'),((0,70,180,250),'X')]:
            node,_=synthetic(angles)
            self.assertEqual(node['family'],family)
        node,_=synthetic()
        arms=node['arms']
        for i,a in enumerate(arms):
            a['incoming']=['l'] if i else []
            a['outgoing']=[] if i else ['l']
        self.assertEqual(road_graph.classify(arms),'merge')
        for a in arms: a['incoming'],a['outgoing']=a['outgoing'],a['incoming']
        self.assertEqual(road_graph.classify(arms),'split')

    def test_mode_is_opt_in_and_options_are_bounded(self):
        self.assertEqual(roadgen.options({})['mode'],'legacy')
        for value in (None,[],{'mode':'typo'},{'curve_tolerance_m':float('nan')},{'curve_tolerance_m':True}):
            with self.assertRaises(ValueError):
                validate_config({'road_geometry':value})


class TemplateTests(unittest.TestCase):
    def test_lane_areas_fill_pinholes_but_keep_real_islands(self):
        # Densified ribbons left zero-area holes between triangles and lanes
        # (536 Bilychi junctions rejected as "not a single ribbon").
        outer = [(0,0),(20,0),(20,10),(0,10)]
        speck = [(5,5),(5+1e-4,5),(5,5+1e-4)]
        island = [(12,4),(14,4),(14,6),(12,6)]
        area = roadgen._solid(Polygon(outer,[speck,island]))
        self.assertEqual(area.geom_type,'Polygon')
        self.assertEqual(len(area.interiors),1)
        self.assertAlmostEqual(area.area,196.)

    def test_adaptive_curve_stays_inside_control_hull(self):
        controls=[(0,0),(5,0),(10,5),(10,10)]
        coarse=roadgen.bezier(*controls,.1)
        fine=roadgen.bezier(*controls,.005)
        self.assertEqual(fine[0],controls[0]); self.assertEqual(fine[-1],controls[-1])
        self.assertGreater(len(fine),len(coarse))
        self.assertTrue(Polygon(controls).convex_hull.buffer(1e-9).covers(LineString(fine)))

    def test_templates_partition_and_reproduce_analytic_grade(self):
        for angles,widths in [((0,90,180),[7,7,7]),((0,70,180,250),[7,10,7,10]),
                              ((0,120,240),[7,7,7]),((0,180),[7,10])]:
            with self.subTest(angles=angles):
                node,strips=synthetic(angles,widths)
                patch=roadgen.candidate(node,strips)
                regions=[patch['core']]+[a['_band'] for a in patch['arms']]
                self.assertAlmostEqual(sum(p.area for p in regions),patch['poly'].area,places=4)
                for a in patch['arms']:
                    for p in a['outer']+a['inner']:
                        # Strips are transversely flat, so socket heights need
                        # not equal an analytic crossfall; endpoints must still
                        # be finite and match the original ribbon at the outside.
                        self.assertTrue(math.isfinite(patch['height'](*p)))
                    r=strips[a['lanes'][0]['lane']]
                    mesh=audit.TriangleIndex([('',audit.ribbon_triangles(r['points'],r['width']),{})])
                    from akadem_maps.core.road_geometry import height_on
                    for x,y in a['outer']:
                        self.assertAlmostEqual(patch['height'](x,y),height_on(mesh,x,y),places=5)

    def test_core_absorbs_approach_before_socket(self):
        # A wider arm leaves a sliver of its approach outside the curb-return
        # curve; it must become core, not stay as road under the template.
        node,strips=synthetic((0,180),[7,10])
        patch=roadgen.candidate(node,strips)
        for a in patch['arms']:
            stub=a['_area'].intersection(roadgen._halfplane(node['position'],a['direction'],a['inner_m']))
            self.assertLess(stub.difference(patch['core']).area,1e-6)

    def test_band_slices_tile_the_transition(self):
        node,strips=synthetic(slope=(.05,0))
        patch=roadgen.candidate(node,strips)
        for a in patch['arms']:
            pieces=roadgen._band_slices(a['_band'],patch['origin'],a)
            self.assertEqual(len(pieces),math.ceil((a['outer_m']-a['inner_m'])/roadgen.BAND_STEP))
            self.assertAlmostEqual(sum(p.area for p in pieces),a['_band'].area,places=6)
        self.assertEqual(roadgen._band_slices(patch['core'],patch['origin'],None),[patch['core']])

    def test_sidewalk_runs_clear_of_collar_keep_heights(self):
        pts=[(0,0,0),(10,0,1),(20,0,2),(30,0,3)]
        obstacle=Polygon([(12,-5),(18,-5),(18,5),(12,5)])
        runs=roadgen._runs_clear_of(pts,obstacle,2)
        self.assertEqual(len(runs),2)
        self.assertEqual(runs[0][0],(0,0,0)); self.assertEqual(runs[1][-1],(30,0,3))
        self.assertAlmostEqual(runs[0][-1][0],12); self.assertAlmostEqual(runs[0][-1][2],1.2)
        self.assertAlmostEqual(runs[1][0][0],18); self.assertAlmostEqual(runs[1][0][2],1.8)
        # Pieces shorter than the strip width are left to the walking area.
        self.assertEqual(roadgen._runs_clear_of(pts,Polygon([(1,-5),(29,-5),(29,5),(1,5)]),2),[])

    def test_short_and_grade_separated_approaches_are_not_forced(self):
        node,strips=synthetic(length=10)
        with self.assertRaisesRegex(roadgen.Unsupported,'too short'):
            roadgen.candidate(node,strips)
        node,strips=synthetic()
        node['levels']=[[1,True,False]]
        before=copy.deepcopy(strips)
        with self.assertRaisesRegex(roadgen.Unsupported,'structure'):
            roadgen.candidate(node,strips)
        self.assertEqual(before,strips)


    def test_dead_end_gets_a_rounded_level_cap(self):
        node,strips=synthetic((0,),[7],slope=(.05,0))
        self.assertEqual(node['family'],'endcap')
        patch=roadgen.candidate(node,strips)
        # The cap reaches a half width past the last cross-section (lanes start at 4 m).
        self.assertAlmostEqual(patch['poly'].bounds[0],4-3.5,delta=.1)
        self.assertTrue(patch['poly'].covers(Point(4-3.4,0)))
        # The approach keeps its grade; inside the cap it levels out without a step.
        for x in (6,8,10):
            self.assertAlmostEqual(patch['height'](x,0),.05*x,places=4)
        cap=[patch['height'](x,0) for x in (4,3,2,1,.6)]
        self.assertTrue(all(a>=b>=a-.06 for a,b in zip(cap,cap[1:])),cap)
        self.assertLess(abs(cap[-1]-cap[-2])/.4,.02)

    def test_through_road_keeps_its_profile_and_side_road_ramps(self):
        # The through road climbs 5 % along x; the side road is level in y.
        node,strips=synthetic((0,90,180),slope=(.05,0))
        patch=roadgen.candidate(node,strips)
        self.assertFalse(patch['planar'])
        for x in (-6,-2,0,3,6):
            # No crossfall across the through road inside the core.
            self.assertAlmostEqual(patch['height'](x,-2),patch['height'](x,2),places=4)
            self.assertAlmostEqual(patch['height'](x,0),.05*x,delta=.01)
        # The side road meets its own approach at the outer socket.
        side=next(a for a in patch['arms'] if a['direction'][1]>.9)
        from akadem_maps.core.road_geometry import height_on
        r=strips[side['lanes'][0]['lane']]
        mesh=audit.TriangleIndex([('',audit.ribbon_triangles(r['points'],r['width']),{})])
        for x,y in side['outer']:
            self.assertAlmostEqual(patch['height'](x,y),height_on(mesh,x,y),places=5)

    def test_flattest_pair_is_the_through_road(self):
        # x climbs 8 %, y 1 %: the y road carries the core, so x sees 1 % crossfall.
        node,strips=synthetic((0,90,180,270),slope=(.08,.01))
        patch=roadgen.candidate(node,strips)
        across_y=abs(patch['height'](1,0)-patch['height'](-1,0))/2
        self.assertLess(across_y,.02)

    def test_shared_lane_is_split_between_neighbours(self):
        node,strips=synthetic(length=24)
        for a in node['arms']:
            a['other']='n'+a['id']
        full=roadgen.candidate(node,strips)
        half=roadgen.candidate(node,strips,shared={'n0'})
        east=lambda p:next(a for a in p['arms'] if a['id']=='0')
        self.assertFalse(east(full)['short'])
        self.assertTrue(east(half)['short'])
        # Lanes run from 4 m to 24 m: the template keeps to its half, minus the gap.
        self.assertLessEqual(east(half)['outer_m'],14-roadgen.SHORT_GAP+1e-9)

    def test_clusters_join_junctions_on_tiny_lanes_only(self):
        def lane(lid,pts):
            return {'lane':lid,'points':[(*p,0.) for p in pts],'width':3.,'topology':{'edge':lid}}
        strips={'ab':lane('ab',[(0,0),(1.5,0)]),'bc':lane('bc',[(1.5,0),(40,0)]),
                'a1':lane('a1',[(0,0),(0,30)]),'a2':lane('a2',[(0,0),(-30,0)]),'b1':lane('b1',[(1.5,0),(1.5,30)])}
        def arm(lid,other,u):
            return {'id':lid,'other':other,'direction':u,'width':3.,'ways':[lid],
                    'lanes':[{'lane':lid,'incoming':False,'edge':lid,'width':3.}]}
        graph={'junctions':[
            {'id':'a','position':[0,0],'family':'X','levels':[[0,False,False]],'unmapped_ways':[],
             'arms':[arm('ab','b',(1,0)),arm('a1','p',(0,1)),arm('a2','q',(-1,0))]},
            {'id':'b','position':[1.5,0],'family':'X','levels':[[0,False,False]],'unmapped_ways':[],
             'arms':[arm('ab','a',(-1,0)),arm('bc','c',(1,0)),arm('b1','r',(0,1))]},
            {'id':'c','position':[40,0],'family':'endcap','levels':[[0,False,False]],'unmapped_ways':[],
             'arms':[arm('bc','b',(-1,0))]}]}
        groups=roadgen.clusters(graph,strips)
        self.assertEqual([g['members'] for g in groups],[['a','b']])
        g=groups[0]
        self.assertEqual(g['absorbed'],['ab'])
        self.assertEqual(sorted(a['id'] for a in g['arms']),['a1','a2','b1','bc'])
        self.assertEqual((g['family'],g['shape']),('cluster','X'))
        self.assertEqual(g['position'],[.75,0])


class OfflineLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.cfg,cls.cases=fixture(cls.root/'inputs','t_regular')
        cls.world=cls.root/'world'
        build_world(cls.cfg,cls.world,inputs=cls.root/'inputs',offline=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_primary_junction_uses_v2_and_keeps_lane_bindings(self):
        report=read_json(self.world/'roadgen_report.json')
        main=next(r for r in report['junctions'] if r['id']==self.cases[0]['source_nodes'][0])
        self.assertEqual(main['status'],'v2',main)
        self.assertEqual(main['family'],'T')
        graph=read_json(self.world/'road_graph.json')
        node=next(n for n in graph['junctions'] if n['id']==main['id'])
        self.assertEqual(len(node['arms']),3)
        self.assertTrue(all(a['incoming'] and a['outgoing'] for a in node['arms']))
        self.assertTrue(all(len(a['lanes'])==2 for a in node['arms']))

    def test_replay_is_deterministic_and_source_is_unchanged(self):
        other=self.root/'again'
        before=sha256(self.world/'network.net.xml')
        build_world(self.cfg,other,inputs=self.world/'inputs',offline=True)
        self.assertEqual(before,sha256(other/'network.net.xml'))
        for name in ['road_graph.json','roadgen_report.json','index.json']:
            self.assertEqual(sha256(self.world/name),sha256(other/name),name)
        self.assertEqual({p.name:sha256(p) for p in (self.world/'tiles').glob('*.json')},
                         {p.name:sha256(p) for p in (other/'tiles').glob('*.json')})

    def test_final_pavement_has_no_double_coverage_at_primary_patch(self):
        junctions=[]; roads=[]
        for tile in (self.world/'tiles').glob('*.json'):
            data=read_json(tile); junctions+=data['junctions']; roads+=data['road_strips']
        patch=next(p for p in junctions if p['id']==self.cases[0]['source_nodes'][0])
        xy=lambda tri:Polygon([(p[0],p[2]) for p in tri])
        poly=unary_union([xy(t) for t in patch['triangles']])
        for r in roads:
            overlap=poly.intersection(unary_union([xy(t) for t in r['triangles']])).area
            self.assertLess(overlap,.02,r['lane'])  # final world is quantized to millimetres
        report=read_json(self.world/'surface_audit.json')
        self.assertLess(report['steps']['connected']['max_m'],.005)
        # Every lane station has pavement under it (no cut-induced slivers).
        self.assertEqual(report['lane_surface_errors']['over_5cm'],0,report['lane_surface_errors'])


if __name__=='__main__': unittest.main()
