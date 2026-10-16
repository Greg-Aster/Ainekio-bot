"""Check complete-body reach before ranking compact linkage candidates."""
exec(open(str(__import__('pathlib').Path(__file__).with_name('compact_verify.py'))).read().split('cases=')[0])
source=json.loads((p/'compact-45-55-comparison.json').read_text())
seeds={}
for group in source:
 if group['speed_bin']!=600:continue
 for row in group['best']:
  dims=tuple(round(v) for v in row['dimensions']);seeds[(group['stroke'],dims)]=group['relocate']
rows=[];trials=0
for (stroke,dims),relocate in seeds.items():
 A,F,r,b,L,H,cx,cz=dims
 if not relocate:cx,cz=-12.5,11.5
 projection=original@u;vertices=original+u*np.clip((projection-7)/41,0,1)[:,None]*(F-55)-u*np.clip((-projection-7)/14,0,1)[:,None]*(b-28)
 m.foot=F;m.ref=F*m.u;m.r=r;m.A=A;m.b=b;m.C=m.O+np.array([cx,cz]);w.ref3=np.array([m.ref[0],-56.65,m.ref[1]]);w.hull3=vertices[ConvexHull(vertices).vertices]
 w.feet=original_feet.copy();w.feet[:,:,0]=centres+(original_feet[:,:,0]-centres)*stroke/82
 w.shift=original_shift.copy();w.shift[:,0]*=stroke/82
 w.acc=original_acc.copy();w.acc[:,0]*=stroke/82
 for dh in [-4,-2,0,2]:
  HH=H+dh;nominal=HH+49.2500076-47.27323
  for dl in [-4,-2,0,2,4]:
   LL=L+dl;m.L=LL;answers=[];trials+=1
   for k,leg in enumerate(w.legs):
    target=np.c_[w.feet[:,k,:]-w.shift,m.floor-nominal+w.lift[:,k]];v=w.ik3(leg,target,nominal)
    if not v['ok'].all():break
    answers.append(v)
   if len(answers)!=4:continue
   angle=min(float(np.rad2deg(np.arcsin(abs(np.sin(v['beta']))))[w.stance[:,k]].min()) for k,v in enumerate(answers))
   if angle<45:continue
   q=np.stack([v['q'] for v in answers],1);q=np.rad2deg(np.unwrap(np.deg2rad(q),axis=0));ranges=np.max(np.ptp(q,axis=0),axis=0);speed=np.max(abs(np.gradient(q,2/w.N,axis=0)),axis=(0,1))
   if max(ranges)>225:continue
   vertical=np.max([abs(v['jac'][w.stance[:,k],2,:]).max(0) for k,v in enumerate(answers)],axis=0)*.01
   score=float(max(vertical[1:]))
   rows.append(dict(geometry=[F,A,LL,b,r],stroke=stroke,clearance=HH,pivot_offset=[cx,cz],relocate=relocate,min_loaded_angle=angle,peak_vertical_Nm_per_10N=vertical.tolist(),speed_deg_s=speed.tolist(),excursions=ranges.tolist(),score=score))
 print('checked',trials,'survivors',len(rows),flush=True)
(p/'compact-body-candidates.json').write_text(json.dumps(rows,indent=2))
for stroke in [60,70,82]:
 for F in [45,50,55]:
  for relocate in [False,True]:
   a=[r for r in rows if r['stroke']==stroke and r['geometry'][0]==F and r['relocate']==relocate]
   if a:print('RESULT',json.dumps(min(a,key=lambda r:r['score'])),flush=True)
