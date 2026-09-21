"""Background-only: save and reopen each independent turn; check its actual rig."""
import array
import hashlib
import json
from pathlib import Path
import bpy
from mathutils import Vector

P=Path(__file__).resolve().parent
assert bpy.app.background, 'Run in background Blender; do not replace a live scene with this batch.'
catalog=json.loads((P/'catalog.json').read_text())
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


for entry in catalog['commands']:
    command=entry['command'];folder=P/entry['path']
    bpy.ops.wm.open_mainfile(filepath=str(P/'Before-Turn-Family.blend'))
    baseline=signatures()
    path=P/'apply_turn.py'
    exec(compile(path.read_text(),str(path),'exec'),{'__file__':str(path),'COMMAND_NAME':command,'PLAY':False})
    saved=bpy.data.filepath
    bpy.ops.wm.open_mainfile(filepath=saved)
    after=signatures();changes=[n for n,v in baseline.items() if after.get(n)!=v]
    (folder/'preservation.json').write_text(json.dumps(dict(compared_objects=len(baseline),unexpected_changes=changes,
        scope='All rig and original test meshes/parents; original test keys and handles; saved-file reopen.'),indent=2))
    assert not changes,changes
    path=P/'check_turn_blender.py'
    exec(compile(path.read_text(),str(path),'exec'),{'__file__':str(path),'COMMAND_NAME':command})
    # Preview settings affect only this background process, after the file was saved and verified.
    scene=bpy.context.scene
    scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=640;scene.render.resolution_y=540;scene.render.resolution_percentage=100
    scene.display.shading.show_shadows=False;scene.display.shading.show_cavity=False
    if 'FXAA' in {x.identifier for x in scene.display.bl_rna.properties['render_aa'].enum_items}:scene.display.render_aa='FXAA'
    if 'PNG' in {x.identifier for x in scene.render.image_settings.bl_rna.properties['file_format'].enum_items}:scene.render.image_settings.file_format='PNG'
    camera=scene.camera
    try:camera.driver_remove('location',0)
    except (TypeError,RuntimeError):pass
    camera.location=(240.,-320.,235.)
    camera.rotation_euler=(Vector((0.,0.,45.))-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.type='ORTHO';camera.data.ortho_scale=340.
    source=json.loads((folder/'source.json').read_text())
    t0,t1=source['validation']['turn_time_range_s']
    scene.frame_set(529+round((t0+t1)/2*scene.render.fps))
    scene.render.filepath=str(folder/'preview.png');bpy.ops.render.render(write_still=True)
    print('COMMAND SAVED, REOPENED, CHECKED AND PREVIEWED',command,flush=True)
print('ALL EIGHT TURN COMMANDS COMPLETE',flush=True)
