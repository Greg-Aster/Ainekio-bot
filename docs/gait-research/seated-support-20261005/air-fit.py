from remap import *
from scipy.optimize import minimize
from scipy.spatial import cKDTree

def plane(a,t):
 D=m.O+m.A*np.array([math.cos(m.a0+a),math.sin(m.a0+a)]);P=m.C+m.r*np.array([math.cos(m.t0+t),math.sin(m.t0+t)]);w=P-D;d=np.linalg.norm(w);along=(m.b*m.b-m.L*m.L+d*d)/(2*d);height=math.sqrt(max(0,m.b*m.b-along*along));E=D+(along*w+height*np.array([-w[1],w[0]]))/d;beta=math.atan2(E[1]-D[1],E[0]-D[0]);tip=D-m.O+(ref.ry(m.b0-beta)@ankle)[[0,2]];v=E-m.C;u=P-m.C;cross=v[0]*u[1]-v[1]*u[0];return tip,np.array([d-abs(m.b-m.L),m.b+m.L-d,-cross/38.])

def make_grid():
 qs=[];points=[]
 for a in np.linspace(-math.pi,math.pi,361):
  for t in np.linspace(-math.pi,math.pi,361):
   tip,cons=plane(a,t)
   if cons.min()>.001:qs.append([a,t]);points.append(tip)
 return np.array(qs),np.array(points)
cache=(WORK/'air-grid.npz')
if not cache.exists():
 qs,points=make_grid();np.savez(cache,q=qs,points=points)
grid=np.load(cache);knees=m.A*np.c_[np.cos(m.a0+grid['q'][:,0]),np.sin(m.a0+grid['q'][:,0])];tree=cKDTree(np.c_[grid['points'],knees])
def fitair(oq,previous,tip_delta=None,knee_delta=None,body=None):
 D,P,E,beta,_=old.planar(oq);target=D-old.O+(ref.ry(old.b0-beta)@ankle)[[0,2]];knee=D-old.O
 if tip_delta is not None:target=target+tip_delta
 if knee_delta is not None:knee=knee+knee_delta
 _,idx=tree.query(np.r_[target,knee],k=4);seeds=[previous[1:]]+list(grid['q'][idx]);candidates=[]
 for seed in seeds:
  def cost(x):
   tip,cons=plane(*x);delta=np.remainder(x-previous[1:]+math.pi,2*math.pi)-math.pi
   return np.sum((tip-target)**2)+np.sum((m.A*np.array([math.cos(m.a0+x[0]),math.sin(m.a0+x[0])])-knee)**2)+1e-5*np.sum(delta**2)
  constraints=[dict(type='ineq',fun=lambda x:plane(*x)[1])]
  if body is not None:
   def floor(x):
    try:return m.vertices('RL',np.r_[oq[0],x],body)[:,2].min()
    except ValueError:return -1000.
   constraints.append(dict(type='ineq',fun=floor))
  fit=minimize(cost,seed,method='SLSQP',constraints=constraints,options={'maxiter':60,'ftol':1e-10})
  tip,cons=plane(*fit.x)
  if cons.min()>-1e-5:
   x=previous[1:]+np.remainder(fit.x-previous[1:]+math.pi,2*math.pi)-math.pi;candidates.append((cost(x),np.r_[oq[0],x],float(np.linalg.norm(tip-target))))
 if not candidates:raise ValueError(('air optimization',oq))
 best=min(candidates,key=lambda x:x[0]);return best[1:]
if __name__=='__main__':
 src=read(BASE/'motions/gestures/upright/source.json');prev=np.array(src['samples'][1440]['actuator_angles_rad'][2]);qs=[];err=[]
 for n in range(1440,2401,12):
  prev,e=fitair(np.array(src['samples'][n]['actuator_angles_rad'][2]),prev);qs.append(prev);err.append(e)
  if n%120==0:print(n/120,'q',np.degrees(prev),'err',e,flush=True)
 print('step',np.degrees(abs(np.diff(qs,axis=0))).max());np.savez(WORK/'air-path.npz',q=qs,error=err)
