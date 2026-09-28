extends PanelContainer
## Traffic control panel (T): road situations and traffic lights, applied live by the
## SUMO bridge (tools/situations.py).
##
## Pick a situation, then click a road. With nothing picked, a click asks the bridge what
## is there (street, lanes, speed limit, traffic light) and unlocks the signal buttons.
##
## This is the one place in the HUD built from containers instead of absolute positions:
## it is a real form with two dozen controls, and a container keeps the rows aligned as
## the incident list grows. Everything else in main.gd stays hand-placed.
##
## Texts are English translation keys (scripts/i18n.gd): labels and buttons re-translate
## themselves when the language changes; composed texts go through tr().

signal command(msg: Dictionary)

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

func _init() -> void:
	visible = false
	position = Vector2(20, 88)
	custom_minimum_size = Vector2(300, 0)
	size = Vector2(300, 0)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.025, 0.05, 0.07, 0.92)
	style.content_margin_left = 14
	style.content_margin_right = 14
	style.content_margin_top = 12
	style.content_margin_bottom = 12
	add_theme_stylebox_override("panel", style)

func _ready() -> void:
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 4)
	add_child(root)
	root.add_child(head("TRAFFIC CONTROL · T", 15, Color.WHITE))

	root.add_child(head("SITUATION", 11, Color("f1bc60")))
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
	duration_menu.focus_mode = Control.FOCUS_NONE
	for item in DURATIONS:
		duration_menu.add_item(item[0])
	duration_menu.select(1)
	rows.add_child(duration_menu)
	rows.add_child(head("Speed", 11, Color("a0b4bd")))
	speed_menu = OptionButton.new()
	speed_menu.focus_mode = Control.FOCUS_NONE
	for value in SPEEDS:
		speed_menu.add_item(tr("%d km/h") % value)
	speed_menu.select(0)
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
	scroll.custom_minimum_size = Vector2(0, 72)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	root.add_child(scroll)
	active_box = VBoxContainer.new()
	active_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	active_box.add_theme_constant_override("separation", 2)
	scroll.add_child(active_box)
	var clear := small_button("Cancel all")
	clear.pressed.connect(func(): command.emit({"type": "incident", "action": "clear"}))
	root.add_child(clear)

func head(text: String, size_px: int, colour: Color) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", size_px)
	l.add_theme_color_override("font_color", colour)
	return l

func small_button(text: String) -> Button:
	var b := Button.new()
	b.text = text
	b.focus_mode = Control.FOCUS_NONE
	b.add_theme_font_size_override("font_size", 11)
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
	for child in active_box.get_children():
		child.queue_free()
	active_count.text = tr("ACTIVE SITUATIONS · %d") % items.size()
	for item in items:
		var row := HBoxContainer.new()
		var text: String = tr(item.get("label", item.get("kind", "")))
		if item.get("left") != null:
			text += tr(" · %d s") % int(item.left)
		if item.get("blocking", false):
			text += tr(" · road blocked")
		var name := head(text, 11, Color("e08a6a") if item.get("blocking", false) else Color("cfdae0"))
		name.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(name)
		var drop := small_button("✕")
		drop.pressed.connect(func(): command.emit({"type": "incident", "action": "remove", "id": item.id}))
		row.add_child(drop)
		active_box.add_child(row)
