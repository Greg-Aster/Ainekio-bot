"""Offline screw-aware internal linkage envelope from captured current meshes.

Run in background Blender. No robot commands or runtime limiting are added.
The modeled contact boundary has a numerical tolerance, not an angular guard.
"""
import argparse,hashlib,json,math,sys,time
from pathlib import Path
import numpy as np
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ry(a):
 c,s=math.cos(a),math.sin(a);return np.array([[c,0,s],[0,1,0],[-s,0,c]])
def mesh(v,f):return dict(v=v,f=f,lo=v.min(0),hi=v.max(0),tree=None)
def overlap(a,b,joint=None):
 if np.any(a['lo']>b['hi']) or np.any(b['lo']>a['hi']):return False
 for m in (a,b):
  if m['tree'] is None:m['tree']=BVHTree.FromPolygons(m['v'].tolist(),m['f'].tolist(),all_triangles=True)
 hits=a['tree'].overlap(b['tree'])
 if not hits:return False
 if joint is None:return True
 mid=(a['v'][a['f'][[i for i,j in hits]]].mean(1)+b['v'][b['f'][[j for i,j in hits]]].mean(1))/2
 return bool(np.any(((mid[:,[0,2]]-joint)**2).sum(1)>=64))
class CollisionModel:
 pairs=[('Part_009','Part_023',None),('Part_009','Part_027',None),('Part_009','Part_026','input'),('Part_023','Part_027','knee'),('Part_023','Part_026',None),('Part_027','Part_026','output'),('Part_009','Part_020',None),('Part_009','Part_022',None),('Part_026','Part_020',None),('Part_026','Part_022',None),('Part_023','Head009',None),('Part_009','Head023',None)]
 def __init__(self,root=ROOT):
  self.meta=json.loads((root/'mechanics/collision-meshes.json').read_text());self.data=np.load(root/'mechanics/collision-meshes.npz');self.p=self.meta['parameters'];self.records={l:{r['label']:r for r in self.meta['records'] if r['leg']==l} for l in ['FL','FR','RL','RR']}
  self.fixed={l:{label:mesh(self.data[r['key']+'_v'],self.data[r['key']+'_f']) for label,r in rr.items() if r['group']=='fixed'} for l,rr in self.records.items()}
 def kin(self,alpha,theta):
  p=self.p;a=p['alpha_neutral']+math.radians(alpha);t=p['new_theta_neutral']+math.radians(theta);O=np.array(p['O']);C=np.array(p['C_new'])
  D=O+p['primary_length']*np.array([math.cos(a),math.sin(a)]);P=C+p['input_length']*np.array([math.cos(t),math.sin(t)]);w=P-D;d=np.linalg.norm(w);b=p['pickup_length'];L=p['rod_length']
  if not abs(L-b)+1e-7<d<L+b-1e-7:return None
  along=(b*b-L*L+d*d)/(2*d);height=math.sqrt(b*b-along*along);E=D+(along*w+p['assembly_branch']*height*np.array([-w[1],w[0]]))/d
  beta=math.atan2(E[1]-D[1],E[0]-D[0]);phi=math.atan2(E[1]-P[1],E[0]-P[0])
  return {'input':(ry(p['old_theta_neutral']-t),[C[0],0,C[1]]),'primary':(ry(p['alpha_neutral']-a),[O[0],0,O[1]]),'rod':(ry(p['old_rod_reference_angle']-phi),[P[0],0,P[1]]),'foot':(ry(p['beta_neutral']-beta),[D[0],0,D[1]])},dict(input=P,knee=D,output=E)
 def check(self,alpha,theta,leg='FR',first=False):
  k=self.kin(alpha,theta)
  if k is None:return ['closure']
  mats,joints=k;ms={};findings=[]
  for label,r in self.records[leg].items():
   if r['group']=='fixed':continue
   R,T=mats[r['group']];key=r['key'];ms[label]=mesh(self.data[key+'_v']@R.T+T,self.data[key+'_f'])
  for a,b,j in self.pairs:
   if overlap(ms[a],ms[b],joints[j] if j else None):
    findings.append(a+'/'+b)
    if first:return findings
  for label,m in ms.items():
   if label.startswith('Head'):continue
   for b,f in self.fixed[leg].items():
    if overlap(m,f):
     findings.append(label+'/'+b)
     if first:return findings
  return findings
 def edge(self,theta,clear,blocked,leg='FR',tolerance=.001):
  assert not self.check(clear,theta,leg,True) and self.check(blocked,theta,leg,True),(theta,clear,blocked,leg)
  while abs(clear-blocked)>tolerance:
   mid=(clear+blocked)/2
   if self.check(mid,theta,leg,True):blocked=mid
   else:clear=mid
  return clear

def generate(root=ROOT):
 model=CollisionModel(root);profile=json.loads((root/'servo_profile.json').read_text());old=np.array(profile['coupled_envelope']['raw_sampled_bounds']);raw=[];start=time.monotonic()
 # Actual crank-versus-Part006 boundary; centidegree inward rounding matches
 # command precision, without the former two-degree guard or amplitude cap.
 for theta in np.sort(np.r_[-53.27,np.arange(-53,140),135.97889427226454,139.36]):
  theta=min(float(theta),139.36)
  if raw and theta==raw[-1][0]:continue
  low=max(-39.99,float(np.interp(theta,old[:,0],old[:,1])));high=float(np.interp(theta,old[:,0],old[:,2]));seed=(low+high)/2
  assert not model.check(seed,theta,first=True),(theta,seed,'seed contact')
  lo=seed
  while not model.check(lo-4,theta,first=True):lo-=4
  hi=seed
  while not model.check(hi+4,theta,first=True):hi+=4
  lower=model.edge(theta,lo,lo-4);upper=model.edge(theta,hi,hi+4)
  # Intersect all four current legs' connected regions, not only a mirrored
  # ideal leg. Most boundary tests are AABB rejects before tree construction.
  for leg in ['FL','RL','RR']:
   if model.check(lower,theta,leg,True):lower=model.edge(theta,seed,lower,leg)
   if model.check(upper,theta,leg,True):upper=model.edge(theta,seed,upper,leg)
  raw.append([theta,lower,upper])
  if len(raw)%10==0:print('Envelope',theta,'seconds',round(time.monotonic()-start),flush=True)
 nodes=[[t,max(-39.99,math.ceil(a*100)/100),math.floor(b*100)/100] for t,a,b in raw]
 # Include the optimized maximum witness, retaining full carrier reach.
 profile['coupled_envelope']=dict(independent='theta_Part005',dependent='alpha_Part006',units='degrees relative to current model zero',interpolation='linear',angular_guard_degrees=0,numerical_boundary_tolerance_degrees=.01,nodes=nodes,raw_sampled_bounds=raw,source_mesh_sha256=digest(root/'mechanics/collision-meshes.npz'),source_metadata_sha256=digest(root/'mechanics/collision-meshes.json'),scope=model.meta['scope'])
 profile['joint_bounds_degrees'][1]=[min(n[1] for n in nodes),185.33];profile['joint_bounds_degrees'][2]=[-53.27,139.36]
 (root/'servo_profile.json').write_text(json.dumps(profile,indent=2)+'\n');print('PROFILE COMPLETE',len(nodes),time.monotonic()-start,flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=ROOT);args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [];generate(ap.parse_args(args).root)
