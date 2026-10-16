import sys,json,numpy as np
from pathlib import Path
from scipy.spatial import ConvexHull
base=Path('/home/greggles/Ainekio/docs/gait-research/locomotion-modernization-20261012');sys.path.insert(0,str(base/'body-support-20261013'));import research as m,whole_body as w
bare=json.loads((base/'installed55-20261013/bare55.json').read_text());original=np.array(bare['vertices']);u=np.array([m.u[0],0,m.u[1]])
rows=[]
for F,A,crank,b,L,H in [(55,35,20,28,38,43),(81,22,36,51,25,74),(72,26,28,43,26,64)]:
 proj=original@u;verts=original+u*np.clip((proj-7)/41,0,1)[:,None]*(F-55)-u*np.clip((-proj-7)/14,0,1)[:,None]*(b-28)
 m.foot=F;m.ref=F*m.u;m.r=crank;w.ref3=np.array([m.ref[0],-56.65,m.ref[1]]);w.hull3=verts[ConvexHull(verts).vertices]
 report=w.evaluate((A,b,L,H+49.2500076-47.27323),True)
 loads=np.array(report['joint_torques'])*.566
 row=dict(geometry=[F,A,L,b,crank],body_clearance=H,stance_closed=report['stance_closed'],old_index_stance_fits=report['valid_stance'],full_geometric_closure=all(all(v['ok']) for v in report['legs'].values()),minimum_effective_support_margin=report['min_support_margin_mm'],minimum_weight_fraction=report['min_weight_fraction'],equilibrium_error=report['max_force_equilibrium_error'],peak_joint_torque_Nm=np.max(abs(loads),axis=(0,1)).tolist(),peak_joint_speed_deg_s=report['peak_speed_deg_s'],mass_kg=.566,scope='Existing body-shift trajectory reused, assumed centred COM, point-body forces, no leg inertia; fixed reference mass for redesigned legs')
 rows.append(row);print(json.dumps(row),flush=True)
(base/'geometry-ratios-20261013/whole-body-cross-check.json').write_text(json.dumps(rows,indent=2))
