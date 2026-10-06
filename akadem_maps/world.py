"""Public world build and verification API; imports no game or traffic code."""
import copy
import importlib.metadata
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from .context import BuildContext, RESOURCES, atomic_directory, contained, read_json, sha256, write_json
from .world_format import COORDINATES
from . import __version__

def validate_config(cfg):
    dna = cfg.get('local_visual_dna')
    if dna is not None:
        if not isinstance(dna, dict) or not isinstance(dna.get('file'), str) or not dna['file']:
            raise ValueError('local_visual_dna requires a profile file')
        contained(Path.cwd(), dna['file'])
        if cfg.get('visual_profile') == 'rural':
            raise ValueError('local_visual_dna and visual_profile=rural cannot be combined')
    from .core.roadgen import options
    options(cfg)
    if 'corridor' in cfg:
        from .core.corridor import validate_includes
        validate_includes(cfg['corridor'])
    if not re.fullmatch('[a-z0-9_]+', str(cfg.get('id', ''))):
        raise ValueError('Map id must contain only lowercase ASCII letters, digits and underscores')
    if not str(cfg.get('name', '')).strip():
        raise ValueError('Map name is required')
    if 'bbox' in cfg:
        bbox = cfg['bbox']
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in bbox):
            raise ValueError('bbox must be four finite numbers: west south east north')
        w,s,e,n = bbox
        if not (-180 <= w < e <= 180 and -85 < s < n < 85):
            raise ValueError('Invalid bbox: require west < east, south < north, latitude within ±85°. Antimeridian crossing is unsupported')
        cfg.setdefault('center', [(w+e)/2, (s+n)/2])
    elif not ('corridor' in cfg or 'boundary' in cfg):
        raise ValueError('Specify bbox, corridor, or boundary')
    cfg.setdefault('seed', 311)
    cfg.setdefault('terrain_zoom', 12)
    cfg.setdefault('overpass', 'https://overpass-api.de/api/interpreter')
    cfg.setdefault('region_profile', 'experimental')
    if cfg['region_profile'] not in ('ukraine', 'experimental'):
        raise ValueError('region_profile must be ukraine or experimental')
    cfg.setdefault('source_kind', 'osm')
    if cfg['source_kind'] not in ('osm', 'synthetic'):
        raise ValueError('source_kind must be osm or synthetic')
    if not isinstance(cfg['seed'], int) or not 0 <= cfg['seed'] < 2**31:
        raise ValueError('seed must be an integer from 0 to 2147483647')
    if not isinstance(cfg['terrain_zoom'], int) or not 0 <= cfg['terrain_zoom'] <= 15:
        raise ValueError('terrain_zoom must be an integer from 0 to 15')
    for name in ('osm_file',):
        if cfg.get(name):
            contained(Path.cwd(), cfg[name])
    return cfg

SYNTHETIC_ATTRIBUTION = 'Synthetic example data, MIT; not OpenStreetMap or measured terrain'

def data_licenses(cfg):
    if cfg.get('source_kind') == 'synthetic':
        return {'code':'MIT','data':'MIT (synthetic fixture; no OSM or terrain data)'}
    return {'code':'MIT','osm':'ODbL-1.0','terrain':'Mapzen Terrain Tiles source-specific attribution'}

