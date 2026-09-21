"""Held Rest: measured sole rolling and full body pitch, no servo output."""
import argparse,json,math
from pathlib import Path
import numpy as np
import plan_crawl as k

P=Path(__file__).resolve().parent
LEGS=k.LEGS

def ry(a):
    c,s=math.cos(a),math.sin(a)
    return np.array([[c,0,s],[0,1,0],[-s,0,c]])

def generate(settings=None):
    base=json.loads((P/'base-config.json').read_text())
    cfg=dict(command='rest',display_label='REST',name='Rest held posture',
        sample_hz=120,preview_fps=24,gait_start_frame=529,existing_animation_end_frame=505,
        target_body_height_mm=32.,target_body_x_mm=0.,target_body_pitch_degrees=0.,
        lower_seconds=3.,hold_seconds=2.,com=base['com'],
        geometric_research_angle_bounds_degrees=base['geometric_research_angle_bounds_degrees'],
        source_blend='Before-Rest.blend',output_blend='Ainekio-Rest.blend',
        scene_name='AINEKIO - Rest',part023_forward_limit_degrees=90.,
        contact_model='Four grounded feet. A sole material vertex is fixed in world space until a supporting-feature transfer; finite-step rolling corrections are logged.',
        face_cues=[dict(time_s=0.,name='rest',mode='boomerang',fps=1)],
        completion='Hold the recorded resting pose until another command. No automatic stand or joint reset.',
        hardware_qualified=False)
    cfg.update(settings or {})
    hz=cfg['sample_hz'];neutral_z=max(-k.sole_world(l,np.zeros(3),np.zeros(3))[:,2].min() for l in LEGS)
    body=np.array([0.,0.,neutral_z]);pitch=0.;R=ry(0);com=k.configured_body_com(cfg)
    body_mesh=np.load(P/'body-samples.npz')['vertices']
    def foot(l,q):
        bolt,r,beta=k.foot_pose(l,q,np.zeros(3));return body+R@bolt,R@r,beta
    def sole(l,q):
        bolt,r,_=foot(l,q);return (k.SOLE[l]-k.F0[l])@r.T+bolt
    state={}
    for l in LEGS:
        vv=sole(l,np.zeros(3));idx=int(vv[:,2].argmin());anchor=vv[idx].copy();anchor[2]=0.
        state[l]=dict(q=np.zeros(3),index=idx,anchor=anchor)
    def inverse(l,world,seed,ref):return k.inverse(l,R.T@(world-body),np.zeros(3),seed,ref)
    rows=[];transfers=0;max_correction=0.
    duration=cfg['lower_seconds']+cfg['hold_seconds']
    for n in range(round(duration*hz)+1):
        time=n/hz;u=k.smooth(min(1.,time/cfg['lower_seconds']))
        body=np.array([cfg['target_body_x_mm']*u,0,neutral_z+(cfg['target_body_height_mm']-neutral_z)*u])
        pitch=math.radians(cfg['target_body_pitch_degrees'])*u;R=ry(pitch)
        qrow=[];betas=[];feet=[];contacts=[];clearance=[];errors=[];indices=[];carrier=[]
        for l in LEGS:
            st=state[l]
            q=inverse(l,st['anchor'],st['q'],k.SOLE[l][st['index']]) if n else st['q']
            for _ in range(16):
                vv=sole(l,q);idx=int(vv[:,2].argmin());low=vv[idx,2]
                if low>=-2e-8:break
                max_correction=max(max_correction,float(-low));transfers+=1
                anchor=vv[idx].copy();anchor[2]=0.
                q=inverse(l,anchor,q,k.SOLE[l][idx]);st=dict(q=q,index=idx,anchor=anchor)
            else:raise ValueError((l,'rolling did not converge',low))
            for j,name in enumerate(['h','alpha','theta']):
                low,high=cfg['geometric_research_angle_bounds_degrees'][name]
                if not low-1e-7<=math.degrees(q[j])<=high+1e-7:
                    raise ValueError(f'{l} {name} {math.degrees(q[j]):.3f} outside {low,high} at {time:.3f}s')
            st['q']=q;state[l]=st;bolt,_,beta=foot(l,q);vv=sole(l,q)
            qrow.append(q.tolist());betas.append(beta);feet.append(bolt.tolist());contacts.append(st['anchor'].tolist())
            clearance.append(float(vv[:,2].min()));errors.append(float(np.linalg.norm(vv[st['index']]-st['anchor'])));indices.append(st['index'])
            par=k.g.PARAMETERS['legs'][l];od=np.array(k.g.fk(l,*q)['planar_pivots']['D'])-par['pivots_xy_mm']['O']
            angle=math.degrees(math.atan2(od[1]*math.cos(q[0]),od[0]));carrier.append(angle if angle>=0 else angle+360)
        com_world=body+R@com;body_low=float((body_mesh@R[2,:]+body[2]).min())
        if body_low < -1e-5:raise ValueError(('body ground clearance',body_low,time))
        rows.append(dict(time_s=time,phase='lower_into_rest' if time<cfg['lower_seconds'] else 'hold_rest',
            phase_fraction=min(1.,time/cfg['lower_seconds']),cycle=-1,swing_leg=None,
            body_position_world_mm=body.tolist(),body_orientation_world_quaternion_wxyz=[math.cos(pitch/2),0.,math.sin(pitch/2),0.],
            body_rotation_euler_xyz_rad=[0.,pitch,0.],actuator_angles_rad=qrow,passive_beta_rad=betas,
            foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_active=[True]*4,contact_vertex_index=indices,
            sole_clearance_mm=clearance,stance_constraint_error_mm=errors,assumed_com_world_mm=com_world.tolist(),
            support_margin_mm=k.margin([c[:2] for c in contacts],com_world[:2]),body_ground_clearance_mm=body_low,
            part023_OD_angle_from_forward_degrees=carrier))
    qd=np.degrees([r['actuator_angles_rad'] for r in rows]);vel=np.gradient(qd,1/hz,axis=0);acc=np.gradient(vel,1/hz,axis=0)
    validation=dict(duration_s=duration,motion_end_s=cfg['lower_seconds'],sample_hz=hz,samples=len(rows),
        actuator_min_degrees=qd.min(0).tolist(),actuator_max_degrees=qd.max(0).tolist(),
        actuator_peak_speed_degrees_s=np.abs(vel).max(0).tolist(),actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),
        final_actuator_degrees=qd[-1].tolist(),minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),
        minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),
        min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
        max_stance_material_vertex_constraint_error_mm=max(max(r['stance_constraint_error_mm']) for r in rows),
        maximum_adjacent_joint_step_degrees=float(abs(np.diff(qd,axis=0)).max()),
        maximum_rolling_normal_correction_mm=max_correction,rolling_transfers=transfers,minimum_stance_contacts=4,
        research_angle_bounds_satisfied=True,part023_forward_limit_satisfied=min(min(r['part023_OD_angle_from_forward_degrees']) for r in rows)>=90.,
        collision_checked=False,measured_mass_balance_verified=False,hardware_qualified=False)
    return dict(metadata=dict(configuration=cfg,leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],
        position_units='mm',angle_units='radian',time_units='second',world_axes='X forward, Y left, Z up; negative body Y pitch lifts the front.',
        source_geometry=k.g.PARAMETERS['source_blend']),validation=validation,samples=rows,
        phases=[dict(start=0,end=cfg['lower_seconds'],kind='lower_into_rest'),dict(start=cfg['lower_seconds'],end=duration,kind='hold_rest')])

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--height',type=float,default=32.);ap.add_argument('--pitch',type=float,default=0.);ap.add_argument('--x',type=float,default=0.);a=ap.parse_args()
    data=generate(dict(target_body_height_mm=a.height,target_body_pitch_degrees=a.pitch,target_body_x_mm=a.x))
    for file,value in [('source.json',data),('config.json',data['metadata']['configuration']),('validation.json',data['validation'])]:
        (P/file).write_text(json.dumps(value,indent=None if file=='source.json' else 2)+'\n')
    print(json.dumps(data['validation'],indent=2))
