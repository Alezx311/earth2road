extends RefCounted
## Original procedural vehicle kit. Metric geometry, -Z forward, four animation pivots.
## One palette atlas is also compatible with the existing far-traffic shader.
static var atlas: ImageTexture
static var material: StandardMaterial3D
const COLORS := ["b8b9b7","223640","202325","686e70","d4d5cf","ac2420","d4c894","375362","e5e4dc","344248","d4b749","738078","b7bcc0","e9e2ca","c77735","25303a"]
var surfaces: Dictionary = {}

static func init() -> void:
	if atlas != null: return
	var img:=Image.create(16,1,false,Image.FORMAT_RGB8)
	for i in range(16): img.set_pixel(i,0,Color(COLORS[i]))
	atlas=ImageTexture.create_from_image(img)
	material=StandardMaterial3D.new()
	material.albedo_texture=atlas
	material.texture_filter=BaseMaterial3D.TEXTURE_FILTER_NEAREST
	material.roughness=.35
	material.metallic=.2

func triangle(a: Vector3,b: Vector3,c: Vector3,color: int) -> void:
	if not surfaces.has(color):
		var st:=SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		surfaces[color]=st
	var st: SurfaceTool=surfaces[color]
	for p in [a,b,c]:
		st.set_uv(Vector2((color+.5)/16.0,.5))
		st.add_vertex(p)

func quad(a: Vector3,b: Vector3,c: Vector3,d: Vector3,color: int) -> void:
	triangle(a,b,c,color)
	triangle(a,c,d,color)

func box(center: Vector3,size: Vector3,color: int) -> void:
	var a:=center-size*.5
	var b:=center+size*.5
	quad(Vector3(a.x,a.y,a.z),Vector3(b.x,a.y,a.z),Vector3(b.x,b.y,a.z),Vector3(a.x,b.y,a.z),color)
	quad(Vector3(b.x,a.y,b.z),Vector3(a.x,a.y,b.z),Vector3(a.x,b.y,b.z),Vector3(b.x,b.y,b.z),color)
	quad(Vector3(a.x,a.y,b.z),Vector3(a.x,a.y,a.z),Vector3(a.x,b.y,a.z),Vector3(a.x,b.y,b.z),color)
	quad(Vector3(b.x,a.y,a.z),Vector3(b.x,a.y,b.z),Vector3(b.x,b.y,b.z),Vector3(b.x,b.y,a.z),color)
	quad(Vector3(a.x,b.y,a.z),Vector3(b.x,b.y,a.z),Vector3(b.x,b.y,b.z),Vector3(a.x,b.y,b.z),color)
	quad(Vector3(a.x,a.y,b.z),Vector3(b.x,a.y,b.z),Vector3(b.x,a.y,a.z),Vector3(a.x,a.y,a.z),color)

func loft(sections: Array, color: int) -> void:
	# z, lower half width, shoulder half width, lower y, shoulder y, crown y
	var rings: Array=[]
	for s in sections:
		rings.append([Vector3(-s[1],s[3],s[0]),Vector3(-s[2],s[4],s[0]),Vector3(-s[2]*.88,s[5],s[0]),Vector3(s[2]*.88,s[5],s[0]),Vector3(s[2],s[4],s[0]),Vector3(s[1],s[3],s[0])])
	for i in range(rings.size()-1):
		for j in range(6):
			var k: int=(j+1)%6
			quad(rings[i][j],rings[i+1][j],rings[i+1][k],rings[i][k],color)
	for j in range(1,5):
		triangle(rings[0][0],rings[0][j],rings[0][j+1],color)
		triangle(rings[-1][0],rings[-1][j+1],rings[-1][j],color)

func wheel(radius: float, width: float) -> void:
	var n:=24
	for i in range(n):
		var a:=TAU*i/n
		var b:=TAU*(i+1)/n
		var v0:=Vector3(-width*.5,sin(a)*radius,cos(a)*radius)
		var v1:=Vector3(width*.5,sin(a)*radius,cos(a)*radius)
		var v2:=Vector3(width*.5,sin(b)*radius,cos(b)*radius)
		var v3:=Vector3(-width*.5,sin(b)*radius,cos(b)*radius)
		quad(v0,v1,v2,v3,2)
		for side in [-1.0,1.0]:
			var center:=Vector3(width*.505*side,0,0)
			var p:=Vector3(center.x,sin(a)*radius,cos(a)*radius)
			var q:=Vector3(center.x,sin(b)*radius,cos(b)*radius)
			triangle(center,q,p,2) if side>0 else triangle(center,p,q,2)
			var inner0:=Vector3(center.x*1.01,p.y*.64,p.z*.64)
			var inner1:=Vector3(center.x*1.01,q.y*.64,q.z*.64)
			triangle(center,inner1,inner0,3 if i%3==0 else 12) if side>0 else triangle(center,inner0,inner1,3 if i%3==0 else 12)

func mesh() -> ArrayMesh:
	var out:=ArrayMesh.new()
	for color in surfaces:
		var st: SurfaceTool=surfaces[color]
		st.generate_normals()
		st.set_material(material)
		st.commit(out)
	return out

