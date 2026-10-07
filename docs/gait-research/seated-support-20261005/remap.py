import json,sys,math,copy,importlib.util,os
from pathlib import Path
import numpy as np
from scipy.optimize import root_scalar,least_squares
BASE=Path(os.environ['AINEKIO_REMAP_BASE']);ROOT=Path(os.environ['AINEKIO_REMAP_MODEL']);WORK=Path(os.environ['AINEKIO_REMAP_WORK'])
spec=importlib.util.spec_from_file_location('reference',ROOT/'motions/walk/reference.py');ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
legs=['FL','FR','RL','RR'];read=lambda p:json.loads(p.read_text());cfg=read(ROOT/'geometry.json');m=ref.Mechanism(cfg);old=ref.Mechanism(read(BASE/'geometry.json'));hulls=np.load(BASE/'motions/gestures/sit/posture-hulls.npz');m.hulls=old.hulls={l:hulls['sole_'+l] for l in legs};pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm']);ankle=np.array(read(BASE/'motions/gestures/point/posture.json')['ankle_local_mm']);ankle[1]=0

def inverse(h,a,beta,seed):
 D=m.O+m.A*np.array([math.cos(m.a0+a),math.sin(m.a0+a)]);E=D+m.b*np.array([math.cos(beta),math.sin(beta)]);v=E-m.C;d=np.linalg.norm(v);co=(m.r*m.r+d*d-m.L*m.L)/(2*m.r*d)
 if abs(co)>1+1e-8:raise ValueError('input unreachable')
 co=float(np.clip(co,-1,1))
 t=math.atan2(v[1],v[0])-math.acos(co)-m.t0;t=seed+math.remainder(t-seed,2*math.pi);q=np.array([h,a,t])
 if abs(math.remainder(m.planar(q)[3]-beta,2*math.pi))>1e-5:raise ValueError('output branch')
 return q

def metrics(row,q,body=None):
 row=copy.deepcopy(row);body=np.array(row['body_translation_world_mm']) if body is None else body;m.body_euler=np.array(row['body_rotation_euler_xyz_rad']);B=ref.rz(m.body_euler[2])@ref.ry(m.body_euler[1])@ref.rx(m.body_euler[0]);feet=[];vs=[];contacts=[];indices=[];zs=[];beta=[];height=[];reach=[];support=[]
 for i,l in enumerate(legs):
  v=m.vertices(l,q[i],body);idx=int(np.argmin(v[:,2]));p=m.reference(l,q[i],body);D,P,E,b,h=m.planar(q[i]);feet.append(p.tolist());contacts.append(v[idx].tolist());indices.append(idx);zs.append(float(v[idx,2]));beta.append(b);height.append(h);reach.append(float(np.linalg.norm(np.r_[D[0]-m.O[0],0,D[1]-m.O[1]]+ref.ry(m.b0-b)@ankle)))
  if row['contact_active'][i]:support.extend(v[v[:,2]<v[idx,2]+.5])
 clear=float(((hulls['body']-pivot)@B.T+pivot+body)[:,2].min());com=body+pivot
 row.update(actuator_angles_rad=q.tolist(),body_translation_world_mm=body.tolist(),body_position_world_mm=com.tolist(),assumed_com_world_mm=com.tolist(),foot_bolt_world_mm=feet,contact_world_mm=contacts,contact_vertex_index=indices,sole_clearance_mm=zs,passive_beta_rad=beta,minimum_closure_height_mm=min(height),body_ground_clearance_mm=clear,support_margin_mm=ref.margin(com[:2],support),arm_reach_mm=reach,target_foot_reference_xy_mm=[p[:2] for p in feet],target_sole_clearance_mm=zs)
 return row

def sit():
 src=read(BASE/'motions/gestures/sit/source.json');end=src['samples'][360];body=np.array(end['body_translation_world_mm']);m.body_euler=old.body_euler=np.array(end['body_rotation_euler_xyz_rad']);post=read(BASE/'motions/gestures/sit/posture.json');oldq=np.array(end['actuator_angles_rad']);deltas=[];endq=[]
 for i,l in enumerate(legs[:2]):
  beta=old.planar(oldq[i])[3]
  def fun(a):
   # Evaluate lower sole height with requested beta; no four-bar approximation.
   S=np.array(m.geom[l]['shoulder_world']);M=np.array(m.geom[l]['mechanism_local']);B=ref.ry(m.body_euler[1]);R=B@S[:3,:3]@ref.rx(oldq[i,0])@M[:3,:3];D=m.O+m.A*np.array([math.cos(m.a0+a),math.sin(m.a0+a)]);T=body+pivot+B@(S[:3,3]+S[:3,:3]@ref.rx(oldq[i,0])@M[:3,3]-pivot)+R@np.array([D[0],0,D[1]]);return float((m.hulls[l]@(R@ref.ry(m.b0-beta))[2]+T[2]).min())
  a=root_scalar(fun,x0=oldq[i,1],x1=oldq[i,1]+.01,xtol=1e-12).root;q=inverse(oldq[i,0],a,beta,oldq[i,2]);endq.append(q);deltas.append(m.reference(l,q,body)[:2]-np.array(end['foot_bolt_world_mm'][i])[:2])
 print('Sit terminal deltas',deltas,'q',np.degrees(endq),flush=True)
 out=[];prev=None
 for row in src['samples']:
  t=row['time_s'];m.body_euler=np.array(row['body_rotation_euler_xyz_rad']);body=np.array(row['body_translation_world_mm']);q=[]
  for i,l in enumerate(legs):
   xy=np.array(row['foot_bolt_world_mm'][i])[:2]
   if i<2:xy+=ref.smooth(np.clip((t-post['step_start_seconds'][i])/post['step_duration_seconds'],0,1))*deltas[i]
   seed=np.array(row['actuator_angles_rad'][i]) if prev is None else prev[i]
   qq,err=m.solve(l,body,seed,xy,row['sole_clearance_mm'][i]);q.append(qq)
  prev=np.array(q);out.append(metrics(row,prev))
 src['samples']=out;report('sit',out);return src

