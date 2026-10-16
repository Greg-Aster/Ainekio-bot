"""Create an isolated, animated schematic in live Blender; preserve existing scenes."""
import bpy,json,math
from pathlib import Path
from mathutils import Vector
P=Path('/home/greggles/Ainekio/docs/gait-research/locomotion-modernization-20261012/geometry-ratios-20261013')
d=json.loads((P/'compact39-blender-motion.json').read_text())
name='Geometry - Compact39 proposed linkage'
assert name not in bpy.data.scenes, 'Reference already exists; inspect before replacing'
s=bpy.data.scenes.new(name);bpy.context.window.scene=s
s.unit_settings.system='METRIC';s.unit_settings.scale_length=.001;s.unit_settings.length_unit='MILLIMETERS'
s.frame_start=1;s.frame_end=120;s.render.fps=120;s.render.fps_base=.9
s['description']='Proposed 20 crank / 39 carrier / 56 rod / 55 foot / 28 pickup, mm. Mechanism-local projection of audited RL cycle. Body and shoulder motion omitted. Schematic, not manufacturing CAD or physical walking proof.'
s['crank_shaft_local_xz_mm']=[15.5,21.2];s['source']='compact83-rounded39.json + body-audit-compact83-rounded39-n1920.json'
colors={'carrier':(.1,.48,.95,1),'crank':(1,.37,.06,1),'rod':(.65,.27,.85,1),'foot':(.12,.7,.4,1),'pickup':(.62,.78,.22,1),'ink':(.72,.8,.88,1),'muted':(.28,.34,.42,1),'white':(.94,.96,1,1)}
mats={}
for key,c in colors.items():
 m=bpy.data.materials.new('C39 '+key);m.diffuse_color=c;m.use_nodes=True
 bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');bs.inputs['Base Color'].default_value=c;mats[key]=m

def add(name,data,mat):
 o=bpy.data.objects.new('C39 | '+name,data);s.collection.objects.link(o)
 if hasattr(data,'materials'):data.materials.append(mats[mat])
 return o

def pos(p,y=0):return Vector((float(p[0]),y,float(p[1])))

def line(name,pts,mat,r=.45):
 c=bpy.data.curves.new(name,'CURVE');c.dimensions='3D';c.bevel_depth=r;c.bevel_resolution=3
 sp=c.splines.new('POLY');sp.points.add(len(pts)-1)
 for q,p in zip(sp.points,pts):q.co=(*p,1)
 return add(name,c,mat)

def bar(name,length,mat,r=2):
 o=line(name,[(0,0,0),(0,0,length)],mat,r);o.rotation_mode='QUATERNION';o['joint_distance_mm']=length
 return o

def orient(o,p,q):
 o.location=p;o.rotation_quaternion=(q-p).to_track_quat('Z','Y')

def text(name,body,x,z,size=3.1,mat='ink'):
 c=bpy.data.curves.new(name,'FONT');c.body=body;c.size=size;c.space_line=1.25
 o=add(name,c,mat);o.location=(x,-10,z);o.rotation_euler=(math.pi/2,0,0);return o

def pivot(name,p,mat='white'):
 # Ring in the mechanism plane; through-hole center stays visible.
 pts=[pos(p,-5)+Vector((2.3*math.cos(t),0,2.3*math.sin(t))) for t in [i*2*math.pi/32 for i in range(33)]]
 return line(name,pts,mat,.7)

C=pos(d['C']);O=pos([0,0]);old=pos([-12.5,11.5])
line('shaft baseline',[O,C],'muted',.65)
line('installed shaft to proposed shaft',[old,C],'muted',.35)
pivot('carrier shaft O',[0,0]);pivot('proposed crank shaft C',d['C']);pivot('installed crank shaft reference',[-12.5,11.5],'muted')
text('carrier label','O',-6,-2,3.6,'white');text('crank label','C',19,23,3.6,'white')
text('old mount label','old C',-27,14,2.5,'muted')
line('local X',[pos([-28,-2],3),pos([35,-2],3)],'muted',.18)
line('local Z',[pos([-2,-12],3),pos([-2,34],3)],'muted',.18)
text('x axis','+X',32,-7,2.4,'muted');text('z axis','+Z',-8,33,2.4,'muted')
carrier=bar('carrier 39 mm',39,'carrier');crank=bar('crank 20 mm',20,'crank');rod=bar('rod 56 mm',56,'rod',1.4)
foot=bar('knee to foot 55 mm',55,'foot',1.3);pickup=bar('knee to pickup 28 mm',28,'pickup',1.3)
h=d['hull'];n=len(h);verts=[(x,y,z) for y in [-1.5,1.5] for x,z in h]
faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
mesh=bpy.data.meshes.new('Existing lower-leg projected envelope');mesh.from_pydata(verts,[],faces);mesh.update()
leg=add('existing 55-28 leg silhouette (projected envelope)',mesh,'muted')
leg['scope']='Extruded projected convex envelope of existing bare Part027; not detailed manufacturing mesh.'
markers=[]
for key in ['D','E','P','F']:
 o=pivot('moving joint '+key,[0,0]);markers.append((key,o))
