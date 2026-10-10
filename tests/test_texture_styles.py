import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from akadem_maps.adapters.beamng import texture_styles as ts

ROOT = Path(__file__).resolve().parents[1]


def fake_pack(folder):
    """Plain-colour stand-ins for the textures tools/import_panelka.py writes."""
    sizes = {'panelka_panels': (512*ts.PANEL_LAYERS, 512), 'panelka_brick_red': (64, 64),
             'panelka_brick_white': (64, 64), 'panelka_plaster': (64, 64),
             'panelka_loggias': (512*ts.LOGGIA_GRID[0], 256*ts.LOGGIA_GRID[1])}
    for name, size in sizes.items():
        (folder/name).mkdir(parents=True)
        Image.new('RGB', size, (128, 128, 128)).save(folder/name/'albedo.jpg')
    # tools/fetch_textures.py photo ground sets: distinct colours so the patches show.
    for i, name in enumerate(('photo_lawn', 'photo_meadow', 'photo_verge', 'photo_worn', 'photo_trodden')):
        (folder/name).mkdir(parents=True)
        Image.new('RGB', (64, 64), (60 + 30*i, 120, 50)).save(folder/name/'albedo.jpg')
        Image.new('RGB', (64, 64), (128, 100, 255)).save(folder/name/'normal.jpg')


