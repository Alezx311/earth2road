extends SceneTree
## Actual GEVP car follows three map routes with steering/throttle. No teleporting
## during a run. Includes a stop/hold and reverse check; rural roads need no kerbs.
const WorldStream = preload("res://scripts/world_stream.gd")
const Player = preload("res://scripts/player.gd")
var player: Node3D
var world: Node3D
var data: Dictionary

func _initialize() -> void:
	create_timer(900).timeout.connect(func(): quit(2))
	call_deferred("run")

func v(p: Array) -> Vector3:
	return Vector3(p[0],p[1],p[2])

func release() -> void:
	for a in ["Throttle","Brakes","Steer Left","Steer Right"]:
		Input.action_release(a)

func follow(route: Dictionary) -> Dictionary:
	var points: Array = route.points
	var start := v(points[0])
	var forward := v(points[1])-start
	player.spawn(start,rad_to_deg(atan2(forward.x,-forward.z)))
	for i in range(60): await physics_frame
	var i := 0
	var travel := 0.0
	var previous: Vector3 = player.pos
	var offroad := 0
	var max_deviation := 0.0
	var elapsed := 0.0
	var before: int = player.contacts
	while elapsed < 150.0 and travel < 350.0 and i < points.size()-3:
		var nearest := i
		var best := INF
		for j in range(i,mini(i+15,points.size()-1)):
			var a := v(points[j]); a.y = player.pos.y
			var b := v(points[j+1]); b.y = player.pos.y
			var q := Geometry3D.get_closest_point_to_segment(player.pos,a,b)
			var d: float = player.pos.distance_to(q)
			if d < best:
				best = d; nearest = j
		i = nearest
		max_deviation = maxf(max_deviation,best)
		if best > 12.0: break
		var a := v(points[i]); a.y=player.pos.y
		var b := v(points[i+1]); b.y=player.pos.y
		var target_pos := Geometry3D.get_closest_point_to_segment(player.pos,a,b)
		var remaining := 4.0
		for j in range(i+1,points.size()):
			var next := v(points[j]); next.y=player.pos.y
			var distance := target_pos.distance_to(next)
			if distance >= remaining:
				target_pos=target_pos.lerp(next,remaining/maxf(distance,0.001))
				break
			remaining-=distance
			target_pos=next
		var local: Vector3 = player.body.global_transform.basis.inverse()*(target_pos-player.pos)
		var angle := atan2(local.x,-local.z)
		var desired := 4.5 if absf(angle)<0.2 else 2.8
		release()
		if player.speed < desired:
			Input.action_press("Throttle",0.55)
		elif player.speed > desired+1.0:
			Input.action_press("Brakes",0.22)
		var steering := atan(5.2*sin(angle)/maxf(local.length(),1.0))/deg_to_rad(36.0)
		Input.action_press("Steer Right" if steering>0 else "Steer Left",clampf(absf(steering),0,1.0))
		await physics_frame
		elapsed+=1.0/Engine.physics_ticks_per_second
		travel+=player.pos.distance_to(previous)
		previous=player.pos
		var ray := PhysicsRayQueryParameters3D.create(player.pos+Vector3.UP,player.pos-Vector3.UP*2,1)
		if world.get_world_3d().direct_space_state.intersect_ray(ray).is_empty(): offroad+=1
	release()
	return {"travel_m":travel,"seconds":elapsed,"max_deviation_m":max_deviation,"offroad_frames":offroad,
		"contacts":player.contacts-before,"passed":travel>250 and max_deviation<6 and offroad<120}

func run() -> void:
	data=WorldStream.load_index()
	world=WorldStream.new(); root.add_child(world)
	world.start(data,v(data.spawn.position)); world.set_process(false); world.build_all()
	player=Player.new(); root.add_child(player)
	await physics_frame
	var report := {"routes":[],"passed":true}
	for route in data.validation_routes.slice(0,3):
		var result := await follow(route)
		report.routes.append(result)
		report.passed = report.passed and result.passed
		print("RURAL_ROUTE ",JSON.stringify(result))
	player.spawn(v(data.spawn.position),float(data.spawn.angle))
	for i in range(60): await physics_frame
	var at: Vector3=player.pos
	for i in range(600): await physics_frame
	report.hold_m=player.pos.distance_to(at)
	report.passed=report.passed and report.hold_m<0.5
	var back: Vector3=player.body.global_transform.basis.z
	at=player.pos
	Input.action_press("Brakes")
	for i in range(480): await physics_frame
	release()
	report.reverse_m=(player.pos-at).dot(back)
	report.passed=report.passed and report.reverse_m>3
	FileAccess.open("res://../logs/rivne_drive_validation.json",FileAccess.WRITE).store_string(JSON.stringify(report,"  "))
	print("RURAL_DRIVE ",JSON.stringify(report))
	player.queue_free(); world.queue_free()
	await process_frame
	quit(0 if report.passed else 1)