static func template(name: String,spec: Dictionary) -> Dictionary:
	init()
	var kit=new()
	var size:=Vector3(spec.size[0],spec.size[1],spec.size[2])
	var w:=size.x*.5
	var h:=size.y
	var l:=size.z
	var r:=float(spec.tire_radius)
	var color: int={"sedan":0,"hatchback-sports":7,"sedan-sports":9,"suv":8,"suv-luxury":15,"taxi":10,"van":11,"delivery":8,"truck":0,"garbage-truck":11,"police":8,"ambulance":8}.get(name,0)
	var utility:=name in ["van","delivery","truck","garbage-truck","ambulance"]
	var front_axle: float=-l*.30
	var rear_axle: float=l*.30
	var belt:=h*.55 if not utility else minf(h*.5,1.12)
	# Rounded shoulder and tapered bumper sections, rather than scaled toy geometry.
	kit.loft([[-l*.5,w*.83,w*.78,r*.7,belt*.83,belt*.86],[-l*.42,w*.96,w,r*.75,belt*.96,belt],[-l*.2,w*.98,w,r*.75,belt,belt*1.03],[l*.35,w*.97,w,r*.75,belt,belt*1.03],[l*.5,w*.84,w*.85,r*.85,belt*.9,belt*.94]],color)
	var z_front: float=-l*.20
	var z_roof_front: float=-l*.055
	var z_roof_rear: float=l*(.24 if utility or name in ["suv","suv-luxury","hatchback-sports"] else .17)
	var z_rear: float=l*.36
	var roof_w:=w*.78
	var roof_h:=h*.96
	var bl:=Vector3(-w*.93,belt,z_front)
	var br:=Vector3(w*.93,belt,z_front)
	var tl:=Vector3(-roof_w,roof_h,z_roof_front)
	var tr:=Vector3(roof_w,roof_h,z_roof_front)
	kit.quad(bl,br,tr,tl,1)
	kit.quad(Vector3(-roof_w,roof_h,z_roof_rear),Vector3(roof_w,roof_h,z_roof_rear),Vector3(w*.91,belt,z_rear),Vector3(-w*.91,belt,z_rear),1)
	kit.box(Vector3(0,roof_h,(z_roof_front+z_roof_rear)*.5),Vector3(roof_w*2,.075,z_roof_rear-z_roof_front),color)
	for side in [-1.0,1.0]:
		var a:=Vector3(side*w*.94,belt+.025,z_front+.06)
		var b:=Vector3(side*roof_w,roof_h-.04,z_roof_front+.06)
		var c:=Vector3(side*roof_w,roof_h-.04,z_roof_rear-.03)
		var d:=Vector3(side*w*.92,belt+.025,z_rear-.05)
		if side<0: kit.quad(a,b,c,d,1)
		else: kit.quad(d,c,b,a,1)
		kit.box(Vector3(side*w*.85,(belt+roof_h)*.5,l*.08),Vector3(.07,roof_h-belt,.075),2)
		kit.box(Vector3(side*w*1.035,belt+.1,-l*.15),Vector3(.17,.11,.24),color)
		for z in [-l*.08,l*.20]:
			kit.box(Vector3(side*w*1.006,belt-.09,z),Vector3(.025,.035,.17),3)
		# Sills and fine door seams.
		kit.box(Vector3(side*w*.995,r*.87,0),Vector3(.04,.08,l*.58),2)
		kit.box(Vector3(side*w*1.001,(r+belt)*.5,l*.09),Vector3(.012,belt-r,.012),3)
	kit.box(Vector3(0,belt*.7,-l*.498),Vector3(w*.9,.18,.025),2)
	for y in range(4): kit.box(Vector3(0,belt*.65+y*.04,-l*.513),Vector3(w*.85,.012,.01),3)
	for z in [-l*.502,l*.502]:
		kit.box(Vector3(0,belt*.48,z),Vector3(.48,.105,.02),8)
		kit.box(Vector3(-.21,belt*.48,z*1.003),Vector3(.045,.10,.005),7)
	if utility and name not in ["van","truck"]:
		kit.box(Vector3(0,(h+belt)*.5,l*.18),Vector3(size.x*.98,h-belt,l*.59),color)
		kit.box(Vector3(0,h+.025,l*.18),Vector3(size.x,.05,l*.60),3)
		if name=="ambulance":
			for side in [-1.0,1.0]: kit.box(Vector3(side*w*1.002,h*.66,l*.18),Vector3(.025,.2,l*.57),14)
	if name=="police":
		kit.box(Vector3(0,h+.075,l*.05),Vector3(.95,.1,.22),7)
	if name=="taxi": kit.box(Vector3(0,h+.09,l*.06),Vector3(.38,.16,.16),10)
	var root:=Node3D.new()
	root.name=name
	var body:=MeshInstance3D.new()
	body.name="body"
	body.mesh=kit.mesh()
	root.add_child(body)
	var wheel_kit=new()
	wheel_kit.wheel(r,.20 if w<1.1 else .28)
	var wheel_mesh: ArrayMesh=wheel_kit.mesh()
	var pivots: Array=[]
	var keys: Array=["wheel-front-left","wheel-front-right","wheel-back-left","wheel-back-right"]
	for i in range(4):
		var pivot:=Node3D.new()
		pivot.name=keys[i]
		pivot.position=Vector3((-1 if i%2==0 else 1)*(w-.07),r,front_axle if i<2 else rear_axle)
		var part:=MeshInstance3D.new()
		part.mesh=wheel_mesh
		pivot.add_child(part)
		root.add_child(pivot)
		pivots.append(pivot.position)
	return {"root":root,"size":size,"tire_radius":r,"wheels":pivots}
