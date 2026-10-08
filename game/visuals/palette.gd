extends RefCounted
## Shared, main-thread initialized resources. Tile workers only read these caches.
static var materials: Dictionary = {}
static var meshes: Dictionary = {}
static var config: Dictionary = {}

static func init() -> void:
	if not materials.is_empty():
		return
	var path := ProjectSettings.globalize_path("res://../config/visuals/style.json")
	if FileAccess.file_exists(path):
		config = JSON.parse_string(FileAccess.get_file_as_string(path))
	for pair in [["concrete", "a5a398"], ["frame", "d1d0c5"], ["metal", "444b4c"], ["wood", "76634c"], ["bark", "625548"], ["glass", "354b55"], ["rubber", "202326"], ["cream", "c8c3af"], ["blue", "4f727d"], ["white", "dddcd1"], ["red", "a8483c"], ["yellow", "d2a83e"], ["green", "4f7d4a"], ["sand", "cbb88c"], ["hedge", "4a6436"]]:
		var m := StandardMaterial3D.new()
		m.albedo_color = Color(pair[1])
		m.roughness = 0.86
		if pair[0] == "glass":
			m.roughness = 0.18
			m.metallic = 0.25
		if pair[0] == "metal":
			m.metallic = 0.65
			m.roughness = 0.5
		materials[pair[0]] = m
	var leaf := ShaderMaterial.new()
	leaf.shader = load("res://visuals/foliage.gdshader")
	materials.leaf = leaf
	var box := BoxMesh.new()
	meshes.box = box
	var pole := CylinderMesh.new()
	pole.top_radius = 0.5
	pole.bottom_radius = 0.5
	pole.height = 1.0
	pole.radial_segments = 10
	meshes.pole = pole
	var sphere := SphereMesh.new()
	sphere.radius = 0.5
	sphere.height = 1.0
	sphere.radial_segments = 8
	sphere.rings = 4
	meshes.sphere = sphere
	var leaf_mesh := QuadMesh.new()
	leaf_mesh.size = Vector2(1, 1)
	meshes.leaf = leaf_mesh
	var plate := QuadMesh.new()
	plate.size = Vector2(0.72, 0.72)
	meshes.sign_plate = plate

static func distance_for(kind: String) -> float:
	return float(config.get(kind + "_distance", 180.0))
