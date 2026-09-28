extends Node
## Build-up timelapse and flythrough for presentations: `--timelapse` (with the traffic
## bridge running). The map is built as usual; then every layer is hidden and revealed again
## in the order the generator produces it — terrain, land cover, the SUMO lane network, road
## surfaces, markings, sidewalks, buildings, dressing, signals, traffic — as a wave from the
## map centre, while the camera flies an aerial orbit, drops to a signalised junction, flies
## down the main street at street level and climbs out over the whole map.
## Each frame is saved to logs/timelapse/frame_NNNN.jpg at a fixed 15 fps of animation time:
##   ffmpeg -framerate 15 -i logs/timelapse/frame_%04d.jpg -c:v libx264 -pix_fmt yuv420p out.mp4
## Nothing here changes the game itself.
## Options: --timelapse-near=X,Z (centre, default: middle of the map), --timelapse-title=TEXT,
## --timelapse-outro=TEXT (last caption).

const World = preload("res://scripts/world.gd")
const Palette = preload("res://visuals/palette.gd")
const FPS := 15.0
const ANIM := 0.7                 # seconds one piece takes to move into place
const LENGTH := 42.0
const STAGES := [
	# [key, list label, start, end, motion: >0 slide up from this many metres below, <0 grow in height]
	["ground", "Terrain", 0.4, 2.4, 20.0],
	["cover", "Land cover", 2.2, 4.0, 3.0],
	["network", "SUMO lane network", 4.0, 6.8, 0.0],
	["roads", "Road surfaces", 6.4, 8.8, 3.0],
	["marks", "Markings", 9.6, 11.4, 0.4],
	["walks", "Curbs and sidewalks", 10.4, 12.2, 0.5],
	["buildings", "Buildings", 12.4, 15.8, -1.0],
	["dressing", "Trees and street furniture", 15.6, 17.6, 30.0],
	["signals", "Traffic lights and signs", 17.4, 19.2, 8.0],
	["traffic", "Traffic simulation", 19.4, LENGTH, 0.0],
]
## The lane overlay leaves again, as a wave, while the markings come in.
const NETWORK_OUT := [9.4, 11.6]
const KIND_STAGE := {"ground": "ground", "road": "roads", "parking": "roads", "bridge": "roads",
	"mark": "marks", "sidewalk": "walks", "curb": "walks", "path": "walks",
	"facade": "buildings", "shopfront": "buildings", "roof": "buildings", "roof_tile": "buildings", "roof_metal": "buildings",
	"fence": "dressing"}

var main: Node3D
var center := Vector3.ZERO        # middle of the map (the reveal wave starts here)
var junction := Vector3.ZERO      # signalised junction next to the main street
var avenue := Vector3.FORWARD     # direction of the main street through the centre
var fly_from := Vector3.ZERO
var fly_to := Vector3.ZERO
var extent := 1000.0              # map size, metres
var keys: Array = []              # camera keyframes [t, focus, heading, tilt, distance]
var pieces: Array = []            # {"node", "start", "end", "motion", "base"}
var stats := {}
var clock := 0.0
var frame := 0
var recording := false
var caption: Label
var numbers: Label
var stage_labels: Array = []
var out_dir: String
var saves: Array = []

func _ready() -> void:
	main.hud.visible = false
	main.player.visible = false
	main.traffic.visible = false
	main.set_spectating(true)
	main.free_cam.active = false
	measure()
	main.capture_focus = center
	main.world.focus = center
	out_dir = ProjectSettings.globalize_path("res://../logs/timelapse")
	DirAccess.make_dir_recursive_absolute(out_dir)
	for f in DirAccess.get_files_at(out_dir):
		DirAccess.remove_absolute(out_dir + "/" + f)
	build_keys()
	build_overlay()
	aim(0.0)
	await prepare()
	count_tiles()
	collect()
	build_network()
	Engine.max_fps = int(FPS)
	recording = true
	print("TIMELAPSE recording %d pieces, centre %s, junction %s, avenue %s" % [pieces.size(), center, junction, avenue])

func arg(name: String, fallback: String) -> String:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--timelapse-%s=" % name):
			return a.split("=", true, 1)[1]
	return fallback

func v3(p: Array) -> Vector3:
	return Vector3(p[0], p[1], p[2])

