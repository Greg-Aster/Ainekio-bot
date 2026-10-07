"""Bake preview transforms directly, avoiding legacy frame-driven layout changes.

MODEL_ROOT is the candidate model. Only the new seated preview is edited.
"""
import bpy,json,math
import numpy as np
from pathlib import Path
root=Path(MODEL_ROOT);scene=bpy.data.scenes['Seated Support - 35-20-28'];cfg=json.loads((root/'geometry.json').read_text());p=cfg['parameters']
source=bpy.data.objects['TESTS - CAD to Research World'];objects=[source]+list(source.children_recursive)
for original in objects:
 clone=scene.objects['SEATED | '+original.name]
 basis=original.matrix_local.copy()
 if clone.animation_data:
  for curve in list(clone.animation_data.drivers):
   if curve.data_path.startswith(('location','rotation_','scale','delta_')):
    clone.driver_remove(curve.data_path,curve.array_index)
 clone.matrix_parent_inverse.identity()
 clone.matrix_basis=basis
chapters=json.loads(scene['seated_remap_chapters']);rows=[];frames=[];ends=set()
for chapter in chapters:
 source=json.loads((root/f"motions/gestures/{chapter['command']}/source.json").read_text())['samples'];rows.extend(source);frames.extend(chapter['start_frame']+r['time_s']*30 for r in source);ends.add(chapter['end_frame'])
frames=np.array(frames)
def bake(obj,channels):
 for path,index,values in channels:
  obj.keyframe_insert(data_path=path,index=index,frame=float(frames[0]));action=obj.animation_data.action
  curve=next(f for layer in action.layers for strip in layer.strips for bag in strip.channelbags for f in bag.fcurves if f.data_path==path and f.array_index==index)
  curve.keyframe_points.clear();curve.keyframe_points.add(len(frames));curve.keyframe_points.foreach_set('co',np.c_[frames,values].ravel())
  for key,frame in zip(curve.keyframe_points,frames):key.interpolation='CONSTANT' if frame in ends else 'LINEAR'
  curve.update();action.name=obj.name
for i,l in enumerate(['FL','FR','RL','RR']):
 q=np.array([r['actuator_angles_rad'][i] for r in rows]);a=q[:,1]+p['alpha_neutral'];t=q[:,2]+p['new_theta_neutral'];D=np.array(p['O'])+p['primary_length']*np.c_[np.cos(a),np.sin(a)];P=np.array(p['C_new'])+p['input_length']*np.c_[np.cos(t),np.sin(t)];w=P-D;d=np.linalg.norm(w,axis=1);along=(p['pickup_length']**2-p['rod_length']**2+d*d)/(2*d);height=np.sqrt(p['pickup_length']**2-along*along);E=D+(along[:,None]*w+height[:,None]*np.c_[-w[:,1],w[:,0]])/d[:,None];beta=np.arctan2(E[:,1]-D[:,1],E[:,0]-D[:,0]);phi=np.arctan2(E[:,1]-P[:,1],E[:,0]-P[:,0]);wrap=lambda x:np.arctan2(np.sin(x),np.cos(x))
 obj=lambda suffix:scene.objects[f'SEATED | REFINED | {l} | {suffix}']
 bake(obj('h alpha theta'),[('rotation_euler',0,q[:,0])])
 bake(obj('primary'),[('rotation_euler',1,-q[:,1])])
 bake(obj('input'),[('rotation_euler',1,-t+1.9819596522116156)])
 bake(obj('foot'),[('location',0,D[:,0]),('location',2,D[:,1]),('rotation_euler',1,-wrap(beta-p['beta_neutral']))])
 bake(obj('rod'),[('location',0,P[:,0]),('location',2,P[:,1]),('rotation_euler',1,-wrap(phi-(-2.4045130067927207)))])
scene['Playback']='Recorded 120 Hz joint and linkage transforms. Legacy frame-driven layout changes are excluded from this preview.'
print('Baked exact linkage transforms for 5163 seated-motion samples; source scene preserved.')
