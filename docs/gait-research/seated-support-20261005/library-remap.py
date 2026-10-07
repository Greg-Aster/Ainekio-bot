"""Recalculate the remaining compact-linkage motion library from retained paths.

Offline only. No electrical calibration, motion clock, command semantics, runtime
limits or mesh geometry changes. Thirteen clips retain exact body/foot paths;
Crouch retains its native planner path. Six support/reach refits are explicit below. Upright remains the separately
disclosed seated review candidate; it is not regenerated here.
"""

import argparse, copy, hashlib, importlib.util, json, math, time, subprocess
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares


LEGS=['FL','FR','RL','RR']
def configure(base,model,work):
 global BASE,MODEL,WORK,read,ref,cfg,m,old,pivot
 BASE=Path(base);MODEL=Path(model);WORK=Path(work);WORK.mkdir(parents=True,exist_ok=True)
 read=lambda p:json.loads(p.read_text())
 spec=importlib.util.spec_from_file_location('reference',MODEL/'motions/walk/reference.py')
 ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
 cfg=read(MODEL/'geometry.json');m=ref.Mechanism(cfg);old=ref.Mechanism(read(BASE/'geometry.json'))
 pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])

def inverse(h,a,beta,seed):
 D=m.O+m.A*np.array([math.cos(m.a0+a),math.sin(m.a0+a)])
 E=D+m.b*np.array([math.cos(beta),math.sin(beta)]);v=E-m.C;d=np.linalg.norm(v)
 co=(m.r*m.r+d*d-m.L*m.L)/(2*m.r*d)
 if abs(co)>1+1e-9:raise ValueError(f'input unreachable cos={co}')
 t=math.atan2(v[1],v[0])-math.acos(float(np.clip(co,-1,1)))-m.t0
 t=seed+math.remainder(t-seed,2*math.pi);q=np.array([h,a,t])
 if abs(math.remainder(m.planar(q)[3]-beta,2*math.pi))>1e-5:raise ValueError('output branch')
 return q

def serial_functions(leg,body,euler):
 S=np.array(m.geom[leg]['shoulder_world']);M=np.array(m.geom[leg]['mechanism_local'])
 B=ref.rz(euler[2])@ref.ry(euler[1])@ref.rx(euler[0]);BS=B@S[:3,:3]
 T0=body+pivot+B@(S[:3,3]-pivot);Mr=M[:3,:3];Mt=M[:3,3]
 def pose(v):
  h,a,b=v;R0=BS@ref.rx(h);R=R0@Mr
  D=m.O+m.A*np.array([math.cos(m.a0+a),math.sin(m.a0+a)])
  return R@ref.ry(m.b0-b),T0+R0@Mt+R@np.r_[D[0],0.,D[1]]
 return pose

def solve(leg,body,euler,oq,seed=None,target_body=None):
 old.body_euler=euler;m.body_euler=euler
 target_body=body if target_body is None else target_body
 xy=old.reference(leg,oq,target_body)[:2];z=old.vertices(leg,oq,target_body)[:,2].min()
 pose=serial_functions(leg,body,euler);point=np.array(m.geom[leg]['foot_reference_local_mm']);hull=m.hulls[leg]
 def residual(v):
  R,T=pose(v);p=R@point+T
  return np.r_[p[:2]-xy,(hull@R[2]+T[2]).min()-z]
 start=np.r_[oq[:2],old.planar(oq)[3]] if seed is None else seed
 fit=least_squares(residual,start,xtol=1e-10,ftol=1e-10,gtol=1e-10,max_nfev=45)
 err=float(np.max(abs(fit.fun)))
 if err>.0001:raise ValueError(f'serial reach residual={err}')
 q=inverse(*fit.x,oq[2]);return q,fit.x,err


