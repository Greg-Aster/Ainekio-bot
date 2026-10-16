"""Separate animated compact reference; source CAD remains untouched."""
import bpy,json,math
from pathlib import Path
from mathutils import Matrix,Vector
P=Path(__file__).resolve().parent
d=json.loads((P/'compact55-animation-cycle.json').read_text())
live=json.loads((P.parent/'body-support-20261013/live45.json').read_text());par=live['params']
O=Vector(par['O']);C=Vector(d['C']);N=len(d['q']);legs=['RL','RR','FL','FR']
old=bpy.data.scenes['Geometry - 72 mm walking reference']
original=bpy.data.scenes['Wireless - Original 55mm Legs'].objects['ORIGINAL55 | REFINED | FL | Part_027 - 28mm pickup short collar - plain joint bore']
for name in ['Geometry - Compact 55 mm walk','Geometry - Compact linkage detail']:
    assert name not in bpy.data.scenes, 'Preserve existing reference: '+name

def material(name,color):
    m=bpy.data.materials.new('Compact | '+name);m.diffuse_color=(*color,1);m.use_nodes=True
    next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED').inputs['Base Color'].default_value=(*color,1)
    return m
white=material('text',(.88,.93,1));cyan=material('carrier26',(.02,.66,1));red=material('crank21',(1,.12,.08));orange=material('rod23',(1,.51,.05));green=material('support',(.15,.85,.30));gray=material('chassis',(.22,.27,.32));muted=material('previous shaft',(.45,.48,.54));pink=material('assumed COM',(1,.12,.60));floor_mat=material('floor',(.06,.08,.11))
world=bpy.data.worlds.new('Compact reference world');world.color=(.025,.035,.05)

def scene_new(name,scale,eye,target):
    s=bpy.data.scenes.new(name);s.unit_settings.system='METRIC';s.unit_settings.scale_length=.001
    s.render.engine=old.render.engine;s.render.resolution_x=1600;s.render.resolution_y=1000;s.render.resolution_percentage=100
    s.render.fps=60;s.frame_start=1;s.frame_end=120;s.world=world
    s.display.shading.color_type='MATERIAL';s.display.shading.light='STUDIO';s.display.shading.show_cavity=True
    s['Geometry mm']='55 foot /26 carrier /21 crank /23 rod /27 pickup';s['Qualification']='Kinematic reference only. Mount housing and link-layer fit unresolved.'
    col=bpy.data.collections.new(name+' objects');s.collection.children.link(col)
    cam=bpy.data.objects.new(name+' camera',bpy.data.cameras.new(name+' camera'));col.objects.link(cam)
    cam.location=eye;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=scale;cam.data.clip_end=5000;s.camera=cam
    return s,col,cam

def empty(name,col,parent=None):
    o=bpy.data.objects.new('C55 | '+name,None);col.objects.link(o);o.parent=parent;return o

def curve(name,pts,col,mat,r=.5,parent=None):
    c=bpy.data.curves.new('C55 | '+name,'CURVE');c.dimensions='3D';c.bevel_depth=r;c.bevel_resolution=2
    spl=c.splines.new('POLY');spl.points.add(len(pts)-1)
    for p,v in zip(spl.points,pts):p.co=(*v,1)
    o=bpy.data.objects.new('C55 | '+name,c);col.objects.link(o);o.parent=parent;c.materials.append(mat);return o

def text(name,body,pos,size,col,cam,parent=None,mat=white,align='CENTER'):
    c=bpy.data.curves.new('C55 | '+name,'FONT');c.body=body;c.size=size;c.align_x=align
    o=bpy.data.objects.new('C55 | '+name,c);col.objects.link(o);o.location=pos;o.rotation_euler=cam.rotation_euler;o.parent=parent;c.materials.append(mat);return o

def linear(data):
    if not data.animation_data or not data.animation_data.action:return
    for layer in data.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for key in fc.keyframe_points:key.interpolation='LINEAR'

