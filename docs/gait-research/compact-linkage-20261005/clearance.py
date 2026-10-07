import bpy,json,math,time
import numpy as np
from mathutils.bvhtree import BVHTree
from pathlib import Path
ROOT=Path('/tmp/ainekio-compact-linkage');m=np.load(ROOT/'mesh-reference.npz');poses=np.load(ROOT/'collision-poses.npz');p=json.loads(Path('/home/greggles/Ainekio/Slave/software/models/v2-12servo/geometry.json').read_text())['parameters'];C=np.array(p['C_new']);O=np.array(p['O'])
def tree(v,f):return BVHTree.FromPolygons(v.tolist(),f.tolist(),all_triangles=True)
def ry(t):return np.array([[math.cos(t),0,math.sin(t)],[0,1,0],[-math.sin(t),0,math.cos(t)]])
def unit(t):return np.array([math.cos(t),math.sin(t)])
def xyz(v):return np.array([v[0],0,v[1]])
fixed={i:tree(m['v'+str(i)],m['f'+str(i)]) for i in [4,5,6]}
fixedbounds={i:(m['v'+str(i)].min(0),m['v'+str(i)].max(0)) for i in fixed}
pairs=[(0,1),(0,2),(0,3),(0,4),(0,5),(0,6),(2,1),(2,3),(2,4),(2,5),(2,6),(3,4),(3,5),(3,6)]
variants=[(24,24),(32,36),(28,30),(26,28)]
summary=[];saved={}
for r,b in variants:
    raw={i:m['v'+str(i)].copy() for i in range(4)}
    for i,ref,cut,extra in [(0,p['old_theta_neutral'],18.95,r-24),(2,p['beta_neutral'],12,b-24)]:
        u=np.array([math.cos(ref),0,math.sin(ref)]);raw[i][raw[i]@u>cut]+=extra*u
    records=[];start=time.time()
    for k in range(len(poses['a'])):
        D=poses['D'][k];a=poses['a'][k];beta=poses['beta'][k];E=D+b*unit(beta);v=E-C;d=np.linalg.norm(v);theta=math.atan2(v[1],v[0])-math.acos((r*r+d*d-38**2)/(2*r*d));P=C+r*unit(theta);gamma=math.atan2(*(E-P)[::-1])
        vertices={i:raw[i]@ry(t).T+xyz(o) for i,t,o in [(0,p['old_theta_neutral']-theta,C),(1,p['alpha_neutral']-a,O),(2,p['beta_neutral']-beta,D),(3,p['old_rod_reference_angle']-gamma,P)]}
        bounds={**fixedbounds,**{i:(v.min(0),v.max(0)) for i,v in vertices.items()}};trees=dict(fixed);hits=[]
        for i,j in pairs:
            if np.any(bounds[i][1]<bounds[j][0]) or np.any(bounds[j][1]<bounds[i][0]):continue
            for n in [i,j]:
                if n not in trees:trees[n]=tree(vertices[n],m['f'+str(n)])
            if trees[i].overlap(trees[j]):hits.append(f'{i}-{j}')
        records.append(hits)
        if k%200==0:print(r,b,k,'elapsed',round(time.time()-start),flush=True)
    saved[f'{r}/{b}']=records
    base=saved['24/24'];new=[dict(sample=k,group=str(poses['groups'][k]),source_index=int(poses['index'][k]),leg=int(poses['leg'][k]),pairs=sorted(set(h)-set(base[k]))) for k,h in enumerate(records) if set(h)-set(base[k])]
    counts={pair:sum(pair in h for h in records) for pair in set(sum(records,[]))}
    summary.append(dict(crank=r,pickup=b,samples=len(records),contact_counts=counts,new_contacts_vs_original=new))
    print('SUMMARY',r,b,'newcontacts',len(new),'counts',counts,flush=True)
    (ROOT/'clearance.json').write_text(json.dumps(summary,indent=2))
print('complete')