def calculate_exact(commands):
 args=argparse.Namespace(step=1,commands=commands)
 results={};start=time.time()
 for path in sorted((BASE/'motions/gestures').glob('*/source.json')):
  cmd=path.parent.name
  if cmd in ['sit','wave','upright'] or args.commands and cmd not in args.commands:continue
  src=read(path);post=path.with_name('posture.json');hp=path.parent/read(post)['contact_hulls_file'] if post.exists() else BASE/'motions/gestures/sit/posture-hulls.npz'
  with np.load(hp) as hs:m.hulls=old.hulls={l:hs['sole_'+l].copy() for l in LEGS}
  prev=[None]*4;bad=[];out=[];errors=[];indices=np.unique(np.r_[np.arange(0,len(src['samples']),args.step),len(src['samples'])-1])
  for n in indices:
   row=src['samples'][n];body=np.array(row['body_translation_world_mm']);euler=np.array(row['body_rotation_euler_xyz_rad']);q=[]
   for i,l in enumerate(LEGS):
    oq=np.array(row['actuator_angles_rad'][i])
    try:
     qq,prev[i],err=solve(l,body,euler,oq,prev[i]);q.append(qq.tolist());errors.append(err)
    except ValueError as exc:
     bad.append(dict(index=int(n),time_s=row['time_s'],leg=l,error=str(exc)));prev[i]=None;q.append(None)
   out.append(q)
  results[cmd]=dict(samples=len(indices),failures=len(bad),witnesses=bad[:12],max_residual_mm=max(errors,default=0))
  print(cmd,results[cmd]['failures'],'/',len(indices)*4,'first',bad[:1], 'elapsed',round(time.time()-start),flush=True)
  (WORK/(cmd+'-scan.json')).write_text(json.dumps(dict(indices=indices.tolist(),q=out,failures=bad)))
  (WORK/'scan-summary.json').write_text(json.dumps(results,indent=2))



def calculate_rest():
 from scipy.optimize import root_scalar
 src=read(BASE/'motions/gestures/rest/source.json');post=read(BASE/'motions/gestures/rest/posture.json')
 hulls=np.load(BASE/'motions/gestures/rest/posture-hulls.npz');m.hulls=old.hulls={l:hulls['sole_'+l] for l in LEGS}
 end=src['samples'][360];body=np.array(end['body_translation_world_mm']);euler=np.array(end['body_rotation_euler_xyz_rad']);deltas=[]
 for i,l in enumerate(LEGS):
  oq=np.array(end['actuator_angles_rad'][i]);beta=old.planar(oq)[3];pose=serial_functions(l,body,euler)
  def floor(a):
   R,T=pose([oq[0],a,beta]);return (m.hulls[l]@R[2]+T[2]).min()-end['sole_clearance_mm'][i]
  a=root_scalar(floor,x0=oq[1],x1=oq[1]+.01,xtol=1e-12).root
  q=inverse(oq[0],a,beta,oq[2]);m.body_euler=euler;old.body_euler=euler
  delta=m.reference(l,q,body)[:2]-old.reference(l,oq,body)[:2];deltas.append(delta)
 print('landing shifts',deltas,flush=True)
 out=[];prev=[None]*4;errors=[]
 for row in src['samples']:
  body=np.array(row['body_translation_world_mm']);euler=np.array(row['body_rotation_euler_xyz_rad']);q=[];old.body_euler=euler;m.body_euler=euler
  for i,l in enumerate(LEGS):
   oq=np.array(row['actuator_angles_rad'][i]);pose=serial_functions(l,body,euler)
   blend=ref.smooth(np.clip((row['time_s']-post['step_start_seconds'][i])/post['step_duration_seconds'],0,1))
   xy=old.reference(l,oq,body)[:2]+blend*deltas[i];z=old.vertices(l,oq,body)[:,2].min();point=np.array(m.geom[l]['foot_reference_local_mm'])
   def residual(v):
    R,T=pose(v);return np.r_[(R@point+T)[:2]-xy,(m.hulls[l]@R[2]+T[2]).min()-z]
   v=np.r_[oq[:2],old.planar(oq)[3]] if prev[i] is None else prev[i]
   fit=least_squares(residual,v,xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=70)
   assert max(abs(fit.fun))<.00001,(row['time_s'],l,fit.fun)
   qq=inverse(*fit.x,oq[2]);prev[i]=fit.x;q.append(qq.tolist());errors.append(max(abs(fit.fun)))
  out.append(q)
 (WORK/'rest-scan.json').write_text(json.dumps(dict(indices=list(range(len(out))),q=out,failures=[],landing_shifts_mm=[d.tolist() for d in deltas],max_error_mm=max(errors))))
 print('Rest solved',len(out),max(errors),flush=True)


