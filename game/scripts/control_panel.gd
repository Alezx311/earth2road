extends PanelContainer
## Traffic control panel (T): road situations and traffic lights, applied live by the
## SUMO bridge (tools/situations.py).
##
## Pick a situation, then click a road. With nothing picked, a click asks the bridge what
## is there (street, lanes, speed limit, traffic light) and unlocks the signal buttons.
##
signal command(msg: Dictionary)
signal speed_selected(index: int)
signal density_selected(value: float)
signal closed
const Ui = preload("res://scripts/ui_theme.gd")
var density_slider: HSlider
var density_label: Label
var time_buttons: Array[Button] = []
var active_rows := {}

const TOOLS := [
	["accident", "Accident"],
	["stalled", "Stalled car"],
	["lane_closed", "Lane closed"],
	["roadworks", "Roadworks"],
	["jam", "Traffic jam"],
	["speed_limit", "Speed limit"],
]
const DURATIONS := [["30 s", 30], ["1 min", 60], ["5 min", 300], ["until cancelled", 0]]
const SPEEDS := [20, 30, 40, 50, 60]
const SIGNAL_ACTIONS := [
	["next", "Next phase"],
	["allred", "All red"],
	["amber", "Flashing amber"],
	["off", "Turn off"],
	["restore", "Restore"],
]

var armed := ""
var picked: Dictionary = {}
var tool_buttons: Dictionary = {}
var signal_buttons: Array[Button] = []
var hint: Label
var info: Label
var duration_menu: OptionButton
var speed_menu: OptionButton
var active_box: VBoxContainer
var active_count: Label
var body_scroll: ScrollContainer

func _init() -> void:
	visible = false

func _ready() -> void:
	theme = Ui.make()
	var layout := VBoxContainer.new()
	add_child(layout)
	var header := HBoxContainer.new()
	layout.add_child(header)
	header.add_child(Ui.label("Traffic control", 24))
	header.add_child(Ui.expand())
	header.add_child(Ui.button("×", func(): closed.emit()))
	var root := Ui.scroll_box(layout)
	body_scroll = root.get_parent().get_parent()
	root.add_child(Ui.label("TIME AND TRAFFIC", 18, Ui.ACCENT))
	var speeds := HBoxContainer.new()
	speeds.add_theme_constant_override("separation", 8)
	root.add_child(speeds)
	for i in range(6):
		var b := Ui.button("×%d" % [0, 1, 2, 4, 8, 16][i], func(): speed_selected.emit(i))
		b.toggle_mode = true
		b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		b.add_theme_font_size_override("font_size", 18)
		b.add_theme_stylebox_override("normal", Ui.style(Ui.SURFACE, 8, Ui.BORDER))
		speeds.add_child(b)
		time_buttons.append(b)
	root.add_child(Ui.label("Time speed applies in spectator mode", 16, Ui.MUTED, true))
	density_label = Ui.label("", 18, Ui.TEXT, true)
	root.add_child(density_label)
	density_slider = HSlider.new()
	density_slider.custom_minimum_size.y = 32
	density_slider.max_value = 100
	density_slider.step = 0.5
	density_slider.value_changed.connect(func(v): density_selected.emit(v))
	root.add_child(density_slider)
	root.add_child(Ui.label("Traffic demand is synthetic", 16, Ui.MUTED, true))
	root.add_child(HSeparator.new())
	root.add_child(head("SITUATION", 18, Ui.ACCENT))
	var grid := GridContainer.new()
	grid.columns = 2
	root.add_child(grid)
	for tool in TOOLS:
		var button := small_button(tool[1])
		button.toggle_mode = true
		button.pressed.connect(func(): arm(tool[0]))
		grid.add_child(button)
		tool_buttons[tool[0]] = button

	var rows := GridContainer.new()
	rows.columns = 2
	root.add_child(rows)
	rows.add_child(head("Duration", 11, Color("a0b4bd")))
	duration_menu = OptionButton.new()
	duration_menu.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for item in DURATIONS:
		duration_menu.add_item(item[0])
	duration_menu.select(1)
	rows.add_child(duration_menu)
	rows.add_child(head("Speed", 11, Color("a0b4bd")))
	speed_menu = OptionButton.new()
	speed_menu.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for value in SPEEDS:
		speed_menu.add_item("")
	speed_menu.select(0)
	translate_speeds()
	rows.add_child(speed_menu)

	hint = head("", 11, Color("f1bc60"))
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(hint)
	info = head("Click a road to see what is there", 11, Color("a0b4bd"))
	info.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(info)

	root.add_child(head("TRAFFIC LIGHT", 11, Color("f1bc60")))
	var signals_grid := GridContainer.new()
	signals_grid.columns = 2
	root.add_child(signals_grid)
	for action in SIGNAL_ACTIONS:
		var button := small_button(action[1])
		button.disabled = true
		button.pressed.connect(func(): signal_action(action[0]))
		signals_grid.add_child(button)
		signal_buttons.append(button)
	root.add_child(head("Phases are netconvert defaults, not observed timings", 9, Color("859ca7")))

	active_count = head(tr("ACTIVE SITUATIONS · %d") % 0, 11, Color("f1bc60"))
	root.add_child(active_count)
	# Fixed height: the panel must not grow into the speedometer as situations pile up.
	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(0, 120)
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	root.add_child(scroll)
	active_box = VBoxContainer.new()
	active_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	active_box.add_theme_constant_override("separation", 2)
	scroll.add_child(active_box)
	var clear := small_button("Cancel all")
	clear.pressed.connect(func(): command.emit({"type": "incident", "action": "clear"}))
	root.add_child(clear)

