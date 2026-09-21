"""Append the reviewed batch to a preserved live robot, using one animation writer.

Run this script from Blender; earlier curves and model meshes remain intact.
"""
import bpy,json,math
import numpy as np
from pathlib import Path
from mathutils import Euler
P=Path(__file__).resolve().parent
index=json.loads((P/'motion-index.json').read_text());scene=bpy.context.scene
only=globals().get('ONLY_COMMANDS');PRESERVE_FUTURE=bool(only)
items=[m for m in index['commands'] if not only or m['command'] in only]
assert Path(bpy.data.filepath).name in ['Ainekio-Bow.blend','Before-Motion-Batch.blend','Ainekio-Motion-Library.blend']
assert scene.render.fps==24 and scene.render.fps_base==1.
if bpy.context.screen and bpy.context.screen.is_animation_playing:bpy.ops.screen.animation_cancel(restore_frame=False)
first=index['commands'][0]['start_frame'];last=index['commands'][-1]['end_frame']
rig=json.loads((P/'commands'/index['commands'][0]['command']/'blender-rig.json').read_text());par=json.loads((P/'commands'/index['commands'][0]['command']/'robot-gait-parameters.json').read_text());body=bpy.data.objects[rig['body']]
library_copied=set()
collection=bpy.data.collections.get('BATCH - twelve motion commands')
if collection is None:collection=bpy.data.collections.new('BATCH - twelve motion commands');scene.collection.children.link(collection)
def visible_between(ob,lo,hi):
 for path in ['hide_render','hide_viewport']:
  fc=ob.driver_add(path);fc.driver.type='SCRIPTED';fc.driver.expression=f'frame < {lo} or frame >= {hi}'
def material(name,color):
 m=bpy.data.materials.get(name) or bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
 n=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');n.inputs['Base Color'].default_value=(*color,1);n.inputs['Roughness'].default_value=.8
 return m
black=material('BATCH - screen black',(.002,.004,.008));cyan=material('BATCH - face cyan',(.02,.7,1.));amber=material('BATCH - assumed belly support',(.75,.4,.02))
if (P/'prior-display-drivers.json').exists():
 f=P/'fix_display_drivers.py';exec(compile(f.read_text(),str(f),'exec'),{'__file__':str(f)})
# Earlier face layers are untouched before the new batch.
for ob in list(scene.objects):
 if ob.name.startswith(('BOW -','PUSHUP -','NOD -','POINT -','SWIM -','DANCE -','WAVE -','SIT -','REST -')) and ob.animation_data:
  for fc in ob.animation_data.drivers:
   if fc.data_path in ['hide_render','hide_viewport'] and f'frame >= {first}' not in fc.driver.expression:fc.driver.expression=f'({fc.driver.expression}) or frame >= {first}'
for name in ['CRAWL title','CRAWL status','CRAWL scale','CRAWL collision legend']+[f'CRAWL {l} - sole path' for l in ['FL','FR','RL','RR']]:
 ob=bpy.data.objects.get(name)
 if ob:
  for path in ['hide_render','hide_viewport']:
   fc=ob.driver_add(path);fc.driver.type='SCRIPTED';fc.driver.expression=f'frame >= {first}'
for marker in list(scene.timeline_markers):
 if any(m['start_frame']<=marker.frame<=m['end_frame'] for m in items):scene.timeline_markers.remove(marker)
reference=json.loads((P/'commands'/index['commands'][0]['command']/'body-and-face-reference.json').read_text());lo,hi=reference['face_regions']['Robot Face - Screen']['bounds'];x=hi[0]+.045;center=(lo[2]+hi[2])/2

def mesh_object(name,quads,mat,parent=None):
 ob=bpy.data.objects.get(name)
 if ob is None:
  me=bpy.data.meshes.new(name);me.from_pydata([v for q in quads for v in q],[],[tuple(range(4*i,4*i+4)) for i in range(len(quads))]);me.materials.append(mat)
  ob=bpy.data.objects.new(name,me);collection.objects.link(ob);ob.parent=parent
 return ob

