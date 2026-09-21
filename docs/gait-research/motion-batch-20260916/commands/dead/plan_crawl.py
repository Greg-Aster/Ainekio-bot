"""Complete crawl planner using actual sole vertices and discrete rolling contact.

No hardware transport. Units: mm, seconds, geometric joint radians.
"""
import json,math,copy,argparse,time
from pathlib import Path
import numpy as np
import gait_kinematics as g

P=Path(__file__).resolve().parent
LEGS=['FL','FR','RL','RR']
A=np.array([[1.,0,0],[0,0,1],[0,-1,0]])
DATUM=np.array(g.PARAMETERS['controller_body_datum_CAD_xyz_mm'])
SOLE=np.load(P/'sole-hulls.npz')
F0={l:np.array(g.PARAMETERS['legs'][l]['foot_bolt_reference_xyz_mm']) for l in LEGS}

def smooth(u):return u*u*u*(10+u*(-15+6*u))
def rx(a):
    c,s=math.cos(a),math.sin(a)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]])
def rz(a):
    c,s=math.cos(a),math.sin(a)
    return np.array([[c,-s,0],[s,c,0],[0,0,1]])
def to_cad(world,body):return DATUM+A.T@(np.array(world)-body)
def foot_pose(leg,q,body):
    f=g.fk(leg,*q)
    bolt=body+A@(np.array(f['foot_CAD_xyz_mm'])-DATUM)
    rotation=A@rx(q[0])@rz(f['beta'])
    return bolt,rotation,f['beta']
def sole_world(leg,q,body):
    bolt,r,beta=foot_pose(leg,q,body)
    return (SOLE[leg]-F0[leg])@r.T+bolt
def inverse(leg,target,body,seed,reference=None):
    found=g.ik(leg,to_cad(target,body).tolist(),seed=seed,
               foot_reference=None if reference is None else reference.tolist())
    if not found:raise ValueError(('Unreachable',leg,target,body,seed))
    return np.array(seed)+np.array([g.wrap(a-b) for a,b in zip(found[0],seed)])

def sole_target(leg,xy,clearance,body,seed):
    """IK with prescribed bolt XY and evaluated minimum sole height."""
    z=foot_pose(leg,seed,body)[0][2]
    q=seed.copy()
    for _ in range(20):
        q=inverse(leg,[xy[0],xy[1],z],body,q)
        vv=sole_world(leg,q,body);low=float(vv[:,2].min())
        error=clearance-low
        if abs(error)<2e-8:return q,vv
        z+=error
    raise ValueError(('Sole height did not converge',leg,clearance,low))

def contact_state(leg,q,body):
    vv=sole_world(leg,q,body);i=int(np.argmin(vv[:,2]))
    anchor=vv[i].copy();anchor[2]=0.
    return {'q':q.copy(),'index':i,'anchor':anchor}

def roll_step(leg,state,body):
    """Retain a ground-fixed material vertex; transfer when another supports.

    At a feature transfer the new material vertex keeps its predicted tangent
    coordinates and is projected onto the ground. The small normal correction
    is logged, making this finite-step rolling approximation explicit.
    """
    q=inverse(leg,state['anchor'],body,state['q'],SOLE[leg][state['index']])
    transfers=0; correction=0.
    for _ in range(12):
        vv=sole_world(leg,q,body);i=int(np.argmin(vv[:,2]));low=vv[i,2]
        if low>=-2e-8:break
        correction=max(correction,float(-low));transfers+=1
        anchor=vv[i].copy();anchor[2]=0.
        q=inverse(leg,anchor,body,q,SOLE[leg][i])
        state={'q':q,'index':i,'anchor':anchor}
    else:raise ValueError(('Rolling contact did not converge',leg,low))
    state['q']=q
    return state,correction,transfers

def polygon(points):
    v=np.array(points);m=v.mean(0)
    return v[np.argsort(np.arctan2(v[:,1]-m[1],v[:,0]-m[0]))]
def inequalities(points,inset=0):
    v=polygon(points);e=np.roll(v,-1,axis=0)-v
    a=np.column_stack([-e[:,1],e[:,0]])/np.linalg.norm(e,axis=1)[:,None]
    return a,(a*v).sum(1)+inset
def margin(points,point):
    a,b=inequalities(points)
    return float(np.min(a@point-b))
def inside(points,point,inset):
    a,b=inequalities(points,inset);point=np.array(point);candidates=[point]
    candidates += [point+n*(d-n@point) for n,d in zip(a,b)]
    for i in range(len(a)):
        for j in range(i):
            if abs(np.linalg.det(a[[i,j]]))>1e-9:candidates.append(np.linalg.solve(a[[i,j]],b[[i,j]]))
    valid=[x for x in candidates if min(a@x-b)>-1e-8]
    if not valid:raise ValueError('Empty inset support polygon')
    return min(valid,key=lambda x:np.linalg.norm(x-point))

