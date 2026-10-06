"""Distance-based road elevation, derived from DEM, never surveyed geometry.

Filter uniformly spaced samples, not OSM vertices. A robust local linear fit
rejects short spikes; distance-scaled curvature fairing suppresses longer DEM
waves without flattening constant grades. Reconcile strokes before assembling
ways, then apply paired-carriageway and structure constraints.
"""
import math
from collections import defaultdict

import numpy as np

from .surface_audit import structure

STEP = 2.0
RADIUS = 24.0
# Filter radius by road class: main roads are built with long vertical curves,
# a 24 m window kept every DEM undulation of the Zhytomyr highway.
CLASS_RADIUS = {'motorway': 90., 'trunk': 90., 'primary': 70., 'secondary': 50., 'tertiary': 36.}
# DEM samples this close to a bridge deck include the structure and its
# embankment; a road passing under it takes its height from either side.
UNDER_BRIDGE = 14.
# Divided roads: the two one-way carriageways of one named road share a profile
# where they run within PAIR_DISTANCE of each other, faded over PAIR_FADE metres.
PAIR_DISTANCE = 45.
DECK_CURVE = 60.  # m, length of the crest curve over a crossing beneath a bridge
DECK_JOIN = 8.    # m, Gaussian rounding where a deck lift meets the deck profile
PAIR_FADE = 30.
# Divided motorways/trunks get a continuous median barrier where the two centrelines
# run within MEDIAN_MAX metres (owner's request, playtest 2026-10-06 note 1).
MEDIAN_CLASSES = ('motorway', 'trunk')
MEDIAN_MAX = 30.
SPIKE = 1.0
STROKE_TURN = 35.  # degrees; a straighter continuation through a junction is one stroke
# Synthetic road engineering scale, not a surveyed design standard. Penalize
# curvature over metres, separately from rejecting short DEM outliers.
FAIRING_LENGTH = 30.
FAIRING_CLASS_FACTOR = .8
# A shared-node correction fades out over |correction|/CORRECTION_GRADE metres,
# clamped to [CORRECTION_MIN, CORRECTION_MAX], instead of at the next OSM node.
CORRECTION_GRADE = .03
CORRECTION_MIN = 12.
CORRECTION_MAX = 60.
# A minor road keeps the junction node's height across the major road's half width
# plus MOUTH_MARGIN, then returns to its own profile at no more than MOUTH_GRADE
# (playtest 2026-10-06, note 8: a service mouth 0.6 m above a primary road).
CLASS_RANK = {'motorway': 0, 'trunk': 1, 'primary': 2, 'secondary': 3, 'tertiary': 4,
              'unclassified': 5, 'residential': 5, 'living_street': 6, 'service': 7}
MOUTH_MARGIN = 4.
MOUTH_GRADE = .04
MOUTH_FADE = (6., 40.)
LANE_WIDTH = 3.3


class BendField:
    """A continuous height near sharp source bends.

    Nearest-segment projection changes discontinuously across the bisector of
    an inside bend. Near a bend, use a Gaussian average of the dense profile
    stations instead; its width grows with distance from the centreline, so
    lanes on the centreline keep the station profile and lanes far inside a
    ring see a broad, continuous average. It never extrapolates: a fitted
    plane carried the terrain slope across wide roads and roundabouts as
    crossfall (Bilychi roundabout 1200327578: 0.64 m between lanes). Bend
    weights fade over 6-12 m and are summed, never switched by nearest centre.
    """
    def __init__(self, points):
        self.bends = []
        self.points = p = np.asarray(points, dtype=float)
        for i in range(len(p)-1):
            if i == 0 and np.linalg.norm(p[0,:2]-p[-1,:2]) > 1e-6:
                continue  # an open end is not a bend; a closed ring's start is
            a,b = p[i,:2]-p[i-2 if i == 0 else i-1,:2],p[i+1,:2]-p[i,:2]
            den = np.linalg.norm(a)*np.linalg.norm(b)
            if den < 1e-9 or np.dot(a,b)/den > math.cos(math.radians(15)):
                continue
            self.bends.append(p[i,:2])

    def average(self,x,y):
        d2 = np.sum((self.points[:,:2]-(x,y))**2,axis=1)
        sigma = max(2.,.5*math.sqrt(float(d2.min())))
        w = np.exp(-.5*d2/(sigma*sigma))
        return float(np.dot(w,self.points[:,2])/w.sum())

    def height(self,x,y,original):
        total = 0.
        for centre in self.bends:
            distance = math.hypot(x-centre[0],y-centre[1])
            if distance < 12.:
                t = max(0., (distance-6.)/6.)
                total += 1-t*t*(3-2*t)
        if total <= 0.:
            return original
        return original+min(1.,total)*(self.average(x,y)-original)


