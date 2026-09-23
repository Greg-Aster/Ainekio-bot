"""Run in background Blender: derive the coupled internal-leg envelope from captured meshes.

This offline tool never loads or changes the author's Blender project.
The resulting angular guard is a model constraint, not hardware qualification.
"""
import argparse,hashlib,json,math,sys,time
from pathlib import Path
import numpy as np
from mathutils.bvhtree import BVHTree

ROOT=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
meta=json.loads((ROOT/'mechanics/collision-meshes.json').read_text());data=np.load(ROOT/'mechanics/collision-meshes.npz');p=meta['parameters']
O=np.array(p['O']);C=np.array(p['C_new']);a0=p['alpha_neutral'];t0=p['new_theta_neutral'];b0=p['beta_neutral']
def ry(x):
 c,s=math.cos(x),math.sin(x);return np.array([[c,0,s],[0,1,0],[-s,0,c]])
def tf(r=np.eye(3),t=(0,0,0)):
 m=np.eye(4);m[:3,:3]=r;m[:3,3]=t;return m
def kin(alpha,theta):
 a=a0+math.radians(alpha);t=t0+math.radians(theta)
 D=O+p['primary_length']*np.array([math.cos(a),math.sin(a)]);P=C+p['input_length']*np.array([math.cos(t),math.sin(t)]);w=P-D;d=np.linalg.norm(w)
 if not abs(p['rod_length']-p['pickup_length'])+1e-5<d<p['rod_length']+p['pickup_length']-1e-5:return None
 along=(p['pickup_length']**2-p['rod_length']**2+d*d)/(2*d);height=math.sqrt(p['pickup_length']**2-along**2)
 E=D+(along*w+p['assembly_branch']*height*np.array([-w[1],w[0]]))/d;beta=math.atan2(*(E-D)[::-1]);phi=math.atan2(*(E-P)[::-1])
 return {'input':tf(ry(-t+p['old_theta_neutral']),(C[0],0,C[1])), 'primary':tf(ry(a0-a),(O[0],0,O[1])), 'rod':tf(ry(p['old_rod_reference_angle']-phi),(P[0],0,P[1])), 'foot':tf(ry(b0-beta),(D[0],0,D[1])), 'mechanism frame':np.eye(4),'mount frame':np.eye(4)}
class Mesh:
 def __init__(self,record):
  self.name=record['name'];self.group=record['group'];key=record['key'];self.v=data[key+'v'];self.f=data[key+'f']
 def posed(self,m):
  v=self.v@m[:3,:3].T+m[:3,3]
  return (v.min(0),v.max(0),BVHTree.FromPolygons(v.tolist(),self.f.tolist(),all_triangles=True))
def overlap(a,b):return not(np.any(a[0]>b[1]) or np.any(b[0]>a[1])) and bool(a[2].overlap(b[2]))
meshes={r['name'].split(' | ',2)[2]:Mesh(r) for r in meta['objects']}
def key(part):return next(k for k in meshes if k.startswith(part+' -'))
fixed_names=[k for k,m in meshes.items() if m.group in ['mechanism frame','mount frame']]
fixed={k:meshes[k].posed(np.eye(4)) for k in fixed_names}
moving=[key('Part_009'),key('Part_023'),key('Part_026'),key('Part_027'),key('Part_020'),key('Part_022')]
def check(alpha,theta):
 mats=kin(alpha,theta)
 if mats is None:return 'closure'
 posed={}
 for name in moving:
  ob=meshes[name].posed(mats[meshes[name].group])
  for k,other in fixed.items():
   if overlap(ob,other):return name+' / '+k
  for k,other in posed.items():
   if meshes[k].group!=meshes[name].group and overlap(ob,other):return name+' / '+k
  posed[name]=ob
 return None
def edge(theta,clear,blocked):
 assert check(clear,theta) is None and check(blocked,theta) is not None
 while abs(clear-blocked)>.01:
  mid=(clear+blocked)/2
  if check(mid,theta) is None:clear=mid
  else:blocked=mid
 return clear
def generate(audit_path):
 audit=json.loads(audit_path.read_text());g=audit['grid'];states=np.array(g['states']);ts=np.array(g['theta_degrees']);aa=np.array(g['alpha_degrees']);good=[]
 for i,t in enumerate(ts):
  found=aa[states[:,i]==1]
  if len(found):good.append((t,float(found.min()),float(found.max())))
 base=np.array(good);raw=[];start=time.time()
 for theta in range(-52,139):
  lo=np.interp(theta,base[:,0],base[:,1]);hi=np.interp(theta,base[:,0],base[:,2]);samples=np.arange(math.floor(lo)-6,math.ceil(hi)+7,2.)
  hits=[check(float(a),theta) for a in samples];indices=[i for i,x in enumerate(hits) if x is None]
  assert indices and indices==list(range(min(indices),max(indices)+1)),(theta,'clear region has holes')
  i,j=min(indices),max(indices);assert i>0 and j<len(samples)-1,(theta,'extend bracket')
  low=edge(theta,float(samples[i]),float(samples[i-1]));high=edge(theta,float(samples[j]),float(samples[j+1]))
  raw.append([theta,low,high])
  if theta%10==0:print('Envelope',theta,'elapsed',round(time.time()-start),flush=True)
 # Reserve two degrees in both variables; whole-degree inward rounding adds a
 # guard against sub-grid variations. Interpolation and motion paths are checked separately.
 nodes=[]
 for theta in range(-50,137):
  nearby=[r for r in raw if abs(r[0]-theta)<=2]
  low=max(-58,math.ceil(max(r[1] for r in nearby)+2));high=min(172,math.floor(min(r[2] for r in nearby)-2))
  assert high>low
  nodes.append([theta,low,high])
 # Mechanical-envelope regeneration must preserve the selected horn indexing,
 # pulse conversion and calibration metadata; it does not own mounting offsets.
 profile=json.loads((ROOT/'servo_profile.json').read_text())
 profile['coupled_envelope']={'independent':'theta_Part005','dependent':'alpha_Part006','units':'degrees relative to current model zero','interpolation':'linear','angular_guard_degrees':2,'nodes':nodes,'raw_sampled_bounds':raw,'source_mesh_sha256':digest(ROOT/'mechanics/collision-meshes.npz'),'source_metadata_sha256':digest(ROOT/'mechanics/collision-meshes.json'),'scope':'Internal leg printed-part surfaces versus stationary servo/mount meshes and one another. No full-body, neighboring-leg, floor, cable or all-fastener qualification.'}
 profile['joint_bounds_degrees'][1]=[min(n[1] for n in nodes),max(n[2] for n in nodes)]
 profile['joint_bounds_degrees'][2]=[nodes[0][0],nodes[-1][0]]
 (ROOT/'servo_profile.json').write_text(json.dumps(profile,indent=2)+'\n');print('PROFILE COMPLETE',len(nodes),time.time()-start,flush=True)
if __name__=='__main__':
 args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
 ap=argparse.ArgumentParser();ap.add_argument('--audit',type=Path,required=True);a=ap.parse_args(args);generate(a.audit)
