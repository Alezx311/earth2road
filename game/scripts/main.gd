extends Node3D

const WorldStream = preload("res://scripts/world_stream.gd")
const Player = preload("res://scripts/player.gd")
const TrafficView = preload("res://scripts/traffic_view.gd")
const Map = preload("res://scripts/minimap.gd")
const FreeCamera = preload("res://scripts/free_camera.gd")
const Hud = preload("res://scripts/hud.gd")
const Ui = preload("res://scripts/ui_theme.gd")
const Modal = preload("res://scripts/ui_modal.gd")
const IncidentView = preload("res://scripts/incident_view.gd")
const MapMenu = preload("res://scripts/map_menu.gd")
const I18n = preload("res://scripts/i18n.gd")
const DefectMarker = preload("res://scripts/defect_marker.gd")
const SPEEDS := [0, 1, 2, 4, 8, 16]
const MAX_DENSITY := 10000       # fallback; the bridge reports its own limit on connect
## Seconds between automatic reconnect attempts while the bridge is unreachable.
const RECONNECT_SECONDS := 2.0
var world: Node3D
var player: Node3D
var data: Dictionary
var socket := WebSocketPeer.new()
var traffic: Node3D
var status: Label
var speed_label: Label
var detail: Label
var minimap: Control
var frame_age := 0.0
var send_clock := 0.0
var map_clock := 0.0
var paused := false
var ready_bridge := false
var fps_samples: Array[float]=[]
var gpu_samples: Array[float]=[]
var cpu_samples: Array[float]=[]
var runtime := 0.0
var capture_done := false
var headless_limit := 0.0
var hud: CanvasLayer
var hud_view: Control
var pause_menu: Control
var offline := false
var free_cam: Camera3D
var spectating := false
var speed_index := 1
var density := 100
var max_density := MAX_DENSITY
var density_slider: HSlider
var density_label: Label
var help_panel: Control
var panel: PanelContainer
var incidents: Node3D
var short_clock := 0.0
var short_seconds := 0.0
var env: Environment
var sun: DirectionalLight3D
var last_header: Dictionary = {}
var start_args := {}
var capture_focus = null
var map_menu: Control
var defect_dialog: Control
## The traffic socket is opened from _process, never from _ready: Godot sends the WebSocket
## handshake only while polling, and building a large map (plus the first shader compile)
## can block the main thread for longer than the bridge used to wait for it.
var bridge_wanted := false
var reconnect_clock := 0.0
## Seconds without an open socket: after a few, the status says the bridge is not running
## instead of promising a connection.
var unreachable := 0.0
const UNREACHABLE_SECONDS := 6.0

