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
const USER_AGENT := "User-Agent: Earth2Road-map-picker/1.0 (open-source driving sandbox; Godot)"
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
const Ui = preload("res://scripts/ui_theme.gd")
const SIDE_W := 536.0
## Plain-language status per generator stage (tools/generate_map.py, akadem_maps/world.py);
## the raw phase/stage stays in the technical details.
const STAGE_TEXT := {
	"start": "Starting the generator…",
	"sources": "Reading the map data…",
	"local_extract": "Extracting local map data…",
	"geometry": "Reading the map data…",
	"terrain": "Shaping the terrain…",
	"network": "Building the road network…",
	"roads": "Building roads and scenery…",
	"ground": "Building roads and scenery…",
	"landcover": "Building roads and scenery…",
	"buildings": "Placing buildings…",
	"trees": "Placing trees…",
	"signs": "Placing road signs…",
	"tiles": "Packing map tiles…",
	"surface_audit": "Checking road surfaces…",
	"provenance": "Recording data sources…",
	"export": "Preparing the map to drive…",
	"install": "Installing the map…",
}

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
var side: VBoxContainer
var details: Label
var details_button: Button
var search_status: Label
var had_error := false
var source_mode: OptionButton
var local_package: OptionButton
var saved_area: OptionButton
var readiness: Label
var refresh_source: CheckBox
var source_buttons: Array[Button] = []
var download_package_button: Button
var package_offer: Dictionary = {}
var active_action := "generate"
var source_check_at := -1
var import_path := ""
var import_bounds: LineEdit

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
	theme = Ui.make()
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	DirAccess.make_dir_recursive_absolute(TILE_CACHE)
	var bg := ColorRect.new()
	bg.color = Ui.BG
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg)
	var layout := VBoxContainer.new()
	Ui.inset(self).add_child(layout)
	var header := HBoxContainer.new()
	layout.add_child(header)
	header.add_child(Ui.label("NEW MAP", 32))
	header.add_child(Ui.expand())
	header.add_child(Ui.label("Choose a place. Build a drive.", 20, Ui.MUTED))
	var columns := HBoxContainer.new()
	columns.size_flags_vertical = Control.SIZE_EXPAND_FILL
	columns.add_theme_constant_override("separation", 24)
	layout.add_child(columns)
	var map_column := VBoxContainer.new()
	map_column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	columns.add_child(map_column)
	var map_tools := HBoxContainer.new()
	map_column.add_child(map_tools)
	map_tools.add_child(Ui.label("1 / LOCATION", 18, Ui.ACCENT))
	map_tools.add_child(Ui.expand())
	map_tools.add_child(Ui.button("−", func(): zoom_at(view.size / 2.0, -1)))
	map_tools.add_child(Ui.button("+", func(): zoom_at(view.size / 2.0, 1)))
	view = Control.new()
	view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	view.clip_contents = true
	view.focus_mode = Control.FOCUS_ALL
	view.mouse_filter = Control.MOUSE_FILTER_STOP
	view.draw.connect(draw_map)
	view.gui_input.connect(map_input)
	view.resized.connect(func(): view.queue_redraw())
	map_column.add_child(view)
	map_column.add_child(Ui.label("Drag — pan · wheel — zoom · click — set the centre", 18, Ui.MUTED, true))
	map_column.add_child(Ui.label("© OpenStreetMap contributors · ODbL", 16, Ui.MUTED))
	var card := PanelContainer.new()
	card.custom_minimum_size.x = SIDE_W + 48
	columns.add_child(card)
	side = VBoxContainer.new()
	card.add_child(side)
	search_request = HTTPRequest.new()
	search_request.timeout = 15.0
	search_request.request_completed.connect(search_done)
	add_child(search_request)
	build_side()
	var here := current_map_center()
	if here != Vector2.INF:
		center = here
		selected = here
	sync_fields()
	search.grab_focus.call_deferred()
	# follow_focus can scroll against a not yet sorted layout; start at the top instead.
	await get_tree().process_frame
	(search.get_parent().get_parent().get_parent() as ScrollContainer).scroll_vertical = 0

