import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import visual_tags

class VisualPackTests(unittest.TestCase):
    def test_metadata_never_claims_unobserved_details(self):
        fixes={'3':{'family':'modern','source':'reference-2026'}}
        brick=visual_tags.classify(1,{'building':'apartments','building:material':'brick'},fixes)
        self.assertEqual((brick['visual_family'],brick['visual_source'],brick['building_type']),('brick','osm','apartments'))
        plain=visual_tags.classify(2,{'building':'yes'},fixes)
        self.assertEqual(plain['visual_source'],'synthetic')
        self.assertNotIn('visual_family',plain)
        fixed=visual_tags.classify(3,{},fixes)
        self.assertEqual((fixed['visual_family'],fixed['visual_source']),('modern','reference-2026'))

    def test_overrides_use_known_families(self):
        style=json.loads((ROOT/'config/visuals/style.json').read_text())
        for fix in visual_tags.overrides().values():
            self.assertIn(fix['family'],style['families'])

    def test_assets_are_pinned_and_stay_in_catalog_directory(self):
        cfg=json.loads((ROOT/'config/visuals/downloads.json').read_text())
        for pack in cfg['packs'].values():
            self.assertEqual(pack['license'],'CC0-1.0')
            for name,file in pack['files'].items():
                self.assertNotIn('..',Path(name).parts)
                self.assertEqual(len(file['sha256']),64)
                self.assertGreater(file['size'],0)

if __name__=='__main__':unittest.main()
