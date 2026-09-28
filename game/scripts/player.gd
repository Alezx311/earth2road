extends Node3D
## Player car: a GEVP Vehicle (RigidBody3D with raycast wheels, automatic gearbox, ABS,
## traction and stability control) dressed with a Kenney model from vehicles.gd.
## Tuning starts from GEVP's "simcade" demo and is scaled to a ~1300 kg front-drive car.

const Vehicles = preload("res://scripts/vehicles.gd")
const VehicleScript = preload("res://addons/gevp/scripts/vehicle.gd")
const WheelScript = preload("res://addons/gevp/scripts/wheel.gd")
const ControllerScript = preload("res://addons/gevp/scripts/vehicle_controllergd.gd")

const LAYER_PLAYER := 32
const MASK_WORLD := 1 | 2 | 4 | 8
const LAYER_TRAFFIC := 16
const CLEARANCE := 0.35
const HOLD_BRAKE := 0.35
const REVERSE_MAX := 5.5      # m/s, ~20 km/h
const ACTIONS := {
	"Throttle": [KEY_W, KEY_UP], "Brakes": [KEY_S, KEY_DOWN],
	"Steer Left": [KEY_A, KEY_LEFT], "Steer Right": [KEY_D, KEY_RIGHT], "Handbrake": [KEY_SPACE],
}

var body: RigidBody3D
var controller: Node3D
var model_index := 0
var model_name := ""
var size := Vector3(1.8, 1.45, 4.5)
var enabled := true:
	set(value):
		enabled = value
		if body:
			body.freeze = not value
var cockpit := false
var contacts := 0
var chase: Camera3D
var inside: Camera3D
var lamps: Dictionary = {}

## Mouse look (hold the right button): the chase camera orbits the car, the cockpit camera
## turns the head; the wheel sets the chase distance. A second and a half after the button
## is released the view eases back behind the car / straight ahead.
const LOOK_SENSITIVITY := 0.005
const LOOK_RETURN_DELAY := 1.5
const LOOK_RETURN_RATE := 3.0
const CHASE_MIN := 4.0
const CHASE_MAX := 25.0
var looking := false
var look_idle := 0.0
var orbit_yaw := 0.0              # rad around the car, 0 = behind
var orbit_pitch := 0.0            # rad above the default chase elevation
var head_yaw := 0.0               # cockpit
var head_pitch := 0.0
var chase_zoom := 1.0             # distance multiplier from the wheel

func _ready() -> void:
	# Physics order: controller (reads keys) -> this rig (hold brake) -> vehicle (uses inputs).
	process_physics_priority = -1
	for action in ACTIONS:
		if not InputMap.has_action(action):
			InputMap.add_action(action)
			for key in ACTIONS[action]:
				var ev := InputEventKey.new()
				ev.physical_keycode = key
				InputMap.action_add_event(action, ev)
	chase = Camera3D.new()
	chase.far = 2400
	chase.fov = 66
	chase.top_level = true
	add_child(chase)
	chase.current = true
	model_name = Vehicles.catalog().player_models[0]

## Signed forward speed, m/s.
var speed: float:
	get:
		return 0.0 if body == null else body.linear_velocity.dot(-body.global_transform.basis.z)

var pos: Vector3:
	get:
		return body.global_position if body else global_position

var yaw: float:
	get:
		return body.global_rotation.y if body else 0.0

func spawn(at: Vector3, heading_deg: float) -> void:
	var xf := Transform3D(Basis(Vector3.UP, -deg_to_rad(heading_deg)), at + Vector3.UP * 0.15)
	build(model_name, xf)
	chase.global_position = xf * Vector3(0, 4.0, 9.0)

func cycle_model() -> void:
	var models: Array = Vehicles.catalog().player_models
	model_index = (model_index + 1) % models.size()
	model_name = models[model_index]
	build(model_name, body.global_transform if body else Transform3D.IDENTITY)