def foot(name,col,parent=None,flatten=False):
    mesh=original.data.copy()
    for vertex,co in zip(mesh.vertices,d['vertices']):
        vertex.co=co
        if flatten:vertex.co.y+=56.65
    mesh.materials.clear();mesh.materials.append(white);mesh.update()
    ob=bpy.data.objects.new('C55 | '+name,mesh);col.objects.link(ob);ob.parent=parent;return ob

def pivot(name,pos,col,mat,parent=None,r=2):
    x,y,z=pos
    return curve(name,[(x+r*math.cos(i*math.tau/32),y-3,z+r*math.sin(i*math.tau/32)) for i in range(33)],col,mat,.45,parent)

def animate_beam(ob,ends,frame):
    for p,v in zip(ob.data.splines[0].points,ends):p.co=(*v,1);p.keyframe_insert('co',frame=frame)

s,col,cam=scene_new('Geometry - Compact 55 mm walk',550,(240,-700,320),(0,0,72))
travel=empty('camera travel',col);cam.parent=travel
root=empty('body motion',col)
# Actual chassis scale, isolated copies; no pretend relocated servo housing CAD.
for src in old.objects:
    if src.type=='MESH' and src.parent and src.parent.name=='R72 | Body' and ('TESTS | Body -' in src.name or 'STRUCTURAL |' in src.name or 'Radxa_Dragon_Q6A_Bottom_Slot' in src.name):
        ob=bpy.data.objects.new(src.name.replace('R72 |','C55 |'),src.data.copy());col.objects.link(ob);ob.parent=root;ob.matrix_basis=src.matrix_basis.copy();ob.data.materials.clear();ob.data.materials.append(gray)
text('walk title','COMPACT 55 mm LEG | WALKING REFERENCE',(0,0,197),9,col,cam,travel)
text('walk subtitle','26 carrier / 21 crank / 23 rod / 27 pickup | 60 mm nominal stroke',(0,0,178),6,col,cam,travel)
text('walk clearance','51 mm modeled body clearance | 2-second cycle',(0,0,160),6,col,cam,travel)
text('walk legend','CYAN carrier   RED crank   ORANGE rod   WHITE lower leg',(0,-140,-28),5.5,col,cam,travel)
text('walk scope','New shaft positions shown; servo housings and mount fit NOT resolved',(0,-140,-43),5.5,col,cam,travel)
text('walk scope2','Calculated motion, not physical walking proof',(0,-140,-56),5,col,cam,travel)
rigs={};feet={};beams={}
for k,leg in enumerate(legs):
    shoulder=empty(leg+' shoulder frame',col,root);S=Matrix(live['legs'][leg]['shoulder_matrix']);M=Matrix(live['legs'][leg]['mechanism_matrix']);shoulder.matrix_basis=S
    lateral=empty(leg+' shoulder rotation',col,shoulder);mech=empty(leg+' mechanism',col,lateral);mech.matrix_basis=S.inverted()@M;rigs[leg]=lateral
    feet[leg]=foot(leg+' Part027 preview',col,mech)
    beams[leg]={key:curve(leg+' '+key,[(0,0,0)]*2,col,mat,r,mech) for key,mat,r in [('carrier26',cyan,2.1),('crank21',red,2.1),('rod23',orange,1.6)]}
    for key,v,mat in [('carrier shaft',O,cyan),('proposed crank shaft',C,red)]:pivot(leg+' '+key,(v.x,-56.65,v.y),col,mat,mech,1.7)
    curve(leg+' shaft reference',[(O.x,-56.65,O.y),(C.x,-56.65,C.y)],col,muted,.5,mech)
    for i in range(N+1):
        j=i%N;frame=i+1;f=d['forward'][leg];q=d['q'][j][k]
        lateral.rotation_euler=(math.radians(q[0]),0,0);lateral.keyframe_insert('rotation_euler',frame=frame)
        D=Vector(f['D'][j]);PP=Vector(f['P'][j]);E=Vector(f['E'][j])
        feet[leg].location=(D.x,0,D.y);feet[leg].rotation_euler=(0,-(f['beta'][j]-par['beta_neutral']),0)
        feet[leg].keyframe_insert('location',frame=frame);feet[leg].keyframe_insert('rotation_euler',frame=frame)
        for key,pair in [('carrier26',(O,D)),('crank21',(C,PP)),('rod23',(PP,E))]:animate_beam(beams[leg][key],[(v.x,-56.65,v.y) for v in pair],frame)
    linear(lateral);linear(feet[leg])
    for ob in beams[leg].values():linear(ob.data)
