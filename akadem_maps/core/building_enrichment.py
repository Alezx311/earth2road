"""INTEGRATE package: DATA building candidates -> render-schema buildings.

Pure helpers bridging ``tools/building_sources.py`` normal form (GeoJSON
features in EPSG4326 with ``source/source_id/release/license/height/
height_provenance``) into the existing render building schema used by
``game/visuals/tile.gd`` (``id``, ``points`` as local ``[x, z, -y]``, ``height``,
``height_source``, ``levels``, ``building_type``, ``visual_family``,
``visual_source``, optional ``ground_floor`` / ``base``).

The documented priority chain is enforced here in metric metres:

    OSM (always first)  >  Overture  >  Microsoft

Nothing in this module touches the network, the SUMO network/demand or any OSM
record: OSM buildings are never mutated, only *excluded against*. The caller
(tools/prepare.py) supplies the projected ``to_xy(lon, lat)`` callback, the
projected OSM building footprints, the non-bridge road cut and the water
polygons.

Rules implemented (documented in .opencode/plans/city-enrichment.md):

* MultiPolygon features are split: every part becomes its own building record.
* A polygon WITH holes is skipped and counted in the audit (``holes_skipped``):
  the existing renderer draws simple footprints only, and emitting the exterior
  ring alone would silently fill the hole. Skipping is the honest default.
* Heights: a source height is carried over untouched with its provenance
  (``ml_estimated`` / ``overture_assumed``), but a source-provided value is ML/
  Overture metadata, never surveyed ground truth. Candidates without a usable
  (finite, >0) source height are skipped by default
  (``unknown_height_policy="skip"``, counted in ``unknown_height_skipped``);
  only an explicit ``unknown_height_policy="assume"`` opt-in applies the
  synthetic ``default_height`` (``height_source="enriched_assumed"``).
  Nothing is ever claimed measured.
* Exclusions happen in this order: OSM overlap -> non-bridge road overlap ->
  water overlap -> indexed duplicate/overlap among survivors (higher priority
  Overture > Microsoft wins; footprints that merely touch are neighbours, not
  duplicates). The road cut passed in already omits bridge decks, so buildings
  under a bridge are not rejected by its deck.
* Source ids stay stable (``enriched:<source>:<source_id>[:p<part>]``); OSM ids
  are never invented, and the ``enriched:`` prefix keeps these from ever
  colliding with the numeric OSM way ids.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shapely import STRtree
from shapely.geometry import Polygon, shape
from shapely.prepared import prep

SOURCE_ORDER = {'overture': 0, 'microsoft': 1}
# Conservative default: external candidates without a usable (finite >0) source
# height are SKIPPED, never invented. 'assume' is the explicit legacy opt-in
# that applies DEFAULT_HEIGHT to unknown heights.
UNKNOWN_HEIGHT_POLICIES = ('skip', 'assume')
DEFAULT_HEIGHT = 10.0        # synthetic default, used only with 'assume' policy
HEIGHT_MIN = 2.0             # same clamp as OSM buildings in prepare.py
HEIGHT_MAX = 180.0
MIN_AREA = 1.0               # m2; ML/assumed footprints smaller than this are slivers
BAD_STATUSES = ('error', 'offline_cache_miss', 'partial')


class EnrichmentError(RuntimeError):
    """Strict-mode failure: enrichment is enabled but the data is unusable
    (fetch error, offline cache miss, partial failure)."""


ATTRIBUTION_OSM = '© OpenStreetMap contributors · ODbL'
ATTRIBUTION_TERRAIN = 'Mapzen'
SOURCE_ATTRIBUTION_LABELS = {
    'overture': 'Overture · ODbL',
    'microsoft': 'Microsoft · CDLA-2.0',
}


def attribution(records: Sequence[Dict[str, Any]], base: str) -> str:
    """Footer line for the generated world.

    Returns ``base`` unchanged when no enrichment source was accepted, so
    OSM-only worlds keep their exact existing footer. Once Overture/Microsoft
    buildings are shipped, returns a shorter footer that still keeps the full
    "OpenStreetMap contributors · ODbL" attribution, names only the accepted
    enrichment sources and keeps \"Mapzen\" for terrain. Length target <= 100."""
    present = [s for s in ('overture', 'microsoft')
               if any(r.get('source') == s for r in records)]
    if not present:
        return base
    return ' | '.join([ATTRIBUTION_OSM] + [SOURCE_ATTRIBUTION_LABELS[s] for s in present]
                      + [ATTRIBUTION_TERRAIN])


