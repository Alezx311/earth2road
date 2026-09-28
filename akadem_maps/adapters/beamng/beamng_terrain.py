"""Native low terrain substrate for mesh-based levels.

BeamNG 0.39 mesh-only levels have a collision fallback at world z=0. A native
TerrainBlock below the mesh replaces that fallback without moving the city.
Binary layout: https://documentation.beamng.com/modding/levels/level_formats/terrain/
The substrate is not the road surface and must never conceal missing road meshes.
"""
import json
import math
import struct


def write_substrate(level, level_id, bounds, minimum_z):
    size=128
    margin=512
    square=math.ceil(max(bounds[2]-bounds[0]+2*margin,bounds[3]-bounds[1]+2*margin)/size)
    name=level_id+'_substrate'
    encoded=name.encode('ascii')
    payload=(struct.pack('<BI',9,size)+bytes(size*size*2)+bytes(size*size)
             +struct.pack('<I',1)+bytes([len(encoded)])+encoded)
    (level/'mesh-substrate.ter').write_bytes(payload)
    folder=level/'art/terrains';folder.mkdir(parents=True,exist_ok=True)
    (folder/'main.materials.json').write_text(json.dumps({name:{
        'name':name,'class':'TerrainMaterial','internalName':name,
        'diffuseMap':'/assets/materials/terrain/grass/groundmesh_grass2/groundmesh_grass_b.color.png',
        'diffuseSize':500,'detailSize':5,'groundmodelName':'DIRT'}},indent=2),encoding='utf8')
    return dict(name='KyivMeshSubstrate',class_='TerrainBlock',
                terrainFile=f'/levels/{level_id}/mesh-substrate.ter',
                position=[bounds[0]-margin,bounds[1]-margin,math.floor(minimum_z)-100],
                squareSize=square,maxHeight=100,baseTexSize=128,lightMapSize=128,
                castShadows=False)
