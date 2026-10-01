extends Control
## A single owned export process; terminal events are displayed after the process exits.
signal back
const Ui = preload("res://scripts/ui_theme.gd")
const Modal = preload("res://scripts/ui_modal.gd")
const Picker = preload("res://scripts/location_picker.gd")
const SETTINGS := "user://settings.cfg"
const STAGES := {
	"prepare": "Checking map data…", "geometry": "Exporting roads and scenery…",
	"sidewalks": "Exporting sidewalks…", "buildings": "Exporting buildings…",
	"dressing": "Exporting vegetation and signs…",
	"validate": "Checking the level…", "package": "Creating ZIP…",
	"validate_zip": "Checking ZIP…"
}
var map_id := ""
var map_title := ""
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
	body.add_child(Ui.label("Copy the ZIP into your BeamNG.drive user folder's mods folder to install it.", 18, Ui.MUTED, true))
	var results := HBoxContainer.new()
	body.add_child(results)
	open_button = Ui.button("Open folder", func(): OS.shell_open(zip_path.get_base_dir()))
	copy_button = Ui.button("Copy ZIP path", func(): DisplayServer.clipboard_set(zip_path))
	results.add_child(open_button)
	results.add_child(copy_button)
	open_button.hide()
	copy_button.hide()
	back_button = Ui.button("Back", request_close)
	modal.footer.add_child(back_button)
	modal.footer.add_child(Ui.expand())
	start_button = Ui.button("Export ZIP", start_export, true)
	modal.footer.add_child(start_button)
	start_button.grab_focus.call_deferred()

func choose_folder() -> void:
	chooser.current_dir = destination.text if DirAccess.dir_exists_absolute(destination.text) else Picker.project_root()
	chooser.popup_centered_ratio(0.8)

func set_busy(busy: bool) -> void:
	destination.editable = not busy
	browse.disabled = busy
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
		status.text = tr("Python environment missing. Run TerraDrive setup and retry.")
		return
	if DirAccess.make_dir_recursive_absolute(root + "/logs") != OK:
		status.text = tr("Could not write export logs. Check folder permissions.")
		return
	var settings := ConfigFile.new()
	settings.load(SETTINGS)
	settings.set_value("beamng", "destination", destination.text)
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
	details.text = events_path + ".log"
	pid = OS.create_process(python, PackedStringArray([root + "/tools/export_beamng_gui.py",
		"--map", map_id, "--destination", destination.text, "--events", events_path,
		"--log", events_path + ".log", "--parent-pid", str(OS.get_process_id()), "--cancel-file", cancel_path]), false)
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
	elapsed.text = tr("Elapsed: %d s") % ((Time.get_ticks_msec() - started) / 1000)
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
