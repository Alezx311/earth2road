extends Control
## Presentation only: game state and commands remain in main.gd.
const Ui = preload("res://scripts/ui_theme.gd")
const MiniMap = preload("res://scripts/minimap.gd")
const TrafficPanel = preload("res://scripts/control_panel.gd")
signal action(name: String)
var status: Label
var speed_label: Label
var gear: Label
var detail: Label
var minimap: Control
var panel: PanelContainer
var buttons: Dictionary = {}

func _ready() -> void:
	theme = Ui.make()
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var margin := Ui.inset(self)
	margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var rows := VBoxContainer.new()
	rows.mouse_filter = Control.MOUSE_FILTER_IGNORE
	margin.add_child(rows)
	var top := HBoxContainer.new()
	rows.add_child(top)
	var brand := PanelContainer.new()
	brand.add_theme_stylebox_override("panel", Ui.style(Ui.BG, 16))
	brand.add_child(Ui.label("TERRA / DRIVE", 24, Ui.ACCENT))
	top.add_child(brand)
	top.add_child(Ui.expand())
	for item in [["maps", "Maps · M"], ["pause", "Pause · P"], ["camera", "Camera · C"],
			["spectator", "Spectator · F"], ["traffic", "Traffic · T"], ["help", "Help · F1"]]:
		var button := Ui.button(item[1], func(): action.emit(item[0]))
		button.tooltip_text = item[1]
		top.add_child(button)
		buttons[item[0]] = button
	var info_row := HBoxContainer.new()
	info_row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	rows.add_child(info_row)
	var status_card := PanelContainer.new()
	status_card.add_theme_stylebox_override("panel", Ui.style(Ui.BG, 16))
	status = Ui.label("LOADING", 18, Ui.ACCENT)
	status_card.add_child(status)
	info_row.add_child(status_card)
	info_row.add_child(Ui.expand())
	rows.add_child(Ui.expand())
	var lower := HBoxContainer.new()
	lower.mouse_filter = Control.MOUSE_FILTER_IGNORE
	rows.add_child(lower)
	var left := VBoxContainer.new()
	left.custom_minimum_size.x = 320
	left.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lower.add_child(left)
	left.add_child(Ui.expand())
	var credits := Ui.label("© OpenStreetMap contributors · ODbL\nMapzen Terrain · F1", 16, Ui.TEXT)
	credits.add_theme_color_override("font_shadow_color", Color.BLACK)
	credits.add_theme_constant_override("shadow_offset_x", 1)
	credits.add_theme_constant_override("shadow_offset_y", 1)
	left.add_child(credits)
	var instrument := PanelContainer.new()
	instrument.custom_minimum_size.x = 352
	instrument.size_flags_vertical = Control.SIZE_SHRINK_END
	lower.add_child(instrument)
	var readout := VBoxContainer.new()
	readout.add_theme_constant_override("separation", 0)
	instrument.add_child(readout)
	var speed_row := HBoxContainer.new()
	readout.add_child(speed_row)
	speed_label = Ui.label("000", 72)
	speed_row.add_child(speed_label)
	var unit := Ui.label("km/h", 20, Ui.MUTED)
	unit.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	speed_row.add_child(unit)
	speed_row.add_child(Ui.expand())
	gear = Ui.label("N", 40, Ui.ACCENT)
	gear.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	speed_row.add_child(gear)
	detail = Ui.label("", 16, Ui.MUTED)
	readout.add_child(detail)
	var right := HBoxContainer.new()
	right.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lower.add_child(right)
	right.add_child(Ui.expand())
	var map_card := PanelContainer.new()
	map_card.add_theme_stylebox_override("panel", Ui.style(Ui.BG, 16, Ui.BORDER))
	right.add_child(map_card)
	var map_column := VBoxContainer.new()
	map_card.add_child(map_column)
	map_column.add_child(Ui.label("LOCAL ROADS   /   N ↑", 16, Ui.MUTED))
	minimap = MiniMap.new()
	minimap.custom_minimum_size = Vector2(272, 248)
	minimap.clip_contents = true
	minimap.mouse_filter = Control.MOUSE_FILTER_IGNORE
	map_column.add_child(minimap)
	panel = TrafficPanel.new()
	add_child(panel)
	panel.set_anchors_and_offsets_preset(Control.PRESET_LEFT_WIDE)
	panel.offset_left = 32
	panel.offset_top = 184
	panel.offset_right = 544
	panel.offset_bottom = -104
