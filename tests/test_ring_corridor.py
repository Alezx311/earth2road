"""Corridor maps: polygon area, OSM cut, quick-travel points and border stubs in the navgraph."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import corridor
import osm_extract
import pois
from beamng_network import BORDER_DRIVABILITY, border_stubs, road_network
from export_beamng import export_map, write_json
from test_beamng_export import fixture


def local_xy(lon, lat):
    return corridor.Local(30.4, 50.44).to_xy(lon, lat)


class CorridorTests(unittest.TestCase):
    def test_included_akadem_bbox_is_a_union_and_changes_digest(self):
        from shapely.geometry import box, Point
        ways = [(1, 'ring', [(30.365, 50.40), (30.365, 50.5)])]
        old = {'buffer_m': 500, 'axis': {'names': ['ring']}, 'lat_range': [50.41, 50.49]}
        spec = {**old, 'include_bboxes': [[30.342, 50.449, 30.397, 50.481]]}
        area, _ = corridor.polygon_from_axes(ways, spec)
        self.assertTrue(area.covers(box(*spec['include_bboxes'][0])))
        self.assertFalse(area.covers(Point(30.396, 50.42)))
        self.assertNotEqual(corridor.spec_digest(old, 'abc'), corridor.spec_digest(spec, 'abc'))
        with self.assertRaises(ValueError):
            corridor.include_areas(area, {'include_bboxes': [[30, 50, 29, 51]]})
        with self.assertRaises(ValueError):
            corridor.include_areas(area, {'include_bboxes': [[20, 40, 21, 41]]})

    def test_branch_buffers_join_without_filling_the_bounding_rectangle(self):
        from shapely.geometry import Point
        ways=[(1,'ring',[(30.4,50.40),(30.4,50.49)]),
              (2,'avenue',[(30.35,50.45),(30.55,50.45)])]
        spec={'buffer_m':500,'axes':[{'names':['ring'],'lat_range':[50.41,50.48]},
                                    {'names':['avenue'],'clip_bbox':[30.39,50.44,30.5,50.46]}]}
        area,axis=corridor.polygon_from_axes(ways,spec)
        self.assertTrue(area.contains(Point(30.49,50.45)))
        self.assertFalse(area.contains(Point(30.49,50.48)))
        self.assertAlmostEqual(axis.bounds[2],30.5)

    def test_polygon_buffers_the_axis_and_clips_latitude(self):
        ways = [(1, 'a', [(30.40, 50.40), (30.40, 50.45)]), (2, 'b', [(30.40, 50.45), (30.41, 50.50)])]
        polygon, axis = corridor.polygon_from_axis(ways, 500, [50.41, 50.48])
        self.assertAlmostEqual(axis.bounds[1], 50.41)
        self.assertAlmostEqual(axis.bounds[3], 50.48)
        # 500 m past the clipped ends, not the original ones.
        self.assertAlmostEqual(polygon.bounds[1], 50.41 - 500 / 110540, places=4)
        x0, _ = local_xy(30.40, 50.43)
        x1, _ = local_xy(polygon.bounds[0], 50.43)
        self.assertAlmostEqual(x0 - x1, 500, delta=3)
        self.assertFalse(polygon.interiors)

    def test_gap_in_the_axis_is_an_error_not_two_maps(self):
        ways = [(1, 'a', [(30.40, 50.40), (30.40, 50.42)]), (2, 'b', [(30.40, 50.45), (30.40, 50.47)])]
        with self.assertRaises(ValueError):
            corridor.polygon_from_axis(ways, 500, [50.3, 50.6])

    def test_bbox_maps_keep_their_rectangle(self):
        cfg = {'id': 'x', 'bbox': [30.3, 50.4, 30.5, 50.5]}
        self.assertEqual(corridor.area(cfg).bounds, (30.3, 50.4, 30.5, 50.5))

    def test_netconvert_boundary_is_a_closed_lon_lat_list(self):
        polygon, _axis = corridor.polygon_from_axis([(1, 'a', [(30.40, 50.40), (30.40, 50.45)])], 500, [50, 51])
        values = [float(v) for v in corridor.geo_boundary(polygon).split(',')]
        self.assertEqual(len(values) % 2, 0)
        self.assertEqual(values[:2], values[-2:])

    def test_extract_keeps_ways_and_pois_inside_the_polygon_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / 'in.osm', Path(tmp) / 'out.osm'
            src.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" version="1" lat="50.40" lon="30.40"/>
  <node id="2" version="1" lat="50.41" lon="30.40"/>
  <node id="3" version="1" lat="50.40" lon="30.45"/>
  <node id="4" version="1" lat="50.41" lon="30.45"/>
  <node id="5" version="1" lat="50.405" lon="30.401"><tag k="amenity" v="fuel"/><tag k="brand" v="WOG"/></node>
  <node id="6" version="1" lat="50.405" lon="30.45"><tag k="amenity" v="fuel"/></node>
  <node id="7" version="1" lat="50.405" lon="30.4005"><tag k="amenity" v="bench"/></node>
  <way id="10" version="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="trunk"/></way>
  <way id="11" version="1"><nd ref="3"/><nd ref="4"/><tag k="highway" v="residential"/></way>
</osm>''', encoding='utf8')
            polygon, _axis = corridor.polygon_from_axis([(1, 'a', [(30.40, 50.40), (30.40, 50.41)])], 500, [50, 51])
            # The bbox covers both roads; the polygon only the first.
            osm_extract.extract(src, out, [30.39, 50.39, 30.46, 50.42], polygon)
            root = ET.parse(out).getroot()
            self.assertEqual({w.get('id') for w in root.findall('way')}, {'10'})
            self.assertEqual({n.get('id') for n in root.findall('node')}, {'1', '2', '5'})


class PoiTests(unittest.TestCase):
    def test_candidates_from_nodes_and_ways(self):
        root = ET.fromstring('''<osm>
  <node id="1" lat="50.40" lon="30.40"><tag k="amenity" v="fuel"/><tag k="brand" v="OKKO"/></node>
  <node id="2" lat="50.40" lon="30.50"><tag k="shop" v="supermarket"/><tag k="name" v="Сільпо"/></node>
  <node id="3" lat="50.41" lon="30.41"/><node id="4" lat="50.41" lon="30.42"/><node id="5" lat="50.42" lon="30.42"/>
  <way id="9"><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="3"/><tag k="shop" v="mall"/><tag k="name" v="ТРЦ"/></way>
</osm>''')
        tags = lambda e: {t.get('k'): t.get('v') for t in e.findall('tag')}
        nodes = {n.get('id'): (float(n.get('lon')), float(n.get('lat'))) for n in root.findall('node')}
        found = pois.candidates(root, tags, nodes, lambda lon, lat: lon < 30.45)
        self.assertEqual([(c['osm'], c['kind'], c['name']) for c in found],
                         [('node/1', 'fuel', 'OKKO'), ('way/9', 'mall', 'ТРЦ')])
        self.assertAlmostEqual(found[1]['lon'], (30.41 + 30.42 + 30.42) / 3)

    def test_select_prefers_fuel_and_merges_close_points(self):
        found = [{'osm': 'node/1', 'kind': 'supermarket', 'name': 'АТБ', 'lon': 30.4, 'lat': 50.4},
                 {'osm': 'node/2', 'kind': 'fuel', 'name': 'WOG', 'lon': 30.4001, 'lat': 50.4},
                 {'osm': 'node/3', 'kind': 'fuel', 'name': 'SOCAR', 'lon': 30.4, 'lat': 50.41}]
        kept = pois.select(found, local_xy)
        self.assertEqual([c['osm'] for c in kept], ['node/2', 'node/3'])
        self.assertEqual(len(pois.select(found, local_xy, limit=1)), 1)

    def test_select_keeps_room_for_named_shops(self):
        fuel = [{'osm': f'node/{i}', 'kind': 'fuel', 'name': 'WOG', 'lon': 30.4, 'lat': 50.40 + i * 0.01}
                for i in range(5)]
        shops = [{'osm': 'way/1', 'kind': 'supermarket', 'name': 'Фора', 'lon': 30.5, 'lat': 50.4},
                 {'osm': 'way/2', 'kind': 'mall', 'name': 'Respublika', 'lon': 30.5, 'lat': 50.45},
                 {'osm': 'way/3', 'kind': 'department_store', 'name': 'Іваненко', 'lon': 30.5, 'lat': 50.5},
                 {'osm': 'way/4', 'kind': 'mall', 'name': '', 'lon': 30.5, 'lat': 50.55}]
        kept = pois.select(fuel + shops, local_xy, limit=4, fuel_limit=2)
        self.assertEqual([c['osm'] for c in kept], ['node/0', 'node/1', 'way/2', 'way/1'])
        # Without shops the spare places go to fuel.
        self.assertEqual(len(pois.select(fuel, local_xy, limit=4, fuel_limit=2)), 4)


class BorderStubTests(unittest.TestCase):
    def test_dead_end_at_the_outline_is_made_unattractive(self):
        with tempfile.TemporaryDirectory() as tmp:
            index, net = fixture(Path(tmp))
            # Outline 10 m past junction j2 (y=150); j0 is a dead end 100 m inside it.
            index['area'] = [[x, 0, -y] for x, y in ((-100, -100), (100, -100), (100, 160), (-100, 160), (-100, -100))]
            roads, _lanes, _location, stats, _elevation = road_network(index, net)
            self.assertEqual(stats['roads_border_stub'], 1)
            by_lanes = {r['lanesLeft']: r for r in roads}
            self.assertEqual(by_lanes[0]['drivability'], BORDER_DRIVABILITY)   # service stub b
            self.assertEqual(by_lanes[1]['drivability'], 0.75)                 # residential a

    def test_junctions_outside_the_outline_count_as_border(self):
        edges = {'a': {'from': 'j0', 'to': 'j1'}, 'b': {'from': 'j1', 'to': 'j2'}, 'c': {'from': 'j1', 'to': 'j3'}}
        junctions = {'j0': (0, 0), 'j1': (0, 100), 'j2': (0, 900), 'j3': (100, 100)}
        ring = [(-200, -200), (200, -200), (200, 300), (-200, 300)]
        self.assertEqual(border_stubs(edges, junctions, ring), {'j2'})


class ExportTests(unittest.TestCase):
    def test_pois_become_spawn_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index, _net = fixture(root)
            index['pois'] = [{'id': 'poi_01', 'title': '01 · АЗС WOG', 'position': [0, 0, -60], 'angle': 0}]
            write_json(root / 'game/data/test/index.json', index)
            report = export_map('test', root / 'out', source_root=root)
            level = root / 'out/levels/kyiv_test'
            info = json.loads((level / 'info.json').read_text(encoding='utf8'))
            self.assertEqual(info['spawnPoints'][1], {'objectname': 'spawn_poi_01', 'name': '01 · АЗС WOG',
                                                      'translationId': '01 · АЗС WOG'})
            objects = [json.loads(line) for file in level.rglob('main/**/items.level.json')
                       for line in file.read_text(encoding='utf8').splitlines() if line.strip()]
            sphere = next(o for o in objects if o['name'] == 'spawn_poi_01')
            self.assertEqual(sphere['class'], 'SpawnSphere')
            self.assertEqual(sphere['position'], [0.0, 60.0, 0.7])
            self.assertEqual(report['counts']['spawn_points'], 2)


if __name__ == '__main__':
    unittest.main()
