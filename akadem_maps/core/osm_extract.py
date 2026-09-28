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
    ways, relations, member_ways, member_nodes = set(), set(), set(), set()
    # Pass 1 (node locations): ways touching the bbox; relations with a member inside.
    for obj in osmium.FileProcessor(str(pbf)).with_locations():
        if obj.is_node():
            if obj.tags and poi(obj.tags) and inside(obj.location):
                member_nodes.add(obj.id)
        elif obj.is_way():
            if any(inside(nd.location) for nd in obj.nodes):
                ways.add(obj.id)
        elif obj.is_relation():
            if obj.tags.get('type') not in ('restriction', 'multipolygon'):
                continue
            hit = False
            for m in obj.members:
                if (m.type == 'w' and m.ref in ways):
                    hit = True
                    break
            if hit:
                relations.add(obj.id)
                for m in obj.members:
                    if m.type == 'w':
                        member_ways.add(m.ref)
                    elif m.type == 'n':
                        member_nodes.add(m.ref)
    ways |= member_ways
    print(f'pass 1: {len(ways)} ways, {len(relations)} relations ({time.monotonic()-t:.0f} s)', flush=True)
    # Pass 2: nodes of the selected ways.
    nodes = set(member_nodes)
    for obj in osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(osmium.filter.IdFilter(ways)):
        nodes.update(nd.ref for nd in obj.nodes)
    print(f'pass 2: {len(nodes)} nodes ({time.monotonic()-t:.0f} s)', flush=True)
    # Pass 3: write in file order (nodes, ways, relations).
    tmp = Path(str(out) + '.part')
    with osmium.SimpleWriter(osmium.io.File(str(tmp), 'osm'), overwrite=True) as writer:
        for kind, ids, add in ((osmium.osm.NODE, nodes, writer.add_node), (osmium.osm.WAY, ways, writer.add_way), (osmium.osm.RELATION, relations, writer.add_relation)):
            for obj in osmium.FileProcessor(str(pbf), kind).with_filter(osmium.filter.IdFilter(ids)):
                add(obj)
    tmp.replace(out)
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
