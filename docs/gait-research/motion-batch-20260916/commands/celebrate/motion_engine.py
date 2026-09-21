"""Measured four-bar source generator for grounded rocks and belly-supported waves.

No electrical calibration, hardware communication or scene edits. Each copied
command folder is self-contained and config.json selects the choreography.
"""
import copy,json,math
from pathlib import Path
import numpy as np
import plan_crawl as k
import generate_lower_reference as lower
P=Path(__file__).resolve().parent
LEGS=k.LEGS

def orientation(euler):
    x,y,z=euler;c,s=math.cos(y),math.sin(y)
    R=k.rz(z)@np.array([[c,0,s],[0,1,0],[-s,0,c]])@k.rx(x)
    x,y,z=np.array(euler)/2;cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
    return R,[cx*cy*cz+sx*sy*sz,sx*cy*cz-cx*sy*sz,cx*sy*cz+sx*cy*sz,cx*cy*sz-sx*sy*cz]

def hull(points):
    points=sorted(set(tuple(round(float(v),7) for v in p) for p in points))
    def half(seq):
        out=[]
        for p in seq:
            while len(out)>=2 and np.cross(np.array(out[-1])-out[-2],np.array(p)-out[-1])<=0:out.pop()
            out.append(p)
        return out
    return np.array(half(points)[:-1]+half(reversed(points))[:-1])

