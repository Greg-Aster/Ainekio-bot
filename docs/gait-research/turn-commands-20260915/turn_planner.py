"""Four-bar finite-turn research: world contacts, yaw-aware IK, no PWM."""
import argparse,copy,json,math
from pathlib import Path
import numpy as np
import plan_crawl as k
P=Path(__file__).resolve().parent
LEGS=k.LEGS
def rz(a):
    c,s=math.cos(a),math.sin(a)
    return np.array([[c,-s,0],[s,c,0],[0,0,1.]])
def generate(settings=None):
    base=json.loads((P/'base-config.json').read_text())
    cfg=dict(name='Turn right around - twelve-servo four-bar',command='turn_right_180',
        yaw_degrees=-180.,turn_cycles=6,body_height_mm=78.,stance_half_width_mm=67.,
        foot_x_offsets_mm={'FL':-12.,'FR':-12.,'RL':-10.,'RR':-10.},
        shift_seconds=.5,swing_seconds=.5,setup_swing_seconds=.6,setup_shift_seconds=.4,
        support_margin_mm=2.,swing_clearance_mm=5.,sample_hz=120,preview_fps=24,
        gait_start_frame=529,existing_animation_end_frame=505,com=base['com'],
        geometric_research_angle_bounds_degrees=base['geometric_research_angle_bounds_degrees'],
        cad_leg_order=['FL','RL','FR','RR'],part023_forward_limit_degrees=90.,
        contact_model='Measured sole point contact: retain a world-fixed material vertex, transfer at supporting-feature changes, permit rotation about the contact. Yaw scrub, friction and torsional loads unverified.',
        acceptance_status='TURN_RIGHT_180_GEOMETRIC_RESEARCH',source_blend=str(P/'Before-Turn-Right-180.blend'),
        geometry='robot-gait-parameters.json',configuration_file='turn-right-config.json',
        output_blend='Ainekio-Turn-Right-180.blend',scene_name='AINEKIO - Turn Right 180',
        reference_report='TURN_RIGHT_180.md',gait_id='turn_right_180_fourbar_20260915',
        gait_family='whole_body_wave',display_label='TURN RIGHT 180 | TWELVE SERVOS',
        vertical_reference_joint='Part023_O',provisional=True,body_bob_mm=0.,body_sway_mm=0.,
        support_margin_enforced=False,stride_mm=0.,standing_transition_seconds=1.,
        blocking_geometry=base['blocking_geometry'],angle_bounds_note=base['angle_bounds_note'])
    cfg.update(settings or {})
    hz=cfg['sample_hz'];count=cfg['turn_cycles'];cfg['cycles']=count
    cfg['cycle_seconds']=4*(cfg['shift_seconds']+cfg['swing_seconds'])
    hz=int(hz);body=np.array([0.,0.,max(-((k.SOLE[l]-k.DATUM)@k.A.T)[:,2].min() for l in LEGS)])
    neutral_z=body[2];yaw=0.;now=0.;rows=[];phases=[];max_normal=0.;transfers=0
    com=k.configured_body_com(cfg);bounds=cfg['geometric_research_angle_bounds_degrees'];current_phase='stand'
    def foot(l,q):
        bolt,orientation,beta=k.foot_pose(l,q,np.zeros(3));r=rz(yaw)
        return body+r@bolt,r@orientation,beta
    def sole(l,q):
        bolt,r,_=foot(l,q);return (k.SOLE[l]-k.F0[l])@r.T+bolt
    def inverse(l,world,seed,reference=None):
        local=rz(yaw).T@(np.asarray(world)-body)
        return k.inverse(l,local,np.zeros(3),seed,reference)
    def check(l,q):
        deg=np.degrees(q)
        for j,name in enumerate(['h','alpha','theta']):
            if not bounds[name][0]-1e-6<=deg[j]<=bounds[name][1]+1e-6:
                raise ValueError(f'{current_phase}: {l} {name}={deg[j]:.4f} outside {bounds[name]}')
    def target(l,xy,clear,seed):
        z=foot(l,seed)[0][2];q=seed.copy()
        for _ in range(24):
            q=inverse(l,[xy[0],xy[1],z],q);vv=sole(l,q);error=clear-vv[:,2].min()
            if abs(error)<2e-8:check(l,q);return q
            z+=error
        raise ValueError(('sole target',l,error))
    def contact(l,q):
        vv=sole(l,q);idx=int(vv[:,2].argmin());anchor=vv[idx].copy();anchor[2]=0.
        return dict(q=q.copy(),index=idx,anchor=anchor)
    state={l:contact(l,np.zeros(3)) for l in LEGS}
    nominal={l:foot(l,np.zeros(3))[0][:2].copy() for l in LEGS}
    basefoot={l:np.array([nominal[l][0]+cfg['foot_x_offsets_mm'][l],math.copysign(cfg['stance_half_width_mm'],nominal[l][1])]) for l in LEGS}
    def roll(l):
        nonlocal max_normal,transfers
        st=state[l];q=inverse(l,st['anchor'],st['q'],k.SOLE[l][st['index']])
        for _ in range(14):
            vv=sole(l,q);idx=int(vv[:,2].argmin());low=vv[idx,2]
            if low>=-2e-8:break
            max_normal=max(max_normal,float(-low));transfers+=1
            anchor=vv[idx].copy();anchor[2]=0.
            q=inverse(l,anchor,q,k.SOLE[l][idx]);st=dict(q=q,index=idx,anchor=anchor)
        else:raise ValueError(('rolling failed',l,low))
        check(l,q);st['q']=q;state[l]=st
    def record(t,phase,active=None,cycle=-1):
        angles=[];feet=[];contacts=[];clear=[];errors=[];indices=[];betas=[];carrier=[];pitch=[];lower=[]
        for l in LEGS:
            st=state[l];q=st['q'];bolt,_,beta=foot(l,q);vv=sole(l,q);idx=int(vv[:,2].argmin());on=l!=active
            angles.append(q.tolist());feet.append(bolt.tolist());contacts.append((st['anchor'] if on else vv[idx]).tolist())
            clear.append(float(vv[idx,2]));errors.append(float(np.linalg.norm(vv[st['index']]-st['anchor'])) if on else None)
            indices.append(st['index']);betas.append(beta)
            par=k.g.PARAMETERS['legs'][l];fk=k.g.fk(l,*q);od=np.array(fk['planar_pivots']['D'])-par['pivots_xy_mm']['O']
            carrier.append(float(np.degrees(np.arctan2(od[1]*math.cos(q[0]),od[0]))))
            hip=k.A@(np.array(par['hip_axis_point_xyz_mm'])-k.DATUM);v=rz(yaw).T@(bolt-body)-hip
            pitch.append(float(np.degrees(np.arctan2(v[0],-v[2]))))
            df=np.array(fk['planar_pivots']['F'])-fk['planar_pivots']['D'];lower.append(float(np.degrees(np.arctan2(df[1],df[0]))))
        active_flags=[l!=active for l in LEGS];cw=body+rz(yaw)@com
        rows.append(dict(time_s=float(t),phase=phase,cycle=cycle,swing_leg=active,phase_fraction=0.,
            body_position_world_mm=body.tolist(),body_orientation_world_quaternion_wxyz=[math.cos(yaw/2),0,0,math.sin(yaw/2)],
            body_yaw_world_rad=float(yaw),actuator_angles_rad=angles,passive_beta_rad=betas,
            foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_active=active_flags,
            contact_vertex_index=indices,sole_clearance_mm=clear,stance_constraint_error_mm=errors,
            assumed_com_world_mm=cw.tolist(),support_margin_mm=k.margin([c[:2] for c,on in zip(contacts,active_flags) if on],cw[:2]),
            part023_OD_angle_from_forward_degrees=carrier,hip_to_foot_pitch_from_down_vertical_degrees=pitch,
            lower_DF_angle_from_forward_in_leg_plane_degrees=lower))
    def shift(goal,heading,duration,label,cycle=-1):
        nonlocal body,yaw,now,current_phase
        current_phase=label;start=body.copy();begin=yaw;n=round(duration*hz);duration=n/hz
        phases.append(dict(start=now,end=now+duration,kind=label,cycle=cycle))
        for j in range(1,n+1):
            u=k.smooth(j/n);body=start+(np.array(goal)-start)*u;yaw=begin+(heading-begin)*u
            for l in LEGS:roll(l)
            record(now+j/hz,label,cycle=cycle)
        now+=duration
    def prepare(l,heading,duration,label,cycle=-1):
        target_com=k.inside([state[x]['anchor'][:2] for x in LEGS if x!=l],[0.,0.],cfg['support_margin_mm'])
        offset=(rz(heading)@com)[:2]
        shift([*(target_com-offset),body[2]],heading,duration,label,cycle)
    def swing(l,xy,duration,label,cycle=-1):
        nonlocal now,current_phase
        current_phase=label;start=foot(l,state[l]['q'])[0][:2];n=round(duration*hz);duration=n/hz
        phases.append(dict(start=now,end=now+duration,kind=label,cycle=cycle))
        for j in range(1,n+1):
            u=j/n;goal=start+(np.array(xy)-start)*k.smooth(u)
            q=target(l,goal,cfg['swing_clearance_mm']*64*u**3*(1-u)**3,state[l]['q']);state[l]['q']=q
            if j==n:state[l]=contact(l,q)
            record(now+j/hz,label,l if j<n else None,cycle)
        now+=duration
    record(0.,'standing')
    shift([0.,0.,cfg['body_height_mm']],0.,1.,'entry_height')
    for l in cfg['cad_leg_order']:
        prepare(l,0.,cfg['setup_shift_seconds'],'entry_shift_'+l)
        swing(l,basefoot[l],cfg['setup_swing_seconds'],'entry_place_'+l)
    turning_start=now
    for cycle in range(count):
        end_heading=math.radians(cfg['yaw_degrees'])*(cycle+1)/count
        for j,l in enumerate(cfg['cad_leg_order']):
            heading=math.radians(cfg['yaw_degrees'])*(cycle+(j+1)/4)/count
            prepare(l,heading,cfg['shift_seconds'],'turn_shift_'+l,cycle)
            xy=(rz(end_heading)@np.r_[basefoot[l],0.])[:2]
            swing(l,xy,cfg['swing_seconds'],'turn_swing_'+l,cycle)
    turning_end=now
    shift([0.,0.,neutral_z],yaw,1.,'exit_center_and_height')
    for l in cfg['cad_leg_order']:
        prepare(l,yaw,cfg['setup_shift_seconds'],'exit_shift_'+l)
        xy=(rz(yaw)@np.r_[nominal[l],0.])[:2]
        swing(l,xy,cfg['setup_swing_seconds'],'exit_place_'+l)
    shift([0.,0.,neutral_z],yaw,1.,'standing_after_turn')
    q=np.array([r['actuator_angles_rad'] for r in rows]);qd=np.degrees(q)
    vel=np.gradient(qd,1/hz,axis=0);acc=np.gradient(vel,1/hz,axis=0)
    v=dict(duration_s=now,samples=len(rows),sample_hz=hz,heading_change_degrees=math.degrees(yaw),
        turn_time_range_s=[turning_start,turning_end],endpoint_body_translation_mm=body[:2].tolist(),
        maximum_body_radius_mm=max(float(np.linalg.norm(r['body_position_world_mm'][:2])) for r in rows),
        actuator_min_degrees=qd.min(0).tolist(),actuator_max_degrees=qd.max(0).tolist(),
        actuator_peak_speed_degrees_s=np.abs(vel).max(0).tolist(),actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),
        endpoint_actuator_degrees=qd[-1].tolist(),maximum_adjacent_joint_step_degrees=float(abs(np.diff(qd,axis=0)).max()),
        minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),
        min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
        max_stance_material_vertex_constraint_error_mm=max(x for r in rows for x in r['stance_constraint_error_mm'] if x is not None),
        maximum_rolling_normal_correction_mm=max_normal,rolling_transfers=transfers,
        minimum_stance_contacts=min(sum(r['contact_active']) for r in rows),
        minimum_part023_angle_degrees=min(min(r['part023_OD_angle_from_forward_degrees']) for r in rows),
        research_angle_bounds_satisfied=True,part023_forward_limit_satisfied=True,
        balance_qualified=False,hardware_servo_limits_verified=False,collision_checked=False)
    assert v['minimum_part023_angle_degrees']>=90-1e-5
    cfg['body_sway_mm']=v['maximum_body_radius_mm']
    return dict(metadata=dict(configuration=cfg,leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],
        position_units='mm',angle_units='radian',time_units='second',world_axes='X initial forward, Y initial left, Z up; right turn is negative yaw',
        source_geometry=k.g.PARAMETERS['source_blend']),validation=v,phases=phases,samples=rows)
