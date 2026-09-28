extends Control
## Map picker (M in game, or on launch without --map): every prepared map under
## res://data/<id>/index.json, plus "New map…" (location_picker.gd), which builds one around
## any point on Earth. Choosing a map reloads the scene; the traffic bridge switches its
## SUMO network when the game reconnects with ?map=<id>.

signal chosen(id: String)
signal closed

const LocationPicker = preload("res://scripts/location_picker.gd")
const I18n = preload("res://scripts/i18n.gd")
const NAME_RE := "\"name\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\""
const CARD := Rect2(390, 70, 500, 580)

var closable := true
var current := ""
var content: Control
var picker: Control

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
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	var shade := ColorRect.new()
	shade.color = Color(0.01, 0.02, 0.03, 0.72)
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(shade)
	build()

## The list is rebuilt on a language switch (its composed texts are not plain keys).
func build() -> void:
	if content:
		content.queue_free()
	content = Control.new()
	content.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	content.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(content)
	var maps := available()
	var card := ColorRect.new()
	card.color = Color(0.025, 0.05, 0.07, 0.96)
	card.position = CARD.position
	card.size = CARD.size
	content.add_child(card)
	var title := Label.new()
	title.text = "CHOOSE A MAP"
	title.position = CARD.position + Vector2(26, 20)
	title.add_theme_font_size_override("font_size", 20)
	content.add_child(title)
	var language := Button.new()
	language.text = "Language: English"
	language.focus_mode = Control.FOCUS_NONE
	language.position = CARD.position + Vector2(CARD.size.x - 176, 18)
	language.size = Vector2(150, 28)
	language.add_theme_font_size_override("font_size", 12)
	language.pressed.connect(func():
		I18n.toggle()
		build())
	content.add_child(language)
	var hint := Label.new()
	hint.text = tr("↑↓ + ENTER or click") + (tr("  ·  ESC — back") if closable else "")
	hint.position = CARD.position + Vector2(26, 50)
	hint.add_theme_font_size_override("font_size", 12)
	hint.add_theme_color_override("font_color", Color("859ca7"))
	content.add_child(hint)
	var create := Button.new()
	create.text = "+  New map from any place on Earth…"
	create.alignment = HORIZONTAL_ALIGNMENT_LEFT
	create.position = CARD.position + Vector2(20, 80)
	create.size = Vector2(460, 38)
	create.add_theme_font_size_override("font_size", 15)
	create.add_theme_color_override("font_color", Color("f1bc60"))
	create.pressed.connect(open_picker)
	content.add_child(create)
	# The list scrolls: generated maps accumulate.
	var scroll := ScrollContainer.new()
	scroll.position = CARD.position + Vector2(20, 130)
	scroll.size = Vector2(466, CARD.size.y - 150)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	content.add_child(scroll)
	var list := VBoxContainer.new()
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list.add_theme_constant_override("separation", 8)
	scroll.add_child(list)
	var first: Button = null
	for m in maps:
		var b := Button.new()
		# Map names are data (often Ukrainian); never run them through the translation.
		b.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
		b.text = m.name + (tr("   ·   current") if m.id == current else "")
		b.tooltip_text = m.id
		b.alignment = HORIZONTAL_ALIGNMENT_LEFT
		b.custom_minimum_size = Vector2(452, 36)
		b.add_theme_font_size_override("font_size", 15)
		b.pressed.connect(func(): chosen.emit(m.id))
		list.add_child(b)
		if first == null or m.id == current:
			first = b
	if first:
		first.grab_focus.call_deferred()
	else:
		create.grab_focus.call_deferred()

func open_picker() -> void:
	content.visible = false
	picker = LocationPicker.new()
	picker.generated.connect(func(id: String): chosen.emit(id))
	picker.back.connect(func():
		picker.queue_free()
		picker = null
		build())
	add_child(picker)

func _unhandled_key_input(event: InputEvent) -> void:
	if picker:
		return
	if closable and event is InputEventKey and event.pressed and not event.echo \
			and event.physical_keycode in [KEY_ESCAPE, KEY_M]:
		get_viewport().set_input_as_handled()
		closed.emit()
