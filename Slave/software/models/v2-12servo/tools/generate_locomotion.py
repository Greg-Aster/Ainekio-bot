"""Record Crouch and ongoing locomotion demonstrations from the native clock.

Build the model first, then run with --cli /path/to/v2_walk_command.
The demonstration sends speed/stride/rate updates and Finish to an ongoing
command. Its recording length is not a runtime limit. No hardware is driven.
"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from retarget_clips import load_reference, support_margin, LEGS, SOURCE_ORDER
from validate_locomotion import leverage_report


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')

def record(root,cli,command,direction,crawl):
    run_demo=command=="run"
    crab=command.startswith("crab")
    cfg=json.loads((root/'geometry.json').read_text());ref=load_reference(root);m=ref.Mechanism(cfg)
    allowance=json.loads((root/'motions/locomotion/sole-profile.json').read_text())['support_allowance_mm']
    hulls=np.load(root/'motions/gestures/sit/posture-hulls.npz');bodyhull=hulls['body']
    if crab:
        hulls=np.load(root/'motions/gestures/reviewed-hulls.npz');bodyhull=hulls['body']
    if crawl or crab:m.hulls={l:hulls['sole_'+l] for l in ref.LEGS}
    pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
    initial=dict(t='intent',seq=1,name='walk',dir=direction,gait='crab' if crab else 'crawl' if crawl else 'walk',steps=0,speed=0 if command=='crouch' else 100 if run_demo else 25)
    updates=[] if command=='crouch' else [(6000,dict(speed=100)),(12000,dict(stride=60,rate=3)),(17000,dict(speed=0))]
    if run_demo:updates=[(6000,dict(speed=150)),(14000,dict(speed=200)),(20000,dict(speed=75)),(28000,dict(speed=0))]
    events=[(ms,{k:v for k,v in {**initial,**fields,'seq':i+2,'update':1}.items() if k!='speed' or 'stride' not in fields}) for i,(ms,fields) in enumerate(updates)]
    wire=json.dumps(initial)+'\n'+''.join(str(ms)+' '+json.dumps(msg)+'\n' for ms,msg in events)
    run=subprocess.run([str(cli),'40000' if run_demo else '30000','120'],input=wire,capture_output=True,text=True,check=True)
    native=[json.loads(line) for line in run.stdout.splitlines()]
    assert native[-1]['complete'] and all(native[-1]['grounded']),command
    # Crouch's command completion holds the exact final pose for two seconds.
    if command=='crouch':
        for _ in range(240):native.append(copy.deepcopy(native[-1]))
    rows=[];xy_error=0.;sole_low=float('inf');sole_high=-float('inf');closure=float('inf');ground=float('inf');body_ground=float('inf')
    for i,n in enumerate(native):
        body=np.array(n['body']);e=np.array(n['euler']);q=np.array(n['q']).reshape(4,3);m.body_euler=e
        feet=[];contacts=[];sole=[];indices=[];betas=[]
        for l,j in zip(LEGS,SOURCE_ORDER):
            rot,trans=m.pose(l,q[j],body);vs=m.hulls[l]@rot.T+trans;k=int(vs[:,2].argmin())
            feet.append(m.reference(l,q[j],body).tolist());contacts.append(vs[k].tolist());sole.append(float(vs[k,2]));indices.append(k);betas.append(float(m.planar(q[j])[3]-m.b0));closure=min(closure,m.planar(q[j])[4])
        targets=np.array(n['feet'])[SOURCE_ORDER]
        xy_error=max(xy_error,float(np.max(abs(np.array(feet)[:,:2]-targets[:,:2]))))
        sole_error=np.array(sole)-targets[:,2]
        sole_low=min(sole_low,float(sole_error.min()));sole_high=max(sole_high,float(sole_error.max()))
        rot=Rotation.from_euler('xyz',e);clear=float(((bodyhull-pivot)@rot.as_matrix()[2]+pivot[2]+body[2]).min());body_ground=min(body_ground,clear);ground=min(ground,min(sole))
        active=np.array(n['grounded'])[SOURCE_ORDER].tolist();com=body+pivot
        rows.append(dict(time_s=i/120,phase='lower' if i<240 and crawl else 'hold' if command=='crouch' else 'locomotion',body_translation_world_mm=body.tolist(),body_position_world_mm=com.tolist(),body_rotation_euler_xyz_rad=e.tolist(),body_orientation_world_quaternion_wxyz=rot.as_quat(scalar_first=True).tolist(),body_yaw_world_rad=float(e[2]),actuator_angles_rad=q[SOURCE_ORDER].tolist(),passive_beta_rad=betas,foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_vertex_index=indices,contact_active=active,sole_clearance_mm=sole,body_ground_clearance_mm=clear,body_contact_active=False,body_contact_polygon_world_mm=[],support_source='flight' if not any(active) else 'feet',assumed_com_world_mm=com.tolist(),support_margin_mm=support_margin([p for p,on in zip(contacts,active) if on],com),target_foot_reference_xy_mm=targets[:,:2].tolist(),target_sole_clearance_mm=targets[:,2].tolist()))
    if run_demo:
        for r,n in zip(rows,native):r['run_blend']=n['run_blend']
    # Match full-CAD controller validation: XY stays exact; signed sole height
    # includes the compact profile's conservative allowance and arithmetic error.
    assert xy_error<.005 and sole_low>-.001 and sole_high<allowance+(json.loads((root/'motions/locomotion/crab.json').read_text())['sole_refinement_allowance_mm'] if crab else .002),(command,xy_error,sole_low,sole_high,allowance)
    assert ground>-.005 and body_ground>0 and closure>0,(command,ground,body_ground,closure)
    angles=np.array([r['actuator_angles_rad'] for r in rows]);report=dict(command=command,samples=len(rows),max_target_error_mm=max(xy_error,abs(sole_low),abs(sole_high)),foot_xy_error_mm=xy_error,full_sole_height_error_mm=[sole_low,sole_high],support_allowance_mm=allowance,min_sole_z_mm=ground,min_body_z_mm=body_ground,min_closure_height_mm=float(closure),maximum_adjacent_joint_step_degrees=float(np.rad2deg(abs(np.diff(angles,axis=0))).max()),hardware_qualified=False,collision_checked=False)
    report['leverage']=leverage_report(cfg,angles,[r['contact_active'] for r in rows],json.loads((root/'motions/locomotion/config.json').read_text())['leverage_validation'])
    source=dict(metadata=dict(configuration=dict(command=command,sample_hz=120,geometry_id=cfg['geometry_id'],hardware_qualified=False),leg_order=LEGS,joint_order=cfg['joint_order'],angle_units='radian',position_units='mm',time_units='second',generator='tools/generate_locomotion.py',native_initial_command=initial,native_updates=[dict(at_ms=ms,command=msg) for ms,msg in events],native_sources_sha256={p:digest(root/p) for p in ['motion.c','walk_kinematics.c','geometry.json','motions/locomotion/config.json','motions/locomotion/contact-hulls.json','motions/locomotion/sole-profile.json']}),samples=rows,validation=report)
    if crab:
        source['metadata']['native_sources_sha256'].update({p:digest(root/p) for p in ['motions/locomotion/crab.json','motions/gestures/reviewed-hulls.npz']})
    if run_demo:
        source['metadata']['native_sources_sha256']['motions/run/config.json']=digest(root/'motions/run/config.json')
        report['flight_samples']=sum(not any(r['contact_active']) for r in rows)
        report['paired_samples']=sum(n['run_blend']==1 and r['contact_active'][0]==r['contact_active'][1] and r['contact_active'][2]==r['contact_active'][3] for r,n in zip(rows,native))
        report['dynamics_scope']='Kinematic target only; no force or attitude control and no physical running qualification.'
        report['peak_sampled_joint_speed_deg_s']=float(np.rad2deg(abs(np.diff(angles,axis=0))).max()*120)
        profile=json.loads((root/'servo_profile.json').read_text())
        pulses=profile['pulse_reference_us']+(np.rad2deg(angles)-np.array(profile['center_degrees']))*profile['us_per_degree']
        report['reference_pulse_span_us']=[float(pulses.min()),float(pulses.max())]
        from mechanical_limits import Limits
        limits=Limits(root);first=None
        for i,row in enumerate(rows):
            if row['run_blend']!=1:continue
            for leg,q in zip(LEGS,row['actuator_angles_rad']):
                if not limits.allowed_degrees(np.rad2deg(q)):
                    first=dict(sample=i,time_s=row['time_s'],cad_leg=leg,q_deg=np.rad2deg(q).tolist());break
            if first:break
        report['modeled_envelope_conflict']=first is not None;report['first_bound_envelope_conflict']=first
        report['mounting_profile_sha256']=digest(root/'servo_profile.json')
    folder=root/('motions/run' if run_demo else 'motions/gestures/crouch' if command=='crouch' else 'motions/locomotion/'+command);folder.mkdir(exist_ok=True,parents=True)
    # Compact recordings are necessary source assets, not duplicate robot scenes.
    (folder/'source.json').write_text(json.dumps(source,separators=(',',':'),allow_nan=False)+'\n');write(folder/'validation.json',report)
    print(command,report,flush=True)
    if command!='crouch':return
    duration=rows[-1]['time_s'];wire=dict(t='intent',name='emote',asset='crouch');gait_id='crouch_current_geometry';geometry_hash=digest(root/'geometry.json');policy_hash=digest(root/'motions/gestures/execution-policy.json')
    posture=dict(description='Lower all four planted feet into a held squat. Lower legs stay inclined; chassis and shell remain above ground.',contact_hulls_file='../sit/posture-hulls.npz',contact_hulls_sha256=digest(root/'motions/gestures/sit/posture-hulls.npz'),mechanism_geometry_sha256=geometry_hash,body_support_scope='Feet only; complete current body hull above floor.',body_z_mm=rows[-1]['body_translation_world_mm'][2])
    write(folder/'posture.json',posture)
    manifest=dict(command=command,wire=wire,gait_id=gait_id,duration_seconds=duration,motion_end_seconds=2.,source_sample_hz=120,sample_count=len(rows),entry_actuator_angles_rad=rows[0]['actuator_angles_rad'],final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],geometry_id=cfg['geometry_id'],geometry_sha256=geometry_hash,sole_hulls_sha256=digest(root/'motions/turns/sole-hulls.npz'),source_sha256=digest(folder/'source.json'),posture_sha256=digest(folder/'posture.json'),posture_hulls_sha256=posture['contact_hulls_sha256'],hardware_qualified=False,actuator_calibration=None,completion='Hold the four-foot crouch until another command.',source_validation=report)
    write(folder/'manifest.json',manifest)
    schema=dict(command=command,geometry_id=cfg['geometry_id'],leg_order=LEGS,joint_order=cfg['joint_order'],sample_hz=120,units=dict(angle='radian',position='mm',time='second'),contact_model='Current measured sole hull minimum Z; all four feet planted.',body_position_datum='Root geometry rotation pivot plus translation.')
    write(folder/'schema.json',schema)
    phases=[dict(id='lower',name='lower_to_crouch',section='clip',source_interval_s=[0.,2.]),dict(id='hold',name='hold_crouch',section='clip',source_interval_s=[2.,duration])];times={p['id']:p['source_interval_s'][1]-p['source_interval_s'][0] for p in phases}
    owner='Slave/software/models/v2-12servo/motions/gestures/crouch'
    contract=dict(command=command,gait_id=gait_id,wire=wire,policy_sha256=policy_hash,shared_policy='../execution-policy.json',source_files=[dict(path=owner+'/'+n,sha256=digest(folder/n)) for n in ['source.json','manifest.json']],source_units=dict(angle='radian',position='mm',time='second'),source_sample_hz=120,leg_order=LEGS,joint_order=cfg['joint_order'],phases=phases,timing_profiles=dict(demonstration=dict(duration_s=times),research_candidate=dict(duration_s=times),operating=dict(status='unconfigured_pending_loaded_calibration',duration_s={k:None for k in times})),repeat=dict(section=None,minimum=1,maximum=1),face_cues=[],entry=dict(joint_angles_rad=rows[0]['actuator_angles_rad'],arbitrary_pose_entry_verified=False),completion=dict(joint_angles_rad=rows[-1]['actuator_angles_rad'],contacts=[True]*4,behavior='Hold crouched, no automatic stand.'),hardware_ready=False)
    write(folder/'execution-contract.json',contract)
    template=(root/'motions/gestures/sit/sample_reference.py').read_text().replace("command='sit'","command='crouch'");(folder/'sample_reference.py').write_text(template)
    catalog_path=root/'motions/gestures/catalog.json';catalog=json.loads(catalog_path.read_text());catalog['commands']=[x for x in catalog['commands'] if x['command']!='crouch']+[dict(command=command,path=command,handoff=owner,execution_handoff=owner+'/execution-contract.json',sha256={n:digest(folder/n) for n in ['source.json','manifest.json','schema.json','execution-contract.json','sample_reference.py','posture.json','validation.json']})];write(catalog_path,catalog)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--cli',type=Path,required=True);ap.add_argument('--run-only',action='store_true');ap.add_argument('--crab-only',action='store_true');ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);a=ap.parse_args()
    if a.run_only:
        record(a.root,a.cli,'run','fwd',False)
        raise SystemExit(0)
    if a.crab_only:
        for name,direction in [('crab','side_l'),('crab_right','side_r'),('crab_forward','fwd'),('crab_backward','back'),('crab_turn_left','turn_l'),('crab_turn_right','turn_r')]:record(a.root,a.cli,name,direction,False)
        raise SystemExit(0)
    record(a.root,a.cli,'crouch','fwd',True)
    for crawl in [False,True]:
        for suffix,direction in [('forward','fwd'),('backward','back'),('turn_left','turn_l'),('turn_right','turn_r')]:
            record(a.root,a.cli,('crawl_' if crawl else 'walk_')+suffix,direction,crawl)
