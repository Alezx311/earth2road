import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from akadem_maps import area_probe, sources
from akadem_maps.cli import Events
from akadem_maps.core import corridor
from akadem_maps.world import validate_config
import generate_map as gm

# About 1.1 × 0.9 km around Kyiv's Shuliavka, an L-shape like a road corridor outline.
L_SHAPE = [[30.440, 50.452], [30.456, 50.452], [30.456, 50.456], [30.446, 50.456],
           [30.446, 50.460], [30.440, 50.460]]


def cfg(points=L_SHAPE, **extra):
    return {'id': 'drawn', 'name': 'Drawn', 'area': {'polygon': points}, **extra}


class DrawnAreaTest(unittest.TestCase):
    def test_valid_outline_closed_or_open(self):
        polygon = corridor.drawn_area({'polygon': L_SHAPE})
        self.assertTrue(polygon.is_valid)
        closed = corridor.drawn_area({'polygon': L_SHAPE + [L_SHAPE[0]]})
        self.assertTrue(polygon.equals(closed))

    def test_rejections(self):
        bowtie = [[30.44, 50.45], [30.46, 50.46], [30.46, 50.45], [30.44, 50.46]]
        cases = {'crosses itself': bowtie,
                 'antimeridian': [[179.9, 0.0], [-179.9, 0.0], [-179.9, 0.1]],
                 '3..': L_SHAPE[:2],
                 'km²': [[30.0, 50.0], [30.2, 50.0], [30.2, 50.2], [30.0, 50.2]],   # ~200 km²
                 'numbers': [[30.44, 50.45], [30.46, 'x'], [30.46, 50.46]]}
        for message, points in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                corridor.drawn_area({'polygon': points})
        tiny = [[30.44, 50.45], [30.4401, 50.45], [30.4401, 50.4501]]
        with self.assertRaisesRegex(ValueError, 'km²'):
            corridor.drawn_area({'polygon': tiny})

    def test_config_takes_bbox_from_the_outline(self):
        checked = validate_config(cfg(bbox=[0, 0, 1, 1]))
        self.assertEqual(checked['bbox'], [30.44, 50.452, 30.456, 50.46])
        self.assertTrue(corridor.shaped(checked))
        self.assertTrue(corridor.area(dict(checked)).equals(corridor.drawn_area(checked['area'])))
        self.assertEqual(corridor.area_digest(checked), corridor.area_digest(validate_config(cfg())))
        with self.assertRaisesRegex(ValueError, 'mutually exclusive'):
            validate_config(cfg(boundary={'geojson': 'x.geojson', 'buffer_m': 0}))

    def test_coverage_is_the_outline_not_the_bbox(self):
        checked = validate_config(cfg())
        geometry = sources.coverage(checked)
        self.assertEqual(geometry['type'], 'Polygon')
        self.assertEqual(len(geometry['coordinates'][0]), len(L_SHAPE) + 1)


class DrawnProbeTest(unittest.TestCase):
    def test_counts_only_inside_the_outline(self):
        tiny = ROOT/'examples/tiny/inputs/raw/tiny.osm'
        bbox = [30.348, 50.448, 30.364, 50.46]
        west_half = corridor.drawn_area({'polygon': [[30.348, 50.448], [30.356, 50.448], [30.356, 50.46], [30.348, 50.46]]})
        whole = area_probe.count_osm(tiny, bbox)
        half = area_probe.count_osm(tiny, bbox, west_half)
        self.assertLessEqual(half['road_nodes'], whole['road_nodes'])
        self.assertLess(half['road_nodes'] + area_probe.count_osm(tiny, bbox, corridor.drawn_area(
            {'polygon': [[30.356, 50.448], [30.364, 50.448], [30.364, 50.46], [30.356, 50.46]]}))['road_nodes'],
            whole['road_nodes'] + 20)

    def test_overpass_gets_a_poly_filter(self):
        seen = {}
        def counter(url, bbox, polygon=None):
            seen['polygon'] = polygon
            return {'roads': 1, 'road_nodes': 1, 'buildings': 1}
        with tempfile.TemporaryDirectory() as tmp:
            result = area_probe.probe(validate_config(cfg(overpass='https://x.invalid')), tmp, counter=counter)
        self.assertEqual(result['basis'], 'overpass_count')
        self.assertIsNotNone(seen['polygon'])
        self.assertAlmostEqual(result['area_km2'], 1.13 * .445 + .42 * .445, delta=.15)
        query = area_probe.count_query([0, 0, 1, 1], polygon=seen['polygon'])
        self.assertIn('poly:"50.452000 30.440000', query)


class GenerateDrawnTest(unittest.TestCase):
    def test_polygon_file_reaches_the_build_config(self):
        seen = {}
        def build(config, world, **_):
            seen.update(config)
        pipeline = {'build': build, 'export': lambda *a, **k: None, 'install': lambda *a, **k: {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'area.geojson'
            path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {},
                            'geometry': {'type': 'Polygon', 'coordinates': [L_SHAPE + [L_SHAPE[0]]]}}]}))
            polygon = gm.read_polygon(path)
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                result = gm.generate(None, None, None, 'Shuliavka L', Events(None), root=Path(tmp),
                                     pipeline=pipeline, polygon=polygon)
            finally:
                sys.stderr = stderr
        self.assertEqual(seen['area']['polygon'], polygon)
        self.assertEqual(result['bbox'], [30.44, 50.452, 30.456, 50.46])
        lon, lat = seen['center']
        self.assertTrue(corridor.drawn_area(seen['area']).contains(corridor.Polygon([(lon, lat), (lon + 1e-6, lat),
                                                                                     (lon, lat + 1e-6)])))
        self.assertIn('drawn area', seen['note'])
        validate_config(dict(seen))


if __name__ == '__main__':
    unittest.main()
