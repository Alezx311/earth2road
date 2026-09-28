extends Node3D
## Streams the tiled world (game/data/<map>/index.json + tiles/*.json from tools/prepare.py).
## Tiles within FULL_RADIUS of the focus (player or spectator camera) are built in full with
## collisions; all others at "lod" level (ground, roads, buildings), so the whole map stays
## visible from above. Tiles are built on worker threads; collisions are added on the main
## thread within a per-frame time budget.

const World = preload("res://scripts/world.gd")
const FULL_RADIUS := 1000.0
const LOD_MARGIN := 250.0          # hysteresis before a full tile drops back to lod
const START_RADIUS := 600.0        # built before the first frame, around the spawn
const MAX_TASKS := 3
const COLLISION_BUDGET_MS := 3.0

var index: Dictionary
var folder: String
var tiles: Dictionary = {}         # name -> {"center", "level", "node", "busy"}
var jobs: Dictionary = {}          # WorkerThreadPool task id -> job
var collision_queue: Array = []
var signals_builder: Node3D
var focus := Vector3.ZERO
var schedule_clock := 0.0

static func map_id() -> String:
	var env := OS.get_environment("AKADEM_MAP")
	if env != "":
		return env
	if FileAccess.file_exists("res://data/active_map"):
		return FileAccess.get_file_as_string("res://data/active_map").strip_edges()
	return "akadem"

static func map_folder() -> String:
	return "res://data/%s/" % map_id()

static func load_index() -> Dictionary:
	var path := map_folder() + "index.json"
	if not FileAccess.file_exists(path):
		return {}
	return JSON.parse_string(FileAccess.get_file_as_string(path))

func start(source: Dictionary, at: Vector3) -> void:
	index = source
	folder = map_folder()
	focus = at
	World.shared()
	signals_builder = World.new()
	add_child(signals_builder)
	signals_builder.build({"signals": index.signals}, "signals")
	var size := float(index.tile_size)
	for name in index.tiles:
		var t: Array = index.tiles[name]
		tiles[name] = {"center": Vector3((t[0] + 0.5) * size, 0.0, (t[1] + 0.5) * size), "level": "", "node": null, "busy": false}
	add_backdrop()
	for name in tiles:
		if flat_distance(tiles[name].center, at) < START_RADIUS:
			install(name, "full", make(name, "full"))
	flush_collisions()

## Everything in full, synchronously (headless validation).
func build_all() -> void:
	for name in tiles:
		if tiles[name].level != "full":
			install(name, "full", make(name, "full"))
	flush_collisions()

func flush_collisions() -> void:
	for b in collision_queue:
		b.add_collisions(INF)
	collision_queue.clear()

func make(name: String, level: String) -> Node3D:
	var tile = JSON.parse_string(FileAccess.get_file_as_string(folder + "tiles/" + name + ".json"))
	var builder := World.new()
	builder.name = "%s_%s" % [name, level]
	builder.build(tile if tile is Dictionary else {}, level, false)
	return builder

func install(name: String, level: String, builder: Node3D) -> void:
	var t: Dictionary = tiles[name]
	if t.node:
		collision_queue.erase(t.node)
		t.node.queue_free()
	add_child(builder)
	t.node = builder
	t.level = level
	if level == "full":
		collision_queue.append(builder)
	else:
		builder.pending_collisions.clear()

func flat_distance(a: Vector3, b: Vector3) -> float:
	return Vector2(a.x - b.x, a.z - b.z).length()

func wanted(t: Dictionary) -> String:
	var d := flat_distance(t.center, focus)
	if t.level == "full":
		return "full" if d < FULL_RADIUS + LOD_MARGIN else "lod"
	return "full" if d < FULL_RADIUS else "lod"

func _process(delta: float) -> void:
	for id in jobs.keys():
		if not WorkerThreadPool.is_task_completed(id):
			continue
		WorkerThreadPool.wait_for_task_completion(id)
		var job: Dictionary = jobs[id]
		jobs.erase(id)
		var t: Dictionary = tiles[job.name]
		t.busy = false
		if wanted(t) == job.level:
			install(job.name, job.level, job.builder)
		else:
			job.builder.free()
	var start := Time.get_ticks_usec()
	while not collision_queue.is_empty():
		var left := COLLISION_BUDGET_MS - (Time.get_ticks_usec() - start) / 1000.0
		if left <= 0.0:
			break
		if collision_queue[0].add_collisions(left):
			collision_queue.pop_front()
	schedule_clock += delta
	if schedule_clock < 0.2 or jobs.size() >= MAX_TASKS:
		return
	schedule_clock = 0.0
	var todo: Array = []
	for name in tiles:
		var t: Dictionary = tiles[name]
		if not t.busy and wanted(t) != t.level:
			todo.append(name)
	todo.sort_custom(func(a, b): return flat_distance(tiles[a].center, focus) < flat_distance(tiles[b].center, focus))
	for name in todo:
		if jobs.size() >= MAX_TASKS:
			break
		var job := {"name": name, "level": wanted(tiles[name]), "builder": null}
		tiles[name].busy = true
		var id := WorkerThreadPool.add_task(build_job.bind(job), false, "tile " + name)
		jobs[id] = job

func build_job(job: Dictionary) -> void:
	job.builder = make(job.name, job.level)

## Tiles not yet built plus the area outside the map: one plain ground plane underneath.
func add_backdrop() -> void:
	var low := INF
	for lane in index.lanes:
		low = minf(low, float(lane.points[0][1]))
	var plane := PlaneMesh.new()
	plane.size = Vector2(60000, 60000)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color("68704f")
	mat.roughness = 1.0
	var inst := MeshInstance3D.new()
	inst.mesh = plane
	inst.material_override = mat
	inst.position = Vector3(0, (low if low < INF else 0.0) - 4.0, 0)
	inst.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(inst)

func pending() -> int:
	var n := 0
	for name in tiles:
		if wanted(tiles[name]) != tiles[name].level:
			n += 1
	return n

func update_signals(states: Dictionary) -> void:
	signals_builder.update_signals(states)

func _exit_tree() -> void:
	for id in jobs:
		WorkerThreadPool.wait_for_task_completion(id)
		if is_instance_valid(jobs[id].builder): jobs[id].builder.free()
	jobs.clear()
