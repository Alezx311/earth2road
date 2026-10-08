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
