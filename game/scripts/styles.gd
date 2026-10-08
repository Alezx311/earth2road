extends RefCounted
## Texture styles (config/visuals/texture_styles.json): the look of facades switched at run
## time through the global shader uniform `facade_style` (shaders/facade.gdshader), without
## rebuilding tiles. The choice is kept in user://settings.cfg [visuals] texture_style.

const CONFIG := "res://../config/visuals/texture_styles.json"
const TEXTURES := "res://assets/textures/"
const SETTINGS := "user://settings.cfg"

static var _config: Dictionary = {}

static func config() -> Dictionary:
	if _config.is_empty():
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(ProjectSettings.globalize_path(CONFIG)))
		_config = parsed if parsed is Dictionary else {"default": "procedural", "styles": [{"id": "procedural", "facade_style": 0, "requires": []}]}
	return _config

## Styles whose textures are all installed, in config order.
static func available() -> Array:
	var out: Array = []
	for style in config().styles:
		var ok := true
		for set_name in style.get("requires", []):
			if not FileAccess.file_exists("%s%s/albedo.jpg" % [TEXTURES, set_name]):
				ok = false
		if ok:
			out.append(style)
	return out

static func find(id: String) -> Dictionary:
	for style in available():
		if style.id == id:
			return style
	return {}

static func current() -> String:
	var cfg := ConfigFile.new()
	var saved := ""
	if cfg.load(SETTINGS) == OK:
		saved = str(cfg.get_value("visuals", "texture_style", ""))
	for id in [saved, str(config().get("default", "")), "procedural"]:
		if not find(id).is_empty():
			return id
	return "procedural"

static func label(id: String, locale: String) -> String:
	var names: Dictionary = find(id).get("name", {})
	return str(names.get(locale, names.get("en", id)))

static func apply(id: String, remember := false) -> void:
	var style := find(id)
	if style.is_empty():
		return
	RenderingServer.global_shader_parameter_set("facade_style", int(style.facade_style))
	if remember:
		var cfg := ConfigFile.new()
		cfg.load(SETTINGS)
		cfg.set_value("visuals", "texture_style", id)
		cfg.save(SETTINGS)

## Next available style after the current one; applied and remembered.
static func cycle() -> String:
	var list := available()
	var ids: Array = list.map(func(s): return s.id)
	var next: String = ids[(ids.find(current()) + 1) % ids.size()]
	apply(next, true)
	return next