contacts=[curve(leg+' ground contact',[(2*math.cos(i*math.tau/24),2*math.sin(i*math.tau/24),0) for i in range(25)],col,green,.5) for leg in legs]
for i in range(N+1):
    j=i%N;frame=i+1;progress=i/N*75;shift=d['body_shift'][j]
    root.location=(progress+shift[0],shift[1],d['body_z']);root.keyframe_insert('location',frame=frame)
    travel.location=(progress,0,0);travel.keyframe_insert('location',frame=frame)
    for k,leg in enumerate(legs):
        contact=d['forward'][leg]['contact'][j];ob=contacts[k];ob.location=(progress+shift[0]+contact[0],shift[1]+contact[1],d['body_z']+contact[2]+.3)
        ob.scale=(1,1,1) if d['stance'][j][k] else (.001,.001,.001)
        ob.keyframe_insert('location',frame=frame);ob.keyframe_insert('scale',frame=frame)
linear(root);linear(travel)
for ob in contacts:linear(ob)
mesh=bpy.data.meshes.new('Compact floor');mesh.from_pydata([(-240,-140,-.6),(340,-140,-.6),(340,140,-.6),(-240,140,-.6)],[],[(0,1,2,3)])
floor=bpy.data.objects.new('C55 | ground',mesh);col.objects.link(floor);mesh.materials.append(floor_mat)
for x in range(-225,341,25):curve('floor grid',[(x,-140,-.5),(x,140,-.5)],col,muted,.1)
for y in range(-125,140,25):curve('floor grid',[(-240,y,-.5),(340,y,-.5)],col,muted,.1)
s.frame_set(1);full=s

# Side-on detail: actual foot profile, animated links, dimensions and shaft move.
s,col,cam=scene_new('Geometry - Compact linkage detail',360,(0,-700,65),(0,0,65))
text('detail title','COMPACT LINKAGE | 55 mm LEG',(0,0,165),9,col,cam)
text('detail subtitle','60 mm nominal stroke / 2-second cycle / total lower-leg span 82 mm',(0,0,148),5.5,col,cam)
text('detail heading','ANIMATED SIDE VIEW',(-95,0,127),6,col,cam)
text('dimension heading','INSTALLED  /  REFERENCE',(83,0,127),6,col,cam)
for z,label in [(111,'Lower leg       55  /  55 mm'),(98,'Carrier           35  /  26 mm'),(85,'Crank             20  /  21 mm'),(72,'Rod                38  /  23 mm'),(59,'Pickup            28  /  27 mm')]:text('dimensions '+str(z),label,(83,0,z),5.5,col,cam)
def plane(v):return (v[0]-O.x-95,0,v[1]-O.y+90)
anim=foot('detail Part027',col,flatten=True)
links={key:curve('detail '+key,[(0,0,0)]*2,col,mat,r) for key,mat,r in [('carrier26',cyan,2.1),('crank21',red,2.1),('rod23',orange,1.6)]}
for key,v,mat in [('carrier shaft',O,cyan),('crank shaft',C,red)]:pivot('detail '+key,plane(v),col,mat,r=1.3)
trace=[]
f=d['forward']['FR']
for i in range(N+1):
    j=i%N;D=Vector(f['D'][j]);PP=Vector(f['P'][j]);E=Vector(f['E'][j]);beta=f['beta'][j]
    anim.location=plane(D);anim.rotation_euler=(0,-(beta-par['beta_neutral']),0);anim.keyframe_insert('location',frame=i+1);anim.keyframe_insert('rotation_euler',frame=i+1)
    for key,pair in [('carrier26',(O,D)),('crank21',(C,PP)),('rod23',(PP,E))]:animate_beam(links[key],[plane(v) for v in pair],i+1)
    trace.append(plane(D-55*Vector((math.cos(beta),math.sin(beta)))))
