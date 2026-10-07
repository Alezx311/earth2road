"""Playtest 2026-10-06: multipolygon buildings, S3DB parts, observed colours,
roof solids, kiosks and the no-building-on-the-carriageway invariant."""
from collections import Counter
import unittest
import xml.etree.ElementTree as ET

from shapely.geometry import Polygon, box

from akadem_maps.core import osm_buildings as ob


def item(points, height=10., **extra):
    return {'id': 'b', 'points': [[x, 0., z] for x, z in points], 'height': height, **extra}


def square(x0, z0, size):
    return [(x0, z0), (x0+size, z0), (x0+size, z0+size), (x0, z0+size)]


class RelationTests(unittest.TestCase):
    def test_multipolygon_with_courtyard_becomes_hole_free_pieces(self):
        osm = ET.fromstring('''<osm>
          <node id="1" lon="0" lat="0"/><node id="2" lon="10" lat="0"/><node id="3" lon="10" lat="10"/><node id="4" lon="0" lat="10"/>
          <node id="5" lon="4" lat="4"/><node id="6" lon="6" lat="4"/><node id="7" lon="6" lat="6"/><node id="8" lon="4" lat="6"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
          <way id="11"><nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/></way>
          <relation id="99"><member type="way" ref="10" role="outer"/><member type="way" ref="11" role="inner"/>
            <tag k="type" v="multipolygon"/><tag k="building" v="school"/></relation>
        </osm>''')
        nodes = {n.get('id'): (float(n.get('lon')), float(n.get('lat'))) for n in osm.iter('node')}
        (rid, tags, shape), = ob.relation_footprints(osm, nodes)
        self.assertEqual((rid, tags['building']), ('r99', 'school'))
        pieces = [p for poly in ob.polygons(shape) for p in ob.hole_free(poly)]
        self.assertTrue(all(not p.interiors for p in pieces))
        self.assertAlmostEqual(sum(p.area for p in pieces), 96.0, places=3)


class PartTests(unittest.TestCase):
    def test_outline_covered_by_parts_is_hidden_and_parts_know_it(self):
        outline = item(square(0, 0, 10), id='o', _tags={'building': 'church', 'building:colour': '#deb887'}, _part=False)
        parts = [item(square(0, 0, 10), id='p1', _tags={'building:part': 'yes'}, _part=True),
                 item(square(3, 3, 4), id='p2', _tags={'building:part': 'yes', 'roof:shape': 'onion'}, _part=True)]
        footprints = {id(b): Polygon([(p[0], p[2]) for p in b['points']]) for b in [outline, *parts]}
        counts = Counter()
        kept = ob.apply_parts([outline, *parts], footprints, counts)
        self.assertEqual([b['id'] for b in kept], ['p1', 'p2'])
        self.assertIs(parts[1]['_parent'], outline)
        self.assertEqual(counts['s3db_outlines_hidden'], 1)
        b = parts[1]
        ob.observe(b, b['_tags'], outline['_tags'])
        self.assertEqual((b['local_style']['architecture'], b['local_style']['color']), ('historic', '#deb887'))

    def test_partly_mapped_outline_stays(self):
        outline = item(square(0, 0, 10), id='o', _tags={'building': 'yes'}, _part=False)
        part = item(square(0, 0, 3), id='p', _tags={'building:part': 'yes'}, _part=True)
        footprints = {id(b): Polygon([(p[0], p[2]) for p in b['points']]) for b in (outline, part)}
        self.assertEqual(len(ob.apply_parts([outline, part], footprints, Counter())), 2)


