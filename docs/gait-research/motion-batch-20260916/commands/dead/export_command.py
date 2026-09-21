"""Export a reviewed twelve-servo command; run in its portable package directory."""
import csv,datetime,hashlib,json,math
from pathlib import Path
import numpy as np
from sample_reference import Motion
P=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,value):(P/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
d=json.loads((P/'source.json').read_text());cfg=d['metadata']['configuration'];rows=d['samples'];command=cfg['command'];hz=cfg['sample_hz'];legs=d['metadata']['leg_order'];duration=rows[-1]['time_s'];semantic_end=cfg.get('semantic_end_s',duration)
par=json.loads((P/'robot-gait-parameters.json').read_text())
columns=['time_s','time_us','phase']+['body_'+a+'_mm' for a in 'xyz']+['body_q'+a for a in 'wxyz']+['assumed_com_'+a+'_mm' for a in 'xyz']+['support_margin_mm','body_ground_clearance_mm','body_contact_active','support_source']
for leg in legs:columns += [f'{leg}_{j}_rad' for j in ['h002','alpha006','theta005']]+[f'{leg}_foot_bolt_{a}_mm' for a in 'xyz']+[f'{leg}_sole_contact_{a}_mm' for a in 'xyz']+[f'{leg}_contact_active',f'{leg}_sole_clearance_mm']
with (P/'source.csv').open('w',newline='') as f:
 out=csv.writer(f);out.writerow(columns)
 for r in rows:
  values=[r['time_s'],round(r['time_s']*1e6),r['phase']]+r['body_position_world_mm']+r['body_orientation_world_quaternion_wxyz']+r['assumed_com_world_mm']+[r['support_margin_mm'],r['body_ground_clearance_mm'],int(r['body_contact_active']),r['support_source']]
  for i in range(4):values+=r['actuator_angles_rad'][i]+r['foot_bolt_world_mm'][i]+r['contact_world_mm'][i]+[int(r['contact_active'][i]),r['sole_clearance_mm'][i]]
  out.writerow(values)
schema=dict(command=command,columns=columns,leg_order=legs,joint_order=d['metadata']['joint_order'],physical_leg_mapping={l:par['legs'][l]['physical_name'] for l in legs},sample_hz=hz,units=dict(positions='mm',actuator_angles='radians',time='seconds and rounded integer microseconds'),coordinates='World X physical forward, Y left, Z up. Quaternion wxyz; geometric q about positive CAD axes: h X, alpha/theta Z.',joint_zero='Corrected CAD neutral; Part005 re-clocking included.',interpolation='Monotone cubic Hermite, harmonic same-sign secant tangents and zero endpoint tangents. Hold final position after duration.',contact_model=cfg['contact_model'],com=cfg.get('com'),servo_calibration=None,semantic_end_s=semantic_end,optional_demonstration_recovery=semantic_end<duration)
write('schema.json',schema)
motion=Motion(P);q=np.array(motion.positions);v=np.array(motion.velocities)
secant=(q[1:]-q[:-1])*hz;c2=3*secant-2*v[:-1]-v[1:];c3=v[:-1]+v[1:]-2*secant
with np.errstate(divide='ignore',invalid='ignore'):u=-c2/(3*c3)
interior=(u>0)&(u<1);u=np.where(interior,u,0)
speed=np.maximum(np.maximum(abs(v[:-1]),abs(v[1:])),np.where(interior,abs(v[:-1]+2*c2*u+3*c3*u*u),0))
acc=np.maximum(abs(2*c2*hz),abs((2*c2+6*c3)*hz))
# Harmonic tangents are monotone; independently sample each segment at quarters.
for fraction in [.25,.5,.75]:
 x=q[:-1]+(v[:-1]*fraction+c2*fraction**2+c3*fraction**3)/hz
 assert np.all(x>=np.minimum(q[:-1],q[1:])-1e-8) and np.all(x<=np.maximum(q[:-1],q[1:])+1e-8)
assert motion.sample(round(duration*1e6))['position']==motion.sample(999999999)['position']==motion.positions[-1]
assert max(abs(x) for x in motion.sample(999999999)['velocity'])==0
assert np.max(abs(np.array([r['time_s'] for r in rows])-np.arange(len(rows))/hz))<1e-7
iv=dict(segments_checked=len(q)-1,bounded_quarter_samples=True,final_hold_verified=True,peak_interpolated_speed_degrees_s=float(speed.max()/100),peak_interpolated_acceleration_degrees_s2=float(acc.max()/100),continuity='Position and velocity continuous; full acceleration continuity not established.',hardware_qualified=False)
write('interpolation-validation.json',iv)
semantic_row=rows[round(semantic_end*hz)]
manifest=dict(command=command,body_control_label=cfg['display_label'],wire={'t':'intent','name':'emote','asset':command},gait_id=f'{command}_fourbar_20260916',generated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),duration_seconds=duration,semantic_end_seconds=semantic_end,source_sample_hz=hz,sample_count=len(rows),entry_pose='Corrected geometric standing neutral; arbitrary-pose entry not verified.',completion=cfg['completion'],semantic_final_actuator_angles_rad=semantic_row['actuator_angles_rad'],playlist_final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],face_cues=cfg.get('face_cues',[]),hardware_qualified=False,actuator_calibration=None,source_sha256=sha(P/'source.json'),csv_sha256=sha(P/'source.csv'),geometry_sha256=sha(P/'robot-gait-parameters.json'),sole_hulls_sha256=sha(P/'sole-hulls.npz'),body_samples_sha256=sha(P/'body-samples.npz'),face_sha256={str(f.relative_to(P)):sha(f) for f in sorted((P/'faces').glob('*/*.bin'))},blender_workspace_file=cfg['output_blend'],blender_frames=[cfg['gait_start_frame'],cfg['gait_start_frame']+round(duration*cfg['preview_fps'])],design=cfg['adaptation'],contact_model=cfg['contact_model'],source_validation=d['validation'],interpolation_validation=iv)
write('manifest.json',manifest)
phases=[]
for n,p in enumerate(d['phases']):
 lo,hi=[round(p[key]*hz) for key in ('start','end')]
 if hi<=lo:continue
 phases.append(dict(id=f'p{n:03}_{p["kind"]}',name=p['kind'],section='clip',execution_role='optional_demonstration_recovery' if p['start']>=semantic_end-1e-8 else 'command',source_interval_s=[p['start'],p['end']],source_sample_indices_inclusive=[lo,hi],demonstration_duration_s=p['end']-p['start'],supporting_legs_throughout=[leg for i,leg in enumerate(legs) if all(r['contact_active'][i] for r in rows[lo:hi+1])],contact_states=[list(m) for m in sorted(set(tuple(r['contact_active']) for r in rows[lo:hi+1]))],support_sources=sorted(set(r['support_source'] for r in rows[lo:hi+1])),coordination='whole_body_shared_clock',moving_joint_indices=np.flatnonzero(np.ptp(q[lo:hi+1],axis=0)>1e-7).tolist(),reference_peak_speed_rad_s=np.radians(speed[lo:hi].max(0)/100).tolist(),reference_peak_acceleration_rad_s2=np.radians(acc[lo:hi].max(0)/100).tolist()))