func _ready() -> void:
	I18n.setup()
	var args := OS.get_cmdline_user_args()
	for arg in args:
		if arg.begins_with("--seconds="):
			headless_limit = float(arg.split("=")[1])
		elif arg == "--no-vsync":
			# Benchmarks: uncapped frames so metrics show real cost, not the refresh cadence.
			DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
			Engine.max_fps = 0
		elif arg == "--offline":
			offline = true
		elif arg == "--spectate":
			start_args.spectate = true
		elif arg == "--panel":
			start_args.panel = true
		elif arg.begins_with("--altitude="):
			start_args.altitude = float(arg.split("=")[1])
		elif arg.begins_with("--density="):
			density = maxi(0, int(arg.split("=")[1]))
		elif arg.begins_with("--speed="):
			speed_index = maxi(0, SPEEDS.find(int(arg.split("=")[1])))
	RenderingServer.viewport_set_measure_render_time(get_viewport().get_viewport_rid(), true)
	# start.ps1/start.sh without --map: pick the map first, the world is built after the reload.
	if OS.get_environment("AKADEM_MAP_MENU") == "1":
		OS.set_environment("AKADEM_MAP_MENU", "")
		add_child(make_environment())
		var layer := CanvasLayer.new()
		add_child(layer)
		open_map_menu(layer, false)
		return
	data = WorldStream.load_index()
	if not Array(args).any(func(arg): return arg.begins_with("--density=")):
		density = int(data.get("traffic_count", 100))
	if data.is_empty():
		push_error("Map '%s' not built: run .venv/bin/python tools/prepare.py" % WorldStream.map_id())
		get_tree().quit(1)
		return
	add_child(make_environment())
	sun = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-42, -35, 0)
	sun.light_color = Color("fff1dc")
	sun.light_energy = 1.25
	sun.shadow_enabled = true
	sun.shadow_bias = 0.03
	sun.shadow_normal_bias = 1.2
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	sun.directional_shadow_max_distance = 300
	sun.directional_shadow_split_1 = 0.06
	sun.directional_shadow_split_2 = 0.18
	sun.directional_shadow_split_3 = 0.45
	sun.directional_shadow_blend_splits = true
	add_child(sun)
	world = WorldStream.new()
	add_child(world)
	var sp: Array = data.spawn.position
	world.start(data, Vector3(sp[0], sp[1], sp[2]))
	traffic = TrafficView.new()
	add_child(traffic)
	player = Player.new()
	add_child(player)
	free_cam = FreeCamera.new()
	add_child(free_cam)
	incidents = IncidentView.new()
	add_child(incidents)
	reset_player()
	build_ui()
	if "--shots" in OS.get_cmdline_user_args():
		run_shots()
		return
	if "--timelapse" in OS.get_cmdline_user_args():
		var timelapse := preload("res://scripts/timelapse.gd").new()
		timelapse.main = self
		add_child(timelapse)
	# First attempt half a second into _process, i.e. after the first rendered frames.
	bridge_wanted = true
	reconnect_clock = RECONNECT_SECONDS - 0.5
	print("WORLD_READY map=%s lanes=%d tiles=%d" % [WorldStream.map_id(),data.lanes.size(),data.tiles.size()])

## Daylight look: physical-ish sky, SSAO for contact shadows, light aerial fog.
func make_environment() -> WorldEnvironment:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color("5f8fc4")
	sky_mat.sky_horizon_color = Color("c9d8e3")
	sky_mat.ground_horizon_color = Color("b9c3c6")
	sky_mat.ground_bottom_color = Color("6c7270")
	sky_mat.sun_angle_max = 20.0
	sky_mat.sky_curve = 0.12
	var sky := Sky.new()
	sky.sky_material = sky_mat
	var e := Environment.new()
	env = e
	e.background_mode = Environment.BG_SKY
	e.sky = sky
	e.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	e.ambient_light_energy = 0.9
	e.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	e.tonemap_mode = Environment.TONE_MAPPER_AGX
	e.tonemap_exposure = 1.05
	e.ssao_enabled = true
	e.ssao_radius = 1.6
	e.ssao_intensity = 1.6
	e.ssao_power = 1.4
	e.ssil_enabled = false
	e.fog_enabled = true
	e.fog_mode = Environment.FOG_MODE_DEPTH
	e.fog_light_color = Color("c3d2dc")
	e.fog_depth_begin = 250.0
	e.fog_depth_end = 2200.0
	e.fog_density = 0.35
	e.fog_aerial_perspective = 0.4
	e.glow_enabled = true
	e.glow_intensity = 0.35
	e.glow_bloom = 0.02
	e.adjustment_enabled = true
	e.adjustment_saturation = 1.05
	e.adjustment_contrast = 1.04
	var node := WorldEnvironment.new()
	node.environment = e
	return node

func connect_bridge() -> void:
	socket = WebSocketPeer.new()
	# Frames carry thousands of cars (~32 B each); the default 64 KiB buffer is too small.
	socket.inbound_buffer_size = 8 << 20
	var port := OS.get_environment("AKADEM_PORT")
	# ?map= makes the bridge switch its SUMO network when it runs another map.
	socket.connect_to_url("ws://127.0.0.1:%s/?map=%s" % [port if port != "" else "8765", WorldStream.map_id().uri_encode()])
	ready_bridge = false
	frame_age = 0

func reset_player() -> void:
	var p: Array = data.spawn.position
	player.spawn(Vector3(p[0],p[1],p[2]), float(data.spawn.angle))
	paused = false
	set_help(false)
	send({"type":"reset"})

func send(msg: Dictionary) -> void:
	if socket.get_ready_state()==WebSocketPeer.STATE_OPEN:
		socket.send_text(JSON.stringify(msg))

