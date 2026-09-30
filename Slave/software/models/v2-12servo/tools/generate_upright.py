"""Generate the experimental rear-supported Upright clip. NumPy/SciPy required."""
import json,hashlib,copy,importlib.util,math
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from retarget_clips import SEARCH_BOUNDS
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ref',ROOT/'motions/walk/reference.py');ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
FAMILY=ROOT/'motions/gestures';OUT=FAMILY/'upright';OUT.mkdir(exist_ok=True)
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
cfg=read(ROOT/'geometry.json');cfg['research_angle_bounds_deg']=np.rad2deg(SEARCH_BOUNDS).tolist()
m=ref.Mechanism(cfg);hulls=np.load(FAMILY/'sit/posture-hulls.npz');legs=['FL','FR','RL','RR'];m.hulls={l:hulls['sole_'+l] for l in legs}
sit=read(FAMILY/'sit/source.json');base=sit['samples'][360];body0=np.array(base['body_translation_world_mm']);e0=np.array(base['body_rotation_euler_xyz_rad']);q0=np.array(base['actuator_angles_rad']);m.body_euler=e0.copy()
anchors={l:m.pose(l,q0[i],body0) for i,l in enumerate(legs[:2])};R0,T0=anchors['FL'];rear=m.vertices('FL',q0[0],body0);near=rear[rear[:,2]<.5];center=(near[:,0].min()+near[:,0].max())/2
ankle=np.array(read(FAMILY/'point/posture.json')['ankle_local_mm']);ankle[1]=0
bounds=np.deg2rad(cfg['research_angle_bounds_deg']);pivot=np.array([0,0,65.]);q=q0.copy();rows=copy.deepcopy(sit['samples'][:361]);maxerr=0.;rear_drift=0.
front_starts={l:m.reference(l,q[i],body0)[:2] for i,l in enumerate(legs) if i>=2}
# Preserve the authored brace excursion relative to the changed footprint.
reference=np.array(read(ROOT/'motions/retargeting.json').get('choreography_reference_stance_xy_mm',cfg['reference_stance_xy_mm']))
brace=np.array([[0.,52.],[0.,-52.]])+np.array(cfg['reference_stance_xy_mm'])[:2]-reference[:2]
# Backward near-straight reach on the existing assembly branch. This is a
# constrained solution, not a change to the servo map or the legacy motions.
front_extended=np.deg2rad([8.,-2.,-104.])
old_span=reference[0,0]-reference[2,0];new_span=np.array(cfg['reference_stance_xy_mm'])[0,0]-np.array(cfg['reference_stance_xy_mm'])[2,0]
brace_pitch=math.asin(math.sin(e0[1])*old_span/new_span)
def front_pose(leg,body,seed,xy,height=0.):
 try:return m.solve(leg,body,seed,xy,height)
 except ValueError:
  # A flat sole changes its supporting vertex. Try nearby seeds before
  # declaring the authored placement unreachable.
  def residual(v):
   try:return np.r_[m.reference(leg,v,body)[:2]-xy,m.vertices(leg,v,body)[:,2].min()-height]
   except ValueError:return np.ones(3)*1000
  candidates=[]
  for da,dt in [(a,t) for a in [-.1,0.,.1] for t in [-.2,0.,.2]]:
   start=np.clip(seed+[0.,da,dt],bounds[:,0]+1e-8,bounds[:,1]-1e-8)
   fit=least_squares(residual,start,bounds=(bounds[:,0],bounds[:,1]),max_nfev=180,xtol=1e-11,ftol=1e-11,gtol=1e-11,diff_step=1e-5)
   error=float(np.linalg.norm(fit.fun))
   if error<.001:candidates.append((float(np.linalg.norm(fit.x-seed)),fit.x,error))
  if not candidates:raise ValueError(f'{leg}: authored front placement unreachable: {xy}, body={body}')
  _,angles,error=min(candidates,key=lambda c:c[0]);return angles,error
