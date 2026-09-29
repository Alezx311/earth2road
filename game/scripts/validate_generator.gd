extends SceneTree
## Real generator run through the location picker: network error, Retry, Cancel and a
## complete small build. Needs network access and the project venv; it installs and
## activates a new map, so restore game/data/active_map afterwards. Not part of CI.
##   godot --path game --script res://scripts/validate_generator.gd -- --name "QA picker"
const LocationPicker = preload("res://scripts/location_picker.gd")
var failures: Array[String] = []
var picker: Control
var generated_id := ""
var output := "res://../logs/qa-20260929/generator"

func _initialize() -> void:
	call_deferred("run")

func check(condition: bool, message: String) -> void:
	print("GEN_CHECK ", "ok   " if condition else "FAIL ", message)
	if not condition:
		failures.append(message)

func arg(name: String, fallback: String) -> String:
	var args := OS.get_cmdline_user_args()
	var at := args.find(name)
	return args[at + 1] if at >= 0 and at + 1 < args.size() else fallback

func snap(name: String) -> void:
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(output.path_join(name + ".png"))

## Waits until the run ends or `until` returns true; returns elapsed seconds.
func wait(limit: float, until := Callable()) -> float:
	var t := 0.0
	while not picker.finished and t < limit:
		if until.is_valid() and until.call():
			break
		await create_timer(0.5).timeout
		t += 0.5
	return t

## A slightly different point per run: cached Overpass data would hide network errors.
func start() -> int:
	var jitter := float(int(Time.get_unix_time_from_system()) % 10000) * 0.000001
	picker.coords.text = arg("--at", "%.5f, %.5f" % [50.4427 + jitter, 30.5210 + jitter])
	picker.size_slider.value = 0.6
	picker.name_edit.text = arg("--name", "QA picker")
	picker.start_generation()
	return picker.pid

func run() -> void:
	DirAccess.make_dir_recursive_absolute(output)
	picker = LocationPicker.new()
	picker.generated.connect(func(id: String): generated_id = id)
	root.add_child(picker)
	await create_timer(0.5).timeout

	# 1. Network failure: an unreachable proxy makes every download fail for real.
	for key in ["HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"]:
		OS.set_environment(key, "http://127.0.0.1:9")
	var first := start()
	check(first > 0, "generator started")
	var took := await wait(600.0)
	print("GEN_TIME error %.1f s" % took)
	check(picker.finished and picker.had_error, "download failure reported as error")
	check(picker.status.text == tr("Could not build the map. Check your connection and retry."), "connection hint: %s" % picker.status.text)
	check(picker.generate_button.text == "Retry" and not picker.generate_button.disabled, "Retry offered")
	check(picker.name_edit.text == arg("--name", "QA picker"), "name preserved after error")
	check(not OS.is_process_running(first), "failed generator exited")
	picker.details.show()
	await snap("error")
	for key in ["HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"]:
		OS.unset_environment(key)

	# 2. Cancel during a real download.
	await create_timer(1.1).timeout     # next second: a new, uncached area
	var second := start()
	await wait(120.0, func(): return picker.progress.value > 0.0 or "Downloading" in picker.status.text or "Завантаж" in picker.status.text)
	await create_timer(3.0).timeout
	await snap("cancel-before")
	picker.back_or_cancel()
	took = await wait(30.0)
	print("GEN_TIME cancel %.1f s" % took)
	check(picker.finished and not picker.had_error, "cancel reported as cancelled")
	check(picker.status.text == tr("Generation cancelled"), "cancel status: %s" % picker.status.text)
	check(not OS.is_process_running(second), "cancelled generator exited")
	check(picker.back_button.text == "Back" and not picker.back_button.disabled, "Back restored after cancel")

	# 3. Complete build of a new small map.
	await create_timer(1.1).timeout
	var third := start()
	var stages := {}
	var t := 0.0
	while not picker.finished and t < 1800.0:
		stages[picker.status.text] = true
		if t == 30.0: await snap("build-progress")
		await create_timer(0.5).timeout
		t += 0.5
	print("GEN_TIME build %.1f s" % t)
	print("GEN_STATUSES ", stages.keys())
	await create_timer(0.5).timeout
	check(generated_id != "", "map generated: %s (%s)" % [generated_id, picker.status.text])
	check(FileAccess.file_exists("res://data/%s/index.json" % generated_id), "map installed")
	check(not OS.is_process_running(third), "generator exited after success")
	check(stages.keys().all(func(s: String): return not " · " in s or s.begins_with("Done") or s.begins_with("Готово")), "no technical phase · stage status")
	await snap("done")
	print("GEN_VALIDATION ", JSON.stringify({"passed": failures.is_empty(), "failures": failures, "id": generated_id}))
	quit(0 if failures.is_empty() else 1)
