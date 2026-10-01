"""Coordinate, geometry, AI, dressing and regeneration contracts for the BeamNG adapter."""
import copy
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from beamng_assets import (DRAWN_FACADES, FOREST_ITEMS, LANDMARKS, PANEL_FACADES, PROP_SHAPES,
                           building_style, forest_files, forest_item_data, surface_materials,
                           tree_materials, uv_scales)
from beamng_geometry import Mesh, beam_point, cross, sub, ribbon, triangulate, dashed
from beamng_network import edge_profile, profile_height, road_height_audit, road_network, signals
from export_beamng import (apply_overrides, canopy_centre, canopy_mesh, capture_edits, export_map,
                           sha, sign_faces, visible_distance, write_json, write_items)


class GeometryTests(unittest.TestCase):
    def test_visible_distance_keeps_pilot_range(self):
        self.assertEqual(visible_distance([0, 0, 2000, 1500]), 4000)
        self.assertGreaterEqual(visible_distance([0, 0, 11000, 8000]), 4000)
        self.assertLessEqual(visible_distance([0, 0, 11000, 8000]), 8000)

    def test_mesh_chunks_do_not_span_a_city_tile(self):
        """A 500 m tile with a hill and a valley must not be one collision object."""
        m = Mesh()
        m.tri('kyiv_asphalt', (0, 0, 0), (2, 0, 0), (0, 2, 0), up=True)
        m.tri('kyiv_asphalt', (400, 0, 12), (402, 0, 12), (400, 2, 12), up=True)
        parts = m.chunks(50)
        self.assertEqual(len(parts), 2)
        self.assertIn((0, 0), parts)
        self.assertIn((8, 0), parts)
        self.assertEqual(parts[(0, 0)].count, 1)
        self.assertEqual(parts[(8, 0)].count, 1)

    def test_axes_and_orientation(self):
        self.assertEqual(beam_point((10, 7, -20)), (10, 20, 7))
        m = Mesh()
        m.tri('road', (0, 0, 0), (0, 2, 0), (2, 0, 0), up=True)
        a, b, c = m.faces['road'][0]
        self.assertGreater(cross(sub(b, a), sub(c, a))[2], 0)

    def test_ribbon_width_and_shared_bend(self):
        left, right = ribbon([(0, 0, 1), (0, 10, 2), (10, 10, 3)], 4)
        self.assertEqual(math.dist(left[0], right[0]), 4)
        self.assertEqual(left[1][2], right[1][2])
        self.assertLessEqual(math.dist(left[1], right[1]), 8)

    def test_concave_roof_preserves_area(self):
        ring = [(0, 0, 0), (3, 0, 0), (3, 1, 0), (1, 1, 0), (1, 3, 0), (0, 3, 0)]
        faces = triangulate(ring)
        area = sum(abs(cross(sub(b, a), sub(c, a))[2]) / 2 for a, b, c in faces)
        self.assertAlmostEqual(area, 5)
        self.assertEqual(len(faces), 4)

    def test_dash_phase_survives_polyline_vertex(self):
        pieces = list(dashed([(0, 0, 0), (3, 0, 0), (10, 0, 0)], [2, 2]))
        self.assertEqual([(round(p[0][0]), round(p[-1][0])) for p in pieces], [(0, 2), (4, 6), (8, 10)])

    def test_collada_indices_and_local_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'mesh.dae'
            m = Mesh()
            m.tri('kyiv_asphalt', (100, 200, 0), (101, 200, 0), (100, 201, 0))
            m.write(p, (100, 200, 0))
            root = ET.parse(p).getroot()
            ns = {'c': root.tag.split('}')[0][1:]}
            vertices = root.find('.//c:float_array', ns)
            self.assertEqual([float(x) for x in vertices.text.split()][:3], [0, 0, 0])
            self.assertEqual(root.find('.//c:up_axis', ns).text, 'Z_UP')
            self.assertEqual(root.find('.//c:triangles/c:p', ns).text, '0 1 2')

    def test_uv_scale_keeps_texture_world_size(self):
        """A 6 m tile over a 12 m span must repeat twice, not twelve times."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'mesh.dae'
            m = Mesh()
            m.tri('kyiv_asphalt', (0, 0, 0), (12, 0, 0), (0, 12, 0), up=True)
            m.write(p, (0, 0, 0), uv_scales={'kyiv_asphalt': 1 / 6})
            root = ET.parse(p).getroot()
            ns = {'c': root.tag.split('}')[0][1:]}
            uvs = [float(v) for v in root.findall('.//c:float_array', ns)[2].text.split()]
            self.assertEqual(max(uvs), 2.0)

    def test_explicit_uv_survives_winding_fix(self):
        m = Mesh()
        m.tri('plate', (0, 0, 0), (0, 2, 0), (2, 0, 0), up=True, uv=((0, 0), (0, 1), (1, 0)))
        self.assertEqual(m.uvs['plate'][0], ((0, 0), (1, 0), (0, 1)))


class AssetTests(unittest.TestCase):
    def test_every_forest_instance_has_item_data(self):
        items = forest_item_data()
        self.assertEqual(set(items), set(FOREST_ITEMS))
        files = forest_files([('kyiv_bush', 1, 2, 3, math.pi, 1.5)])
        self.assertEqual(list(files), ['forest/kyiv_bush.forest4.json'])
        entry = json.loads(files['forest/kyiv_bush.forest4.json'].strip())
        self.assertEqual(entry['type'], 'kyiv_bush')
        self.assertEqual(entry['pos'], [1, 2, 3])
        self.assertEqual(entry['scale'], 1.5)
        self.assertAlmostEqual(entry['rotationMatrix'][0], -1.0, places=3)   # cos(pi)
        self.assertEqual(entry['rotationMatrix'][8], 1)

    def test_asset_paths_point_at_shared_libraries(self):
        for shape, _radius, _wind in FOREST_ITEMS.values():
            self.assertTrue(shape.startswith('/assets/meshes/'), shape)
        for shape in PROP_SHAPES.values():
            self.assertTrue(shape.startswith('/art/shapes/'), shape)
        for name, material in {**surface_materials(), **tree_materials()}.items():
            for stage in material['Stages']:
                for key, value in stage.items():
                    if key.endswith('Map'):
                        self.assertTrue(value.startswith('/assets/materials/'), f'{name}.{key}={value}')

    def test_building_style_is_stable_and_type_aware(self):
        block = {'id': '123', 'building_type': 'apartments', 'height': 42}
        self.assertEqual(building_style(block), building_style(dict(block)))
        facade, roof = building_style(block)
        self.assertIn(facade, PANEL_FACADES)  # tall blocks keep the windowed panel skins
        self.assertEqual(roof, 'kyiv_roof_flat')
        shed, shed_roof = building_style({'id': '123', 'building_type': 'garage', 'height': 3})
        self.assertEqual((shed, shed_roof), ('kyiv_fac_block', 'kyiv_roof_tin'))
        # Named ring landmarks keep a synthetic commercial skin instead of the type hash.
        mall = {'id': '446901282', 'building_type': 'commercial', 'height': 6}
        self.assertEqual(building_style(mall), ('kyiv_fac_curtain', 'kyiv_roof_flat'))
        box = {'id': '31728267', 'building_type': 'retail', 'height': 6}
        self.assertEqual(building_style(box), ('kyiv_fac_cladding', 'kyiv_roof_flat'))
        self.assertIn('31728267', LANDMARKS)

    def test_sidewalk_is_plain_concrete(self):
        path = surface_materials()['kyiv_concrete']['Stages'][0]['baseColorMap']
        self.assertIn('sidewalk1', path)
        self.assertNotIn('italy', path)

    def test_drawn_facades_have_a_real_world_repeat(self):
        scales = uv_scales()
        self.assertTrue(set(DRAWN_FACADES) <= set(scales))
        self.assertAlmostEqual(scales['kyiv_fac_curtain'], 1 / 8)

    def test_fuel_canopy_stands_off_the_carriageway(self):
        # Heading 0 travels north; the right-hand side is +X. Pavement occupies x < 8.
        centre = canopy_centre([0, 1, 0], 0, lambda p: p[0] < 8)
        self.assertIsNotNone(centre)
        self.assertGreaterEqual(centre[0], 16)
        self.assertAlmostEqual(centre[1], 0)
        self.assertIsNone(canopy_centre([0, 1, 0], 0, lambda p: True))
        mesh = canopy_mesh(centre, 0)
        self.assertGreater(mesh.count, 12)
        deck = [z for tri in mesh.faces['kyiv_fac_cladding'] for p in tri for z in (p[2],)]
        self.assertGreater(min(deck), centre[2] + 4.5)

    def test_uv_scales_cover_every_drawn_material(self):
        scales = uv_scales()
        self.assertTrue(set(surface_materials()) <= set(scales))
        self.assertTrue(set(PANEL_FACADES) <= set(scales))
        self.assertAlmostEqual(scales['kyiv_asphalt'], 1 / 6)

    def test_sign_faces_cover_the_snapshot_kinds(self):
        faces = sign_faces()
        for key in (('oneway', None), ('give_way', None), ('priority_road', None),
                    ('speed_limit', '40'), ('speed_limit', '50')):
            canvas, shape = faces[key]
            self.assertIn(shape, ('round', 'tri', 'diamond', 'wide'))
            opaque = sum(1 for row in canvas for px in row if px[3])
            self.assertGreater(opaque, 1000)
            self.assertLess(opaque, len(canvas) ** 2)  # the outline leaves transparent corners


def fixture(root):
    data = root / 'game/data/test'
    build = root / 'data/build/test'
    data.mkdir(parents=True)
    build.mkdir(parents=True)
    net = build / 'network.net.xml'
    net.write_text('''<net><location projParameter="+proj=utm +zone=36" netOffset="0,0"/>
      <edge id="a" from="j0" to="j1" type="highway.residential" shape="0,0 0,120">
        <lane id="a_0" allow="passenger" width="3.2" speed="13.89"/>
        <lane id="a_1" allow="pedestrian" width="2.0" speed="5"/></edge>
      <edge id="-a" from="j1" to="j0" type="highway.residential" shape="0,120 0,0">
        <lane id="-a_0" allow="passenger" width="3.2" speed="13.89"/></edge>
      <edge id=":j1_0" function="internal"><lane id=":j1_0_0" allow="passenger"/></edge>
      <edge id="b" from="j1" to="j2" type="highway.service" shape="0,122 0,150">
        <lane id="b_0" allow="passenger" width="3.0" speed="8.33"/></edge>
      <junction id="j0" x="0" y="0"/><junction id="j1" x="0" y="121"/><junction id="j2" x="0" y="150"/>
      </net>''', encoding='utf8')
    lanes = [{'id': lid, 'edge': lid.rsplit('_', 1)[0], 'points': p, 'width': 3.2, 'speed': 13.89,
              'internal': lid.startswith(':')}
             for lid, p in [('a_0', [[0, 0, 0], [0, 0, -60], [0, 0, -120]]),
                            ('-a_0', [[0, 0, -120], [0, 0, -60], [0, 0, 0]]),
                            (':j1_0_0', [[0, 0, -120], [0, 0, -122]]),
                            ('b_0', [[0, 0, -122], [0, 0, -150]]),
                            ('a_1', [[5, 0, 0], [5, 0, -120]])]]
    index = {'network_sha256': sha(net), 'version': 2, 'name': 'Test', 'offset': [0, 0], 'base_height': 150,
             'bbox': [30, 50, 31, 51], 'tile_size': 500, 'tiles': {'0_0': [0, 0]}, 'lanes': lanes,
             'signals': [{'tls': 'junction', 'lane': 'a_0', 'index': 0, 'position': [0, 0, -118]}],
             'tls': [{'id': 'junction', 'default_program': '0', 'programs': {'0': [[10, 'G'], [3, 'y'], [10, 'r']]}}],
             'spawn': {'position': [0, 0, 0], 'angle': 0}, 'attribution': 'test fixture'}
    write_json(data / 'index.json', index)
    write_json(data / 'tiles/0_0.json', {
        'ground': [[[-5, 0, 5], [5, 0, 5], [0, 0, -160]]],
        'road_strips': [{'points': [[0, 0, 0], [0, 0, -120]], 'width': 3.2, 'bridge': False},
                        {'points': [[0, 0, -122], [0, 0, -150]], 'width': 3.0, 'bridge': True}],
        'trees': [[6, 0, -4]],
        'greens': [{'id': 'park', 'kind': 'wood',
                    'triangles': [[[-40, 0, 0], [-10, 0, 0], [-10, 0, -30]]]}],
        'signs': [{'kind': 'speed_limit', 'value': '50', 'position': [1, 0, -6], 'yaw': 0.0},
                  {'kind': 'give_way', 'value': None, 'position': [1, 0, -8], 'yaw': 0.0},
                  {'kind': 'traffic_calming', 'value': None, 'position': [1, 0, -9], 'yaw': 0.0}],
        'buildings': [{'id': 'split', 'points': [[8, 0, 0], [12, 0, 0], [12, 0, 5], [8, 0, 5]], 'height': 8,
                       'building_type': 'apartments'},
                      {'id': 'split', 'points': [[12, 0, 0], [15, 0, 0], [15, 0, 5], [12, 0, 5]], 'height': 8,
                       'base': 4.2, 'building_type': 'apartments'}]})
    return index, net


class NetworkTests(unittest.TestCase):
    def test_paired_directions_become_one_two_way_road(self):
        with tempfile.TemporaryDirectory() as tmp:
            index, net = fixture(Path(tmp))
            roads, lanes, _location, stats, _elevation = road_network(index, net)
            self.assertNotIn('a_1', lanes)
            self.assertNotIn(':j1_0_0', lanes)
            self.assertEqual(stats['roads'], 2)
            by_name = {r['lanesLeft']: r for r in roads}
            two_way = by_name[1]
            self.assertFalse(two_way['oneWay'])
            self.assertEqual(two_way['lanesRight'], 1)
            self.assertFalse(two_way['autoLanes'])
            self.assertEqual(two_way['nodes'][0][3], 6.4)  # both carriageways set the width
            # The fixture's only shape point sits 1 m short of the junction centre,
            # inside the 3.2 m navigation radius, so ai_spacing drops it; the road
            # still spans both junctions. Shape points farther apart are kept —
            # see test_ai_nodes_are_never_closer_than_their_navigation_radius.
            self.assertEqual([n[:2] for n in two_way['nodes']], [[0.0, 0.0], [0.0, 121.0]])
            one_way = by_name[0]
            self.assertTrue(one_way['oneWay'])
            self.assertEqual(one_way['drivability'], 0.4)  # service road

    def test_roads_end_on_junction_centres_so_the_graph_connects(self):
        with tempfile.TemporaryDirectory() as tmp:
            index, net = fixture(Path(tmp))
            roads, _lanes, _location, _stats, _elevation = road_network(index, net)
            ends = {(round(r['nodes'][0][0], 2), round(r['nodes'][0][1], 2)) for r in roads}
            ends |= {(round(r['nodes'][-1][0], 2), round(r['nodes'][-1][1], 2)) for r in roads}
            self.assertIn((0.0, 121.0), ends)  # the shared junction, not the trimmed edge ends
            for road in roads:
                for node in road['nodes']:
                    self.assertAlmostEqual(node[2], 0.0, places=3)  # height sampled from the snapshot

    def test_grade_separated_roads_keep_their_own_height(self):
        """An overpass sharing XY with the surface road must not donate its Z to the DecalRoad below."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'game/data/test'
            build = root / 'data/build/test'
            data.mkdir(parents=True)
            build.mkdir(parents=True)
            net = build / 'network.net.xml'
            net.write_text('''<net><location projParameter="+proj=utm +zone=36" netOffset="0,0"/>
              <edge id="ground" from="j0" to="j1" type="highway.residential" shape="0,0 0,120">
                <lane id="ground_0" allow="passenger" width="3.2" speed="13.89"/></edge>
              <edge id="flyover" from="j0" to="j1" type="highway.primary" shape="0,0 0,120">
                <lane id="flyover_0" allow="passenger" width="3.2" speed="22.22"/></edge>
              <junction id="j0" x="0" y="0"/><junction id="j1" x="0" y="121"/>
              </net>''', encoding='utf8')
            lanes = [
                {'id': 'ground_0', 'edge': 'ground', 'points': [[0, 0, 0], [0, 0, -60], [0, 0, -120]],
                 'width': 3.2, 'speed': 13.89, 'internal': False},
                {'id': 'flyover_0', 'edge': 'flyover', 'points': [[0, 8, 0], [0, 8, -60], [0, 8, -120]],
                 'width': 3.2, 'speed': 22.22, 'internal': False},
            ]
            index = {'network_sha256': sha(net), 'version': 2, 'name': 'Test', 'offset': [0, 0],
                     'base_height': 150, 'bbox': [30, 50, 31, 51], 'tile_size': 500,
                     'tiles': {'0_0': [0, 0]}, 'lanes': lanes, 'signals': [], 'tls': [],
                     'spawn': {'position': [0, 0, 0], 'angle': 0}, 'attribution': 'test'}
            write_json(data / 'index.json', index)
            roads, _lanes, _location, stats, _elevation = road_network(index, net)
            self.assertEqual(len(roads), 2)
            self.assertEqual(stats.get('heights_fallback', 0), 0)
            z_by_speed = {r['speedLimit']: {round(n[2], 3) for n in r['nodes']} for r in roads}
            self.assertEqual(z_by_speed[13.89], {0.0})
            self.assertEqual(z_by_speed[22.22], {8.0})

    def test_profile_height_interpolates_along_the_edge(self):
        profile = [(0.0, 0.0, 1.0), (0.0, 10.0, 3.0)]
        self.assertAlmostEqual(profile_height(profile, 0.0, 5.0), 2.0)
        self.assertIsNone(profile_height([], 0.0, 0.0))
        self.assertEqual(edge_profile({'lanes': []}, {}), [])

    def test_signal_cycle_and_shared_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            index, net = fixture(Path(tmp))
            _roads, lanes, _location, _stats, _elevation = road_network(index, net)
            result, _audit = signals(index, lanes)
            self.assertEqual(result['instances'][0]['dir'], (0, 1, 0))
            self.assertEqual(result['sequences'][0]['phases'][0]['totalDuration'], 23)
            ids = [v['id'] for group in result.values() for v in group]
            self.assertEqual(len(ids), len(set(ids)))

    def test_no_green_omits_signal_instead_of_deadlocking_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            index, net = fixture(Path(tmp))
            _roads, lanes, _location, _stats, _elevation = road_network(index, net)
            index['tls'][0]['programs']['0'] = [[10, 'Gr'], [3, 'yy'], [10, 'rG']]
            index['signals'].append({**index['signals'][0], 'index': 1})
            result, audit = signals(index, lanes)
            self.assertEqual(result['instances'], [])
            self.assertEqual(result['sequences'], [])
            self.assertTrue(any(a['reason'].startswith('no common green') for a in audit))


