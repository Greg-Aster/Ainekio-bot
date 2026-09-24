"""Add the current motion library as a separate scene, sharing existing meshes.

Run inside the current Blender project. Saving and recovery belong to the caller.
The existing modeling and gait scenes are preserved. Sources are baked in full.
"""
import bpy,json,math,hashlib
from pathlib import Path
import numpy as np
from mathutils import Vector,Euler
ROOT=Path(globals()['MODEL_ROOT']) if 'MODEL_ROOT' in globals() else Path(__file__).resolve().parents[1]
SCENE='Motions - Current Geometry'

def build():
    assert Path(bpy.data.filepath).name in {'ainekio-variable-gait.blend','ainekio-variable-gait-Recovery.blend'},bpy.data.filepath
    assert SCENE not in bpy.data.scenes,'Existing motion scene must be reviewed before replacing it.'
    cfg=json.loads((ROOT/'geometry.json').read_text());src=bpy.data.scenes['Gait - Stride and Rate'];layer=src.view_layers['Gait playback']
    if bpy.context.window:bpy.context.window.scene=src;bpy.context.window.view_layer=layer
    src.frame_set(src.frame_current);bpy.context.view_layer.update()
    originals={o.name:(o.as_pointer(),o.data.as_pointer() if o.data else 0,o.animation_data.action.as_pointer() if o.animation_data and o.animation_data.action else 0) for s in bpy.data.scenes for o in s.objects}
    scene=bpy.data.scenes.new(SCENE);scene.render.fps=30;scene.render.fps_base=1;scene.render.resolution_x=1280;scene.render.resolution_y=800;scene.render.resolution_percentage=100
    scene.unit_settings.system=src.unit_settings.system;scene.unit_settings.scale_length=src.unit_settings.scale_length
    scene.render.engine='BLENDER_WORKBENCH';sh=scene.display.shading;sh.light='STUDIO';sh.studio_light='paint.sl';sh.color_type='MATERIAL';sh.show_shadows=False;sh.show_cavity=True;sh.cavity_type='BOTH';sh.background_type='WORLD';scene.world=src.world.copy() if src.world else bpy.data.worlds.new('ML | World');scene.world.color=(.035,.04,.055)
    scene.render.film_transparent=False;scene.sync_mode='FRAME_DROP';scene.view_layers[0].name='Motion playback'
    collections={}
    for name in ['Model','Controls','Stage']:
        c=bpy.data.collections.new('MOTION LIBRARY - '+name);scene.collection.children.link(c);collections[name]=c
    candidates=set()
    for name in ['VARIABLE GAIT - Model','VARIABLE GAIT - Cached face','VARIABLE GAIT - Controls']:
        candidates.update(o for o in bpy.data.collections[name].objects if o.visible_get(view_layer=layer) and o.name!='VG | Gait parameters')
    for o in list(candidates):
        parent=o.parent
        while parent:candidates.add(parent);parent=parent.parent
    mapping={}
    for o in candidates:
        clone=o.copy();clone.name='ML | '+o.name.removeprefix('VG | ');clone['motion_library_source']=o.name
        collections['Model' if o.type=='MESH' else 'Controls'].objects.link(clone);mapping[o]=clone
        if clone.animation_data:
            clone.animation_data.action=None
            for track in list(clone.animation_data.nla_tracks):clone.animation_data.nla_tracks.remove(track)
    for o,clone in mapping.items():
        clone.parent=mapping.get(o.parent);clone.hide_viewport=False;clone.hide_render=False
        if clone.animation_data:
            for fc in clone.animation_data.drivers:
                for var in fc.driver.variables:
                    for target in var.targets:
                        if target.id in mapping:target.id=mapping[target.id]
                        elif isinstance(target.id,bpy.types.Object) and target.id not in mapping.values():raise AssertionError(('external driver',clone.name,target.id.name))
        for constraint in clone.constraints:
            if hasattr(constraint,'target') and constraint.target:constraint.target=mapping.get(constraint.target,constraint.target)
        for modifier in clone.modifiers:
            if hasattr(modifier,'object') and modifier.object:modifier.object=mapping.get(modifier.object,modifier.object)
    frames=[];body=[];euler=[];joints=[];chapters=[];cursor=1
    order=['walk','sit','rest','wave','point','nod','pushup','bow','dance','swim','cute','freaky','worm','shake','shrug','dead','lay_down','celebrate','stretch','surprised','sad','curious']+[f'turn_{side}_{angle}' for angle in [15,45,90,180] for side in ['left','right']]
    for command in order:
        if command=='walk':
            folder=ROOT/'motions/walk';source=json.loads((folder/'source.json').read_text());d=source['columns'];t=np.array(d['time_s']);b=np.array(d['body']);e=np.array(d['body_euler']);q=np.array(d['q'])[:,[2,3,0,1]];semantic=t[-1]
        else:
            folder=ROOT/'motions'/('turns/commands' if command.startswith('turn_') else 'gestures')/command
            source=json.loads((folder/'source.json').read_text());rows=source['samples'];t=np.array([x['time_s'] for x in rows]);b=np.array([x['body_translation_world_mm'] for x in rows]);e=np.array([x['body_rotation_euler_xyz_rad'] for x in rows]);q=np.array([x['actuator_angles_rad'] for x in rows]);manifest=json.loads((folder/'manifest.json').read_text());semantic=manifest.get('semantic_end_seconds',t[-1])
        f=cursor+t*30;frames.extend(f);body.extend(b);euler.extend(e);joints.extend(q)
        end=math.ceil(f[-1]);hold_end=end+30;frames.append(float(hold_end));body.append(b[-1]);euler.append(e[-1]);joints.append(q[-1])
        title='Play Dead' if command=='dead' else command.replace('_',' ').title();chapters.append({'command':command,'label':title,'start_frame':cursor,'end_frame':hold_end,'source_end_frame':float(f[-1]),'semantic_end_frame':float(cursor+semantic*30),'source_duration_s':float(t[-1]),'samples':len(t),'source':str(folder.relative_to(ROOT)/'source.json'),'source_sha256':hashlib.sha256((folder/'source.json').read_bytes()).hexdigest(),'presentation_cut_after':True})
        scene.timeline_markers.new(title,frame=cursor)
        if semantic<t[-1]-.05:scene.timeline_markers.new(title+' / demo recovery or hold',frame=round(cursor+semantic*30))
        cursor=hold_end+1
    frames=np.array(frames);body=np.array(body);euler=np.array(euler);joints=np.array(joints);cut_frames={x['end_frame'] for x in chapters}
    def bake(obj,channels,fs=frames,constant=False):
        for path,index,values in channels:
            if path.startswith('["'):obj[json.loads(path[1:-1])]=float(values[0])
            obj.keyframe_insert(data_path=path,index=index,frame=float(fs[0]));action=obj.animation_data.action
            fc=next(fc for layer in action.layers for strip in layer.strips for bag in strip.channelbags for fc in bag.fcurves if fc.data_path==path and fc.array_index==max(index,0))
            fc.keyframe_points.clear();fc.keyframe_points.add(len(fs));fc.keyframe_points.foreach_set('co',np.c_[fs,values].astype(np.float32).ravel())
            for kp,frame in zip(fc.keyframe_points,fs):kp.interpolation='CONSTANT' if constant or frame in cut_frames else 'LINEAR'
            fc.update();action.name='ML | '+obj.name.removeprefix('ML | ')
    pivot=Vector(cfg['continuous_walk']['body_rotation_pivot_mm']);locations=np.array([Vector(b)+pivot-Euler(tuple(e),'XYZ').to_matrix()@pivot for b,e in zip(body,euler)])
    root=mapping[bpy.data.objects['VG | Body motion']];bake(root,[('location',i,locations[:,i]) for i in range(3)]+[('rotation_euler',i,euler[:,i]) for i in range(3)])
    for i,leg in enumerate(['FL','FR','RL','RR']):
        rig=mapping[bpy.data.objects[f'VG | REFINED | {leg} | h alpha theta']];bake(rig,[(f'["{key}"]',-1,np.rad2deg(joints[:,i,j])) for j,key in enumerate(['h_deg','alpha_deg','theta_deg'])])
    follow=mapping[bpy.data.objects['VG | Camera follow']];bake(follow,[('location',i,body[:,i] if i<2 else np.zeros(len(body))) for i in range(3)])
    camera=bpy.data.objects.new('ML | Presentation',bpy.data.cameras.new('ML | Presentation'));collections['Stage'].objects.link(camera);camera.parent=follow;camera.location=(260,365,225);camera.rotation_euler=(Vector((10,0,48))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=440;camera.data.clip_end=10000;scene.camera=camera
    ground=bpy.data.meshes.new('ML | Ground');ground.from_pydata([(-2000,-2000,-.08),(4000,-2000,-.08),(4000,2000,-.08),(-2000,2000,-.08)],[],[(0,1,2,3)]);o=bpy.data.objects.new('ML | Ground',ground);collections['Stage'].objects.link(o);mat=bpy.data.materials.new('ML | Ground');mat.diffuse_color=(.085,.105,.13,1);ground.materials.append(mat)
    def label(name,text,location,size):
        data=bpy.data.curves.new(name,'FONT');data.body=text;data.size=size;data.extrude=0;data.align_y='TOP';o=bpy.data.objects.new(name,data);collections['Stage'].objects.link(o);o.parent=camera;o.location=location;o.color=(.8,.9,1,1);mat=bpy.data.materials.get('ML | Text') or bpy.data.materials.new('ML | Text');mat.diffuse_color=(.8,.9,1,1);data.materials.append(mat);return o
    label('ML | Heading','AINEKIO  /  MOTION LIBRARY',(-205,126,-350),7)
    label('ML | Instructions','Space: play     N > Ainekio: choose motion',(-205,-119,-350),5)
    for index,item in enumerate(chapters):
        text=f'{index+1:02d} / {len(chapters)}   '+item['label'];o=label('ML | Title | '+item['command'],text,(-205,112,-350),11)
        fs=np.array(sorted(set([1,item['start_frame'],item['end_frame']+1,chapters[-1]['end_frame']+1])));hidden=np.array([0. if item['start_frame']<=f<=item['end_frame'] else 1. for f in fs]);bake(o,[('hide_viewport',-1,hidden),('hide_render',-1,hidden)],fs,True)
    scene.frame_start=1;scene.frame_end=chapters[-1]['end_frame'];scene.use_preview_range=True;scene.frame_preview_start=1;scene.frame_preview_end=scene.frame_end
    scene['ainekio_motion_chapters']=json.dumps(chapters);scene['geometry_id']=cfg['geometry_id'];scene['hardware_qualified']=False
    for name,bodytext in [('MOTION LIBRARY - START HERE','Scene: '+SCENE+'\nSpace plays the motion chapters. N > Ainekio > Motion library selects one motion.\nThe timeline has named chapter markers. Each chapter preserves source timing, followed by one second holding its final pose and a presentation cut to the next command. Sit, Rest, Lay Down and Play Dead hold their command endpoints. Play Dead reaches the front arms farther than Lay Down.\nThe original modeling and walking scenes are preserved. Meshes are shared and animation is separate; the finished cached face is included.\nIf the selector is unavailable after reopening, run the packed blender_motion_controls.py text. All baked playback works without scripts.\n'),('MOTION LIBRARY - chapters.json',json.dumps(chapters,indent=2)),('blender_motion_controls.py',(ROOT/'tools/blender_motion_controls.py').read_text())]:
        text=bpy.data.texts.new(name);text.write(bodytext);text.use_module=name.endswith('.py')
    exec(compile((ROOT/'tools/blender_motion_controls.py').read_text(),'blender_motion_controls.py','exec'),{'__name__':'__main__'})
    for name,identity in originals.items():
        o=bpy.data.objects[name];assert identity==(o.as_pointer(),o.data.as_pointer() if o.data else 0,o.animation_data.action.as_pointer() if o.animation_data and o.animation_data.action else 0),name
    if bpy.context.window:
        bpy.context.window.scene=scene
        for area in bpy.context.window.screen.areas:
            if area.type=='VIEW_3D':area.spaces.active.region_3d.view_perspective='CAMERA';area.spaces.active.overlay.show_overlays=False;area.spaces.active.show_region_ui=True
    scene.frame_set(1)
    import runpy
    runpy.run_path(str(ROOT/'tools/append_blender_locomotion.py'), init_globals={'MODEL_ROOT':str(ROOT)}, run_name='append_locomotion')['append'](['crouch','upright','run','crawl_forward','crawl_backward','crawl_turn_left','crawl_turn_right','walk_forward','walk_backward','walk_turn_left','walk_turn_right','crab','crab_right','crab_forward','crab_backward','crab_turn_left','crab_turn_right'])
    chapters=json.loads(scene['ainekio_motion_chapters'])
    return {'scene':scene.name,'file':bpy.data.filepath,'objects':len(scene.objects),'motions':len(chapters),'source_samples':sum(x['samples'] for x in chapters),'frame_end':scene.frame_end,'fps':30,'source_objects_preserved':len(originals),'mesh_data_shared':True,'chapters':chapters}
if __name__=='__main__':print(json.dumps(build(),indent=2))
