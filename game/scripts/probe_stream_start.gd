extends SceneTree
## Isolated benchmark: loads an export directly, without installing/activating a map.

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var folder := OS.get_environment("E2R_PROBE_FOLDER")
	var data = JSON.parse_string(FileAccess.get_file_as_string(folder.path_join("index.json")))
	if not data is Dictionary or not data.has("spawn"):
		quit(1)
		return
	var WorldStream = load("res://scripts/world_stream.gd")
	var world = WorldStream.new()
	root.add_child(world)
	world.set_process(false)
	var p: Array = data.spawn.position
	var position := Vector3(p[0], p[1], p[2])
	var start := Time.get_ticks_usec()
	world.start(data, position, folder)
	var build_ms := (Time.get_ticks_usec() - start) / 1000.0
	for _i in range(3):
		await physics_frame
	var space: PhysicsDirectSpaceState3D = world.get_world_3d().direct_space_state
	var query := PhysicsRayQueryParameters3D.create(position + Vector3.UP * 0.8, position - Vector3.UP * 0.8, 1)
	var hit := space.intersect_ray(query)
	print("STREAM_START ", JSON.stringify({"build_and_collision_ms": build_ms,
		"start_metrics": world.start_metrics,
		"physics_ready_ms": (Time.get_ticks_usec() - start) / 1000.0,
		"spawn_supported": not hit.is_empty(), "tiles": world.tiles.size(),
		"memory_static_bytes": OS.get_static_memory_usage(), "interactive_control_verified": false}))
	world.queue_free()
	await process_frame
	quit(0 if not hit.is_empty() else 1)
