import sys,json,numpy as np
from pathlib import Path
p=Path('/home/greggles/Ainekio/docs/gait-research/locomotion-modernization-20261012');sys.path.insert(0,str(p/'installed55-20261013'));from calculate import calc,m
rows=[]
for A,b,L in [(35,28,38),(40,24,38)]:
 for crank in [20,24,28,32]:
  m.r=crank
  r,v=calc(55,A,b,L,58,40,7);r['crank']=crank;rows.append(r);print(A,b,crank,'closed',r['closes'],'pulses',r['pulse_fits'],'angle',np.round(r['lower_leg_angle_deg'],1),'torque',np.round(r['peak_Nm_per_10N_vertical'],3),'travel',np.round(r['joint_excursion_deg'],1))
(p/'geometry-ratios-20261013/crank-comparison.json').write_text(json.dumps(rows,indent=2))
