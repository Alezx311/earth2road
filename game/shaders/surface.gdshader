// Tiled PBR surface for roads, pavements, ground and roofs. UV is world metres (x, z)
// for flat surfaces and (run, height) for walls; a large-scale noise breaks up tiling.
shader_type spatial;

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

void fragment() {
	vec2 uv = UV / tile_metres;
	float m = texture(macro_noise, UV / macro_metres).r;
	float m2 = texture(macro_noise, UV / (macro_metres * 0.23) + vec2(0.37, 0.71)).r;
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
