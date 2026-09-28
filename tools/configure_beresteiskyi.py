"""Reproduce the avenue config from the ring and dated OSM anchor coordinates."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configuration():
    cfg = json.loads((ROOT/'config/ring_teremky_berkovets.json').read_text(encoding='utf8'))
    old = cfg['corridor']
    cfg.update(id='ring_beresteiskyi', name='Кільцева + Берестейський · Дачна → Цирк',
               level_id='kyiv_ring_teremky_berkovets')
    cfg['corridor'] = {'buffer_m': 500, 'axes': [
        {**old['axis'], 'lat_range': old['lat_range']},
        {'names': ['Берестейський проспект'], 'highway': ['trunk', 'primary', 'secondary', 'tertiary'],
         'clip_bbox': [30.3499, 50.435, 30.4935, 50.47],
         'endpoints': [{'osm': 'node/7250590943', 'name': 'Дачна', 'lon':30.3499887, 'lat':50.4556883},
                       {'osm': 'node/10128642052', 'name': 'Цирк', 'lon':30.4934637, 'lat':50.4477597}]}]}
    cfg['region_profile'] = 'ukraine'
    cfg['note'] = 'Кільцева без зміни центру і масштабу; відгалуження Берестейським від Дачної до Цирку. Буфер 500 м. Висоти й деталізація синтетичні.'
    cfg['pois']['anchors'] += [
        {'name':'Дачна · початок Берестейського', 'lon':30.35711, 'lat':50.455292, 'heading':90, 'osm':'node/6259690580',
         'note':'~260 m east of the OSM node: avenue edges at the node are shorter than the 120 m spawn minimum'},
        {'name':'Святошин', 'lon':30.394735, 'lat':50.457844, 'heading':90, 'osm':'node/10726245823',
         'note':'~190 m east of the OSM node: the avenue edge at the node is not spawn-eligible'},
        {'name':'Нивки', 'lon':30.4042048, 'lat':50.4585958, 'heading':90, 'osm':'node/3806440513'},
        {'name':'Берестейська', 'lon':30.419688, 'lat':50.4590925, 'heading':90, 'osm':'node/3806424761'},
        {'name':'Шулявка', 'lon':30.4453703, 'lat':50.4550745, 'heading':110, 'osm':'node/3806407690'},
        {'name':'Політехнічний інститут', 'lon':30.466127, 'lat':50.4507932, 'heading':100, 'osm':'node/3806396836'},
        {'name':'Цирк · кінець Берестейського', 'lon':30.4922024, 'lat':50.4481716, 'heading':280, 'osm':'node/4931245318'}]
    return cfg


if __name__ == '__main__':
    (ROOT/'config/ring_beresteiskyi.json').write_text(json.dumps(configuration(),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
