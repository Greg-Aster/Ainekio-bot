"""Measured four-bar/sole research motion tools; no physical servo coordinates."""
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
def hull(points):
 pts=sorted(set(tuple(round(float(x),7) for x in p) for p in points))
 def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
 def half(seq):
  out=[]
  for p in seq:
   while len(out)>1 and cross(out[-2],out[-1],p)<=0:out.pop()
   out.append(p)
  return out
 return np.array(half(pts)[:-1]+half(reversed(pts))[:-1])

class Motion:
 def __init__(self,command,signature,settings=None):
  base=json.loads((P/'base-config.json').read_text());self.mesh=np.load(P/'body-samples.npz')['vertices']
  self.belly_z=float(-self.mesh[:,2].min());self.belly_polygon=hull(self.mesh[self.mesh[:,2]<-self.belly_z+.01,:2])
  self.cfg=dict(command=command,display_label=command.upper(),sample_hz=120,preview_fps=24,gait_start_frame=1,existing_animation_end_frame=0,source_blend='Before-Motion-Batch.blend',output_blend='Ainekio-Motion-Batch.blend',scene_name='AINEKIO - Motion Commands',com=base['com'],geometric_research_angle_bounds_degrees=copy.deepcopy(base['geometric_research_angle_bounds_degrees']),part023_forward_limit_degrees=None,face_cues=[dict(time_s=0,name=command,mode='boomerang' if command=='dead' else 'once',fps=1)],adaptation=signature,completion='Return to standing after the gesture; hold the final pose.',contact_model='Measured convex sole rolling: fixed material vertex between feature transfers. Belly support is explicit when selected; no friction or dynamics simulation.',hardware_qualified=False)
  self.cfg.update(settings or {});self.cfg['adaptation']=signature;self.hz=self.cfg['sample_hz'];self.com=k.configured_body_com(self.cfg)
  z=max(-k.sole_world(l,np.zeros(3),np.zeros(3))[:,2].min() for l in LEGS)
  self.body=np.array([0.,0.,z]);self.euler=np.zeros(3);self.R=rotation(self.euler);self.q=np.zeros((4,3));self.state={};self.rows=[];self.phases=[];self.now=0.;self.transfers=0;self.max_correction=0.;self.contacts=[True]*4;self.belly=False
  for i,l in enumerate(LEGS):
   vv=self.sole(i);idx=int(vv[:,2].argmin());a=vv[idx].copy();a[2]=0.;self.state[l]=dict(index=idx,anchor=a)
  self.record(0,'standing',0)
 def foot(self,i):
  bolt,r,beta=k.foot_pose(LEGS[i],self.q[i],np.zeros(3));return self.body+self.R@bolt,self.R@r,beta
 def sole(self,i):
  bolt,r,_=self.foot(i);return (k.SOLE[LEGS[i]]-k.F0[LEGS[i]])@r.T+bolt
 def record(self,t,phase,u):
  feet=[];betas=[];clear=[];ground=[];idxs=[];errs=[];odangles=[]
  for i,l in enumerate(LEGS):
   bolt,_,beta=self.foot(i);vv=self.sole(i);idx=int(vv[:,2].argmin());st=self.state[l]
   feet.append(bolt.tolist());betas.append(beta);clear.append(float(vv[idx,2]));idxs.append(st['index'] if self.contacts[i] else idx);ground.append((st['anchor'] if self.contacts[i] else vv[idx]).tolist());errs.append(float(np.linalg.norm(vv[st['index']]-st['anchor'])) if self.contacts[i] else None)
   p=k.g.PARAMETERS['legs'][l];od=np.array(k.g.fk(l,*self.q[i])['planar_pivots']['D'])-p['pivots_xy_mm']['O'];odangles.append(math.degrees(math.atan2(od[1]*math.cos(self.q[i,0]),od[0]))%360)
  world_com=self.body+self.R@self.com;low=float((self.mesh@self.R[2]+self.body[2]).min())
  support=[ground[i][:2] for i,x in enumerate(self.contacts) if x];belly_poly=[]
  if self.belly:
   if hasattr(self,'support_polygon_world'):belly_poly=self.support_polygon_world
   else:
    if np.linalg.norm(self.euler)>1e-8:raise ValueError('Flat belly support requires zero body rotation')
    belly_poly=np.column_stack([self.belly_polygon+self.body[:2],np.zeros(len(self.belly_polygon))]).tolist()
   support += [p[:2] for p in belly_poly]
  margin=k.margin(hull(support),world_com[:2]) if len(support)>=3 else -1e6
  if min(clear)<-1e-5:raise ValueError(('sole penetration',t,min(clear)))
  if low < -1e-5:raise ValueError(('body penetration',t,low))
  if margin<1.:raise ValueError(('insufficient assumed COM margin',phase,t,margin))
  self.rows.append(dict(time_s=t,phase=phase,phase_fraction=u,cycle=-1,swing_leg=next((LEGS[i] for i,c in enumerate(self.contacts) if not c),None),body_position_world_mm=self.body.tolist(),body_rotation_euler_xyz_rad=self.euler.tolist(),body_orientation_world_quaternion_wxyz=quaternion(self.euler),actuator_angles_rad=self.q.tolist(),passive_beta_rad=betas,foot_bolt_world_mm=feet,contact_world_mm=ground,contact_active=self.contacts[:],contact_vertex_index=idxs,stance_constraint_error_mm=errs,sole_clearance_mm=clear,assumed_com_world_mm=world_com.tolist(),support_margin_mm=margin,body_ground_clearance_mm=low,body_contact_active=self.belly,body_contact_polygon_world_mm=belly_poly,support_source=('belly_and_feet' if any(self.contacts) else 'belly') if self.belly else 'feet',part023_OD_angle_from_forward_degrees=odangles))
 def roll(self,i):
  l=LEGS[i];st=self.state[l]
  def inverse(a,idx):return k.inverse(l,self.R.T@(a-self.body),np.zeros(3),self.q[i],k.SOLE[l][idx])
  self.q[i]=inverse(st['anchor'],st['index'])
  for _ in range(16):
   vv=self.sole(i);idx=int(vv[:,2].argmin());low=vv[idx,2]
   if low>=-2e-8:break
   self.max_correction=max(self.max_correction,float(-low));self.transfers+=1;a=vv[idx].copy();a[2]=0.;self.q[i]=inverse(a,idx);st=dict(index=idx,anchor=a)
  else:raise ValueError(('rolling convergence',l))
  self.state[l]=st
 def segment(self,duration,name,fn):
  n=round(duration*self.hz);start=len(self.rows)-1;t0=self.now;self.phases.append(dict(start=t0,end=t0+n/self.hz,kind=name))
  for j in range(1,n+1):
   fn(j/n);self.record(round(t0*self.hz+j)/self.hz,name,j/n)
  self.now=self.rows[-1]['time_s'];return copy.deepcopy(self.rows[start:])
 def pose(self,pos,euler,duration,name):
  p0=self.body.copy();e0=self.euler.copy();pos=np.array(pos);euler=np.array(euler)
  def step(u):
   u=k.smooth(u);self.body=p0+(pos-p0)*u;self.euler=e0+(euler-e0)*u;self.R=rotation(self.euler)
   for i,c in enumerate(self.contacts):
    if c:self.roll(i)
  return self.segment(duration,name,step)
 def joints(self,target,duration,name):
  q0=self.q.copy();target=np.array(target)
  return self.segment(duration,name,lambda u:setattr(self,'q',q0+(target-q0)*k.smooth(u)))
 def hold(self,duration,name):return self.segment(duration,name,lambda u:None)
 def restore(self,row):
  self.body=np.array(row['body_position_world_mm']);self.euler=np.array(row['body_rotation_euler_xyz_rad']);self.R=rotation(self.euler);self.q=np.array(row['actuator_angles_rad']);self.contacts=row['contact_active'][:];self.belly=row['body_contact_active']
  self.state={l:dict(index=row['contact_vertex_index'][i],anchor=np.array(row['contact_world_mm'][i])) for i,l in enumerate(LEGS)}
 def recorded(self,template,name):
  n=len(template)-1;t0=self.now;self.phases.append(dict(start=t0,end=t0+n/self.hz,kind=name))
  for j,r in enumerate(template[1:],1):
   r=copy.deepcopy(r);r.update(time_s=round(t0*self.hz+j)/self.hz,phase=name,phase_fraction=j/n);self.rows.append(r)
  self.now=self.rows[-1]['time_s'];self.restore(self.rows[-1])
 def belly_support(self):
  self.belly=True;self.cfg['bottom_contact_polygon_body_xy_mm']=self.belly_polygon.tolist();self.cfg['bottom_contact_geometry']='CRAWL | Body - Bottom Cover - Compact';self.cfg['target_body_height_mm']=self.belly_z;self.cfg['geometric_research_angle_bounds_degrees']['h']=[-95.,95.];self.cfg['shoulder_bounds_basis']='90 degree Swim research envelope; geometric only, uncalibrated electrical travel.'
 def finalize(self,motion_end=None):
  self.cfg['face_cues'] = [dict(time_s=0.,name=self.cfg['command'],mode='boomerang' if self.cfg['command']=='dead' else 'once',fps=1),dict(time_s=self.now if motion_end is None else motion_end,name='stand',mode='once',fps=1)]
  rows=self.rows;angles=np.degrees([r['actuator_angles_rad'] for r in rows]);speed=np.gradient(angles,1/self.hz,axis=0);acc=np.gradient(speed,1/self.hz,axis=0)
  for j,key in enumerate(['h','alpha','theta']):
   lo,hi=self.cfg['geometric_research_angle_bounds_degrees'][key]
   if angles[:,:,j].min()<lo-1e-6 or angles[:,:,j].max()>hi+1e-6:raise ValueError(('range',key,angles[:,:,j].min(),angles[:,:,j].max(),lo,hi))
  beta=np.array([r['passive_beta_rad'] for r in rows]);closure=0.
  for r in rows[::4]:
   for i,l in enumerate(LEGS):
    fk=k.g.fk(l,*r['actuator_angles_rad'][i]);p=k.g.PARAMETERS['legs'][l];closure=max(closure,abs(np.linalg.norm(np.array(fk['planar_pivots']['P'])-fk['planar_pivots']['Q'])-p['lengths_mm']['coupler_PQ']))
  v=dict(duration_s=rows[-1]['time_s'],motion_end_s=self.now if motion_end is None else motion_end,sample_hz=self.hz,samples=len(rows),actuator_min_degrees=angles.min(0).tolist(),actuator_max_degrees=angles.max(0).tolist(),actuator_peak_speed_degrees_s=np.abs(speed).max(0).tolist(),actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),maximum_adjacent_joint_step_degrees=float(abs(np.diff(angles,axis=0)).max()),maximum_adjacent_passive_beta_step_degrees=float(np.degrees(abs(np.diff(beta,axis=0)).max())),fourbar_maximum_coupler_closure_error_mm=closure,final_joint_return_error_degrees=float(abs(angles[-1]-angles[0]).max()),minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),minimum_stance_contacts=min(sum(r['contact_active']) for r in rows),minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),max_stance_material_vertex_constraint_error_mm=max((e for r in rows for e in r['stance_constraint_error_mm'] if e is not None),default=0.),maximum_rolling_normal_correction_mm=self.max_correction,rolling_transfers=self.transfers,research_angle_bounds_satisfied=True,collision_checked=False,hardware_servo_limits_verified=False,measured_mass_balance_verified=False,body_contact_strength_verified=False,hardware_qualified=False)
  data=dict(metadata=dict(configuration=self.cfg,leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],position_units='mm',angle_units='radian',time_units='second',world_axes='X forward, Y left, Z up',source_geometry=k.g.PARAMETERS['source_blend']),phases=self.phases,samples=rows,validation=v)
  for name,value in [('source.json',data),('config.json',self.cfg),('validation.json',v)]:
   (P/name).write_text(json.dumps(value,indent=None if name=='source.json' else 2)+'\n')
  print(json.dumps(v,indent=2));return data
