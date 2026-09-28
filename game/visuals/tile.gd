extends Node3D
## Decorative layer only: does not change road geometry, collision or traffic.
const Palette = preload("res://visuals/palette.gd")
const Assets = preload("res://visuals/assets.gd")
const SignFaces = preload("res://visuals/sign_faces.gd")
const PLATE_HEIGHT := 2.3      # must match tools/signs.py
var groups: Dictionary = {}
var occupied: Dictionary = {}
var roads: Dictionary = {}
var buildings: Array = []
## 16 m cell -> building volumes {poly, bottom, top, id}; parts of one complex share walls.
var volumes: Dictionary = {}
var stats := {"instances":0,"groups":0,"rejected":0}

static func init() -> void:
	Assets.init()
	SignFaces.init()

static func family(b: Dictionary) -> int:
	var explicit: String = str(b.get("visual_family", ""))
	var names := ["panel","brick","insulated","modern","public","retail"]
	if explicit in names:
		return names.find(explicit)
	var tag: String = str(b.get("building_type", ""))
	if tag in ["school","hospital","university","civic","office"]:
		return 4
	if float(b.get("height", 6)) < 8 and b.get("ground_floor", "") == "shop":
		return 5
	return posmod(hash(str(b.get("id", "0"))),4)

static func vec(p: Array) -> Vector3:
	return Vector3(p[0],p[1],p[2])

func add_part(part: Dictionary, xf: Transform3D, begin: float, end: float) -> void:
	var final: Transform3D = xf * part.get("transform",Transform3D.IDENTITY)
	var cell := Vector2i(floori(final.origin.x/64),floori(final.origin.z/64))
	var key := "%s:%s:%s:%s:%s" % [part.mesh.get_instance_id(),part.material.get_instance_id(),cell,begin,end]
	if not groups.has(key):
		groups[key] = {"mesh":part.mesh,"material":part.material,"transforms":[],"begin":begin,"end":end}
	groups[key].transforms.append(final)
	stats.instances += 1

func prop(kind: String, xf: Transform3D, end := 180.0, seed := 0) -> void:
	var parts: Array = Assets.resolve_prop(kind, seed)
	if parts.is_empty():
		return
	for part in parts:
		add_part(part,xf,0,end)

func box(mat: String, size: Vector3, xf: Transform3D, end := 180.0) -> void:
	add_part(Assets.box(mat,Vector3.ZERO,size),xf,0,end)

func build(data: Dictionary, level := "full") -> void:
	buildings = data.get("buildings",[])
	index_buildings()
	if level == "full":
		index_roads(data)
		for b in buildings:
			facade(b)
		street(data)
	for p in data.get("trees",[]):
		plant(vec(p),level)
	for item in data.get("signs",[]) if level == "full" else []:
		build_sign(item)
	for item in data.get("visual_props",[]) if level == "full" else []:
		var p := vec(item.position)
		if free_at(p,float(item.get("radius",1))):
			prop(item.kind,Transform3D(Basis(Vector3.UP,float(item.get("yaw",0))),p),Palette.distance_for("prop"))
	flush()

## A derived road sign (tools/signs.py): pole, face, grey back. No free_at() check —
## where a sign stands is dictated by the road, not by the decoration budget.
func build_sign(item: Dictionary) -> void:
	var p := vec(item.position)
	var xf := Transform3D(Basis(Vector3.UP, float(item.get("yaw", 0.0))), p)
	var far := Palette.distance_for("sign")
	# The record's y is the plate centre (signs.py PLATE_HEIGHT), so the pole hangs below it.
	add_part(Assets.part("pole", "metal", Vector3(0, -PLATE_HEIGHT * 0.5, 0), Vector3(.09, PLATE_HEIGHT, .09)), xf, 0, far)
	add_part({"mesh": Palette.meshes.sign_plate,
		"material": SignFaces.material(str(item.kind), int(item.get("value", 0) if item.get("value") != null else 0)),
		"transform": Transform3D(Basis(), Vector3(0, 0, 0.03))}, xf, 0, far)
	add_part({"mesh": Palette.meshes.sign_plate, "material": Palette.materials.metal,
		"transform": Transform3D(Basis(Vector3.UP, PI), Vector3(0, 0, 0.02))}, xf, 0, far)
	stats.instances += 1

