// Tiled PBR surface for roads, pavements, ground and roofs. UV is world metres (x, z)
// for flat surfaces and (run, height) for walls; a large-scale noise breaks up tiling.
// Ground materials with photo layers (materials.gd photo_ground) switch to them when the
// texture style is a photo one (global facade_style, scripts/styles.gd): a base cover,
// patches of a second cover and worn spots, each sampled twice (straight and turned) so
// the 3-4 m photo repeat does not show.
shader_type spatial;

global uniform int facade_style;

uniform bool has_textures = false;
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D normal_tex : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D roughness_tex : hint_roughness_g, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D macro_noise : filter_linear_mipmap, repeat_enable;
uniform float tile_metres = 4.0;
uniform vec3 tint : source_color = vec3(1.0);
uniform vec3 flat_color : source_color = vec3(0.5);
uniform float brightness = 1.0;
uniform float macro_metres = 90.0;
uniform float macro_strength = 0.18;
uniform vec3 macro_tint : source_color = vec3(1.0);
uniform float roughness_bias = 0.0;
uniform float normal_strength = 1.0;

// facade_style 2 (synthwave), set per material in materials.gd: 0 bare ground (magenta grid),
// 1 road (glossy black), 2 pavement (faint slabs), 3 roof/other (dark), 4 water, 5 greens (teal grid).
uniform int synth_kind = 3;

uniform bool photo_ground = false;
uniform sampler2D base_albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D base_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D base_roughness : hint_roughness_g, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D patch_albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D patch_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D patch_roughness : hint_roughness_g, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D wear_albedo : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D wear_normal : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D wear_roughness : hint_roughness_g, filter_linear_mipmap_anisotropic, repeat_enable;
uniform vec3 layer_metres = vec3(3.0, 4.0, 3.0);     // photo repeat of base, patch, wear
uniform vec2 layer_cover = vec2(0.35, 0.15);         // share of the ground under patch, wear
uniform vec3 photo_tint : source_color = vec3(1.0);
uniform float photo_saturation = 0.8;                // photo greens read garish at a distance

// The second sample is turned 37 degrees and shifted, then mixed in by low-frequency noise.
const mat2 TURN = mat2(vec2(0.7986, 0.6018), vec2(-0.6018, 0.7986));
const vec2 SHIFT = vec2(0.31, 0.67);

vec4 photo(sampler2D t, vec2 uv, float k) {
	return mix(texture(t, uv), texture(t, TURN * uv + SHIFT), k);
}

vec3 photo_normal(sampler2D t, vec2 uv, float k) {
	vec3 a = texture(t, uv).rgb;
	vec3 b = texture(t, TURN * uv + SHIFT).rgb;
	b.xy = ((b.xy * 2.0 - 1.0) * TURN) * 0.5 + 0.5;   // turn the sampled slope back
	return mix(a, b, k);
}

// Pull a layer's average colour (its last mip) part way to the base cover's, so patches
// differ in texture more than in hue and the ground does not read as camouflage from above.
vec3 harmonise(sampler2D layer, sampler2D base, vec3 c, float amount) {
	vec3 own = textureLod(layer, vec2(0.5), 12.0).rgb;
	vec3 target = textureLod(base, vec2(0.5), 12.0).rgb;
	return c * mix(vec3(1.0), target / max(own, vec3(0.02)), amount);
}

// Antialiased lines every `step_m` metres, `width_m` wide, fading once a pixel spans
// a good part of the step (no moire towards the horizon).
float grid(vec2 uv, float step_m, float width_m) {
	vec2 fw = fwidth(uv) + 1e-4;
	vec2 d = abs(fract(uv / step_m + .5) - .5) * step_m;
	vec2 l = 1.0 - smoothstep(vec2(width_m) - fw, vec2(width_m) + fw, d);
	float fade = 1.0 - smoothstep(step_m * .06, step_m * .25, max(fw.x, fw.y));
	return max(l.x, l.y) * fade;
}

// Patch mask: noise above (1 - cover), the edge pushed by the layer's own brightness so
// grass blades and clods break the outline instead of a soft fade.
float cover_mask(float noise, float cover, float detail) {
	float edge = 1.0 - cover + (detail - 0.4) * 0.35;
	return cover <= 0.0 ? 0.0 : smoothstep(edge - 0.06, edge + 0.06, noise);
}