func build(name: String, xf: Transform3D) -> void:
	if body:
		body.queue_free()
		controller.queue_free()
	var car := Vehicles.instantiate(name)
	size = car.size
	lamps = car.lamps
	var r: float = car.tire_radius
	var v: RigidBody3D = VehicleScript.new()
	v.name = "PlayerCar"
	v.top_level = true
	v.collision_layer = LAYER_PLAYER
	v.collision_mask = MASK_WORLD | LAYER_TRAFFIC
	v.contact_monitor = true
	v.max_contacts_reported = 4
	v.body_entered.connect(_on_contact)
	# Heavier / taller models get a bit more mass; power is plain city-car level.
	var mass_kg := 1300.0 * clampf(size.x * size.y * size.z / (1.8 * 1.45 * 4.5), 0.85, 1.6)
	v.vehicle_mass = mass_kg
	v.front_weight_distribution = 0.56
	v.front_torque_split = 1.0
	v.center_of_gravity_height_offset = -0.18
	v.max_torque = 240.0 * mass_kg / 1300.0
	v.max_rpm = 6200.0
	v.idle_rpm = 800.0
	v.torque_curve = torque_curve()
	v.motor_moment = 0.3
	var ratios: Array[float] = [3.45, 1.95, 1.3, 1.03, 0.84, 0.7]
	v.gear_ratios = ratios
	v.final_drive = 3.9
	v.reverse_ratio = 3.3
	v.shift_time = 0.3
	v.max_steering_angle = deg_to_rad(36.0)
	v.steering_slip_assist = 0.3
	v.countersteer_assist = 0.75
	v.stability_yaw_strength = 2.0
	v.stability_yaw_ground_multiplier = 4.0
	v.front_resting_ratio = 0.55
	v.rear_resting_ratio = 0.55
	v.front_damping_ratio = 0.5
	v.rear_damping_ratio = 0.5
	v.front_spring_length = 0.16
	v.rear_spring_length = 0.16
	v.tire_stiffnesses = {"Road": 5.0, "Dirt": 0.5, "Grass": 0.5}
	v.coefficient_of_friction = {"Road": 2.0, "Dirt": 1.4, "Grass": 1.0}
	v.longitudinal_grip_ratio = {"Road": 0.55, "Dirt": 0.56, "Grass": 0.8}
	v.front_tire_radius = r
	v.rear_tire_radius = r
	v.front_tire_width = 205.0
	v.rear_tire_width = 205.0
	v.coefficient_of_drag = 0.32
	v.frontal_area = size.x * size.y * 0.82
	var model: Node3D = car.root
	v.add_child(model)
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(size.x * 0.96, size.y - CLEARANCE, size.z * 0.96)
	shape.shape = box
	shape.position = Vector3(0, CLEARANCE + (size.y - CLEARANCE) * 0.5, 0)
	v.add_child(shape)
	var names := ["front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel"]
	for i in range(4):
		var pivot: Node3D = car.wheels[i]
		var ray: RayCast3D = WheelScript.new()
		ray.name = names[i]
		ray.collision_mask = MASK_WORLD
		# Ray starts above the wheel centre by roughly the unloaded spring travel.
		ray.position = pivot.position + Vector3.UP * 0.08
		pivot.get_parent().remove_child(pivot)
		pivot.position = Vector3.ZERO
		var hub := Node3D.new()
		hub.position = Vector3.DOWN * 0.08
		ray.add_child(hub)
		hub.add_child(pivot)
		ray.wheel_node = hub
		v.add_child(ray)
		v.set(names[i], ray)
	v.transform = xf
	body = v
	add_child(v)
	inside = Camera3D.new()
	inside.far = 2400
	inside.fov = 70
	inside.position = Vector3(-size.x * 0.2, size.y * 0.82, -size.z * 0.05)
	v.add_child(inside)
	var c: Node3D = ControllerScript.new()
	c.vehicle_node = v
	c.string_clutch_input = ""
	c.string_toggle_transmission = ""
	c.string_shift_up = ""
	c.string_shift_down = ""
	c.process_physics_priority = -2
	controller = c
	add_child(c)
	body.freeze = not enabled
	set_camera(cockpit)

static func torque_curve() -> Curve:
	var c := Curve.new()
	c.add_point(Vector2(0.0, 0.5), 0.0, 2.0)
	c.add_point(Vector2(0.72, 1.0))
	c.add_point(Vector2(1.0, 0.78), -2.0, 0.0)
	return c

func set_camera(value: bool) -> void:
	cockpit = value
	if inside:
		inside.current = cockpit
	chase.current = not cockpit

