"""Apply a held twelve-servo pushup to the existing mechanism; preserve model meshes."""
import bpy,json,math
from mathutils import Euler
import numpy as np
from pathlib import Path
P=Path(__file__).resolve().parent
d=json.loads((P/'source.json').read_text());cfg=d['metadata']['configuration'];rows=d['samples']
rig=json.loads((P/'blender-rig.json').read_text());par=json.loads((P/'robot-gait-parameters.json').read_text())
scene=bpy.context.scene;command='pushup';body=bpy.data.objects[rig['body']]
assert d['validation']['research_angle_bounds_satisfied']
assert scene.render.fps==cfg['preview_fps'] and scene.render.fps_base==1.0
assert Path(bpy.data.filepath).name in ['Before-Deep-Pushup.blend','Ainekio-Nod.blend','Ainekio-Pushup.blend'], 'Open the preserved Pushup source first'
if bpy.context.screen and bpy.context.screen.is_animation_playing:bpy.ops.screen.animation_cancel(restore_frame=False)
times=np.array([r['time_s'] for r in rows]);frames=cfg['gait_start_frame']+times*scene.render.fps
exec(compile((P/'animate_curves.py').read_text(),str(P/'animate_curves.py'),'exec'))
positions=np.array([r['body_position_world_mm'] for r in rows]);rotations=np.array([r['body_rotation_euler_xyz_rad'] for r in rows])
angles=np.array([r['actuator_angles_rad'] for r in rows]);contacts=np.array([r['contact_world_mm'] for r in rows]);com=np.array([r['assumed_com_world_mm'] for r in rows])
for j in range(3):
    animate(body,'location',j,positions[:,j]);animate(body,'rotation_euler',j,rotations[:,j])
mode=np.array([0 if all(r['contact_active']) else 1+list(r['contact_active']).index(False) for r in rows])
animate(body,'["support_mode"]',-1,mode,constant=True)
for i,leg in enumerate(['FL','FR','RL','RR']):
    for j,(group,axis) in enumerate([('hip',0),('primary',2),('input',2)]):
        ob=bpy.data.objects[rig['controls'][leg][group]];animate(ob,'rotation_euler',axis,angles[:,i,j])
        ob['Research minimum degrees']=float(np.degrees(angles[:,i,j].min()));ob['Research maximum degrees']=float(np.degrees(angles[:,i,j].max()))
    marker=bpy.data.objects['CRAWL '+leg+' - active sole contact']
    for j in range(3):animate(marker,'location',j,contacts[:,i,j])
    path=bpy.data.objects['CRAWL '+leg+' - sole path'];old=path.data
    curve=bpy.data.curves.new('Pushup sole rolling '+leg,'CURVE');curve.dimensions='3D';curve.bevel_depth=old.bevel_depth
    for mat in old.materials:curve.materials.append(mat)
    pushups=contacts[::5,i].copy();pushups[:,2]+=.25;line=curve.splines.new('POLY');line.points.add(len(pushups)-1)
    for pushup,xyz in zip(line.points,pushups):pushup.co=(*xyz,1)
    path.data=curve
    ref=bpy.data.objects.get('CRAWL '+leg+' - shoulder vertical reference')
    if ref:
        l=par['legs'][leg];A=np.array(par['controller_from_CAD_rotation']);datum=np.array(par['controller_body_datum_CAD_xyz_mm']);H=np.array(l['hip_axis_point_xyz_mm']);O=np.array(l['pivots_xy_mm']['O']+[H[2]])
        origin=[]
        for n,row in enumerate(rows):
            h=angles[n,i,0];v=O-H;v=np.array([v[0],v[1]*math.cos(h)-v[2]*math.sin(h),v[1]*math.sin(h)+v[2]*math.cos(h)])
            R=np.array(Euler(tuple(rotations[n]),'XYZ').to_matrix())
            origin.append(positions[n]+R@A@(H+v-datum))
        origin=np.array(origin)
        for j in range(2):animate(ref,'location',j,origin[:,j])
        animate(ref,'location',2,np.zeros(len(rows)));animate(ref,'scale',2,origin[:,2])
        ref['Meaning']='World-vertical reference through Part023 pivot O during Pushup.'
    primary=bpy.data.objects[rig['controls'][leg]['primary']]
    animate(primary,'["Part023 angle from forward degrees"]',-1,[r['part023_OD_angle_from_forward_degrees'][i] for r in rows])
for name,count in [('CRAWL - assumed COM',3),('CRAWL - projected assumed COM',2)]:
    for j in range(count):animate(bpy.data.objects[name],'location',j,com[:,j])

for ob in scene.objects:
    if ob.name.startswith(('NOD -','POINT -','SWIM -','DANCE -','WAVE -','SIT -','REST -')) and ob.animation_data:
        for fc in ob.animation_data.drivers:
            if fc.data_path in ('hide_render','hide_viewport'):
                fc.driver.expression=f'({fc.driver.expression}) or frame >= {cfg["gait_start_frame"]}'
# The existing face mesh stays untouched. Display the original pushup bitmaps on a thin screen overlay.
collection=bpy.data.collections.get('PUSHUP - pushup display')
if collection is None:collection=bpy.data.collections.new('PUSHUP - pushup display');scene.collection.children.link(collection)
def material(name,color,emission=0):
    mat=bpy.data.materials.get(name) or bpy.data.materials.new(name);mat.diffuse_color=(*color,1);mat.use_nodes=True
    node=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED');node.inputs['Base Color'].default_value=(*color,1)
    node.inputs['Roughness'].default_value=.8
    if node.inputs.get('Emission Color'):node.inputs['Emission Color'].default_value=(*color,1);node.inputs['Emission Strength'].default_value=emission
    return mat
