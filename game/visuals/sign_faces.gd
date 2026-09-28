extends RefCounted
## Faces of the road signs, drawn procedurally once and shared by every tile.
##
## Built on the main thread (tile workers only read caches, same rule as visuals/assets.gd)
## and keyed by "kind:value", so the whole map needs about a dozen materials: one per sign
## kind plus one per speed limit that actually occurs.
##
## No font is loaded: digits are drawn as seven-segment bars. The stop plate is the bare
## red octagon without lettering — inventing typography would be a worse lie than leaving
## the shape to speak, and the shape is what a driver reads at speed.

const SIZE := 128
const RED := Color("c0392b")
const BLUE := Color("1f6f9f")
const YELLOW := Color("e8b71d")
const WHITE := Color("f2f0ea")
const DARK := Color("1c1f22")
const CLEAR := Color(0, 0, 0, 0)

# Seven-segment layout: top, top-left, top-right, middle, bottom-left, bottom-right, bottom
const DIGITS := {
	0: [1, 1, 1, 0, 1, 1, 1], 1: [0, 0, 1, 0, 0, 1, 0], 2: [1, 0, 1, 1, 1, 0, 1],
	3: [1, 0, 1, 1, 0, 1, 1], 4: [0, 1, 1, 1, 0, 1, 0], 5: [1, 1, 0, 1, 0, 1, 1],
	6: [1, 1, 0, 1, 1, 1, 1], 7: [1, 0, 1, 0, 0, 1, 0], 8: [1, 1, 1, 1, 1, 1, 1],
	9: [1, 1, 1, 1, 0, 1, 1],
}

## Limits that get their own plate. Anything else snaps to the nearest of these, so a
## tile worker never has to create a texture: faces are built once, on the main thread.
const SPEEDS := [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130]
const PLAIN := ["give_way", "stop", "priority_road", "oneway"]

static var faces: Dictionary = {}

static func init() -> void:
	if not faces.is_empty():
		return
	for kind in PLAIN:
		faces["%s:0" % kind] = make(kind, 0)
	for value in SPEEDS:
		faces["speed_limit:%d" % value] = make("speed_limit", value)
	faces["unknown:0"] = make("unknown", 0)

static func material(kind: String, value: int) -> StandardMaterial3D:
	if kind == "speed_limit":
		var nearest: int = SPEEDS[0]
		for candidate in SPEEDS:
			if absi(candidate - value) < absi(nearest - value):
				nearest = candidate
		return faces["speed_limit:%d" % nearest]
	return faces.get("%s:0" % kind, faces["unknown:0"])

static func make(kind: String, value: int) -> StandardMaterial3D:
	var image := Image.create(SIZE, SIZE, false, Image.FORMAT_RGBA8)
	image.fill(CLEAR)
	match kind:
		"speed_limit":
			disc(image, 62, WHITE)
			ring(image, 62, 50, RED)
			number(image, value)
		"give_way":
			triangle(image, WHITE)
			triangle_border(image, RED)
		"stop":
			octagon(image, RED)
			octagon_border(image, WHITE)
		"priority_road":
			diamond(image, WHITE, 62)
			diamond(image, YELLOW, 44)
		"oneway":
			plate(image, BLUE)
			arrow(image, WHITE)
		_:
			disc(image, 60, WHITE)
			ring(image, 60, 48, DARK)
	var texture := ImageTexture.create_from_image(image)
	var m := StandardMaterial3D.new()
	m.albedo_texture = texture
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
	m.alpha_scissor_threshold = 0.5
	m.roughness = 0.75
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	return m

static func centre() -> Vector2:
	return Vector2(SIZE * 0.5, SIZE * 0.5)

static func disc(image: Image, radius: float, colour: Color) -> void:
	for y in SIZE:
		for x in SIZE:
			if Vector2(x, y).distance_to(centre()) <= radius:
				image.set_pixel(x, y, colour)

static func ring(image: Image, outer: float, inner: float, colour: Color) -> void:
	for y in SIZE:
		for x in SIZE:
			var d := Vector2(x, y).distance_to(centre())
			if d <= outer and d >= inner:
				image.set_pixel(x, y, colour)

static func plate(image: Image, colour: Color) -> void:
	for y in range(14, SIZE - 14):
		for x in range(6, SIZE - 6):
			image.set_pixel(x, y, colour)

static func in_triangle(x: int, y: int, scale: float) -> bool:
	# Point-down triangle, like the Ukrainian give-way sign.
	var u := (float(x) - SIZE * 0.5) / (SIZE * 0.5)
	var v := (float(y) - 8.0) / (SIZE - 20.0)
	return v >= 0.0 and v <= scale and absf(u) <= scale * (1.0 - v / scale) * 0.98

static func triangle(image: Image, colour: Color) -> void:
	for y in SIZE:
		for x in SIZE:
			if in_triangle(x, y, 1.0):
				image.set_pixel(x, y, colour)

static func triangle_border(image: Image, colour: Color) -> void:
	for y in SIZE:
		for x in SIZE:
			if in_triangle(x, y, 1.0) and not in_triangle(x, y, 0.76):
				image.set_pixel(x, y, colour)

static func in_octagon(x: int, y: int, radius: float) -> bool:
	var d := Vector2(x, y) - centre()
	return absf(d.x) <= radius and absf(d.y) <= radius and absf(d.x) + absf(d.y) <= radius * 1.42

static func octagon(image: Image, colour: Color) -> void:
	for y in SIZE:
		for x in SIZE:
			if in_octagon(x, y, 60.0):
				image.set_pixel(x, y, colour)

static func octagon_border(image: Image, colour: Color) -> void:
	for y in SIZE:
		for x in SIZE:
			if in_octagon(x, y, 60.0) and not in_octagon(x, y, 52.0):
				image.set_pixel(x, y, colour)

static func diamond(image: Image, colour: Color, radius: float) -> void:
	for y in SIZE:
		for x in SIZE:
			var d := Vector2(x, y) - centre()
			if absf(d.x) + absf(d.y) <= radius:
				image.set_pixel(x, y, colour)

## Points the way the traffic goes: a driver entering a one-way street sees it upright.
static func arrow(image: Image, colour: Color) -> void:
	for y in range(58, 104):
		for x in range(58, 71):
			image.set_pixel(x, y, colour)
	for y in range(30, 60):
		for x in range(40, 89):
			if absf(float(x) - 64.0) <= (float(y) - 26.0) * 1.35:
				image.set_pixel(x, y, colour)

static func number(image: Image, value: int) -> void:
	var text := str(value)
	var width := 26
	var start := int(SIZE * 0.5 - text.length() * width * 0.5)
	for i in text.length():
		digit(image, text[i].to_int(), start + i * width, 40)

static func digit(image: Image, value: int, x: int, y: int) -> void:
	if not DIGITS.has(value):
		return
	var s: Array = DIGITS[value]
	var w := 18
	var h := 22
	var t := 5
	if s[0]: bar(image, x, y, w, t)
	if s[1]: bar(image, x, y, t, h)
	if s[2]: bar(image, x + w - t, y, t, h)
	if s[3]: bar(image, x, y + h - t / 2, w, t)
	if s[4]: bar(image, x, y + h, t, h)
	if s[5]: bar(image, x + w - t, y + h, t, h)
	if s[6]: bar(image, x, y + 2 * h - t, w, t)

static func bar(image: Image, x: int, y: int, w: int, h: int) -> void:
	for py in range(y, mini(y + h, SIZE)):
		for px in range(x, mini(x + w, SIZE)):
			if px >= 0 and py >= 0:
				image.set_pixel(px, py, DARK)
