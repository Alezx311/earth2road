import json
import math
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import paths
from prepare import mesh_triangles
from shapely.geometry import Polygon
import sumolib

class GeometryTests(unittest.TestCase):
    def test_concave_triangulation_preserves_area(self):
        shape=Polygon([(0,0),(10,0),(10,3),(3,3),(3,10),(0,10)])
        triangles=mesh_triangles(shape)
        self.assertAlmostEqual(sum(Polygon(t).area for t in triangles),shape.area)
    def test_hole_is_not_filled(self):
        shape=Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(3,3),(7,3),(7,7),(3,7)]])
        self.assertAlmostEqual(sum(Polygon(t).area for t in mesh_triangles(shape)),84)
    def test_planar_skips_short_rings(self):
        import scene
        self.assertTrue(scene.planar([(0,0,0),(1,0,0)]).is_empty)
        self.assertTrue(scene.planar([]).is_empty)
        poly=scene.planar([(0,0,0),(4,0,0),(4,3,0),(0,3,0)])
        self.assertAlmostEqual(poly.area,12)

MAP=__import__('os').environ.get('AKADEM_MAP','akadem')

@unittest.skipUnless((paths.game_dir(MAP)/'index.json').exists(),'Generate map first')
class GeneratedMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world=paths.load_world(MAP,tiles=True)
        cls.net=sumolib.net.readNet(str(paths.build_dir(MAP)/'network.net.xml'),withInternal=True)
    def test_lane_coordinates_match_sumo(self):
        ox,oy=self.world['offset']
        for lane in self.world['lanes']:
            source=self.net.getLane(lane['id']).getShape()
            self.assertEqual(len(source),len(lane['points']))
            for (x,y),p in zip(source,lane['points']):
                self.assertAlmostEqual(x-ox,p[0],places=2)
                self.assertAlmostEqual(-(y-oy),p[2],places=2)
                self.assertTrue(all(math.isfinite(v) for v in p))
    def test_routes_have_valid_passenger_connections(self):
        routes=json.loads((paths.build_dir(MAP)/'routes.json').read_text())
        self.assertGreater(len(routes),20)
        for route in routes:
            self.assertFalse(any(e.startswith(':') for e in route))
            for a,b in zip(route,route[1:]):
                outgoing=self.net.getEdge(a).getOutgoing()
                target=self.net.getEdge(b)
                self.assertIn(target,outgoing)
                self.assertTrue(any(c.getFromLane().allows('passenger') and c.getToLane().allows('passenger') for c in outgoing[target]))
    def test_spawn_is_on_lane(self):
        sp=self.world['spawn'];x,y=sumolib.geomhelper.positionAtShapeOffset(self.net.getLane(sp['lane']).getShape(),sp['lane_position'])
        ox,oy=self.world['offset']
        self.assertLess(math.hypot(x-ox-sp['position'][0],-(y-oy)-sp['position'][2]),0.01)
    def test_signal_indices_exist(self):
        root=ET.parse(paths.build_dir(MAP)/'network.net.xml').getroot()
        widths={t.get('id'):len(t.find('phase').get('state')) for t in root.findall('tlLogic')}
        for s in self.world['signals']:
            self.assertLess(s['index'],widths[s['tls']])

@unittest.skipUnless((paths.game_dir(MAP)/'index.json').exists(),'Generate map first')
class RoadHeightTests(unittest.TestCase):
    """Lane heights come from one OSM node profile (tools/prepare.py RoadHeights)."""
    @classmethod
    def setUpClass(cls):
        cls.world=paths.load_world(MAP,tiles=True)
        cls.lanes={l['id']:l for l in cls.world['lanes']}
        cls.net=sumolib.net.readNet(str(paths.build_dir(MAP)/'network.net.xml'),withInternal=True)
    def test_lanes_of_one_edge_share_height(self):
        by_edge={}
        for lane in self.world['lanes']:
            if not lane['internal']:
                by_edge.setdefault(lane['edge'],[]).append(lane)
        worst=(0.0,'')
        for edge,lanes in by_edge.items():
            for a in lanes:
                for b in lanes:
                    if a is b: continue
                    for p in a['points']:
                        q=min(b['points'],key=lambda q:(q[0]-p[0])**2+(q[2]-p[2])**2)
                        if math.hypot(q[0]-p[0],q[2]-p[2])<4:
                            worst=max(worst,(abs(q[1]-p[1]),edge))
        self.assertLess(worst[0],0.3,worst)
    def test_connections_have_no_height_steps(self):
        for lane in self.world['lanes']:
            if lane['internal']: continue
            for conn in self.net.getLane(lane['id']).getOutgoing():
                via=conn.getViaLaneID()
                if via and via in self.lanes:
                    self.assertAlmostEqual(lane['points'][-1][1],self.lanes[via]['points'][0][1],delta=0.05,msg=(lane['id'],via))
                to=conn.getToLane().getID()
                last=via
                while last and self.net.getLane(last).getOutgoing() and self.net.getLane(last).getOutgoing()[0].getViaLaneID():
                    last=self.net.getLane(last).getOutgoing()[0].getViaLaneID()
                if last and to in self.lanes and last in self.lanes:
                    self.assertAlmostEqual(self.lanes[last]['points'][-1][1],self.lanes[to]['points'][0][1],delta=0.05,msg=(last,to))
    def test_grades_are_drivable(self):
        # Yard/garage ramps (highway.service) follow a 12% design cap plus DEM noise;
        # west_kyiv has 18–31% on those. Public roads may follow real hills: a tertiary
        # on west_kyiv peaks at 16.4%, so the cap is 18%, not akadem's flatter 16%.
        for lane in self.world['lanes']:
            if lane['internal'] or lane.get('service'): continue
            for a,b in zip(lane['points'],lane['points'][1:]):
                d=math.hypot(b[0]-a[0],b[2]-a[2])
                if d>2:
                    self.assertLess(abs(b[1]-a[1])/d,0.18,lane['id'])
    def test_service_roads_are_in_network_and_routes(self):
        service={e.getID() for e in self.net.getEdges() if e.getType()=='highway.service'}
        self.assertGreater(len(service),20)
        routes=json.loads((paths.build_dir(MAP)/'routes.json').read_text())
        self.assertTrue(any(set(r)&service for r in routes))