func _notification(what: int) -> void:
	if what == NOTIFICATION_TRANSLATION_CHANGED and speed_menu:
		translate_speeds()

## OptionButton items are formatted once, so they are refreshed when the language changes.
func translate_speeds() -> void:
	speed_menu.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	for i in SPEEDS.size():
		speed_menu.set_item_text(i, tr("%d km/h") % SPEEDS[i])
	speed_menu.select(speed_menu.selected)

## Focuses the current time speed; follow_focus may scroll against an unsorted layout
## on the first frame, so the panel is then returned to its top.
func focus_first() -> void:
	time_buttons[1].grab_focus()
	await get_tree().process_frame
	body_scroll.scroll_vertical = 0

func head(text: String, size_px: int, colour: Color) -> Label:
	return Ui.label(text, maxi(16, size_px), colour, true)

func small_button(text: String) -> Button:
	var b := Button.new()
	b.text = text
	b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	b.custom_minimum_size.y = 48
	b.add_theme_font_size_override("font_size", 18)
	return b

## Arming a tool turns the next click on a road into that situation.
func arm(tool: String) -> void:
	armed = "" if armed == tool else tool
	for key in tool_buttons:
		tool_buttons[key].set_pressed_no_signal(key == armed)
	hint.text = "" if armed == "" else tr("Click a road · ESC — cancel")

func disarm() -> void:
	if armed != "":
		arm(armed)

func duration() -> float:
	return float(DURATIONS[duration_menu.selected][1])

func speed_kmh() -> float:
	return float(SPEEDS[speed_menu.selected])

## A click in the world: place the armed situation, or ask what is there.
func world_click(point: Vector3) -> void:
	if armed == "":
		command.emit({"type": "pick", "p": [point.x, point.y, point.z]})
		return
	var msg := {"type": "incident", "action": "add", "kind": armed,
		"p": [point.x, point.y, point.z], "duration": duration()}
	if armed in ["speed_limit", "roadworks"]:
		msg["value_kmh"] = speed_kmh()
	command.emit(msg)

func signal_action(action: String) -> void:
	if picked.get("tls") == null:
		return
	command.emit({"type": "tls", "action": action, "id": picked.tls})

func show_picked(reply: Dictionary) -> void:
	picked = reply
	var name: String = reply.get("name", "")
	info.text = tr("%s · %d lanes · %d km/h · %d m") % [
		name if name != "" else reply.get("edge", tr("road")),
		int(reply.get("lanes", 0)), int(reply.get("speed_kmh", 0)), int(reply.get("length", 0))]
	if reply.get("tls") != null:
		info.text += tr("\nJunction with a traffic light")
	for button in signal_buttons:
		button.disabled = reply.get("tls") == null

func show_error(text: String) -> void:
	info.text = text

## The bridge owns the list of live situations; the panel only mirrors it.
func show_active(items: Array) -> void:
	active_count.text = tr("ACTIVE SITUATIONS · %d") % items.size()
	var live := {}
	for item in items:
		var id: String = item.id
		live[id] = true
		if not active_rows.has(id):
			var row := HBoxContainer.new()
			var name := Ui.label("", 16, Ui.TEXT, true)
			row.add_child(name)
			var drop := Ui.button("×", func(): command.emit({"type": "incident", "action": "remove", "id": id}))
			drop.tooltip_text = "Cancel"
			row.add_child(drop)
			active_box.add_child(row)
			active_rows[id] = row
		var text: String = tr(item.get("label", item.get("kind", "")))
		if item.get("left") != null:
			text += tr(" · %d s") % int(item.left)
		if item.get("blocking", false):
			text += tr(" · road blocked")
		active_rows[id].get_child(0).text = text
	for id in active_rows.keys():
		if not live.has(id):
			active_rows[id].queue_free()
			active_rows.erase(id)

func show_speed(index: int) -> void:
	for i in time_buttons.size():
		time_buttons[i].set_pressed_no_signal(i == index)
