extends Control
## Map picker (M in game, or on launch without --map): every prepared map under
## res://data/<id>/index.json, plus "New map…" (location_picker.gd), which builds one around
## any point on Earth. Choosing a map reloads the scene; the traffic bridge switches its
## SUMO network when the game reconnects with ?map=<id>.
##
## Each row also manages the map's BeamNG ZIP in the BeamNG mods folder (beamng_mods.gd)
## and can delete the map for good (tools/maps.py delete).

signal chosen(id: String)
signal closed

const LocationPicker = preload("res://scripts/location_picker.gd")
const BeamngExport = preload("res://scripts/beamng_export.gd")
const I18n = preload("res://scripts/i18n.gd")
const NAME_RE := "\"name\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\""
const Ui = preload("res://scripts/ui_theme.gd")
const Modal = preload("res://scripts/ui_modal.gd")
const Mods = preload("res://scripts/beamng_mods.gd")
const SETTINGS := "user://settings.cfg"

var closable := true
var current := ""
var content: Control
var picker: Control
var search: LineEdit
var list: VBoxContainer
var map_rows: Array[Button] = []
var query := ""
var notice: Label
var folder_dialog: FileDialog
var confirm: ConfirmationDialog

## Top-level "name" in the key-sorted, indented index.json that earth2road export writes.
const SORTED_NAME := "\n  \"name\": \""
const SCAN_CHUNK := 1 << 20

static var names_cache: Dictionary = {}     # path -> [modified time, name]

## [{id, name}] sorted by name. index.json can be tens of megabytes, so it is never parsed.
static func available() -> Array:
	var out := []
	for dir in DirAccess.get_directories_at("res://data/"):
		var path := "res://data/%s/index.json" % dir
		if not FileAccess.file_exists(path):
			continue
		var name := map_name(path)
		out.append({"id": dir, "name": name if name != "" else dir})
	out.sort_custom(func(a, b): return a.name < b.name)
	return out

static func map_name(path: String) -> String:
	var modified := FileAccess.get_modified_time(path)
	if names_cache.has(path) and names_cache[path][0] == modified:
		return names_cache[path][1]
	var file := FileAccess.open(path, FileAccess.READ)
	# Older maps: compact JSON with "name" right after the network hash.
	var head := file.get_buffer(mini(2048, file.get_length()))
	var end := head.size()
	while end > 0 and head[end - 1] >= 0x80:    # never split a multibyte character
		end -= 1
	var found := RegEx.create_from_string(NAME_RE).search(head.slice(0, end).get_string_from_utf8())
	var name := found.get_string(1) if found else ""
	# Exported maps: sorted keys, so "name" follows the (large) lane list. Scan the bytes;
	# the ASCII view keeps byte offsets, the name itself is decoded as UTF-8.
	var at := 0
	while name == "" and at < file.get_length():
		file.seek(at)
		var chunk := file.get_buffer(SCAN_CHUNK)
		var hit := chunk.get_string_from_ascii().find(SORTED_NAME)
		if hit >= 0:
			var start := hit + SORTED_NAME.length()
			var stop := start
			while stop < chunk.size() and chunk[stop] != 0x22 and stop - start < 400:
				stop += 1
			name = chunk.slice(start, stop).get_string_from_utf8()
			break
		at += SCAN_CHUNK - 64       # overlap: the key may straddle two chunks
	names_cache[path] = [modified, name]
	return name

func _ready() -> void:
	theme = Ui.make()
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	build()

