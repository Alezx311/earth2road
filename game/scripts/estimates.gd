extends RefCounted
## Run-time estimates for the picker and the BeamNG export (akadem_maps/estimates.py).
## tools/estimate.py prints the coefficients once per dialog, calibrated by this machine's
## logs/timings.jsonl; the dialogs multiply by the size, so sliders update instantly.

## Same base as akadem_maps/estimates.py BASE, used when Python cannot be run.
const FALLBACK := {
	"build": {
		"legacy": {"overhead": [0.5, 2.0], "rate": [0.3, 1.6], "runs": 0},
		"v2": {"overhead": [2.0, 6.0], "rate": [3.5, 11.0], "runs": 0},
	},
	"export": {
		"compact": {"overhead": [0.5, 2.0], "rate": [0.04, 0.17], "runs": 0},
		"balanced": {"overhead": [0.5, 2.0], "rate": [0.06, 0.25], "runs": 0},
	},
}

static var table: Dictionary = {}

## Re-reads the coefficients (a finished run may have changed them).
static func load_table(root: String) -> void:
	table = FALLBACK
	var python := root + ("/.venv/Scripts/python.exe" if OS.get_name() == "Windows" else "/.venv/bin/python")
	if not FileAccess.file_exists(python):
		return
	var output := []
	if OS.execute(python, [root + "/tools/estimate.py"], output) != 0 or output.is_empty():
		return
	var parsed = JSON.parse_string(str(output[0]).strip_edges())
	if parsed is Dictionary and parsed.has("build") and parsed.has("export"):
		table = parsed

static func entry(kind: String, mode: String) -> Dictionary:
	var modes: Dictionary = (table if not table.is_empty() else FALLBACK)[kind]
	if modes.has(mode):
		return modes[mode]
	return modes["balanced" if kind == "export" else "legacy"]

## [low, high] minutes; size is km² for a build and tiles for an export.
static func minutes(kind: String, mode: String, size: float) -> Vector2:
	var e := entry(kind, mode)
	return Vector2(float(e.overhead[0]) + float(e.rate[0]) * size, float(e.overhead[1]) + float(e.rate[1]) * size)

static func span(m: Vector2) -> String:
	if m.y >= 90.0:
		return TranslationServer.translate("≈ %.1f–%.1f h") % [m.x / 60.0, m.y / 60.0]
	return TranslationServer.translate("≈ %d–%d min") % [maxi(1, roundi(m.x)), maxi(1, roundi(m.y))]

## "≈ 5–18 min" plus where the numbers come from.
static func text(kind: String, mode: String, size: float) -> String:
	var runs := int(entry(kind, mode).get("runs", 0))
	var source: String = TranslationServer.translate("from %d of your runs") % runs if runs > 0 \
		else TranslationServer.translate("rough; dense centres take longest")
	return "%s (%s)" % [span(minutes(kind, mode, size)), source]
