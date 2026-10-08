extends Control
## A single owned export process; terminal events are displayed after the process exits.
signal back
const Ui = preload("res://scripts/ui_theme.gd")
const Modal = preload("res://scripts/ui_modal.gd")
const Picker = preload("res://scripts/location_picker.gd")
const Estimates = preload("res://scripts/estimates.gd")
const Mods = preload("res://scripts/beamng_mods.gd")
const Styles = preload("res://scripts/styles.gd")
const I18n = preload("res://scripts/i18n.gd")
const SETTINGS := "user://settings.cfg"
const STAGES := {
	"prepare": "Checking map data…", "geometry": "Exporting roads and scenery…",
	"sidewalks": "Exporting sidewalks…", "buildings": "Exporting buildings…",
	"dressing": "Exporting vegetation and signs…",
	"validate": "Checking the level…", "package": "Creating ZIP…",
	"validate_zip": "Checking ZIP…"
}
## BeamNG optimization modes (tools/export_beamng_gui.py --optimization) with their notes.
## Measured on a 1 km² Kyiv map; see docs/HANDOFF.md (export_optimize).
const MODES := [
	["compact", "A+B+C: all optimizations (large maps)",
		"Smallest level and fastest first load: compact files, light kerbs and native terrain ground. Recommended for maps of several kilometres."],
	["balanced", "Original",
		"Reference export with full kerb detail and mesh ground. Largest files; large maps may not load."],
	["balanced+writer", "A: compact files",
		"Same geometry, 1 mm coordinates and smoothed shading: about 70% smaller model files."],
	["balanced+kerbs", "B: light kerbs",
		"Kerbs without the small bevel and with simpler outlines: about 88% fewer sidewalk triangles."],
	["balanced+terrain", "C: terrain ground",
		"Ground becomes a native BeamNG terrain under the roads instead of meshes; grass extends past the map edge."],
]
var map_id := ""
var map_title := ""
## Set by the map menu's "Add to BeamNG" when no export exists yet.
var install_requested := false
var tiles := 0
var install_box: CheckBox
var install_hint: Label
var install_button: Button
var pid := -1
var events_path := ""
var cancel_path := ""
var lines_seen := 0
var terminal: Dictionary = {}
var cancelling := false
var close_after := false
var started := 0
var poll_clock := 0.0
var zip_path := ""
var destination: LineEdit
var browse: Button
var mode_menu: OptionButton
var mode_note: Label
var style_menu: OptionButton
var style_ids: Array = []
var start_button: Button
var back_button: Button
var open_button: Button
var copy_button: Button
var status: Label
var elapsed: Label
var details: Label
var activity: ProgressBar
var modal: Control
var chooser: FileDialog

