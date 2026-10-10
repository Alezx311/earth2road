extends RefCounted
## Materials for the generated district. Uses CC0 textures from res://assets/textures
## (tools/fetch_textures.py) when present, otherwise flat colours, so the game still
## runs offline without the optional texture download.

const SURFACE := preload("res://shaders/surface.gdshader")
const PAINT := preload("res://shaders/paint.gdshader")
const FACADE := preload("res://shaders/facade.gdshader")
const TEXTURES := "res://assets/textures/"

static var _noise: NoiseTexture2D
static var _textures: Dictionary = {}

static func noise() -> NoiseTexture2D:
	if _noise == null:
		var n := FastNoiseLite.new()
		n.seed = 311
		n.frequency = 0.02
		n.fractal_octaves = 4
		_noise = NoiseTexture2D.new()
		_noise.width = 512
		_noise.height = 512
		_noise.seamless = true
		_noise.generate_mipmaps = true
		_noise.noise = n
	return _noise

static func texture(set_name: String, map: String) -> Texture2D:
	var path := "%s%s/%s.jpg" % [TEXTURES, set_name, map]
	if not FileAccess.file_exists(path):
		return null
	if _textures.has(path):
		return _textures[path]
	var image := Image.load_from_file(ProjectSettings.globalize_path(path))
	if image == null:
		return null
	# Photo sets come at 2K for the colour; their relief and roughness read the same at 1K.
	if map != "albedo" and image.get_width() > 1024:
		image.resize(1024, 1024 * image.get_height() / image.get_width(), Image.INTERPOLATE_LANCZOS)
	image.generate_mipmaps()
	_textures[path] = ImageTexture.create_from_image(image)
	return _textures[path]

static func surface(set_name: String, tile: float, tint: Color, flat: Color, options := {}) -> ShaderMaterial:
	var m := ShaderMaterial.new()
	m.shader = SURFACE
	var albedo := texture(set_name, "albedo") if set_name != "" else null
	m.set_shader_parameter("has_textures", albedo != null)
	if albedo != null:
		m.set_shader_parameter("albedo_tex", albedo)
		m.set_shader_parameter("normal_tex", texture(set_name, "normal"))
		m.set_shader_parameter("roughness_tex", texture(set_name, "roughness"))
	m.set_shader_parameter("macro_noise", noise())
	m.set_shader_parameter("tile_metres", tile)
	m.set_shader_parameter("tint", tint)
	m.set_shader_parameter("flat_color", flat)
	for key in options:
		m.set_shader_parameter(key, options[key])
	return m

## Photo ground of the realistic texture style (surface.gdshader photo branch, shown while
## the global facade_style is 1): [base set, metres], [patch set, metres, cover],
## [wear set, metres, cover]. Left off when a set is missing (tools/fetch_textures.py).
static func photo_ground(m: ShaderMaterial, base: Array, patch: Array, wear: Array, tint := Color.WHITE) -> void:
	for layer in [base, patch, wear]:
		if texture(layer[0], "albedo") == null:
			return
	m.set_shader_parameter("photo_ground", true)
	for pair in [["base", base], ["patch", patch], ["wear", wear]]:
		for map in ["albedo", "normal", "roughness"]:
			m.set_shader_parameter("%s_%s" % [pair[0], map], texture(pair[1][0], map))
	m.set_shader_parameter("layer_metres", Vector3(base[1], patch[1], wear[1]))
	m.set_shader_parameter("layer_cover", Vector2(patch[2], wear[2]))
	m.set_shader_parameter("photo_tint", tint)

