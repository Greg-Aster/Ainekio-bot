"""Focused live-rig comparison at joint extremes and between keys; not collision proof."""
import bpy,json,math,sys
import numpy as np
from pathlib import Path
from mathutils import Matrix,Vector
P=Path(__file__).resolve().parent
sys.path.insert(0,str(P))
import gait_kinematics as g
rig=json.loads((P/'blender-rig.json').read_text())
snap=json.loads((P/'saved-neutral-snapshot.json').read_text())['objects']
d=json.loads((P/'source.json').read_text());cfg=d['metadata']['configuration']
rows=d['samples'];q=np.array([r['actuator_angles_rad'] for r in rows])
chosen=sorted(set(round(t*cfg['sample_hz']) for t in [0.,1.5,1.95,2.4,2.85,3.3,6.,10.5,12.5]))
scene=bpy.context.scene;before=scene.frame_current;playing=bool(bpy.context.screen and bpy.context.screen.is_animation_playing)
if playing:bpy.ops.screen.animation_cancel(restore_frame=False)
A=np.array(g.PARAMETERS['controller_from_CAD_rotation']);datum=np.array(g.PARAMETERS['controller_body_datum_CAD_xyz_mm'])
pairs={'O':('Part_023','Part_025'),'P':('Part_009','Part_024'),'Q':('Part_025','Part_024'),'B':('Part_025','Part_026'),'D':('Part_023','Part_027'),'E':('Part_026','Part_027')}
report=dict(source_blend=bpy.data.filepath,poses=[],maximum_joint_disconnection_mm=0.,maximum_foot_prediction_error_mm=0.,minimum_evaluated_sole_z_mm=1e9,collision_checked=False)
report['minimum_evaluated_part023_angle_degrees']=180.
body_names=json.loads((P/'body-and-face-reference.json').read_text())['included_body_meshes']
try:
 for index in chosen:
  frame=cfg['gait_start_frame']+rows[index]['time_s']*scene.render.fps
  if index not in [0,len(rows)-1]:frame+=.1
  scene.frame_set(math.floor(frame),subframe=frame%1);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
  root=bpy.data.objects[rig['body']].evaluated_get(dg).matrix_world
  body=np.array(root.translation);orientation=np.array(root.to_3x3())
  record={'frame':frame,'legs':{}}
  for leg,par in g.PARAMETERS['legs'].items():
   controls=rig['controls'][leg];angles=[bpy.data.objects[controls['hip']].rotation_euler.x,bpy.data.objects[controls['primary']].rotation_euler.z,bpy.data.objects[controls['input']].rotation_euler.z]
   def point(part,cad):
    old=par['object_prefix']+part;ob=bpy.data.objects[rig['objects'][old]].evaluated_get(dg)
    return ob.matrix_world@(Matrix(snap[old]['world']).inverted()@Vector(cad))
   errors=[]
   for key,(a,b) in pairs.items():
    pv=par['pivots_xy_mm'][key]+[par['hip_axis_point_xyz_mm'][2]]
    errors.append((point(a,pv)-point(b,pv)).length)
   predicted=body+orientation@A@(np.array(g.fk(leg,*angles)['foot_CAD_xyz_mm'])-datum)
   actual=np.array(point('Part_027',par['foot_bolt_reference_xyz_mm']));err=float(np.linalg.norm(predicted-actual))
   low=1e9
   for part in ['Part_020','Part_022']:
    ob=bpy.data.objects[rig['objects'][par['object_prefix']+part]].evaluated_get(dg);mesh=ob.to_mesh()
    vv=np.empty(len(mesh.vertices)*3);mesh.vertices.foreach_get('co',vv);vv=vv.reshape(-1,3);mat=np.array(ob.matrix_world)
    low=min(low,float(np.min(vv@mat[2,:3]+mat[2,3])));ob.to_mesh_clear()
   record['legs'][leg]={'foot_error_mm':err,'maximum_joint_error_mm':max(errors),'minimum_sole_z_mm':low}
   od=point('Part_023',par['pivots_xy_mm']['D']+[par['hip_axis_point_xyz_mm'][2]])-point('Part_023',par['pivots_xy_mm']['O']+[par['hip_axis_point_xyz_mm'][2]])
   carrier_angle=math.degrees(math.atan2(-float(np.dot(np.array(od),orientation[:,2])),float(np.dot(np.array(od),orientation[:,0]))))
   if carrier_angle<0:carrier_angle+=360
   record['legs'][leg]['part023_angle_from_forward_degrees']=carrier_angle
   report['minimum_evaluated_part023_angle_degrees']=min(report['minimum_evaluated_part023_angle_degrees'],carrier_angle)
   report['maximum_joint_disconnection_mm']=max(report['maximum_joint_disconnection_mm'],max(errors))
   report['maximum_foot_prediction_error_mm']=max(report['maximum_foot_prediction_error_mm'],err)
   report['minimum_evaluated_sole_z_mm']=min(report['minimum_evaluated_sole_z_mm'],low)
  for name in rig['objects'].values():
   ob=bpy.data.objects.get(name)
   if ob is None or ob.type!='MESH' or ob.hide_render:continue
   eo=ob.evaluated_get(dg);me=eo.to_mesh();vv=np.empty(len(me.vertices)*3);me.vertices.foreach_get('co',vv);mat=np.array(eo.matrix_world)
   low=float((vv.reshape(-1,3)@mat[2,:3]+mat[2,3]).min());eo.to_mesh_clear()
   if low<report.get('minimum_complete_model_z_mm',1e9):
    report['minimum_complete_model_z_mm']=low;report['lowest_model_object']=name
   if name in body_names:report['minimum_body_z_mm']=min(report.get('minimum_body_z_mm',1e9),low)
  report['poses'].append(record)
finally:
 scene.frame_set(before)
 if playing:bpy.ops.screen.animation_play()
report['sampled_poses']=len(chosen)
(P/'blender-validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='poses'}))
assert report['maximum_joint_disconnection_mm']<.005
assert report['maximum_foot_prediction_error_mm']<.005
assert report['minimum_evaluated_sole_z_mm']>-.05
if cfg.get('part023_forward_limit_degrees') is not None:assert report['minimum_evaluated_part023_angle_degrees']>=cfg['part023_forward_limit_degrees']-.001

assert report['minimum_complete_model_z_mm']>-.05
assert report['minimum_body_z_mm']>1.
