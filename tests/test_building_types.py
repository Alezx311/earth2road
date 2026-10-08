"""Typical models by building type: churches, mosques, fuel canopies, shop halls."""
import unittest

from shapely.geometry import Point, Polygon, box

from akadem_maps.core import building_types as bt


def item(points, height=6., source='assumed', **extra):
    return {'id': 'w1', 'points': [[x, 100., z] for x, z in points], 'height': height,
            'height_source': source, 'building_type': 'church', **extra}


def rect(w, d, x0=0., z0=0.):
    return [(x0, z0), (x0+w, z0), (x0+w, z0+d), (x0, z0+d)]


class KindTests(unittest.TestCase):
    def test_tags_select_the_kind(self):
        self.assertEqual(bt.kind({'building': 'church'}, 400, 'ukraine'), 'church_orthodox')
        self.assertEqual(bt.kind({'building': 'church'}, 400), 'church_western')
        self.assertEqual(bt.kind({'building': 'yes', 'amenity': 'place_of_worship', 'religion': 'christian',
                                  'denomination': 'catholic'}, 400, 'ukraine'), 'church_western')
        self.assertEqual(bt.kind({'building': 'yes', 'amenity': 'place_of_worship', 'religion': 'muslim'}, 400), 'mosque')
        self.assertIsNone(bt.kind({'building': 'yes', 'amenity': 'place_of_worship', 'religion': 'buddhist'}, 400))
        self.assertEqual(bt.kind({'building': 'roof', 'amenity': 'fuel'}, 300), 'fuel_canopy')
        self.assertEqual(bt.kind({'building': 'retail', 'shop': 'mall'}, 20000), 'mall')
        self.assertEqual(bt.kind({'building': 'supermarket'}, 1200), 'retail')
        self.assertIsNone(bt.kind({'building': 'retail'}, 80))           # small shop stays a plain block
        self.assertIsNone(bt.kind({'building': 'roof'}, 300))            # a roof without a fuel station

    def test_context_types_canopies_and_untyped_churches(self):
        canopy = box(0, 0, 20, 12)
        station = [(box(-10, -10, 40, 30), {'amenity': 'fuel'})]
        self.assertEqual(bt.with_context({'building': 'roof'}, canopy, station)['amenity'], 'fuel')
        self.assertNotIn('amenity', bt.with_context({'building': 'yes'}, canopy, station))
        node = [(Point(5, 5), {'amenity': 'place_of_worship', 'religion': 'christian', 'denomination': 'orthodox'})]
        typed = bt.with_context({'building': 'yes'}, canopy, node)
        self.assertEqual(bt.kind(typed, canopy.area), 'church_orthodox')
        self.assertEqual(bt.with_context({'building': 'school'}, canopy, node), {'building': 'school'})

    def test_shop_halls_and_canopies_get_their_heights(self):
        self.assertEqual(bt.heights('retail', {'building': 'retail'}, 2), (1, 4.5, None))
        self.assertEqual(bt.heights('mall', {'shop': 'mall'}, 2), (3, 13.5, None))
        self.assertIsNone(bt.heights('retail', {'building': 'retail', 'building:levels': '2'}, 2))
        self.assertEqual(bt.heights('fuel_canopy', {'building': 'roof'}, 2), (1, 5.3, 4.5))
        self.assertEqual(bt.heights('fuel_canopy', {'building': 'roof', 'min_height': '5', 'height': '6'}, 2), (1, 6.0, 5.0))