def add_face(command,folder,cfg,end):
 start=cfg['gait_start_frame'];prefix='BATCH | '+command+' | '
 quad=[(x,hi[1],hi[2]),(x,lo[1],hi[2]),(x,lo[1],lo[2]),(x,hi[1],lo[2])]
 visible_between(mesh_object(prefix+'screen',[quad],black,body),start,end)
 cues=cfg.get('face_cues',[])
 for ci,cue in enumerate(cues):
  face=cue.get('name',command);paths=sorted((folder/'faces'/face).glob('*.bin'),key=lambda f:int(f.stem));n=len(paths)
  if not paths:continue
  begin=start+float(cue.get('time_s',0))*24;stop=start+float(cues[ci+1].get('time_s',0))*24 if ci+1<len(cues) else end
  fps=cue.get('fps',1);mode=cue.get('mode','once');tick=f'floor((frame-{begin})*{fps}/24)'
  if mode=='loop':select=f'({tick}%{n})'
  elif mode=='boomerang' and n>1:select=f'({n-1}-abs(({tick}%{2*n-2})-{n-1}))'
  else:select=f'min({n-1},{tick})'
  for v,path in enumerate(paths):
   payload=path.read_bytes();assert len(payload)==1024;quads=[];pixel=.3
   for yy in range(64):
    for xx in range(128):
     if payload[yy*16+xx//8]&(0x80>>(xx%8)):
      left=(64-xx)*pixel;right=left-pixel;top=center+(32-yy)*pixel;bottom=top-pixel
      quads.append([(x+.01,left,top),(x+.01,right,top),(x+.01,right,bottom),(x+.01,left,bottom)])
   ob=mesh_object(prefix+f'face {ci} {face} {v}',quads,cyan,body)
   for prop in ['hide_render','hide_viewport']:
    fc=ob.driver_add(prop);fc.driver.type='SCRIPTED';fc.driver.expression=f'frame < {begin} or frame >= {stop} or {select}!={v}'

for item in items:
 command=item['command'];folder=P/'commands'/command;d=json.loads((folder/'source.json').read_text());cfg=d['metadata']['configuration'];rows=d['samples'];end=item['next_start_frame']
 times=np.array([r['time_s'] for r in rows]);frames=cfg['gait_start_frame']+times*24
 exec(compile((P/'animate_curves.py').read_text(),str(P/'animate_curves.py'),'exec'));copied=library_copied
 positions=np.array([r['body_position_world_mm'] for r in rows]);rotations=np.array([r['body_rotation_euler_xyz_rad'] for r in rows]);angles=np.array([r['actuator_angles_rad'] for r in rows]);contacts=np.array([r['contact_world_mm'] for r in rows]);com=np.array([r['assumed_com_world_mm'] for r in rows])
 for j in range(3):animate(body,'location',j,positions[:,j]);animate(body,'rotation_euler',j,rotations[:,j])
 mode=np.array([-1 if r['body_contact_active'] or sum(r['contact_active'])<3 else 0 if all(r['contact_active']) else 1+r['contact_active'].index(False) for r in rows]);animate(body,'["support_mode"]',-1,mode,constant=True)
 for i,leg in enumerate(['FL','FR','RL','RR']):
  for j,(group,axis) in enumerate([('hip',0),('primary',2),('input',2)]):
   ob=bpy.data.objects[rig['controls'][leg][group]];animate(ob,'rotation_euler',axis,angles[:,i,j])
  marker=bpy.data.objects['CRAWL '+leg+' - active sole contact']
  for j in range(3):animate(marker,'location',j,contacts[:,i,j])
  path_name=f'BATCH | {command} | {leg} sole path';path=bpy.data.objects.get(path_name)
  if path is None:
   old=bpy.data.objects[f'CRAWL {leg} - sole path'].data;curve=bpy.data.curves.new(path_name,'CURVE');curve.dimensions='3D';curve.bevel_depth=old.bevel_depth
   for mat in old.materials:curve.materials.append(mat)
   points=contacts[::5,i].copy();points[:,2]+=.25;line=curve.splines.new('POLY');line.points.add(len(points)-1)
   for point,xyz in zip(line.points,points):point.co=(*xyz,1)
   path=bpy.data.objects.new(path_name,curve);collection.objects.link(path)
  visible_between(path,cfg['gait_start_frame'],end)
  ref=bpy.data.objects.get('CRAWL '+leg+' - shoulder vertical reference')
  if ref:
   l=par['legs'][leg];A=np.array(par['controller_from_CAD_rotation']);datum=np.array(par['controller_body_datum_CAD_xyz_mm']);H=np.array(l['hip_axis_point_xyz_mm']);O=np.array(l['pivots_xy_mm']['O']+[H[2]]);origin=[]
   for n,row in enumerate(rows):
    h=angles[n,i,0];v=O-H;v=np.array([v[0],v[1]*math.cos(h)-v[2]*math.sin(h),v[1]*math.sin(h)+v[2]*math.cos(h)]);R=np.array(Euler(tuple(rotations[n]),'XYZ').to_matrix());origin.append(positions[n]+R@A@(H+v-datum))
   origin=np.array(origin)
   for j in range(2):animate(ref,'location',j,origin[:,j])
   animate(ref,'location',2,np.zeros(len(rows)));animate(ref,'scale',2,origin[:,2])
  animate(bpy.data.objects[rig['controls'][leg]['primary']],'["Part023 angle from forward degrees"]',-1,[r['part023_OD_angle_from_forward_degrees'][i] for r in rows])
 for name,count in [('CRAWL - assumed COM',3),('CRAWL - projected assumed COM',2)]:
  for j in range(count):animate(bpy.data.objects[name],'location',j,com[:,j])
 # Belly footprint is an explicitly assumed/measured kinematic support region.
 support_rows=[r for r in rows if r['body_contact_active'] and r.get('body_contact_polygon_world_mm')]
 footprint=support_rows[0]['body_contact_polygon_world_mm'] if support_rows else cfg.get('bottom_contact_polygon_body_xy_mm')
 if footprint:
  vertices=[(xy[0],xy[1],.15) for xy in footprint];patch_name=f'BATCH | {command} | belly support';patch=bpy.data.objects.get(patch_name)
  if patch is None:
   me=bpy.data.meshes.new(patch_name);me.from_pydata(vertices,[],[tuple(range(len(vertices)))]);me.materials.append(amber);patch=bpy.data.objects.new(patch_name,me);collection.objects.link(patch)
  if not support_rows:
   for j in [0,1]:animate(patch,'location',j,positions[:,j])
   animate(patch,'rotation_euler',2,rotations[:,2])
  intervals=[];on=None
  for n,row in enumerate(rows):
   if row['body_contact_active'] and on is None:on=frames[n]
   if on is not None and (not row['body_contact_active'] or n==len(rows)-1):intervals.append(f'({on} <= frame <= {frames[n]})');on=None
  for prop in ['hide_render','hide_viewport']:
   fc=patch.driver_add(prop);fc.driver.type='SCRIPTED';fc.driver.expression='not ('+' or '.join(intervals)+')' if intervals else 'True'
  patch['Meaning']='Declared belly support footprint projected onto floor; load strength and friction unverified.'
 add_face(command,folder,cfg,end)
 for suffix,base_name,message in [('title','CRAWL title','AINEKIO | '+command.upper()),('status','CRAWL status',cfg.get('viewport_label',cfg['display_label'])),('scale','CRAWL scale',f'{rows[-1]["time_s"]:g} s | 12 SERVO GEOMETRIC REFERENCE'),('caveat','CRAWL collision legend','ASSUMED COM | HARDWARE UNQUALIFIED')]:
  template=bpy.data.objects.get(base_name)
  if template:
   name=f'BATCH | {command} | {suffix}';ob=bpy.data.objects.get(name)
   if ob is None:ob=template.copy();ob.data=template.data.copy();ob.animation_data_clear();collection.objects.link(ob);ob.name=name
   ob.data.body=message;visible_between(ob,cfg['gait_start_frame'],end)
 for phase in d['phases']:scene.timeline_markers.new(command.upper()+' | '+phase['kind'],frame=cfg['gait_start_frame']+round(phase['start']*24))
 for name in ['README.md','config.json','execution-contract.json']:
  t=bpy.data.texts.get(command.upper()+' '+name) or bpy.data.texts.new(command.upper()+' '+name);t.clear();t.write((folder/name).read_text())
 print('APPENDED',command,item['start_frame'],item['end_frame'],flush=True)

scene.name='AINEKIO - Motion Library';scene.frame_end=last;scene.use_preview_range=True;scene.frame_preview_start=first;scene.frame_preview_end=last
scene['Command']='motion_library';scene['Motion index']=str(P/'motion-index.json');scene['Versioned data directory']=str(P);scene['Current reference report']=str(P/'README.md');scene['Timeline']='Prior motions through Bow frame 3085; twelve new commands appended.';scene['Source backup']=str(P/'Before-Motion-Batch.blend');scene['Research status']='Twelve V1 gesture adaptations. Geometric closure reviewed; COM assumed. Contact/friction and hardware qualification remain command-specific and unverified.'
for name in ['README.md','motion-index.json','select_motion.py']:
 t=bpy.data.texts.get('BATCH '+name) or bpy.data.texts.new('BATCH '+name);t.clear();t.write((P/name).read_text())
if bpy.context.screen:
 for area in bpy.context.screen.areas:
  if area.type=='VIEW_3D' and area.spaces.active.local_view:
   for ob in collection.objects:ob.local_view_set(area.spaces.active,True)
scene.frame_set(items[0]['review_frames'][1]);bpy.context.view_layer.update()
if (P/'prior-display-drivers.json').exists():
 f=P/'fix_display_drivers.py';exec(compile(f.read_text(),str(f),'exec'),{'__file__':str(f)})
bpy.ops.wm.save_as_mainfile(filepath=str(P/'Ainekio-Motion-Library.blend'),compress=True)
print('SAVED LIBRARY',bpy.data.filepath,flush=True)
