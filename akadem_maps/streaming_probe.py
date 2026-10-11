"""Feasibility measurements, deliberately separate from the installed-map workflow.

These probes measure the current full-quality pipeline; they are not a streaming
service. Reports distinguish completed measurements, timeouts and untested gates.
"""
import math
from pathlib import Path
import time

from .context import read_json


def square(lon, lat, size):
    """Metric square, approximated in the local geodesic frame; never wrap longitude."""
    from pyproj import Geod
    from .world import validate_config
    if not all(math.isfinite(v) for v in (lon, lat, size)) or size <= 0:
        raise ValueError('Coordinates and positive size must be finite')
    if not -180 <= lon <= 180 or not -85 < lat < 85:
        raise ValueError('Point outside supported longitude/latitude range')
    geod = Geod(ellps='WGS84')
    west = geod.fwd(lon, lat, 270, size / 2)[0]
    east = geod.fwd(lon, lat, 90, size / 2)[0]
    south = geod.fwd(lon, lat, 180, size / 2)[1]
    north = geod.fwd(lon, lat, 0, size / 2)[1]
    bbox = [west, south, east, north]
    validate_config({'id': 'probe', 'name': 'probe', 'bbox': bbox})
    return bbox


class StageClock:
    """Exclusive stage intervals, including repeated events and failed final stages."""
    def __init__(self, sink, clock=time.perf_counter):
        self.clock, self.sink = clock, sink
        self.start = self.last = clock()
        self.stage = 'setup'
        self.seconds = {}

    def close_interval(self):
        now = self.clock()
        self.seconds[self.stage] = self.seconds.get(self.stage, 0.) + now - self.last
        self.last = now

    def emit(self, event, **data):
        if event == 'stage':
            self.close_interval()
            self.stage = data['stage']
        self.sink({'event': event, 'elapsed_s': self.clock() - self.start,
                   'monotonic_s': self.clock(), **data})

    def finish(self):
        self.close_interval()
        return {k: round(v, 6) for k, v in self.seconds.items()}


def acceptance(elapsed, collision, traffic, mode):
    """A fast build alone never certifies start-to-control or a 20-minute drive."""
    ready = bool(collision and collision.get('spawn_supported') and
                 traffic and traffic.get('vehicles', 0) > 0 and
                 not traffic.get('collisions', 0) and not traffic.get('teleports', 0))
    return {'pipeline_ready': ready, 'pipeline_within_30s': ready and elapsed <= 30,
            'cold_start_to_control': 'not_tested', 'cache_mode': mode,
            'twenty_minute_drive': 'not_tested', 'bounded_memory': 'not_tested',
            'offline_boundary_stop': 'not_tested', 'streaming_release': False}


class SurfaceWorld:
    """Road surfaces in their own projection, queried in geographic coordinates.

    Matching uses topology and absolute height, so a bridge cannot be substituted
    by the road below it. Each world's base_height and SUMO offset are respected.
    """
    def __init__(self, folder):
        import sumolib
        from .core.surface_audit import TriangleIndex, surfaces, source_metadata
        self.folder = Path(folder)
        self.index = read_json(self.folder / 'index.json')
        self.net = sumolib.net.readNet(str(self.folder / 'network.net.xml'))
        lane_meta, junction_meta = source_metadata(self.folder)
        self.lane_meta, self.junction_meta = lane_meta, junction_meta
        tiles = (read_json(self.folder / 'tiles' / (name + '.json'))
                 for name in self.index['tiles'])
        self.mesh = TriangleIndex(surfaces(tiles, lane_meta, junction_meta))

    def geo(self, point):
        ox, oy = self.index['offset']
        return self.net.convertXY2LonLat(point[0] + ox, point[1] + oy)

    def hits(self, lon, lat):
        x, y = self.net.convertLonLat2XY(lon, lat)
        ox, oy = self.index['offset']
        return [(h + self.index['base_height'], sid, self.mesh.metadata[sid])
                for h, sid in self.mesh.hits(x - ox, y - oy)]


def compare_surfaces(reference, candidate, bbox=None, step=2., tolerance=.05):
    """Probe lane centres and both wheel tracks against a monolithic reference.

    Optional bbox limits the check to an overlap/border band. Missing reference
    surfaces are reported separately, never removed from the denominator.
    """
    from .core.surface_audit import stations, xyz
    if not math.isfinite(step) or step <= 0 or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('Require positive finite step and nonnegative tolerance')
    ref, other = SurfaceWorld(reference), SurfaceWorld(candidate)
    bbox = bbox or other.index['bbox']
    from .world import validate_config
    validate_config({'id': 'probe', 'name': 'probe', 'bbox': bbox})
    samples = missing = reference_missing = mismatched = ambiguous = 0
    maximum, examples = 0., []
    for lane in ref.index['lanes']:
        if lane.get('internal'):
            junction_id = lane.get('edge', lane['id'].rsplit('_', 1)[0])[1:].rsplit('_', 1)[0]
            expected_meta = getattr(ref, 'junction_meta', {}).get(junction_id, {})
        else:
            expected_meta = getattr(ref, 'lane_meta', {}).get(lane['id'], {})
        points = list(stations([xyz(p) for p in lane['points']], step))
        for i, (_, p) in enumerate(points):
            q = points[min(i + 1, len(points) - 1)][1] if i + 1 < len(points) else points[max(0, i - 1)][1]
            length = math.hypot(q[0] - p[0], q[1] - p[1])
            nx, ny = ((q[1] - p[1]) / length, (p[0] - q[0]) / length) if length else (0., 0.)
            for lateral in (-min(.8, lane.get('width', 3.) / 4), 0., min(.8, lane.get('width', 3.) / 4)):
                lon, lat = ref.geo((p[0] + nx * lateral, p[1] + ny * lateral))
                if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                    continue
                samples += 1
                a, b = ref.hits(lon, lat), other.hits(lon, lat)
                if expected_meta.get('levels'):
                    levels = set(map(tuple, expected_meta['levels']))
                    a = [(h, sid, m) for h, sid, m in a
                         if levels & set(map(tuple, m.get('levels', ())))]
                status, delta = None, None
                if not a:
                    reference_missing += 1
                    status = 'reference_missing'
                else:
                    expected = p[2] + ref.index['base_height']
                    height, owner, meta = min(a, key=lambda h: abs(h[0] - expected))
                    # Do not select a different bridge/ground layer just because it is nearby.
                    compatible = [(h, sid) for h, sid, m in b
                                  if (sid == owner or set(meta.get('ways', ())) & set(m.get('ways', ())))
                                  and set(map(tuple, meta.get('levels', ()))) == set(map(tuple, m.get('levels', ())))]
                    if not b:
                        missing += 1
                        status = 'candidate_missing'
                    elif not compatible:
                        ambiguous += 1
                        status = 'topology_unmatched'
                    else:
                        delta = min(abs(h - height) for h, _ in compatible)
                        maximum = max(maximum, delta)
                        if delta > tolerance:
                            mismatched += 1
                            status = 'height_difference'
                if status and len(examples) < 30:
                    examples.append({'lon': lon, 'lat': lat, 'lane': lane['id'],
                                     'status': status, 'delta_m': delta})
    return {'samples': samples, 'candidate_missing': missing, 'reference_missing': reference_missing,
            'topology_unmatched': ambiguous, 'over_tolerance': mismatched,
            'max_height_difference_m': maximum, 'tolerance_m': tolerance, 'bbox': bbox,
            'passed': samples > 0 and not (missing or reference_missing or mismatched or ambiguous),
            'examples': examples, 'runtime_verified': False}
