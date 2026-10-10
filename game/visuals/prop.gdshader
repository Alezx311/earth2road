// Street furniture, balconies and playground kit (visuals/palette.gd): a plain colour, or for
// the synthwave texture style (global facade_style 2) a dark body with a neon rim.
shader_type spatial;
global uniform int facade_style;
uniform vec3 albedo : source_color = vec3(0.6);
uniform float roughness = 0.86;
uniform float metallic = 0.0;
uniform vec3 neon : source_color = vec3(0.1, 0.85, 1.0);

void fragment() {
	ALBEDO = albedo;
	ROUGHNESS = roughness;
	METALLIC = metallic;
	if (facade_style == 2) {
		float rim = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 3.0);
		ALBEDO = albedo * 0.12;
		EMISSION = neon * (rim * 1.6 + 0.08);
		ROUGHNESS = 0.35;
	}
	if (facade_style == 3) {
		// NES: the colour flattened, a black sprite outline at grazing angles.
		ALBEDO = floor(albedo * 4.0 + 0.5) / 4.0;
		if (dot(NORMAL, VIEW) < 0.25) ALBEDO = vec3(0.0);
		ROUGHNESS = 1.0;
		METALLIC = 0.0;
	}
}
