"""Add an isolated preview using the edited meshes and firmware angle reference.

Run inside Blender with MODEL_ROOT. Caller owns recovery and saving.
The Wireless modeling scene and mesh data are preserved.
"""
import bpy,json,math
from pathlib import Path
import numpy as np
from mathutils import Euler,Vector
root=Path(MODEL_ROOT)
source=bpy.data.scenes['Wireless'];scene=bpy.data.scenes.new('Seated Support - 35-20-28')
scene.unit_settings.system=source.unit_settings.system;scene.unit_settings.scale_length=source.unit_settings.scale_length
scene.render.fps=30;scene.render.fps_base=1;scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_x=1280;scene.render.resolution_y=800
scene.world=source.world;scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL';scene.display.shading.show_shadows=True
collection=bpy.data.collections.new('SEATED REMAP - Preview');scene.collection.children.link(collection)
original_root=bpy.data.objects['TESTS - CAD to Research World'];objects=[original_root]+list(original_root.children_recursive);mapping={}
for obj in objects:
 clone=obj.copy();clone.name='SEATED | '+obj.name;collection.objects.link(clone);mapping[obj]=clone
 if clone.animation_data:
  clone.animation_data.action=None
  for track in list(clone.animation_data.nla_tracks):clone.animation_data.nla_tracks.remove(track)
  for curve in list(clone.animation_data.drivers):
   if curve.data_path in ['hide_viewport','hide_render']:clone.driver_remove(curve.data_path)
 if obj.type=='MESH':clone.hide_viewport=not obj.visible_get();clone.hide_render=clone.hide_viewport
for obj,clone in mapping.items():
 clone.parent=mapping.get(obj.parent)
 if clone.animation_data:
  for curve in clone.animation_data.drivers:
   for variable in curve.driver.variables:
    for target in variable.targets:
     if target.id in mapping:target.id=mapping[target.id]
 for constraint in clone.constraints:
  if hasattr(constraint,'target') and constraint.target in mapping:constraint.target=mapping[constraint.target]
body=bpy.data.objects.new('SEATED | Body motion',None);collection.objects.link(body);mapping[original_root].parent=body
frames=[];qs=[];locations=[];rotations=[];chapters=[];cursor=1;pivot=Vector((0,0,65))
for command in ['sit','wave','upright']:
 path=root/f'motions/gestures/{command}/source.json';rows=json.loads(path.read_text())['samples'];start=cursor
 for row in rows:
  frames.append(cursor+row['time_s']*30);qs.append(np.degrees(row['actuator_angles_rad']));e=Euler(row['body_rotation_euler_xyz_rad'],'XYZ');locations.append(Vector(row['body_translation_world_mm'])+pivot-e.to_matrix()@pivot);rotations.append(e)
 end=frames[-1];cursor=math.ceil(end)+31;chapters.append(dict(command=command,start_frame=start,end_frame=end,source=str(path),firmware_integrated=False))
 scene.timeline_markers.new(command.title(),frame=start)
frames=np.array(frames);qs=np.array(qs);locations=np.array(locations);rotations=np.array(rotations);endpoints={c['end_frame'] for c in chapters}
def bake(obj,channels):
 for path,index,values in channels:
  obj.keyframe_insert(data_path=path,index=index,frame=float(frames[0]));action=obj.animation_data.action
  curve=next(f for layer in action.layers for strip in layer.strips for bag in strip.channelbags for f in bag.fcurves if f.data_path==path and f.array_index==max(0,index))
  curve.keyframe_points.clear();curve.keyframe_points.add(len(frames));curve.keyframe_points.foreach_set('co',np.c_[frames,values].ravel())
  for key,frame in zip(curve.keyframe_points,frames):key.interpolation='CONSTANT' if frame in endpoints else 'LINEAR'
  curve.update();action.name=obj.name
bake(body,[('location',i,locations[:,i]) for i in range(3)]+[('rotation_euler',i,rotations[:,i]) for i in range(3)])
for i,leg in enumerate(['FL','FR','RL','RR']):
 control=mapping[bpy.data.objects[f'REFINED | {leg} | h alpha theta']];control['Manual leg posing']=False
 bake(control,[(f'["{key}"]',-1,qs[:,i,j]) for j,key in enumerate(['h_deg','alpha_deg','theta_deg'])])
camera=bpy.data.objects.new('SEATED | Camera',bpy.data.cameras.new('SEATED | Camera'));collection.objects.link(camera);camera.location=(300,400,300);camera.rotation_euler=(Vector((-35,0,105))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=500;camera.data.clip_end=2000;scene.camera=camera
mesh=bpy.data.meshes.new('SEATED | Floor');mesh.from_pydata([(-400,-300,-.05),(400,-300,-.05),(400,300,-.05),(-400,300,-.05)],[],[(0,1,2,3)]);floor=bpy.data.objects.new('SEATED | Floor',mesh);collection.objects.link(floor)
scene.frame_start=1;scene.frame_end=math.ceil(frames[-1]);scene['seated_remap_chapters']=json.dumps(chapters);scene['geometry_id']=json.loads((root/'geometry.json').read_text())['geometry_id'];scene['hardware_qualified']=False
scene['Remap scope']='Sit and Wave support retained; Upright full vertical rise with 76.58 mm closest forelimb reach versus 90.34 mm baseline. No physical calibration or firmware installation.'
scene.frame_set(1)
print(json.dumps(dict(scene=scene.name,objects=len(mapping),samples=len(frames),chapters=chapters)))
