"""Background saved-file preservation, actual mechanism checks and five-second preview."""
import bpy,json,array,hashlib
from pathlib import Path
from mathutils import Vector
P=Path(__file__).resolve().parent
assert bpy.app.background
rig=json.loads((P/'blender-rig.json').read_text())
def signatures():
    result={}
    for old,name in {**rig['objects'],**{('TEST '+k):v for k,v in rig['existing_test_objects'].items()}}.items():
        ob=bpy.data.objects.get(name)
        if ob is None:continue
        row=dict(parent=ob.parent.name if ob.parent else None,type=ob.type)
        if ob.type=='MESH':
            mesh=ob.data;co=array.array('f',[0])*len(mesh.vertices)*3;indices=array.array('i',[0])*len(mesh.loops)
            mesh.vertices.foreach_get('co',co);mesh.loops.foreach_get('vertex_index',indices)
            row['mesh']=hashlib.sha256(co.tobytes()+indices.tobytes()).hexdigest()
        if old.startswith('TEST ') and ob.animation_data and ob.animation_data.action:
            ad=ob.animation_data
            curves=ad.action.layers[0].strips[0].channelbag(ad.action_slot).fcurves
            row['tests']=[(f.data_path,f.array_index,[(tuple(k.co),tuple(k.handle_left),tuple(k.handle_right),k.interpolation) for k in f.keyframe_points]) for f in curves]
        result[name]=row
    return result



bpy.ops.wm.open_mainfile(filepath=str(P/'Before-Sit-Bored.blend'))
old=signatures()
bpy.ops.wm.open_mainfile(filepath=str(P/'Ainekio-Sit-Bored.blend'))
new=signatures();changed=[n for n,v in old.items() if new.get(n)!=v]
cover_names={'CRAWL | Body - Top Cover - Compact','CRAWL | Body - Bottom Cover - Compact','TESTS | Body - Top Cover - Compact','TESTS | Body - Bottom Cover - Compact'}
unexpected=[n for n in changed if n not in cover_names]
(P/'preservation.json').write_text(json.dumps(dict(compared_objects=len(old),unexpected_changes=unexpected,cover_differences_since_initial_backup=[n for n in changed if n in cover_names],scope='Current cover edits retained. Other mapped model meshes/parents and original test keys/handles compared with initial backup; three independent screen overlays added.'),indent=2))
assert not unexpected,unexpected
# Refresh only measured fixed-body samples from the current saved model; preserve its meshes.
import numpy as np
scene=bpy.context.scene;scene.frame_set(529);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
root=bpy.data.objects[rig['body']].evaluated_get(dg).matrix_world.inverted()
reference=json.loads((P/'body-and-face-reference.json').read_text());points=[]
for name in reference['included_body_meshes']:
    ob=bpy.data.objects[name].evaluated_get(dg);mesh=ob.to_mesh();vv=np.empty(len(mesh.vertices)*3);mesh.vertices.foreach_get('co',vv);mat=np.array(root@ob.matrix_world)
    points.extend((vv.reshape(-1,3)@mat[:3,:3].T+mat[:3,3]).tolist());ob.to_mesh_clear()
np.savez_compressed(str(P/'body-samples.npz'),vertices=np.array(points))
reference['body_bounds']=[np.min(points,axis=0).tolist(),np.max(points,axis=0).tolist()]
reference['cover_edits_preserved']=True
(P/'body-and-face-reference.json').write_text(json.dumps(reference,indent=2))
p=P/'check_blender.py';exec(compile(p.read_text(),str(p),'exec'),{'__file__':str(p)})
scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_x=640;scene.render.resolution_y=540;scene.render.resolution_percentage=100
scene.display.shading.show_shadows=False;scene.display.shading.show_cavity=False
if 'FXAA' in {x.identifier for x in scene.display.bl_rna.properties['render_aa'].enum_items}:scene.display.render_aa='FXAA'
if 'PNG' in {x.identifier for x in scene.render.image_settings.bl_rna.properties['file_format'].enum_items}:scene.render.image_settings.file_format='PNG'
camera=scene.camera
try:camera.driver_remove('location',0)
except (TypeError,RuntimeError):pass
camera.location=(250.,-330.,185.);camera.rotation_euler=(Vector((0.,0.,55.))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=325.
frames=P/'preview-frames';frames.mkdir(exist_ok=True)
for i in range(30):
    scene.frame_set(529+i*4);scene.render.filepath=str(frames/f'{i:04}.png');bpy.ops.render.render(write_still=True)
scene.frame_set(649);scene.render.filepath=str(P/'sit-bored-preview.png');bpy.ops.render.render(write_still=True)
print('SAVED SIT VERIFIED; PREVIEW COMPLETE',flush=True)
