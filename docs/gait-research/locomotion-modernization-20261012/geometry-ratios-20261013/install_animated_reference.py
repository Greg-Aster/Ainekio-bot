"""Build a separate concept scene in the owner's open Blender; preserve source CAD."""
import bpy, json, math, re
from pathlib import Path
from mathutils import Matrix, Vector

P = Path(__file__).resolve().parent.parent / 'body-support-20261013'
R = Path(__file__).resolve().parent
live = json.loads((P / 'live45.json').read_text())
plan = json.loads((P / 'body-plan.json').read_text())
par = live['params']
bare_vertices = json.loads((P.parent / 'installed55-20261013/bare55.json').read_text())['vertices']
source = bpy.data.scenes['Wireless']
name = 'Geometry - 72 mm walking reference'
assert name not in bpy.data.scenes, 'Preserve existing study; choose another scene name.'
scene = bpy.data.scenes.new(name)
scene.unit_settings.system = source.unit_settings.system
scene.unit_settings.scale_length = source.unit_settings.scale_length
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = 1700
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
scene.render.fps = 24
scene.frame_start, scene.frame_end = 1, 96
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'MATERIAL'
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.background_type = 'WORLD'
scene.world = bpy.data.worlds.new('Body support study world')
scene.world.color = (.025, .035, .045)
scene['Qualification'] = 'Concept geometry and assumed point-mass dynamics; no measured COM, link inertia, collision or physical walking qualification.'
scene['Nominal stroke mm'] = 82
scene['Cycle seconds'] = 2
scene['Duty fraction'] = .8