@unittest.skipUnless((paths.game_dir(MAP)/'index.json').exists(),'Generate map first')
class JunctionSurfaceTests(unittest.TestCase):
    """Lane strips must meet junction surfaces without steps (a step stops a car)."""
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np=np
        cls.world=paths.load_world(MAP,tiles=True)
        tris=np.array([t for j in cls.world['junctions'] for t in j['triangles']])
        cls.A,cls.B,cls.C=tris[:,0],tris[:,1],tris[:,2]
        cls.net=sumolib.net.readNet(str(paths.build_dir(MAP)/'network.net.xml'))
    def surface_z(self,x,z,near=None):
        np,A,B,C=self.np,self.A,self.B,self.C
        d=(B[:,2]-C[:,2])*(A[:,0]-C[:,0])+(C[:,0]-B[:,0])*(A[:,2]-C[:,2])
        ok=np.abs(d)>1e-9
        a=((B[:,2]-C[:,2])*(x-C[:,0])+(C[:,0]-B[:,0])*(z-C[:,2]))/np.where(ok,d,1)
        b=((C[:,2]-A[:,2])*(x-C[:,0])+(A[:,0]-C[:,0])*(z-C[:,2]))/np.where(ok,d,1)
        c=1-a-b
        m=ok&(a>=-1e-6)&(b>=-1e-6)&(c>=-1e-6)
        if not m.any(): return None
        zs=(a*A[:,1]+b*B[:,1]+c*C[:,1])[m]
        # Stacked levels (bridges over junctions): compare with the nearest surface.
        return float(zs[np.argmin(np.abs(zs-near))]) if near is not None else float(zs[0])
    def test_lane_ends_meet_junctions(self):
        steps=[]
        for lane in self.world['lanes']:
            if lane['internal'] or lane.get('service'): continue
            # netconvert leaves sub-metre stubs; the 0.1 m probe past the end then
            # samples a neighbouring junction and reports a false step (0.76 m on a
            # 0.2 m primary leftover on west_kyiv).
            try:
                if self.net.getLane(lane['id']).getEdge().getLength() < 5.0:
                    continue
            except Exception:
                pass
            p=lane['points']
            for a,b in ((p[-2],p[-1]),(p[1],p[0])):
                length=math.hypot(b[0]-a[0],b[2]-a[2]) or 1
                z=self.surface_z(b[0]+(b[0]-a[0])/length*0.1,b[2]+(b[2]-a[2])/length*0.1,b[1])
                if z is not None: steps.append((abs(z-b[1]),lane['id']))
        steps.sort()
        self.assertGreater(len(steps),50)
        # Akademmistechko is the polish corridor (p99 3 cm, max 10 cm). Larger maps
        # keep joined TLS clusters whose IDW surface can sit ~20 cm off a lane end.
        if MAP == 'akadem':
            p99, worst = 0.03, 0.10
        else:
            p99, worst = 0.05, 0.30
        self.assertLess(steps[int(len(steps)*0.99)][0], p99, steps[-5:])
        self.assertLess(steps[-1][0], worst, steps[-5:])
    def test_spawn_is_on_a_long_rightmost_lane(self):
        sp=self.world['spawn']
        edge=self.net.getEdge(sp['edge'])
        passenger=[l.getIndex() for l in edge.getLanes() if l.allows('passenger')]
        self.assertEqual(sp['lane_index'],min(passenger))
        self.assertGreaterEqual(edge.getLength(),120)
        self.assertNotEqual(edge.getType(),'highway.service')

class VehicleCatalogueTests(unittest.TestCase):
    def test_catalogue_matches_assets(self):
        catalogue=json.loads((ROOT/'config/vehicles.json').read_text())
        pack=json.loads((ROOT/'config/assets.json').read_text())['packs']['cars']
        files=set(pack['files'])
        self.assertAlmostEqual(sum(m['share'] for m in catalogue['models'].values()),1.0,places=6)
        for name,spec in catalogue['models'].items():
            self.assertIn(name+'.glb',files)
            self.assertIn(spec['class'],catalogue['sumo'])
            w,h,l=spec['size']
            self.assertTrue(1.5<=w<=2.6 and 1.2<=h<=3.5 and 3.5<=l<=9.0,name)
        self.assertTrue(set(catalogue['player_models'])<=set(catalogue['models']))
