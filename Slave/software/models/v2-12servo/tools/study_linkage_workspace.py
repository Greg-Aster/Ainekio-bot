"""Map the installed linkage workspace without changing firmware or CAD.

A live geometry snapshot is optional. All results describe geometry; they do not
qualify collision clearance, loaded servo tracking, friction or ground stability.
"""
import argparse,json,sys,subprocess,hashlib
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.spatial import ConvexHull
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
parser.add_argument('--binary',type=Path,required=True)
parser.add_argument('--live-geometry',type=Path)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();root=args.root.resolve();args.out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(root/'tools'))
from retarget_clips import load_reference
cfg=json.loads((root/'geometry.json').read_text());live=json.loads(args.live_geometry.read_text()) if args.live_geometry else None
p=cfg['parameters'];leg='RL';g=cfg['legs'][leg];sole=json.loads((root/'motions/locomotion/sole-profile.json').read_text());hull=np.array(sole['profiles']['walk'])
verts=np.array(live['legs'][leg]['sole_vertices_local_mm'] if live else g['sole_hull_local_mm']);visible=verts[ConvexHull(verts).vertices]
a0=p['alpha_neutral'];t0=p['new_theta_neutral'];b0=p['beta_neutral'];O=np.array(p['O']);C=np.array(p['C_new']);A=p['primary_length'];r=p['input_length'];b=p['pickup_length'];L=p['rod_length'];ref=np.array(g['foot_reference_local_mm']);S=np.array(g['shoulder_world']);M=np.array(g['mechanism_local']);origin=S[:3,3]+S[:3,:3]@M[:3,3];floor=min(v[2] for v in cfg['current_body_hull_local_mm'])
# Existing physical reference mapping: 400..2900 us spans 225 degrees at 11.111us/degree.
alpha=np.linspace(1.17+(400-856)/ (100/9),1.17+(2900-856)/(100/9),901)
theta=np.linspace(-40.41+(400-723)/(100/9),-40.41+(2900-723)/(100/9),901)

def evaluate(ad,td):
 ad,td=np.broadcast_arrays(ad,td);shape=ad.shape;av=np.deg2rad(ad).ravel()+a0;tv=np.deg2rad(td).ravel()+t0
 D=O+A*np.c_[np.cos(av),np.sin(av)];P=C+r*np.c_[np.cos(tv),np.sin(tv)];w=P-D;d=np.linalg.norm(w,axis=1);valid=(d>abs(L-b))&(d<L+b)
 along=(b*b-L*L+d*d)/(2*d);height=np.sqrt(np.maximum(0,b*b-along*along));E=D+(along[:,None]*w+height[:,None]*np.c_[-w[:,1],w[:,0]])/d[:,None]
 beta=np.arctan2(E[:,1]-D[:,1],E[:,0]-D[:,0]);rot=beta-b0;co=np.cos(rot);si=np.sin(rot)
 rod=E-P;out=E-D;inp=P-C
 cross=lambda a,b:a[:,0]*b[:,1]-a[:,1]*b[:,0]
 branch=cross(E-C,inp)
 # Preserve the installed inverse-crank branch, without arbitrary angular floors.
 valid &= branch<0
 index=np.empty(len(av),int);bottom=np.empty(len(av));support_error=0.
 for i in range(0,len(av),6000):
  normal=np.c_[si[i:i+6000],np.zeros(len(si[i:i+6000])),co[i:i+6000]]
  z=normal@hull.T;idx=z.argmin(axis=1);index[i:i+6000]=idx;bottom[i:i+6000]=z[np.arange(len(z)),idx]-sole['support_allowance_mm']
 contact=hull[index];vx=co*contact[:,0]-si*contact[:,2];vz=si*contact[:,0]+co*contact[:,2]
 xref=origin[0]+D[:,0]+co*ref[0]-si*ref[2]
 xcontact=origin[0]+D[:,0]+vx
 bodyz=-(origin[2]+D[:,1]+bottom)
 da=A*np.c_[-np.sin(av),np.cos(av)];dt=r*np.c_[-np.sin(tv),np.cos(tv)];den=np.sum(rod*np.c_[-out[:,1],out[:,0]],axis=1)
 den=np.where(valid & (np.abs(den)>1e-12),den,np.nan)
 ba=-np.sum(rod*da,axis=1)/den;bt=np.sum(rod*dt,axis=1)/den
 za=da[:,1]+vx*ba;zt=vx*bt
 outangle=np.rad2deg(np.arccos(np.clip(np.abs(np.sum(rod*out,axis=1))/(L*b),0,1)))
 inangle=np.rad2deg(np.arccos(np.clip(np.abs(np.sum(rod*inp,axis=1))/(L*r),0,1)))
 vals=dict(xref=xref,xcontact=xcontact,bodyz=bodyz,clearance=bodyz+floor,carrier_arm=np.abs(za),crank_arm=np.abs(zt),output_angle=outangle,input_angle=inangle,closure=L+b-d)
 return {k:np.where(valid,v,np.nan).reshape(shape) for k,v in vals.items()}
