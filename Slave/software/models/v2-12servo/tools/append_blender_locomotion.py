"""Append native locomotion demonstrations to the existing motion scene.

Run inside the open project after making and verifying its rolling recovery.
Existing geometry and all prior animation keys are retained. Saving is caller-owned.
"""
import bpy,json,hashlib,math
from pathlib import Path
import numpy as np
from mathutils import Vector,Euler
ROOT=Path(globals()['MODEL_ROOT']) if 'MODEL_ROOT' in globals() else Path(__file__).resolve().parents[1]

def append(order=None):
    scene=bpy.data.scenes['Motions - Current Geometry'];chapters=json.loads(scene['ainekio_motion_chapters']);old_end=scene.frame_end
    order=order or ['crouch','crawl_forward','crawl_backward','crawl_turn_left','crawl_turn_right','walk_forward','walk_backward','walk_turn_left','walk_turn_right']
    assert not set(order)&{c['command'] for c in chapters},'Review existing chapters before replacing them.'
    fps=scene.render.fps/scene.render.fps_base;assert fps==30
    cfg=json.loads((ROOT/'geometry.json').read_text());fs=[];bs=[];es=[];qs=[];cursor=old_end+1
    for command in order:
        folder=ROOT/('motions/run' if command=='run' else 'motions/gestures/'+command if command in {'crouch','upright'} else 'motions/locomotion/'+command);path=folder/'source.json';source=json.loads(path.read_text());rows=source['samples'];times=np.array([r['time_s'] for r in rows]);f=cursor+times*fps
        b=[r['body_translation_world_mm'] for r in rows];e=[r['body_rotation_euler_xyz_rad'] for r in rows];q=[r['actuator_angles_rad'] for r in rows]
        end=math.ceil(f[-1])+30;fs.extend(f);fs.append(end);bs.extend(b);bs.append(b[-1]);es.extend(e);es.append(e[-1]);qs.extend(q);qs.append(q[-1])
        title='Crab Left' if command=='crab' else 'Walk > Run > Walk' if command=='run' else 'Upright (experimental)' if command=='upright' else command.replace('_',' ').title();chapters.append(dict(command=command,label=title,start_frame=cursor,end_frame=end,source_end_frame=float(f[-1]),semantic_end_frame=float(f[-1]),source_duration_s=float(times[-1]),samples=len(rows),source=str(path.relative_to(ROOT)),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),presentation_cut_after=True,ongoing_native=command not in {'crouch','upright'}))
        scene.timeline_markers.new(title,frame=cursor)
        if command not in {'crouch','upright'}:
            stages=[(0,'Walk 100%'),(6,'Run 150%'),(14,'Run 200%'),(20,'Walk 75%'),(28,'Finish')] if command=='run' else [(0,'Speed 25%'),(6,'Speed 100%'),(12,'Stride 60% / cadence 3x'),(17,'Finish')]
            for seconds,label in stages:scene.timeline_markers.new(title+' | '+label,frame=cursor+seconds*30)
        if command=='upright':
            for seconds,label in [(0,'Sit'),(3,'Front feet back'),(8,'Supported push'),(12,'Rise'),(20,'Hold upright')]:
                scene.timeline_markers.new('Upright | '+label,frame=cursor+seconds*30)
        cursor=end+1
    fs=np.array(fs);bs=np.array(bs);es=np.array(es);qs=np.array(qs);cuts={c['end_frame'] for c in chapters};pivot=Vector(cfg['continuous_walk']['body_rotation_pivot_mm'])
    locations=np.array([Vector(b)+pivot-Euler(tuple(e),'XYZ').to_matrix()@pivot for b,e in zip(bs,es)])
    def curves(a):return [f for l in a.layers for s in l.strips for bag in s.channelbags for f in bag.fcurves]
    def bake(obj,channels,frames=fs,constant=False):
        for path,index,values in channels:
            action=obj.animation_data.action if obj.animation_data else None
            fc=next((f for f in curves(action) if f.data_path==path and f.array_index==max(index,0)),None) if action else None
            if fc is None:
                obj.keyframe_insert(data_path=path,index=index,frame=float(frames[0]));action=obj.animation_data.action;fc=next(f for f in curves(action) if f.data_path==path and f.array_index==max(index,0));fc.keyframe_points.clear()
            count=len(fc.keyframe_points)
            if count:assert fc.keyframe_points[-1].co.x<frames[0],obj.name
            fc.keyframe_points.add(len(frames))
            for k,frame,value in zip(list(fc.keyframe_points)[count:],frames,values):k.co=(float(frame),float(value));k.interpolation='CONSTANT' if constant or frame in cuts else 'LINEAR'
            fc.update()
    bake(bpy.data.objects['ML | Body motion'],[('location',i,locations[:,i]) for i in range(3)]+[('rotation_euler',i,es[:,i]) for i in range(3)])
    for i,leg in enumerate(['FL','FR','RL','RR']):bake(bpy.data.objects[f'ML | REFINED | {leg} | h alpha theta'],[(f'["{key}"]',-1,np.rad2deg(qs[:,i,j])) for j,key in enumerate(['h_deg','alpha_deg','theta_deg'])])
    bake(bpy.data.objects['ML | Camera follow'],[('location',i,bs[:,i] if i<2 else np.zeros(len(bs))) for i in range(3)])
    # Each title retains its original visibility keys; only total-count text changes.
    stage=bpy.data.collections['MOTION LIBRARY - Stage'];template=bpy.data.objects['ML | Title | walk']
    for index,item in enumerate(chapters):
        name='ML | Title | '+item['command'];obj=bpy.data.objects.get(name)
        if obj is None:
            obj=template.copy();obj.data=template.data.copy();obj.name=name;obj.animation_data_clear();stage.objects.link(obj)
            frames=np.array(sorted(set([1,item['start_frame'],item['end_frame']+1,chapters[-1]['end_frame']+1])));hidden=np.array([0. if item['start_frame']<=f<=item['end_frame'] else 1. for f in frames]);bake(obj,[('hide_viewport',-1,hidden),('hide_render',-1,hidden)],frames,True);obj.animation_data.action.name=name
        obj.data.body=f'{index+1:02d} / {len(chapters)}   '+item['label']
        if item.get('ongoing_native'):
            obj.data.size=8.5;obj.data.body+=('\nWalk 100% > Run 150% > Run 200% > Walk 75% > Finish' if item['command']=='run' else '\nSpeed 25% > 100% > Stride 60%, Cadence 3x > Finish')
    scene.frame_end=chapters[-1]['end_frame'];scene['ainekio_motion_chapters']=json.dumps(chapters)
    bpy.data.texts['MOTION LIBRARY - chapters.json'].clear();bpy.data.texts['MOTION LIBRARY - chapters.json'].write(json.dumps(chapters,indent=2))
    info=bpy.data.texts['MOTION LIBRARY - START HERE'];content=info.as_string().replace('all 30 motions',f'all {len(chapters)} chapters');info.clear();info.write(content+('\nRun chapter: native automatic Speed 100% Walk > 150% Run > 200% Run > 75% Walk > Finish. Front and rear pairs alternate with flight phases. Geometric demonstration only; physical running remains unqualified.\n' if order==['run'] else '' if order==['upright'] else '\nCrouch and directional locomotion chapters were appended from the native C gait engine. Crawl stays low after Finish. Each ongoing demonstration ramps Speed 25% to 100%, then shows advanced stride/cadence and controlled Finish. Recording duration does not limit the running command. These are geometric demonstrations; hardware remains unqualified.\n'))
    if 'upright' in order: info.write('\nUpright: experimental Sit, front feet back, supported push and rise onto flat rear lower legs. Assumed center of mass only; physical balance and torque unqualified.\n')
    selector=(ROOT/'tools/blender_motion_controls.py').read_text();exec(compile(selector,'blender_motion_controls.py','exec'),{'__name__':'__main__'})
    scene.use_preview_range=True;scene.frame_preview_start=old_end+1;scene.frame_preview_end=scene.frame_end
    if bpy.context.window:bpy.context.window.scene=scene
    scene.frame_set(old_end+61)
    return dict(scene=scene.name,chapters=len(chapters),new_start_frame=old_end+1,frame_end=scene.frame_end,objects=len(scene.objects),source_samples=len(fs)-len(order))

