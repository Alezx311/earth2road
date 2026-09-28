import json
from pathlib import Path
import random
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import paths
import demand
import sumolib

class ProfileTests(unittest.TestCase):
    def test_hourly_shares_sum_to_one(self):
        for hour,mix in enumerate(demand.PROFILE):
            self.assertAlmostEqual(sum(mix.values()),1.0,places=6,msg=hour)
            self.assertEqual(set(mix),set(demand.CATEGORIES))
    def test_peaks_have_direction(self):
        self.assertGreater(demand.PROFILE[8]['hw'],demand.PROFILE[8]['wh'])
        self.assertGreater(demand.PROFILE[18]['wh'],demand.PROFILE[18]['hw'])

MAP=__import__('os').environ.get('AKADEM_MAP','akadem')

@unittest.skipUnless((paths.build_dir(MAP)/'demand.json').exists(),'Run tools/prepare.py first')
class GeneratedDemandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demand=json.loads((paths.build_dir(MAP)/'demand.json').read_text())
        cls.net=sumolib.net.readNet(str(paths.build_dir(MAP)/'network.net.xml'))
    def test_every_category_has_routes(self):
        for cat in demand.CATEGORIES:
            self.assertGreater(len(self.demand['categories'][cat]),50,cat)
    def test_routes_are_connected_passenger_paths(self):
        rng=random.Random(1)
        for cat,routes in self.demand['categories'].items():
            for route in rng.sample(routes,min(40,len(routes))):
                for a,b in zip(route,route[1:]):
                    self.assertIn(self.net.getEdge(b),self.net.getEdge(a).getOutgoing(),(cat,a,b))
    def test_trip_sampling_is_reproducible(self):
        pools={'hw':({'a':1.0,'b':2.0},{'c':1.0,'d':3.0})}
        class Net:
            def getEdges(self):
                class E:
                    def __init__(s,i,x): s.i=i; s.x=x
                    def getID(s): return s.i
                    def getFunction(s): return ''
                    def getShape(s): return [(s.x,0),(s.x+1,0)]
                return [E('a',0),E('b',100),E('c',2000),E('d',3000)]
        one=demand.sample_trips(Net(),pools,50,random.Random(7))
        two=demand.sample_trips(Net(),pools,50,random.Random(7))
        self.assertEqual(one,two)
        self.assertEqual(len(one),50)

if __name__=='__main__':
    unittest.main()
