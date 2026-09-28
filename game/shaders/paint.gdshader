// Road paint: slightly worn retro-reflective white; wear is world-space noise.
shader_type spatial;
uniform sampler2D wear_noise : filter_linear_mipmap, repeat_enable;
uniform vec3 paint : source_color = vec3(0.92, 0.92, 0.88);
uniform vec3 asphalt : source_color = vec3(0.23, 0.23, 0.24);
varying vec3 wp;
void vertex() { wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }
void fragment() {
	float wear = texture(wear_noise, wp.xz * 0.35).r * 0.6 + texture(wear_noise, wp.xz * 0.05).r * 0.4;
	ALBEDO = mix(paint, asphalt, smoothstep(0.62, 0.9, wear) * 0.55);
	ROUGHNESS = 0.55;
}
