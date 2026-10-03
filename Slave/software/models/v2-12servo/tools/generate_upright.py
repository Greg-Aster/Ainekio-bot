"""Generate the experimental rear-supported Upright clip. NumPy/SciPy required."""
import json,hashlib,copy,importlib.util,math
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from retarget_clips import SEARCH_BOUNDS
from mechanical_limits import Limits
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ref',ROOT/'motions/walk/reference.py');ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
FAMILY=ROOT/'motions/gestures';OUT=FAMILY/'upright';OUT.mkdir(exist_ok=True)
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
limits=Limits(ROOT);cfg=read(ROOT/'geometry.json');cfg['research_angle_bounds_deg']=limits.bounds
m=ref.Mechanism(cfg);hulls=np.load(FAMILY/'sit/posture-hulls.npz');legs=['FL','FR','RL','RR'];m.hulls={l:hulls['sole_'+l] for l in legs}
sit=read(FAMILY/'sit/source.json');base=sit['samples'][360];body0=np.array(base['body_translation_world_mm']);e0=np.array(base['body_rotation_euler_xyz_rad']);q0=np.array(base['actuator_angles_rad']);m.body_euler=e0.copy()
anchors={l:m.pose(l,q0[i],body0) for i,l in enumerate(legs[:2])};R0,T0=anchors['FL'];rear=m.vertices('FL',q0[0],body0);near=rear[rear[:,2]<.5];center=(near[:,0].min()+near[:,0].max())/2
ankle=np.array(read(FAMILY/'point/posture.json')['ankle_local_mm']);ankle[1]=0
bounds=np.deg2rad(cfg['research_angle_bounds_deg']);pivot=np.array([0,0,65.]);q=q0.copy();rows=copy.deepcopy(sit['samples'][:361]);maxerr=0.;rear_drift=0.
front_starts={l:m.reference(l,q[i],body0)[:2] for i,l in enumerate(legs) if i>=2}
# Level the seated chassis before shifting rearward. A simultaneous transfer at
# the old seated pitch puts the grounded front anchors beyond the screw-aware
# linkage range. This two-stage route keeps all four feet supporting the body
# until the modeled COM is over the rear soles.
front_extended=None
brace_pitch=math.radians(-10.)
def encode(a):
 d=np.rad2deg(a);theta=float(np.clip(d[2],limits.theta[0]+.02,limits.theta[-1]-.02));lo,hi=limits.alpha_bounds(theta)
 return np.array([np.clip(d[0],-109.99,109.99),theta,np.clip((d[1]-lo)/(hi-lo),.0001,.9999)])
def decode(v):
 lo,hi=limits.alpha_bounds(v[1]);return np.deg2rad([v[0],lo+(hi-lo)*v[2],v[1]])
encoded_bounds=([-110,limits.theta[0]+.02,0],[110,limits.theta[-1]-.02,1])
def front_pose(leg,body,seed,xy,height=0.):
 def residual(v):
  try:
   a=decode(v);return np.r_[m.reference(leg,a,body)[:2]-xy,m.vertices(leg,a,body)[:,2].min()-height]
  except ValueError:return np.ones(3)*1000
 fit=least_squares(residual,encode(seed),bounds=encoded_bounds,max_nfev=100,xtol=1e-10,ftol=1e-10,gtol=1e-10,diff_step=1e-5)
 error=float(np.linalg.norm(fit.fun))
 if error>.01:raise ValueError(f'{leg}: front placement unreachable: {xy}, body={body}, residual={error}')
 return decode(fit.x),error