q=evaluate(alpha[:,None],theta[None,:]);print('grid solved',flush=True)
# Audit the source pose against the current visible Blender rig and sole mesh.
m=load_reference(root).Mechanism(cfg);parity={}
for l,v in (live['legs'].items() if live else []):
 joints=np.deg2rad([v['controls'][k] for k in ['h_deg','alpha_deg','theta_deg']]);R,t=m.pose(l,joints,[0,0,0]);W=np.array(v['foot_world']);parity[l]={'foot_transform_translation_error_mm':float(np.linalg.norm(t-W[:3,3])),'foot_transform_rotation_element_error':float(np.max(np.abs(R-W[:3,:3])))}
rot=np.linspace(-np.pi,np.pi,721);n=np.c_[np.sin(rot),np.zeros(len(rot)),np.cos(rot)];support_error=float(np.max(np.abs((n@visible.T).min(axis=1)-((n@hull.T).min(axis=1)-sole['support_allowance_mm']))))
print('visible sole support discrepancy',support_error,flush=True)
# Source gait sample, full steady stride; no real robot commands.
cmd=dict(t='intent',seq=1,name='walk',dir='fwd',gait='walk',steps=0,speed=99)
rn=subprocess.run([str(args.binary),'12000','100'],input=json.dumps(cmd)+'\n',text=True,capture_output=True,check=True)
rows=[json.loads(l) for l in rn.stdout.splitlines()];steady=[v for v in rows if v['ms']>=8000];qs=np.array([v['q'] for v in steady]).reshape(-1,4,3);gd=np.array([v['grounded'] for v in steady]);deg=np.rad2deg(qs)
current={'evidence':'Native commanded trajectory from the supplied binary, not measured servo tracking or installed firmware.', 'speed':99,'carrier_range_degrees': [float(deg[:,:,1].min()),float(deg[:,:,1].max())],'crank_range_degrees':[float(deg[:,:,2].min()),float(deg[:,:,2].max())],'carrier_excursion_degrees':np.ptp(deg[:,:,1],axis=0).tolist(),'crank_excursion_degrees':np.ptp(deg[:,:,2],axis=0).tolist(),'body_translation_z_mm':[min(v['body'][2] for v in steady),max(v['body'][2] for v in steady)]}
# Level constant-height contours in joint space, mapped to foot stroke. Split at
# turning points of x: a usable planted stroke must travel continuously one way.
levels=[20,30,40,45,50,55,60,65,70,75,80]
fig,ax=plt.subplots();cont=ax.contour(theta,alpha,np.ma.masked_invalid(q['clearance']),levels=levels);plt.close(fig)
candidates=[]
for level,segs in zip(cont.levels,cont.allsegs):
 for seg in segs:
  if len(seg)<5:continue
  val=evaluate(seg[:,1],seg[:,0]);x=val['xref'];dx=np.diff(x);sgn=np.sign(dx);cuts=[0]+(np.flatnonzero(sgn[1:]*sgn[:-1]<0)+1).tolist()+[len(seg)-1]
  for start,end in zip(cuts[:-1],cuts[1:]):
   if end-start<4:continue
   ids=np.arange(start,end+1);valid=np.isfinite(x[ids]);ids=ids[valid]
   if len(ids)<5:continue
   stroke=np.ptp(x[ids]);
   if stroke<20:continue
   item={'body_clearance_mm':float(level),'body_z_mm':float(level-floor),'stroke_mm':float(stroke),'foot_reference_x_mm':[float(min(x[ids])),float(max(x[ids]))],'foot_reference_x_from_shoulder_mm':[float(min(x[ids])-S[0,3]),float(max(x[ids])-S[0,3])],'carrier_range_degrees':[float(min(seg[ids,1])),float(max(seg[ids,1]))],'crank_range_degrees':[float(min(seg[ids,0])),float(max(seg[ids,0]))],'carrier_excursion_degrees':float(np.ptp(seg[ids,1])),'crank_excursion_degrees':float(np.ptp(seg[ids,0])),'minimum_output_angle_degrees':float(np.nanmin(val['output_angle'][ids])),'minimum_input_angle_degrees':float(np.nanmin(val['input_angle'][ids])),'vertical_force_carrier_moment_arm_peak_mm':float(np.nanmax(val['carrier_arm'][ids])),'vertical_force_crank_moment_arm_peak_mm':float(np.nanmax(val['crank_arm'][ids])),'samples':len(ids)}
   candidates.append(item)
