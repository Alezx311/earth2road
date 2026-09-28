extends SceneTree

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var WorldStream = load("res://scripts/world_stream.gd")
	var world = WorldStream.new()
	root.add_child(world)
	var data: Dictionary=WorldStream.load_index()
	var sp: Array=data.spawn.position
	world.start(data,Vector3(sp[0],sp[1],sp[2]))
	world.build_all()
	for _i in range(12):
		await physics_frame
	var space: PhysicsDirectSpaceState3D=world.get_world_3d().direct_space_state
	var results: Array=[]
	var misses:=0
	for route in data.validation_routes:
		var failed: Array=[]
		var checked:=0
		for p in route.points:
			var position:=Vector3(p[0],p[1],p[2])
			var query:=PhysicsRayQueryParameters3D.create(position+Vector3.UP*0.8,position-Vector3.UP*0.8,1)
			var hit:=space.intersect_ray(query)
			checked+=1
			if hit.is_empty():
				failed.append(p)
		misses+=failed.size()
		results.append({"checked":checked,"missing_surface":failed.size(),"examples":failed.slice(0,8),"edges":route.edges})
	var output={"routes":results,"missing_total":misses,"passed":misses==0}
	var file:=FileAccess.open("res://../logs/surface_validation.json",FileAccess.WRITE)
	file.store_string(JSON.stringify(output,"  "))
	print("SURFACE_VALIDATION ",JSON.stringify(output))
	quit(0 if misses==0 else 1)
