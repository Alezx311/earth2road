extends SceneTree
## Close-up contact sheet of every catalogue vehicle on a neutral stage, three views each,
## to catch see-through faces and inverted shading. Needs a window (not --headless).
##   godot --path game --script res://scripts/validate_vehicle_looks.gd -- [--out NAME] [--procedural]
const Vehicles = preload("res://scripts/vehicles.gd")
const CELL := Vector2i(480, 300)
const VIEWS := [Vector3(-1.0, 0.45, -1.1), Vector3(1.1, 0.5, 1.0), Vector3(-1.4, 0.18, 0.05)]

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var args := OS.get_cmdline_user_args()
	var out_name := args[args.find("--out") + 1] if "--out" in args else "vehicles"
	Vehicles.use_glb = not "--procedural" in args
	root.size = CELL
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color("9fb3bf")
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.55, 0.58, 0.62)
	root.add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-50), deg_to_rad(35), 0)
	sun.shadow_enabled = true
	root.add_child(sun)
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(40, 40)
	ground.mesh = plane
	var gm := StandardMaterial3D.new()
	gm.albedo_color = Color("5b6166")
	ground.material_override = gm
	root.add_child(ground)
	var cam := Camera3D.new()
	cam.fov = 40
	root.add_child(cam)
	cam.make_current()
	var models: Array = Vehicles.catalog().models.keys()
	var sheet := Image.create(CELL.x * VIEWS.size(), CELL.y * models.size(), false, Image.FORMAT_RGBA8)
	for row in models.size():
		var car := Vehicles.instantiate(models[row])
		root.add_child(car.root)
		var size: Vector3 = car.size
		var reach := size.length() * 1.25
		for col in VIEWS.size():
			var dir: Vector3 = VIEWS[col].normalized()
			cam.global_position = dir * reach + Vector3.UP * size.y * 0.4
			cam.look_at(Vector3(0, size.y * 0.45, 0), Vector3.UP)
			for k in 4:
				await process_frame
			await RenderingServer.frame_post_draw
			var img := root.get_texture().get_image()
			img.convert(Image.FORMAT_RGBA8)
			img.resize(CELL.x, CELL.y)
			sheet.blit_rect(img, Rect2i(Vector2i.ZERO, CELL), Vector2i(col * CELL.x, row * CELL.y))
		car.root.queue_free()
		await process_frame
	var path := ProjectSettings.globalize_path("res://../logs/qa-20260929/%s.png" % out_name)
	sheet.save_png(path)
	Vehicles.release_visual_templates()
	print("VEHICLE_SHEET ", path)
	quit()
