extends Control
## Road minimap. Lanes are bucketed once into CELL-metre cells in world coordinates;
## each redraw only draws the cells around the player through a canvas transform, so
## the cost does not grow with the district size.

const SCALE := 0.15
const CELL := 500.0
var player: Node3D
var cells: Dictionary = {}

var lanes: Array = []:
	set(value):
		lanes = value
		cells.clear()
		# Per cell: one segment list for streets and one for yards -> one draw call each.
		for lane in value:
			if lane.internal or lane.points.size() < 2:
				continue
			var first: Array = lane.points[0]
			var key := Vector2i(floori(first[0] / CELL), floori(first[2] / CELL))
			if not cells.has(key):
				cells[key] = {"street": PackedVector2Array(), "yard": PackedVector2Array()}
			var bucket: PackedVector2Array = cells[key]["yard" if lane.get("service", false) else "street"]
			for i in range(lane.points.size() - 1):
				var a: Array = lane.points[i]
				var b: Array = lane.points[i + 1]
				bucket.append(Vector2(a[0], a[2]))
				bucket.append(Vector2(b[0], b[2]))
			cells[key]["yard" if lane.get("service", false) else "street"] = bucket

func _draw() -> void:
	var center := size * 0.5
	draw_style_box(panel(), Rect2(Vector2.ZERO, size))
	if player == null:
		return
	var here := Vector2(player.pos.x, player.pos.z)
	var home := Vector2i(floori(here.x / CELL), floori(here.y / CELL))
	draw_set_transform(center - here * SCALE, 0.0, Vector2(SCALE, SCALE))
	for dx in range(-2, 3):
		for dy in range(-2, 3):
			var cell: Dictionary = cells.get(home + Vector2i(dx, dy), {})
			if cell.is_empty():
				continue
			if not cell.yard.is_empty():
				draw_multiline(cell.yard, Color("3d4c54"), 1.2 / SCALE)
			if not cell.street.is_empty():
				draw_multiline(cell.street, Color("8a9ca4"), 2.2 / SCALE)
	draw_set_transform(Vector2.ZERO)
	var f := Vector2(sin(-player.yaw), -cos(player.yaw))
	var r := Vector2(-f.y, f.x)
	draw_colored_polygon(PackedVector2Array([center + f * 9, center - f * 6 + r * 5, center - f * 6 - r * 5]), Color("f1bb58"))
	draw_circle(center, 3, Color.WHITE)

func panel() -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = Color(0.035, 0.07, 0.09, 0.92)
	s.set_corner_radius_all(12)
	return s