def calculate_point():
 src=read(BASE/'motions/gestures/point/source.json');hs=np.load(BASE/'motions/gestures/sit/posture-hulls.npz');m.hulls=old.hulls={l:hs['sole_'+l] for l in LEGS}
 out=[];prev=[None]*4;delta=None;errors=[]
 for row in src['samples']:
  t=row['time_s'];body=np.array(row['body_translation_world_mm']);e=np.array(row['body_rotation_euler_xyz_rad']);oq=np.array(row['actuator_angles_rad']);q=[]
  for i,l in enumerate(LEGS):
   if i!=2 or t<=3 or t>=7.4:
    qq,prev[i],err=solve(l,body,e,oq[i],prev[i]);errors.append(err)
    if i==2 and t==3:delta=prev[i]-np.r_[oq[i,:2],old.planar(oq[i])[3]]
   else:
    u=np.clip((t-3)/1.2,0,1) if t<=6.2 else np.clip((7.4-t)/1.2,0,1)
    v=np.r_[oq[i,:2],old.planar(oq[i])[3]]+delta*(1-ref.smooth(u))
    qq=inverse(*v,oq[i,2]);prev[i]=v
   q.append(qq.tolist())
  out.append(q)
 (WORK/'point-scan.json').write_text(json.dumps(dict(indices=list(range(len(out))),q=out,failures=[],policy='Preserve original carrier and boot orientation at full extension; join the exact remapped lift within the existing extension/retraction phases.',max_ground_error_mm=max(errors))))
 print('Point solved',len(out),'max grounded error',max(errors),flush=True)


def calculate_dead():
 from scipy.optimize import root_scalar
 src=read(BASE/'motions/gestures/dead/source.json');hs=np.load(BASE/'motions/gestures/reviewed-hulls.npz');m.hulls=old.hulls={l:hs['sole_'+l] for l in LEGS};end=src['samples'][-1];body=np.array(end['body_translation_world_mm']);e=np.array(end['body_rotation_euler_xyz_rad']);deltas=[]
 for i,l in enumerate(LEGS):
  oq=np.array(end['actuator_angles_rad'][i]);beta=old.planar(oq)[3];pose=serial_functions(l,body,e)
  if i<2:deltas.append(np.zeros(2));continue
  def floor(a):
   R,T=pose([oq[0],a,beta]);return (m.hulls[l]@R[2]+T[2]).min()-end['sole_clearance_mm'][i]
  a=root_scalar(floor,x0=oq[1],x1=oq[1]+.01,xtol=1e-12).root;q=inverse(oq[0],a,beta,oq[2]);m.body_euler=old.body_euler=e
  deltas.append(m.reference(l,q,body)[:2]-old.reference(l,oq,body)[:2])
 print('Dead front landing shifts',deltas,flush=True)
 collapse=src['phases'][1];out=[];prev=[None]*4;errors=[]
 for row in src['samples']:
  body=np.array(row['body_translation_world_mm']);e=np.array(row['body_rotation_euler_xyz_rad']);old.body_euler=m.body_euler=e;q=[]
  blend=ref.smooth(np.clip((row['time_s']-collapse['start'])/(collapse['end']-collapse['start']),0,1))
  for i,l in enumerate(LEGS):
   oq=np.array(row['actuator_angles_rad'][i]);pose=serial_functions(l,body,e);xy=old.reference(l,oq,body)[:2]+blend*deltas[i];z=old.vertices(l,oq,body)[:,2].min();point=np.array(m.geom[l]['foot_reference_local_mm'])
   def residual(v):
    R,T=pose(v);return np.r_[(R@point+T)[:2]-xy,(m.hulls[l]@R[2]+T[2]).min()-z]
   v=np.r_[oq[:2],old.planar(oq)[3]] if prev[i] is None else prev[i]
   sol=least_squares(residual,v,xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=70);assert max(abs(sol.fun))<1e-5,(row['time_s'],l,sol.fun)
   qq=inverse(*sol.x,oq[2]);prev[i]=sol.x;q.append(qq.tolist());errors.append(max(abs(sol.fun)))
  out.append(q)
 (WORK/'dead-scan.json').write_text(json.dumps(dict(indices=list(range(len(out))),q=out,failures=[],landing_shifts_mm=[d.tolist() for d in deltas],max_error_mm=max(errors),policy='Retain body collapse, supporting boot orientation and rear foot paths. Adjust the front sliding destinations during the existing collapse phase.')))
 print('Dead solved',len(out),max(errors),flush=True)


