import bpy,json
import numpy as np
from pathlib import Path
P=Path(__file__).resolve().parent
rig=json.loads((P/'blender-rig.json').read_text());scene=bpy.context.scene;scene.frame_set(3085);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();root=bpy.data.objects[rig['body']].evaluated_get(dg).matrix_world.inverted();v=[];details={}
for name in ['CRAWL | Body - Bottom Cover - Compact','CRAWL | Face - OV5647 Camera - 25x24 reference','CRAWL | Face - Front Carapace - 2.4 inch']:
 ob=bpy.data.objects.get(name)
 if ob is None:continue
 ob=ob.evaluated_get(dg);mesh=ob.to_mesh();a=np.empty(len(mesh.vertices)*3);mesh.vertices.foreach_get('co',a);a=a.reshape(-1,3);mat=np.array(root@ob.matrix_world);a=a@mat[:3,:3].T+mat[:3,3];ob.to_mesh_clear();lo=a[:,2].min();details[name]=dict(min_body_z_mm=float(lo),bounds_mm=[a.min(0).tolist(),a.max(0).tolist()])
 if 'Bottom Cover' in name:np.savez_compressed(P/'belly-cover-samples.npz',vertices=a);details[name]['bottom_xy_points_mm']=a[a[:,2]<lo+.01,:2].tolist()
# Preserve complete current rigid-body samples separately from contact geometry.
controls={name for group in rig['controls'].values() for name in group.values() if isinstance(name,str)}
body_ob=bpy.data.objects[rig['body']];all_vertices=[];included=[];object_minima={}
for ob0 in bpy.data.objects:
 if ob0.type!='MESH' or ob0.hide_render or not ob0.name.startswith('CRAWL | '):continue
 ancestor=ob0.parent;under=False;leg=False
 while ancestor:
  if ancestor.name in controls:leg=True
  if ancestor==body_ob:under=True
  ancestor=ancestor.parent
 if not under or leg:continue
 if 'BOW |' in ob0.name or 'FACE |' in ob0.name or 'FacePixel' in ob0.name:continue
 ob=ob0.evaluated_get(dg);mesh=ob.to_mesh();a=np.empty(len(mesh.vertices)*3);mesh.vertices.foreach_get('co',a);a=a.reshape(-1,3);mat=np.array(root@ob.matrix_world);a=a@mat[:3,:3].T+mat[:3,3];ob.to_mesh_clear();all_vertices.append(a);included.append(ob0.name);object_minima[ob0.name]=float(a[:,2].min())
np.savez_compressed(P/'current-body-samples.npz',vertices=np.concatenate(all_vertices))
(P/'current-body-provenance.json').write_text(json.dumps(dict(source_blend=bpy.data.filepath,frame=3085,objects=included,object_min_body_z_mm=object_minima,method='Evaluated body descendants excluding moving-leg-control descendants and hidden render objects',minimum_body_z_mm=float(np.concatenate(all_vertices)[:,2].min())),indent=2)+'\n')
(P/'belly-cover-provenance.json').write_text(json.dumps(dict(source_blend=bpy.data.filepath,frame=3085,objects=details),indent=2)+'\n');print(json.dumps({k:{a:b for a,b in val.items() if a!='bottom_xy_points_mm'} for k,val in details.items()}))
