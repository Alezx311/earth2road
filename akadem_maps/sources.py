"""Verified, immutable OSM snapshots keyed by coverage and selection rules, not map ID."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
import urllib.parse
import xml.etree.ElementTree as ET

from .context import atomic_directory, contained, read_json, scratch_directory, sha256, write_json
from .errors import NetworkError, NoRoads, OfflineMissing, SourceError

# Bump whenever the Overpass/PBF object selection or reference closure changes.
SELECTION = 'ways-pois-landmarks-restrictions-multipolygons-recursive-v3'
OVERPASS_BUDGET = 180


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_osm(path, require_roads=True):
    from .core.prepare import drivable
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise SourceError(f'Invalid OSM XML: {exc}') from exc
    if root.tag != 'osm':
        raise SourceError('Input is not an OSM XML document')
    if root.find('remark') is not None:
        raise SourceError('Overpass returned incomplete data: ' + (root.findtext('remark') or 'remark'))
    objects = {kind: {o.get('id'): o for o in root.findall(kind)} for kind in ('node', 'way', 'relation')}
    for kind, entries in objects.items():
        if None in entries or len(entries) != len(root.findall(kind)):
            raise SourceError(f'Invalid or duplicate {kind} IDs')
    for node in objects['node'].values():
        try:
            lon, lat = float(node.get('lon')), float(node.get('lat'))
            if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError('coordinates out of range')
        except (ValueError, TypeError) as exc:
            raise SourceError(f'Invalid OSM node {node.get("id")}: coordinates') from exc
    for way in objects['way'].values():
        refs = way.findall('nd')
        if len(refs) < 2 or any(nd.get('ref') not in objects['node'] for nd in refs):
            raise SourceError(f'Incomplete OSM way {way.get("id")}: missing nodes')
    for relation in objects['relation'].values():
        for member in relation.findall('member'):
            if member.get('ref') not in objects.get(member.get('type'), {}):
                raise SourceError(f'Incomplete OSM relation {relation.get("id")}: missing member')
    if require_roads and not any(drivable({t.get('k'): t.get('v') for t in w.findall('tag')})
                                 for w in objects['way'].values()):
        raise NoRoads('OSM input has no suitable passenger roads')
    return root


def coverage(cfg):
    # Polygon extracts are only reusable for that exact polygon; rectangles can serve
    # any contained area. Do not infer coverage from the object coordinate envelope.
    from .core import corridor
    if corridor.shaped(cfg):
        raise ValueError('Polygon coverage needs the resolved area')
    from shapely.geometry import box, mapping
    return mapping(box(*cfg['bbox']))


def area_key(geometry):
    value = json.dumps([SELECTION, geometry], sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def snapshots(raw, geometry=None):
    from shapely.geometry import shape
    from shapely.errors import ShapelyError
    requested = shape(geometry) if geometry else None
    found = []
    for stamp in (Path(raw) / 'snapshots').glob('*/*/snapshot.json'):
        try:
            meta = read_json(stamp)
            if meta['selection'] != SELECTION:
                continue
            if requested is not None and not shape(meta['coverage']).covers(requested):
                continue
            path = stamp.parent / 'source.osm'
            if sha256(path) != meta['sha256']:
                continue
            validate_osm(path)
            found.append((path, meta))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, SourceError, ShapelyError):
            continue
    # Prefer the smallest covering snapshot; newest revision for the same extent.
    found.sort(key=lambda item: item[1]['created_at'], reverse=True)
    found.sort(key=lambda item: shape(item[1]['coverage']).area)
    return found


def publish(raw, path, geometry, source):
    validate_osm(path)
    digest = sha256(path)
    dest = Path(raw) / 'snapshots' / area_key(geometry) / digest
    meta = {'selection': SELECTION, 'coverage': geometry, 'sha256': digest,
            'created_at': now(), 'source': source, 'bytes': Path(path).stat().st_size,
            'license': 'ODbL-1.0; © OpenStreetMap contributors'}
    if dest.exists():
        # Never replace a good previous revision, even during refresh.
        if sha256(dest/'source.osm') != digest:
            raise SourceError(f'Damaged immutable snapshot: {dest}')
        return dest/'source.osm', read_json(dest/'snapshot.json')
    try:
        with atomic_directory(dest) as stage:
            shutil.copyfile(path, stage/'source.osm')
            write_json(stage/'snapshot.json', meta)
    except FileExistsError:
        if sha256(dest/'source.osm') != digest:
            raise SourceError(f'Concurrent snapshot checksum mismatch: {dest}')
    return dest/'source.osm', meta


def overpass(cfg, context, dest):
    w, s, e, n = cfg['bbox']
    timeout = min(120, int(cfg.get('overpass_timeout', 120)))
    maxsize = int(cfg.get('overpass_maxsize', 256 * 1024 * 1024))
    bbox = f'{s},{w},{n},{e}'
    from .core.landmarks import TAGS
    landmark_query = ''.join(f'{kind}["{key}"~"^({"|".join(sorted(values))})$"]({bbox});'
                             for kind in ('node', 'relation') for key, values in sorted(TAGS.items()))
    q = (f'[out:xml][timeout:{timeout}][maxsize:{maxsize}];(way({bbox});'
         f'node["amenity"="fuel"]({bbox});'
         f'node["shop"~"^(supermarket|hypermarket|mall|doityourself|department_store)$"]({bbox});'
         f'{landmark_query}relation["type"="restriction"]({bbox});relation["type"="multipolygon"]({bbox}););'
         '(._;>>;);out body;')
    urls = list(dict.fromkeys([cfg['overpass']] + cfg.get('overpass_mirrors', [])))
    deadline = time.monotonic() + OVERPASS_BUDGET
    failures = []
    retry_at = {}
    # One attempt per mirror. Retry-After is retained per host if a URL repeats under
    # a different path. No internal HTTP retries can multiply the total time budget.
    for i, url in enumerate(urls):
        host = urllib.parse.urlsplit(url).hostname
        delay = max(0, retry_at.get(host, 0) - time.monotonic())
        if time.monotonic() + delay >= deadline:
            continue
        if delay:
            time.sleep(delay)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        context.notify('download', source='overpass', url=url,
                       query_url=url+'?'+urllib.parse.urlencode({'data': q}))
        try:
            # Reserve a fair slice for the remaining mirrors.
            context.download(url, dest, q, max_time=remaining / (len(urls) - i))
            validate_osm(dest)
            return url
        except NoRoads:
            raise  # A complete empty selection is not a busy server.
        except (RuntimeError, OSError, ValueError) as exc:
            dest.unlink(missing_ok=True)
            cause = exc.__cause__ or exc
            retry_at[host] = time.monotonic() + getattr(cause, 'retry_after', 0)
            failures.append(f'{host}: {cause}')
            if i + 1 < len(urls):
                context.notify('warning', message=f'{failures[-1]}; trying {urllib.parse.urlsplit(urls[i+1]).hostname}')
    raise NetworkError(f'Could not download OpenStreetMap data from Overpass ({"; ".join(failures)}). '
                       'Use a local package or try again later (180 s total budget).')


def acquire(cfg, context, geometry):
    """Explicit/legacy input, verified snapshot, covered PBF, then bounded Overpass."""
    from .core import osm_extract
    from .packages import available_packages, verify_package
    from shapely.geometry import shape
    raw = context.raw
    raw.mkdir(parents=True, exist_ok=True)
    refresh = cfg.get('refresh', False)
    # Old map-specific files are accepted only for that ID or explicit osm_file;
    # they are never indexed as general coverage without independent provenance.
    legacy = contained(raw, cfg.get('osm_file', cfg['id'] + '.osm'))
    if legacy.exists() and not refresh:
        validate_osm(legacy)
        stamp = legacy.parent/'snapshot.json'
        if stamp.exists() and legacy.name == 'source.osm':
            meta = read_json(stamp)
            if meta.get('sha256') != sha256(legacy):
                raise SourceError('Explicit snapshot checksum mismatch')
            if cfg.get('local_visual_dna') and meta.get('selection') != SELECTION:
                raise SourceError('Local Visual DNA needs a snapshot with landmark selection v3; re-extract the source')
            if not shape(meta['coverage']).covers(shape(geometry)):
                raise SourceError('Explicit snapshot does not cover the selected area')
            return legacy, meta
        return legacy, {'source': 'explicit-or-legacy-input', 'sha256': sha256(legacy),
                        'coverage': None, 'created_at': None}
    if cfg.get('osm_file') and not refresh:
        raise OfflineMissing(f'Offline input is missing: {cfg["osm_file"]}')
    if cfg.get('source_kind') == 'synthetic':
        raise OfflineMissing('Synthetic worlds require explicit local inputs; real OSM sources are not synthetic data')
    if not refresh:
        found = snapshots(raw, geometry)
        if found:
            path, meta = found[0]
            if shape(meta['coverage']).equals(shape(geometry)):
                return path, meta
            with scratch_directory(raw, 'cut-') as tmp:
                cut = Path(tmp)/'source.osm'
                osm_extract.extract(path, cut, cfg['bbox'], shape(geometry))
                return publish(raw, cut, geometry, {'kind': 'snapshot', 'sha256': meta['sha256'], 'origin': meta['source']})
    candidates = available_packages(raw, geometry, cfg.get('package'))
    for package in candidates:
        try:
            context.progress('local_extract', .05)
            context.notify('source', kind='pbf', name=package['name'])
            pbf = verify_package(package)
            with scratch_directory(raw, 'cut-') as tmp:
                cut = Path(tmp)/'source.osm'
                osm_extract.extract(pbf, cut, cfg['bbox'], shape(geometry))
                return publish(raw, cut, geometry, {'kind': 'pbf', 'id': package['id'],
                                                    'sha256': package['sha256'], 'origin': package['source']})
        except (SourceError, OSError, RuntimeError) as exc:
            if cfg.get('package'):
                raise
            context.notify('warning', message=f'Local package {package["id"]}: {exc}')
    if context.offline:
        raise OfflineMissing('Offline input is missing: no verified snapshot or local package covers this area')
    with scratch_directory(raw, 'download-') as tmp:
        dest = Path(tmp)/'source.osm'
        url = overpass(cfg, context, dest)
        return publish(raw, dest, geometry, url)
