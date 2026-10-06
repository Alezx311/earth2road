extends PanelContainer
## F9 playtest note: the frame as seen before the dialog, the camera and the point under the
## screen centre, plus a typed comment. Appended to logs/defects/<map>/defects.jsonl for
## tools/defects.py, which resolves lon/lat and the nearest SUMO edge/junction.

const Ui = preload("res://scripts/ui_theme.gd")

signal closed

var record: Dictionary
var image: Image
var input: LineEdit

func _ready() -> void:
	add_theme_stylebox_override("panel", Ui.style(Ui.BG, 16, Ui.ACCENT))
	set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	custom_minimum_size = Vector2(760, 0)
	position = Vector2((get_viewport_rect().size.x - 760) / 2, get_viewport_rect().size.y - 190)
	var box := VBoxContainer.new()
	add_child(box)
	var where: Dictionary = record.get("target", record.camera)
	box.add_child(Ui.label("Defect #%d at x=%.1f z=%.1f — Enter saves, Esc cancels" % [record.n, where.position[0], where.position[2]], 18, Ui.ACCENT))
	input = LineEdit.new()
	input.placeholder_text = "What is wrong here?"
	input.custom_minimum_size = Vector2(720, 44)
	input.text_submitted.connect(func(_t): save())
	box.add_child(input)
	input.grab_focus.call_deferred()

func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.physical_keycode == KEY_ESCAPE:
		get_viewport().set_input_as_handled()
		closed.emit()

func save() -> void:
	record.note = input.text.strip_edges()
	var dir: String = record.dir
	record.erase("dir")
	image.save_png(dir.path_join(record.screenshot))
	var path := dir.path_join("defects.jsonl")
	var f := FileAccess.open(path, FileAccess.READ_WRITE if FileAccess.file_exists(path) else FileAccess.WRITE)
	f.seek_end()
	f.store_line(JSON.stringify(record))
	f.close()
	print("DEFECT %s #%d %s" % [record.map, record.n, record.note])
	closed.emit()

static func vec(v: Vector3) -> Array:
	return [snappedf(v.x, 0.01), snappedf(v.y, 0.01), snappedf(v.z, 0.01)]

## Godot (x, y, z) -> SUMO network (x, y): the same transform as tools/traffic.py.
static func sumo_xy(v: Vector3, offset: Array) -> Array:
	return [snappedf(v.x + float(offset[0]), 0.01), snappedf(-v.z + float(offset[1]), 0.01)]

static func next_number(dir: String) -> int:
	var path := dir.path_join("defects.jsonl")
	if not FileAccess.file_exists(path): return 1
	return FileAccess.get_file_as_string(path).strip_edges().split("\n", false).size() + 1

## Builds the record from the live scene; `exclude` keeps the ray from hitting the player's car.
static func describe(viewport: Viewport, map_id: String, offset: Array, car: Node3D, exclude: Array[RID], mode: String) -> Dictionary:
	var dir := ProjectSettings.globalize_path("res://").path_join("../logs/defects").path_join(map_id).simplify_path()
	DirAccess.make_dir_recursive_absolute(dir)
	var n := next_number(dir)
	var cam := viewport.get_camera_3d()
	var forward := -cam.global_transform.basis.z
	var rec := {
		"n": n, "map": map_id, "time": Time.get_datetime_string_from_system(),
		"mode": mode, "dir": dir, "screenshot": "defect-%03d.png" % n,
		"camera": {"position": vec(cam.global_position), "sumo_xy": sumo_xy(cam.global_position, offset),
			"heading_deg": snappedf(fposmod(rad_to_deg(atan2(forward.x, -forward.z)), 360.0), 0.1),
			"pitch_deg": snappedf(rad_to_deg(asin(clampf(forward.y, -1, 1))), 0.1)},
	}
	if car:
		rec.car = {"position": vec(car.global_position), "sumo_xy": sumo_xy(car.global_position, offset)}
	var space := cam.get_world_3d().direct_space_state
	var query := PhysicsRayQueryParameters3D.create(cam.global_position, cam.global_position + forward * 3000.0)
	query.exclude = exclude
	var hit := space.intersect_ray(query)
	if not hit.is_empty():
		var p: Vector3 = hit.position
		rec.target = {"position": vec(p), "sumo_xy": sumo_xy(p, offset),
			"distance_m": snappedf(cam.global_position.distance_to(p), 0.1),
			"collider": str(hit.collider.name) if hit.collider else ""}
	return rec
