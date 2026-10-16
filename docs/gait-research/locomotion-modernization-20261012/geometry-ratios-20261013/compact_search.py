"""Owner-requested 45/50/55 mm comparison; research constraints, no firmware edits."""
import json,numpy as np
from pathlib import Path
from scipy.stats import qmc
import ratio_model as m
p=Path(__file__).resolve().parent
rows=[]
for stroke in [60,70,82]:
 phase=m.phase;u=np.clip((phase-.8)/.2,0,1);smooth=10*u**3-15*u**4+6*u**5;e=u-10*u**3+15*u**4-6*u**5
 m.x=np.where(m.stance,stroke/2-stroke*phase/.8,-stroke/2+stroke*smooth-stroke*.2/.8*e)
 for F in [45,50,55]:
  for free in [False,True]:
   bounds=np.array([[24,50],[F,F],[20,32],[20,min(38,83-F)],[22,55],[45,65],[-12.5,-12.5],[11.5,11.5]])
   if free:bounds[-2:]=[[-20,5],[-5,20]]
   v=qmc.Sobol(8,scramble=True,seed=17).random_base2(13);v=bounds[:,0]+v*(bounds[:,1]-bounds[:,0]);good=[]
   for start in range(0,len(v),256):
    d=v[start:start+256];valid,ang,vert,comb,speed,ranges=m.evaluate(d)
    ids=np.flatnonzero(valid&(ang>=45)&np.isfinite(comb).all(1)&np.isfinite(speed).all(1))
    for i in ids:
     good.append(dict(dimensions=d[i].tolist(),min_loaded_angle_deg=float(ang[i]),peak_vertical_Nm_per_10N=vert[i].tolist(),peak_traction_Nm_per_10N=comb[i].tolist(),peak_speed_deg_s=speed[i].tolist(),excursions_deg=ranges[i].tolist()))
   for speedbin in [400,600,800]:
    candidates=[r for r in good if max(r['peak_speed_deg_s'])<=speedbin]
    if candidates:
     best=sorted(candidates,key=lambda r:max(r['peak_traction_Nm_per_10N']))[:3]
     rows.append(dict(stroke=stroke,leg=F,relocate=free,speed_bin=speedbin,feasible_samples=len(candidates),best=best))
   print('stroke',stroke,'foot',F,'relocate',free,'closed upright',len(good),flush=True)
(p/'compact-45-55-comparison.json').write_text(json.dumps(rows,indent=2))
for stroke in [60,70,82]:
 for F in [45,50,55]:
  for free in [False,True]:
   a=[r for r in rows if r['stroke']==stroke and r['leg']==F and r['relocate']==free and r['speed_bin']==600]
   if a:print(json.dumps(a[0]|{'best':a[0]['best'][:1]}),flush=True)
