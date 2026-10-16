"""Minimax linkage optimization, not a runtime controller or physical qualification.
Design variables: carrier, knee-to-foot, crank, pickup, rod, ground clearance,
crank pivot X/Z relative to carrier. Joint dimensions in mm.
Objective: minimum worst-case servo torque/speed utilization for a fixed stride.
Torque-speed normalization is a reference model, NOT identification of owner's MG90.
"""
import json,sys,numpy as np
from pathlib import Path
from scipy.optimize import differential_evolution
from scipy.stats import qmc
import ratio_model as m
P=Path(__file__).resolve().parent
# A fixed load lets geometry be compared without silently changing mass or support.
WEIGHT=.566*9.81;LEG_FORCE=WEIGHT/2
TREF=1.8*.0980665;WREF=600.
DUTY=.8;PERIOD=.9
N=200;phase=np.arange(N)/N;stance=phase<DUTY;u=np.clip((phase-DUTY)/(1-DUTY),0,1)
# Short cubic velocity ramps around constant-speed return, with continuous
# stance-to-swing velocity. Research trajectory, not a firmware change.
def path(stroke):
 r=.08;sw=PERIOD*(1-DUTY);v0=-stroke/(PERIOD*DUTY);vm=(stroke/sw-r*v0)/(1-r)
 def integ(z):
  a=np.clip(z/r,0,1);start=v0*z+(vm-v0)*r*(a**3-.5*a**4)
  return np.where(z<r,start, v0*r+(vm-v0)*r/2+vm*(z-r))
 xx=np.where(u<=.5,-stroke/2+sw*integ(u),stroke/2-sw*integ(1-u))
 x=np.where(stance,stroke*(.5-phase/DUTY),xx)
 lift=np.where(stance,0,160*u*u*(1-u)*(1-u))
 return x,lift

def evaluate(data,stroke,details=False):
 d=np.atleast_2d(data);A,F,r,b,L,H,cx,cz=d.T
 A=A[:,None];F=F[:,None];r=r[:,None];b=b[:,None];L=L[:,None];H=H[:,None];C=np.stack([cx,cz],-1)[:,None,:]
 x,lift=path(stroke);target=np.stack([np.broadcast_to(x,(len(d),N)),-(H+22.43859-7.5)+lift],-1)
 D,ok=m.circle(target,A,F,-1);lower=(target-D)/F[...,None];E=D-b[...,None]*lower;ip,ok2=m.circle(E-C,r,L,-1);PP=C+ip;out=E-D;rod=E-PP
 aa=np.unwrap(np.arctan2(D[...,1],D[...,0]),axis=1);tt=np.unwrap(np.arctan2(ip[...,1],ip[...,0]),axis=1);q=np.stack([aa,tt],-1)
 branch=m.cross(PP-D,out)>0;valid=(ok&ok2&branch).all(1)
 ranges=np.rad2deg(np.ptp(q,axis=1));valid&=(ranges<=225).all(1)
 den=m.cross(out,rod);da=m.perp(D);dt=m.perp(ip)
 with np.errstate(divide='ignore',invalid='ignore'):
  ba=-np.sum(rod*da,-1)/den;bt=np.sum(rod*dt,-1)/den;v=target-D;v[...,1]-=7.5
  J=np.stack([da+ba[...,None]*m.perp(v),bt[...,None]*m.perp(v)],-1)
 angles=np.degrees(np.arcsin(np.clip(abs(lower[:,:,1]),0,1)))[:,stance].min(1)
 # Only stance carries modeled body weight. Swing inertia is unknown/excluded.
 tau=np.zeros((len(d),N,2));tau[:,stance]=abs(J[:,stance,1,:])*LEG_FORCE/1000
 vel=abs(np.rad2deg(np.gradient(q,PERIOD/N,axis=1)))
 peak_torque=tau.max(1);peak_speed=vel.max(1);util=tau/TREF+vel/WREF
 jointutil=util.max(1);imbalance=abs(peak_torque[:,0]-peak_torque[:,1])/np.maximum(peak_torque.max(1),1e-9)
 score=jointutil.max(1)+5*np.maximum(0,imbalance-.10)**2+ .005*np.sum(d[:,[0,2,3,4]],axis=1)/100
 # Closure/posture are mathematical feasibility, not runtime restrictions.
 score=np.where(valid&np.isfinite(score)&(angles>=45),score,100+np.nan_to_num(np.maximum(0,45-angles),nan=100))
 if not details:return score
 return dict(score=score.tolist(),closed=valid.tolist(),min_leg_angle=angles.tolist(),peak_torque_Nm=peak_torque.tolist(),peak_speed_deg_s=peak_speed.tolist(),peak_reference_utilization=jointutil.tolist(),torque_imbalance_fraction=imbalance.tolist(),joint_excursions_deg=ranges.tolist())

if __name__=='__main__':
 stroke=float(sys.argv[1]);seed=int(sys.argv[2]) if len(sys.argv)>2 else 1
 mode=sys.argv[3] if len(sys.argv)>3 else 'expanded'
 bounds=[(20,160),(45,55),(20,100),(8,120),(8,180),(35,170),(-100,100),(-100,80)]
 if mode=='compact':bounds=[(20,45),(45,55),(20,45),(8,55),(8,70),(35,75),(-45,45),(-35,40)]
 if mode=='medium':bounds=[(20,60),(45,55),(20,60),(8,65),(8,90),(35,90),(-50,50),(-50,50)]
 # Sobol initial population, explicit feasible seeds, then continuous DE refinement.
 vals=qmc.Sobol(8,scramble=True,seed=seed).random_base2(14);bb=np.array(bounds);vals=bb[:,0]+vals*(bb[:,1]-bb[:,0]);scores=[]
 for k in range(0,len(vals),128):scores.extend(evaluate(vals[k:k+128],stroke))
 idx=np.argsort(scores)[:96];init=vals[idx]
 init=np.vstack([init,[26,55,21,27,23,51,4,0]])
 def loss(v):return evaluate(v.T,stroke) if v.ndim>1 else evaluate(v,stroke)[0]
 counter=[0]
 def progress(intermediate_result):
  counter[0]+=1
  if counter[0]%40==0:print('generation',counter[0],'score',float(intermediate_result.fun),flush=True)
 fit=differential_evolution(loss,bounds,init=init,seed=seed,maxiter=600,tol=1e-5,polish=False,vectorized=True,updating='deferred',callback=progress)
 ans=dict(mode=mode,stroke=stroke,seed=seed,dimensions=fit.x.tolist(),result=evaluate(fit.x,stroke,True),generations=fit.nit,converged=bool(fit.success),bounds=bounds,assumptions={'cycle_seconds':PERIOD,'duty':DUTY,'stance_force_per_leg_N':LEG_FORCE,'reference_stall_Nm':TREF,'reference_no_load_deg_s':WREF,'scope':'Spherical toe planar surrogate; half body weight per loaded leg; no limb inertia. Reference motor normalization, not installed-servo qualification. Full mesh/body verification required.'})
 (P/f'optimized-{mode}-stride{int(stroke)}-seed{seed}.json').write_text(json.dumps(ans,indent=2));print(json.dumps(ans),flush=True)
