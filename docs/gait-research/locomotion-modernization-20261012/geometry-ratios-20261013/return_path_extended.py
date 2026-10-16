import whole_body as w, research as m
import numpy as np,json
from scipy.optimize import differential_evolution,minimize

def fk3(leg,q):
 S=np.array(m.live['legs'][leg]['shoulder_matrix']);M=np.array(m.live['legs'][leg]['mechanism_matrix']);T=np.linalg.inv(S)@M;R0=S[:3,:3];n=len(q);h,a,t=np.deg2rad(q).T;a+=m.a0;t+=m.t0
 D=m.O+m.A*np.c_[np.cos(a),np.sin(a)];P=m.C+m.r*np.c_[np.cos(t),np.sin(t)];ed,ok=m.circle(P-D,m.b,m.L,1);E=D+ed;beta=np.arctan2(ed[:,1],ed[:,0]);rot=beta-m.b0;co=np.cos(rot);si=np.sin(rot);rx=np.zeros((n,3,3));rx[:,0,0]=1;rx[:,1,1]=np.cos(h);rx[:,1,2]=-np.sin(h);rx[:,2,1]=np.sin(h);rx[:,2,2]=np.cos(h);basis=np.einsum('ij,njk,kl->nil',R0,rx,T[:3,:3]);origin=S[:3,3]+np.einsum('ij,njk,k->ni',R0,rx,T[:3,3]);normal=np.c_[basis[:,2,0]*co+basis[:,2,2]*si,basis[:,2,1],-basis[:,2,0]*si+basis[:,2,2]*co];zs=normal@w.hull3.T;idx=zs.argmin(1);bottom=zs[np.arange(n),idx]+origin[:,2]+basis[:,2,0]*D[:,0]+basis[:,2,2]*D[:,1];v=w.hull3[idx];cv=np.c_[co*v[:,0]-si*v[:,2],v[:,1],si*v[:,0]+co*v[:,2]];contact=origin+np.einsum('nij,nj->ni',basis,np.c_[D[:,0],np.zeros(n),D[:,1]]+cv)
 return dict(ok=ok,bottom=bottom,contact=contact,D=D,P=P,E=E,beta=beta,phi=np.arctan2(*(E-P).T[::-1]))

def refine(params):
 r=w.evaluate(params,True);N=w.N;qs=np.stack([r['legs'][leg]['q'] for leg in w.legs],1);new=qs.copy();result=[];interval=2*(1-w.data['duty']);step=2/N
 for k,leg in enumerate(w.legs):
  offset=round(w.data['offsets'][k]*N);start=round(w.data['duty']*N);idx=(np.arange(start,N+1)-offset)%N
  q0=qs[idx[0],k];q1=qs[idx[-1],k];v0=(q0-qs[(idx[0]-1)%N,k])/step;v1=(qs[(idx[-1]+1)%N,k]-q1)/step
  u=np.linspace(0,1,len(idx));s=10*u**3-15*u**4+6*u**5;h0=u-6*u**3+8*u**4-3*u**5;h1=-4*u**3+7*u**4-3*u**5;bump=16*u*u*(1-u)*(1-u)
  base=q0+(q1-q0)*s[:,None]+interval*(h0[:,None]*v0+h1[:,None]*v1)
  def calc(delta):
   adjust=np.c_[np.zeros(len(u)),np.tile(delta[:2],(len(u),1))+(2*u-1)[:,None]*delta[2:]]
   q=base+bump[:,None]*adjust;f=fk3(leg,q);z=f['bottom']+r['body_z'];vel=np.gradient(q,interval/(len(idx)-1),axis=0);return q,f,z,vel
  def cost(delta):
   q,f,z,vel=calc(delta)
   if not f['ok'].all():return 1e8
   # Shape the airborne arc and minimize its highest demanded joint speed.
   return np.max(abs(vel[:,1:]))/500+1000*np.sum(np.minimum(z,0)**2)+.04*(np.max(z)-10)**2+.002*np.sum((z-10*bump)**2)
  fit=differential_evolution(cost,[(-120,120)]*4,seed=10,popsize=8,maxiter=65,tol=.0002,polish=True);polished=minimize(cost,fit.x,method='SLSQP',bounds=[(-120,120)]*4,constraints=[{'type':'ineq','fun':lambda delta:calc(delta)[2][1:-1]-0.0001}],options={'ftol':1e-9,'maxiter':200})
  if polished.success:fit=polished
  q,f,z,vel=calc(fit.x);new[idx[:-1],k]=q[:-1]
  result.append(dict(leg=leg,offset_deg=fit.x.tolist(),min_sole_z=float(z.min()),max_lift=float(z.max()),peak_speed=np.max(abs(vel),axis=0).tolist(),closure=bool(f['ok'].all())))
 out=dict(summary={k:v for k,v in r.items() if k not in ['legs','phase','body_shift','body_acceleration','stance','contact_xy','support_margin_mm','weights','joint_torques']},return_fit=result,phase=r['phase'],body_shift=r['body_shift'],body_z=r['body_z'],stance=r['stance'],q=new.tolist(),contact_xy=r['contact_xy'],support_margin_mm=r['support_margin_mm'],weights=r['weights'],joint_torques=r['joint_torques'])
 print(json.dumps({'geometry':params,'fit':result}),flush=True);return out
