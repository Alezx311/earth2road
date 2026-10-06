"""OSM landmark discovery. Scores express a deterministic heuristic, not popularity."""
import math

# Shared by PBF and Overpass selection. Name alone does not make a point a landmark.
TAGS = {'historic': {'monument', 'memorial', 'castle', 'ruins'},
        'amenity': {'place_of_worship', 'university', 'theatre'},
        'building': {'church', 'cathedral', 'stadium', 'train_station', 'university'},
        'railway': {'station'}, 'shop': {'mall'}, 'leisure': {'park', 'stadium'},
        'place': {'square'}, 'man_made': {'bridge', 'tower', 'works'},
        'tourism': {'museum', 'attraction'}}
BASE = {'monument': .85, 'memorial': .55, 'castle': .85, 'ruins': .60,
        'place_of_worship': .65, 'church': .65, 'cathedral': .85,
        'university': .65, 'theatre': .7, 'train_station': .85, 'station': .85,
        'mall': .65, 'park': .55, 'stadium': .75, 'square': .8, 'bridge': .75,
        'tower': .6, 'works': .55, 'museum': .7, 'attraction': .65}
POI_SPACING = 150.0   # metres; a landmark spawn this close to another quick-travel point is dropped


def category(tags):
    values = [tags.get(k) for k, choices in TAGS.items() if tags.get(k) in choices]
    return max(values, key=lambda v: (BASE[v], v)) if values else None


def discover(root, to_world, inside, limit=5):
    objects = {kind: {e.get('id'): e for e in root.findall(kind)} for kind in ('node', 'way', 'relation')}
    def coordinates(kind, oid, seen):
        key = (kind, oid)
        if key in seen:
            return {}
        seen.add(key)
        e = objects.get(kind, {}).get(oid)
        if e is None:
            return {}
        if kind == 'node':
            return {oid: (float(e.get('lon')), float(e.get('lat')))}
        result = {}
        members = [('node', n.get('ref')) for n in e.findall('nd')] if kind == 'way' else [(m.get('type'), m.get('ref')) for m in e.findall('member')]
        for typ, ref in members:
            result.update(coordinates(typ, ref, seen))
        return result
    found = []
    for kind, items in objects.items():
        for oid, obj in items.items():
            t = {a.get('k'): a.get('v') for a in obj.findall('tag')}
            cat = category(t)
            if not cat:
                continue
            coords = coordinates(kind, oid, set())
            if not coords:
                continue
            lon, lat = (sum(p[i] for p in coords.values())/len(coords) for i in (0, 1))
            if not inside(lon, lat):
                continue
            name = t.get('name:uk') or t.get('name') or ''
            score = min(.99, BASE[cat]+.05*bool(name)+.06*bool(t.get('wikidata'))+.04*bool(t.get('wikipedia')))
            found.append({'id': f'{kind}/{oid}', 'osm': f'{kind}/{oid}', 'kind': cat,
                          'name': name, 'lon': lon, 'lat': lat, 'position': to_world(lon, lat),
                          'importance_score': round(score, 3), 'score_source': 'heuristic:category+name+wiki',
                          'provenance': 'osm', 'wikidata': t.get('wikidata'), 'wikipedia': t.get('wikipedia'),
                          'geometry_source': 'mean of member nodes; representative point',
                          '_nodes': set(coords)})
    found.sort(key=lambda a: (-a['importance_score'], a['id']))
    unique, duplicates = [], []
    for a in found:
        duplicate = next((b for b in unique if
            (a['wikidata'] and a['wikidata'] == b['wikidata']) or
            (a['name'] and a['name'].casefold() == b['name'].casefold() and
             (a['_nodes'] & b['_nodes'] or math.dist(a['position'][::2], b['position'][::2]) < 150))), None)
        if duplicate:
            duplicates.append({'id': a['id'], 'duplicate_of': duplicate['id']})
        else:
            unique.append(a)
    selected = []
    for a in unique:
        if len(selected) < limit and a['name'] and all(math.dist(a['position'][::2], b['position'][::2]) >= 200 for b in selected):
            selected.append(a)
    for a in unique:
        a.pop('_nodes')
        a['selected'] = a in selected
    return {'candidates': unique, 'selected': selected, 'duplicates': duplicates}


def merge_spawns(records, snapped, selected):
    """Append snapped landmark spawns to quick-travel `records`; return the IDs skipped.

    A config anchor or OSM POI already stopping at the place wins: one spawn per place."""
    existing, skipped = list(records), []
    names = {a['osm']: a['name'] for a in selected}
    for p in snapped:
        p['id'] = 'landmark_' + p['osm'].replace('/', '_')
        p['title'] = names[p['osm']]
        if any(q.get('osm') == p['osm'] or math.dist(q['position'][::2], p['position'][::2]) < POI_SPACING
               for q in existing):
            skipped.append(p['id'])
        else:
            records.append(p)
    return skipped
