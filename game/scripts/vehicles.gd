extends RefCounted
## Vehicle models from config/vehicles.json. The Kenney Car Kit GLB (CC0, fetched by
## tools/fetch_assets.py) is used when present, rescaled to the configured real size; the
## procedural kit (visuals/vehicles.gd) is the fallback for a checkout without the pack.
## availability() follows the configured catalogue, not the presence of a fetched GLB.
## Instances get their own lamp materials so traffic can show brake lights and indicators.

const VisualVehicles = preload("res://visuals/vehicles.gd")
const CARS := "res://assets/cars/"
const CONFIG := "res://../config/vehicles.json"

static var _catalog: Dictionary
static var _templates: Dictionary = {}
## false: always build the procedural fallback (comparison and fallback checks).
static var use_glb := true

static func catalog() -> Dictionary:
	if _catalog.is_empty():
		_catalog = JSON.parse_string(FileAccess.get_file_as_string(ProjectSettings.globalize_path(CONFIG)))
	return _catalog

## A model is available when it is configured: template() builds every catalogue entry
## procedurally, so no fetched GLB is required. Unknown names are never available.
static func available(name: String) -> bool:
	return catalog().models.has(name)

static func traffic_models() -> Array:
	var out: Array = []
	for name in catalog().models:
		if available(name):
			out.append(name)
	return out

## Normalised template: {"root": Node3D, "size": Vector3, "tire_radius": float, "wheels": [4 × Vector3 pivots FL, FR, RL, RR]}
static func template(name: String) -> Dictionary:
	if _templates.has(name):
		return _templates[name]
	if not catalog().models.has(name):
		return {}
	var glb := ProjectSettings.globalize_path(CARS + name + ".glb")
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	if not use_glb or not FileAccess.file_exists(glb) or doc.append_from_file(glb, state) != OK:
		var generated := VisualVehicles.template(name, catalog().models[name])
		if not generated.is_empty():
			generated.lamps = lamp_spots(generated.root.get_node("body"), generated.size)
			_templates[name] = generated
		return generated
	var scene: Node3D = doc.generate_scene(state)
	var spec: Dictionary = catalog().models[name]
	var size := Vector3(spec.size[0], spec.size[1], spec.size[2])
	var body: MeshInstance3D = null
	var wheels: Dictionary = {}
	for child in scene.get_children():
		if child is MeshInstance3D:
			if child.name.begins_with("wheel"):
				wheels[String(child.name)] = child
			elif child.name == "body":
				body = child
	var root := Node3D.new()
	root.name = name
	# Body: original faces +Z; turn to -Z and stretch to the real size.
	var box := body.mesh.get_aabb()
	var lo := box.position + body.position
	var hi := box.end + body.position
	var scale := Vector3(size.x / (hi.x - lo.x), size.y / hi.y, size.z / (hi.z - lo.z))
	var body_node := MeshInstance3D.new()
	body_node.name = "body"
	body_node.mesh = body.mesh
	body_node.transform = Transform3D(Basis(Vector3.UP, PI).scaled(scale), Vector3(-body.position.x * scale.x, body.position.y * scale.y, -body.position.z * scale.z))
	root.add_child(body_node)
	var tire := float(spec.tire_radius)
	var pivots: Array = []
	for key in ["wheel-front-left", "wheel-front-right", "wheel-back-left", "wheel-back-right"]:
		var src: MeshInstance3D = wheels[key]
		var wbox := src.mesh.get_aabb()
		var radius := wbox.size.y * 0.5
		var s := tire / radius
		# Keep the original inset between tyre sidewall and body side.
		var outward := maxf(absf(wbox.position.x), absf(wbox.end.x))
		var inset := (hi.x - lo.x) * 0.5 - (absf(src.position.x) + outward)
		var x := size.x * 0.5 - inset - outward * s
		var side := -1.0 if src.position.x > 0.0 else 1.0     # +X in the model = left = -X after the turn
		var pivot := Node3D.new()
		pivot.name = key
		pivot.position = Vector3(side * x, tire, -src.position.z * scale.z)
		var mesh := MeshInstance3D.new()
		mesh.mesh = src.mesh
		mesh.transform = Transform3D(Basis(Vector3.UP, PI).scaled(Vector3.ONE * s), Vector3.ZERO)
		pivot.add_child(mesh)
		root.add_child(pivot)
		pivots.append(pivot.position)
	scene.free()
	_templates[name] = {"root": root, "size": size, "tire_radius": tire, "wheels": pivots,
		"lamps": lamp_spots(body_node, size)}
	return _templates[name]

