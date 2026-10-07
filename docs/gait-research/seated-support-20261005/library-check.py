"""Independently compare remapped FK, supports and choreography to the baseline."""
import argparse,importlib.util,json,math
from pathlib import Path
import numpy as np
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline',type=Path,required=True)
parser.add_argument('--model',type=Path,required=True)
parser.add_argument('--results',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();BASE=args.baseline;MODEL=args.model
read=lambda p:json.loads(p.read_text())
spec=importlib.util.spec_from_file_location('reference',MODEL/'motions/walk/reference.py')
ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
cfg=read(MODEL/'geometry.json');m=ref.Mechanism(cfg);old=ref.Mechanism(read(BASE/'geometry.json'));LEGS=['FL','FR','RL','RR'];pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
reports={}
for cmd in read(args.results):
 folder=MODEL/f'motions/gestures/{cmd}';src=read(folder/'source.json');original=read(BASE/f'motions/gestures/{cmd}/source.json');rows=src['samples'];prior=original['samples'];post=folder/'posture.json';hp=folder/read(post)['contact_hulls_file'] if post.exists() else MODEL/'motions/gestures/sit/posture-hulls.npz'
 with np.load(hp) as hs:m.hulls=old.hulls={l:hs['sole_'+l].copy() for l in LEGS};hull=hs['body'].copy()
 assert len(rows)==len(prior) and src.get('phases')==original.get('phases')
 fkerror=0.;targeterror=0.;original_xy_error=0.;original_z_error=0.;bodyerror=0.;rot_error=0.;minfloor=math.inf;minbody=math.inf;support_R_error=0.;point_R_error=0.
 for row,before in zip(rows,prior):
  assert row['time_s']==before['time_s'] and row['contact_active']==before['contact_active']
  assert row['body_rotation_euler_xyz_rad']==before['body_rotation_euler_xyz_rad']
  body=np.array(row['body_translation_world_mm']);oldbody=np.array(before['body_translation_world_mm']);m.body_euler=old.body_euler=np.array(row['body_rotation_euler_xyz_rad']);bodyerror=max(bodyerror,float(np.linalg.norm(body-oldbody)))
  B=ref.rz(m.body_euler[2])@ref.ry(m.body_euler[1])@ref.rx(m.body_euler[0]);minbody=min(minbody,float(((hull-pivot)@B[2]+pivot[2]+body[2]).min()))
  for i,l in enumerate(LEGS):
   q=row['actuator_angles_rad'][i];oq=before['actuator_angles_rad'][i];point=m.reference(l,q,body);op=old.reference(l,oq,oldbody);z=float(m.vertices(l,q,body)[:,2].min());oz=float(old.vertices(l,oq,oldbody)[:,2].min());minfloor=min(minfloor,z)
   fkerror=max(fkerror,float(np.max(abs(point-row['foot_bolt_world_mm'][i]))),abs(z-row['sole_clearance_mm'][i]));targeterror=max(targeterror,float(np.max(abs(point[:2]-row['target_foot_reference_xy_mm'][i]))),abs(z-row['target_sole_clearance_mm'][i]));original_xy_error=max(original_xy_error,float(np.linalg.norm(point[:2]-op[:2])));original_z_error=max(original_z_error,abs(z-oz))
   # These terminal supporting faces are part of the gesture, not just a tip.
   preserve=(cmd=='rest' and row['time_s']>=3) or (cmd=='dead' and i>=2 and row['time_s']>=original['phases'][1]['end']) or (cmd=='bow' and i==2 and 1<=row['time_s']<=7) or (cmd=='nod' and i==2 and 2<=row['time_s']<=6)
   if preserve:
    R,_=m.pose(l,q,body);Ro,_=old.pose(l,oq,oldbody);support_R_error=max(support_R_error,float(np.max(abs(R-Ro))))
   if cmd=='point' and i==2 and 4.2<=row['time_s']<=6.2:
    R,_=m.pose(l,q,body);Ro,_=old.pose(l,oq,oldbody);point_R_error=max(point_R_error,float(np.max(abs(R-Ro))));assert abs(q[0]-oq[0])<1e-8 and abs(q[1]-oq[1])<1e-8
 # Retain the repository's existing -0.25 mm sampled sole tolerance; several
 # baseline recordings already lie below the nominal floor by up to 0.241 mm.
 target_tolerance=read(MODEL/'motions/locomotion/sole-profile.json')['support_allowance_mm']+.002 if cmd=='crouch' else .0001
 assert fkerror<1e-7 and targeterror<target_tolerance and minfloor>-.25 and minbody>-.000001,(cmd,fkerror,targeterror,minfloor,minbody)
 assert support_R_error<1e-5 and point_R_error<1e-8,(cmd,support_R_error,point_R_error)
 if cmd not in ['bow','nod','pushup']:assert bodyerror==0
 if cmd not in ['rest','dead','point']:
  assert original_xy_error<.0001 and original_z_error<(target_tolerance if cmd=='crouch' else .0001)
 reports[cmd]=dict(samples=len(rows),maximum_stored_fk_error_mm=fkerror,maximum_planned_target_error_mm=targeterror,maximum_original_xy_error_mm=original_xy_error,maximum_original_sole_height_error_mm=original_z_error,maximum_body_translation_change_mm=bodyerror,minimum_sole_height_mm=minfloor,minimum_body_clearance_mm=minbody,maximum_supporting_sole_rotation_matrix_error=support_R_error,point_hold_rotation_matrix_error=point_R_error,timing_phases_contacts_and_body_rotations_preserved=True)
 print(cmd,'PASS',reports[cmd],flush=True)
args.out.write_text(json.dumps(reports,indent=2))
