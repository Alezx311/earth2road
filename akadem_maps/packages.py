"""Local PBF registration and explicit Geofabrik package discovery/downloads."""
import hashlib
from pathlib import Path
import re
import urllib.request
import uuid

from .context import read_json, scratch_directory, sha256, write_json
from .errors import OfflineMissing, SourceError
from .sources import now

CATALOG_URL = 'https://download.geofabrik.de/index-v1.json'


def valid_coverage(geometry):
    from shapely.geometry import shape
    try:
        area = shape(geometry)
        w, s, e, n = area.bounds
        if (area.geom_type not in ('Polygon', 'MultiPolygon') or not area.is_valid or area.is_empty
                or not (-180 <= w < e <= 180 and -85 < s < n < 85)):
            raise ValueError('invalid polygon')
        return area
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SourceError('Coverage must be a valid Polygon/MultiPolygon within supported coordinates') from exc


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        write_json(temporary, value)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def register(raw, path, geometry, *, name=None, source='user-declared coverage', md5=None):
    """An imported bbox is a user's coverage declaration, never an object envelope."""
    import osmium
    valid_coverage(geometry)
    path = Path(path).resolve()
    if not path.is_file():
        raise SourceError(f'Local PBF is missing: {path}')
    # Reject impossible blob headers before entering the native parser (which can
    # retain a Windows file handle when construction fails on arbitrary bytes).
    with path.open('rb') as stream:
        prefix = stream.read(4)
    if len(prefix) != 4 or not 0 < int.from_bytes(prefix, 'big') <= 64*1024:
        raise SourceError('Invalid PBF blob header')
    if md5:
        h = hashlib.md5()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                h.update(block)
        if h.hexdigest() != md5.lower():
            raise SourceError(f'PBF checksum mismatch: {path.name}')
    try:
        # Native reader scans every compressed block, without retaining the planet's
        # objects or invoking millions of Python callbacks.
        with osmium.io.Reader(str(path)) as reader:
            osmium.apply(reader, osmium.filter.EmptyTagFilter())
    except (RuntimeError, OSError) as exc:
        raise SourceError(f'Invalid PBF: {exc}') from exc
    digest = sha256(path)
    pid = re.sub('[^a-z0-9_]+', '_', (name or path.stem).lower()).strip('_')[:60] or 'package'
    pid += '_' + digest[:12]
    meta = {'id': pid, 'name': name or path.name, 'path': str(path), 'coverage': geometry,
            'source': source, 'sha256': digest, 'bytes': path.stat().st_size, 'verified_at': now()}
    atomic_json(Path(raw)/'packages'/f'{pid}.json', meta)
    return meta


def available_packages(raw, geometry=None, selected=None):
    from shapely.geometry import shape
    target = shape(geometry) if geometry else None
    result = []
    for stamp in (Path(raw)/'packages').glob('*.json'):
        try:
            meta = read_json(stamp)
            if selected and meta['id'] != selected:
                continue
            area = valid_coverage(meta['coverage'])
            if target is not None and not area.covers(target):
                continue
            if not Path(meta['path']).is_file():
                continue
            result.append(meta)
        except (ValueError, KeyError, OSError, SourceError):
            continue
    if selected and not result:
        raise SourceError('Selected local package is missing or does not completely cover the area')
    return sorted(result, key=lambda meta: meta['bytes'])


def verify_package(meta):
    path = Path(meta['path'])
    if path.stat().st_size != meta['bytes'] or sha256(path) != meta['sha256']:
        raise SourceError(f'Local PBF checksum mismatch: {path.name}; import it again')
    return path


def catalog(raw, *, offline=False, refresh=False):
    from .network import download
    path = Path(raw)/'packages'/'geofabrik-index.geojson'
    if path.exists() and not refresh:
        return read_json(path)
    if offline:
        raise OfflineMissing('Offline input is missing: Geofabrik catalog')
    path.parent.mkdir(parents=True, exist_ok=True)
    with scratch_directory(path.parent) as tmp:
        dest = Path(tmp)/'index.json'
        download(CATALOG_URL, dest, max_time=30)
        document = read_json(dest)
        if document.get('type') != 'FeatureCollection' or not document.get('features'):
            raise SourceError('Invalid Geofabrik catalog')
        atomic_json(path, document)
        return document


def suggest(raw, geometry, *, offline=False):
    from concurrent.futures import ThreadPoolExecutor
    from shapely.geometry import shape
    from .core.prepare import user_agent
    target = valid_coverage(geometry)
    candidates = []
    for feature in catalog(raw, offline=offline)['features']:
        props = feature['properties']
        if props.get('urls', {}).get('pbf') and shape(feature['geometry']).covers(target):
            candidates.append(feature)
    candidates.sort(key=lambda feature: shape(feature['geometry']).area)
    if not candidates:
        raise SourceError('No Geofabrik package fully covers this area')
    # Compare actual transfer sizes among every fully covering region. A polygon's
    # area alone does not tell us how many OSM objects its PBF contains.
    def transfer_size(feature):
        url = feature['properties']['urls']['pbf']
        if offline or not url.startswith('https://download.geofabrik.de/'):
            return None
        try:
            request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': user_agent()})
            with urllib.request.urlopen(request, timeout=15) as response:
                return int(response.headers['Content-Length']) if response.headers.get('Content-Length') else None
        except (OSError, ValueError):
            return None
    with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as executor:
        sizes = list(executor.map(transfer_size, candidates))
    known = [(size, i) for i, size in enumerate(sizes) if size and size > 0]
    index = min(known)[1] if known else 0
    feature = candidates[index]
    props = feature['properties']
    url = props['urls']['pbf']
    if not url.startswith('https://download.geofabrik.de/'):
        raise SourceError('Unexpected Geofabrik package URL')
    return {'id': props['id'], 'name': props['name'], 'url': url, 'bytes': sizes[index],
            'coverage': feature['geometry'], 'size_comparison_complete': len(known) == len(candidates)}


def download_package(raw, offer, *, accepted_bytes):
    """Called only for an explicit selection with a displayed, accepted size."""
    from .network import download
    if not offer.get('bytes') or accepted_bytes != offer['bytes']:
        raise SourceError('Package size must be shown and accepted before downloading')
    url = offer['url']
    if not url.startswith('https://download.geofabrik.de/') or not url.endswith('.osm.pbf'):
        raise SourceError('Unexpected Geofabrik package URL')
    directory = Path(raw)/'packages'/'files'
    directory.mkdir(parents=True, exist_ok=True)
    with scratch_directory(directory) as tmp:
        md5_file, pbf = Path(tmp)/'checksum.txt', Path(tmp)/'download.osm.pbf'
        download(url+'.md5', md5_file, max_time=30)
        checksum = md5_file.read_text(encoding='ascii').split()[0]
        if not re.fullmatch('[a-fA-F0-9]{32}', checksum):
            raise SourceError('Invalid Geofabrik checksum')
        download(url, pbf, max_time=3600)
        if pbf.stat().st_size != accepted_bytes:
            raise SourceError('Package changed since the size was shown; find the package again')
        # Move only after checksum + parsing succeeded. Registration is published last.
        staging_raw = Path(tmp)/'registry'
        meta = register(staging_raw, pbf, offer['coverage'], name=offer['name'], source=url, md5=checksum)
        dest = directory/(meta['sha256']+'.osm.pbf')
        if not dest.exists():
            pbf.replace(dest)
        elif sha256(dest) != meta['sha256']:
            raise SourceError('Existing package file is damaged')
        meta['path'] = str(dest.resolve())
        atomic_json(Path(raw)/'packages'/(meta['id']+'.json'), meta)
        return meta
