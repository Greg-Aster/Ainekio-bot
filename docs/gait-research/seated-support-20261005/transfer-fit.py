from remap import *
from scipy.optimize import minimize

def inv_constraints(a,beta):
 D=m.O+m.A*np.array([math.cos(m.a0+a),math.sin(m.a0+a)]);E=D+m.b*np.array([math.cos(beta),math.sin(beta)]);v=E-m.C;d=np.linalg.norm(v);co=(m.r*m.r+d*d-m.L*m.L)/(2*m.r*d);t=math.atan2(v[1],v[0])-math.acos(np.clip(co,-1,1));P=m.C+m.r*np.array([math.cos(t),math.sin(t)]);w=P-D;e=E-D;return [d-abs(m.L-m.r),m.L+m.r-d,(w[0]*e[1]-w[1]*e[0])/m.b]

def transfer(row,anchor,previous=None,root_x=None):
 anchor=anchor.copy();anchor[2]=row['foot_bolt_world_mm'][0][2]
 oq=np.array(row['actuator_angles_rad']);b0=np.array(row['body_translation_world_mm']);e0=np.array(row['body_rotation_euler_xyz_rad']);old.body_euler=e0;oldR,_=old.pose('FL',oq[0],b0);Rf,Tf=old.pose('RL',oq[2],b0);frontold=old.hulls['RL']@Rf.T+Tf;bodyold=(hulls['body']-pivot)@ref.ry(e0[1]).T+pivot+b0;xy=np.array(row['foot_bolt_world_mm'][2])[:2]
 def evaluate(v):
  ar,pitch,hf,af,bf=v;m.body_euler=np.array([0.,pitch,0.]);S=np.array(m.geom['FL']['shoulder_world']);M=np.array(m.geom['FL']['mechanism_local']);rb=ref.ry(pitch)@S[:3,:3]@ref.rx(oq[0,0])@M[:3,:3];rot=rb.T@oldR;br=m.b0-math.atan2(rot[0,2],rot[0,0]);R,T=serial_pose('FL',oq[0,0],ar,br,np.zeros(3));body=anchor-R@m.geom['FL']['foot_reference_local_mm']-T;R,T=serial_pose('RL',hf,af,bf,body);pt=R@m.geom['RL']['foot_reference_local_mm']+T;verts=m.hulls['RL']@R.T+T;bverts=(hulls['body']-pivot)@ref.ry(pitch).T+pivot+body;eq=np.r_[pt[:2]-xy,verts[:,2].min()]
  if root_x is not None:eq=np.r_[eq,body[0]-root_x]
  cons=np.r_[inv_constraints(ar,br),inv_constraints(af,bf),bverts[:,2].min()];cost=np.mean(np.sum((bverts-bodyold)**2,axis=1))+np.mean(np.sum((verts-frontold)**2,axis=1))
  for aa,bb,oi in [(ar,br,0),(af,bf,2)]:
   D=m.O+m.A*np.array([math.cos(m.a0+aa),math.sin(m.a0+aa)]);E=D+m.b*np.array([math.cos(bb),math.sin(bb)]);v=E-m.C;d=np.linalg.norm(v);co=(m.r*m.r+d*d-m.L*m.L)/(2*m.r*d);tt=math.atan2(v[1],v[0])-math.acos(np.clip(co,-1,1));P=m.C+m.r*np.array([math.cos(tt),math.sin(tt)]);oldD,oldP,*_=old.planar(oq[oi]);cost+=float(np.sum((P-oldP)**2))
  return cost,eq,cons,br,body
 if previous is None:previous=np.array([oq[0,1],e0[1]+.1,oq[2,0],oq[2,1],old.planar(oq[2])[3]])
 fit=minimize(lambda v:evaluate(v)[0],previous,method='SLSQP',constraints=[{'type':'eq','fun':lambda v:evaluate(v)[1]},{'type':'ineq','fun':lambda v:evaluate(v)[2]}],options={'maxiter':100,'ftol':1e-9})
 cost,eq,cons,br,body=evaluate(fit.x)
 if np.linalg.norm(eq)>.001 or cons.min()<-.001:raise ValueError(('transfer',row['time_s'],fit.message,eq,cons))
 ar,pitch,hf,af,bf=fit.x;rear=inverse(oq[0,0],ar,br,oq[0,2]);front=inverse(hf,af,bf,oq[2,2]);return fit.x,body,rear,front,cost
if __name__=='__main__':
 s=read((WORK/'sit.json'));src=read(BASE/'motions/gestures/upright/source.json');anchor=np.array(s['samples'][360]['foot_bolt_world_mm'][0]);previous=None
 for n in range(960,1441,30):
  previous,body,rear,front,cost=transfer(src['samples'][n],anchor,previous);print(n/120,'pitchdelta',math.degrees(previous[1]-src['samples'][n]['body_rotation_euler_xyz_rad'][1]),'rootdelta',body-np.array(src['samples'][n]['body_translation_world_mm']),'q',np.degrees(front),cost,flush=True)