## Map centre, main-street direction (the dominant lane direction around the centre),
## the street through the centre and the signalised junction on it.
func measure() -> void:
	# Bounds of the road network: tiles also hold far-reaching multipolygons (rivers, parks).
	var lo := Vector2(INF, INF)
	var hi := -lo
	for lane in main.data.lanes:
		for q in lane.points:
			lo = Vector2(minf(lo.x, q[0]), minf(lo.y, q[2]))
			hi = Vector2(maxf(hi.x, q[0]), maxf(hi.y, q[2]))
	extent = maxf(hi.x - lo.x, hi.y - lo.y)
	center = Vector3((lo.x + hi.x) * 0.5, 0, (lo.y + hi.y) * 0.5)
	var near := arg("near", "")
	if near != "":
		var xz := near.split(",")
		center = Vector3(float(xz[0]), 0, float(xz[1]))
	# Dominant direction (mod 180°), weighted by lane length and speed.
	var bins := PackedFloat32Array()
	bins.resize(36)
	var heights := []
	for lane in main.data.lanes:
		if lane.internal:
			continue
		var pts: Array = lane.points
		for i in range(pts.size() - 1):
			var a := v3(pts[i])
			var b := v3(pts[i + 1])
			if Vector2(a.x - center.x, a.z - center.z).length() > 700.0:
				continue
			heights.append(a.y)
			var d := b - a
			var ang := fposmod(atan2(d.z, d.x), PI)
			bins[int(ang / PI * 36.0) % 36] += Vector2(d.x, d.z).length() * float(lane.speed)
	var best := 0
	for i in range(36):
		if bins[i] > bins[best]:
			best = i
	var ang := (best + 0.5) / 36.0 * PI
	avenue = Vector3(cos(ang), 0, sin(ang))
	heights.sort()
	center.y = heights[heights.size() / 2] if not heights.is_empty() else 0.0
	# The fastest aligned lane closest to the centre is the street to fly down.
	var street_point := center
	var street_dir := avenue
	var score := INF
	for lane in main.data.lanes:
		if lane.internal or lane.service:
			continue
		var pts: Array = lane.points
		var a := v3(pts[0])
		var b := v3(pts[pts.size() - 1])
		var d := b - a
		if d.length() < 60.0 or absf(d.normalized().dot(avenue)) < 0.97:
			continue
		var mid := (a + b) * 0.5
		var s := Vector2(mid.x - center.x, mid.z - center.z).length() / maxf(float(lane.speed), 1.0)
		if s < score:
			score = s
			street_point = mid
			street_dir = d.normalized() * signf(d.dot(avenue))
	# The histogram is 5° coarse: fly along the chosen lane itself.
	avenue = street_dir
	var along := (center - street_point).dot(avenue)
	var on_street := street_point + avenue * along
	fly_from = on_street - avenue * 280.0
	fly_to = on_street + avenue * 280.0
	# --timelapse-fly=X1,Z1,X2,Z2: an explicit street-level flight (e.g. down an avenue).
	var fly := arg("fly", "")
	if fly != "":
		var f := fly.split(",")
		fly_from = Vector3(float(f[0]), center.y, float(f[1]))
		fly_to = Vector3(float(f[2]), center.y, float(f[3]))
		avenue = (fly_to - fly_from).normalized()
	# Signalised junction nearest to the start of the flight.
	var best_sig: Dictionary = {}
	var best_d := INF
	for sig in main.data.get("signals", []):
		var dd := Vector2(sig.position[0] - fly_from.x, sig.position[2] - fly_from.z).length()
		if dd < best_d:
			best_d = dd
			best_sig = sig
	junction = fly_from
	if not best_sig.is_empty():
		var sum := Vector3.ZERO
		var n := 0
		for sig in main.data.signals:
			if sig.tls == best_sig.tls:
				sum += v3(sig.position)
				n += 1
		junction = sum / n

func heading_along(dir: Vector3) -> float:
	return atan2(-dir.x, -dir.z)

