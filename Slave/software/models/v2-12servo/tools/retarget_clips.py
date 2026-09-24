"""Rebuild the finite motion library from preserved choreography and current geometry.

Uses measured current sole/body hulls and the retained desktop geometry model. The legacy research packages supply timing and semantic motion targets,
never current servo angles. NumPy/SciPy are offline tools only.
"""
from __future__ import annotations
import argparse,copy,hashlib,importlib.util,json,math,time
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation

LEGS=['FL','FR','RL','RR']
SOURCE_ORDER=[2,3,0,1]
BODY_SUPPORTED={'swim','cute','celebrate','surprised'}
SHORTER_REACH=BODY_SUPPORTED|{'bow','stretch','point','wave'}
SEARCH_BOUNDS=np.deg2rad([[-150,150],[-145,145],[-180,180]])

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def load_reference(root):
    spec=importlib.util.spec_from_file_location('ainekio_reference',root/'motions/walk/reference.py')
    ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref);return ref

def support_margin(points,com):
    if len(points)<3:return None
    try:poly=np.array(points)[ConvexHull(np.array(points)[:,:2]).vertices,:2]
    except Exception:return None
    d=np.roll(poly,-1,axis=0)-poly
    return float(np.min((d[:,0]*(com[1]-poly[:,1])-d[:,1]*(com[0]-poly[:,0]))/np.linalg.norm(d,axis=1)))

def target_rows(source,cfg,command,ref):
    """Adapt full-body targets; step to a wide support stance before lying down."""
    rows=source['samples'];first=rows[0];neutral=np.array(cfg['reference_stance_xy_mm'])[SOURCE_ORDER]
    oldfeet=np.array(first['foot_bolt_world_mm']);scale=np.array([(neutral[2,0]-neutral[0,0])/(oldfeet[2,0]-oldfeet[0,0]),neutral[0,1]/oldfeet[0,1]])
    shift=neutral.mean(0)-(oldfeet[:,:2]*scale).mean(0);pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    hull=np.array(cfg['current_body_hull_local_mm']);clearance=float(hull[:,2].min()+cfg['body_translation_z_mm'])
    oldclear=first.get('body_ground_clearance_mm');wide=command in BODY_SUPPORTED
    if wide:
        lower_end=source['phases'][0]['end'];prep=min(1.,lower_end*.6)
        recovery=next(p for p in source['phases'] if p['kind'] in ['return_to_standing','demonstration_recovery_stand'])
        recover_prep=min(1.,(recovery['end']-recovery['start'])*.6)
    for original in rows:
        t=original['time_s'];row=original;mapped=t
        if wide:
            if t<lower_end:mapped=lower_end*max(0.,t-prep)/(lower_end-prep)
            if recovery['start']<=t<=recovery['end']:
                mapped=min(recovery['end'],recovery['start']+(t-recovery['start'])*(recovery['end']-recovery['start'])/(recovery['end']-recovery['start']-recover_prep))
            index=min(int(mapped*120),len(rows)-2);u=mapped*120-index;row=copy.copy(rows[index])
            for key in ['body_position_world_mm','body_rotation_euler_xyz_rad','foot_bolt_world_mm','sole_clearance_mm','actuator_angles_rad','body_ground_clearance_mm']:
                if key in row:row[key]=((1-u)*np.array(rows[index][key])+u*np.array(rows[index+1][key])).tolist()
        e=np.array(row.get('body_rotation_euler_xyz_rad',[0,0,row.get('body_yaw_world_rad',0)]),dtype=float)
        if wide:
            depth=np.clip(1-row['body_ground_clearance_mm']/oldclear,0,1);w=ref.smooth(depth)
            e=e*(1-w)+np.array(cfg['body_rest_euler_xyz_rad'])*w
        B=Rotation.from_euler('xyz',e).as_matrix();floor=float(((hull-pivot)@B[2]+pivot[2]).min())
        oldbody=np.array(row['body_position_world_mm'])
        body=np.array([*(oldbody[:2]*scale+shift-B[:2,:2]@shift),cfg['body_translation_z_mm']+.865*(oldbody[2]-first['body_position_world_mm'][2])])
        if oldclear and 'body_ground_clearance_mm' in row:body[2]=max(0.,row['body_ground_clearance_mm'])/oldclear*clearance-floor
        feet=np.array(row['foot_bolt_world_mm'])[:,:2]*scale+shift
        if command in SHORTER_REACH:feet=neutral+.65*(feet-neutral)
        lift_scale=.60 if command=='surprised' else .65 if wide else .70 if command in SHORTER_REACH else .92
        z=np.maximum(0,np.array(row['sole_clearance_mm']))*lift_scale
        grounded=np.array(row['contact_active'],dtype=bool);phase=original['phase']
        if wide:
            for i in range(4):
                enter=np.clip((t-i*prep/4)/(prep/4),0,1)
                leave=np.clip((t-(recovery['end']-recover_prep)-i*recover_prep/4)/(recover_prep/4),0,1)
                feet[i,1]+=np.sign(neutral[i,1])*35*(ref.smooth(enter)-ref.smooth(leave))
                if 0<enter<1:z[i]=6*ref.bump(enter);grounded[i]=False;phase='place_feet_for_body_support'
                if 0<leave<1:z[i]=6*ref.bump(leave);grounded[i]=False;phase='restore_standing_footprint'
        # Every recorded standing hold uses the exact common walking stance.
        if (np.max(np.abs(row['actuator_angles_rad']))<1e-6 and np.max(np.abs(e))<1e-7
            and np.linalg.norm(oldbody-np.array(first['body_position_world_mm']))<1e-5
            and (not wide or t==0 or t>=recovery['end'])):
            body=np.array([0.,0.,cfg['body_translation_z_mm']]);feet=neutral.copy();z[:]=0.;grounded[:]=True
        yield dict(time_s=t,phase=phase,body=body,euler=e,feet=feet,z=z,grounded=grounded,original=original)