func _unhandled_key_input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo: return
	if modal_open(): return
	var code: int = event.physical_keycode
	if code==KEY_M:
		open_map_menu(hud, true)
	elif code==KEY_F:
		set_spectating(not spectating)
	elif code>=KEY_1 and code<=KEY_6:
		set_speed(code-KEY_1)
	elif code==KEY_BRACKETLEFT:
		set_speed(speed_index-1)
	elif code==KEY_BRACKETRIGHT:
		set_speed(speed_index+1)
	elif code in [KEY_EQUAL,KEY_KP_ADD]:
		set_density(density_step(1))
	elif code in [KEY_MINUS,KEY_KP_SUBTRACT]:
		set_density(density_step(-1))
	elif code==KEY_F1:
		set_help(help_panel == null)
	elif code==KEY_T:
		toggle_traffic()
	elif code in [KEY_ESCAPE,KEY_P]:
		if code==KEY_ESCAPE and panel.armed != "":
			panel.disarm()
		else:
			set_paused(not paused)
	elif code==KEY_F5:
		reconnect_clock = 0.0
		connect_bridge()
	elif code==KEY_L:
		# Labels re-translate themselves; formatted texts follow NOTIFICATION_TRANSLATION_CHANGED.
		I18n.toggle()
	elif code==KEY_F12:
		capture()
	elif code==KEY_F9:
		mark_defect()
	elif spectating:
		return
	elif code==KEY_C:
		player.set_camera(not player.cockpit)
	elif code==KEY_V:
		player.cycle_model()
	elif code==KEY_R:
		reset_player()

func open_map_menu(layer: CanvasLayer, closable: bool) -> void:
	if map_menu: return
	if pause_menu: pause_menu.hide()
	map_menu = MapMenu.new()
	map_menu.closable = closable
	map_menu.current = WorldStream.map_id() if closable else ""
	map_menu.chosen.connect(switch_map)
	map_menu.closed.connect(func():
		map_menu.queue_free()
		map_menu = null
		if pause_menu: pause_menu.show()
		sync_modal_state())
	layer.add_child(map_menu)
	sync_modal_state()

## The scene is rebuilt from scratch for the new map; AKADEM_MAP is read by WorldStream.
func switch_map(id: String) -> void:
	OS.set_environment("AKADEM_MAP", id)
	socket.close()
	get_tree().reload_current_scene()

func modal_open() -> bool:
	return map_menu != null or help_panel != null or paused or defect_dialog != null

## Called at the opening event, before the next physics tick. Raw Input polling
## must be gated as well as GUI events (a modal only consumes the latter).
func sync_modal_state() -> void:
	var blocked := modal_open()
	if player:
		player.enabled = not blocked and not spectating
		player.input_blocked = blocked
		if blocked: player.stop_looking()
	if free_cam:
		free_cam.input_blocked = blocked
		if blocked:
			free_cam.dragging = false
			free_cam.panning = false
	if blocked:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		if panel: panel.disarm()
	send({"type": "pause", "paused": blocked})

func set_paused(on: bool) -> void:
	paused = on
	if pause_menu:
		pause_menu.queue_free()
		pause_menu = null
	if on:
		pause_menu = Modal.new()
		pause_menu.title = "PAUSED"
		pause_menu.bounds = Rect2(0.33, 0.0, 0.34, 0.0)
		pause_menu.compact = true
		pause_menu.closed.connect(func(): set_paused(false))
		hud.add_child(pause_menu)
		var body: VBoxContainer = pause_menu.body
		body.add_child(Ui.label("Take your time. Your drive will wait.", 20, Ui.MUTED, true))
		var resume := Ui.button("Resume driving · P", func(): set_paused(false), true)
		body.add_child(resume)
		body.add_child(Ui.button("Maps · M", func(): open_map_menu(hud, true)))
		body.add_child(Ui.button("Help · F1", func(): set_help(true)))
		body.add_child(Ui.button("Language: English", func(): I18n.toggle()))
		resume.grab_focus.call_deferred()
	sync_modal_state()

