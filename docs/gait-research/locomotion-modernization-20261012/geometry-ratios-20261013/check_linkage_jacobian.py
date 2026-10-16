import sys,json,numpy as np
from pathlib import Path
P=Path(__file__).resolve().parent;sys.path.insert(0,str(P));import optimize_actual_body as a
v=json.load(open(P/f'actual-body-optimized-{a.name}.json'))['dimensions'];a.perf(v,True);m=a.m
ans=a.w.ik3(a.w.legs[0],np.c_[a.feet[:,0]-a.shift,47.27323-v[5]+a.lifts[:,0]],v[5]);errors=[]
for i in [0,20,60,97,105,115]:
 D=ans['D'][i];P0=ans['P'][i];E=ans['E'][i];ang=np.array([np.arctan2(*(D-m.O)[::-1]),np.arctan2(*(P0-m.C)[::-1])]);rod=E-P0;out=E-D;da=np.array([-(D-m.O)[1],(D-m.O)[0]]);dt=np.array([-(P0-m.C)[1],(P0-m.C)[0]]);den=m.cross(out,rod);ba=-rod@da/den;bt=rod@dt/den;unit=out/m.b;pe=np.array([-unit[1],unit[0]])
 def loc(q,ss):
  DD=m.O+m.A*np.array([np.cos(q[0]),np.sin(q[0])]);PP=m.C+m.r*np.array([np.cos(q[1]),np.sin(q[1])]);opts=[DD+m.circle(PP-DD,m.b,m.L,s)[0] for s in [-1,1]];EE=min(opts,key=lambda z:np.linalg.norm(z-E));return DD+ss*(EE-DD)/m.b
 for ss in [-m.foot,(m.b-m.foot)/2,m.b]:
  analytic=np.stack([da+ss*ba*pe,ss*bt*pe],-1);fd=np.stack([(loc(ang+np.eye(2)[j]*1e-6,ss)-loc(ang-np.eye(2)[j]*1e-6,ss))/(2e-6) for j in range(2)],-1);errors.append(float(abs(analytic-fd).max()))
result={'geometry':a.name,'point_jacobian_max_error_mm_per_rad':max(errors),'checks':len(errors),'scope':'Independent finite difference of closed-chain linkage pickup, foot and centre points; not contact dynamics or hardware proof.'}
print(result);(P/f'jacobian-check-{a.name}.json').write_text(json.dumps(result,indent=2))
