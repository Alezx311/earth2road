extends SceneTree
## Headless driving checks for the player car (GEVP physics on the generated world).
## Writes logs/drive_validation.json; exit code 1 if any scenario fails.

const WorldStream = preload("res://scripts/world_stream.gd")
const Player = preload("res://scripts/player.gd")

var world: Node3D
var player: Node3D
var data: Dictionary
var results: Dictionary = {}

func _initialize() -> void:
	# A script error leaves the coroutine suspended; never hang the check.
	create_timer(300.0).timeout.connect(func(): print("DRIVE_VALIDATION timeout"); quit(2))
	call_deferred("run")

func lane(id: String) -> Dictionary:
	for l in data.lanes:
		if l.id == id:
			return l
	return {}

## Point and heading (degrees, clockwise from north) `back` metres before the lane end.
func before_end(l: Dictionary, back: float) -> Array:
	var pts: Array = l.points
	var remaining := back
	for i in range(pts.size() - 1, 0, -1):
		var b := Vector3(pts[i][0], pts[i][1], pts[i][2])
		var a := Vector3(pts[i - 1][0], pts[i - 1][1], pts[i - 1][2])
		var d := Vector2(b.x - a.x, b.z - a.z).length()
		if remaining <= d:
			var p := b.lerp(a, remaining / d)
			return [p, heading(a, b)]
		remaining -= d
	var a0 := Vector3(pts[0][0], pts[0][1], pts[0][2])
	return [a0, heading(a0, Vector3(pts[1][0], pts[1][1], pts[1][2]))]

func heading(a: Vector3, b: Vector3) -> float:
	# Godot: north = -Z. Clockwise from north like SUMO.
	return fposmod(rad_to_deg(atan2(b.x - a.x, -(b.z - a.z))), 360.0)

var watch: Node3D = null

## Collision layer of whatever is under the car centre (for kerb/pavement checks).
func ground_layer() -> int:
	var from: Vector3 = player.pos + Vector3.UP * 1.0
	var q := PhysicsRayQueryParameters3D.create(from, from + Vector3.DOWN * 3.0, 1 | 2 | 4 | 8)
	var space: PhysicsDirectSpaceState3D = player.body.get_world_3d().direct_space_state
	var hit := space.intersect_ray(q)
	return 0 if hit.is_empty() else int(hit.collider.collision_layer)

func drive(seconds: float, throttle: bool, steer := 0.0) -> Dictionary:
	var start: Vector3 = player.pos
	var on_pavement := 0
	var min_dist := INF
	var max_rise := 0.0
	var min_speed_after := INF
	var t := 0.0
	if throttle:
		Input.action_press("Throttle")
	if steer > 0.0:
		Input.action_press("Steer Right", steer)
	elif steer < 0.0:
		Input.action_press("Steer Left", -steer)
	while t < seconds:
		await physics_frame
		t += 1.0 / Engine.physics_ticks_per_second
		max_rise = maxf(max_rise, player.pos.y - start.y)
		if ground_layer() == 8:
			on_pavement += 1
		if watch:
			min_dist = minf(min_dist, player.pos.distance_to(watch.global_position))
		if t > seconds * 0.5:
			min_speed_after = minf(min_speed_after, absf(player.speed))
	for a in ["Throttle", "Steer Right", "Steer Left"]:
		Input.action_release(a)
	var end: Vector3 = player.pos
	return {"start": [start.x, start.y, start.z], "end": [end.x, end.y, end.z], "travel": Vector2(end.x - start.x, end.z - start.z).length(), "max_rise": max_rise, "final_speed_kmh": absf(player.speed) * 3.6, "min_speed_second_half_kmh": min_speed_after * 3.6, "pavement_frames": on_pavement, "min_distance_to_obstacle": min_dist if watch else -1.0}

func place(at: Vector3, heading_deg: float, speed := 0.0) -> void:
	player.spawn(at, heading_deg)
	for i in range(30):
		await physics_frame
	if speed > 0.0:
		player.body.linear_velocity = -player.body.global_transform.basis.z * speed

func run() -> void:
	data = WorldStream.load_index()
	world = WorldStream.new()
	root.add_child(world)
	var sp: Array = data.spawn.position
	world.start(data, Vector3(sp[0], sp[1], sp[2]))
	world.build_all()
	player = Player.new()
	root.add_child(player)
	await physics_frame
	var spawn_lane := lane(data.spawn.lane)
	var p: Array = data.spawn.position
	var spawn := Vector3(p[0], p[1], p[2])

	# 1. From 30 m before the stop line, full throttle: must cross into the junction.
	var s1 := before_end(spawn_lane, 30.0)
	await place(s1[0], s1[1])
	var r1 := await drive(7.0, true)
	r1.passed = r1.travel > 45.0 and r1.min_speed_second_half_kmh > 15.0
	results.stop_line = r1

	# 2. From the spawn point, 15 s full throttle along the road.
	await place(spawn, float(data.spawn.angle))
	var r2 := await drive(15.0, true)
	r2.passed = r2.travel > 100.0
	results.long_drive = r2

	# 2b. Standing still without input must not roll (hold brake), even on a slope.
	await place(spawn, float(data.spawn.angle))
	var r5 := await drive(8.0, false)
	r5.passed = r5.travel < 0.5
	results.standstill_hold = r5

	# 2c. Holding S from a stop engages reverse and backs up.
	Input.action_press("Brakes")
	var r6 := await drive(5.0, false)
	Input.action_release("Brakes")
	r6.gear = player.body.current_gear
	var back_dir: Vector3 = player.body.global_transform.basis.z
	var moved := Vector3(r6.end[0] - r6.start[0], 0, r6.end[2] - r6.start[2])
	r6.backwards = moved.dot(back_dir)
	r6.passed = r6.backwards > 3.0 and r6.final_speed_kmh < 25.0
	results.reverse = r6

	# 3. Kerb: from the rightmost lane turn 35° right towards the pavement at ~20 km/h.
	var s3 := before_end(spawn_lane, 120.0)
	await place(s3[0], fposmod(float(s3[1]) + 35.0, 360.0), 5.5)
	var r3 := await drive(4.0, true)
	r3.passed = r3.pavement_frames > 20 and r3.travel > 10.0
	results.kerb = r3

	# 4. A kinematic traffic car 15 m ahead: the player hits it and keeps simulating.
	var s4 := before_end(spawn_lane, 90.0)
	await place(s4[0], s4[1])
	var obstacle := AnimatableBody3D.new()
	obstacle.collision_layer = 16
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(1.8, 1.4, 4.5)
	shape.shape = box
	shape.position.y = 0.7
	obstacle.add_child(shape)
	var ahead: Vector3 = -player.body.global_transform.basis.z
	obstacle.transform = Transform3D(Basis(Vector3.UP, player.yaw), player.pos + ahead * 15.0)
	root.add_child(obstacle)
	watch = obstacle
	await physics_frame
	var before: int = player.contacts
	var r4 := await drive(5.0, true)
	r4.contacts = player.contacts - before
	r4.passed = r4.contacts > 0 and absf(player.pos.y - s4[0].y) < 3.0 and is_finite(player.speed)
	results.traffic_collision = r4

	var passed := true
	for k in results:
		passed = passed and results[k].passed
	results.passed = passed
	var f := FileAccess.open("res://../logs/drive_validation.json", FileAccess.WRITE)
	f.store_string(JSON.stringify(results, "  "))
	print("DRIVE_VALIDATION ", JSON.stringify(results))
	quit(0 if passed else 1)
