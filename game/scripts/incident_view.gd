extends Node3D
## Markers for the live road situations reported by the bridge (header "incidents").
##
## They live outside the tile streaming on purpose: a jam two kilometres away is exactly
## what the spectator camera is looking for, and tiles that far are LOD-only.
## The stopped cars of an accident are real SUMO vehicles and are drawn by traffic_view;
## what is added here is the roadside signalling around them.

const CONE_COLOUR := Color("e2621f")
const BAND_COLOUR := Color("e8e4d8")
const BLOCKED_COLOUR := Color("d94f3d")

var markers: Dictionary = {}          # incident id -> Node3D
var cone_mesh: Mesh
var band_mesh: Mesh
var cone_material: StandardMaterial3D
var band_material: StandardMaterial3D

func _ready() -> void:
	cone_material = StandardMaterial3D.new()
	cone_material.albedo_color = CONE_COLOUR
	cone_material.roughness = 0.8
	band_material = StandardMaterial3D.new()
	band_material.albedo_color = BAND_COLOUR
	band_material.roughness = 0.8
	var cone := CylinderMesh.new()
	cone.top_radius = 0.03
	cone.bottom_radius = 0.19
	cone.height = 0.62
	cone.radial_segments = 8
	cone.rings = 1
	cone_mesh = cone
	var band := CylinderMesh.new()
	band.top_radius = 0.13
	band.bottom_radius = 0.15
	band.height = 0.1
	band.radial_segments = 8
	band.rings = 1
	band_mesh = band

## Diffs the list: only new situations are built, only gone ones are freed.
func update(items: Array) -> void:
	var seen := {}
	for item in items:
		var id: String = str(item.get("id", ""))
		seen[id] = true
		if not markers.has(id):
			markers[id] = build(item)
			add_child(markers[id])
	for id in markers.keys():
		if not seen.has(id):
			markers[id].queue_free()
			markers.erase(id)

func build(item: Dictionary) -> Node3D:
	var node := Node3D.new()
	var p: Array = item.get("p", [0, 0, 0])
	node.position = Vector3(p[0], p[1], p[2])
	node.rotation.y = -deg_to_rad(float(item.get("heading", 0.0)))
	var blocked: bool = item.get("blocking", false)
	var count := 5 if item.kind in ["roadworks", "lane_closed", "accident"] else 3
	for i in range(count):
		var cone := MeshInstance3D.new()
		cone.mesh = cone_mesh
		cone.material_override = cone_material
		cone.position = Vector3(0.0, 0.31, float(i) * 2.2 - float(count - 1) * 1.1)
		node.add_child(cone)
		var band := MeshInstance3D.new()
		band.mesh = band_mesh
		band.material_override = band_material
		band.position = cone.position + Vector3(0.0, 0.14, 0.0)
		node.add_child(band)
	var text := Label3D.new()
	text.text = tr(item.get("label", item.get("kind", "")))
	if item.get("value") != null:
		text.text += " %d" % int(item.value)
	text.font_size = 96
	text.pixel_size = 0.006
	text.position = Vector3(0.0, 3.2, 0.0)
	text.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	text.modulate = BLOCKED_COLOUR if blocked else Color.WHITE
	text.outline_size = 24
	text.outline_modulate = Color(0, 0, 0, 0.8)
	text.no_depth_test = true
	text.visibility_range_end = 1200.0
	node.add_child(text)
	var beacon := OmniLight3D.new()
	beacon.light_color = BLOCKED_COLOUR if blocked else CONE_COLOUR
	beacon.light_energy = 2.0
	beacon.omni_range = 14.0
	beacon.position = Vector3(0.0, 1.6, 0.0)
	beacon.name = "Beacon"
	node.add_child(beacon)
	return node

func _process(_delta: float) -> void:
	# One slow blink for every marker: an incident should catch the eye from the air.
	var pulse := 1.4 + 1.4 * sin(Time.get_ticks_msec() / 260.0)
	for id in markers:
		var beacon: Node = markers[id].get_node_or_null("Beacon")
		if beacon:
			beacon.light_energy = pulse