def calculate_front_support(cmd):
 args=argparse.Namespace(step=1)
 src=read(BASE/f'motions/gestures/{cmd}/source.json');post=BASE/f'motions/gestures/{cmd}/posture.json';hp=post.parent/read(post)['contact_hulls_file'] if post.exists() else BASE/'motions/gestures/sit/posture-hulls.npz'
 with np.load(hp) as hs:m.hulls=old.hulls={l:hs['sole_'+l].copy() for l in LEGS};hull=hs['body'].copy()
 entry=src['phases'][0]['end'];recover=next(x for x in src['phases'] if x['kind']=='return_to_standing');prev=[None]*4;out=[];bodies=[];errors=[];clearances=[];indices=np.unique(np.r_[np.arange(0,len(src['samples']),args.step),len(src['samples'])-1])
 for n in indices:
  row=src['samples'][n];t=row['time_s'];body=np.array(row['body_translation_world_mm']);e=np.array(row['body_rotation_euler_xyz_rad']);oq=np.array(row['actuator_angles_rad']);m.body_euler=old.body_euler=e
  qf=inverse(oq[2,0],oq[2,1],old.planar(oq[2])[3],oq[2,2]);shift=old.reference('RL',oq[2],body)-m.reference('RL',qf,body)
  if cmd=='pushup':
   # Blend the requested downward root correction toward zero as the authored
   # chassis approaches the floor. Both lengths come from FK, not a new limit.
   # clear_new = clear_old**2 / (clear_old + abs(requested_shift_z)).
   clear=row['body_ground_clearance_mm']
   shift[2]=shift[2]*clear/(clear+abs(shift[2]))
  envelope=ref.smooth(np.clip(t/entry,0,1))*(1-ref.smooth(np.clip((t-recover['start'])/(recover['end']-recover['start']),0,1)))
  b=body+shift*envelope;qq=[]
  for i,l in enumerate(LEGS):
   q,prev[i],err=solve(l,b,e,oq[i],prev[i],target_body=body);qq.append(q.tolist());errors.append(err)
  B=ref.rz(e[2])@ref.ry(e[1])@ref.rx(e[0]);clearances.append(float(((hull-pivot)@B[2]+pivot[2]+b[2]).min()))
  out.append(qq);bodies.append(b.tolist())
 print(cmd,'success',len(out),'floor',min(clearances),'step',np.degrees(abs(np.diff(np.array(out),axis=0))).max(),flush=True)
 (WORK/(cmd+'-scan.json')).write_text(json.dumps(dict(indices=indices.tolist(),q=out,bodies=bodies,failures=[],max_error_mm=max(errors),minimum_body_clearance_mm=min(clearances),policy='Preserve carrier and sole orientation of front support, retain all foot paths and torso rotation. Introduce the root correction within the existing entry/recovery phases.')))