func build_side() -> void:
	var box := Ui.scroll_box(side)
	box.add_child(Ui.label("Find a place", 24))
	search = LineEdit.new()
	search.placeholder_text = "Search a place (Enter)"
	search.text_submitted.connect(func(_t): run_search())
	box.add_child(search)
	var find_button := Ui.button("Search", run_search)
	box.add_child(find_button)
	search_status = Ui.label("", 18, Ui.WARNING, true)
	search_status.visible = false
	box.add_child(search_status)
	results = VBoxContainer.new()
	results.visible = false
	box.add_child(results)
	box.add_child(Ui.label("Latitude, longitude (e.g. 50.45, 30.52)", 18, Ui.MUTED, true))
	coords = LineEdit.new()
	coords.text_submitted.connect(func(_t): apply_coords())
	coords.focus_exited.connect(apply_coords)
	box.add_child(coords)
	box.add_child(HSeparator.new())
	box.add_child(Ui.label("2 / AREA & DETAILS", 18, Ui.ACCENT))
	size_label = Ui.label("", 20, Ui.TEXT, true)
	box.add_child(size_label)
	size_slider = HSlider.new()
	size_slider.custom_minimum_size.y = 32
	size_slider.min_value = MIN_SIZE_KM
	size_slider.max_value = MAX_SIZE_KM
	size_slider.step = 0.1
	size_slider.value = size_km
	size_slider.value_changed.connect(func(v):
		size_km = v
		source_check_at = Time.get_ticks_msec() + 700
		package_offer.clear()
		if download_package_button: download_package_button.visible = false
		update_size()
		view.queue_redraw())
	box.add_child(size_slider)
	size_warning = Ui.label("", 18, Ui.MUTED, true)
	box.add_child(size_warning)
	box.add_child(Ui.label("Map name", 18, Ui.MUTED))
	name_edit = LineEdit.new()
	box.add_child(name_edit)
	signs_box = CheckBox.new()
	signs_box.text = "Ukrainian road signs (Ukraine only)"
	signs_box.add_theme_font_size_override("font_size", 18)
	box.add_child(signs_box)
	box.add_child(Ui.label("Downloads OpenStreetMap data and terrain. Areas outside Ukraine build without road signs.", 18, Ui.MUTED, true))
	box.add_child(HSeparator.new())
	box.add_child(Ui.label("Map data", 24))
	source_mode = OptionButton.new()
	source_mode.add_item(tr("Auto: cache → local package → internet"))
	source_mode.add_item(tr("Offline: local data only"))
	source_mode.item_selected.connect(func(_i):
		if source_mode.selected == 1:
			search_request.cancel_request()
			queue.clear()
			for request in loading.values():
				request.cancel_request()
				request.queue_free()
			loading.clear()
			refresh_source.button_pressed = false
		update_size()
		view.queue_redraw())
	box.add_child(source_mode)
	saved_area = OptionButton.new()
	saved_area.add_item(tr("Saved offline areas"))
	saved_area.item_selected.connect(func(index):
		if index == 0: return
		var area: Dictionary = saved_area.get_item_metadata(index)
		var b: Array = area["bbox"]
		size_km = clampf((float(b[3])-float(b[1]))*KM_PER_DEG_LAT, MIN_SIZE_KM, MAX_SIZE_KM)
		size_slider.set_value_no_signal(size_km)
		name_edit.text = str(area["name"])
		select(Vector2((float(b[0])+float(b[2]))/2.0, (float(b[1])+float(b[3]))/2.0), true))
	box.add_child(saved_area)
	local_package = OptionButton.new()
	local_package.add_item(tr("Choose local package automatically"))
	box.add_child(local_package)
	readiness = Ui.label("Check local OSM and terrain readiness", 18, Ui.MUTED, true)
	box.add_child(readiness)
	for item in [["Check local data", "status"], ["Prepare area offline", "prepare"], ["Find regional package", "suggest"]]:
		var action: String = item[1]
		var button := Ui.button(item[0], func(): start_data_action(action))
		source_buttons.append(button)
		box.add_child(button)
	download_package_button = Ui.button("Download package", func(): start_data_action("download"))
	download_package_button.visible = false
	box.add_child(download_package_button)
	var import_button := Ui.button("Import local PBF…", choose_pbf)
	source_buttons.append(import_button)
	box.add_child(import_button)
	refresh_source = CheckBox.new()
	refresh_source.text = "Refresh snapshot (keep previous version)"
	box.add_child(refresh_source)
	details_button = Ui.button("Technical details", func(): details.visible = not details.visible)
	details_button.toggle_mode = true
	box.add_child(details_button)
	details = Ui.label("", 16, Ui.MUTED, true)
	details.visible = false
	box.add_child(details)
	side.add_child(HSeparator.new())
	side.add_child(Ui.label("3 / BUILD", 18, Ui.ACCENT))
	status = Ui.label("Select an area, then Generate", 20, Ui.TEXT, true)
	side.add_child(status)
	progress = ProgressBar.new()
	progress.custom_minimum_size.y = 24
	progress.max_value = 1.0
	progress.step = 0.001
	progress.visible = false
	side.add_child(progress)
	var buttons := HBoxContainer.new()
	side.add_child(buttons)
	back_button = Ui.button("Back", back_or_cancel)
	back_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	buttons.add_child(back_button)
	generate_button = Ui.button("Generate", start_generation, true)
	generate_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	buttons.add_child(generate_button)
	update_size()
	source_check_at = Time.get_ticks_msec() + 500

