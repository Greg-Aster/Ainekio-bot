"""Refresh existing motion chapters without replacing model geometry.

Run in Blender after saving and verifying a rolling recovery. Caller owns saving.
"""
import bpy, hashlib, json, math
from pathlib import Path
import numpy as np
from mathutils import Euler, Vector

ROOT = Path(globals().get('MODEL_ROOT', Path(__file__).resolve().parents[1]))

def refresh(scene_name='Motions - Current Geometry', prefix='ML | '):
    scene = bpy.data.scenes[scene_name]
    previous = json.loads(scene['ainekio_motion_chapters'])
    assert previous and len({c['command'] for c in previous}) == len(previous)
    cfg = json.loads((ROOT/'geometry.json').read_text())
    profile = json.loads((ROOT/'servo_profile.json').read_text())
    frames, bodies, eulers, joints, chapters = [], [], [], [], []
    cursor = 1
    for old in previous:
        command = old['command']; path = ROOT/old['source']
        source = json.loads(path.read_text())
        if command == 'walk':
            d = source['columns']; t = np.array(d['time_s'])
            b = np.array(d['body']); e = np.array(d['body_euler'])
            q = np.array(d['q'])[:, [2,3,0,1]]; semantic = t[-1]
        else:
            rows = source['samples']; t = np.array([r['time_s'] for r in rows])
            b = np.array([r['body_translation_world_mm'] for r in rows])
            e = np.array([r['body_rotation_euler_xyz_rad'] for r in rows])
            q = np.array([r['actuator_angles_rad'] for r in rows])
            manifest = json.loads(path.with_name('manifest.json').read_text()) if path.with_name('manifest.json').exists() else {}
            semantic = manifest.get('semantic_end_seconds', t[-1])
        fs = cursor + t*30; end = math.ceil(fs[-1])+30
        frames.extend(fs); frames.append(end)
        for dest, values in [(bodies,b),(eulers,e),(joints,q)]:
            dest.extend(values); dest.append(values[-1])
        chapter = dict(old, start_frame=cursor, end_frame=end,
            source_end_frame=float(fs[-1]), semantic_end_frame=float(cursor+semantic*30),
            source_duration_s=float(t[-1]), samples=len(t),
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        chapters.append(chapter); cursor=end+1
    frames=np.array(frames); bodies=np.array(bodies); eulers=np.array(eulers); joints=np.array(joints)
    cuts={c['end_frame'] for c in chapters}; old_actions=[]
    def bake(obj, channels, fs=frames, constant=False):
        obj.animation_data_create(); assert not obj.animation_data.nla_tracks, obj.name
        old=obj.animation_data.action
        if old: old_actions.append(old)
        obj.animation_data.action=None
        for path,index,values in channels:
            obj.keyframe_insert(data_path=path,index=index,frame=float(fs[0]))
            action=obj.animation_data.action
            fc=next(f for l in action.layers for s in l.strips for bag in s.channelbags for f in bag.fcurves if f.data_path==path and f.array_index==max(index,0))
            fc.keyframe_points.clear(); fc.keyframe_points.add(len(fs))
            fc.keyframe_points.foreach_set('co',np.c_[fs,values].astype(np.float32).ravel())
            for key,frame in zip(fc.keyframe_points,fs): key.interpolation='CONSTANT' if constant or frame in cuts else 'LINEAR'
            fc.update()
        obj.animation_data.action.name=obj.name
    pivot=Vector(cfg['continuous_walk']['body_rotation_pivot_mm'])
    locations=np.array([Vector(b)+pivot-Euler(tuple(e),'XYZ').to_matrix()@pivot for b,e in zip(bodies,eulers)])
    bake(scene.objects[prefix+'Body motion'], [('location',i,locations[:,i]) for i in range(3)]+[('rotation_euler',i,eulers[:,i]) for i in range(3)])
    for i,leg in enumerate(['FL','FR','RL','RR']):
        bake(scene.objects[f'{prefix}REFINED | {leg} | h alpha theta'],[(f'["{key}"]',-1,np.rad2deg(joints[:,i,j])) for j,key in enumerate(['h_deg','alpha_deg','theta_deg'])])
    bake(scene.objects[prefix+'Camera follow'],[('location',i,bodies[:,i] if i<2 else np.zeros(len(bodies))) for i in range(3)])
    for marker in list(scene.timeline_markers): scene.timeline_markers.remove(marker)
    for i,item in enumerate(chapters):
        obj=scene.objects[prefix+'Title | '+item['command']]
        fs=np.array(sorted(set([1,item['start_frame'],item['end_frame']+1,chapters[-1]['end_frame']+1])))
        hidden=np.array([float(not item['start_frame']<=f<=item['end_frame']) for f in fs])
        bake(obj,[('hide_viewport',-1,hidden),('hide_render',-1,hidden)],fs,True)
        obj.data.body=f'{i+1:02d} / {len(chapters)}   '+item['label']
        scene.timeline_markers.new(item['label'],frame=item['start_frame'])
        if item.get('ongoing_native'):
            obj.data.body+='\nSpeed 25% > 100% > Stride 60%, Cadence 3x > Finish'
            for seconds,label in [(0,'Speed 25%'),(6,'Speed 100%'),(12,'Stride 60% / cadence 3x'),(17,'Finish')]:
                scene.timeline_markers.new(item['label']+' | '+label,frame=item['start_frame']+seconds*30)
        elif item['semantic_end_frame'] < item['source_end_frame']-1:
            scene.timeline_markers.new(item['label']+' / demo recovery or hold',frame=round(item['semantic_end_frame']))
    for old in set(old_actions):
        if old.users==0 and old.name.startswith(prefix): bpy.data.actions.remove(old)
    scene.frame_start=1; scene.frame_end=chapters[-1]['end_frame']; scene.use_preview_range=True
    scene.frame_preview_start=1; scene.frame_preview_end=scene.frame_end
    scene['ainekio_motion_chapters']=json.dumps(chapters); scene['geometry_id']=cfg['geometry_id']
    scene['servo_profile_id']=profile['profile_id']; scene['hardware_qualified']=False
    texts={
        'MOTION LIBRARY - chapters.json':json.dumps(chapters,indent=2),
        'MOTION LIBRARY - START HERE': 'Scene: Motions - Current Geometry\nSpace plays '+str(len(chapters))+' chapters; N > Ainekio selects a command.\nThe current servo profile is '+profile['profile_id']+'. The canonical model owns all baked trajectories.\nSit, Rest, Wave, Point, two-cycle Nod and forward-hands Bow retain their intended postures.\nOngoing Walk/Crawl chapters show forward, backward and both turn directions, Speed 25% to 100%, advanced stride/cadence and Finish.\nEach chapter has a one-second hold and a presentation cut. Cuts are not firmware transitions. Firmware coordinates entry from a known commanded calibrated pose.\nGeometry, face cache and editable modeling dependencies are preserved. Mesh checks and offline playback do not qualify actual shaft travel, load or full-body clearance.\n',
        'blender_motion_controls.py':(ROOT/'tools/blender_motion_controls.py').read_text(),
        'SERVO ASSEMBLY - READ FIRST':(ROOT/'SERVO_ASSEMBLY.md').read_text(),
    }
    for name,value in texts.items():
        if scene_name!='Motions - Current Geometry':
            if name=='blender_motion_controls.py':continue
            name='FIRMWARE PREVIEW - '+name
            value=value.replace('Scene: Motions - Current Geometry','Scene: '+scene_name).replace('; N > Ainekio selects a command','; timeline markers identify each command')
        text=bpy.data.texts.get(name) or bpy.data.texts.new(name); text.clear(); text.write(value)
    if not bpy.app.background and scene_name=='Motions - Current Geometry':
        exec(compile(texts['blender_motion_controls.py'],'blender_motion_controls.py','exec'),{'__name__':'__main__'})
    scene.frame_set(1)
    return dict(scene=scene.name,chapters=len(chapters),samples=len(frames)-len(chapters),frame_end=scene.frame_end,servo_profile_id=profile['profile_id'])

if __name__=='__main__': print(json.dumps(refresh()))
