"""Export the independent Rest source and its firmware integration contract."""
import csv,datetime,hashlib,json,math
from pathlib import Path
import numpy as np
from sample_reference import Motion
P=Path(__file__).resolve().parent
d=json.loads((P/'source.json').read_text());cfg=d['metadata']['configuration'];rows=d['samples'];legs=d['metadata']['leg_order']
par=json.loads((P/'robot-gait-parameters.json').read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
columns=['time_s','time_us','phase']+['body_'+a+'_mm' for a in 'xyz']+['body_q'+a for a in 'wxyz']
columns+=['assumed_com_'+a+'_mm' for a in 'xyz']+['support_margin_mm','body_ground_clearance_mm']
for leg in legs:
    columns += [f'{leg}_{j}_rad' for j in ['h002','alpha006','theta005']]
    columns += [f'{leg}_foot_bolt_{a}_mm' for a in 'xyz']+[f'{leg}_sole_contact_{a}_mm' for a in 'xyz']+[f'{leg}_contact_active',f'{leg}_sole_clearance_mm']
with (P/'source.csv').open('w',newline='') as f:
    out=csv.writer(f);out.writerow(columns)
    for r in rows:
        values=[r['time_s'],round(r['time_s']*1e6),r['phase']]+r['body_position_world_mm']+r['body_orientation_world_quaternion_wxyz']
        values+=r['assumed_com_world_mm']+[r['support_margin_mm'],r['body_ground_clearance_mm']]
        for i in range(4):values+=r['actuator_angles_rad'][i]+r['foot_bolt_world_mm'][i]+r['contact_world_mm'][i]+[int(r['contact_active'][i]),r['sole_clearance_mm'][i]]
        out.writerow(values)
schema=dict(command='rest',columns=columns,leg_order=legs,joint_order=d['metadata']['joint_order'],
    physical_leg_mapping={l:par['legs'][l]['physical_name'] for l in legs},sample_hz=120,
    units=dict(positions='mm',actuator_angles='radians',time='seconds; time_us rounded integer microseconds'),
    coordinates='World X physical forward, Y left, Z up. Quaternion wxyz. Negative pitch about body Y raises the front.',
    joint_zero='Corrected CAD neutral; Part005 re-clocking already included.',
    positive_axes=dict(h002='CAD +X / body +X',alpha006='CAD +Z / body +Y',theta005='CAD +Z / body +Y'),
    interpolation='Monotone cubic Hermite; harmonic same-sign secant tangents, zero endpoint tangents. Hold final position after duration.',
    contact_model=cfg['contact_model'],com=cfg['com'],servo_calibration=None,
    shoulder_behavior='All four h002 angles remain zero. The leg folds occur in sagittal leg planes; no lateral stance change is requested.')
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
manifest=dict(command='rest',body_control_label='Rest',wire={'t':'intent','name':'emote','asset':'rest'},
    gait_id='rest_fourbar_20260915',generated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    duration_seconds=d['validation']['duration_s'],motion_end_seconds=cfg['lower_seconds'],source_sample_hz=120,sample_count=len(rows),
    entry_pose='Corrected CAD standing neutral, four feet supported. Arbitrary-current-pose entry is not provided.',
    completion=cfg['completion'],final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],
    body_target=dict(position_mm=rows[-1]['body_position_world_mm'],pitch_degrees=cfg['target_body_pitch_degrees']),
    face_cues=cfg['face_cues'],face_asset=dict(name='rest',width=128,height=64,encoding='row-major MSB-first 1-bit bitmap; 16 bytes per row',
        fps=1,mode='boomerang',frames=['faces/rest/0.bin','faces/rest/1.bin','faces/rest/2.bin'],source='Unchanged existing Ainekio owner-authored rest face bitmaps'),
    hardware_qualified=False,actuator_calibration=None,source_sha256=sha(P/'source.json'),csv_sha256=sha(P/'source.csv'),
    geometry_sha256=sha(P/'robot-gait-parameters.json'),sole_hulls_sha256=sha(P/'sole-hulls.npz'),body_samples_sha256=sha(P/'body-samples.npz'),
    face_sha256={str(i):sha(P/f'faces/rest/{i}.bin') for i in range(3)},
    blender_workspace_file=str(P/'Ainekio-Rest.blend'),blender_frames=[529,649],
    design='Level body lowered on all four legs. All four measured soles remain grounded.',
    source_validation=d['validation'],interpolation_validation=interpolation)
(P/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(dict(samples=len(rows),columns=len(columns),interpolation=interpolation)))