def report(cmd,rows):
 q=np.array([r['actuator_angles_rad'] for r in rows]);print(cmd,'body',min(r['body_ground_clearance_mm'] for r in rows),'sole',min(min(r['sole_clearance_mm']) for r in rows),'support',min(r['support_margin_mm'] for r in rows),'step',np.degrees(abs(np.diff(q,axis=0))).max(), 'end reach',rows[-1]['arm_reach_mm'],flush=True)

if __name__=='__main__':
 s=sit();(WORK/'sit.json').write_text(json.dumps(s));

def rear_at(row,anchor,desired_x,seed):
 oq=np.array(row['actuator_angles_rad'][0]);beta=old.planar(oq)[3];h=oq[0];l='FL';m.body_euler=old.body_euler=np.array(row['body_rotation_euler_xyz_rad']);B=ref.ry(m.body_euler[1]);S=np.array(m.geom[l]['shoulder_world']);M=np.array(m.geom[l]['mechanism_local']);R=B@S[:3,:3]@ref.rx(h)@M[:3,:3];base=pivot+B@(S[:3,3]+S[:3,:3]@ref.rx(h)@M[:3,3]-pivot)+R@np.r_[m.O[0],0,m.O[1]]+R@ref.ry(m.b0-beta)@m.geom[l]['foot_reference_local_mm'];v=(anchor[0]-desired_x-base[0])/m.A;norm=np.hypot(R[0,0],R[0,2]);phi=math.atan2(R[0,2],R[0,0]);cos=np.clip(v/norm,-1,1);candidates=[]
 for sign in [-1,1]:
  a=phi+sign*math.acos(cos)-m.a0;a=seed[1]+math.remainder(a-seed[1],2*math.pi)
  try:
   q=inverse(h,a,beta,seed[2]);body=anchor-m.reference(l,q,np.zeros(3));candidates.append((np.linalg.norm(q-seed),q,body))
  except ValueError:pass
 if not candidates:raise ValueError(('rear impossible',row['time_s'],cos,v/norm))
 return min(candidates,key=lambda c:c[0])[1:]

def serial_pose(l,h,a,beta,body):
 S=np.array(m.geom[l]['shoulder_world']);M=np.array(m.geom[l]['mechanism_local']);B=ref.rz(m.body_euler[2])@ref.ry(m.body_euler[1])@ref.rx(m.body_euler[0]);R0=B@S[:3,:3]@ref.rx(h);R=R0@M[:3,:3];D=m.O+m.A*np.array([math.cos(m.a0+a),math.sin(m.a0+a)]);T=body+pivot+B@(S[:3,3]-pivot)+R0@M[:3,3]+R@np.r_[D[0],0,D[1]];return R@ref.ry(m.b0-beta),T

def serial_solve(l,body,seed,xy,z):
 beta=m.planar(seed)[3]
 def fun(v):
  R,T=serial_pose(l,*v,body);p=R@m.geom[l]['foot_reference_local_mm']+T;return np.r_[p[:2]-xy,np.min(m.hulls[l]@R[2]+T[2])-z]
 fit=least_squares(fun,[seed[0],seed[1],beta],xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=80)
 if np.linalg.norm(fit.fun)>.005:raise ValueError(('serial unreachable',fit.fun))
 return inverse(*fit.x,seed[2]),np.linalg.norm(fit.fun)

def wave():
 src=read(BASE/'motions/gestures/wave/source.json');s=read((WORK/'sit.json'));out=[];prev=None
 for row in src['samples']:
  t=row['time_s'];sn=min(360,round(t*120)) if t<=3 else round(np.clip(15.2-t,0,3)*120) if t>=12.2 else 360;base=s['samples'][sn];q=np.array(base['actuator_angles_rad']);body=np.array(base['body_translation_world_mm']);m.body_euler=np.array(base['body_rotation_euler_xyz_rad'])
  if 3<t<12.2:
   q[2],err=m.solve('RL',body,prev[2],np.array(row['foot_bolt_world_mm'][2])[:2],row['sole_clearance_mm'][2])
  prev=q;out.append(metrics(row,q,body))
 src['samples']=out;report('wave',out);(WORK/'wave.json').write_text(json.dumps(src));return src