def rear_pose(pitch,x):
 global q,maxerr
 m.body_euler=np.array([0.,pitch,0.])
 def residual(v):
  try:
   R,T=m.pose('FL',np.r_[0.,v],np.zeros(3));d=(R-R0)@np.array([1.,0,0]);return [100*d[0],100*d[2],(T0-T)[0]-x]
  except ValueError:return [1000.]*3
 sol=least_squares(residual,q[0,1:],bounds=(bounds[1:,0],bounds[1:,1]),xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=200)
 assert np.linalg.norm(sol.fun)<.001,sol.fun
 q[0]=np.r_[0.,sol.x];_,T=m.pose('FL',q[0],np.zeros(3));body=T0-T
 # Mirrored model differs only at float precision; solve the full right pose.
 def rres(v):
  try:
   R,T=m.pose('FR',v,body);return np.r_[T-anchors['FR'][1],((R-anchors['FR'][0])@np.array([1.,0,0]))*100]
  except ValueError:return [1000.]*6
 sol=least_squares(rres,q[1],bounds=(bounds[:,0],bounds[:,1]),xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=80);assert np.linalg.norm(sol.fun)<.001;q[1]=sol.x
 return body
for n in range(361,22*120+1):
 if n>2400:
  held=copy.deepcopy(rows[-1]);held['time_s']=n/120;held['phase']='hold';rows.append(held);continue
 t=n/120;body=body0.copy();m.body_euler=e0.copy();contact=[True]*4
 if t<=5:
  u=(t-3)/2;s=ref.smooth(u);target=(1-s)*front_starts['RL']+s*brace[0]
  q[2],err=front_pose('RL',body,q[2],target,8*ref.bump(u));maxerr=max(maxerr,err);contact[2]=u>=1;phase='front_left_back'
 elif t<=6:
  u=ref.smooth(t-5);body=rear_pose(e0[1]+(brace_pitch-e0[1])*u,body0[0]+(-16.5-body0[0])*u)
  for i in [2,3]:q[i],err=front_pose(legs[i],body,q[i],brace[0] if i==2 else front_starts['RR']);maxerr=max(maxerr,err)
  phase='brace_shift'
 elif t<=8:
  body=rear_pose(brace_pitch,-16.5);u=(t-6)/2;s=ref.smooth(u);target=(1-s)*front_starts['RR']+s*brace[1]
  q[3],err=front_pose('RR',body,q[3],target,8*ref.bump(u));maxerr=max(maxerr,err);contact[3]=u>=1;phase='front_right_back'
 elif t<=12:
  u=ref.smooth((t-8)/4);body=rear_pose(brace_pitch,-16.5-33.5*u)
  for i in [2,3]:q[i],err=front_pose(legs[i],body,q[i],brace[i-2]);maxerr=max(maxerr,err)
  phase='supported_push';push_q=q[2:].copy()
 else:
  u=ref.smooth(min(1.,(t-12)/8));body=rear_pose(brace_pitch+(-math.pi/2-brace_pitch)*u,-50+(center+50)*u)
  # Valid connected route around the four-bar's unreachable region.
  way=[push_q[0],np.deg2rad([8.,-4.,-78.]),np.deg2rad([8.,-4.,-102.]),front_extended]
  clock=np.clip((t-14)/2,0.,3.);j=min(2,int(clock));v=ref.smooth(clock-j)
  for i in [2,3]:
   if j==0:
    middle=np.array([way[1][0],way[1][1],way[0][2]])
    q[i]=way[0]+ref.smooth(min(1.,clock*2))*(middle-way[0])+ref.smooth(max(0.,clock*2-1))*(way[1]-middle)
   else:q[i]=(1-v)*way[j]+v*way[j+1]
  contact=[True,True,False,False];phase='rise' if t<=20 else 'hold'
 feet=[];zs=[];contacts=[];indices=[];support=[];betas=[];closures=[];reach=[]
 for i,l in enumerate(legs):
  vs=m.vertices(l,q[i],body);idx=int(np.argmin(vs[:,2]));feet.append(m.reference(l,q[i],body).tolist());zs.append(float(vs[idx,2]));contacts.append(vs[idx].tolist());indices.append(idx)
  if contact[i]:support.extend(vs[vs[:,2]<vs[idx,2]+.5])
  D,P,E,beta,height=m.planar(q[i]);betas.append(beta);closures.append(height);reach.append(float(np.linalg.norm(np.r_[D[0]-m.O[0],0,D[1]-m.O[1]]+ref.ry(-(beta-m.b0))@ankle)))
  if i<2:
   R,T=m.pose(l,q[i],body);rear_drift=max(rear_drift,float(np.linalg.norm(T-anchors[l][1])),float(np.linalg.norm(R-anchors[l][0])))
 B=ref.ry(m.body_euler[1]);com=body+pivot;clear=float(((hulls['body']-pivot)@B.T+pivot+body)[:,2].min())
 row=dict(time_s=t,phase=phase,body_translation_world_mm=body.tolist(),body_position_world_mm=com.tolist(),body_rotation_euler_xyz_rad=m.body_euler.tolist(),body_orientation_world_quaternion_wxyz=[math.cos(m.body_euler[1]/2),0,math.sin(m.body_euler[1]/2),0],body_yaw_world_rad=0.,actuator_angles_rad=q.tolist(),passive_beta_rad=betas,foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_vertex_index=indices,contact_active=contact,sole_clearance_mm=zs,body_ground_clearance_mm=clear,body_contact_active=False,body_contact_polygon_world_mm=[],support_source='broad_rear_soles_and_grounded_front_feet',assumed_com_world_mm=com.tolist(),support_margin_mm=ref.margin(com[:2],support),arm_reach_mm=reach,minimum_closure_height_mm=min(closures))
 row['target_foot_reference_xy_mm']=[p[:2] for p in feet];row['target_sole_clearance_mm']=zs
 rows.append(row)
 if n%120==0:print(t,phase,'q',np.round(np.rad2deg(q[[0,2]]),2).tolist(),'floor',min(zs),'body',clear,'margin',row['support_margin_mm'],flush=True)