def _clean_height(value: Any) -> Optional[float]:
    """Finite, strictly positive height in metres, else None (parity with
    building_sources.clean_height; local copy keeps this module input-only)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def translate_polygon(p: Any, to_xy) -> Polygon:
    """One shapely polygon (EPSG4326) -> metric Polygon, holes preserved."""
    if p.is_empty:
        return Polygon()
    shell = [tuple(to_xy(*c)) for c in p.exterior.coords]
    if len(shell) < 4:
        return Polygon()
    holes = [[tuple(to_xy(*c)) for c in hole.coords] for hole in p.interiors]
    try:
        out = Polygon(shell, holes)
    except ValueError:
        return Polygon()
    if not out.is_valid:
        out = out.buffer(0)
    return out if not out.is_empty else Polygon()


def to_local_polys(geom: Any, to_xy) -> List[Polygon]:
    """Feature geometry (EPSG4326) -> list of metric Polygons.

    Polygons keep their holes (handled later, not dropped); MultiPolygon parts
    come back as separate entries so each part becomes one building record."""
    if geom is None:
        return []
    try:
        g = shape(geom)
    except Exception:
        return []
    if g.geom_type == 'Polygon':
        return [translate_polygon(g, to_xy)]
    if g.geom_type == 'MultiPolygon':
        return [translate_polygon(part, to_xy) for part in g.geoms]
    return []


def to_render_items(features: Sequence[Dict[str, Any]], to_xy, point, *,
                    default_height: float = DEFAULT_HEIGHT,
                    min_area: float = MIN_AREA,
                    unknown_height_policy: str = 'skip') -> Tuple[List[Dict[str, Any]], List[Polygon], Dict[str, int]]:
    """Normal-form features -> ``(records, polys, conversion_audit)``.

    ``to_xy(lon, lat)`` projects WGS84 into metric metres
    (``net.convertLonLat2XY`` in prepare.py). ``point(x, y)`` turns metres into
    a render point ``[x, ground_z, -y]``; the caller's callback samples ground
    height. Returns parallel ``records`` (render schema) and ``polys`` (metric
    footprints for exclusion). Records come out in input order — DATA already
    sorts deterministically by ``(source priority, source_id)``.

    Heights are conservative by default (``unknown_height_policy="skip"``):
    candidates whose source height is absent/invalid/nonpositive are skipped
    and counted in ``unknown_height_skipped``. Only an explicit
    ``unknown_height_policy="assume"`` opt-in applies ``default_height`` to
    unknown heights (``heights_assumed``). A source-provided value is ML/
    Overture metadata, never surveyed ground truth."""
    if unknown_height_policy not in UNKNOWN_HEIGHT_POLICIES:
        raise ValueError(f"unknown_height_policy {unknown_height_policy!r} must be one of "
                         f"{UNKNOWN_HEIGHT_POLICIES}")
    records: List[Dict[str, Any]] = []
    polys: List[Polygon] = []
    audit = {'features': len(features), 'parts': 0, 'holes_skipped': 0,
             'too_small_skipped': 0, 'unknown_height_skipped': 0,
             'heights_known': 0, 'heights_assumed': 0}
    for f in features:
        p = f.get('properties') or {}
        source, source_id = p.get('source'), p.get('source_id')
        if not source or not source_id:
            continue
        geom_polys = to_local_polys(f.get('geometry'), to_xy)
        multi = len(geom_polys) > 1
        for part_index, poly in enumerate(geom_polys):
            if poly.is_empty or not poly.is_valid:
                continue
            if len(poly.interiors) > 0:
                # Renderer draws simple footprints only; exterior-only output
                # would silently fill the hole, so skip and report instead.
                audit['holes_skipped'] += 1
                continue
            if poly.area < min_area:
                audit['too_small_skipped'] += 1
                continue
            audit['parts'] += 1
            height = _clean_height(p.get('height'))
            if height is not None:
                # Source metadata carries a usable value, but that is ML/Overture
                # metadata, not surveyed ground truth.
                prov = p.get('height_provenance')
                audit['heights_known'] += 1
                height_source = prov or 'enriched_assumed'
            elif unknown_height_policy == 'assume':
                # Explicit legacy opt-in: synthetic default for unknown heights.
                prov = None
                height = _clean_height(default_height)
                if height is None:
                    raise ValueError(f"default_height {default_height!r} must be finite "
                                     f"and > 0 for unknown_height_policy='assume'")
                audit['heights_assumed'] += 1
                height_source = 'enriched_assumed'
            else:
                audit['unknown_height_skipped'] += 1
                continue
            height = max(HEIGHT_MIN, min(HEIGHT_MAX, height))
            rid = f'enriched:{source}:{source_id}'
            if multi:
                rid += f':p{part_index}'
            ring = [point(x, y) for x, y in list(poly.exterior.coords)[:-1]]
            records.append({
                'id': rid,
                'points': ring,
                'height': round(height, 2),
                'height_source': height_source,
                'levels': int(max(1, round(height / 3.0))),
                'building_type': source,
                'visual_family': '',
                'visual_source': 'synthetic',
                'source': source,
                'source_id': source_id,
                'release': p.get('release'),
                'license': p.get('license'),
                'height_provenance': prov,
            })
            polys.append(poly)
    return records, polys, audit


def _union_buffered(geom: Any, margin: float) -> Polygon:
    if geom is None or geom.is_empty:
        return Polygon()
    g = geom.buffer(float(margin)) if margin else geom
    return g if not g.is_empty else Polygon()


def _overlaps_tree(tree: STRtree, geoms: Sequence[Any], poly: Polygon, area_min: float) -> bool:
    """True if ``poly`` overlaps any ``geoms`` with positive intersection area
    (boundary-touching neighbours stay). Envelope test via the tree first, then
    the exact intersection, so only genuine overlap counts."""
    for idx in tree.query(poly):
        if poly.intersection(geoms[idx]).area > area_min:
            return True
    return False


def exclude(records: Sequence[Dict[str, Any]], polys: Sequence[Polygon],
            osm_footprints: Optional[Sequence[Any]] = None,
            road_union: Any = None, water_union: Any = None, *,
            road_margin: float = 0.5, water_margin: float = 0.5,
            overlap_area_min: float = 1e-4) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Priority/exclusion pipeline -> ``(kept_records, exclusion_audit)``.

    Drop order: OSM overlap, road overlap, water overlap, then indexed
    duplicate/overlap among the survivors. ``road_union`` is the *non-bridge*
    road cut (prepare.py builds it without bridge strips, so bridge decks never
    reject buildings below them). ``polys`` are the metric footprints parallel
    to ``records``.

    The pipeline is order-independent: candidates are re-sorted by the stable
    priority key ``(SOURCE_ORDER[source], source_id)`` before anything else, so
    the caller never has to pre-sort input. An overlap means *positive
    intersection area* (> ``overlap_area_min``); footprints that merely touch
    (adjacent buildings sharing an edge) are never dropped. Only the first
    (highest-priority) copy of an overlap is kept.

    Scalability (Kyiv-scale candidate sets): every spatial index is built
    exactly once per call. The OSM footprint tree is static; road/water get a
    single prepared geometry whose cheap ``intersects()`` prefilter avoids the
    full intersection+area cost for far-away candidates; the duplicate check
    uses one STRtree over ALL sorted candidates plus a *kept index set*, so the
    tree is never rebuilt per candidate (once per call, not once per kept
    polygon). The audit includes ``by_source`` breakdowns of accepted/rejected
    counts per reason."""
    audit = {'osm_excluded': [], 'road_excluded': [], 'water_excluded': [],
             'duplicate_overlap_dropped': [], 'by_source': {}}

    def bump(source: Any, key: str) -> None:
        d = audit['by_source'].setdefault(
            str(source or 'unknown'),
            {'accepted': 0, 'rejected': 0, 'osm': 0, 'road': 0,
             'water': 0, 'duplicate': 0})
        d[key] += 1

    osm = [geom for geom in (osm_footprints or [])
           if geom is not None and not geom.is_empty and geom.is_valid
           and geom.geom_type in ('Polygon', 'MultiPolygon')]
    road = _union_buffered(road_union, road_margin)
    water = _union_buffered(water_union, water_margin)
    # Stable internal priority ordering: never rely on the caller's input order.
    pairs = [(rec, poly) for rec, poly in zip(records, polys)
             if poly is not None and not poly.is_empty and poly.is_valid]
    pairs.sort(key=lambda pair: (SOURCE_ORDER.get(str(pair[0].get('source') or ''), 9),
                                 str(pair[0].get('source_id') or '')))
    osmtree = STRtree(osm) if osm else None
    # One static index over ALL sorted candidates; kept-ness is tracked as a set
    # of pair indices, so the duplicate check never rebuilds the tree.
    cand_polys = [poly for _, poly in pairs]
    cand_tree = STRtree(cand_polys) if cand_polys else None
    # Prepared geometries: intersects() is the cheap prefilter, then the full
    # intersection + area is computed only for candidates that might overlap.
    road_prep = prep(road) if not road.is_empty else None
    water_prep = prep(water) if not water.is_empty else None
    kept_records: List[Dict[str, Any]] = []
    accepted = set()  # pair indices already kept; j > i is decided later anyway
    for i, (rec, poly) in enumerate(pairs):
        source = rec.get('source')
        if osmtree is not None and _overlaps_tree(osmtree, osm, poly, overlap_area_min):
            audit['osm_excluded'].append(rec.get('id'))
            bump(source, 'osm')
            bump(source, 'rejected')
            continue
        if (road_prep is not None and road_prep.intersects(poly)
                and poly.intersection(road).area > overlap_area_min):
            audit['road_excluded'].append(rec.get('id'))
            bump(source, 'road')
            bump(source, 'rejected')
            continue
        if (water_prep is not None and water_prep.intersects(poly)
                and poly.intersection(water).area > overlap_area_min):
            audit['water_excluded'].append(rec.get('id'))
            bump(source, 'water')
            bump(source, 'rejected')
            continue
        duplicate = False
        if cand_tree is not None:
            for j in cand_tree.query(poly):
                jj = int(j)
                if jj == i or jj not in accepted:
                    # self, not yet decided (j > i), or already dropped: the
                    # overlap is resolved when the other side is processed.
                    continue
                if poly.intersection(cand_polys[jj]).area > overlap_area_min:
                    duplicate = True
                    break
        if duplicate:
            audit['duplicate_overlap_dropped'].append(rec.get('id'))
            bump(source, 'duplicate')
            bump(source, 'rejected')
            continue
        kept_records.append(rec)
        accepted.add(i)
        bump(source, 'accepted')
    return kept_records, audit


