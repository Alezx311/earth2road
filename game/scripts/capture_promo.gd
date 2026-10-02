extends SceneTree
## Capture the actual game/UI for the launch edit. No exports or settings writes.
const I18n = preload("res://scripts/i18n.gd")
const Menu = preload("res://scripts/map_menu.gd")
var output := ""
var pending: Array[int] = []

func _initialize() -> void:
	call_deferred("run")

func record(name: String, count: int) -> void:
	var folder := output.path_join(name)
	if DirAccess.dir_exists_absolute(folder):
		push_error("Capture directory already exists")
		quit(1)
		return
	DirAccess.make_dir_recursive_absolute(folder)
	for i in range(count):
		await process_frame
		await RenderingServer.frame_post_draw
		var img := root.get_texture().get_image()
		var file := folder.path_join("frame_%04d.jpg" % i)
		pending.append(WorkerThreadPool.add_task(func(): img.save_jpg(file, 0.94)))
		if pending.size() > 8:
			WorkerThreadPool.wait_for_task_completion(pending.pop_front())
	for task in pending:
		WorkerThreadPool.wait_for_task_completion(task)
	pending.clear()
	print("PROMO_CAPTURE ", name, " ", count)

func run() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--capture-output="):
			output = arg.trim_prefix("--capture-output=")
	if output == "":
		push_error("Pass --capture-output=<fresh absolute directory>")
		quit(1)
		return
	Engine.max_fps = 30
	I18n.setup()
	TranslationServer.set_locale("uk")
	print("USER_DIRECTORY ", OS.get_user_data_dir())
	var game: Node3D = load("res://main.tscn").instantiate()
	root.add_child(game)
	current_scene = game
	await create_timer(15).timeout
	game.player.enabled = true
	# GEVP squares the action strength; 0.8 -> 0.64 throttle, enough for the automatic to pull away.
	Input.action_press("Throttle", 0.8)
	await record("godot-drive", 240)
	Input.action_release("Throttle")
	game.queue_free()
	await process_frame
	var menu: Control = Menu.new()
	root.add_child(menu)
	await create_timer(1).timeout
	menu.open_picker()
	var picker: Control = menu.picker
	picker.coords.text = "50.4502431, 30.5240622"
	picker.apply_coords()
	picker.name_edit.text = "Київ — Майдан"
	picker.size_slider.value = 1.0
	picker.zoom = 14
	picker.view.queue_redraw()
	await create_timer(12).timeout
	await record("picker", 150)
	picker.back.emit()
	await process_frame
	menu.open_export("kyiv_maidan", "Київ — Майдан Незалежності")
	await create_timer(1).timeout
	menu.picker.destination.text = ProjectSettings.globalize_path("res://../out/beamng")
	# Show the mode the published ZIPs use (display only; the setting is not saved).
	menu.picker.mode_menu.select(0)
	menu.picker.update_mode_note()
	await record("export", 150)
	quit()
