"""World v2 geometry: metres, X east, Y up, Z south (Godot compatible)."""
TILED = ('road_strips', 'markings', 'sidewalks', 'walkingareas', 'junctions', 'buildings',
         'greens', 'parking', 'paths', 'trees', 'ground', 'signs', 'fences', 'visual_props')
COORDINATES = {'units': 'metres', 'axes': {'x': 'east', 'y': 'up', 'z': 'south'},
               'beamng': '[x, -z, y + vertical_offset]',
               'height': 'relative to base_height; smoothed DEM, synthetic structures',
               'horizontal_origin': 'SUMO projection with index.offset subtracted'}
