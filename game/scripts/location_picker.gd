extends Control
## New map from any place on Earth (opened from the map menu).
##
## Left: a slippy map of OpenStreetMap raster tiles (drag to pan, wheel to zoom around the
## cursor, click to set the centre) with the build area drawn as a rectangle. Right: place
## search (Nominatim), a lat/lon field that accepts "50.45, 30.52" pasted from any web map,
## the area size, the map name and Generate.
##
## Generate runs tools/generate_map.py (build → export → install, all existing pipeline)
## as a separate process and follows its JSONL progress file; on success `generated(id)`
## hands the new map to main.gd, which reloads the scene with it. The build is atomic:
## cancelling publishes nothing.
##
## Tile and search use follows the OSM Foundation policies: a descriptive User-Agent, a
## disk cache, at most 4 tile downloads at a time, searches only on Enter and at most one
## per second, attribution always visible.

signal generated(id: String)
signal back

const TILE := 256
const TILE_URL := "https://tile.openstreetmap.org/%d/%d/%d.png"
const SEARCH_URL := "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6&q=%s"
const USER_AGENT := "User-Agent: TerraDrive-map-picker/1.0 (open-source driving sandbox; Godot)"
const TILE_CACHE := "user://tile_cache"
const MAX_DOWNLOADS := 4
const MAX_TEXTURES := 400
const MIN_ZOOM := 2
const MAX_ZOOM := 18
const KM_PER_DEG_LAT := 110.574      # same constants as tools/generate_map.py
const KM_PER_DEG_LON := 111.320
const MIN_SIZE_KM := 0.3
const MAX_SIZE_KM := 5.0
const LARGE_KM := 2.5
const VIEW := Rect2(20, 20, 820, 680)
const SIDE_X := 860.0
const SIDE_W := 400.0
const EVENTS_FILE := "logs/generate_events.jsonl"
const LOG_FILE := "logs/generate.log"

# Map view state: `center` is what the view shows, `selected` is what will be built.
var center := Vector2(30.52, 50.45)          # (lon, lat)
var selected := Vector2(30.52, 50.45)
var zoom := 12
var size_km := 1.5
var view: Control
var textures: Dictionary = {}                # "z/x/y" -> Texture2D
var texture_order: Array[String] = []
var queue: Array[String] = []
var loading: Dictionary = {}                 # key -> HTTPRequest
var failed: Dictionary = {}
var dragging := false
var press_at := Vector2.ZERO
var moved := 0.0

# Side panel
var search: LineEdit
var results: VBoxContainer
var coords: LineEdit
var size_slider: HSlider
var size_label: Label
var size_warning: Label
var name_edit: LineEdit
var signs_box: CheckBox
var status: Label
var progress: ProgressBar
var generate_button: Button
var back_button: Button
var search_request: HTTPRequest
var last_search := -10.0

# Generator process
var pid := -1
var events_path := ""
var lines_seen := 0
var poll_clock := 0.0
var finished := false
var last_stage := ""
var cancel_path := ""
var cancelling := false

func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	DirAccess.make_dir_recursive_absolute(TILE_CACHE)
	var bg := ColorRect.new()
	bg.color = Color(0.025, 0.05, 0.07, 0.97)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg)
	view = Control.new()
	view.position = VIEW.position
	view.size = VIEW.size
	view.clip_contents = true
	view.mouse_filter = Control.MOUSE_FILTER_STOP
	view.draw.connect(draw_map)
	view.gui_input.connect(map_input)
	add_child(view)
	var attribution := Label.new()
	attribution.text = "© OpenStreetMap contributors"
	attribution.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
	attribution.position = VIEW.position + Vector2(VIEW.size.x - 190, VIEW.size.y - 20)
	attribution.add_theme_font_size_override("font_size", 11)
	attribution.add_theme_color_override("font_color", Color("1d2b33"))
	var attribution_bg := ColorRect.new()
	attribution_bg.color = Color(1, 1, 1, 0.75)
	attribution_bg.position = attribution.position - Vector2(6, 1)
	attribution_bg.size = Vector2(190, 18)
	attribution_bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(attribution_bg)
	add_child(attribution)
	var help := Label.new()
	help.text = "Drag — pan · wheel — zoom · click — set the centre"
	help.position = VIEW.position + Vector2(10, 8)
	help.add_theme_font_size_override("font_size", 12)
	help.add_theme_color_override("font_color", Color("1d2b33"))
	help.add_theme_color_override("font_outline_color", Color(1, 1, 1, 0.85))
	help.add_theme_constant_override("outline_size", 4)
	add_child(help)
	search_request = HTTPRequest.new()
	search_request.timeout = 15.0
	search_request.request_completed.connect(search_done)
	add_child(search_request)
	build_side()
	# Start where the player is now: the current map's centre, if it records one.
	var here := current_map_center()
	if here != Vector2.INF:
		center = here
		selected = here
	sync_fields()