func index_roads(data: Dictionary) -> void:
	for road in data.get("road_strips",[]):
		var pts: Array = road.points
		var r := float(road.width)*.5+.6
		for i in range(pts.size()-1):
			var a := vec(pts[i])
			var b := vec(pts[i+1])
			var segment := [a,b,r]
			for x in range(floori((minf(a.x,b.x)-r)/16),floori((maxf(a.x,b.x)+r)/16)+1):
				for z in range(floori((minf(a.z,b.z)-r)/16),floori((maxf(a.z,b.z)+r)/16)+1):
					var key := Vector2i(x,z)
					if not roads.has(key): roads[key]=[]
					roads[key].append(segment)
	for junction in data.get("junctions",[]):
		for triangle in junction.get("triangles",[]):
			var a := vec(triangle[0])
			var b := vec(triangle[1])
			var c := vec(triangle[2])
			var triangle_xz := PackedVector2Array([Vector2(a.x,a.z),Vector2(b.x,b.z),Vector2(c.x,c.z)])
			for x in range(floori(minf(a.x,minf(b.x,c.x))/16)-1,floori(maxf(a.x,maxf(b.x,c.x))/16)+2):
				for z in range(floori(minf(a.z,minf(b.z,c.z))/16)-1,floori(maxf(a.z,maxf(b.z,c.z))/16)+2):
					var key := Vector2i(x,z)
					if not roads.has(key): roads[key]=[]
					roads[key].append({"triangle":triangle_xz,"y":(a.y+b.y+c.y)/3})

func index_buildings() -> void:
	for b in buildings:
		var points: Array = b.get("points",[])
		if points.size()<3: continue
		var poly := PackedVector2Array()
		var floor_y := INF
		for point in points:
			poly.append(Vector2(point[0],point[2]))
			floor_y=minf(floor_y,float(point[1]))
		var box2 := Rect2(poly[0],Vector2.ZERO)
		for q in poly: box2=box2.expand(q)
		var base := float(b.get("base",0))
		var volume := {"poly":poly,"bottom":floor_y+base if base>0 else floor_y-1.0,"top":floor_y+float(b.get("height",6)),"id":str(b.get("id",""))}
		for x in range(floori(box2.position.x/16),floori(box2.end.x/16)+1):
			for z in range(floori(box2.position.y/16),floori(box2.end.y/16)+1):
				var key := Vector2i(x,z)
				if not volumes.has(key): volumes[key]=[]
				volumes[key].append(volume)

## Highest roof of another building volume covering q (XZ), or -INF. Facade details below it
## would be buried in (or poke through the roof of) an adjoining building:part.
func covered_to(q: Vector2, own_id: String, below := INF) -> float:
	var top := -INF
	for v in volumes.get(Vector2i(floori(q.x/16),floori(q.y/16)),[]):
		if v.id==own_id or v.bottom>below: continue
		if v.top>top and Geometry2D.is_point_in_polygon(q,v.poly): top=v.top
	return top

func free_at(p: Vector3, radius: float) -> bool:
	var q := Vector2(p.x,p.z)
	for x in range(floori((p.x-radius)/16),floori((p.x+radius)/16)+1):
		for z in range(floori((p.z-radius)/16),floori((p.z+radius)/16)+1):
			for segment in roads.get(Vector2i(x,z),[]):
				if segment is Dictionary:
					if absf(p.y-segment.y)<3 and Geometry2D.is_point_in_polygon(q,segment.triangle): return false
				else:
					var a: Vector3=segment[0]
					var b: Vector3=segment[1]
					var closest := Geometry2D.get_closest_point_to_segment(q,Vector2(a.x,a.z),Vector2(b.x,b.z))
					if absf(p.y-(a.y+b.y)*.5)<3 and q.distance_to(closest)<float(segment[2])+radius: return false
	var seen_volumes := {}
	for x in range(floori((p.x-radius-.5)/16),floori((p.x+radius+.5)/16)+1):
		for z in range(floori((p.z-radius-.5)/16),floori((p.z+radius+.5)/16)+1):
			for v in volumes.get(Vector2i(x,z),[]):
				if v.bottom>p.y+3 or seen_volumes.has(v): continue
				seen_volumes[v]=true
				var poly: PackedVector2Array=v.poly
				if Geometry2D.is_point_in_polygon(q,poly): return false
				for i in range(poly.size()):
					if q.distance_to(Geometry2D.get_closest_point_to_segment(q,poly[i],poly[(i+1)%poly.size()]))<radius+.5: return false
	var key := Vector2i(floori(p.x/4),floori(p.z/4))
	for dx in range(-1,2):
		for dz in range(-1,2):
			for other in occupied.get(key+Vector2i(dx,dz),[]):
				if q.distance_to(other[0])<radius+float(other[1]): return false
	if not occupied.has(key): occupied[key]=[]
	occupied[key].append([q,radius])
	return true

