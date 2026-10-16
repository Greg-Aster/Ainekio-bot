"""Exploratory collinear-reference screen; final native audit uses the retained virtual reference."""
import sys,json,numpy as np
from pathlib import Path
P=Path('/home/greggles/Ainekio/docs/gait-research/locomotion-modernization-20261012/geometry-ratios-20261013');sys.path.insert(0,str(P));sys.argv=['scan','compact60']
import optimize_actual_body as a
from scipy.spatial import ConvexHull
N=120;a.N=N;a.period=.9;a.step=.9/N
phase=np.arange(N)/N;offset=np.array([0,.5,.75,.25]);ph=(phase[:,None]-offset)%1
a.stance=ph<.8
# same duty and swing polynomial as firmware (world anchors, zero endpoint speed)
r=.08
u=np.clip((ph-.8)/.2,0,1)
t=np.clip(u/r,0,1);tt=np.clip((1-u)/r,0,1)
swing=np.where(u<r,r*(t**3-.5*t**4)/(1-r),np.where(u>1-r,1-r*(tt**3-.5*tt**4)/(1-r),(u-r*.5)/(1-r)))
homes=np.array([[1670,2444,2577],[1760,856,723],[1600,2444,2577],[1670,856,723]])
signs=np.where([[True,True,True],[False,False,False],[False,True,True],[True,False,False]],-1,1)
a.m.A=35;a.m.foot=55;a.m.ref=55*a.m.u;a.m.r=20;a.m.b=28;a.m.L=38;a.m.C=a.m.O+[-12.5,11.5]
a.w.ref3=np.r_[a.m.ref[0],-56.65,a.m.ref[1]];a.w.hull3=a.original[ConvexHull(a.original).vertices]
centres=np.array([[74.20747,67.11117],[74.20747,-67.11115],[-59.20195,67.11115],[-59.20196,-67.11115]])
rows=[]
for stroke in [24,30,36,40,44]:
 for H in [52,56,60,64]:
  for bias in [0,4,8,12]:
   x=stroke*(.5-ph/.8)+np.where(ph>=.8,stroke/.8*swing,0)-bias
   feet=np.tile(centres,(N,1,1));feet[:,:,0]+=x
   lift=8*64*u**3*(1-u)**3
   shift=np.c_[4*np.sin(4*np.pi*phase),7*np.sin(2*np.pi*phase)]
   answers=[a.w.ik3(leg,np.c_[feet[:,k]-shift,47.27323-H+lift[:,k]],H) for k,leg in enumerate(a.w.legs)]
   ok=all(ans['ok'].all() for ans in answers)
   qs=np.stack([ans['q'] for ans in answers],1);pulse=homes+(qs-[0,1.17,-40.41])*100/9*signs
   if not ok or pulse.min()<400 or pulse.max()>2900:continue
   minangle=min(np.rad2deg(np.arcsin(abs(np.sin(ans['beta'][a.stance[:,k]])))).min() for k,ans in enumerate(answers))
   # Simple force solution at actual contacts, no min-load restriction.
   acc=(np.roll(shift,-1,axis=0)-2*shift+np.roll(shift,1,axis=0))/a.step**2
   contacts=np.stack([ans['contact'][:,:2]+shift for ans in answers],1);ww=[];margins=[]
   for i in range(N):
    ids=np.flatnonzero(a.stance[i]);xy=contacts[i,ids];cop=shift[i]-(H+17.7268)/9810*acc[i];B=np.vstack([xy.T,np.ones(len(ids))]);weights=np.linalg.lstsq(B,np.r_[cop,1],rcond=None)[0];full=np.zeros(4);full[ids]=weights;ww.append(full)
    hull=ConvexHull(xy).equations;margins.append(-(hull[:,:2]@cop+hull[:,2]).max())
   a.feet=feet;a.lifts=lift;a.shift=shift;a.acc=acc;a.weights=np.array(ww)
   perf=a.perf(np.array([35,55,20,28,38,H,-12.5,11.5]),True)
   row=dict(stroke=stroke,H=H,bias=bias,minangle=float(minangle),minweight=float(np.min(ww)),margin=float(min(margins)),pulse=[float(pulse.min()),float(pulse.max())],**perf);rows.append(row)
print('valid',len(rows))
for row in sorted(rows,key=lambda r:max(r['utilization'])+max(0,-r['margin']))[:12]:print(json.dumps(row))
(P/'installed-gait-screen.json').write_text(json.dumps(rows,indent=2))
