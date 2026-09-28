import contextlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import struct
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from beamng_collision_suite import western_cases, drive_path
from report_beamng_roads import report
from beamng_terrain import write_substrate


class CollisionQA(unittest.TestCase):
    def test_native_substrate_covers_map_and_stays_below_roads(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            obj=write_substrate(p,'kyiv_test',[-1200,-1800,1900,2300],-37.2)
            self.assertLess(obj['position'][2],-137.2)
            payload=(p/'mesh-substrate.ter').read_bytes()
            version,size=struct.unpack_from('<BI',payload)
            self.assertEqual(version,9)
            self.assertEqual(len(payload),5+size*size*3+4+1+len('kyiv_test_substrate'))
            self.assertEqual(set(payload[5:5+size*size*3]),{0})
            self.assertLess(obj['position'][0],-1200)
            self.assertLess(obj['position'][1],-1800)
            self.assertGreater(obj['position'][0]+obj['squareSize']*size,1900)
            self.assertGreater(obj['position'][1]+obj['squareSize']*size,2300)

    def test_exact_spawn_and_ten_distinct_western_sites(self):
        lanes=[dict(id=str(i),width=3.5,points=[[x,0,-y],[x,0,-y-100]])
               for i,(x,y) in enumerate([(0,0)]+[(-100-i*100,j*150) for i in range(5) for j in range(3)])]
        index={'spawn':{'lane':'0','position':[0,0,-15]},'lanes':lanes}
        a=western_cases(index,ET.fromstring('<net/>'))
        self.assertEqual(a,western_cases(index,ET.fromstring('<net/>')))
        self.assertEqual(a[0]['point'],[0,15,0])
        self.assertEqual(len(a),11)
        self.assertTrue(all(c['point'][0]<0 for c in a[1:]))
        self.assertEqual(len({tuple(c['point']) for c in a}),11)
        # West sites never sit on a lane's first station (possible dead end at the map border).
        self.assertTrue(all(c['point'][1]>0 for c in a[1:]))
        for c in a:
            self.assertEqual(c['path'][0],c['point'])

    def test_paths_never_follow_dead_end_turnarounds(self):
        lanes=[dict(id=f'{i}_0',width=3.5,points=[[x,0,-y],[x,0,-y-100]])
               for i,(x,y) in enumerate([(0,0)]+[(-100-i*100,j*150) for i in range(5) for j in range(3)])]
        lanes.append(dict(id='back_0',width=3.5,points=[[5000,0,5000],[5001,0,5000]]))
        index={'spawn':{'lane':'0_0','position':[0,0,-15]},'lanes':lanes}
        net=''.join(f'<connection from="{i}" fromLane="0" to="back" toLane="0" dir="{{d}}"/>' for i in range(16))
        paths=lambda d:[c['path'] for c in western_cases(index,ET.fromstring('<net>'+net.format(d=d)+'</net>'))]
        self.assertTrue(any([5000,-5000,0] in path for path in paths('s')))
        self.assertFalse(any([5000,-5000,0] in path for path in paths('t')))

    def test_path_includes_internal_lane_instead_of_jump_across_junction(self):
        lanes={name:{'points':[[x,0,-y] for x,y in points]}
               for name,points in [('a',[(0,0),(0,10)]),(':j',[(0,10),(3,13),(6,13)]),('b',[(6,13),(60,13)])]}
        path=drive_path('a',[0,8,0],lanes,{'a':[':j'],':j':['b']})
        self.assertIn([3,13,0],path)
        self.assertEqual(path[-1],[60,13,0])

    def test_report_rejects_missing_cases_telemetry_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'profile/current';p.mkdir(parents=True)
            (p/'kyiv-qa-input.json').write_text(json.dumps({'cases':[{'name':'a'},{'name':'b'}]}))
            (p/'kyiv-qa-result.json').write_text(json.dumps({'status':'complete','version':3,'cases':[
                {'name':'a','lane':'x','point':[0,0,0],'rays':[{'error':0}], 'distance':20, 'shots':['missing-overview']}]}))
            with contextlib.redirect_stdout(io.StringIO()): summary=report(root/'profile',root/'out')
            self.assertFalse(summary['passed'])
            self.assertEqual({f['name'] for f in summary['failures']},{'a','b'})

    def test_report_rejects_floating_car_even_with_wheel_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'profile/current';p.mkdir(parents=True)
            (p/'kyiv-qa-input.json').write_text(json.dumps({'cases':[{'name':'a','expectedRays':[0,0,0,0]}]}))
            telemetry={'wheels':[{'force':100}]*4,'damage':0}
            (p/'kyiv-qa-result.json').write_text(json.dumps({'status':'complete','version':3,'cases':[
                {'name':'a','lane':'x','point':[0,0,-10],'rays':[{'error':0},{'error':0},{'error':10},{'error':10}],
                 'spawnSurface':0,'distance':20,'settled':telemetry,'driven':telemetry,'shots':[]}]}))
            with contextlib.redirect_stdout(io.StringIO()): summary=report(root/'profile',root/'out')
            self.assertFalse(summary['passed'])
            self.assertTrue(any('спавн' in issue for issue in summary['failures'][0]['issues']))


if __name__=='__main__': unittest.main()