static func make() -> Dictionary:
	var mats := {}
	mats.road = surface("asphalt", 5.0, Color(1.55, 1.55, 1.6), Color("3c4145"), {"macro_strength": 0.22, "macro_metres": 60.0, "normal_strength": 0.7, "roughness_bias": 0.15})
	mats.parking = surface("asphalt", 5.0, Color(1.75, 1.72, 1.7), Color("4a4d50"), {"macro_strength": 0.28})
	mats.sidewalk = surface("paving", 2.5, Color(0.95, 0.95, 1.0), Color("9a9790"), {"macro_strength": 0.15})
	mats.path = surface("paving", 2.0, Color(0.9, 0.88, 0.86), Color("8f8b83"), {"macro_strength": 0.2})
	mats.curb = surface("concrete", 1.0, Color(0.85, 0.85, 0.85), Color("b3b1ab"))
	mats.bridge = surface("concrete", 3.0, Color(0.72, 0.72, 0.72), Color("8d8c88"), {"macro_strength": 0.25})
	mats.ground = surface("ground", 4.0, Color(0.72, 0.78, 0.62), Color("6f7457"), {"macro_strength": 0.3, "macro_tint": Color(0.75, 0.95, 0.6), "roughness_bias": 0.25})
	mats.green = surface("grass", 3.0, Color(0.9, 0.95, 0.85), Color("587a45"), {"macro_strength": 0.25, "macro_tint": Color(1.15, 1.05, 0.7), "roughness_bias": 0.25})
	mats.wood = surface("grass", 3.0, Color(0.62, 0.72, 0.58), Color("3f5a36"), {"macro_strength": 0.3, "roughness_bias": 0.25})
	mats.water = surface("", 1.0, Color.WHITE, Color("3d5e6b"), {"roughness_bias": -0.8})
	# Sports grounds (playtest 2026-10-06, note 9): a brighter mown pitch and a tartan track.
	mats.pitch = surface("grass", 2.0, Color(1.05, 1.2, 0.85), Color("4f8a3c"), {"macro_strength": 0.12, "roughness_bias": 0.2})
	mats.track = surface("", 1.0, Color.WHITE, Color("9a4a3a"), {"macro_strength": 0.1, "roughness_bias": 0.1})
	mats.roof = surface("gravel", 3.0, Color(0.42, 0.42, 0.43), Color("5b5d5f"), {"macro_strength": 0.2})
	mats.dirt = surface("ground", 3.0, Color(1.0, 0.88, 0.7), Color("9b896c"), {"macro_strength":0.2})
	mats.gravel = surface("gravel", 2.0, Color(0.95, 0.88, 0.73), Color("a99e87"), {"normal_strength":0.9})
	mats.yard = surface("ground", 4.0, Color(0.85,0.85,0.7), Color("8e8c70"))
	mats.orchard = surface("grass", 3.0, Color(0.85,0.88,0.7), Color("6a7945"))
	# Realistic ground (texture style "panelka"): Kyiv lawns are clover and weeds with worn
	# turf; the fill between streets and verges is patchy mossy grass; yards are trodden soil.
	photo_ground(mats.green, ["photo_lawn", 3.0], ["photo_meadow", 3.5, 0.3], ["photo_worn", 3.0, 0.08], Color(0.86, 0.88, 0.8))
	photo_ground(mats.ground, ["photo_lawn", 3.0], ["photo_verge", 3.5, 0.35], ["photo_worn", 3.0, 0.14], Color(0.9, 0.88, 0.76))
	photo_ground(mats.wood, ["photo_meadow", 3.5], ["photo_verge", 3.5, 0.35], ["photo_worn", 3.0, 0.06], Color(0.78, 0.82, 0.74))
	photo_ground(mats.orchard, ["photo_lawn", 3.0], ["photo_verge", 3.5, 0.35], ["photo_worn", 3.0, 0.1], Color(0.88, 0.88, 0.78))
	photo_ground(mats.yard, ["photo_trodden", 3.0], ["photo_worn", 3.0, 0.45], ["photo_lawn", 3.0, 0.15], Color(0.9, 0.88, 0.84))
	photo_ground(mats.dirt, ["photo_trodden", 3.0], ["photo_worn", 3.0, 0.3], ["photo_verge", 3.5, 0.08], Color(0.92, 0.88, 0.82))
	# Synthwave look of each surface (surface.gdshader synth_kind; facade_style 2).
	var synth := {"road": 1, "parking": 1, "bridge": 1, "track": 1, "sidewalk": 2, "path": 2, "curb": 2,
		"ground": 0, "dirt": 0, "yard": 0, "gravel": 0, "green": 5, "wood": 5, "orchard": 5, "pitch": 5, "water": 4}
	for key in synth:
		mats[key].set_shader_parameter("synth_kind", synth[key])
	for kind in ["farmland", "garden"]:
		var field := ShaderMaterial.new()
		field.shader = preload("res://shaders/field.gdshader")
		field.set_shader_parameter("base_color", Color("b1a264") if kind == "farmland" else Color("7c8050"))
		mats[kind] = field
	mats.roof_tile = surface("", 1.0, Color.WHITE, Color("97604b"), {"macro_strength":0.12})
	mats.roof_metal = surface("", 1.0, Color.WHITE, Color("737e80"), {"roughness_bias":-0.1})
	mats.fence = surface("concrete", 2.0, Color(1.0,0.95,0.85), Color("aea99b"), {"macro_strength":0.15})
	var paint := ShaderMaterial.new()
	paint.shader = PAINT
	paint.set_shader_parameter("wear_noise", noise())
	paint.render_priority = 1
	mats.mark = paint
	var facade := ShaderMaterial.new()
	facade.shader = FACADE
	facade.set_shader_parameter("wall_noise", noise())
	var wall_normal := texture("concrete", "normal")
	facade.set_shader_parameter("has_normal", wall_normal != null)
	if wall_normal != null:
		facade.set_shader_parameter("wall_normal", wall_normal)
	var panels := texture("panelka_panels", "albedo")
	facade.set_shader_parameter("has_panels", panels != null)
	if panels != null:
		facade.set_shader_parameter("panels", panels)
	var loggias := texture("panelka_loggias", "albedo")
	facade.set_shader_parameter("has_loggias", loggias != null)
	if loggias != null:
		facade.set_shader_parameter("loggia_atlas", loggias)
	var plaster := texture("panelka_plaster", "albedo")
	facade.set_shader_parameter("has_plaster", plaster != null)
	if plaster != null:
		facade.set_shader_parameter("plaster", plaster)
	var red := texture("panelka_brick_red", "albedo")
	var white := texture("panelka_brick_white", "albedo")
	facade.set_shader_parameter("has_bricks", red != null and white != null)
	if red != null and white != null:
		facade.set_shader_parameter("brick_red", red)
		facade.set_shader_parameter("brick_white", white)
		facade.set_shader_parameter("brick_red_normal", texture("panelka_brick_red", "normal"))
		facade.set_shader_parameter("brick_white_normal", texture("panelka_brick_white", "normal"))
	mats.facade = facade
	mats.shopfront = facade
	var pole := StandardMaterial3D.new()
	pole.albedo_color = Color("5d6468")
	pole.metallic = 0.6
	pole.roughness = 0.45
	mats.pole = pole
	var housing := StandardMaterial3D.new()
	housing.albedo_color = Color("1b1f22")
	housing.roughness = 0.6
	mats.signal_housing = housing
	return mats
