"""Body/sole gesture solver; mm and geometric radians, no hardware output."""
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

class Motion:
 def __init__(self,cfg):
  self.cfg=cfg;self.hz=cfg['sample_hz'];self.rows=[];self.phases=[];self.now=0.;self.correction=0.;self.transfers=0
  self.body=np.array([0.,0.,max(-k.sole_world(l,np.zeros(3),np.zeros(3))[:,2].min() for l in LEGS)])
  self.euler=np.zeros(3);self.R=rotation(self.euler);self.q=np.zeros((4,3));self.com=k.configured_body_com(cfg)
  self.mesh=np.load(P/'body-samples.npz')['vertices'];self.state={}
  for i,l in enumerate(LEGS):
   vv=self.sole(i);idx=int(vv[:,2].argmin());anchor=vv[idx].copy();anchor[2]=0.;self.state[l]=dict(index=idx,anchor=anchor)
  self.record('standing',0.)
 def foot(self,i):
  bolt,r,b=k.foot_pose(LEGS[i],self.q[i],np.zeros(3));return self.body+self.R@bolt,self.R@r,b
 def sole(self,i):
  bolt,r,_=self.foot(i);return (k.SOLE[LEGS[i]]-k.F0[LEGS[i]])@r.T+bolt
 def record(self,phase,u,belly=False,sliding=None):
  feet=[];contacts=[];clear=[];errors=[];betas=[];indices=[];carrier=[];active=[]
  for i,l in enumerate(LEGS):
   bolt,_,beta=self.foot(i);vv=self.sole(i);st=self.state[l];idx=int(vv[:,2].argmin()) if belly else st['index'];anchor=vv[idx] if belly else st['anchor']
   feet.append(bolt.tolist());betas.append(beta);clear.append(float(vv[:,2].min()));contacts.append(anchor.tolist());indices.append(idx);active.append(not belly)
   errors.append(None if belly else float(np.linalg.norm(vv[idx]-anchor)))
   par=k.g.PARAMETERS['legs'][l];od=np.array(k.g.fk(l,*self.q[i])['planar_pivots']['D'])-par['pivots_xy_mm']['O'];carrier.append(math.degrees(math.atan2(od[1]*math.cos(self.q[i,0]),od[0]))%360)
  world_com=self.body+self.R@self.com;support=np.array(self.cfg['body_rest_support_polygon_world_mm'])[:,:2] if belly else np.array(contacts)[:,:2]
  margin=k.margin(support,world_com[:2]);low=float((self.mesh@self.R[2]+self.body[2]).min())
  if min(clear)<-1e-5:raise ValueError(('sole penetration',self.now,min(clear)))
  if margin<5.:raise ValueError(('support margin',self.now,margin))
  if low<-1e-5 and not self.cfg.get('allow_known_body_reference_overlap',False):raise ValueError(('body clearance',self.now,low))
  self.rows.append(dict(time_s=self.now,phase=phase,phase_fraction=u,cycle=-1,swing_leg=None,
   body_position_world_mm=self.body.tolist(),body_rotation_euler_xyz_rad=self.euler.tolist(),body_orientation_world_quaternion_wxyz=quaternion(self.euler),
   actuator_angles_rad=self.q.tolist(),passive_beta_rad=betas,foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_active=active,
   contact_vertex_index=indices,sole_clearance_mm=clear,stance_constraint_error_mm=errors,assumed_com_world_mm=world_com.tolist(),support_margin_mm=margin,
   body_ground_clearance_mm=low,body_contact_active=belly,support_source='rear_cover_and_visor' if belly else 'feet',part023_OD_angle_from_forward_degrees=carrier,
   body_contact_polygon_world_mm=np.column_stack([support,np.zeros(len(support))]).tolist() if belly else [],
   contact_motion_model=['airborne']*4 if belly else [('intentional_slide' if sliding is not None and np.linalg.norm(sliding[i])>0 else 'rolling') for i in range(4)]))
 def solve(self,body,euler):
  self.body=body;self.euler=euler;self.R=rotation(euler)
  for i,l in enumerate(LEGS):
   st=self.state[l]
   def inv(anchor,idx):return k.inverse(l,self.R.T@(anchor-self.body),np.zeros(3),self.q[i],k.SOLE[l][idx])
   self.q[i]=inv(st['anchor'],st['index'])
   for _ in range(16):
    vv=self.sole(i);idx=int(vv[:,2].argmin());low=vv[idx,2]
    if low>=-2e-8:break
    self.correction=max(self.correction,float(-low));self.transfers+=1;anchor=vv[idx].copy();anchor[2]=0.;self.q[i]=inv(anchor,idx);st=dict(index=idx,anchor=anchor)
   else:raise ValueError(('rolling failed',l))
   self.state[l]=st
 def pose(self,body,euler_deg,duration,name,front_slide=0.):
  b0=self.body.copy();e0=self.euler.copy();e1=np.radians(euler_deg);n=round(duration*self.hz);start=self.now;first=len(self.rows)-1;last_u=0.
  self.phases.append(dict(start=start,end=start+n/self.hz,kind=name));slide=np.zeros((4,3));slide[2:,0]=front_slide
  for j in range(1,n+1):
   u=k.smooth(j/n)
   for i,l in enumerate(LEGS):self.state[l]['anchor']+=slide[i]*(u-last_u)
   last_u=u;self.solve(b0+(np.array(body)-b0)*u,e0+(e1-e0)*u);self.now=round(start*self.hz+j)/self.hz;self.record(name,j/n,sliding=slide)
  return copy.deepcopy(self.rows[first:])
 def hold(self,duration,name):
  start=self.now;n=round(duration*self.hz);self.phases.append(dict(start=start,end=start+n/self.hz,kind=name))
  for j in range(1,n+1):
   r=copy.deepcopy(self.rows[-1]);r.update(time_s=round(start*self.hz+j)/self.hz,phase=name,phase_fraction=j/n);self.rows.append(r)
  self.now=self.rows[-1]['time_s']
 def reverse(self,template,name):
  start=self.now;self.phases.append(dict(start=start,end=start+(len(template)-1)/self.hz,kind=name))
  for j,r in enumerate(list(reversed(template))[1:],1):
   r=copy.deepcopy(r);r.update(time_s=round(start*self.hz+j)/self.hz,phase=name,phase_fraction=j/(len(template)-1));self.rows.append(r)
  self.now=self.rows[-1]['time_s'];r=self.rows[-1];self.body=np.array(r['body_position_world_mm']);self.euler=np.array(r['body_rotation_euler_xyz_rad']);self.R=rotation(self.euler);self.q=np.array(r['actuator_angles_rad'])
  for i,l in enumerate(LEGS):self.state[l]=dict(index=r['contact_vertex_index'][i],anchor=np.array(r['contact_world_mm'][i]))
 def joint_segment(self,target,duration,name):
  q0=self.q.copy();n=round(duration*self.hz);start=self.now;first=len(self.rows)-1;self.phases.append(dict(start=start,end=start+n/self.hz,kind=name))
  for j in range(1,n+1):
   self.q=q0+(target-q0)*k.smooth(j/n);self.now=round(start*self.hz+j)/self.hz;self.record(name,j/n,belly=True)
  return copy.deepcopy(self.rows[first:])
 def output(self):
  cfg=self.cfg;rows=self.rows;hz=self.hz;qd=np.degrees([r['actuator_angles_rad'] for r in rows]);speed=np.gradient(qd,1/hz,axis=0);acc=np.gradient(speed,1/hz,axis=0)
  for axis,key in enumerate(['h','alpha','theta']):
   lo,hi=cfg['geometric_research_angle_bounds_degrees'][key]
   if qd[:,:,axis].min()<lo-1e-6 or qd[:,:,axis].max()>hi+1e-6:raise ValueError(('bound',key,qd[:,:,axis].min(),qd[:,:,axis].max(),lo,hi))
  v=dict(duration_s=self.now,motion_end_s=cfg['face_cues'][-1]['time_s'],sample_hz=hz,samples=len(rows),
   actuator_min_degrees=qd.min(0).tolist(),actuator_max_degrees=qd.max(0).tolist(),actuator_peak_speed_degrees_s=np.abs(speed).max(0).tolist(),actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),
   minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),minimum_stance_contacts=min(sum(r['contact_active']) for r in rows),maximum_rolling_normal_correction_mm=self.correction,solved_rolling_transfers=self.transfers,
   max_stance_material_vertex_constraint_error_mm=max((e for r in rows for e in r['stance_constraint_error_mm'] if e is not None),default=0.),minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
   maximum_adjacent_joint_step_degrees=float(abs(np.diff(qd,axis=0)).max()),final_joint_return_error_degrees=float(abs(qd[-1]-qd[0]).max()),research_angle_bounds_satisfied=True,
   complete_body_floor_check_passed=min(r['body_ground_clearance_mm'] for r in rows)>=-1e-5,body_support_contacts='Rear bottom-cover edge and front visor low point',body_contact_strength_verified=False,fourbar_branch_preserved=True,belly_support_required=any(r['body_contact_active'] for r in rows),collision_checked=False,hardware_servo_limits_verified=False,measured_mass_balance_verified=False,hardware_qualified=False)
  return dict(metadata=dict(configuration=cfg,leg_order=LEGS,joint_order=['h_Part002','alpha_Part006','theta_Part005'],position_units='mm',angle_units='radian',time_units='second',world_axes='X forward, Y left, Z up; negative body Y pitch lifts front.',source_geometry=k.g.PARAMETERS['source_blend']),phases=self.phases,samples=rows,validation=v)

def configuration(command,description):
 base=json.loads((P/'base-config.json').read_text());return dict(command=command,name=description,display_label=command.upper(),sample_hz=120,preview_fps=24,gait_start_frame=1,existing_animation_end_frame=0,source_blend='Before-Motion-Batch.blend',output_blend='Ainekio-Motion-Batch.blend',scene_name='AINEKIO - Motion Batch',com=base['com'],geometric_research_angle_bounds_degrees=base['geometric_research_angle_bounds_degrees'],part023_forward_limit_degrees=None,face_cues=[],completion='Return to exact recorded standing and hold; this matches the V1 final stand frame.',adaptation=description,contact_model='Four measured convex soles roll at fixed material vertices between feature transfers. Prescribed front slides are explicitly labelled; physical friction is unverified.',hardware_qualified=False)

def save(data):
 for name,value in [('source.json',data),('config.json',data['metadata']['configuration']),('validation.json',data['validation'])]:(P/name).write_text(json.dumps(value,indent=None if name=='source.json' else 2)+'\n')
 print(json.dumps(data['validation'],indent=2))
