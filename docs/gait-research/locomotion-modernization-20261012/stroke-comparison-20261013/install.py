import bpy,json,math,re
from pathlib import Path
from mathutils import Matrix,Vector
P=Path(__file__).resolve().parent;data=json.loads((P/'cycles.json').read_text());live=json.loads((P/'live45.json').read_text());par=live['params']
source=bpy.data.scenes['Wireless']
name='Gait - 70 vs 82 mm'
assert name not in bpy.data.scenes or len(bpy.data.scenes[name].objects)==0
bpy.ops.wm.save_as_mainfile(filepath=str(P/'before-stroke-comparison.blend'),copy=True)
scene=bpy.data.scenes.get(name) or bpy.data.scenes.new(name);scene.unit_settings.system=source.unit_settings.system;scene.unit_settings.scale_length=source.unit_settings.scale_length
scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_x=1600;scene.render.resolution_y=900;scene.render.resolution_percentage=100;scene.render.fps=24;scene.frame_start=1;scene.frame_end=96
scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL';scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True;scene.display.shading.background_type='WORLD';scene.world=bpy.data.worlds.new('Stroke comparison world');scene.world.color=(.045,.045,.045)
scene['Study']='70 versus 82 mm; actual 45 mm Part027; 35/20/28/30 linkage';scene['Qualification']='Kinematic research. No physical walking proof. Return exceeds reviewed crank calibration. No collision qualification.'
scene['Cycle seconds']=2.;scene['Duty fraction']=.75;scene['Body clearance mm']=35.;scene['Lift mm']=12.
manifest=json.loads(bpy.data.texts['ROBOT - Approved playback parts.json'].as_string())['source_names']
manifest=list(dict.fromkeys(manifest+[o.name for o in source.objects if o.type=='MESH' and o.name.startswith('REFINED | ') and any(k in o.name for k in ['Part_009','Part_023','Part_026','Part_027','Horn_009'])]))
sources=[source.objects[n] for n in manifest if n in source.objects and not any(x in n for x in ['Part_020','Part_021','Part_022','CARAPACE | Rear helmet'])]
anchor_re=re.compile(r'^REFINED \| (FL|FR|RL|RR) \| (foot|primary|input|rod)$')
bpy.context.window.scene=source;dg=bpy.context.evaluated_depsgraph_get();dg.update();staged=[]
for o in sources:
 ancestor=o.parent
 while ancestor and not anchor_re.match(ancestor.name):ancestor=ancestor.parent
 mesh=bpy.data.meshes.new_from_object(o.evaluated_get(dg),depsgraph=dg,preserve_all_data_layers=True);mesh.name='STUDY mesh | '+o.name
 relative=ancestor.matrix_world.inverted()@o.matrix_world if ancestor else o.matrix_world.copy()
 staged.append((o,mesh,ancestor.name if ancestor else None,relative))

def mat(n,c):
 m=bpy.data.materials.new(n);m.diffuse_color=(*c,1);m.use_nodes=True;node=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');node.inputs['Base Color'].default_value=(*c,1);return m
cyan=mat('Study 70 cyan',(.035,.7,.95));orange=mat('Study 82 orange',(1,.35,.04));white=mat('Study text',(.9,.95,1));gray=mat('Study floor',(.12,.15,.18))
def empty(n,col,parent=None):
 o=bpy.data.objects.new(n,None);col.objects.link(o);o.parent=parent;return o

def curve(n,points,col,material,radius=.45):
 c=bpy.data.curves.new(n,'CURVE');c.dimensions='3D';c.bevel_depth=radius;c.bevel_resolution=2;s=c.splines.new('POLY');s.points.add(len(points)-1)
 for p,v in zip(s.points,points):p.co=(*v,1)
 o=bpy.data.objects.new(n,c);col.objects.link(o);c.materials.append(material);return o

