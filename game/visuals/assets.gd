extends RefCounted
const Palette = preload("res://visuals/palette.gd")
static var trees: Dictionary = {}
static var props: Dictionary = {}
## Pack-slot manifest (config/visuals/downloads.json), loaded once on the main thread.
static var manifest: Dictionary = {}
## slot -> sorted pack ids that could offer external variants.
static var slot_packs: Dictionary = {}
## slot -> successfully loaded external variant part-sets, in sorted pack-id order.
static var slot_variants: Dictionary = {}

static func init() -> void:
	Palette.init()
	if not trees.is_empty():
		return
	for species in range(5):
		for variant in range(3):
			for lod in range(3):
				trees["%d:%d:%d" % [species,variant,lod]] = tree(species,variant,lod)
	for kind in ["lamp", "lamp_modern", "bench", "bin", "planter", "bollard", "cabinet", "stop", "stop_old", "kiosk", "fence", "drain", "manhole", "metro", "ac", "balcony", "loggia", "entrance", "vent"]:
		props[kind] = prop(kind)
	load_manifest()

static func tree(species: int, variant: int, lod: int) -> Array:
	var rng := RandomNumberGenerator.new()
	rng.seed = 311 + species * 137 + variant * 19
	var height: float = [10.0,12.0,9.0,17.0,15.0][species] * (0.87 + variant*.13)
	var radius: float = [3.7,3.4,3.6,2.0,3.4][species]
	var trunk := CylinderMesh.new()
	trunk.top_radius = .10
	trunk.bottom_radius = .22 + height*.008
	trunk.height = height*.72
	trunk.radial_segments = 6 if lod > 0 else 10
	var trunk_st := SurfaceTool.new()
	trunk_st.append_from(trunk,0,Transform3D(Basis(),Vector3(0,trunk.height*.5,0)))
	if lod < 2:
		for branch in range(10):
			var angle := float(branch)*2.4
			var start := Vector3(0,height*(.32+branch*.033),0)
			var finish := Vector3(cos(angle)*radius*.78,height*(.51+branch*.026),sin(angle)*radius*.78)
			var delta := finish-start
			var limb := CylinderMesh.new()
			limb.top_radius=.025
			limb.bottom_radius=.10
			limb.height=delta.length()
			limb.radial_segments=5
			trunk_st.append_from(limb,0,Transform3D(Basis(Quaternion(Vector3.UP,delta.normalized())),(start+finish)*.5))
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var count: int = [650,180,45][lod]
	var leaf_size: float = [1.1,1.9,3.2][lod]
	for i in range(count):
		var dir := Vector3(rng.randf_range(-1,1),rng.randf_range(-1,1),rng.randf_range(-1,1)).normalized()
		var p := dir * pow(rng.randf(),.333)
		var crown_y := height*.65
		var extent_y := height*.33
		if species == 4:
			p.x *= 1.0 - (p.y+1.0)*.35
			p.z *= 1.0 - (p.y+1.0)*.35
		p = Vector3(p.x*radius,crown_y+p.y*extent_y,p.z*radius)
		var basis := Basis.from_euler(Vector3(rng.randf()*TAU,rng.randf()*TAU,rng.randf()*TAU))
		var size := leaf_size*rng.randf_range(.65,1.3)
		var color := Color.from_hsv(.23+rng.randf_range(-.025,.025),.16,.75+rng.randf()*.25)
		for index in [0,1,2,0,2,3]:
			var uv: Vector2 = [Vector2.ZERO,Vector2(1,0),Vector2.ONE,Vector2(0,1)][index]
			st.set_uv(uv)
			st.set_color(color)
			st.set_normal((dir + Vector3.UP*.6).normalized())
			st.add_vertex(p + basis * Vector3((uv.x-.5)*size,(uv.y-.5)*size,0))
	return [{"mesh":trunk_st.commit(),"material":Palette.materials.bark}, {"mesh":st.commit(),"material":Palette.materials.leaf}]

static func part(shape: String, material: String, pos: Vector3, size: Vector3, rot := Vector3.ZERO) -> Dictionary:
	return {"mesh":Palette.meshes[shape],"material":Palette.materials[material],"transform":Transform3D(Basis.from_euler(rot).scaled(size),pos)}

static func box(material: String, pos: Vector3, size: Vector3) -> Dictionary:
	return part("box",material,pos,size)

