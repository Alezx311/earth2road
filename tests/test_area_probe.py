import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from akadem_maps import area_probe
import generate_map as gm

TINY = ROOT/'examples/tiny/inputs/raw/tiny.osm'
TINY_BBOX = [30.348, 50.448, 30.364, 50.46]


def config(bbox=TINY_BBOX):
    return {'id': 'probe', 'name': 'probe', 'bbox': bbox, 'terrain_zoom': 12,
            'overpass': 'https://first.invalid/api', 'overpass_mirrors': ['https://second.invalid/api']}


class CountTest(unittest.TestCase):
    def test_counts_roads_nodes_and_buildings_inside_the_bbox(self):
        counts = area_probe.count_osm(TINY, TINY_BBOX)
        self.assertGreater(counts['roads'], 0)
        self.assertGreaterEqual(counts['road_nodes'], counts['roads'])
        # A bbox away from the fixture contains nothing.
        self.assertGreater(counts['road_km'], 0)
        self.assertEqual(area_probe.count_osm(TINY, [0, 0, .01, .01]),
                         {'roads': 0, 'road_km': 0, 'road_nodes': 0, 'buildings': 0})

    def test_overpass_query_and_response(self):
        query = area_probe.count_query([30.1, 50.2, 30.3, 50.4])
        self.assertIn('(50.2,30.1,50.4,30.3)', query)          # south, west, north, east
        self.assertIn('_link$', query)
        self.assertEqual(query.count('out count'), 2)
        self.assertIn('make stat roads=count(ways),road_m=sum(length())', query)
        self.assertEqual(area_probe.count_query([30.1, 50.2, 30.3, 50.4], length=False).count('out count'), 3)
        stat = {'elements': [{'type': 'stat', 'tags': {'roads': '12', 'road_m': '4321.5'}},
                             {'type': 'count', 'tags': {'nodes': '340', 'ways': '0'}},
                             {'type': 'count', 'tags': {'ways': '55', 'nodes': '0'}}]}
        self.assertEqual(area_probe.parse_counts(stat),
                         {'roads': 12, 'road_km': 4.322, 'road_nodes': 340, 'buildings': 55})
        plain = {'elements': [{'type': 'count', 'tags': {'ways': '12', 'nodes': '0'}},
                              {'type': 'count', 'tags': {'nodes': '340', 'ways': '0'}},
                              {'type': 'count', 'tags': {'ways': '55', 'nodes': '0'}}]}
        self.assertEqual(area_probe.parse_counts(plain), {'roads': 12, 'road_nodes': 340, 'buildings': 55})
        with self.assertRaises(ValueError):
            area_probe.parse_counts({'elements': []})


class CountOverpassTest(unittest.TestCase):
    def test_server_without_length_statistic_gets_plain_counts(self):
        from unittest import mock
        sent = []
        plain = {'elements': [{'type': 'count', 'tags': {'ways': '2', 'nodes': '0'}},
                              {'type': 'count', 'tags': {'nodes': '9', 'ways': '0'}},
                              {'type': 'count', 'tags': {'ways': '1', 'nodes': '0'}}]}
        def urlopen(request, timeout):
            sent.append(request.data.decode())
            if 'make%20stat' in sent[-1]:
                raise urllib.error.HTTPError(request.full_url, 400, 'Bad Request', {}, io.BytesIO())
            return io.BytesIO(json.dumps(plain).encode())
        with mock.patch.object(area_probe.urllib.request, 'urlopen', urlopen):
            self.assertEqual(area_probe.count_overpass('https://x.invalid', TINY_BBOX),
                             {'roads': 2, 'road_nodes': 9, 'buildings': 1})
        self.assertEqual(len(sent), 2)
        def busy(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 504, 'Gateway Timeout', {}, io.BytesIO())
        with mock.patch.object(area_probe.urllib.request, 'urlopen', busy), \
                self.assertRaises(urllib.error.HTTPError):
            area_probe.count_overpass('https://x.invalid', TINY_BBOX)


class ProbeTest(unittest.TestCase):
    def test_offline_without_data_is_area_only_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = area_probe.probe(config(), tmp, offline=True)
        self.assertEqual(result['basis'], 'area_only')
        self.assertIn('offline', result['note'])
        self.assertAlmostEqual(result['area_km2'], 1.13*1.33, delta=.15)
        self.assertGreater(result['dem_tiles'], 0)
        self.assertEqual(result['dem_missing'], result['dem_tiles'])
        self.assertFalse(result['osm_ready'])

    def test_overpass_counts_are_cached_per_area(self):
        calls = []
        def counter(url, bbox):
            calls.append(url)
            return {'roads': 3, 'road_nodes': 30, 'buildings': 4}
        with tempfile.TemporaryDirectory() as tmp:
            first = area_probe.probe(config(), tmp, counter=counter)
            second = area_probe.probe(config(), tmp, counter=counter)
        self.assertEqual(calls, ['https://first.invalid/api'])
        self.assertEqual(first['basis'], 'overpass_count')
        self.assertEqual((second['roads'], second['road_nodes'], second['buildings'], second['basis']),
                         (3, 30, 4, 'overpass_count'))

    def test_rate_limit_is_not_retried_on_mirrors(self):
        calls = []
        def counter(url, bbox):
            calls.append(url)
            raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, io.BytesIO())
        with tempfile.TemporaryDirectory() as tmp:
            result = area_probe.probe(config(), tmp, counter=counter)
        self.assertEqual(calls, ['https://first.invalid/api'])
        self.assertEqual(result['basis'], 'area_only')
        self.assertIn('429', result['note'])

    def test_unreachable_server_tries_the_mirror(self):
        calls = []
        def counter(url, bbox):
            calls.append(url)
            if 'first' in url:
                raise OSError('unreachable')
            return {'roads': 1, 'road_nodes': 2, 'buildings': 0}
        with tempfile.TemporaryDirectory() as tmp:
            result = area_probe.probe(config(), tmp, counter=counter)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['basis'], 'overpass_count')


class EstimateActionTest(unittest.TestCase):
    def test_estimate_action_combines_readiness_counts_and_seconds(self):
        def counter(url, bbox):
            return {'roads': 200, 'road_nodes': 600, 'buildings': 250}
        with tempfile.TemporaryDirectory() as tmp:
            args = gm.argparse.Namespace(id=None, name='Somewhere', lat=50.45, lon=30.52, size_km=0.5)
            result = gm.estimate_area(gm.area_config(args), tmp, 'auto', 'v2',
                                      history_path=Path(tmp)/'none.jsonl', counter=counter)
        self.assertEqual(result['action'], 'estimate')
        self.assertFalse(result['osm_ready'])
        self.assertEqual(result['features']['basis'], 'overpass_count')
        low, high = result['estimate']['seconds']
        self.assertLess(low, result['estimate']['expected_s'])
        self.assertLess(result['estimate']['expected_s'], high)
        self.assertEqual(set(result['estimate']['stages']), {'download', 'roads', 'buildings', 'scenery', 'export'})
        json.dumps(result)   # goes to the events file


if __name__ == '__main__':
    unittest.main()
