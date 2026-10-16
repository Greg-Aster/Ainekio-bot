from pathlib import Path
import sys,json,numpy as np
from scipy.spatial import ConvexHull
base=Path('/home/greggles/Ainekio/docs/gait-research/locomotion-modernization-20261012');sys.path.insert(0,str(base/'body-support-20261013'));import research as m
sys.path.insert(0,str(base/'geometry-ratios-20261013'));import ratio_model as rm
verts=np.array(json.loads((base/'installed55-20261013/bare55.json').read_text())['vertices'])[:,[0,2]]
rows=[]
for F,A,r,b,L,H in [(81,22,36,51,25,74),(72,26,28,43,26,64)]:
 projection=verts@m.u
 v=verts+m.u*np.maximum(0,np.minimum(1,(projection-7)/41))[:,None]*(F-55)-m.u*np.maximum(0,np.minimum(1,(-projection-7)/14))[:,None]*(b-28)
 m.hull=v[ConvexHull(v).vertices];m.foot=F;m.ref=F*m.u;m.A=A;m.r=r;m.b=b;m.L=L;m.floor=47.27323
 ans=m.ik(m.O[0]+rm.x,np.full(len(rm.x),m.floor-H)+rm.lift);q=np.unwrap(np.deg2rad(ans['q']),axis=0)*180/np.pi;pu=np.c_[856+(q[:,0]-1.17)*100/9,723+(q[:,1]+40.41)*100/9]
 ang=np.degrees(np.arcsin(abs(np.sin(ans['beta'][rm.stance]))));vel=np.gradient(q,2/len(q),axis=0);row=dict(dimensions={'leg':F,'carrier':A,'crank':r,'pickup':b,'rod':L},model_clearance_mm=H,all_samples_close=bool(ans['ok'].all()),minimum_loaded_leg_angle=float(ang.min()),peak_vertical_torque_Nm_per_10N=np.max(abs(ans['jac'][rm.stance,1,:]),axis=0).__mul__(.01).tolist(),peak_joint_speed_deg_s=np.max(abs(vel),axis=0).tolist(),joint_excursion_deg=np.ptp(q,axis=0).tolist(),current_pulse_range=[float(pu.min()),float(pu.max())],current_index_fits=bool(((pu>=400)&(pu<=2900)).all()))
 errors=[]
 for i in [0,64,127,150]:
  a,t=np.deg2rad(q[i])+[m.a0,m.t0];rr=ans['beta'][i]-m.b0;rot=np.array([[np.cos(rr),-np.sin(rr)],[np.sin(rr),np.cos(rr)]]);local=m.hull[(m.hull@rot.T)[:,1].argmin()]
  def fk(aa,tt):
   dd=m.O+m.A*np.array([np.cos(aa),np.sin(aa)]);pp=m.C+m.r*np.array([np.cos(tt),np.sin(tt)]);ee,ok=m.circle(pp-dd,m.b,m.L,1);assert bool(ok);beta=np.arctan2(ee[1],ee[0]);rr=beta-m.b0;return dd+np.array([[np.cos(rr),-np.sin(rr)],[np.sin(rr),np.cos(rr)]])@local
  eps=1e-6;J=np.stack([(fk(a+eps,t)-fk(a-eps,t))/(2*eps),(fk(a,t+eps)-fk(a,t-eps))/(2*eps)],-1);errors.append(float(abs(J-ans['jac'][i]).max()))
 row['jacobian_difference_error_mm_per_rad']=max(errors)
 rows.append(row);print(json.dumps(row),flush=True)
(base/'geometry-ratios-20261013/reshaped-mesh-check.json').write_text(json.dumps(rows,indent=2))