## Camera keyframes: aerial orbit → close for the paint → wide low for the skyline →
## junction → street-level flight down the avenue → climb out over the map.
func build_keys() -> void:
	var h := rad_to_deg(heading_along(avenue))
	var d0 := clampf(extent * 0.45, 500.0, 2000.0)
	var sky := clampf(extent * 0.25, 350.0, 1100.0)
	keys = [
		[0.0, center, h - 70, -52, d0],
		[6.0, center, h - 58, -48, d0 * 0.8],
		[10.5, center, h - 42, -42, 470.0],
		[12.5, center, h - 32, -36, 430.0],
		[15.6, center, h - 16, -18, sky],
		[18.6, center, h - 6, -26, sky * 0.75],
		# Straight down the street axis and steep: in a dense grid anything else is inside a block.
		[22.0, junction, h, -58, 190.0],
		[25.0, junction, h, -50, 140.0],
		[27.6, fly_from, h, -15, 66.0],
		[35.0, fly_to, h, -15, 66.0],
		[37.0, fly_to, h, -45, 320.0],
		[39.6, fly_to.lerp(center, 0.5), h + 45, -34, d0 * 0.6],
		[LENGTH, center, h + 80, -32, d0 * 0.75],
	]
	var last := 0.0
	for k in keys:
		# Unwrap headings so every segment turns the short way.
		k[2] = last + wrapf(k[2] - last, -180.0, 180.0)
		last = k[2]

## Monotone cubic (Fritsch–Carlson style): never overshoots a keyframe, so a held heading
## stays held and the street-level flight cannot swing sideways into the buildings.
func mono(pre: float, a: float, b: float, post: float, ta: float, tb: float, tpre: float, tpost: float, w: float) -> float:
	var span := tb - ta
	var ma := 0.0 if (a - pre) * (b - a) <= 0.0 else (b - pre) / (tb - tpre)
	var mb := 0.0 if (b - a) * (post - b) <= 0.0 else (post - a) / (tpost - ta)
	var w2 := w * w
	var w3 := w2 * w
	return (2 * w3 - 3 * w2 + 1) * a + (w3 - 2 * w2 + w) * span * ma + (-2 * w3 + 3 * w2) * b + (w3 - w2) * span * mb

func camera_at(t: float) -> Array:
	var i := 0
	while i < keys.size() - 2 and t > keys[i + 1][0]:
		i += 1
	var a: Array = keys[i]
	var b: Array = keys[i + 1]
	var pre: Array = keys[maxi(i - 1, 0)]
	var post: Array = keys[mini(i + 2, keys.size() - 1)]
	var w := clampf((t - a[0]) / (b[0] - a[0]), 0.0, 1.0)
	var tpre: float = pre[0] if i > 0 else a[0] - 1.0
	var tpost: float = post[0] if i + 2 < keys.size() else b[0] + 1.0
	var values := []
	for c in range(1, 5):
		var pick := func(k: Array, axis: int) -> float:
			if c == 1:
				return k[1][axis]
			return log(k[4]) if c == 4 else float(k[c])
		var out := []
		for axis in (range(3) if c == 1 else [0]):
			out.append(mono(pick.call(pre, axis), pick.call(a, axis), pick.call(b, axis), pick.call(post, axis), a[0], b[0], tpre, tpost, w))
		values.append(Vector3(out[0], out[1], out[2]) if c == 1 else out[0])
	values[3] = exp(values[3])
	return values

func aim(t: float) -> void:
	var c := camera_at(t)
	var cam: Camera3D = main.free_cam
	cam.focus = c[0]
	cam.heading = deg_to_rad(c[1])
	cam.tilt = deg_to_rad(c[2])
	cam.distance = c[3]
	cam.target_distance = c[3]
	cam.place()
	cam.current = true

## Wait for every tile at its final level, the bridge and some traffic on the streets.
func prepare() -> void:
	var waited := 0.0
	while waited < 300.0:
		await get_tree().process_frame
		waited += get_process_delta_time()
		aim(0.0)
		var cars: int = main.traffic.count()
		if main.world.pending() == 0 and main.world.jobs.is_empty() and main.ready_bridge and waited > 8.0 and cars >= mini(main.density, 200):
			return
	push_warning("Timelapse: started without everything ready (bridge %s, %d cars)" % [main.ready_bridge, main.traffic.count()])

