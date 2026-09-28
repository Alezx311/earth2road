// Procedural facade. UV = (metres along wall, metres above ground). COLOR.r tints per building,
// COLOR.g = 1 marks a shop ground floor, COLOR.b = family / 5 (panel, brick, insulated, modern,
// public, retail; see visuals/tile.gd). Windows assume a 3 m storey and 3.3 m bay.
shader_type spatial;
uniform sampler2D wall_noise : filter_linear_mipmap, repeat_enable;
uniform sampler2D wall_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform bool has_normal = false;
varying vec3 wn;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
void vertex() { wn = (MODEL_MATRIX * vec4(NORMAL,0.0)).xyz; }
void fragment() {
	float family = floor(COLOR.b * 5.0 + 0.5);
	vec3 colors[6] = vec3[](vec3(.65,.64,.59), vec3(.48,.34,.25), vec3(.76,.72,.60), vec3(.66,.68,.66), vec3(.64,.61,.53), vec3(.55,.55,.51));
	vec3 wall = colors[int(family)] * (0.93 + COLOR.r * 0.12);
	float floor_height = 3.0;
	vec2 cell = floor(UV / vec2(3.3, floor_height));
	vec2 f = fract(UV / vec2(3.3, floor_height));
	float grime = texture(wall_noise, UV * .055).r;
	wall *= .91 + .13 * grime;
	wall *= mix(.76,1.0,smoothstep(0.0,2.0,UV.y));
	float seams = max(1.0-step(.012,f.x),1.0-step(.018,f.y));
	if(family < .5) wall *= 1.0 - seams * .19;
	if(family > .5 && family < 1.5) {
		vec2 brick = fract(vec2(UV.x / .27 + mod(floor(UV.y/.09),2.0)*.5, UV.y/.09));
		float mortar = max(1.0-step(.045,brick.x),1.0-step(.07,brick.y));
		wall = mix(wall,vec3(.46,.43,.37),mortar*.6);
	}
	float window = step(.22,f.x)*step(f.x,.78)*step(.32,f.y)*step(f.y,.82);
	float inner = step(.24,f.x)*step(f.x,.76)*step(.34,f.y)*step(f.y,.80);
	float mullion = 1.0-step(.014,abs(f.x-.5));
	float frame = window*(1.0-inner + inner*mullion);
	float shop = COLOR.g*step(.25,UV.y)*step(UV.y,2.8);
	window = max(window,shop*step(.07,fract(UV.x/3.3))*step(fract(UV.x/3.3),.93));
	float blind = step(.62,hash(cell + COLOR.r*31.0))*step(.58,f.y);
	vec3 glass = mix(vec3(.075,.12,.145),vec3(.24,.30,.31),hash(cell+COLOR.r*9.0));
	glass = mix(glass,vec3(.41,.39,.32),blind*.62);
	float roof = step(.6,abs(wn.y));
	float glazing = window * (1.0-clamp(frame,0.0,1.0))*(1.0-roof);
	ALBEDO = mix(wall,glass,glazing);
	ALBEDO = mix(ALBEDO,vec3(.71,.72,.69),clamp(frame,0.0,1.0)*(1.0-roof));
	ROUGHNESS = mix(.88,.22,glazing);
	METALLIC = glazing*.12;
	if(has_normal) { NORMAL_MAP = mix(texture(wall_normal,UV*.3).rgb,vec3(.5,.5,1.0),glazing); NORMAL_MAP_DEPTH=.32; }
}