def reused_cache_files(cache_root: Any, candidate_audit: Optional[Dict[str, Any]]) -> List[str]:
    """Real on-disk cache files behind THIS map's candidate fetch.

    The DATA audit does not expose file paths, so the per-source cache dirs are
    derived the same deterministic way ``building_sources`` computes them
    (``cache_root / source / release / <expanded-bbox geo key>``) and only files
    that actually exist are reported. Sources whose status is not ``ok`` have no
    usable cache and are skipped. This deliberately replaces the old whole-tree
    ``rglob``, which listed caches belonging to *other* maps/releases and was
    wrong provenance."""
    from akadem_maps.core.building_sources import _geo_key  # same cache-key derivation as DATA
    root = Path(cache_root)
    out: List[str] = []
    for source, src_audit in (candidate_audit or {}).get('sources', {}).items():
        if not isinstance(src_audit, dict) or src_audit.get('status') != 'ok':
            continue
        release = src_audit.get('release')
        bbox = src_audit.get('bbox_cached')
        geo_q = src_audit.get('geo_q')
        if not release or not bbox or not geo_q:
            continue
        path = root / source / release / _geo_key(bbox, geo_q) / 'features.geojson'
        if path.is_file():
            out.append(str(path))
    return sorted(out)


def gate(audit: Optional[Dict[str, Any]], *, strict: bool = True) -> List[str]:
    """Non-silent gate for the prepare.py call site.

    Returns human-readable problems (possibly empty). With ``strict=True`` a
    fetch error, offline cache miss or partial failure raises EnrichmentError
    instead of letting enrichment degrade into an empty success; with
    ``strict=False`` the problems are still returned and must be recorded in
    the map audit."""
    status = (audit or {}).get('status')
    problems: List[str] = []
    if status in BAD_STATUSES:
        problems.append(f"building enrichment status {status!r}: {audit.get('sources')}")
    if strict and problems:
        raise EnrichmentError('; '.join(problems))
    return problems