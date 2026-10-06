extends Node3D
## Builds one piece of the district (a tile from tools/prepare.py, or the signals from the
## index). Heights are final in the data; the only offsets added here are paint
## (MARK_LIFT) and curbs (CURB). world_stream.gd runs it on worker threads: nothing here
## touches the scene tree above this node, and collisions are created later on the main
## thread (add_collisions).

const MARK_LIFT := 0.025
const CURB := 0.15
const BRIDGE_DEPTH := 1.2
const CHUNK := 250.0
const COLLIDE := {"road": 1, "dirt": 1, "gravel": 1, "farmland": 2, "garden": 2, "orchard": 2, "yard": 2, "fence": 4, "ground": 2, "green": 2, "wood": 2, "parking": 2, "building": 4, "bridge": 4, "sidewalk": 8}
## Tyre surface for GEVP wheels (Wheel reads the collider's first group).
const SURFACE := {"road": "Road", "dirt": "Dirt", "gravel": "Dirt", "farmland": "Dirt", "garden": "Dirt", "orchard": "Grass", "yard": "Dirt", "parking": "Road", "sidewalk": "Road", "bridge": "Road", "building": "Road", "ground": "Dirt", "green": "Grass", "wood": "Grass"}
const Materials = preload("res://scripts/materials.gd")
const VisualTile = preload("res://visuals/tile.gd")

static var _mats: Dictionary

var data: Dictionary
var buckets: Dictionary = {}
var pending_collisions: Array = []
var signal_heads: Array = []
var mats: Dictionary = {}
## When set, whole polylines go to the chunk of this point: no collision seams inside a strip.
var chunk_anchor = null

func vec(p: Array) -> Vector3:
	return Vector3(p[0], p[1], p[2])

func surface(kind: String, center: Vector3) -> SurfaceTool:
	if chunk_anchor != null:
		center = chunk_anchor
	var key := "%s:%d:%d" % [kind, floori(center.x / CHUNK), floori(center.z / CHUNK)]
	if not buckets.has(key):
		var st := SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		buckets[key] = {"st": st, "kind": kind}
	return buckets[key].st

## Adds one triangle. Flat surfaces are wound to face up; walls keep the given order.
func tri(a: Vector3, b: Vector3, c: Vector3, kind: String, facing_up := true, uv := Vector2.INF, color := Color.WHITE) -> void:
	# Rounded roof ridges can leave zero-area gable faces. Do not hand Jolt a
	# chunk containing only degenerate triangles.
	if (b-a).cross(c-a).length_squared() < 0.00000004:
		return
	if facing_up and (b - a).cross(c - a).y > 0:
		var t := b
		b = c
		c = t
	var st := surface(kind, (a + b + c) / 3.0)
	for v in [a, b, c]:
		st.set_color(color)
		st.set_uv(Vector2(v.x, v.z) if uv == Vector2.INF else uv)
		st.add_vertex(v)

func wall(a: Vector3, b: Vector3, bottom: float, top: float, kind: String, color := Color.WHITE) -> void:
	var st := surface(kind, (a + b) * 0.5)
	var run := Vector2(a.x, a.z).distance_to(Vector2(b.x, b.z))
	var quad := [Vector3(a.x, a.y + bottom, a.z), Vector3(b.x, b.y + bottom, b.z), Vector3(b.x, b.y + top, b.z), Vector3(a.x, a.y + top, a.z)]
	var uvs := [Vector2(0, bottom), Vector2(run, bottom), Vector2(run, top), Vector2(0, top)]
	for i in [0, 1, 2, 0, 2, 3]:
		st.set_color(color)
		st.set_uv(uvs[i])
		st.add_vertex(quad[i])

