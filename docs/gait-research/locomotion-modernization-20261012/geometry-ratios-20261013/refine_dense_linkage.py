import json,sys
from pathlib import Path
import numpy as np
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P));import optimize_actual_body as a
v=json.load(open(P/f'actual-body-optimized-{a.name}.json'))['dimensions'];oldshift=a.shift.copy();oldweights=a.weights.copy()
N=480;a.N=N;a.step=a.period/N;p=np.arange(N)/N;a.pathmodel.N=N;a.pathmodel.phase=p;a.pathmodel.stance=p<.8;a.pathmodel.u=np.clip((p-.8)/.2,0,1)
x,lift=a.pathmodel.path(a.stroke);a.feet=np.tile(a.centres,(N,1,1));a.lifts=np.zeros((N,4));a.stance=(p[:,None]+np.array([0,.5,.75,.25]))%1<.8
for k,off in enumerate([0,N//2,3*N//4,N//4]):a.feet[:,k,0]+=np.roll(x,-off);a.lifts[:,k]=np.roll(lift,-off)
cs=CubicSpline(np.arange(121)/120,np.vstack([oldshift,oldshift[:1]]),bc_type='periodic');a.shift=cs(p);a.acc=cs(p,2)/a.period**2
a.weights=np.stack([np.interp(p,np.arange(120)/120,oldweights[:,k],period=1) for k in range(4)],1)
bound=[(20,160),(45,55),(20,100),(8,120),(8,180),(35,170),(-100,100),(-100,80)]
if a.name=='compact60':bound[0]=(20,45)
if a.name=='medium82':bound[0]=(20,60)
c=[0]
def cb(x):
 c[0]+=1
 if c[0]%100==0:print(a.name,c[0],a.perf(x),flush=True)
fit=minimize(a.perf,v,method='Nelder-Mead',bounds=bound,callback=cb,options={'maxiter':1600,'xatol':.002,'fatol':1e-6})
out=a.perf(fit.x,True);out.update(samples=N,converged=bool(fit.success),iterations=fit.nit,scope='Local 480 sample refinement with periodic cubic interpolated body trajectory and linearly interpolated reactions. Not global optimality or manufacturing qualification.')
(P/f'actual-body-dense-optimized-{a.name}.json').write_text(json.dumps(out,indent=2));print('DONE',json.dumps(out),flush=True)
