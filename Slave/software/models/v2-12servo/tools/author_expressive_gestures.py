"""Author quick Point, deep Pushup and held Bow for the installed bare legs.

The retained baseline archive supplies Point/Bow choreography. Pushup is solved
from planted foot anchors and body poses. No runtime or calibration policy changes.
"""
import argparse
import copy
import gzip
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.spatial.transform import Rotation

from retarget_clips import LEGS, digest, load_reference, write
from remap_reviewed_clips import refresh_metrics


def read(path):
    return json.loads(path.read_text())


def compact(path, value):
    path.write_text(json.dumps(value, separators=(',', ':'), allow_nan=False)+'\n')


def finish(root, name, source, rows, phases, description, hulls, calibration, baseline,
           generator="tools/author_expressive_gestures.py"):
    """Bind the authored samples, geometry evidence and playback contract together."""
    family = root/'motions/gestures'; folder = family/name
    cfg = read(root/'geometry.json'); contact = root/'motions/locomotion/walk-contact.json'
    np.savez_compressed(folder/'contact-hulls.npz', **hulls)
    posture = read(folder/'posture.json') if (folder/'posture.json').exists() else {}
    # Previous fit claims and pose keys describe the archived source, not this fit.
    for key in ['linkage_remap', 'calibrated_motion_revision', 'extension_waypoints_rad',
                'extension_waypoint_fractions', 'brace_solver_seed_rad', 'timing_s',
                'measured_blender_file', 'measured_date']:
        posture.pop(key, None)
    posture.update(schema=f'ainekio.{name}.expressive-bare.v1', description=description,
        mechanism_geometry_sha256=digest(root/'geometry.json'),
        contact_hulls_file='contact-hulls.npz', contact_hulls_sha256=digest(folder/'contact-hulls.npz'),
        body_support_scope='Complete body hull; bare Part027 contact.',
        bare_contact_source_sha256=digest(contact),
        phases=[dict(p) for p in phases],
        baseline_source_archive_sha256=digest(baseline))
    if name in ('point', 'bow'):
        held = next(r for r in rows if r['phase']=='hold_'+name)
        posture['posture_sample_time_s'] = held['time_s']
        if name=='point':
            posture['extended_joint_offsets_rad'] = held['actuator_angles_rad'][2]
            posture['extension_interpolation'] = 'Authored joint path with bare-contact lift/replacement joins.'
        else:
            posture['extended_joint_offsets_rad'] = {l: held['actuator_angles_rad'][i] for i,l in enumerate(LEGS) if i>=2}
            posture['held_body_x_mm'] = held['body_translation_world_mm'][0]
            posture['held_body_euler_xyz_rad'] = held['body_rotation_euler_xyz_rad']
    write(folder/'posture.json', posture)
    metadata = source['metadata']
    for key in ['linkage_remap', 'calibrated_motion_revision', 'baseline_validation',
                'authoring_source', 'authoring_sha256']:
        metadata.pop(key, None)
    metadata.update(generator=generator,
        contact_model='Bare Part027 hull minimum Z; complete body hull; assumed COM.',
        authoring=dict(description=description, baseline_archive_sha256=digest(baseline),
                       geometry_sha256=digest(root/'geometry.json'), hardware_qualified=False))
    source.update(samples=rows, phases=phases, validation={})
    compact(folder/'source.json', source)
    reviewed = folder/'reviewed.json'
    if reviewed.exists():
        # A retimed source needs a new 30 Hz review, not the old row count.
        compact(reviewed, dict(command=name, description=description, sample_hz=30,
            geometry_sha256=digest(root/'geometry.json'),
            cues=[[p['start'],p['kind']] for p in phases],
            samples=[dict(time_s=r['time_s'],body=r['body_translation_world_mm'],
                euler=r['body_rotation_euler_xyz_rad'],q=r['actuator_angles_rad'],
                phase=r['phase'],contact=r['contact_active']) for r in rows[::4]]))
    refresh_metrics(root, [name])
    source = read(folder/'source.json'); rows = source['samples']
    q = np.array([r['actuator_angles_rad'] for r in rows])
    velocity = np.gradient(q, 1/120, axis=0); acceleration = np.gradient(velocity, 1/120, axis=0)
    pulses = np.zeros((len(rows), 12))
    for j in calibration.get('calibration', calibration)['joints']:
        pulses[:,j['id']] = j['home_us']+(np.rad2deg(q).reshape(-1,12)[:,j['id']]-j['home_cd']/100)*j['us_per_degree']*(-1 if j['invert'] else 1)
    v = source['validation']; end = rows[-1]['time_s']; motion_end = phases[-1]['start']
    v.update(command=name, geometry_id=cfg['geometry_id'], samples=len(rows), sample_hz=120,
        duration_s=end, motion_end_s=motion_end,
        peak_joint_speed_deg_s=float(np.rad2deg(abs(velocity)).max()),
        joint_min_deg=np.rad2deg(q.min(0)).tolist(), joint_max_deg=np.rad2deg(q.max(0)).tolist(),
        minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows if r['support_margin_mm'] is not None),
        mapped_pulse_min_us=float(pulses.min()), mapped_pulse_max_us=float(pulses.max()),
        reviewed_pulse_window_us=[400,2900], collision_checked=False, hardware_qualified=False)
    if name=='pushup':
        pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm']); bh=hulls['body']
        for r in rows:
            matrix=Rotation.from_euler('xyz',r['body_rotation_euler_xyz_rad']).as_matrix()
            vertices=(bh-pivot)@matrix.T+pivot+np.array(r['body_translation_world_mm'])
            r['front_body_clearance_mm']=float(vertices[bh[:,0]>pivot[0],2].min())
            r['rear_body_clearance_mm']=float(vertices[bh[:,0]<pivot[0],2].min())
        low=next(r for r in rows if r['phase']=='pushup_1_bottom')
        high=rows[round(phases[0]['end']*120)]
        v['press_front_clearance_low_high_mm']=[low['front_body_clearance_mm'],high['front_body_clearance_mm']]
        v['press_rear_clearance_low_high_mm']=[low['rear_body_clearance_mm'],high['rear_body_clearance_mm']]
    compact(folder/'source.json', source); write(folder/'validation.json',v)
    manifest=read(folder/'manifest.json')
    manifest.update(gait_id=f'{name}_expressive_bare_20261015',generated_utc='2026-10-15',
        duration_seconds=end,motion_end_seconds=motion_end,sample_count=len(rows),
        source_sha256=digest(folder/'source.json'),posture_sha256=digest(folder/'posture.json'),
        posture_hulls_sha256=digest(folder/'contact-hulls.npz'),source_validation=v,
        entry_actuator_angles_rad=rows[0]['actuator_angles_rad'],final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],
        entry_pose='Bare-Part027 standing pose; existing executor owns entry interpolation.',
        body_target=dict(position_mm=rows[-1]['body_position_world_mm'],euler_xyz_rad=rows[-1]['body_rotation_euler_xyz_rad']),
        contact_model=metadata['contact_model'],retargeting_notes=description,
        current_mounting_qualification='Current geometry and installed pulse mapping; loaded behavior and whole-body collisions unqualified.')
    if 'reviewed_sha256' in manifest:manifest['reviewed_sha256']=digest(reviewed)
    if 'semantic_end_seconds' in manifest:
        manifest.update(semantic_end_seconds=end,semantic_final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],
                        playlist_final_actuator_angles_rad=rows[-1]['actuator_angles_rad'])
    manifest['face_cues']=[*(cue for cue in manifest.get('face_cues', [])[:1] if cue['time_s']==0),
                           dict(time_s=motion_end,name='stand',mode='once',fps=1)]
    for key in ['blender_workspace_file','blender_scene']:manifest.pop(key,None)
    write(folder/'manifest.json',manifest)
    schema=read(folder/'schema.json');schema.update(contact_model=metadata['contact_model'],sample_fields=list(rows[0]))
    schema[name+'_posture']=description
    if 'semantic_end_s' in schema:schema.update(semantic_end_s=end,optional_demonstration_recovery=False)
    write(folder/'schema.json',schema)
    if (folder/'config.json').exists():
        config=read(folder/'config.json');config['geometry_id']=cfg['geometry_id'];write(folder/'config.json',config)
    contract=read(folder/'execution-contract.json')
    contract.update(gait_id=manifest['gait_id'],phases=[],contact_events=[],face_cues=manifest['face_cues'])
    for i,p in enumerate(phases):
        a,b=round(p['start']*120),round(p['end']*120)
        contacts=np.array([r['contact_active'] for r in rows[a:b+1]])
        contract['phases'].append(dict(id=f'p{i:03d}_{p["kind"]}',name=p['kind'],section='clip',execution_role='command',
            source_interval_s=[p['start'],p['end']],source_sample_indices_inclusive=[a,b],
            demonstration_duration_s=p['end']-p['start'],
            supporting_legs_throughout=[l for j,l in enumerate(LEGS) if contacts[:,j].all()],
            contact_states=np.unique(contacts,axis=0).tolist(),
            moving_joint_indices=np.flatnonzero(np.ptp(q[a:b+1].reshape(-1,12),axis=0)>1e-6).tolist(),
            coordination='whole_body_shared_clock',reference_peak_speed_rad_s=abs(velocity[a:b+1]).max(0).ravel().tolist(),
            reference_peak_acceleration_rad_s2=abs(acceleration[a:b+1]).max(0).ravel().tolist()))
    for name_profile,profile in contract['timing_profiles'].items():
        profile['duration_s']={p['id']:None if name_profile=='operating' else p['demonstration_duration_s'] for p in contract['phases']}
    for i,r in enumerate(rows):
        if i==0 or r['contact_active']!=rows[i-1]['contact_active']:
            contract['contact_events'].append(dict(source_time_s=r['time_s'],sample_index=i,active=r['contact_active'],body_contact_active=r['body_contact_active'],support_source='feet'))
    contract['entry'].update(joint_angles_rad=rows[0]['actuator_angles_rad'],body_position_world_mm=rows[0]['body_position_world_mm'],body_orientation_world_quaternion_wxyz=rows[0]['body_orientation_world_quaternion_wxyz'])
    contract['completion']['joint_angles_rad']=rows[-1]['actuator_angles_rad']
    if 'semantic_end_s' in contract['completion']:
        contract['completion'].update(semantic_end_s=end,optional_demo_recovery_end_s=None)
    for f in contract['source_files']:f['sha256']=digest(folder/Path(f['path']).name)
    write(folder/'execution-contract.json',contract)
    for filename in ['interpolation-validation.json','blender-validation.json']:
        write(folder/filename,dict(status='pending_current_source_validation',source_sha256=digest(folder/'source.json')))
    catalog=read(family/'catalog.json');item=next(e for e in catalog['commands'] if e['command']==name)
    for filename in [*item['sha256'],'posture.json','contact-hulls.npz']:
        item['sha256'][filename]=digest(folder/filename)
    compact(family/'catalog.json',catalog)
    print(name,json.dumps(v),flush=True)