def grounded_posture_targets(targets,cfg,posture,mechanism,ref):
    """Lay the configured boot surfaces along the floor in the final hold."""
    from scipy.optimize import least_squares
    targets=list(targets);grounded_legs=posture['grounded_legs'];first=targets[0]
    end_body=targets[-1]['body'].copy();end_body[2]+=posture['body_lift_mm']
    mechanism.body_euler=targets[-1]['euler'];end_xy={}
    for leg in grounded_legs:
        axis=np.array(posture['knee_to_ankle_local_unit'][leg])
        def residual(q):
            try:
                R,_=mechanism.pose(leg,q,end_body);direction=R@axis
                return [50*(direction[2]-math.sin(math.radians(posture['lower_leg_angle_above_floor_deg']))),50*direction[1],mechanism.vertices(leg,q,end_body)[:,2].min()]
            except ValueError:return [999.,999.,999.]
        fit=least_squares(residual,posture['terminal_solver_seed_rad'][leg],
            bounds=(SEARCH_BOUNDS[:,0],SEARCH_BOUNDS[:,1]),xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=120)
        assert np.linalg.norm(fit.fun)<.001,(leg,fit.fun)
        assert (mechanism.pose(leg,fit.x,end_body)[0]@axis)[0]>.99
        end_xy[leg]=mechanism.reference(leg,fit.x,end_body)[:2]
    start_xy=first['feet'].copy()
    for target in targets:
        t=target['time_s'];target['body'][2]+=posture['body_lift_mm']*ref.smooth(min(1.,t/posture['lowering_seconds']))
        for j,leg in enumerate(grounded_legs):
            i=LEGS.index(leg);u=np.clip((t-posture['step_start_seconds'][j])/posture['step_duration_seconds'],0,1)
            target['feet'][i]=start_xy[i]+ref.smooth(u)*(end_xy[leg]-start_xy[i]);target['z'][i]=posture['step_lift_mm']*ref.bump(u)
            target['grounded'][i]=not 0<u<1
        yield target