static func prop(kind: String) -> Array:
	var p: Array = []
	match kind:
		"lamp", "lamp_modern":
			var h := 8.5 if kind == "lamp" else 6.0
			p.append(part("pole","metal",Vector3(0,h*.5,0),Vector3(.14,h,.14)))
			p.append(box("metal",Vector3(0,h,-.9),Vector3(.09,.09,1.8)))
			p.append(box("cream",Vector3(0,h-.12,-1.7),Vector3(.42,.16,.85)))
		"bench":
			for x in [-.72,.72]:
				p.append(box("metal",Vector3(x,.3,0),Vector3(.08,.6,.5)))
			for z in [-.18,0,.18]:
				p.append(box("wood",Vector3(0,.5,z),Vector3(1.8,.07,.14)))
			for y in [.72,.9]:
				p.append(box("wood",Vector3(0,y,.23),Vector3(1.8,.14,.05)))
		"bin":
			p.append(box("metal",Vector3(0,.43,0),Vector3(.42,.86,.42)))
			p.append(box("rubber",Vector3(0,.87,0),Vector3(.34,.02,.34)))
		"planter":
			p.append(box("concrete",Vector3(0,.26,0),Vector3(.84,.52,.84)))
			p.append(box("rubber",Vector3(0,.56,0),Vector3(.66,.1,.66)))
		"bollard":
			p.append(part("pole","metal",Vector3(0,.38,0),Vector3(.10,.76,.10)))
			p.append(part("pole","white",Vector3(0,.62,0),Vector3(.105,.10,.105)))
		"cabinet":
			p.append(box("concrete",Vector3(0,.13,0),Vector3(.9,.26,.5)))
			p.append(box("cream",Vector3(0,.8,0),Vector3(.75,1.3,.4)))
			p.append(box("metal",Vector3(.23,.8,-.21),Vector3(.025,.12,.035)))
		"stop", "stop_old":
			for x in [-2.0,0,2.0]:
				p.append(box("metal",Vector3(x,1.25,.7),Vector3(.08,2.5,.08)))
			p.append(box("metal",Vector3(0,2.5,0),Vector3(4.5,.14,2.0)))
			p.append(box("glass" if kind == "stop" else "cream",Vector3(0,1.35,.72),Vector3(4,1.8,.035)))
			p.append(box("wood",Vector3(0,.5,.35),Vector3(3.6,.08,.42)))
			p.append(box("blue",Vector3(1.6,1.5,.68),Vector3(.4,.65,.06)))
		"kiosk":
			p.append(box("cream",Vector3(0,1.35,0),Vector3(3.6,2.7,2.6)))
			p.append(box("metal",Vector3(0,2.75,0),Vector3(3.9,.18,2.9)))
			p.append(box("glass",Vector3(-.35,1.5,-1.32),Vector3(2.3,1.3,.05)))
			p.append(box("metal",Vector3(1.35,1.05,-1.32),Vector3(.65,2.1,.05)))
			p.append(box("blue",Vector3(0,2.4,-1.36),Vector3(3.4,.35,.05)))
		"fence":
			for x in [-1,1]:
				p.append(box("metal",Vector3(x,.6,0),Vector3(.06,1.2,.06)))
			for y in [.3,.9]:
				p.append(box("metal",Vector3(0,y,0),Vector3(2,.04,.04)))
			for x in range(9):
				p.append(box("metal",Vector3(-.9+x*.225,.6,0),Vector3(.018,.8,.018)))
		"manhole":
			p.append(part("pole","metal",Vector3(0,.015,0),Vector3(.65,.03,.65)))
		"drain":
			for x in range(8):
				p.append(box("metal",Vector3(-.28+x*.08,.012,0),Vector3(.04,.024,.4)))
		"ac":
			p.append(box("cream",Vector3(0,0,.2),Vector3(.8,.55,.4)))
			for y in range(6):
				p.append(box("metal",Vector3(0,-.20+y*.08,.405),Vector3(.63,.012,.01)))
		"balcony", "loggia":
			p.append(box("concrete",Vector3(0,-.75,.55),Vector3(2.25,.15,1.1)))
			p.append(box("cream",Vector3(0,-.25,1.04),Vector3(2.25,.9,.06)))
			for x in [-1.1,1.1]:
				p.append(box("cream",Vector3(x,-.25,.55),Vector3(.06,.9,1.1)))
			if kind == "loggia":
				p.append(box("glass",Vector3(0,.7,1.02),Vector3(2.2,1.0,.04)))
				p.append(box("concrete",Vector3(0,1.3,.55),Vector3(2.3,.1,1.15)))
				for x in [-1.1,0,1.1]:
					p.append(box("frame",Vector3(x,.72,1.06),Vector3(.055,1.1,.04)))
		"entrance":
			p.append(box("metal",Vector3(0,1.1,.04),Vector3(1.4,2.2,.08)))
			p.append(box("glass",Vector3(0,1.4,.09),Vector3(1.1,1.1,.02)))
			p.append(box("metal",Vector3(0,2.4,.7),Vector3(2.1,.12,1.5)))
		"vent":
			p.append(box("concrete",Vector3(0,.6,0),Vector3(.7,1.2,.7)))
			p.append(box("metal",Vector3(0,1.25,0),Vector3(.95,.1,.95)))
		"metro":
			for x in [-2,2]:
				p.append(box("metal",Vector3(x,1.5,0),Vector3(.12,3,.12)))
			p.append(box("metal",Vector3(0,3,0),Vector3(4.3,.15,3.4)))
			p.append(box("glass",Vector3(0,3.12,0),Vector3(4.1,.06,3.2)))
			p.append(box("blue",Vector3(0,2.65,-1.55),Vector3(3.8,.4,.1)))
	return p

