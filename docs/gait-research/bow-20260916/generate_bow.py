"""Single Bow: brace, reach front legs forward while bowing, hold, and stand.

Measured sole rolling, geometric joint radians, fixed four-bar branches.
"""
import copy,json,math
from pathlib import Path
import numpy as np
import plan_crawl as k
P=Path(__file__).resolve().parent
LEGS=k.LEGS

def rotation(e):
    x,y,z=e;c,s=math.cos(y),math.sin(y)
    return k.rz(z)@np.array([[c,0,s],[0,1,0],[-s,0,c]])@k.rx(x)

def quaternion(e):
    x,y,z=np.array(e)/2;cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
    return [cx*cy*cz+sx*sy*sz,sx*cy*cz-cx*sy*sz,cx*sy*cz+sx*cy*sz,cx*cy*sz-sx*sy*cz]

def generate(settings=None):
    base=json.loads((P/'base-config.json').read_text())
    cfg=dict(command='bow',name='Front-low rear-high Bow',display_label='BOW',sample_hz=120,preview_fps=24,
        gait_start_frame=2881,existing_animation_end_frame=2857,source_blend='Before-Bow.blend',output_blend='Ainekio-Bow.blend',scene_name='AINEKIO - Bow',
        ready_body_position_mm=[0.,0.,76.],bow_body_position_mm=[-10.,0.,70.],bow_body_euler_degrees=[0.,12.,0.],front_reach_slide_mm=20.,
        brace_seconds=1.,lower_seconds=1.5,bow_hold_seconds=3.,stand_hold_seconds=.5,minimum_support_margin_mm=8.,
        com=base['com'],geometric_research_angle_bounds_degrees=base['geometric_research_angle_bounds_degrees'],part023_forward_limit_degrees=None,
        face_cues=[dict(time_s=0.,name='bow',mode='once',fps=1)],
        completion='Hold the bow, raise the front through the braced stance, then return to exact standing and hold.',
        adaptation='Emulate V1 Bow: prepare the stance, lower the front pair while the rear remains raised, hold, then stand. V1 front lower joints R3/L3 both reach 90 degrees; solve the analogous twelve-servo pose using geometric body/sole targets instead of copying electrical angles.',
        contact_model='Four grounded measured convex soles. Retain fixed material vertices between rolling feature transfers; reverse the solved paths to rise without accumulated contact drift.',hardware_qualified=False)
    cfg.update(settings or {});hz=cfg['sample_hz'];z=max(-k.sole_world(l,np.zeros(3),np.zeros(3))[:,2].min() for l in LEGS)
    body=np.array([0.,0.,z]);euler=np.zeros(3);R=rotation(euler);q=np.zeros((4,3));com=k.configured_body_com(cfg)
    mesh=np.load(P/'body-samples.npz')['vertices'];state={};rows=[];phases=[];now=0.;max_correction=0.;transfers=0
    def foot(i):
        bolt,r,beta=k.foot_pose(LEGS[i],q[i],np.zeros(3));return body+R@bolt,R@r,beta
    def sole(i):
        bolt,r,_=foot(i);return (k.SOLE[LEGS[i]]-k.F0[LEGS[i]])@r.T+bolt
    for i,l in enumerate(LEGS):
        vv=sole(i);idx=int(vv[:,2].argmin());anchor=vv[idx].copy();anchor[2]=0.;state[l]=dict(index=idx,anchor=anchor)
    def record(t,phase,u,cycle=-1):
        feet=[];contacts=[];clear=[];errors=[];betas=[];indices=[];carrier=[]
        for i,l in enumerate(LEGS):
            bolt,_,beta=foot(i);vv=sole(i);st=state[l]
            feet.append(bolt.tolist());betas.append(beta);clear.append(float(vv[:,2].min()));contacts.append(st['anchor'].tolist());indices.append(st['index'])
            errors.append(float(np.linalg.norm(vv[st['index']]-st['anchor'])))
            par=k.g.PARAMETERS['legs'][l];od=np.array(k.g.fk(l,*q[i])['planar_pivots']['D'])-par['pivots_xy_mm']['O'];carrier.append(math.degrees(math.atan2(od[1]*math.cos(q[i,0]),od[0]))%360)
        world_com=body+R@com;margin=k.margin([c[:2] for c in contacts],world_com[:2]);low=float((mesh@R[2]+body[2]).min())
        if min(clear)<-1e-5:raise ValueError(('sole penetration',t,min(clear)))
        if margin<cfg['minimum_support_margin_mm']:raise ValueError(('support margin',t,margin))
        if low<1.:raise ValueError(('body clearance',t,low))
        rows.append(dict(time_s=t,phase=phase,phase_fraction=u,cycle=cycle,swing_leg=None,
            body_position_world_mm=body.tolist(),body_rotation_euler_xyz_rad=euler.tolist(),body_orientation_world_quaternion_wxyz=quaternion(euler),
            actuator_angles_rad=q.tolist(),passive_beta_rad=betas,foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_active=[True]*4,
            contact_vertex_index=indices,sole_clearance_mm=clear,stance_constraint_error_mm=errors,assumed_com_world_mm=world_com.tolist(),support_margin_mm=margin,
            body_ground_clearance_mm=low,body_contact_active=False,support_source='feet',part023_OD_angle_from_forward_degrees=carrier))
    def solve_pose(pos,angles):
        nonlocal body,euler,R,max_correction,transfers
        body=pos;euler=angles;R=rotation(euler)
        for i,l in enumerate(LEGS):
            st=state[l]
            def inverse(anchor,idx):return k.inverse(l,R.T@(anchor-body),np.zeros(3),q[i],k.SOLE[l][idx])
            q[i]=inverse(st['anchor'],st['index'])
            for _ in range(16):
                vv=sole(i);idx=int(vv[:,2].argmin());low=vv[idx,2]
                if low>=-2e-8:break
                max_correction=max(max_correction,float(-low));transfers+=1
                anchor=vv[idx].copy();anchor[2]=0.;q[i]=inverse(anchor,idx);st=dict(index=idx,anchor=anchor)
            else:raise ValueError(('rolling failed',l))
            state[l]=st
    def add_recorded(template,name,cycle=-1):
        nonlocal now
        start=now;phases.append(dict(start=start,end=start+(len(template)-1)/hz,kind=name,cycle=cycle))
        for j,r in enumerate(template[1:],1):
            r=copy.deepcopy(r);r.update(time_s=round(start*hz+j)/hz,phase=name,phase_fraction=j/(len(template)-1),cycle=cycle);rows.append(r)
        now=rows[-1]['time_s']
    def pose_segment(position,angles,duration,name,front_slide_mm=0.):
        nonlocal now
        initial_pos=body.copy();initial_angles=euler.copy();n=round(duration*hz)
        phases.append(dict(start=now,end=now+n/hz,kind=name));first=len(rows)-1
        previous_u=0.
        for j in range(1,n+1):
            u=k.smooth(j/n)
            for l in ['RL','RR']:state[l]['anchor'][0]+=front_slide_mm*(u-previous_u)
            previous_u=u
            solve_pose(initial_pos+(np.array(position)-initial_pos)*u,initial_angles+(np.array(angles)-initial_angles)*u)
            record(round(now*hz+j)/hz,name,j/n)
        now=rows[-1]['time_s'];return copy.deepcopy(rows[first:])
    def hold(duration,name):
        nonlocal now
        n=round(duration*hz);start=now;phases.append(dict(start=start,end=start+n/hz,kind=name))
        for j in range(1,n+1):
            r=copy.deepcopy(rows[-1]);r.update(time_s=round(start*hz+j)/hz,phase=name,phase_fraction=j/n);rows.append(r)
        now=rows[-1]['time_s']
    record(0.,'brace_stance',0.)
    brace=pose_segment(cfg['ready_body_position_mm'],[0.,0.,0.],cfg['brace_seconds'],'brace_stance')
    lowering=pose_segment(cfg['bow_body_position_mm'],np.radians(cfg['bow_body_euler_degrees']),cfg['lower_seconds'],'stretch_front_into_bow',cfg['front_reach_slide_mm'])
    bow_start=now;bow_q=q.copy();hold(cfg['bow_hold_seconds'],'hold_bow');bow_end=now
    add_recorded(list(reversed(lowering)),'raise_front');add_recorded(list(reversed(brace)),'return_to_standing');motion_end=now
    cfg['face_cues']=[dict(time_s=0.,name='bow',mode='once',fps=1),dict(time_s=motion_end,name='stand',mode='once',fps=1)]
    hold(cfg['stand_hold_seconds'],'hold_standing')
    for r in rows:
        sliding=r['phase'] in ['stretch_front_into_bow','raise_front'] and 0.<r['phase_fraction']<1.
        r['contact_motion_model']=['rolling','rolling']+(['intentional_slide','intentional_slide'] if sliding else ['rolling','rolling'])
        r['prescribed_front_slide_mm']=cfg['front_reach_slide_mm']*(k.smooth(r['phase_fraction']) if r['phase']=='stretch_front_into_bow' else 1.-k.smooth(r['phase_fraction']) if r['phase']=='raise_front' else 1. if r['phase']=='hold_bow' else 0.)
    qd=np.degrees([r['actuator_angles_rad'] for r in rows]);vel=np.gradient(qd,1/hz,axis=0);acc=np.gradient(vel,1/hz,axis=0)
    for i,l in enumerate(LEGS):
        for axis,key in enumerate(['h','alpha','theta']):
            lo,hi=cfg['geometric_research_angle_bounds_degrees'][key]
            if qd[:,i,axis].min()<lo-1e-6 or qd[:,i,axis].max()>hi+1e-6:raise ValueError(('bound',l,key,qd[:,i,axis].min(),qd[:,i,axis].max(),lo,hi))
    front_datum=np.array([75.,0.,0.]);front=body+R@front_datum
    R0=rotation([0.,0.,0.]);standing_front=np.array(rows[0]['body_position_world_mm'])+R0@front_datum
    v=dict(duration_s=rows[-1]['time_s'],motion_end_s=motion_end,sample_hz=hz,samples=len(rows),bow_hold_start_s=bow_start,bow_hold_end_s=bow_end,
        actuator_min_degrees=qd.min(0).tolist(),actuator_max_degrees=qd.max(0).tolist(),actuator_peak_speed_degrees_s=np.abs(vel).max(0).tolist(),actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),
        bow_actuator_degrees=np.degrees(bow_q).tolist(),front_body_datum_mm=front_datum.tolist(),front_body_drop_mm=float(standing_front[2]-front[2]),
        minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),minimum_stance_contacts=4,maximum_rolling_normal_correction_mm=max_correction,solved_rolling_transfers=transfers,
        max_stance_material_vertex_constraint_error_mm=max(max(r['stance_constraint_error_mm']) for r in rows),minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
        maximum_adjacent_joint_step_degrees=float(abs(np.diff(qd,axis=0)).max()),final_joint_return_error_degrees=float(abs(qd[-1]-qd[0]).max()),research_angle_bounds_satisfied=True,
        intentional_front_contact_slide_mm=cfg['front_reach_slide_mm'],sliding_friction_verified=False,
        collision_checked=False,hardware_servo_limits_verified=False,measured_mass_balance_verified=False,hardware_qualified=False)
    return dict(metadata=dict(configuration=cfg,leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],position_units='mm',angle_units='radian',time_units='second',
        world_axes='X forward, Y left, Z up; negative body Y pitch lifts the front.',source_geometry=k.g.PARAMETERS['source_blend']),phases=phases,samples=rows,validation=v)

if __name__=='__main__':
    data=generate(json.loads((P/'config.json').read_text()) if (P/'config.json').exists() else None)
    for name,value in [('source.json',data),('config.json',data['metadata']['configuration']),('validation.json',data['validation'])]:
        (P/name).write_text(json.dumps(value,indent=None if name=='source.json' else 2)+'\n')
    print(json.dumps(data['validation'],indent=2))