func count_tiles() -> void:
	var buildings := 0
	var trees := 0
	var tallest := 0.0
	for name in main.data.tiles:
		var tile = JSON.parse_string(FileAccess.get_file_as_string(main.world.folder + "tiles/" + name + ".json"))
		if not tile is Dictionary:
			continue
		buildings += tile.get("buildings", []).size()
		trees += tile.get("trees", []).size()
		for b in tile.get("buildings", []):
			tallest = maxf(tallest, float(b.get("wall_height", b.get("height", 0.0))))
	var lanes := 0
	var km := 0.0
	for lane in main.data.lanes:
		if lane.internal:
			continue
		lanes += 1
		var pts: Array = lane.points
		for i in range(pts.size() - 1):
			km += v3(pts[i]).distance_to(v3(pts[i + 1])) / 1000.0
	var junctions := {}
	for sig in main.data.get("signals", []):
		junctions[sig.tls] = true
	stats = {"buildings": buildings, "trees": trees, "tallest": tallest, "lanes": lanes, "km": km,
		"tls": junctions.size(), "heads": main.data.get("signals", []).size(), "area": extent / 1000.0}

func stage_window(key: String) -> Array:
	for s in STAGES:
		if s[0] == key:
			return s
	return STAGES[0]

func wave(d: float, from: float, to: float) -> float:
	var sweep := clampf(extent * 0.45, 600.0, 2000.0)
	return from + maxf(0.0, to - from - ANIM) * minf(1.0, d / sweep)

func add_piece(node: Node3D, key: String, at: Vector3) -> void:
	var s: Array = stage_window(key)
	var d := Vector2(at.x - center.x, at.z - center.z).length()
	var p := {"node": node, "start": wave(d, s[2], s[3]), "end": INF, "motion": s[4], "base": node.position.y}
	if key == "network":
		p.end = wave(d, NETWORK_OUT[0], NETWORK_OUT[1])
	pieces.append(p)

func collect() -> void:
	var kind_of := {}
	var mats: Dictionary = World.shared()
	for kind in mats:
		kind_of[mats[kind]] = kind
	kind_of[mats.facade] = "facade"
	for tile in main.world.get_children():
		if tile == main.world.signals_builder:
			for pole in tile.get_children():
				add_piece(pole, "signals", pole.position)
			continue
		if tile is MeshInstance3D or not tile is Node3D:
			continue          # the backdrop plane stays: the blank table the map is built on
		for child in tile.get_children():
			if child is MeshInstance3D:
				var kind: String = kind_of.get(child.material_override, "ground")
				add_piece(child, KIND_STAGE.get(kind, "cover"), child.get_aabb().get_center())
			elif child.name == "KyivVisuals":
				for mm in child.get_children():
					if mm is MultiMeshInstance3D:
						var key := "signals" if mm.multimesh.mesh == Palette.meshes.get("sign_plate") else "dressing"
						add_piece(mm, key, mm.multimesh.get_aabb().get_center())
	for p in pieces:
		p.node.visible = false

## The SUMO lanes as glowing ribbons, coloured by speed limit, one mesh per 250 m cell.
func build_network() -> void:
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.vertex_color_use_as_albedo = true
	var cells := {}
	var width := clampf(extent / 1800.0, 1.2, 3.0)
	for lane in main.data.lanes:
		var pts: Array = lane.points
		var color := speed_color(float(lane.speed))
		if lane.internal:
			color = color.lerp(Color.WHITE, 0.35)
		var first := v3(pts[0])
		var key := Vector2i(floori(first.x / 250.0), floori(first.z / 250.0))
		if not cells.has(key):
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			cells[key] = {"st": st, "at": first}
		var st: SurfaceTool = cells[key].st
		for i in range(pts.size() - 1):
			var a := v3(pts[i]) + Vector3.UP * 1.2
			var b := v3(pts[i + 1]) + Vector3.UP * 1.2
			var side := (b - a).cross(Vector3.UP).normalized() * width * 0.5
			if side == Vector3.ZERO:
				continue
			for v in [a - side, b - side, b + side, a - side, b + side, a + side]:
				st.set_color(color)
				st.add_vertex(v)
	for key in cells:
		var inst := MeshInstance3D.new()
		inst.mesh = cells[key].st.commit()
		inst.material_override = mat
		inst.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		inst.visible = false
		main.world.add_child(inst)
		add_piece(inst, "network", cells[key].at)

func speed_color(v: float) -> Color:
	var kmh := v * 3.6
	if kmh < 25.0:
		return Color("5aa9ff")
	if kmh < 45.0:
		return Color("3fe0c5")
	if kmh < 65.0:
		return Color("ffd23f")
	return Color("ff7a3d")