func build() -> void:
	if content:
		remove_child(content)
		content.queue_free()
	content = Modal.new()
	content.title = "CHOOSE A MAP"
	content.bounds = Rect2(0.12, 0.08, 0.76, 0.84)
	content.closed.connect(func():
		if closable and not dialog_open(): closed.emit())
	add_child(content)
	content.close_button.visible = closable
	var body: VBoxContainer = content.body
	body.add_child(Ui.label("Choose your next drive", 20, Ui.MUTED))
	var create := Ui.button("+  New map from any place on Earth…", open_picker, true)
	body.add_child(create)
	search = LineEdit.new()
	search.placeholder_text = "Search installed maps…"
	search.text = query
	search.text_changed.connect(filter_maps)
	search.text_submitted.connect(func(_value):
		for row in map_rows:
			if row.visible:
				row.pressed.emit()
				break)
	body.add_child(search)
	var mods := Mods.mods_dir()
	var mods_row := HBoxContainer.new()
	body.add_child(mods_row)
	var mods_label := Ui.label(tr("BeamNG mods: %s") % mods if mods != "" else tr("BeamNG mods folder not found"),
		18, Ui.MUTED if mods != "" else Ui.WARNING)
	mods_label.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	mods_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	mods_label.clip_text = true
	mods_label.tooltip_text = mods
	mods_row.add_child(mods_label)
	mods_row.add_child(Ui.button("Change…", choose_mods_dir))
	var open_mods := Ui.button("Open folder", func(): OS.shell_open(mods))
	open_mods.disabled = mods == ""
	mods_row.add_child(open_mods)
	notice = Ui.label("", 18, Ui.WARNING, true)
	notice.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	notice.visible = false
	body.add_child(notice)
	list = VBoxContainer.new()
	body.add_child(list)
	map_rows.clear()
	for m in available():
		var row := HBoxContainer.new()
		list.add_child(row)
		var in_beamng := not Mods.installed(m.id, mods).is_empty()
		var b := Ui.button(m.name + (tr("   ·   current") if m.id == current else "")
			+ (tr("   ·   in BeamNG") if in_beamng else ""), func(): chosen.emit(m.id))
		b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		b.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
		b.alignment = HORIZONTAL_ALIGNMENT_LEFT
		b.clip_text = true
		b.tooltip_text = m.name + "  /  " + m.id
		b.set_meta("search", (m.name + " " + m.id).to_lower())
		if m.id == current:
			b.add_theme_color_override("font_color", Ui.ACCENT)
		row.add_child(b)
		row.add_child(Ui.button("Export to BeamNG…", func(): open_export(m.id, m.name)))
		if in_beamng:
			row.add_child(Ui.button("Remove from BeamNG", func(): ask(
				tr("Remove “%s” from BeamNG? The ZIP is deleted from the mods folder; the map stays in this game.") % m.name,
				func(): remove_from_beamng(m.id), "Remove")))
		else:
			var add_button := Ui.button("Add to BeamNG", func(): add_to_beamng(m.id, m.name))
			add_button.disabled = mods == ""
			row.add_child(add_button)
		var delete_button := Ui.button("Delete…", func(): ask(
			tr("Delete “%s” (%s) for good? Removes the map from this game, its build files, its BeamNG exports and its ZIP in BeamNG mods. This cannot be undone.") % [m.name, m.id],
			func(): delete_map(m.id), "Delete"))
		delete_button.disabled = m.id == current
		delete_button.tooltip_text = tr("Switch to another map first") if m.id == current else ""
		row.add_child(delete_button)
		map_rows.append(b)
	var empty := Ui.label("No maps found. Try another search or create a map.", 20, Ui.MUTED, true)
	empty.name = "Empty"
	list.add_child(empty)
	filter_maps(query)
	content.footer.add_child(Ui.label("↑↓ + ENTER or click", 18, Ui.MUTED))
	content.footer.add_child(Ui.expand())
	content.footer.add_child(Ui.button("Language: English", func():
		I18n.toggle()
		build()))
	search.grab_focus.call_deferred()

func filter_maps(value: String) -> void:
	query = value
	var found := 0
	var needle := value.strip_edges().to_lower()
	for row in map_rows:
		# Godot's `"" in text` is false, so an empty query must match explicitly.
		row.visible = needle == "" or needle in str(row.get_meta("search"))
		row.get_parent().visible = row.visible
		if row.visible: found += 1
	list.get_node("Empty").visible = found == 0

func open_picker() -> void:
	content.visible = false
	picker = LocationPicker.new()
	picker.generated.connect(func(id: String): chosen.emit(id))
	picker.back.connect(func():
		picker.queue_free()
		picker = null
		content.show()
		search.grab_focus.call_deferred())
	add_child(picker)

