extends SceneTree
## Menu/export regression. --runtime exports local tiny; --shots writes rendered UI.
const Menu = preload("res://scripts/map_menu.gd")
const I18n = preload("res://scripts/i18n.gd")
var failures: Array[String] = []
var menu: Control
var output := ""

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, message: String) -> void:
	if not ok:
		failures.append(message)
		printerr("BEAMNG UI FAIL: ", message)

func settle() -> void:
	for i in range(4): await process_frame

func snap(name: String) -> void:
	await settle()
	if "--shots" in OS.get_cmdline_user_args():
		await RenderingServer.frame_post_draw
		var img := root.get_texture().get_image()
		var size := DisplayServer.window_get_size()
		if img.get_size() != size: img.resize(size.x, size.y, Image.INTERPOLATE_LANCZOS)
		img.save_png(output.path_join(name + ".png"))

func escape() -> void:
	var event := InputEventKey.new()
	event.keycode = KEY_ESCAPE
	event.physical_keycode = KEY_ESCAPE
	event.pressed = true
	Input.parse_input_event(event)
	await settle()
	event = event.duplicate()
	event.pressed = false
	Input.parse_input_event(event)
	await settle()

func finish(exporter: Control) -> void:
	var deadline := Time.get_ticks_msec() + 60000
	while exporter.pid >= 0 and Time.get_ticks_msec() < deadline:
		await create_timer(0.1).timeout
	check(exporter.pid < 0, "export process exits within 60 seconds")
	if exporter.pid >= 0:
		exporter.stop_export()