static func load_manifest() -> void:
	var path := ProjectSettings.globalize_path("res://../config/visuals/downloads.json")
	if FileAccess.file_exists(path):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
		if parsed is Dictionary:
			manifest = parsed
	var packs: Dictionary = manifest.get("packs", {})
	for pack_id in packs:
		var pack: Dictionary = packs[pack_id]
		var slot := str(pack.get("slot", ""))
		if slot.is_empty():
			continue
		if not slot_packs.has(slot):
			slot_packs[slot] = []
		slot_packs[slot].append(pack_id)
	for slot in slot_packs:
		slot_packs[slot].sort()
		var loaded: Array = []
		for pack_id in slot_packs[slot]:
			var parts := load_pack(pack_id)
			if not parts.is_empty():
				loaded.append(parts)
		if not loaded.is_empty():
			slot_variants[slot] = loaded

## Resolve the parts to draw for a slot. External variants win and are picked
## deterministically from the (sorted) loaded pack list; procedural props remain
## the fallback whenever no external pack is usable.
static func resolve_prop(kind: String, seed: int) -> Array:
	var variants: Array = slot_variants.get(kind, [])
	if variants.is_empty():
		return props.get(kind, [])
	return variants[posmod(seed, variants.size())]

static func load_pack(pack_id: String) -> Array:
	var pack: Dictionary = manifest.get("packs", {}).get(pack_id, {})
	var files: Dictionary = pack.get("files", {})
	var gltf_name := ""
	for name in files:
		if name.ends_with(".gltf"):
			gltf_name = name
			break
	if gltf_name.is_empty():
		return []
	var slot := str(pack.get("slot", "prop"))
	var folder := "res://assets/visuals/%s" % pack_id
	if not FileAccess.file_exists("%s/%s" % [folder, gltf_name]):
		return []
	if not preflight(folder, gltf_name, files, pack_id, slot):
		return []
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	var path := ProjectSettings.globalize_path("%s/%s" % [folder, gltf_name])
	if doc.append_from_file(path, state) != OK:
		push_warning("props %s: gltf load failed; procedural '%s' fallback" % [pack_id, slot])
		return []
	var scene := doc.generate_scene(state)
	if scene == null:
		return []
	var parts: Array = []
	collect(scene, Transform3D.IDENTITY, parts)
	scene.free()
	if parts.is_empty():
		return []
	print("props: loaded %s -> %s (%d parts)" % [pack_id, slot, parts.size()])
	return parts

## Verify every buffer/image dependency before asking the engine to load the
## gltf. local relative URIs only; data: URIs are embedded and skipped.
## One actionable warning on failure so the tile keeps its procedural fallback.
static func preflight(folder: String, gltf_name: String, files: Dictionary, pack_id: String, slot: String) -> bool:
	var text := FileAccess.get_file_as_string("%s/%s" % [folder, gltf_name])
	var gltf: Variant = JSON.parse_string(text)
	if gltf is not Dictionary:
		push_warning("props %s: gltf is not a JSON object; procedural '%s' fallback" % [pack_id, slot])
		return false
	var missing: Array = []
	for buffer in gltf.get("buffers", []):
		var uri := str(buffer.get("uri", ""))
		if not uri.begins_with("data:"):
			_check_dependency(folder, uri, files, missing)
	for image in gltf.get("images", []):
		var uri := str(image.get("uri", ""))
		if not uri.begins_with("data:"):
			_check_dependency(folder, uri, files, missing)
	if not missing.is_empty():
		push_warning("props %s: bad dependencies (%s); procedural '%s' fallback" % [pack_id, ", ".join(missing), slot])
		return false
	return true

static func _check_dependency(folder: String, uri: String, files: Dictionary, missing: Array) -> void:
	var name := uri.uri_decode()
	if name == "" or name.begins_with("/") or name.begins_with("\\") \
			or name.contains("\\") or name.contains(":") or name.contains("://") \
			or name.contains("../") or name.begins_with("..") \
			or not files.has(name) \
			or not FileAccess.file_exists("%s/%s" % [folder, name]):
		missing.append(uri)

static func collect(node: Node, parent: Transform3D, parts: Array) -> void:
	var xf := parent
	if node is Node3D: xf=parent*node.transform
	if node is MeshInstance3D and node.mesh != null:
		for i in range(node.mesh.get_surface_count()):
			var mesh:=ArrayMesh.new()
			mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,node.mesh.surface_get_arrays(i))
			var mat: Material=node.get_active_material(i)
			parts.append({"mesh":mesh,"material":mat if mat!=null else Palette.materials.concrete,"transform":xf})
	for child in node.get_children(): collect(child,xf,parts)