func open_export(id: String, title: String, install := false) -> void:
	content.hide()
	picker = BeamngExport.new()
	picker.map_id = id
	picker.map_title = title
	picker.install_requested = install
	picker.back.connect(func():
		picker.queue_free()
		picker = null
		build())
	add_child(picker)

func dialog_open() -> bool:
	return (confirm != null and confirm.visible) or (folder_dialog != null and folder_dialog.visible)

func show_notice(text: String) -> void:
	notice.text = text
	notice.visible = text != ""

## Confirmation before anything is removed.
func ask(question: String, action: Callable, ok_text: String) -> void:
	if confirm:
		confirm.queue_free()
	confirm = ConfirmationDialog.new()
	confirm.theme = Ui.make()
	confirm.title = tr("Confirm")
	confirm.dialog_text = question
	confirm.dialog_autowrap = true
	confirm.ok_button_text = tr(ok_text)
	confirm.confirmed.connect(action)
	add_child(confirm)
	confirm.popup_centered(Vector2i(720, 260))

func choose_mods_dir() -> void:
	if folder_dialog == null:
		folder_dialog = FileDialog.new()
		folder_dialog.access = FileDialog.ACCESS_FILESYSTEM
		folder_dialog.file_mode = FileDialog.FILE_MODE_OPEN_DIR
		folder_dialog.title = tr("BeamNG mods folder")
		folder_dialog.dir_selected.connect(func(path: String):
			Mods.set_mods_dir(path)
			build())
		add_child(folder_dialog)
	var mods := Mods.mods_dir()
	folder_dialog.current_dir = mods if mods != "" else OS.get_environment("LOCALAPPDATA")
	folder_dialog.popup_centered_ratio(0.8)

static func exports_dir() -> String:
	var settings := ConfigFile.new()
	settings.load(SETTINGS)
	return str(settings.get_value("beamng", "destination", LocationPicker.project_root() + "/out/beamng"))

## The newest export goes straight in; without one, the export dialog opens set to install.
func add_to_beamng(id: String, title: String) -> void:
	var zip := Mods.latest_export(id, exports_dir())
	if zip == "":
		open_export(id, title, true)
		return
	var err := Mods.install(id, zip)
	build()
	show_notice(tr("Added to BeamNG from %s. Restart BeamNG to see the map.") % zip if err == OK else Mods.error_text(err))

func remove_from_beamng(id: String) -> void:
	var err := Mods.remove(id)
	build()
	show_notice(tr("Removed from BeamNG.") if err == OK else Mods.error_text(err))

func delete_map(id: String) -> void:
	var root := LocationPicker.project_root()
	var python := root + ("/.venv/Scripts/python.exe" if OS.get_name() == "Windows" else "/.venv/bin/python")
	if not FileAccess.file_exists(python):
		show_notice(tr("Python environment missing. Run Earth2Road setup and retry."))
		return
	var args := [root + "/tools/maps.py", "delete", "--id", id, "--current", current, "--exports-dir", exports_dir()]
	if Mods.mods_dir() != "":
		args.append_array(["--mods-dir", Mods.mods_dir()])
	var output := []
	var code := OS.execute(python, args, output)
	var result = JSON.parse_string(str(output[0]).strip_edges().get_slice("
", 0)) if not output.is_empty() else null
	names_cache.clear()
	build()
	if code == 0:
		show_notice(tr("Deleted %s.") % id)
	elif result is Dictionary and result.has("failed"):
		show_notice(tr("Deleted %s, except files still in use (close BeamNG and retry): %s") % [id,
			", ".join(PackedStringArray(result["failed"].map(func(f): return str(f["path"]))))])
	else:
		show_notice(tr("Could not delete %s: %s") % [id, str(result.get("error", output)) if result is Dictionary else str(output)])

func _input(event: InputEvent) -> void:
	if picker or dialog_open(): return
	if event is InputEventKey and event.pressed and not event.echo:
		if closable and event.physical_keycode == KEY_M and not get_viewport().gui_get_focus_owner() is LineEdit:
			get_viewport().set_input_as_handled()
			closed.emit()
		elif event.physical_keycode == KEY_DOWN and search.has_focus():
			for row in map_rows:
				if row.visible:
					row.grab_focus()
					get_viewport().set_input_as_handled()
					break
