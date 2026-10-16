"""Fixed nominal20 mm crank; compact carrier; balance support effort explicitly.
Research only: all dimensions centre-to-centre, no firmware/calibration changes.
"""
import sys,json,numpy as np
from pathlib import Path
from scipy.stats import qmc
from scipy.optimize import differential_evolution,minimize
import optimize_dynamic_linkage as model
P=Path(__file__).resolve().parent
stroke=float(sys.argv[1]);amax=float(sys.argv[2]);seed=int(sys.argv[3]) if len(sys.argv)>3 else 31
# A,F,b,L,H,cx,cz; crank is fixed, not an optimizer variable.
bounds=[(20,amax),(45,55),(10,38),(10,80),(30,95),(-60,60),(-50,50)]
model.N=320;model.phase=np.arange(model.N)/model.N;model.stance=model.phase<.8;model.u=np.clip((model.phase-.8)/.2,0,1)
def expand(v):
 v=np.atleast_2d(v);return np.insert(v,2,20.,axis=1)
def objective(v,details=False):
 full=expand(v);r=model.evaluate(full,stroke,True)
 demand=np.max(r['peak_reference_utilization'],axis=1)
 support=np.max(r['static_support_rms_Nm'],axis=1)
 # Equalize instantaneous support effort without rewarding added torque alone.
 difference=np.array(r['static_support_difference_rms_Nm'])
 score=demand+2*(support+2*difference)/model.TREF + 2*np.maximum(0,full[:,0]/full[:,1]-35/55)**2
 angle=np.array(r['min_leg_angle']);closed=np.array(r['closed'])
 score=np.where(closed&np.isfinite(score)&(angle>=45)&(full[:,1]+full[:,3]<=83),score,100+np.nan_to_num(np.maximum(0,45-angle),nan=100))
 if details:return dict(dimensions=full.tolist(),objective=score.tolist(),**r)
 return score
bb=np.array(bounds);vals=qmc.Sobol(7,scramble=True,seed=seed).random_base2(13);vals=bb[:,0]+vals*(bb[:,1]-bb[:,0]);scores=[]
for k in range(0,len(vals),64):scores.extend(objective(vals[k:k+64]))
init=vals[np.argsort(scores)[:72]]
# Previously inspected compact reference, projected within this comparison envelope.
init=np.vstack([init,[min(26,amax),55,27,23,51,4,0]])
def loss(x):return objective(x.T) if x.ndim>1 else objective(x)[0]
counter=[0]
def progress(intermediate_result):
 counter[0]+=1
 if counter[0]%80==0:print('stroke',stroke,'generation',counter[0],'score',float(intermediate_result.fun),flush=True)
fit=differential_evolution(loss,bounds,init=init,seed=seed,maxiter=500,tol=1e-5,polish=False,vectorized=True,updating='deferred',callback=progress)
polish=minimize(lambda x:objective(x)[0],fit.x,method='Nelder-Mead',bounds=bounds,options={'maxiter':1400,'xatol':.001,'fatol':1e-6})
out=objective(polish.x,True);out.update(stroke_mm=stroke,carrier_max_mm=amax,crank_fixed_mm=20,global_converged=bool(fit.success),local_converged=bool(polish.success),seed=seed,scope='Planar spherical-toe screening; 0.9-second cycle,80% stance. Fixed20 mm crank,45–55 mm foot,minimum20 mm carrier. Static support effort objective plus generic MG90S torque-speed proxy. Requires actual bare-foot/full-body verification.')
(P/f'compact83-carrier{int(amax)}-stroke{int(stroke)}-seed{seed}.json').write_text(json.dumps(out,indent=2));print('RESULT',json.dumps(out),flush=True)
