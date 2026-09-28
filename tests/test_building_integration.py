"""INTEGRATE package tests: DATA candidates -> render-schema buildings.

Fixture-only (no network, no SUMO net, no OSM parse). The coordinate callbacks
mirror the real prepare.py conventions exactly: ``to_xy`` has the signature of
``sumolib net.convertLonLat2XY(lon, lat) -> (x, y)`` in metres and ``point``
has the signature of ``prepare.point(x, y, z=None) -> [x, z, -y]`` local
render point. ``exclude`` must enforce OSM > Overture > Microsoft internally,
independent of the caller's input order.
"""
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import building_enrichment as be
import building_sources as bs

CENTER_LON, CENTER_LAT = 30.40, 50.45
M_LON = 71000.0     # metres per degree lon at Kyiv latitude (prepare.py uses 71000)
M_LAT = 111200.0    # metres per degree lat


def to_xy(lon, lat):
    """Same convention as net.convertLonLat2XY(lon, lat) -> (x, y) metres."""
    return ((lon - CENTER_LON) * M_LON, (lat - CENTER_LAT) * M_LAT)


def point(x, y, z=None):
    """Same convention as prepare.point(x, y, z=None) -> local [x, z, -y]."""
    return [round(x, 3), round(0.0 if z is None else z, 3), round(-y, 3)]


def feat(sid, source, geom, height=None):
    """A building_sources normal-form feature (exact property set)."""
    prov = {'overture': 'overture_assumed', 'microsoft': 'ml_estimated'}[source]
    return {
        'type': 'Feature',
        'geometry': geom,
        'properties': {
            'source': source, 'source_id': sid, 'release': 'test-release',
            'license': 'ODbL-1.0' if source == 'overture' else 'CDLA-Permissive-2.0',
            'height': height,
            'height_provenance': prov if height is not None else None,
        },
    }


