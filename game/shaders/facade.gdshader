// Procedural facade. UV = (metres along wall, metres above ground). COLOR.r tints per building,
// COLOR.g = 1 marks a shop ground floor, COLOR.b = family / 5 (panel, brick, insulated, modern,
// public, retail; see visuals/tile.gd). Windows assume a 3 m storey and 3.3 m bay.
shader_type spatial;
uniform sampler2D wall_noise : filter_linear_mipmap, repeat_enable;
uniform sampler2D wall_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool has_normal = false;
uniform bool dna_enabled = false;
uniform vec4 dna_color : source_color = vec4(0.7, 0.7, 0.65, 1.0);
uniform int dna_architecture = 0; // historic, brick, panel, modern, industrial
uniform int dna_material = 0; // plaster, brick, concrete, glass, metal, stone
// Photo textures from the Panelka pack (tools/import_panelka.py); procedural walls without them.
// panels: PANEL_LAYERS modules side by side, one storey x one bay each, the last one blank.
uniform bool has_panels = false;
uniform sampler2D panels : source_color, filter_linear_mipmap_anisotropic;
uniform bool has_bricks = false;
uniform sampler2D brick_red : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D brick_white : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D brick_red_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D brick_white_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool has_loggias = false;
uniform sampler2D loggia_atlas : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
const vec2 LOGGIA_GRID = vec2(5.0, 11.0);   // tools/import_panelka.py LOGGIA_GRID
const float LOGGIA_BAY = 6.6;
uniform bool has_plaster = false;
uniform sampler2D plaster : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
global uniform int facade_style;
const float PANEL_LAYERS = 6.0;
const vec2 PLASTER_METRES = vec2(4.0, 4.0);
const vec2 BRICK_METRES = vec2(2.0, 1.8);
varying vec3 wn;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
void vertex() { wn = (MODEL_MATRIX * vec4(NORMAL,0.0)).xyz; }
void fragment() {
	float family = floor(COLOR.b * 5.0 + 0.5);
	vec3 colors[6] = vec3[](vec3(.65,.64,.59), vec3(.48,.34,.25), vec3(.76,.72,.60), vec3(.66,.68,.66), vec3(.64,.61,.53), vec3(.55,.55,.51));
	vec3 wall = colors[int(family)] * (0.93 + COLOR.r * 0.12);
	if(dna_enabled) wall = dna_color.rgb;
	float floor_height = 3.0;
	vec2 cell = floor(UV / vec2(3.3, floor_height));
	vec2 f = fract(UV / vec2(3.3, floor_height));
	float grime = texture(wall_noise, UV * .055).r;
	wall *= .91 + .13 * grime;
	wall *= mix(.76,1.0,smoothstep(0.0,2.0,UV.y));
	// Panel seams 5 cm wide, antialiased and faded once a pixel spans more than ~10 cm:
	// hard step() lines crawled ("flickered") on photo panels as the camera moved.
	vec2 fw = fwidth(UV);
	vec2 edge = vec2(min(f.x,1.0-f.x)*3.3, min(f.y,1.0-f.y)*floor_height);
	float seams = max(1.0-smoothstep(.025-fw.x,.025+fw.x,edge.x), 1.0-smoothstep(.025-fw.y,.025+fw.y,edge.y));
	seams *= 1.0 - smoothstep(.04,.12,max(fw.x,fw.y));
	if(dna_enabled ? dna_material == 2 : family < .5) wall *= 1.0 - seams * .19;
	if(dna_enabled ? dna_material == 1 : (family > .5 && family < 1.5)) {
		vec2 brick = fract(vec2(UV.x / .27 + mod(floor(UV.y/.09),2.0)*.5, UV.y/.09));
		float mortar = max(1.0-step(.045,brick.x),1.0-step(.07,brick.y));
		wall = mix(wall,vec3(.46,.43,.37),mortar*.6);
	}
	float window = step(.22,f.x)*step(f.x,.78)*step(.32,f.y)*step(f.y,.82);
	float inner = step(.24,f.x)*step(f.x,.76)*step(.34,f.y)*step(f.y,.80);
	if(dna_enabled) {
		float lo = dna_architecture == 0 ? .24 : (dna_architecture >= 3 ? .08 : .18);
		float hi = dna_architecture == 0 ? .64 : (dna_architecture >= 3 ? .92 : .82);
		float bottom = dna_architecture == 4 ? .35 : .22;
		float top = dna_architecture == 0 ? .85 : .78;
		window = step(lo,f.x)*step(f.x,hi)*step(bottom,f.y)*step(f.y,top);
		inner = step(lo+.025,f.x)*step(f.x,hi-.025)*step(bottom+.025,f.y)*step(f.y,top-.025);
		if(dna_architecture == 0 && f.y < .09) wall = vec3(.82,.79,.72);
	}
	float mullion = 1.0-step(.014,abs(f.x-.5));
	float frame = window*(1.0-inner + inner*mullion);
	float shop = COLOR.g*step(.25,UV.y)*step(UV.y,2.8);
	window = max(window,shop*step(.07,fract(UV.x/3.3))*step(fract(UV.x/3.3),.93));
	float blind = step(.62,hash(cell + COLOR.r*31.0))*step(.58,f.y);
	vec3 glass = mix(vec3(.075,.12,.145),vec3(.24,.30,.31),hash(cell+COLOR.r*9.0));
	glass = mix(glass,vec3(.41,.39,.32),blind*.62);
	float roof = step(.6,abs(wn.y));
	float glazing = window * (1.0-clamp(frame,0.0,1.0))*(1.0-roof);
	// facade_style (global, scripts/styles.gd): 0 procedural, 1 photo pack. In the photo style every
	// family gets a pack surface: panel-like blocks the photo panels, brick blocks photo brick, the
	// rest photo plaster tinted by the family / OSM colour under the procedural windows.
	bool photo = facade_style == 1 && has_panels && has_bricks;
	bool is_panel = dna_enabled ? (dna_architecture == 2 || dna_architecture == 3 || dna_material == 2) : (family < .5 || (family > 1.5 && family < 3.5));
	bool is_brick = dna_enabled ? (dna_material == 1 || dna_architecture == 1) : (family > .5 && family < 1.5);
	bool shop_floor = COLOR.g > .5 && UV.y < 3.0;
	// COLOR.a (world.gd): 1 windows, .5 loggias, each .25 less on an end wall.
	bool end_wall = COLOR.a < .375 || (COLOR.a > .625 && COLOR.a < .875);
	bool loggia_block = COLOR.a < .625;
	if(photo && is_brick && end_wall) { glazing = 0.0; frame = 0.0; }
	vec3 hue = dna_enabled ? dna_color.rgb : colors[int(family)];
	vec3 tint = mix(vec3(1.0), hue / max(dot(hue, vec3(1.0/3.0)), .05), .5);
	if(photo && is_panel && roof < .5 && !shop_floor) {
		// One photo panel per cell. A building keeps one window style; ~10 % of flats replaced
		// theirs; a few blank panels. Gradients from the continuous UV avoid mip seams at cell edges.
		// Layer 2 (window grille) only on the ground floor; the others are the building's style.
		float own = floor(hash(vec2(COLOR.r*53.0, 7.0)) * 4.0);
		own += step(1.5, own);
		float swap = floor(hash(cell.yx + COLOR.r*29.0) * 4.0);
		swap += step(1.5, swap);
		float layer = hash(cell + COLOR.r*13.0) < .1 ? swap : own;
		if(cell.y < .5 && hash(cell + COLOR.r*41.0) < .35) layer = 2.0;
		if(hash(cell*1.7 + COLOR.r*3.0) > .97 || end_wall) layer = PANEL_LAYERS-1.0;
		vec2 q = UV / vec2(3.3, floor_height);
		vec2 uv = vec2((layer + clamp(f.x,.003,.997)) / PANEL_LAYERS, 1.0 - clamp(f.y,.003,.997));
		vec2 dx = dFdx(q) * vec2(1.0/PANEL_LAYERS, -1.0), dy = dFdy(q) * vec2(1.0/PANEL_LAYERS, -1.0);
		ALBEDO = textureGrad(panels, uv, dx, dy).rgb * (1.0 - seams * .35);
		if(has_loggias && loggia_block && !end_wall && UV.y >= floor_height) {
			// Loggia blocks: the whole II-68 photo (5 bays x 11 storeys = 33 x 33 m) as one
			// continuous facade above the ground floor, shifted by whole bays per building.
			float shift = floor(hash(vec2(COLOR.r*61.0, 2.0)) * LOGGIA_GRID.x) * LOGGIA_BAY;
			vec2 sheet = LOGGIA_GRID * vec2(LOGGIA_BAY, floor_height);
			ALBEDO = texture(loggia_atlas, vec2((UV.x + shift) / sheet.x, 1.0 - (UV.y - floor_height) / sheet.y)).rgb;
		}
		ALBEDO *= (.92 + COLOR.r*.14) * mix(.8,1.0,smoothstep(0.0,2.0,UV.y)) * tint;
		ROUGHNESS = .86;
	} else {
		if(photo && is_brick && roof < .5) {
			bool white = hash(vec2(COLOR.r*71.0, 3.0)) < .4;
			vec2 b = UV / BRICK_METRES;
			vec3 bricks = white ? texture(brick_white, b).rgb : texture(brick_red, b).rgb;
			wall = bricks * (.9 + COLOR.r*.15) * mix(.8,1.0,smoothstep(0.0,2.0,UV.y));
			NORMAL_MAP = mix(white ? texture(brick_white_normal,b).rgb : texture(brick_red_normal,b).rgb, vec3(.5,.5,1.0), glazing);
			NORMAL_MAP_DEPTH = .6;
		} else if(photo && has_plaster && roof < .5) {
			wall = texture(plaster, UV / PLASTER_METRES).rgb * hue / .62 * (.93 + COLOR.r*.12) * mix(.8,1.0,smoothstep(0.0,2.0,UV.y));
			if(has_normal) { NORMAL_MAP = mix(texture(wall_normal,UV*.3).rgb,vec3(.5,.5,1.0),glazing); NORMAL_MAP_DEPTH=.32; }
		} else if(has_normal) { NORMAL_MAP = mix(texture(wall_normal,UV*.3).rgb,vec3(.5,.5,1.0),glazing); NORMAL_MAP_DEPTH=.32; }
		ALBEDO = mix(wall,glass,glazing);
		ALBEDO = mix(ALBEDO,vec3(.71,.72,.69),clamp(frame,0.0,1.0)*(1.0-roof));
		ROUGHNESS = mix(.88,.22,glazing);
		METALLIC = glazing*.12;
	}
}
