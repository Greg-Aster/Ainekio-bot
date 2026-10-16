"""Build a separate concept scene in the owner's open Blender; preserve source CAD."""
import bpy, json, math, re
from pathlib import Path
from mathutils import Matrix, Vector

P = Path(__file__).resolve().parent
live = json.loads((P / 'live45.json').read_text())
plan = json.loads((P / 'body-plan.json').read_text())
par = live['params']
source = bpy.data.scenes['Wireless']
name = 'Gait - 82 mm body support'
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
camera.location = (0, -770, 440)
camera.rotation_euler = (Vector((0, 0, 65))-camera.location).to_track_quat('-Z', 'Y').to_euler()
camera.data.type, camera.data.ortho_scale, camera.data.clip_end = 'ORTHO', 760, 5000
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

label('Support title', '82 mm WALK | BODY SUPPORT + JOINT LOAD', (0, 0, 223), 12)
label('Support subtitle', '45 mm bare foot / 20 mm crank / existing servo locations', (0, 0, 203), 7)
label('Support legend', 'GREEN: supporting feet    PINK: assumed COM    YELLOW: effective pressure point', (0, -105, -36), 6)
label('Support scope', 'CONCEPT STUDY | 2 s cycle | mass / COM unmeasured | no collision or physical walking proof', (0, -105, -52), 6)

all_objects = []
for tag, params, xoff, color in [('A', (40,28,30,45), -182, cyan), ('B', (45,32,34,55), 182, orange)]:
    A, b, L, H = params
    d = json.loads((P / ('refined-'+'-'.join(map(str,params))+'.json')).read_text())
    col = bpy.data.collections.new('Support '+tag)
    scene.collection.children.link(col)
    root = empty(tag+' | Body', col)
    root['Dimensions mm'] = f'carrier {A} / crank 20 / pickup {b} / rod {L} / foot 45'
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
            spec = {'primary':(35,A,par['alpha_neutral'],'Part_023'), 'foot':(28,b,par['beta_neutral'],'Part_027'), 'rod':(30,L,par['old_rod_reference_angle'],'Part_026')}.get(part)
            if spec and spec[0] != spec[1]:
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
    label(tag+' title',f'{tag} | {A} carrier / {b} pickup / {L} rod',(xoff,0,175),8,color)
    label(tag+' clearance',f'BODY CLEARANCE {H-1.977:.0f} mm | nominal stroke 82 mm',(xoff,0,155),6.5)
    label(tag+' load',f'PEAK Nm/kg: carrier {peak[1]:.3f} / crank {peak[2]:.3f}',(xoff,-180,0),6.5,color)

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
readme=bpy.data.texts.new('BODY SUPPORT STUDY - READ ME')
readme.write('Space to play. Separate concept study; Wireless source remains unchanged.\n82 mm nominal stance sweep, 80% stance, 2 second cycle; no preparation moves.\nBody translates and shifts during the walking cycle. Pink COM is assumed, not measured.\nYellow pressure point includes torso acceleration; green polygon joins planned supporting contacts.\nPeak torque is Nm per kg TOTAL robot mass, from a point-body model, excluding leg inertia.\nCandidate B uses 45 carrier / 20 crank / 32 pickup / 34 rod / 45 lower foot.\nPreview meshes were deformed for illustration; they are not manufacturing-ready CAD.\nNo measured friction, load tracking, contact feedback or collision qualification; not proof of walking.\n')
scene.frame_set(1)
bpy.context.window.scene=scene
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D': area.spaces.active.region_3d.view_perspective='CAMERA'
print(json.dumps({'scene':name,'objects':len(scene.objects),'source_snapshots':len(snapshots)}))