phase_offsets={'RL':0.,'RR':.5,'FL':.75,'FR':.25};roots=[]
for case,xoff,color in zip(data['cases'],[-175.,175.],[cyan,orange]):
 stroke=case['stroke_mm'];prefix=f'S{stroke} | ';col=bpy.data.collections.new(prefix+'Robot');scene.collection.children.link(col);root=empty(prefix+'Body',col);root.location=(xoff,0,data['body_translation_z']);roots.append(root)
 anchors={}
 for leg in phase_offsets:
  m=Matrix(live['legs'][leg]['mechanism_matrix']);mech=empty(prefix+leg+' mechanism',col,root);mech.matrix_basis=m
  for part in ['primary','input','foot','rod']:anchors['REFINED | '+leg+' | '+part]=empty(prefix+leg+' '+part,col,mech)
 for original,mesh,an,relative in staged:
  o=bpy.data.objects.new(prefix+original.name,mesh);col.objects.link(o);o.parent=anchors[an] if an else root;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_basis=relative;o.color=original.color;o['source_object']=original.name
  for index,slot in enumerate(original.material_slots):
   if slot.link=='OBJECT':o.material_slots[index].link='OBJECT';o.material_slots[index].material=slot.material
 rows=case['rows']
 for frame in range(1,98):
  for leg,offset in phase_offsets.items():
   ph=((frame-1)/48+offset)%1.;f=ph*240;i=int(f);t=f-i;r1=rows[i];r2=rows[min(i+1,240)]
   def mix(k):
    v,w=r1[k],r2[k]
    return [a+(b-a)*t for a,b in zip(v,w)] if isinstance(v,list) else v+(w-v)*t
   q=mix('q');D=mix('D');Piv=mix('P');beta=mix('beta');phi=mix('phi');a=math.radians(q[0])+par['alpha_neutral'];theta=math.radians(q[1])+par['firmware_theta_zero_rad']
   for part,loc,rot in [('primary',(par['O'][0],0,par['O'][1]),-a+par['alpha_neutral']),('input',(par['C_new'][0],0,par['C_new'][1]),-theta+par['old_theta_neutral']),('foot',(D[0],0,D[1]),-(beta-par['beta_neutral'])),('rod',(Piv[0],0,Piv[1]),-(phi-par['old_rod_reference_angle']))]:
    o=anchors['REFINED | '+leg+' | '+part];o.location=loc;o.rotation_euler=(0,rot,0);o.keyframe_insert('location',frame=frame);o.keyframe_insert('rotation_euler',frame=frame)
   o=anchors['REFINED | '+leg+' | primary'];o['Carrier deg']=q[0];o['Crank deg']=q[1];o.keyframe_insert('["Carrier deg"]',frame=frame);o.keyframe_insert('["Crank deg"]',frame=frame)
 for o in anchors.values():
  if o.animation_data and o.animation_data.action:
   act=o.animation_data.action
   for layer in act.layers:
    for strip in layer.strips:
     for bag in strip.channelbags:
      for fc in bag.fcurves:
       for kp in fc.keyframe_points:kp.interpolation='LINEAR'
 # Right-front foot trajectory, with actual lowest mesh surface at each pose.
 yy=-64.5
 pts=[(xoff+4.100021+r['x'],yy,r['sole_z']+data['body_translation_z']+.25) for r in rows]
 curve(prefix+'Foot sole path',pts,col,color,.55)
 lo=xoff+34.5;hi=lo+stroke
 curve(prefix+'Planted stroke ruler',[(lo,-95,1),(hi,-95,1)],col,color,.7)
 for xx in [lo,hi]:curve(prefix+'Endpoint',[(xx,-98,1),(xx,-92,1)],col,color,.7)
 root['Stroke mm']=stroke;root['Cycle seconds']=2;root['Carrier full cycle range deg']=case['angle_range_deg'][0];root['Crank full cycle range deg']=case['angle_range_deg'][1]
# Presentation camera and text face the camera direction.
col=bpy.data.collections.new('Stroke comparison presentation');scene.collection.children.link(col)
camdata=bpy.data.cameras.new('Stroke comparison camera');camera=bpy.data.objects.new('Stroke comparison camera',camdata);col.objects.link(camera);camera.location=(0,-650,310);target=Vector((0,0,55));camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler();camdata.type='ORTHO';camdata.ortho_scale=740;camdata.clip_end=5000;scene.camera=camera

def text(n,body,loc,size,material):
 c=bpy.data.curves.new(n,'FONT');c.body=body;c.size=size;c.align_x='CENTER';o=bpy.data.objects.new(n,c);col.objects.link(o);o.location=loc;o.rotation_euler=camera.rotation_euler;c.materials.append(material);return o
text('Study title','45 mm LEG | 70 vs 82 mm WALK STROKE',(0,0,195),13,white)
text('Study subtitle','35 carrier / 20 crank / 28 pickup / 30 rod | dimensions in mm',(0,0,176),7,white)
for case,xoff,color in zip(data['cases'],[-175.,175.],[cyan,orange]):
 a,c=case['angle_range_deg'];text(f"Title {case['stroke_mm']}",f"{case['stroke_mm']} mm PLANTED STROKE",(xoff,0,149),11,color)
 text(f"Travel {case['stroke_mm']}",f"FULL CYCLE: carrier {a[1]-a[0]:.0f} deg | crank {c[1]-c[0]:.0f} deg",(xoff,0,127),6.5,white)
text('Study conditions','SAME CAD / 2 s CYCLE / 35 mm BODY CLEARANCE / 12 mm LIFT',(0,-80,-47),7,white)
text('Study scope','IN-PLACE KINEMATICS | return exceeds current crank calibration | not hardware-qualified',(0,-80,-64),6,white)
mesh=bpy.data.meshes.new('Study floor mesh');mesh.from_pydata([(-500,-150,-1),(500,-150,-1),(500,150,-1),(-500,150,-1)],[],[(0,1,2,3)]);o=bpy.data.objects.new('Study floor',mesh);col.objects.link(o);mesh.materials.append(gray)
for frame,label in [(1,'Cycle 1'),(25,'Half cycle'),(49,'Cycle 2')]:scene.timeline_markers.new(label,frame=frame)
t=bpy.data.texts.new('STROKE COMPARISON - READ ME');t.write('Space: play 70 and 82 mm side by side. Scene: '+name+'\nActual Wireless 45 mm bare Part027 / 35 carrier / 20 crank / 28 pickup / 30 rod.\nConstant-speed planted reference path, 75% stance, 12 mm return lift, 2 second cycle. Source CAD and other gait scenes retained.\nBody is fixed for comparison: floor-relative sliding represents body-frame motion, not simulated traction. Planned contact is not measured contact. No COM dynamics.\nComplete return path requires approximately 379 / 373 us crank minima against the current 400 us reviewed endpoint. Geometry is shown without clipping. No firmware changes.\n')
bpy.context.window.scene=scene;scene.frame_set(1)
for screen in bpy.data.screens:
 for area in screen.areas:
  if area.type=='VIEW_3D':area.spaces.active.region_3d.view_perspective='CAMERA'
print(json.dumps({'scene':name,'objects':len(scene.objects),'source_parts':len(staged),'frames':[1,96],'roots':[r.name for r in roots]}))
