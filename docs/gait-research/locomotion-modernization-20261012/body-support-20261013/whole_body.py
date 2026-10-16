import research as m
import numpy as np,json
from scipy.spatial import ConvexHull
from scipy.optimize import minimize
live=m.live;data=json.loads((m.p/'body-plan.json').read_text());legs=['RL','RR','FL','FR'];N=len(data['phase']);shift=np.array(data['body_shift']);feet=np.array(data['feet_nominal']);lift=np.array(data['lift']);stance=np.array(data['stance']);acc=np.array(data['body_acceleration_mm_s2']);cop=np.array(data['effective_support_xy']);phase=np.array(data['phase']);ref3=np.r_[m.ref[0],-56.65,m.ref[1]]
verts=np.array(live['legs']['RL']['vertices']);hull3=verts[ConvexHull(verts).vertices]

def ik3(leg,target,H):
 S=np.array(live['legs'][leg]['shoulder_matrix']);M=np.array(live['legs'][leg]['mechanism_matrix']);T=np.linalg.inv(S)@M;R0=S[:3,:3];ST=S[:3,3];sr=np.linalg.inv(R0);mr=T[:3,:3];mt=T[:3,3];zsole=target[:,2];F=target.copy();F[:,2]+=7.5;ok=np.ones(len(F),bool)
 for iteration in range(15):
  v=(F-ST)@sr.T;ylocal=mt[1]+mr[1,1]*ref3[1];z2=v[:,1]**2+v[:,2]**2-ylocal**2;ok=z2>=0;z=-np.sqrt(np.maximum(z2,0));norm=v[:,1]**2+v[:,2]**2;hc=(ylocal*v[:,1]+z*v[:,2])/norm;hs=(ylocal*v[:,2]-z*v[:,1])/norm;h=np.arctan2(hs,hc)
  x=(v[:,0]-mt[0])/mr[0,0];zz=(z-mt[2])/mr[2,2];F2=np.c_[x,zz];k,ok1=m.circle(F2-m.O,m.A,m.foot,-1);D=m.O+k;lower=(F2-D)/m.foot;E=D-m.b*lower;po,ok2=m.circle(E-m.C,m.r,m.L,-1);P=m.C+po;beta=np.arctan2(-lower[:,1],-lower[:,0]);a=np.arctan2(k[:,1],k[:,0]);theta=np.arctan2(po[:,1],po[:,0]);co=np.cos(beta-m.b0);si=np.sin(beta-m.b0)
  rx=np.zeros((len(F),3,3));rx[:,0,0]=1;rx[:,1,1]=hc;rx[:,1,2]=-hs;rx[:,2,1]=hs;rx[:,2,2]=hc;basis=np.einsum('ij,njk,kl->nil',R0,rx,mr);origin=ST+np.einsum('ij,njk,k->ni',R0,rx,mt)
  normal=np.c_[basis[:,2,0]*co+basis[:,2,2]*si,basis[:,2,1],-basis[:,2,0]*si+basis[:,2,2]*co];heights=normal@hull3.T;idx=heights.argmin(1);bottom=heights[np.arange(len(F)),idx]+origin[:,2]+basis[:,2,0]*D[:,0]+basis[:,2,2]*D[:,1];F[:,2]+=zsole-bottom
 q=np.rad2deg(np.c_[h,np.arctan2(np.sin(a-m.a0),np.cos(a-m.a0)),np.arctan2(np.sin(theta-m.t0),np.cos(theta-m.t0))]);rod=E-P;op=E-D;ip=P-m.C;ok &=ok1&ok2&(m.cross(P-D,E-D)>0)&(abs(bottom-zsole)<.002)
 contactlocal=hull3[idx];cv=np.c_[co*contactlocal[:,0]-si*contactlocal[:,2],contactlocal[:,1],si*contactlocal[:,0]+co*contactlocal[:,2]];kp=np.c_[D[:,0],np.zeros(len(D)),D[:,1]];contact=origin+np.einsum('nij,nj->ni',basis,kp+cv)
 den=m.cross(op,rod);da=np.c_[-k[:,1],k[:,0]];dp=np.c_[-ip[:,1],ip[:,0]];ba=-np.sum(rod*da,1)/den;bt=np.sum(rod*dp,1)/den
 jc=np.c_[da[:,0]-cv[:,2]*ba,np.zeros(len(D)),da[:,1]+cv[:,0]*ba];jt=np.c_[-cv[:,2]*bt,np.zeros(len(D)),cv[:,0]*bt]
 jh=np.linalg.det(R0)*np.cross(np.tile(R0[:,0],(len(D),1)),contact-ST)
 J=np.stack([jh,np.einsum('nij,nj->ni',basis,jc),np.einsum('nij,nj->ni',basis,jt)],-1)
 angle=lambda a,b:np.rad2deg(np.arccos(np.clip(abs(np.sum(a*b,1))/(np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1)),0,1)))
 return dict(q=q,ok=ok,contact=contact,jac=J,D=D,P=P,E=E,beta=beta,phi=np.arctan2(rod[:,1],rod[:,0]),input=angle(rod,ip),output=angle(rod,op),bottom_error=bottom-zsole)