## Left/right borders of a polyline ribbon with mitred joints (no wedges on bends).
func borders(points: Array, half: float) -> Array:
	var n := points.size()
	var left: Array[Vector3] = []
	var right: Array[Vector3] = []
	for i in range(n):
		var p := vec(points[i])
		var prev := vec(points[maxi(i - 1, 0)])
		var next := vec(points[mini(i + 1, n - 1)])
		var d0 := Vector2(p.x - prev.x, p.z - prev.z).normalized() if i > 0 else Vector2.ZERO
		var d1 := Vector2(next.x - p.x, next.z - p.z).normalized() if i < n - 1 else Vector2.ZERO
		var dir := d0 + d1
		if dir.length() < 1e-5:
			dir = d1 if d1 != Vector2.ZERO else d0
		dir = dir.normalized()
		var perp := Vector2(-dir.y, dir.x)
		var ref := Vector2(-d0.y, d0.x) if d0 != Vector2.ZERO else Vector2(-d1.y, d1.x)
		var scale := 1.0 / maxf(0.5, absf(perp.dot(ref)))
		var off := Vector3(perp.x, 0, perp.y) * half * scale
		left.append(p - off)
		right.append(p + off)
	return [left, right]

func ribbon(points: Array, width: float, lift: float, kind: String) -> Array:
	if points.size() < 2:
		return [[], []]
	var sides := borders(points, width * 0.5)
	chunk_anchor = vec(points[0])
	var l: Array = sides[0]
	var r: Array = sides[1]
	var up := Vector3.UP * lift
	for i in range(points.size() - 1):
		tri(l[i] + up, r[i] + up, r[i + 1] + up, kind)
		tri(l[i] + up, r[i + 1] + up, l[i + 1] + up, kind)
	chunk_anchor = null
	return sides

## Polyline lengthened at both ends so consecutive strips overlap instead of just touching.
func extended(points: Array, by: float) -> Array:
	if points.size() < 2:
		return points
	var out := points.duplicate()
	var a := vec(points[0])
	var b := vec(points[1])
	var d := (a - b).normalized() * by
	out[0] = [a.x + d.x, a.y + d.y, a.z + d.z]
	var y := vec(points[-2])
	var z := vec(points[-1])
	var e := (z - y).normalized() * by
	out[-1] = [z.x + e.x, z.y + e.y, z.z + e.z]
	return out

## Sub-polylines of `points` for a dash pattern [on, off] (continuous along the line).
func dashes(points: Array, pattern: Array) -> Array:
	var out: Array = []
	if pattern.is_empty():
		return [points]
	var on := float(pattern[0])
	var period := on + float(pattern[1])
	var travelled := 0.0
	var current: Array = []
	for i in range(points.size() - 1):
		var a := vec(points[i])
		var b := vec(points[i + 1])
		var length := Vector2(b.x - a.x, b.z - a.z).length()
		var s := 0.0
		while s < length:
			var phase := fposmod(travelled + s, period)
			var drawing := phase < on
			var boundary := (on - phase) if drawing else (period - phase)
			var step := minf(boundary, length - s)
			var p := a.lerp(b, s / length)
			var q := a.lerp(b, (s + step) / length)
			if drawing:
				if current.is_empty():
					current.append([p.x, p.y, p.z])
				current.append([q.x, q.y, q.z])
			elif not current.is_empty():
				out.append(current)
				current = []
			s += maxf(step, 1e-4)
		travelled += length
	if current.size() >= 2:
		out.append(current)
	return out

## Materials and visual-pack meshes are shared by all tiles; create them on the main thread first.
static func shared() -> Dictionary:
	if _mats.is_empty():
		VisualTile.init()
		_mats = Materials.make()
	return _mats