def material(n, c):
    m = bpy.data.materials.new(n)
    m.diffuse_color = (*c, 1)
    m.use_nodes = True
    next(x for x in m.node_tree.nodes if x.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = (*c, 1)
    return m

white = material('Support study text', (.85, .92, 1))
cyan = material('Support study A', (.02, .65, 1))
orange = material('Support study B', (1, .40, .05))
green = material('Supporting feet', (.1, .85, .3))
pink = material('Assumed COM', (1, .15, .5))
yellow = material('Effective pressure point', (1, .9, .03))
gray = material('Support floor', (.09, .12, .15))
gridmat = material('Support grid', (.18, .23, .27))

def empty(n, col, parent=None):
    o = bpy.data.objects.new(n, None)
    col.objects.link(o)
    o.parent = parent
    return o

def curve(n, points, col, mat, radius=.5, parent=None):
    c = bpy.data.curves.new(n, 'CURVE')
    c.dimensions = '3D'
    c.bevel_depth, c.bevel_resolution = radius, 2
    s = c.splines.new('POLY')
    s.points.add(len(points)-1)
    for p, v in zip(s.points, points):
        p.co = (*v, 1)
    o = bpy.data.objects.new(n, c)
    col.objects.link(o)
    o.parent = parent
    c.materials.append(mat)
    return o

def ring(n, col, mat, radius=3):
    return curve(n, [(radius*math.cos(i*math.tau/24), radius*math.sin(i*math.tau/24), 0) for i in range(25)], col, mat, .65)

def linear(o):
    if not o.animation_data or not o.animation_data.action:
        return
    for layer in o.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for key in fc.keyframe_points:
                        key.interpolation = 'LINEAR'

# Reuse the exact evaluated source mesh snapshots from the earlier comparison.
# Bind static mechanism hardware to its actual shoulder, not to the torso.
old = bpy.data.scenes['Gait - 70 vs 82 mm']
snapshots = [o for o in old.objects if o.type == 'MESH' and o.name.startswith('S82 | ') and 'source_object' in o]
presentation = bpy.data.collections.new('Body support presentation')
scene.collection.children.link(presentation)
travel = empty('Study camera travel', presentation)
camera = bpy.data.objects.new('Body support camera', bpy.data.cameras.new('Body support camera'))
presentation.objects.link(camera)
camera.parent = travel
camera.location = (0, -700, 300)
camera.rotation_euler = (Vector((0, 0, 65))-camera.location).to_track_quat('-Z', 'Y').to_euler()
camera.data.type, camera.data.ortho_scale, camera.data.clip_end = 'ORTHO', 570, 5000
scene.camera = camera

def label(n, body, loc, size, mat=white):
    c = bpy.data.curves.new(n, 'FONT')
    c.body, c.size, c.align_x = body, size, 'CENTER'
    o = bpy.data.objects.new(n, c)
    presentation.objects.link(o)
    o.parent = travel
    o.location = loc
    o.rotation_euler = camera.rotation_euler
    c.materials.append(mat)
    return o

label('Support title', '72 mm LEG | ANIMATED RESEARCH GEOMETRY', (0, 0, 215), 10)
label('Support subtitle', '72 foot + 43 pickup = 115 mm lower-leg span | 26 carrier / 26 rod / 28 crank', (0, 0, 195), 5.5)
label('Support legend', 'GREEN: supporting feet    PINK: assumed COM    YELLOW: effective pressure point', (0, -105, -36), 6)
label('Support scope', 'RESEARCH CANDIDATE | 2 s cycle | 566 g assumed | COM / collisions / actual walking unqualified', (0, -105, -52), 6)

all_objects = []
for tag, params, xoff, color in [('R72', (26,43,26,65.9767776), 0, cyan)]:
    A, b, L, H = params
    d = json.loads((R / 'refined-72mm-body-cycle.json').read_text())
    col = bpy.data.collections.new('Support '+tag)
    scene.collection.children.link(col)
    root = empty(tag+' | Body', col)
    root['Dimensions mm'] = f'carrier {A} / crank 28 / pickup {b} / rod {L} / foot 72'
    root['Peak carrier Nm per kg'] = d['summary']['peak_joint_torque_Nm_per_kg'][1]
    root['Peak crank Nm per kg'] = d['summary']['peak_joint_torque_Nm_per_kg'][2]
    anchors, hs = {}, {}
    for leg in ['RL','RR','FL','FR']:
        S = Matrix(live['legs'][leg]['shoulder_matrix'])
        M = Matrix(live['legs'][leg]['mechanism_matrix'])
        shoulder = empty(tag+' | '+leg+' shoulder', col, root)
        shoulder.matrix_basis = S
        h = empty(tag+' | '+leg+' lateral joint', col, shoulder)
        hs[leg] = h
        mech = empty(tag+' | '+leg+' mechanism', col, h)
        mech.matrix_basis = S.inverted() @ M
        anchors[(leg,'mechanism frame')] = mech
        anchors[(leg,'h alpha theta')] = h
        anchors[(leg,'shoulder frame')] = shoulder
        mount = empty(tag+' | '+leg+' mount', col, h)
        srcmount = source.objects['REFINED | '+leg+' | mount frame']
        mount.matrix_basis = S.inverted() @ srcmount.matrix_world
        anchors[(leg,'mount frame')] = mount
        for part in ['primary','input','foot','rod']:
            anchors[(leg,part)] = empty(tag+' | '+leg+' '+part, col, mech)
    for oldob in snapshots:
        srcname = oldob['source_object']
        srcob = source.objects.get(srcname)
        mesh = oldob.data.copy()
        o = bpy.data.objects.new(tag+' | '+srcname, mesh)
        col.objects.link(o)
        o['source_object'] = srcname
        o.hide_render = oldob.hide_render
        o.hide_viewport = oldob.hide_viewport
        o['Geometry status'] = 'Concept deformation of preview copy, not production CAD'
        ancestor = srcob.parent if srcob else None
        match = None
        while ancestor:
            match = re.match(r'^REFINED \| (RL|RR|FL|FR) \| (primary|input|foot|rod|mechanism frame|mount frame|h alpha theta|shoulder frame)$', ancestor.name)
            if match: break
            ancestor = ancestor.parent
        if match:
            leg, part = match.groups()
            o.parent = anchors[(leg,part)]
            if part in ['primary','input','foot','rod']:
                o.matrix_basis = oldob.matrix_basis.copy()
            else:
                o.matrix_basis = ancestor.matrix_world.inverted() @ srcob.matrix_world
            if part == 'foot' and 'Part_027 -' in srcname:
                original = bpy.data.scenes['Wireless - Original 55mm Legs'].objects['ORIGINAL55 | '+srcname]
                mesh = original.data.copy()
                o.data = mesh
                o.matrix_basis = Matrix.Identity(4)
                for vertex, coords in zip(mesh.vertices, bare_vertices): vertex.co = coords
                rel = o.matrix_basis.copy()
                invrel = rel.inverted()
                axis = Vector((math.cos(par['beta_neutral']-math.pi),0,math.sin(par['beta_neutral']-math.pi)))
                for vertex in mesh.vertices:
                    v = rel @ vertex.co
                    t = v.dot(axis)
                    v += axis * (17*max(0,min(1,(t-7)/41))-15*max(0,min(1,(-t-7)/14)))
                    vertex.co = invrel @ v
                mesh.update()
            spec = {'primary':(35,A,par['alpha_neutral'],'Part_023'), 'input':(20,28,par['old_theta_neutral'],'Part_009'), 'foot':(28,b,par['beta_neutral'],'Part_027'), 'rod':(30,L,par['old_rod_reference_angle'],'Part_026')}.get(part)
            if spec and spec[0] != spec[1] and not (part == 'foot' and 'Part_027 -' in srcname):
                oldlen,newlen,angle,partname = spec
                axis = Vector((math.cos(angle),0,math.sin(angle)))
                delta = newlen-oldlen
                rel = o.matrix_basis.copy()
                invrel = rel.inverted()
                if partname in srcname:
                    # Keep pivot regions rigid; stretch only the inter-hole span.
                    for vertex in mesh.vertices:
                        v = rel @ vertex.co
                        t = max(0,min(1,(v.dot(axis)-7)/(oldlen-14)))
                        vertex.co = invrel @ (v+axis*delta*t)
                    mesh.update()
                else:
                    center = sum((rel @ Vector(corner) for corner in o.bound_box), Vector())/8
                    if center.dot(axis) > oldlen/2:
                        o.location += axis*delta
        else:
            o.parent = root
            o.matrix_basis = oldob.matrix_basis.copy()
        for i, slot in enumerate(oldob.material_slots):
            if slot.link == 'OBJECT':
                o.material_slots[i].link = 'OBJECT'
                o.material_slots[i].material = slot.material
    com = ring(tag+' | COM ground projection', col, pink, 3.5)
    cop = ring(tag+' | Effective pressure point', col, yellow, 1.8)
    # A visible vertical marker indicates the assumed body point-mass height.
    comline = curve(tag+' | COM vertical', [(0,0,0),(0,0,H+15.75)], col, pink, .45)
    polygon = curve(tag+' | Contact support polygon', [(0,0,.6)]*5, col, green, .7)
    contacts = [ring(tag+' | '+leg+' contact', col, green, 2) for leg in ['RL','RR','FL','FR']]
    n = len(d['phase'])
    for sample in range(2*n+1):
        i = sample % n
        frame = 1 + sample*48/n
        progress = sample/n * 82/.8
        shift = d['body_shift'][i]
        root.location = (xoff+progress+shift[0], shift[1], d['body_z'])
        root.keyframe_insert('location', frame=frame)
        com.location = (xoff+progress+shift[0],shift[1],1)
        comline.location = (xoff+progress+shift[0],shift[1],1)
        acc = plan['body_acceleration_mm_s2'][i]
        cop.location = (xoff+progress+shift[0]-(H+15.75)/9810*acc[0],shift[1]-(H+15.75)/9810*acc[1],1.2)
        for obj in [com,comline,cop]: obj.keyframe_insert('location',frame=frame)
        pts=[]
        for k,leg in enumerate(['RL','RR','FL','FR']):
            q = d['q'][i][k]
            f = d['forward'][leg]
            hs[leg].rotation_euler = (math.radians(q[0]),0,0)
            hs[leg].keyframe_insert('rotation_euler',frame=frame)
            a = math.radians(q[1])+par['alpha_neutral']
            theta = math.radians(q[2])+par['firmware_theta_zero_rad']
            D, piv, beta, phi = f['D'][i],f['P'][i],f['beta'][i],f['phi'][i]
            poses=[('primary',(par['O'][0],0,par['O'][1]),-a+par['alpha_neutral']),('input',(par['C_new'][0],0,par['C_new'][1]),-theta+par['old_theta_neutral']),('foot',(D[0],0,D[1]),-(beta-par['beta_neutral'])),('rod',(piv[0],0,piv[1]),-(phi-par['old_rod_reference_angle']))]
            for part,loc,rot in poses:
                ob=anchors[(leg,part)]
                ob.location,ob.rotation_euler=loc,(0,rot,0)
                ob.keyframe_insert('location',frame=frame)
                ob.keyframe_insert('rotation_euler',frame=frame)
            contact=f['contact'][i]
            pos=(xoff+progress+shift[0]+contact[0],shift[1]+contact[1],contact[2]+d['body_z']+.7)
            contacts[k].location=pos
            contacts[k].scale=(1,1,1) if d['stance'][i][k] else (.01,.01,.01)
            contacts[k].keyframe_insert('location',frame=frame)
            contacts[k].keyframe_insert('scale',frame=frame)
            if d['stance'][i][k]: pts.append(pos)
            for j,part in [(1,'primary'),(2,'input')]:
                ob=anchors[(leg,part)]
                ob['Torque Nm per kg']=d['joint_torques'][i][k][j]
                ob.keyframe_insert('["Torque Nm per kg"]',frame=frame)
        cx=sum(p[0] for p in pts)/len(pts);cy=sum(p[1] for p in pts)/len(pts)
        pts.sort(key=lambda p:math.atan2(p[1]-cy,p[0]-cx))
        pts.append(pts[0])
        while len(pts)<5:pts.append(pts[-1])
        for point,coord in zip(polygon.data.splines[0].points,pts):
            point.co=(*coord[:2],.6,1)
            point.keyframe_insert('co',frame=frame)
    for ob in col.objects: linear(ob)
    # Curve point coordinates also interpolate linearly.
    linear(polygon.data)
    peak=d['summary']['peak_joint_torque_Nm_per_kg']
    label(tag+' title','Nominal planted sweep 82 mm | bare Part 027 foot',(xoff,0,175),8,color)
    label(tag+' clearance',f'MODEL BODY CLEARANCE {H-1.977:.0f} mm',(xoff,0,155),6.5)
    label(tag+' load',f'Calculated support torque at 566 g: carrier {peak[1]*.566:.3f} / crank {peak[2]*.566:.3f} Nm',(xoff,-130,-4),5.5,color)

for sample in range(241):
    travel.location=(sample/120*102.5,0,0)
    travel.keyframe_insert('location',frame=1+sample*.4)
linear(travel)
mesh=bpy.data.meshes.new('Support floor mesh')
mesh.from_pydata([(-420,-155,-1),(690,-155,-1),(690,155,-1),(-420,155,-1)],[],[(0,1,2,3)])
floor=bpy.data.objects.new('Body support floor',mesh)
presentation.objects.link(floor)
mesh.materials.append(gray)
for x in range(-400,701,25):curve('World floor grid',[(x,-150,-.8),(x,150,-.8)],presentation,gridmat,.12)
for y in range(-150,151,25):curve('World floor grid',[(-420,y,-.8),(690,y,-.8)],presentation,gridmat,.12)

readme=bpy.data.texts.new('72 MM RESEARCH GEOMETRY - READ ME')
readme.write("Two scenes: Geometry - 72 mm walking reference; Geometry - Leg dimensions and motion.\nSpace to play the 2-second calculated cycle. All dimensions in mm.\n72 knee-to-toe + 43 knee-to-pickup = 115 mm between pickup and toe centres. Installed leg is 55+28=83 mm.\nCarrier 26, rod 26, crank 28; existing servo pivot locations.\nResearch reference, not a proven ideal or manufacturing CAD. Deformed preview copies preserve original objects.\n82 mm nominal planted sweep; 80% stance; modeled clearance64 mm.\nRequires changed crank indexing; does not fit current saved calibration. No robot commands or firmware changes.\nSupport torque model assumes a centred point mass of566 g; excludes limb inertia and impacts.\nPhysical servo speed, collisions, COM and walking remain unqualified.\n")
scene.frame_set(1)
full_scene=scene

# A second scene gives a readable sagittal mechanism and true-scale leg comparison.
scene=bpy.data.scenes.new('Geometry - Leg dimensions and motion')
scene.unit_settings.system='METRIC'
scene.unit_settings.scale_length=.001
scene.render.engine=full_scene.render.engine
scene.render.resolution_x,scene.render.resolution_y=1600,1000
scene.render.fps=24
scene.frame_start,scene.frame_end=1,48
scene.world=full_scene.world
scene.display.shading.light='STUDIO'
scene.display.shading.color_type='MATERIAL'
scene.display.shading.show_cavity=True
presentation=bpy.data.collections.new('Leg geometry dimensions and animation')
scene.collection.children.link(presentation)
travel=empty('Leg detail fixed origin',presentation)
camera=bpy.data.objects.new('Leg dimensions camera',bpy.data.cameras.new('Leg dimensions camera'))
presentation.objects.link(camera)
camera.location=(0,-700,72)
camera.rotation_euler=(Vector((0,0,72))-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO'
camera.data.ortho_scale=400
camera.data.clip_end=5000
scene.camera=camera
red=material('Reference crank red',(1,.16,.12))
purple=material('Reference pickup purple',(.65,.30,1))
label('Detail title','LINKAGE MOTION + LOWER-LEG SIZE',(0,0,171),9)
label('Detail subtitle','72 / 26 / 26 / 43 / 28 mm research reference | not a proven ideal',(0,0,156),5.5)
label('Moving mechanism title','ANIMATED LEG - BODY FRAME',(-95,0,141),6)
label('Size comparison title','LOWER LEGS - SAME SCALE',(90,0,132),6)
label('Detail legend','Carrier 26   Crank 28   Rod 26',(-95,0,-7),5.5)
label('Detail legend 2','Cyan carrier / red crank / orange rod',(-95,0,-18),4.5)
label('Detail scope','2 s cycle | 82 mm nominal planted sweep | detailed robot in the other Geometry scene',(0,0,-33),5)
label('Detail scope 2','Pickup-to-toe centres: 83 mm installed / 115 mm candidate (+39%)',(0,0,-46),5)

# Actual preserved Part027 mesh, repositioned for a direct side-on size comparison.
original=bpy.data.scenes['Wireless - Original 55mm Legs'].objects['ORIGINAL55 | REFINED | FL | Part_027 - 28mm pickup short collar - plain joint bore']
axis=Vector((math.cos(par['beta_neutral']-math.pi),0,math.sin(par['beta_neutral']-math.pi)))
across=Vector((-axis.z,0,axis.x))
for tag,F,B,x in [('Installed',55,28,58),('Candidate',72,43,123)]:
    mesh=original.data.copy()
    for v in mesh.vertices:
        old=Vector(bare_vertices[v.index]);t=old.dot(axis);side=old.dot(across)
        t+=(F-55)*max(0,min(1,(t-7)/41))-(B-28)*max(0,min(1,(-t-7)/14))
        # Toe centres share z=8; knee lies F mm higher.
        v.co=(x+side,(old.y+56.65),8+F-t)
    ob=bpy.data.objects.new(tag+' | Part027 dimension preview',mesh)
    presentation.objects.link(ob)
    mesh.materials.clear();mesh.materials.append(cyan if tag=='Installed' else orange)
    for zz,n in [(8,'Toe centre'),(8+F,'Knee'),(8+F+B,'Pickup')]:
        curve(tag+' | '+n,[(x-3,-9,zz),(x+3,-9,zz)],presentation,white,.45)
    curve(tag+' | dimension',[(x+15,-9,8),(x+15,-9,8+F+B)],presentation,white,.3)
    for zz in [8,8+F,8+F+B]:
        curve(tag+' | dimension tick',[(x+12,-9,zz),(x+18,-9,zz)],presentation,white,.3)
    label(tag+' foot length',str(F),(x+24,-10,8+F/2),6)
    label(tag+' pickup length',str(B),(x+24,-10,8+F+B/2),6)
    label(tag+' size',tag+' '+str(F+B)+' mm',(x,0,-6),5)

# Sagittal projection of one leg, using the same solved cycle as the robot.
f=d['forward']['FR']
O=Vector(par['O']);C=Vector(par['C_new'])
def plane(v):return (v[0]-O[0]-100,0,v[1]-O[1]+96)
beams={n:curve('Animated | '+n,[(0,0,0)]*2,presentation,mat,rr) for n,mat,rr in [('carrier',cyan,2.3),('crank',red,2.5),('rod',orange,1.8),('pickup',purple,2.2),('lower leg',gray,4)]}
curve('Fixed servo pivot separation',[plane(O),plane(C)],presentation,white,.55)
# Small circular pivots in the sagittal plane.
def pivot(name,pos,mat,r=2):
    return curve(name,[(pos[0]+r*math.cos(i*math.tau/24),-4,pos[2]+r*math.sin(i*math.tau/24)) for i in range(25)],presentation,mat,.55)
pivot('Carrier servo centre',plane(O),cyan)
pivot('Crank servo centre',plane(C),red)
mesh=original.data.copy()
for vertex in mesh.vertices:
    v=Vector(bare_vertices[vertex.index]);t=v.dot(axis)
    v+=axis*(17*max(0,min(1,(t-7)/41))-15*max(0,min(1,(-t-7)/14)))
    v.y+=56.65
    vertex.co=v
mesh.materials.clear();mesh.materials.append(white)
footob=bpy.data.objects.new('Animated | actual leg profile reshaped to 72 plus 43',mesh)
presentation.objects.link(footob)
# The separate cylinder is redundant now that the actual leg profile is visible.
beams['lower leg'].hide_render=True
beams['lower leg'].hide_viewport=True
trace=[]
for i in range(len(d['phase'])+1):
    j=i%len(d['phase']);frame=1+48*i/len(d['phase'])
    D=Vector(f['D'][j]);Piv=Vector(f['P'][j]);beta=f['beta'][j]
    E=D+43*Vector((math.cos(beta),math.sin(beta)))
    Toe=D-72*Vector((math.cos(beta),math.sin(beta)))
    coords={'carrier':(O,D),'crank':(C,Piv),'rod':(Piv,E),'pickup':(D,E),'lower leg':(D,Toe)}
    for key,ends in coords.items():
        for point,v in zip(beams[key].data.splines[0].points,ends):
            point.co=(*plane(v),1);point.keyframe_insert('co',frame=frame)
    footob.location=plane(D)
    footob.rotation_euler=(0,-(beta-par['beta_neutral']),0)
    footob.keyframe_insert('location',frame=frame)
    footob.keyframe_insert('rotation_euler',frame=frame)
    trace.append(plane(Toe))
curve('Toe-centre path in body frame',trace,presentation,green,.5)
for ob in beams.values():linear(ob.data)
linear(footob)
scene.frame_set(1)
scene['Evidence']='Visual research reference. Same solved joint cycle as full robot; not physical qualification.'
full_scene['Dimensions mm']='leg 72 / pickup 43 / carrier 26 / rod 26 / crank 28'
full_scene['Total lower-leg centres mm']=115
full_scene['Model body clearance mm']=64
full_scene['Physical build status']='Not installed. Requires changed crank index; current calibration cannot execute these poses.'
full_scene.frame_set(1)
for ob in full_scene.objects:
    if 'CARAPACE |' in ob.name and 'helmet - extracted' in ob.name:
        ob.hide_render=True; ob.hide_viewport=True
full_scene.objects['R72 load'].hide_render=True
full_scene.objects['R72 load'].hide_viewport=True
bpy.context.window.scene=full_scene
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_perspective='CAMERA'
            area.spaces.active.region_3d.view_camera_zoom=0
# Save only the two studies and their dependencies, leaving the source file untouched.
out=Path('/home/greggles/Ainekio/Slave/hardware/v2-12servo/Ainekio-72mm-Animated-Geometry-Reference.blend')
assert not out.exists(), 'Preserve existing saved study.'
bpy.data.libraries.write(str(out),{full_scene,scene,readme},fake_user=True,compress=True)
print(json.dumps({'saved':str(out),'scenes':[full_scene.name,scene.name],'objects':[len(full_scene.objects),len(scene.objects)]}))
def activate_reference():
    bpy.context.window.scene=bpy.data.scenes['Geometry - 72 mm walking reference']
    return None
bpy.app.timers.register(activate_reference,first_interval=.3)
