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
    image = {'panel': panel_tile, 'loggia': loggia_sheet, 'brick': brick_tile, 'plaster': plaster_tile}[kind](colour, key, textures)
    return list(image.tobytes())


def tile_size(kind):
    """(pixels, metres) of one repeat of a facade kind."""
    return (SHEET_PX, LOGGIA_SHEET_M) if kind == 'loggia' else (TILE_PX, 6.0)


def end_pixels(kind, colour, key, textures=TEXTURES):
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
