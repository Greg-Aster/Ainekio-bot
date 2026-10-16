from pathlib import Path
import json,subprocess,hashlib
import numpy as np
root=Path('/home/greggles/Ainekio/Slave/software/models/v2-12servo');binary=Path('/tmp/ainekio-gait-repair-optimized/v2_model/v2_walk_command')
g=json.loads((root/'geometry.json').read_text());p=g['parameters'];O=np.array(p['O']);C=np.array(p['C_new']);A=p['primary_length'];radius=p['input_length'];b0=p['beta_neutral']
wire=json.dumps(dict(t='intent',seq=1,name='walk',dir='fwd',gait='walk',steps=0,speed=100))+'\n'
s=subprocess.run([str(binary),'12000','100'],input=wire,text=True,capture_output=True,check=True);rows=[json.loads(l) for l in s.stdout.splitlines()];rows=[v for v in rows if v['ms']>=8000]
q=np.array([v['q'] for v in rows]).reshape(-1,4,3);ground=np.array([v['grounded'] for v in rows]);a=q[:,:,1]+p['alpha_neutral'];t=q[:,:,2]+p['new_theta_neutral'];pair=lambda x,y:np.stack([x,y],axis=-1);perp=lambda v:pair(-v[...,1],v[...,0]);dot=lambda x,y:np.sum(x*y,axis=-1);cross=lambda x,y:x[...,0]*y[...,1]-x[...,1]*y[...,0]
D=O+A*pair(np.cos(a),np.sin(a));P=C+radius*pair(np.cos(t),np.sin(t));w=P-D;d=np.linalg.norm(w,axis=-1);along=(p['pickup_length']**2-p['rod_length']**2+d*d)/(2*d);h=np.sqrt(p['pickup_length']**2-along*along);E=D+(along[...,None]*w+h[...,None]*perp(w))/d[...,None];beta=np.arctan2((E-D)[...,1],(E-D)[...,0]);rot=beta-b0
hull=np.array(json.loads((root/'motions/locomotion/sole-profile.json').read_text())['profiles']['walk']);normal=np.stack([np.sin(rot),np.zeros_like(rot),np.cos(rot)],axis=-1);idx=(normal@hull.T).argmin(axis=-1);local=hull[idx];vx=np.cos(rot)*local[...,0]-np.sin(rot)*local[...,2];vz=np.sin(rot)*local[...,0]+np.cos(rot)*local[...,2]
results=[]
for pickup,L in [(28,34),(28,36),(28,38),(28,40),(28,42),(28,44),(32,38),(32,40),(32,42),(34,38),(34,40)]:
 e=D+pickup*pair(np.cos(beta),np.sin(beta));w=e-C;d=np.linalg.norm(w,axis=-1);valid=(d<radius+L)&(d>abs(L-radius));item=dict(crank_mm=radius,pickup_mm=pickup,rod_mm=L,full_cycle_closure=bool(valid.all()))
 if not valid.all():results.append(item);continue
 k=(radius**2-L**2+d*d)/(2*d*d);h=np.sqrt(radius**2/d**2-k*k);P=C+k[...,None]*w-h[...,None]*perp(w);inp=P-C;out=e-D;rod=e-P;branch=cross(P-D,out)>0;item['same_assembly_branch']=bool(branch.all())
 da=A*pair(-np.sin(a),np.cos(a));den=dot(rod,perp(out));ba=-dot(rod,da)/den;bt=dot(rod,perp(inp))/den
 za=da[...,1]+vx*ba;zt=vx*bt;xa=da[...,0]-vz*ba;xt=-vz*bt
 item['peak_stance_vertical_arms_mm']=[float(abs(v[ground]).max()) for v in [za,zt]];item['peak_stance_horizontal_arms_mm']=[float(abs(v[ground]).max()) for v in [xa,xt]]
 angles=np.unwrap(np.arctan2(inp[...,1],inp[...,0]),axis=0);item['crank_excursion_deg']=np.rad2deg(np.ptp(angles,axis=0)).tolist()
 outang=np.rad2deg(np.arccos(np.clip(abs(dot(rod,out))/(L*pickup),0,1)));inang=np.rad2deg(np.arccos(np.clip(abs(dot(rod,inp))/(L*radius),0,1)));item['minimum_stance_transmission_deg']=[float(v[ground].min()) for v in [outang,inang]]
 # Independently verify analytic unit-force torque arms using central differences
 # of the four-bar forward solution, keeping the selected contact vertex fixed.
 def position(aa,tt):
  dd=O+A*pair(np.cos(aa),np.sin(aa));pp=C+radius*pair(np.cos(tt),np.sin(tt));ww=pp-dd;dist=np.linalg.norm(ww,axis=-1)
  ll=(pickup**2-L**2+dist**2)/(2*dist);hh=np.sqrt(pickup**2-ll**2);ee=dd+(ll[...,None]*ww+hh[...,None]*perp(ww))/dist[...,None]
  rr=np.arctan2((ee-dd)[...,1],(ee-dd)[...,0])-b0
  return dd+pair(np.cos(rr)*local[...,0]-np.sin(rr)*local[...,2],np.sin(rr)*local[...,0]+np.cos(rr)*local[...,2])
 eps=1e-6;ja=(position(a+eps,angles)-position(a-eps,angles))/(2*eps);jt=(position(a,angles+eps)-position(a,angles-eps))/(2*eps)
 item['central_difference_max_error_mm_per_rad']=float(max(abs(ja-pair(xa,za)).max(),abs(jt-pair(xt,zt)).max()))
 results.append(item)
 print(pickup,L,'branch',item['same_assembly_branch'],'vertical',np.round(item['peak_stance_vertical_arms_mm'],2),'horizontal',np.round(item['peak_stance_horizontal_arms_mm'],2),'angles',np.round(item['minimum_stance_transmission_deg'],1),'range',np.round([min(item['crank_excursion_deg']),max(item['crank_excursion_deg'])],1),flush=True)
report=dict(scope='Read-only planar static comparison at identical carrier and lower-leg poses from 8–12 s of a native 100% forward Walk, sampled at 100 Hz. Crank fixed at 20 mm. Torque arms use the existing sole support vertex under vertical or horizontal unit force. Three-dimensional shoulder/body rotations, dynamics, collisions, strength, servo pulse indexing and physical tracking are not qualified.',geometry_sha256=hashlib.sha256((root/'geometry.json').read_bytes()).hexdigest(),binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),cases=results)
Path('/tmp/gait-candidate/fixed-crank-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
