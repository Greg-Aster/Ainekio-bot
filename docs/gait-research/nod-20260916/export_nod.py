"""Export the independent Nod source and its firmware integration contract."""
import csv,datetime,hashlib,json,math
from pathlib import Path
import numpy as np
from sample_reference import Motion
P=Path(__file__).resolve().parent
d=json.loads((P/'source.json').read_text());cfg=d['metadata']['configuration'];rows=d['samples'];legs=d['metadata']['leg_order']
par=json.loads((P/'robot-gait-parameters.json').read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
columns=['time_s','time_us','phase']+['body_'+a+'_mm' for a in 'xyz']+['body_q'+a for a in 'wxyz']
columns+=['assumed_com_'+a+'_mm' for a in 'xyz']+['support_margin_mm','body_ground_clearance_mm','body_contact_active','support_source']
for leg in legs:
    columns += [f'{leg}_{j}_rad' for j in ['h002','alpha006','theta005']]
    columns += [f'{leg}_foot_bolt_{a}_mm' for a in 'xyz']+[f'{leg}_sole_contact_{a}_mm' for a in 'xyz']+[f'{leg}_contact_active',f'{leg}_sole_clearance_mm']
with (P/'source.csv').open('w',newline='') as f:
    out=csv.writer(f);out.writerow(columns)
    for r in rows:
        values=[r['time_s'],round(r['time_s']*1e6),r['phase']]+r['body_position_world_mm']+r['body_orientation_world_quaternion_wxyz']
        values+=r['assumed_com_world_mm']+[r['support_margin_mm'],r['body_ground_clearance_mm'],int(r['body_contact_active']),r['support_source']]
        for i in range(4):values+=r['actuator_angles_rad'][i]+r['foot_bolt_world_mm'][i]+r['contact_world_mm'][i]+[int(r['contact_active'][i]),r['sole_clearance_mm'][i]]
        out.writerow(values)
schema=dict(command='nod',columns=columns,leg_order=legs,joint_order=d['metadata']['joint_order'],
    physical_leg_mapping={l:par['legs'][l]['physical_name'] for l in legs},sample_hz=120,
    units=dict(positions='mm',actuator_angles='radians',time='seconds; time_us rounded integer microseconds'),
    coordinates='World X physical forward, Y left, Z up. Quaternion wxyz. Negative pitch about body Y raises the front.',
    joint_zero='Corrected CAD neutral; Part005 re-clocking already included.',
    positive_axes=dict(h002='CAD +X / body +X',alpha006='CAD +Z / body +Y',theta005='CAD +Z / body +Y'),
    interpolation='Monotone cubic Hermite; harmonic same-sign secant tangents, zero endpoint tangents. Hold final position after duration.',
    contact_model=cfg['contact_model'],com=cfg['com'],servo_calibration=None,
    shoulder_behavior='Rear-right crouch precedes front-leg nods. Shoulder, Part006 carrier and Part005 crank tracks are solved together for all four grounded feet.')
(P/'schema.json').write_text(json.dumps(schema,indent=2)+'\n')
motion=Motion(P);q=np.array(motion.positions);v=np.array(motion.velocities)
secant=(q[1:]-q[:-1])*120;c2=3*secant-2*v[:-1]-v[1:];c3=v[:-1]+v[1:]-2*secant
middle=q[:-1]+(v[:-1]*.5+c2*.25+c3*.125)/120
assert np.all(middle>=np.minimum(q[:-1],q[1:])-1e-8) and np.all(middle<=np.maximum(q[:-1],q[1:])+1e-8)
with np.errstate(divide='ignore',invalid='ignore'):u=-c2/(3*c3)
interior=(u>0)&(u<1);u=np.where(interior,u,0)
speed=np.maximum(np.maximum(abs(v[:-1]),abs(v[1:])),np.where(interior,abs(v[:-1]+2*c2*u+3*c3*u*u),0))
acc=np.maximum(abs(2*c2*120),abs((2*c2+6*c3)*120))
assert motion.sample(round(d['validation']['duration_s']*1e6))['position']==motion.sample(999999999)['position']==motion.positions[-1]
assert max(abs(x) for x in motion.sample(999999999)['velocity'])==0
assert np.max(abs(np.array([r['time_s'] for r in rows])-np.arange(len(rows))/120))<1e-8
interpolation=dict(segments_checked=len(middle),bounded_midpoints=True,final_hold_verified=True,
    peak_interpolated_speed_degrees_s=float(speed.max()/100),peak_interpolated_acceleration_degrees_s2=float(acc.max()/100),
    continuity='Position and velocity continuous. Acceleration continuity and hardware capability unqualified.')
(P/'interpolation-validation.json').write_text(json.dumps(interpolation,indent=2)+'\n')
manifest=dict(command='nod',body_control_label='Nod',wire={'t':'intent','name':'emote','asset':'nod'},
    gait_id='nod_rear_support_fourbar_20260916',generated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    duration_seconds=d['validation']['duration_s'],motion_end_seconds=d['validation']['motion_end_s'],source_sample_hz=120,sample_count=len(rows),
    entry_pose='Corrected CAD standing neutral, four feet supported. Arbitrary-current-pose entry is not provided.',
    completion=cfg['completion'],final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],
    body_target=dict(position_mm=rows[-1]['body_position_world_mm'],pitch_degrees=0.),
    face_cues=cfg['face_cues'],face_asset=dict(name='nod',width=128,height=64,encoding='row-major MSB-first 1-bit bitmap; 16 bytes per row',
        fps=1,mode='once',frames=['faces/nod/0.bin'],source='Retained prior Pushup face bitmap for the user-preserved Nod sequence; not a replacement of the V1 Nod face'),
    hardware_qualified=False,actuator_calibration=None,source_sha256=sha(P/'source.json'),csv_sha256=sha(P/'source.csv'),
    geometry_sha256=sha(P/'robot-gait-parameters.json'),sole_hulls_sha256=sha(P/'sole-hulls.npz'),body_samples_sha256=sha(P/'body-samples.npz'),
    face_sha256={str(f.relative_to(P)):sha(f) for f in sorted((P/'faces').glob('*/*.bin'))},
    blender_workspace_file=str(P/cfg['output_blend']),blender_frames=[cfg['gait_start_frame'],cfg['gait_start_frame']+round(d['validation']['duration_s']*cfg['preview_fps'])],
    design=cfg['adaptation'],
    body_contact_required=False,source_validation=d['validation'],interpolation_validation=interpolation)
