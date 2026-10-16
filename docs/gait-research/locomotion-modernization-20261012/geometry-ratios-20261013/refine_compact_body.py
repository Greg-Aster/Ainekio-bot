"""Optimize the actual four-leg model at slow, medium and full walking speeds.
Research: fixed20 mm crank,45–55 knee-to-foot, no longer lower link than original.
"""
import sys,json,numpy as np
from pathlib import Path
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize
P=Path(__file__).resolve().parent
source=sys.argv[1];sys.argv=['research','compact60']
import optimize_actual_body as a
src=json.load(open(P/source));initial=np.array(src['dimensions'],dtype=float);S=40.;N=240;phase=np.arange(N)/N
conditions=[]
for row in src['rows']:
 percent=row['speed_percent'];period=row['cycle_seconds'];saved=row['reference_body_plan'];shift=np.array(saved['shift']);weights=np.array(saved['weights'])
 cs=CubicSpline(np.arange(121)/120,np.vstack([shift,shift[:1]]),bc_type='periodic')
 a.pathmodel.N=N;a.pathmodel.phase=phase;a.pathmodel.stance=phase<.8;a.pathmodel.u=np.clip((phase-.8)/.2,0,1);a.pathmodel.PERIOD=period
 x,lift=a.pathmodel.path(S*percent/100);lift*=.2+.8*percent/100;feet=np.tile(a.centres,(N,1,1));lifts=np.zeros((N,4))
 for k,off in enumerate([0,N//2,3*N//4,N//4]):feet[:,k,0]+=np.roll(x,-off);lifts[:,k]=np.roll(lift,-off)
 conditions.append(dict(period=period,step=period/N,feet=feet,lifts=lifts,shift=cs(phase),acc=cs(phase,2)/period**2,weights=np.stack([np.interp(phase,np.arange(120)/120,weights[:,k],period=1) for k in range(4)],1)))
a.N=N;a.stance=(phase[:,None]+np.array([0,.5,.75,.25]))%1<.8
# Encoded pickup fraction guarantees F+b<=83 mm (existing lower-link joint span).
def decode(x):
 A,F,t,L,H,cx,cz=x;return np.array([A,F,20,10+t*(73-F),L,H,cx,cz])
def encode(v):
 A,F,r,b,L,H,cx,cz=v;return np.array([A,F,(b-10)/(73-F),L,H,cx,cz])
def objective(x,details=False):
 v=decode(x);rr=[]
 for c in conditions:
  for key,value in c.items():setattr(a,key,value)
  r=a.perf(v,True);rr.append(r)
 if not all(r['valid'] for r in rr):score=100+sum(r['score']-100 for r in rr if not r['valid'])
 else:
  demand=max(max(r['utilization']) for r in rr)
  support=max(max(r['loaded_rms_torque_Nm'])+2*r['loaded_difference_rms_Nm'] for r in rr)
  score=demand+2*support/.1765197+2*max(0,v[0]/v[1]-35/55)**2+10*max(0,45-min(r['min_angle'] for r in rr))**2
 return dict(dimensions=v.tolist(),stroke_mm=S,objective=score,conditions=rr) if details else score
bounds=[(20,70),(45,55),(0,1),(10,80),(30,95),(-60,60),(-50,50)];count=[0]
def cb(x):
 count[0]+=1
 if count[0]%100==0:print('iteration',count[0],'score',objective(x),flush=True)
print('START',json.dumps(objective(encode(initial),True)),flush=True)
fit=minimize(objective,encode(initial),method='Nelder-Mead',bounds=bounds,callback=cb,options={'maxiter':1400,'xatol':.002,'fatol':1e-6})
out=objective(fit.x,True);out.update(converged=bool(fit.success),iterations=fit.nit,scope='Local multi-speed actual-foot/body optimization; fixed starting support trajectories and reactions; no hardware qualification. Knee-to-foot45–55,crank20,lower-link joint span<=original83. Short-carrier soft preference uses original35/55 ratio,not a hard ceiling.')
f=P/('refined-'+source.replace('body-audit-',''));f.write_text(json.dumps(out,indent=2));print('RESULT',f.name,json.dumps(out),flush=True)