func build_side() -> void:
	var box := VBoxContainer.new()
	box.position = Vector2(SIDE_X, 20)
	box.size = Vector2(SIDE_W, 680)
	box.add_theme_constant_override("separation", 6)
	add_child(box)
	box.add_child(head("NEW MAP", 20, Color.WHITE))
	search = LineEdit.new()
	search.placeholder_text = "Search a place (Enter)"
	search.text_submitted.connect(func(_t): run_search())
	box.add_child(search)
	results = VBoxContainer.new()
	results.add_theme_constant_override("separation", 2)
	box.add_child(results)
	box.add_child(head("Latitude, longitude (e.g. 50.45, 30.52)", 11, Color("a0b4bd")))
	coords = LineEdit.new()
	coords.text_submitted.connect(func(_t): apply_coords())
	coords.focus_exited.connect(apply_coords)
	box.add_child(coords)
	size_label = head("", 12, Color("cfdae0"))
	box.add_child(size_label)
	size_slider = HSlider.new()
	size_slider.min_value = MIN_SIZE_KM
	size_slider.max_value = MAX_SIZE_KM
	size_slider.step = 0.1
	size_slider.value = size_km
	size_slider.value_changed.connect(func(v):
		size_km = v
		update_size()
		view.queue_redraw())
	box.add_child(size_slider)
	size_warning = head("", 11, Color("859ca7"))
	size_warning.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(size_warning)
	box.add_child(head("Map name", 11, Color("a0b4bd")))
	name_edit = LineEdit.new()
	box.add_child(name_edit)
	signs_box = CheckBox.new()
	signs_box.text = "Ukrainian road signs (Ukraine only)"
	signs_box.focus_mode = Control.FOCUS_NONE
	signs_box.add_theme_font_size_override("font_size", 12)
	box.add_child(signs_box)
	var note := head("Downloads OpenStreetMap data and terrain. Areas outside Ukraine build without road signs.", 11, Color("859ca7"))
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	note.custom_minimum_size = Vector2(SIDE_W, 0)
	box.add_child(note)
	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_child(spacer)
	status = head("", 12, Color("f1bc60"))
	status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status.custom_minimum_size = Vector2(SIDE_W, 0)
	box.add_child(status)
	progress = ProgressBar.new()
	progress.max_value = 1.0
	progress.step = 0.001
	progress.visible = false
	box.add_child(progress)
	var buttons := HBoxContainer.new()
	buttons.add_theme_constant_override("separation", 10)
	box.add_child(buttons)
	back_button = Button.new()
	back_button.text = "Back"
	back_button.custom_minimum_size = Vector2(120, 38)
	back_button.pressed.connect(back_or_cancel)
	buttons.add_child(back_button)
	generate_button = Button.new()
	generate_button.text = "Generate"
	generate_button.custom_minimum_size = Vector2(200, 38)
	generate_button.add_theme_font_size_override("font_size", 16)
	generate_button.pressed.connect(start_generation)
	buttons.add_child(generate_button)
	update_size()

func head(text: String, size_px: int, colour: Color) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_size_override("font_size", size_px)
	l.add_theme_color_override("font_color", colour)
	return l

