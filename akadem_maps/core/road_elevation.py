"""Distance-based road elevation, derived from DEM, never surveyed geometry.

Filter uniformly spaced samples, not OSM vertices. A robust local linear fit
preserves constant grades, including at the ends, while rejecting short spikes.
Structure and paired-carriageway constraints are applied by prepare afterwards.
"""
import math
from collections import defaultdict

import numpy as np

from .road_profiles import profile_z
from .surface_audit import structure

STEP = 2.0
RADIUS = 24.0
SPIKE = 1.0
STROKE_TURN = 35.  # degrees; a straighter continuation through a junction is one stroke


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


def smooth(distances, heights, radius=RADIUS):
    s, raw = np.asarray(distances), np.asarray(heights, dtype=float)
    if not np.all(np.isfinite(raw)):
        raise ValueError('Non-finite road DEM sample')
    if len(raw) < 3:
        return raw.copy()
    reliability = np.ones(len(raw))
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
            reliability = np.minimum(1., (2.5*scale/np.maximum(residual, 1e-12))**2)
    return result


def ground_profiles(root, nodes, tags, drivable, to_xy, sample):
    profiles, node_samples, spikes = {}, defaultdict(list), []
    ways, edges, adjacent = {}, {}, defaultdict(list)
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
        level = structure(tags(way))
        for i,(a,b) in enumerate(zip(refs,refs[1:])):
            if along[i+1]-along[i] < 1e-7:
                continue
            key = (wid,i)
            edges[key] = (a,b,level)
            adjacent[a,level].append(key)
            adjacent[b,level].append(key)
    # Continue through degree-two source nodes, including OSM way boundaries.
    # True branches anchor chains; a nearby disconnected road is never sampled.
    unused, edge_samples = set(edges), {}
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
        if refs[0] == refs[-1] and along[-1] > 2*RADIUS:
            left, right = stations[:-1] > along[-1]-RADIUS, stations[1:] < RADIUS
            ss = np.r_[stations[:-1][left]-along[-1],stations,stations[1:][right]+along[-1]]
            zz = np.r_[raw[:-1][left],raw,raw[1:][right]]
            filtered = smooth(ss,zz)[sum(left):sum(left)+len(raw)]
            filtered[0] = filtered[-1] = (filtered[0]+filtered[-1])/2
        else:
            filtered = smooth(stations, raw)
        delta = np.abs(filtered-raw)
        count += len(stations)
        max_shift = max(max_shift, float(delta.max()))
        for i in np.flatnonzero(delta > SPIKE):
            segment = min(len(run)-1,int(np.searchsorted(along,stations[i],side='right'))-1)
            wid = run[segment][0][0]
            spikes.append({'way': wid, 'station_m': round(float(stations[i]), 3),
                           'chain_start_node': refs[0],
                           'xy': [float(xx[i]), float(yy[i])], 'raw_m': float(raw[i]),
                           'filtered_m': float(filtered[i]), 'correction_m': round(float(delta[i]), 4)})
        node_z = np.interp(along, stations, filtered)
        for nid, z in zip(refs, node_z):
            node_samples[nid].append(float(z))
        for i,(key,forward) in enumerate(run):
            edge_samples[key] = (stations,filtered,along[i] if forward else along[i+1],1 if forward else -1)
    for wid,(refs,xy,along) in ways.items():
        stations = np.linspace(0.,along[-1],max(1,math.ceil(along[-1]/STEP))+1)
        def value(s):
            i = min(len(refs)-2,max(0,int(np.searchsorted(along,s,side='right'))-1))
            if (wid,i) not in edge_samples:
                return sample(*xy[i])
            ss,zz,offset,sign = edge_samples[wid,i]
            return float(np.interp(offset+sign*(s-along[i]),ss,zz))
        xx,yy = (np.interp(stations,along,xy[:,k]) for k in (0,1))
        filtered = [value(s) for s in stations]
        node_z = np.interp(along,stations,filtered)
        profiles[wid] = {'refs': refs, 'along': along, 'stations': stations,
                         'xy': xy, 'points': list(zip(xx, yy, filtered)), 'node_z': node_z}
    ground = {nid: sum(zs)/len(zs) for nid, zs in node_samples.items()}
    report = {'version': 1, 'provenance': 'derived/synthetic DEM filtering and structure assumptions',
              'coordinates': 'xy = SUMO projected metres; heights relative to world base_height',
              'station_reference': 'arc length from chain_start_node, possibly across multiple OSM ways',
              'sample_step_m': STEP, 'filter_radius_m': RADIUS, 'samples': count,
              'spike_threshold_m': SPIKE, 'spike_samples': len(spikes),
              'max_filter_shift_m': round(max_shift, 4),
              'worst': sorted(spikes, key=lambda r: (-r['correction_m'], r['way'], r['station_m']))[:100]}
    return profiles, ground, report


def constrained_profiles(profiles, heights, structure_ways):
    """Carry shared-node/structure constraints into the dense, filtered profiles.

    Insert source nodes as exact knots. Bridges use the existing constrained deck
    profile; ground roads retain DEM detail plus a monotone constraint correction.
    """
    result = {}
    for wid, p in profiles.items():
        along = p['along']
        values = [heights[n] for n in p['refs']]
        corrections = [(float(s), 0., float(z-g)) for s, z, g in zip(along, values, p['node_z'])]
        knots = np.unique(np.r_[p['stations'], along])
        base = np.interp(knots, p['stations'], [v[2] for v in p['points']])
        xx, yy = (np.interp(knots, along, p['xy'][:, k]) for k in (0, 1))
        out = []
        for s, x, y, z in zip(knots, xx, yy, base):
            i = min(len(along)-2, max(0, int(np.searchsorted(along, s, side='right'))-1))
            length = along[i+1]-along[i]
            t = (s-along[i])/length if length > 1e-9 else 0.
            z = (values[i]+(values[i+1]-values[i])*t if wid in structure_ways else
                 z+profile_z(corrections, i, t))
            if out and math.dist(out[-1][:2], (x, y)) < 1e-7:
                continue
            out.append((float(x), float(y), float(z)))
        result[wid] = out
    return result
