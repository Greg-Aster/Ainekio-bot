import whole_body as w,research as m
import numpy as np,json
rows=[]
for cx,cz in [(-35,0),(-30,10),(-25,15),(-20,15),(-12.5,11.5),(20,15),(30,10)]:
 m.C=m.O+[cx,cz]
 for carrier in [40,45]:
  for pickup in [28,32,36]:
   for rod in [26,30,34,38,42]:
    for H in [55,60,65]:
     try:
      r=w.evaluate((carrier,pickup,rod,H));r['C_relative_O']=[cx,cz]
      if not r['stance_closed']:continue
      a,b=r['peak_joint_torque_Nm_per_kg'][1:];r['score']=max(a,b)+.3*abs(a-b);rows.append(r)
     except (ValueError,np.linalg.LinAlgError):pass
 print('pivot',cx,cz,'closing',len(rows),flush=True)
(m.p/'tall-layout.json').write_text(json.dumps(rows,indent=2))
for r in sorted([r for r in rows if r['height']>=60],key=lambda r:r['score'])[:8]:print({k:v for k,v in r.items() if k!='pulse_ranges'})
