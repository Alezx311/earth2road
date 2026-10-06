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
