import sys,json,time
import numpy as np
from itertools import product
from scipy.spatial import ConvexHull
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize,LinearConstraint
from pathlib import Path
P=Path(__file__).resolve().parent
sys.path.insert(0,str(P))
import optimize_actual_body as a
N=a.N
ph=(np.arange(N)[:,None]/N+np.array([0,.5,.75,.25]))%1
cap=np.minimum(.5-.5*np.cos(np.pi*np.clip(ph/.05,0,1)),.5-.5*np.cos(np.pi*np.clip((.8-ph)/.05,0,1)));cap=np.where(ph<.8,cap,0)
D=np.eye(N)-np.roll(np.eye(N),1,axis=1);D2=D@D;Q=np.kron(np.eye(N)+100*D.T@D+5000*D2.T@D2,np.eye(2))
source=P/sys.argv[2];input_data=json.load(open(source));v=np.array(input_data['dimensions'],dtype=float).reshape(-1,8)[0];S=float(input_data['stroke_mm']);name=source.stem
rows=[];last=np.zeros(2*N)
for percent in ([int(x) for x in sys.argv[3].split(',')] if len(sys.argv)>3 else [1,50,100]):
 a.N=N;a.pathmodel.N=N;a.pathmodel.phase=np.arange(N)/N;a.pathmodel.stance=a.pathmodel.phase<.8;a.pathmodel.u=np.clip((a.pathmodel.phase-.8)/.2,0,1);a.stance=ph<.8
 A,F,r,b,L,H,cx,cz=v
 a.period=1.8/(1+percent/100);a.step=a.period/N;a.pathmodel.PERIOD=a.period
 x,lift=a.pathmodel.path(S*percent/100);lift*=.2+.8*percent/100
 a.feet=np.tile(a.centres,(N,1,1));a.lifts=np.zeros((N,4))
 for k,off in enumerate([0,60,90,30]):a.feet[:,k,0]+=np.roll(x,-off);a.lifts[:,k]=np.roll(lift,-off)
 second=(np.roll(np.eye(N),1,axis=1)-2*np.eye(N)+np.roll(np.eye(N),-1,axis=1))/a.step**2
 HH=H+1.9767776;Z=np.eye(N)-(HH+15.75)/9810*second
 cons=[];limits=[]
 for i in range(N):
  ids=np.flatnonzero(a.stance[i]);caps=cap[i,ids];pts=a.feet[i,ids];vs=[]
  for free in range(len(ids)):
   others=[k for k in range(len(ids)) if k!=free]
   for choices in product([0,1],repeat=len(others)):
    ww=np.zeros(len(ids));ww[others]=caps[others]*choices;ww[free]=1-ww.sum()
    if -1e-9<=ww[free]<=caps[free]+1e-9:vs.append(ww@pts)
  for plane in ConvexHull(np.array(vs)).equations:
   row=np.zeros(2*N);row[0::2]=plane[0]*Z[i];row[1::2]=plane[1]*Z[i];cons.append(row);limits.append(-plane[2]-4.)
 cons=np.array(cons);limits=np.array(limits)
 fit=minimize(lambda z:.0005*z@Q@z,last,jac=lambda z:.001*Q@z,constraints=[LinearConstraint(cons,-np.inf,limits)],method='SLSQP',options={'ftol':1e-7,'maxiter':300});last=fit.x
 a.shift=last.reshape(N,2);a.acc=second@a.shift
 # Set actual foot geometry through perf, then recompute reactions for this geometry.
 a.weights=np.zeros((N,4))  # Geometry setup only; replace with solved reactions below.
 a.perf(v,True)
 w=a.w;w.feet=a.feet;w.shift=a.shift;w.lift=a.lifts;w.stance=a.stance;w.acc=a.acc;w.data['force_fraction_upper']=cap.tolist()
 report=w.evaluate((A,b,L,HH),True);a.weights=np.array(report['weights'])
 # Re-evaluate dynamics on 480 phase samples after solving 120-sample body support.
 NN=int(sys.argv[4]) if len(sys.argv)>4 else 480
 pp=np.arange(NN)/NN;oldshift=a.shift.copy();oldweights=a.weights.copy()
 a.N=NN;a.step=a.period/NN;a.pathmodel.N=NN;a.pathmodel.phase=pp;a.pathmodel.stance=pp<.8;a.pathmodel.u=np.clip((pp-.8)/.2,0,1)
 xx,ll=a.pathmodel.path(S*percent/100);ll*=.2+.8*percent/100
 a.feet=np.tile(a.centres,(NN,1,1));a.lifts=np.zeros((NN,4));a.stance=(pp[:,None]+np.array([0,.5,.75,.25]))%1<.8
 for k,off in enumerate([0,NN//2,3*NN//4,NN//4]):a.feet[:,k,0]+=np.roll(xx,-off);a.lifts[:,k]=np.roll(ll,-off)
 cs=CubicSpline(np.arange(N+1)/N,np.vstack([oldshift,oldshift[:1]]),bc_type='periodic');a.shift=cs(pp);a.acc=cs(pp,2)/a.period**2
 a.weights=np.stack([np.interp(pp,np.arange(N)/N,oldweights[:,k],period=1) for k in range(4)],1)
 detail=a.perf(v,True)
 detail.update(reference_body_plan={"shift":oldshift.tolist(),"weights":oldweights.tolist()},speed_percent=percent,cycle_seconds=a.period,stride_mm=S*percent/100,body_plan_success=bool(fit.success),support_margin_mm=report['min_support_margin_mm'],minimum_reaction_fraction=report['min_weight_fraction'],force_equilibrium_error=report['max_force_equilibrium_error'],shoulder_point_body_peak_Nm=report['peak_joint_torque_Nm_per_kg'][0]*detail.get('estimated_mass_kg',.566))
 rows.append(detail)
 if percent==1 or percent%10==0:print(name,percent,detail.get('valid'),detail.get('peak_torque_Nm'),detail.get('peak_speed_deg_s'),detail['support_margin_mm'],flush=True)
(P/f'body-audit-{name}-n{NN}.json').write_text(json.dumps({'scope':f'Listed speed settings with recomputed body shift and actual-contact force distribution,120 samples per cycle for body support,then {NN} samples for dynamics with interpolated body shift and reactions. Research trajectory with80% stance,not deployed firmware trajectory. Assumed COM and uniform plastic links; no measured servo curve or physical qualification.','dimensions':v.tolist(),'rows':rows},indent=2))
print('DONE',name,flush=True)