def generate(cfg):
    cfg=copy.deepcopy(cfg);base=json.loads((P/'base-config.json').read_text())
    cfg.setdefault('com',base['com']);cfg.setdefault('geometric_research_angle_bounds_degrees',base['geometric_research_angle_bounds_degrees'])
    hz=cfg['sample_hz'];mesh=np.load(P/'body-samples.npz')['vertices'];com=k.configured_body_com(cfg)
    neutral_z=max(-k.sole_world(l,np.zeros(3),np.zeros(3))[:,2].min() for l in LEGS)
    neutral=np.array([0.,0.,neutral_z,0.,0.,0.]);rows=[];phases=[];max_correction=0.;rolling_transfers=0

    def append(sequence,name,cycle=-1):
        start=(len(rows)-1)/hz if rows else 0.;n=len(sequence)-1
        if n<=0:raise ValueError('Empty primitive')
        phases.append(dict(start=start,end=start+n/hz,kind=name,cycle=cycle))
        for i,old in enumerate(sequence):
            if rows and i==0:continue
            r=copy.deepcopy(old);r.update(time_s=len(rows)/hz,phase=name,phase_fraction=i/n,cycle=cycle,swing_leg=None);rows.append(r)

    def grounded(start,goal,duration,initial=None):
        nonlocal max_correction,rolling_transfers
        state=copy.deepcopy(initial);result=[];n=round(duration*hz)
        for sample in range(n+1):
            pose=start+(goal-start)*k.smooth(sample/n);body,euler=pose[:3],pose[3:];R,quat=orientation(euler)
            def sole(l,q):
                bolt,r,beta=k.foot_pose(l,q,np.zeros(3));return (k.SOLE[l]-k.F0[l])@(R@r).T+body+R@bolt
            if state is None:
                state={}
                for l in LEGS:
                    vv=sole(l,np.zeros(3));idx=int(vv[:,2].argmin());anchor=vv[idx].copy();anchor[2]=0.;state[l]=dict(q=np.zeros(3),index=idx,anchor=anchor)
            angles=[];feet=[];contacts=[];indices=[];errors=[];clear=[];betas=[];carrier=[]
            for l in LEGS:
                st=state[l]
                def inverse(anchor,q,index):return k.inverse(l,R.T@(anchor-body),np.zeros(3),q,k.SOLE[l][index])
                q=inverse(st['anchor'],st['q'],st['index']) if sample else st['q'].copy()
                for _ in range(20):
                    vv=sole(l,q);idx=int(vv[:,2].argmin());low=vv[idx,2]
                    if low>=-2e-8:break
                    max_correction=max(max_correction,float(-low));rolling_transfers+=1
                    anchor=vv[idx].copy();anchor[2]=0.;q=inverse(anchor,q,idx);st=dict(q=q,index=idx,anchor=anchor)
                else:raise ValueError(('rolling did not converge',l,low))
                st['q']=q;state[l]=st;bolt,_,beta=k.foot_pose(l,q,np.zeros(3));vv=sole(l,q)
                angles.append(q.tolist());feet.append((body+R@bolt).tolist());contacts.append(st['anchor'].tolist());indices.append(st['index']);betas.append(beta)
                clear.append(float(vv[:,2].min()));errors.append(float(np.linalg.norm(vv[st['index']]-st['anchor'])))
                par=k.g.PARAMETERS['legs'][l];od=np.array(k.g.fk(l,*q)['planar_pivots']['D'])-par['pivots_xy_mm']['O'];carrier.append(math.degrees(math.atan2(od[1]*math.cos(q[0]),od[0]))%360)
            cw=body+R@com;low=float((mesh@R[2]+body[2]).min())
            result.append(dict(body_position_world_mm=body.tolist(),body_rotation_euler_xyz_rad=euler.tolist(),body_orientation_world_quaternion_wxyz=quat,
                actuator_angles_rad=angles,passive_beta_rad=betas,foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_active=[True]*4,
                contact_vertex_index=indices,sole_clearance_mm=clear,stance_constraint_error_mm=errors,assumed_com_world_mm=cw.tolist(),
                support_margin_mm=k.margin([c[:2] for c in contacts],cw[:2]),body_ground_clearance_mm=low,body_contact_active=False,support_source='feet',
                body_contact_polygon_world_mm=[],part023_OD_angle_from_forward_degrees=carrier,contact_motion_model=['rolling']*4))
        return result,state

    if cfg['motion_kind']=='grounded':
        ready=neutral.copy();ready[:3]+=cfg['ready_translation_from_stand_mm'];ready[3:]=np.radians(cfg['ready_euler_degrees'])
        entry,st=grounded(neutral,ready,cfg['entry_seconds']);append(entry,'prepare_'+cfg['command'])
        for i,beat in enumerate(cfg['grounded_beats']):
            goal=ready.copy();goal[:3]+=beat['translation_from_ready_mm'];goal[3:]+=np.radians(beat['rotation_from_ready_degrees'])
            outbound,_=grounded(ready,goal,beat['seconds'],st);append(outbound,beat['name'],i)
            if beat.get('hold_seconds',0):append([outbound[-1]]*(round(beat['hold_seconds']*hz)+1),beat['name']+'_hold',i)
            append(list(reversed(outbound)),beat['name']+'_return',i)
        append(list(reversed(entry)),'return_to_standing')
    elif cfg['motion_kind']=='belly':
        cfg['geometric_research_angle_bounds_degrees']['h']=[-95.,95.]
        cfg['shoulder_bounds_basis']='Research envelope for mirrored 90-degree splay, inherited from Swim; not calibrated electrical stops or collision clearance.'
        rest=json.loads((P/'body-rest-plane.json').read_text());belly_height=rest['height_mm'];rest_pitch=rest['pitch_degrees'];rest_R,_=orientation(np.radians([0.,rest_pitch,0.]));rest_contacts=np.array(rest['contact_world_mm']);footprint=hull(rest_contacts[:,:2]);cfg['target_body_height_mm']=belly_height;cfg['target_body_pitch_degrees']=rest_pitch;cfg['body_rest_contact_world_mm']=rest_contacts.tolist();cfg.pop('bottom_contact_polygon_body_xy_mm',None)
        lowered=lower.generate(dict(target_body_height_mm=belly_height,target_body_pitch_degrees=rest_pitch,lower_seconds=cfg['lower_seconds'],hold_seconds=0.))
        max_correction=lowered['validation']['maximum_rolling_normal_correction_mm'];rolling_transfers=lowered['validation']['rolling_transfers']
        standing=copy.deepcopy(lowered['samples'])
        for r in standing:r.update(body_contact_active=False,support_source='feet',body_contact_polygon_world_mm=[],contact_motion_model=['rolling']*4)
        append(standing,'lower_onto_belly');belly=copy.deepcopy(rows[-1]);body=np.array(belly['body_position_world_mm']);support=np.column_stack([footprint+body[:2],np.zeros(len(footprint))]);margin=k.margin(footprint+body[:2],(body+rest_R@com)[:2]);q=np.array(belly['actuator_angles_rad']);folded=q.copy()
        belly.update(body_contact_active=True,support_source='rear_cover_visor_and_feet',body_contact_polygon_world_mm=support.tolist(),support_margin_mm=margin)
        rows[-1]=copy.deepcopy(belly)
        def airborne_row(q):
            row=copy.deepcopy(belly);row.update(actuator_angles_rad=q.tolist(),contact_active=[False]*4,stance_constraint_error_mm=[None]*4,support_source='rear_cover_and_visor',contact_motion_model=['airborne']*4)
            for i,l in enumerate(LEGS):
                bolt,r,beta=k.foot_pose(l,q[i],np.zeros(3));bolt=body+rest_R@bolt;vv=(k.SOLE[l]-k.F0[l])@(rest_R@r).T+bolt;idx=int(vv[:,2].argmin())
                row['foot_bolt_world_mm'][i]=bolt.tolist();row['passive_beta_rad'][i]=beta;row['contact_world_mm'][i]=vv[idx].tolist();row['contact_vertex_index'][i]=idx;row['sole_clearance_mm'][i]=float(vv[idx,2])
                par=k.g.PARAMETERS['legs'][l];od=np.array(k.g.fk(l,*q[i])['planar_pivots']['D'])-par['pivots_xy_mm']['O'];row['part023_OD_angle_from_forward_degrees'][i]=math.degrees(math.atan2(od[1]*math.cos(q[i,0]),od[0]))%360
            return row
        def segment(target,duration,name):
            nonlocal q
            start=q.copy();n=round(duration*hz);seq=[airborne_row(start)]
            for j in range(1,n+1):q=start+(target-start)*k.smooth(j/n);seq.append(airborne_row(q))
            append(seq,name);return seq
        raised=folded.copy();raised[:,0]=np.radians([90.,-90.,90.,-90.]);lift=segment(raised,cfg['lift_seconds'],'splay_shoulders_for_lying_pose')
        ready=np.radians(cfg['lying_actuator_degrees']);reach=segment(ready,cfg['reach_seconds'],'set_lying_pose')
        for i,beat in enumerate(cfg['airborne_beats']):segment(np.radians(beat['actuator_degrees']),beat['seconds'],beat['name'])
        segment(ready,cfg['reach_seconds'],'settle_lying_pose');append(list(reversed(reach)),'fold_legs_for_touchdown');append(list(reversed(lift)),'replace_all_feet')
        rows[-1]=copy.deepcopy(belly);rows[-1].update(time_s=(len(rows)-1)/hz,phase='replace_all_feet',phase_fraction=1.)
        append(list(reversed(standing)),'return_to_standing')
    else:raise ValueError(cfg['motion_kind'])
    motion_end=rows[-1]['time_s'];append([rows[-1]]*(round(cfg['standing_hold_seconds']*hz)+1),'hold_standing')
    cfg['face_cues']=[dict(time_s=0.,name=cfg['command'],mode=cfg['face_mode'],fps=cfg['face_fps']),dict(time_s=motion_end,name='stand',mode='once',fps=1)]
    angles=np.degrees([r['actuator_angles_rad'] for r in rows]);vel=np.gradient(angles,1/hz,axis=0);acc=np.gradient(vel,1/hz,axis=0)
    for j,key in enumerate(['h','alpha','theta']):
        lo,hi=cfg['geometric_research_angle_bounds_degrees'][key]
        if angles[:,:,j].min()<lo-1e-6 or angles[:,:,j].max()>hi+1e-6:raise ValueError(('angle bounds',key,float(angles[:,:,j].min()),float(angles[:,:,j].max()),lo,hi))
    minsole=min(min(r['sole_clearance_mm']) for r in rows);minbody=min(r['body_ground_clearance_mm'] for r in rows);minmargin=min(r['support_margin_mm'] for r in rows)
    if minsole< -1e-5:raise ValueError(('sole penetration',minsole))
    if minbody< -1e-5:raise ValueError(('body penetration',minbody))
    if minmargin<cfg['minimum_support_margin_mm']:raise ValueError(('support margin',minmargin))
    v=dict(duration_s=rows[-1]['time_s'],motion_end_s=motion_end,sample_hz=hz,samples=len(rows),actuator_min_degrees=angles.min(0).tolist(),actuator_max_degrees=angles.max(0).tolist(),
        actuator_peak_speed_degrees_s=np.abs(vel).max(0).tolist(),actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),maximum_adjacent_joint_step_degrees=float(abs(np.diff(angles,axis=0)).max()),
        final_joint_return_error_degrees=float(abs(angles[-1]-angles[0]).max()),minimum_support_margin_mm=minmargin,min_sole_height_mm=minsole,minimum_body_ground_clearance_mm=minbody,
        maximum_rolling_normal_correction_mm=max_correction,solved_rolling_transfers=rolling_transfers,minimum_stance_contacts=min(sum(r['contact_active']) for r in rows),
        max_stance_material_vertex_constraint_error_mm=max(e for r in rows for e in r['stance_constraint_error_mm'] if e is not None),
        complete_body_floor_check_passed=minbody>=-1e-5,body_floor_interference_retained=cfg['motion_kind']=='belly' and minbody<-1e-5,research_angle_bounds_satisfied=True,fourbar_closure='Recomputed from measured branch at every sample',collision_checked=False,measured_mass_balance_verified=False,
        hardware_servo_limits_verified=False,body_contact_strength_verified=False,hardware_qualified=False)
    return dict(metadata=dict(configuration=cfg,leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],position_units='mm',angle_units='radian',time_units='second',world_axes='X forward, Y left, Z up; CAD FL/FR physical rear, CAD RL/RR physical front',source_geometry=k.g.PARAMETERS['source_blend']),phases=phases,samples=rows,validation=v)

def write(command):
    cfg=json.loads((P/'config.json').read_text());assert cfg['command']==command
    data=generate(cfg)
    for name,value in [('source.json',data),('config.json',data['metadata']['configuration']),('validation.json',data['validation'])]:(P/name).write_text(json.dumps(value,indent=None if name=='source.json' else 2)+'\n')
    print(json.dumps(dict(command=command,**data['validation']),indent=2),flush=True)
