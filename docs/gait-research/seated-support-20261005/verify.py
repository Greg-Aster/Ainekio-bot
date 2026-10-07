"""Independent FK, contact and choreography checks for the seated candidate."""
import argparse,importlib.util,json,math
from pathlib import Path
import numpy as np
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model',type=Path,required=True)
parser.add_argument('--baseline',type=Path,required=True)
args=parser.parse_args();root=args.model;baseline=args.baseline
spec=importlib.util.spec_from_file_location('reference',root/'motions/walk/reference.py');ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
read=lambda p:json.loads(p.read_text());m=ref.Mechanism(read(root/'geometry.json'));old=ref.Mechanism(read(baseline/'geometry.json'));legs=['FL','FR','RL','RR'];hulls=np.load(root/'motions/gestures/sit/posture-hulls.npz');m.hulls=old.hulls={l:hulls['sole_'+l] for l in legs};report={}
for command in ['sit','wave','upright']:
 rows=read(root/f'motions/gestures/{command}/source.json')['samples'];prior=read(baseline/f'motions/gestures/{command}/source.json')['samples'];max_position_error=0.;max_support_rotation_error=0.;min_floor=math.inf;max_planted_z=0.;max_rear_xy_drift=0.;minimum_margin=math.inf;min_body=math.inf;rear_xy=np.array(rows[360]['foot_bolt_world_mm'])[:2,:2]
 assert len(rows)==len(prior)
 for row,original in zip(rows,prior):
  assert row['time_s']==original['time_s'] and row['contact_active']==original['contact_active']
  body=np.array(row['body_translation_world_mm']);m.body_euler=np.array(row['body_rotation_euler_xyz_rad']);old.body_euler=np.array(original['body_rotation_euler_xyz_rad']);support=[]
  for i,l in enumerate(legs):
   q=row['actuator_angles_rad'][i];vertices=m.vertices(l,q,body);point=m.reference(l,q,body);z=vertices[:,2].min();min_floor=min(min_floor,z);max_position_error=max(max_position_error,np.max(abs(point-np.array(row['foot_bolt_world_mm'][i]))))
   if row['contact_active'][i]:max_planted_z=max(max_planted_z,abs(z));support.extend(vertices[vertices[:,2]<z+.5])
   seated_support=i<2 and ((command=='sit' and row['time_s']>=3) or (command=='wave' and 3<=row['time_s']<=12.2) or (command=='upright' and row['time_s']>=3))
   if seated_support:
    R,_=m.pose(l,q,body);Rold,_=old.pose(l,original['actuator_angles_rad'][i],original['body_translation_world_mm']);max_support_rotation_error=max(max_support_rotation_error,float(np.max(abs(R-Rold))))
    max_rear_xy_drift=max(max_rear_xy_drift,float(np.max(abs(point[:2]-rear_xy[i]))))
  if command=='upright' and row['time_s']>3:
   margin=ref.margin((body+np.array([0,0,65]))[:2],support);minimum_margin=min(minimum_margin,margin);assert abs(margin-row['support_margin_mm'])<1e-8
  B=ref.rz(m.body_euler[2])@ref.ry(m.body_euler[1])@ref.rx(m.body_euler[0]);pivot=np.array([0,0,65]);min_body=min(min_body,float(((hulls['body']-pivot)@B.T+pivot+body)[:,2].min()))
 assert max_position_error<.0001 and min_floor>-.005 and max_planted_z<.005
 assert max_support_rotation_error<.00001 and max_rear_xy_drift<.001 and min_body>0
 if command=='upright':
  sit=read(root/'motions/gestures/sit/source.json')['samples'];assert rows[:361]==sit[:361]
  assert minimum_margin>0 and abs(rows[-1]['body_rotation_euler_xyz_rad'][1]+math.pi/2)<1e-8
  assert all(row['actuator_angles_rad']==rows[-1]['actuator_angles_rad'] for row in rows[2400:])
 report[command]=dict(samples=len(rows),maximum_stored_fk_error_mm=float(max_position_error),minimum_sole_height_mm=float(min_floor),maximum_declared_contact_height_error_mm=float(max_planted_z),minimum_body_clearance_mm=min_body,maximum_support_rotation_matrix_error=max_support_rotation_error,maximum_seated_rear_xy_drift_mm=max_rear_xy_drift,timing_and_contacts_preserved=True)
 if command=='upright':report[command].update(minimum_support_margin_after_sit_mm=minimum_margin,final_front_reach_mm=rows[-1]['arm_reach_mm'][2:],historical_90_mm_reach_check_passed=False)
print(json.dumps(report,indent=2))
