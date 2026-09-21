"""Independent numeric review of generated command sources; no Blender or hardware writes."""
import json,sys,math,importlib.util,hashlib
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
base=P.parent/'robot-bow-20260916'
spec=importlib.util.spec_from_file_location('review_kinematics',base/'gait_kinematics.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
A=np.array(g.PARAMETERS['controller_from_CAD_rotation']);datum=np.array(g.PARAMETERS['controller_body_datum_CAD_xyz_mm']);sole=np.load(base/'sole-hulls.npz');legs=['FL','FR','RL','RR']
def rotation(e):
 x,y,z=e;cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
 return np.array([[cz,-sz,0],[sz,cz,0],[0,0,1.]])@np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])@np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
def check(folder):
 d=json.loads((folder/'source.json').read_text());cfg=d['metadata']['configuration'];rows=d['samples'];hz=cfg['sample_hz'];q=np.array([r['actuator_angles_rad'] for r in rows]);positions=np.array([r['body_position_world_mm'] for r in rows]);errors=[]
 assert hz==120 and cfg['preview_fps']==24
 assert d['metadata']['leg_order']==legs
 assert q.shape==(len(rows),4,3) and np.isfinite(q).all()
 assert np.isfinite(positions).all()
 assert max(abs(r['time_s']-n/hz) for n,r in enumerate(rows))<1e-6
 max_foot=0.;max_sole=0.;min_sole=1e9;max_closure=0.;max_passive=0.;max_active_height=0.
 # Whole source: positions, geometric constraints, passive continuity and real sole vertices.
 for row in rows:
  R=rotation(row['body_rotation_euler_xyz_rad']);body=np.array(row['body_position_world_mm'])
  for i,l in enumerate(legs):
   h,alpha,theta=row['actuator_angles_rad'][i];fk=g.fk(l,h,alpha,theta);bolt=body+R@A@(np.array(fk['foot_CAD_xyz_mm'])-datum)
   max_foot=max(max_foot,float(np.linalg.norm(bolt-np.array(row['foot_bolt_world_mm'][i]))))
   beta=fk['beta'];max_passive=max(max_passive,abs(g.wrap(beta-row['passive_beta_rad'][i])))
   c,s=math.cos(h),math.sin(h);rx=np.array([[1,0,0],[0,c,-s],[0,s,c]]);c,s=math.cos(beta),math.sin(beta);rz=np.array([[c,-s,0],[s,c,0],[0,0,1.]])
   F0=np.array(g.PARAMETERS['legs'][l]['foot_bolt_reference_xyz_mm']);vv=(sole[l]-F0)@(R@A@rx@rz).T+bolt;low=float(vv[:,2].min());min_sole=min(min_sole,low);max_sole=max(max_sole,abs(low-row['sole_clearance_mm'][i]))
   if row['contact_active'][i]:max_active_height=max(max_active_height,abs(low))
   piv=fk['planar_pivots'];expected=g.PARAMETERS['legs'][l]['lengths_mm']['coupler_PQ'];max_closure=max(max_closure,abs(np.linalg.norm(np.array(piv['P'])-piv['Q'])-expected))
 if max_foot>1e-4:errors.append(f'Foot source prediction error {max_foot} mm')
 if max_sole>1e-4:errors.append(f'Sole source prediction error {max_sole} mm')
 if min_sole<-.02:errors.append(f'Sole penetration {min_sole} mm')
 if max_passive>1e-7:errors.append('Passive beta mismatch')
 if max_closure>1e-6:errors.append('Fourbar closure error')
 step=float(abs(np.diff(np.degrees(q),axis=0)).max())
 if step>3:errors.append(f'Large adjacent actuator step {step} deg')
 limits=cfg.get('geometric_research_angle_bounds_degrees',{})
 for i,l in enumerate(legs):
  for j,axis in enumerate(['h','alpha','theta']):
   if axis in limits:
    lo,hi=limits[axis];mn,mx=np.degrees(q[:,i,j]).min(),np.degrees(q[:,i,j]).max()
    if mn<lo-1e-5 or mx>hi+1e-5:errors.append(f'{l} {axis} exceeds declared range: {mn},{mx} vs{lo},{hi}')
 report=dict(command=cfg['command'],samples=len(rows),duration_s=rows[-1]['time_s'],maximum_fk_foot_source_error_mm=max_foot,maximum_sole_source_error_mm=max_sole,minimum_sole_z_mm=min_sole,maximum_active_sole_distance_from_ground_mm=max_active_height,maximum_fourbar_closure_error_mm=max_closure,maximum_passive_beta_error_rad=max_passive,maximum_adjacent_angle_step_degrees=step,entry_q_error_degrees=float(abs(np.degrees(q[0])).max()),playlist_exit_q_error_degrees=float(abs(np.degrees(q[-1])).max()),playlist_body_return_error_mm=float(np.linalg.norm(positions[-1]-positions[0])),minimum_reported_support_margin_mm=min(r['support_margin_mm'] for r in rows),body_support_used=any(r['body_contact_active'] for r in rows),semantic_end_s=cfg.get('semantic_end_s',rows[-1]['time_s']),errors=errors,passed=not errors,collision_checked=False,physical_balance_verified=False)
 (folder/'source-review.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
 return report
if __name__=='__main__':
 names=sys.argv[1:] or [p.name for p in sorted((P/'commands').iterdir()) if (p/'source.json').exists()]
 results=[check(P/'commands'/n) for n in names]
 if any(not r['passed'] for r in results):sys.exit(1)
