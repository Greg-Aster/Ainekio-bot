"""Export the already-reviewed compact 55 mm candidate for Blender."""
exec(open(str(__import__('pathlib').Path(__file__).with_name('compact_verify.py'))).read().split('cases=')[0])
from return_path_extended import fk3
F,A,L,b,crank,H,stroke=55,26,23,27,21,51,60
projection=original@u;vertices=original-u*np.clip((-projection-7)/14,0,1)[:,None]
m.foot=F;m.ref=F*m.u;m.r=crank;m.A=A;m.b=b;m.L=L;m.C=m.O+np.array([4.,0.]);w.ref3=np.array([m.ref[0],-56.65,m.ref[1]]);w.hull3=vertices[ConvexHull(vertices).vertices]
w.feet=original_feet.copy();w.feet[:,:,0]=centres+(original_feet[:,:,0]-centres)*stroke/82
w.shift=original_shift.copy();w.shift[:,0]*=stroke/82
w.acc=original_acc.copy();w.acc[:,0]*=stroke/82
r=w.evaluate((A,b,L,H+49.2500076-47.27323),True)
q=np.stack([r['legs'][leg]['q'] for leg in w.legs],1)
r['q']=np.rad2deg(np.unwrap(np.deg2rad(q),axis=0)).tolist()
r['forward']={leg:{key:value.tolist() for key,value in fk3(leg,q[:,k]).items()} for k,leg in enumerate(w.legs)}
r['geometry_mm']={'foot':F,'carrier':A,'rod':L,'pickup':b,'crank':crank,'clearance':H,'stroke':stroke,'crank_relative_carrier':[4,0]}
r['C']=m.C.tolist();r['vertices']=vertices.tolist();r['cycle_seconds']=2
assert r['stance_closed'] and all(all(v['ok']) for v in r['forward'].values())
(p/'compact55-animation-cycle.json').write_text(json.dumps(r,indent=2))
print('Exported 120 samples, all four legs close; dimensions',r['geometry_mm'])
