import whole_body as w
import research as m
import json,numpy as np
rows=[]
for A in [35,40,45]:
 for b in [24,28,32,36]:
  for L in [26,30,34,38,42]:
   for H in [40,45,50,55]:
    try:
     r=w.evaluate((A,b,L,H))
     if r['valid_stance']:
      rows.append(r)
    except (ValueError,np.linalg.LinAlgError):pass
 print('done',A,len(rows),flush=True)
(m.p/'whole-body-scan.json').write_text(json.dumps(rows,indent=2))
for r in sorted(rows,key=lambda r:max(r['peak_joint_torque_Nm_per_kg'][1:]))[:15]:print({k:v for k,v in r.items() if k!='pulse_ranges'})
