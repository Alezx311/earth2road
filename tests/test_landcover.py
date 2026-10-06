"""Playtest 2026-10-06 notes 5 and 9: relation landcover in every mode, sports grounds, one cover per point."""
import unittest
import xml.etree.ElementTree as ET

from shapely.geometry import box

from akadem_maps.core import landcover


class LandcoverTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(landcover.kind({'natural': 'water', 'water': 'lake'}), 'water')
        self.assertEqual(landcover.kind({'landuse': 'forest'}), 'wood')
        self.assertEqual(landcover.kind({'leisure': 'pitch', 'sport': 'soccer'}), 'pitch')
        self.assertEqual(landcover.kind({'leisure': 'track'}), 'track')
        self.assertIsNone(landcover.kind({'landuse': 'farmland'}))
        self.assertEqual(landcover.kind({'landuse': 'farmland'}, is_rural=True), 'farmland')

    def test_urban_lake_and_forest_relations_with_holes(self):
        osm = ET.fromstring('''<osm>
          <node id="1" lon="0" lat="0"/><node id="2" lon="10" lat="0"/><node id="3" lon="10" lat="10"/><node id="4" lon="0" lat="10"/>
          <node id="5" lon="4" lat="4"/><node id="6" lon="6" lat="4"/><node id="7" lon="6" lat="6"/><node id="8" lon="4" lat="6"/>
          <way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/></way><way id="11"><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
          <way id="12"><nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/></way>
          <relation id="7"><member type="way" ref="10" role="outer"/><member type="way" ref="11" role="outer"/>
            <member type="way" ref="12" role="inner"/><tag k="type" v="multipolygon"/><tag k="natural" v="water"/></relation>
          <relation id="8"><member type="way" ref="12" role="outer"/><tag k="type" v="multipolygon"/><tag k="landuse" v="forest"/></relation>
        </osm>''')
        nodes = {n.get('id'): (float(n.get('lon')), float(n.get('lat'))) for n in osm.iter('node')}
        areas = landcover.relation_covers(osm, nodes, lambda x, y: (x, y), box(0, 0, 10, 10))
        self.assertEqual({a['kind']: round(a['poly'].area, 6) for a in areas}, {'water': 96.0, 'wood': 4.0})

    def test_overlaps_resolved_by_priority(self):
        park = {'id': 'p', 'kind': 'green', 'poly': box(0, 0, 10, 10)}
        pond = {'id': 'w', 'kind': 'water', 'poly': box(2, 2, 4, 4)}
        track = {'id': 't', 'kind': 'track', 'poly': box(5, 5, 9, 9)}
        pitch = {'id': 'f', 'kind': 'pitch', 'poly': box(6, 6, 8, 8)}
        out = {a['id']: a['poly'].area for a in landcover.resolve([park, track, pond, pitch])}
        self.assertEqual(out, {'w': 4.0, 'f': 4.0, 't': 12.0, 'p': 80.0})

    def test_water_is_flat_at_a_low_dem_percentile_and_shore_avoids_roads(self):
        lake = box(0, 0, 100, 100)
        level = landcover.water_level(lake, lambda x, y: x/10)     # DEM rises 0..10 across the lake
        self.assertLess(level, 1.5)
        lines = landcover.shore(lake, level, box(40, -5, 60, 5))    # a road crosses the south shore
        self.assertTrue(all(p[2] == level for line in lines for p in line))
        self.assertFalse(any(40 < p[0] < 60 and p[1] < 1 for line in lines for p in line))


if __name__ == '__main__':
    unittest.main()