func _input(event: InputEvent) -> void:
	Ui.trap_focus(self, event)
	if event is InputEventKey and event.pressed and not event.echo and event.physical_keycode == KEY_ESCAPE:
		get_viewport().set_input_as_handled()
		if not cancelling and not back_button.disabled: back_or_cancel()

func set_search_status(text: String) -> void:
	search_status.text = text
	search_status.visible = text != ""

func technical(text: String) -> void:
	details.text = (details.text + "\n" + text).right(3000)

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
	view.draw_rect(rect, Color(0.1, 0.65, 0.55, 0.18))
	view.draw_rect(rect, Color("208d7d"), false, 2.0)
	var p := lonlat_to_screen(selected)
	view.draw_circle(p, 5.0, Color("208d7d"))
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
	if source_mode != null and source_mode.selected == 1:
		return
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
			set_search_status(tr("Map tiles unavailable (offline?) — coordinates still work"))
	view.queue_redraw()
	pump()

func remember(key: String, tex: Texture2D) -> void:
	textures[key] = tex
	texture_order.append(key)
	while texture_order.size() > MAX_TEXTURES:
		textures.erase(texture_order.pop_front())

# --- Input ------------------------------------------------------------------------

func map_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed:
		var movement := Vector2.ZERO
		match event.physical_keycode:
			KEY_LEFT: movement.x = -1
			KEY_RIGHT: movement.x = 1
			KEY_UP: movement.y = -1
			KEY_DOWN: movement.y = 1
			KEY_EQUAL: zoom_at(view.size / 2.0, 1)
			KEY_MINUS: zoom_at(view.size / 2.0, -1)
			KEY_ENTER:
				if pid < 0: select(center, false)
		if movement != Vector2.ZERO:
			center = from_tile(to_tile(center, zoom) + movement * 0.25, zoom)
		view.queue_redraw()
		view.accept_event()
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
	var changed := not selected.is_equal_approx(lonlat)
	selected = Vector2(wrapf(lonlat.x, -180.0, 180.0), clampf(lonlat.y, -84.9, 84.9))
	if recenter:
		center = selected
	sync_fields()
	source_check_at = Time.get_ticks_msec() + 700
	if changed:
		package_offer.clear()
		if download_package_button: download_package_button.visible = false
	view.queue_redraw()

