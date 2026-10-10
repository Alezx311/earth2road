// 8-bit NES post effect (texture style 3, main.gd): a full-screen quad drawn after the 3D
// scene. Each console pixel (`block` screen pixels) takes the average of four taps, gets a
// black outline where depth jumps (silhouettes) or the surface turns (creases), and is snapped
// to the NES (2C02) palette. All uniforms are tuned live from config/visuals/nes_tune.json.
shader_type spatial;
render_mode unshaded, depth_draw_never, depth_test_disabled, cull_disabled, fog_disabled, shadows_disabled;

uniform sampler2D screen_tex : hint_screen_texture, filter_nearest;
uniform sampler2D depth_tex : hint_depth_texture, filter_nearest;
uniform sampler2D normal_tex : hint_normal_roughness_texture, filter_nearest;

uniform float block = 4.0;           // screen pixels per console pixel
uniform float brightness = 0.82;
uniform float contrast = 1.15;
uniform float saturation = 1.35;
uniform float dither = 0.0;
uniform float palette_mix = 1.0;     // 0 = no palette snap
uniform float outline = 1.0;         // 0 = no outlines
uniform float outline_depth = 0.06;  // relative depth jump that draws a silhouette
uniform float outline_normal = 0.45; // 1 - cos(angle) between faces that draws a crease
uniform float outline_far = 900.0;   // metres: no outlines beyond (distant noise)

const vec3 PAL[40] = vec3[](
	vec3(0.0), vec3(.486), vec3(.737), vec3(.988), vec3(.290),
	vec3(0.,0.,.988), vec3(0.,0.,.737), vec3(0.,.345,.973), vec3(.408,.533,.988), vec3(.235,.737,.988), vec3(.643,.894,.988),
	vec3(.361,.580,.988),
	vec3(.267,.157,.737), vec3(.408,.267,.988), vec3(.596,.471,.973), vec3(.580,0.,.518), vec3(.973,.471,.973),
	vec3(.659,0.,.125), vec3(.894,0.,.345), vec3(.973,.345,.596),
	vec3(.659,.063,0.), vec3(.973,.220,0.), vec3(.973,.471,.345), vec3(.533,.078,0.), vec3(.784,.298,.047), vec3(.988,.596,.220),
	vec3(.314,.188,0.), vec3(.675,.486,0.), vec3(.973,.722,0.), vec3(.988,.878,.659), vec3(.973,.847,.471),
	vec3(0.,.471,0.), vec3(0.,.659,0.), vec3(.345,.847,.329), vec3(.722,.973,.471), vec3(0.,.345,0.),
	vec3(0.,.408,.267), vec3(0.,.659,.267), vec3(.345,.973,.596), vec3(0.,.533,.533));
const float BAYER[16] = float[](0., 8., 2., 10., 12., 4., 14., 6., 3., 11., 1., 9., 15., 7., 13., 5.);

// The 3D buffer is linear; the palette and all tuning work in sRGB.
vec3 to_srgb(vec3 c) { return mix(c * 12.92, 1.055 * pow(max(c, vec3(0.0)), vec3(1.0/2.4)) - 0.055, step(vec3(0.0031308), c)); }
vec3 to_linear(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }

void vertex() {
	POSITION = vec4(VERTEX.xy, 1.0, 1.0);
}

float linear_depth(vec2 uv, mat4 inv_proj) {
	float d = textureLod(depth_tex, uv, 0.0).r;
	vec4 v = inv_proj * vec4(uv * 2.0 - 1.0, d, 1.0);
	return -v.z / v.w;
}

vec3 normal_at(vec2 uv) {
	return normalize(textureLod(normal_tex, uv, 0.0).xyz * 2.0 - 1.0);
}

void fragment() {
	vec2 px = 1.0 / VIEWPORT_SIZE;
	vec2 cell = floor(FRAGCOORD.xy / block);
	vec2 uv = (cell * block + block * 0.5) * px;
	vec2 q = block * 0.25 * px;
	vec3 c = (textureLod(screen_tex, uv + vec2(-q.x, -q.y), 0.0).rgb + textureLod(screen_tex, uv + vec2(q.x, -q.y), 0.0).rgb
		+ textureLod(screen_tex, uv + vec2(-q.x, q.y), 0.0).rgb + textureLod(screen_tex, uv + vec2(q.x, q.y), 0.0).rgb) * 0.25;
	c = to_srgb(c);
	c = (c - 0.5) * contrast + 0.5;
	c *= brightness;
	c = clamp(mix(vec3(dot(c, vec3(0.3, 0.59, 0.11))), c, saturation), 0.0, 1.0);
	int b = int(mod(cell.x, 4.0)) + int(mod(cell.y, 4.0)) * 4;
	c += (BAYER[b] / 16.0 - 0.47) * dither;
	vec3 best = PAL[0];
	float bd = 1e9;
	for (int i = 0; i < 40; i++) {
		vec3 d = (c - PAL[i]) * vec3(0.30, 0.59, 0.11) * 3.0;
		float dd = dot(d, d) + dot(c - PAL[i], c - PAL[i]) * 0.15;
		if (dd < bd) { bd = dd; best = PAL[i]; }
	}
	c = mix(c, best, palette_mix);
	if (outline > 0.0) {
		// Outline on the nearer side of an edge, one console pixel wide.
		vec2 stp = block * px;
		float d0 = linear_depth(uv, INV_PROJECTION_MATRIX);
		vec3 n0 = normal_at(uv);
		float edge = 0.0;
		vec2 offs[4] = vec2[](vec2(stp.x, 0.0), vec2(-stp.x, 0.0), vec2(0.0, stp.y), vec2(0.0, -stp.y));
		for (int i = 0; i < 4; i++) {
			float dn = linear_depth(uv + offs[i], INV_PROJECTION_MATRIX);
			if ((dn - d0) / d0 > outline_depth) edge = 1.0;
			if (1.0 - dot(n0, normal_at(uv + offs[i])) > outline_normal && abs(dn - d0) / d0 < 0.5) edge = 1.0;
		}
		edge *= outline * (1.0 - step(outline_far, d0));
		c = mix(c, vec3(0.0), edge);
	}
	ALBEDO = to_linear(c);
}
