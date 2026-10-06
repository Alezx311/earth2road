import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from shapely.geometry import Polygon

from akadem_maps.core.local_dna import Field, roof, validate, facade_pixels, material_key
from akadem_maps.core import landmarks, osm_extract
from akadem_maps.adapters.beamng.export_beamng import building_mesh, vegetation
from akadem_maps.adapters.beamng.beamng_assets import building_style


def document():
    profile = {'architecture': {'historic': 1}, 'materials': {'plaster': 1},
               'colors': {'cream': 1}, 'floors': {'3': 1}, 'roofs': {'gabled': 1},
               'vegetation_density': .5, 'provenance': 'synthetic test'}
    return {'version': 1, 'profiles': {'a': profile}, 'anchors': [
        {'id': 'one', 'lon': 0, 'lat': 0, 'radius_m': 750, 'profile': 'a', 'provenance': 'synthetic test'}]}


def field(doc=None):
    return Field(doc or document(), lambda x, z: [x*100, 0, z*100], 311)


def building():
    return {'id': '42', 'points': [[-10, 0, -5], [10, 0, -5], [10, 0, 5], [-10, 0, 5]],
            'height': 6., 'levels': 2, 'height_source': 'assumed', 'building_type': 'yes'}


class DNATests(unittest.TestCase):
    def test_opt_in_deterministic_independent_of_anchor_order_and_building_order(self):
        d = document()
        d['anchors'].append(dict(d['anchors'][0], id='two', lon=1))
        f, g = field(d), field(dict(d, anchors=list(reversed(d['anchors']))))
        a, b = building(), building()
        f.apply(a, {})
        g.apply(dict(building(), id='other'), {})
        g.apply(b, {})
        self.assertEqual(a, b)
        self.assertEqual(a['height'], 9)
        self.assertTrue(all(v.startswith('synthetic:') for v in a['local_style']['provenance'].values()))

    def test_weights_blend_smoothly(self):
        d = document()
        d['profiles']['b'] = dict(d['profiles']['a'], colors={'grey': 1})
        d['anchors'].append(dict(d['anchors'][0], id='two', lon=4, profile='b'))
        f = field(d)
        self.assertAlmostEqual(f.sample(200, 0)['colors']['cream'], .5)
        self.assertLess(abs(f.sample(200.01, 0)['colors']['cream']-f.sample(199.99, 0)['colors']['cream']), .001)

    def test_no_anchors_and_outside_leave_building_unchanged(self):
        for d in (dict(document(), anchors=[]), document()):
            b = building()
            b['points'] = [[p[0]+10000, p[1], p[2]] for p in b['points']]
            original = copy.deepcopy(b)
            field(d).apply(b, {})
            self.assertEqual(b, original)

    def test_osm_priority_per_property(self):
        b = dict(building(), height=22., levels=7, height_source='height')
        field().apply(b, {'height': '22', 'building:levels': '7', 'building:material': 'brick',
                          'building:colour': '#aabbcc', 'roof:shape': 'flat'})
        self.assertEqual((b['height'], b['levels']), (22, 7))
        s = b['local_style']
        self.assertEqual((s['material'], s['color'], s['roof']), ('brick', '#aabbcc', 'flat'))
        self.assertEqual(s['provenance']['color'], 'osm')
        roof(b)
        self.assertNotIn('roof_triangles', b)

    def test_unknown_osm_color_is_preserved_not_replaced_by_profile(self):
        b = building()
        field().apply(b, {'building:colour': 'unrecognised'})
        self.assertIsNone(b['local_style']['color'])
        self.assertEqual(b['local_style']['observed_color'], 'unrecognised')

    def test_height_without_levels_retained(self):
        b = dict(building(), height=30., height_source='height')
        field().apply(b, {'height': '30'})
        self.assertEqual((b['height'], b['levels']), (30., 10))

    def test_roof_stays_inside_footprint_and_total_height(self):
        b = dict(building(), height=12., height_source='height')
        field().apply(b, {'height': '12'})
        roof(b)
        self.assertEqual(b['height'], 12)
        self.assertLess(b['wall_height'], 12)
        area = sum(Polygon([(p[0], p[2]) for p in t]).area for t in b['roof_triangles'])
        self.assertAlmostEqual(area, 200, places=2)
        self.assertAlmostEqual(max(p[1] for t in b['roof_triangles'] for p in t), 12)
        mesh = building_mesh(b, *building_style(b))
        self.assertAlmostEqual(max(p[2] for fs in mesh.faces.values() for t in fs for p in t), 12)
        self.assertNotEqual(building_style(b)[0], building_style(building())[0])

    def test_unsupported_roof_and_raised_passage_report_fallback(self):
        for tags, base in (({'roof:shape': 'dome'}, 0), ({}, 4.2)):
            b = dict(building(), base=base)
            field().apply(b, tags)
            roof(b)
            self.assertIn('roof_fallback', b['local_style'])
            self.assertNotIn('roof_triangles', b)

    def test_invalid_profiles_fail(self):
        for key, value in (('floors', {'0': 1}), ('colors', {'bad': 1}), ('roofs', {'flat': math.nan}),
                           ('architecture', {'alien': 1}), ('vegetation_density', -1)):
            d = document()
            d['profiles']['a'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(d)
        d = document()
        d['anchors'] *= 2
        with self.assertRaises(ValueError):
            validate(d)

    def test_zero_density_keeps_explicit_trees(self):
        d = document()
        d['profiles']['a']['vegetation_density'] = 0
        d['anchors'].append(dict(d['anchors'][0], id='overlap'))
        tiles = [('0_0', {'trees': [[0, 0, 0]], 'tree_records': [{'position': [0, 0, 0], 'provenance': 'osm'}],
                         'greens': [{'id': 'g', 'kind': 'green', 'triangles': [[[0,0,0],[100,0,0],[0,0,100]]]}]})]
        instances, counts = vegetation(tiles, field(d))
        self.assertEqual(len(instances), 1)
        self.assertEqual(counts['trees_osm'], 1)

    def test_density_fades_to_default_at_outer_coverage_edge(self):
        f = field()
        self.assertAlmostEqual(f.density(749.99, 0), 1, places=7)
        self.assertEqual(f.density(750, 0), 1)

    def test_materials_share_by_style_and_have_distinct_grammar(self):
        b = building()
        field().apply(b, {})
        s = b['local_style']
        self.assertEqual(material_key(s), material_key(dict(s, influences=[])))
        self.assertNotEqual(facade_pixels(s, 32), facade_pixels(dict(s, architecture='industrial'), 32))


class LandmarkTests(unittest.TestCase):
    def test_unsnappable_landmark_is_reported(self):
        from akadem_maps.core.pois import place
        from unittest.mock import Mock
        net, snapper = Mock(), Mock()
        net.convertLonLat2XY.return_value = (0,0)
        snapper.lane_at.return_value = None
        report = {'pois_unsnapped': []}
        points = [{'osm': 'node/1', 'kind': 'monument', 'name': 'Place', 'lon': 0, 'lat': 0}]
        self.assertEqual(place(points, [], net, snapper, None, None, report), [])
        self.assertEqual(report['pois_unsnapped'], ['node/1'])
    def test_relations_duplicates_named_selection_and_heuristic_provenance(self):
        root = ET.fromstring('''<osm><node id="1" lon="0" lat="0"><tag k="historic" v="monument"/><tag k="name" v="Place"/><tag k="wikidata" v="Q1"/></node>
        <node id="2" lon=".001" lat="0"/><node id="3" lon=".001" lat=".001"/>
        <way id="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/><tag k="historic" v="monument"/><tag k="name" v="Place"/><tag k="wikidata" v="Q1"/></way>
        <relation id="1"><member type="way" ref="1"/><tag k="leisure" v="park"/><tag k="name" v="Park"/></relation></osm>''')
        r = landmarks.discover(root, lambda x, z: [x*1e6,0,z*1e6], lambda x,z: True)
        self.assertEqual(len(r['duplicates']), 1)
        self.assertIn('relation/1', [a['id'] for a in r['candidates']])
        self.assertTrue(all(a['score_source'].startswith('heuristic:') for a in r['selected']))

    def test_landmark_spawn_near_existing_point_is_skipped(self):
        records = [{'id': 'poi_01', 'osm': None, 'position': [0, 0, 0]}]
        snapped = [{'osm': 'node/1', 'position': [100, 5, 0]}, {'osm': 'way/2', 'position': [400, 5, 0]}]
        selected = [{'osm': 'node/1', 'name': 'Near'}, {'osm': 'way/2', 'name': 'Far'}]
        self.assertEqual(landmarks.merge_spawns(records, snapped, selected), ['landmark_node_1'])
        self.assertEqual([(r['id'], r.get('title')) for r in records], [('poi_01', None), ('landmark_way_2', 'Far')])

    def test_landmark_limit_is_validated(self):
        from akadem_maps.world import validate_config
        for bad in (-1, 51, 2.5, True):
            with self.assertRaises(ValueError):
                validate_config({'local_visual_dna': {'file': 'config/visuals/podil_dna.json', 'landmark_limit': bad}})

    def test_pbf_selection_keeps_standalone_landmark(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'input.osm'
            p.write_text('<osm version="0.6"><node id="1" version="1" lon="0" lat="0"><tag k="historic" v="monument"/></node></osm>')
            dest = Path(td)/'cut.osm'
            osm_extract.extract(p, dest, [-1,-1,1,1])
            self.assertEqual(len(ET.parse(dest).getroot().findall('node')), 1)


class DNAIntegrationTests(unittest.TestCase):
    def test_world_and_both_exports_keep_provenance_and_geometry(self):
        import shutil
        from akadem_maps.world import build_world, validate_world
        from akadem_maps.context import read_json, write_json
        from akadem_maps.adapters.beamng.export import export_world as beam_export
        from akadem_maps.adapters.godot.export import export_world as godot_export
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            shutil.copytree(root/'examples/tiny/inputs/raw',temp/'raw')
            osm = temp/'raw/tiny.osm'
            tree = ET.parse(osm)
            source = tree.getroot()
            for i,(x,z) in enumerate(((30.354,50.4543),(30.3544,50.4543),(30.3544,50.4545),(30.354,50.4545)),1000):
                ET.SubElement(source,'node',id=str(i),lon=str(x),lat=str(z))
            w = ET.SubElement(source,'way',id='1000')
            for i in (1000,1001,1002,1003,1000): ET.SubElement(w,'nd',ref=str(i))
            ET.SubElement(w,'tag',k='building',v='yes')
            ET.SubElement(w,'tag',k='height',v='12')
            ET.SubElement(w,'tag',k='roof:shape',v='gabled')
            n = ET.SubElement(source,'node',id='2000',lon='30.3541',lat='50.4542')
            for k,v in (('historic','monument'),('name','Synthetic landmark')): ET.SubElement(n,'tag',k=k,v=v)
            tree.write(osm,encoding='utf8')
            d = document()
            d['anchors'] = [dict(d['anchors'][0],lon=30.354,lat=50.454,radius_m=2000)]
            write_json(temp/'dna.json',d)
            cfg = read_json(root/'examples/tiny/config.json')
            cfg['local_visual_dna']={'file':'dna.json'}
            build_world(cfg,temp/'world',cache=temp/'raw',config_root=temp,offline=True)
            validate_world(temp/'world')
            index=read_json(temp/'world/index.json')
            tiles=[read_json(temp/'world/tiles'/f'{tid}.json') for tid in index['tiles']]
            b=next(b for t in tiles for b in t['buildings'])
            self.assertEqual(b['height'],12)
            self.assertIn('roof_triangles',b)
            self.assertEqual(len(index['pois']),1)
            self.assertEqual(index['pois'][0]['osm'],'node/2000')
            beam_export(temp/'world',temp/'beamng')
            self.assertTrue((temp/'beamng/reports/local_visual_dna.json').exists())
            godot_export(temp/'world',temp/'godot',offline=True)
            # The exported world carries the shared style; adapters never mutate inputs.
            validate_world(temp/'world')