def versions():
    from .runtime import sumo_binary
    packages = {}
    for name in ('numpy','shapely','pyproj','Pillow','sumolib','eclipse-sumo','osmium'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {'generator': __version__, 'python': platform.python_version(), 'platform': platform.platform(),
            'packages': packages, 'netconvert': subprocess.check_output([str(sumo_binary('netconvert')), '--version'], text=True).splitlines()[0]}

def verify_files(root, files):
    for relative, digest in files.items():
        path = contained(root, relative)
        if not path.is_file():
            raise ValueError(f'Missing package file: {relative}')
        if sha256(path) != digest:
            raise ValueError(f'SHA-256 mismatch: {relative}')

def validate_world(folder):
    folder = Path(folder)
    manifest = read_json(folder/'world.json')
    if manifest.get('format') != 'akadem-world' or manifest.get('version') != 2:
        raise ValueError('Unsupported world format; expected akadem-world v2')
    verify_files(folder, manifest['files'])
    index = read_json(folder/'index.json')
    if index.get('version') != 2 or not index.get('lanes') or not index.get('tiles'):
        raise ValueError('World has no road network or tiles')
    if sha256(folder/'network.net.xml') != index['network_sha256']:
        raise ValueError('Network SHA-256 differs from world index')
    if index['spawn']['lane'] not in {lane['id'] for lane in index['lanes']}:
        raise ValueError('Spawn references a missing lane')
    for name in index['tiles']:
        if not re.fullmatch(r'-?\d+_-?\d+', name):
            raise ValueError('Invalid tile name')
        read_json(folder/'tiles'/f'{name}.json')
    return {'id':manifest['id'], 'tiles':len(index['tiles']), 'lanes':len(index['lanes']), 'verified_files':len(manifest['files'])}

def build_world(config, output, *, config_root=None, cache=None, inputs=None, offline=False,
                mode='auto', package=None, refresh=False, emit=lambda *a,**k: None):
    cfg = validate_config(copy.deepcopy(config))
    if mode not in ('auto', 'offline'):
        raise ValueError('Source mode must be auto or offline')
    offline = offline or mode == 'offline'
    refresh = refresh or cfg.get('refresh', False)
    if refresh and (offline or inputs):
        raise ValueError('Refreshing needs online source mode without --inputs')
    if package:
        cfg['package'] = package
    if refresh:
        cfg['refresh'] = True
    from .runtime import check_sumo
    check_sumo('netconvert')
    output = Path(output).resolve()
    raw = Path(cache).resolve() if cache else output.parent/'.akadem-inputs'
    resource_root, expected = RESOURCES, {}
    config_root = Path(config_root or Path.cwd()).resolve()
    if inputs:
        inputs = Path(inputs).resolve()
        lock = read_json(inputs/'manifest.json')
        verify_files(inputs, lock['files'])
        raw, resource_root, config_root = inputs/'raw', inputs/'resources', inputs/'config_root'
        expected = {p[4:]:h for p,h in lock['files'].items() if p.startswith('raw/')}
    with atomic_directory(output) as stage:
        context = BuildContext(stage, raw, config_root, offline, resource_root, expected=expected,
                               emit=emit, diagnostics=output.parent/(output.name+'.logs'))
        if cfg.get('local_visual_dna'):
            from .core.local_dna import validate as validate_dna
            validate_dna(read_json(context.config_file(cfg['local_visual_dna']['file'])))
        if inputs and (inputs/'corridor.geojson').exists():
            shutil.copy2(inputs/'corridor.geojson', stage/'corridor.geojson')
        elif (raw/(cfg['id']+'.corridor.geojson')).exists():
            # Cached corridor next to the raw OSM; corridor.load() rejects it if its digest is stale.
            shutil.copy2(raw/(cfg['id']+'.corridor.geojson'), stage/'corridor.geojson')
        from .core import prepare, corridor
        emit('stage', stage='sources', progress=0)
        source = prepare.fetch(cfg, context)
        cfg.pop('refresh', None)
        validate_config(cfg)
        # Explicit profile controls local appearance; no implicit worldwide Ukrainian signs.
        emit('stage', stage='geometry', progress=0.15)
        report = prepare.build(cfg, source, context)
        emit('stage', stage='provenance', progress=0.9)
        (stage/'inputs/raw').mkdir(parents=True)
        for name in context.inputs:
            dest = stage/'inputs/raw'/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(raw/name, dest)
        # Cached area digest accompanies the exact extracted OSM.
        for name in context.inputs:
            stamp = raw/(name+'.area.json')
            if stamp.exists():
                dest = stage/'inputs/raw'/(name+'.area.json')
                shutil.copy2(stamp, dest)
        if (stage/'corridor.geojson').exists():
            shutil.copy2(stage/'corridor.geojson', stage/'inputs/corridor.geojson')
        for name in ('osm_types.typ.xml','corrections.json','style.json','shots.json','landmarks.json','building_sources.json'):
            context.resource(name)
        for name, path in context.config_inputs.items():
            dest = stage/'inputs'/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        write_json(stage/'config.json', cfg)
        write_json(stage/'inputs/config.json', cfg)
        tool_versions = versions()
        write_json(stage/'inputs/manifest.json', {'files': {p.relative_to(stage/'inputs').as_posix():sha256(p) for p in sorted((stage/'inputs').rglob('*')) if p.is_file()}, 'tools':tool_versions})
        write_json(stage/'world.json', {'format':'akadem-world', 'version':2, 'id':cfg['id'], 'generator':__version__,
                   'coordinates':COORDINATES, 'tools':tool_versions, 'seed':cfg['seed'],
                   'licenses':data_licenses(cfg),
                   'files':{p.relative_to(stage).as_posix():sha256(p) for p in sorted(stage.rglob('*')) if p.is_file() and p.name != 'netconvert.log'}})
        result = validate_world(stage)
    emit('result', output=str(output), **result)
    return result
