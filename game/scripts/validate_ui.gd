extends SceneTree
## Real scene regression and optional rendered screen matrix. No public map build.
var game: Node
var failures: Array[String] = []
var shots := false
var output := ""

func _initialize() -> void:
	shots = "--ui-shots" in OS.get_cmdline_user_args()
	call_deferred("run")

func check(condition: bool, message: String) -> void:
	if not condition:
		failures.append(message)
		printerr("UI FAIL: ", message)

func key(code: int) -> void:
	var event := InputEventKey.new()
	event.keycode = code
	event.physical_keycode = code
	event.pressed = true
	Input.parse_input_event(event)
	await process_frame
	event = event.duplicate()
	event.pressed = false
	Input.parse_input_event(event)
	await process_frame

func settle() -> void:
	for i in range(4): await process_frame

func snap(name: String) -> void:
	await settle()
	if shots:
		await RenderingServer.frame_post_draw
		var img := root.get_texture().get_image()
		var window := DisplayServer.window_get_size()
		if img.get_size() != window:
			img.resize(window.x, window.y, Image.INTERPOLATE_LANCZOS)
		img.save_png(output.path_join(name + ".png"))

func run() -> void:
	OS.set_environment("AKADEM_MAP_MENU", "")
	game = load("res://main.tscn").instantiate()
	root.add_child(game)
	current_scene = game
	game.offline = true
	var waited := 0.0
	while game.world.pending() > 0 and waited < 45.0:
		await create_timer(0.1).timeout
		waited += 0.1
	await create_timer(1.0).timeout
	for locale in ["en", "uk"]:
		TranslationServer.set_locale(locale)
		var size := DisplayServer.window_get_size()
		output = "res://../logs/qa-20260929/ui/%dx%d/%s" % [size.x, size.y, locale]
		DirAccess.make_dir_recursive_absolute(output)
		await snap("hud")
		game.toggle_traffic()
		game.panel.arm("roadworks")
		await snap("traffic")
		check(game.panel.body_scroll.scroll_vertical == 0, "traffic panel opens at the top")
		game.hud_view.buttons.pause.grab_focus()
		game.set_paused(true)
		await settle()
		check(not game.player.enabled and game.player.body.freeze, "pause freezes player")
		check(game.panel.armed == "", "modal disarms situation placement")
		var camera_before: bool = game.player.cockpit
		await key(KEY_C)
		check(game.player.cockpit == camera_before, "camera shortcut blocked by pause")
		var before: Vector3 = game.player.pos
		Input.action_press("Throttle")
		await create_timer(0.2).timeout
		Input.action_release("Throttle")
		check(game.player.pos.distance_to(before) < 0.01, "raw driving input blocked by pause")
		await snap("pause")
		game.set_help(true)
		await key(KEY_TAB)
		check(game.help_panel.is_ancestor_of(root.gui_get_focus_owner()), "help contains keyboard focus")
		await snap("help")
		await key(KEY_ESCAPE)
		check(game.help_panel == null and game.paused, "help returns to existing pause")
		game.set_paused(false)
		await settle()
		check(game.player.enabled, "closing pause restores driving without bridge")
		check(root.gui_get_focus_owner() == game.hud_view.buttons.pause, "closing pause restores focus")
		game.set_spectating(true)
		game.set_help(true)
		check(game.free_cam.input_blocked, "help blocks spectator polling")
		game.set_help(false)
		game.set_spectating(false)
		game.toggle_traffic()
		game.open_map_menu(game.hud, true)
		await settle()
		check(not game.player.enabled, "map menu blocks driving")
		check(game.map_menu.map_rows.any(func(row): return row.visible), "installed maps listed without a query")
		await snap("maps")
		game.map_menu.search.text = "__no_such_map__"
		game.map_menu.filter_maps("__no_such_map__")
		check(game.map_menu.list.get_node("Empty").visible, "empty search has visible recovery")
		await snap("maps-empty")
		game.map_menu.open_picker()
		await settle()
		var picker: Control = game.map_menu.picker
		check(picker.search.has_focus(), "picker focuses place search (focus: %s)" % root.gui_get_focus_owner())
		var side_scroll: ScrollContainer = picker.search.get_parent().get_parent().get_parent()
		check(side_scroll.scroll_vertical == 0, "picker opens at the top (%d)" % side_scroll.scroll_vertical)
		picker.name_edit.text = "QA preserved name"
		await snap("generator")
		# Complete-line JSONL consumption: a split write must not lose its event.
		picker.events_path = "user://ui-regression.jsonl"
		var file := FileAccess.open(picker.events_path, FileAccess.WRITE)
		file.store_string('{"event":"stage","phase":"build","progress":0.4}\n{"event":"stage"')
		file.close()
		picker.read_events()
		check(is_equal_approx(picker.progress.value, 0.4), "complete progress event consumed")
		check(picker.lines_seen == 1, "partial JSONL event deferred")
		file = FileAccess.open(picker.events_path, FileAccess.READ_WRITE)
		file.seek_end()
		file.store_string(',"phase":"export","progress":0.8}\n')
		file.close()
		picker.read_events()
		check(is_equal_approx(picker.progress.value, 0.8), "split progress event recovered")
		check(picker.status.text == tr("Preparing the map to drive…"), "build status is plain language")
		check("export" in picker.details.text, "raw stage kept in technical details")
		picker.progress.show()
		await snap("generator-progress")
		picker.had_error = true
		picker.fail(tr("Could not build the map. Check your connection and retry."))
		check(picker.name_edit.text == "QA preserved name", "retry preserves map name")
		check(not picker.generate_button.disabled, "retry available after error")
		picker.details.text = "HTTP 504 · overpass-api.de\n" + picker.events_path
		picker.details.show()
		await snap("generator-error")
		picker.coords.text = "invalid"
		picker.start_generation()
		check(picker.pid == -1, "invalid coordinates cannot start stale selection")
		await key(KEY_ESCAPE)
		check(game.map_menu.picker == null, "Escape returns from picker to maps")
		await key(KEY_ESCAPE)
		check(game.map_menu == null, "Escape closes map menu")
		await settle()
	DirAccess.remove_absolute("user://ui-regression.jsonl")
	print("UI_VALIDATION ", JSON.stringify({"passed": failures.is_empty(), "failures": failures}))
	quit(0 if failures.is_empty() else 1)
