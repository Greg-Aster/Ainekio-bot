from pathlib import Path
import json,numpy as np
from scipy.spatial import ConvexHull
p=Path(__file__).resolve().parent;src=p;live=json.loads((src/'live45.json').read_text());par=live['params'];O=np.array(par['O']);C=np.array(par['C_new']);A=35.;r=20.;b=28.;L=30.;a0=par['alpha_neutral'];t0=par['firmware_theta_zero_rad'];b0=par['beta_neutral'];foot=45.;u=np.array([np.cos(b0-np.pi),np.sin(b0-np.pi)]);ref=foot*u
verts=np.array(live['legs']['RL']['vertices'])[:,[0,2]];hull=verts[ConvexHull(verts).vertices];floor=49.25000762939453

def cross(x,y):return x[...,0]*y[...,1]-x[...,1]*y[...,0]
def circle(v,r1,r2,sign):
 d2=np.sum(v*v,axis=-1);al=(r1*r1-r2*r2+d2)/(2*d2);h2=r1*r1/d2-al*al;return al[...,None]*v+sign*np.sqrt(np.maximum(0,h2))[...,None]*np.stack([-v[...,1],v[...,0]],-1),(h2>=0)&(d2>1e-9)
def ik(x,z):
 x,z=np.broadcast_arrays(x,z);fz=z+7.5
 for _ in range(12):
  F=np.stack([x,fz],-1);k,ok=circle(F-O,A,foot,-1);D=O+k;lower=(F-D)/foot;E=D-b*lower;Poff,ok2=circle(E-C,r,L,-1);P=C+Poff
  beta=np.arctan2(-lower[...,1],-lower[...,0]);a=np.arctan2(k[...,1],k[...,0]);t=np.arctan2(Poff[...,1],Poff[...,0]);rot=beta-b0;co=np.cos(rot);si=np.sin(rot)
  bottom=(si[...,None]*hull[:,0]+co[...,None]*hull[:,1]).min(-1)+D[...,1];fz+=z-bottom
 q=np.rad2deg(np.stack([np.arctan2(np.sin(a-a0),np.cos(a-a0)),np.arctan2(np.sin(t-t0),np.cos(t-t0))],-1))
 rod=E-P;op=E-D;ip=P-C;ok &=ok2 & (cross(P-D,E-D)>0)&(np.abs(bottom-z)<.002)
 idx=(si[...,None]*hull[:,0]+co[...,None]*hull[:,1]).argmin(-1);v=hull[idx];vx=co*v[...,0]-si*v[...,1];vz=si*v[...,0]+co*v[...,1];da=np.stack([-k[...,1],k[...,0]],-1);dt=np.stack([-ip[...,1],ip[...,0]],-1);den=cross(op,rod);ba=-np.sum(rod*da,-1)/den;bt=np.sum(rod*dt,-1)/den
 jac=np.stack([np.stack([da[...,0]-vz*ba,da[...,1]+vx*ba],-1),np.stack([-vz*bt,vx*bt],-1)],-1)
 angle=lambda x,y:np.rad2deg(np.arccos(np.clip(np.abs(np.sum(x*y,-1))/(np.linalg.norm(x,axis=-1)*np.linalg.norm(y,axis=-1)),0,1)))
 return dict(q=q,ok=ok,D=D,P=P,E=E,beta=beta,phi=np.arctan2(rod[...,1],rod[...,0]),sole=bottom,contact_x=D[...,0]+vx,jac=jac,output=angle(rod,op),input=angle(rod,ip))

if __name__=='__main__':
 rows=[]
 for H in [35,40,45,50,55,60]:
  for L in [26.,28.,30.,32.,34.,36.,38.,40.,42.,44.,46.]:
   for stroke in [60,70,82]:
    x=O[0]+np.linspace(-stroke/2,stroke/2,101);v=ik(x,np.full(101,floor-H));q=v['q'];pulses=np.c_[856+(q[:,0]-1.17)*100/9,723+(q[:,1]+40.41)*100/9];valid=bool(v['ok'].all() and (pulses>=400).all() and (pulses<=2900).all());score=np.max(abs(v['jac'][:,1,:])+.3*abs(v['jac'][:,0,:]))
    rows.append(dict(height=H,rod=L,stroke=stroke,valid=valid,score=float(score),min_input=float(v['input'].min()),min_output=float(v['output'].min()),qrange=np.c_[q.min(0),q.max(0)].tolist(),pulses=np.c_[pulses.min(0),pulses.max(0)].tolist()))
 (p/'workspace.json').write_text(json.dumps(rows,indent=2))
 for stroke in [70,82]:
  print('STROKE',stroke)
  for row in sorted([x for x in rows if x['valid'] and x['stroke']==stroke],key=lambda x:x['score'])[:12]:print(row)