func _input(event: InputEvent) -> void:
	if not event is InputEventKey or not event.pressed or event.echo: return
	if map_menu: return
	if help_panel and event.physical_keycode == KEY_F1:
		set_help(false)
		get_viewport().set_input_as_handled()
	elif paused and help_panel == null and event.physical_keycode == KEY_P:
		set_paused(false)
		get_viewport().set_input_as_handled()

func toggle_traffic() -> void:
	panel.visible = not panel.visible
	if not panel.visible: panel.disarm()
	else: panel.focus_first()

func ui_action(action: String) -> void:
	match action:
		"maps": open_map_menu(hud, true)
		"pause": set_paused(true)
		"help": set_help(true)
		"traffic": toggle_traffic()
		"spectator": set_spectating(not spectating)
		"camera":
			if not spectating: player.set_camera(not player.cockpit)

## Clicking the map: the ray hits a collider on a full tile, and beyond that (the
## spectator can be kilometres up) it falls back to the horizontal plane through the
## camera focus. The bridge knows the whole network and resolves the point to a lane.
func _unhandled_input(event: InputEvent) -> void:
	if modal_open() or panel == null or not panel.visible or not event is InputEventMouseButton: return
	if event.button_index != MOUSE_BUTTON_LEFT or not event.pressed: return
	var cam: Camera3D = free_cam if spectating else (player.inside if player.cockpit else player.chase)
	if cam == null: return
	var from := cam.project_ray_origin(event.position)
	var dir := cam.project_ray_normal(event.position)
	var space := get_world_3d().direct_space_state
	var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(from, from + dir * 6000.0, 1 | 2 | 4))
	if hit:
		panel.world_click(hit.position)
		return
	var plane := Plane(Vector3.UP, (free_cam.focus if spectating else player.pos).y)
	var point = plane.intersects_ray(from, dir)
	if point != null:
		panel.world_click(point)

func _process(delta: float) -> void:
	if player==null: return
	runtime+=delta
	frame_age+=delta
	send_clock+=delta
	socket.poll()
	if bridge_wanted and not offline and socket.get_ready_state()==WebSocketPeer.STATE_CLOSED:
		# Bridge not started yet, restarted, or the connection dropped: keep trying.
		reconnect_clock += delta
		if reconnect_clock >= RECONNECT_SECONDS:
			reconnect_clock = 0.0
			connect_bridge()
	var latest := PackedByteArray()
	while socket.get_available_packet_count()>0:
		var packet := socket.get_packet()
		if not socket.was_string_packet():
			latest = packet          # only the newest frame matters
			continue
		var msg = JSON.parse_string(packet.get_string_from_utf8())
		if msg is Dictionary and msg.get("type")=="picked":
			panel.show_picked(msg)
		elif msg is Dictionary and msg.get("type")=="error":
			panel.show_error(tr(msg.get("text","")))
		elif msg is Dictionary and msg.get("type")=="ready":
			if msg.get("map", WorldStream.map_id()) != WorldStream.map_id():
				# The bridge could not switch: its cars would drive on another network.
				socket.close()
				offline = true
				continue
			ready_bridge = true
			frame_age=0
			traffic.set_models(msg.get("models",[]))
			max_density = int(msg.get("max_density",MAX_DENSITY))
			set_density(density)
			send({"type":"spectate","on":spectating})
			send({"type":"speed","x":SPEEDS[speed_index]})
			sync_modal_state()
			if start_args.get("spectate",false) and not spectating:
				set_spectating(true)
	if not latest.is_empty():
		var n := latest.decode_u32(0)
		var header = JSON.parse_string(latest.slice(4,4+n).get_string_from_utf8())
		if header is Dictionary:
			frame_age=0
			last_header = header
			traffic.update(header, latest.slice(4+n).to_float32_array())
			world.update_signals(header.signals)
			if header.has("incidents"):
				incidents.update(header.incidents)
				panel.show_active(header.incidents)
	var connected := ready_bridge and socket.get_ready_state()==WebSocketPeer.STATE_OPEN and frame_age<2
	# Traffic is optional: the car drives whether or not the bridge is there. Once it
	# connects, SUMO places the ego car wherever the player is (moveToXY).
	player.enabled = not modal_open() and not spectating
	if socket.get_ready_state()==WebSocketPeer.STATE_OPEN:
		unreachable = 0.0
	else:
		unreachable += delta
	if send_clock>=0.05:
		send_clock=0
		var pos: Vector3 = player.pos
		if spectating:
			var cam := free_cam.global_position
			send({"type":"focus","p":[cam.x,cam.y,cam.z]})
		else:
			send({"type":"focus","p":[pos.x,pos.y,pos.z]})
			send({"type":"ego","position":[pos.x,pos.y,pos.z],"angle":fposmod(-rad_to_deg(player.yaw),360),"speed":absf(player.speed),"length":player.size.z})
	world.focus = capture_focus if capture_focus != null else (free_cam.focus if spectating else player.pos)
	if spectating:
		adapt_view()
	status.text = status_text(connected)
	speed_label.text = "%03d" % roundi(absf(player.speed)*3.6)
	hud_view.gear.text = gear_text() if not spectating else "—"
	detail.text = tr("%d cars · %d FPS · %s") % [traffic.count(), Engine.get_frames_per_second(), sim_clock()]
	hud_view.buttons.camera.disabled = spectating
	hud_view.buttons.spectator.set_pressed_no_signal(spectating)
	track_shortfall(delta)
	map_clock += delta
	if map_clock > 0.2:
		map_clock = 0
		minimap.queue_redraw()
	if runtime>5:
		fps_samples.append(delta*1000)
		var vp := get_viewport().get_viewport_rid()
		gpu_samples.append(RenderingServer.viewport_get_measured_render_time_gpu(vp))
		cpu_samples.append(RenderingServer.viewport_get_measured_render_time_cpu(vp)+RenderingServer.get_frame_setup_time_cpu())
	if "--capture" in OS.get_cmdline_user_args() and runtime>8 and not capture_done:
		capture_done=true
		capture()
	if headless_limit>0 and runtime>headless_limit:
		write_metrics()
		get_tree().quit()
	if player.pos.y < -100:
		reset_player()

