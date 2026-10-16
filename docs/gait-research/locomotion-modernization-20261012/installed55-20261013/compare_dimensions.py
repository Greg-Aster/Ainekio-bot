from calculate import *
rows=[]
for dims in [(55,35,28,38),(55,35,28,36),(55,35,28,34),(55,35,32,38),(45,40,28,30),(45,45,32,34)]:
 good=[]
 for bias in np.arange(-20,35.1,1):
  r,v=calc(*dims,58,40,float(bias))
  if r['closes'] and r['pulse_fits']:good.append(r)
 if good:
  r=min(good,key=lambda x:abs(x['bias']));rows.append(r);print(dims,'bias',r['bias'],'angle',np.round(r['lower_leg_angle_deg'],1),'torque',np.round(r['peak_Nm_per_10N_vertical'],3),'range',np.round(r['joint_excursion_deg'],1),flush=True)
 else: print(dims,'no candidate')
(base/'installed55-20261013/dimension-comparison.json').write_text(json.dumps(rows,indent=2))