def stamp(row,t,phase):
    quat=Rotation.from_euler('xyz',row['body_rotation_euler_xyz_rad']).as_quat()
    row.update(time_s=t,phase=phase['kind'],phase_fraction=(t-phase['start'])/(phase['end']-phase['start']),
               body_orientation_world_quaternion_wxyz=[float(quat[3]),*quat[:3]],body_yaw_world_rad=row['body_rotation_euler_xyz_rad'][2])
    return row


def retime(name,source,mechanism,ref):
    durations={'point':[.6,.35,.6,1.5,.6,.35,.6,.2], 'bow':[.4,.65,5.,.65,.4,.2]}[name]
    original=source['samples'];times=np.array([r['time_s'] for r in original])
    keys=['body_translation_world_mm','body_rotation_euler_xyz_rad','actuator_angles_rad',
          'target_foot_reference_xy_mm','target_sole_clearance_mm']
    curves={k:PchipInterpolator(times,np.array([r[k] for r in original]),axis=0) for k in keys}
    phases=[];cursor=0.
    for old,duration in zip(source['phases'],durations):
        phases.append(dict(start=cursor,end=round(cursor+duration,8),kind=old['kind']))
        cursor=phases[-1]['end']
    delta=None
    if name=='point':
        base=original[240];mechanism.body_euler=base['body_rotation_euler_xyz_rad']
        q,_=mechanism.solve('RL',base['body_translation_world_mm'],base['actuator_angles_rad'][2],base['target_foot_reference_xy_mm'][2],0)
        delta=q-np.array(base['actuator_angles_rad'][2])
    rows=[]
    held_phase=next(p for p in phases if p['kind']=='hold_'+name)
    hold_index=round(held_phase['start']*120)
    for i in range(round(cursor*120)+1):
        t=i/120;j=next((j for j,p in enumerate(phases) if t<p['end']),len(phases)-1)
        p=phases[j];old=source['phases'][j];u=(t-p['start'])/(p['end']-p['start']);old_t=old['start']+(old['end']-old['start'])*u
        # Hold exactly, then retrace the fitted entry. Re-solving the reverse
        # path from old boot poses can select another bare-foot contact branch.
        if i>hold_index:
            index=hold_index if t<=held_phase['end'] else max(0,round((held_phase['start']-(t-held_phase['end']))*120))
            rows.append(stamp(copy.deepcopy(rows[index]),t,p))
            continue
        row=copy.deepcopy(original[min(len(original)-1,round(old_t*120))])
        for k,curve in curves.items():row[k]=curve(old_t).tolist()
        mechanism.body_euler=row['body_rotation_euler_xyz_rad'];q=np.array(row['actuator_angles_rad'])
        for leg,l in enumerate(LEGS):
            if row['contact_active'][leg]:
                seed=rows[-1]['actuator_angles_rad'][leg] if rows else q[leg]
                q[leg],_=mechanism.solve(l,row['body_translation_world_mm'],seed,row['target_foot_reference_xy_mm'][leg],row['target_sole_clearance_mm'][leg])
        if name=='point' and not row['contact_active'][2]:
            if p['kind']=='lift_front_left':q[2]+=delta*(1-ref.smooth(u))
            elif p['kind']=='replace_front_left':q[2]+=delta*ref.smooth(u)
        row['actuator_angles_rad']=q.tolist();rows.append(stamp(row,t,p))
    return rows,phases