func status_text(connected: bool) -> String:
	if paused:
		return tr("PAUSED · P — resume")
	if not connected:
		if offline:
			return tr("NO TRAFFIC")
		if socket.get_ready_state()==WebSocketPeer.STATE_OPEN and not ready_bridge:
			# Connected; the bridge is (re)building SUMO for this map.
			return tr("LOADING TRAFFIC FOR THIS MAP…")
		if unreachable > UNREACHABLE_SECONDS:
			return tr("NO TRAFFIC BRIDGE · run start.ps1 · F5")
		return tr("CONNECTING TO TRAFFIC · F5 — retry")
	if not spectating:
		return tr("FREE DRIVE")
	var x: int = SPEEDS[speed_index]
	if x == 0:
		return tr("SPECTATOR · TIME STOPPED")
	var actual := float(last_header.get("actual", x))
	if actual < x * 0.9:
		return tr("SPECTATOR · ×%d (actual ×%.1f)") % [x, actual]
	return tr("SPECTATOR · ×%d") % x

## Time of day in the simulation (demand follows it: morning and evening peaks).
func sim_clock() -> String:
	var t := int(float(last_header.get("clock", last_header.get("time", 0.0))))
	return "%02d:%02d:%02d" % [t / 3600, (t / 60) % 60, t % 60]

## F: spectator camera over the player; the car waits, SUMO drops the ego proxy.
func set_spectating(on: bool) -> void:
	if on == spectating:
		return
	spectating = on
	sync_modal_state()
	if on:
		free_cam.start(player.pos, player.yaw, float(start_args.get("altitude", 120.0)))
		start_args.erase("altitude")
		minimap.player = free_cam
	else:
		free_cam.stop()
		player.set_camera(player.cockpit)
		minimap.player = player
		restore_view()
	send({"type":"spectate","on":on})
	send({"type":"speed","x":SPEEDS[speed_index] if on else 1})

func set_speed(index: int) -> void:
	speed_index = clampi(index, 0, SPEEDS.size() - 1)
	if panel: panel.show_speed(speed_index)
	if spectating:
		send({"type":"speed","x":SPEEDS[speed_index]})

const DENSITY_STEPS := [0, 50, 100, 200, 500, 1000, 2000, 3000, 5000, 7500, 10000]
const HEAVY_DENSITY := 5000      # above this the SUMO step and the frame visibly cost more

