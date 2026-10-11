// Synthwave sky (texture style 2, main.gd apply_atmosphere): violet zenith, magenta band, an
// orange horizon glow, a striped sun low over the horizon and sparse stars.
shader_type sky;

uniform vec3 zenith : source_color = vec3(0.03, 0.0, 0.09);
uniform vec3 band : source_color = vec3(0.42, 0.04, 0.38);
uniform vec3 horizon : source_color = vec3(1.0, 0.36, 0.3);
uniform vec3 below : source_color = vec3(0.06, 0.01, 0.08);
uniform vec3 sun_top : source_color = vec3(1.0, 0.86, 0.25);
uniform vec3 sun_bottom : source_color = vec3(1.0, 0.1, 0.55);
uniform vec3 sun_dir = vec3(0.0, 0.12, -1.0);
uniform float sun_radius = 0.2;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

void sky() {
	vec3 d = normalize(EYEDIR);
	float y = d.y;
	vec3 c = mix(horizon, band, smoothstep(0.0, 0.16, y));
	c = mix(c, zenith, smoothstep(0.12, 0.55, y));
	c = y < 0.0 ? mix(horizon * 0.6, below, smoothstep(0.0, 0.08, -y)) : c;
	// Stars: one cell in a fine direction grid, faded towards the horizon glow.
	vec2 cell = floor(vec2(atan(d.x, d.z) * 180.0, y * 260.0));
	float star = step(0.9975, hash(cell)) * smoothstep(0.2, 0.5, y);
	c += vec3(0.9, 0.85, 1.0) * star * 1.5;
	// Sun: a disc whose lower half is cut by horizontal gaps growing towards the bottom.
	vec3 s = normalize(sun_dir);
	float r = acos(clamp(dot(d, s), -1.0, 1.0));
	float h = (y - s.y) / sun_radius;                         // -1 bottom .. 1 top of the disc
	float gap = h < 0.35 ? step(fract(h * 6.0), 0.08 + clamp(0.35 - h, 0.0, 1.35) * 0.32) : 0.0;
	float disc = (1.0 - smoothstep(sun_radius - 0.004, sun_radius, r)) * (1.0 - gap) * step(-0.02, y);
	vec3 sun = mix(sun_bottom, sun_top, clamp(h * 0.5 + 0.5, 0.0, 1.0)) * 2.4;
	c = mix(c, sun, disc);
	c += sun_bottom * 0.35 * exp(-r * 6.0) * step(0.0, y);
	COLOR = c;
}