def calculate_crouch(cli):
 """Keep the original planner path and -35 mm depth, using current native IK."""
 src=read(BASE/'motions/gestures/crouch/source.json');order=[2,3,0,1];lines=[]
 for row in src['samples']:
  feet=np.c_[row['target_foot_reference_xy_mm'],np.zeros(4)][order]
  values=np.r_[row['body_translation_world_mm'],row['body_rotation_euler_xyz_rad'],feet.ravel(),np.array(row['target_sole_clearance_mm'])[order]]
  lines.append(' '.join(format(v,'.17g') for v in values))
 result=subprocess.run([str(cli)],input='\n'.join(lines)+'\n',text=True,capture_output=True,check=True)
 q=np.array([json.loads(s) for s in result.stdout.splitlines()]).reshape(-1,4,3)[:,order]
 assert len(q)==len(src['samples'])
 (WORK/'crouch-scan.json').write_text(json.dumps(dict(indices=list(range(len(q))),q=q.tolist(),failures=[],policy='Native IK applied to the original Crouch planner targets and body trajectory, including the unchanged -35 mm terminal depth. Entry matches native Stand without retaining the previous geometry solver residual.')))

def package(commands=None):
 from scipy.spatial import ConvexHull
 digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 write=lambda p,v:p.write_text(json.dumps(v,separators=(',',':'),allow_nan=False)+'\n')
 family=MODEL/'motions/gestures';catalog=read(family/'catalog.json');results=read(WORK/'library-results.json') if commands and (WORK/'library-results.json').exists() else {}
 ankle=np.array(read(BASE/'motions/gestures/point/posture.json')['ankle_local_mm']);ankle[1]=0
 for scan in sorted(WORK.glob('*-scan.json')):
  cmd=scan.name.removesuffix('-scan.json');data=read(scan);folder=family/cmd;original=read(BASE/f'motions/gestures/{cmd}/source.json')
  if commands and cmd not in commands:continue
  if data['failures'] or len(data['indices'])!=len(original['samples']):continue
  src=copy.deepcopy(original);post=folder/'posture.json';hp=post.parent/read(post)['contact_hulls_file'] if post.exists() else MODEL/'motions/gestures/sit/posture-hulls.npz'
  with np.load(hp) as hs:m.hulls=old.hulls={l:hs['sole_'+l].copy() for l in LEGS};body_hull=hs['body'].copy()
  oldrows=original['samples'];rows=src['samples'];times=np.array([r['time_s'] for r in rows]);angles=np.array(data['q']);maxxy=0.;maxheight=0.;min_input=180.;witness=None
  for n,(row,prior) in enumerate(zip(rows,oldrows)):
   q=angles[n];body=np.array(data['bodies'][n] if 'bodies' in data else prior['body_translation_world_mm']);m.body_euler=old.body_euler=np.array(prior['body_rotation_euler_xyz_rad']);B=ref.rz(m.body_euler[2])@ref.ry(m.body_euler[1])@ref.rx(m.body_euler[0]);feet=[];contacts=[];zs=[];ids=[];betas=[];heights=[];reaches=[];support=[];requested=[];targets=[];targetz=[]
   for i,l in enumerate(LEGS):
    v=m.vertices(l,q[i],body);k=int(np.argmin(v[:,2]));p=m.reference(l,q[i],body);op=old.reference(l,prior['actuator_angles_rad'][i],prior['body_translation_world_mm']);oz=old.vertices(l,prior['actuator_angles_rad'][i],prior['body_translation_world_mm'])[:,2].min();D,P,E,b,height=m.planar(q[i]);feet.append(p.tolist());contacts.append(v[k].tolist());zs.append(float(v[k,2]));ids.append(k);betas.append(float(b));heights.append(height);reaches.append(float(np.linalg.norm(np.r_[D[0]-m.O[0],0,D[1]-m.O[1]]+ref.ry(m.b0-b)@ankle)))
    input_u=P-m.C;rod=E-P;angle=math.degrees(math.asin(float(np.clip(abs(np.cross(input_u,rod))/(m.r*m.L),0,1))))
    if angle<min_input:min_input=angle;witness=[row['time_s'],l]
    if row['contact_active'][i]:support.extend(v[v[:,2]<v[k,2]+.5])
    requested.append(op[:2].tolist());xy=op[:2].copy();zz=float(oz)
    if cmd=='crouch':xy=np.array(prior['target_foot_reference_xy_mm'][i]);zz=prior['target_sole_clearance_mm'][i]
    elif cmd=='rest':
     po=read(BASE/'motions/gestures/rest/posture.json');u=ref.smooth(np.clip((row['time_s']-po['step_start_seconds'][i])/po['step_duration_seconds'],0,1));xy+=u*np.array(data['landing_shifts_mm'][i])
    elif cmd=='dead':
     phase=src['phases'][1];u=ref.smooth(np.clip((row['time_s']-phase['start'])/(phase['end']-phase['start']),0,1));xy+=u*np.array(data['landing_shifts_mm'][i])
    elif cmd=='point' and i==2 and 3<row['time_s']<7.4:xy=p[:2].copy();zz=float(v[k,2])
    targets.append(xy.tolist());targetz.append(zz);maxxy=max(maxxy,float(np.linalg.norm(p[:2]-op[:2])));maxheight=max(maxheight,abs(v[k,2]-oz))
   worldbody=(body_hull-pivot)@B.T+pivot+body;clear=float(worldbody[:,2].min());touch=clear<=.0005;patch=worldbody[worldbody[:,2]<.5] if touch else np.empty((0,3));support.extend(patch);com=body+pivot
   try:margin=ref.margin(com[:2],support) if len(support)>=3 else None
   except Exception:margin=None
   row.update(actuator_angles_rad=q.tolist(),body_translation_world_mm=body.tolist(),body_position_world_mm=com.tolist(),assumed_com_world_mm=com.tolist(),foot_bolt_world_mm=feet,contact_world_mm=contacts,sole_clearance_mm=zs,contact_vertex_index=ids,passive_beta_rad=betas,body_ground_clearance_mm=clear,body_contact_active=touch,body_contact_polygon_world_mm=patch.tolist(),support_margin_mm=margin,minimum_closure_height_mm=float(min(heights)),arm_reach_mm=reaches,target_foot_reference_xy_mm=targets,target_sole_clearance_mm=targetz,baseline_foot_reference_xy_mm=requested)
  validation=dict(command=cmd,geometry_id=cfg['geometry_id'],samples=len(rows),duration_s=times[-1],sample_hz=120,minimum_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),minimum_closure_triangle_height_mm=min(r['minimum_closure_height_mm'] for r in rows),minimum_input_toggle_clearance_deg=min_input,input_toggle_witness_time_and_cad_leg=witness,maximum_adjacent_joint_step_degrees=float(np.degrees(abs(np.diff(angles,axis=0))).max()),peak_joint_speed_deg_s=float(np.degrees(abs(np.gradient(angles,times,axis=0))).max()),joint_min_deg=np.degrees(angles.min((0,1))).tolist(),joint_max_deg=np.degrees(angles.max((0,1))).tolist(),maximum_body_translation_difference_mm=float(np.max(np.linalg.norm(np.array([r['body_translation_world_mm'] for r in rows])-np.array([r['body_translation_world_mm'] for r in oldrows]),axis=1))),maximum_foot_xy_difference_mm=maxxy,maximum_sole_height_difference_mm=maxheight,timing_preserved=True,contact_schedule_preserved=True,body_rotations_preserved=True,hardware_qualified=False,collision_checked=False,calibration_qualified=False,policy=data.get('policy','Preserve original foot XY, whole-sole height, body path, timing and contacts.'))
  oldmanifest=read(BASE/f'motions/gestures/{cmd}/manifest.json');validation['motion_end_s']=oldmanifest['source_validation'].get('motion_end_s',oldmanifest.get('motion_end_seconds',oldmanifest['duration_seconds']))
  if cmd=='pushup':validation['policy']='Retain all foot paths and torso rotations. Refit root translation from the shortened front support; smoothly reduce the downward correction using the recorded chassis clearance. Existing entry and recovery phase timing is unchanged.'
  remap=dict(geometry_sha256=digest(MODEL/'geometry.json'),baseline_geometry_sha256=digest(BASE/'geometry.json'),baseline_source_sha256=digest(BASE/f'motions/gestures/{cmd}/source.json'),generator='docs/gait-research/seated-support-20261005/library-remap.py',qualification='Offline geometry and sampler candidate. No calibration or runtime limits changed.',policy=validation['policy'])
  src['metadata'].pop('calibrated_path_fit',None);src['metadata']['configuration']['geometry_id']=cfg['geometry_id'];src['metadata']['linkage_remap']=remap;src['validation']=validation;write(folder/'source.json',src);write(folder/'validation.json',validation)
  if post.exists():
   p=read(post);p['mechanism_geometry_sha256']=digest(MODEL/'geometry.json');p.pop('calibrated_path_fit',None);p['linkage_remap']=remap;p['angle_scope']='Firmware geometric offsets; physical calibration and assembly mounting unqualified.'
   if cmd=='rest':p['terminal_solver_seed_rad']={l:rows[360]['actuator_angles_rad'][i] for i,l in enumerate(LEGS)}
   if cmd=='point':p['extended_joint_offsets_rad']=rows[600]['actuator_angles_rad'][2];p['nominal_link_lengths_mm']=[35,55];p['extension_waypoints_rad']=[rows[360]['actuator_angles_rad'][2],rows[504]['actuator_angles_rad'][2]];p['extension_interpolation']='Recorded 120 Hz carrier/boot-orientation remap; source.json is the execution source.'
   if cmd=='bow':p['extended_joint_offsets_rad']={l:rows[360]['actuator_angles_rad'][i] for i,l in enumerate(LEGS) if i>=2};p['held_body_x_mm']=rows[360]['body_translation_world_mm'][0]
   write(post,p)
  reviewed=folder/'reviewed.json'
  if reviewed.exists():
   rev=read(reviewed)
   for r in rev['samples']:
    row=rows[round(r['time_s']*120)];r['body']=row['body_translation_world_mm'];r['q']=row['actuator_angles_rad'];r['contact']=row['contact_active']
   rev.pop('summary',None);rev['geometry_sha256']=digest(MODEL/'geometry.json');rev['linkage_remap']=remap;write(reviewed,rev);src['metadata']['authoring_sha256']=digest(reviewed);write(folder/'source.json',src)
  manifest=read(folder/'manifest.json');schema=read(folder/'schema.json');contract=read(folder/'execution-contract.json');manifest.update(geometry_sha256=digest(MODEL/'geometry.json'),geometry_id=cfg['geometry_id'],source_sha256=digest(folder/'source.json'),source_validation=validation,entry_actuator_angles_rad=rows[0]['actuator_angles_rad'],final_actuator_angles_rad=rows[-1]['actuator_angles_rad'],generated_utc='2026-10-06')
  if post.exists():manifest['posture_sha256']=digest(post)
  if reviewed.exists():manifest['reviewed_sha256']=digest(reviewed)
  terminal=round(manifest.get('semantic_end_seconds',manifest['duration_seconds'])*120)
  if 'semantic_end_seconds' in manifest:manifest['semantic_final_actuator_angles_rad']=rows[terminal]['actuator_angles_rad'];manifest['playlist_final_actuator_angles_rad']=rows[-1]['actuator_angles_rad']
  if 'body_target' in manifest:manifest['body_target']={'position_mm':rows[terminal]['body_position_world_mm'],'euler_xyz_rad':rows[terminal]['body_rotation_euler_xyz_rad']}
  write(folder/'manifest.json',manifest);schema['geometry_id']=cfg['geometry_id'];write(folder/'schema.json',schema);contract['geometry_id']=cfg['geometry_id'];contract['entry']['joint_angles_rad']=rows[0]['actuator_angles_rad'];contract['completion']['joint_angles_rad']=rows[terminal]['actuator_angles_rad']
  for f in contract['source_files']:
   name=Path(f['path']).name
   if (folder/name).exists():f['sha256']=digest(folder/name)
  contract['source_qualification']={'hardware_qualified':False,'collision_checked':False,'calibration_qualified':False};write(folder/'execution-contract.json',contract)
  entry=next(x for x in catalog['commands'] if x['command']==cmd)
  for name in entry['sha256']:
   if (folder/name).exists():entry['sha256'][name]=digest(folder/name)
  results[cmd]=validation;print(cmd,'step',validation['maximum_adjacent_joint_step_degrees'],'floor',validation['minimum_sole_height_mm'],'body',validation['minimum_body_ground_clearance_mm'],'input',min_input,flush=True)
 write(family/'catalog.json',catalog);(WORK/'library-results.json').write_text(json.dumps(results,indent=2))