func facade(b: Dictionary) -> void:
	if b.get("visual_profile", "") == "rural":
		rural_facade(b)
		return
	if float(b.get("base",0)) > 0: return
	var points: Array = b.get("points",[])
	if points.size()<3: return
	var floor_y := INF
	var area := 0.0
	for i in range(points.size()):
		floor_y=minf(floor_y,float(points[i][1]))
		var a:=vec(points[i])
		var c:=vec(points[(i+1)%points.size()])
		area += a.x*c.z-c.x*a.z
	var h := float(b.get("height",6))
	var fam := family(b)
	var seed_id := posmod(hash(str(b.get("id","0"))),65521)
	var own_id := str(b.get("id",""))
	var end := Palette.distance_for("detail")
	for i in range(points.size()):
		var a:=vec(points[i]); a.y=floor_y
		var c:=vec(points[(i+1)%points.size()]); c.y=floor_y
		var length := a.distance_to(c)
		if length<3: continue
		var along := (c-a).normalized()
		var outward := Vector3(along.z,0,-along.x) * (1.0 if area>0 else -1.0)
		var basis := Basis(Vector3.UP.cross(outward),Vector3.UP,outward)
		box("concrete",Vector3(length,.24,.24),Transform3D(basis,(a+c)*.5+Vector3.UP*(h-.12)),end*2)
		for column in range(int(length/3.3)):
			var center := a+along*(column*3.3+1.65)+outward*.07
			# Probe 0.8 m out: the depth of a balcony slab.
			var probe := center+outward*.8
			var buried := covered_to(Vector2(probe.x,probe.z),own_id)
			for storey in range(1,int(h/3)):
				var p := center+Vector3.UP*(storey*3+1.71)
				# Loggia glazing reaches 1.35 m above p; keep it under the own roof and above neighbours.
				if p.y+1.4>floor_y+h or p.y-.85<buried: continue
				# Window sills add depth without rebuilding every procedural window.
				box("frame",Vector3(1.95,.09,.22),Transform3D(basis,p-Vector3.UP*.77),end)
				if fam in [0,1,2,3] and (column+seed_id)%3==0:
					prop("loggia" if (column+storey+seed_id)%3==0 else "balcony",Transform3D(basis,p),end)
				elif (column*7+storey*11+seed_id)%13==0:
					prop("ac",Transform3D(basis,p+along*1.2-Vector3.UP*.7),80)
		var mid := (a+c)*.5+outward*.8
		if length>8 and covered_to(Vector2(mid.x,mid.z),own_id)<floor_y+2.5:
			prop("entrance",Transform3D(basis,(a+c)*.5+outward*.09),end)
		if i==0 and length>12:
			prop("vent",Transform3D(Basis(),(a+c)*.5-outward*2+Vector3.UP*h),end*2)

