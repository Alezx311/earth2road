// Road paint: slightly worn retro-reflective white; wear is world-space noise.
shader_type spatial;
global uniform int facade_style;   // 2 = synthwave: glowing marks, 3 = NES: flat white
uniform sampler2D wear_noise : filter_linear_mipmap, repeat_enable;
uniform vec3 paint : source_color = vec3(0.92, 0.92, 0.88);
uniform vec3 asphalt : source_color = vec3(0.23, 0.23, 0.24);
varying vec3 wp;
void vertex() { wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }
void fragment() {
	float wear = texture(wear_noise, wp.xz * 0.35).r * 0.6 + texture(wear_noise, wp.xz * 0.05).r * 0.4;
	ALBEDO = mix(paint, asphalt, smoothstep(0.62, 0.9, wear) * 0.55);
	ROUGHNESS = 0.55;
	if (facade_style == 2) {
		ALBEDO = vec3(.05, .02, .06);
		EMISSION = vec3(1.0, .45, .95) * (1.6 - smoothstep(0.62, 0.9, wear) * 0.6);
	}
	if (facade_style == 3) {
		ALBEDO = vec3(.988);
		ROUGHNESS = 1.0;
	}
}
