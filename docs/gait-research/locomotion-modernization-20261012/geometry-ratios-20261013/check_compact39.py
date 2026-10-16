import json,sys,numpy as np
from pathlib import Path
from scipy.interpolate import CubicSpline
P=Path(__file__).resolve().parent;sys.argv=['research','compact60']
import optimize_actual_body as a
v=np.array(json.load(open(P/'compact83-rounded39.json'))['dimensions'][0]);row=json.load(open(P/'body-audit-compact83-rounded39-n1920.json'))['rows'][-1];saved=row['reference_body_plan'];N=480;phase=np.arange(N)/N
shift=np.array(saved['shift']);weights=np.array(saved['weights']);cs=CubicSpline(np.arange(121)/120,np.vstack([shift,shift[:1]]),bc_type='periodic')
a.N=N;a.period=.9;a.step=.9/N;a.shift=cs(phase);a.acc=cs(phase,2)/.9**2;a.weights=np.stack([np.interp(phase,np.arange(120)/120,weights[:,k],period=1) for k in range(4)],1)
a.pathmodel.N=N;a.pathmodel.phase=phase;a.pathmodel.stance=phase<.8;a.pathmodel.u=np.clip((phase-.8)/.2,0,1);a.pathmodel.PERIOD=.9
x,lift=a.pathmodel.path(40);a.feet=np.tile(a.centres,(N,1,1));a.lifts=np.zeros((N,4));a.stance=(phase[:,None]+np.array([0,.5,.75,.25]))%1<.8
for k,off in enumerate([0,N//2,3*N//4,N//4]):a.feet[:,k,0]+=np.roll(x,-off);a.lifts[:,k]=np.roll(lift,-off)
rows=[]
for j,label in enumerate(['carrier','foot','crank','pickup','rod','height','shaft_x','shaft_z']):
 for delta in [-.5,.5]:
  vv=v.copy();vv[j]+=delta;r=a.perf(vv,True);rows.append(dict(variable=label,delta_mm=delta,**r))
(P/'compact39-sensitivity.json').write_text(json.dumps({'scope':'Single-parameter perturbations on fixed nominal full-speed body trajectory; not joint manufacturing tolerance stack or collision analysis.','rows':rows},indent=2));print('closed',sum(r['valid'] for r in rows),'of',len(rows),'peak_speed',max(max(r['peak_speed_deg_s']) for r in rows if r['valid']),'max_proxy',max(max(r['utilization']) for r in rows if r['valid']))