## level "full": everything; "lod": ground, cover, roads, junctions and buildings only
## (far tiles). collide: create trimesh collisions now, else queue them for add_collisions().
func build(source: Dictionary, level := "full", collide := true) -> void:
	data = source
	mats = shared().duplicate()
	var full := level == "full"
	for t in data.get("ground", []):
		tri(vec(t[0]), vec(t[1]), vec(t[2]), "ground")
	for area in data.get("greens", []):
		for t in area.triangles:
			tri(vec(t[0]), vec(t[1]), vec(t[2]), area.kind)
	for t in data.get("parking", []):
		tri(vec(t[0]), vec(t[1]), vec(t[2]), "parking")
	for path in data.get("paths", []) if full else []:
		ribbon(path.points, path.width, 0.0, "path")
	for strip in data.get("road_strips", []):
		var sides: Array
		if strip.has("triangles"):
			for t in strip.triangles:
				tri(vec(t[0]), vec(t[1]), vec(t[2]), str(strip.get("surface", "road")))
			sides = borders(strip.points, strip.width * 0.5)
		else:
			sides = ribbon(extended(strip.points, 0.25), strip.width, 0.0, str(strip.get("surface", "road")))
		if strip.bridge and not strip.internal:
			build_deck_sides(sides)
	for junction in data.get("junctions", []):
		for t in junction.triangles:
			tri(vec(t[0]), vec(t[1]), vec(t[2]), str(junction.get("surface", "road")))
	for mark in data.get("markings", []) if full else []:
		for piece in dashes(mark.points, mark.dash):
			ribbon(piece, mark.width, MARK_LIFT, "mark")
	for walk in data.get("sidewalks", []) if full else []:
		var sides := ribbon(walk.points, walk.width, CURB, "sidewalk")
		for side in sides:
			for i in range(side.size() - 1):
				wall(side[i], side[i + 1], 0.0, CURB, "curb")
	for area in data.get("walkingareas", []) if full else []:
		for t in area.triangles:
			tri(vec(t[0]) + Vector3.UP * CURB, vec(t[1]) + Vector3.UP * CURB, vec(t[2]) + Vector3.UP * CURB, "sidewalk")
		for ring in area.rings:
			for i in range(ring.size()):
				wall(vec(ring[i]), vec(ring[(i + 1) % ring.size()]), 0.0, CURB, "curb")
	for building in data.get("buildings", []):
		build_building(building)
	for fence in data.get("fences", []) if full else []:
		var sides := borders(fence.points, 0.07)
		for side in sides:
			for i in range(side.size()-1):
				wall(side[i], side[i+1], -0.1, float(fence.height), "fence")
				wall(side[i+1], side[i], -0.1, float(fence.height), "fence")
	commit(collide)
	var visual := VisualTile.new()
	visual.name = "KyivVisuals"
	add_child(visual)
	visual.build(data, level)
	if data.has("signals"):
		build_signals()

func build_deck_sides(sides: Array) -> void:
	for side in sides:
		for i in range(side.size() - 1):
			wall(side[i], side[i + 1], -BRIDGE_DEPTH, 0.0, "bridge")
	var l: Array = sides[0]
	var r: Array = sides[1]
	var down := Vector3.DOWN * BRIDGE_DEPTH
	for i in range(l.size() - 1):
		tri(l[i] + down, r[i] + down, r[i + 1] + down, "bridge", false)
		tri(l[i] + down, r[i + 1] + down, l[i + 1] + down, "bridge", false)