func density_step(direction: int) -> int:
	var steps := DENSITY_STEPS.filter(func(v): return v <= max_density)
	var i := 0
	while i < steps.size() - 1 and steps[i] < density:
		i += 1
	if direction > 0 and steps[i] <= density:
		i += 1
	elif direction < 0:
		i -= 1
	return steps[clampi(i, 0, steps.size() - 1)]

## Density 0..max on a quadratic slider: fine steps at the low end. The ceiling comes from
## the bridge (MAX_DENSITY there); past HEAVY_DENSITY the label says what it costs.
func set_density(count: int, from_slider := false) -> void:
	density = clampi(count, 0, max_density)
	short_seconds = 0.0
	if not from_slider and density_slider:
		density_slider.set_value_no_signal(sqrt(float(density) / max_density) * 100.0)
	update_density_label()
	send({"type":"density","count":density})

func _notification(what: int) -> void:
	# Also reached from the Pause and Maps language buttons, not only the L key.
	if what == NOTIFICATION_TRANSLATION_CHANGED:
		update_density_label()

func update_density_label() -> void:
	if density_label == null:
		return
	var text := tr("TRAFFIC DENSITY · %d cars  (−/+)") % density
	var colour := Color("cfdae0")
	if density > HEAVY_DENSITY:
		text += tr("\n× frame rate and SUMO step will drop")
		colour = Color("f1bc60")
	if short_seconds > 30.0:
		text += tr("\n× the network cannot hold that many")
		colour = Color("e08a6a")
	density_label.text = text
	density_label.add_theme_color_override("font_color", colour)

## The network may simply not hold the requested number of cars; say so instead of
## letting the slider claim a density that never appears on the streets.
func track_shortfall(delta: float) -> void:
	var live := int(last_header.get("total", 0))
	if density >= 500 and live < density * 0.85:
		short_seconds += delta
	else:
		short_seconds = 0.0
	short_clock += delta
	if short_clock > 1.0:
		short_clock = 0.0
		update_density_label()

## High camera: longer shadows and fog pushed out so the whole district stays visible.
func adapt_view() -> void:
	var d: float = free_cam.distance
	sun.directional_shadow_max_distance = clampf(d * 2.5, 300.0, 3000.0)
	env.fog_depth_begin = maxf(250.0, d * 1.5)
	env.fog_depth_end = maxf(2200.0, d * 8.0)

func restore_view() -> void:
	sun.directional_shadow_max_distance = 300
	env.fog_depth_begin = 250.0
	env.fog_depth_end = 2200.0

func gear_text() -> String:
	var g: int = player.body.current_gear if player.body else 0
	return "R" if g == -1 else ("N" if g == 0 else "D%d" % g)

func build_ui() -> void:
	hud = CanvasLayer.new()
	add_child(hud)
	hud_view = Hud.new()
	hud.add_child(hud_view)
	hud_view.action.connect(ui_action)
	# Aim for F9: the defect point is whatever lies under the screen centre.
	var crosshair := Ui.label("+", 22, Color(1, 1, 1, 0.55))
	crosshair.set_anchors_and_offsets_preset(Control.PRESET_CENTER, Control.PRESET_MODE_MINSIZE)
	crosshair.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(crosshair)
	status = hud_view.status
	speed_label = hud_view.speed_label
	detail = hud_view.detail
	minimap = hud_view.minimap
	minimap.lanes = data.lanes
	minimap.player = player
	panel = hud_view.panel
	panel.command.connect(send)
	panel.closed.connect(toggle_traffic)
	panel.speed_selected.connect(set_speed)
	panel.density_selected.connect(func(value): set_density(roundi(pow(value / 100.0, 2.0) * max_density / 10.0) * 10, true))
	panel.visible = start_args.get("panel", false)
	density_slider = panel.density_slider
	density_label = panel.density_label
	hud_view.buttons.spectator.toggle_mode = true
	panel.show_speed(speed_index)
	set_density(density)