def configured_body_com(config):
    """An explicit assumption, or a user-measured lumped body plus payloads.

    The base mass excludes separately counted payloads. This optional model
    treats the remaining robot as one rigid mass; moving leg mass is still an
    approximation unless a more complete component model is supplied.
    """
    c=config['com']
    if c['mode']=='assumed':return np.array(c['assumed_body_com_mm'],float)
    if c['mode']!='lumped_body_plus_payloads':raise ValueError('Unknown COM model')
    mass=c['base_mass_kg']
    if mass is None or mass<=0:raise ValueError('A measured positive base mass is required')
    weighted=mass*np.array(c.get('base_com_body_mm',c['assumed_body_com_mm']),float)
    for name in ['battery','optional_q6a']:
        payload=c[name]
        if not payload.get('present',True):continue
        if payload['mass_kg'] is None or payload['position_body_mm'] is None:
            raise ValueError('Missing mass or placement for '+name)
        if payload['mass_kg']<0:raise ValueError('Negative payload mass')
        weighted+=payload['mass_kg']*np.array(payload['position_body_mm'],float);mass+=payload['mass_kg']
    return weighted/mass

def simulate(config,verbose=False):
    hz=config['sample_hz'];stride=config['stride_mm'];order=config['cad_leg_order']
    com=configured_body_com(config)
    # The measured soles define the floor; no constant bolt-to-ground offset.
    neutral_v={l:(SOLE[l]-DATUM)@A.T for l in LEGS}
    neutral_height=max(-v[:,2].min() for v in neutral_v.values())
    height=neutral_height+config['body_height_offset_mm']
    body=np.array([0.,0.,neutral_height]);state={};neutral_anchor={};neutral_bolt={}
    for l in LEGS:
        neutral_bolt[l]=A@(F0[l]-DATUM)
        q,vv=sole_target(l,neutral_bolt[l][:2],0.,body,np.zeros(3))
        state[l]=contact_state(l,q,body)
        neutral_anchor[l]=state[l]['anchor'].copy()
    center=np.mean([neutral_anchor[l][:2] for l in LEGS],axis=0)
    samples=[];max_correction=0.;transfers=0;phases=[];swing_peaks=[]
    initial_state=copy.deepcopy(state)

    def record(t,kind,cycle=-1,swing=None,u=0.,goal_clearance=0.):
        contacts=[l!=swing for l in LEGS]
        feet=[];ground=[];idx=[];q=[];clear=[];beta=[];anchor_error=[]
        for l in LEGS:
            st=state[l];bolt,r,b=foot_pose(l,st['q'],body)
            vv=(SOLE[l]-F0[l])@r.T+bolt;low=int(np.argmin(vv[:,2]))
            feet.append(bolt.tolist());q.append(st['q'].tolist());beta.append(b)
            clear.append(float(vv[low,2]));idx.append(st['index'])
            ground.append((st['anchor'] if l!=swing else vv[low]).tolist())
            anchor_error.append(float(np.linalg.norm(vv[st['index']]-st['anchor'])) if l!=swing else None)
        support=[ground[i][:2] for i,c in enumerate(contacts) if c]
        samples.append(dict(time_s=float(t),phase=kind,cycle=cycle,swing_leg=swing,phase_fraction=float(u),
            body_position_world_mm=body.tolist(),body_orientation_world_quaternion_wxyz=[1,0,0,0],
            actuator_angles_rad=q,passive_beta_rad=beta,foot_bolt_world_mm=feet,
            contact_world_mm=ground,contact_active=contacts,contact_vertex_index=idx,
            sole_clearance_mm=clear,support_margin_mm=margin(support,(body+com)[:2]),
            assumed_com_world_mm=(body+com).tolist(),stance_constraint_error_mm=anchor_error,
            swing_clearance_target_mm=float(goal_clearance)))

    record(0,'standing')
    now=0.
    def shift(goal,duration,kind,cycle=-1):
        nonlocal body,state,now,max_correction,transfers
        start=body.copy();n=round(duration*hz);phases.append(dict(start=now,end=now+duration,kind=kind,cycle=cycle))
        for k in range(1,n+1):
            u=k/n;body=start+(goal-start)*smooth(u)
            for l in LEGS:
                state[l],cor,changes=roll_step(l,state[l],body)
                max_correction=max(max_correction,cor);transfers+=changes
            record(now+k/hz,kind,cycle,u=u)
        now+=duration

    shift(np.r_[center-com[:2],height],config['standing_transition_seconds'],'stand_to_crawl')
    for cycle in range(config['cycles']):
        placed=set()
        for phase,lifted in enumerate(order):
            # Fixed, translation-equivariant waypoints make steady cycles repeat.
            proxy=[state[l]['anchor'][:2].copy() for l in LEGS if l!=lifted]
            guide=center+[stride*(cycle+(phase+.5)/4),0]
            target_com=inside(proxy,guide,config['support_margin_mm']+config['support_reserve_mm'])
            target_com+=config.get('body_shift_corrections_mm',{}).get(lifted,[0.,0.])
            goal=np.r_[target_com-com[:2],height]
            shift(goal,config['shift_seconds'],'body_shift_before_'+lifted,cycle)
            start=foot_pose(lifted,state[lifted]['q'],body)[0]
            end_xy=neutral_bolt[lifted][:2]+[stride*(cycle+1),0]
            duration=config['swing_seconds'];n=round(duration*hz)
            phases.append(dict(start=now,end=now+duration,kind='swing_'+lifted,cycle=cycle))
            peak=0.
            for k in range(1,n+1):
                u=k/n;xy=start[:2]+(end_xy-start[:2])*smooth(u)
                clearance=config['swing_clearance_mm']*64*u**3*(1-u)**3
                q,vv=sole_target(lifted,xy,clearance,body,state[lifted]['q'])
                state[lifted]['q']=q
                if k==n:state[lifted]=contact_state(lifted,q,body)
                peak=max(peak,float(vv[:,2].min()))
                record(now+k/hz,'swing_'+lifted,cycle,swing=lifted if k<n else None,u=u,goal_clearance=clearance)
            now+=duration;swing_peaks.append(peak);placed.add(lifted)
        if verbose:print('CYCLE',cycle+1,'t',now,'margin',min(x['support_margin_mm'] for x in samples if x['cycle']==cycle),flush=True)
    shift(np.array([config['cycles']*stride,0.,neutral_height]),config['standing_transition_seconds'],'crawl_to_stand')
    # Hold both standing endpoints for playback clarity without extra displacement.
    q=np.array([x['actuator_angles_rad'] for x in samples]);dt=1/hz
    speed=np.gradient(q,dt,axis=0);acc=np.gradient(speed,dt,axis=0)
    cycle_n=round(4*(config['shift_seconds']+config['swing_seconds'])*hz)
    first=round(config['standing_transition_seconds']*hz)
    repeats=[]
    for cyc in range(2,config['cycles']):
        aa=q[first+cyc*cycle_n:first+(cyc+1)*cycle_n+1]
        bb=q[first+(cyc-1)*cycle_n:first+cyc*cycle_n+1]
        repeats.append(float(np.max(abs(aa-bb))*180/math.pi))
    bounds=config.get('geometric_research_angle_bounds_degrees')
    range_ok=None if bounds is None else all(np.all(q[:,:,j]*180/math.pi>=bounds[n][0]) and np.all(q[:,:,j]*180/math.pi<=bounds[n][1]) for j,n in enumerate(['h','alpha','theta']))
    report=dict(duration_s=now,samples=len(samples),sample_hz=hz,cycles=config['cycles'],steady_cycles=config['steady_cycles'],
        forward_displacement_mm=float(samples[-1]['body_position_world_mm'][0]-samples[0]['body_position_world_mm'][0]),
        walking_advance_mm_per_cycle=stride,walking_speed_mm_s=stride/(4*(config['shift_seconds']+config['swing_seconds'])),
        minimum_support_margin_mm=min(x['support_margin_mm'] for x in samples),requested_support_margin_mm=config['support_margin_mm'],
        min_sole_height_mm=min(min(x['sole_clearance_mm']) for x in samples),swing_peak_sole_clearance_mm=swing_peaks,
        max_stance_material_vertex_constraint_error_mm=max(v for x in samples for v in x['stance_constraint_error_mm'] if v is not None),
        rolling_feature_transfers=transfers,max_rolling_feature_normal_correction_mm=max_correction,
        actuator_min_degrees=(q.min(0)*180/math.pi).tolist(),actuator_max_degrees=(q.max(0)*180/math.pi).tolist(),
        actuator_peak_speed_degrees_s=(abs(speed).max(0)*180/math.pi).tolist(),
        actuator_peak_acceleration_degrees_s2=(abs(acc).max(0)*180/math.pi).tolist(),
        maximum_adjacent_joint_step_degrees=float(abs(np.diff(q,axis=0)).max()*180/math.pi),
        steady_cycle_joint_repeat_error_degrees=repeats,
        research_angle_bounds_satisfied=range_ok,hardware_servo_limits_verified=False,
        contact_model=config['contact_model'],com_mode=config['com']['mode'],
        geometry_feasible=True,collision_checked=False)
    return dict(metadata=dict(leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],
                    position_units='mm',angle_units='radian',time_units='second',world_axes='X physical forward, Y left, Z up',
                    source_geometry=g.PARAMETERS['source_blend'],configuration=config),
                validation=report,phases=phases,samples=samples)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--config',default='crawl-config.json');ap.add_argument('--output',default='crawl-trajectory.json');args=ap.parse_args()
    config=json.loads((P/args.config).read_text())
    result=simulate(config,verbose=True)
    if result['validation']['research_angle_bounds_satisfied'] is False:
        raise ValueError('Trajectory rejected: configured research joint bounds exceeded; change the foot/body trajectory, not individual joint angles')
    if result['validation']['minimum_support_margin_mm']<config['support_margin_mm']-.01:
        raise ValueError('Trajectory rejected: support margin is too small; refine body shifts or stance')
    (P/args.output).write_text(json.dumps(result,separators=(',',':')))
    (P/(Path(args.output).stem+'-validation.json')).write_text(json.dumps(result['validation'],indent=2))
    print(json.dumps(result['validation'],indent=2))
