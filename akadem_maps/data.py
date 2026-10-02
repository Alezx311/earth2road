"""Shared data actions for the public CLI and game picker process."""
from pathlib import Path

from .context import read_json
from .errors import OfflineMissing
from . import offline as prepared
from . import packages
from .sources import area_key, coverage


def data_action(action, cfg, cache, *, offline=False, package=None, refresh=False,
                pbf=None, bounds=None, offer=None, accepted_bytes=None, emit=lambda *a, **k: None):
    cache = Path(cache)
    if action == 'status':
        return prepared.status(cfg, cache)
    if action == 'prepare':
        return prepared.prepare_area(cfg, cache, offline=offline, package=package, refresh=refresh, emit=emit)
    if action == 'suggest':
        result = packages.suggest(cache, coverage(cfg), offline=offline)
        path = cache/'packages'/'offers'/(area_key(result['coverage'])+'.json')
        packages.atomic_json(path, result)
        return {'action': action, 'offer': str(path.resolve()), **result}
    if action == 'download':
        if offline:
            raise OfflineMissing('Package download is unavailable in offline mode')
        if not offer:
            raise ValueError('Find a package and accept its displayed size first')
        result = packages.download_package(cache, read_json(offer), accepted_bytes=accepted_bytes)
        return {'action': action, 'package': result}
    if action == 'import':
        from .world import validate_config
        from shapely.geometry import box, mapping
        if pbf is None or bounds is None:
            raise ValueError('Import requires a PBF and declared coverage: west south east north')
        validate_config({'id': 'coverage', 'name': 'coverage', 'bbox': bounds})
        result = packages.register(cache, pbf, mapping(box(*bounds)))
        return {'action': action, 'package': result}
    raise ValueError(f'Unknown data action: {action}')