def rear_pose(pitch,x):
 global q,maxerr
 m.body_euler=np.array([0.,pitch,0.])
 anchor=np.array(base['foot_bolt_world_mm'][0])[:2]
 def calculate(v):
  a=decode(np.r_[0.,v]);vs=m.vertices('FL',a,np.zeros(3));p=m.reference('FL',a,np.zeros(3));b=np.r_[anchor-p[:2],-vs[:,2].min()]
  return a,b,vs+b
 def residual(v):
  try:
   a,b,vs=calculate(v);R,T=m.pose('FL',a,b);d=(R-R0)@np.array([1.,0,0]);near=vs[vs[:,2]<.5];com=b+pivot
   clear=float(((hulls['body']-pivot)@ref.ry(pitch).T+pivot+b)[:,2].min())
   # Retain broad rear contact where possible; allow the soles to roll as
   # the body rises instead of forcing the crank through its screw boundary.
   return [b[0]-x,d[0]*.05,d[2]*.05,min(0.,clear-.01)*30]
  except ValueError:return [1000.]*4
 seed=encode(q[0])[1:];sol=least_squares(residual,seed,bounds=(np.array(encoded_bounds[0])[1:],np.array(encoded_bounds[1])[1:]),xtol=1e-10,ftol=1e-10,gtol=1e-10,max_nfev=100,diff_step=1e-5)
 q[0],body,_=calculate(sol.x)
 q[1],err=front_pose('FR',body,q[0],np.array(base['foot_bolt_world_mm'][1])[:2],0.)
 return body
