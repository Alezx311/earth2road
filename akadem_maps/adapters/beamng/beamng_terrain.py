"""Native low terrain substrate for mesh-based levels.

BeamNG 0.39 mesh-only levels have a collision fallback at world z=0. A native
TerrainBlock below the mesh replaces that fallback without moving the city.
Binary layout: https://documentation.beamng.com/modding/levels/level_formats/terrain/
The substrate is not the road surface and must never conceal missing road meshes.
"""
import json
import math
import struct
import uuid


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


# --- 'terrain' optimization: ground as a native heightmap ---------------------------

SINK = .05            # terrain stays this far below every road/sidewalk/green surface
OUTLIER_MARGIN = 5.   # metres kept beyond the 0.01–99.99 % height percentiles
# BeamNG 0.39 terrain materials are PBR (base/detail/macro sets, as in the stock levels);
# the old diffuseMap fields render as a flat default. Textures are the shared game assets.
GRASS = '/assets/materials/terrain/grass/t_grass_01/t_grass_01_'
MACRO = '/assets/materials/terrain/grass/t_macro_grass/t_macro_grass_'


# Base maps are per-level colour maps in the stock levels (the shared detail and macro
# sets are grey modulators), so the level gets small flat base maps of its own: the
# dry-grass albedo of the kyiv_ground mesh, a flat normal, matte roughness, full AO.
BASE_MAPS = {'b': (118, 112, 78), 'nm': (128, 128, 255), 'r': (235, 235, 235), 'h': (128, 128, 128), 'ao': (255, 255, 255)}


BASE_SIZE = 256     # must equal the texture set's baseTexSize, or the game drops the map


def flat_png(path, rgb, size=BASE_SIZE):
    import zlib
    row = b'\x00'+bytes(rgb)*size
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
                     +chunk(b'IDAT', zlib.compress(row*size, 9))+chunk(b'IEND', b''))


def ground_material(name, extent, base):
    """Grass TerrainMaterial: own flat base maps, shared t_grass_01 detail and t_macro_grass macro."""
    material = {'name': name, 'internalName': name, 'class': 'TerrainMaterial',
                'persistentId': str(uuid.uuid5(uuid.NAMESPACE_URL, 'terradrive-terrain/'+name)),
                'annotation': 'GRASS', 'groundmodelName': 'DIRT',
                'detailDistances': [0, 0, 50, 70], 'detailDistAtten': [0, .9],
                'macroDistances': [0, 0, 400, 8000], 'macroDistAtten': [.35, 1], 'detailSize': 2,
                'baseColorDetailStrength': [.4, 0], 'normalDetailStrength': [.7, .2],
                'roughnessDetailStrength': [.9, .7], 'baseColorMacroStrength': [.1, .4],
                'normalMacroStrength': [.4, 1.1], 'roughnessMacroStrength': [.9, .9]}
    for channel, suffix in (('baseColor', 'b'), ('normal', 'nm'), ('roughness', 'r'), ('height', 'h'), ('ao', 'ao')):
        material[f'{channel}DetailTex'] = f'{GRASS}{suffix}.png'
        material[f'{channel}MacroTex'] = f'{MACRO}{suffix}.png'
        material[f'{channel}MacroTexSize'] = 50
        material[f'{channel}BaseTex'] = f'{base}_{suffix}.png'
        material[f'{channel}BaseTexSize'] = extent
    return material


def terrain_grid(bounds, max_size=4096):
    """(metres per cell, power-of-two size) covering bounds from its min corner.

    1 m cells while the area fits max_size; larger areas keep max_size cells and
    stretch the cell to the next 0.25 m (8.3 km → 4096 × 2.25 m).
    """
    extent = max(bounds[2]-bounds[0], bounds[3]-bounds[1])
    size = 128
    while size < extent and size < max_size:
        size *= 2
    square = max(1.0, math.ceil(extent/size*4)/4)
    return square, size