def pushup(source,mechanism,ref,hulls,cfg):
    pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm']);bh=hulls['body']
    def pose(clearance,pitch):
        e=np.deg2rad([0,pitch,0]);matrix=Rotation.from_euler('xyz',e).as_matrix()
        floor=((bh-pivot)@matrix[2]+pivot[2]).min()
        return np.array([-20.,0.,clearance-floor]),e
    high,eh=pose(24.,-15.);low,el=pose(3.,5.)
    standing=np.array(source['samples'][0]['body_translation_world_mm']);es=np.zeros(3)
    segments=[('brace_for_pushups',.7,standing,es,high,eh)]
    for i in range(1,6):
        segments += [(f'pushup_{i}_down',.6,high,eh,low,el),
                     (f'pushup_{i}_bottom',.1,low,el,low,el),
                     (f'pushup_{i}_up',.45,low,el,high,eh)]
    segments += [('return_to_standing',.7,high,eh,standing,es),('hold_standing',.2,standing,es,standing,es)]
    phases=[];cursor=0.
    for name,duration,*_ in segments:
        phases.append(dict(start=cursor,end=round(cursor+duration,8),kind=name));cursor=phases[-1]['end']
    anchor=source['samples'][0];xy=np.array(anchor['target_foot_reference_xy_mm']);seed=np.array(anchor['actuator_angles_rad'])
    rows=[]
    for i in range(round(cursor*120)+1):
        t=i/120;j=next((j for j,p in enumerate(phases) if t<p['end']),len(phases)-1);p=phases[j]
        _,_,a,ea,b,eb=segments[j];u=ref.smooth((t-p['start'])/(p['end']-p['start']))
        body=a+(b-a)*u;e=ea+(eb-ea)*u;mechanism.body_euler=e;q=seed.copy()
        for leg,l in enumerate(LEGS):q[leg],_=mechanism.solve(l,body,q[leg],xy[leg],0)
        row=copy.deepcopy(anchor);row.update(body_translation_world_mm=body.tolist(),body_rotation_euler_xyz_rad=e.tolist(),
            actuator_angles_rad=q.tolist(),target_foot_reference_xy_mm=xy.tolist(),target_sole_clearance_mm=[0.]*4,contact_active=[True]*4)
        rows.append(stamp(row,t,p));seed=q
    return rows,phases


