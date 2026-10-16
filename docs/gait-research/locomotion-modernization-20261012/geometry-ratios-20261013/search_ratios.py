from ratio_model import *
bounds=np.array([[25,80],[35,80],[20,40],[20,50],[25,85],[40,100],[-12.5,-12.5],[11.5,11.5]])
rows=[]
for free in [False,True]:
 if free:bounds[-2:]=[[-30,10],[-10,30]]
 values=qmc.Sobol(8,scramble=True,seed=32+free).random_base2(15);values=bounds[:,0]+values*(bounds[:,1]-bounds[:,0])
 count=0
 for start in range(0,len(values),512):
  d=values[start:start+512];valid,ang,vert,comb,speed,ranges=evaluate(d)
  ids=np.flatnonzero(valid&(ang>=45)&np.isfinite(comb).all(1)&np.isfinite(speed).all(1))
  for i in ids:rows.append(dict(dimensions=d[i].tolist(),minimum_lower_leg_angle=float(ang[i]),peak_vertical_Nm_per_10N=vert[i].tolist(),peak_traction_envelope_Nm=comb[i].tolist(),peak_speed_deg_s=speed[i].tolist(),joint_excursion_deg=ranges[i].tolist(),relocated_pivot=free))
  count+=len(ids)
 print('free pivot',free,'candidates',count,flush=True)
(p/'ratio-candidates.json').write_text(json.dumps(rows))
for free in [False,True]:
 good=[r for r in rows if r['relocated_pivot']==free]
 for limit in [400,600,800,1200]:
  under=[r for r in good if max(r['peak_speed_deg_s'])<=limit]
  if under:
   r=min(under,key=lambda r:max(r['peak_traction_envelope_Nm']));print('free/nominal-speed-bin',free,limit,json.dumps(r),flush=True)