class RoofTests(unittest.TestCase):
    def check_solid(self, b, height):
        ys = [v[1] for t in b['roof_triangles'] for v in t]
        self.assertAlmostEqual(max(ys), height, places=2)
        self.assertAlmostEqual(min(ys), b['floor_height'] + b['wall_height'], places=2)
        fp = Polygon([(p[0], p[2]) for p in b['points']]).buffer(1e-3)
        for t in b['roof_triangles']:
            self.assertTrue(fp.contains(Polygon([(v[0], v[2]) for v in t]).buffer(-1e-4)) or
                            Polygon([(v[0], v[2]) for v in t]).area < 1e-6)

    def test_each_shape_keeps_total_height_and_footprint(self):
        for shape in ob.SHAPED_ROOFS:
            b = item(square(0, 0, 8), height=12.)
            self.assertIsNone(ob.shaped_roof(b, shape), shape)
            self.check_solid(b, 12.)

    def test_hipped_rectangle_has_ridge_and_tagged_roof_height(self):
        b = item([(0, 0), (12, 0), (12, 6), (0, 6)], height=9.)
        self.assertIsNone(ob.shaped_roof(b, 'hipped', roof_height=2.))
        self.assertAlmostEqual(b['wall_height'], 7.)
        apex = {(v[0], v[2]) for t in b['roof_triangles'] for v in t if abs(v[1]-9.) < 1e-6}
        self.assertEqual(apex, {(3.0, 3.0), (9.0, 3.0)})

    def test_raised_part_keeps_base_and_non_star_footprint_falls_back(self):
        b = item(square(0, 0, 4), height=22., base=18.)
        self.assertIsNone(ob.shaped_roof(b, 'onion', roof_height=2.))
        self.assertAlmostEqual(b['wall_height'], 20.)
        u = item([(0, 0), (9, 0), (9, 9), (6, 9), (6, 3), (3, 3), (3, 9), (0, 9)])
        self.assertIn('star-shaped', ob.shaped_roof(u, 'dome'))


class KioskAndCarriagewayTests(unittest.TestCase):
    def test_kiosks_and_booths_get_one_storey(self):
        self.assertEqual(ob.assumed_levels({'building': 'yes', 'shop': 'bakery'}, 33, 2), 1)
        self.assertEqual(ob.assumed_levels({'building': 'kiosk'}, 80, 2), 1)
        self.assertEqual(ob.assumed_levels({'building': 'yes'}, 20, 2), 1)
        self.assertEqual(ob.assumed_levels({'building': 'yes'}, 120, 2), 2)

    def test_building_on_carriageway_clipped_or_dropped_and_reported(self):
        road = box(0, 0, 100, 7)
        edge = item(square(0, 5, 10), id='edge')      # 2 m of 10 on the road -> clipped
        mid = item(square(40, 0, 5), id='mid')        # wholly on the road -> dropped
        free = item(square(0, 20, 5), id='free')
        raised = item(square(60, 0, 5), id='raised', base=4.5)
        footprints = {id(b): Polygon([(p[0], p[2]) for p in b['points']]) for b in (edge, mid, free, raised)}
        audit, counts = [], Counter()
        kept = ob.clear_carriageway([edge, mid, free, raised], footprints, road,
                                    lambda x, y: [x, 0., y], lambda x, y: (x, y), counts, audit)
        self.assertEqual(sorted(b['id'] for b in kept), ['edge', 'free', 'raised'])
        clipped = next(b for b in kept if b['id'] == 'edge')
        self.assertGreaterEqual(min(p[2] for p in clipped['points']), 7 - 1e-6)
        self.assertEqual({r['id']: r['action'] for r in audit}, {'edge': 'clipped', 'mid': 'dropped'})


class RobustTests(unittest.TestCase):
    def test_failing_precision_snap_falls_through_to_next_repair(self):
        from unittest import mock
        import shapely
        from shapely.errors import GEOSException
        calls = []
        def op(g):
            calls.append(g)
            if len(calls) < 3:
                raise GEOSException('TopologyException')
            return g.area
        def broken_snap(g, grid):
            raise GEOSException('IllegalArgumentException: Points of LinearRing do not form a closed linestring')
        with mock.patch.object(shapely, 'set_precision', broken_snap):
            self.assertEqual(ob.robust(op, box(0, 0, 2, 2)), 4)
        self.assertEqual(len(calls), 3)  # original, make_valid, then buffer(0) after both snaps failed

    def test_unrecoverable_inputs_are_dumped_for_repro(self):
        import os, tempfile
        from pathlib import Path
        from unittest import mock
        from shapely import wkb
        from shapely.errors import GEOSException
        def op(g):
            raise GEOSException('always')
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'AKADEM_MAPS_GEOS_DUMP': tmp}):
            with self.assertRaises(GEOSException):
                ob.robust(op, box(0, 0, 1, 1))
            dumped = list(Path(tmp).glob('robust-*/0.wkb'))
            self.assertEqual(len(dumped), 1)
            self.assertTrue(wkb.loads(dumped[0].read_bytes()).equals(box(0, 0, 1, 1)))


if __name__ == '__main__':
    unittest.main()