func sync_fields() -> void:
	coords.text = "%.5f, %.5f" % [selected.y, selected.x]
	signs_box.button_pressed = selected.x >= 22.1 and selected.x <= 40.3 and selected.y >= 44.3 and selected.y <= 52.4
	update_size()

## "50.45, 30.52", "50.45 30.52" or "50.45;30.52" (latitude first, as web maps copy it).
func apply_coords() -> bool:
	if pid >= 0: return false
	var parts := coords.text.replace(";", ",").replace(",", " ").split(" ", false)
	if parts.size() == 2 and parts[0].is_valid_float() and parts[1].is_valid_float():
		var lat := parts[0].to_float()
		var lon := parts[1].to_float()
		if absf(lat) < 85.0 and absf(lon) <= 180.0:
			select(Vector2(lon, lat), true)
			return true
	status.text = tr("Invalid coordinates")
	return false

func update_size() -> void:
	if size_label == null:
		return
	size_label.text = tr("Area: %.1f × %.1f km (%.1f km²)") % [size_km, size_km, size_km * size_km]
	size_warning.text = tr("Large area: may take 10–30 minutes and several GB of memory") if size_km > LARGE_KM else tr("Usually a few minutes")
	size_warning.add_theme_color_override("font_color", Color("e08a6a") if size_km > LARGE_KM else Color("859ca7"))
	# Edges near the antimeridian or the poles cannot be built.
	var b := area_bbox()
	if generate_button:
		generate_button.text = "Retry" if had_error else "Generate"
		search.editable = pid < 0
		coords.editable = pid < 0
		name_edit.editable = pid < 0
		size_slider.editable = pid < 0
		signs_box.disabled = pid >= 0
		generate_button.disabled = pid >= 0 or b[0] < -180.0 or b[2] > 180.0 or b[1] <= -85.0 or b[3] >= 85.0
	if source_mode:
		source_mode.disabled = pid >= 0
		local_package.disabled = pid >= 0
		saved_area.disabled = pid >= 0
		refresh_source.disabled = pid >= 0 or source_mode.selected == 1
		for button in source_buttons: button.disabled = pid >= 0
		source_buttons[2].disabled = pid >= 0 or source_mode.selected == 1
		download_package_button.disabled = pid >= 0 or source_mode.selected == 1

# --- Search -----------------------------------------------------------------------

func run_search() -> void:
	if pid >= 0: return
	if source_mode.selected == 1:
		set_search_status(tr("Offline: use coordinates or a saved area"))
		return
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
	results.visible = false
	status.text = tr("Searching…")
	var lang := "Accept-Language: " + ("uk,en" if TranslationServer.get_locale().begins_with("uk") else "en")
	search_request.request(SEARCH_URL % q.uri_encode(), [USER_AGENT, lang])

