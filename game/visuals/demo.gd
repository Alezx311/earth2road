extends Node3D
const Tile = preload("res://visuals/tile.gd")
const World = preload("res://scripts/world.gd")
const Vehicles = preload("res://scripts/vehicles.gd")
var camera: Camera3D
var elapsed:=0.0
var limit:=0.0
var captured:=false
func _ready() -> void:
	World.shared()
	var data: Dictionary={"ground":[],"greens":[],"parking":[],"road_strips":[],"junctions":[],"buildings":[],"trees":[],"sidewalks":[]}
	var types: Array=["panel","brick","insulated","modern","public","retail"]
	for i in range(6):
		var x:=float(i%3)*32-32
		var z:=float(i/3)*54-24
		var h: float=[27,15,24,33,12,5][i]
		data.buildings.append({"id":str(i),"points":[[x-12,0,z-7],[x+12,0,z-7],[x+12,0,z+7],[x-12,0,z+7]],"height":h,"visual_family":types[i],"ground_floor":"shop" if i==5 else ""})
	for i in range(15):
		data.trees.append([-53+(i%5)*26,0,-48+(i/5)*42])
	data.ground=[[[ -90,0,-90],[90,0,-90],[90,0,90]], [[-90,0,-90],[90,0,90],[-90,0,90]]]
	data.road_strips=[{"points":[[-90,.035,3],[90,.035,3]],"width":12,"bridge":false,"internal":false}]
	data.sidewalks=[{"points":[[-90,.035,-5],[90,.035,-5]],"width":3},{"points":[[-90,.035,11],[90,.035,11]],"width":3}]
	var world:=World.new()
	world.build(data)
	add_child(world)
	var display:=Tile.new()
	add_child(display)
	var i:=0
	for name in Vehicles.catalog().models:
		var car:=Vehicles.instantiate(name)
		car.root.position=Vector3(-44+i*8,.05,3)
		car.root.rotation.y=PI*.5
		add_child(car.root)
		i+=1
	i=0
	for kind in ["stop","stop_old","kiosk","metro","bench","fence","cabinet"]:
		display.prop(kind,Transform3D(Basis(),Vector3(-42+i*14,.15,13)),500)
		i+=1
	display.flush()
	var env:=Environment.new()
	var sky:=Sky.new()
	var skymat:=ProceduralSkyMaterial.new()
	skymat.sky_top_color=Color("6386a2")
	skymat.sky_horizon_color=Color("c5cbd0")
	sky.sky_material=skymat
	env.background_mode=Environment.BG_SKY
	env.sky=sky
	env.ambient_light_source=Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy=.65
	env.tonemap_mode=Environment.TONE_MAPPER_AGX
	env.ssao_enabled=true
	env.ssao_radius=1.2
	env.ssao_intensity=1.1
	var we:=WorldEnvironment.new()
	we.environment=env
	add_child(we)
	var sun:=DirectionalLight3D.new()
	sun.rotation_degrees=Vector3(-38,-35,0)
	sun.light_color=Color("fff0d8")
	sun.light_energy=1.5
	sun.shadow_enabled=true
	sun.directional_shadow_max_distance=180
	add_child(sun)
	camera=Camera3D.new()
	camera.position=Vector3(62,29,76)
	camera.far=1500
	add_child(camera)
	camera.look_at(Vector3(0,10,0))
	camera.current=true
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--seconds="): limit=float(arg.split("=")[1])
	print("VISUAL_DEMO_READY families=6 trees=15 vehicles=12 props=7")
func _process(delta: float) -> void:
	elapsed+=delta
	if Input.is_key_pressed(KEY_ESCAPE): get_tree().quit()
	if Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT):
		var move:=Vector3(float(Input.is_key_pressed(KEY_D))-float(Input.is_key_pressed(KEY_A)),float(Input.is_key_pressed(KEY_E))-float(Input.is_key_pressed(KEY_Q)),float(Input.is_key_pressed(KEY_S))-float(Input.is_key_pressed(KEY_W)))
		camera.position+=camera.basis*move*delta*25
	if elapsed>3 and not captured and "--capture" in OS.get_cmdline_user_args():
		captured=true
		await RenderingServer.frame_post_draw
		if DisplayServer.get_name()!="headless":
			get_viewport().get_texture().get_image().save_png("res://../logs/visual-demo.png")
	if limit>0 and elapsed>limit: get_tree().quit()
func _input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT):
		camera.rotation.y-=event.relative.x*.003
		camera.rotation.x=clampf(camera.rotation.x-event.relative.y*.003,-1.5,1.5)

func _exit_tree() -> void:
	Vehicles.release_visual_templates()