black=material('PUSHUP - screen black',(.002,.004,.008));cyan=material('PUSHUP - pushup pixels',(.02,.7,1.),1.2)
def screen_mesh(name,quads,mat,expression):
    ob=bpy.data.objects.get(name)
    if ob is None:
        mesh=bpy.data.meshes.new(name);mesh.from_pydata([v for quad in quads for v in quad],[],[tuple(range(4*i,4*i+4)) for i in range(len(quads))]);mesh.materials.append(mat)
        ob=bpy.data.objects.new(name,mesh);collection.objects.link(ob);ob.parent=body
    for path in ['hide_render','hide_viewport']:
        fc=ob.driver_add(path);fc.driver.type='SCRIPTED';fc.driver.expression=expression
    return ob
reference=json.loads((P/'body-and-face-reference.json').read_text());lo,hi=reference['face_regions']['Robot Face - Screen']['bounds'];x=hi[0]+.045;center=(lo[2]+hi[2])/2
quad=[(x,hi[1],hi[2]),(x,lo[1],hi[2]),(x,lo[1],lo[2]),(x,hi[1],lo[2])]
screen_mesh('PUSHUP - pushup screen',[quad],black,f'frame < {cfg["gait_start_frame"]}')
face_end=cfg['gait_start_frame']+d['validation']['motion_end_s']*scene.render.fps
for variant,face_index in [('pushup',0),('stand',0)]:
    payload=(P/f'faces/{variant}/{face_index}.bin').read_bytes();assert len(payload)==1024
    quads=[];pixel=.3
    for y in range(64):
        for col in range(128):
            if payload[y*16+col//8] & (0x80>>(col%8)):
                left=(64-col)*pixel;right=left-pixel;top=center+(32-y)*pixel;bottom=top-pixel
                quads.append([(x+.01,left,top),(x+.01,right,top),(x+.01,right,bottom),(x+.01,left,bottom)])
    expr=f'frame < {cfg["gait_start_frame"]} or frame >= {face_end}' if variant=='pushup' else f'frame < {face_end}'
    screen_mesh(f'PUSHUP - bitmap {variant} {face_index}',quads,cyan,expr)

scene.name=cfg['scene_name'];scene.frame_end=round(frames[-1]);scene.use_preview_range=True
scene.frame_preview_start=cfg['gait_start_frame'];scene.frame_preview_end=scene.frame_end
for marker in list(scene.timeline_markers):
    if marker.frame>=cfg['gait_start_frame']:scene.timeline_markers.remove(marker)
for phase in d['phases']:scene.timeline_markers.new(phase['kind'].upper(),frame=cfg['gait_start_frame']+round(phase['start']*scene.render.fps))
for key in ['Heading change degrees','Loop frames','Loop behavior','Loop world translation mm','Stride mm','Cycle seconds']:
    if key in scene:del scene[key]
scene['Gait reference ID']='pushup_deep_rear_fourbar_20260916';scene['Versioned data directory']=str(P);scene['Shoulder strategy']='Both rear legs crouch close to the floor before five coordinated front-leg presses.'
scene['Command']='pushup';scene['Face cue']='pushup once; stand on completion';scene['Completion behavior']=cfg['completion']
scene['Trajectory file']=str(P/'source.json');scene['Configuration file']=str(P/'config.json');scene['Current reference report']=str(P/'README.md')
scene['Research status']='Deep rear crouch; both front legs perform five grounded pushups. Hardware stops, collisions and physical loads unqualified.'
body['COM assumption']='Assumed at body datum; measured mass distribution unavailable.'
for name,text in [('CRAWL title','AINEKIO | PUSHUP'),('CRAWL status','DEEP REAR CROUCH | FRONT LEG PRESS'),('CRAWL scale','FIVE PUSHUPS | FOUR FOOT SUPPORT'),('CRAWL collision legend','RESEARCH POSE | HARDWARE UNQUALIFIED')]:
    if name in scene.objects:scene.objects[name].data.body=text
for name in ['config.json','README.md']:
    if (P/name).exists():text=bpy.data.texts.new('PUSHUP '+name);text.write((P/name).read_text())
# Reveal the command in an existing isolated view without changing its zoom or rotation.
if bpy.context.screen:
    for area in bpy.context.screen.areas:
        if area.type=='VIEW_3D' and area.spaces.active.local_view:
            for ob in scene.objects:
                if (ob.name.startswith('CRAWL') or ob.name.startswith('PUSHUP -')) and not ob.hide_render:
                    ob.local_view_set(area.spaces.active,True)
scene['Execution contract']=str(P/'execution-contract.json')
scene['Validation report']=str(P/'README.md')
scene['Collision validation']='Pushup: unverified'
scene['User visual review']='Pushup: awaiting owner review'
scene['Timeline']='Nod preserved at 2137-2485; deep Pushup appended from 2509'
if 'Point revision' in scene:del scene['Point revision']
scene.frame_set(cfg['gait_start_frame']+round((cfg['crouch_seconds']+cfg['half_pushup_seconds'])*scene.render.fps));bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=str(P/cfg['output_blend']),compress=True)
if globals().get('PLAY',True):
    scene.frame_set(cfg['gait_start_frame']);bpy.ops.screen.animation_play()
    target_file=str(P/cfg['output_blend']);end_frame=scene.frame_end
    def hold_pushup_preview():
        # A finite command demonstration: stop on the held pose, respecting a user's earlier pause.
        if bpy.data.filepath==target_file and bpy.context.screen and bpy.context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False);scene.frame_set(end_frame)
        return None
    bpy.app.timers.register(hold_pushup_preview,first_interval=d['validation']['duration_s']+.05)
print('PUSHUP APPLIED',bpy.data.filepath)