class GroundTerrain:
    """Rasterises ground triangles into a TerrainBlock heightmap.

    Grid point (i, j) is world (x0 + i*square, y0 + j*square); the .ter stores it at
    index i + j*size. Ground triangles set heights (highest wins where they overlap).
    Every other surface (roads, sidewalks, greens, parking) is a cap: within one cell
    of a cap the terrain is pulled SINK below it, so the mesh is never pierced by the
    terrain's own triangles. Holes (under roads and buildings) are filled from their
    edges; the area past the data repeats its edge heights.
    """
    def __init__(self, bounds):
        import numpy as np
        self.square, self.size = terrain_grid(bounds)
        self.x0, self.y0 = float(math.floor(bounds[0])), float(math.floor(bounds[1]))
        self.ground = np.full((self.size, self.size), np.nan, dtype=np.float32)
        self.cap = np.full((self.size, self.size), np.inf, dtype=np.float32)
        self.ground_triangles = self.cap_triangles = 0

    def add_ground(self, triangles):
        self.ground_triangles += self._raster(triangles, self.ground, cap=False)

    def add_cap(self, triangles):
        self.cap_triangles += self._raster(triangles, self.cap, cap=True)

    def _raster(self, triangles, grid, cap):
        import numpy as np
        t = np.asarray(list(triangles), dtype=np.float64).reshape(-1, 3, 3)
        if not len(t):
            return 0
        gx = (t[:, :, 0]-self.x0)/self.square
        gy = (t[:, :, 1]-self.y0)/self.square
        z = t[:, :, 2]
        last = self.size-1
        if cap:    # small triangles may hold no grid point: their corners still count
            ci = np.clip(np.rint(gx), 0, last).astype(np.int64).ravel()
            cj = np.clip(np.rint(gy), 0, last).astype(np.int64).ravel()
            np.minimum.at(grid, (cj, ci), z.ravel().astype(np.float32))
        i0 = np.clip(np.ceil(gx.min(1)), 0, last).astype(np.int64)
        i1 = np.clip(np.floor(gx.max(1)), 0, last).astype(np.int64)
        j0 = np.clip(np.ceil(gy.min(1)), 0, last).astype(np.int64)
        j1 = np.clip(np.floor(gy.max(1)), 0, last).astype(np.int64)
        span = np.maximum(i1-i0, j1-j0)+1
        valid = (i1 >= i0) & (j1 >= j0)
        k = 1
        # Triangles are batched by grid-point span (1, 2, 4, … cells) and tested vectorised.
        while valid.any():
            pick = np.nonzero(valid & (span <= k))[0]
            valid[pick] = False
            off_j, off_i = np.divmod(np.arange(k*k), k)
            batch = max(1, 2_000_000//(k*k))
            for s in range(0, len(pick), batch):
                idx = pick[s:s+batch]
                I = i0[idx, None]+off_i[None, :]
                J = j0[idx, None]+off_j[None, :]
                ax, ay = gx[idx, 0, None], gy[idx, 0, None]
                bx, by = gx[idx, 1, None], gy[idx, 1, None]
                cx, cy = gx[idx, 2, None], gy[idx, 2, None]
                d = (by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
                d = np.where(np.abs(d) < 1e-12, np.nan, d)
                u = ((by-cy)*(I-cx)+(cx-bx)*(J-cy))/d
                v = ((cy-ay)*(I-cx)+(ax-cx)*(J-cy))/d
                w = 1-u-v
                inside = (u >= -1e-9) & (v >= -1e-9) & (w >= -1e-9) & (I <= i1[idx, None]) & (J <= j1[idx, None])
                h = (u*z[idx, 0, None]+v*z[idx, 1, None]+w*z[idx, 2, None]).astype(np.float32)
                (np.minimum if cap else np.fmax).at(grid, (J[inside], I[inside]), h[inside])
            k *= 2
        return len(t)

    def heights(self):
        import numpy as np
        h = self.ground.copy()
        known = ~np.isnan(h)
        if not known.any():
            raise ValueError('No ground triangles for the terrain')
        rows, cols = np.nonzero(known.any(1))[0], np.nonzero(known.any(0))[0]
        r0, r1, c0, c1 = rows[0], rows[-1]+1, cols[0], cols[-1]+1
        inner = h[r0:r1, c0:c1]
        # Fill holes from their edges: each pass gives unknown cells the mean of known
        # 4-neighbours, so a hole closes in (its radius) passes.
        while np.isnan(inner).any():
            p = np.pad(inner, 1, constant_values=np.nan)
            nb = np.stack([p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]])
            count = (~np.isnan(nb)).sum(0)
            total = np.nansum(nb, 0)
            fill = np.isnan(inner) & (count > 0)
            inner[fill] = total[fill]/count[fill]
        h = np.pad(inner, ((r0, self.size-r1), (c0, self.size-c1)), mode='edge')
        p = np.pad(self.cap, 1, constant_values=np.inf)
        near = np.min(np.stack([p[1+dj:1+dj+self.size, 1+di:1+di+self.size]
                                for dj in (-1, 0, 1) for di in (-1, 0, 1)]), 0)
        return np.minimum(h, near-SINK)

    def write(self, level, level_id):
        import numpy as np
        h = self.heights()
        # Source spikes (a few cells at −2000 m or +150 m in real snapshots) would stretch
        # maxHeight and the 16-bit step to centimetres; clamp to the robust range.
        lo, hi = np.percentile(h, [.01, 99.99])
        lo, hi = float(lo)-OUTLIER_MARGIN, float(hi)+OUTLIER_MARGIN
        clamped = int(((h < lo) | (h > hi)).sum())
        h = np.clip(h, lo, hi)
        base = math.floor(float(h.min()))-1
        top = float(h.max())-base
        max_height = float(max(16, math.ceil(top+1)))
        # floor(): quantisation only ever lowers the terrain, never through a surface.
        stored = np.clip(np.floor((h-base)*(65536/max_height)), 0, 65535).astype('<u2')
        name = level_id+'_ground'
        encoded = name.encode('ascii')
        path = level/'ground.ter'
        path.write_bytes(struct.pack('<BI', 9, self.size)+stored.tobytes(order='C')
                         +bytes(self.size*self.size)+struct.pack('<I', 1)+bytes([len(encoded)])+encoded)
        folder = level/'art/terrains'
        folder.mkdir(parents=True, exist_ok=True)
        texture_set = level_id+'_terrain_textures'
        for suffix, rgb in BASE_MAPS.items():
            flat_png(folder/f'{name}_base_{suffix}.png', rgb)
        (folder/'main.materials.json').write_text(json.dumps({
            name: ground_material(name, self.size*self.square, f'/levels/{level_id}/art/terrains/{name}_base'),
            texture_set: {'name': texture_set, 'class': 'TerrainMaterialTextureSet',
                          'baseTexSize': [BASE_SIZE, BASE_SIZE], 'detailTexSize': [1024, 1024], 'macroTexSize': [1024, 1024]}},
            indent=2), encoding='utf8')
        stats = {'size': self.size, 'square_m': self.square, 'max_height_m': max_height,
                 'step_mm': round(1000*max_height/65536, 3), 'bytes': path.stat().st_size,
                 'ground_triangles': self.ground_triangles, 'cap_triangles': self.cap_triangles,
                 'clamped_cells': clamped}
        obj = dict(name='KyivGroundTerrain', class_='TerrainBlock', terrainFile=f'/levels/{level_id}/ground.ter',
                   position=[self.x0, self.y0, base], squareSize=self.square, maxHeight=max_height,
                   materialTextureSet=texture_set, baseTexSize=1024, lightMapSize=1024, castShadows=True)
        return obj, stats