const HELP_LINES := [
	["DRIVING","WASD or arrows — throttle, brake, steer (S when stopped — reverse) · SPACE — handbrake\nC — camera · RMB + mouse — look around · wheel — camera distance · V — car model · R — back to start"],
	["SPECTATOR","F — free camera over the city · WASD move · wheel or Q/E height\nRMB + mouse — turn and tilt · MMB — pan · Z/X — rotate · SHIFT — faster"],
	["TIME AND TRAFFIC","1–6 or [ ] — time speed ×0 … ×16 · −/+ or slider — traffic density\nP or ESC — pause · F5 — reconnect traffic · F12 — screenshot · F9 — mark a defect"],
	["ROAD SITUATIONS","T — panel: accident, lane closure, roadworks, jam, speed limit\nPick a situation and click a road · a click without one shows what is there and unlocks the traffic light"],
]
const ATTRIBUTION := "© OpenStreetMap contributors · ODbL  |  Mapzen Terrain"
const PROVENANCE := "Heights, facades, signs and signal phases are approximate or derived, not surveyed"

func set_help(on: bool) -> void:
	if help_panel:
		help_panel.queue_free()
		help_panel = null
	if on:
		if pause_menu: pause_menu.hide()
		help_panel = Modal.new()
		help_panel.title = "CONTROLS · F1"
		help_panel.bounds = Rect2(0.20, 0.08, 0.60, 0.84)
		help_panel.closed.connect(func(): set_help(false))
		hud.add_child(help_panel)
		for block in HELP_LINES:
			help_panel.body.add_child(Ui.label(block[0], 20, Ui.ACCENT))
			help_panel.body.add_child(Ui.label(block[1], 20, Ui.TEXT, true))
			help_panel.body.add_child(HSeparator.new())
		help_panel.body.add_child(Ui.label("M — map menu · L — language (English / Українська)", 20, Ui.ACCENT, true))
		help_panel.body.add_child(Ui.label("Traffic demand is synthetic", 18, Ui.MUTED, true))
		help_panel.body.add_child(Ui.label(PROVENANCE, 18, Ui.MUTED, true))
		help_panel.body.add_child(Ui.label(ATTRIBUTION, 18, Ui.MUTED, true))
	elif pause_menu:
		pause_menu.show()
	sync_modal_state()

func capture() -> void:
	await RenderingServer.frame_post_draw
	if DisplayServer.get_name()=="headless": return
	get_viewport().get_texture().get_image().save_png("res://../logs/screenshot.png")
	print("SCREENSHOT logs/screenshot.png")

## F9: the frame is grabbed before the dialog appears; the crosshair marks the recorded point.
func mark_defect() -> void:
	if defect_dialog or DisplayServer.get_name()=="headless": return
	await RenderingServer.frame_post_draw
	var exclude: Array[RID] = []
	if player.body: exclude.append(player.body.get_rid())
	var dialog := DefectMarker.new()
	dialog.image = get_viewport().get_texture().get_image()
	dialog.record = DefectMarker.describe(get_viewport(), WorldStream.map_id(), data.offset,
		player.body, exclude, "spectator" if spectating else ("cockpit" if player.cockpit else "chase"))
	dialog.closed.connect(func():
		dialog.queue_free()
		defect_dialog = null
		sync_modal_state())
	defect_dialog = dialog
	hud.add_child(dialog)
	sync_modal_state()

func write_metrics() -> void:
	if fps_samples.is_empty():return
	fps_samples.sort()
	var median: float=fps_samples[fps_samples.size()/2]
	var p95: float=fps_samples[int(fps_samples.size()*0.95)]
	gpu_samples.sort()
	cpu_samples.sort()
	var f:=FileAccess.open("res://../logs/render_metrics.json",FileAccess.WRITE)
	f.store_string(JSON.stringify({"duration":runtime,"median_frame_ms":median,"p95_frame_ms":p95,"median_fps":1000.0/median,"median_gpu_ms":gpu_samples[gpu_samples.size()/2],"p95_gpu_ms":gpu_samples[int(gpu_samples.size()*0.95)],"median_render_cpu_ms":cpu_samples[cpu_samples.size()/2],"vsync":DisplayServer.window_get_vsync_mode(),"renderer":RenderingServer.get_video_adapter_name(),"display":DisplayServer.get_name(),"cars":traffic.count(),"far_cars":traffic.far_count,"near_cars":traffic.cars.size(),"spectating":spectating,"camera_distance":free_cam.distance,"sim_speed":SPEEDS[speed_index],"sim_actual":last_header.get("actual",0),"sumo_step_ms":last_header.get("step_ms",0),"player_position":[player.pos.x,player.pos.y,player.pos.z],"player_contacts":player.contacts,"window_resolution":[get_viewport().size.x,get_viewport().size.y],"render_resolution":[1920,1080]}))