func styled(l: Label, size: int, color := Color.WHITE) -> Label:
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	l.add_theme_constant_override("outline_size", 7)
	return l

func build_overlay() -> void:
	var layer := CanvasLayer.new()
	layer.layer = 50
	add_child(layer)
	var title := styled(Label.new(), 26)
	title.text = arg("title", "TerraDrive  ·  %s  ·  generated from OpenStreetMap" % main.data.get("name", ""))
	title.position = Vector2(30, 22)
	layer.add_child(title)
	for i in range(STAGES.size()):
		var l := styled(Label.new(), 19)
		l.text = "%d  %s" % [i + 1, STAGES[i][1]]
		l.position = Vector2(30, 72 + i * 27)
		layer.add_child(l)
		stage_labels.append(l)
	caption = styled(Label.new(), 32)
	numbers = styled(Label.new(), 22, Color(1, 1, 1, 0.9))
	layer.add_child(caption)
	layer.add_child(numbers)

func stage_text(key: String) -> Array:
	match key:
		"ground": return ["Terrain from open elevation tiles", "%.0f × %.0f km" % [stats.area, stats.area]]
		"cover": return ["Land cover from OpenStreetMap", "water, parks, plazas, parking"]
		"network": return ["Road network: OSM → SUMO netconvert", "%d lanes · %.0f km · coloured by speed limit" % [stats.lanes, stats.km]]
		"roads": return ["Road surfaces, junctions and bridges", "meshed from the lane network"]
		"marks": return ["Lane markings", "derived from lanes and junction shapes"]
		"walks": return ["Curbs and sidewalks", ""]
		"buildings": return ["Buildings from OSM footprints", "%d buildings · heights from tags, up to %.0f m" % [stats.buildings, stats.tallest]]
		"dressing": return ["Trees and street furniture", "%d trees" % stats.trees]
		"signals": return ["Traffic lights", "%d signalised junctions · %d signal heads" % [stats.tls, stats.heads]]
	return ["Traffic: SUMO simulation", "%d vehicles · right of way · signal phases" % main.traffic.count()]

func _process(_delta: float) -> void:
	if not recording:
		return
	aim(clock)
	for p in pieces:
		if not is_instance_valid(p.node):
			continue
		var k := clampf((clock - p.start) / ANIM, 0.0, 1.0)
		p.node.visible = k > 0.0 and clock < p.end
		var eased := 1.0 - pow(1.0 - k, 3.0)
		if p.motion < 0.0:
			p.node.scale.y = maxf(0.001, eased)
		else:
			p.node.position.y = p.base - p.motion * (1.0 - eased)
	main.traffic.visible = clock >= stage_window("traffic")[2]
	var current := 0
	for i in range(STAGES.size()):
		if clock >= STAGES[i][2] - 0.3:
			current = i
	for i in range(stage_labels.size()):
		var c := Color("ffd23f") if i == current else (Color(1, 1, 1, 0.95) if i < current else Color(1, 1, 1, 0.4))
		stage_labels[i].add_theme_color_override("font_color", c)
	var text := stage_text(STAGES[current][0])
	if clock >= 26.8 and clock < 36.0:
		text = ["Street level: the world you drive in", "Jolt vehicle physics · SUMO traffic around you"]
	elif clock >= 36.0:
		text = [arg("outro", "Any place on Earth: M → New map in the game"), "%d vehicles in the simulation" % main.traffic.count()]
	caption.text = text[0]
	numbers.text = text[1]
	var h := get_viewport().get_visible_rect().size.y
	caption.position = Vector2(30, h - 104)
	numbers.position = Vector2(32, h - 60)
	clock += 1.0 / FPS
	await RenderingServer.frame_post_draw
	var image := get_viewport().get_texture().get_image()
	var path := "%s/frame_%04d.jpg" % [out_dir, frame]
	frame += 1
	saves.append(WorkerThreadPool.add_task(func(): image.save_jpg(path, 0.92)))
	if clock >= LENGTH:
		recording = false
		for id in saves:
			WorkerThreadPool.wait_for_task_completion(id)
		print("TIMELAPSE %d frames in %s" % [frame, out_dir])
		get_tree().quit()
