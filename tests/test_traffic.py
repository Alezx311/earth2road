import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import paths
from traffic import LaneHeights, far_rows, pack_frame, unpack_frame, FLOATS

def reference_height(lane,pos):
    """The bridge's original per-car walk along the lane polyline."""
    pts=lane['points']; remaining=pos
    for a,b in zip(pts,pts[1:]):
        d=math.hypot(b[0]-a[0],b[2]-a[2])
        if remaining<=d and d>0:
            return a[1]+(b[1]-a[1])*remaining/d
        remaining-=d
    return pts[-1][1]

class FrameTests(unittest.TestCase):
    def test_pack_roundtrip(self):
        blocks=[np.arange(2*FLOATS,dtype=np.float32).reshape(2,FLOATS),np.ones((3,FLOATS),dtype=np.float32)]
        header={'type':'frame','cars':[{'id':'car1','m':'sedan'}],'far':[[0,2],[5,3]],'note':'ї'}
        data=pack_frame(header,blocks)
        self.assertEqual((4+int.from_bytes(data[:4],'little'))%4,0)
        got,parsed=unpack_frame(data)
        self.assertEqual(got,header)
        np.testing.assert_array_equal(parsed[0],blocks[0])
        np.testing.assert_array_equal(parsed[5],blocks[1])

    def test_far_rows_basis_and_deltas(self):
        yaw,pitch=0.7,0.05
        prev=np.array([[1.0,2.0,3.0,yaw,pitch]]); cur=np.array([[4.0,2.5,1.0,yaw+0.1-2*math.pi,pitch]])
        row=far_rows(prev,cur,np.array([1.0]),np.array([-1.0]))[0]
        # Godot Basis(UP, yaw) * Basis(RIGHT, pitch), columns x, y, z.
        ry=np.array([[math.cos(yaw),0,math.sin(yaw)],[0,1,0],[-math.sin(yaw),0,math.cos(yaw)]])
        rx=np.array([[1,0,0],[0,math.cos(pitch),-math.sin(pitch)],[0,math.sin(pitch),math.cos(pitch)]])
        basis=ry@rx
        np.testing.assert_allclose(row[[0,1,2,4,5,6,8,9,10]].reshape(3,3),basis,atol=1e-6)
        np.testing.assert_allclose(row[[3,7,11]],[1,2,3])
        np.testing.assert_allclose(row[12:16],[1,-1,0,1])
        np.testing.assert_allclose(row[16:19],[3,0.5,-2])
        self.assertAlmostEqual(float(row[19]),0.1,places=5)   # wrapped to the short way round

MAP=__import__('os').environ.get('AKADEM_MAP','akadem')

@unittest.skipUnless((paths.game_dir(MAP)/'index.json').exists(),'Generate map first')
class HeightTests(unittest.TestCase):
    def test_vectorised_heights_match_polyline_walk(self):
        lanes=paths.load_world(MAP,tiles=True)['lanes']
        heights=LaneHeights(lanes)
        rng=np.random.default_rng(1)
        picks=rng.choice(len(lanes),400,replace=False)
        idx=[];pos=[];want=[]
        for i in picks:
            lane=lanes[i]; length=heights.lengths[i]
            for p in (0.0,float(rng.uniform(0,length)),length+3.0):
                idx.append(i);pos.append(p);want.append(reference_height(lane,p))
        got=heights.at(np.array(idx),np.array(pos))
        np.testing.assert_allclose(got,want,atol=1e-6)
        self.assertEqual(float(heights.at(np.array([-1]),np.array([5.0]))[0]),0.0)

if __name__=='__main__':
    unittest.main()

class SparseDemandTests(unittest.TestCase):
    def test_hour_without_demand_falls_back_to_routes(self):
        """A map with no homes/workplaces (e.g. a synthetic grid) must still spawn traffic."""
        import random
        from traffic import Simulation
        sim=Simulation.__new__(Simulation)
        sim.rng=random.Random(1)
        sim.routes=[['a','b'],['c']]
        sim.pools={'hw':[]}                       # non-empty dict, but nothing to pick this hour
        sim.demand={'profile':[{'hw':1.0,'wh':0.0}]*24}
        sim.clock=lambda:8*3600
        rid,edges=sim.pick_route()
        self.assertTrue(rid.startswith('r'))
        self.assertIn(edges,sim.routes)
