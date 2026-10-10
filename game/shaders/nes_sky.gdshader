// 8-bit NES sky (texture style 3, main.gd apply_atmosphere): the flat Super Mario blue with
// blocky white clouds outlined in light blue, in a band above the horizon.
shader_type sky;

uniform vec3 sky_blue : source_color = vec3(0.361, 0.580, 0.988);   // NES $22 area, #5C94FC
uniform vec3 cloud : source_color = vec3(0.988, 0.988, 0.988);
uniform vec3 cloud_edge : source_color = vec3(0.235, 0.737, 0.988);

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

// Cloud blob mask on a coarse grid of "pixels" (about 0.9 degrees each).
float clouds(vec2 p) {
	vec2 g = floor(p / 9.0);
	float m = 0.0;
	for (int i = -1; i <= 1; i++) for (int j = -1; j <= 1; j++) {
		vec2 c = g + vec2(float(i), float(j));
		if (hash(c) < 0.55) continue;
		vec2 o = c * 9.0 + vec2(hash(c + 1.7), hash(c + 3.1)) * 4.0;
		vec2 r = vec2(3.0 + hash(c + 5.3) * 4.0, 1.5 + hash(c + 7.9) * 1.2);
		vec2 q = (p - o) / r;
		m = max(m, step(dot(q, q), 1.0));
		// a second, smaller puff on top
		vec2 q2 = (p - o - vec2(r.x * 0.3, r.y * 0.9)) / (r * 0.6);
		m = max(m, step(dot(q2, q2), 1.0));
	}
	return m;
}

void sky() {
	vec3 d = normalize(EYEDIR);
	vec3 c = sky_blue;
	float elev = degrees(asin(clamp(d.y, -1.0, 1.0)));
	if (elev > 3.0 && elev < 30.0) {
		vec2 p = floor(vec2(degrees(atan(d.x, d.z)), elev) / 0.9);
		float m = clouds(p);
		float e = max(max(clouds(p + vec2(1.0, 0.0)), clouds(p - vec2(1.0, 0.0))), max(clouds(p + vec2(0.0, 1.0)), clouds(p - vec2(0.0, 1.0))));
		c = m > 0.5 ? cloud : (e > 0.5 ? cloud_edge : c);
	}
	COLOR = c;
}