for i in range(121):
 j=i%120;fr=i+1;D=pos(d['D'][j]);E=pos(d['E'][j]);PP=pos(d['P'][j]);F=pos(d['F'][j])
 for o,p,q in [(carrier,O,D),(crank,C,PP),(rod,PP,E),(foot,D+Vector((0,-3,0)),F+Vector((0,-3,0))),(pickup,D+Vector((0,-3,0)),E+Vector((0,-3,0)))]:
  orient(o,p,q);o.keyframe_insert('location',frame=fr);o.keyframe_insert('rotation_quaternion',frame=fr)
 leg.location=D;leg.rotation_euler=(0,-d['beta'][j],0);leg.keyframe_insert('location',frame=fr);leg.keyframe_insert('rotation_euler',frame=fr)
 for key,o in markers:o.location=pos(d[key][j]);o.keyframe_insert('location',frame=fr)
# Dense sampled keys follow the solved cycle; avoid Bezier overshoot between samples.
for o in [carrier,crank,rod,foot,pickup,leg]+[x[1] for x in markers]:
 act=o.animation_data.action
 for layer in act.layers:
  for strip in layer.strips:
   for bag in strip.channelbags:
    for fc in bag.fcurves:
     for kp in fc.keyframe_points:kp.interpolation='LINEAR'
line('foot reference trajectory',[pos(p,4) for p in d['F']+[d['F'][0]]],'foot',.22)
text('heading','COMPACT LINKAGE / 20 mm CRANK',-58,55,4.2,'white')
text('subtitle','Proposed geometry - existing lower leg retained',-58,48,2.8)
text('dimension heading','JOINT DISTANCES',49,32,3.5,'white')
for z,body,mat in [(23,'20 mm  crank','crank'),(16,'39 mm  carrier','carrier'),(9,'56 mm  connecting rod','rod'),(2,'55 mm  knee to foot reference','foot'),(-5,'28 mm  knee to rod pickup','pickup')]:text(body,body,49,z,3,mat)
text('mount dimensions','CRANK SHAFT FROM CARRIER\nX +15.5 mm / Z +21.2 mm\n\nMount shift from installed:\nX +28.0 mm / Z +9.7 mm',49,-19,2.8)
text('animation details','PLAY / SCRUB FRAMES 1-120\n40 mm planted sweep / 0.9 s cycle\nMechanism-local view; shoulder and\nbody motion omitted.',49,-57,2.65)
text('qualification','Schematic reference - motor housings / mount fit unverified',-58,-108,2.7)
for fr,title in [(1,'Stance begins'),(49,'Mid stance'),(97,'Swing begins')]:s.timeline_markers.new(title,frame=fr)
camdata=bpy.data.cameras.new('C39 reference camera');cam=add('reference camera',camdata,'ink');cam.location=(40,-350,-24);target=Vector((40,0,-24));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();camdata.type='ORTHO';camdata.ortho_scale=225;camdata.clip_end=2000;s.camera=cam
s.render.engine='BLENDER_WORKBENCH';s.display.shading.light='STUDIO';s.display.shading.color_type='MATERIAL';s.display.shading.show_shadows=True;s.display.shading.show_cavity=True;s.display.shading.background_type='WORLD'
s.world=bpy.data.worlds.new('C39 dark background');s.world.color=(.018,.026,.04)
s.render.resolution_x=1450;s.render.resolution_y=1150;s.render.resolution_percentage=100
s.frame_set(49)
for screen in bpy.data.screens:
 for area in screen.areas:
  if area.type=='VIEW_3D':
   space=area.spaces.active;space.region_3d.view_perspective='CAMERA';space.region_3d.view_camera_zoom=0;space.shading.color_type='MATERIAL';space.clip_end=10000
out=Path('/home/greggles/Ainekio/Slave/hardware/v2-12servo/Ainekio-Compact39-Linkage-Reference.blend')
assert not out.exists(), 'Do not overwrite existing file'
bpy.data.libraries.write(str(out),{s},fake_user=True,compress=True)
print(json.dumps({'scene':s.name,'saved':str(out),'objects':len(s.objects),'frames':[1,120],'source_file_preserved':bpy.data.filepath}))