# Also report 78mm contiguous strokes at each height, minimizing peak vertical
# load torque arm rather than choosing a low body height to fit old choreography.
selected=[]
for level,segs in zip(cont.levels,cont.allsegs):
 best=None
 for seg in segs:
  if len(seg)<10:continue
  val=evaluate(seg[:,1],seg[:,0]);x=val['xref'];dx=np.diff(x);cuts=[0]+(np.flatnonzero(dx[1:]*dx[:-1]<0)+1).tolist()+[len(seg)-1]
  for start,end in zip(cuts[:-1],cuts[1:]):
   ids=np.arange(start,end+1)
   if len(ids)<10:continue
   if x[ids[0]]>x[ids[-1]]:ids=ids[::-1]
   for k in range(len(ids)):
    l=np.searchsorted(x[ids],x[ids[k]]+78)
    if l>=len(ids):break
    ii=ids[k:l+1]
    if np.any(~np.isfinite(val['carrier_arm'][ii])):continue
    score=max(np.max(val['carrier_arm'][ii]),np.max(val['crank_arm'][ii]))
    row={'body_clearance_mm':float(level),'body_z_mm':float(level-floor),'stroke_mm':float(np.ptp(x[ii])),'foot_reference_x_mm':[float(min(x[ii])),float(max(x[ii]))],'carrier_range_degrees':[float(min(seg[ii,1])),float(max(seg[ii,1]))],'crank_range_degrees':[float(min(seg[ii,0])),float(max(seg[ii,0]))],'carrier_excursion_degrees':float(np.ptp(seg[ii,1])),'crank_excursion_degrees':float(np.ptp(seg[ii,0])),'minimum_output_angle_degrees':float(np.min(val['output_angle'][ii])),'minimum_input_angle_degrees':float(np.min(val['input_angle'][ii])),'peak_vertical_force_moment_arm_mm':float(score)}
    if best is None or score<best[0]:best=score,row
 if best:selected.append(best[1])