func search_done(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		set_search_status(tr("Search failed (HTTP %d)") % code)
		return
	var found = JSON.parse_string(body.get_string_from_utf8())
	if not found is Array or found.is_empty():
		set_search_status(tr("Nothing found"))
		return
	set_search_status("")
	results.visible = true
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
		b.custom_minimum_size = Vector2(0, 48)
		b.add_theme_font_size_override("font_size", 18)
		b.pressed.connect(func():
			if pid >= 0: return
			zoom = 14
			select(Vector2(lon, lat), true)
			if name_edit.text.strip_edges() == "":
				name_edit.text = title.split(",")[0].strip_edges())
		results.add_child(b)

# --- Generation -------------------------------------------------------------------

static func project_root() -> String:
	return ProjectSettings.globalize_path("res://").trim_suffix("/").get_base_dir()

func start_generation() -> void:
	start_data_action("generate")

func start_data_action(action: String) -> void:
	if pid >= 0:
		return
	var accepted_offer := package_offer.duplicate()
	if not apply_coords(): return
	active_action = action
	source_check_at = -1
	var root := project_root()
	var python := root + ("/.venv/Scripts/python.exe" if OS.get_name() == "Windows" else "/.venv/bin/python")
	if not FileAccess.file_exists(python):
		status.text = tr("Could not start the generator: %s") % python
		return
	DirAccess.make_dir_recursive_absolute(root + "/logs")
	events_path = root + "/logs/generate_%d_%d.jsonl" % [OS.get_process_id(), Time.get_ticks_msec()]
	cancel_path = events_path + ".cancel"
	cancelling = false
	had_error = false
	details.text = events_path + ".log"
	if FileAccess.file_exists(events_path):
		DirAccess.remove_absolute(events_path)
	var args := PackedStringArray([root + "/tools/generate_map.py",
		"--lat", "%.6f" % selected.y, "--lon", "%.6f" % selected.x, "--size-km", "%.2f" % size_km,
		"--region-profile", "ukraine" if signs_box.button_pressed else "experimental",
		"--events", events_path, "--log", events_path + ".log", "--exit-with-parent",
		"--parent-pid", str(OS.get_process_id()), "--cancel-file", cancel_path])
	args.append_array(["--action", action, "--mode", "offline" if source_mode.selected == 1 else "auto"])
	if local_package.selected > 0:
		args.append_array(["--package", str(local_package.get_item_metadata(local_package.selected))])
	if refresh_source.button_pressed and action in ["generate", "prepare"]:
		args.append("--refresh")
	if action == "download":
		if accepted_offer.is_empty(): return
		args.append_array(["--offer", str(accepted_offer["offer"]), "--accept-bytes", str(accepted_offer["bytes"])])
	if action == "import":
		var values := import_bounds.text.replace(",", " ").split(" ", false)
		if values.size() != 4:
			status.text = tr("Enter coverage: west south east north")
			return
		args.append_array(["--pbf", import_path, "--coverage"])
		args.append_array(values)
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
	print("Map generator started (pid %d); full log: %s" % [pid, events_path + ".log"])
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
	if pid < 0 and source_check_at >= 0 and Time.get_ticks_msec() >= source_check_at:
		start_data_action("status")
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
			printerr("Map generator stopped without a result (log: %s.log)" % events_path)
			had_error = true
			fail(tr("Could not build the map. Check your connection and retry."))

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
				progress.value = maxf(progress.value, float(record.get("progress", progress.value)))
				back_button.disabled = cancelling or record.get("phase", "") == "install"
				status.text = stage_text(str(record.get("phase", "")), str(record.get("stage", "")))
				var stage := "%s · %s" % [record.get("phase", ""), record.get("stage", "")]
				if stage != last_stage:
					last_stage = stage
					technical("%s (%d%%)" % [stage, int(progress.value * 100)])
					print("Map generator: %s (%d%%)" % [stage, int(progress.value * 100)])
			"download":
				var url := str(record.get("url", ""))
				technical(url)
				status.text = tr("Downloading terrain…") if record.get("source") == "terrain" else tr("Downloading OpenStreetMap data from %s…") % url.get_slice("/", 2)
				print("Map generator: downloading from %s" % url)
				if record.has("query_url"):
					print("  to check by hand, open: %s" % record["query_url"])
			"source":
				status.text = tr("Extracting local map data…")
				technical(str(record.get("name", "")))
			"warning":
				technical(str(record.get("message", "")))
				status.text = tr("Server busy. Trying another source…")
				print("Map generator: %s" % record.get("message", ""))
			"result":
				if active_action != "generate":
					data_result(record)
					continue
				finished = true
				pid = -1
				progress.value = 1.0
				status.text = tr("Done: %s — loading…") % str(record.get("id", ""))
				generated.emit.call_deferred(str(record.get("id", "")))
			"error":
				var message := str(record.get("message", record.get("code", "")))
				printerr("Map generator failed: %s (log: %s.log)" % [message, events_path])
				technical(message)
				had_error = record.get("code", "") != "cancelled"
				fail(error_text(message, str(record.get("code", ""))) if had_error else tr("Generation cancelled"))
	lines_seen = lines.size()

## Network failures suggest the connection; anything else (e.g. no drivable roads in the
## area) suggests another area. The raw message stays in the technical details.
func error_text(message: String, code: String = "") -> String:
	if code == "sumo":
		return tr("SUMO could not run. Repair the installation; see the saved log.")
	if code == "offline_missing":
		return tr("Local data is missing or damaged. Prepare this area while online.")
	if code == "source_invalid":
		return tr("The data is incomplete or does not cover this area. Check the package or refresh.")
	if code == "no_roads":
		return tr("Could not build this area. Move it or make it larger, then retry.")
	var lower := message.to_lower()
	if "download" in lower or "urlopen" in lower or "http" in lower or "timed out" in lower:
		return tr("Could not build the map. Check your connection and retry.")
	return tr("Could not finish. See the saved log in Technical details.")

func choose_pbf() -> void:
	var dialog := FileDialog.new()
	dialog.access = FileDialog.ACCESS_FILESYSTEM
	dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILE
	dialog.filters = PackedStringArray(["*.pbf ; OSM PBF"])
	add_child(dialog)
	dialog.file_selected.connect(func(path):
		import_path = path
		var declaration := ConfirmationDialog.new()
		declaration.title = tr("Declare package coverage")
		declaration.dialog_text = tr("Enter the coverage guaranteed by the provider (west south east north). This is not inferred from the file name.")
		import_bounds = LineEdit.new()
		import_bounds.placeholder_text = "west south east north"
		declaration.add_child(import_bounds)
		add_child(declaration)
		declaration.confirmed.connect(func(): start_data_action("import"); declaration.queue_free())
		declaration.canceled.connect(declaration.queue_free)
		declaration.popup_centered(Vector2i(620, 230))
		dialog.queue_free())
	dialog.canceled.connect(dialog.queue_free)
	dialog.popup_centered_ratio(0.7)

func data_result(record: Dictionary) -> void:
	fail(tr("Local data updated"))
	had_error = false
	match active_action:
		"status":
			readiness.text = tr("OSM: %s · Terrain: %s") % [tr("ready") if record.get("osm_ready") else tr("missing"), tr("ready") if record.get("terrain_ready") else tr("missing")]
			var selected_package := ""
			if local_package.selected > 0: selected_package = str(local_package.get_item_metadata(local_package.selected))
			local_package.clear()
			local_package.add_item(tr("Choose local package automatically"))
			for package in record.get("covering_packages", []):
				local_package.add_item(str(package["name"]))
				var index := local_package.item_count - 1
				local_package.set_item_metadata(index, package["id"])
				if str(package["id"]) == selected_package: local_package.select(index)
			saved_area.clear()
			saved_area.add_item(tr("Saved offline areas"))
			for area in record.get("areas", []):
				saved_area.add_item(str(area["name"]))
				saved_area.set_item_metadata(saved_area.item_count - 1, area)
			status.text = tr("Select an area, then Generate")
		"suggest":
			package_offer = record
			if record.get("bytes") != null:
				download_package_button.text = tr("Download %s (%.1f MB)") % [record["name"], float(record["bytes"])/1000000.0]
				download_package_button.visible = true
				status.text = tr("Package found. Download only if you need it.")
			else:
				status.text = tr("Package size unavailable. Try again later.")
		"prepare":
			refresh_source.button_pressed = false
			readiness.text = tr("OSM: ready · Terrain: ready")
			source_check_at = Time.get_ticks_msec() + 700
		_:
			source_check_at = Time.get_ticks_msec() + 700

static func stage_text(phase: String, stage: String) -> String:
	if STAGE_TEXT.has(stage):
		return TranslationServer.translate(STAGE_TEXT[stage])
	return TranslationServer.translate({"build": "Building roads and scenery…",
		"export": "Preparing the map to drive…", "install": "Installing the map…"}.get(phase, "Working…"))

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