linear(anim)
for ob in links.values():linear(ob.data)
curve('detail toe centre trace',trace,col,green,.35)
text('detail legend','Carrier26 / Crank21 / Rod23',(-95,0,-9),5,col,cam)
text('detail leg dimensions','Knee-to-foot55 / Knee-to-pickup27',(-95,0,-20),4.5,col,cam)
text('shaft heading','SHAFT CENTRES - 2x DETAIL',(83,0,36),5.5,col,cam)
# Diagram has a separate 2x scale, explicitly labelled.
po=(72,0,0);pc=(80,0,0);oldc=(47,0,23)
pivot('shaft diagram carrier',po,col,cyan,r=2);pivot('shaft diagram proposed crank',pc,col,red,r=2);pivot('shaft diagram previous crank',oldc,col,muted,r=2)
curve('shaft relocation',[oldc,pc],col,orange,.4)
curve('shaft diagram separation',[po,pc],col,white,.35)
text('shaft prior','Old crank',(37,0,10),4,col,cam)
text('shaft after','4 mm apart',(100,0,-3),4.5,col,cam)
text('shaft delta','Move +16.5 mm X / -11.5 mm Z',(83,0,-21),4.5,col,cam)
text('detail scope','Mount and housing fit unresolved | reference geometry, not printable CAD',(0,0,-43),5.3,col,cam)
s.frame_set(1);detail=s
readme=bpy.data.texts.new('COMPACT55 REFERENCE - READ ME')
readme.write('Space to play. Two independent scenes: Compact55 walk and Compact linkage detail.\n55 foot /26 carrier /21 crank /23 rod /27 pickup, millimetres between pivot centres.\n60 mm nominal planted sweep; 80% stance; 2s cycle; modeled body clearance51 mm.\n120 solved samples,60fps. Full robot includes actual chassis scale and schematic linkage beams.\nCrank is4 mm ahead of carrier at equal height in mechanism coordinates. This moves it+16.5 X/-11.5 Z from installed geometry.\nServo housings, brackets and link layers are NOT designed or collision-qualified.\nThe reference is not manufacturing CAD and cannot be sent through existing firmware calibration unchanged.\nNo source CAD, firmware, calibration or hardware commands changed.\n')
for scene in [full,detail]:scene['Nominal planted stroke mm']=60;scene['Cycle seconds']=2;scene['Model clearance mm']=51
out=Path('/home/greggles/Ainekio/Slave/hardware/v2-12servo/Ainekio-Compact55-Walking-Reference.blend')
assert not out.exists(), 'Preserve prior saved reference.'
bpy.data.libraries.write(str(out),{full,detail,readme},fake_user=True,compress=True)
full.render.filepath=str(P/'compact55-robot-preview.png');detail.render.filepath=str(P/'compact55-detail-preview.png')
bpy.ops.render.render(scene=detail.name,write_still=True)
bpy.ops.render.render(scene=full.name,write_still=True)
def activate():
    bpy.context.window.scene=bpy.data.scenes['Geometry - Compact 55 mm walk']
    for area in bpy.context.screen.areas:
        if area.type=='VIEW_3D':area.spaces.active.region_3d.view_perspective='CAMERA';area.spaces.active.region_3d.view_camera_zoom=0
    return None
bpy.app.timers.register(activate,first_interval=.3)
print(json.dumps({'file':str(out),'scenes':[full.name,detail.name],'frames':120,'fps':60,'objects':[len(full.objects),len(detail.objects)]}))
