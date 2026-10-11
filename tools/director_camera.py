"""Convert a photographic GPS camera position to this export's BeamNG coordinates.

Altitude is absolute metres above sea level (EXIF GPS altitude is only an estimate
of that datum). Confirm with a probe: this does not infer heading or FOV.
"""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def gps_to_beamng(world, export, lon, lat, altitude):
    from pyproj import CRS, Transformer
    if not all(math.isfinite(v) for v in (lon,lat,altitude)) or not -180 <= lon <= 180 or not -85 < lat < 85:
        raise ValueError('Invalid finite camera coordinates')
    world,export=Path(world),Path(export)
    index=json.loads((world/'index.json').read_text(encoding='utf-8'))
    manifest=json.loads((export/'reports/kyiv-manifest.json').read_text(encoding='utf-8'))
    artifact=json.loads((export/'artifact.json').read_text(encoding='utf-8'))
    if artifact['map'] != index['id'] or manifest['base_height'] != index['base_height'] or manifest['sumo_center_offset'] != index['offset']:
        raise ValueError('World and export coordinate systems do not match')
    loc=ET.parse(world/'network.net.xml').getroot().find('location')
    transformer=Transformer.from_crs(CRS.from_epsg(4326),CRS.from_user_input(loc.get('projParameter')),always_xy=True)
    x,y=transformer.transform(lon,lat)
    nx,ny=map(float,loc.get('netOffset').split(','))
    return [x+nx-index['offset'][0],y+ny-index['offset'][1],altitude-index['base_height']+manifest['vertical_offset']]


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--world',type=Path,required=True)
    p.add_argument('--export',type=Path,required=True)
    p.add_argument('--lon',type=float,required=True)
    p.add_argument('--lat',type=float,required=True)
    p.add_argument('--altitude',type=float,required=True)
    a=p.parse_args()
    print(json.dumps({'pos':gps_to_beamng(a.world,a.export,a.lon,a.lat,a.altitude),'note':'Estimate; verify altitude datum, heading and FOV with a probe.'}))
