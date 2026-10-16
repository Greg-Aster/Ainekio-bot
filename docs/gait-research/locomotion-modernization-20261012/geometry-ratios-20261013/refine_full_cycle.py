import sys,json,numpy as np
from pathlib import Path
from scipy.spatial import ConvexHull
base=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(base/'body-support-20261013'))
import research as m,whole_body as w
bare=json.loads((base/'installed55-20261013/bare55.json').read_text())
original=np.array(bare['vertices']);u=np.array([m.u[0],0,m.u[1]])
from return_path_extended import refine,fk3
F,A,crank,b,L,H=72,26,28,43,26,64
proj=original@u;verts=original+u*np.clip((proj-7)/41,0,1)[:,None]*(F-55)-u*np.clip((-proj-7)/14,0,1)[:,None]*(b-28)
m.foot=F;m.ref=F*m.u;m.r=crank;w.ref3=np.array([m.ref[0],-56.65,m.ref[1]]);w.hull3=verts[ConvexHull(verts).vertices]
out=refine((A,b,L,H+49.2500076-47.27323));q=np.array(out['q']);forward={};ok=True;bottom=1e9
for k,leg in enumerate(w.legs):
 f=fk3(leg,q[:,k]);ok &=f['ok'].all();bottom=min(bottom,float((f['bottom']+out['body_z']).min()));forward[leg]={k:v.tolist() for k,v in f.items()}
loads=np.array(out['joint_torques'])*.566
out['forward']=forward
out['ratio_verification']=dict(geometry=[F,A,L,b,crank],mass_kg=.566,supply_volts=5,all_samples_close=bool(ok),minimum_sole_z_mm=bottom,peak_joint_torque_Nm=np.max(abs(loads),axis=(0,1)).tolist(),peak_joint_speed_deg_s=np.max(abs(np.gradient(q,2/w.N,axis=0)),axis=(0,1)).tolist(),joint_excursion_deg=np.max(np.ptp(q,axis=0),axis=0).tolist(),assumed_COM='centred point body, height body nominal H+15.75 mm',scope='No limb inertia, friction or housing collision qualification; physical crank re-indexing required; fixed 566 g comparison mass')
(base/'geometry-ratios-20261013/refined-72mm-body-cycle.json').write_text(json.dumps(out,indent=2));print(json.dumps(out['ratio_verification']),flush=True)