func run() -> void:
	I18n.setup()
	var settings_exists := FileAccess.file_exists(I18n.SETTINGS)
	var settings_bytes := FileAccess.get_file_as_bytes(I18n.SETTINGS) if settings_exists else PackedByteArray()
	menu = Menu.new()
	root.add_child(menu)
	await settle()
	for locale in ["en", "uk"]:
		TranslationServer.set_locale(locale)
		output = "res://../logs/qa-beamng-ui/%dx%d/%s" % [root.size.x, root.size.y, locale]
		DirAccess.make_dir_recursive_absolute(output)
		menu.filter_maps("")
		await snap("maps")
		menu.filter_maps("__absent__")
		check(menu.map_rows.all(func(row): return not row.get_parent().visible), "search hides export buttons too")
		menu.filter_maps("")
		menu.open_export("tiny", "Tiny synthetic example")
		await settle()
		var exporter: Control = menu.picker
		check(exporter.map_id == "tiny", "selected map forwarded")
		check(exporter.start_button.has_focus(), "export starts with keyboard focus")
		check(exporter.mode_menu.item_count == exporter.MODES.size(), "all optimization modes listed")
		var notes := {}
		for i in exporter.MODES.size():
			exporter.mode_menu.select(i)
			exporter.mode_menu.item_selected.emit(i)
			check(exporter.optimization() == exporter.MODES[i][0], "mode %d maps to its value" % i)
			check(exporter.mode_note.text != "", "mode %d has a note" % i)
			notes[exporter.mode_note.text] = true
		check(notes.size() == exporter.MODES.size(), "every mode has its own note")
		if locale == "uk":
			check(exporter.mode_menu.get_item_text(0).begins_with("A+B+C: усі"), "mode names translated")
			check(exporter.mode_note.text.begins_with("Земля"), "mode note translated")
		exporter.mode_menu.select(0)
		exporter.mode_menu.item_selected.emit(0)
		exporter.set_busy(true)
		check(exporter.mode_menu.disabled, "mode locked while exporting")
		exporter.set_busy(false)
		check(not exporter.mode_menu.disabled, "mode unlocked after export")
		await snap("export")
		exporter.browse.pressed.emit()
		await settle()
		check(exporter.chooser.visible, "folder chooser opens")
		await snap("folder")
		exporter.chooser.dir_selected.emit(ProjectSettings.globalize_path("res://../out/beamng"))
		check(exporter.destination.text.ends_with("out/beamng"), "folder selection updates destination")
		exporter.chooser.hide()
		exporter.destination.text = "relative"
		exporter.start_export()
		check(exporter.pid < 0, "relative destination rejected")
		exporter.events_path = output + "/events.jsonl"
		var file := FileAccess.open(exporter.events_path, FileAccess.WRITE)
		file.store_string('{"event":"stage","stage":"geometry"}\n{"event":"res')
		file.close()
		exporter.read_events()
		check(exporter.lines_seen == 1 and exporter.terminal.is_empty(), "partial event deferred")
		exporter.set_busy(true)
		await snap("progress")
		file = FileAccess.open(exporter.events_path, FileAccess.READ_WRITE)
		file.seek_end()
		file.store_string('ult","zip":"example.zip"}\n')
		file.close()
		exporter.read_events()
		check(exporter.terminal.get("zip") == "example.zip", "split event recovered")
		exporter.set_busy(false)
		exporter.status.text = tr("Export failed. Check technical details and retry.")
		exporter.details.text = "Example error · export log"
		exporter.details.show()
		await snap("error")
		await escape()
		check(menu.picker == null and menu.content.visible, "Escape returns to map menu")
		check(menu.search.has_focus(), "focus returns to search")
	if "--runtime" in OS.get_cmdline_user_args():
		menu.open_export("tiny", "Tiny synthetic example")
		await settle()
		var exporter: Control = menu.picker
		exporter.destination.text = ProjectSettings.globalize_path("res://../logs/qa-beamng-ui/Експорт карт")
		exporter.mode_menu.select(0)
		exporter.mode_menu.item_selected.emit(0)
		exporter.start_export()
		check(exporter.pid > 0, "real exporter starts")
		var first_pid: int = exporter.pid
		exporter.start_export()
		check(exporter.pid == first_pid, "duplicate start blocked")
		await finish(exporter)
		check(exporter.terminal.get("event") == "result", "real tiny export completes")
		check(exporter.terminal.get("optimization") == "compact", "selected optimization used by the exporter")
		var saved := ConfigFile.new()
		saved.load("user://settings.cfg")
		check(saved.get_value("beamng", "optimization", "") == "compact", "optimization remembered")
		check(FileAccess.file_exists(exporter.zip_path), "ZIP published")
		print("BEAMNG_GUI_ZIP: ", exporter.zip_path)
		await snap("success")
		exporter.map_id = "__missing_map__"
		exporter.start_export()
		await finish(exporter)
		check(exporter.terminal.get("event") == "error" and not exporter.start_button.disabled, "error enables retry")
		check(exporter.destination.text.ends_with("Експорт карт"), "retry keeps destination")
		exporter.map_id = "tiny"
		exporter.start_export()
		exporter.cancelling = true
		exporter.stop_export()
		await finish(exporter)
		check(exporter.terminal.get("code") == "cancelled", "real export cancellation")
		await escape()
		menu.open_export("tiny", "Tiny synthetic example")
		await settle()
		exporter = menu.picker
		exporter.destination.text = ProjectSettings.globalize_path("res://../logs/qa-beamng-ui/Експорт карт")
		exporter.start_export()
		var owned_pid: int = exporter.pid
		menu.remove_child(exporter)
		exporter.queue_free()
		menu.picker = null
		var deadline := Time.get_ticks_msec() + 25000
		while OS.is_process_running(owned_pid) and Time.get_ticks_msec() < deadline:
			await create_timer(0.1).timeout
		check(not OS.is_process_running(owned_pid), "removing UI stops its export process")
	# QA must not replace the person's saved export folder.
	if settings_exists:
		var settings := FileAccess.open(I18n.SETTINGS, FileAccess.WRITE)
		settings.store_buffer(settings_bytes)
		settings.close()
	else:
		DirAccess.remove_absolute(I18n.SETTINGS)
	menu.queue_free()
	await settle()
	print("BEAMNG UI: ", "PASS" if failures.is_empty() else str(failures))
	quit(0 if failures.is_empty() else 1)
