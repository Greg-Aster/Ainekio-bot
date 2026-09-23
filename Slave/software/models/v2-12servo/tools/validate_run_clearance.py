"""Part027 pair interference using exported live meshes and native joint poses."""
import json,sys,math,argparse,time,hashlib,bpy,bmesh
from pathlib import Path
import numpy as np
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--midpoints',action='store_true');ap.add_argument('--source',type=Path,default=ROOT/'motions/run/source.json');ap.add_argument('--report',type=Path,required=True);ap.add_argument('--step',type=int,default=1);ap.add_argument('--start',type=float,default=0);ap.add_argument('--end',type=float,default=1e9);args=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
cfg=json.loads((ROOT/'geometry.json').read_text());p=cfg['parameters'];mesh={};mesh_provenance={}
assert bpy.data.filepath,'Open the current robot Blender project first'
for leg,g in cfg['legs'].items():
    vs=[];ts=[];count=0;names=[]
    for key in ['2','10','11']:
        obj=bpy.data.objects['ML | '+g['objects'][key]]
        assert obj.parent.name=='ML | REFINED | '+leg+' | foot'
        assert all(m.type=='WEIGHTED_NORMAL' for m in obj.modifiers)
        if obj.animation_data and obj.animation_data.action:
            assert all(c.data_path in {'hide_viewport','hide_render'} for l in obj.animation_data.action.layers for st in l.strips for b in st.channelbags for c in b.fcurves)
        data=obj.data;data.calc_loop_triangles()
        xyz=np.empty(len(data.vertices)*3,dtype=np.float32);data.vertices.foreach_get('co',xyz)
        M=np.array(obj.matrix_parent_inverse@obj.matrix_basis);xyz=xyz.reshape(-1,3)@M[:3,:3].T+M[:3,3]
        tri=np.empty(len(data.loop_triangles)*3,dtype=np.int32);data.loop_triangles.foreach_get('vertices',tri)
        vs.extend(xyz);ts.extend(tri.reshape(-1,3)+count);count+=len(xyz);names.append(obj.name)
    mesh[leg+'_vertices']=np.array(vs);mesh[leg+'_triangles']=np.array(ts,dtype=np.int32)
    mesh_provenance[leg]=dict(objects=names,sha256=hashlib.sha256(mesh[leg+'_vertices'].tobytes()+mesh[leg+'_triangles'].tobytes()).hexdigest())
    bm=bmesh.new()
    for co in vs:bm.verts.new(co)
    result=bmesh.ops.convex_hull(bm,input=list(bm.verts),use_existing_faces=False);bm.normal_update()
    faces=[g for g in result['geom'] if isinstance(g,bmesh.types.BMFace)]
    hull_vertices={v for face in faces for v in face.verts}
    mesh[leg+'_convex_vertices']=np.array([tuple(v.co) for v in hull_vertices])
    mesh[leg+'_convex_normals']=np.unique(np.round([tuple(face.normal) for face in faces],8),axis=0)
    bm.free()
legs=['FL','FR','RL','RR'];pairs=[('FL','RL'),('FR','RR'),('FL','FR'),('RL','RR'),('FL','RR'),('FR','RL')]
def rx(t):
 c,s=math.cos(t),math.sin(t);return np.array([[1,0,0],[0,c,-s],[0,s,c]])
def ry(t):
 c,s=math.cos(t),math.sin(t);return np.array([[c,0,s],[0,1,0],[-s,0,c]])
def foot(leg,q):
 a=p['alpha_neutral']+q[1];t=p['new_theta_neutral']+q[2];D=np.array(p['O'])+p['primary_length']*np.array([math.cos(a),math.sin(a)]);P=np.array(p['C_new'])+p['input_length']*np.array([math.cos(t),math.sin(t)]);v=P-D;d=np.linalg.norm(v);b=p['pickup_length'];L=p['rod_length'];along=(b*b-L*L+d*d)/(2*d);h=math.sqrt(max(0,b*b-along*along));E=D+(along*v+p['assembly_branch']*h*np.array([-v[1],v[0]]))/d;beta=math.atan2(E[1]-D[1],E[0]-D[0]);g=cfg['legs'][leg];S=np.array(g['shoulder_world']);M=np.array(g['mechanism_local']);R=S[:3,:3]@rx(q[0]);T=S[:3,3]+R@M[:3,3];R=R@M[:3,:3];T+=R@np.array([D[0],0,D[1]]);return R@ry(-(beta-p['beta_neutral'])),T