class ModelTests(unittest.TestCase):
    def check_parts(self, b, parts):
        fp = Polygon([(p[0], p[2]) for p in b['points']]).buffer(0.06)
        for part in parts:
            self.assertEqual(part['id'], b['id'])
            self.assertEqual(part['typical']['provenance'], bt.PROVENANCE)
            self.assertTrue(fp.contains(Polygon([(p[0], p[2]) for p in part['points']])), part['typical'])
            self.assertTrue(all(p[1] == 100. for p in part['points']))
            if 'roof_triangles' in part:
                top = max(v[1] for t in part['roof_triangles'] for v in t)
                self.assertAlmostEqual(top, 100. + part['height'], places=2)

    def test_orthodox_church_gets_dome_and_bell_tower(self):
        b = item(rect(30, 14))
        parts, why = bt.apply(b, 'church_orthodox', {'building': 'church'}, 'ukraine')
        self.assertIsNone(why)
        self.assertEqual(sorted(p['typical']['role'] for p in parts), ['bell_tower', 'dome'])
        self.check_parts(b, parts)
        self.assertGreater(b['height'], 9)                    # not a two-storey box
        self.assertEqual(b['local_style']['roof'], 'hipped')
        self.assertEqual(b['roof_color'], bt.PALETTE['church_orthodox']['roof'])
        dome = next(p for p in parts if p['typical']['role'] == 'dome')
        self.assertEqual(dome['roof_shape_rendered'], 'onion')
        self.assertGreater(dome['base'], 0)
        self.assertGreater(dome['height'], b['height'])
        tower = next(p for p in parts if p['typical']['role'] == 'bell_tower')
        self.assertLess(min(p[0] for p in tower['points']), 10)    # west end (-x)

    def test_small_chapel_gets_a_dome_but_no_tower(self):
        b = item(rect(12, 7))
        parts, why = bt.apply(b, 'church_orthodox', {'building': 'chapel'}, 'ukraine')
        self.assertIsNone(why)
        self.assertEqual([p['typical']['role'] for p in parts], ['dome'])

    def test_bell_tower_is_narrower_than_the_nave(self):
        b = item(rect(30, 14))
        parts, _ = bt.apply(b, 'church_orthodox', {'building': 'church'}, 'ukraine')
        tower = next(p for p in parts if p['typical']['role'] == 'bell_tower')
        self.assertLessEqual(Polygon([(p[0], p[2]) for p in tower['points']]).area, (0.5*14)**2 + 1e-6)

    def test_osm_colours_and_heights_win(self):
        b = item(rect(30, 14), height=20., source='height')
        bt.apply(b, 'church_orthodox', {'building': 'church', 'building:colour': '#ffcc00', 'roof:colour': 'red'}, 'ukraine')
        self.assertEqual(b['height'], 20.)
        self.assertEqual(b['local_style']['color'], '#ffcc00')
        self.assertEqual(b['local_style']['provenance']['color'], 'osm')
        self.assertNotIn('roof_color', b)                     # set later from roof:colour by the caller

    def test_western_church_and_mosque(self):
        b = item(rect(30, 12))
        parts, _ = bt.apply(b, 'church_western', {'building': 'church'})
        self.assertEqual([p['typical']['role'] for p in parts], ['bell_tower'])
        self.assertEqual(parts[0]['roof_shape_rendered'], 'pyramidal')
        self.check_parts(b, parts)
        m = item(rect(24, 18), building_type='mosque')
        parts, _ = bt.apply(m, 'mosque', {'building': 'mosque'})
        self.assertEqual(sorted(p['typical']['role'] for p in parts), ['dome', 'minaret'])
        self.check_parts(m, parts)

    def test_narrow_footprint_falls_back_with_reason(self):
        b = item(rect(12, 1.6))
        parts, why = bt.apply(b, 'church_orthodox', {'building': 'chapel'}, 'ukraine')
        self.assertIn('no dome', why)
        self.assertEqual(b['typical']['fallback'], why)

    def test_fuel_canopy_is_raised_on_posts(self):
        b = item(rect(24, 12), height=5.3, building_type='roof', base=4.5)
        parts, why = bt.apply(b, 'fuel_canopy', {'building': 'roof', 'amenity': 'fuel'})
        self.assertIsNone(why)
        self.assertGreaterEqual(len(parts), 4)
        self.check_parts(b, parts)
        self.assertTrue(all(p['height'] == 4.5 and 'base' not in p for p in parts))
        self.assertEqual(b['local_style']['roof'], 'flat')

    def test_retail_changes_nothing_but_the_marker(self):
        b = item(rect(40, 30), building_type='retail')
        self.assertEqual(bt.apply(b, 'retail', {'building': 'retail'}), ([], None))
        self.assertNotIn('local_style', b)
        self.assertEqual(b['typical']['kind'], 'retail')

    def test_mapped_detail_blocks_the_model(self):
        b = item(rect(30, 14))
        self.assertEqual(bt.blocked({'building': 'church', 'roof:shape': 'gabled'}, b, set()), 'osm: roof:shape')
        self.assertIn('building:part', bt.blocked({'building': 'church'}, b, {id(b)}))
        self.assertIn('building:part', bt.blocked({'building:part': 'yes'}, {**b, '_part': True}, set()))
        self.assertIsNone(bt.blocked({'building': 'church'}, b, set()))



