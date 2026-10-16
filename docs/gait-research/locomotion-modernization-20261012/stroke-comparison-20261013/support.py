from pathlib import Path
import json,numpy as np
from scipy.spatial import ConvexHull
from scipy.optimize import linprog
p=Path(__file__).resolve().parent;j=json.loads((p/'live45.json').read_text());d=json.loads((p/'cycles.json').read_text());g=json.load(open('/home/greggles/Ainekio/Slave/software/models/v2-12servo/geometry.json'));print('provisional_com',g['provisional_COM_body_mm'],'mass',g['mass_kg'])
offs={'RL':0,'RR':120,'FL':180,'FR':60};out=[]
for case in d['cases']:
 inequalities=[];margins=[];weights=[];refs={k:[] for k in offs}
 for i in range(240):
  contacts=[]
  for leg,off in offs.items():
   ii=(i+off)%240
   if ii>=180:continue
   r=case['rows'][ii];v=np.array(j['legs'][leg]['vertices']);rot=r['beta']-j['params']['beta_neutral'];c,s=np.cos(rot),np.sin(rot);R=np.array([[c,0,-s],[0,1,0],[s,0,c]]);v=v@R.T+np.array([r['D'][0],0,r['D'][1]]);M=np.array(j['legs'][leg]['mechanism_matrix']);v=v@M[:3,:3].T+M[:3,3];idx=v[:,2].argmin();point=v[idx,:2].copy();point[1]=float((v[:,1].min()+v[:,1].max())/2);contacts.append(point)
   refs[leg].append(float(r['x']+M[0,3]-np.array(j['legs'][leg]['shoulder_matrix'])[0,3]))
  xy=np.array(contacts);h=ConvexHull(xy).equations;inequalities.extend(h.tolist());com=np.array(g['provisional_COM_body_mm'][:2]);margins.append(float(-(h[:,:2]@com+h[:,2]).max()));weights.append(np.linalg.solve(np.vstack([xy.T,np.ones(3)]),np.r_[com,1]).tolist())
 h=np.array(inequalities);res=linprog([0,0,-1],A_ub=np.c_[h[:,:2],np.ones(len(h))],b_ub=-h[:,2],bounds=[(None,None)]*3,method='highs')
 row={'stroke_mm':case['stroke_mm'],'nominal_foot_reference_range_relative_hip_mm':{k:[min(v),max(v)] for k,v in refs.items()},'provisional_com_xy_mm':g['provisional_COM_body_mm'][:2],'samples_outside_support':sum(m<0 for m in margins),'samples':len(margins),'minimum_margin_mm':min(margins),'best_fixed_com_and_margin_mm':res.x.tolist() if res.success else None,'scope':'Static vertical-load support at sampled three-foot phases. Assumed COM, no measured mass/contact/dynamics; excludes finite sole patch width.'};out.append(row);print(json.dumps(row))
(p/'support-research.json').write_text(json.dumps(out,indent=2))