class TextureStyleTests(unittest.TestCase):
    def test_config_lists_procedural_and_godot_reads_the_same_ids(self):
        cfg = json.loads((ROOT/'config/visuals/texture_styles.json').read_text(encoding='utf-8'))
        ids = [s['id'] for s in cfg['styles']]
        self.assertIn('procedural', ids)
        self.assertIn(cfg['default'], ids)
        self.assertEqual(len(set(s['facade_style'] for s in cfg['styles'])), len(ids))

    def test_missing_pack_is_an_error_not_a_silent_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(ts.resolve('procedural', Path(td))['id'], 'procedural')
            with self.assertRaisesRegex(ValueError, 'import_panelka'):
                ts.resolve('panelka', Path(td))
            with self.assertRaises(ValueError):
                ts.resolve('no_such_style', Path(td))

    def test_tiles_are_one_6_m_repeat_and_tinted(self):
        with tempfile.TemporaryDirectory() as td:
            fake_pack(Path(td))
            ts.resolve('panelka', Path(td))
            for kind in ('panel', 'loggia', 'brick', 'plaster'):
                pixels = ts.tile_for(kind, (0.8, 0.6, 0.4), 'kyiv_fac_x', Path(td))
                self.assertEqual(len(pixels), ts.tile_size(kind)[0]**2*3, kind)
                self.assertEqual(len(ts.end_pixels(kind, (0.8, 0.6, 0.4), 'k', Path(td))), ts.TILE_PX**2*3)
            warm = ts.tile_for('panel', (0.8, 0.6, 0.4), 'k', Path(td))
            self.assertGreater(warm[0], warm[2])                  # red above blue after the tint
            self.assertEqual(warm, ts.tile_for('panel', (0.8, 0.6, 0.4), 'k', Path(td)))

    def test_ground_sheet_tiles_mixes_layers_and_flips_normals(self):
        with tempfile.TemporaryDirectory() as td:
            fake_pack(Path(td))
            ts.resolve('panelka', Path(td))
            saved = ts.GROUND_PX
            ts.GROUND_PX = 96
            try:
                colour, normal = ts.ground_sheet('kyiv_ground', Path(td))
            finally:
                ts.GROUND_PX = saved
            self.assertEqual(len(colour), 96*96*3)
            reds = set(colour[0::3])
            self.assertGreater(max(reds) - min(reds), 10)       # verge patches over the lawn
            # Slope GL green 100 (and 128 where the turned sample is mixed in) -> DirectX 127..155.
            greens = normal[1::3]
            self.assertTrue(all(125 <= g <= 157 for g in greens))
            self.assertGreater(sum(greens)/len(greens), 135)
            self.assertEqual(set(ts.GROUND_RECIPES), {'kyiv_grass', 'kyiv_ground'})

    def test_synthwave_needs_no_pack_and_glows(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(ts.resolve('synthwave', Path(td))['facade_style'], 2)
        self.assertEqual([ts.family(s) for s in ('procedural', 'panelka', 'synthwave')], ['procedural', 'photo', 'synth'])
        tile = ts.tile_for('synth', None, 'kyiv_fac_x')
        self.assertEqual(len(tile), ts.TILE_PX**2*3)
        self.assertEqual(tile, ts.tile_for('synth', None, 'kyiv_fac_x'))
        self.assertEqual(tuple(tile[:3]), ts.SYNTH_WALL)                 # dark wall at the corner
        self.assertGreater(max(tile), 150)                              # lit neon windows
        self.assertEqual(len(ts.end_pixels('synth', None, 'k')), ts.TILE_PX**2*3)
        saved = ts.GROUND_PX
        ts.GROUND_PX = 96
        try:
            grass = ts.synth_ground('kyiv_grass')
        finally:
            ts.GROUND_PX = saved
        row = lambda y: grass[y*96*3:(y+1)*96*3]
        self.assertEqual(row(0), row(95))                               # the grid line wraps the seam
        self.assertGreater(grass[1], grass[0])                          # teal on grass

    def test_synthwave_sky_is_a_dusk(self):
        from akadem_maps.adapters.beamng.export_beamng import sky_objects
        day, dusk = sky_objects(4000), sky_objects(4000, synth=True)
        sun = lambda objs: next(o for o in objs if o['class'] == 'ScatterSky')
        self.assertLess(sun(dusk)['elevation'], sun(day)['elevation'])
        self.assertFalse(any(o['class'] == 'CloudLayer' for o in dusk))

    def test_nes_needs_no_pack_and_uses_the_palette(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(ts.resolve('nes', Path(td))['facade_style'], 3)
        self.assertEqual(ts.family('nes'), 'nes')
        self.assertEqual(ts.nes_kind('brick', 'kyiv_fac_x'), 'brick')
        self.assertEqual(ts.nes_kind('loggia', 'kyiv_fac_x'), 'panel')
        self.assertIn(ts.nes_kind(None, 'kyiv_fac_stock'), ('panel', 'plaster', 'glass'))
        palette = set(ts.NES.values())
        for kind in ts.NES_KINDS:
            tile = ts.nes_tile(kind, 'k')
            self.assertEqual(tile.size, (ts.TILE_PX, ts.TILE_PX))
            self.assertTrue({c for _n, c in tile.getcolors(ts.TILE_PX**2)} <= palette)
            self.assertEqual(tile.tobytes(), ts.nes_tile(kind, 'k').tobytes())
            self.assertNotIn(ts.NES['navy'], {c for _n, c in ts.nes_end_tile(kind, 'k').getcolors(ts.TILE_PX**2)})
        saved = ts.GROUND_PX
        ts.GROUND_PX = 96
        try:
            grass, ground = ts.nes_ground('kyiv_grass'), ts.nes_ground('kyiv_ground')
        finally:
            ts.GROUND_PX = saved
        self.assertEqual(len(grass), 96*96*3)
        self.assertTrue({tuple(grass[i:i+3]) for i in range(0, len(grass), 3)} <= palette)
        self.assertNotEqual(grass, ground)

    def test_nes_sky_is_flat_blue_without_clouds(self):
        from akadem_maps.adapters.beamng.export_beamng import sky_objects
        nes = sky_objects(4000, nes=True)
        info = next(o for o in nes if o['class'] == 'LevelInfo')
        self.assertEqual(info['canvasClearColor'][:3], [92, 148, 252])
        self.assertFalse(any(o['class'] == 'CloudLayer' for o in nes))

    def test_end_walls_are_the_short_sides_of_elongated_blocks(self):
        slab = [(0, 0), (60, 0), (60, 12), (0, 12)]            # a 60 x 12 m panel block
        self.assertEqual(ts.end_walls(slab), [False, True, False, True])
        self.assertEqual(ts.end_walls([(0, 0), (20, 0), (20, 18), (0, 18)]), [False]*4)   # a tower
        # An L-shaped block: the 12 m end of the long wing; the wing's 18 m and 30 m sides are facades.
        ell = [(0, 0), (80, 0), (80, 12), (12, 12), (12, 30), (0, 30)]
        self.assertEqual(ts.end_walls(ell), [False, True, False, False, False, False])

    def test_dna_styles_map_like_the_godot_shader(self):
        blocks = [ts.dna_kind({'architecture': 'panel', 'material': 'concrete'}, f'k{i}') for i in range(200)]
        self.assertEqual(set(blocks), {'panel', 'loggia'})
        self.assertGreater(blocks.count('loggia'), blocks.count('panel'))
        self.assertIn(ts.dna_kind({'architecture': 'modern', 'material': 'glass'}), ('panel', 'loggia'))
        self.assertEqual(ts.dna_kind({'architecture': 'brick', 'material': 'brick'}), 'brick')
        self.assertEqual(ts.dna_kind({'architecture': 'historic', 'material': 'plaster'}), 'plaster')


if __name__ == '__main__':
    unittest.main()