func _ready() -> void:
	theme = Ui.make()
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	modal = Modal.new()
	modal.title = "EXPORT TO BEAMNG"
	modal.bounds = Rect2(0.14, 0.08, 0.72, 0.84)
	add_child(modal)
	modal.closed.connect(request_close)
	Estimates.load_table(Picker.project_root())
	tiles = DirAccess.get_files_at("res://data/%s/tiles" % map_id).size()
	var body: VBoxContainer = modal.body
	var title := Ui.label(map_title + "  /  " + map_id, 22, Ui.TEXT, true)
	title.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	body.add_child(title)
	body.add_child(Ui.label("Save ZIP to", 20))
	var row := HBoxContainer.new()
	body.add_child(row)
	destination = LineEdit.new()
	destination.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var settings := ConfigFile.new()
	settings.load(SETTINGS)
	destination.text = str(settings.get_value("beamng", "destination", Picker.project_root() + "/out/beamng"))
	row.add_child(destination)
	browse = Ui.button("Browse…", choose_folder)
	row.add_child(browse)
	chooser = FileDialog.new()
	chooser.access = FileDialog.ACCESS_FILESYSTEM
	chooser.file_mode = FileDialog.FILE_MODE_OPEN_DIR
	chooser.title = tr("Save ZIP to")
	chooser.dir_selected.connect(func(path: String): destination.text = path)
	add_child(chooser)
	body.add_child(Ui.label("Each export gets a new folder. Previous ZIPs are kept.", 18, Ui.MUTED, true))
	body.add_child(Ui.label("Optimization", 20))
	mode_menu = OptionButton.new()
	mode_menu.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for mode in MODES:
		mode_menu.add_item("")
	var saved := str(settings.get_value("beamng", "optimization", "balanced"))
	mode_menu.select(maxi(0, MODES.map(func(m): return m[0]).find(saved)))
	mode_menu.item_selected.connect(func(_i): update_mode_note())
	body.add_child(mode_menu)
	mode_note = Ui.label("", 18, Ui.MUTED, true)
	mode_note.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	body.add_child(mode_note)
	translate_modes()
	# Facade textures baked into the level (akadem_maps/adapters/beamng/texture_styles.py);
	# defaults to the style shown in the game now (K).
	body.add_child(Ui.label("Textures", 20))
	style_menu = OptionButton.new()
	style_menu.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	style_menu.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	style_ids = Styles.available().map(func(s): return s.id)
	for id in style_ids:
		style_menu.add_item(Styles.label(id, I18n.current()))
	style_menu.select(maxi(0, style_ids.find(Styles.current())))
	body.add_child(style_menu)
	status = Ui.label("Ready to export", 20, Ui.MUTED, true)
	body.add_child(status)
	activity = ProgressBar.new()
	activity.indeterminate = true
	activity.show_percentage = false
	activity.hide()
	body.add_child(activity)
	elapsed = Ui.label("", 18, Ui.MUTED)
	body.add_child(elapsed)
	details = Ui.label("", 16, Ui.MUTED, true)
	details.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	details.hide()
	body.add_child(Ui.button("Technical details", func(): details.visible = not details.visible))
	body.add_child(details)
	install_box = CheckBox.new()
	install_box.text = "Install into the BeamNG mods folder"
	install_box.add_theme_font_size_override("font_size", 18)
	install_box.button_pressed = install_requested or bool(settings.get_value("beamng", "install", false))
	install_box.toggled.connect(func(_on): update_install_hint())
	body.add_child(install_box)
	install_hint = Ui.label("", 18, Ui.MUTED, true)
	install_hint.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	body.add_child(install_hint)
	update_install_hint()
	var results := HBoxContainer.new()
	body.add_child(results)
	open_button = Ui.button("Open folder", func(): OS.shell_open(zip_path.get_base_dir()))
	copy_button = Ui.button("Copy ZIP path", func(): DisplayServer.clipboard_set(zip_path))
	install_button = Ui.button("Install into BeamNG", install_zip)
	results.add_child(open_button)
	results.add_child(copy_button)
	results.add_child(install_button)
	open_button.hide()
	copy_button.hide()
	install_button.hide()
	back_button = Ui.button("Back", request_close)
	modal.footer.add_child(back_button)
	modal.footer.add_child(Ui.expand())
	start_button = Ui.button("Export ZIP", start_export, true)
	modal.footer.add_child(start_button)
	start_button.grab_focus.call_deferred()

func texture_style() -> String:
	return str(style_ids[style_menu.selected]) if style_menu.selected >= 0 and style_menu.selected < style_ids.size() else "procedural"

func optimization() -> String:
	return MODES[mode_menu.selected][0]

func update_mode_note() -> void:
	mode_note.text = tr(MODES[mode_menu.selected][2]) + "
" + tr("Export time: %s") % 		Estimates.text("export", optimization(), tiles)

func update_install_hint() -> void:
	var mods := Mods.mods_dir()
	if mods == "":
		install_box.button_pressed = false
		install_box.disabled = true
		install_hint.text = tr("BeamNG mods folder not found. Choose it in the map menu.")
	elif install_box.button_pressed:
		install_hint.text = tr("The ZIP goes to %s; restart BeamNG to see the map.") % mods
	else:
		install_hint.text = tr("Copy the ZIP into your BeamNG.drive user folder's mods folder to install it.")

## Copies the finished ZIP into BeamNG's mods folder; a running BeamNG may lock the old copy.
func install_zip() -> void:
	var err := Mods.install(map_id, zip_path)
	if err == OK:
		status.text = tr("Installed in BeamNG: %s") % Mods.installed(map_id)[0]
		install_button.hide()
	else:
		status.text = tr("ZIP ready: %s") % zip_path + "
" + Mods.error_text(err)
		install_button.text = "Retry install"
		install_button.show()

func _notification(what: int) -> void:
	if what == NOTIFICATION_TRANSLATION_CHANGED and mode_menu:
		translate_modes()

## OptionButton items are formatted once, so they are refreshed when the language changes.
func translate_modes() -> void:
	mode_menu.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	for i in MODES.size():
		mode_menu.set_item_text(i, tr(MODES[i][1]))
	mode_menu.select(mode_menu.selected)
	update_mode_note()

func choose_folder() -> void:
	chooser.current_dir = destination.text if DirAccess.dir_exists_absolute(destination.text) else Picker.project_root()
	chooser.popup_centered_ratio(0.8)

func set_busy(busy: bool) -> void:
	destination.editable = not busy
	browse.disabled = busy
	mode_menu.disabled = busy
	install_box.disabled = busy or Mods.mods_dir() == ""
	start_button.disabled = busy
	activity.visible = busy
	back_button.text = "Cancel" if busy else "Back"
	back_button.disabled = false