## index.json records bbox as [west, south, east, north]; its centre is a good start.
func current_map_center() -> Vector2:
	var path := "res://data/%s/index.json" % OS.get_environment("AKADEM_MAP")
	if OS.get_environment("AKADEM_MAP") == "" or not FileAccess.file_exists(path):
		return Vector2.INF
	var file := FileAccess.open(path, FileAccess.READ)
	var head_text := file.get_buffer(mini(4096, file.get_length())).get_string_from_ascii()
	var found := RegEx.create_from_string("\"bbox\"\\s*:\\s*\\[\\s*([-0-9.eE]+)\\s*,\\s*([-0-9.eE]+)\\s*,\\s*([-0-9.eE]+)\\s*,\\s*([-0-9.eE]+)").search(head_text)
	if found == null:
		return Vector2.INF
	return Vector2((found.get_string(1).to_float() + found.get_string(3).to_float()) / 2.0,
		(found.get_string(2).to_float() + found.get_string(4).to_float()) / 2.0)

# --- Web Mercator ------------------------------------------------------------------

## (lon, lat) -> tile coordinates at `z` (fractional).
static func to_tile(lonlat: Vector2, z: int) -> Vector2:
	var n := float(1 << z)
	var lat := deg_to_rad(clampf(lonlat.y, -85.0511, 85.0511))
	return Vector2((lonlat.x + 180.0) / 360.0 * n, (1.0 - log(tan(lat) + 1.0 / cos(lat)) / PI) / 2.0 * n)

static func from_tile(t: Vector2, z: int) -> Vector2:
	var n := float(1 << z)
	return Vector2(t.x / n * 360.0 - 180.0, rad_to_deg(atan(sinh(PI * (1.0 - 2.0 * t.y / n)))))

## Tile edge in view units: the menu layer is scaled, tiles stay 256 screen pixels.
func tile_px() -> float:
	return TILE / maxf(0.01, view.get_global_transform_with_canvas().get_scale().x)

func screen_to_lonlat(p: Vector2) -> Vector2:
	return from_tile(to_tile(center, zoom) + (p - view.size / 2.0) / tile_px(), zoom)

func lonlat_to_screen(ll: Vector2) -> Vector2:
	return view.size / 2.0 + (to_tile(ll, zoom) - to_tile(center, zoom)) * tile_px()

## Same square as tools/generate_map.py bbox_around: [west, south, east, north].
func area_bbox() -> Array:
	var dlat := size_km / 2.0 / KM_PER_DEG_LAT
	var dlon := size_km / 2.0 / (KM_PER_DEG_LON * cos(deg_to_rad(selected.y)))
	return [selected.x - dlon, selected.y - dlat, selected.x + dlon, selected.y + dlat]

# --- Drawing and tiles ------------------------------------------------------------

func draw_map() -> void:
	var ts := tile_px()
	var n := 1 << zoom
	var c := to_tile(center, zoom)
	var half := view.size / 2.0 / ts
	view.draw_rect(Rect2(Vector2.ZERO, view.size), Color("aad3df"))
	for ty in range(maxi(0, floori(c.y - half.y)), mini(n, ceili(c.y + half.y))):
		for tx in range(floori(c.x - half.x), ceili(c.x + half.x)):
			var pos := view.size / 2.0 + (Vector2(tx, ty) - c) * ts
			var key := "%d/%d/%d" % [zoom, posmod(tx, n), ty]
			var tex: Texture2D = textures.get(key)
			if tex == null:
				tex = cached_tile(key)
			if tex:
				view.draw_texture_rect(tex, Rect2(pos, Vector2(ts, ts)), false)
			else:
				view.draw_rect(Rect2(pos, Vector2(ts, ts)), Color("dfe6e8"))
				request_tile(key)
	# Build area and centre marker.
	var b := area_bbox()
	var a := lonlat_to_screen(Vector2(b[0], b[3]))
	var z := lonlat_to_screen(Vector2(b[2], b[1]))
	var rect := Rect2(a, z - a)
	view.draw_rect(rect, Color(0.95, 0.55, 0.1, 0.18))
	view.draw_rect(rect, Color(0.95, 0.45, 0.05, 0.95), false, 2.0)
	var p := lonlat_to_screen(selected)
	view.draw_circle(p, 5.0, Color(0.95, 0.45, 0.05))
	view.draw_circle(p, 2.0, Color.WHITE)

