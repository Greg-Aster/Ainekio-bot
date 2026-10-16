import json,numpy as np
from itertools import product
from pathlib import Path
from scipy.spatial import ConvexHull
from scipy.optimize import minimize,LinearConstraint
p=Path(__file__).resolve().parent
N=120;stroke=82.;duty=.8;offsets=np.array([0,.5,.75,.25]);centers=np.array([[66.69,64.5],[66.69,-64.5],[-66.72,64.5],[-66.72,-64.5]])
phase=np.arange(N)/N;ph=(phase[:,None]+offsets)%1;stance=ph<duty
u=ph/duty;x=stroke*(.5-u);lift=np.zeros_like(x)
v=np.clip((ph-duty)/(1-duty),0,1);s=10*v**3-15*v**4+6*v**5;e=v-10*v**3+15*v**4-6*v**5
x=np.where(stance,x,-stroke/2+stroke*s-stroke*(1-duty)/duty*e);lift=np.where(stance,0,10*16*v*v*(1-v)*(1-v))
feet=np.tile(centers[None,:,:],(N,1,1));feet[:,:,0]+=x
dt=2/N; second=(np.roll(np.eye(N),1,axis=1)-2*np.eye(N)+np.roll(np.eye(N),-1,axis=1))/(dt*dt)
Z=np.eye(N)-.066/9.81*second
ramp=.05
cap=np.minimum(.5-.5*np.cos(np.pi*np.clip(ph/ramp,0,1)),.5-.5*np.cos(np.pi*np.clip((duty-ph)/ramp,0,1)))
cap=np.where(stance,cap,0)
cons=[];limits=[]
for i in range(N):
 ids=np.flatnonzero(stance[i]);caps=cap[i,ids];points=feet[i,ids];verts=[]
 for free in range(len(ids)):
  others=[k for k in range(len(ids)) if k!=free]
  for choices in product([0,1],repeat=len(others)):
   weights=np.zeros(len(ids));weights[others]=caps[others]*choices;weights[free]=1-weights.sum()
   if -1e-9<=weights[free]<=caps[free]+1e-9:verts.append(weights@points)
 h=ConvexHull(np.array(verts)).equations
 for plane in h:
  row=np.zeros(2*N);row[0::2]=plane[0]*Z[i];row[1::2]=plane[1]*Z[i];cons.append(row);limits.append(-plane[2]-4.)
A=np.array(cons);b=np.array(limits)
D=np.eye(N)-np.roll(np.eye(N),1,axis=1);D2=D@D
Q=np.kron(np.eye(N)+100*(D.T@D)+5000*(D2.T@D2),np.eye(2));fun=lambda a:.0005*a@Q@a;jac=lambda a:.001*Q@a
res=minimize(fun,np.zeros(2*N),jac=jac,constraints=[LinearConstraint(A,-np.inf,b)],method='SLSQP',options={'ftol':1e-7,'maxiter':300})
shift=res.x.reshape(N,2);print(res.success,res.message,'max residual',float((A@res.x-b).max()),'shift ranges',np.c_[shift.min(0),shift.max(0)].tolist(),flush=True)
report=dict(stroke=stroke,duty=duty,cycle_seconds=2,assumed_com=[0,0,65],nominal_margin_mm=4,phase=phase.tolist(),offsets=offsets.tolist(),feet_nominal=feet.tolist(),lift=lift.tolist(),stance=stance.tolist(),force_fraction_upper=cap.tolist(),body_shift=shift.tolist(),body_acceleration_mm_s2=(second@shift).tolist(),effective_support_xy=(Z@shift).tolist(),com_height_mm=66.,solver_success=bool(res.success),max_constraint_error=float((A@res.x-b).max()))
(p/'body-plan.json').write_text(json.dumps(report,indent=2))
