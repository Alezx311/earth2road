"""Texture styles for BeamNG facades (config/visuals/texture_styles.json).

Godot switches a style at run time; BeamNG gets it baked into the facade textures at export.
`procedural` keeps the exporter's own drawn facades. A photo style builds each 6 m facade tile
(two 3 m storeys by two 3 m bays, PANEL_TILE) from the textures its import tool wrote into
game/assets/textures; a missing texture is an error, never a silent fallback.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT/'config/visuals/texture_styles.json'
TEXTURES = ROOT/'game/assets/textures'
TILE_PX = 512                 # one 6 m repeat
CELL = TILE_PX // 2           # one 3 m storey / bay
PANEL_LAYERS = 6              # tools/import_panelka.py atlas: five windowed panels, then a blank
WINDOW_LAYERS = (0, 1, 3, 4)  # layer 2 has a window grille: ground floors only, not in a repeat
LOGGIA_GRID = (5, 11)         # tools/import_panelka.py LOGGIA_GRID (columns, rows) of II-68 modules
LOGGIA_SHEET_M = 33.0         # the whole II-68 sheet: 5 bays x 6.6 m = 11 storeys x 3 m
SHEET_PX = 2048
END_WALL_MAX_M = 16.0         # deeper walls are a wing's long side (Soviet blocks are 11–14 m deep)


def styles():
    return {s['id']: s for s in json.loads(CONFIG.read_text(encoding='utf-8'))['styles']}


def resolve(style, textures=TEXTURES):
    """The style record, after checking that every texture it needs is installed."""
    known = styles()
    if style not in known:
        raise ValueError(f'Unknown texture style {style!r}; known: {", ".join(known)}')
    record = known[style]
    missing = [s for s in record.get('requires', []) if not (Path(textures)/s/'albedo.jpg').is_file()]
    if missing:
        raise ValueError(f'Texture style {style!r} needs {", ".join(missing)} in {textures}; '
                         f'run {record.get("import", "its import tool")} first')
    return record


def _unit(*key):
    return int.from_bytes(hashlib.sha256(repr(key).encode()).digest()[:4], 'big') / 2**32


def _tint(image, colour, strength=0.5):
    """Shift a photo toward `colour` (0..1 RGB) keeping its brightness, as facade.gdshader does."""
    from PIL import Image
    mean = sum(colour)/3 or 0.05
    factors = [1 + strength*(c/mean - 1) for c in colour]
    bands = [b.point(lambda v, k=k: max(0, min(255, round(v*k)))) for b, k in zip(image.split(), factors)]
    return Image.merge('RGB', bands)


def _windows(image, glass=(0.20, 0.24, 0.27)):
    """Procedural windows over a plain wall, on the same 3 m grid and proportions as Godot."""
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    frame = (205, 206, 198)
    pane = tuple(round(c*255) for c in glass)
    for bx in range(2):
        for sy in range(2):
            x0, y0 = bx*CELL, sy*CELL
            # Image rows run top-down; the window sits 0.32–0.82 of a storey above its floor.
            box = (x0+.22*CELL, y0+(1-.82)*CELL, x0+.78*CELL, y0+(1-.32)*CELL)
            draw.rectangle(box, fill=frame)
            inner = (box[0]+.02*CELL, box[1]+.02*CELL, box[2]-.02*CELL, box[3]-.02*CELL)
            draw.rectangle(inner, fill=pane)
            mid = (box[0]+box[2])/2
            draw.rectangle((mid-.012*CELL, inner[1], mid+.012*CELL, inner[3]), fill=frame)
    return image


def _tiled(path, metres):
    """A tileable texture repeated to cover 6 m at its real scale (rounded to whole repeats)."""
    from PIL import Image
    src = Image.open(path).convert('RGB')
    nx, ny = max(1, round(6/metres[0])), max(1, round(6/metres[1]))
    cell = src.resize((TILE_PX//nx, TILE_PX//ny), Image.LANCZOS)
    out = Image.new('RGB', (TILE_PX, TILE_PX))
    for i in range(nx):
        for j in range(ny):
            out.paste(cell, (i*cell.width, j*cell.height))
    return out.resize((TILE_PX, TILE_PX))


def panel_tile(colour, key, textures=TEXTURES):
    """2 x 2 photo panels: one window style per facade, an occasional different flat."""
    from PIL import Image
    atlas = Image.open(Path(textures)/'panelka_panels/albedo.jpg').convert('RGB')
    size = atlas.height
    own = WINDOW_LAYERS[int(_unit('own', key)*len(WINDOW_LAYERS))]
    out = Image.new('RGB', (TILE_PX, TILE_PX))
    for bx in range(2):
        for sy in range(2):
            swap = WINDOW_LAYERS[int(_unit('flat', key, bx, sy)*len(WINDOW_LAYERS))]
            layer = swap if _unit('swap', key, bx, sy) < .15 else own
            out.paste(atlas.crop((layer*size, 0, (layer+1)*size, size)).resize((CELL, CELL), Image.LANCZOS), (bx*CELL, sy*CELL))
    return _tint(out, colour)


def loggia_sheet(colour, key, textures=TEXTURES):
    """The whole II-68 photo as one SHEET_PX square repeating every LOGGIA_SHEET_M metres, so
    neighbouring loggias keep the variety and alignment of the original facade."""
    from PIL import Image
    atlas = Image.open(Path(textures)/'panelka_loggias/albedo.jpg').convert('RGB')
    return _tint(atlas.resize((SHEET_PX, SHEET_PX), Image.LANCZOS), colour, 0.3)


def end_tile(kind, colour, key, textures=TEXTURES):
    """Blank end wall: the windowless panel module, or brick without windows."""
    from PIL import Image
    if kind == 'brick':
        white = _unit('white', key) < .4 or sum(colour)/3 > .7
        return _tiled(Path(textures)/('panelka_brick_white' if white else 'panelka_brick_red')/'albedo.jpg', (2.0, 1.8))
    atlas = Image.open(Path(textures)/'panelka_panels/albedo.jpg').convert('RGB')
    size = atlas.height
    blank = atlas.crop(((PANEL_LAYERS-1)*size, 0, PANEL_LAYERS*size, size)).resize((CELL, CELL), Image.LANCZOS)
    out = Image.new('RGB', (TILE_PX, TILE_PX))
    for bx in range(2):
        for sy in range(2):
            out.paste(blank, (bx*CELL, sy*CELL))
    return _tint(out, colour)


def brick_tile(colour, key, textures=TEXTURES):
    white = _unit('white', key) < .4 or sum(colour)/3 > .7
    name = 'panelka_brick_white' if white else 'panelka_brick_red'
    return _windows(_tiled(Path(textures)/name/'albedo.jpg', (2.0, 1.8)))


def plaster_tile(colour, key, textures=TEXTURES):
    wall = _tiled(Path(textures)/'panelka_plaster/albedo.jpg', (4.0, 4.0))
    return _windows(_tint(wall, colour, 0.8))


def tile_for(kind, colour, key, textures=TEXTURES):
    """kind: panel | loggia | brick | plaster -> RGB pixel list (row 0 at the top) for export_beamng.png();
    loggia is the whole SHEET_PX sheet, the others one TILE_PX repeat (see tile_size)."""
    if kind == 'synth':
        return list(synth_tile(key).tobytes())
    image = {'panel': panel_tile, 'loggia': loggia_sheet, 'brick': brick_tile, 'plaster': plaster_tile}[kind](colour, key, textures)
    return list(image.tobytes())


def tile_size(kind):
    """(pixels, metres) of one repeat of a facade kind."""
    return (SHEET_PX, LOGGIA_SHEET_M) if kind == 'loggia' else (TILE_PX, 6.0)


def end_pixels(kind, colour, key, textures=TEXTURES):
    if kind == 'synth':
        return list(synth_end_tile(key).tobytes())
    return list(end_tile('brick' if kind == 'brick' else 'panel', colour, key, textures).tobytes())


def end_walls(points):
    """Per edge of a footprint ring (x, y pairs, not closed): True for the short walls across
    the long axis of an elongated block (length >= 1.6 x width). Same rule as
    game/visuals/tile.gd end_walls()."""
    n = len(points)
    mask = [False]*n
    if n < 3:
        return mask
    edges = [(points[(i+1) % n][0]-points[i][0], points[(i+1) % n][1]-points[i][1]) for i in range(n)]
    longest = max(edges, key=lambda d: d[0]**2 + d[1]**2)
    norm = (longest[0]**2 + longest[1]**2) ** .5
    if norm < 1e-6:
        return mask
    ax, ay = longest[0]/norm, longest[1]/norm
    along = [p[0]*ax + p[1]*ay for p in points]
    across = [-p[0]*ay + p[1]*ax for p in points]
    length, width = max(along)-min(along), max(across)-min(across)
    if length < 1.6*width:
        return mask
    for i, (dx, dy) in enumerate(edges):
        d = (dx*dx + dy*dy) ** .5
        if d > 1e-6 and abs((dx*ax + dy*ay)/d) < .5 and d <= min(width*1.05 + .5, END_WALL_MAX_M):
            mask[i] = True
    return mask


def dna_kind(style, key=''):
    """Local Visual DNA / S3DB local_style -> tile kind, matching facade.gdshader's photo branch
    (most panel blocks show loggias, as VisualTile.loggias picks ~70 % of them)."""
    if style.get('architecture') in ('panel', 'modern') or style.get('material') == 'concrete':
        return 'loggia' if _unit('loggia_block', key) < .7 else 'panel'
    if style.get('architecture') == 'brick' or style.get('material') == 'brick':
        return 'brick'
    return 'plaster'


# --- photo ground ------------------------------------------------------------------
# BeamNG mesh materials cannot blend layers per pixel like surface.gdshader does, so each
# ground material gets one baked sheet: the same base cover, patches and worn spots as
# game/scripts/materials.gd photo_ground(), on masks that repeat with the sheet.
GROUND_PX = 2048
GROUND_SHEET_M = 24.0         # 8 repeats of a 3 m photo, 6 of a 4 m one
GROUND_SATURATION = 0.8       # surface.gdshader photo_saturation
# material -> (base set, metres), (patch set, metres, cover), (wear set, metres, cover), tint
GROUND_RECIPES = {
    'kyiv_grass': (('photo_lawn', 3.0), ('photo_meadow', 4.0, 0.3), ('photo_worn', 3.0, 0.08), (0.86, 0.88, 0.80)),
    'kyiv_ground': (('photo_lawn', 3.0), ('photo_verge', 4.0, 0.35), ('photo_worn', 3.0, 0.14), (0.90, 0.88, 0.76)),
}


def _ground_layer(textures, name, metres, mode):
    """One photo map tiled over the sheet at its real size (`metres` must divide the sheet)."""
    from PIL import Image
    import numpy as np
    repeats = round(GROUND_SHEET_M/metres)
    cell = GROUND_PX // repeats
    image = Image.open(Path(textures)/name/f'{"albedo" if mode == "RGB" else "normal"}.jpg').convert('RGB')
    tile = np.asarray(image.resize((cell, cell), Image.LANCZOS), dtype=np.float32)/255
    sheet = np.tile(tile, (repeats, repeats, 1))
    if sheet.shape[0] != GROUND_PX:
        sheet = np.asarray(Image.fromarray((sheet*255).astype('uint8')).resize((GROUND_PX, GROUND_PX), Image.LANCZOS), dtype=np.float32)/255
    return sheet


def _periodic_noise(seed, cycles):
    """Smooth noise in 0..1 that repeats with the sheet: random waves of whole cycles."""
    import numpy as np
    rng = np.random.default_rng(seed)
    axis = np.linspace(0, 2*np.pi, GROUND_PX, endpoint=False, dtype=np.float32)
    u, v = np.meshgrid(axis, axis)
    total = np.zeros_like(u)
    for _ in range(28):
        fx, fy = rng.integers(-cycles, cycles+1, 2)
        if fx == 0 and fy == 0:
            continue
        total += np.cos(fx*u + fy*v + rng.uniform(0, 2*np.pi)) / (fx*fx + fy*fy) ** .35
    return (total - total.min()) / (total.max() - total.min())


def _cover(noise, cover, detail):
    """surface.gdshader cover_mask on arrays (a narrower edge: the baked noise is smoother)."""
    import numpy as np
    edge = 1 - cover + (detail - 0.4)*0.5
    t = np.clip((noise - (edge - .03)) / .06, 0, 1)
    return (t*t*(3 - 2*t))[..., None]


def ground_sheet(material, textures=TEXTURES):
    """-> (colour pixels, normal pixels) of a GROUND_PX sheet covering GROUND_SHEET_M; the
    normal map has its green channel flipped for BeamNG (DirectX convention; ambientCG ships GL)."""
    import numpy as np
    (base, bm), (patch, pm, pc), (wear, wm, wc), tint = GROUND_RECIPES[material]
    key = int.from_bytes(hashlib.sha256(material.encode()).digest()[:4], 'big')
    layers = {}
    for name, metres in ((base, bm), (patch, pm), (wear, wm)):
        layers[name] = (_ground_layer(textures, name, metres, 'RGB'), _ground_layer(textures, name, metres, 'N'))
    # The shader's turned second sample: here the base turned 90 degrees and shifted half a
    # repeat (both keep the sheet tileable), mixed in by noise so the 3 m grid does not show.
    shift = GROUND_PX // round(GROUND_SHEET_M/bm) // 2
    turned_c = np.roll(np.rot90(layers[base][0]), (shift, shift), (0, 1))
    turned_n = np.roll(np.rot90(layers[base][1]), (shift, shift), (0, 1))
    turned_n = np.stack([1 - turned_n[..., 1], turned_n[..., 0], turned_n[..., 2]], -1)  # turn the slope too
    k = _cover(_periodic_noise(key + 99, 6), .5, np.full((GROUND_PX, GROUND_PX), .4, np.float32))
    colour = layers[base][0]*(1 - k) + turned_c*k
    normal = layers[base][1]*(1 - k) + turned_n*k
    target = colour.reshape(-1, 3).mean(0)
    for name, cover, amount, cycles in ((patch, pc, .6, 2), (wear, wc, .3, 4)):
        own_c, own_n = layers[name]
        own_c = own_c * (1 + amount*(target/np.maximum(own_c.reshape(-1, 3).mean(0), .02) - 1))
        noise = (_periodic_noise(key + cycles, cycles)*.7 + _periodic_noise(key + 7*cycles, 3*cycles)*.2
                 + _periodic_noise(key + 13*cycles, 24)*.1)
        mask = _cover(noise, cover, own_c.mean(2))
        colour = colour*(1 - mask) + own_c*mask
        normal = normal*(1 - mask) + own_n*mask
    grey = (colour @ np.array([.3, .59, .11], dtype=np.float32))[..., None]
    colour = (grey + (colour - grey)*GROUND_SATURATION) * np.array(tint, dtype=np.float32)
    normal[..., 1] = 1 - normal[..., 1]
    to_bytes = lambda a: list(np.clip(a*255 + .5, 0, 255).astype('uint8').tobytes())
    return to_bytes(colour), to_bytes(normal)


# --- synthwave (facade_style 2) ------------------------------------------------------
# Fully procedural: no pack. Facades are dark tiles with lit neon windows (used as both the
# colour and the emissive map), ground is a neon grid, roads and pavements go dark.
SYNTH_NEON = ((1.0, .12, .6), (.1, .85, 1.0), (.62, .22, 1.0), (1.0, .42, .12), (.95, .2, .95))
SYNTH_WALL = (5, 4, 9)
SYNTH_GRID_M = 12.0           # two grid squares per GROUND_SHEET_M sheet
SYNTH_FINE_M = 3.0


def family(style):
    """'procedural', 'photo', 'synth' or 'nes' by the style's facade_style (0, 1, 2, 3)."""
    return {0: 'procedural', 1: 'photo', 2: 'synth', 3: 'nes'}.get(styles()[style]['facade_style'], 'photo')


