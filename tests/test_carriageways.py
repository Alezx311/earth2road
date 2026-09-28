"""Two carriageways of one divided road share a height profile.

Beresteiskyi near Dachna (ring_beresteiskyi_02): the OSM one-way ways sampled the coarse DEM
separately, leaving the directions up to 0.8 m apart with a pit and gaps in the median."""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import prepare


def osm(ways, nodes):
    root = ET.Element('osm')
    for nid, (lon, lat) in nodes.items():
        ET.SubElement(root, 'node', id=nid, lon=str(lon), lat=str(lat))
    for wid, (refs, tags) in ways.items():
        w = ET.SubElement(root, 'way', id=wid)
        for r in refs:
            ET.SubElement(w, 'nd', ref=r)
        for k, v in tags.items():
            ET.SubElement(w, 'tag', k=k, v=v)
    return root


def divided(east_tags=None, west_tags=None, gap_deg=0.00018):
    """Two antiparallel one-way ways ~20 m apart, 5 nodes each, 280 m long."""
    nodes = {}
    for i in range(5):
        nodes[f'e{i}'] = (30.0+i*0.001, 50.0)
        nodes[f'w{i}'] = (30.004-i*0.001, 50.0+gap_deg)
    base = {'highway': 'trunk', 'oneway': 'yes', 'name': 'Avenue'}
    ways = {'1': ([f'e{i}' for i in range(5)], {**base, **(east_tags or {})}),
            '2': ([f'w{i}' for i in range(5)], {**base, **(west_tags or {})})}
    return nodes, ways


def heights(nodes, ways, sample):
    root = osm(ways, nodes)
    tags = lambda e: {t.attrib['k']: t.attrib['v'] for t in e.findall('tag')}
    return prepare.road_node_heights(root, nodes, tags, sample)


class CarriagewayPairTest(unittest.TestCase):
    def test_opposite_carriageways_share_height(self):
        nodes, ways = divided()
        # DEM tilted across the road: 0.8 m between the two lines, as near Dachna.
        h, _, report = heights(nodes, ways, lambda lon, lat: 0.0 if lat < 50.0001 else 0.8)
        self.assertEqual(report['paired_nodes'], 10)
        for i in range(5):
            self.assertLess(abs(h[f'e{i}']-h[f'w{4-i}']), 0.05)

    def test_same_direction_or_other_name_is_not_paired(self):
        nodes, ways = divided(west_tags={'name': 'Side street'})
        _, _, report = heights(nodes, ways, lambda lon, lat: 0.0)
        self.assertEqual(report['paired_nodes'], 0)
        nodes, ways = divided(west_tags={'oneway': '-1'})  # drawn backwards = same direction
        _, _, report = heights(nodes, ways, lambda lon, lat: 0.0)
        self.assertEqual(report['paired_nodes'], 0)

    def test_far_parallel_road_is_not_paired(self):
        nodes, ways = divided(gap_deg=0.001)  # ~110 m apart
        _, _, report = heights(nodes, ways, lambda lon, lat: 0.0)
        self.assertEqual(report['paired_nodes'], 0)

    def test_tunnel_is_not_lifted_by_its_partner(self):
        nodes, ways = divided(east_tags={'tunnel': 'yes', 'layer': '-1'})
        h, _, _ = heights(nodes, ways, lambda lon, lat: 0.0)
        self.assertLess(h['e2'], -3.0)


def diverging(slip_tags=None, offset_deg=0.00003):
    """A 4-lane one-way trunk and a one-lane road leaving it at a shallow angle.

    The slip shares the first trunk node, runs ~3 m off the trunk axis (inside its 13 m
    footprint) for ~140 m, then turns away, as Chornobylska leaves Beresteiskyi."""
    nodes = {f'm{i}': (30.0+i*0.001, 50.0) for i in range(4)}
    nodes.update({'s1': (30.0005, 50.0+offset_deg), 's2': (30.002, 50.0+offset_deg),
                  's3': (30.0024, 50.0004), 's4': (30.0026, 50.001)})
    ways = {'1': ([f'm{i}' for i in range(4)], {'highway': 'trunk', 'oneway': 'yes', 'lanes': '4', 'name': 'Avenue'}),
            '2': (['m0', 's1', 's2', 's3', 's4'], {'highway': 'secondary', 'oneway': 'yes', 'name': 'Side', **(slip_tags or {})})}
    return nodes, ways


# DEM 0.8 m higher just north of the trunk axis: the slip samples the higher side.
NORTH_UP = staticmethod(lambda lon, lat: 0.8 if lat > 50.00002 else 0.0)


class OverlappingCarriagewayTest(unittest.TestCase):
    def test_slip_road_inside_the_main_footprint_follows_it(self):
        nodes, ways = diverging()
        h, _, report = heights(nodes, ways, OverlappingCarriagewayTest.dem)
        self.assertGreaterEqual(report['overlap_nodes'], 2)
        def trunk(lon):
            i = min(2, int((lon-30.0)/0.001))
            u = (lon-30.0)/0.001-i
            return h[f'm{i}']+(h[f'm{i+1}']-h[f'm{i}'])*u
        for n in ('s1', 's2'):
            self.assertLess(abs(h[n]-trunk(nodes[n][0])), 0.05)
        # Once apart it keeps its own terrain: the far node stays on the higher DEM.
        self.assertGreater(h['s4'], h['m3']+0.4)

    def test_adjacent_road_outside_the_footprint_is_not_coupled(self):
        nodes, ways = diverging(offset_deg=0.00009)  # ~10 m off the axis: beside, not on it
        _, _, report = heights(nodes, ways, OverlappingCarriagewayTest.dem)
        self.assertEqual(report['overlap_nodes'], 0)

    def test_bridge_is_never_flattened_onto_the_road_below(self):
        nodes, ways = diverging(slip_tags={'bridge': 'yes', 'layer': '1'})
        _, _, report = heights(nodes, ways, OverlappingCarriagewayTest.dem)
        self.assertEqual(report['overlap_nodes'], 0)

    def test_main_road_is_not_moved_by_the_slip(self):
        from unittest.mock import patch
        nodes, ways = diverging()
        coupled, _, _ = heights(nodes, ways, OverlappingCarriagewayTest.dem)
        with patch.object(prepare, 'overlap_targets', return_value={}):
            alone, _, _ = heights(nodes, ways, OverlappingCarriagewayTest.dem)
        self.assertGreater(abs(coupled['s1']-alone['s1']), 0.2)  # the rule did act
        for i in range(4):
            self.assertAlmostEqual(coupled[f'm{i}'], alone[f'm{i}'], delta=0.05)

OverlappingCarriagewayTest.dem = NORTH_UP


if __name__ == '__main__':
    unittest.main()
