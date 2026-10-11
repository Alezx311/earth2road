"""Configs for Kyiv districts and nearby towns from OSM administrative boundaries.

Reads boundaries extracted from the dated Geofabrik PBF (relations listed in AREAS),
writes config/districts/areas/<id>.geojson (role=settlement, already buffered) and config/districts/<id>.json.
The boundary is administrative; the playable area adds BUFFER_M outward. Areas above
MAX_PART_KM2 are split into equal-area parts along their longer axis (one map each, with
OVERLAP_M shared at the seams): a whole large district does not fit in build memory and
an 8 x 8 km BeamNG level already failed to load.
"""
import argparse
import json
import math
from pathlib import Path

from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
BUFFER_M = 150
MAX_PART_KM2 = 55
OVERLAP_M = 200
SIMPLIFY_M = 10  # netconvert gets the buffered ring on its command line (Windows: 32767 chars)
# Kyiv-area cut of ukraine-260918.osm.pbf (md5 8357c720d91f72db3aa5feb6dea04bf3) made with the
# same selection as core/osm_extract.py for bbox REGION_BBOX, so every per-map extract stays complete.
# It is local only: the "url" names the cache file, nothing is downloaded from it.
REGION_BBOX = [30.10, 50.16, 31.06, 50.68]
GEOFABRIK = {'url': 'local/ukraine-260918-kyiv.osm.pbf',
             'md5': '41a038084c3ba11ed0fe2a7bb0c17c71',
             'note': 'Local cut of the dated Geofabrik extract ukraine-260918 (OSM data 2026-09-18), '
                     f'bbox {REGION_BBOX}; place it in <cache>/geofabrik/.'}

# id, display name, OSM relation ids (unioned)
AREAS = [
    ('kyiv_pecherskyi', 'Київ — Печерський район', [1755013]),
    ('kyiv_shevchenkivskyi', 'Київ — Шевченківський район', [1755014]),
    ('kyiv_podilskyi', 'Київ — Подільський район', [1754975]),
    ('kyiv_solomianskyi', 'Київ — Солом’янський район', [1754514]),
    ('kyiv_dniprovskyi', 'Київ — Дніпровський район', [1754781]),
    ('kyiv_sviatoshynskyi', 'Київ — Святошинський район', [1754751]),
    ('kyiv_obolonskyi', 'Київ — Оболонський район', [1754928]),
    ('kyiv_darnytskyi', 'Київ — Дарницький район', [1754757]),
    ('kyiv_desnianskyi', 'Київ — Деснянський район', [1754820]),
    ('kyiv_holosiivskyi', 'Київ — Голосіївський район', [1754513]),
    ('irpin', 'Ірпінь', [11092577]),
    ('bucha', 'Буча', [2265598]),
    ('brovary', 'Бровари', [1929810]),
    ('vyshneve', 'Вишневе і Крюківщина', [2614178, 2613594]),
    ('boryspil', 'Бориспіль', [1934961]),
    ('vyshhorod', 'Вишгород', [421865]),
    ('boiarka', 'Боярка', [2222157]),
    ('borshchahivka', 'Софіївська і Петропавлівська Борщагівка', [3572141, 4741502]),
]


LABELS = {('y', 2): ['південь', 'північ'], ('y', 3): ['південь', 'центр', 'північ'],
          ('x', 2): ['захід', 'схід'], ('x', 3): ['захід', 'центр', 'схід'],
          ('y', 4): ['південь', 'південний центр', 'північний центр', 'північ'],
          ('x', 4): ['захід', 'західний центр', 'східний центр', 'схід']}
SUFFIX = {'південь': 's', 'північ': 'n', 'центр': 'c', 'захід': 'w', 'схід': 'e',
          'південний центр': 'cs', 'північний центр': 'cn', 'західний центр': 'cw', 'східний центр': 'ce'}


def playable(metric):
    """Outline + BUFFER_M with coarse arcs, simplified so netconvert's boundary argument fits
    the Windows command line; the config then uses buffer_m 0 (no extra fine arcs)."""
    area = metric.buffer(BUFFER_M, quad_segs=2).simplify(SIMPLIFY_M)
    if area.geom_type != 'Polygon':
        raise ValueError(f'buffered area is {area.geom_type}')
    return Polygon(area.exterior)