def smooth(distances, heights, radius=RADIUS, trusted=None):
    """`trusted` (bool per sample, optional): False samples carry no weight; the
    fit passes over them from the samples on either side."""
    s, raw = np.asarray(distances), np.asarray(heights, dtype=float)
    if not np.all(np.isfinite(raw)):
        raise ValueError('Non-finite road DEM sample')
    if len(raw) < 3:
        return raw.copy()
    base = np.ones(len(raw)) if trusted is None else np.where(trusted, 1., 1e-6)
    reliability = base.copy()
    result = raw.copy()
    windows = [(np.searchsorted(s, x-radius), np.searchsorted(s, x+radius, side='right')) for x in s]
    for iteration in range(3):
        for i, (lo, hi) in enumerate(windows):
            x = s[lo:hi]-s[i]
            w = np.exp(-.5*(x/(radius/3))**2)*reliability[lo:hi]
            y = raw[lo:hi]
            a, b, c = w.sum(), (w*x).sum(), (w*x*x).sum()
            d, e = (w*y).sum(), (w*x*y).sum()
            den = a*c-b*b
            result[i] = (d*c-b*e)/den if den > 1e-12 else raw[i]
        if iteration < 2:
            residual = np.abs(raw-result)
            # A fixed floor avoids declaring quantized DEM millimetres outliers.
            scale = max(.05, float(np.median(residual))*1.4826)
            reliability = base*np.minimum(1., (2.5*scale/np.maximum(residual, 1e-12))**2)
    return result


def fair_profile(distances, heights, length=FAIRING_LENGTH):
    """Fit a road profile by penalizing changes in grade, with free end slopes.

    Minimize sum((z-h)**2) + length**4 * sum(z_second_derivative**2).
    Samples must be uniformly spaced in metres. The pentadiagonal system costs
    O(n) memory/time and needs no additional numerical dependency. Linear grades
    are in the penalty's null space; there is no absolute grade limit or endpoint
    pin to noisy DEM. Long terrain trends survive while repeated hills/dips do not.
    """
    s, h = np.asarray(distances, dtype=float), np.asarray(heights, dtype=float)
    if len(s) != len(h) or not np.all(np.isfinite(h)) or not np.all(np.isfinite(s)):
        raise ValueError('Invalid road profile samples')
    if not math.isfinite(length) or length < 0:
        raise ValueError('Invalid road fairing length')
    if len(h) < 3 or length == 0:
        return h.copy()
    step = (s[-1]-s[0])/(len(s)-1)
    if step <= 0 or not np.allclose(np.diff(s), step, rtol=1e-6, atol=1e-8):
        raise ValueError('Road fairing requires uniform distance samples')
    penalty = (length/step)**4
    n = len(h)
    diag = np.ones(n)
    diag[:-2] += penalty
    diag[1:-1] += 4*penalty
    diag[2:] += penalty
    off = np.zeros(n-1)
    off[:-1] -= 2*penalty
    off[1:] -= 2*penalty
    second = np.full(n-2, penalty)
    trend = h[0]+(h[-1]-h[0])*(s-s[0])/(s[-1]-s[0])
    rhs = h-trend
    for i in range(n-1):
        factor = off[i]/diag[i]
        diag[i+1] -= factor*off[i]
        rhs[i+1] -= factor*rhs[i]
        if i < n-2:
            factor2 = second[i]/diag[i]
            diag[i+2] -= factor2*second[i]
            rhs[i+2] -= factor2*rhs[i]
            off[i+1] -= factor*second[i]
    result = np.empty(n)
    for i in range(n-1, -1, -1):
        value = rhs[i]
        if i < n-1:
            value -= off[i]*result[i+1]
        if i < n-2:
            value -= second[i]*result[i+2]
        result[i] = value/diag[i]
    return result+trend


