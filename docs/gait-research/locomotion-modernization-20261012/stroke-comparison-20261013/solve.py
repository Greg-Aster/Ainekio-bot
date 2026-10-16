import json,math
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
from scipy.optimize import least_squares
p=Path(__file__).resolve().parent;j=json.loads((p/'live45.json').read_text());par=j['params'];O=np.array(par['O']);C=np.array(par['C_new']);a0=par['alpha_neutral'];t0=par['firmware_theta_zero_rad'];b0=par['beta_neutral'];A=35.;r=20.;b=28.;L=30.;u=np.array([np.cos(b0-np.pi),np.sin(b0-np.pi)]);ref=45*u
verts=np.array(j['legs']['RL']['vertices'])[:,[0,2]];hull=verts[ConvexHull(verts).vertices]
base=49.25000762939453-35; rear=34.5-4.1000213623046875

def fk(q):
 a,t=np.deg2rad(q)+[a0,t0];D=O+A*np.array([np.cos(a),np.sin(a)]);P=C+r*np.array([np.cos(t),np.sin(t)]);w=P-D;d=np.linalg.norm(w);along=(b*b-L*L+d*d)/(2*d);h2=b*b-along*along
 if h2<0:raise ValueError('unclosed')
 E=D+(along*w+np.sqrt(h2)*np.array([-w[1],w[0]]))/d;beta=np.arctan2(*(E-D)[::-1]);rot=beta-b0;R=np.array([[np.cos(rot),-np.sin(rot)],[np.sin(rot),np.cos(rot)]]);foot=D+R@ref;sole=(hull@R.T)[:,1].min()+D[1]
 return foot[0],sole,D,P,E,beta,np.arctan2(*(E-P)[::-1]),d

def residual(q,x,z):
 try:
  v=fk(q);return np.array([v[0]-x,v[1]-z])
 except ValueError:return np.array([1000,1000])
report={'dimensions_mm':{'leg':45,'carrier':35,'crank':20,'pickup':28,'rod':30},'body_translation_z':-base,'stance_fraction':.75,'cycle_seconds':2,'lift_mm':12,'rear_foot_x_mm':34.5,'scope':'Kinematic comparison using live bare Part027 contact mesh. In-place body frame. No dynamics or measured contact.','cases':[]}
for stroke in [70,82]:
 rows=[];q=np.array([50.,61.]) if stroke==70 else np.array([68.,65.])
 for i in range(241):
  ph=i/240
  if ph<=.75: x=rear+stroke*(1-ph/.75);z=base;stance=True
  else:
   v=(ph-.75)/.25;f=10*v**3-15*v**4+6*v**5;d=v-10*v**3+15*v**4-6*v**5
   x=rear+stroke*f-stroke/3*d;z=base+12*16*v*v*(1-v)*(1-v);stance=False
  fit=least_squares(residual,q,args=(x,z),xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=150)
  if np.linalg.norm(fit.fun)>.001:raise RuntimeError((stroke,i,fit.fun.tolist()))
  q=fit.x;v=fk(q)
  rows.append(dict(phase=ph,q=q.tolist(),D=v[2].tolist(),P=v[3].tolist(),E=v[4].tolist(),beta=float(v[5]),phi=float(v[6]),sole_z=float(v[1]),x=float(v[0]),stance=stance,residual=float(np.linalg.norm(fit.fun))))
 angles=np.array([r['q'] for r in rows]);pulses=np.c_[856+(angles[:,0]-1.17)*100/9,723+(angles[:,1]+40.41)*100/9]
 case=dict(stroke_mm=stroke,rows=rows,angle_range_deg=np.c_[angles.min(0),angles.max(0)].tolist(),pulse_range_us=np.c_[pulses.min(0),pulses.max(0)].tolist(),max_residual_mm=max(r['residual'] for r in rows),max_adjacent_angle_step_deg=float(abs(np.diff(angles,axis=0)).max()),cycle_closure_deg=float(abs(angles[0]-angles[-1]).max()))
 report['cases'].append(case);print({k:v for k,v in case.items() if k!='rows'},flush=True)
(p/'cycles.json').write_text(json.dumps(report,indent=2))