func _on_contact(other: Node) -> void:
	if other is PhysicsBody3D and (other.collision_layer & LAYER_TRAFFIC) != 0:
		contacts += 1

func _physics_process(delta: float) -> void:
	if body == null:
		return
	if not enabled:
		body.throttle_input = 0.0
		body.brake_input = 0.0
	elif body.current_gear == -1 and -speed > REVERSE_MAX:
		body.throttle_input = 0.0      # in reverse GEVP maps the S key to throttle
	elif body.throttle_input < 0.01 and body.brake_input < 0.01 and absf(speed) < 0.8:
		# Hold the car like an automatic with the foot on the brake (no creeping down slopes).
		body.brake_input = HOLD_BRAKE
	Vehicles.set_lamps(lamps, body.brake_amount > 0.05 and body.current_gear != -1, 0, false)

## Only while one of this car's cameras is on screen (not in spectator mode or a menu).
func viewing() -> bool:
	var cam := get_viewport().get_camera_3d()
	return cam != null and (cam == chase or cam == inside)

func _unhandled_input(event: InputEvent) -> void:
	if body == null or not viewing():
		if looking:
			stop_looking()
		return
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_RIGHT:
			if event.pressed:
				looking = true
				Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
			else:
				stop_looking()
			get_viewport().set_input_as_handled()
		elif event.pressed and not cockpit and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
			var base := chase_base_distance()
			var step := 0.9 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 1.0 / 0.9
			chase_zoom = clampf(chase_zoom * step, CHASE_MIN / base, CHASE_MAX / base)
			get_viewport().set_input_as_handled()
	elif event is InputEventMouseMotion and looking:
		var d: Vector2 = event.relative * LOOK_SENSITIVITY
		if cockpit:
			head_yaw = clampf(head_yaw - d.x, -deg_to_rad(120.0), deg_to_rad(120.0))
			head_pitch = clampf(head_pitch - d.y, -deg_to_rad(60.0), deg_to_rad(60.0))
		else:
			orbit_yaw = wrapf(orbit_yaw - d.x, -PI, PI)
			orbit_pitch = clampf(orbit_pitch + d.y, deg_to_rad(-20.0), deg_to_rad(50.0))
		look_idle = 0.0
		get_viewport().set_input_as_handled()

func stop_looking() -> void:
	looking = false
	look_idle = 0.0
	if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

## Pivot height and default distance of the chase camera (as before mouse look existed:
## 5 m behind the bumper and 2.2 m above the roof, aimed just above the car).
func chase_base_distance() -> float:
	return Vector2(size.z * 0.5 + 5.0, size.y + 2.2 - size.y * 0.8).length()

func _process(delta: float) -> void:
	if body == null:
		return
	if not looking:
		look_idle += delta
		if look_idle > LOOK_RETURN_DELAY:
			var k := minf(1.0, delta * LOOK_RETURN_RATE)
			orbit_yaw = lerp_angle(orbit_yaw, 0.0, k)
			orbit_pitch = lerpf(orbit_pitch, 0.0, k)
			head_yaw = lerpf(head_yaw, 0.0, k)
			head_pitch = lerpf(head_pitch, 0.0, k)
	if inside:
		inside.rotation = Vector3(head_pitch, head_yaw, 0.0)
	# Chase camera: follows the direction of travel, smoothed, never parented to the body;
	# mouse look rotates it around the car.
	var xf := body.global_transform
	var back := xf.basis.z
	back.y = 0.0
	back = back.normalized()
	var dir := back.rotated(Vector3.UP, orbit_yaw)
	var pivot := xf.origin + Vector3.UP * (size.y * 0.8)
	var base_back := size.z * 0.5 + 5.0
	var elevation := clampf(atan2(size.y + 2.2 - size.y * 0.8, base_back) + orbit_pitch, deg_to_rad(-5.0), deg_to_rad(75.0))
	var dist := chase_base_distance() * chase_zoom
	var target := pivot + dir * cos(elevation) * dist + Vector3.UP * sin(elevation) * dist
	# Snappier while the player steers the view, the usual lag while driving.
	var follow := 14.0 if looking or look_idle < LOOK_RETURN_DELAY + 1.0 else 5.0
	chase.global_position = chase.global_position.lerp(target, minf(1.0, delta * follow))
	chase.look_at(pivot - dir * 4.0, Vector3.UP)
