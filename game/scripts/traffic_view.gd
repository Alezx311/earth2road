extends Node3D
## Traffic from the SUMO bridge (tools/traffic.py), two levels of detail:
## * near cars (a hundred or so around the focus) are full models with spinning wheels,
##   lamps and an AnimatableBody3D (layer 16), so the player collides with them physically;
##   SUMO keeps driving them regardless;
## * every other car is an instance in one MultiMesh per model. The bridge sends the
##   finished MultiMesh buffer; the shader traffic_far.gdshader moves the instances from
##   the previous to the current pose, so thousands of cars cost no per-car GDScript.
## Frames arrive every ~0.1 s; cars are drawn one frame behind and interpolated between the
## last two frames over the measured frame interval.

const Vehicles = preload("res://scripts/vehicles.gd")
const FarShader = preload("res://shaders/traffic_far.gdshader")
const LAYER_TRAFFIC := 16
const FLOATS := 20
const SIGNAL_RIGHT := 1
const SIGNAL_LEFT := 2
const SIGNAL_BRAKE := 8

var cars: Dictionary = {}
var clock := 0.0
var models: Array = []
var far: Dictionary = {}          # model index -> {"node", "mm", "material", "capacity"}
var far_count := 0
var total := 0
var since_frame := 0.0
var period := 0.1                 # measured wall time between frames
var time_scale := 1.0             # simulated seconds per wall second (wheel spin)

func set_models(names: Array) -> void:
	models = names

## One bridge frame: header (near cars, far block sizes) and the float32 payload.
func update(msg: Dictionary, floats: PackedFloat32Array) -> void:
	if since_frame > 0.0:
		period = lerpf(period, clampf(since_frame, 0.05, 1.0), 0.3)
	since_frame = 0.0
	time_scale = float(msg.get("actual", 1.0)) if msg.get("spectating", false) else 1.0
	total = int(msg.get("total", 0))
	update_near(msg.cars)
	update_far(msg.get("far", []), floats)

func update_near(list: Array) -> void:
	var seen: Dictionary = {}
	for v in list:
		seen[v.id] = true
		var pose := {"p": Vector3(v.p[0], v.p[1], v.p[2]), "yaw": -deg_to_rad(float(v.a)), "pitch": float(v.get("pt", 0.0))}
		if not cars.has(v.id):
			var car := spawn(v.get("m", "sedan"))
			if car.is_empty():
				continue
			car.prev = pose
			car.cur = pose
			cars[v.id] = car
			place(car, pose)
		var c: Dictionary = cars[v.id]
		c.prev = interpolated(c)
		c.cur = pose
		c.t = 0.0
		c.speed = float(v.speed)
		c.signals = int(v.get("s", 0))
	for id in cars.keys():
		if not seen.has(id):
			cars[id].body.queue_free()
			cars.erase(id)

func far_model(index: int) -> Dictionary:
	if far.has(index):
		return far[index]
	var name: String = models[index] if index < models.size() else "sedan"
	if not Vehicles.available(name):
		name = "sedan"
	var baked := Vehicles.baked(name)
	if baked.is_empty():
		return {}
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.use_custom_data = true
	mm.mesh = baked.mesh
	var material := ShaderMaterial.new()
	material.shader = FarShader
	material.set_shader_parameter("albedo_tex", baked.texture)
	material.set_shader_parameter("rear_z", baked.size.z * 0.5)
	var node := MultiMeshInstance3D.new()
	node.multimesh = mm
	node.material_override = material
	# Instances move on the GPU; a fixed box over the whole map avoids per-frame AABB work.
	node.custom_aabb = AABB(Vector3(-20000, -500, -20000), Vector3(40000, 1500, 40000))
	add_child(node)
	far[index] = {"node": node, "mm": mm, "material": material, "capacity": 0}
	return far[index]

func update_far(blocks: Array, floats: PackedFloat32Array) -> void:
	var used: Dictionary = {}
	var at := 0
	far_count = 0
	for block in blocks:
		var index := int(block[0])
		var count := int(block[1])
		var item := far_model(index)
		var data := floats.slice(at * FLOATS, (at + count) * FLOATS)
		at += count
		if item.is_empty():
			continue
		used[index] = true
		far_count += count
		var mm: MultiMesh = item.mm
		if count > item.capacity:
			item.capacity = maxi(64, nearest_po2(count))
			mm.instance_count = item.capacity
		data.resize(item.capacity * FLOATS)
		mm.buffer = data
		mm.visible_instance_count = count
	for index in far:
		if not used.has(index):
			far[index].mm.visible_instance_count = 0

func spawn(model: String) -> Dictionary:
	if not Vehicles.available(model):
		model = "sedan"
	var car := Vehicles.instantiate(model)
	if car.is_empty():
		return {}
	var body := AnimatableBody3D.new()
	body.collision_layer = LAYER_TRAFFIC
	body.collision_mask = 0
	body.sync_to_physics = true
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	var size: Vector3 = car.size
	box.size = Vector3(size.x * 0.96, size.y * 0.85, size.z * 0.97)
	shape.shape = box
	shape.position = Vector3(0, size.y * 0.5, 0)
	body.add_child(shape)
	body.add_child(car.root)
	add_child(body)
	return {"body": body, "wheels": car.wheels, "lamps": car.lamps, "radius": car.tire_radius, "size": size, "t": 0.0, "speed": 0.0, "signals": 0, "spin": 0.0, "steer": 0.0}

func interpolated(c: Dictionary) -> Dictionary:
	var a := clampf(c.t / period, 0.0, 1.0)
	return {"p": c.prev.p.lerp(c.cur.p, a), "yaw": lerp_angle(c.prev.yaw, c.cur.yaw, a), "pitch": lerpf(c.prev.pitch, c.cur.pitch, a)}

func place(c: Dictionary, pose: Dictionary) -> void:
	var basis := Basis(Vector3.UP, pose.yaw) * Basis(Vector3.RIGHT, pose.pitch)
	c.body.global_transform = Transform3D(basis, pose.p)

func _process(delta: float) -> void:
	since_frame += delta
	var alpha := clampf(since_frame / period, 0.0, 1.0)
	for index in far:
		far[index].material.set_shader_parameter("alpha", alpha)

func _physics_process(delta: float) -> void:
	clock += delta
	var blink := fmod(clock * time_scale, 0.8) < 0.4
	for id in cars:
		var c: Dictionary = cars[id]
		c.t += delta
		var pose := interpolated(c)
		place(c, pose)
		# Wheels: roll with speed; front wheels follow the yaw rate (bicycle model).
		c.spin = fmod(c.spin - c.speed / c.radius * delta * time_scale, TAU)
		var yaw_rate := angle_difference(c.prev.yaw, c.cur.yaw) / maxf(period * time_scale, 0.01)
		var wheelbase: float = c.size.z * 0.6
		var target := clampf(atan(yaw_rate * wheelbase / maxf(c.speed, 1.0)), -0.6, 0.6)
		c.steer = lerpf(c.steer, target, minf(1.0, delta * 8.0))
		for i in range(4):
			var w: Node3D = c.wheels[i]
			w.rotation = Vector3(c.spin, c.steer if i < 2 else 0.0, 0.0)
		var s: int = c.signals
		var indicator := -1 if s & SIGNAL_LEFT else (1 if s & SIGNAL_RIGHT else 0)
		Vehicles.set_lamps(c.lamps, (s & SIGNAL_BRAKE) != 0, indicator, blink)

func count() -> int:
	return total
