"""Cross-check rounded compact candidates using bare foot mesh and body support."""
import json,sys,numpy as np
from pathlib import Path
from scipy.spatial import ConvexHull
base=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(base/'body-support-20261013'))
import research as m, whole_body as w
p=Path(__file__).resolve().parent
original=np.array(json.loads((base/'installed55-20261013/bare55.json').read_text())['vertices']);u=np.array([m.u[0],0,m.u[1]])
original_feet=w.feet.copy();original_shift=w.shift.copy();original_acc=w.acc.copy();centres=np.array([66.69,66.69,-66.72,-66.72])
# F,A,L,b,crank,H,stroke,relative Cx,Cz
cases=[(55,26,23,27,21,51,60,4,0),(50,24,21,25,20,45,55,4,0),(45,22,20,23,20,40,50,4,0)]
rows=[]
for F,A,L,b,crank,H,stroke,cx,cz in cases:
 projection=original@u;vertices=original+u*np.clip((projection-7)/41,0,1)[:,None]*(F-55)-u*np.clip((-projection-7)/14,0,1)[:,None]*(b-28)
 m.foot=F;m.ref=F*m.u;m.r=crank;m.C=m.O+np.array([cx,cz]);w.ref3=np.array([m.ref[0],-56.65,m.ref[1]]);w.hull3=vertices[ConvexHull(vertices).vertices]
 w.feet=original_feet.copy();w.feet[:,:,0]=centres+(original_feet[:,:,0]-centres)*stroke/82
 w.shift=original_shift.copy();w.shift[:,0]*=stroke/82
 w.acc=original_acc.copy();w.acc[:,0]*=stroke/82
 r=w.evaluate((A,b,L,H+49.2500076-47.27323),True)
 loads=np.array(r['joint_torques'])*.566
 q=np.stack([r['legs'][leg]['q'] for leg in w.legs],1);q=np.rad2deg(np.unwrap(np.deg2rad(q),axis=0));vel=np.gradient(q,2/w.N,axis=0)
 angles=[]
 for k,leg in enumerate(w.legs):
  beta=np.array(r['legs'][leg]['beta']);angles.extend(np.rad2deg(np.arcsin(abs(np.sin(beta))))[w.stance[:,k]].tolist())
 row=dict(geometry=[F,A,L,b,crank],stroke=stroke,clearance=H,pivot_offset=[cx,cz],stance_closed=r['stance_closed'],all_cycle_closed=all(all(v['ok']) for v in r['legs'].values()),current_index_fits=r['valid_kinematics_and_pulses'],min_loaded_sagittal_angle=min(angles),peak_joint_torque_Nm=np.max(abs(loads),axis=(0,1)).tolist(),peak_speed_deg_s=np.max(abs(vel),axis=(0,1)).tolist(),excursions_deg=np.max(np.ptp(q,axis=0),axis=0).tolist(),min_support_margin=r['min_support_margin_mm'],force_equilibrium_error=r['max_force_equilibrium_error'],min_weight_fraction=r['min_weight_fraction'],model='Reused body-shift path; x scaled with stroke. Assumed centred 566g body. No limb inertia, collision or physical qualification. Original Cartesian return, not retuned.')
 rows.append(row);print(json.dumps(row),flush=True)
(p/'compact-scaled-body-check.json').write_text(json.dumps(rows,indent=2))