def refresh_run():
    """Replace only Run values, retaining every earlier chapter and key.

    The recording must retain its existing time grid. Saving and a verified
    rolling recovery are caller-owned, as for append().
    """
    scene=bpy.data.scenes['Motions - Current Geometry']
    chapters=json.loads(scene['ainekio_motion_chapters']);chapter=chapters[-1]
    assert chapter['command']=='run' and sum(c['command']=='run' for c in chapters)==1
    path=ROOT/chapter['source'];rows=json.loads(path.read_text())['samples']
    frames=np.array([chapter['start_frame']+30*r['time_s'] for r in rows]+[chapter['end_frame']],dtype=np.float32)
    assert scene.render.fps/scene.render.fps_base==30 and len(rows)==chapter['samples']
    assert abs(frames[-2]-chapter['source_end_frame'])<.002
    body=np.array([r['body_translation_world_mm'] for r in rows]+[rows[-1]['body_translation_world_mm']])
    euler=np.array([r['body_rotation_euler_xyz_rad'] for r in rows]+[rows[-1]['body_rotation_euler_xyz_rad']])
    joints=np.array([r['actuator_angles_rad'] for r in rows]+[rows[-1]['actuator_angles_rad']])
    pivot=Vector(json.loads((ROOT/'geometry.json').read_text())['continuous_walk']['body_rotation_pivot_mm'])
    locations=np.array([Vector(b)+pivot-Euler(tuple(e),'XYZ').to_matrix()@pivot for b,e in zip(body,euler)])
    channels=[(bpy.data.objects['ML | Body motion'],'location',i,locations[:,i]) for i in range(3)]
    channels += [(bpy.data.objects['ML | Body motion'],'rotation_euler',i,euler[:,i]) for i in range(3)]
    channels += [(bpy.data.objects['ML | Camera follow'],'location',i,body[:,i] if i<2 else np.zeros(len(body))) for i in range(3)]
    for i,leg in enumerate(['FL','FR','RL','RR']):
        channels += [(bpy.data.objects[f'ML | REFINED | {leg} | h alpha theta'],f'["{key}"]',0,np.rad2deg(joints[:,i,j])) for j,key in enumerate(['h_deg','alpha_deg','theta_deg'])]
    replacements=[]
    for obj,data_path,index,values in channels:
        curves=[f for l in obj.animation_data.action.layers for strip in l.strips for bag in strip.channelbags for f in bag.fcurves]
        curve=next(f for f in curves if f.data_path==data_path and f.array_index==index)
        keys=[k for k in curve.keyframe_points if k.co.x>=chapter['start_frame']]
        assert np.array_equal(np.array([k.co.x for k in keys],dtype=np.float32),frames),(obj.name,data_path,'time grid differs')
        replacements.append((curve,keys,values))
    for curve,keys,values in replacements:
        for key,value in zip(keys,values):key.co.y=float(value)
        curve.update()
    chapter['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    scene['ainekio_motion_chapters']=json.dumps(chapters)
    text=bpy.data.texts['MOTION LIBRARY - chapters.json'];text.clear();text.write(json.dumps(chapters,indent=2))
    scene.use_preview_range=True;scene.frame_preview_start=chapter['start_frame'];scene.frame_preview_end=chapter['end_frame']
    if bpy.context.window:
        bpy.context.window.scene=scene;bpy.context.window.view_layer=scene.view_layers['Motion playback']
    scene.frame_set(chapter['start_frame']+16*30)
    return dict(scene=scene.name,command='run',start_frame=chapter['start_frame'],end_frame=chapter['end_frame'],replaced_values=len(channels)*len(frames),source_sha256=chapter['source_sha256'])

if __name__=='__main__':print(json.dumps(append()))
