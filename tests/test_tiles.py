import json
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import paths

def tile_of(p,size):
    return f'{math.floor(p[0]/size)}_{math.floor(p[2]/size)}'

def centroid(tri):
    return [sum(p[i] for p in tri)/3 for i in range(3)]

MAP=__import__('os').environ.get('AKADEM_MAP','akadem')

@unittest.skipUnless((paths.game_dir(MAP)/'index.json').exists(),'Generate map first')
class TileTests(unittest.TestCase):
    """The tiled world (tools/prepare.py write_world) for Akademmistechko."""
    @classmethod
    def setUpClass(cls):
        cls.index=paths.load_world(MAP)
        cls.folder=paths.game_dir(MAP)
        cls.size=cls.index['tile_size']
        cls.tiles={name:json.loads((cls.folder/'tiles'/f'{name}.json').read_text()) for name in cls.index['tiles']}

    def test_index_matches_files(self):
        files={p.stem for p in (self.folder/'tiles').glob('*.json')}
        self.assertEqual(files,set(self.index['tiles']))
        for key in paths.TILED:
            self.assertNotIn(key,self.index)
        for name,(tx,tz) in self.index['tiles'].items():
            self.assertEqual(name,f'{tx}_{tz}')

    def test_items_sit_in_their_tile(self):
        for name,tile in self.tiles.items():
            for key in ('road_strips','markings','sidewalks','paths','buildings'):
                for item in tile[key]:
                    self.assertEqual(tile_of(item['points'][0],self.size),name,key)
            for key in ('ground','parking'):
                for tri in tile[key]:
                    self.assertEqual(tile_of(centroid(tri),self.size),name,key)
            for area in tile['greens']:
                for tri in area['triangles']:
                    self.assertEqual(tile_of(centroid(tri),self.size),name,'greens')
            for p in tile['trees']:
                self.assertEqual(tile_of(p,self.size),name,'trees')

    def test_every_junction_once(self):
        ids=[j['id'] for tile in self.tiles.values() for j in tile['junctions']]
        self.assertEqual(len(ids),len(set(ids)))

    def test_spawn_tile_has_road(self):
        name=tile_of(self.index['spawn']['position'],self.size)
        self.assertIn(name,self.tiles)
        self.assertTrue(self.tiles[name]['road_strips'] or self.tiles[name]['junctions'])

if __name__=='__main__':
    unittest.main()