def seated_wave_targets(targets,posture,folder,mechanism,ref):
    """Replay Sit exactly; only the front-left leg moves during the wave."""
    base=posture['base_motion'];path=folder/base['source_file']
    assert digest(path)==base['source_sha256']
    sit=json.loads(path.read_text());rows=sit['samples'];timing=posture['timing_s']
    assert sit['metadata']['configuration']['sample_hz']==120
    assert abs(sit['phases'][0]['end']-timing['sit_end'])<1e-9
    held=rows[round(timing['sit_end']*120)];arm=LEGS.index(posture['waving_leg'])
    lift=np.deg2rad(posture['lift_joint_offsets_deg']);extended=np.deg2rad(posture['extended_joint_offsets_deg'])
    def blend(a,b,t,start,end):return a+(b-a)*ref.smooth(np.clip((t-start)/(end-start),0.,1.))
    for target in targets:
        t=target['time_s']
        if t<=timing['sit_end']:
            row=rows[round(t*120)]
        elif t>=timing['foot_replacement_end']:
            back=np.clip(timing['stand_end']-t,0.,timing['sit_end']);row=rows[round(back*120)]
        else:row=held
        target['body']=np.array(row['body_translation_world_mm']);target['euler']=np.array(row['body_rotation_euler_xyz_rad'])
        target['feet']=np.array(row['target_foot_reference_xy_mm']);target['z']=np.array(row['target_sole_clearance_mm']);target['grounded']=np.array(row['contact_active'])
        q=np.array(row['actuator_angles_rad']);seated=np.array(held['actuator_angles_rad'][arm])
        if timing['sit_end']<t<timing['foot_replacement_end']:
            if t<=timing['lift_end']:q[arm]=blend(seated,lift,t,timing['sit_end'],timing['lift_end'])
            elif t<=timing['extension_end']:q[arm]=blend(lift,extended,t,timing['lift_end'],timing['extension_end'])
            elif t<=timing['wave_end']:
                q[arm]=extended;duration=timing['wave_end']-timing['extension_end'];elapsed=t-timing['extension_end'];edge=posture['wave_envelope_seconds']
                envelope=ref.smooth(min(1.,elapsed/edge))*ref.smooth(min(1.,(duration-elapsed)/edge))
                q[arm,0]-=math.radians(posture['shoulder_wave_amplitude_deg'])*envelope*math.sin(2*math.pi*posture['wave_cycles']*elapsed/duration)
            elif t<=timing['retraction_end']:q[arm]=blend(extended,lift,t,timing['wave_end'],timing['retraction_end'])
            else:q[arm]=blend(lift,seated,t,timing['retraction_end'],timing['foot_replacement_end'])
            mechanism.body_euler=target['euler'];leg=posture['waving_leg']
            target['feet'][arm]=mechanism.reference(leg,q[arm],target['body'])[:2]
            target['z'][arm]=mechanism.vertices(leg,q[arm],target['body'])[:,2].min();target['grounded'][arm]=False
        target['joint_targets']=q[SOURCE_ORDER].copy()
        yield target

def extended_point_targets(targets,posture,mechanism,ref):
    """Route the crank around the unreachable region before fully pointing."""
    from scipy.interpolate import CubicSpline
    targets=list(targets);timing=posture['timing_s'];leg=posture['pointing_leg'];arm=LEGS.index(leg)
    lift=targets[round(timing['lift_end']*120)];mechanism.body_euler=lift['euler']
    waypoints=np.array(posture['extension_waypoints_rad']);waypoints[0],_=mechanism.solve(leg,lift['body'],waypoints[0],lift['feet'][arm],lift['z'][arm])
    spline=CubicSpline(posture['extension_waypoint_fractions'],waypoints,bc_type='clamped')
    for target in targets:
        t=target['time_s']
        if timing['lift_end']<=t<=timing['retraction_end']:
            if t<timing['extension_end']:u=(t-timing['lift_end'])/(timing['extension_end']-timing['lift_end'])
            elif t<=timing['hold_end']:u=1.
            else:u=1.-(t-timing['hold_end'])/(timing['retraction_end']-timing['hold_end'])
            q=spline(ref.smooth(np.clip(u,0.,1.)));mechanism.body_euler=target['euler']
            target['feet'][arm]=mechanism.reference(leg,q,target['body'])[:2]
            target['z'][arm]=mechanism.vertices(leg,q,target['body'])[:,2].min();target['grounded'][arm]=False
            target['joint_overrides']={ref.LEGS.index(leg):q}
        yield target

def bind_sources(root,source_repo):
    path=root/'motions/retargeting.json'
    if path.exists():return json.loads(path.read_text())
    records=[]
    for family in ['turns','gestures']:
        catalog=json.loads((root/'motions'/family/'catalog.json').read_text())
        for entry in catalog['commands']:
            command=entry['command'];folder=root/'motions'/family/entry['path']
            handoff=entry.get('handoff',f'docs/gait-research/turn-commands-20260915/commands/{command}')
            for name in ['source.json','manifest.json','schema.json']:
                assert digest(folder/name)==digest(source_repo/handoff/name),(command,name,'legacy snapshot drift')
            records.append(dict(command=command,family=family,path=entry['path'],legacy_handoff=handoff,
                legacy_source_sha256=digest(folder/'source.json'),execution_handoff=entry.get('execution_handoff')))
    result=dict(schema='ainekio.current-geometry-retarget.v1',geometry_id=json.loads((root/'geometry.json').read_text())['geometry_id'],
        coordinate_policy='Preserve world contact choreography, phase timing, headings and semantic completion; solve all twelve joints on current geometry.',
        finite_motion_solver_search_bounds_deg=np.rad2deg(SEARCH_BOUNDS).tolist(),
        bounds_scope='Numerical branch-search envelope only. Not mechanical or electrical travel limits.',
        shorter_reach_commands=sorted(SHORTER_REACH),reach_displacement_scale=.65,
        body_support=dict(commands=sorted(BODY_SUPPORTED),lateral_preparation_mm=35,preparation_lift_mm=6,
            policy='Sequential foot placements inside lowering and standing phases; measured stable shell support plane while feet are airborne.'),
        hardware_qualified=False,commands=records)
    write(path,result);return result

