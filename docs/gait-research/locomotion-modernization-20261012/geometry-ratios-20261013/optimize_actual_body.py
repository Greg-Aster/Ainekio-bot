"""Refine using actual sole mesh, all four mechanisms, and modeled link dynamics."""
import json,sys,numpy as np,time
from pathlib import Path
from scipy.spatial import ConvexHull
from scipy.optimize import minimize
P=Path(__file__).resolve().parent;base=P.parent
sys.path.insert(0,str(base/'body-support-20261013'))
import research as m,whole_body as w
name=sys.argv[1] if len(sys.argv)>1 else 'compact60'
baseline=json.load(open(P/f'body-optimum-{name}-cycle.json'))
check=next(r for r in json.load(open(P/'optimized-body-cross-check.json')) if r['name']==name)
initial=np.array(check['dimensions']);stroke=check['stride'];N=120;period=.9;step=period/N
shift=np.array(baseline['body_shift']);acc=np.array(baseline['body_acceleration']);stance=np.array(baseline['stance']);weights=np.array(baseline['weights'])
# Keep the established point-body trajectory for this local refinement.
import optimize_dynamic_linkage as pathmodel
pathmodel.N=N;pathmodel.phase=np.arange(N)/N;pathmodel.stance=pathmodel.phase<.8;pathmodel.u=np.clip((pathmodel.phase-.8)/.2,0,1)
x,lift=pathmodel.path(stroke);centres=np.array([[66.69,64.5],[66.69,-64.5],[-66.72,64.5],[-66.72,-64.5]])
feet=np.tile(centres,(N,1,1));lifts=np.zeros((N,4))
for k,off in enumerate([0,60,90,30]):feet[:,k,0]+=np.roll(x,-off);lifts[:,k]=np.roll(lift,-off)
original=np.array(json.load(open(base/'installed55-20261013/bare55.json'))['vertices']);axis=np.array([m.u[0],0,m.u[1]]);proj=original@axis
coeff=np.array([1926.604/35,1040.189/20,1293.828/38,3911.507/83])*1.24e-6
body_mass=.566-4*np.dot([35,20,38,83],coeff)
frames=[]
for leg in w.legs:
 S=np.array(m.live['legs'][leg]['shoulder_matrix']);M=np.array(m.live['legs'][leg]['mechanism_matrix']);T=np.linalg.inv(S)@M
 frames.append((S[:3,:3],S[:3,3],T[:3,:3],T[:3,3]))
