"""Bake the full candidate library in an isolated Blender scene.

Run inside Blender with MODEL_ROOT set to the expanded candidate model.
The caller preserves recovery and owns saving. Existing scenes are unchanged.
"""
import bpy,json,math
from pathlib import Path
import numpy as np
from mathutils import Euler,Vector

root=Path(MODEL_ROOT);cfg=json.loads((root/'geometry.json').read_text());p=cfg['parameters']
source=bpy.data.scenes['Seated Support - 35-20-28'];name='Motion Library - 35-20-28'
if bpy.data.scenes.get(name):raise ValueError('The candidate library preview already exists.')
# An inactive scene may expose identity cached matrices. Evaluate its own
# dependency graph before freezing mount and mesh transforms for the new scene.
with bpy.context.temp_override(scene=source,view_layer=source.view_layers[0]):
 source.frame_set(source.frame_current,subframe=source.frame_subframe);source.view_layers[0].update();dg=bpy.context.evaluated_depsgraph_get()
 local={obj:obj.evaluated_get(dg).matrix_local.copy() for obj in source.objects}
scene=bpy.data.scenes.new(name);scene.unit_settings.system=source.unit_settings.system;scene.unit_settings.scale_length=source.unit_settings.scale_length
scene.render.fps=30;scene.render.fps_base=1;scene.render.engine=source.render.engine;scene.render.resolution_x=1280;scene.render.resolution_y=800
scene.world=source.world;scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL';scene.display.shading.show_shadows=True
collection=bpy.data.collections.new('COMPACT MOTION LIBRARY - Preview');scene.collection.children.link(collection);mapping={}
for obj in source.objects:
 clone=obj.copy();clone.name='LIBRARY | '+obj.name.removeprefix('SEATED | ');collection.objects.link(clone);mapping[obj]=clone;clone.animation_data_clear()
for obj,clone in mapping.items():
 clone.parent=mapping.get(obj.parent);clone.matrix_parent_inverse.identity();clone.matrix_basis=local[obj]
 for constraint in clone.constraints:
  if hasattr(constraint,'target') and constraint.target in mapping:constraint.target=mapping[constraint.target]
 for modifier in clone.modifiers:
  for prop in modifier.bl_rna.properties:
   if prop.type=='POINTER' and not prop.is_readonly:
    value=getattr(modifier,prop.identifier,None)
    if isinstance(value,bpy.types.Object) and value in mapping:setattr(modifier,prop.identifier,mapping[value])
scene.camera=mapping[source.camera]
catalog=json.loads((root/'motions/gestures/catalog.json').read_text());commands=[item['command'] for item in catalog['commands']]
frames=[];rows=[];chapters=[];cursor=1
archive=str(Path(__file__).with_name('motion-library-candidate.zip'))
for command in commands:
 path=root/f'motions/gestures/{command}/source.json';samples=json.loads(path.read_text())['samples'];start=cursor
 frames.extend(cursor+r['time_s']*30 for r in samples);rows.extend(samples);end=frames[-1]
 chapters.append(dict(command=command,start_frame=start,end_frame=end,source=str(path.relative_to(root)),candidate_archive=archive,firmware_integrated=False))
 scene.timeline_markers.new(command.replace('_',' ').title(),frame=start);cursor=math.ceil(end)+31
frames=np.array(frames);ends={c['end_frame'] for c in chapters};q=np.array([r['actuator_angles_rad'] for r in rows]);pivot=Vector(cfg['continuous_walk']['body_rotation_pivot_mm'])
def bake(obj,channels):
 for path,index,values in channels:
  obj.keyframe_insert(data_path=path,index=index,frame=float(frames[0]));action=obj.animation_data.action
  curve=next(f for layer in action.layers for strip in layer.strips for bag in strip.channelbags for f in bag.fcurves if f.data_path==path and f.array_index==max(0,index))
  curve.keyframe_points.clear();curve.keyframe_points.add(len(frames));curve.keyframe_points.foreach_set('co',np.c_[frames,values].ravel())
  for key,frame in zip(curve.keyframe_points,frames):key.interpolation='CONSTANT' if frame in ends else 'LINEAR'
  curve.update();action.name=obj.name
body=scene.objects['LIBRARY | Body motion'];locations=[];rotations=[]
for row in rows:
 e=Euler(row['body_rotation_euler_xyz_rad'],'XYZ');locations.append(Vector(row['body_translation_world_mm'])+pivot-e.to_matrix()@pivot);rotations.append(e)
locations=np.array(locations);rotations=np.array(rotations)
bake(body,[('location',i,locations[:,i]) for i in range(3)]+[('rotation_euler',i,rotations[:,i]) for i in range(3)])
for i,leg in enumerate(['FL','FR','RL','RR']):
 joint=q[:,i];a=joint[:,1]+p['alpha_neutral'];t=joint[:,2]+p['new_theta_neutral'];D=np.array(p['O'])+p['primary_length']*np.c_[np.cos(a),np.sin(a)];P=np.array(p['C_new'])+p['input_length']*np.c_[np.cos(t),np.sin(t)]
 w=P-D;d=np.linalg.norm(w,axis=1);along=(p['pickup_length']**2-p['rod_length']**2+d*d)/(2*d);height=np.sqrt(p['pickup_length']**2-along*along);E=D+(along[:,None]*w+height[:,None]*np.c_[-w[:,1],w[:,0]])/d[:,None]
 beta=np.arctan2(E[:,1]-D[:,1],E[:,0]-D[:,0]);phi=np.arctan2(E[:,1]-P[:,1],E[:,0]-P[:,0]);wrap=lambda x:np.arctan2(np.sin(x),np.cos(x))
 obj=lambda suffix:scene.objects[f'LIBRARY | REFINED | {leg} | {suffix}']
 control=obj('h alpha theta');control['Manual leg posing']=False
 bake(control,[(f'["{key}"]',-1,np.degrees(joint[:,j])) for j,key in enumerate(['h_deg','alpha_deg','theta_deg'])]+[('rotation_euler',0,joint[:,0])])
 bake(obj('primary'),[('rotation_euler',1,-joint[:,1])]);bake(obj('input'),[('rotation_euler',1,-t+1.9819596522116156)])
 bake(obj('foot'),[('location',0,D[:,0]),('location',2,D[:,1]),('rotation_euler',1,-wrap(beta-p['beta_neutral']))])
 bake(obj('rod'),[('location',0,P[:,0]),('location',2,P[:,1]),('rotation_euler',1,-wrap(phi+2.4045130067927207))])
scene.frame_start=1;scene.frame_end=math.ceil(frames[-1]);scene['motion_library_chapters']=json.dumps(chapters);scene['geometry_id']=cfg['geometry_id'];scene['hardware_qualified']=False
scene['Playback']='Recorded 120 Hz transforms at 30 fps with quarter-frame keys. Chapter boundaries are presentation cuts.'
scene['Review notes']='Complete offline library candidate. Upright retains its disclosed 76.585 mm reach and input dead center; original reach was 90.339 mm. Geometry collisions and physical calibration remain unqualified.'
scene.frame_set(1)
print(json.dumps(dict(scene=scene.name,objects=len(mapping),samples=len(rows),chapters=chapters)))