(P/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(dict(samples=len(rows),columns=len(columns),interpolation=interpolation)))

# Same execution contract as the preceding twelve motions, bound to this source.
phases=[]
for number,phase in enumerate(d['phases']):
    lo,hi=[round(phase[key]*cfg['sample_hz']) for key in ('start','end')]
    phases.append(dict(id=f'p{number:03}_{phase["kind"]}',name=phase['kind'],section='clip',
        source_interval_s=[phase['start'],phase['end']],source_sample_indices_inclusive=[lo,hi],
        demonstration_duration_s=round(phase['end']-phase['start'],9),
        supporting_legs_throughout=[leg for i,leg in enumerate(legs) if all(r['contact_active'][i] for r in rows[lo:hi+1])],
        contact_states=[list(m) for m in sorted(set(tuple(r['contact_active']) for r in rows[lo:hi+1]))],
        support_sources=sorted(set(r['support_source'] for r in rows[lo:hi+1])),coordination='whole_body_shared_clock',
        moving_joint_indices=np.flatnonzero(np.ptp(q[lo:hi+1],axis=0)>1e-7).tolist(),
        reference_peak_speed_rad_s=np.radians(speed[lo:hi].max(0)/100).tolist(),
        reference_peak_acceleration_rad_s2=np.radians(acc[lo:hi].max(0)/100).tolist()))
durations={phase['id']:phase['demonstration_duration_s'] for phase in phases}
contract=dict(schema='ainekio-motion-execution-contract-1',command='nod',gait_id=manifest['gait_id'],
    wire=manifest['wire'],shared_policy='execution-policy.json',policy_sha256=sha(P/'execution-policy.json'),
    source_files=[dict(path='docs/gait-research/nod-20260916/'+name,sha256=sha(P/name)) for name in ('source.json','manifest.json')],
    source_units=dict(angle='radian',position='mm',time='second'),source_sample_hz=cfg['sample_hz'],
    leg_order=legs,joint_order=d['metadata']['joint_order'],physical_leg_order=[par['legs'][l]['physical_name'] for l in legs],
    phases=phases,contact_events=[dict(source_time_s=r['time_s'],sample_index=i,active=r['contact_active'],body_contact_active=r['body_contact_active'],support_source=r['support_source']) for i,r in enumerate(rows) if i==0 or (r['contact_active'],r['body_contact_active'])!=(rows[i-1]['contact_active'],rows[i-1]['body_contact_active'])],
    timing_profiles=dict(demonstration=dict(status='recorded_kinematic_timing',duration_s=durations),
        research_candidate=dict(status='offline_unvalidated',duration_s=durations.copy()),
        operating=dict(status='unconfigured_pending_loaded_calibration',duration_s={key:None for key in durations},calibration_id=None)),
    repeat=dict(section=None,minimum=1,maximum=1),face_cues=cfg['face_cues'],
    entry=dict(joint_angles_rad=rows[0]['actuator_angles_rad'],contact_active=rows[0]['contact_active'],arbitrary_pose_entry_verified=False),
    completion=dict(behavior=cfg['completion'],joint_angles_rad=rows[-1]['actuator_angles_rad'],contacts=[True]*4),
    source_qualification=dict(hardware_qualified=False,collision_checked=False,measured_mass_balance_verified=False,
        minimum_assumed_support_margin_mm=d['validation']['minimum_support_margin_mm']),body_support_required=False,interruption_note='Keep all four supporting legs coordinated. Stop along the recorded body path and return through the raised crouch to standing; never seek directly to the last row.',hardware_ready=False)
(P/'execution-contract.json').write_text(json.dumps(contract,indent=2)+'\n')