def largest(geom):
    return max(getattr(geom, 'geoms', [geom]), key=lambda g: g.area)


def split(area, k):
    """k connected parts of equal area along the longer axis, each grown by OVERLAP_M inside area."""
    w, s, e, n = area.bounds
    axis = 'y' if n - s >= e - w else 'x'
    lo, hi = (s, n) if axis == 'y' else (w, e)
    slab = lambda a, b: box(w - 1, a, e + 1, b) if axis == 'y' else box(a, s - 1, b, n + 1)
    cuts = [lo]
    for i in range(1, k):
        a, b = cuts[-1], hi
        for _ in range(60):  # bisection on the cumulative area
            m = (a + b) / 2
            if area.intersection(slab(lo, m)).area < area.area * i / k:
                a = m
            else:
                b = m
        cuts.append((a + b) / 2)
    cuts.append(hi)
    pieces = [area.intersection(slab(cuts[i], cuts[i + 1])) for i in range(k)]
    mains = [largest(p) for p in pieces]
    # Disconnected fragments of a slab join the part they touch.
    for i, p in enumerate(pieces):
        frags = sorted(getattr(p, 'geoms', []), key=lambda g: g.area)[:-1]
        for frag in frags:
            j = min((j for j in range(k) if j != i), key=lambda j: mains[j].distance(frag))
            mains[j] = largest(unary_union([mains[j], frag.buffer(1)]))
    parts = [Polygon(largest(m.buffer(OVERLAP_M, quad_segs=2).intersection(area)).exterior).simplify(SIMPLIFY_M) for m in mains]
    return list(zip(LABELS[axis, k], parts))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('admin', type=Path, help='GeoJSON of admin relations (properties.rel)')
    args = p.parse_args(argv)
    doc = json.loads(args.admin.read_text(encoding='utf8'))
    by_rel = {f['properties']['rel']: shape(f['geometry']) for f in doc['features']}
    for mid, name, rels in AREAS:
        geom = unary_union([by_rel[r] for r in rels])
        lat = geom.centroid.y
        kx, ky = 111320.0 * math.cos(math.radians(lat)), 110540.0
        area = playable(transform(lambda x, y, z=None: (x * kx, y * ky), geom))
        k = math.ceil(area.area / 1e6 / MAX_PART_KM2)
        parts = [(None, area)] if k == 1 else split(area, k)
        for label, part in parts:
            pid = mid if label is None else f'{mid}_{SUFFIX[label]}'
            pname = name if label is None else f'{name} · {label}'
            write(pid, pname, rels, transform(lambda x, y, z=None: (x / kx, y / ky), part), label)
            print(pid, round(part.area / 1e6, 1), 'km2', len(part.exterior.coords), 'points')


def write(mid, name, rels, outline, label):
    osm = ', '.join(f'relation/{r}' for r in rels)
    (ROOT / 'config/districts/areas' / f'{mid}.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'role': 'settlement', 'name': name, 'osm': [f'relation/{r}' for r in rels]},
         'geometry': mapping(outline)}]}, ensure_ascii=False), encoding='utf8')
    c = outline.representative_point()
    note = f'OSM administrative boundary ({osm}) + {BUFFER_M} m buffer.'
    if label:
        note += f' Part "{label}" of an equal-area split, {OVERLAP_M} m overlap with neighbouring parts.'
    cfg = {'id': mid, 'name': name, 'region_profile': 'ukraine', 'center': [round(c.x, 6), round(c.y, 6)],
           'boundary': {'geojson': f'areas/{mid}.geojson', 'buffer_m': 0},
           'chunk_size': 250, 'seed': 311, 'terrain_zoom': 12, 'traffic_count': 600, 'start_time': '08:00',
           'geofabrik': GEOFABRIK, 'note': note}
    (ROOT / 'config/districts' / f'{mid}.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

if __name__ == '__main__':
    main()
