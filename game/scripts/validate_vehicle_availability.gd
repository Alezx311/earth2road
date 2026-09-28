extends SceneTree
## Headless regression: configured models available, traffic_models matches,
## unknown unavailable / template empty, template and instantiate wheels for known names.

const Vehicles = preload("res://scripts/vehicles.gd")

var passed := true
var failures: Array = []

func _initialize() -> void:
	create_timer(30.0).timeout.connect(func(): print("VEHICLE_VALIDATION timeout"); quit(2))
	call_deferred("run")

func _record(label: String, cond: bool, detail: String = "") -> void:
	if not cond:
		passed = false
		failures.append({"label": label, "detail": detail})
		print("FAIL ", label, " ", detail)
	else:
		print("PASS ", label)

func _actual_membership(got: Array, want: Dictionary) -> bool:
	if got.size() != want.size():
		return false
	var got_set := {}
	for g in got:
		got_set[g] = true
	for w in want:
		if not got_set.has(w):
			return false
	return true

func run() -> void:
	var catalog := Vehicles.catalog()
	var models: Dictionary = catalog["models"]

	# 1. Configured models are available.
	for name in models:
		_record("configured_available_" + name, Vehicles.available(name), name)

	# 2. traffic_models matches configured models (actual membership).
	var traffic := Vehicles.traffic_models()
	_record("traffic_models_matches", _actual_membership(traffic, models),
		"traffic=%d models=%d" % [traffic.size(), models.size()])

	# 3. Unknown names are unavailable.
	for name in ["nonexistent", "foo", "unknown-model-99"]:
		_record("unknown_unavailable_" + name, not Vehicles.available(name), name)

	# 4. Template returns empty dict for unknown names.
	for name in ["nonexistent", "foo", "unknown-model-99"]:
		var t := Vehicles.template(name)
		_record("unknown_template_empty_" + name, t.is_empty(), name)

	# 5. Template and instantiate wheels for known names.
	var template_roots: Array = []
	for name in models:
		var t := Vehicles.template(name)
		_record("template_has_root_" + name, not t.is_empty() and t.has("root"), name)
		_record("template_has_wheels_" + name, t.has("wheels") and t["wheels"] is Array and t["wheels"].size() == 4, name)
		if not t.is_empty() and t.has("root") and t["root"] is Node3D:
			template_roots.append(t["root"])
		var inst := Vehicles.instantiate(name)
		_record("instantiate_has_wheels_" + name, not inst.is_empty() and inst.has("wheels") and inst["wheels"] is Array and inst["wheels"].size() == 4, name)
		_record("instantiate_has_root_" + name, not inst.is_empty() and inst.has("root"), name)
		if not inst.is_empty() and inst.has("root") and inst["root"] is Node3D:
			inst["root"].free()
		if not t.is_empty() and t.has("root") and t["root"] is Node3D:
			t["root"].free()

	# Free cached template roots.
	Vehicles.release_visual_templates()

	# Summary
	print("VEHICLE_VALIDATION ", JSON.stringify({"passed": passed, "failures": failures}, "  "))
	quit(0 if passed else 1)