def _rgb(colour, gain=1.0):
    return tuple(max(0, min(255, round(c*255*gain))) for c in colour)


def synth_tile(key):
    """2 x 2 cells of 3 m: lit windows in the building's neon hue (a few in a second), dark
    unlit panes, a neon slab line at the bottom of the repeat (every second storey)."""
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (TILE_PX, TILE_PX), SYNTH_WALL)
    draw = ImageDraw.Draw(image)
    neon = SYNTH_NEON[int(_unit('neon', key)*len(SYNTH_NEON))]
    alt = SYNTH_NEON[int(_unit('alt', key)*len(SYNTH_NEON))]
    for bx in range(2):
        for sy in range(2):
            x0, y0 = bx*CELL, sy*CELL
            box = (x0+.22*CELL, y0+(1-.82)*CELL, x0+.78*CELL, y0+(1-.32)*CELL)
            lit = _unit('lit', key, bx, sy) < .55
            pane = alt if _unit('pane', key, bx, sy) < .18 else neon
            draw.rectangle(box, fill=_rgb(pane, .65 + .35*_unit('gain', key, bx, sy)) if lit else (12, 11, 20))
    draw.rectangle((0, TILE_PX-4, TILE_PX, TILE_PX-1), fill=_rgb(neon, .55))
    return image


