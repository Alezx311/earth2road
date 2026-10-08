"""Geometry and compatibility gates for opt-in village maps."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from shapely.geometry import Polygon, Point, mapping, shape
from shapely.ops import unary_union, transform
from pyproj import Geod, Transformer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import corridor
import rural


class BoundaryTests(unittest.TestCase):
    def test_buffer_covers_one_kilometre_around_every_outline_vertex(self):
        cfg=json.loads((ROOT/'config/rivne_mykolaiv.json').read_text(encoding='utf8'))
        outline=shape(json.loads((ROOT/cfg['boundary']['geojson']).read_text(encoding='utf8'))['features'][0]['geometry'])
        area=corridor.area(cfg)
        self.assertTrue(area.covers(outline))
        geod=Geod(ellps='WGS84')
        for lon,lat in outline.exterior.coords:
            for heading in range(0,360,15):
                x,y,_=geod.fwd(lon,lat,heading,1000)
                self.assertTrue(area.covers(Point(x,y)),(lon,lat,heading))
        project=Transformer.from_crs(4326,32636,always_xy=True).transform
        self.assertGreater(transform(project,area).area,12e6)
        self.assertLess(transform(project,area).area,14e6)

    def test_digest_changes_when_source_outline_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'outline.json'
            path.write_text('one')
            cfg={'boundary':{'geojson':str(path),'buffer_m':1000}}
            before=corridor.area_digest(cfg)
            path.write_text('two')
            self.assertNotEqual(before,corridor.area_digest(cfg))

    def test_legacy_bbox_stays_identical(self):
        cfg={'bbox':[30,50,31,51]}
        self.assertEqual(corridor.area(cfg).bounds,tuple(cfg['bbox']))
        self.assertFalse(corridor.shaped(cfg))

    def test_supplementary_outlying_footprints_are_inside_settlement(self):
        document=json.loads((ROOT/'config/areas/rivne_mykolaiv.geojson').read_text(encoding='utf8'))
        outline=shape(document['features'][0]['geometry'])
        for f in document['supplementary_footprints']:
            self.assertTrue(outline.covers(shape(f['geometry'])))


class RuralGeometryTests(unittest.TestCase):
    def test_roofs_preserve_concave_footprints_and_total_height(self):
        for pts in ([[0,0],[12,0],[12,7],[0,7]],[[0,0],[12,0],[12,4],[6,4],[6,9],[0,9]]):
            item={'id':'test','points':[[x,2,z] for x,z in pts],'height':4.8}
            rural.roof(item,{})
            roof=unary_union([Polygon([(p[0],p[2]) for p in t]) for t in item['roof_triangles']])
            self.assertLess(roof.symmetric_difference(Polygon(pts)).area,0.02)
            self.assertAlmostEqual(max(p[1] for t in item['roof_triangles'] for p in t),6.8,delta=.002)
            self.assertLess(item['wall_height'],item['height'])
            self.assertEqual(item['roof_source'],'synthetic')

    def test_tree_row_outside_the_map_area_is_skipped(self):
        # An empty intersection is a LineString too; it used to reach LocalArea as an empty point.
        from akadem_maps.core import rural as core_rural
        source = ET.fromstring('<osm><way id="1"><nd ref="1"/><nd ref="2"/><tag k="natural" v="tree_row"/></way></osm>')
        net = type('Net', (), {'convertLonLat2XY': staticmethod(lambda x, y: (x, y))})()
        fences, trees, gardens = core_rural.dress([], {}, source, {'1': (500., 0.), '2': (600., 0.)}, net,
                                                  lambda x, y: [x, 0., -y], Polygon(), Polygon.from_bounds(0, 0, 100, 100))
        self.assertEqual((fences, trees, gardens), ([], [], []))

    def test_explicit_flat_roof_stays_flat(self):
        b={'id':'a','points':[[0,0,0],[8,0,0],[8,0,6],[0,0,6]],'height':4.8}
        rural.roof(b,{'roof:shape':'flat'})
        self.assertNotIn('roof_triangles',b)
        self.assertEqual(b['roof_source'],'osm')

    def test_track_access_respects_specific_motorcar_override(self):
        self.assertTrue(rural.accessible_track({'highway':'track','surface':'ground'}))
        self.assertFalse(rural.accessible_track({'highway':'track','access':'private'}))
        self.assertFalse(rural.accessible_track({'highway':'track','motor_vehicle':'agricultural'}))
        self.assertTrue(rural.accessible_track({'highway':'track','access':'no','motorcar':'yes'}))

    def test_distinct_road_and_land_surfaces(self):
        self.assertEqual(rural.surface({'surface':'asphalt'}),'road')
        self.assertEqual(rural.surface({'surface':'compacted'}),'gravel')
        self.assertEqual(rural.surface({'surface':'ground'}),'dirt')
        self.assertEqual(rural.surface({'highway':'track'}),'dirt')
        self.assertEqual(rural.cover({'landuse':'farmland'}),'farmland')
        self.assertEqual(rural.cover({'landuse':'orchard'}),'orchard')
        self.assertFalse(rural.enabled({}))

    def test_shared_street_width_is_assumed_only_when_absent(self):
        root=ET.fromstring('<osm><way id="1"><tag k="highway" v="residential"/><tag k="lanes" v="1"/></way><way id="2"><tag k="highway" v="residential"/><tag k="lanes" v="1"/><tag k="width" v="4"/></way></osm>')
        rural.prepare_tracks(root)
        values=[{t.get('k'):t.get('v') for t in w.findall('tag')} for w in root.findall('way')]
        self.assertEqual(values[0]['width'],'5.0')
        self.assertEqual(values[0]['lanes'],'1')
        self.assertIn('assumed',values[0]['akadem:width_source'])
        self.assertEqual(values[1]['width'],'4')

    def test_boundary_road_clip_keeps_shared_nodes_and_source(self):
        root=ET.fromstring('<osm><node id="1" lon="-1" lat="2"/><node id="2" lon="2" lat="2"/><node id="3" lon="12" lat="2"/><node id="4" lon="2" lat="8"/><way id="11"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/></way><way id="12"><nd ref="2"/><nd ref="4"/><tag k="highway" v="residential"/></way></osm>')
        area=Polygon([(0,0),(10,0),(10,10),(0,10)])
        report=rural.clip_roads(root,area)
        self.assertEqual(report['cut_nodes'],2)
        ways=root.findall('way')
        self.assertTrue(all('2' in [n.get('ref') for n in w.findall('nd')] for w in ways))
        nodes={n.get('id'):Point(float(n.get('lon')),float(n.get('lat'))) for n in root.findall('node')}
        for w in ways:
            for n in w.findall('nd'): self.assertTrue(area.covers(nodes[n.get('ref')]))

    def test_estuary_multipolygon_preserves_holes(self):
        root=ET.fromstring('''<osm><way id="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
        <way id="2"><nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/></way>
        <relation id="3"><tag k="type" v="multipolygon"/><tag k="natural" v="bay"/>
        <member type="way" ref="1" role="outer"/><member type="way" ref="2" role="inner"/></relation></osm>''')
        nodes=dict(zip(map(str,range(1,9)),[(0,0),(10,0),(10,10),(0,10),(2,2),(4,2),(4,4),(2,4)]))
        covers=rural.relation_covers(root,nodes,lambda x,y:(x,y),Polygon([(0,0),(10,0),(10,10),(0,10)]))
        self.assertEqual(covers[0]['kind'],'water')
        self.assertEqual(covers[0]['poly'].area,96)


if __name__=='__main__':unittest.main()
