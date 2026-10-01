extends Control
## Map picker (M in game, or on launch without --map): every prepared map under
## res://data/<id>/index.json, plus "New map…" (location_picker.gd), which builds one around
## any point on Earth. Choosing a map reloads the scene; the traffic bridge switches its
## SUMO network when the game reconnects with ?map=<id>.

signal chosen(id: String)
signal closed

const LocationPicker = preload("res://scripts/location_picker.gd")
const BeamngExport = preload("res://scripts/beamng_export.gd")
const I18n = preload("res://scripts/i18n.gd")
const NAME_RE := "\"name\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\""
const Ui = preload("res://scripts/ui_theme.gd")
const Modal = preload("res://scripts/ui_modal.gd")

var closable := true
var current := ""
var content: Control
var picker: Control
var search: LineEdit
var list: VBoxContainer
var map_rows: Array[Button] = []
var query := ""

## Top-level "name" in the key-sorted, indented index.json that terra-drive export writes.
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
	content.bounds = Rect2(0.24, 0.08, 0.52, 0.84)
	content.closed.connect(func():
		if closable: closed.emit())
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
	list = VBoxContainer.new()
	body.add_child(list)
	map_rows.clear()
	for m in available():
		var row := HBoxContainer.new()
		list.add_child(row)
		var b := Ui.button(m.name + (tr("   ·   current") if m.id == current else ""), func(): chosen.emit(m.id))
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

func open_export(id: String, title: String) -> void:
	content.hide()
	picker = BeamngExport.new()
	picker.map_id = id
	picker.map_title = title
	picker.back.connect(func():
		picker.queue_free()
		picker = null
		content.show()
		search.grab_focus.call_deferred())
	add_child(picker)

func _input(event: InputEvent) -> void:
	if picker: return
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