func build_building(building: Dictionary) -> void:
	var facade_kind := "facade"
	if building.has("local_style"):
		var style: Dictionary = building.local_style
		var shade: String = str(style.get("color") if style.get("color") != null else "#b5b2aa")
		var material_id := ["plaster", "brick", "concrete", "glass", "metal", "stone"].find(str(style.material))
		facade_kind = "dna_facade_" + str(style.architecture) + "_" + str(material_id) + "_" + shade.substr(1)
		if not mats.has(facade_kind):
			var material: ShaderMaterial = mats.facade.duplicate()
			material.set_shader_parameter("dna_enabled", true)
			material.set_shader_parameter("dna_color", Color(shade))
			material.set_shader_parameter("dna_architecture", ["historic", "brick", "panel", "modern", "industrial"].find(style.architecture))
			material.set_shader_parameter("dna_material", material_id)
			mats[facade_kind] = material
	var pts: Array = building.points.duplicate()
	var area := 0.0
	for i in range(pts.size()):
		area += pts[i][0] * pts[(i + 1) % pts.size()][2] - pts[(i + 1) % pts.size()][0] * pts[i][2]
	if area < 0.0:
		pts.reverse()
	var floor_y := INF
	for p in pts:
		floor_y = minf(floor_y, p[1])
	var base := float(building.get("base", 0.0))
	var bottom := floor_y + base if base > 0.0 else floor_y - 1.0
	floor_y = float(building.get("floor_height", floor_y))
	var top := floor_y + float(building.get("wall_height", building.height))
	var poly := PackedVector2Array()
	for p in pts:
		poly.append(Vector2(p[0], p[2]))
	var indices := Geometry2D.triangulate_polygon(poly)
	for t in building.get("roof_triangles", []):
		tri(vec(t[0]), vec(t[1]), vec(t[2]), str(building.get("roof_material", "roof")))
	for t in building.get("roof_gables", []):
		tri(vec(t[0]), vec(t[1]), vec(t[2]), str(building.get("roof_material", "roof")), false)
		tri(vec(t[2]), vec(t[1]), vec(t[0]), str(building.get("roof_material", "roof")), false)
	for i in range(0, indices.size(), 3) if not building.has("roof_triangles") else []:
		var a := Vector3(poly[indices[i]].x, top, poly[indices[i]].y)
		var b := Vector3(poly[indices[i + 1]].x, top, poly[indices[i + 1]].y)
		var c := Vector3(poly[indices[i + 2]].x, top, poly[indices[i + 2]].y)
		tri(a, b, c, "roof")
		if base > 0.0:
			tri(Vector3(a.x, bottom, a.z), Vector3(b.x, bottom, b.z), Vector3(c.x, bottom, c.z), "facade", false, Vector2(0, -1))
	# COLOR.r: tint from the OSM id; COLOR.g: shop ground floor; COLOR.b: facade family / 5 (facade.gdshader).
	var tint := Color(fposmod(float(hash(str(building.id))) / 7919.0, 1.0), 1.0 if building.get("ground_floor", "") == "shop" else 0.0, float(VisualTile.family(building)) / 5.0)
	for i in range(pts.size()):
		var j := (i + 1) % pts.size()
		var a := Vector3(pts[i][0], floor_y, pts[i][2])
		var b := Vector3(pts[j][0], floor_y, pts[j][2])
		wall(a, b, bottom - floor_y, top - floor_y, facade_kind, tint)

func commit(collide := true) -> void:
	for key in buckets:
		var item: Dictionary = buckets[key]
		var st: SurfaceTool = item.st
		st.generate_normals()
		st.generate_tangents()
		var inst := MeshInstance3D.new()
		inst.mesh = st.commit()
		inst.material_override = mats[item.kind]
		# Wide ranges: the spectator camera looks at the whole district from kilometres up.
		inst.visibility_range_end = 5000 if item.kind in ["facade", "roof", "roof_tile", "roof_metal"] else (500 if item.kind in ["mark", "path", "curb", "fence"] else 9000)
		# Flat cover cannot shade anything visible; skipping it keeps the shadow passes cheap.
		if item.kind in ["mark", "path", "ground", "green", "wood", "water", "parking", "road", "sidewalk", "curb", "dirt", "gravel", "farmland", "garden", "orchard", "yard"]:
			inst.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(inst)
		var layer_kind: String = "building" if item.kind in ["facade", "roof", "roof_tile", "roof_metal"] else item.kind
		if str(item.kind).begins_with("dna_facade_"):
			layer_kind = "building"
			inst.visibility_range_end = 5000
		if COLLIDE.has(layer_kind):
			pending_collisions.append([inst, layer_kind])
	buckets.clear()
	if collide:
		add_collisions(INF)