## A tile from the disk cache, loaded while drawing (a redraw requested inside the draw
## callback would be dropped), or null.
func cached_tile(key: String) -> Texture2D:
	var path := "%s/%s.png" % [TILE_CACHE, key]
	if not FileAccess.file_exists(path):
		return null
	var img := Image.new()
	if img.load_png_from_buffer(FileAccess.get_file_as_bytes(path)) != OK:
		return null
	var tex := ImageTexture.create_from_image(img)
	remember(key, tex)
	return tex

func request_tile(key: String) -> void:
	if loading.has(key) or failed.has(key) or key in queue:
		return
	queue.append(key)
	pump()

func pump() -> void:
	# Only tiles of the current zoom are worth downloading; older requests are dropped.
	queue.assign(queue.filter(func(k: String): return k.begins_with("%d/" % zoom)))
	while loading.size() < MAX_DOWNLOADS and not queue.is_empty():
		var key: String = queue.pop_back()     # newest first: what is on screen now
		var parts := key.split("/")
		var http := HTTPRequest.new()
		http.timeout = 20.0
		add_child(http)
		loading[key] = http
		http.request_completed.connect(func(result, code, _h, body): tile_done(key, http, result, code, body))
		var err := http.request(TILE_URL % [int(parts[0]), int(parts[1]), int(parts[2])], [USER_AGENT])
		if err != OK:
			tile_done(key, http, HTTPRequest.RESULT_CANT_CONNECT, 0, PackedByteArray())

func tile_done(key: String, http: HTTPRequest, result: int, code: int, body: PackedByteArray) -> void:
	loading.erase(key)
	http.queue_free()
	if result == HTTPRequest.RESULT_SUCCESS and code == 200:
		var img := Image.new()
		if img.load_png_from_buffer(body) == OK:
			var path := "%s/%s.png" % [TILE_CACHE, key]
			DirAccess.make_dir_recursive_absolute(path.get_base_dir())
			var f := FileAccess.open(path, FileAccess.WRITE)
			if f:
				f.store_buffer(body)
			remember(key, ImageTexture.create_from_image(img))
	else:
		failed[key] = true
		if failed.size() == 1:
			status.text = tr("Map tiles unavailable (offline?) — coordinates still work")
	view.queue_redraw()
	pump()

func remember(key: String, tex: Texture2D) -> void:
	textures[key] = tex
	texture_order.append(key)
	while texture_order.size() > MAX_TEXTURES:
		textures.erase(texture_order.pop_front())

# --- Input ------------------------------------------------------------------------

func map_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN] and event.pressed:
			zoom_at(event.position, 1 if event.button_index == MOUSE_BUTTON_WHEEL_UP else -1)
		elif event.button_index == MOUSE_BUTTON_LEFT:
			if event.pressed:
				dragging = true
				press_at = event.position
				moved = 0.0
			else:
				dragging = false
				if moved < 5.0 and pid < 0:
					select(screen_to_lonlat(event.position), false)
	elif event is InputEventMouseMotion and dragging:
		moved += event.relative.length()
		center = from_tile(to_tile(center, zoom) - event.relative / tile_px(), zoom)
		center.x = wrapf(center.x, -180.0, 180.0)
		view.queue_redraw()

## Zoom one level keeping the point under the cursor in place.
func zoom_at(p: Vector2, step: int) -> void:
	var next := clampi(zoom + step, MIN_ZOOM, MAX_ZOOM)
	if next == zoom:
		return
	var anchor := screen_to_lonlat(p)
	zoom = next
	center = from_tile(to_tile(anchor, zoom) - (p - view.size / 2.0) / tile_px(), zoom)
	view.queue_redraw()

func select(lonlat: Vector2, recenter: bool) -> void:
	selected = Vector2(wrapf(lonlat.x, -180.0, 180.0), clampf(lonlat.y, -84.9, 84.9))
	if recenter:
		center = selected
	sync_fields()
	view.queue_redraw()

func sync_fields() -> void:
	coords.text = "%.5f, %.5f" % [selected.y, selected.x]
	signs_box.button_pressed = selected.x >= 22.1 and selected.x <= 40.3 and selected.y >= 44.3 and selected.y <= 52.4
	update_size()