def forward_bow_targets(targets,posture,mechanism,ref):
    """Reach both hands forward with grounded soles, then reverse into standing."""
    targets=list(targets);timing=posture['timing_s'];brace=targets[round(timing['brace_end']*120)]
    mechanism.body_euler=brace['euler'];starts={}
    for leg in posture['front_legs']:
        i=LEGS.index(leg)
        starts[leg],_=mechanism.solve(leg,brace['body'],posture['brace_solver_seed_rad'][leg],brace['feet'][i],brace['z'][i])
    for target in targets:
        t=target['time_s']
        if timing['brace_end']<t<timing['retraction_end']:
            if t<timing['extension_end']:u=(t-timing['brace_end'])/(timing['extension_end']-timing['brace_end'])
            elif t<=timing['hold_end']:u=1.
            else:u=1.-(t-timing['hold_end'])/(timing['retraction_end']-timing['hold_end'])
            w=ref.smooth(np.clip(u,0.,1.));front={l:starts[l]+(np.array(posture['extended_joint_offsets_rad'][l])-starts[l])*w for l in posture['front_legs']}
            target['euler']=brace['euler']+(np.array(posture['held_body_euler_xyz_rad'])-brace['euler'])*w
            target['body']=brace['body'].copy();target['body'][0]+=(posture['held_body_x_mm']-brace['body'][0])*w
            mechanism.body_euler=target['euler'];target['body'][2]=0.
            target['body'][2]=-min(mechanism.vertices(l,q,target['body'])[:,2].min() for l,q in front.items())
            target['feet']=brace['feet'].copy();target['z']=brace['z'].copy();target['grounded'][:]=True
            target['joint_overrides']={}
            for leg,q in front.items():
                i=LEGS.index(leg);target['joint_overrides'][ref.LEGS.index(leg)]=q
                target['feet'][i]=mechanism.reference(leg,q,target['body'])[:2]
                target['z'][i]=mechanism.vertices(leg,q,target['body'])[:,2].min()
        yield target

def trim_nod_cycles(source, manifest, contract, repetitions):
    """Keep complete nod cycles, then rejoin the original standing recovery."""
    cycles=[p for p in source['phases'] if p.get('cycle',-1)>=0]
    total=1+max(p['cycle'] for p in cycles)
    if type(repetitions) is not int or not 1<=repetitions<=total:
        raise ValueError('Nod repetitions must fit the recorded complete cycles')
    cut_start=max(p['end'] for p in cycles if p['cycle']<repetitions)
    cut_end=max(p['end'] for p in cycles);removed=cut_end-cut_start
    hz=manifest['source_sample_hz']
    source['samples']=[r for r in source['samples'] if not cut_start<r['time_s']<=cut_end]
    for i,row in enumerate(source['samples']):row['time_s']=i/hz
    source['phases']=[p for p in source['phases'] if p.get('cycle',-1)<repetitions]
    for phase in source['phases']:
        if phase['start']>=cut_end:
            phase['start']-=removed;phase['end']-=removed
    kept_names={p['kind'] for p in source['phases']}
    contract['phases']=[p for p in contract['phases'] if p['name'] in kept_names]
    for phase in contract['phases']:
        if phase['source_interval_s'][0]>=cut_end:
            phase['source_interval_s']=[t-removed for t in phase['source_interval_s']]
            phase['source_sample_indices_inclusive']=[round(t*hz) for t in phase['source_interval_s']]
    ids={p['id'] for p in contract['phases']}
    for profile in contract['timing_profiles'].values():
        profile['duration_s']={k:v for k,v in profile['duration_s'].items() if k in ids}
    manifest['duration_seconds']-=removed;manifest['motion_end_seconds']-=removed
    manifest['sample_count']=len(source['samples'])
    manifest['completion']=f"Complete {repetitions} nods, retrace the rear-right support crouch, and hold exact standing neutral."
    contract['completion']['behavior']=manifest['completion']
    for owner in [manifest,contract]:
        for cue in owner['face_cues']:
            if cue['time_s']>=cut_end:cue['time_s']-=removed
    manifest.pop('source_validation',None)