## Trimesh collisions for the built meshes, within a time budget (ms). True when done.
func add_collisions(budget_ms: float) -> bool:
	var start := Time.get_ticks_usec()
	while not pending_collisions.is_empty():
		var item: Array = pending_collisions.pop_back()
		var inst: MeshInstance3D = item[0]
		inst.create_trimesh_collision()
		var body: StaticBody3D = inst.get_child(0)
		body.collision_layer = COLLIDE[item[1]]
		body.add_to_group(SURFACE.get(item[1], "Road"))
		if (Time.get_ticks_usec() - start) / 1000.0 > budget_ms:
			break
	return pending_collisions.is_empty()

## One pole per signalised approach at the right edge, heads over each lane on an arm.
func build_signals() -> void:
	var approaches: Dictionary = {}
	for sig in data.signals:
		var edge: String = sig.lane.rsplit("_", true, 1)[0]
		if not approaches.has(edge):
			approaches[edge] = {}
		if not approaches[edge].has(sig.lane):
			approaches[edge][sig.lane] = sig
	var pole_mat: Material = mats.pole
	for edge in approaches:
		var lanes: Array = approaches[edge].values()
		lanes.sort_custom(func(a, b): return int(a.lane.rsplit("_", true, 1)[1]) < int(b.lane.rsplit("_", true, 1)[1]))
		var first: Dictionary = lanes[0]
		var h := deg_to_rad(float(first.heading))
		var right := Vector3(cos(h), 0, sin(h))
		var base := vec(first.position) + right * (float(first.width) * 0.5 + 0.8)
		var span := 0.0
		for sig in lanes:
			span = maxf(span, (vec(sig.position) - base).dot(-right))
		var pole := Node3D.new()
		pole.position = base
		pole.rotation.y = -h
		add_child(pole)
		box_mesh(pole, Vector3(0.16, 6.0, 0.16), Vector3(0, 3.0, 0), pole_mat)
		box_mesh(pole, Vector3(span + 0.6, 0.12, 0.12), Vector3(-(span + 0.6) * 0.5, 5.9, 0), pole_mat)
		for sig in lanes:
			var offset := (vec(sig.position) - base).dot(-right)
			var head := Node3D.new()
			head.position = Vector3(-offset, 5.2, 0.1)
			pole.add_child(head)
			box_mesh(head, Vector3(0.36, 1.0, 0.25), Vector3.ZERO, mats.signal_housing)
			var lamps: Array = []
			for k in range(3):
				var m := StandardMaterial3D.new()
				m.albedo_color = Color("202020")
				m.emission_enabled = true
				m.emission = Color.BLACK
				var lamp := MeshInstance3D.new()
				var sphere := SphereMesh.new()
				sphere.radius = 0.1
				sphere.height = 0.12
				lamp.mesh = sphere
				lamp.material_override = m
				lamp.position = Vector3(0, 0.3 - k * 0.3, 0.13)
				head.add_child(lamp)
				lamps.append(m)
			signal_heads.append({"tls": sig.tls, "index": int(sig.index), "lamps": lamps})

func box_mesh(parent: Node3D, size: Vector3, pos: Vector3, mat: Material) -> MeshInstance3D:
	var m := MeshInstance3D.new()
	var cube := BoxMesh.new()
	cube.size = size
	m.mesh = cube
	m.material_override = mat
	m.position = pos
	parent.add_child(m)
	return m

const LAMP_ON := [Color("ff3b30"), Color("ffc83a"), Color("3ddc84")]

func update_signals(states: Dictionary) -> void:
	for head in signal_heads:
		if not states.has(head.tls) or head.index >= states[head.tls].length():
			continue
		var code: String = states[head.tls][head.index]
		var lit := 2 if code in ["g", "G"] else (1 if code in ["y", "Y"] else 0)
		for k in range(3):
			var m: StandardMaterial3D = head.lamps[k]
			m.emission = LAMP_ON[k] * (3.0 if k == lit else 0.0)
			m.albedo_color = LAMP_ON[k] if k == lit else Color("202020")
