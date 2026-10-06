"""Independent BeamNG adapter. Runtime ZIPs and technical reports are separate."""
from pathlib import Path
import re
import shutil
import tempfile
import zipfile
from akadem_maps import __version__
from akadem_maps.context import atomic_directory, contained, read_json, sha256, write_json
from akadem_maps.world import validate_world
from .beamng_assets import STOCK_MESH_MATERIALS
from .export_beamng import export_map, validate_level as validate_level_files, deterministic_zip


def validate_level(level):
    """Structural checks plus material scoping: own names carry the level ID prefix."""
    level=Path(level)
    result=validate_level_files(level)
    prefix=level.name+'_'  # namespace.py keeps level_id_* names (terrain .ter binds them)
    unscoped=set()
    for path in level.rglob('*materials.json'):
        for name in read_json(path):
            if not name.startswith(prefix) and name not in STOCK_MESH_MATERIALS:
                unscoped.add(name)
    if unscoped:
        raise ValueError('Materials without level prefix: '+', '.join(sorted(unscoped)[:20]))
    # Renamed DAE material symbols must still resolve, or the shape renders NO TEXTURE.
    defined=set()
    for path in level.rglob('*materials.json'):
        for name,value in read_json(path).items():
            defined.update((name,value.get('mapTo',name)))
    missing=set()
    for path in level.rglob('*.dae'):
        missing.update(re.findall(r'<material id="([^"]+)"',path.read_text(encoding='utf8')))
    missing-=defined
    if missing:
        raise ValueError('DAE materials without definition: '+', '.join(sorted(missing)[:20]))
    return result

def export_world(world, output, *, overrides=None, level_id=None, optimization='balanced'):
    world=Path(world).resolve()
    validate_world(world)
    cfg=read_json(world/'config.json')
    mid=cfg['id']
    with atomic_directory(output) as stage:
        report=export_map(mid,stage/'mod',level_id=level_id,overrides=overrides,world_dir=world,namespace=True,package_zip=False,optimization=optimization)
        level=stage/'mod/levels'/report['level_id']
        info=read_json(level/'info.json')
        info['version']=__version__
        synthetic=cfg.get('source_kind')=='synthetic'
        if synthetic:
            info['description']='Synthetic example layout; no OpenStreetMap or measured terrain data.'
        else:
            info['description'] += ' © OpenStreetMap contributors; ODbL-1.0. https://www.openstreetmap.org/copyright'
        if cfg.get('region_profile')!='ukraine':
            info['title']=cfg['name']+' (experimental region)'
        write_json(level/'info.json',info)
        technical=stage/'reports'
        technical.mkdir()
        shutil.move(str(stage/'mod.performance.json'),str(technical/'performance.json'))
        for name in ('kyiv-manifest.json','kyiv-baseline.json','placement-corrections.json','building-conflicts.json'):
            shutil.move(str(level/name),str(technical/name))
        write_json(technical/'world.json',read_json(world/'world.json'))
        for name in ('surface_audit.json', 'road_seams.json', 'road_graph.json', 'roadgen_report.json', 'local_visual_dna.json'):
            if (world/name).exists():
                shutil.copy2(world/name, technical/name)
        common=('Original generated artwork and code: MIT, Earth2Road contributors.\n'
                'BeamNG assets are referenced by path and are not redistributed.\n')
        data=('Synthetic example streets and flat terrain: MIT, Earth2Road contributors.\n'
              'No OpenStreetMap or measured terrain data.\n') if synthetic else (
              '© OpenStreetMap contributors\n'
              'OSM-derived databases: Open Database License 1.0\n'
              'https://opendatacommons.org/licenses/odbl/1-0/\n'
              'https://www.openstreetmap.org/copyright\n'
              'Terrain: Mapzen Terrain Tiles, source-specific licenses; see companion source bundle.\n')
        (level/'LICENSE-DATA.txt').write_text(data+common,encoding='utf8')
        result=validate_level(level)
        zip_name='earth2road_'+mid+'.zip'
        deterministic_zip(stage/'mod',stage/zip_name)
        digest=sha256(stage/zip_name)
        write_json(stage/'artifact.json',{'zip':zip_name,'sha256':digest,'version':__version__,'map':mid,'level_id':level.name,'runtime_verified':False})
        write_json(stage/'acceptance.json',{'zip_sha256':digest,'status':'pending','checks':{},'note':'Export validation is structural only. Runtime acceptance requires separately recorded evidence.'})
    return {'output':str(Path(output).resolve()),'zip':zip_name,'sha256':digest,'structural':result,'runtime_verified':False}

def validate_export(source):
    source=Path(source)
    if source.suffix.lower()=='.zip':
        with tempfile.TemporaryDirectory() as temp:
            with zipfile.ZipFile(source) as archive:
                roots=set()
                plate_roots=set()
                for name in archive.namelist():
                    contained(temp,name)
                    parts=name.split('/')
                    # Ukrainian exports include this level's generated licence plates.
                    if len(parts)>=5 and parts[:3]==['vehicles','common','licenseplates']:
                        plate_roots.add(parts[3])
                        continue
                    if parts[0]!='levels' or len(parts)<3:
                        raise ValueError('ZIP member outside levels/<id>/: '+name)
                    roots.add(parts[1])
                if len(roots)!=1:
                    raise ValueError('Expected exactly one level')
                if plate_roots-roots:
                    raise ValueError('Licence plates belong to a different level')
                if archive.testzip():
                    raise ValueError('Corrupt ZIP member')
                archive.extractall(temp)
            levels=list((Path(temp)/'levels').iterdir())
            if len(levels)!=1:
                raise ValueError('Expected exactly one level')
            return {**validate_level(levels[0]),'zip_sha256':sha256(source)}
    if (source/'artifact.json').exists():
        artifact=read_json(source/'artifact.json')
        result=validate_export(contained(source,artifact['zip']))
        if result['zip_sha256']!=artifact['sha256']:
            raise ValueError('ZIP SHA-256 differs from artifact record')
        return result
    return validate_level(source)