def retarget(root,source_repo,only=None):
    from import_reviewed_clips import import_clips
    import_clips(root, only)
    cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);settings=bind_sources(root,source_repo)
    pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm']);bodyhull=np.array(cfg['current_body_hull_local_mm'])
    geometry_hash=digest(root/'geometry.json');sole_hash=digest(root/'motions/turns/sole-hulls.npz')
    catalogues={f:json.loads((root/'motions'/f/'catalog.json').read_text()) for f in ['turns','gestures']}
    reports=[]
    for record in settings['commands']:
        name=record['command'];family=record['family']
        if only and name not in only:continue
        start=time.perf_counter();old=source_repo/record['legacy_handoff'];folder=root/'motions'/family/record['path']
        assert digest(old/'source.json')==record['legacy_source_sha256']
        source=json.loads((old/'source.json').read_text());manifest=json.loads((old/'manifest.json').read_text());schema=json.loads((old/'schema.json').read_text())
        contract=json.loads((source_repo/record['execution_handoff']).read_text()) if family=='gestures' else None
        if name=='nod':trim_nod_cycles(source,manifest,contract,record['repetitions'])
        posture_path=folder/'posture.json';posture=json.loads(posture_path.read_text()) if name in {'sit','rest','wave','point','bow'} and posture_path.exists() else None
        if name=='wave' and posture:
            base=posture['base_motion'];base_posture=json.loads((folder/base['posture_file']).read_text());base_manifest=json.loads((folder/'../sit/manifest.json').read_text())
            assert base_manifest['source_sha256']==digest(folder/base['source_file']) and base_manifest['geometry_sha256']==geometry_hash
            assert base_manifest['posture_sha256']==digest(folder/base['posture_file'])
            assert digest(folder/posture['contact_hulls_file'])==base_posture['contact_hulls_sha256']
            base['source_sha256']=digest(folder/base['source_file']);base['posture_sha256']=digest(folder/base['posture_file'])
            posture['contact_hulls_sha256']=base_posture['contact_hulls_sha256'];write(posture_path,posture)
        current=copy.deepcopy(cfg)
        if posture:
            assert posture['mechanism_geometry_sha256']==geometry_hash
            assert digest(folder/posture['contact_hulls_file'])==posture['contact_hulls_sha256']
            hulls=np.load(folder/posture['contact_hulls_file'])
            for leg in ref.LEGS:current['legs'][leg]['sole_hull_local_mm']=hulls['sole_'+leg].tolist()
            bodyhull=hulls['body']
        else:bodyhull=np.array(cfg['current_body_hull_local_mm'])
        current['research_angle_bounds_deg']=np.rad2deg(SEARCH_BOUNDS).tolist();mechanism=ref.Mechanism(current)
        neutral=np.array(cfg['reference_stance_xy_mm']);standing_mechanism=ref.Mechanism(cfg);q=np.array([standing_mechanism.solve(l,[0,0,-2],[0,0,0],neutral[i])[0] for i,l in enumerate(ref.LEGS)])
        output=[];worst=0.;closure=1e9;minimum_body=1e9;minimum_margin=1e9
        targets=target_rows(source,cfg,name,ref)
        if name=='wave' and posture:targets=seated_wave_targets(targets,posture,folder,mechanism,ref)
        elif name=='point' and posture:targets=extended_point_targets(targets,posture,mechanism,ref)
        elif name=='bow' and posture:targets=forward_bow_targets(targets,posture,mechanism,ref)
        elif posture:targets=grounded_posture_targets(targets,cfg,posture,mechanism,ref)
        for target in targets:
            body=target['body'];e=target['euler'];desired=np.column_stack((target['feet'],target['z']))[SOURCE_ORDER].copy()
            if 'joint_targets' in target:q=target['joint_targets']
            elif posture:
                mechanism.body_euler=e
                if target['time_s']>0:
                    for i,l in enumerate(ref.LEGS):
                        if i in target.get('joint_overrides',{}):q[i]=target['joint_overrides'][i]
                        else:q[i],_=mechanism.solve(l,body,q[i],desired[i,:2],desired[i,2])
            else:
                mechanism.body_euler=e
                for i,l in enumerate(ref.LEGS):q[i],_=mechanism.solve(l,body,q[i],desired[i,:2],desired[i,2])
            mechanism.body_euler=e;feet=[];contacts=[];sole=[];indices=[];betas=[]
            for l,j in zip(LEGS,SOURCE_ORDER):
                R,T=mechanism.pose(l,q[j],body);v=mechanism.hulls[l]@R.T+T;k=int(v[:,2].argmin());point=mechanism.reference(l,q[j],body)
                feet.append(point.tolist());contacts.append(v[k].tolist());sole.append(float(v[k,2]));indices.append(k);betas.append(float(mechanism.planar(q[j])[3]-mechanism.b0));closure=min(closure,mechanism.planar(q[j])[4])
            actual=np.column_stack((np.array(feet)[:,:2],sole));worst=max(worst,float(np.max(np.abs(actual-np.column_stack((target['feet'],target['z']))))))
            B=Rotation.from_euler('xyz',e);worldbody=(bodyhull-pivot)@B.as_matrix().T+pivot+body;clear=float(worldbody[:,2].min());minimum_body=min(minimum_body,clear)
            body_support=worldbody[worldbody[:,2]<.031] if clear<.001 else np.empty((0,3))
            supporting=[p for p,on in zip(contacts,target['grounded']) if on]+body_support.tolist()
            com=body+pivot;balance=support_margin(supporting,com)
            if balance is not None:minimum_margin=min(minimum_margin,balance)
            original=target['original']
            output.append(dict(time_s=target['time_s'],phase=target['phase'],phase_fraction=original.get('phase_fraction',0.),
                body_translation_world_mm=body.tolist(),body_position_world_mm=(body+pivot).tolist(),body_rotation_euler_xyz_rad=e.tolist(),
                body_orientation_world_quaternion_wxyz=B.as_quat(scalar_first=True).tolist(),body_yaw_world_rad=float(e[2]),
                actuator_angles_rad=q[SOURCE_ORDER].tolist(),passive_beta_rad=betas,foot_bolt_world_mm=feet,contact_world_mm=contacts,
                contact_vertex_index=indices,contact_active=target['grounded'].tolist(),sole_clearance_mm=sole,
                body_ground_clearance_mm=clear,body_contact_active=bool(len(body_support)),body_contact_polygon_world_mm=body_support.tolist(),
                support_source='body_and_feet' if len(body_support) and any(target['grounded']) else 'body' if len(body_support) else 'feet',
                assumed_com_world_mm=com.tolist(),support_margin_mm=balance,
                target_foot_reference_xy_mm=target['feet'].tolist(),target_sole_clearance_mm=target['z'].tolist()))
        angles=np.array([r['actuator_angles_rad'] for r in output]);dt=1/120.;velocity=np.gradient(angles,dt,axis=0);acceleration=np.gradient(velocity,dt,axis=0)
        report=dict(command=name,geometry_id=cfg['geometry_id'],samples=len(output),duration_s=output[-1]['time_s'],sample_hz=120,
            max_target_error_mm=worst,min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in output),minimum_body_ground_clearance_mm=minimum_body,
            minimum_closure_triangle_height_mm=float(closure),minimum_assumed_support_margin_mm=minimum_margin,
            actuator_min_degrees=np.rad2deg(angles.min(0)).tolist(),actuator_max_degrees=np.rad2deg(angles.max(0)).tolist(),
            maximum_adjacent_joint_step_degrees=float(np.rad2deg(abs(np.diff(angles,axis=0))).max()),
            peak_joint_speed_deg_s=float(np.rad2deg(abs(velocity)).max()),peak_joint_acceleration_deg_s2=float(np.rad2deg(abs(acceleration)).max()),
            seconds=time.perf_counter()-start,hardware_qualified=False,collision_checked=False,
            validation_scope='Current measured linkage, sole and body hulls. Assumed COM, unmeasured load, friction and electrical limits.')
        assert worst<.02 and report['min_sole_height_mm']>-.02 and minimum_body>-.02,report
        assert report['maximum_adjacent_joint_step_degrees']<12,report
        if posture:
            pose_row=output[round(posture.get('posture_sample_time_s',output[-1]['time_s'])*120)];mechanism.body_euler=pose_row['body_rotation_euler_xyz_rad']
            report['lower_leg_angle_above_floor_deg']={leg:float(np.rad2deg(np.arcsin(np.clip((mechanism.pose(leg,pose_row['actuator_angles_rad'][LEGS.index(leg)],pose_row['body_translation_world_mm'])[0]@posture['knee_to_ankle_local_unit'][leg])[2],-1,1)))) for leg in posture['grounded_legs']}
            report['posture_hulls_sha256']=posture['contact_hulls_sha256']
            report['body_support_scope']=posture['body_support_scope']
            if name=='bow':
                report['front_hand_forward_travel_mm']={leg:pose_row['foot_bolt_world_mm'][LEGS.index(leg)][0]-output[0]['foot_bolt_world_mm'][LEGS.index(leg)][0] for leg in posture['front_legs']}
                assert min(report['front_hand_forward_travel_mm'].values())>60
            if name=='point':
                leg=posture['pointing_leg'];aq=np.array(pose_row['actuator_angles_rad'][LEGS.index(leg)]);D,_,_,_,_=mechanism.planar(aq)
                S=np.array(cfg['legs'][leg]['shoulder_world']);M=np.array(cfg['legs'][leg]['mechanism_local']);B=Rotation.from_euler('xyz',pose_row['body_rotation_euler_xyz_rad']).as_matrix()
                R0=B@S[:3,:3]@ref.rx(aq[0])@M[:3,:3];upper=R0@np.array([D[0]-mechanism.O[0],0,D[1]-mechanism.O[1]])
                ankle=np.array(posture['ankle_local_mm']);ankle[1]=0;lower=mechanism.pose(leg,aq,pose_row['body_translation_world_mm'])[0]@ankle
                extension=upper+lower;report['full_forward_extension_mm']=float(extension[0]);report['pointing_endpoint_lateral_vertical_error_mm']=float(np.linalg.norm(extension[1:]))
                assert abs(extension[0]-posture['full_modeled_extension_mm'])<.001 and np.linalg.norm(extension[1:])<.001,(extension,aq,pose_row['body_rotation_euler_xyz_rad'],upper,lower)

        report['motion_end_s']=manifest.get('source_validation',{}).get('motion_end_s',manifest.get('motion_end_seconds',output[-1]['time_s']))
        configuration=dict(command=name,sample_hz=120,geometry_id=cfg['geometry_id'],retargeting='../../retargeting.json',
            preview_fps=30,geometric_solver_search_bounds_degrees=np.rad2deg(SEARCH_BOUNDS).tolist(),hardware_qualified=False)
        if name=='nod':configuration['repetitions']=record['repetitions'];report['repetitions']=record['repetitions']
        metadata=dict(configuration=configuration,leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],angle_units='radian',position_units='mm',time_units='second',
            body_position_datum='Current geometry rotation pivot; body_translation_world_mm is the model translation offset.',
            contact_model='Current complete sole hull minimum Z; preserved contact choreography and explicit sequential stance preparation for body support.',
            legacy_source=dict(path=record['legacy_handoff']+'/source.json',sha256=record['legacy_source_sha256']))
        result=dict(metadata=metadata,phases=source['phases'],samples=output,validation=report)
        (folder/'source.json').write_text(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n')
        if posture:configuration['posture_file']='posture.json'
        write(folder/'config.json',configuration);write(folder/'validation.json',report)
        for key in ['csv_sha256','body_samples_sha256','blender_workspace_file','blender_file','blender_frames','blender_in_source_archive','source_validation','interpolation_validation']:
            manifest.pop(key,None)
        manifest.update(gait_id=name+'_upright_24_38_20260921',geometry_id=cfg['geometry_id'],generated_utc='2026-09-21',source_sha256=digest(folder/'source.json'),geometry_sha256=geometry_hash,sole_hulls_sha256=sole_hash,
            entry_pose='Common current-geometry standing pose; calibrated arbitrary-pose entry remains unimplemented.',entry_actuator_angles_rad=output[0]['actuator_angles_rad'],
            source_validation=report,contact_model=metadata['contact_model'],retargeted_from=metadata['legacy_source'],hardware_qualified=False,
            blender_workspace_file='Slave/hardware/v2-12servo/ainekio-variable-gait.blend',blender_scene='Motions - Current Geometry')
        semantic=manifest.get('semantic_end_seconds',manifest['duration_seconds']);final=output[round(semantic*120)]
        if 'semantic_end_seconds' in manifest:
            manifest['semantic_final_actuator_angles_rad']=final['actuator_angles_rad'];manifest['playlist_final_actuator_angles_rad']=output[-1]['actuator_angles_rad']
        else:manifest['final_actuator_angles_rad']=final['actuator_angles_rad']
        if posture:
            manifest.update(posture_sha256=digest(posture_path),posture_hulls_sha256=posture['contact_hulls_sha256'],generated_utc='2026-09-22',blender_workspace_file=posture['measured_blender_file'],retargeting_notes=posture['description'])
        manifest['body_target']=dict(position_mm=final['body_position_world_mm'],euler_xyz_rad=final['body_rotation_euler_xyz_rad'])
        manifest.pop('design',None)
        manifest['choreography_source']=record['legacy_handoff']+'/manifest.json'
        if not posture:manifest['retargeting_notes']='Current full-body and sole targets are solved against root geometry.json; geometry-dependent legacy prose remains only in the historical package.'
        if name=='nod':manifest.update(generated_utc='2026-09-22',blender_workspace_file='Slave/hardware/v2-12servo/ainekio-variable-gait-Recovery.blend',retargeting_notes=f"{record['repetitions']} complete nod cycles; original nod speed, amplitude, support entry and standing recovery preserved.")
        write(folder/'manifest.json',manifest)
        if posture:
            schema[name+'_posture']=posture['description'];schema['body_support_scope']=posture['body_support_scope']
        schema.pop('columns',None)
        for key in ['shoulder_behavior','actuator_zero','positive_axes']:schema.pop(key,None)
        schema['joint_conventions']=cfg['joint_conventions'];schema['com']={'mode':'assumed','body_reference_mm':cfg['provisional_COM_body_mm'],'measured_mass_kg':None}
        schema.update(geometry_id=cfg['geometry_id'],joint_zero='Current root geometry CAD offsets; standing is the solved entry pose.',
            contact_model=metadata['contact_model'],sample_fields=list(output[0]),body_position_datum=metadata['body_position_datum'])
        write(folder/'schema.json',schema)
        write(folder/'blender-validation.json',dict(status='pending_current_scene_verification',geometry_id=cfg['geometry_id'],command=name,legacy_report_replaced=True))
        entry=next(e for e in catalogues[family]['commands'] if e['command']==name)
        if family=='gestures':
            contract['gait_id']=manifest['gait_id'];contract['entry']['joint_angles_rad']=output[0]['actuator_angles_rad'];contract['completion']['joint_angles_rad']=final['actuator_angles_rad'];contract['completion']['contacts']=final['contact_active']
            contract['contact_events']=[]
            for index,row in enumerate(output):
                event={'source_time_s':row['time_s'],'sample_index':index,'active':row['contact_active'],'body_contact_active':row['body_contact_active'],'support_source':row['support_source']}
                previous=contract['contact_events'][-1] if contract['contact_events'] else None
                if previous is None or any(previous[key]!=event[key] for key in ['active','body_contact_active','support_source']):contract['contact_events'].append(event)
            contract['geometry_id']=cfg['geometry_id'];contract['source_qualification']={'hardware_qualified':False,'collision_checked':False,'measured_mass_balance_verified':False,'source_acceleration_continuous':False,'minimum_assumed_support_margin_mm':minimum_margin}
            owner='Slave/software/models/v2-12servo/motions/gestures/'+name;entry['legacy_handoff']=record['legacy_handoff'];entry['handoff']=owner;entry['execution_handoff']=owner+'/execution-contract.json'
            contract['source_files']=[{'path':owner+'/'+key,'sha256':digest(folder/key)} for key in ['source.json','manifest.json']]
            for p in contract['phases']:
                if posture and p['source_interval_s'][0]==0:p['current_geometry_note']='Replays the canonical corrected Sit lowering exactly.' if name=='wave' else 'Preserves the support preload before full forward pointing.' if name=='point' else 'Braces before the two front hands extend forward into a held bow.' if name=='bow' else 'Includes sequential foot placements before the grounded lower-leg hold.'
                if name in BODY_SUPPORTED and p['source_interval_s'][0]==0:p['current_geometry_note']='Includes sequential wide-stance preparation before lowering.'
            write(folder/'execution-contract.json',contract)
            entry['sha256']={key:digest(folder/key) for key in entry['sha256'] if (folder/key).exists()}
        else:
            entry['source_sha256']=digest(folder/'source.json');entry['minimum_support_margin_mm']=minimum_margin
        reports.append(report);print(json.dumps({'command':name,'samples':len(output),'seconds':round(report['seconds'],2),'max_error_mm':worst,'max_step_deg':report['maximum_adjacent_joint_step_degrees']}),flush=True)
    for family,catalog in catalogues.items():catalog['geometry_id']=cfg['geometry_id'];write(root/'motions'/family/'catalog.json',catalog)
    aggregate=root/'motions/retarget-validation.json'
    if only and aggregate.exists():
        previous=json.loads(aggregate.read_text())['commands'];updated={r['command']:r for r in reports};reports=[updated.get(r['command'],r) for r in previous]
    write(aggregate,dict(geometry_id=cfg['geometry_id'],commands=reports,hardware_qualified=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--source-repo',type=Path,required=True);parser.add_argument('--commands',nargs='*')
    args=parser.parse_args();retarget(args.root,args.source_repo,args.commands)