## "50.45, 30.52", "50.45 30.52" or "50.45;30.52" (latitude first, as web maps copy it).
func apply_coords() -> void:
	var parts := coords.text.replace(";", ",").replace(",", " ").split(" ", false)
	if parts.size() == 2 and parts[0].is_valid_float() and parts[1].is_valid_float():
		var lat := parts[0].to_float()
		var lon := parts[1].to_float()
		if absf(lat) < 85.0 and absf(lon) <= 180.0:
			select(Vector2(lon, lat), true)
			return
	status.text = tr("Invalid coordinates")

func update_size() -> void:
	if size_label == null:
		return
	size_label.text = tr("Area: %.1f × %.1f km (%.1f km²)") % [size_km, size_km, size_km * size_km]
	size_warning.text = tr("Large area: may take 10–30 minutes and several GB of memory") if size_km > LARGE_KM else tr("Usually a few minutes")
	size_warning.add_theme_color_override("font_color", Color("e08a6a") if size_km > LARGE_KM else Color("859ca7"))
	# Edges near the antimeridian or the poles cannot be built.
	var b := area_bbox()
	if generate_button:
		generate_button.disabled = pid >= 0 or b[0] < -180.0 or b[2] > 180.0 or b[1] <= -85.0 or b[3] >= 85.0

# --- Search -----------------------------------------------------------------------

func run_search() -> void:
	var q := search.text.strip_edges()
	if q == "":
		return
	var now := Time.get_ticks_msec() / 1000.0
	if now - last_search < 1.0:
		return
	last_search = now
	search_request.cancel_request()
	for child in results.get_children():
		child.queue_free()
	status.text = tr("Searching…")
	var lang := "Accept-Language: " + ("uk,en" if TranslationServer.get_locale().begins_with("uk") else "en")
	search_request.request(SEARCH_URL % q.uri_encode(), [USER_AGENT, lang])