# Fixed camera poses from config/shots.json, for before/after visual comparison.
func run_shots() -> void:
	hud.visible = false
	player.enabled = false
	var cam := Camera3D.new()
	cam.far = 7000 if data.get("visual_profile", "") == "rural" else 2400
	cam.fov = 68
	add_child(cam)
	cam.current = true
	var dir := ProjectSettings.globalize_path("res://../logs/shots")
	DirAccess.make_dir_recursive_absolute(dir)
	if "--showroom" in OS.get_cmdline_user_args():
		await showroom(cam, dir)
		get_tree().quit()
		return
	if "--with-traffic" in OS.get_cmdline_user_args():
		# Let the SUMO bridge populate the streets before shooting.
		connect_bridge()
		var waited := 0.0
		while waited < 12.0:
			await get_tree().process_frame
			waited += get_process_delta_time()
	var shots: Array = data.get("shots",[])
	# --shots-file=PATH: ad-hoc QA poses in world coordinates (tools/shots_file.py), no rebuild.
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--shots-file="):
			shots = JSON.parse_string(FileAccess.get_file_as_string(arg.split("=", true, 1)[1])).shots
	for shot in shots:
		if data.get("visual_profile", "") == "rural":
			env.fog_depth_begin = maxf(600.0, float(shot.height)*2.0)
			env.fog_depth_end = maxf(4500.0, float(shot.height)*8.0)
		var p: Array = shot.position
		cam.position = Vector3(p[0],p[1]+float(shot.height),p[2])
		cam.rotation = Vector3(deg_to_rad(float(shot.pitch)),-deg_to_rad(float(shot.heading)),0)
		capture_focus = cam.position
		world.focus = cam.position
		var waited := 0.0
		while waited < 1.0 or world.pending() > 0:
			# The player's chase camera re-takes the viewport after a reset/menu sync.
			cam.make_current()
			await get_tree().process_frame
			waited += get_process_delta_time()
			if waited > 90.0:
				push_error("Capture tile timeout")
				get_tree().quit(2)
				return
		cam.make_current()
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(dir+"/"+shot.name+".png")
		print("SHOT ",shot.name," camera=",get_viewport().get_camera_3d() == cam)
	get_tree().quit()

## Every catalogue model parked in a row next to the spawn, photographed from the side
## and at an angle (visual QA of scale, wheels and lamps).
func showroom(cam: Camera3D, dir: String) -> void:
	const Vehicles = preload("res://scripts/vehicles.gd")
	var p: Array = data.spawn.position
	var h := -deg_to_rad(float(data.spawn.angle))
	var basis := Basis(Vector3.UP, h)
	var fwd := -basis.z
	var right := basis.x
	var origin := Vector3(p[0], p[1], p[2]) + fwd * 25.0
	var models: Array = Vehicles.traffic_models()
	var i := 0
	for name in models:
		var car := Vehicles.instantiate(name)
		car.root.transform = Transform3D(basis, origin + fwd * (i * 7.5))
		add_child(car.root)
		Vehicles.set_lamps(car.lamps, i % 2 == 0, -1 if i % 3 == 0 else 0, true)
		i += 1
	player.body.visible = false
	var middle := origin + fwd * ((models.size() - 1) * 3.75)
	var views := {"showroom_side": middle - right * 26.0 + Vector3.UP * 3.0, "showroom_angle": origin - fwd * 10.0 - right * 9.0 + Vector3.UP * 4.0}
	for name in views:
		cam.global_position = views[name]
		cam.look_at(middle if name == "showroom_side" else origin + fwd * 10.0 + Vector3.UP * 1.0, Vector3.UP)
		for k in range(10):
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(dir + "/" + name + ".png")
		print("SHOT ", name)

func _exit_tree() -> void:
	preload("res://scripts/vehicles.gd").release_visual_templates()
