#!/usr/bin/env python3
"""Build facade textures from Kureca's Panelka pack (CC0, https://kureca.itch.io/panelka-pack).

itch.io serves the ZIP only through a browser button, so the owner downloads it and unpacks it
into texture_packs/Panelka (git-ignored). This script reads only the PNG files named below and
writes into game/assets/textures (git-ignored, like tools/fetch_textures.py):

  panelka_panels/albedo.jpg   6 panel modules (one storey x one bay each) side by side
  panelka_brick_red/{albedo,normal}.jpg, panelka_brick_white/{albedo,normal}.jpg
  panelka_plaster/albedo.jpg  walls of public, retail and historic buildings
  panelka_loggias/albedo.jpg  55 loggia modules (6.6 m bay x 3 m storey) cut from the II-68 photo

The facade shader (game/shaders/facade.gdshader) falls back to procedural walls when absent.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT/'game/assets/textures'
SOURCE = 'https://kureca.itch.io/panelka-pack'
LICENSE = 'CC0-1.0 (Kureca, Panelka pack)'
# Order is the atlas layer index used by facade.gdshader (PANEL_LAYERS there).
PANELS = ['Panels/Panel1.png', 'Panels/Panel2.png', 'Panels/Panel4.png', 'Panels/Panel5.png',
          'Panels/Panel6.png', 'Panels/Panel3.png']          # last: blank panel, no window
BRICKS = {'panelka_brick_red': ('Walls/Bricks/BrickWall1diffuse.png', 'Walls/Bricks/BrickWall1normal.png'),
          'panelka_brick_white': ('Walls/Bricks/Bricks1diffuse.png', 'Walls/Bricks/Bricks1normal.png')}
PLASTER = 'Concrete1diffuse.png'      # public, retail and historic walls (tinted in the shader)
# II-68: a photo of a whole 16-storey facade, a regular grid of loggias. Measured from its row and
# column brightness profiles: storey 82.6 px, bay 190.9 px, first edges at y 7 and x 5. The top
# row (attic loggias under the roof) is left out: 5 bays x 11 storeys = 55 loggia modules.
LOGGIAS = 'Panels/II-68.png'
LOGGIA_GRID = dict(storey=82.6, bay=190.9, y0=7, x0=5, cols=5, rows=11, skip_rows=1)
LOGGIA_CELL = (512, 256)              # one 6.6 m bay x one 3 m storey
PANEL_SIZE, BRICK_SIZE = 512, 1024
CROP = 0.05


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _jpg(image, path):
    buf = io.BytesIO()
    image.convert('RGB').save(buf, 'JPEG', quality=90)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    return _sha(buf.getvalue())


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--pack', type=Path, default=ROOT/'texture_packs/Panelka')
    args = p.parse_args()
    sources = {}

    def open_png(rel):
        path = args.pack/rel
        if not path.is_file():
            raise SystemExit(f'Missing {path}; unpack the Panelka pack into {args.pack}')
        sources[rel] = _sha(path.read_bytes())
        return Image.open(path)

    manifest_path = DEST/'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    # Crop the ragged photo edge (the shader draws a thin seam) and bring every panel's wall to
    # one common tone, so a facade of mixed modules does not read as a checkerboard.
    crops = []
    for rel in PANELS:
        im = open_png(rel).convert('RGB')
        w, h = im.size
        crops.append(im.crop((int(w*CROP), int(h*CROP), int(w*(1-CROP)), int(h*(1-CROP))))
                     .resize((PANEL_SIZE, PANEL_SIZE), Image.LANCZOS))
    tones = [ImageStat.Stat(im).median for im in crops]
    target = [sum(t[c] for t in tones)/len(tones) for c in range(3)]
    atlas = Image.new('RGB', (PANEL_SIZE*len(PANELS), PANEL_SIZE))
    for i, (im, tone) in enumerate(zip(crops, tones)):
        bands = [b.point(lambda v, k=target[c]/max(tone[c], 1): min(255, int(v*k))) for c, b in enumerate(im.split())]
        atlas.paste(Image.merge('RGB', bands), (i*PANEL_SIZE, 0))
    files = {'albedo': _jpg(atlas, DEST/'panelka_panels/albedo.jpg')}
    manifest['panelka_panels'] = {'asset': 'Panelka panels', 'source': SOURCE, 'license': LICENSE,
                                  'layers': PANELS, 'files': files,
                                  'sources': {k: sources[k] for k in PANELS}}
    for name, (albedo, normal) in BRICKS.items():
        files = {'albedo': _jpg(open_png(albedo).resize((BRICK_SIZE, BRICK_SIZE), Image.LANCZOS), DEST/name/'albedo.jpg'),
                 'normal': _jpg(open_png(normal).resize((BRICK_SIZE, BRICK_SIZE), Image.LANCZOS), DEST/name/'normal.jpg')}
        manifest[name] = {'asset': 'Panelka '+Path(albedo).stem, 'source': SOURCE, 'license': LICENSE,
                          'files': files, 'sources': {albedo: sources[albedo], normal: sources[normal]}}
    files = {'albedo': _jpg(open_png(PLASTER).resize((BRICK_SIZE, BRICK_SIZE), Image.LANCZOS), DEST/'panelka_plaster/albedo.jpg')}
    manifest['panelka_plaster'] = {'asset': 'Panelka Concrete1', 'source': SOURCE, 'license': LICENSE,
                                   'files': files, 'sources': {PLASTER: sources[PLASTER]}}
    g = LOGGIA_GRID
    photo = open_png(LOGGIAS).convert('RGB')
    cells = []
    for k in range(g['skip_rows'], g['skip_rows']+g['rows']):
        for j in range(g['cols']):
            box = (round(g['x0']+j*g['bay']), round(g['y0']+k*g['storey']),
                   round(g['x0']+(j+1)*g['bay']), round(g['y0']+(k+1)*g['storey']))
            cells.append(photo.crop(box).resize(LOGGIA_CELL, Image.LANCZOS))
    # The photo is graded dark and blue: bring its median to the panels' wall tone.
    sheet = Image.new('RGB', (LOGGIA_CELL[0]*g['cols'], LOGGIA_CELL[1]*g['rows']))
    for i, cell in enumerate(cells):
        sheet.paste(cell, ((i % g['cols'])*LOGGIA_CELL[0], (i//g['cols'])*LOGGIA_CELL[1]))
    tone = ImageStat.Stat(sheet).median
    sheet = Image.merge('RGB', [b.point(lambda v, k=target[c]/max(tone[c], 1): min(255, int(v*k)))
                                for c, b in enumerate(sheet.split())])
    files = {'albedo': _jpg(sheet, DEST/'panelka_loggias/albedo.jpg')}
    manifest['panelka_loggias'] = {'asset': 'Panelka II-68 loggias', 'source': SOURCE, 'license': LICENSE,
                                   'grid': g, 'files': files, 'sources': {LOGGIAS: sources[LOGGIAS]}}
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print('panelka:', ', '.join(k for k in manifest if k.startswith('panelka_')))


if __name__ == '__main__':
    main()
