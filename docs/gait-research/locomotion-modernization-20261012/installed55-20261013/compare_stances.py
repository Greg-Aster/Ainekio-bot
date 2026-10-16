from calculate import *
rows=[]
for H in [43,53,58,63]:
 for stroke in [40,60,78,82]:
  good=[]
  for bias in np.arange(-25,40.01,1):
   r,v=calc(55,35,28,38,H,stroke,float(bias))
   if r['closes'] and r['pulse_fits']:good.append(r)
  if good:
   r=min(good,key=lambda x:abs(x['bias']));rows.append(r);print('H/S',H,stroke,'center',r['bias'],'angle',np.round(r['lower_leg_angle_deg'],1),'exc',np.round(r['joint_excursion_deg'],1),'torque',np.round(r['peak_Nm_per_10N_vertical'],3),flush=True)
  else: print('H/S',H,stroke,'NONE',flush=True)
(base/'installed55-20261013/calibrated-stance-options.json').write_text(json.dumps(rows,indent=2))
