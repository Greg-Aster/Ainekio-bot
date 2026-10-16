"""Independent saved Blender reference versus native C, including physical joint IDs."""
import json,math,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
source=json.loads((root/'motions/walk/source.json').read_text())['columns']
rows=[]
for body,euler,feet,sole in zip(source['body'],source['body_euler'],source['feet'],source['sole_z']):
    rows.append(' '.join(map(repr,body+euler+[x for leg in feet for x in leg]+sole)))
beg=time.perf_counter();result=subprocess.run([sys.argv[2]],input='\n'.join(rows),capture_output=True,text=True,check=True)
actual=[json.loads(line) for line in result.stdout.splitlines()];assert len(actual)==len(rows)
import numpy as np
sys.path.insert(0,str(root/'tools'))
from retarget_clips import load_reference
cfg=json.loads((root/'geometry.json').read_text())
model=load_reference(root).Mechanism(cfg)
bare=np.array(json.loads((root/'motions/locomotion/walk-contact.json').read_text())['sole_hull_local_mm'])
profile=json.loads((root/'motions/locomotion/sole-profile.json').read_text())
error=0.
for row,body,euler,feet,sole in zip(actual,source['body'],source['body_euler'],source['feet'],source['sole_z']):
    model.body_euler=np.array(euler)
    for i,leg in enumerate(cfg['leg_order']):
        q=np.array(row[i*3:i*3+3]);R,t=model.pose(leg,q,body)
        point=R@np.array(cfg['legs'][leg]['foot_reference_local_mm'])+t
        xy=float(abs(point[:2]-np.array(feet[i][:2])).max())
        z=float((bare@R[2]+t[2]).min()-sole[i]);error=max(error,xy)
        assert xy<.005 and -.002<z<profile['support_allowance_mm']+.003,(leg,xy,z)
# The archived Blender recording predates the current compact gait tuning.
# Its IK parity above remains independent; compare the diagnostic planner with
# explicit targets from the current configuration, not historical choreography.
cfg=json.loads((root/'geometry.json').read_text())
walk=json.loads((root/'motions/locomotion/config.json').read_text())['walk']
settings=cfg['continuous_walk'];duty=walk['ground_contact_fraction']
phases=[(4.+i/40.,stride) for stride in (25,50,75,100) for i in range(40)]
requests=''.join(f'{phase} {stride} 1\n' for phase,stride in phases)
result=subprocess.run([sys.argv[1]],input=requests,capture_output=True,text=True,check=True)
pose_rows=[json.loads(row) for row in result.stdout.splitlines()]
targets=[]
for phase,stride in phases:
    strength=stride/100.;amplitude=strength*walk['body_motion_scale'];a=2*math.pi*phase
    advance=walk['stance_sweep_mm']*strength/duty
    support_phase=a+2*math.pi*walk['support_phase_cycles']
    body=[phase*advance+walk['support_x_mean_mm']+(walk['support_x_mean_full_stride_mm']-walk['support_x_mean_mm'])*strength*strength+walk['support_x_mm']*math.sin(2*support_phase),walk['support_y_mm']*math.sin(support_phase),
          walk['body_z_mm']+settings['body_bob_mm']*amplitude*math.cos(2*a)]
    height_basis=[math.sin(2*a),math.cos(2*a),math.sin(4*a),math.cos(4*a)]
    body[2]+=strength*(walk['body_z_full_stride_mm']-walk['body_z_mm']+
                      sum(c*b for c,b in zip(walk['body_height_coefficients_mm'],height_basis)))
    euler=[math.radians(settings['roll_deg'])*amplitude*math.sin(a),
           math.radians(settings['pitch_deg'])*amplitude*math.sin(2*a),0.]
    feet=[];sole=[]
    for leg,xy in zip(cfg['leg_order'],cfg['reference_stance_xy_mm']):
        offset=settings['phase_offsets'][leg];td=math.floor(phase-offset)+offset;local=phase-td
        x=td*advance+walk['stance_sweep_mm']*strength*.5-walk['rearward_bias_mm']*strength
        height=0.
        if local>=duty:
            u=(local-duty)/(1-duty)
            r=json.loads((root/'motions/run/config.json').read_text())['swing_ramp_fraction'];v=1/(1-r)
            if u<r:
                t=u/r;fraction=v*r*(t**3-.5*t**4)
            elif u>1-r:
                t=(1-u)/r;fraction=1-v*r*(t**3-.5*t**4)
            else: fraction=v*(u-r*.5)
            x+=advance*fraction
            height=(walk['minimum_lift_mm']+(walk['lift_mm']-walk['minimum_lift_mm'])*strength)*16*u**2*(1-u)**2
        feet.extend([xy[0]+x,xy[1],0.]);sole.append(height)
    targets.append(' '.join(map(repr,body+euler+feet+sole)))
result=subprocess.run([sys.argv[2]],input='\n'.join(targets),capture_output=True,text=True,check=True)
expected_rows=[json.loads(line) for line in result.stdout.splitlines()]
assert len(pose_rows)==len(expected_rows)==len(phases)
planner_error=0.
for actual_row,expected_row in zip(pose_rows,expected_rows):
    expected=[math.degrees(expected_row[j*3+k])*100 for j in (2,3,0,1) for k in range(3)]
    planner_error=max(planner_error,max(abs(a-b) for a,b in zip(actual_row,expected))/100)
assert planner_error<.01,planner_error
print(json.dumps({'reference_poses':len(rows),'native_foot_xy_max_error_mm':error,'whole_planner_max_error_deg':planner_error,'source_joint_remapping':[2,3,0,1],'host_total_seconds':time.perf_counter()-beg}))
