import json
import math
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, box

from akadem_maps.core import yards

ROOT = Path(__file__).resolve().parents[1]


def osm(*items):
    """Ways from (id, coords, tags); coordinates are metres (to_xy is the identity)."""
    root, nodes, nid = ET.Element('osm'), {}, 1
    for wid, coords, tags, *node_tags in items:
        refs = []
        for k, c in enumerate(coords):
            if refs and k == len(coords)-1 and c == coords[0]:
                refs.append(refs[0])
                continue
            nodes[str(nid)] = c
            node = ET.SubElement(root, 'node', id=str(nid))
            for key, v in (node_tags[0].get(k, {}) if node_tags else {}).items():
                ET.SubElement(node, 'tag', k=key, v=v)
            refs.append(str(nid))
            nid += 1
        way = ET.SubElement(root, 'way', id=str(wid))
        for r in refs:
            ET.SubElement(way, 'nd', ref=r)
        for k, v in tags.items():
            ET.SubElement(way, 'tag', k=k, v=v)
    return root, nodes


def ring(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def xy(item):
    return item['position'][0], -item['position'][2]


def run(root, nodes, road_cut=Polygon(), parking=(), seed=7):
    return yards.dress(root, nodes, lambda x, y: (x, y), lambda x, y: [x, 0.0, -y], road_cut,
                       box(-500, -500, 500, 500), list(parking), seed)


class YardTests(unittest.TestCase):
    def test_models_match_the_vehicle_catalogue(self):
        catalogue = json.loads((ROOT/'config/vehicles.json').read_text(encoding='utf-8'))['models']
        for name, (size, _) in yards.PARKED_MODELS.items():
            self.assertEqual(list(size), catalogue[name]['size'], name)
            self.assertIn(catalogue[name]['class'], ('passenger', 'delivery'))

    def test_parking_lot_gets_rows_of_cars_off_the_aisle(self):
        lot = Polygon(ring(0, 0, 40, 16))
        aisle = box(0, 5.5, 40, 10.5)          # mapped parking aisle = carriageway
        root, nodes = osm()
        props, counts = run(root, nodes, road_cut=aisle, parking=[lot])
        cars = [p for p in props if p['kind'] == 'parked_car']
        self.assertGreater(len(cars), 8)
        self.assertEqual(counts['parked_cars_lots'], len(cars))
        boxes = [yards._car_box(*xy(c), (math.sin(c['yaw']), -math.cos(c['yaw'])), c['size']) for c in cars]
        for c, b in zip(cars, boxes):
            self.assertTrue(lot.covers(b), c)
            self.assertFalse(aisle.intersects(b), c)
            self.assertEqual((c['provenance'], c['rule']), ('synthetic:yard', 'parking_stall'))
        for i, a in enumerate(boxes):
            self.assertFalse(any(a.intersects(b) for b in boxes[i+1:]))

    def test_kerb_cars_only_on_yard_roads_near_apartment_blocks(self):
        road = LineString([(0, 0), (120, 0)])
        far = LineString([(0, 300), (120, 300)])
        root, nodes = osm((1, list(road.coords), {'highway': 'service'}),
                          (2, list(far.coords), {'highway': 'service'}),
                          (3, ring(20, 12, 100, 24), {'building': 'apartments'}))
        cut = road.buffer(2.5).union(far.buffer(2.5))
        props, counts = run(root, nodes, road_cut=cut)
        cars = [p for p in props if p['kind'] == 'parked_car']
        self.assertTrue(cars)
        self.assertEqual(counts['parked_cars_kerb'], len(cars))
        for c in cars:
            self.assertEqual(c['source'], 'way/1')
            fp = yards._car_box(*xy(c), (math.sin(c['yaw']), -math.cos(c['yaw'])), c['size'])
            self.assertFalse(cut.buffer(0.2).intersects(fp))
            self.assertLess(Point(xy(c)).distance(road), 5.0)

    def test_entrance_bench_stands_outside_with_its_back_to_the_wall(self):
        # Door in the middle of the south wall (y = 0) of a block spanning y 0..12.
        coords = [(0, 0), (15, 0), (30, 0), (30, 12), (0, 12), (0, 0)]
        root, nodes = osm((5, coords, {'building': 'apartments'}, {1: {'entrance': 'staircase'}}))
        props, counts = run(root, nodes)
        bench, = [p for p in props if p['kind'] == 'bench']
        x, y = xy(bench)
        self.assertLess(y, 0)                                   # outside, south of the wall
        self.assertLess(abs(x-15), 3)
        back = (math.sin(bench['yaw']), -math.cos(bench['yaw']))  # local +Z in network XY
        self.assertGreater(back[1], 0.99)                      # backrest toward the wall (north)
        self.assertEqual((counts['entrance_benches'], bench['source']), (1, 'node/2'))
        shrubs = [p for p in props if p['kind'] == 'shrub']
        self.assertTrue(shrubs)
        self.assertTrue(all(Point(xy(s)).distance(Point(15, 0)) > 4 for s in shrubs))
        self.assertFalse(any(Polygon(coords).buffer(0.5).contains(Point(xy(s))) for s in shrubs))

    def test_playground_equipment_stays_inside_and_is_deterministic(self):
        pg = ring(0, 0, 30, 20)
        root, nodes = osm((9, pg, {'leisure': 'playground'}))
        props, _ = run(root, nodes)
        kit = [p for p in props if p['kind'] in yards.PLAYGROUND_KIT]
        self.assertGreaterEqual(len(kit), 2)
        self.assertTrue(all(Polygon(pg).contains(Point(xy(p))) for p in kit))
        self.assertEqual(props, run(*osm((9, pg, {'leisure': 'playground'})))[0])


if __name__ == '__main__':
    unittest.main()
