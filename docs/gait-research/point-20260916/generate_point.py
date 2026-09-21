"""Point: preload rear-right support, lift front-left, extend, return.

Geometric coordinates only. Reuses measured soles and four-bar closure.
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
    cfg=dict(command='point',name='Point with rear-right support crouch',display_label='POINT',sample_hz=120,preview_fps=24,
        gait_start_frame=1849,existing_animation_end_frame=1825,source_blend='Before-Point.blend',output_blend='Ainekio-Point.blend',scene_name='AINEKIO - Point',
        pointing_cad_leg='RL',pointing_physical_leg='front_left',preloaded_cad_leg='FR',preloaded_physical_leg='rear_right',
        crouch_body_position_mm=[-18.,-16.,73.],crouch_body_euler_degrees=[8.,-13.,0.],
        crouch_seconds=2.,lift_seconds=1.,extend_seconds=1.2,point_hold_seconds=2.,stand_hold_seconds=.6,
        lift_shoulder_degrees=40.,point_joint_degrees=[35.,-100.,-48.],pointing_airborne_carrier_bounds_degrees=[-100.,67.4],pointing_shoulder_bounds_degrees=[-5.,65.],minimum_lift_support_margin_mm=8.,
        com=base['com'],geometric_research_angle_bounds_degrees=base['geometric_research_angle_bounds_degrees'],part023_forward_limit_degrees=None,
        face_cues=[dict(time_s=0.,name='point',mode='boomerang',fps=2)],
        completion='Retract front-left arm, replace its sole, undo the support crouch, and hold exact standing neutral.',
        adaptation='Adapt the V1 point gesture: first preload rear-right support with a body shift and crouch; then lift front-left with Part002 and point forward using Part006 and Part005. Keep the three supporting soles planted.',
        contact_model='Measured convex-sole discrete rolling during the four-contact crouch. Fix three material contacts while the front-left foot is airborne. Retrace the arm and crouch to stand. Feature-transfer normal corrections are logged.',hardware_qualified=False)
    cfg.update(settings or {});hz=cfg['sample_hz'];w=LEGS.index(cfg['pointing_cad_leg']);leg=LEGS[w]
    z=max(-k.sole_world(l,np.zeros(3),np.zeros(3))[:,2].min() for l in LEGS)
    body=np.array([0.,0.,z]);euler=np.zeros(3);R=rotation(euler);com=k.configured_body_com(cfg)
    body_mesh=np.load(P/'body-samples.npz')['vertices'];q=np.zeros((4,3));state={}
    rows=[];phases=[];now=0.;transfers=0;max_correction=0.
    def foot(i):
        bolt,r,beta=k.foot_pose(LEGS[i],q[i],np.zeros(3));return body+R@bolt,R@r,beta
    def sole(i):
        bolt,r,_=foot(i);return (k.SOLE[LEGS[i]]-k.F0[LEGS[i]])@r.T+bolt
    for i,l in enumerate(LEGS):
        vv=sole(i);idx=int(vv[:,2].argmin());anchor=vv[idx].copy();anchor[2]=0.;state[l]=dict(index=idx,anchor=anchor)
    def record(t,phase,u,airborne=False):
        active=[i!=w or not airborne for i in range(4)];feet=[];contacts=[];clear=[];errors=[];betas=[];indices=[];carrier=[]
        for i,l in enumerate(LEGS):
            bolt,_,beta=foot(i);vv=sole(i);idx=int(vv[:,2].argmin());st=state[l]
            feet.append(bolt.tolist());betas.append(beta);clear.append(float(vv[idx,2]))
            indices.append(st['index'] if active[i] else idx);contacts.append((st['anchor'] if active[i] else vv[idx]).tolist())
            errors.append(float(np.linalg.norm(vv[st['index']]-st['anchor'])) if active[i] else None)
            par=k.g.PARAMETERS['legs'][l];od=np.array(k.g.fk(l,*q[i])['planar_pivots']['D'])-par['pivots_xy_mm']['O']
            carrier.append(math.degrees(math.atan2(od[1]*math.cos(q[i,0]),od[0]))%360)
        world_com=body+R@com;margin=k.margin([c[:2] for i,c in enumerate(contacts) if active[i]],world_com[:2])
        if min(clear)<-1e-5:raise ValueError(('sole penetration',t,min(clear)))
        if airborne and margin<cfg['minimum_lift_support_margin_mm']:raise ValueError(('support margin before lift',margin))
        low=float((body_mesh@R[2]+body[2]).min())
        if low<1.:raise ValueError(('body clearance',low))
        rows.append(dict(time_s=t,phase=phase,phase_fraction=u,cycle=-1,swing_leg=leg if airborne else None,
            body_position_world_mm=body.tolist(),body_rotation_euler_xyz_rad=euler.tolist(),body_orientation_world_quaternion_wxyz=quaternion(euler),
            actuator_angles_rad=q.tolist(),passive_beta_rad=betas,foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_active=active,
            contact_vertex_index=indices,sole_clearance_mm=clear,stance_constraint_error_mm=errors,assumed_com_world_mm=world_com.tolist(),support_margin_mm=margin,
            body_ground_clearance_mm=low,body_contact_active=False,support_source='feet',part023_OD_angle_from_forward_degrees=carrier))
    record(0.,'preload_rear_right',0.)
    n=round(cfg['crouch_seconds']*hz);phases.append(dict(start=0.,end=n/hz,kind='preload_rear_right'))
    for j in range(1,n+1):
        u=k.smooth(j/n);body=np.array([0.,0.,z])+(np.array(cfg['crouch_body_position_mm'])-[0.,0.,z])*u
        euler=np.radians(cfg['crouch_body_euler_degrees'])*u;R=rotation(euler)
        for i,l in enumerate(LEGS):
            st=state[l]
            def inverse(anchor,idx):return k.inverse(l,R.T@(anchor-body),np.zeros(3),q[i],k.SOLE[l][idx])
            q[i]=inverse(st['anchor'],st['index'])
            for _ in range(16):
                vv=sole(i);idx=int(vv[:,2].argmin());low=vv[idx,2]
                if low>=-2e-8:break
                max_correction=max(max_correction,float(-low));transfers+=1
                anchor=vv[idx].copy();anchor[2]=0.;q[i]=inverse(anchor,idx);st=dict(index=idx,anchor=anchor)
            else:raise ValueError(('rolling did not converge',l))
            state[l]=st
        record(j/hz,'preload_rear_right',j/n)
    now=n/hz;crouch=copy.deepcopy(rows);crouch_q=q.copy();lowered=rows[-1]
    triangle=k.margin([c[:2] for i,c in enumerate(lowered['contact_world_mm']) if i!=w],lowered['assumed_com_world_mm'][:2])
    if triangle<cfg['minimum_lift_support_margin_mm']:raise ValueError(('preload incomplete',triangle))
    def segment(target,duration,name,airborne=True):
        nonlocal now,q
        initial=q[w].copy();n=round(duration*hz);phases.append(dict(start=now,end=now+n/hz,kind=name))
        for j in range(1,n+1):
            q[w]=initial+(np.array(target)-initial)*k.smooth(j/n);record(round(now*hz+j)/hz,name,j/n,airborne)
        now=round(now*hz+n)/hz
    lifted=q[w].copy();lifted[0]=math.radians(cfg['lift_shoulder_degrees'])
    segment(lifted,cfg['lift_seconds'],'lift_front_left')
    point=np.radians(cfg['point_joint_degrees']);segment(point,cfg['extend_seconds'],'extend_to_point')
    point_start=now;segment(point,cfg['point_hold_seconds'],'hold_point');point_end=now
    segment(lifted,cfg['extend_seconds'],'retract_front_left');segment(crouch_q[w],cfg['lift_seconds'],'replace_front_left')
    touchdown=copy.deepcopy(lowered);touchdown.update(time_s=now,phase='replace_front_left',phase_fraction=1.);rows[-1]=touchdown
    phases.append(dict(start=now,end=now+cfg['crouch_seconds'],kind='return_to_standing'))
    for j,r in enumerate(reversed(crouch[:-1]),1):
        r=copy.deepcopy(r);r.update(time_s=round(now*hz+j)/hz,phase='return_to_standing',phase_fraction=j/(len(crouch)-1));rows.append(r)
    now+=cfg['crouch_seconds'];motion_end=now;cfg['face_cues'].append(dict(time_s=now,name='stand',mode='once',fps=1))
    phases.append(dict(start=now,end=now+cfg['stand_hold_seconds'],kind='hold_standing'))
    for j in range(1,round(cfg['stand_hold_seconds']*hz)+1):
        r=copy.deepcopy(rows[-1]);r.update(time_s=round(now*hz+j)/hz,phase='hold_standing',phase_fraction=1.);rows.append(r)
    qd=np.degrees([r['actuator_angles_rad'] for r in rows]);vel=np.gradient(qd,1/hz,axis=0);acc=np.gradient(vel,1/hz,axis=0)
    for i,l in enumerate(LEGS):
        for axis,key in enumerate(['h','alpha','theta']):
            base_lo,base_hi=cfg['geometric_research_angle_bounds_degrees'][key]
            lo,hi=cfg['pointing_shoulder_bounds_degrees'] if i==w and axis==0 else cfg['pointing_airborne_carrier_bounds_degrees'] if i==w and axis==1 else [base_lo,base_hi]
            if qd[:,i,axis].min()<lo-1e-6 or qd[:,i,axis].max()>hi+1e-6:raise ValueError(('bound',l,key,qd[:,i,axis].min(),qd[:,i,axis].max(),lo,hi))
            planted=np.array([r['contact_active'][i] for r in rows])
            if qd[planted,i,axis].min()<base_lo-1e-6 or qd[planted,i,axis].max()>base_hi+1e-6:raise ValueError(('loaded stance bound',l,key))
    pivots=k.g.fk(leg,*point)['planar_pivots'];par=k.g.PARAMETERS['legs'][leg]
    reach=float(np.linalg.norm(np.array(pivots['F'])-par['pivots_xy_mm']['O']))

    v=dict(duration_s=rows[-1]['time_s'],motion_end_s=motion_end,sample_hz=hz,samples=len(rows),point_hold_start_s=point_start,point_hold_end_s=point_end,point_pivot_O_to_foot_bolt_mm=reach,
        actuator_min_degrees=qd.min(0).tolist(),actuator_max_degrees=qd.max(0).tolist(),actuator_peak_speed_degrees_s=np.abs(vel).max(0).tolist(),actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),
        crouched_actuator_degrees=np.degrees(crouch_q).tolist(),minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),prelift_triangle_margin_mm=triangle,minimum_stance_contacts=3,
        maximum_rolling_normal_correction_mm=max_correction,rolling_transfers=transfers,max_stance_material_vertex_constraint_error_mm=max(e for r in rows for e in r['stance_constraint_error_mm'] if e is not None),
        minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
        point_foot_bolt_world_mm=rows[round(point_start*hz)]['foot_bolt_world_mm'][w],maximum_adjacent_joint_step_degrees=float(abs(np.diff(qd,axis=0)).max()),
        final_joint_return_error_degrees=float(abs(qd[-1]-qd[0]).max()),research_angle_bounds_satisfied=True,collision_checked=False,hardware_servo_limits_verified=False,measured_mass_balance_verified=False,hardware_qualified=False)
    return dict(metadata=dict(configuration=cfg,leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],position_units='mm',angle_units='radian',time_units='second',
        world_axes='X forward, Y left, Z up; negative body Y pitch lifts the front.',source_geometry=k.g.PARAMETERS['source_blend']),phases=phases,samples=rows,validation=v)

if __name__=='__main__':
    data=generate(json.loads((P/'config.json').read_text()) if (P/'config.json').exists() else None)
    for name,value in [('source.json',data),('config.json',data['metadata']['configuration']),('validation.json',data['validation'])]:
        (P/name).write_text(json.dumps(value,indent=None if name=='source.json' else 2)+'\n')
    print(json.dumps(data['validation'],indent=2))