def refresh_documents():
 """Bind the complete remapped library, including seated-source dependencies."""
 digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 write=lambda p,v:p.write_text(json.dumps(v,separators=(',',':'),allow_nan=False)+'\n')
 family=MODEL/'motions/gestures';catalog=read(family/'catalog.json')
 for item in catalog['commands']:
  folder=family/item['command'];source=read(folder/'source.json');meta=source['metadata']
  meta['configuration']['geometry_id']=cfg['geometry_id']
  inherited={k:meta.pop(k) for k in list(meta) if k.startswith('native_')}
  if inherited:meta['baseline_native_recording']=inherited
  if 'linkage_remap' in meta:meta['generator']=meta['linkage_remap']['generator']
  write(folder/'source.json',source)
 for item in catalog['commands']:
  folder=family/item['command'];path=folder/'posture.json'
  if path.exists():
   posture=read(path)
   if 'base_motion' in posture:
    base=posture['base_motion'];base['source_sha256']=digest(folder/base['source_file']);base['posture_sha256']=digest(folder/base['posture_file']);write(path,posture)
  manifest=read(folder/'manifest.json');manifest['source_sha256']=digest(folder/'source.json')
  if path.exists():manifest['posture_sha256']=digest(path)
  write(folder/'manifest.json',manifest)
  contract=read(folder/'execution-contract.json')
  for record in contract['source_files']:
   path=folder/Path(record['path']).name
   if path.exists():record['sha256']=digest(path)
  write(folder/'execution-contract.json',contract)
  for name in item['sha256']:
   path=folder/name
   if path.exists():item['sha256'][name]=digest(path)
 write(family/'catalog.json',catalog)

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--baseline',type=Path,required=True)
 parser.add_argument('--model',type=Path,required=True)
 parser.add_argument('--work',type=Path,required=True)
 parser.add_argument('--solve-cli',type=Path,required=True,help='v2_walk_solve built with the candidate geometry')
 parser.add_argument('--package-only',action='store_true')
 args=parser.parse_args();configure(args.baseline,args.model,args.work)
 if not args.package_only:
  calculate_exact(['celebrate','curious','cute','dance','freaky','lay_down','sad','shake','shrug','stretch','surprised','swim','worm'])
  calculate_rest();calculate_point();calculate_dead()
  for command in ['bow','nod','pushup']:calculate_front_support(command)
  calculate_crouch(args.solve_cli)
 package()
 refresh_documents()
if __name__=='__main__':main()