class IntegrationTests(unittest.TestCase):
    def test_world_and_both_exports_draw_typical_models(self):
        import shutil
        import tempfile
        import xml.etree.ElementTree as ET
        from pathlib import Path
        from akadem_maps.world import build_world, validate_world
        from akadem_maps.context import read_json
        from akadem_maps.adapters.beamng.export import export_world as beam_export
        from akadem_maps.adapters.godot.export import export_world as godot_export
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            shutil.copytree(root/'examples/tiny/inputs/raw', temp/'raw')
            osm = temp/'raw/tiny.osm'
            tree = ET.parse(osm)
            source = tree.getroot()
            def way(wid, lon, lat, w, h, tags):
                refs = []
                for i, (x, y) in enumerate(((lon, lat), (lon+w, lat), (lon+w, lat+h), (lon, lat+h))):
                    nid = str(wid*10+i)
                    ET.SubElement(source, 'node', id=nid, lon=f'{x:.7f}', lat=f'{y:.7f}')
                    refs.append(nid)
                el = ET.SubElement(source, 'way', id=str(wid))
                for r in refs+refs[:1]:
                    ET.SubElement(el, 'nd', ref=r)
                for k, v in tags.items():
                    ET.SubElement(el, 'tag', k=k, v=v)
            # ~30 x 14 m church, ~24 x 13 m canopy inside a fuel area, ~55 x 33 m supermarket.
            way(3000, 30.3540, 50.4543, 0.00042, 0.000126, {'building': 'church'})
            way(3001, 30.3550, 50.4550, 0.00034, 0.000117, {'building': 'roof'})
            way(3002, 30.35495, 50.45495, 0.00044, 0.000217, {'amenity': 'fuel'})
            way(3003, 30.3560, 50.4543, 0.00077, 0.0003, {'building': 'supermarket'})
            # Not typical models, built in the same world: a tower part on a podium
            # (building:min_level only) and a school relation with a courtyard (playtest 08.10).
            way(3004, 30.3570, 50.4550, 0.0002, 0.0001, {'building:part': 'yes', 'building:levels': '16', 'building:min_level': '4'})
            way(3005, 30.3530, 50.4555, 0.0007, 0.0005, {})
            way(3006, 30.3532, 50.4557, 0.0003, 0.0003, {})
            rel = ET.SubElement(source, 'relation', id='3007')
            for ref, role in (('3005', 'outer'), ('3006', 'inner')):
                ET.SubElement(rel, 'member', type='way', ref=ref, role=role)
            for k, v in (('type', 'multipolygon'), ('building', 'school'), ('building:levels', '3')):
                ET.SubElement(rel, 'tag', k=k, v=v)
            tree.write(osm, encoding='utf8')
            cfg = read_json(root/'examples/tiny/config.json')
            cfg['region_profile'] = 'ukraine'
            build_world(cfg, temp/'world', cache=temp/'raw', config_root=temp, offline=True)
            validate_world(temp/'world')
            index = read_json(temp/'world/index.json')
            tiles = [read_json(temp/'world/tiles'/f'{tid}.json') for tid in index['tiles']]
            built = [b for t in tiles for b in t['buildings'] if 'typical' in b]
            def of(wid):
                return [b for b in built if str(b['id']) == wid]
            church = of('3000')
            self.assertEqual(sorted(b['typical'].get('role', 'main') for b in church), ['bell_tower', 'dome', 'main'])
            self.assertTrue(all('roof_triangles' in b for b in church))
            canopy = of('3001')
            self.assertEqual(canopy[0]['typical']['kind'], 'fuel_canopy')
            self.assertGreaterEqual(len(canopy), 3)
            main = next(b for b in canopy if 'role' not in b['typical'])
            self.assertEqual(main['base'], 4.5)
            hall, = of('3003')
            self.assertEqual((hall['typical']['kind'], hall['height']), ('retail', 4.5))
            every = [b for t in tiles for b in t['buildings']]
            part, = [b for b in every if str(b['id']) == '3004']
            self.assertEqual((part['base'], part['height']), (12.0, 48.0))
            self.assertTrue([b for b in every if str(b['id']) == 'r3007'])
            beam_export(temp/'world', temp/'beamng')
            godot_export(temp/'world', temp/'godot', offline=True)
            validate_world(temp/'world')

if __name__ == '__main__':
    unittest.main()