def synth_end_tile(key):
    """Blank end wall: dark with a faint neon grid on the 3 m storey / bay lines."""
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (TILE_PX, TILE_PX), SYNTH_WALL)
    draw = ImageDraw.Draw(image)
    line = _rgb(SYNTH_NEON[int(_unit('neon', key)*len(SYNTH_NEON))], .35)
    for i in range(2):
        draw.rectangle((i*CELL, 0, i*CELL+2, TILE_PX), fill=line)
        draw.rectangle((0, i*CELL, TILE_PX, i*CELL+2), fill=line)
    return image


def synth_ground(material):
    """-> pixels of a GROUND_PX sheet over GROUND_SHEET_M: dark ground, bright grid every
    SYNTH_GRID_M and a faint one every SYNTH_FINE_M (magenta on bare ground, teal on grass)."""
    from PIL import Image, ImageDraw
    teal = material == 'kyiv_grass'
    image = Image.new('RGB', (GROUND_PX, GROUND_PX), (3, 8, 12) if teal else (6, 3, 12))
    draw = ImageDraw.Draw(image)
    colour = SYNTH_NEON[1] if teal else SYNTH_NEON[0]
    px_m = GROUND_PX/GROUND_SHEET_M
    for step, width, gain in ((SYNTH_FINE_M, 2, .3), (SYNTH_GRID_M, 6, 1.0)):
        for i in range(round(GROUND_SHEET_M/step)):
            c = round(i*step*px_m)
            # Lines straddle the sheet edge so the repeat seam is one continuous line.
            for at in (c, c + GROUND_PX) if c == 0 else (c,):
                draw.rectangle((at-width//2, 0, at+width//2, GROUND_PX), fill=_rgb(colour, gain))
                draw.rectangle((0, at-width//2, GROUND_PX, at+width//2), fill=_rgb(colour, gain))
    return list(image.tobytes())


# --- 8-bit NES (facade_style 3) --------------------------------------------------------
# Fully procedural, the same drawing as facade.gdshader / surface.gdshader's NES branches: a
# 3.3 x 3 m cell is 12 x 12 console pixels in the NES (2C02) palette, scaled up with nearest
# neighbour so the blocks stay hard. BeamNG has no screen filter: the textures carry the look.
NES = {'black': (0, 0, 0), 'white': (252, 252, 252), 'grey': (124, 124, 124), 'light': (188, 188, 188),
       'dark': (74, 74, 74), 'navy': (0, 0, 188), 'blue': (0, 88, 248), 'sky': (92, 148, 252),
       'cyan': (60, 188, 252), 'brick': (200, 76, 12), 'brick_dark': (136, 20, 0), 'brick_light': (252, 152, 56),
       'cream': (252, 224, 168), 'gold': (248, 184, 0), 'green': (0, 168, 0), 'green_dark': (0, 88, 0),
       'green_light': (88, 216, 84), 'dirt': (172, 124, 0), 'dirt_dark': (80, 48, 0), 'roof_red': (168, 16, 0)}
NES_KINDS = ('brick', 'panel', 'plaster', 'glass')
NES_PIXEL_M = 0.5             # ground pixel


def nes_kind(kind, key):
    """Facade kind (texture_styles / export kinds, or None for a stock set) -> NES sprite kind."""
    if kind == 'brick' or 'brick' in key:
        return 'brick'
    if kind in ('panel', 'loggia'):
        return 'panel'
    if kind == 'plaster':
        return 'plaster'
    return NES_KINDS[1 + int(_unit('nes', key) * 3)]


def _nes_cell(kind, key, bx, sy, end=False):
    """One 12 x 12 cell as rows of palette names (row 0 at the top)."""
    base, shade, light = {'brick': ('brick', 'brick_dark', 'brick_light'), 'panel': ('light', 'grey', 'white'),
                          'plaster': ('cream', 'gold', 'white'), 'glass': ('cyan', 'blue', 'white')}[kind]
    rows = []
    for y in range(12):
        gy = 11 - y + sy*12            # from the bottom, as the shader's f.y
        row = []
        for x in range(12):
            if kind == 'brick':
                qx = x + bx*12
                b_x, b_y = (qx + (gy // 3 % 2) * 2) % 4, gy % 3
                c = shade if b_x == 0 or b_y == 0 else (light if b_y == 2 and b_x == 1 else base)
            else:
                c = base
                if x == 0 or (11 - y) == 0:
                    c = shade if kind == 'panel' else base
                if kind != 'panel' and (x + (11 - y)) % 4 == 0 and (11 - y) > 9:
                    c = shade
            row.append(c)
        rows.append(row)
    if not end:
        lit = _unit('nes_lit', key, bx, sy) > .8
        for y in range(12):
            fy = 11 - y
            for x in range(12):
                if 3 <= x <= 8 and 3 <= fy <= 9:
                    inner = 4 <= x <= 7 and 4 <= fy <= 8
                    rows[y][x] = ('gold' if lit else 'navy') if inner else 'black'
                    if inner and not lit and x == 5 and fy == 7:
                        rows[y][x] = 'white'
    return rows


def _nes_image(cells):
    """2 x 2 cells (bx, sy) -> TILE_PX square, nearest-neighbour upscale."""
    from PIL import Image
    small = Image.new('RGB', (24, 24))
    for (bx, sy), rows in cells.items():
        for y, row in enumerate(rows):
            for x, name in enumerate(row):
                small.putpixel((bx*12 + x, (1 - sy)*12 + y), NES[name])
    return small.resize((TILE_PX, TILE_PX), Image.NEAREST)


def nes_tile(kind, key):
    """6 m repeat: 2 bays x 2 storeys of the NES facade sprite."""
    return _nes_image({(bx, sy): _nes_cell(kind, key, bx, sy) for bx in range(2) for sy in range(2)})


def nes_end_tile(kind, key):
    return _nes_image({(bx, sy): _nes_cell(kind, key, bx, sy, end=True) for bx in range(2) for sy in range(2)})


def nes_ground(material):
    """-> pixels of a GROUND_PX sheet over GROUND_SHEET_M in half-metre console pixels: two
    greens with light tufts on grass, light lawn with SMB dirt patches on bare ground."""
    from PIL import Image
    n = round(GROUND_SHEET_M / NES_PIXEL_M)
    small = Image.new('RGB', (n, n))
    grass = material == 'kyiv_grass'
    for y in range(n):
        for x in range(n):
            h = _unit('nes_g', material, x, y)
            # periodic blobs so the sheet repeats without a seam
            import math
            big = (math.sin(2*math.pi*x/n*2 + 1.3) + math.sin(2*math.pi*y/n*2 + .4) + math.sin(2*math.pi*(x+y)/n*3)) / 3
            if grass:
                c = 'green_dark' if big > .45 else 'green'
                if h > .93:
                    c = 'green_light'
            else:
                c = 'green' if h > .9 else 'green_light'
                if big > .55:
                    c = 'dirt_dark' if h > .85 else 'dirt'
            small.putpixel((x, y), NES[c])
    return list(small.resize((GROUND_PX, GROUND_PX), Image.NEAREST).tobytes())
