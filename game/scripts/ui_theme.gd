extends RefCounted
## Shared, inexpensive simulator UI. All dimensions use an eight-pixel rhythm.

const BG := Color("171e25")
const SURFACE := Color("222c35")
const BORDER := Color("3a4954")
const TEXT := Color("e8eff2")
const MUTED := Color("a0b2be")
const ACCENT := Color("67dacb")
const WARNING := Color("efbc70")
static var shared: Theme

static func style(color: Color, padding := 16, edge := Color.TRANSPARENT) -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.bg_color = color
	s.set_corner_radius_all(8)
	s.set_content_margin_all(padding)
	s.border_color = edge
	s.set_border_width_all(1 if edge.a > 0 else 0)
	return s

static func make() -> Theme:
	if shared:
		return shared
	shared = Theme.new()
	shared.default_font_size = 20
	shared.set_color("font_color", "Label", TEXT)
	shared.set_stylebox("panel", "PanelContainer", style(BG, 24, BORDER))
	for type in ["Button", "OptionButton"]:
		shared.set_stylebox("normal", type, style(SURFACE, 16, BORDER))
		shared.set_stylebox("hover", type, style(Color("2d3f48"), 16, ACCENT.darkened(0.3)))
		shared.set_stylebox("pressed", type, style(Color("234d4b"), 16, ACCENT))
		shared.set_stylebox("disabled", type, style(Color("1c242b"), 16))
		shared.set_stylebox("focus", type, focus_style())
		shared.set_color("font_color", type, TEXT)
		shared.set_color("font_hover_color", type, Color.WHITE)
		shared.set_color("font_pressed_color", type, ACCENT)
		shared.set_color("font_disabled_color", type, Color("6e7e87"))
	shared.set_stylebox("normal", "LineEdit", style(Color("11191f"), 16, BORDER))
	shared.set_stylebox("focus", "LineEdit", focus_style())
	shared.set_color("font_color", "LineEdit", TEXT)
	shared.set_color("font_placeholder_color", "LineEdit", MUTED)
	shared.set_color("caret_color", "LineEdit", ACCENT)
	shared.set_stylebox("background", "ProgressBar", style(SURFACE, 8))
	shared.set_stylebox("fill", "ProgressBar", style(ACCENT, 8))
	shared.set_color("font_color", "ProgressBar", TEXT)
	shared.set_stylebox("panel", "PopupMenu", style(BG, 16, BORDER))
	shared.set_stylebox("hover", "PopupMenu", style(SURFACE, 8))
	shared.set_stylebox("panel", "TooltipPanel", style(BG, 16, BORDER))
	shared.set_color("font_color", "TooltipLabel", TEXT)
	for type in ["HBoxContainer", "VBoxContainer", "GridContainer"]:
		shared.set_constant("separation", type, 16)
		shared.set_constant("h_separation", type, 16)
		shared.set_constant("v_separation", type, 8)
	return shared

static func focus_style() -> StyleBoxFlat:
	var s := style(Color.TRANSPARENT, 0, ACCENT)
	s.set_border_width_all(2)
	return s

static func label(text: String, size_px := 20, color := TEXT, wrap := false) -> Label:
	var l := Label.new()
	l.text = text
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	l.add_theme_font_size_override("font_size", size_px)
	l.add_theme_color_override("font_color", color)
	if wrap:
		l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		l.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return l

static func button(text: String, action: Callable, primary := false) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size.y = 48
	b.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	b.pressed.connect(action)
	if primary:
		b.add_theme_stylebox_override("normal", style(Color("27514e"), 16, ACCENT))
		b.add_theme_color_override("font_color", ACCENT)
	return b

static func expand() -> Control:
	var c := Control.new()
	c.mouse_filter = Control.MOUSE_FILTER_IGNORE
	c.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	c.size_flags_vertical = Control.SIZE_EXPAND_FILL
	return c

static func inset(parent: Control, amount := 32) -> MarginContainer:
	var m := MarginContainer.new()
	parent.add_child(m)
	m.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "top", "right", "bottom"]:
		m.add_theme_constant_override("margin_" + side, amount)
	return m

static func scroll_box(parent: Node) -> VBoxContainer:
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.follow_focus = true
	parent.add_child(scroll)
	# Right gutter keeps fields and buttons clear of the vertical scrollbar.
	var gutter := MarginContainer.new()
	gutter.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	gutter.add_theme_constant_override("margin_right", 16)
	scroll.add_child(gutter)
	var box := VBoxContainer.new()
	box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	gutter.add_child(box)
	return box

static func focusable(root: Node) -> Array[Control]:
	var controls: Array[Control] = []
	for child in root.get_children():
		if child is Control and child.is_visible_in_tree() and child.focus_mode == Control.FOCUS_ALL:
			if not child is BaseButton or not child.disabled:
				controls.append(child)
		controls.append_array(focusable(child))
	return controls

static func trap_focus(root: Control, event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_TAB:
		var controls := focusable(root)
		if not controls.is_empty():
			var at := controls.find(root.get_viewport().gui_get_focus_owner())
			controls[posmod(at + (-1 if event.shift_pressed else 1), controls.size())].grab_focus()
		root.get_viewport().set_input_as_handled()
