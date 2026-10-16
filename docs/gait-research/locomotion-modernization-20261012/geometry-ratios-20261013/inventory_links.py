from pathlib import Path
import trimesh,numpy as np,json
root=Path('/home/greggles/Ainekio/Slave/hardware/v2-12servo/STL/Red')
rows=[]
for f in root.rglob('*.stl'):
 if not any(n in f.name for n in ['Part_009','Part_023','Part_026','Part_027']):continue
 mesh=trimesh.load(f,force='mesh');v=mesh.vertices;_,_,vh=np.linalg.svd(v-v.mean(0),full_matrices=False);normal=mesh.facets_normal[np.argmax(mesh.facets_area)];vh[0]=np.cross(normal,np.eye(3)[np.argmin(abs(normal))]);vh[0]/=np.linalg.norm(vh[0]);vh[1]=np.cross(normal,vh[0]);proj=v@normal;lo,hi=proj.min(),proj.max();circles=[]
 for frac in [.15,.3,.5,.7,.85]:
  section=mesh.section(plane_origin=normal*(lo+(hi-lo)*frac),plane_normal=normal)
  if section is None:continue
  for loop in section.discrete:

   if len(loop)<13:continue
   xy=loop@vh[:2].T
   mat=np.c_[2*xy,np.ones(len(xy))];sol=np.linalg.lstsq(mat,np.sum(xy*xy,axis=1),rcond=None)[0];center=sol[:2];rad=np.linalg.norm(xy-center,axis=1);err=np.max(abs(rad-rad.mean()))
   angles=np.sort(np.arctan2(xy[:,1]-center[1],xy[:,0]-center[0]));gap=np.diff(np.r_[angles,angles[0]+2*np.pi]).max()
   if err<.02 and gap<.7 and .6<rad.mean()<8:
    if not any(np.linalg.norm(center-np.array(c['center_plane']))<.15 and abs(rad.mean()-c['radius'])<.1 for c in circles):circles.append(dict(center_plane=center.tolist(),radius=float(rad.mean()),fit_error=float(err)))
 centers=[]
 for c in circles:
  if not any(np.linalg.norm(np.array(c['center_plane'])-cc)<.15 for cc in centers):centers.append(np.array(c['center_plane']))
 distances=sorted(set(round(float(np.linalg.norm(a-b)),2) for i,a in enumerate(centers) for b in centers[i+1:] if np.linalg.norm(a-b)>10))
 row=dict(file=str(f.relative_to(root)),bounds_mm=mesh.extents.tolist(),circles=circles,axis_pair_distances_mm=distances);rows.append(row)
 print(f.parent.name,f.name.split('Part_')[-1],'distances',distances,flush=True)
out=Path('/home/greggles/Ainekio/docs/gait-research/locomotion-modernization-20261012/geometry-ratios-20261013');(out/'stl-inventory.json').write_text(json.dumps(rows,indent=2))
