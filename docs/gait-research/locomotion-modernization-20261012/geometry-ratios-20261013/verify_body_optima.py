"""Independent bare-foot/body check for optimizer outputs, with matching cycle timing."""
import json,sys,numpy as np
from pathlib import Path
from itertools import product
from scipy.spatial import ConvexHull
from scipy.optimize import minimize,LinearConstraint
P=Path(__file__).resolve().parent;base=P.parent
sys.path.insert(0,str(base/'body-support-20261013'))
import research as m,whole_body as w
import optimize_dynamic_linkage as opt
original=np.array(json.load(open(base/'installed55-20261013/bare55.json'))['vertices']);axis=np.array([m.u[0],0,m.u[1]])
centres=np.array([[66.69,64.5],[66.69,-64.5],[-66.72,64.5],[-66.72,-64.5]])
N=120;ph=(np.arange(N)[:,None]/N+np.array([0,.5,.75,.25]))%1
opt.N=N;opt.PERIOD=.9;opt.phase=np.arange(N)/N;opt.stance=opt.phase<.8;opt.u=np.clip((opt.phase-.8)/.2,0,1)
rows=[]
for name,values,S in [('compact60',[45,55,20,18.3,26.5,68.1,-10.9,-27.3],60),('medium82',[60,55,20.1,13.9,30.3,84,-5.3,-39.2],82),('unrestricted82',[113,53,20.1,14.5,63.2,135.4,-9.2,-59.3],82)]:
 A,F,r,b,L,H,cx,cz=values
 x,lift=opt.path(S);feet=np.tile(centres,(N,1,1));lifts=[]
 for k,off in enumerate([0,60,90,30]):feet[:,k,0]+=np.roll(x,-off);lifts.append(np.roll(lift,-off))
 lifts=np.array(lifts).T;stance=ph<.8
 second=(np.roll(np.eye(N),1,axis=1)-2*np.eye(N)+np.roll(np.eye(N),-1,axis=1))/(.9/N)**2
 HH=H+1.9767776;Z=np.eye(N)-(HH+15.75)/9810*second
 ramp=.05;cap=np.minimum(.5-.5*np.cos(np.pi*np.clip(ph/ramp,0,1)),.5-.5*np.cos(np.pi*np.clip((.8-ph)/ramp,0,1)));cap=np.where(stance,cap,0)
 cons=[];limits=[]
 for i in range(N):
  ids=np.flatnonzero(stance[i]);caps=cap[i,ids];pts=feet[i,ids];vs=[]
  for free in range(len(ids)):
   others=[k for k in range(len(ids)) if k!=free]
   for choices in product([0,1],repeat=len(others)):
    ww=np.zeros(len(ids));ww[others]=caps[others]*choices;ww[free]=1-ww.sum()
    if -1e-9<=ww[free]<=caps[free]+1e-9:vs.append(ww@pts)
  for plane in ConvexHull(np.array(vs)).equations:
   row=np.zeros(2*N);row[0::2]=plane[0]*Z[i];row[1::2]=plane[1]*Z[i];cons.append(row);limits.append(-plane[2]-4.)
 cons=np.array(cons);limits=np.array(limits);D=np.eye(N)-np.roll(np.eye(N),1,axis=1);D2=D@D;Q=np.kron(np.eye(N)+100*D.T@D+5000*D2.T@D2,np.eye(2))
 fit=minimize(lambda a:.0005*a@Q@a,np.zeros(2*N),jac=lambda a:.001*Q@a,constraints=[LinearConstraint(cons,-np.inf,limits)],method='SLSQP',options={'ftol':1e-7,'maxiter':300})
 shift=fit.x.reshape(N,2)
 w.feet=feet;w.shift=shift;w.lift=lifts;w.stance=stance;w.acc=second@shift;w.data['force_fraction_upper']=cap.tolist()
 proj=original@axis;verts=original+axis*np.clip((proj-7)/41,0,1)[:,None]*(F-55)-axis*np.clip((-proj-7)/14,0,1)[:,None]*(b-28)
 m.foot=F;m.ref=F*m.u;m.r=r;m.C=m.O+np.array([cx,cz]);w.ref3=np.array([m.ref[0],-56.65,m.ref[1]]);w.hull3=verts[ConvexHull(verts).vertices]
 report=w.evaluate((A,b,L,HH),True)
 q=np.stack([report['legs'][leg]['q'] for leg in w.legs],1);q=np.rad2deg(np.unwrap(np.deg2rad(q),axis=0));speed=np.max(abs(np.gradient(q,.9/N,axis=0)),axis=(0,1))
 angle=min(float(np.degrees(np.arcsin(abs(np.sin(v['beta']))))[stance[:,k]].min()) for k,v in enumerate(report['legs'].values()))
 row=dict(name=name,dimensions=values,stride=S,body_plan_success=bool(fit.success),body_plan_max_residual=float((cons@fit.x-limits).max()),stance_closed=report['stance_closed'],all_cycle_closed=all(all(v['ok']) for v in report['legs'].values()),minimum_loaded_sagittal_angle=angle,minimum_support_margin=report['min_support_margin_mm'],minimum_reaction_fraction=report['min_weight_fraction'],body_shift_extent=np.ptp(shift,axis=0).tolist(),peak_speed_deg_s=speed.tolist(),point_body_torque_Nm=(np.array(report['peak_joint_torque_Nm_per_kg'])*.566).tolist(),force_equilibrium_error=report['max_force_equilibrium_error'],scope='Independent actual foot mesh and body shift. Point body load only in this cross-check; dynamic optimizer supplies separate link inertia estimate. Not physical qualification.')
 rows.append(row);print(json.dumps(row),flush=True)
 (P/f'body-optimum-{name}-cycle.json').write_text(json.dumps(report))
(P/'optimized-body-cross-check.json').write_text(json.dumps(rows,indent=2))