void fragment() {
	float m = texture(macro_noise, UV / macro_metres).r;
	float m2 = texture(macro_noise, UV / (macro_metres * 0.23) + vec2(0.37, 0.71)).r;
	if (facade_style == 3) {
		// 8-bit NES, same surface kinds as synthwave: half-metre pixels in palette colours.
		vec2 p = floor(UV / 0.5);
		float h = fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
		float big = texture(macro_noise, (p * 0.5) / 60.0).r;
		vec3 c;
		if (synth_kind == 5) {            // grass: two greens, light tufts, darker clumps
			c = big > .55 ? vec3(0., .345, 0.) : vec3(0., .659, 0.);
			if (h > .93) c = vec3(.345, .847, .329);
		} else if (synth_kind == 0) {     // fill ground, yards: light lawn with patches of SMB dirt
			c = vec3(.345, .847, .329);
			if (h > .9) c = vec3(0., .659, 0.);
			if (big > .7) c = h > .85 ? vec3(.314, .188, 0.) : vec3(.675, .486, 0.);
		} else if (synth_kind == 1) {     // road: dark grey with a few specks
			c = vec3(.29);
			if (h > .95) c = vec3(.486);
		} else if (synth_kind == 2) {     // pavement: light slabs, 1 px seams every 1.5 m
			vec2 s = mod(p, 3.0);
			c = (s.x < .5 || s.y < .5) ? vec3(.486) : vec3(.737);
		} else if (synth_kind == 4) {     // water: blue with moving white wave dashes
			c = vec3(0., .345, .973);
			vec2 w = vec2(floor(p.x / 3.0 + floor(TIME * 2.0) * (mod(p.y, 2.0) * 2.0 - 1.0)), p.y);
			if (fract(sin(dot(w, vec2(12.9, 78.2))) * 43758.5) > .9 && mod(p.y, 4.0) < .5) c = vec3(.235, .737, .988);
		} else {                          // roofs and the rest: flat grey, 1 px seams every 2 m
			vec2 r = mod(p, 4.0);
			c = (r.x < .5 || r.y < .5) ? vec3(.29) : vec3(.486);
		}
		ALBEDO = c;
		ROUGHNESS = 1.0;
		METALLIC = 0.0;
	} else if (facade_style == 2) {
		vec3 magenta = vec3(1.0, .12, .62), teal = vec3(.08, .9, 1.0), violet = vec3(.55, .2, 1.0);
		vec3 base = vec3(.022, .01, .045);
		vec3 glow = vec3(0.0);
		float rough = .45;
		if (synth_kind == 0) {
			glow = magenta * (grid(UV, 10.0, .07) * 2.6 + grid(UV, 2.5, .025) * .35);
		} else if (synth_kind == 5) {
			base = vec3(.01, .03, .045);
			glow = teal * (grid(UV, 10.0, .07) * 2.2 + grid(UV, 2.5, .025) * .3);
		} else if (synth_kind == 1) {
			base = vec3(.012, .01, .02) * (.8 + m * .4);
			rough = .16;
		} else if (synth_kind == 2) {
			base = vec3(.05, .035, .08);
			glow = violet * grid(UV, tile_metres, .03) * .5;
			rough = .3;
		} else if (synth_kind == 4) {
			base = vec3(.0, .015, .04);
			glow = teal * grid(UV, 20.0, .05) * .8;
			rough = .04;
		} else {
			base = vec3(.03, .025, .05);
			rough = .5;
		}
		ALBEDO = base;
		EMISSION = glow;
		ROUGHNESS = rough;
		METALLIC = synth_kind == 1 || synth_kind == 4 ? .4 : .1;
	} else if (photo_ground && facade_style == 1) {
		float k = smoothstep(0.4, 0.6, texture(macro_noise, UV / 9.0 + vec2(0.13, 0.57)).r);
		vec2 ua = UV / layer_metres.x;
		vec2 ub = UV / layer_metres.y + vec2(0.21, 0.43);
		vec2 uc = UV / layer_metres.z + vec2(0.62, 0.09);
		vec3 base = photo(base_albedo, ua, k).rgb;
		vec3 nrm = photo_normal(base_normal, ua, k);
		float rough = photo(base_roughness, ua, k).r;
		vec3 pa = harmonise(patch_albedo, base_albedo, photo(patch_albedo, ub, k).rgb, 0.6);
		// Patches tens of metres across with ragged 5-7 m lobes, worn spots smaller.
		float n2 = texture(macro_noise, UV / 47.0 + vec2(0.71, 0.19)).r * 0.75 + texture(macro_noise, UV / 6.7 + vec2(0.4, 0.2)).r * 0.25;
		float wp = cover_mask(n2, layer_cover.x, dot(pa, vec3(0.33)));
		base = mix(base, pa, wp);
		nrm = mix(nrm, photo_normal(patch_normal, ub, k), wp);
		rough = mix(rough, photo(patch_roughness, ub, k).r, wp);
		vec3 wa = harmonise(wear_albedo, base_albedo, photo(wear_albedo, uc, k).rgb, 0.3);
		float n3 = texture(macro_noise, UV / 19.0 + vec2(0.05, 0.83)).r * 0.7 + texture(macro_noise, UV / 3.1).r * 0.3;
		float ww = cover_mask(n3, layer_cover.y, dot(wa, vec3(0.33)));
		base = mix(base, wa, ww);
		nrm = mix(nrm, photo_normal(wear_normal, uc, k), ww);
		rough = mix(rough, photo(wear_roughness, uc, k).r, ww);
		base = mix(vec3(dot(base, vec3(0.3, 0.59, 0.11))), base, photo_saturation);
		base *= photo_tint * brightness;
		base *= mix(1.0 - macro_strength * 0.6, 1.0 + macro_strength * 0.6, m * 0.7 + m2 * 0.3);
		ALBEDO = base;
		NORMAL_MAP = nrm;
		NORMAL_MAP_DEPTH = normal_strength;
		ROUGHNESS = clamp(rough + roughness_bias * 0.5, 0.65, 1.0);   // turf never shows sky
	} else {
		vec2 uv = UV / tile_metres;
		vec3 base = has_textures ? texture(albedo_tex, uv).rgb : flat_color;
		base *= tint * brightness;
		base *= mix(1.0 - macro_strength, 1.0 + macro_strength, m * 0.7 + m2 * 0.3);
		base = mix(base, base * macro_tint, smoothstep(0.35, 0.75, m2));
		ALBEDO = base;
		if (has_textures) {
			NORMAL_MAP = texture(normal_tex, uv).rgb;
			NORMAL_MAP_DEPTH = normal_strength;
			ROUGHNESS = clamp(texture(roughness_tex, uv).r + roughness_bias, 0.02, 1.0);
		} else {
			ROUGHNESS = clamp(0.85 + roughness_bias, 0.02, 1.0);
		}
	}
}