func search_done(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		status.text = tr("Search failed (HTTP %d)") % code
		return
	var found = JSON.parse_string(body.get_string_from_utf8())
	if not found is Array or found.is_empty():
		status.text = tr("Nothing found")
		return
	status.text = ""
	for item in found:
		var lat := str(item.get("lat", "")).to_float()
		var lon := str(item.get("lon", "")).to_float()
		var title := str(item.get("display_name", ""))
		var b := Button.new()
		b.auto_translate_mode = Node.AUTO_TRANSLATE_MODE_DISABLED
		b.text = title if title.length() <= 60 else title.substr(0, 58) + "…"
		b.tooltip_text = title
		b.alignment = HORIZONTAL_ALIGNMENT_LEFT
		b.clip_text = true
		b.custom_minimum_size = Vector2(SIDE_W, 26)
		b.add_theme_font_size_override("font_size", 11)
		b.pressed.connect(func():
			zoom = 14
			select(Vector2(lon, lat), true)
			if name_edit.text.strip_edges() == "":
				name_edit.text = title.split(",")[0].strip_edges())
		results.add_child(b)

# --- Generation -------------------------------------------------------------------

static func project_root() -> String:
	return ProjectSettings.globalize_path("res://").trim_suffix("/").get_base_dir()

func start_generation() -> void:
	if pid >= 0:
		return
	apply_coords()
	var root := project_root()
	var python := root + ("/.venv/Scripts/python.exe" if OS.get_name() == "Windows" else "/.venv/bin/python")
	if not FileAccess.file_exists(python):
		status.text = tr("Could not start the generator: %s") % python
		return
	DirAccess.make_dir_recursive_absolute(root + "/logs")
	events_path = root + "/logs/generate_%d_%d.jsonl" % [OS.get_process_id(), Time.get_ticks_msec()]
	cancel_path = events_path + ".cancel"
	cancelling = false
	if FileAccess.file_exists(events_path):
		DirAccess.remove_absolute(events_path)
	var args := PackedStringArray([root + "/tools/generate_map.py",
		"--lat", "%.6f" % selected.y, "--lon", "%.6f" % selected.x, "--size-km", "%.2f" % size_km,
		"--region-profile", "ukraine" if signs_box.button_pressed else "experimental",
		"--events", events_path, "--log", events_path + ".log", "--exit-with-parent",
		"--parent-pid", str(OS.get_process_id()), "--cancel-file", cancel_path])
	var map_name := name_edit.text.strip_edges()
	if map_name != "":
		args.append_array(["--name", map_name])
	pid = OS.create_process(python, args, false)
	if pid <= 0:
		pid = -1
		status.text = tr("Could not start the generator: %s") % python
		return
	lines_seen = 0
	finished = false
	last_stage = ""
	print("Map generator started (pid %d); full log: %s" % [pid, root + "/" + LOG_FILE])
	status.text = tr("Starting the generator…")
	progress.value = 0.0
	progress.visible = true
	back_button.text = "Cancel"
	update_size()

## Stops the generator together with its children (curl, netconvert…). The generator runs
## in its own process group (Godot starts it with setsid), so SIGTERM to the group reaches
## all of them; OS.kill alone would SIGKILL only Python and orphan a running download.
func stop_generator() -> void:
	if OS.get_name() == "Windows":
		var request := FileAccess.open(cancel_path, FileAccess.WRITE)
		if request:
			request.store_string("cancel\n")
		else:
			OS.execute("taskkill", ["/PID", str(pid), "/T", "/F"])
	elif OS.execute("kill", ["-TERM", "-%d" % pid]) != 0:
		OS.kill(pid)

func back_or_cancel() -> void:
	if pid >= 0:
		stop_generator()
		cancelling = true
		back_button.disabled = true
		status.text = tr("Cancelling…")
	else:
		back.emit()

func _process(delta: float) -> void:
	if pid < 0 or finished:
		return
	poll_clock += delta
	if poll_clock < 0.25:
		return
	poll_clock = 0.0
	read_events()
	if not finished and not OS.is_process_running(pid):
		read_events()
		if not finished:
			if cancelling:
				fail(tr("Generation cancelled"))
				return
			printerr("Map generator stopped without a result (log: %s)" % LOG_FILE)
			fail(tr("Generator stopped without a result (see logs/generate.log)"))

func read_events() -> void:
	if not FileAccess.file_exists(events_path):
		return
	var text := FileAccess.get_file_as_string(events_path)
	# Only complete lines: the generator may be writing the last one right now.
	var lines := text.substr(0, text.rfind("\n") + 1).split("\n", false)
	for i in range(lines_seen, lines.size()):
		var record = JSON.parse_string(lines[i])
		if not record is Dictionary:
			continue
		match str(record.get("event", "")):
			"stage":
				progress.value = float(record.get("progress", progress.value))
				status.text = "%s · %s" % [tr(str(record.get("phase", ""))), tr(str(record.get("stage", "")))]
				var stage := "%s · %s" % [record.get("phase", ""), record.get("stage", "")]
				if stage != last_stage:
					last_stage = stage
					print("Map generator: %s (%d%%)" % [stage, int(progress.value * 100)])
			"download":
				var url := str(record.get("url", ""))
				status.text = tr("Downloading OpenStreetMap data from %s…") % url.get_slice("/", 2)
				print("Map generator: downloading from %s" % url)
				if record.has("query_url"):
					print("  to check by hand, open: %s" % record["query_url"])
			"warning":
				status.text = str(record.get("message", ""))
				print("Map generator: %s" % record.get("message", ""))
			"result":
				finished = true
				pid = -1
				progress.value = 1.0
				status.text = tr("Done: %s — loading…") % str(record.get("id", ""))
				generated.emit.call_deferred(str(record.get("id", "")))
			"error":
				var message := str(record.get("message", record.get("code", "")))
				printerr("Map generator failed: %s (log: %s)" % [message, LOG_FILE])
				fail(tr("Failed: %s") % message)
	lines_seen = lines.size()

func fail(message: String) -> void:
	finished = true
	pid = -1
	progress.visible = false
	back_button.text = "Back"
	back_button.disabled = false
	status.text = message
	update_size()

func _exit_tree() -> void:
	if pid >= 0:
		stop_generator()
