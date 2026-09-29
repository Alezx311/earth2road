#!/usr/bin/env python3
"""Reproducible OSM -> SUMO -> render geometry. All derived defaults are audited."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET

import numpy as np
import sumolib
from PIL import Image
from shapely.geometry import Polygon, box, LineString, Point
from shapely.ops import unary_union

from akadem_maps.core import scene
from akadem_maps import world_format as layout
from akadem_maps.context import BuildContext, contained, read_json, sha256
from akadem_maps import runtime
from akadem_maps.core import signs as road_signs
from akadem_maps.core import visual_tags
from akadem_maps.core import building_sources
from akadem_maps.core import building_enrichment
from akadem_maps.core import road_profiles
from akadem_maps.core import corridor
from akadem_maps.core import pois as poi_points
from akadem_maps.core import rural
from akadem_maps.core import road_geometry, surface_audit


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

def user_agent():
    """Overpass (overpass-api.de) answers 406 to the default Python-urllib/curl agents, and
    the OSM tile/terrain usage policies ask for an identifying one."""
    from akadem_maps import __version__
    return f'TerraDrive/{__version__} (OpenStreetMap map generator for a driving sandbox)'

def download(url, path, form=None, max_time=180):
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    if os.name == 'nt':
        # Windows curl's Schannel can fail with SEC_E_NO_CREDENTIALS in a
        # noninteractive session; Python TLS uses the installed trust store.
        import urllib.request
        import urllib.parse
        import shutil
        import time
        data = urllib.parse.urlencode({'data':form}).encode() if form else None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, data=data, headers={'User-Agent': user_agent()})
                with urllib.request.urlopen(request, timeout=max_time) as response:
                    with Path(str(path)+'.part').open('wb') as out:
                        shutil.copyfileobj(response,out)
                Path(str(path)+'.part').replace(path)
                return
            except Exception as exc:
                # HTTPError owns a response stream even when urlopen did not enter
                # the context manager. Close it before retrying another mirror.
                if hasattr(exc, 'close'):
                    exc.close()
                if attempt == 2: raise
                time.sleep(1)
    # -sS: no progress meter (it went straight to the game's terminal), errors only; they are
    # captured and become the exception message.
    args = ['curl', '-sSfL', '--retry', '2', '--max-time', str(max_time), '-A', user_agent(), url, '-o', str(path)+'.part']
    if form:
        args.extend(['--data-urlencode', 'data='+form])
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(curl_error(done.returncode, done.stderr, max_time))
    Path(str(path)+'.part').replace(path)

def curl_error(returncode, stderr, max_time):
    """A short reason for a failed curl run: 'HTTP 504', 'timed out after 240 s', …"""
    import re
    status = re.search(r'returned error: (\d{3})', stderr or '')
    if status:
        return f'HTTP {status.group(1)}'
    if returncode == 28:
        return f'timed out after {max_time} s'
    lines = [l for l in (stderr or '').splitlines() if l.startswith('curl:')]
    return lines[-1] if lines else f'curl exit {returncode}'

def fetch(cfg, context):
    BUILD, RAW = context.build, context.raw
    map_area = corridor.area(cfg, context=context)   # a corridor also fills cfg['bbox'] with its bounds
    w,s,e,n = cfg['bbox']
    # A focus config may reuse the district snapshot; netconvert and the scene clip to its bbox.
    dest = RAW / cfg.get('osm_file', f"{cfg['id']}.osm")
    geofabrik = cfg.get('geofabrik')
    area_stamp=dest.with_suffix(dest.suffix+'.area.json')
    expected_area=corridor.area_digest(cfg, context=context)
    known_area=None
    if area_stamp.exists():
        known_area=json.loads(area_stamp.read_text(encoding='utf8')).get('digest')
    elif expected_area and (BUILD/'sources.json').exists():
        previous=json.loads((BUILD/'sources.json').read_text(encoding='utf8')).get('config',{})
        if previous.get('corridor') and previous.get('geofabrik'):
            known_area=corridor.spec_digest(previous['corridor'],previous['geofabrik']['md5'])
    stale=expected_area is not None and known_area!=expected_area
    if (not dest.exists() or stale) and geofabrik:
        # Large areas: cut from a dated Geofabrik extract (Overpass times out on them).
        pbf = RAW / 'geofabrik' / geofabrik['url'].rsplit('/', 1)[1]
        if not pbf.exists():
            context.download(geofabrik['url'], pbf, max_time=3600)
        digest = hashlib.md5(pbf.read_bytes()).hexdigest()
        if digest != geofabrik['md5']:
            raise RuntimeError(f'{pbf.name}: md5 {digest} != {geofabrik["md5"]}')
        from akadem_maps.core import osm_extract
        osm_extract.extract(pbf, dest, cfg['bbox'], map_area if corridor.shaped(cfg) else None)
        if expected_area:
            write_json(area_stamp,{'digest':expected_area})
    overpass_used = cfg.get('overpass')
    if not dest.exists():
        timeout = int(cfg.get('overpass_timeout', 120))
        # maxsize is the RAM the server reserves for the query; a busy server turns large
        # reservations away (504/429) while it still admits small ones. Small areas can ask
        # for less (tools/generate_map.py: 256 MiB covers a dense 5 km city square).
        maxsize = int(cfg.get('overpass_maxsize', 1073741824))
        q = f'[out:xml][timeout:{timeout}][maxsize:{maxsize}];(way({s},{w},{n},{e});relation["type"="restriction"]({s},{w},{n},{e});relation["type"="multipolygon"]({s},{w},{n},{e}););(._;>;);out body;'
        # Public Overpass servers are often overloaded (504/429): optional mirrors are tried in
        # order. The OSM data is the same; the manifest records which server answered.
        urls = [cfg['overpass']] + [u for u in cfg.get('overpass_mirrors', []) if u != cfg['overpass']]
        failures = []
        for i, url in enumerate(urls):
            # Overpass answers the same query as GET ?data=…: that link can be opened in a
            # browser to check a failing server by hand.
            context.notify('download', source='overpass', url=url,
                           query_url=url+'?'+urllib.parse.urlencode({'data': q}))
            try:
                context.download(url, dest, q, max_time=timeout+120)
                overpass_used = url
                break
            except RuntimeError as exc:
                failures.append(f'{urllib.parse.urlsplit(url).hostname}: {exc.__cause__ or exc}')
                if i == len(urls) - 1:
                    raise RuntimeError(f'Could not download OpenStreetMap data from Overpass ({"; ".join(failures)}). '
                                       'The public Overpass servers are often overloaded (HTTP 504/429); '
                                       'try again in a few minutes.') from exc
                context.notify('warning', message=f'{failures[-1]}; trying {urllib.parse.urlsplit(urls[i+1]).hostname}')
    context.record_input(dest)
    root = ET.parse(dest).getroot()
    if root.tag != 'osm':
        raise ValueError('Input is not an OSM XML document')
    if root.find('remark') is not None:
        raise RuntimeError('Overpass returned incomplete data: '+root.findtext('remark'))
    if not any(drivable({t.get('k'): t.get('v') for t in w.findall('tag')}) for w in root.findall('way')):
        raise ValueError('OSM input has no suitable passenger roads')
    if root.find('remark') is not None:
        raise RuntimeError('Overpass returned incomplete data: '+root.findtext('remark'))
    manifest = {'osm_sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'download_checked_at': datetime.now(timezone.utc).isoformat(), 'config': cfg, 'source': cfg['geofabrik']['url'] if cfg.get('geofabrik') else overpass_used, 'bbox': cfg['bbox'], 'osm_timestamp': (root.find('meta').attrib if root.find('meta') is not None else {}), 'license': 'ODbL-1.0; © OpenStreetMap contributors'}
    write_json(BUILD/'sources.json', manifest)
    # Tracked snapshot is the default district; other maps keep theirs under data/build/<id>/.
    return root

class Terrain:
    def __init__(self, cfg, context):
        self.context = context
        self.zoom = cfg['terrain_zoom']
        self.images = {}
        self.used = set()
    def sample(self, lon, lat):
        count = 2**self.zoom
        x = (lon+180)/360*count
        y = (1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*count
        tx,ty = int(x),int(y)
        key = (tx,ty)
        if key not in self.images:
            path = self.context.raw / f'terrain/{self.zoom}/{tx}/{ty}.png'
            if not path.exists():
                self.context.download(f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{self.zoom}/{tx}/{ty}.png', path)
            self.images[key] = Image.open(path).convert('RGB')
            self.used.add(path.relative_to(self.context.raw).as_posix())
            self.context.record_input(path)
        # Bilinear within tile; DEM resolution is far coarser than road features.
        u,v = (x-tx)*255,(y-ty)*255
        ix,iy = int(u),int(v)
        def h(a,b):
            r,g,bl = self.images[key].getpixel((min(a,255),min(b,255)))
            return r*256+g+bl/256-32768
        return (h(ix,iy)*(1-u+ix)+h(ix+1,iy)*(u-ix))*(1-v+iy)+(h(ix,iy+1)*(1-u+ix)+h(ix+1,iy+1)*(u-ix))*(v-iy)

def sumolib_typemap():
    import sumo_data
    return Path(list(sumo_data.__path__)[0])/'data/typemap/osmNetconvert.typ.xml'

def number(raw, default):
    try:
        return float(str(raw).split(';')[0].replace(' m','').replace(',','.'))
    except (ValueError,TypeError):
        return default

mesh_triangles = scene.triangles

DRIVABLE = ('motorway','trunk','primary','secondary','tertiary','residential','unclassified','service','living_street')

def drivable(t):
    h = t.get('highway','')
    return h in DRIVABLE or h.endswith('_link')

BRIDGE_CLEARANCE = {'road': 6.5, 'rail': 7.0}   # assumed deck height above what passes below
TUNNEL_DEPTH = 3.5                               # assumed metres per negative OSM layer
PASSAGE_CLEARANCE = 4.2                          # assumed arch height of a building passage
PASSAGE_HALF_WIDTH = 2.6
SPAWN_MIN_EDGE = 120.0
SPAWN_OFFSET = 15.0
YARD_TRIP_SHARE = 0.3                             # synthetic, not measured
MAX_RAMP_GRADE = {'service': 0.12, 'default': 0.06}
PAIR_MAX_DISTANCE = 35.0   # m between the centrelines of the two carriageways of one named road
PAIR_FULL_DISTANCE = 20.0  # m; the coupling fades out between this and PAIR_MAX_DISTANCE
PAIR_FADE = 0.85           # share of the closing correction passed on per node along joining roads
PAIR_FADE_STEPS = 30
PAIR_CLOSE_ROUNDS = 4
PAIR_MIN_OPPOSITION = 0.8  # -cos of the angle between them: 0.8 = within ~37 deg of antiparallel
OVERLAP_MIN = 0.5          # m the two drawn carriageways must actually overlap (merely adjacent roads stay apart)
OVERLAP_TAPER = 60.0       # m along the road graph over which a follower's correction tapers to 0
OVERLAP_MAX_STEP = 2.0     # m; a larger difference is grade separation, never flattened
OVERLAP_MIN_PARALLEL = 0.8 # |cos| of the angle between the two ways
OVERLAP_LANE_WIDTH = 3.25  # m per lane when estimating how wide an OSM way is drawn
EMBANKMENT_MAX = 3.0       # m above the DEM: a bridge-tagged road this low is an earth ramp, not a span
UNDERPASS_REACH = 10.0     # m around a deck point searched for a road passing beneath
UNDERPASS_DROP = 2.0       # m lower than the deck = passing beneath, so the deck stays a span

def layer_of(t):
    try:
        return int(float(t.get('layer', '0')))
    except ValueError:
        return 0

def structure_level(t):
    """+n for bridges, -n for tunnels/underground aisles; building passages stay at grade."""
    layer = layer_of(t)
    if t.get('bridge', 'no') not in ('no',):
        return max(1, layer)
    if t.get('tunnel', 'no') not in ('no', 'building_passage'):
        return min(-1, layer)
    return 0

def _segments_cross(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    if d1*d2 < 0 and d3*d4 < 0:
        t = d1/(d1-d2)
        u = d3/(d3-d4)
        return t, u
    return None

def carriageway_partners(road_ways, xy):
    """Node -> (a, b, t, weight) on the opposite carriageway of the same named road.

    OSM draws a divided road as two one-way ways. Each samples the coarse DEM on its own
    line, so without coupling the two directions end up at different heights with a step
    down into the median. Pairs: one-way, same name, not a link, within PAIR_MAX_DISTANCE
    and nearly antiparallel; `t` interpolates between partner nodes a and b, and `weight` fades
    from 1 to 0 as the carriageways part, so the coupling ends without a kink."""
    from shapely import STRtree
    lines, meta = [], []
    for refs, t in road_ways:
        oneway = t.get('oneway') in ('yes', '1', '-1', 'true')
        if not oneway or not t.get('name') or t.get('highway', '').endswith('_link') or t.get('highway') == 'service':
            continue
        order = refs[::-1] if t.get('oneway') == '-1' else refs
        for a, b in zip(order, order[1:]):
            pa, pb = xy(a), xy(b)
            if pa != pb:
                lines.append(LineString([pa, pb]))
                meta.append((t['name'], t['__id'], a, b, pa, pb))
    if not lines:
        return {}
    tree = STRtree(lines)
    by_way = {}
    for m in meta:
        by_way.setdefault(m[1], []).append(m)
    partners = {}
    for wid, segs in by_way.items():
        name = segs[0][0]
        for k, (_, _, a, b, pa, pb) in enumerate(segs):
            nodes_here = [a]
            if k == len(segs)-1:
                nodes_here.append(b)
            dx, dy = pb[0]-pa[0], pb[1]-pa[1]
            length = math.hypot(dx, dy)
            ux, uy = dx/length, dy/length
            for nid in nodes_here:
                p = xy(nid)
                best = None
                for i in tree.query(Point(p).buffer(PAIR_MAX_DISTANCE)):
                    oname, owid, oa, ob, qa, qb = meta[i]
                    if owid == wid or oname != name or nid in (oa, ob):
                        continue
                    ex, ey = qb[0]-qa[0], qb[1]-qa[1]
                    olen = math.hypot(ex, ey)
                    if (ux*ex+uy*ey)/olen > -PAIR_MIN_OPPOSITION:
                        continue
                    s = max(0.0, min(1.0, ((p[0]-qa[0])*ex+(p[1]-qa[1])*ey)/(olen*olen)))
                    d = math.dist(p, (qa[0]+ex*s, qa[1]+ey*s))
                    if d <= PAIR_MAX_DISTANCE and (best is None or d < best[0]):
                        best = (d, oa, ob, s)
                if best:
                    fade = (PAIR_MAX_DISTANCE-best[0])/(PAIR_MAX_DISTANCE-PAIR_FULL_DISTANCE)
                    partners[nid] = (*best[1:], max(0.0, min(1.0, fade)))
    return partners

HIGHWAY_RANK = {'motorway': 0, 'trunk': 1, 'primary': 2, 'secondary': 3, 'tertiary': 4,
                'unclassified': 5, 'residential': 6, 'living_street': 7, 'service': 8}

def _way_width(t):
    try:
        lanes = max(1, int(float(t.get('lanes', ''))))
    except ValueError:
        lanes = 1 if t.get('oneway') in ('yes', '1', '-1', 'true') else 2
    return lanes*OVERLAP_LANE_WIDTH

def _rank(t):
    return HIGHWAY_RANK.get(t.get('highway', '').removesuffix('_link'), 9) + 0.5*t.get('highway', '').endswith('_link')

def overlap_targets(road_ways, xy):
    """Node -> (a, b, t, weight, major) on an at-grade way at least as important whose surface it overlaps.

    A slip road or a side street leaving a divided road at a shallow angle runs for tens of
    metres inside the main carriageway's footprint. Each way samples its own DEM profile, so
    the two surfaces there differ by decimetres (a car straddling them is thrown over).
    Only nodes lying inside the footprint of a strictly more important way are returned;
    they follow it (equal ranks are left alone: divided roads are coupled by
    carriageway_partners). At-grade ways, nearly parallel, never across a shared node."""
    from shapely import STRtree
    lines, meta = [], []
    for refs, t in road_ways:
        if structure_level(t) != 0:
            continue
        for a, b in zip(refs, refs[1:]):
            pa, pb = xy(a), xy(b)
            if pa != pb:
                lines.append(LineString([pa, pb]))
                meta.append((t['__id'], _rank(t), _way_width(t), a, b, pa, pb))
    if not lines:
        return {}
    tree = STRtree(lines)
    targets = {}
    way_nodes = {t['__id']: set(refs) for refs, t in road_ways}
    for refs, t in road_ways:
        if structure_level(t) != 0:
            continue
        wid, rank, width = t['__id'], _rank(t), _way_width(t)
        for k, nid in enumerate(refs):
            p = xy(nid)
            # A diverging way curves away: test both adjacent segments, keep the better aligned.
            dirs = []
            for m in (refs[k-1] if k > 0 else None, refs[k+1] if k+1 < len(refs) else None):
                if m is not None:
                    q = xy(m)
                    length = math.hypot(q[0]-p[0], q[1]-p[1])
                    if length > 0:
                        dirs.append(((q[0]-p[0])/length, (q[1]-p[1])/length))
            if not dirs:
                continue
            best = None
            for i in tree.query(Point(p).buffer(width/2+8*OVERLAP_LANE_WIDTH)):
                owid, orank, owidth, oa, ob, qa, qb = meta[i]
                if owid == wid or orank >= rank or nid in (oa, ob):
                    continue
                if not way_nodes[wid] & way_nodes[owid]:
                    continue  # XY overlap is not evidence of a road connection.
                ex, ey = qb[0]-qa[0], qb[1]-qa[1]
                olen = math.hypot(ex, ey)
                if max(abs(ux*ex+uy*ey) for ux, uy in dirs)/olen < OVERLAP_MIN_PARALLEL:
                    continue
                s = max(0.0, min(1.0, ((p[0]-qa[0])*ex+(p[1]-qa[1])*ey)/(olen*olen)))
                d = math.dist(p, (qa[0]+ex*s, qa[1]+ey*s))
                if d > (width+owidth)/2-OVERLAP_MIN:
                    continue
                if best is None or (orank, d) < (best[0], best[5]):
                    best = (orank, oa, ob, s, True, d)
            if best:
                targets[nid] = (best[1], best[2], best[3], 1.0, True)
    return targets

def road_node_heights(root, nodes, tags, sample, iterations=40, include_tracks=False):
    """One height per drivable OSM node. Every lane, junction and car takes its height
    from this profile (see RoadHeights), so all lanes of a road agree at each station.

    1. Ground: DEM (~24 m/pixel) smoothed by a distance-weighted Laplacian along the road
       graph; shared nodes stay identical for all ways.
    2. Structures: bridge decks are linear between their ends and raised to an assumed
       clearance above every road/railway crossing beneath; tunnels sink TUNNEL_DEPTH per
       layer. Offsets then ramp out along connected roads at a limited grade, so approach
       embankments and garage ramps have no steps. All structure heights are assumptions."""
    lon0 = min(lon for lon, _ in nodes.values())
    xy = lambda nid: ((nodes[nid][0]-lon0)*71000, nodes[nid][1]*111200)
    raw, neighbours, road_ways, rail_ways = {}, {}, [], []
    for w in root.findall('way'):
        t = {**tags(w), '__id': w.attrib['id']}
        refs = [nd.attrib['ref'] for nd in w.findall('nd') if nd.attrib['ref'] in nodes]
        if len(refs) < 2:
            continue
        if t.get('railway') in ('rail', 'light_rail', 'tram', 'subway', 'narrow_gauge'):
            rail_ways.append((refs, t))
        if not (drivable(t) or (include_tracks and rural.accessible_track(t))):
            continue
        road_ways.append((refs, t))
        grade = MAX_RAMP_GRADE['service'] if t.get('highway') == 'service' else MAX_RAMP_GRADE['default']
        for a, b in zip(refs, refs[1:]):
            d = max(1.0, math.dist(xy(a), xy(b)))
            neighbours.setdefault(a, {})[b] = (d, grade)
            neighbours.setdefault(b, {})[a] = (d, grade)
    for nid in neighbours:
        raw[nid] = sample(*nodes[nid])
    # The two carriageways of a divided road share one DEM anchor and pull toward each other
    # while smoothing, so the road has no step between directions.
    partners = carriageway_partners(road_ways, xy)
    across = lambda field, p: field.get(p[0], 0.0)+(field.get(p[1], 0.0)-field.get(p[0], 0.0))*p[2]
    pull = lambda n: 0.5*partners[n][3] if n in partners else 0.0
    anchor = {n: z+pull(n)*(across(raw, partners[n])-z) if n in partners else z for n, z in raw.items()}
    ground = dict(anchor)
    for _ in range(iterations):
        nxt = {}
        for nid, near in neighbours.items():
            total = sum(1/d for d, _ in near.values())
            avg = sum(ground[m]/d for m, (d, _) in near.items())/total
            if nid in partners:
                avg += pull(nid)*(across(ground, partners[nid])-avg)
            # Mostly neighbour average, lightly anchored to the DEM so long roads keep terrain shape.
            nxt[nid] = 0.15*anchor[nid] + 0.85*avg
        ground = nxt

    def ground_on(refs, i, u):
        a, b = refs[i], refs[i+1]
        za = ground.get(a, sample(*nodes[a]))
        zb = ground.get(b, sample(*nodes[b]))
        return za + (zb-za)*u

    offset = {}
    report = Counter()
    # Segments of every road and railway in one STRtree: bridge decks query only nearby ones.
    from shapely import STRtree
    seg_lines, seg_meta = [], []
    for kind, others in (('road', road_ways), ('rail', rail_ways)):
        for orefs, ot in others:
            opts = [xy(n) for n in orefs]
            oset = set(orefs)
            for j in range(len(opts)-1):
                seg_lines.append(LineString([opts[j], opts[j+1]]))
                seg_meta.append((kind, orefs, oset, ot, j, opts[j], opts[j+1]))
    seg_tree = STRtree(seg_lines) if seg_lines else None
    for refs, t in road_ways:
        level = structure_level(t)
        if level == 0:
            continue
        if level < 0:
            report['tunnel_ways'] += 1
            for nid in refs:
                offset[nid] = min(offset.get(nid, 0.0), level*TUNNEL_DEPTH)
            continue
        report['bridge_ways'] += 1
        pts = [xy(n) for n in refs]
        along = [0.0]
        for a, b in zip(pts, pts[1:]):
            along.append(along[-1]+math.dist(a, b))
        span = along[-1] or 1.0
        z0, z1 = ground[refs[0]], ground[refs[-1]]
        deck = [z0+(z1-z0)*s/span for s in along]
        grade = MAX_RAMP_GRADE['default']
        own = set(refs)
        for i in range(len(pts)-1):
            if seg_tree is None:
                break
            for k in seg_tree.query(LineString([pts[i], pts[i+1]])):
                kind, orefs, oset, ot, j, oa, ob = seg_meta[k]
                if ot is t or layer_of(ot) >= level or oset & own:
                    continue
                hit = _segments_cross(pts[i], pts[i+1], oa, ob)
                if not hit:
                    continue
                report['bridge_crossings_'+kind] += 1
                below = ground_on(orefs, j, hit[1]) + structure_level(ot)*TUNNEL_DEPTH*(structure_level(ot) < 0)
                need = below + BRIDGE_CLEARANCE[kind]
                at = along[i] + (along[i+1]-along[i])*hit[0]
                deck = [max(z, need-grade*abs(s-at)) for z, s in zip(deck, along)]
        for nid, z in zip(refs, deck):
            offset[nid] = max(offset.get(nid, 0.0), z-ground[nid])

    # Both carriageways of a divided road take the higher deck, before the ramps spread it.
    decks = dict(offset)
    for nid, p in partners.items():
        other = across(decks, p)*p[3]
        if other > 0 and other > offset.get(nid, 0.0) and offset.get(nid, 0.0) >= 0:
            offset[nid] = other
            report['paired_deck_raised'] += 1
    report['paired_nodes'] = len(partners)

    # Grade-limited ramps: relax offsets outward along the road graph (Dijkstra-like).
    import heapq
    for sign in (1, -1):
        best = {n: sign*o for n, o in offset.items() if sign*o > 0}
        heap = [(-v, n) for n, v in best.items()]
        heapq.heapify(heap)
        while heap:
            v, n = heapq.heappop(heap)
            v = -v
            if v < best.get(n, 0) - 1e-9:
                continue
            for m, (d, grade) in neighbours.get(n, {}).items():
                nv = v - d*grade
                if nv > best.get(m, 0) + 1e-6:
                    best[m] = nv
                    heapq.heappush(heap, (-nv, m))
        for n, v in best.items():
            if sign > 0:
                offset[n] = max(offset.get(n, 0.0), v)
            elif offset.get(n, 0.0) <= 0:
                offset[n] = min(offset.get(n, 0.0), -v)

    height = {n: ground[n]+offset.get(n, 0.0) for n in ground}
    # Coupled smoothing leaves the directions a few decimetres apart where their ramps or DEM
    # samples differ. Close it: paired nodes meet halfway, and the correction fades out along
    # the roads joining them so a side street does not get a kink.
    closable = [n for n, p in partners.items()
                if offset.get(n, 0.0) >= 0 and min(offset.get(p[0], 0.0), offset.get(p[1], 0.0)) >= 0]
    for rnd in range(PAIR_CLOSE_ROUNDS):
        fixed = {n: 0.5*partners[n][3]*(across(height, partners[n])-height[n]) for n in closable}
        if rnd == 0:
            report['paired_gap_before_max_m'] = round(2*max((abs(c) for c in fixed.values()), default=0.0), 2)
        correction = dict(fixed)
        for _ in range(PAIR_FADE_STEPS):
            nxt = dict(fixed)
            for n, near in neighbours.items():
                if n not in fixed:
                    total = sum(1/d for d, _ in near.values())
                    nxt[n] = PAIR_FADE*sum(correction.get(m, 0.0)/d for m, (d, _) in near.items())/total
            correction = nxt
        for n, c in correction.items():
            height[n] += c
    # Overlapping carriageways (slip roads leaving at a shallow angle) share one surface: the
    # less important way follows. The main way's nodes stay fixed and the correction fades
    # along the follower's graph, as for the pairs above.
    overlaps = overlap_targets(road_ways, xy)
    frozen = {m for p in overlaps.values() if p[4] for m in p[:2]}
    movable = {n: p for n, p in overlaps.items()
               if n not in frozen and abs(offset.get(n, 0.0)) < 0.05
               and abs(across(height, p)-height[n]) < OVERLAP_MAX_STEP}
    report['overlap_nodes'] = len(movable)
    report['overlap_gap_before_max_m'] = round(max((abs(across(height, p)-height[n]) for n, p in movable.items()), default=0.0), 2)
    fixed = {n: p[3]*(across(height, p)-height[n]) for n, p in movable.items()}
    # Taper by distance along the graph, not per node: closely spaced nodes would otherwise
    # drop the whole correction within a few metres and leave a kink. Each node takes the
    # strongest tapered correction reaching it (per sign), not merely the nearest one.
    taper = {}
    for sign in (1, -1):
        best = {}
        heap = []
        for n, c in fixed.items():
            if sign*c > 0:
                best[n] = (sign*c, 0.0, sign*c)
                heap.append((-sign*c, n))
        heapq.heapify(heap)
        while heap:
            v, n = heapq.heappop(heap)
            if -v < best[n][0] - 1e-9:
                continue
            _, dist, c = best[n]
            for m, (d, _) in neighbours.get(n, {}).items():
                nd = dist + d
                nv = c*(1-nd/OVERLAP_TAPER)
                if m in fixed or m in frozen or nv <= 0 or nv <= best.get(m, (0.0,))[0]:
                    continue
                best[m] = (nv, nd, c)
                heapq.heappush(heap, (-nv, m))
        for n, (v, _, _) in best.items():
            if n not in fixed:
                taper[n] = taper.get(n, 0.0) + sign*v
    for n, c in {**taper, **fixed}.items():
        height[n] += c
    report['overlap_gap_after_max_m'] = round(max((abs(across(height, p)-height[n]) for n, p in movable.items()), default=0.0), 2)
    report.update({'road_nodes': len(height), 'raised_nodes': sum(o > 0.05 for o in offset.values()),
                   'lowered_nodes': sum(o < -0.05 for o in offset.values()),
                   'max_ground_smoothing_shift_m': round(max((abs(ground[n]-raw[n]) for n in ground), default=0), 2)})
    return height, {w: refs for refs, t in road_ways for w in [t['__id']]}, dict(report)

class RoadHeights:
    """Lane heights from the OSM node profile.

    Normal lanes project onto the OSM ways they came from (lane param origId), so every
    lane of an edge has the same height at the same station, independent of how
    netconvert averages joined junction clusters. Internal lanes interpolate linearly
    from the end of their incoming lane to the start of their outgoing lane; junction
    surfaces and anything left blend the adjoining lane ends by inverse distance."""
    def __init__(self, net, nodes, heights, way_refs):
        self.net = net
        self.poly = {}
        for wid, refs in way_refs.items():
            pts = [(*net.convertLonLat2XY(*nodes[n]), heights[n]) for n in refs if n in heights]
            if len(pts) >= 2:
                self.poly[wid] = pts
        self.z = {}
        self.unmatched = 0
        lanes = [l for e in net.getEdges(withInternal=True) for l in e.getLanes()]
        self.shapes = {lane.getID(): lane.getShape() for lane in lanes}
        for lane in lanes:
            if lane.getEdge().getFunction() == '':
                wids = lane.getParam('origId', '').split()
                zs = [self.project(wids, x, y) for x, y in lane.getShape()]
                if any(z is None for z in zs):
                    self.unmatched += 1
                    continue
                self.z[lane.getID()] = zs
        self.refresh_junctions()

    def shape(self, lane):
        return self.shapes[lane.getID()]

    def refresh_junctions(self):
        net = self.net
        lanes = [l for e in net.getEdges(withInternal=True) for l in e.getLanes()]
        for lane in lanes:
            if lane.getEdge().getFunction() != '' or lane.getID() not in self.z:
                continue
            for conn in lane.getOutgoing():
                chain, via = [], conn.getViaLaneID()
                while via and via not in chain:
                    chain.append(via)
                    outs = net.getLane(via).getOutgoing()
                    via = outs[0].getViaLaneID() if outs else ''
                to = conn.getToLane().getID()
                if not chain or to not in self.z:
                    continue
                z0, z1 = self.z[lane.getID()][-1], self.z[to][0]
                total = sum(net.getLane(v).getLength() for v in chain) or 1.0
                done = 0.0
                for v in chain:
                    shape = self.shape(net.getLane(v))
                    along = [0.0]
                    for a, b in zip(shape, shape[1:]):
                        along.append(along[-1]+math.dist(a, b))
                    scale = net.getLane(v).getLength()/(along[-1] or 1.0)
                    self.z[v] = [z0+(z1-z0)*(done+s*scale)/total for s in along]
                    done += net.getLane(v).getLength()
        self.internal_by_node = {}
        for edge in net.getEdges(withInternal=True):
            if edge.getFunction() == 'internal':
                node_id = edge.getID()[1:].rsplit('_', 1)[0]
                self.internal_by_node.setdefault(node_id, []).extend(l.getID() for l in edge.getLanes())
        self.node_z = {node.getID(): self._node_blend(node) for node in net.getNodes()}
        for lane in lanes:
            if lane.getID() not in self.z:
                z_at = self.node_z[(lane.getEdge().getToNode() if lane.getEdge().getFunction() == 'internal' else lane.getEdge().getFromNode()).getID()]
                self.z[lane.getID()] = [z_at(x, y) for x, y in self.shape(lane)]

    def project(self, wids, x, y):
        best = None
        for wid in wids:
            pts = self.poly.get(wid)
            for segment, ((ax, ay, az), (bx, by, bz)) in enumerate(zip(pts or [], (pts or [])[1:])):
                dx, dy = bx-ax, by-ay
                length = dx*dx+dy*dy
                t = 0.0 if length == 0 else max(0.0, min(1.0, ((x-ax)*dx+(y-ay)*dy)/length))
                d = (ax+dx*t-x)**2+(ay+dy*t-y)**2
                if best is None or d < best[0]:
                    best = (d, road_profiles.profile_z(pts, segment, t))
        return None if best is None else best[1]

    def _node_blend(self, node):
        """Junction surface height: inverse-distance blend (power 3, so it reproduces each
        sample almost exactly) of every adjoining lane end's cross-section and of the
        internal lanes. Lane strips are flat across, so sampling their edges too makes the
        junction meet each strip without a step."""
        samples = []
        def section(lane, index):
            shape, z = self.shape(lane), self.z[lane.getID()][index]
            (ax, ay), (bx, by) = (shape[-2], shape[-1]) if index == -1 else (shape[0], shape[1])
            length = math.hypot(bx-ax, by-ay) or 1.0
            nx, ny = -(by-ay)/length, (bx-ax)/length
            x, y = shape[index]
            half = lane.getWidth()/2
            return [(x+nx*t*half, y+ny*t*half, z) for t in (-1.0, -0.5, 0.0, 0.5, 1.0)]
        for edge in node.getIncoming():
            for lane in edge.getLanes():
                if lane.getID() in self.z and edge.getFunction() == '':
                    samples += section(lane, -1)
        for edge in node.getOutgoing():
            for lane in edge.getLanes():
                if lane.getID() in self.z and edge.getFunction() == '':
                    samples += section(lane, 0)
        for lane_id in self.internal_by_node.get(node.getID(), []):
            if lane_id in self.z:
                samples += [(x, y, z) for (x, y), z in zip(self.shape(self.net.getLane(lane_id)), self.z[lane_id])]
        fallback = sum(z for *_, z in samples)/len(samples) if samples else 0.0
        if samples:
            arr = np.array(samples)
        def z_at(x, y):
            if not samples:
                return fallback
            d2 = np.maximum((arr[:, 0]-x)**2+(arr[:, 1]-y)**2, 1e-6)
            w = d2**-1.5
            return float((w*arr[:, 2]).sum()/w.sum())
        return z_at

    def points(self, lane, point):
        return [point(x, y, z) for (x, y), z in zip(self.shape(lane), self.z[lane.getID()])]

    def at_offset(self, lane, offset):
        shape, zs = self.shape(lane), self.z[lane.getID()]
        for (a, b), za, zb in zip(zip(shape, shape[1:]), zs, zs[1:]):
            d = math.dist(a, b)
            if offset <= d and d > 0:
                return za+(zb-za)*offset/d
            offset -= d
        return zs[-1]

TILE = 500.0   # metres; Godot streams the world tile by tile

MIN_TRIANGLE_AREA = 1e-4     # m2; below this a triangle is a sliver, not a surface


def drop_slivers(world):
    """Remove zero-area triangles before tiling.

    Triangulation and the draping grid leave slivers with repeated or collinear corners.
    They draw nothing, carry no collision, and a chunk that happens to hold only slivers
    makes Jolt refuse the whole shape ("Need triangles to create a mesh shape"). Returns
    how many were dropped, for the audit."""
    def area(t):
        (x1, _, z1), (x2, _, z2), (x3, _, z3) = t
        return abs((x2 - x1) * (z3 - z1) - (x3 - x1) * (z2 - z1)) / 2

    def keep(tris):
        return [t for t in tris if area(t) >= MIN_TRIANGLE_AREA]

    dropped = 0
    for field in ('ground', 'parking'):
        before = len(world[field])
        world[field] = keep(world[field])
        dropped += before - len(world[field])
    for field in ('greens', 'junctions', 'walkingareas'):
        out = []
        for item in world[field]:
            before = len(item['triangles'])
            item = {**item, 'triangles': keep(item['triangles'])}
            dropped += before - len(item['triangles'])
            if item['triangles'] or item.get('rings'):
                out.append(item)
        world[field] = out
    return dropped


def write_world(world, folder):
    """game/data/<id>/index.json (everything but bulk geometry) + tiles/<tx>_<tz>.json.
    Polylines, buildings and junctions go whole to the tile of their first point (no seams
    inside one strip); triangle soups (ground, greens, parking) are split per triangle."""
    folder = Path(folder)
    import shutil
    if (folder/'tiles').exists():
        shutil.rmtree(folder/'tiles')
    dropped = drop_slivers(world)
    tiles = {}
    def key(p):
        return f'{math.floor(p[0]/TILE)}_{math.floor(p[2]/TILE)}'
    def put(name, field, item):
        tiles.setdefault(name, {k: [] for k in layout.TILED})[field].append(item)
    def centroid(tri):
        return [sum(p[i] for p in tri)/3 for i in range(3)]
    for field in ('road_strips', 'markings', 'sidewalks', 'paths', 'buildings', 'fences'):
        for item in world.get(field, []):
            put(key(item['points'][0]), field, item)
    for item in world['junctions']:
        if item['triangles']:                 # slivers already dropped by drop_slivers
            put(key(centroid(item['triangles'][0])), 'junctions', item)
    for item in world['walkingareas']:
        if not item['rings'] and not item['triangles']:
            continue
        first = item['rings'][0][0] if item['rings'] and item['rings'][0] else centroid(item['triangles'][0])
        put(key(first), 'walkingareas', item)
    for field in ('ground', 'parking'):
        for tri in world[field]:
            put(key(centroid(tri)), field, tri)
    for area in world['greens']:
        parts = {}
        for tri in area['triangles']:
            parts.setdefault(key(centroid(tri)), []).append(tri)
        for name, tris in parts.items():
            put(name, 'greens', {**{k: v for k, v in area.items() if k != 'triangles'}, 'triangles': tris})
    for p in world['trees']:
        put(key(p), 'trees', p)
    for item in world['signs']:
        put(key(item['position']), 'signs', item)
    world['sliver_triangles_dropped'] = dropped
    index = {k: v for k, v in world.items() if k not in layout.TILED}
    index['tile_size'] = TILE
    index['tiles'] = {name: [int(v) for v in name.split('_')] for name in sorted(tiles)}
    for name, tile in tiles.items():
        write_json(folder/'tiles'/f'{name}.json', tile)
    write_json(folder/'index.json', index)
    return len(tiles)

def build(cfg, root, context):
    BUILD = context.build
    BUILD.mkdir(parents=True, exist_ok=True)
    map_clip_report = rural.clip_roads(root,corridor.area(cfg, context=context)) if 'boundary' in cfg else None
    nodes = {n.attrib['id']: (float(n.attrib['lon']),float(n.attrib['lat'])) for n in root.findall('node')}
    tags = lambda e: {t.attrib['k']:t.attrib['v'] for t in e.findall('tag')}
    ways = {w.attrib['id']: w for w in root.findall('way')}
    is_rural = rural.enabled(cfg)
    if is_rural:
        rural.prepare_tracks(root)
    overrides = json.loads(context.resource('corrections.json').read_text(encoding='utf-8'))['ways']
    for wid, updates in overrides.items():
        if wid not in ways:
            raise ValueError(f'Correction references missing OSM way {wid}')
        way = ways[wid]
        for key,value in updates.items():
            for tag in list(way.findall('tag')):
                if tag.attrib['k'] == key:
                    way.remove(tag)
            if value is not None:
                ET.SubElement(way,'tag', k=key,v=str(value))
    # Underground garage aisles are out of scope for v1; keep them out of the drivable network.
    underground_excluded = 0
    for w in ways.values():
        t = tags(w)
        if t.get('highway') == 'service' and structure_level(t) < 0:
            for tag in list(w.findall('tag')):
                if tag.attrib['k'] == 'highway':
                    w.remove(tag)
            underground_excluded += 1
    context.progress('terrain', 0.2)
    terrain = Terrain(cfg, context)
    base = terrain.sample(*cfg['center'])
    node_heights, way_refs, elevation_report = road_node_heights(root, nodes, tags, lambda lon,lat: terrain.sample(lon,lat)-base, include_tracks=is_rural)
    map_area = corridor.area(cfg, context=context)
    processed = BUILD/'corrected.osm'
    ET.ElementTree(root).write(processed, encoding='utf-8', xml_declaration=True)
    type_file = BUILD/'road_types.typ.xml'
    width_defaults = road_profiles.write_types(sumolib_typemap(), context.resource('osm_types.typ.xml'), type_file)
    if is_rural:
        rural.configure_types(type_file)
        width_defaults['rural'] = {'residential_width_m':2.75, 'track_width_m':2.5, 'shared_lanes_1_carriageway_m':5.0, 'untagged_street_speed_kmh':30, 'untagged_track_speed_kmh':20, 'provenance':'assumed'}
    context.progress('network', 0.3)
    cmd = [str(runtime.sumo_binary('netconvert')), '--osm-files', str(processed), '--output-file', str(BUILD/'network.net.xml'), '--keep-edges.by-vclass', 'passenger', '--keep-edges.in-geo-boundary', ','.join(map(str,cfg['bbox'])), '--geometry.remove', '--junctions.join', '--tls.guess-signals', '--tls.join', '--ramps.guess', '--no-turnarounds.except-deadend', '--keep-edges.components', '1', '--output.original-names', '--junctions.corner-detail', '5', '--geometry.max-segment-length', '10', '--osm.sidewalks', '--sidewalks.guess', '--crossings.guess', '--default.connection.cont-pos', '0', '--type-files', ','.join([str(sumolib_typemap()), str(context.resource('osm_types.typ.xml'))])]
    if is_rural:
        cmd.remove('--sidewalks.guess')
    if corridor.shaped(cfg):
        # Edges partly inside the polygon are kept; the rest of the bbox is dropped.
        cmd[cmd.index('--keep-edges.in-geo-boundary')+1] = corridor.geo_boundary(map_area)
    with (BUILD/'netconvert.log').open('w') as log:
        cmd[cmd.index('--type-files')+1] = str(type_file)
        cmd[cmd.index('--geometry.max-segment-length')+1] = '5'
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    # SUMO records wall clock and absolute temporary paths in an XML comment.
    # Remove only comments so the same inputs have stable network/geometry hashes.
    import re
    network_file = BUILD/'network.net.xml'
    network_file.write_bytes(re.sub(rb'<!--.*?-->', b'', network_file.read_bytes(), flags=re.S))
    net = sumolib.net.readNet(str(BUILD/'network.net.xml'), withInternal=True, withPrograms=True)
    cx,cy = net.convertLonLat2XY(*cfg['center'])
    def height(x,y):
        lon,lat = net.convertXY2LonLat(x,y)
        return terrain.sample(lon,lat)-base
    ground_height = [height]   # replaced by the road-aware GroundField once lanes are known
    def point(x,y,z=None):
        return [round(x-cx,3),round(ground_height[0](x,y) if z is None else z,3),round(-(y-cy),3)]
    def geo_point(lon,lat):
        return point(*net.convertLonLat2XY(lon,lat))
    road_z = RoadHeights(net, nodes, node_heights, way_refs)
    elevation_report['lanes_without_osm_profile'] = road_z.unmatched
    way_tags = {wid: tags(w) for wid, w in ways.items()}
    road_meta = road_geometry.metadata(net, way_tags, way_refs)
    prepared_strips = {}
    for edge in net.getEdges():
        if edge.getFunction():
            continue
        for lane in edge.getLanes():
            if lane.allows('passenger') and len(lane.getShape()) >= 2:
                prepared_strips[lane.getID()] = {'points': scene.lane_xyz(lane, road_z),
                    'width': lane.getWidth()+.02, 'lane': lane.getID(), 'topology': road_meta[lane.getID()]}
    seam_report = road_geometry.align_strips(list(prepared_strips.values()))
    for lid, strip in prepared_strips.items():
        road_z.shapes[lid] = [(x, y) for x, y, _ in strip['points']]
        road_z.z[lid] = [z for _, _, z in strip['points']]
    for edge in net.getEdges(withInternal=True):
        if edge.getFunction() == 'internal':
            for lane in edge.getLanes():
                if lane.allows('passenger'):
                    curve = road_geometry.smooth_turn(scene.lane_xyz(lane, road_z))
                    road_z.shapes[lane.getID()] = [(x, y) for x, y, _ in curve]
                    road_z.z[lane.getID()] = [z for _, _, z in curve]
    road_z.refresh_junctions()
    road_z.paint_heights = {}
    road_z.paint_areas = {}
    for edge in net.getEdges():
        strips = [prepared_strips[l.getID()] for l in edge.getLanes() if l.getID() in prepared_strips]
        if any('_height' in r for r in strips):
            mesh = surface_audit.TriangleIndex((r['lane'], r.get('triangles', list(surface_audit.ribbon_triangles(r['points'], r['width']))), r['topology']) for r in strips)
            road_z.paint_heights[edge.getID()] = lambda x,y,z,m=mesh: road_geometry.height_on(m,x,y,z)
            road_z.paint_areas[edge.getID()] = road_geometry.union(mesh.polys)
    def edge_surface(edge):
        for lane in edge.getLanes():
            for wid in lane.getParam('origId', '').split():
                if wid in way_tags:
                    return rural.surface(way_tags[wid])
        return 'road'
    def structure_of(edge):
        """Bridge (>0) / tunnel (<0) level of an edge from its OSM ways."""
        levels = [structure_level(way_tags.get(w, {})) for w in edge.getLanes()[0].getParam('origId', '').split()]
        return max(levels, key=abs) if levels else 0
    edge_level = {e.getID(): structure_of(e) for e in net.getEdges() if e.getFunction() == ''}
    def node_on_bridge(node):
        edges = [e for e in node.getIncoming()+node.getOutgoing() if e.getFunction() == '']
        return bool(edges) and all(edge_level.get(e.getID(), 0) > 0 for e in edges)
    xyz = lambda pts: [point(x, y, z) for x, y, z in pts]
    below = []   # filled after the lane loop: (segment, z0, z1) of every road strip
    def over_road(x, y, z):
        """A lower road passes under or right beside (x, y, z): the ground must stay open."""
        p = Point(x, y)
        for k in below_tree.query(p.buffer(UNDERPASS_REACH)):
            seg, z0, z1 = below[k]
            s = seg.project(p, normalized=True)
            if z0+(z1-z0)*s < z-UNDERPASS_DROP and seg.distance(p) <= UNDERPASS_REACH:
                return True
        return False
    def embankment_runs(points):
        """(ramps, spans) of a bridge-tagged polyline. OSM bridge ways usually include the
        approaches, and the ramps grow from the terrain; up to EMBANKMENT_MAX above the DEM,
        with no lower road beneath, the ground meets them like any road (an earth ramp).
        The rest stays a span with open ground under it."""
        low = [p[2]-height(p[0], p[1]) <= EMBANKMENT_MAX and not over_road(*p) for p in points]
        segs = [a and b for a, b in zip(low, low[1:])]
        ramps, spans, start = [], [], 0
        for i in range(1, len(segs)+1):
            if i == len(segs) or segs[i] != segs[start]:
                (ramps if segs[start] else spans).append(points[start:i+1])
                start = i
        return ramps, spans
    lanes, road_strips, anchors, edges, profile = [], [], [], [], []
    ramp_strips, span_strips = [], []
    for edge in net.getEdges(withInternal=True):
        internal = edge.getFunction() == 'internal'
        if internal:
            on_bridge = node_on_bridge(edge.getFromNode())
        else:
            on_bridge = edge_level.get(edge.getID(), 0) > 0
        for lane in edge.getLanes():
            if not lane.allows('passenger') or len(lane.getShape()) < 2:
                continue
            item = {'id':lane.getID(),'edge':edge.getID(),'width':lane.getWidth(), 'speed':lane.getSpeed(),'internal':internal,'service':edge.getType()=='highway.service','points':road_z.points(lane,point)}
            lanes.append(item)
            if edge.getFunction() == '':
                strip = {**prepared_strips[lane.getID()], 'bridge':on_bridge,'internal':False,
                         'lane':lane.getID(), 'edge':edge.getID(), 'osm_way':lane.getParam('origId','')}
                if is_rural:
                    strip['surface'] = edge_surface(edge)
                    strip['surface_source'] = 'osm' if any('surface' in way_tags.get(w,{}) for w in strip['osm_way'].split()) else 'assumed'
                road_strips.append(strip)
    for strip in road_strips:
        pts = strip['points']
        below.extend((LineString([a[:2], b[:2]]), a[2], b[2]) for a, b in zip(pts, pts[1:]) if a[:2] != b[:2])
    from shapely import STRtree
    below_tree = STRtree([seg for seg, _, _ in below])
    for strip in road_strips:
        runs = [strip['points']]
        if strip['bridge']:
            runs, spans = embankment_runs(strip['points'])
            ramp_strips += [{**strip, 'points': r} for r in runs]
            span_strips += [{**strip, 'points': r} for r in spans]
        for run in runs:
            # GroundField edges = the actual ribbon borders (roads and earth ramps); the
            # ground mesh then snaps to their exact height right on the seam.
            anchors += run
            left, right = scene.strip_borders(run, strip['width'])
            if '_height' in strip:
                left, right = ([(x, y, strip['_height'](x, y)) for x, y, _ in side] for side in (left, right))
            edges += scene.border_segments(left)+scene.border_segments(right)
            profile += [(p[0], p[1]) for p in left]+[(p[0], p[1]) for p in right]
    context.progress('roads', 0.45)
    # Junction surface = node outline plus the swept internal lanes (turns, dead-end U-turn
    # bulbs), one continuous mesh; internal lanes are not drawn as separate strips.
    junctions, junction_polys, bridge_junctions = [], [], []
    node_polys = {}
    strip_polys = [scene.strip_polygon(r['points'], r['width']) for r in road_strips]
    strip_tree = STRtree(strip_polys)
    joined_surfaces, joined_grid = [], {}
    def cells(poly):
        if poly.is_empty:
            return []
        x0,y0,x1,y1 = poly.bounds
        return [(x,y) for x in range(math.floor(x0/50),math.floor(x1/50)+1)
                for y in range(math.floor(y0/50),math.floor(y1/50)+1)]
    def priority(node):
        ranks = [road_meta[l.getID()]['rank'] for e in node.getIncoming()+node.getOutgoing()
                 for l in e.getLanes() if l.getID() in road_meta]
        return min(ranks, default=99), node.getID()
    for node in sorted(net.getNodes(), key=priority):
        shape = node.getShape()
        parts = [Polygon(shape).buffer(0)] if len(shape) >= 3 else []
        for lane_id in road_z.internal_by_node.get(node.getID(), []):
            lane = net.getLane(lane_id)
            if lane.allows('passenger') and len(road_z.shape(lane)) >= 2 and LineString(road_z.shape(lane)).length > 0.05:
                parts.append(scene.strip_polygon(scene.lane_xyz(lane, road_z), lane.getWidth()+.1))
        if not parts:
            continue
        poly = road_geometry.union(parts).buffer(0)
        if poly.is_empty:
            continue
        adjoining = [road_strips[int(k)] for k in strip_tree.query(poly.buffer(.01))
                     if node.getID() in road_strips[int(k)]['topology']['nodes']]
        levels = {tuple(s) for r in adjoining for s in r['topology']['levels']}
        topology = {'nodes': [node.getID()], 'ways': sorted({w for r in adjoining for w in r['topology']['ways']}),
                    'levels': [list(s) for s in sorted(levels)]}
        # Mixed explicit structure levels are kept for audit, never silently joined by XY.
        compatible = adjoining if len(levels) <= 1 else []
        previous = {i for cell in cells(poly) for i in joined_grid.get(cell, [])}
        compatible = compatible + [joined_surfaces[i][1] for i in sorted(previous)
                      if poly.intersects(joined_surfaces[i][0]) and
                      surface_audit.relationship(topology, joined_surfaces[i][1]['topology']) == 'connected']
        poly, surface_tris, z_at = road_geometry.junction_surface(poly, compatible, road_z.node_z[node.getID()])
        node_polys[node.getID()] = poly
        if surface_tris:
            record = {'lane':'junction:'+node.getID(), 'points':surface_tris[0], 'width':1.,
                      'triangles':surface_tris, 'topology':topology}
            for cell in cells(poly):
                joined_grid.setdefault(cell, []).append(len(joined_surfaces))
            joined_surfaces.append((poly,record))
        road_z.node_z[node.getID()] = z_at
        for lid in road_z.internal_by_node.get(node.getID(), []):
            lane = net.getLane(lid)
            road_z.z[lid] = [z_at(x, y) for x, y in road_z.shape(lane)]
        bridge = node_on_bridge(node)
        # A junction on an earth ramp takes part in the ground like one at grade.
        span = bridge and any(z_at(x, y)-height(x, y) > EMBANKMENT_MAX or over_road(x, y, z_at(x, y))
                              for pg in scene.polygons(poly) for x, y in pg.exterior.coords)
        if span:
            bridge_junctions.append((poly, z_at))
        else:
            junction_polys.append(poly)
            for pg in scene.polygons(poly):
                ring = list(pg.exterior.coords)
                pts = [(x, y, z_at(x, y)) for x, y in ring]
                anchors += pts
                edges += scene.border_segments(pts)
                profile += [(x, y) for x, y in ring]
                for hole in pg.interiors:
                    hpts = [(x, y, z_at(x, y)) for x, y in list(hole.coords)]
                    edges += scene.border_segments(hpts)
                    profile += [(x, y) for x, y in list(hole.coords)]
        junctions.append({'id':node.getID(),'bridge':bridge,'topology':topology,
                          'triangles':[[point(x,y,z) for x,y,z in tri] for tri in surface_tris]})
        if is_rural:
            surfaces = [edge_surface(e) for e in node.getIncoming()+node.getOutgoing() if e.getFunction()=='']
            junctions[-1]['surface'] = 'road' if 'road' in surfaces else ('gravel' if 'gravel' in surfaces else 'dirt')
    for item in lanes:
        if item['internal']:
            item['points'] = road_z.points(net.getLane(item['id']), point)
    road_z.turn_markings = road_geometry.turn_markings(net, road_z, node_polys)
    carriageway = road_geometry.union([scene.footprint(road_strips), *junction_polys]).buffer(0.05)
    walk_strips, walk_areas = scene.sidewalks(net, road_z, carriageway, structure_of)
    walk_ramps = []
    for strip in walk_strips:
        runs = [strip['points']]
        if strip.get('bridge'):
            # Sidewalks on a span must not pull the ground toward the deck level; on an earth
            # ramp they meet it like the carriageway beside them. Tunnels stay excluded.
            runs = embankment_runs(strip['points'])[0] if strip.get('structure_level', 0) > 0 else []
            walk_ramps += [{**strip, 'points': r} for r in runs]
        for run in runs:
            anchors += run
            # Sidewalk edges at their base height: the curb wall (0..0.15 m) then sits exactly
            # on the ground instead of floating over a sagging field.
            left, right = scene.strip_borders(run, strip['width'])
            edges += scene.border_segments(left)+scene.border_segments(right)
            profile += [(p[0], p[1]) for p in left]+[(p[0], p[1]) for p in right]
    elevation_report['earth_ramp_strips'] = len(ramp_strips)
    road_cut = road_geometry.union([scene.footprint([r for r in road_strips if not r['bridge']]+ramp_strips),
                            scene.footprint([w for w in walk_strips if not w.get('bridge')]+walk_ramps),
                            *junction_polys,
                            # Walking areas keep their original rendered levels; only their
                            # ground-cut contribution is limited to non-bridge areas, so the
                            # terrain is not excavated under an elevated plaza either.
                            *[p for area in walk_areas if not area.get('bridge') for ring in area['rings'] if not (p := scene.planar(ring)).is_empty]])
    dem = lambda x, y: height(x, y)
    ground_z = scene.GroundField(dem, anchors, edges=edges)
    context.progress('ground', 0.55)
    # Low decks (terrain within 2 m under the asphalt) are cut out of the ground, and the
    # ground around them is held below the deck: the coarse DEM otherwise shows through.
    deck_cut, deck_segments = scene.low_decks(span_strips, bridge_junctions, ground_z)
    if not deck_cut.is_empty:
        road_cut = road_geometry.union([road_cut, deck_cut])
        ground_z = scene.DeckClamp(ground_z, deck_segments)
    elevation_report['low_deck_cut_m2'] = round(deck_cut.area, 1)
    medians = scene.deck_medians(span_strips)
    by_tile = {}
    for tri in medians:
        pts = [point(x, y, z) for x, y, z in tri]
        cell = (math.floor(sum(p[0] for p in pts)/3/TILE), math.floor(sum(p[2] for p in pts)/3/TILE))
        by_tile.setdefault(cell, []).append(pts)
    for (tx, tz), tris in sorted(by_tile.items()):
        junctions.append({'id': f'deck_median_{tx}_{tz}', 'bridge': True, 'triangles': tris})
    elevation_report['deck_median_m2'] = round(sum(Polygon([p[:2] for p in t]).area for t in medians), 1)
    ground_height[0] = ground_z
    markings = scene.markings(net, road_z, edge_level)
    if is_rural:
        # Untagged village markings are unknown. Keep the carriageway unpainted.
        markings = []
    elevation_report['ground_anchor_points'] = len(anchors)
    buildings, greens, parking_polys, osm_footprints = [], [], [], []
    facade_fixes = visual_tags.overrides(context.resource('style.json'))
    counts = Counter()
    counts['underground_service_ways_excluded'] = underground_excluded
    clip = map_area
    context.progress('landcover', 0.6)
    # A corridor also trims landcover and ground to its polygon (network XY); ways that only
    # touch it (a large forest, a rail yard) would otherwise be drawn far outside the map.
    area_xy = corridor.to_net(map_area,net) if corridor.shaped(cfg) else None
    passage_lines = [LineString([net.convertLonLat2XY(*nodes[r]) for r in (nd.attrib['ref'] for nd in w.findall('nd')) if r in nodes]) for w in ways.values() if drivable(tags(w)) and tags(w).get('tunnel')=='building_passage']
    passages = unary_union([l.buffer(PASSAGE_HALF_WIDTH) for l in passage_lines if len(l.coords)>=2]) if passage_lines else None
    for wid,w in ways.items():
        t = tags(w)
        refs = [nd.attrib['ref'] for nd in w.findall('nd')]
        if 'highway' in t:
            counts['highway_ways'] += 1
            if t['highway'] in ('motorway','trunk','primary','secondary','tertiary','residential','unclassified','service','living_street') or t['highway'].endswith('_link'):
                counts['motor_road_ways'] += 1
                for key in ('lanes','width','maxspeed'):
                    counts['motor_roads_with_'+key] += key in t
            for key in ('lanes','width','maxspeed','oneway'):
                counts['roads_with_'+key] += key in t
            counts['bridge_ways'] += t.get('bridge','no')!='no'
            counts['tunnel_ways'] += t.get('tunnel','no')!='no'
        if len(refs)<4 or refs[0]!=refs[-1] or not all(r in nodes for r in refs):
            continue
        polygon = Polygon([nodes[r] for r in refs])
        if not polygon.is_valid or not clip.intersects(polygon):
            continue
        coords = [geo_point(*nodes[r]) for r in refs[:-1]]
        if 'building' in t or 'building:part' in t:
            counts['buildings']+=1
            default_levels = (2 if t.get('building')=='apartments' else 1) if is_rural else (5 if t.get('building')=='apartments' else 2)
            levels = number(t.get('building:levels'),default_levels)
            h = number(t.get('height'),levels*3+(1.8 if is_rural else 0))
            mode = 'height' if 'height' in t else ('levels' if 'building:levels' in t else 'assumed')
            counts['building_height_'+mode]+=1
            item = {'id':wid,'points':coords,'height':max(2,min(h,180)),'height_source':mode,'levels':levels,**visual_tags.classify(wid,t,facade_fixes)}
            if 'shop' in t or 'amenity' in t or t.get('building') in ('retail','commercial','supermarket'):
                item['ground_floor']='shop'
            footprint = Polygon([net.convertLonLat2XY(*nodes[r]) for r in refs]).buffer(0)
            osm_footprints.append(footprint)
            if passages is not None and footprint.intersects(passages):
                # Building passage: full-height block outside the carriageway, raised block above it.
                counts['buildings_split_for_passages']+=1
                for part, raised in ((footprint.difference(passages),False),(footprint.intersection(passages),True)):
                    for poly in (part.geoms if part.geom_type=='MultiPolygon' else [part]):
                        if poly.geom_type!='Polygon' or poly.area<1:
                            continue
                        ring = list(poly.exterior.coords)[:-1]
                        piece = {**item,'points':[point(x,y) for x,y in ring]}
                        if raised:
                            piece['base']=PASSAGE_CLEARANCE
                        buildings.append(piece)
                continue
            buildings.append(item)
        elif is_rural and rural.cover(t):
            greens.append({'id':wid,'kind':rural.cover(t),'poly':Polygon([net.convertLonLat2XY(*nodes[r]) for r in refs]).buffer(0)})
        elif t.get('landuse') in ('forest','grass','recreation_ground','meadow','village_green') or t.get('natural') in ('wood','scrub','grassland','water') or t.get('leisure') in ('park','garden','playground','pitch'):
            kind = 'water' if t.get('natural')=='water' else ('wood' if t.get('landuse')=='forest' or t.get('natural') in ('wood','scrub') else 'green')
            greens.append({'id':wid,'kind':kind,'poly':Polygon([net.convertLonLat2XY(*nodes[r]) for r in refs]).buffer(0)})
        elif t.get('amenity')=='parking' and 'building' not in t and t.get('parking','surface') in ('surface','lane','street_side'):
            parking_polys.append(Polygon([net.convertLonLat2XY(*nodes[r]) for r in refs]).buffer(0))
    context.progress('buildings', 0.7)
    # Building enrichment (INTEGRATE): DATA candidates merged strictly after the
    # OSM buildings above. OSM keeps priority (they are never mutated, only
    # excluded against), road_cut here is the non-bridge cut so bridge decks do
    # not reject buildings below them, and a missing enrichment cache fails
    # loudly (strict) instead of degrading to an empty success.
    enrichment_audit = None
    kept = []  # accepted enrichment buildings ([] when enrichment disabled)
    en = cfg.get('building_enrichment')
    if isinstance(en, dict) and en.get('enabled'):
        sc = en.get('sources_config')
        source_config = read_json(context.config_file(sc) if sc else context.resource('building_sources.json'))
        # A cache directory is not a config file: resolve it without archiving it as one.
        cache_dir = contained(context.config_root, en['cache_dir']) if en.get('cache_dir') else context.raw/'buildings'
        features, cand_audit = building_sources.load_candidates(
            cfg, offline=context.offline or bool(en.get('offline', False)), cache_dir=cache_dir,
            sources_config=source_config, base=context.config_root)
        problems = building_enrichment.gate(cand_audit, strict=bool(en.get('strict', True)))
        water = unary_union([g['poly'] for g in greens if g['kind'] == 'water']) or Polygon()
        policy = en.get('unknown_height_policy', 'skip')
        if policy not in building_enrichment.UNKNOWN_HEIGHT_POLICIES:
            raise building_enrichment.EnrichmentError(
                f"building_enrichment.unknown_height_policy {policy!r} must be one of "
                f"{building_enrichment.UNKNOWN_HEIGHT_POLICIES}")
        records, enriched_polys, conversion = building_enrichment.to_render_items(
            features, net.convertLonLat2XY, point,
            default_height=float(en.get('default_height', building_enrichment.DEFAULT_HEIGHT)),
            unknown_height_policy=policy)
        kept, exclusion = building_enrichment.exclude(
            records, enriched_polys, osm_footprints, road_cut, water,
            road_margin=float(en.get('road_margin', 0.5)),
            water_margin=float(en.get('water_margin', 0.5)))
        if area_xy is not None:
            kept = [b for b in kept if area_xy.intersects(Polygon([(p[0]+cx,cy-p[2]) for p in b['points']]))]
        buildings.extend(kept)
        enrichment_audit = {
            'offline': context.offline or bool(en.get('offline', False)),
            'strict': bool(en.get('strict', True)),
            'unknown_height_policy': policy,
            'candidates': cand_audit,
            'conversion': conversion,
            'exclusion': exclusion,
            'problems': problems,
            'accepted': len(kept),
            # Exact candidate caches used, relative to the cache root, with hashes.
            'cache_files': {Path(f).relative_to(cache_dir).as_posix(): sha256(f)
                            for f in building_enrichment.reused_cache_files(cache_dir, cand_audit)},
        }
        counts['enrichment_accepted'] = len(kept)
        counts['enrichment_rejected'] = (conversion['holes_skipped'] + conversion['too_small_skipped']
                                         + conversion['unknown_height_skipped']
                                         + len(exclusion['osm_excluded']) + len(exclusion['road_excluded'])
                                         + len(exclusion['water_excluded']) + len(exclusion['duplicate_overlap_dropped']))
        counts['enrichment_candidates'] = len(features)
    fences, row_trees = [], []
    if is_rural:
        fences, row_trees, gardens = rural.dress(buildings,way_tags,root,nodes,net,point,road_cut,
                                      area_xy if area_xy is not None else corridor.to_net(map_area,net))
        greens = rural.relation_covers(root,nodes,net.convertLonLat2XY,map_area)+greens+gardens
        counts['rural_fences'] = len(fences)
        counts['rural_roofs'] = sum('roof_triangles' in b for b in buildings)
        counts['tree_row_instances'] = len(row_trees)
    signals=[]
    for tls in net.getTrafficLights():
        for incoming,outgoing,index in tls.getConnections():
            if incoming.allows('passenger'):
                (xa,ya),(x,y) = incoming.getShape()[-2:]
                signals.append({'tls':tls.getID(),'index':index,'lane':incoming.getID(),'width':incoming.getWidth(),'heading':math.degrees(math.atan2(x-xa,y-ya))%360,'position':point(x,y,road_z.z[incoming.getID()][-1])})
    counts['osm_signal_nodes'] = sum(tags(n).get('highway')=='traffic_signals' for n in root.findall('node'))
    counts['restriction_relations'] = sum(tags(r).get('type')=='restriction' for r in root.findall('relation'))
    # Spawn: rightmost passenger lane of a long ordinary road (not a yard, bridge or turn
    # pocket), SPAWN_OFFSET m in, so the player starts with room before the next junction.
    # config 'spawn' {lon, lat, heading} picks the nearest such lane in that direction.
    def spawn_ok(edge):
        return (edge.getFunction()=='' and edge.getType() not in ('highway.service','highway.living_street')
                and edge_level.get(edge.getID(),0)==0 and edge.getLength()>=SPAWN_MIN_EDGE)
    def rightmost(edge):
        lanes_ok=[l for l in edge.getLanes() if l.allows('passenger')]
        return min(lanes_ok,key=lambda l:l.getIndex()) if lanes_ok else None
    target=cfg.get('spawn')
    tx,ty=net.convertLonLat2XY(target['lon'],target['lat']) if target else (cx,cy)
    def spawn_cost(edge):
        (ax,ay),(bx,by)=edge.getShape()[0],edge.getShape()[1]
        heading=math.degrees(math.atan2(bx-ax,by-ay))%360
        if target and abs((heading-target['heading']+180)%360-180)>45:
            return float('inf')
        return min((x-tx)**2+(y-ty)**2 for x,y in edge.getShape())
    candidates = [e for e in net.getEdges() if spawn_ok(e) and rightmost(e) and math.isfinite(spawn_cost(e))]
    if not candidates:
        raise ValueError('No suitable start road: need an ordinary ground-level passenger road at least 120 m long; enlarge the bbox or change spawn.')
    spawn_edge=min(candidates,key=spawn_cost)
    spawn = rightmost(spawn_edge)
    shape = spawn.getShape()
    pos = SPAWN_OFFSET
    x,y = sumolib.geomhelper.positionAtShapeOffset(shape,pos)
    xa,ya = sumolib.geomhelper.positionAtShapeOffset(shape,min(pos+2,spawn.getLength()))
    angle = math.degrees(math.atan2(xa-x,ya-y))%360
    # Quick-travel points (tools/pois.py), only for configs that ask for them.
    poi_cfg=cfg.get('pois') or {}
    poi_report,poi_records=None,[]
    if poi_cfg.get('enabled'):
        poi_report={'pois_unsnapped':[]}
        found=poi_points.candidates(root,tags,nodes,corridor.contains(map_area))
        poi_kept=poi_points.select(found,net.convertLonLat2XY,limit=int(poi_cfg.get('limit',poi_points.LIMIT)))
        snapper=poi_points.Snapper(net,spawn_ok,rightmost)
        poi_records=poi_points.place(poi_kept,poi_cfg.get('anchors',[]),net,snapper,point,road_z.at_offset,poi_report)
        poi_report.update(candidates=len(found),kept=len(poi_kept),placed=len(poi_records))
    import random
    rng_trees=random.Random(cfg['seed'])
    context.progress('trees', 0.78)
    # Planted trees: ~250 per km2 of map, at least 4000 (the original district cap).
    tree_cap=max(4000,int(map_area.area*111000*71000/1e6*250))
    trees=list(row_trees)
    # Landcover is cut out of the ground so grass never overlaps asphalt or other cover.
    cover_cut = road_cut.buffer(0.5)
    parking = unary_union(parking_polys).difference(cover_cut) if parking_polys else Polygon()
    if area_xy is not None:
        parking = parking.intersection(area_xy)
    green_out=[]
    for area in greens:
        poly=area['poly'].difference(cover_cut).difference(parking)
        if is_rural:
            poly=poly.difference(unary_union([a['cut'] for a in greens if 'cut' in a]))
        if area_xy is not None:
            poly=poly.intersection(area_xy)
        if poly.is_empty:
            continue
        green_out.append({'id':area['id'],'kind':area['kind'],'triangles':[[point(x,y) for x,y in tri] for tri in scene.draped_triangles(poly)]})
        area['cut']=poly
        if area['kind'] in ('green','wood','orchard'):
            left,bottom,right,top=poly.bounds
            attempts=min(500,int(poly.area/(90 if area['kind']=='wood' else 180)))
            for _ in range(attempts):
                x,y=rng_trees.uniform(left,right),rng_trees.uniform(bottom,top)
                if poly.contains(Point(x,y)) and len(trees)<tree_cap:
                    trees.append(point(x,y))
    for n in root.findall('node'):
        if tags(n).get('natural')=='tree':
            x,y=net.convertLonLat2XY(float(n.attrib['lon']),float(n.attrib['lat']))
            if clip.contains(Point(float(n.attrib['lon']),float(n.attrib['lat']))) and not road_cut.contains(Point(x,y)):
                trees.append(point(x,y))
                counts['osm_trees']+=1
    covered = unary_union([road_cut, parking, *[a['cut'] for a in greens if 'cut' in a]])
    ground=[]
    west,south,east,north=cfg['bbox']
    x0,y0=net.convertLonLat2XY(west,south); x1,y1=net.convertLonLat2XY(east,north)
    # A corridor keeps ground only inside its polygon, not over the whole bounding box.
    area_box = area_xy if area_xy is not None else box(x0,y0,x1,y1)
    # Stitch the road profile vertices into the ground cut boundary: the draped triangles
    # then carry ribbon-profile stations and follow the same piecewise-linear slope as the
    # drawn road edges (GroundField snaps those vertices to the border segment heights).
    ground_polys = scene.stitch_vertices(scene.polygons(area_box.difference(covered)), profile)
    ground=[[point(a,b) for a,b in tri] for poly in ground_polys for tri in scene.draped_triangles(poly)]
    parking_tris=[[point(a,b) for a,b in tri] for tri in scene.draped_triangles(parking)]
    paths=[{**pth,'points':xyz(pth['points'])} for pth in scene.paths(ways,nodes,tags,net.convertLonLat2XY,covered.difference(parking),ground_z)]
    counts['paths']=len(paths)
    shots=[]
    for shot in json.loads((context.config_file(cfg['shots_config']) if cfg.get('shots_config') else context.resource('shots.json')).read_text(encoding='utf-8'))['shots']:
        if west<=shot['lon']<=east and south<=shot['lat']<=north and clip.intersects(Point(shot['lon'],shot['lat'])):
            item={**{k:shot[k] for k in ('name','heading','height','pitch')},'position':geo_point(shot['lon'],shot['lat'])}
            if shot.get('snap'):
                sx,sy=net.convertLonLat2XY(shot['lon'],shot['lat'])
                best=None
                for e in net.getEdges():
                    if e.getFunction()!='' or (e.getType()=='highway.service')!=bool(shot.get('service')):
                        continue
                    for lane in e.getLanes():
                        if not lane.allows('passenger'):
                            continue
                        shp=lane.getShape()
                        for i,((ax,ay),(bx,by)) in enumerate(zip(shp,shp[1:])):
                            h=math.degrees(math.atan2(bx-ax,by-ay))%360
                            if abs((h-shot['heading']+180)%360-180)>60:
                                continue
                            d=(ax-sx)**2+(ay-sy)**2
                            if best is None or d<best[0]:
                                best=(d,lane,i,h)
                if best:
                    _,lane,i,h=best
                    x,y=lane.getShape()[i]
                    item.update({'heading':h,'position':point(x,y,road_z.z[lane.getID()][i])})
            shots.append(item)
    context.progress('signs', 0.84)
    # Road signs and traffic-light programmes (tools/signs.py). Both are derived, never
    # observed: every record carries its provenance.
    sign_facts={'maxspeed':set(),'oneway':set(),'nodes':[]}
    for w in root.findall('way'):
        t=tags(w)
        if 'maxspeed' in t: sign_facts['maxspeed'].add(w.get('id'))
        if t.get('oneway') in ('yes','-1','true','1'): sign_facts['oneway'].add(w.get('id'))
    for n in root.findall('node'):
        t=tags(n)
        if t.get('highway') in ('stop','give_way'):
            x,y=net.convertLonLat2XY(float(n.get('lon')),float(n.get('lat')))
            sign_facts['nodes'].append((t['highway'],x-cx,-(y-cy)))
    sign_records=road_signs.derive(net,lanes,sign_facts,counts)
    tls_records=road_signs.traffic_lights(net,lambda x,y:[round(x-cx,3),0.0,round(-(y-cy),3)])
    exported_roads = [{**{k: v for k, v in r.items() if not k.startswith('_')}, 'points': xyz(r['points']),
                       'triangles': [xyz(t) for t in r.get('triangles', surface_audit.ribbon_triangles(r['points'], r['width']))]}
                      for r in road_strips]
    world={'network_sha256':hashlib.sha256((BUILD/'network.net.xml').read_bytes()).hexdigest(),'version':2,'name':cfg['name'],'offset':[cx,cy],'base_height':base,'bbox':cfg['bbox'],'lanes':lanes,'road_strips':exported_roads,'markings':[{**m,'points':xyz(m['points'])} for m in markings],'sidewalks':[{**w,'points':xyz(w['points'])} for w in walk_strips],'walkingareas':[{'bridge':a.get('bridge',False),'structure_level':a.get('structure_level',0),'triangles':[xyz(t) for t in a['triangles']],'rings':[xyz(r) for r in a['rings']]} for a in walk_areas],'junctions':junctions,'buildings':buildings,'greens':green_out,'parking':parking_tris,'paths':paths,'trees':trees,'signals':signals,'signs':sign_records,'tls':tls_records,'ground':ground,'shots':shots,'spawn':{'lane':spawn.getID(),'edge':spawn.getEdge().getID(),'lane_index':spawn.getIndex(),'lane_position':pos,'position':point(*sumolib.geomhelper.positionAtShapeOffset(shape,pos),road_z.at_offset(spawn,pos)),'angle':angle},'attribution':'© OpenStreetMap contributors · ODbL | Terrain: Mapzen / source attribution in docs/SOURCES.md'}
    # Attribution after construction: keep the OSM-only footer byte-for-byte
    # when enrichment accepted nothing, otherwise the shorter combined footer
    # (full OSM name preserved; Overture/Microsoft listed only when shipped).
    if cfg.get('source_kind') == 'synthetic':
        from akadem_maps.world import SYNTHETIC_ATTRIBUTION
        world['attribution'] = SYNTHETIC_ATTRIBUTION
    world['attribution'] = building_enrichment.attribution(kept, world['attribution'])
    if poi_cfg.get('enabled'):
        world['pois']=poi_records
    world['id'] = cfg['id']
    world['region_profile'] = cfg.get('region_profile', 'experimental')
    if is_rural:
        world['fences'] = fences
        world['visual_profile'] = 'rural'
        world['traffic_count'] = cfg.get('traffic_count',20)
        world['map_boundary_cuts'] = map_clip_report
    if corridor.shaped(cfg):
        # Map outline for the exporter (tile selection) and the navgraph border stubs.
        world['area']=[[round(x-cx,3),0.0,round(-(y-cy),3)] for x,y in area_xy.exterior.coords]
    context.progress('tiles', 0.87)
    tile_count=write_world(world, context.world)
    report={'counts':dict(counts),'elevation':elevation_report,'lanes':len(lanes),'junctions':len(junctions),'sliver_triangles_dropped':world.get('sliver_triangles_dropped',0),'traffic_lights':len(net.getTrafficLights()),'terrain_tiles':sorted(terrain.used),'assumptions':['OSM-derived lane widths/speeds and missing lanes may use SUMO defaults.','Signal phases are synthetic. Traffic demand is generated separately by the Godot adapter.','Road heights: coarse DEM smoothed along the road graph; bridge decks assumed 6.5 m (road) / 7 m (rail) above crossings, tunnels 3.5 m per layer, ramps limited to 6% (12% service). Not surveyed heights.','Building multipolygon relations are retained in source but rendering currently uses closed ways; holes/parts require review.','Initial rectangle includes neighboring streets; not an administrative boundary.','Road signs are derived from the SUMO network and OSM tags; Kyiv OSM has almost no traffic_sign nodes. Each record carries provenance = osm | derived. Signal phase programs are netconvert defaults, not observed Kyiv timings.'],'spawn':world['spawn'],'building_enrichment':enrichment_audit,'tiles':tile_count,**({'pois':poi_report} if poi_report else {})}
    context.progress('surface_audit', .89)
    surfaces_report = surface_audit.audit(world, [world])
    write_json(BUILD/'surface_audit.json', surfaces_report)
    write_json(BUILD/'road_seams.json', seam_report)
    report['surface_audit'] = {k: surfaces_report[k] for k in ('version', 'method', 'steps', 'acceptance', 'worst')}
    report['surface_audit']['smooth'] = {k: v for k, v in surfaces_report['smooth'].items() if k != 'all'}
    report['surface_audit']['report'] = 'surface_audit.json'
    report['surface_audit']['seams'] = seam_report['counts']
    write_json(BUILD/'audit.json',report)
    write_json(BUILD/'road_width_defaults.json',width_defaults)
    return report