# Report the contiguous stroke surviving the PRE-EXISTING offline geometry
# criteria, separately from absolute reach. These are not new runtime limits.
margins=json.loads((root/'motions/locomotion/config.json').read_text())['leverage_validation']
reviewed=[]
for level,segs in zip(cont.levels,cont.allsegs):
 best=None
 for seg in segs:
  if len(seg)<5:continue
  val=evaluate(seg[:,1],seg[:,0]);x=val['xref']
  good=(val['output_angle']>=margins['stance_output_min_deg'])&(val['input_angle']>=margins['stance_input_min_deg'])&(val['closure']>=margins['straightening_clearance_min_mm'])
  dx=np.diff(x);turns=set((np.flatnonzero(dx[1:]*dx[:-1]<0)+1).tolist())
  start=None
  for i in range(len(seg)+1):
   if i==len(seg) or not good[i] or i in turns:
    if start is not None and i-start>4:
     ii=np.arange(start,i);span=float(np.ptp(x[ii]))
     if best is None or span>best['stroke_mm']:
      best={'body_clearance_mm':float(level),'body_z_mm':float(level-floor),'stroke_mm':span,'foot_reference_x_mm':[float(min(x[ii])),float(max(x[ii]))],'carrier_excursion_degrees':float(np.ptp(seg[ii,1])),'crank_excursion_degrees':float(np.ptp(seg[ii,0])),'peak_vertical_force_moment_arm_mm':float(max(np.max(val['carrier_arm'][ii]),np.max(val['crank_arm'][ii])))}
    start=None
   if i<len(seg) and good[i] and start is None:start=i
 if best:reviewed.append(best)
report={'scope':'Offline level-body planar planted strokes; no collision, ground stability, force or tracking qualification. Joint windows from existing 400..2900us review range, no firmware limits changed. Shoulder held neutral. Contours sampled at 0.25 degree joint resolution.','geometry_sha256':hashlib.sha256((root/'geometry.json').read_bytes()).hexdigest(),'sampled_binary_sha256':hashlib.sha256(args.binary.read_bytes()).hexdigest(),'sampled_motion_source_sha256':hashlib.sha256((root/'motion.c').read_bytes()).hexdigest(),'live_blender_parity':parity,'existing_geometry_review_criteria':margins,'longest_with_existing_review_criteria':reviewed,'maximum_visible_sole_profile_support_difference_mm':support_error,'current_walk':current,'longest_by_height':[max([c for c in candidates if c['body_clearance_mm']==level],key=lambda c:c['stroke_mm']) for level in levels if any(c['body_clearance_mm']==level for c in candidates)],'load_arm_selected_78mm_strokes':selected}
out=args.out/'workspace-report.json';out.write_text(json.dumps(report,indent=2,allow_nan=False));print(json.dumps(report,indent=2),flush=True)
fig,axs=plt.subplots(1,2,figsize=(13,6),layout='constrained')
image=axs[0].pcolormesh(theta,alpha,q['clearance'],shading='auto',vmin=0,vmax=90,cmap='viridis');fig.colorbar(image,ax=axs[0],label='Model body clearance at ground contact (mm)')
axs[0].plot(deg[:,0,2],deg[:,0,1],color='red',lw=2,label='Current 99% Walk, front left')
axs[0].set(xlabel='Crank offset (degrees)',ylabel='Carrier offset (degrees)',title='Actual compact linkage joint workspace');axs[0].legend(loc='upper right')
for c in report['longest_by_height']:
 axs[1].plot(c['foot_reference_x_mm'],[c['body_clearance_mm']]*2,lw=2,color='0.7')
for c in selected:axs[1].plot(c['foot_reference_x_mm'],[c['body_clearance_mm']]*2,lw=4,color='tab:blue')
stance=cfg['reference_stance_xy_mm'][0][0];axs[1].plot([stance-23,stance+55],[floor-10]*2,'r-',lw=4,label='Current nominal 100% planted stroke')
axs[1].axvline(S[0,3],color='black',linestyle=':',label='Shoulder X')
axs[1].plot([],[],'-',color='0.7',lw=2,label='Longest sampled continuous stroke');axs[1].plot([],[],'-',color='tab:blue',lw=4,label='78 mm segment: lowest peak vertical-load arm')
axs[1].set(xlabel='Front-left foot reference X in body coordinates (mm)',ylabel='Model body clearance (mm)',title='Reach derived from linkage, not an authored foot path');axs[1].legend(fontsize=8)
fig.suptitle('35 / 20 / 28 / 38 / 55 mm linkage — geometry only; physical fit and torque unqualified')
fig.savefig(args.out/'linkage-workspace.png',dpi=160)