def box_geom(w, s, e, n):
    return {'type': 'Polygon',
            'coordinates': [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def rec(sid, source, poly):
    """Render-format record for exclusion tests (id + priority fields only)."""
    return {'id': sid, 'source': source, 'source_id': sid, 'points': [], 'height': 10.0}


def grid_candidates(side, start=100.0, step=60.0, size=40.0):
    """``side*side`` pairwise-disjoint boxes (40 m on a 60 m grid) in stable
    (i, j) order, with matching render records."""
    recs, polys = [], []
    for i in range(side):
        for j in range(side):
            w, s = start + i * step, start + j * step
            poly = box(w, s, w + size, s + size)
            polys.append(poly)
            recs.append(rec(f'g-{i}-{j}', 'overture', poly))
    return recs, polys


def shuffle_pairs(recs, polys, seed):
    """Same candidates, differently shuffled input order (records stay paired
    with their footprints) so exclude() can prove order-independence."""
    pairs = list(zip(recs, polys))
    random.Random(seed).shuffle(pairs)
    return [r for r, _ in pairs], [p for _, p in pairs]


class ProjectionTests(unittest.TestCase):
    def test_projection_and_height_real_conventions(self):
        f = feat('ovt-1', 'overture', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=21.0)
        records, polys, audit = be.to_render_items([f], to_xy, point)
        self.assertEqual(len(records), 1)
        r = records[0]
        # (30.4000-30.40)*71000 = 0, (30.4010-30.40)*71000 = 71.0;
        # lat 50.4500 -> 0, 50.4510 -> +111.2 -> render z = -111.2.
        self.assertEqual(r['points'], [[0.0, 0.0, 0.0], [71.0, 0.0, 0.0],
                                       [71.0, 0.0, -111.2], [0.0, 0.0, -111.2]])
        self.assertEqual(r['height'], 21.0)
        self.assertEqual(r['height_source'], 'overture_assumed')
        self.assertEqual(r['levels'], 7)
        self.assertEqual(r['id'], 'enriched:overture:ovt-1')
        self.assertEqual(r['building_type'], 'overture')
        self.assertEqual(r['visual_source'], 'synthetic')
        self.assertEqual(r['source_id'], 'ovt-1')
        self.assertEqual(r['license'], 'ODbL-1.0')
        self.assertAlmostEqual(polys[0].area, 71.0 * 111.2, places=3)
        self.assertEqual(audit['features'], 1)
        self.assertEqual(audit['parts'], 1)
        self.assertEqual(audit['heights_known'], 1)
        self.assertEqual(audit['heights_assumed'], 0)

    def test_microsoft_provenance(self):
        f = feat('ms-1', 'microsoft', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=4.5)
        records, _, _ = be.to_render_items([f], to_xy, point)
        self.assertEqual(records[0]['id'], 'enriched:microsoft:ms-1')
        self.assertEqual(records[0]['height_source'], 'ml_estimated')
        self.assertEqual(records[0]['height'], 4.5)
        self.assertEqual(records[0]['license'], 'CDLA-Permissive-2.0')

    def test_default_height_assumed_with_explicit_opt_in(self):
        # Default is conservative ('skip'); the legacy synthetic default only
        # applies when 'assume' is explicitly opted in.
        f = feat('ovt-x', 'overture', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=None)
        records, _, audit = be.to_render_items([f], to_xy, point, unknown_height_policy='assume')
        self.assertEqual(records[0]['height'], be.DEFAULT_HEIGHT)
        self.assertEqual(records[0]['height_source'], 'enriched_assumed')
        self.assertIsNone(records[0]['height_provenance'])
        self.assertEqual(audit['heights_assumed'], 1)
        self.assertEqual(records[0]['levels'], int(max(1, round(be.DEFAULT_HEIGHT / 3.0))))

    def test_ms_unknown_height_assumed_only_with_opt_in(self):
        # MS marks unknown heights as -1; normaliser maps them to None, and the
        # enriched default must be explicit and flagged, never claimed measured.
        f = feat('ms-neg', 'microsoft', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=-1)
        records, _, audit = be.to_render_items([f], to_xy, point, unknown_height_policy='assume')
        self.assertEqual(records[0]['height'], be.DEFAULT_HEIGHT)
        self.assertEqual(records[0]['height_source'], 'enriched_assumed')
        self.assertEqual(audit['heights_assumed'], 1)

    def test_height_clamped(self):
        f = feat('tall', 'overture', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=500.0)
        records, _, _ = be.to_render_items([f], to_xy, point)
        self.assertEqual(records[0]['height'], be.HEIGHT_MAX)

    def test_bad_geometry_ignored(self):
        bad = {'type': 'Feature', 'geometry': {'type': 'LineString',
                                               'coordinates': [[30.4, 50.45], [30.41, 50.45]]},
               'properties': {'source': 'overture', 'source_id': 'line', 'release': 'r',
                              'license': 'l', 'height': None, 'height_provenance': None}}
        records, _, audit = be.to_render_items([bad], to_xy, point)
        self.assertEqual(records, [])
        self.assertEqual(audit['parts'], 0)


class UnknownHeightPolicyTests(unittest.TestCase):
    """Conservative default: only usable (finite >0) source heights survive,
    unless the explicit 'assume' policy opts into the synthetic default."""

    def _feat(self, sid, height):
        return feat(sid, 'overture', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=height)

    def test_default_policy_skips_absent_and_bad_heights(self):
        for i, h in enumerate((None, 0, -1, -5.0, float('nan'), float('inf'),
                               float('-inf'), 'abc', '')):
            records, _, audit = be.to_render_items([self._feat(f'bad-{i}', h)], to_xy, point)
            self.assertEqual(records, [], f'height {h!r} must be skipped by default')
            # Geometry converted fine (1 part); only the height policy rejects it.
            self.assertEqual(audit['parts'], 1, f'height {h!r}')
            self.assertEqual(audit['unknown_height_skipped'], 1, f'height {h!r}')
            self.assertEqual(audit['heights_known'], 0, f'height {h!r}')
            self.assertEqual(audit['heights_assumed'], 0, f'height {h!r}')

    def test_valid_positive_heights_kept_by_default(self):
        feats = [self._feat('h3', 3.0), self._feat('h180', 180.0)]
        records, _, audit = be.to_render_items(feats, to_xy, point)
        self.assertEqual(len(records), 2)
        self.assertEqual([r['height'] for r in records], [3.0, 180.0])
        self.assertEqual(audit['heights_known'], 2)
        self.assertEqual(audit['unknown_height_skipped'], 0)
        self.assertEqual(audit['heights_assumed'], 0)

    def test_assume_policy_restores_legacy_default(self):
        f = self._feat('legacy', None)
        records, _, audit = be.to_render_items([f], to_xy, point, unknown_height_policy='assume')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['height'], be.DEFAULT_HEIGHT)
        self.assertEqual(records[0]['height_source'], 'enriched_assumed')
        self.assertIsNone(records[0]['height_provenance'])
        self.assertEqual(audit['heights_assumed'], 1)
        self.assertEqual(audit['unknown_height_skipped'], 0)

    def test_assume_policy_uses_explicit_default_height(self):
        f = self._feat('explicit', None)
        records, _, audit = be.to_render_items([f], to_xy, point,
                                               unknown_height_policy='assume', default_height=7.5)
        self.assertEqual(records[0]['height'], 7.5)
        self.assertEqual(audit['heights_assumed'], 1)
        self.assertEqual(audit['unknown_height_skipped'], 0)

    def test_invalid_policy_rejected(self):
        f = self._feat('x', None)
        for bad in ('', 'SKIP', 'assume-', 'foo', 1, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                be.to_render_items([f], to_xy, point, unknown_height_policy=bad)

    def test_assume_with_unusable_default_height_rejected(self):
        f = self._feat('x', None)
        for bad in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError, msg=repr(bad)):
                be.to_render_items([f], to_xy, point,
                                   unknown_height_policy='assume', default_height=bad)


class ShapeHandlingTests(unittest.TestCase):
    def test_polygon_with_holes_skipped_audited(self):
        outer = box_geom(30.4000, 50.4500, 30.4010, 50.4510)
        inner = box_geom(30.4004, 50.4504, 30.4006, 50.4506)
        f = {'type': 'Feature',
             'geometry': {'type': 'Polygon', 'coordinates': outer['coordinates'] + inner['coordinates']},
             'properties': {'source': 'overture', 'source_id': 'with-hole', 'release': 'r',
                            'license': 'l', 'height': 15.0, 'height_provenance': 'overture_assumed'}}
        records, _, audit = be.to_render_items([f], to_xy, point)
        self.assertEqual(records, [])               # never exterior-only fill
        self.assertEqual(audit['holes_skipped'], 1)

    def test_always_multi_polygon_parts_become_records(self):
        mp = {'type': 'MultiPolygon',
              'coordinates': [box_geom(30.4000, 50.4500, 30.4010, 50.4510)['coordinates'],
                              box_geom(30.4020, 50.4500, 30.4030, 50.4510)['coordinates']]}
        f = feat('mp-1', 'overture', mp, height=12.0)
        records, _, audit = be.to_render_items([f], to_xy, point)
        self.assertEqual(len(records), 2)
        self.assertEqual([r['id'] for r in records], ['enriched:overture:mp-1:p0', 'enriched:overture:mp-1:p1'])
        self.assertEqual(audit['parts'], 2)

    def test_deterministic_render_order(self):
        feats = [
            feat('b', 'microsoft', box_geom(30.4020, 50.4520, 30.4030, 50.4530), height=9.0),
            feat('a', 'overture', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=21.0),
        ]
        r1, _, _ = be.to_render_items(feats, to_xy, point)
        r2, _, _ = be.to_render_items(feats, to_xy, point)
        self.assertEqual(r1, r2)


class ExclusionTests(unittest.TestCase):
    def test_osm_priority_overlap_dropped_adjacent_kept(self):
        osm_fp = [box(0.0, 0.0, 50.0, 50.0)]
        on_fp = box(0.0, 0.0, 50.0, 50.0)          # exact overlap with OSM
        beside = box(50.0, 0.0, 100.0, 50.0)        # touches the edge only
        records = [rec('on', 'overture', on_fp), rec('beside', 'overture', beside)]
        polys = [on_fp, beside]
        kept, audit = be.exclude(records, polys, osm_footprints=osm_fp)
        self.assertEqual([r['id'] for r in kept], ['beside'])
        self.assertEqual(audit['osm_excluded'], ['on'])
        self.assertEqual(audit['road_excluded'], [])
        self.assertEqual(audit['water_excluded'], [])

    def test_road_and_water_conflicts(self):
        road = box(-10.0, -10.0, 10.0, 10.0)
        water = box(100.0, 100.0, 120.0, 120.0)
        on_road = box(0.0, 0.0, 5.0, 5.0)
        in_water = box(105.0, 105.0, 110.0, 110.0)
        clear = box(50.0, 50.0, 60.0, 60.0)
        records = [rec('r', 'overture', on_road), rec('w', 'overture', in_water), rec('c', 'overture', clear)]
        polys = [on_road, in_water, clear]
        kept, audit = be.exclude(records, polys, road_union=road, water_union=water)
        self.assertEqual([r['id'] for r in kept], ['c'])
        self.assertEqual(audit['road_excluded'], ['r'])
        self.assertEqual(audit['water_excluded'], ['w'])

    def test_overlap_deduplicated_by_internal_priority_not_input_order(self):
        # Input deliberately reversed: microsoft first. exclude() must sort
        # internally (Overture > Microsoft), so overture always wins.
        ms = box(10.0, 10.0, 50.0, 50.0)
        ovt = box(0.0, 0.0, 40.0, 40.0)             # overlaps ms square
        records = [rec('ms-late', 'microsoft', ms), rec('ovt-first', 'overture', ovt)]
        polys = [ms, ovt]
        kept, audit = be.exclude(records, polys)
        self.assertEqual([r['id'] for r in kept], ['ovt-first'])
        self.assertEqual(audit['duplicate_overlap_dropped'], ['ms-late'])
        self.assertEqual(audit['osm_excluded'], [])
        self.assertEqual(audit['road_excluded'], [])
        self.assertEqual(audit['water_excluded'], [])

    def test_same_source_overlap_first_sorted_kept(self):
        a = box(0.0, 0.0, 40.0, 40.0)
        b = box(10.0, 10.0, 50.0, 50.0)
        records = [rec('zz', 'microsoft', a), rec('aa', 'microsoft', b)]
        polys = [a, b]
        kept, audit = be.exclude(records, polys)
        self.assertEqual([r['id'] for r in kept], ['aa'])          # source_id sorted
        self.assertEqual(audit['duplicate_overlap_dropped'], ['zz'])

    def test_adjacent_buildings_are_not_duplicates(self):
        a = box(0.0, 0.0, 40.0, 40.0)
        b = box(40.0, 0.0, 80.0, 40.0)             # shares the edge only
        records = [rec('a', 'overture', a), rec('b', 'microsoft', b)]
        polys = [a, b]
        kept, audit = be.exclude(records, polys)
        self.assertEqual([r['id'] for r in kept], ['a', 'b'])
        self.assertEqual(audit['duplicate_overlap_dropped'], [])
        self.assertEqual(audit['osm_excluded'], [])
        self.assertEqual(audit['road_excluded'], [])
        self.assertEqual(audit['water_excluded'], [])

    def test_deterministic_kept_order_regardless_of_input(self):
        ms = box(10.0, 10.0, 50.0, 50.0)
        ovt = box(0.0, 0.0, 40.0, 40.0)
        clear = box(200.0, 200.0, 220.0, 220.0)
        triples = [(rec('m', 'microsoft', ms), ms),
                   (rec('o', 'overture', ovt), ovt),
                   (rec('c', 'overture', clear), clear)]
        forward = ([t[0] for t in triples], [t[1] for t in triples])
        backward = ([t[0] for t in reversed(triples)], [t[1] for t in reversed(triples)])
        k1, a1 = be.exclude(*forward)
        k2, a2 = be.exclude(*backward)
        self.assertEqual([r['id'] for r in k1], [r['id'] for r in k2])
        self.assertEqual(a1, a2)
        # internal sort: overture ('c' < 'o') then microsoft; 'm' overlaps 'o' -> dropped
        self.assertEqual([r['id'] for r in k1], ['c', 'o'])
        self.assertEqual(a1['duplicate_overlap_dropped'], ['m'])

    def test_end_to_end_feature_to_kept(self):
        feats = [
            feat('ms-dup', 'microsoft', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=6.0),
            feat('ovt-same', 'overture', box_geom(30.4000, 50.4500, 30.4010, 50.4510), height=21.0),
            feat('ovt-clear', 'overture', box_geom(30.4080, 50.4580, 30.4090, 50.4590), height=9.0),
        ]
        records, polys, conversion = be.to_render_items(feats, to_xy, point)
        kept, audit = be.exclude(records, polys)
        # exclude() sorts internally by (source priority, source_id): both kept
        # are overture, so alphabetical source_id order wins.
        self.assertEqual([r['id'] for r in kept], ['enriched:overture:ovt-clear', 'enriched:overture:ovt-same'])
        self.assertEqual(audit['duplicate_overlap_dropped'], ['enriched:microsoft:ms-dup'])
        # every kept record must not carry a "_poly" bucket and must be render-ready
        for r in kept:
            self.assertTrue(r['points'])
            self.assertTrue(r['id'].startswith('enriched:'))

    def test_by_source_accepted_rejected_counts(self):
        records = [
            rec('ms-d', 'microsoft', box(0.0, 0.0, 50.0, 50.0)),      # dup: overlaps ovt-a
            rec('ovt-a', 'overture', box(10.0, 10.0, 40.0, 40.0)),    # accepted
            rec('ovt-b', 'overture', box(100.0, 100.0, 140.0, 140.0)),  # accepted
            rec('ms-r', 'microsoft', box(200.0, 200.0, 240.0, 240.0)),  # road
            rec('ovt-c', 'overture', box(300.0, 300.0, 330.0, 330.0)),  # osm
            rec('ms-c', 'microsoft', box(400.0, 400.0, 440.0, 440.0)),  # accepted
        ]
        polys = [box(0, 0, 50, 50), box(10, 10, 40, 40), box(100, 100, 140, 140),
                 box(200, 200, 240, 240), box(300, 300, 330, 330), box(400, 400, 440, 440)]
        kept, audit = be.exclude(records, polys,
                                 osm_footprints=[box(290.0, 290.0, 340.0, 340.0)],
                                 road_union=box(190.0, 190.0, 250.0, 250.0))
        self.assertEqual([r['id'] for r in kept], ['ovt-a', 'ovt-b', 'ms-c'])
        self.assertEqual(audit['by_source'], {
            'overture': {'accepted': 2, 'rejected': 1, 'osm': 1,
                         'road': 0, 'water': 0, 'duplicate': 0},
            'microsoft': {'accepted': 1, 'rejected': 2, 'osm': 0,
                          'road': 1, 'water': 0, 'duplicate': 1},
        })
        # accepted + rejected must cover every candidate per source
        for source, per in audit['by_source'].items():
            self.assertEqual(per['accepted'] + per['rejected'],
                             sum(1 for r in records if r['source'] == source))


class InstrumentationTests(unittest.TestCase):
    """Scalability regression: STRtree must be built exactly once per spatial
    stage, never per candidate (the old exclude() rebuilt the kept-polygons
    tree inside the duplicate loop -> O(n^2))."""

    @staticmethod
    def _counted_tree():
        real_tree = be.STRtree

        class CountedTree:
            builds = 0

            def __init__(self, geoms):
                type(self).builds += 1
                self._t = real_tree(geoms)

            def query(self, geom):
                return self._t.query(geom)

        return real_tree, CountedTree

    def test_strtree_construction_count_constant_400_vs_4(self):
        real_tree, counted = self._counted_tree()
        be.STRtree = counted
        try:
            for side in (2, 20):                    # 4 vs 400 disjoint candidates
                recs, polys = grid_candidates(side)
                counted.builds = 0
                k1, a1 = be.exclude(*shuffle_pairs(recs, polys, seed=1))
                # exactly ONE build per call: the candidate index; count must
                # not depend on candidate count (4 vs 400).
                self.assertEqual(counted.builds, 1, f'{len(recs)} candidates first run')
                counted.builds = 0
                k2, a2 = be.exclude(*shuffle_pairs(recs, polys, seed=2))
                self.assertEqual(counted.builds, 1, f'{len(recs)} candidates second run')
                self.assertEqual(len(recs), len(k1))
                self.assertEqual([r['id'] for r in k1], [r['id'] for r in k2])
                self.assertEqual(a1, a2)
        finally:
            be.STRtree = real_tree

    def test_strtree_osm_and_candidate_trees_built_once(self):
        real_tree, counted = self._counted_tree()
        recs, polys = grid_candidates(10)           # 100 disjoint candidates
        recs.append(rec('osm-hit', 'overture', box(5.0, 5.0, 25.0, 25.0)))
        polys.append(box(5.0, 5.0, 25.0, 25.0))
        osm = [box(0.0, 0.0, 30.0, 30.0)]
        be.STRtree = counted
        try:
            counted.builds = 0
            k1, a1 = be.exclude(*shuffle_pairs(recs, polys, seed=3), osm_footprints=osm)
            # OSM tree + candidate tree: exactly 2 builds per call, once each.
            self.assertEqual(counted.builds, 2)
            counted.builds = 0
            k2, a2 = be.exclude(*shuffle_pairs(recs, polys, seed=4), osm_footprints=osm)
            self.assertEqual(counted.builds, 2)
            self.assertEqual(len(k1), 100)
            self.assertEqual(a1['osm_excluded'], ['osm-hit'])
            self.assertEqual([r['id'] for r in k1], [r['id'] for r in k2])
            self.assertEqual(a1, a2)
        finally:
            be.STRtree = real_tree


class CacheProvenanceTests(unittest.TestCase):
    """reused_cache_files() must report exactly the cache files behind THIS
    map's candidate fetch (per-source key derived from the audit the same way
    building_sources computes it), never unrelated caches from other maps."""

    @staticmethod
    def _focus_like_audit():
        bbox = [30.348, 50.452, 30.366, 50.47]
        return {'sources': {
            'overture': {'status': 'ok', 'release': '2026-08-19.0',
                         'bbox_cached': list(bs._expand(bbox, 0.002)), 'geo_q': 0.002},
            'microsoft': {'status': 'ok', 'release': '2026-08-13',
                          'bbox_cached': list(bs._expand(bbox, 0.002)), 'geo_q': 0.002},
            'local': {'status': 'error', 'release': 'x',
                      'bbox_cached': [0.0, 0.0, 1.0, 1.0], 'geo_q': 0.002},
        }}

    def test_cache_paths_derived_from_audit_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ovt_key = bs._geo_key([30.348, 50.452, 30.366, 50.47], 0.002)
            ms_key = bs._geo_key([30.348, 50.452, 30.366, 50.47], 0.002)
            ovt_file = root / 'overture' / '2026-08-19.0' / ovt_key / 'features.geojson'
            ms_file = root / 'microsoft' / '2026-08-13' / ms_key / 'features.geojson'
            for f in (ovt_file, ms_file):
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text('{}')
            # decoys that must NOT appear: other release, unrelated map dir
            # (no audit entry), and the errored 'local' source.
            decoys = [
                root / 'overture' / '1999-01-01' / '0.0000_0.0000_1.0000_1.0000' / 'features.geojson',
                root / 'edge-junk' / 'x' / 'y' / 'features.geojson',
                root / 'local' / 'x' / '0.0000_0.0000_1.0000_1.0000' / 'features.geojson',
            ]
            for d in decoys:
                d.parent.mkdir(parents=True, exist_ok=True)
                d.write_text('{}')
            got = be.reused_cache_files(root, self._focus_like_audit())
            self.assertEqual(got, sorted([str(ovt_file), str(ms_file)]))
            self.assertEqual(be.reused_cache_files(root, None), [])
            self.assertEqual(be.reused_cache_files(root, {'sources': {}}), [])

    def test_real_focus_cache_meta_matches_derivation(self):
        cache_root = ROOT / '.cache' / 'buildings'
        if not cache_root.exists():
            self.skipTest('building caches not present on this machine')
        audit = {'sources': {}}
        for source, release in (('overture', '2026-08-19.0'), ('microsoft', '2026-08-13')):
            key_dir = cache_root / source / release / '30.3480_50.4520_30.3660_50.4700'
            if not (key_dir / 'meta.json').is_file() or not (key_dir / 'features.geojson').is_file():
                self.skipTest('optional real focus cache is incomplete or uses another release')
            meta = json.loads((key_dir / 'meta.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['status'], 'ok')
            audit['sources'][source] = {'status': meta['status'], 'release': meta['release'],
                                        'bbox_cached': meta['bbox_cached'], 'geo_q': meta['geo_q']}
        files = be.reused_cache_files(cache_root, audit)
        self.assertEqual(files, sorted([
            str(cache_root / 'overture' / '2026-08-19.0' / '30.3480_50.4520_30.3660_50.4700' / 'features.geojson'),
            str(cache_root / 'microsoft' / '2026-08-13' / '30.3480_50.4520_30.3660_50.4700' / 'features.geojson'),
        ]))
        for f in files:
            self.assertTrue(Path(f).is_file())


class AttributionTests(unittest.TestCase):
    BASE = '© OpenStreetMap contributors · ODbL | Terrain: Mapzen / source attribution in docs/SOURCES.md'

    def test_base_unchanged_without_enrichment(self):
        # no enrichment sources accepted -> base footer byte-for-byte
        self.assertEqual(be.attribution([], self.BASE), self.BASE)
        self.assertEqual(be.attribution([{'source': 'building'}, {'source': 'yes'}], self.BASE),
                         self.BASE)

    def test_only_accepted_sources_added(self):
        ovt = be.attribution([{'source': 'overture'}], self.BASE)
        self.assertIn('OpenStreetMap contributors · ODbL', ovt)
        self.assertIn('Overture · ODbL', ovt)
        self.assertNotIn('Microsoft', ovt)
        self.assertTrue(ovt.endswith('| Mapzen'))
        ms = be.attribution([{'source': 'microsoft'}], self.BASE)
        self.assertIn('Microsoft · CDLA-2.0', ms)
        self.assertNotIn('Overture', ms)
        # duplicates and non-enrichment records never add extra sources
        both = be.attribution([{'source': 'microsoft'}, {'source': 'overture'},
                               {'source': 'building'}, {'source': 'building'}], self.BASE)
        self.assertIn('Overture · ODbL', both)
        self.assertIn('Microsoft · CDLA-2.0', both)

    def test_full_footer_exact_and_short(self):
        full = be.attribution([{'source': 'overture'}, {'source': 'overture'},
                               {'source': 'microsoft'}], self.BASE)
        self.assertEqual(full, '© OpenStreetMap contributors · ODbL | Overture · ODbL'
                               ' | Microsoft · CDLA-2.0 | Mapzen')
        self.assertLessEqual(len(full), 100)


class GateTests(unittest.TestCase):
    def test_missing_cache_not_silent(self):
        audit = {'status': 'offline_cache_miss', 'sources': {'microsoft': {'error': 'no valid cache'}}}
        with self.assertRaises(be.EnrichmentError):
            be.gate(audit, strict=True)
        problems = be.gate(audit, strict=False)     # visible even non-strict
        self.assertTrue(problems)
        self.assertTrue(any('offline_cache_miss' in p for p in problems))

    def test_error_and_partial_raise_when_strict(self):
        for status in ('error', 'partial'):
            with self.assertRaises(be.EnrichmentError, msg=status):
                be.gate({'status': status, 'sources': {}}, strict=True)

    def test_ok_and_no_input_are_clean(self):
        self.assertEqual(be.gate({'status': 'ok', 'sources': {}}, strict=True), [])
        self.assertEqual(be.gate({'status': 'no_source_data', 'sources': {}}, strict=True), [])
        self.assertEqual(be.gate(None, strict=True), [])


class MapConfigTests(unittest.TestCase):
    def test_maps_share_reusable_enrichment_configuration(self):
        focus = json.loads((ROOT / 'config' / 'focus_metro_mcd.json').read_text(encoding='utf-8'))
        akadem = json.loads((ROOT / 'config' / 'akadem.json').read_text(encoding='utf-8'))
        west = json.loads((ROOT / 'config' / 'west_kyiv.json').read_text(encoding='utf-8'))
        for cfg in (focus, akadem, west):
            self.assertIn('building_enrichment', cfg)
            self.assertIsInstance(cfg['building_enrichment']['enabled'], bool)
        self.assertTrue(focus['building_enrichment']['offline'])
        self.assertTrue(focus['building_enrichment']['strict'])
        block = {k: v for k, v in focus['building_enrichment'].items() if k != 'enabled'
                 and k != 'note'}
        for cfg in (akadem, west):
            same = {k: v for k, v in cfg['building_enrichment'].items() if k != 'enabled'
                    and k != 'note'}
            self.assertEqual(same, block)
        self.assertEqual(set(focus['building_enrichment']['sources']), {'overture', 'microsoft'})
        self.assertTrue(focus['building_enrichment']['sources']['overture']['duckdb'])
        for cfg in (focus, akadem, west):
            self.assertEqual(cfg['building_enrichment']['unknown_height_policy'], 'skip',
                             'default policy must stay conservative across maps')
            self.assertIn('default_height', cfg['building_enrichment'],
                          'default_height stays as explicit opt-in for the assume policy')


if __name__ == '__main__':
    unittest.main()
