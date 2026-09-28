extends Camera3D
## Spectator camera: orbits a point on the ground (strategy-game style).
## WASD / arrows move the point along the view direction, speed grows with distance;
## wheel or Q/E zoom (3 m ... 6 km); right mouse drag rotates and tilts, middle drag pans;
## Z/X rotate; Shift = faster. The point follows the ground by a ray down the colliders.

const MIN_DISTANCE := 3.0
const MAX_DISTANCE := 6000.0
const MASK_GROUND := 1 | 2 | 4

var focus := Vector3.ZERO
var heading := 0.0            # radians, 0 = looking towards -Z
var tilt := deg_to_rad(-50.0)
var distance := 120.0
var target_distance := 120.0
var active := false
var dragging := false
var panning := false

## Same shape as the player for the minimap: position and yaw.
var pos: Vector3:
	get:
		return focus

var yaw: float:
	get:
		return heading

func _ready() -> void:
	far = 20000.0
	fov = 60.0

func start(at: Vector3, yaw_rad: float, from_distance := 120.0) -> void:
	focus = at
	heading = yaw_rad
	distance = from_distance
	target_distance = from_distance
	active = true
	current = true
	place()

func stop() -> void:
	active = false
	dragging = false
	panning = false
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func _unhandled_input(event: InputEvent) -> void:
	if not active:
		return
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			target_distance = maxf(MIN_DISTANCE, target_distance / 1.18)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			target_distance = minf(MAX_DISTANCE, target_distance * 1.18)
		elif event.button_index == MOUSE_BUTTON_RIGHT:
			dragging = event.pressed
		elif event.button_index == MOUSE_BUTTON_MIDDLE:
			panning = event.pressed
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if dragging or panning else Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseMotion:
		if dragging:
			heading -= event.relative.x * 0.004
			tilt = clampf(tilt - event.relative.y * 0.004, deg_to_rad(-89.0), deg_to_rad(-3.0))
		elif panning:
			var scale := distance * 0.0015
			var basis := Basis(Vector3.UP, heading)
			focus += basis.x * (-event.relative.x * scale) + basis.z * (-event.relative.y * scale)

func _process(delta: float) -> void:
	if not active:
		return
	var fast := 4.0 if Input.is_key_pressed(KEY_SHIFT) else 1.0
	var move := Vector2.ZERO
	if Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP): move.y -= 1
	if Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN): move.y += 1
	if Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT): move.x -= 1
	if Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT): move.x += 1
	if Input.is_key_pressed(KEY_Q): target_distance = minf(MAX_DISTANCE, target_distance * (1.0 + 1.5 * delta * fast))
	if Input.is_key_pressed(KEY_E): target_distance = maxf(MIN_DISTANCE, target_distance / (1.0 + 1.5 * delta * fast))
	if Input.is_key_pressed(KEY_Z): heading += 1.2 * delta
	if Input.is_key_pressed(KEY_X): heading -= 1.2 * delta
	if move != Vector2.ZERO:
		var basis := Basis(Vector3.UP, heading)
		var speed := maxf(8.0, distance * 1.2) * fast
		focus += (basis.x * move.x + basis.z * move.y).normalized() * speed * delta
	distance = lerpf(distance, target_distance, minf(1.0, delta * 8.0))
	follow_ground(delta)
	place()

func follow_ground(delta: float) -> void:
	var space := get_world_3d().direct_space_state
	var query := PhysicsRayQueryParameters3D.create(focus + Vector3.UP * 2000.0, focus + Vector3.DOWN * 2000.0, MASK_GROUND)
	var hit := space.intersect_ray(query)
	if hit:
		focus.y = lerpf(focus.y, hit.position.y, minf(1.0, delta * 6.0))

func place() -> void:
	var dir := Basis(Vector3.UP, heading) * Basis(Vector3.RIGHT, tilt) * Vector3.FORWARD
	global_position = focus - dir * distance
	look_at(focus, Vector3.UP)
	near = clampf(distance * 0.002, 0.05, 4.0)
