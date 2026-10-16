import sys,json,numpy as np
from pathlib import Path
from scipy.optimize import minimize
import optimize_dynamic_linkage as m
P=Path(__file__).resolve().parent
for stroke in [60,82]:
 r=json.load(open(P/f'dynamic-optimized-expanded-stride{stroke}-seed41.json'));v=np.array(r['dimensions'])
 m.N=400;m.phase=np.arange(m.N)/m.N;m.stance=m.phase<m.DUTY;m.u=np.clip((m.phase-m.DUTY)/(1-m.DUTY),0,1)
 # Local constrained refinement of the global-search result.
 fit=minimize(lambda x:float(m.evaluate(x,stroke)[0]),v,method='Nelder-Mead',bounds=r['bounds'],options={'maxiter':5000,'xatol':.0002,'fatol':1e-7})
 r['dimensions']=fit.x.tolist();r['result']=m.evaluate(fit.x,stroke,True);r['local_converged']=bool(fit.success);r['local_iterations']=fit.nit
 (P/f'dynamic-polished-{stroke}.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True)