timing={p['id']:p['demonstration_duration_s'] for p in phases}
contract=dict(schema='ainekio-motion-execution-contract-1',command=command,gait_id=manifest['gait_id'],wire=manifest['wire'],shared_policy='execution-policy.json',policy_sha256=sha(P/'execution-policy.json'),source_files=[dict(path=f'docs/gait-research/motion-batch-20260916/commands/{command}/'+n,sha256=sha(P/n)) for n in ['source.json','manifest.json']],source_units=dict(angle='radian',position='mm',time='second'),source_sample_hz=hz,leg_order=legs,joint_order=d['metadata']['joint_order'],physical_leg_order=[par['legs'][l]['physical_name'] for l in legs],phases=phases,contact_model=cfg['contact_model'],contact_events=[dict(source_time_s=r['time_s'],sample_index=i,active=r['contact_active'],body_contact_active=r['body_contact_active'],support_source=r['support_source']) for i,r in enumerate(rows) if i==0 or (r['contact_active'],r['body_contact_active'])!=(rows[i-1]['contact_active'],rows[i-1]['body_contact_active'])],timing_profiles=dict(demonstration=dict(status='recorded_kinematic_timing',duration_s=timing),research_candidate=dict(status='offline_unvalidated',duration_s=timing.copy()),operating=dict(status='unconfigured_pending_loaded_calibration',duration_s={key:None for key in timing},calibration_id=None)),repeat=dict(section=None,minimum=1,maximum=1),face_cues=cfg.get('face_cues',[]),entry=dict(joint_angles_rad=rows[0]['actuator_angles_rad'],contact_active=rows[0]['contact_active'],arbitrary_pose_entry_verified=False),completion=dict(behavior=cfg['completion'],semantic_end_s=semantic_end,joint_angles_rad=semantic_row['actuator_angles_rad'],contacts=semantic_row['contact_active'],optional_demo_recovery_end_s=duration if semantic_end<duration else None),source_qualification=dict(hardware_qualified=False,collision_checked=False,measured_mass_balance_verified=False),body_support_required=any(r['body_contact_active'] for r in rows),interruption_note='Hold or resume along the coordinated recorded path; do not jump tracks or seek to standing. Preserve the documented support model.',hardware_ready=False)
write('execution-contract.json',contract)
print(json.dumps(dict(command=command,samples=len(rows),duration_s=duration,**iv)))
