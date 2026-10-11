shader_type spatial;
render_mode cull_disabled;
global uniform int facade_style;   // 3 = 8-bit NES: two palette greens
varying vec3 world;
void vertex() {
	world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	VERTEX.x += sin(TIME * 1.3 + world.x * 0.7 + world.z) * 0.025;
}
void fragment() {
	vec2 grid = floor(UV * 3.0);
	vec2 q = fract(UV * 3.0) * 2.0 - 1.0;
	q.x += sin(grid.y * 3.1 + grid.x) * 0.2;
	float vein = abs(q.x) + pow(abs(q.y), 1.5);
	ALPHA = 1.0 - smoothstep(0.82, 1.0, vein);
	ALPHA_SCISSOR_THRESHOLD = 0.5;
	vec3 green = mix(vec3(0.11,0.22,0.065), vec3(0.28,0.37,0.10), UV.y);
	ALBEDO = green * COLOR.rgb;
	ROUGHNESS = 0.85;
	BACKLIGHT = vec3(0.22,0.29,0.075) * 0.35;
	if (facade_style == 3) {
		ALBEDO = mod(grid.x + grid.y, 2.0) < 0.5 ? vec3(0.0, 0.659, 0.0) : vec3(0.0, 0.345, 0.0);
		BACKLIGHT = vec3(0.0);
		ROUGHNESS = 1.0;
	}
}
