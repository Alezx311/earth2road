"""Playtest 2026-10-06 note 3: one lane count around a roundabout."""
import unittest
import xml.etree.ElementTree as ET

from akadem_maps.core import roundabouts


def osm(tags_a, tags_b, approach='<tag k="highway" v="primary"/><tag k="lanes" v="6"/>'):
    return ET.fromstring(f'''<osm>
      <node id="1" lon="0" lat="0"/><node id="2" lon="0.001" lat="0"/><node id="3" lon="0.001" lat="0.001"/><node id="9" lon="0.002" lat="0"/>
      <way id="a"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="highway" v="secondary"/><tag k="junction" v="roundabout"/>{tags_a}</way>
      <way id="b"><nd ref="3"/><nd ref="1"/><tag k="highway" v="secondary"/><tag k="junction" v="roundabout"/>{tags_b}</way>
      <way id="c"><nd ref="9"/><nd ref="2"/>{approach}</way>
    </osm>''')


def lanes(root):
    return {w.get('id'): {t.get('k'): t.get('v') for t in w.findall('tag')}.get('lanes') for w in root.findall('way')}


class RoundaboutTests(unittest.TestCase):
    def run_unify(self, root):
        nodes = {n.get('id'): (float(n.get('lon')), float(n.get('lat'))) for n in root.iter('node')}
        return roundabouts.unify(root, nodes, lambda t: 'highway' in t)

    def test_piecewise_tags_become_one_weighted_value(self):
        root = osm('<tag k="lanes" v="2"/>', '<tag k="lanes" v="4"/>')
        (rep,) = self.run_unify(root)
        self.assertEqual(lanes(root)['a'], lanes(root)['b'])
        self.assertEqual(rep['source'], 'osm_ring_weighted_mean')
        self.assertEqual(lanes(root)['c'], '6')

    def test_untagged_ring_takes_widest_approach_capped(self):
        root = osm('', '')
        (rep,) = self.run_unify(root)
        self.assertEqual((lanes(root)['a'], lanes(root)['b'], rep['source']), ('3', '3', 'derived_widest_approach'))

    def test_consistent_ring_untouched(self):
        root = osm('<tag k="lanes" v="2"/>', '<tag k="lanes" v="2"/>')
        self.assertEqual(self.run_unify(root), [])


if __name__ == '__main__':
    unittest.main()
