import json,sys,numpy as np
from pathlib import Path
from scipy.spatial import ConvexHull
import optimize_dynamic_linkage as opt
P=Path(__file__).resolve().parent;base=P.parent
sys.path.insert(0,str(base/'body-support-20261013'))
import research as m,whole_body as w
# Evaluate at denser time resolution and at every user speed percentage.
opt.N=1000;opt.phase=np.arange(opt.N)/opt.N;opt.stance=opt.phase<opt.DUTY;opt.u=np.clip((opt.phase-opt.DUTY)/(1-opt.DUTY),0,1)
basepath=opt.path
lift_scale=1.
def path(stroke):
 x,z=basepath(stroke);return x,z*lift_scale
opt.path=path
candidates=[('compact60',[45,55,20,18.3,26.5,68.1,-10.9,-27.3],60),('medium82',[60,55,20.1,13.9,30.3,84,-5.3,-39.2],82),('unrestricted82',[113,53,20.1,14.5,63.2,135.4,-9.2,-59.3],82)]
rows=[]
for name,dims,S in candidates:
 sweep=[]
 for speed in range(1,101):
  opt.PERIOD=1.8/(1+speed/100);lift_scale=(2+8*speed/100)/10
  result=opt.evaluate(dims,S*speed/100,True)
  sweep.append(dict(speed=speed,period=opt.PERIOD,stroke=S*speed/100,**{k:v[0] for k,v in result.items()}))
 row=dict(name=name,dimensions=dims,stride_max=S,all_speeds_close=all(r['closed'] for r in sweep),minimum_loaded_angle=min(r['min_leg_angle'] for r in sweep),max_reference_utilization=max(max(r['peak_reference_utilization']) for r in sweep),full_speed=sweep[-1],sweep=sweep)
 rows.append(row);print(json.dumps({k:v for k,v in row.items() if k!='sweep'}),flush=True)
(P/'optimization-speed-1-100-verification.json').write_text(json.dumps(rows,indent=2))