def evaluate(params,details=False):
 m.A,m.b,m.L,H=params;answers=[];valid=True;stance_valid=True;stance_closed=True;pulse_ranges=[]
 homes=[[1600,2444,2577],[1670,856,723],[1670,2444,2577],[1760,856,723]];inv=[[False,True,True],[True,False,False],[True,True,True],[False,False,False]]
 for k,leg in enumerate(legs):
  target=np.c_[feet[:,k,:]-shift,m.floor-H+lift[:,k]];v=ik3(leg,target,H);answers.append(v);pulse=np.array(homes[k])+(v['q']-[0,1.17,-40.41])*(100/9)*np.where(inv[k],-1,1);pulse_ranges.append(np.c_[pulse.min(0),pulse.max(0)].tolist());valid &=v['ok'].all() and (pulse>=400).all() and (pulse<=2900).all();stance_closed &=v['ok'][stance[:,k]].all();stance_valid &=v['ok'][stance[:,k]].all() and (pulse[stance[:,k]]>=400).all() and (pulse[stance[:,k]]<=2900).all()
 # Each foot's contact point and support reactions are computed from solved geometry.
 contacts=np.stack([a['contact'][:,:2]+shift for a in answers],1);weights=[];margins=[];tau=[];force_errors=[]
 for i in range(N):
  ids=np.flatnonzero(stance[i]);xy=contacts[i,ids];h=ConvexHull(xy).equations;targetcop=shift[i]-(H+15.75)/9810*acc[i];margins.append(float(-(h[:,:2]@targetcop+h[:,2]).max()));B=np.vstack([xy.T,np.ones(len(ids))]);rhs=np.r_[targetcop,1]
  if len(ids)==3:w=np.linalg.solve(B,rhs)
  else:
   # Minimize squared actuator demand across the four active contacts.
   J=np.stack([answers[k]['jac'][i] for k in ids]);direction=np.r_[acc[i]/9810,1.];cost=np.sum(np.einsum('kij,i->kj',J,direction)**2,axis=1)
   fun=lambda w:np.sum(cost*w*w);jac=lambda w:2*cost*w
   fit=minimize(fun,np.full(len(ids),1/len(ids)),jac=jac,constraints=[{'type':'eq','fun':lambda w:B@w-rhs,'jac':lambda w:B}],bounds=[(0,float(data['force_fraction_upper'][i][k])) for k in ids],method='SLSQP',options={'ftol':1e-10,'maxiter':80});w=fit.x
  force_errors.append(float(abs(B@w-rhs).max()))
  wfull=np.zeros(4);wfull[ids]=w;weights.append(wfull)
  # Nm per kg of robot total mass, normalized by shared reaction forces.
  joint=[]
  for k in range(4):joint.append(answers[k]['jac'][i].T@np.r_[acc[i]/9810,1.]*9.81/1000*wfull[k])
  tau.append(joint)
 tau=np.array(tau);weights=np.array(weights);qs=np.stack([a['q'] for a in answers],1);qd=np.gradient(qs,2/N,axis=0);r=dict(carrier=m.A,pickup=m.b,rod=m.L,height=H,valid_kinematics_and_pulses=bool(valid),valid_stance=bool(stance_valid),stance_closed=bool(stance_closed),min_support_margin_mm=min(margins),min_weight_fraction=float(weights.min()),max_force_equilibrium_error=max(force_errors),peak_joint_torque_Nm_per_kg=np.max(abs(tau),axis=(0,1)).tolist(),rms_joint_torque_Nm_per_kg=np.sqrt(np.mean(tau*tau,axis=(0,1))).tolist(),peak_speed_deg_s=np.max(abs(qd),axis=(0,1)).tolist(),min_input_deg=min(float(a['input'].min()) for a in answers),min_output_deg=min(float(a['output'].min()) for a in answers),pulse_ranges=pulse_ranges)
 if details:r.update(phase=phase.tolist(),body_shift=shift.tolist(),body_z=H-m.floor,body_acceleration=acc.tolist(),stance=stance.tolist(),contact_xy=contacts.tolist(),support_margin_mm=margins,weights=weights.tolist(),joint_torques=tau.tolist(),legs={leg:{k:val.tolist() for k,val in v.items()} for leg,v in zip(legs,answers)})
 return r

if __name__=='__main__':
 candidates=[(35,28,30,35),(35,28,26,45),(40,24,34,45),(40,28,30,45),(40,32,26,50),(40,32,30,50),(40,36,26,50),(45,36,30,55)]
 rows=[]
 for c in candidates:
  try:r=evaluate(c);rows.append(r);print({k:v for k,v in r.items() if k!='pulse_ranges'},flush=True)
  except Exception as e:print('FAIL',c,str(e),flush=True)
 (m.p/'whole-body-comparison.json').write_text(json.dumps(rows,indent=2))
