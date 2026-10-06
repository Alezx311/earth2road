#!/usr/bin/env python3
"""Cut a bbox out of a Geofabrik .osm.pbf into OSM XML, with the same selection as the
Overpass query in prepare.fetch():

    way(bbox); relation[type=restriction|multipolygon](bbox); (._; >;)

i.e. every way with a node inside the bbox, restriction/multipolygon relations with a
member inside, the member ways of those relations and all nodes of the selected ways.
Used when Overpass is too busy for a large area (config key "geofabrik").

With ``polygon`` (a corridor, see corridor.py) "inside" means inside that polygon, not its
bounding box. Tagged point features that the way-only selection would miss (fuel stations,
large shops: see POI_TAGS) are kept as standalone nodes when they lie inside the area."""
import argparse
from pathlib import Path
import time

import osmium
from akadem_maps.core.landmarks import category as landmark_category

POI_TAGS = {'amenity': {'fuel'},
            'shop': {'supermarket', 'hypermarket', 'mall', 'doityourself', 'department_store'}}


def poi(tags):
    return any(tags.get(key) in values for key, values in POI_TAGS.items())


def extract(pbf, out, bbox, polygon=None):
    w, s, e, n = bbox
    in_box = lambda loc: loc.valid() and w <= loc.lon <= e and s <= loc.lat <= n
    if polygon is None:
        inside = in_box
    else:
        from akadem_maps.core.corridor import contains
        in_polygon = contains(polygon)
        inside = lambda loc: in_box(loc) and in_polygon(loc.lon, loc.lat)
    t = time.monotonic()
    ways, relations, member_nodes, inside_nodes = set(), set(), set(), set()
    relation_members, relevant = {}, set()
    print(f'Reading local OSM package {Path(pbf).name}; first extraction may take several minutes', flush=True)
    # Locations are cached natively before the filter. Only tagged nodes need Python
    # callbacks; relation-only via nodes can be looked up in that native cache.
    processor = osmium.FileProcessor(str(pbf)).with_locations().with_filter(
        osmium.filter.EmptyTagFilter().enable_for(osmium.osm.NODE))
    # Pass 1 (node locations): ways touching the bbox; relations with a member inside.
    for obj in processor:
        if obj.is_node():
            if inside(obj.location):
                inside_nodes.add(obj.id)
                if obj.tags and (poi(obj.tags) or landmark_category(obj.tags)):
                    member_nodes.add(obj.id)
        elif obj.is_way():
            if any(inside(nd.location) for nd in obj.nodes):
                ways.add(obj.id)
        elif obj.is_relation():
            relation_members[obj.id] = [(m.type, m.ref) for m in obj.members]
            if obj.tags.get('type') in ('restriction', 'multipolygon') or landmark_category(obj.tags):
                relevant.add(obj.id)
                for member in obj.members:
                    if member.type == 'n':
                        try:
                            if inside(processor.node_location_storage.get(member.ref)):
                                inside_nodes.add(member.ref)
                        except KeyError:
                            pass  # Reference validation below reports a selected missing member.
    # Seed by original spatial hits (including via-node restrictions), then include
    # nested parent relations regardless of file order. Complete all descendants.
    changed = True
    while changed:
        hits = {rid for rid, members in relation_members.items() if rid in relevant and any(
            (kind == 'w' and ref in ways) or (kind == 'n' and ref in inside_nodes)
            or (kind == 'r' and ref in relations) for kind, ref in members)}
        changed = bool(hits - relations)
        relations |= hits
    pending = list(relations)
    while pending:
        rid = pending.pop()
        for kind, ref in relation_members.get(rid, []):
            if kind == 'w':
                ways.add(ref)
            elif kind == 'n':
                member_nodes.add(ref)
            elif kind == 'r' and ref not in relations:
                relations.add(ref)
                pending.append(ref)
    print(f'pass 1: {len(ways)} ways, {len(relations)} relations ({time.monotonic()-t:.0f} s)', flush=True)
    # Pass 2: nodes of the selected ways.
    nodes = set(member_nodes)
    for obj in osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(osmium.filter.IdFilter(ways)):
        nodes.update(nd.ref for nd in obj.nodes)
    print(f'pass 2: {len(nodes)} nodes ({time.monotonic()-t:.0f} s)', flush=True)
    # Pass 3: write in file order (nodes, ways, relations).
    tmp = Path(str(out) + '.part')
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with osmium.SimpleWriter(osmium.io.File(str(tmp), 'osm'), overwrite=True) as writer:
        for kind, ids, add in ((osmium.osm.NODE, nodes, writer.add_node), (osmium.osm.WAY, ways, writer.add_way), (osmium.osm.RELATION, relations, writer.add_relation)):
            for obj in osmium.FileProcessor(str(pbf), kind).with_filter(osmium.filter.IdFilter(ids)):
                add(obj)
    from akadem_maps.sources import validate_osm
    try:
        validate_osm(tmp, require_roads=False)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    print(f'written {out} ({time.monotonic()-t:.0f} s)', flush=True)
    return {'ways': len(ways), 'relations': len(relations), 'nodes': len(nodes)}

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('pbf'); p.add_argument('out')
    p.add_argument('--bbox', required=True, help='west,south,east,north')
    p.add_argument('--polygon', help='GeoJSON file whose "area" feature (corridor.py) limits the cut')
    a = p.parse_args()
    polygon = None
    if a.polygon:
        import json
        from shapely.geometry import shape
        document = json.loads(Path(a.polygon).read_text(encoding='utf8'))
        polygon = next(shape(f['geometry']) for f in document['features'] if f['properties'].get('role') == 'area')
    extract(a.pbf, a.out, [float(v) for v in a.bbox.split(',')], polygon)