func rural_facade(b: Dictionary) -> void:
	var points: Array = b.get("points", [])
	if points.size() < 3: return
	var floor_y := INF
	var area := 0.0
	for i in range(points.size()):
		floor_y = minf(floor_y, float(points[i][1]))
		var a := vec(points[i])
		var c := vec(points[(i+1)%points.size()])
		area += a.x*c.z-c.x*a.z
	var h := float(b.get("wall_height", b.height))
	floor_y = float(b.get("floor_height",floor_y))
	for i in range(points.size()):
		var a := vec(points[i]); a.y = floor_y
		var c := vec(points[(i+1)%points.size()]); c.y = floor_y
		var length := a.distance_to(c)
		if length < 3: continue
		var along := (c-a).normalized()
		var outward := Vector3(along.z,0,-along.x)*(1.0 if area>0 else -1.0)
		var basis := Basis(Vector3.UP.cross(outward),Vector3.UP,outward)
		box("frame",Vector3(length,.12,.25),Transform3D(basis,(a+c)*.5+Vector3.UP*(h-.05)),220)
		if h<2.6: continue
		for column in range(int(length/3.3)):
			var center := a+along*(column*3.3+1.65)+outward*.07
			if covered_to(Vector2(center.x,center.z),str(b.id))>floor_y+.8: continue
			box("frame",Vector3(1.55,.1,.2),Transform3D(basis,center+Vector3.UP*.9),150)
			box("frame",Vector3(.1,1.35,.15),Transform3D(basis,center+along*.78+Vector3.UP*1.55),150)
			box("frame",Vector3(.1,1.35,.15),Transform3D(basis,center-along*.78+Vector3.UP*1.55),150)

func street(data: Dictionary) -> void:
	var seen: Dictionary = {}
	for walk in data.get("sidewalks",[]):
		var pts: Array=walk.points
		var width := float(walk.width)
		if width<2.2: continue
		var walked := 0.0
		var next := 12.0
		for i in range(pts.size()-1):
			var a:=vec(pts[i]); var b:=vec(pts[i+1])
			var length:=a.distance_to(b)
			if length<.01: continue
			var along:=(b-a).normalized()
			var side:=Vector3(along.z,0,-along.x)
			while next<walked+length:
				var center:=a.lerp(b,(next-walked)/length)+Vector3.UP*.15
				var id:=Vector2i(roundi(center.x),roundi(center.z))
				if not seen.has(id):
					seen[id]=true
					var seed_id:=posmod(hash(str(id)),65521)
					var kind: String=["lamp","lamp_modern","bench","bin","cabinet","planter"][seed_id%6]
					var radius:=.9 if kind=="bench" else (.5 if kind=="planter" else .4)
					for sign_value in [1.0,-1.0]:
						var p: Vector3=center+side*(width*.5-radius-.15)*sign_value
						if free_at(p,radius):
							prop(kind,Transform3D(Basis(Vector3.UP,atan2(side.x,side.z)),p),Palette.distance_for("prop"),seed_id)
							break
						stats.rejected+=1
				next+=28.0
			walked+=length

func plant(p: Vector3, level: String) -> void:
	var key:=posmod(hash("%.2f:%.2f" % [p.x,p.z]),65521)
	var species:=key%5
	var variant: int=(key/5)%3
	var scale_value:=.85+float(key%31)*.01
	var xf:=Transform3D(Basis(Vector3.UP,float(key%628)*.01).scaled(Vector3.ONE*scale_value),p)
	for lod in range(3):
		if level != "full" and lod<2: continue
		var start: float=[0.0,140.0,450.0][lod] if level=="full" else 0.0
		var end: float=[140.0,450.0,Palette.distance_for("tree")][lod]
		for part in Assets.trees["%d:%d:%d" % [species,variant,lod]]:
			add_part(part,xf,start,end)

func flush() -> void:
	for group in groups.values():
		var mm:=MultiMesh.new()
		mm.transform_format=MultiMesh.TRANSFORM_3D
		mm.mesh=group.mesh
		mm.instance_count=group.transforms.size()
		for i in range(mm.instance_count): mm.set_instance_transform(i,group.transforms[i])
		var node:=MultiMeshInstance3D.new()
		node.multimesh=mm
		node.material_override=group.material
		node.visibility_range_begin=group.begin
		node.visibility_range_end=group.end
		node.visibility_range_begin_margin=5
		node.visibility_range_end_margin=5
		node.cast_shadow=GeometryInstance3D.SHADOW_CASTING_SETTING_ON if group.end<=450 else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(node)
	stats.groups=groups.size()
	groups.clear()
