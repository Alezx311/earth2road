extends Control
## Full-screen input shield, contained focus and a scrollable modal body.
const Ui = preload("res://scripts/ui_theme.gd")
signal closed
var title := ""
var bounds := Rect2(0.24, 0.14, 0.52, 0.72)
## Short fixed content: height fits the content and the panel is centred vertically.
var compact := false
var body: VBoxContainer
var footer: HBoxContainer
var close_button: Button
var previous_focus: WeakRef

func _ready() -> void:
	theme = Ui.make()
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	var owner := get_viewport().gui_get_focus_owner()
	if owner:
		previous_focus = weakref(owner)
	var shade := ColorRect.new()
	shade.color = Color(0.025, 0.04, 0.05, 0.8)
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(shade)
	var panel := PanelContainer.new()
	add_child(panel)
	panel.set_anchor(SIDE_LEFT, bounds.position.x)
	panel.set_anchor(SIDE_TOP, 0.5 if compact else bounds.position.y)
	panel.set_anchor(SIDE_RIGHT, bounds.end.x)
	panel.set_anchor(SIDE_BOTTOM, 0.5 if compact else bounds.end.y)
	panel.grow_vertical = Control.GROW_DIRECTION_BOTH
	for side in [SIDE_LEFT, SIDE_TOP, SIDE_RIGHT, SIDE_BOTTOM]:
		panel.set_offset(side, 0)
	var layout := VBoxContainer.new()
	panel.add_child(layout)
	var header := HBoxContainer.new()
	layout.add_child(header)
	header.add_child(Ui.label(title, 32))
	header.add_child(Ui.expand())
	close_button = Ui.button("Close · Esc", func(): closed.emit())
	header.add_child(close_button)
	layout.add_child(HSeparator.new())
	if compact:
		body = VBoxContainer.new()
		layout.add_child(body)
	else:
		body = Ui.scroll_box(layout)
	footer = HBoxContainer.new()
	layout.add_child(footer)
	close_button.grab_focus.call_deferred()

func _input(event: InputEvent) -> void:
	if not is_visible_in_tree(): return
	Ui.trap_focus(self, event)
	if event is InputEventKey and event.pressed and not event.echo and event.physical_keycode == KEY_ESCAPE:
		get_viewport().set_input_as_handled()
		closed.emit()

func _exit_tree() -> void:
	if previous_focus and is_instance_valid(previous_focus.get_ref()):
		previous_focus.get_ref().grab_focus.call_deferred()