func start_export() -> void:
	if pid >= 0: return
	if destination.text.strip_edges() == "" or not destination.text.is_absolute_path():
		status.text = tr("Choose an absolute output folder path.")
		return
	var root := Picker.project_root()
	var python := root + ("/.venv/Scripts/python.exe" if OS.get_name() == "Windows" else "/.venv/bin/python")
	if not FileAccess.file_exists(python):
		status.text = tr("Python environment missing. Run Earth2Road setup and retry.")
		return
	if DirAccess.make_dir_recursive_absolute(root + "/logs") != OK:
		status.text = tr("Could not write export logs. Check folder permissions.")
		return
	var settings := ConfigFile.new()
	settings.load(SETTINGS)
	settings.set_value("beamng", "destination", destination.text)
	settings.set_value("beamng", "optimization", optimization())
	settings.set_value("beamng", "install", install_box.button_pressed)
	settings.save(SETTINGS)
	events_path = root + "/logs/beamng_%d_%d.jsonl" % [OS.get_process_id(), Time.get_ticks_usec()]
	cancel_path = events_path + ".cancel"
	lines_seen = 0
	terminal = {}
	cancelling = false
	close_after = false
	zip_path = ""
	open_button.hide()
	copy_button.hide()
	install_button.hide()
	details.text = events_path + ".log"
	pid = OS.create_process(python, PackedStringArray([root + "/tools/export_beamng_gui.py",
		"--map", map_id, "--destination", destination.text, "--events", events_path,
		"--log", events_path + ".log", "--parent-pid", str(OS.get_process_id()), "--cancel-file", cancel_path,
		"--optimization", optimization(), "--texture-style", texture_style()]), false)
	details.text += "\n" + tr("Optimization") + ": " + optimization() + "\n" + tr("Textures") + ": " + texture_style()
	if pid <= 0:
		pid = -1
		status.text = tr("Could not start the exporter. Check technical details.")
		return
	started = Time.get_ticks_msec()
	status.text = tr("Checking map data…")
	set_busy(true)

func stop_export() -> void:
	if OS.get_name() == "Windows":
		var request := FileAccess.open(cancel_path, FileAccess.WRITE)
		if request:
			request.store_string("cancel\n")
		else:
			OS.execute("taskkill", ["/PID", str(pid), "/T", "/F"])
	elif OS.execute("kill", ["-TERM", "-%d" % pid]) != 0:
		OS.kill(pid)

func request_close() -> void:
	if chooser.visible: return
	if pid < 0:
		back.emit()
		return
	close_after = true
	if cancelling: return
	cancelling = true
	status.text = tr("Cancelling…")
	back_button.disabled = true
	stop_export()

func read_events() -> void:
	if not FileAccess.file_exists(events_path): return
	var text := FileAccess.get_file_as_string(events_path)
	var lines := text.substr(0, text.rfind("\n") + 1).split("\n", false)
	for i in range(lines_seen, lines.size()):
		var record = JSON.parse_string(lines[i])
		if not record is Dictionary: continue
		match str(record.get("event", "")):
			"stage":
				if not cancelling:
					status.text = tr(STAGES.get(str(record.get("stage", "")), "Working…"))
			"result", "error":
				terminal = record
	lines_seen = lines.size()

func _process(delta: float) -> void:
	if pid < 0: return
	elapsed.text = tr("Elapsed: %d s") % ((Time.get_ticks_msec() - started) / 1000) + "  ·  " + 		tr("expected %s") % Estimates.span(Estimates.minutes("export", optimization(), tiles))
	poll_clock += delta
	if poll_clock < 0.25: return
	poll_clock = 0.0
	read_events()
	if OS.is_process_running(pid): return
	read_events()
	pid = -1
	set_busy(false)
	if terminal.get("event", "") == "result":
		zip_path = str(terminal.get("zip", ""))
		if not FileAccess.file_exists(zip_path):
			status.text = tr("Export failed. Check technical details and retry.")
			return
		status.text = tr("ZIP ready: %s") % zip_path
		open_button.show()
		copy_button.show()
		if install_box.button_pressed:
			install_zip()
		elif Mods.mods_dir() != "":
			install_button.text = "Install into BeamNG"
			install_button.show()
		start_button.text = "Export again"
		# A completed export wins a late cancellation; keep its location visible.
	elif terminal.get("code", "") == "cancelled" or (cancelling and terminal.is_empty()):
		status.text = tr("Export cancelled")
		if close_after: back.emit()
	else:
		var code := str(terminal.get("code", ""))
		var message := str(terminal.get("message", ""))
		status.text = tr("Export failed. Check technical details and retry.")
		if code == "FileNotFoundError":
			status.text = tr("Map data is missing. Generate the map again before exporting.")
		elif "hash differs" in message:
			status.text = tr("Map files do not match. Generate the map again before exporting.")
		elif code in ["PermissionError", "NotADirectoryError", "FileExistsError"]:
			status.text = tr("Cannot write to this folder. Choose another folder and retry.")
		details.text += "\n" + str(terminal.get("message", "Exporter exited without a result"))
		details.show()
		start_button.text = "Retry"

func _exit_tree() -> void:
	if pid >= 0: stop_export()