## A fresh vehicle: {"root", "wheels": [FL, FR, RL, RR] Node3D, "lamps": {...}, "size", "tire_radius"}
static func instantiate(name: String) -> Dictionary:
	var t := template(name)
	if t.is_empty():
		return {}
	var root: Node3D = t.root.duplicate()
	var wheels: Array = []
	for key in ["wheel-front-left", "wheel-front-right", "wheel-back-left", "wheel-back-right"]:
		wheels.append(root.get_node(key))
	var lamps := {
		"brake": lamp_material(Color("ff2a1f")),
		"left": lamp_material(Color("ffa31a")),
		"right": lamp_material(Color("ffa31a")),
		"head": lamp_material(Color("fff6e0")),
	}
	for spot in t.lamps:
		add_lamp(root, spot.position, spot.size, lamps[spot.kind])
	lamps.head.emission_energy_multiplier = 0.4
	return {"root": root, "wheels": wheels, "lamps": lamps, "size": t.size, "tire_radius": t.tire_radius}

## Lamp boxes placed on the body's actual front and rear surface: a ray along Z through the
## body triangles at each lamp's x/y, moved inwards where a tapered corner makes it miss.
## Nominal catalogue ends are the last fallback. [{position, size, kind}] in vehicle space.
static func lamp_spots(body: MeshInstance3D, size: Vector3) -> Array:
	var faces := body.mesh.get_faces()
	for i in faces.size():
		faces[i] = body.transform * faces[i]
	var y := clampf(size.y * 0.45, 0.6, 1.1)
	var spots: Array = []
	for side in [-1.0, 1.0]:
		var x: float = side * (size.x * 0.5 - 0.22)
		var turn := "left" if side < 0 else "right"
		for item in [[Vector3(x, y, 1), Vector3(0.32, 0.12, 0.03), "brake"],
				[Vector3(x + side * 0.12, y + 0.1, 1), Vector3(0.08, 0.06, 0.03), turn],
				[Vector3(x + side * 0.12, y, -1), Vector3(0.08, 0.06, 0.03), turn],
				[Vector3(x, y, -1), Vector3(0.3, 0.1, 0.03), "head"]]:
			var p: Vector3 = item[0]
			var end := INF
			for shrink in [1.0, 0.85, 0.7, 0.55]:
				end = surface_z(faces, p.x * shrink, p.y, p.z, size.z)
				if end != INF:
					p.x *= shrink
					break
			if end == INF:
				end = p.z * size.z * 0.5
			spots.append({"position": Vector3(p.x, p.y, end + p.z * 0.015), "size": item[1], "kind": item[2]})
	return spots

## Outermost body surface at (x, y) towards +Z (way = 1, rear) or -Z (way = -1, front),
## or INF when the ray misses the body.
static func surface_z(faces: PackedVector3Array, x: float, y: float, way: float, length: float) -> float:
	var from := Vector3(x, y, way * length)
	var dir := Vector3(0, 0, -way)
	var best := INF
	for i in range(0, faces.size(), 3):
		var hit = Geometry3D.ray_intersects_triangle(from, dir, faces[i], faces[i + 1], faces[i + 2])
		if hit != null:
			best = minf(best, from.distance_to(hit))
	return INF if best == INF else from.z + dir.z * best

## One static mesh (body + wheels, no lamps) and the shared colour texture, for the
## MultiMesh far traffic: {"mesh": ArrayMesh, "texture": Texture2D, "size": Vector3}.
static func baked(name: String) -> Dictionary:
	var t := template(name)
	if t.is_empty():
		return {}
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var texture: Texture2D = null
	var root: Node3D = t.root
	for child in root.get_children():
		var parts: Array = [child] if child is MeshInstance3D else child.get_children()
		for part in parts:
			if not part is MeshInstance3D:
				continue
			var xf: Transform3D = child.transform * part.transform if part != child else child.transform
			var mesh: Mesh = part.mesh
			for s in range(mesh.get_surface_count()):
				st.append_from(mesh, s, xf)
				var mat := mesh.surface_get_material(s)
				if texture == null and mat is BaseMaterial3D:
					texture = mat.albedo_texture
	return {"mesh": st.commit(), "texture": texture, "size": t.size}

static func lamp_material(color: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = color.darkened(0.55)
	m.emission_enabled = true
	m.emission = color
	m.emission_energy_multiplier = 0.0
	return m

static func add_lamp(parent: Node3D, pos: Vector3, size: Vector3, mat: Material) -> void:
	var m := MeshInstance3D.new()
	var b := BoxMesh.new()
	b.size = size
	m.mesh = b
	m.material_override = mat
	m.position = pos
	m.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	parent.add_child(m)

## Lamp state: brake on/off, indicator side (-1 left, 1 right, 0 none), blink phase.
static func set_lamps(lamps: Dictionary, brake: bool, indicator: int, blink_on: bool) -> void:
	lamps.brake.emission_energy_multiplier = 2.5 if brake else 0.0
	lamps.left.emission_energy_multiplier = 3.0 if indicator == -1 and blink_on else 0.0
	lamps.right.emission_energy_multiplier = 3.0 if indicator == 1 and blink_on else 0.0

static func release_visual_templates() -> void:
	for t in _templates.values():
		if is_instance_valid(t.root): t.root.free()
	_templates.clear()
