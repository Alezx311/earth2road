"""Ground under a bridge deck must not show through it.

Kyiv ring 04: the coarse DEM stood up to 1.83 m above low bridge decks near Lavina
(OSM ways 36406865/62192819); the uncut ground mesh covered the asphalt."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import scene
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union


def deck(z, width=7.0):
    return {'points': [(0.0, 0.0, z), (20.0, 0.0, z), (40.0, 0.0, z)], 'width': width, 'bridge': True}


class LowDeckTest(unittest.TestCase):
    def test_low_deck_is_cut_and_ground_held_below(self):
        dem = lambda x, y: 5.0
        strip = deck(4.0)
        cut, segments = scene.low_decks([strip], [], dem)
        self.assertTrue(cut.contains(Point(20, 0)))
        ground = scene.DeckClamp(dem, segments)
        footprint = scene.strip_polygon(strip['points'], strip['width'])
        tris = scene.draped_triangles(box(-30, -30, 70, 30).difference(cut))
        self.assertTrue(tris)
        for tri in tris:
            self.assertFalse(Polygon(tri).buffer(-1e-6).intersects(footprint))
            for x, y in tri:
                if footprint.distance(Point(x, y)) < 1.0:
                    self.assertLessEqual(ground(x, y), 4.0)
        self.assertEqual(ground(20, 20), 5.0)

    def test_real_overpass_keeps_its_ground(self):
        dem = lambda x, y: 5.0
        cut, segments = scene.low_decks([deck(12.0)], [], dem)
        self.assertTrue(cut.is_empty)
        self.assertEqual(segments, [])

    def test_low_bridge_junction_is_cut(self):
        dem = lambda x, y: 5.0
        node = box(0, 0, 10, 10)
        cut, segments = scene.low_decks([], [(node, lambda x, y: 4.5)], dem)
        self.assertTrue(cut.contains(Point(5, 5)))
        self.assertLessEqual(scene.DeckClamp(dem, segments)(5, 10.2), 4.5)


class DeckMedianTest(unittest.TestCase):
    """Beresteiskyi overpass at the ring: two one-way bridge ways 3 m apart left a slot
    3-4 m deep between the decks (ring_beresteiskyi_02)."""
    def pair(self, gap, z2=7.0):
        a = {'points': [(0.0, 0.0, 7.0), (60.0, 0.0, 7.0)], 'width': 7.0, 'bridge': True}
        b = {'points': [(60.0, 7.0+gap, z2), (0.0, 7.0+gap, z2)], 'width': 7.0, 'bridge': True}
        return [a, b]

    def test_narrow_slot_between_twin_decks_is_closed_at_deck_level(self):
        tris = scene.deck_medians(self.pair(3.0))
        cover = unary_union([Polygon([p[:2] for p in t]) for t in tris])
        self.assertTrue(cover.contains(Point(30, 5.0)))
        self.assertTrue(all(abs(p[2]-7.0) < 1e-6 for t in tris for p in t))

    def test_wide_or_split_level_gap_stays_open(self):
        self.assertEqual(scene.deck_medians(self.pair(9.0)), [])
        self.assertEqual(scene.deck_medians(self.pair(3.0, z2=9.0)), [])


if __name__ == '__main__':
    unittest.main()
