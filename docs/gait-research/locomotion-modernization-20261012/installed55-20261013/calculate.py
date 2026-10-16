import json,sys
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
base=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(base/'body-support-20261013'))
import research as m
verts=np.array(json.loads((base/'installed55-20261013/bare55.json').read_text())['vertices']);h55=verts[ConvexHull(verts).vertices][:,[0,2]];h45=m.hull.copy();m.floor=47.27323

def calc(foot,A,b,L,H,stroke,bias=0):
 m.foot=foot;m.ref=foot*m.u;m.A=A;m.b=b;m.L=L;m.hull=h55 if foot==55 else h45
 x=m.O[0]+bias+np.linspace(-stroke/2,stroke/2,401);v=m.ik(x,np.full(len(x),m.floor-H));q=v['q'];pulses=np.c_[856+(q[:,0]-1.17)*100/9,723+(q[:,1]+40.41)*100/9];angle=np.degrees(np.arcsin(abs(np.sin(v['beta']))))
 row=dict(leg=foot,carrier=A,pickup=b,rod=L,crank=20,clearance=H,stroke=stroke,bias=bias,closes=bool(v['ok'].all()),pulse_fits=bool(((pulses>=400)&(pulses<=2900)).all()),lower_leg_angle_deg=[float(angle.min()),float(angle.max())],joint_excursion_deg=np.ptp(q,axis=0).tolist(),joint_ranges_deg=np.c_[q.min(0),q.max(0)].tolist(),peak_Nm_per_10N_vertical=(np.max(abs(v['jac'][:,1,:]),axis=0)*.01).tolist(),minimum_transmission_deg=[float(v['input'].min()),float(v['output'].min())],pulse_range_us=[float(pulses.min()),float(pulses.max())])
 return row,v
