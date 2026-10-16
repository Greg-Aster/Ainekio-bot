"""Actual native commands and bare-foot FK; no robot I/O. Ground forces are modeled."""
import sys,json,subprocess,numpy as np
from pathlib import Path
from scipy.spatial import ConvexHull
P=Path(__file__).resolve().parent
sys.path.insert(0,str(P));args=sys.argv[1:];sys.argv=['audit','compact60']
import optimize_actual_body as a
root=Path('/home/greggles/Ainekio/Slave/software/models/v2-12servo')
cfg=json.load(open(root/'geometry.json'));sole=np.array(json.load(open(root/'motions/locomotion/walk-contact.json'))['sole_hull_local_mm'])
binary=Path(next((arg for arg in args if not arg.startswith('--')),None) or '/tmp/ainekio-gait-repair-native/v2_model/v2_walk_command')
homes=np.array([[1670,2444,2577],[1760,856,723],[1600,2444,2577],[1670,856,723]]);signs=np.where([[True,True,True],[False,False,False],[False,True,True],[True,False,False]],-1,1)
O=a.m.O;C=np.array(cfg['parameters']['C_new']);a0=a.m.a0;t0=a.m.t0;b0=a.m.b0

def measure(rows):
 times=np.array([r['ms'] for r in rows])/1000;body=np.array([r['body'] for r in rows]);q=np.array([r['q'] for r in rows]).reshape(-1,4,3);grounded=np.array([r['grounded'] for r in rows]);phase=np.array([r['phase'] for r in rows]);N=len(rows)
 pulses=homes+(np.rad2deg(q)-[0,1.17,-40.41])*100/9*signs
 moving=(phase>=4)&(times<15);contacts=[];jacs=[];angles=[];inputs=[];outputs=[]
 for k in range(4):
  aa=q[:,k,1]+a0;tt=q[:,k,2]+t0
  D=O+35*np.c_[np.cos(aa),np.sin(aa)];PP=C+20*np.c_[np.cos(tt),np.sin(tt)]
  out,ok=a.m.circle(PP-D,28,38,1);E=D+out;beta=np.arctan2(out[:,1],out[:,0]);rot=beta-b0
  R,ST,MR,MT=a.frames[k];h=q[:,k,0];rx=np.zeros((N,3,3));rx[:,0,0]=1;rx[:,1,1]=np.cos(h);rx[:,1,2]=-np.sin(h);rx[:,2,1]=np.sin(h);rx[:,2,2]=np.cos(h)
  basis=np.einsum('ij,njk,kl->nil',R,rx,MR);origin=ST+np.einsum('ij,njk,k->ni',R,rx,MT)+body
  co=np.cos(rot);si=np.sin(rot);normal=np.c_[basis[:,2,0]*co+basis[:,2,2]*si,basis[:,2,1],-basis[:,2,0]*si+basis[:,2,2]*co]
  idx=(normal@sole.T).argmin(1);v=sole[idx];cv=np.c_[co*v[:,0]-si*v[:,2],v[:,1],si*v[:,0]+co*v[:,2]]
  contact=origin+np.einsum('nij,nj->ni',basis,cv+np.c_[D[:,0],np.zeros(N),D[:,1]]);contacts.append(contact)
  rod=E-PP;ip=PP-C;da=np.c_[-(D-O)[:,1],(D-O)[:,0]];dp=np.c_[-ip[:,1],ip[:,0]];den=a.m.cross(out,rod);ba=-np.sum(rod*da,1)/den;bt=np.sum(rod*dp,1)/den
  jac=np.stack([np.c_[da[:,0]-cv[:,2]*ba,np.zeros(N),da[:,1]+cv[:,0]*ba],np.c_[-cv[:,2]*bt,np.zeros(N),cv[:,0]*bt]],-1)
  jacs.append(np.einsum('nij,njk->nik',basis,jac))
  direction=np.einsum('nij,nj->ni',basis,np.c_[-out[:,0]/28,np.zeros(N),-out[:,1]/28]);angles.append(np.rad2deg(np.arcsin(np.clip(abs(direction[:,2]),0,1))))
  angle=lambda v,w:np.rad2deg(np.arccos(np.clip(abs((v*w).sum(1))/(np.linalg.norm(v,axis=1)*np.linalg.norm(w,axis=1)),0,1)))
  inputs.append(angle(rod,ip));outputs.append(angle(rod,out))
 contacts=np.stack(contacts,1);jacs=np.stack(jacs,1);angles=np.array(angles).T;inputs=np.array(inputs).T;outputs=np.array(outputs).T
 acc=np.gradient(np.gradient(body[:,:2],times,axis=0),times,axis=0)
 margins=[];weights=[];torques=[]
 for i in np.flatnonzero(moving):
  ids=np.flatnonzero(grounded[i]);xy=contacts[i,ids,:2];cop=body[i,:2]-(65+body[i,2])/9810*acc[i]
  if len(ids)<3:continue
  hull=ConvexHull(xy).equations;margins.append(float(-(hull[:,:2]@cop+hull[:,2]).max()))
  B=np.vstack([xy.T,np.ones(len(ids))]);ww=np.linalg.lstsq(B,np.r_[cop,1],rcond=None)[0];full=np.zeros(4);full[ids]=ww;weights.append(full)
  torques.append(np.einsum('kij,i->kj',jacs[i]/1000,np.r_[acc[i]/9810,1])*full[:,None]*.566*9.81)
 active=grounded&moving[:,None]
 vel=np.rad2deg(np.gradient(np.unwrap(q,axis=0),times,axis=0))
 result={'samples':N,'complete':rows[-1]['complete'],'pulse_span_us':[float(pulses.min()),float(pulses.max())],'minimum_scheduled_contacts':int(grounded[moving].sum(1).min()),'loaded_leg_min_deg':float(angles[active].min()),'loaded_input_min_deg':float(inputs[active].min()),'loaded_output_min_deg':float(outputs[active].min()),'peak_joint_speed_deg_s_steady':abs(vel[moving]).max((0,1)).tolist(),'body_z_mm':float(np.median(body[moving,2])),'bare_sole_target_error_mm':[float((contacts[:,:,2]-np.array([r['feet'] for r in rows])[:,:,2]).min()),float((contacts[:,:,2]-np.array([r['feet'] for r in rows])[:,:,2]).max())]}
 if margins:result.update(support_margin_mm=min(margins),minimum_force_fraction=float(np.min(weights)),external_support_peak_carrier_crank_Nm=abs(np.array(torques)).max((0,1)).tolist())
 return result

reports=[]
for speed in (range(1,101) if '--all' in args else [1,50,100]):
 c=dict(t='intent',seq=1,name='walk',gait='walk',dir='fwd',steps=0,speed=speed)
 wire=json.dumps(c)+'\n'+ '15000 '+json.dumps(dict(c,seq=2,update=1,speed=0))+'\n'
 r=subprocess.run([str(binary),'22000','100'],input=wire,capture_output=True,text=True);rows=[json.loads(x) for x in r.stdout.splitlines()]
 if r.returncode:report={'speed':speed,'error':r.stderr,'returncode':r.returncode}
 else:report={'speed':speed,**measure(rows)}
 reports.append(report)
 if speed in [1,50,100]:print(json.dumps(report),flush=True)
(P/'installed-native-audit.json').write_text(json.dumps({'scope':'Native firmware targets; independent bare Part027 forward geometry; external support forces from assumed centered 566 g COM at original z65 mm. Uniform four-contact least squares load split. Does not include link/gear inertia or verify physical tracking.','reports':reports},indent=2))