def _bridge_index(root, nodes, tags, to_xy):
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
    lines, refs = [], []
    for way in root.findall('way'):
        if structure(tags(way))[0] <= 0 and not structure(tags(way))[1]:
            continue
        pts = [to_xy(*nodes[nd.get('ref')]) for nd in way.findall('nd') if nd.get('ref') in nodes]
        if len(pts) >= 2:
            lines.append(LineString(pts))
            refs.append({nd.get('ref') for nd in way.findall('nd')})
    return (STRtree(lines), lines, refs) if lines else None


def _class_radius(tags):
    return CLASS_RADIUS.get(tags.get('highway', '').replace('_link', ''), RADIUS)


def ground_profiles(root, nodes, tags, drivable, to_xy, sample):
    from shapely.geometry import Point
    profiles, node_samples, spikes = {}, defaultdict(list), []
    node_anchors = defaultdict(list)
    ways, edges, adjacent = {}, {}, defaultdict(list)
    bridges = _bridge_index(root, nodes, tags, to_xy)
    way_tags = {}
    for way in sorted(root.findall('way'), key=lambda w: w.get('id')):
        if not drivable(tags(way)):
            continue
        refs = [nd.get('ref') for nd in way.findall('nd') if nd.get('ref') in nodes]
        if len(refs) < 2:
            continue
        xy = np.array([to_xy(*nodes[n]) for n in refs])
        along = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        if along[-1] < 1e-6:
            continue
        wid = way.get('id')
        ways[wid] = (refs, xy, along)
        way_tags[wid] = tags(way)
        level = structure(tags(way))
        for i,(a,b) in enumerate(zip(refs,refs[1:])):
            if along[i+1]-along[i] < 1e-7:
                continue
            key = (wid,i)
            edges[key] = (a,b,level)
            adjacent[a,level].append(key)
            adjacent[b,level].append(key)
    # Continue through degree-two source nodes, including OSM way boundaries.
    # Straight continuations form strokes; disconnected roads are never sampled.
    unused, edge_samples, strokes = set(edges), {}, []
    count, max_shift = 0, 0.
    point = lambda n: np.asarray(to_xy(*nodes[n]), dtype=float)

    def heading(key, frm):
        a,b,_ = edges[key]
        v = point(b if frm == a else a)-point(frm)
        return v/max(float(np.linalg.norm(v)), 1e-12)

    def follow(node, came, level):
        """The next edge of a stroke: the only one at a degree-two node, else the
        straightest unused continuation. A filter that stops at every junction
        bends a straight street at each side road."""
        options = [k for k in adjacent[node,level] if k in unused]
        if len(adjacent[node,level]) == 2:
            return options[0] if options else None
        incoming = -heading(came, node)
        best = max(options, key=lambda k: (float(np.dot(incoming, heading(k, node))), k), default=None)
        if best is None or float(np.dot(incoming, heading(best, node))) < math.cos(math.radians(STROKE_TURN)):
            return None
        return best

    def walk(node, key, level):
        steps = []
        while key is not None and key in unused:
            unused.remove(key)
            a,b,_ = edges[key]
            target = b if node == a else a
            steps.append((key, node, target))
            node, key = target, follow(target, key, level)
        return steps

    starts = sorted(edges, key=lambda k: (all(len(adjacent[n,edges[k][2]])==2 for n in edges[k][:2]), k))
    for first in starts:
        if first not in unused:
            continue
        a,b,level = edges[first]
        start = a if len(adjacent[a,level]) != 2 else b
        ahead = walk(start, first, level)
        behind = walk(start, follow(start, first, level), level)
        steps = [(k, t, f) for k, f, t in reversed(behind)]+ahead
        refs = [steps[0][1]]+[t for _, _, t in steps]
        run = [(k, f == edges[k][0]) for k, f, _ in steps]
        xy = np.array([to_xy(*nodes[n]) for n in refs])
        along = np.r_[0.,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
        stations = np.linspace(0., along[-1], max(1, math.ceil(along[-1]/STEP))+1)
        xx, yy = (np.interp(stations, along, xy[:, k]) for k in (0,1))
        raw = np.array([sample(x, y) for x, y in zip(xx, yy)])
        # The chain's road class sets the filter: the class carrying most of its length.
        lengths = defaultdict(float)
        for key, _ in run:
            a_, b_, _l = edges[key]
            lengths[_class_radius(way_tags[key[0]])] += float(np.linalg.norm(point(a_)-point(b_)))
        radius = max(lengths, key=lambda r: (lengths[r], r))
        trusted = np.ones(len(raw), dtype=bool)
        if bridges is not None and level[0] <= 0 and not level[1]:
            chain_nodes = set(refs)
            tree, blines, brefs = bridges
            for i, (x, y) in enumerate(zip(xx, yy)):
                q = Point(x, y)
                for k in tree.query(q.buffer(UNDER_BRIDGE)):
                    if not (brefs[int(k)] & chain_nodes) and blines[int(k)].distance(q) < UNDER_BRIDGE:
                        trusted[i] = False
                        break
        if trusted.sum() < 2:
            trusted[:] = True
        fairing = max(FAIRING_LENGTH, radius*FAIRING_CLASS_FACTOR)
        if refs[0] == refs[-1]:
            # Periodic padding also covers small rings; a free endpoint at an
            # arbitrary first OSM node would introduce a crest at the seam.
            step = stations[1]-stations[0]
            pad = math.ceil(max(radius, 8*fairing)/step)
            indices = np.arange(-pad, len(raw)+pad)
            ss = indices*step
            zz = raw[indices % (len(raw)-1)]
            tt = trusted[indices % (len(raw)-1)]
            filtered = fair_profile(ss, smooth(ss,zz,radius,tt), fairing)[pad:pad+len(raw)]
            filtered[0] = filtered[-1] = (filtered[0]+filtered[-1])/2
        else:
            filtered = fair_profile(stations, smooth(stations, raw, radius, trusted), fairing)
        delta = np.abs(filtered-raw)
        count += len(stations)
        max_shift = max(max_shift, float(delta.max()))
        for i in np.flatnonzero((delta > SPIKE) & trusted):
            segment = min(len(run)-1,int(np.searchsorted(along,stations[i],side='right'))-1)
            wid = run[segment][0][0]
            spikes.append({'way': wid, 'station_m': round(float(stations[i]), 3),
                           'chain_start_node': refs[0],
                           'xy': [float(xx[i]), float(yy[i])], 'raw_m': float(raw[i]),
                           'filtered_m': float(filtered[i]), 'correction_m': round(float(delta[i]), 4)})
        node_z = np.interp(along, stations, filtered)
        for nid, z in zip(refs, node_z):
            node_samples[nid].append(float(z))
            node_anchors[nid].append((radius, float(along[-1]), float(z)))
        strokes.append((refs, along, stations, filtered, run, fairing))
    # The through road sets the shared height: first the higher road class,
    # then the longer supported stroke. Averaging every tiny driveway into a
    # main road repeatedly pulls its otherwise smooth profile up and down.
    ground = {nid: max(candidates, key=lambda c:c[:2])[2] for nid,candidates in node_anchors.items()}
    # A source way can switch strokes at a bend/branch. Reconcile complete
    # strokes BEFORE assembling ways, otherwise two independently filtered
    # heights meet in one 2 m interval and create an artificial cliff.
    for refs, along, stations, filtered, run, fairing in strokes:
        node_z = np.interp(along, stations, filtered)
        correction = correction_field(along, [ground[n]-z for n,z in zip(refs,node_z)],
                                      [len(node_samples[n]) > 1 for n in refs],
                                      min_width=2*fairing)
        for i,(key,forward) in enumerate(run):
            edge_samples[key] = (stations,filtered,along[i] if forward else along[i+1],
                                 1 if forward else -1,correction)
    for wid,(refs,xy,along) in ways.items():
        stations = np.unique(np.r_[np.linspace(0.,along[-1],max(1,math.ceil(along[-1]/STEP))+1), along])
        def value(s):
            i = min(len(refs)-2,max(0,int(np.searchsorted(along,s,side='right'))-1))
            if (wid,i) not in edge_samples:
                return sample(*xy[i])
            ss,zz,offset,sign,correction = edge_samples[wid,i]
            at = offset+sign*(s-along[i])
            return float(np.interp(at,ss,zz))+correction(at)
        xx,yy = (np.interp(stations,along,xy[:,k]) for k in (0,1))
        filtered = [value(s) for s in stations]
        node_z = np.interp(along,stations,filtered)
        profiles[wid] = {'refs': refs, 'along': along, 'stations': stations,
                         'xy': xy, 'points': list(zip(xx, yy, filtered)), 'node_z': node_z}
    medians = []
    paired = pair_carriageways(profiles, way_tags, medians)
    # Every node follows the reconciled profile, including non-junction nodes
    # inside a correction's fade. Old pre-correction anchors would undo the
    # reconciliation at each OSM vertex. Average shared paired nodes explicitly
    # instead of making their height depend on dictionary iteration order.
    reconciled = defaultdict(list)
    for p in profiles.values():
        for nid,z in zip(p['refs'], p['node_z']):
            reconciled[nid].append(float(z))
    ground = {nid: sum(zs)/len(zs) for nid,zs in reconciled.items()}
    report = {'version': 1, 'provenance': 'derived/synthetic DEM filtering and structure assumptions',
              'coordinates': 'xy = SUMO projected metres; heights relative to world base_height',
              'station_reference': 'arc length from chain_start_node, possibly across multiple OSM ways',
              'sample_step_m': STEP, 'filter_radius_m': RADIUS, 'samples': count,
              'spike_threshold_m': SPIKE, 'spike_samples': len(spikes),
              'max_filter_shift_m': round(max_shift, 4),
              'class_radius_m': CLASS_RADIUS, 'under_bridge_m': UNDER_BRIDGE,
              'fairing_length_m': FAIRING_LENGTH, 'fairing_class_factor': FAIRING_CLASS_FACTOR,
              'shared_height_policy': 'higher class, then longer stroke; reconcile before way assembly',
              'paired_carriageway_ways': len(paired),
              'medians': medians,
              'worst': sorted(spikes, key=lambda r: (-r['correction_m'], r['way'], r['station_m']))[:100]}
    return profiles, ground, report


def crest_drop(distance, grade):
    """Height below a deck's crest at `distance` from it: parabolic over
    DECK_CURVE metres around the crest, then tangents at `grade`."""
    d = np.abs(distance)
    return np.where(d < DECK_CURVE, grade*d*d/(2*DECK_CURVE), grade*(d-DECK_CURVE/2))


def deck_clearance(profiles, way_refs, levels, clearance, grade):
    """Lift bridge decks over the final profile of every road passing beneath.

    Node heights already clear the road below, but only at OSM nodes: a deck
    between nodes 150 m apart stayed straight, and the road beneath follows its
    own filtered profile, so an overpass ended 2 m above traffic. Every dense
    deck station takes max(deck, below + clearance - grade * distance to the
    crossing). Ends stay where node heights put them; a lift still needed there
    is reported, not hidden by a step."""
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
    ids = [w for w in profiles if len(profiles[w]) >= 2]
    lines = {w: LineString([p[:2] for p in profiles[w]]) for w in ids}
    order = [w for w in ids]
    tree = STRtree([lines[w] for w in order])
    report = {'crossings': 0, 'lifted_ways': 0, 'max_lift_m': 0., 'end_shortfall_m': 0.}
    for w in ids:
        level = levels.get(w, (0, False, False))
        if level[0] <= 0 and not level[1]:
            continue
        pts = profiles[w]
        along = np.r_[0., np.cumsum([math.dist(a[:2], b[:2]) for a, b in zip(pts, pts[1:])])]
        z = np.array([p[2] for p in pts])
        lifted = z.copy()
        own = set(way_refs.get(w, ()))
        for k in tree.query(lines[w]):
            o = order[int(k)]
            olevel = levels.get(o, (0, False, False))
            if o == w or olevel[0] >= max(level[0], 1) or own & set(way_refs.get(o, ())):
                continue
            hit = lines[w].intersection(lines[o])
            for q in getattr(hit, 'geoms', [hit]):
                if q.is_empty or q.geom_type != 'Point':
                    continue
                ops = profiles[o]
                oalong = np.r_[0., np.cumsum([math.dist(a[:2], b[:2]) for a, b in zip(ops, ops[1:])])]
                below = float(np.interp(lines[o].project(q), oalong, [p[2] for p in ops]))
                at = lines[w].project(q)
                # A crest curve, not a tent: parabolic over DECK_CURVE metres
                # around the crossing, then tangents at the ramp grade.
                lifted = np.maximum(lifted, below+clearance-crest_drop(np.abs(along-at), grade))
                report['crossings'] += 1
        lift = lifted-z
        if lift.max() > 1e-3 and len(lift) > 2:
            # Round the joins where the lift starts on the deck's own profile.
            step = max(along[-1]/(len(along)-1), 1e-6)
            kernel = np.exp(-.5*(np.arange(-3*DECK_JOIN, 3*DECK_JOIN+step, step)/DECK_JOIN)**2)
            kernel /= kernel.sum()
            padded = np.r_[np.full(len(kernel)//2, lift[0]), lift, np.full(len(kernel)//2, lift[-1])]
            smooth_lift = np.convolve(padded, kernel, mode='valid')[:len(lift)]
            lift = np.maximum(smooth_lift, lift-.05)
        if lift.max() > 1e-3:
            report['lifted_ways'] += 1
            report['max_lift_m'] = max(report['max_lift_m'], round(float(lift.max()), 3))
            report['end_shortfall_m'] = max(report['end_shortfall_m'], round(float(max(lift[0], lift[-1])), 3))
            # Keep the ends: a lift reaching them fades out over the last 10 m.
            fade = np.clip(np.minimum(along, along[-1]-along)/10., 0., 1.)
            lifted = z+np.where(lift > 0, lift*np.maximum(fade, 0.), 0.)
            profiles[w] = [(x, y, float(v)) for (x, y, _), v in zip(pts, lifted)]
    return report


def pair_key(tags):
    """What makes two one-way ways the carriageways of one road: the name, else the
    route ref, else (unnamed main roads, playtest 2026-10-06 note 1) the class."""
    if tags.get('name'):
        return ('name', tags['name'])
    if tags.get('ref'):
        return ('ref', tags['ref'])
    if tags.get('highway') in ('motorway', 'trunk', 'primary', 'secondary'):
        return ('class', tags['highway'])
    return None


def pair_carriageways(profiles, way_tags, medians=None):
    """Average the profiles of the two one-way carriageways of a divided road.

    Each carriageway samples the DEM on its own line, tens of metres from the
    other, so the directions drifted apart by up to metres. Where an antiparallel
    one-way way of the same name runs within PAIR_DISTANCE, both take the mean;
    the weight fades in and out over PAIR_FADE metres. Returns the changed ways."""
    from shapely.geometry import LineString, Point
    from shapely.strtree import STRtree
    cand = [w for w, t in way_tags.items() if w in profiles and pair_key(t) and
            t.get('oneway') in ('yes', '1', 'true') and not t.get('highway', '').endswith('_link') and
            t.get('highway') not in ('service',) and structure(t) == (0, False, False)]
    if len(cand) < 2:
        return []
    lines = [LineString([p[:2] for p in profiles[w]['points']]) for w in cand]
    index = {w: i for i, w in enumerate(cand)}
    tree = STRtree(lines)
    original = {w: np.array([p[2] for p in profiles[w]['points']]) for w in cand}
    changed = []
    for i, w in enumerate(cand):
        pts = profiles[w]['points']
        if len(pts) < 2:
            continue
        stations = profiles[w]['stations']
        partner_z, weight, partner = np.zeros(len(pts)), np.zeros(len(pts)), [None]*len(pts)
        options = []
        for k, (x, y, _) in enumerate(pts):
            a, b = pts[max(0, k-1)], pts[min(len(pts)-1, k+1)]
            u = np.subtract(b[:2], a[:2]); u = u/max(np.linalg.norm(u), 1e-9)
            q = Point(x, y)
            found = {}
            for j in tree.query(q.buffer(PAIR_DISTANCE)):
                o = cand[int(j)]
                if o == w or pair_key(way_tags[o]) != pair_key(way_tags[w]):
                    continue
                d = lines[int(j)].distance(q)
                if d > PAIR_DISTANCE:
                    continue
                s = lines[int(j)].project(q)
                p0, p1 = lines[int(j)].interpolate(max(0., s-1.)), lines[int(j)].interpolate(s+1.)
                v = np.subtract((p1.x, p1.y), (p0.x, p0.y)); v = v/max(np.linalg.norm(v), 1e-9)
                if float(np.dot(u, v)) > -.8:
                    continue
                ops = profiles[o]['points']
                along = np.r_[0., np.cumsum([math.dist(c[:2], e[:2]) for c, e in zip(ops, ops[1:])])]
                found[o] = (d, float(np.interp(s, along, original[o])))
            options.append(found)
        # One partner per stretch: the way that is nearest at most stations. A
        # same-named slip road running alongside must not take over for a few
        # stations (a 0.3 m step on Beresteiskyi avenue at a side street).
        votes = defaultdict(int)
        for found in options:
            if found:
                votes[min(found, key=lambda o: found[o][0])] += 1
        for k, found in enumerate(options):
            if found:
                o = max(found, key=lambda o: (votes[o], -found[o][0]))
                partner_z[k], weight[k] = found[o][1], 1.
                partner[k] = o
        if medians is not None and way_tags[w].get('highway') in MEDIAN_CLASSES:
            # Median line of a divided main road: midway to the partner's centreline.
            run = []
            for k, (x, y, _) in enumerate(pts):
                o = partner[k]
                if o is None or o < w or options[k][o][0] > MEDIAN_MAX:
                    if len(run) > 1:
                        medians.append({'ways': [w, last], 'points': run})
                    run = []
                    continue
                j = index[o]
                q = lines[j].interpolate(lines[j].project(Point(x, y)))
                run.append(((x+q.x)/2, (y+q.y)/2))
                last = o
            if len(run) > 1:
                medians.append({'ways': [w, last], 'points': run})
        if not weight.any():
            continue
        # Fade the coupling in and out instead of switching it at a station.
        reach = PAIR_FADE/2
        soft = np.array([weight[(stations >= s-reach) & (stations <= s+reach)].mean() for s in stations])
        on = weight > 0
        diff = np.interp(stations, stations[on], (partner_z-original[w])[on])
        # A partner change between ways still leaves a small jump; spread it.
        sigma = PAIR_FADE/3
        diff = np.array([np.average(diff, weights=np.exp(-.5*((stations-s)/sigma)**2)) for s in stations])
        z = original[w]+.5*soft*diff
        profiles[w]['points'] = [(x, y, float(v)) for (x, y, _), v in zip(pts, z)]
        profiles[w]['node_z'] = np.interp(profiles[w]['along'], stations, z)
        changed.append(w)
    return changed


def _smoothstep(t):
    t = min(1., max(0., t))
    return t*t*(3-2*t)


def correction_field(along, deltas, fixed, min_width=CORRECTION_MIN):
    """Height correction along a way, exact at its shared and corrected source nodes.

    Shared nodes take a common height, so the filtered profile is corrected
    there. Interpolating between node corrections stopped each one at the next
    OSM node, often 2 m away: a 0.5 m tent on a residential street. Only nodes
    shared with another way (`fixed`) or carrying a correction must stay exact.
    Corrections between close exact nodes blend into each other; otherwise each
    one fades out over a width that keeps its added grade small."""
    keys = [(float(s), float(d)) for s, d, f in zip(along, deltas, fixed) if f or abs(d) > 1e-4]
    width = [max(min_width, min(CORRECTION_MAX, abs(d)/CORRECTION_GRADE)) for _, d in keys]
    def at(s):
        if not keys:
            return 0.
        i = int(np.searchsorted([k[0] for k in keys], s, side='right'))-1
        left = (keys[i], width[i]) if i >= 0 else None
        right = (keys[i+1], width[i+1]) if i+1 < len(keys) else None
        if left and abs(s-left[0][0]) < 1e-9:
            return left[0][1]
        if left and right and right[0][0]-left[0][0] <= left[1]+right[1]:
            (s0, d0), (s1, d1) = left[0], right[0]
            return d0+(d1-d0)*_smoothstep((s-s0)/(s1-s0))
        value = 0.
        if left:
            value += left[0][1]*(1-_smoothstep((s-left[0][0])/left[1]))
        if right:
            value += right[0][1]*(1-_smoothstep((right[0][0]-s)/right[1]))
        return value
    return at


def _rank(tags):
    kind = tags.get('highway', '')
    return CLASS_RANK.get(kind.removesuffix('_link'), 8)


def _width(tags):
    try:
        lanes = int(str(tags.get('lanes', '')).split(';')[0])
    except ValueError:
        lanes = 2 if tags.get('oneway') in ('yes', '1', 'true', '-1') else 2
    return max(1, lanes)*LANE_WIDTH


def mouths(profiles, way_tags):
    """way -> [(node index, plateau half-length)] where the way meets a higher-class road."""
    at_node = defaultdict(list)
    for wid, p in profiles.items():
        for n in set(p['refs']):
            at_node[n].append(wid)
    out = defaultdict(list)
    for n, wids in at_node.items():
        if len(wids) < 2:
            continue
        for wid in wids:
            mine = _rank(way_tags.get(wid, {}))
            major = [o for o in wids if o != wid and _rank(way_tags.get(o, {})) < mine]
            if not major:
                continue
            reach = max(_width(way_tags.get(o, {})) for o in major)/2+MOUTH_MARGIN
            for k, r in enumerate(profiles[wid]['refs']):
                if r == n:
                    out[wid].append((k, reach))
    return out


def plateau(knots, z, anchors):
    """Hold each anchor height within its reach, then carry the offset to the road's own
    profile and fade it out; the added grade stays within 1.5 x MOUTH_GRADE."""
    z = np.asarray(z, dtype=float).copy()
    for s0, h, reach in anchors:
        base = z.copy()
        for side in (1, -1):
            edge_s = s0+side*reach
            if not knots[0] <= edge_s <= knots[-1]:
                edge_s = min(knots[-1], max(knots[0], edge_s))
            offset = h-float(np.interp(edge_s, knots, base))
            fade = min(MOUTH_FADE[1], max(MOUTH_FADE[0], abs(offset)/MOUTH_GRADE))
            d = side*(knots-s0)
            mask = d >= 0
            inside = mask & (d <= reach)
            beyond = mask & (d > reach)
            z[inside] = h
            z[beyond] = base[beyond]+offset*(1-np.array([_smoothstep((v-reach)/fade) for v in d[beyond]]))
    return z


def constrained_profiles(profiles, heights, structure_ways, way_tags=None):
    """Carry shared-node/structure constraints into the dense, filtered profiles.

    Insert source nodes as exact knots. Bridges use the existing constrained deck
    profile; ground roads retain DEM detail plus a smooth constraint correction.
    With ``way_tags``, a minor road also levels out at the mouth of a major road.
    """
    result = {}
    uses = defaultdict(int)
    for p in profiles.values():
        for n in set(p['refs']):
            uses[n] += 1
    mouth = mouths(profiles, way_tags) if way_tags else {}
    for wid, p in profiles.items():
        along = p['along']
        values = [heights[n] for n in p['refs']]
        fixed = [uses[n] > 1 or k in (0, len(p['refs'])-1) for k, n in enumerate(p['refs'])]
        correction = correction_field(along, [z-g for z, g in zip(values, p['node_z'])], fixed)
        knots = np.unique(np.r_[p['stations'], along])
        base = np.interp(knots, p['stations'], [v[2] for v in p['points']])
        xx, yy = (np.interp(knots, along, p['xy'][:, k]) for k in (0, 1))
        out = []
        for s, x, y, z in zip(knots, xx, yy, base):
            i = min(len(along)-2, max(0, int(np.searchsorted(along, s, side='right'))-1))
            length = along[i+1]-along[i]
            t = (s-along[i])/length if length > 1e-9 else 0.
            z = (values[i]+(values[i+1]-values[i])*t if wid in structure_ways else
                 z+correction(s))
            if out and math.dist(out[-1][:2], (x, y)) < 1e-7:
                continue
            out.append((float(x), float(y), float(z)))
        if mouth.get(wid) and wid not in structure_ways and len(out) > 1:
            s = np.r_[0., np.cumsum([math.dist(a[:2], b[:2]) for a, b in zip(out, out[1:])])]
            anchors = [(float(along[k]), values[k], reach) for k, reach in mouth[wid]]
            zz = plateau(s, [v[2] for v in out], anchors)
            out = [(x, y, float(v)) for (x, y, _), v in zip(out, zz)]
        result[wid] = out
    return result
