import json,numpy as np
import whole_body as w,research as m
from return_path import fk3
report=[]
for params in [(45,32,34,55),(40,28,30,45)]:
 f=m.p/('refined-'+'-'.join(map(str,params))+'.json');d=json.loads(f.read_text());m.A,m.b,m.L,H=params;q=np.array(d['q']);bodyz=d['body_z'];stance=np.array(d['stance']);homes=np.array([[1600,2444,2577],[1670,856,723],[1670,2444,2577],[1760,856,723]]);sign=np.where([[False,True,True],[True,False,False],[True,True,True],[False,False,False]],-1,1);pulse=homes+(q-[0,1.17,-40.41])*(100/9)*sign
 legs={};closure=True;bottom=1e9;errors=[]
 # Independent forward reconstruction and finite-difference Jacobian check.
 for k,leg in enumerate(w.legs):
  v=fk3(leg,q[:,k]);closure &=v['ok'].all();bottom=min(bottom,float((v['bottom']+bodyz).min()));legs[leg]={key:val.tolist() for key,val in v.items()}
  old=w.evaluate(params,True)['legs'][leg]
  oldq=np.array(old['q']);J=np.array(old['jac'])
  for i in [3,17,38,59,77]:
   for col in range(3):
    qp=oldq[i:i+1].copy();qm=qp.copy();qp[0,col]+=.00001*180/np.pi;qm[0,col]-=.00001*180/np.pi
    fd=(fk3(leg,qp)['contact'][0]-fk3(leg,qm)['contact'][0])/.00002
    errors.append(float(abs(fd-J[i,:,col]).max()))
 row={'geometry':params,'closed':bool(closure),'minimum_sole_z_mm':bottom,'pulse_range_us':[float(pulse.min()),float(pulse.max())],'pulse_range_by_leg_joint_us':np.stack([pulse.min(0),pulse.max(0)],-1).tolist(),'peak_joint_speed_deg_s':np.max(abs(np.gradient(q,2/w.N,axis=0)),axis=(0,1)).tolist(),'jacobian_max_error_mm_rad':max(errors),'full_cycle_ranges_deg':np.stack([q.min(0),q.max(0)],-1).tolist()};report.append(row);print(row,flush=True)
 d['forward']=legs;d['verification']=row;f.write_text(json.dumps(d,indent=2))
(m.p/'verification.json').write_text(json.dumps(report,indent=2))
