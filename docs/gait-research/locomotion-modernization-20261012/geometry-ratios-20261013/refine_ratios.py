from ratio_model import *
from scipy.optimize import differential_evolution
rows=json.loads((p/'ratio-candidates.json').read_text())
# Local refinement of the sampled existing-pivot candidate; design comparisons only.
seed=min([r for r in rows if not r['relocated_pivot'] and max(r['peak_speed_deg_s'])<600],key=lambda r:max(r['peak_traction_envelope_Nm']))
initial=np.array(seed['dimensions'])
def loss(v):
 d=np.r_[v,[-12.5,11.5]][None,:];valid,angle,vert,comb,speed,ranges=evaluate(d)
 if not valid[0] or not np.isfinite(comb).all():return 1e4
 return max(comb[0])+10*max(0,45-angle[0])**2+1e-4*max(0,max(speed[0])-600)**2
bounds=[(max(lo,v-delta),min(hi,v+delta)) for v,delta,lo,hi in zip(initial[:6],[8,10,8,8,10,10],[20,35,20,20,20,35],[80,90,45,60,90,110])]
fit=differential_evolution(loss,bounds,x0=initial[:6],seed=6,popsize=10,maxiter=110,tol=.0001,polish=True)
for v in [fit.x,np.round(fit.x),[26,72,28,43,26,64],[30,55,37,45,35,56]]:
 d=np.r_[v,[-12.5,11.5]][None,:];ok,ang,vert,comb,speed,ran=evaluate(d);print('trial',d.tolist(),bool(ok[0]),ang.tolist(),vert.tolist(),comb.tolist(),speed.tolist(),ran.tolist(),flush=True)
(p/'local-refinement.json').write_text(json.dumps({'dimensions':np.r_[fit.x,[-12.5,11.5]].tolist(),'score':float(fit.fun),'scope':'Local search on fixed motor pivots, 82 mm stroke; 45-degree loaded leg angle and 600 deg/s comparison criteria, not firmware limits.'},indent=2))