def perf(v,details=False):
 A,F,r,b,L,H,cx,cz=v
 m.A=A;m.foot=F;m.ref=F*m.u;m.r=r;m.b=b;m.L=L;m.C=m.O+[cx,cz]
 vertices=original+axis*np.clip((proj-7)/41,0,1)[:,None]*(F-55)-axis*np.clip((-proj-7)/14,0,1)[:,None]*(b-28)
 w.ref3=np.array([m.ref[0],-56.65,m.ref[1]]);w.hull3=vertices[ConvexHull(vertices).vertices]
 masses=coeff*np.array([A,r,L,F+b]);totalmass=body_mass+4*masses.sum()
 all_tau=[];all_speed=[];all_ranges=[];angles=[];all_q=[]
 for k,leg in enumerate(w.legs):
  target=np.c_[feet[:,k]-shift,47.27323-H+lifts[:,k]];ans=w.ik3(leg,target,H)
  if not ans['ok'].all():return {'valid':False,'score':100+int((~ans['ok']).sum())} if details else 100+int((~ans['ok']).sum())
  qq=np.unwrap(np.deg2rad(ans['q']),axis=0);all_q.append(qq);ranges=np.rad2deg(np.ptp(qq,axis=0));all_ranges.append(ranges)
  if ranges.max()>225:return {'valid':False,'score':100+ranges.max()} if details else 100+ranges.max()
  beta=ans['beta'];angle=np.degrees(np.arcsin(abs(np.sin(beta))))[stance[:,k]].min();angles.append(angle)
  D=ans['D'];PP=ans['P'];E=ans['E'];da=m.perp(D-m.O) if hasattr(m,'perp') else np.c_[-(D-m.O)[:,1],(D-m.O)[:,0]]
  ip=PP-m.C;dp=np.c_[-ip[:,1],ip[:,0]];out=E-D;rod=E-PP;den=m.cross(out,rod);ba=-np.sum(rod*da,1)/den;bt=np.sum(rod*dp,1)/den
  unit=out/b;pe=np.c_[-unit[:,1],unit[:,0]];Ea=da+b*ba[:,None]*pe;Et=b*bt[:,None]*pe
  R,ST,MR,MT=frames[k];h=qq[:,0];rx=np.zeros((N,3,3));rx[:,0,0]=1;rx[:,1,1]=np.cos(h);rx[:,1,2]=-np.sin(h);rx[:,2,1]=np.sin(h);rx[:,2,2]=np.cos(h)
  basis=np.einsum('ij,njk,kl->nil',R,rx,MR);origin=ST+np.einsum('ij,njk,k->ni',R,rx,MT)
  tau=np.zeros((N,2));zero=np.zeros_like(da)
  for j in range(4):
   for lam in [.5-1/np.sqrt(12),.5+1/np.sqrt(12)]:
    if j==0:point=m.O+lam*(D-m.O);jac=np.stack([lam*da,zero],-1)
    elif j==1:point=m.C+lam*ip;jac=np.stack([zero,lam*dp],-1)
    elif j==2:point=PP+lam*(E-PP);jac=np.stack([lam*Ea,dp+lam*(Et-dp)],-1)
    else:
     ss=-F+lam*(F+b);point=D+ss*unit;jac=np.stack([da+ss*ba[:,None]*pe,ss*bt[:,None]*pe],-1)
    local=np.c_[point[:,0],np.full(N,-56.65),point[:,1]]
    world=origin+np.einsum('nij,nj->ni',basis,local)+np.c_[shift,np.full(N,H-47.27323)]
    accel=(np.roll(world,-1,axis=0)-2*world+np.roll(world,1,axis=0))/(step*step*1000);accel[:,2]+=9.81
    jj=np.stack([jac[:,0,:],np.zeros((N,2)),jac[:,1,:]],axis=1);jworld=np.einsum('nij,njk->nik',basis,jj)
    tau+=np.einsum('nij,ni->nj',jworld/1000,accel)*(masses[j]/2)
  ground=weights[:,k,None]*totalmass*9.81*np.c_[acc/9810,np.ones(N)]
  tau-=np.einsum('nij,ni->nj',ans['jac'][:,:,1:]/1000,ground)
  vel=abs(np.rad2deg(np.arctan2(np.sin(np.roll(qq,-1,axis=0)-np.roll(qq,1,axis=0)),np.cos(np.roll(qq,-1,axis=0)-np.roll(qq,1,axis=0))))/(2*step))
  all_tau.append(abs(tau));all_speed.append(vel[:,1:])
 tau=np.array(all_tau);speed=np.array(all_speed);peak=tau.max((0,1));imbalance=abs(peak[0]-peak[1])/peak.max();util=(tau/.1765197+speed/600).max((0,1))
 score=util.max()+5*max(0,imbalance-.1)**2+ .005*(A+r+b+L)/100+10*max(0,45-min(angles))**2
 out={'valid':True,'score':score,'dimensions':list(v),'peak_torque_Nm':peak.tolist(),'peak_speed_deg_s':speed.max((0,1)).tolist(),'utilization':util.tolist(),'imbalance':float(imbalance),'min_angle':float(min(angles)),'ranges':np.max(all_ranges,axis=0).tolist(),'estimated_mass_kg':float(totalmass)}
 loaded=tau[stance.T]
 out['loaded_rms_torque_Nm']=np.sqrt(np.mean(loaded**2,axis=0)).tolist()
 out['loaded_difference_rms_Nm']=float(np.sqrt(np.mean((loaded[:,0]-loaded[:,1])**2)))
 return out if details else score
if __name__=='__main__':
 bound=[(20,160),(45,55),(20,100),(8,120),(8,180),(35,170),(-100,100),(-100,80)]
 if name=='compact60':bound[0]=(20,45)
 if name=='medium82':bound[0]=(20,60)
 print('BASELINE',json.dumps(perf(initial,True)),flush=True)
 counter=[0]
 def cb(v):
  counter[0]+=1
  if counter[0]%100==0:print('iteration',counter[0],'score',perf(v),flush=True)
 fit=minimize(perf,initial,method='Nelder-Mead',bounds=bound,callback=cb,options={'maxiter':1800,'xatol':.002,'fatol':1e-6})
 result=perf(fit.x,True);result.update(name=name,stride=stroke,converged=bool(fit.success),iterations=fit.nit,scope='Local minimax optimum; fixed previously solved body trajectory; actual sole mesh; uniform-link mass scenario; generic motor torque-speed proxy. Not a proven global optimum or physical qualification.')
 (P/f'actual-body-optimized-{name}.json').write_text(json.dumps(result,indent=2));print('RESULT',json.dumps(result),flush=True)