def main(root,baseline_dir,calibration_path):
    cfg=read(root/'geometry.json');ref=load_reference(root);mechanism=ref.Mechanism(cfg)
    sole=np.array(read(root/'motions/locomotion/walk-contact.json')['sole_hull_local_mm'])
    hulls=dict(np.load(root/'motions/gestures/sit/posture-hulls.npz'))
    for leg in LEGS:hulls['sole_'+leg]=sole.copy()
    mechanism.hulls={leg:sole for leg in LEGS};calibration=read(calibration_path)
    descriptions={
        'point':'Quick support shift and front-left lift, emphatic full forward extension and held point, then replace the bare foot and recover.',
        'pushup':'Five deep front presses with all four bare feet planted: front approaches the floor, pauses briefly and pushes back up with the rear braced.',
        'bow':'Prompt front-low/rear-high bow with forward hands, held for five seconds before rising and returning to standing.'}
    for name in ['point','pushup','bow']:
        baseline=baseline_dir/(name+'-baseline.json.gz');source=json.loads(gzip.decompress(baseline.read_bytes()))
        rows,phases=pushup(source,mechanism,ref,hulls,cfg) if name=='pushup' else retime(name,source,mechanism,ref)
        finish(root,name,source,rows,phases,descriptions[name],hulls,calibration,baseline)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--baseline-dir',type=Path,required=True)
    parser.add_argument('--calibration',type=Path,required=True)
    args=parser.parse_args();main(args.root.resolve(),args.baseline_dir.resolve(),args.calibration)