text=args.source.read_text()
if args.source.suffix=='.jsonl':
 raw=[json.loads(s) for s in text.splitlines()];samples=[dict(time_s=i/120,actuator_angles_rad=np.array(s['q']).reshape(4,3)[[2,3,0,1]]) for i,s in enumerate(raw)]
else:samples=json.loads(text)['samples']
if args.midpoints:
 expanded=[]
 for a,b in zip(samples,samples[1:]):
  expanded.extend([a,dict(time_s=(a['time_s']+b['time_s'])/2,actuator_angles_rad=(np.array(a['actuator_angles_rad'])+np.array(b['actuator_angles_rad']))/2)])
 expanded.append(samples[-1]);samples=expanded
report=dict(file=bpy.data.filepath,mesh_provenance=mesh_provenance,source=str(args.source),source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),sampled_poses=0,intersections=[],pair_stats={a+'-'+b:dict(projected_crossings=0,minimum_lateral_gap_mm=None,intersecting_poses=0,minimum_separating_plane_gap_mm=None) for a,b in pairs},scope='All six pairs of lower-leg assemblies (Part027 plus inner/outer boots); native source knots and optional linear-joint midpoints. Exact triangle intersection after broadphase; separating-plane gaps conservatively bound mesh distance. Common chassis pose removed. No whole-robot or continuous-time collision proof.')
tris={l:mesh[l+'_triangles'].tolist() for l in legs};started=time.monotonic()
for n,row in enumerate(samples):
 if n%args.step or not args.start<=row['time_s']<=args.end:continue
 report['sampled_poses']+=1;vertices={};bounds={};bvh={};hulls={};normals={}
 for leg,q in zip(legs,row['actuator_angles_rad']):
  R,T=foot(leg,q);v=mesh[leg+'_vertices']@R.T+T;vertices[leg]=v;bounds[leg]=(v.min(0),v.max(0))
  if leg+'_convex_vertices' in mesh:
   hulls[leg]=mesh[leg+'_convex_vertices']@R.T+T;normals[leg]=mesh[leg+'_convex_normals']@R.T
 for a,b in pairs:
  amin,amax=bounds[a];bmin,bmax=bounds[b];gap=np.maximum(amin-bmax,bmin-amax);stats=report['pair_stats'][a+'-'+b]
  if gap[0]<=0 and gap[2]<=0:
   stats['projected_crossings']+=1;stats['minimum_lateral_gap_mm']=float(gap[1]) if stats['minimum_lateral_gap_mm'] is None else min(stats['minimum_lateral_gap_mm'],float(gap[1]))
  best=float(np.max(gap))
  if best<3 and a in hulls:
   axes=np.vstack([normals[a],normals[b]]);axes/=np.linalg.norm(axes,axis=1)[:,None]
   pa=hulls[a]@axes.T;pb=hulls[b]@axes.T
   best=max(best,float(np.maximum(pa.min(0)-pb.max(0),pb.min(0)-pa.max(0)).max()))
  stats['minimum_separating_plane_gap_mm']=max(0.,best) if stats['minimum_separating_plane_gap_mm'] is None else min(stats['minimum_separating_plane_gap_mm'],max(0.,best))
  if best>0:continue
  for leg in (a,b):
   if leg not in bvh:bvh[leg]=BVHTree.FromPolygons(vertices[leg].tolist(),tris[leg],all_triangles=True)
  hits=bvh[a].overlap(bvh[b])
  if hits:
   stats['intersecting_poses']+=1;report['intersections'].append(dict(sample=n,time_s=row['time_s'],pair=[a,b],triangle_pairs=len(hits)))
report['intersecting_poses']=len({x['sample'] for x in report['intersections']});report['elapsed_s']=time.monotonic()-started;report['passed']=report['intersecting_poses']==0;args.report.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='intersections'},indent=2));print('FIRST',report['intersections'][:3])

assert report['passed'],'Intersections found in the lower-leg assemblies'
