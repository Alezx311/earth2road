shader_type spatial;
// Distant traffic (one MultiMesh per model, buffer built by tools/traffic.py).
// Instance transform = pose in the previous bridge frame, INSTANCE_CUSTOM = (dx, dy, dz, dyaw)
// to the current pose (world space). `alpha` runs 0 -> 1 between frames, so cars move
// smoothly without a per-car loop on the CPU. Instance COLOR.r = brake lamps.
render_mode cull_back;

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap;
uniform float alpha = 0.0;
uniform float rear_z = 2.2;

varying float brake;

void vertex() {
	float t = INSTANCE_CUSTOM.w * alpha;
	float c = cos(t);
	float s = sin(t);
	mat3 turn = mat3(vec3(c, 0.0, -s), vec3(0.0, 1.0, 0.0), vec3(s, 0.0, c));
	// Rear face, lamp height: glow when braking.
	brake = (VERTEX.z > rear_z * 0.9 && VERTEX.y > 0.45 && VERTEX.y < 1.3) ? COLOR.r : 0.0;
	// World offset into local space (the instance basis is a pure rotation).
	VERTEX = turn * VERTEX + transpose(mat3(MODEL_MATRIX)) * (INSTANCE_CUSTOM.xyz * alpha);
	NORMAL = turn * NORMAL;
}

void fragment() {
	vec3 base = texture(albedo_tex, UV).rgb;
	ALBEDO = mix(base, vec3(0.8, 0.05, 0.03), brake);
	EMISSION = vec3(2.5, 0.12, 0.05) * brake;
	ROUGHNESS = 0.45;
	METALLIC = 0.1;
}