a=np.array([r['actuator_angles_rad'] for r in rows]);new=rows[361:]
validation=dict(command='upright',samples=len(rows),max_target_error_mm=maxerr,max_rear_anchor_error_mm=rear_drift,min_sole_z_mm=min(min(r['sole_clearance_mm']) for r in rows),min_body_z_mm=min(r['body_ground_clearance_mm'] for r in rows),min_support_margin_after_sit_mm=min(r['support_margin_mm'] for r in new),minimum_closure_height_mm=min(r['minimum_closure_height_mm'] for r in new),maximum_adjacent_joint_step_degrees=float(np.rad2deg(abs(np.diff(a,axis=0))).max()),joint_min_deg=np.rad2deg(a.min(0)).tolist(),joint_max_deg=np.rad2deg(a.max(0)).tolist(),final_pitch_deg=-90,final_front_reach_mm=rows[-1]['arm_reach_mm'][2:],hardware_qualified=False,collision_checked=False,support_scope='Provisional COM at body pivot; broad soles within 0.5 mm of floor. No dynamics, mass distribution or traction qualification.')
assert validation['min_sole_z_mm']>-.005
assert validation['min_body_z_mm']>0
assert validation['min_support_margin_after_sit_mm']>0
assert validation['max_rear_anchor_error_mm']<.001
assert validation['minimum_closure_height_mm']>2
print(json.dumps(validation,indent=2),flush=True)
metadata=copy.deepcopy(read(FAMILY/'crouch/source.json')['metadata']);metadata={k:v for k,v in metadata.items() if not k.startswith('native_')};metadata['configuration']['command']='upright';metadata['generator']='tools/generate_upright.py'
write(OUT/'source.json',dict(metadata=metadata,validation=validation,samples=rows));write(OUT/'validation.json',validation)
posture=dict(description='Experimental Sit, front feet backward, supported rearward push and full vertical rise over anchored rear lower legs.',contact_hulls_file='../sit/posture-hulls.npz',contact_hulls_sha256=sha(FAMILY/'sit/posture-hulls.npz'),mechanism_geometry_sha256=sha(ROOT/'geometry.json'),base_motion=dict(source_file='../sit/source.json',source_sha256=sha(FAMILY/'sit/source.json'),posture_file='../sit/posture.json',posture_sha256=sha(FAMILY/'sit/posture.json')),sit_prefix_end_s=3.,provisional_COM_body_mm=[0,0,65],rear_contact_tolerance_mm=.5,front_brace_xy_mm=brace.tolist(),rear_only_support_start_s=12.,brace_pitch_deg=math.degrees(brace_pitch),brace_shift_x_mm=-16.5,rear_support_policy='Rear boot pose fixed throughout. Full vertical pitch and original phase times retained; temporary reference meshes excluded from body clearance.',upright_pitch_deg=-90.,front_extended_angles_rad=front_extended.tolist(),hardware_qualified=False)
write(OUT/'posture.json',posture)
phases=[('sit',0,3),('front_left_back',3,5),('brace_shift',5,6),('front_right_back',6,8),('supported_push',8,12),('rise',12,20),('hold',20,22)]
wire=dict(t='intent',name='emote',asset='upright');manifest=read(FAMILY/'crouch/manifest.json');manifest.update(command='upright',wire=wire,gait_id='upright_experimental_current_geometry',duration_seconds=22.,motion_end_seconds=20.,source_sample_hz=120,sample_count=len(rows),entry_actuator_angles_rad=rows[0]['actuator_angles_rad'],final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],source_sha256=sha(OUT/'source.json'),posture_sha256=sha(OUT/'posture.json'),completion='Hold experimental Upright until another command. Return transition is not physically qualified.',source_validation=validation);write(OUT/'manifest.json',manifest)
schema=read(FAMILY/'crouch/schema.json');schema.update(command='upright',contact_model='Rear lower legs and boot patches remain anchored from Sit; front feet release after rearward weight shift.');write(OUT/'schema.json',schema)
contract=read(FAMILY/'crouch/execution-contract.json');contract.update(command='upright',gait_id=manifest['gait_id'],wire=wire,source_files=[dict(path='Slave/software/models/v2-12servo/motions/gestures/upright/'+f,sha256=sha(OUT/f)) for f in ['source.json','manifest.json']],phases=[dict(id=p,name=p,section='clip',source_interval_s=[s,e]) for p,s,e in phases],timing_profiles={name:dict(duration_s={p:e-s for p,s,e in phases}) for name in ['demonstration','research_candidate']},entry=dict(joint_angles_rad=rows[0]['actuator_angles_rad'],arbitrary_pose_entry_verified=False),completion=dict(joint_angles_rad=rows[-1]['actuator_angles_rad'],contacts=[True,True,False,False],behavior='Hold Upright, no automatic four-foot Stand.'))
contract['timing_profiles']['operating']=dict(status='unconfigured_pending_loaded_calibration',duration_s={p:None for p,s,e in phases});write(OUT/'execution-contract.json',contract)
(OUT/'sample_reference.py').write_text((FAMILY/'crouch/sample_reference.py').read_text().replace("command='crouch'","command='upright'"))
catalog=read(FAMILY/'catalog.json');catalog['commands']=[e for e in catalog['commands'] if e['command']!='upright'];catalog['commands'].append(dict(command='upright',path='upright',handoff='Slave/software/models/v2-12servo/motions/gestures/upright',execution_handoff='Slave/software/models/v2-12servo/motions/gestures/upright/execution-contract.json',sha256={p.name:sha(p) for p in OUT.iterdir() if p.suffix in ['.json','.py']}));write(FAMILY/'catalog.json',catalog)