for n in range(361,22*120+1):
 if n>2400:
  held=copy.deepcopy(rows[-1]);held['time_s']=n/120;held['phase']='hold';rows.append(held);continue
 t=n/120;body=body0.copy();m.body_euler=e0.copy();contact=[True]*4
 if t<=12:
  level=ref.smooth(np.clip((t-3)/2,0.,1.));shift=ref.smooth(np.clip((t-5)/7,0.,1.))
  body=rear_pose(e0[1]+(brace_pitch-e0[1])*level,body0[0]+(-50-body0[0])*shift)
  for i in [2,3]:
   q[i],err=front_pose(legs[i],body,q[i],front_starts[legs[i]])
   maxerr=max(maxerr,err)
  phase='level_body' if t<=5 else 'rearward_transfer';push_q=q[2:].copy()
 else:
  u=ref.smooth(min(1.,(t-12)/8));body=rear_pose(brace_pitch+(-math.pi/2-brace_pitch)*u,-50+(-118+50)*u)
  if front_extended is None:
   target=np.deg2rad([8.8875,3.,-53.25]);front_extended=decode(encode(target))
  withdrawal=decode(encode(np.deg2rad([8.,45.,45.])))
  v=ref.smooth(np.clip((t-12)/2,0.,1.));extension=ref.smooth(np.clip((t-14)/6,0.,1.))
  for i in [2,3]:
   start=decode((1-v)*encode(push_q[i-2])+v*encode(withdrawal))
   q[i]=decode((1-extension)*encode(start)+extension*encode(front_extended))
  contact=[True,True,False,False];phase='rise' if t<=20 else 'hold'
 feet=[];zs=[];contacts=[];indices=[];support=[];betas=[];closures=[];reach=[]
 for i,l in enumerate(legs):
  vs=m.vertices(l,q[i],body);idx=int(np.argmin(vs[:,2]));feet.append(m.reference(l,q[i],body).tolist());zs.append(float(vs[idx,2]));contacts.append(vs[idx].tolist());indices.append(idx)
  if contact[i]:support.extend(vs[vs[:,2]<vs[idx,2]+.5])
  D,P,E,beta,height=m.planar(q[i]);betas.append(beta);closures.append(height);reach.append(float(np.linalg.norm(np.r_[D[0]-m.O[0],0,D[1]-m.O[1]]+ref.ry(-(beta-m.b0))@ankle)))
  if i<2:
   rear_drift=max(rear_drift,float(np.linalg.norm(m.reference(l,q[i],body)[:2]-np.array(base['foot_bolt_world_mm'][i])[:2])))
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
assert all(limits.allowed(a) for r in rows for a in r['actuator_angles_rad'])
assert validation['max_rear_anchor_error_mm']<.001
assert validation['minimum_closure_height_mm']>2
print(json.dumps(validation,indent=2),flush=True)
metadata=copy.deepcopy(read(FAMILY/'crouch/source.json')['metadata']);metadata={k:v for k,v in metadata.items() if not k.startswith('native_')};metadata['configuration']['command']='upright';metadata['generator']='tools/generate_upright.py'
write(OUT/'source.json',dict(metadata=metadata,validation=validation,samples=rows));write(OUT/'validation.json',validation)
posture=dict(description='Experimental Sit, grounded chassis leveling and rearward support transfer, then constrained forelimb withdrawal and full vertical rise over anchored rear foot references.',contact_hulls_file='../sit/posture-hulls.npz',contact_hulls_sha256=sha(FAMILY/'sit/posture-hulls.npz'),mechanism_geometry_sha256=sha(ROOT/'geometry.json'),base_motion=dict(source_file='../sit/source.json',source_sha256=sha(FAMILY/'sit/source.json'),posture_file='../sit/posture.json',posture_sha256=sha(FAMILY/'sit/posture.json')),sit_prefix_end_s=3.,provisional_COM_body_mm=[0,0,65],rear_contact_tolerance_mm=.5,front_anchor_xy_mm={l:v.tolist() for l,v in front_starts.items()},rear_only_support_start_s=12.,brace_pitch_deg=math.degrees(brace_pitch),transfer_root_x_mm=-50.,rear_support_policy='Rear foot reference XY stays anchored; soles can roll as pitch changes to preserve the screw-aware joint branch. Modeled provisional COM stays within the support polygon; mass distribution and dynamic balance are not physically qualified.',upright_pitch_deg=-90.,front_extended_angles_rad=front_extended.tolist(),hardware_qualified=False)
write(OUT/'posture.json',posture)
phases=[('sit',0,3),('level_body',3,5),('rearward_transfer',5,12),('rise',12,20),('hold',20,22)]
wire=dict(t='intent',name='emote',asset='upright');manifest=read(FAMILY/'crouch/manifest.json');manifest.update(command='upright',wire=wire,gait_id='upright_experimental_current_geometry',duration_seconds=22.,motion_end_seconds=20.,source_sample_hz=120,sample_count=len(rows),entry_actuator_angles_rad=rows[0]['actuator_angles_rad'],final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],source_sha256=sha(OUT/'source.json'),posture_sha256=sha(OUT/'posture.json'),completion='Hold experimental Upright until another command. Return transition is not physically qualified.',source_validation=validation);write(OUT/'manifest.json',manifest)
schema=read(FAMILY/'crouch/schema.json');schema.update(command='upright',contact_model='All four foot reference XY anchors remain fixed during leveling and rearward transfer. Rear soles roll on the ground as pitch changes; the front pair withdraws after the modeled support transfer. Dynamic balance is unqualified.');write(OUT/'schema.json',schema)
contract=read(FAMILY/'crouch/execution-contract.json');contract.update(command='upright',gait_id=manifest['gait_id'],wire=wire,source_files=[dict(path='Slave/software/models/v2-12servo/motions/gestures/upright/'+f,sha256=sha(OUT/f)) for f in ['source.json','manifest.json']],phases=[dict(id=p,name=p,section='clip',source_interval_s=[s,e]) for p,s,e in phases],timing_profiles={name:dict(duration_s={p:e-s for p,s,e in phases}) for name in ['demonstration','research_candidate']},entry=dict(joint_angles_rad=rows[0]['actuator_angles_rad'],arbitrary_pose_entry_verified=False),completion=dict(joint_angles_rad=rows[-1]['actuator_angles_rad'],contacts=[True,True,False,False],behavior='Hold Upright, no automatic four-foot Stand.'))
contract['timing_profiles']['operating']=dict(status='unconfigured_pending_loaded_calibration',duration_s={p:None for p,s,e in phases});write(OUT/'execution-contract.json',contract)
(OUT/'sample_reference.py').write_text((FAMILY/'crouch/sample_reference.py').read_text().replace("command='crouch'","command='upright'"))
catalog=read(FAMILY/'catalog.json');catalog['commands']=[e for e in catalog['commands'] if e['command']!='upright'];catalog['commands'].append(dict(command='upright',path='upright',handoff='Slave/software/models/v2-12servo/motions/gestures/upright',execution_handoff='Slave/software/models/v2-12servo/motions/gestures/upright/execution-contract.json',sha256={p.name:sha(p) for p in OUT.iterdir() if p.suffix in ['.json','.py']}));write(FAMILY/'catalog.json',catalog)