class ExportTests(unittest.TestCase):
    def test_reproducible_self_contained_zip_and_split_building(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            a = export_map('test', root / 'a', source_root=root)
            export_map('test', root / 'b', source_root=root)
            self.assertEqual(sha(root / 'a.zip'), sha(root / 'b.zip'))
            self.assertEqual(a['counts']['buildings'], 1)
            # Buildings ship as per-cell meshes, not one TSStatic each.
            self.assertEqual(a['counts']['building_chunks'], 1)
            level = root / 'a/levels/kyiv_test/art/shapes'
            self.assertEqual(len(list(level.glob('kyiv_buildings_*.dae'))), 1)
            self.assertEqual(list(level.glob('kyiv_building_*.dae')), [])
            self.assertGreaterEqual(a['counts'].get('surface_chunks', 0), 1)
            self.assertIn('road_height_audit', a)
            self.assertGreater(a['road_height_audit']['nodes'], 0)
            self.assertEqual(a['road_height_audit']['over_2m'], 0)
            with zipfile.ZipFile(root / 'a.zip') as z:
                self.assertIsNone(z.testzip())
                pngs = [i for i in z.infolist() if i.filename.endswith('.png')]
                self.assertTrue(pngs)
                self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in pngs))
                raw = z.read('levels/kyiv_test/art/kyiv/invisible.png')
                width, height = struct.unpack('>II', raw[16:24])
                self.assertGreaterEqual(width, 16)
                self.assertGreaterEqual(height, 16)
                allowed = ('levels/kyiv_test/', 'vehicles/common/licenseplates/kyiv_test/')
                self.assertTrue(all(n.startswith(allowed) for n in z.namelist()))
                self.assertIn('vehicles/common/licenseplates/kyiv_test/licensePlate-default.sktemplate.json',
                              z.namelist())
            with self.assertRaises(FileExistsError):
                export_map('test', root / 'a', source_root=root)

    def test_scene_uses_decal_roads_and_no_waypoints(self):
        """22 494 BeamNGWaypoints overflowed the game's Lua stack on load; keep them gone."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            export_map('test', root / 'out', source_root=root)
            level = root / 'out/levels/kyiv_test'
            objects = [json.loads(line) for file in level.rglob('main/**/items.level.json')
                       for line in file.read_text(encoding='utf8').splitlines() if line.strip()]
            classes = {o['class'] for o in objects}
            self.assertIn('DecalRoad', classes)
            self.assertNotIn('BeamNGWaypoint', classes)
            self.assertEqual(json.loads((level / 'map.json').read_text(encoding='utf8'))['segments'], {})
            materials = json.loads((level / 'art/kyiv/main.materials.json').read_text(encoding='utf8'))
            for road in (o for o in objects if o['class'] == 'DecalRoad'):
                self.assertIn(road['material'], materials)

    def test_every_declared_group_gets_an_items_file(self):
        """A group folder without items.level.json makes the loader log a parse error."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            export_map('test', root / 'out', source_root=root)
            level = root / 'out/levels/kyiv_test'
            groups = [o['name'] for file in level.rglob('main/**/items.level.json')
                      for line in file.read_text(encoding='utf8').splitlines() if line.strip()
                      for o in [json.loads(line)] if o['class'] == 'SimGroup']
            self.assertGreater(len(groups), 5)
            for name in groups:
                if name == 'MissionGroup':
                    continue
                self.assertTrue((level / 'main/MissionGroup' / name / 'items.level.json').is_file(), name)

    def test_dressing_references_stock_assets_and_skips_unknown_signs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            report = export_map('test', root / 'out', source_root=root)
            level = root / 'out/levels/kyiv_test'
            self.assertEqual(report['counts']['signs'], 2)
            self.assertEqual(report['counts']['signs_unsupported'], 1)
            self.assertGreater(report['counts']['trees_mapped'], 0)
            self.assertGreater(report['counts']['trees_filled'], 0)
            items = json.loads((level / 'art/forest/managedItemData.json').read_text(encoding='utf8'))
            planted = sorted(f.name.removesuffix('.forest4.json') for f in (level / 'forest').glob('*.forest4.json'))
            self.assertTrue(planted)
            self.assertTrue(set(planted) <= set(items))
            props = [json.loads(line) for line in
                     (level / 'main/MissionGroup/KyivProps/items.level.json').read_text(encoding='utf8').splitlines()
                     if line.strip()]
            stock = [p for p in props if p['shapeName'].startswith('/art/shapes/')]
            self.assertTrue(any('lamp' in p['name'] for p in stock), 'lit road got no street lights')
            self.assertTrue(any('rail' in p['name'] for p in stock), 'bridge got no guardrail')
            self.assertGreater(report['counts']['street_lamps'], 0)
            self.assertGreater(report['counts']['guardrails'], 0)

    def test_signal_lenses_take_distinct_instance_colour_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            export_map('test', root / 'out', source_root=root)
            level = root / 'out/levels/kyiv_test'
            materials = json.loads((level / 'art/kyiv/main.materials.json').read_text(encoding='utf8'))
            palettes = {name: materials['kyiv_lens_' + name]['Stages'][0]['colorPaletteMap']
                        for name in ('red', 'amber', 'green')}
            self.assertEqual(len(set(palettes.values())), 3)
            signals_file = level / 'main/MissionGroup/KyivSignals/items.level.json'
            head = json.loads(signals_file.read_text(encoding='utf8').splitlines()[0])
            self.assertEqual(head['signalInstance'], head['name'])
            self.assertTrue(head['dynamic'])
            self.assertEqual(head['annotation'], 'TRAFFIC_SIGNALS')

    def test_network_version_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _index, net = fixture(root)
            net.write_text('<net/>')
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                export_map('test', root / 'out', source_root=root)
            self.assertFalse((root / 'out').exists())

    def test_invalid_ids_explain_the_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            with self.assertRaisesRegex(ValueError, 'lowercase letters.*--world'):
                export_map('out/generated/test', root / 'a', source_root=root)
            with self.assertRaisesRegex(ValueError, "'My-Level'.*lowercase letters"):
                export_map('test', root / 'b', level_id='My-Level', source_root=root)

    def test_legacy_tool_exports_a_world_folder_passed_as_map(self):
        import export_beamng
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / 'my_world'
            write_json(world / 'config.json', {'id': 'my_world'})
            for flags in (['--map', str(world)], ['--world', str(world)]):
                argv = ['export_beamng.py', *flags, '--output', str(Path(tmp) / 'out'), '--level-id', 'my_level']
                with mock.patch('akadem_maps.adapters.beamng.export.export_world', return_value={'zip': 'x.zip'}) as run, \
                        mock.patch.object(sys, 'argv', argv), mock.patch('builtins.print'):
                    export_beamng.main()
                run.assert_called_once_with(world, Path(tmp) / 'out', overrides=None, level_id='my_level', optimization='balanced')

    def test_capture_delete_add_move_and_source_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = [{'name': 'a', 'class': 'TSStatic', 'position': [0, 0, 0]}, {'name': 'b', 'class': 'TSStatic'}]
            write_json(root / 'kyiv-baseline.json', {'level_id': 'test', 'objects': base})
            edited = [{**base[0], 'position': [1, 2, 3]}, {'name': 'manual', 'class': 'SimGroup'}]
            write_items(root / 'main/items.level.json', edited)
            capture_edits(root, root / 'overrides.json')
            doc = json.loads((root / 'overrides.json').read_text(encoding='utf8'))
            merged, conflicts = apply_overrides(base, doc, None)
            self.assertEqual(sorted(merged, key=lambda o: o['name']), edited)
            self.assertEqual(conflicts, [])
            changed = copy.deepcopy(base)
            changed[0]['position'] = [5, 5, 5]
            merged, conflicts = apply_overrides(changed, doc, None)
            self.assertEqual(conflicts, ['a'])
            self.assertEqual(next(o for o in merged if o['name'] == 'a')['position'], [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
