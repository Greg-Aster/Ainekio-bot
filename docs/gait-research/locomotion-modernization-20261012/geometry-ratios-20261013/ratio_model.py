from pathlib import Path
import numpy as np,json
from scipy.stats import qmc
p=Path(__file__).resolve().parent
# Absolute joint offsets are not constrained: new mounts/horns may be re-indexed.
# Available angular excursion is the existing 225-degree calibration span.
# All trials use the same 82 mm planted stroke and 2 s / 80% stance / 10 mm return.
phase=np.arange(160)/160;stance=phase<.8;t=phase*2
u=np.clip((phase-.8)/.2,0,1);s=10*u**3-15*u**4+6*u**5;e=u-10*u**3+15*u**4-6*u**5
x=np.where(stance,41-82*phase/.8,-41+82*s-82*.2/.8*e)
lift=np.where(stance,0,160*u*u*(1-u)*(1-u))
def cross(a,b):return a[...,0]*b[...,1]-a[...,1]*b[...,0]
def perp(a):return np.stack([-a[...,1],a[...,0]],-1)
def circle(v,a,b,sign):
 d2=np.sum(v*v,-1);along=(a*a-b*b+d2)/(2*d2);h2=a*a/d2-along*along
 return along[...,None]*v+sign*np.sqrt(np.maximum(h2,0))[...,None]*perp(v),h2>=0

def evaluate(d):
 A,F,r,b,L,H,cx,cz=d.T
 A=A[:,None];F=F[:,None];r=r[:,None];b=b[:,None];L=L[:,None];H=H[:,None];C=np.stack([cx,cz],-1)[:,None,:]
 # 22.44 mm carrier-to-lowest-body datum; rounded toe radius 7.5 mm.
 target=np.stack([np.broadcast_to(x,(len(d),len(x))),-(H+22.43859-7.5)+lift],-1)
 D,ok=circle(target,A,F,-1);lower=(target-D)/F[...,None];E=D-b[...,None]*lower;ip,ok2=circle(E-C,r,L,-1);P=C+ip;out=E-D;rod=E-P
 aa=np.unwrap(np.arctan2(D[...,1],D[...,0]),axis=1);tt=np.unwrap(np.arctan2(ip[...,1],ip[...,0]),axis=1);q=np.stack([aa,tt],-1)
 branch=cross(P-D,out)>0;valid=(ok&ok2&branch).all(1);ranges=np.rad2deg(np.ptp(q,axis=1));valid &= (ranges<=225).all(1)
 den=cross(out,rod);da=perp(D);dt=perp(ip)
 with np.errstate(divide='ignore',invalid='ignore'):
  ba=-np.sum(rod*da,-1)/den;bt=np.sum(rod*dt,-1)/den;v=target-D;v[...,1]-=7.5
  J=np.stack([da+ba[...,None]*perp(v),bt[...,None]*perp(v)],-1)
 angles=np.degrees(np.arcsin(np.clip(abs(lower[:,:,1]),0,1)))[:,stance].min(1)
 vertical=np.max(abs(J[:,stance,1,:]),axis=1)*.01
 combined=np.max(abs(J[:,stance,1,:])+ .3*abs(J[:,stance,0,:]),axis=1)*.01
 speed=np.max(abs(np.rad2deg(np.gradient(q,2/160,axis=1))),axis=1)
 return valid,angles,vertical,combined,speed,ranges
