"""Prepare OSM plus all DEM tiles needed by the selected area and complete ways."""
import copy
import math
from pathlib import Path

from PIL import Image

from .context import BuildContext, read_json, scratch_directory, sha256
from .errors import OfflineMissing, SourceError
from .packages import atomic_json, available_packages
from .sources import area_key, coverage, now, snapshots, validate_osm


def tile_xy(lon, lat, zoom):
    n = 2**zoom
    return (min(n-1, max(0, int((lon+180)/360*n))),
            min(n-1, max(0, int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n))))


def terrain_keys(cfg, root):
    """Include complete way envelopes and a 500 m margin for SUMO junction geometry.

    A relation may bring in geometry outside the requested bbox. Preparing only the
    rectangle would omit the DEM for those nodes and break offline road profiles.
    """
    zoom = cfg['terrain_zoom']
    keys = set()
    def add(bounds):
        w, s, e, n = bounds
        lat = min(84.9, max(abs(s), abs(n)))
        dx = .5 / (111.32 * math.cos(math.radians(lat)))
        x0, y0 = tile_xy(max(-180, w-dx), min(84.999, n+.005), zoom)
        x1, y1 = tile_xy(min(180, e+dx), max(-84.999, s-.005), zoom)
        keys.update((x, y) for x in range(x0, x1+1) for y in range(y0, y1+1))
    add(cfg['bbox'])
    nodes = {n.get('id'): (float(n.get('lon')), float(n.get('lat'))) for n in root.findall('node')}
    for lon, lat in nodes.values():
        keys.add(tile_xy(lon, lat, zoom))
    for way in root.findall('way'):
        points = [nodes[nd.get('ref')] for nd in way.findall('nd')]
        if points:
            lons, lats = zip(*points)
            add((min(lons), min(lats), max(lons), max(lats)))
    return [f'terrain/{zoom}/{x}/{y}.png' for x, y in sorted(keys)]


def valid_tile(path):
    try:
        with Image.open(path) as img:
            if img.format != 'PNG' or img.size != (256, 256) or img.mode != 'RGB':
                return False
            img.verify()
        stamp = path.with_suffix('.sha256')
        return not stamp.exists() or stamp.read_text(encoding='ascii').strip() == sha256(path)
    except (OSError, ValueError, SyntaxError):
        return False


def ensure_tile(context, relative):
    path = context.raw/relative
    if not valid_tile(path):
        if context.offline:
            raise OfflineMissing(f'Offline input is missing or damaged: {relative}')
        path.parent.mkdir(parents=True, exist_ok=True)
        with scratch_directory(path.parent) as tmp:
            dest = Path(tmp)/'tile.png'
            url = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/' + relative.removeprefix('terrain/')
            context.notify('download', source='terrain', url=url)
            context.download(url, dest)
            if not valid_tile(dest):
                raise SourceError(f'Invalid DEM PNG: {relative}')
            dest.replace(path)
        # Tile and stamp are verified independently; a partial stamp cannot bless data.
        stamp = path.with_suffix('.sha256')
        stamp.write_text(sha256(path), encoding='ascii')
    return path


def prepare_area(config, raw, *, offline=False, refresh=False, package=None, emit=lambda *a, **k: None):
    from .world import validate_config
    from .core.prepare import fetch
    cfg = validate_config(copy.deepcopy(config))
    if offline and refresh:
        raise ValueError('Refreshing needs online source mode')
    cfg['refresh'] = refresh
    if package:
        cfg['package'] = package
    raw = Path(raw).resolve()
    raw.mkdir(parents=True, exist_ok=True)
    with scratch_directory(raw, 'prepare-') as tmp:
        ctx = BuildContext(Path(tmp), raw, Path.cwd(), offline=offline, emit=emit)
        root = fetch(cfg, ctx)
        keys = terrain_keys(cfg, root)
        for i, key in enumerate(keys):
            emit('stage', stage='terrain', progress=.2+.75*i/max(1, len(keys)))
            ensure_tile(ctx, key)
        geometry = coverage(cfg)
        meta = {'name': cfg['name'], 'bbox': cfg['bbox'], 'center': cfg['center'],
                'terrain_zoom': cfg['terrain_zoom'], 'prepared_at': now(),
                'osm_file': cfg['osm_file'], 'osm_sha256': sha256(raw/cfg['osm_file']),
                'terrain': {key: sha256(raw/key) for key in keys}}
        atomic_json(raw/'areas'/(area_key(geometry)+'.json'), meta)
    return {'action': 'prepare', 'osm_ready': True, 'terrain_ready': True, 'terrain_tiles': len(keys), **meta}


def saved_areas(raw):
    result = []
    for path in (Path(raw)/'areas').glob('*.json'):
        try:
            result.append(read_json(path))
        except (OSError, ValueError):
            continue
    return result


def status(cfg, raw):
    geometry = coverage(cfg)
    found = snapshots(raw, geometry)
    keys = terrain_keys(cfg, validate_osm(found[0][0])) if found else []
    return {'action': 'status', 'osm_ready': bool(found),
            'terrain_ready': bool(keys) and all(valid_tile(Path(raw)/key) for key in keys),
            'terrain_tiles': len(keys), 'terrain_missing': sum(not valid_tile(Path(raw)/key) for key in keys),
            'packages': available_packages(raw), 'covering_packages': available_packages(raw, geometry),
            'areas': saved_areas(raw)}
