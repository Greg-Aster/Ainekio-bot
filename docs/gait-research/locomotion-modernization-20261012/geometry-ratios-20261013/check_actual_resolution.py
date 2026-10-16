import json,sys
from pathlib import Path
import numpy as np
from scipy.interpolate import CubicSpline
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P));import optimize_actual_body as a
v=json.load(open(P/f'actual-body-optimized-{a.name}.json'))['dimensions'];oldshift=a.shift.copy();oldweights=a.weights.copy();rows=[]
for N in [120,480,960]:
 a.N=N;a.step=a.period/N;p=np.arange(N)/N;a.pathmodel.N=N;a.pathmodel.phase=p;a.pathmodel.stance=p<.8;a.pathmodel.u=np.clip((p-.8)/.2,0,1)
 x,lift=a.pathmodel.path(a.stroke);a.feet=np.tile(a.centres,(N,1,1));a.lifts=np.zeros((N,4));a.stance=(p[:,None]+np.array([0,.5,.75,.25]))%1<.8
 for k,off in enumerate([0,N//2,3*N//4,N//4]):a.feet[:,k,0]+=np.roll(x,-off);a.lifts[:,k]=np.roll(lift,-off)
 cs=CubicSpline(np.arange(121)/120,np.vstack([oldshift,oldshift[:1]]),bc_type='periodic');a.shift=cs(p);a.acc=cs(p,2)/a.period**2
 a.weights=np.stack([np.interp(p,np.arange(120)/120,oldweights[:,k],period=1) for k in range(4)],1)
 out=a.perf(v,True);out.update(samples=N);rows.append(out);print(a.name,N,out,flush=True)
(P/f'actual-body-resolution-{a.name}.json').write_text(json.dumps(rows,indent=2))
