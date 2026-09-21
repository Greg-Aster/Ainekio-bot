"""Replace only walking actions/diagnostics in the active live robot scene.

Run through Blender MCP or Blender's Text Editor. Original model transforms,
meshes, passive-link drivers, and frames 1-505 are retained.
"""
import bpy,json,math
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
command=globals().get('COMMAND_NAME','turn_left_180')
trajectory_name=f'commands/{command}/source.json'
d=json.loads((P/trajectory_name).read_text());cfg=d['metadata']['configuration']
reach_display=cfg.get('gait_family')=='continuous_wave_reach_display'
whole_body=cfg.get('gait_family')=='whole_body_wave'
looping=cfg.get('playback_mode')=='periodic_walk'
config_name=cfg.get('configuration_file','whole-body-config.json' if whole_body else ('maximum-config.json' if reach_display else 'selected-config.json'))
rig=json.loads((P/'blender-rig.json').read_text())
scene=bpy.context.scene
assert rig['body'] in scene.objects,'Select the current gait scene first'
assert d['validation']['research_angle_bounds_satisfied']
if cfg.get('part023_forward_limit_degrees') is not None:assert d['validation']['part023_forward_limit_satisfied']
if cfg.get('support_margin_enforced',True):assert d['validation']['minimum_support_margin_mm']>=cfg['support_margin_mm']-.1
if bpy.context.screen.is_animation_playing:bpy.ops.screen.animation_cancel(restore_frame=False)
times=np.array([r['time_s'] for r in d['samples']]);frames=cfg['gait_start_frame']+times*scene.render.fps
copied=set()
def animate(ob,path,index,values,constant=False):
    if ob.name not in copied:
        if ob.animation_data and ob.animation_data.action:
            old=ob.animation_data.action;old.use_fake_user=True
            ob.animation_data.action=old.copy();ob.animation_data.action.name=command+' | '+ob.name
            ob.animation_data.action_slot=ob.animation_data.action.slots[0]
        copied.add(ob.name)
    ob.keyframe_insert(data_path=path,index=index,frame=frames[0])
    ad=ob.animation_data;fc=next(f for f in ad.action.layers[0].strips[0].channelbag(ad.action_slot).fcurves if f.data_path==path and f.array_index==(0 if index<0 else index))
    values=np.array(values,float);delta=np.diff(values)/np.diff(times);deriv=np.zeros(len(times))
    same=delta[:-1]*delta[1:]>0;middle=np.zeros(len(times)-2)
    middle[same]=2*delta[:-1][same]*delta[1:][same]/(delta[:-1][same]+delta[1:][same]);deriv[1:-1]=middle
    if looping and delta[0]*delta[-1]>0:
        deriv[0]=deriv[-1]=2*delta[0]*delta[-1]/(delta[0]+delta[-1])
    for modifier in list(fc.modifiers):
        if modifier.type=='CYCLES':fc.modifiers.remove(modifier)
    fc.keyframe_points.clear();fc.keyframe_points.add(len(frames))
    fc.keyframe_points.foreach_set('co',np.column_stack([frames,values]).ravel())
    dt=1/cfg['sample_hz'];df=scene.render.fps*dt
    for i,k in enumerate(fc.keyframe_points):
        k.interpolation='CONSTANT' if constant else 'BEZIER'
        if not constant:
            k.handle_left_type='FREE';k.handle_right_type='FREE'
            k.handle_left=(frames[i]-df/3,values[i]-deriv[i]*dt/3)
            k.handle_right=(frames[i]+df/3,values[i]+deriv[i]*dt/3)
    fc.update()
    if looping:
        modifier=fc.modifiers.new('CYCLES');modifier.mode_before='NONE'
        modifier.mode_after='REPEAT_OFFSET' if abs(values[-1]-values[0])>1e-7 else 'REPEAT'
rows=d['samples'];q=np.array([r['actuator_angles_rad'] for r in rows]);body=bpy.data.objects[rig['body']]
positions=np.array([r['body_position_world_mm'] for r in rows])
for j in range(3):animate(body,'location',j,positions[:,j])
yaw=np.array([r['body_yaw_world_rad'] for r in rows])
assert body.rotation_mode=='XYZ'
for j in range(3):animate(body,'rotation_euler',j,yaw if j==2 else np.zeros(len(rows)))
for key in ['Loop behavior','Loop frames','Loop world translation mm']:
    if key in scene:del scene[key]
for i,leg in enumerate(['FL','FR','RL','RR']):
    for j,(group,axis) in enumerate([('hip',0),('primary',2),('input',2)]):
        ob=bpy.data.objects[rig['controls'][leg][group]];animate(ob,'rotation_euler',axis,q[:,i,j])
        ob['Research minimum degrees']=float(np.degrees(q[:,i,j].min()))
        ob['Research maximum degrees']=float(np.degrees(q[:,i,j].max()))
contacts=np.array([r['contact_world_mm'] for r in rows])
for i,leg in enumerate(['FL','FR','RL','RR']):
    marker=bpy.data.objects['CRAWL '+leg+' - active sole contact']
    for j in range(3):animate(marker,'location',j,contacts[:,i,j])
    path=bpy.data.objects['CRAWL '+leg+' - sole path'];old=path.data
    curve=bpy.data.curves.new('Extended sole path '+leg,'CURVE');curve.dimensions='3D'
    curve.bevel_depth=old.bevel_depth;curve.bevel_resolution=old.bevel_resolution
    for m in old.materials:curve.materials.append(m)
    points=contacts[::5,i].copy()
    if looping:
        points=np.concatenate([points[:-1]+[n*cfg['stride_mm'],0,0] for n in range(cfg['preview_cycles'])]+[points[-1:]+[(cfg['preview_cycles']-1)*cfg['stride_mm'],0,0]])
    points[:,2]+=.25
    spl=curve.splines.new('POLY');spl.points.add(len(points)-1)
    for point,xyz in zip(spl.points,points):point.co=(*xyz,1)
    path.data=curve
mode=np.array([0 if all(r['contact_active']) else 1+list(r['contact_active']).index(False) for r in rows])
animate(body,'["support_mode"]',-1,mode,constant=True)
com=np.array([r['assumed_com_world_mm'] for r in rows])
for name,count in [('CRAWL - assumed COM',3),('CRAWL - projected assumed COM',2)]:
    for j in range(count):animate(bpy.data.objects[name],'location',j,com[:,j])
if whole_body:
    par=json.loads((P/'robot-gait-parameters.json').read_text())
    transform=np.array(par['controller_from_CAD_rotation'],float);datum=np.array(par['controller_body_datum_CAD_xyz_mm'])
    collection=bpy.data.collections.get('Whole body - vertical references')
    if collection is None:
        collection=bpy.data.collections.new('Whole body - vertical references');scene.collection.children.link(collection)
    mat=bpy.data.materials.get('Whole body - cyan vertical reference')
    if mat is None:mat=bpy.data.materials.new('Whole body - cyan vertical reference')
    mat.diffuse_color=(.12,.72,1.,1.)
    if mat.use_nodes:
        shader=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if shader:shader.inputs['Base Color'].default_value=(.12,.72,1.,1.)
    feet=np.array([r['foot_bolt_world_mm'] for r in rows])
    for i,leg in enumerate(['FL','FR','RL','RR']):
        hip=transform@(np.array(par['legs'][leg]['hip_axis_point_xyz_mm'])-datum)
        name='CRAWL '+leg+' - shoulder vertical reference'
        ob=bpy.data.objects.get(name)
        if ob is None:
            curve=bpy.data.curves.new(name,'CURVE');curve.dimensions='3D';curve.bevel_depth=.22
            line=curve.splines.new('POLY');line.points.add(1);line.points[0].co=(0,0,0,1);line.points[1].co=(0,0,1,1)
            curve.materials.append(mat);ob=bpy.data.objects.new(name,curve);collection.objects.link(ob)
        ob.data.bevel_depth=.38
        ob.show_in_front=True;ob.hide_render=False
        ob['Meaning']='Side-view shoulder vertical, drawn in this foot plane. Foot behind this line has negative fore-aft pitch. Not a servo angle.'
        animate(ob,'location',0,positions[:,0]+hip[0]);animate(ob,'location',1,feet[:,i,1])
        animate(ob,'scale',2,positions[:,2]+hip[2])
        if cfg.get('vertical_reference_joint')=='Part023_O':
            par_leg=par['legs'][leg];origin=par_leg['pivots_xy_mm']['O'];hip_cad=par_leg['hip_axis_point_xyz_mm']
            animate(ob,'location',0,positions[:,0]+origin[0]-datum[0])
            animate(ob,'scale',2,positions[:,2]-(hip_cad[1]-datum[1])-(origin[1]-hip_cad[1])*np.cos(q[:,i,0]))
            ob['Meaning']='Part023 carrier pivot O vertical in side view. O-D must remain vertical or tilt rearward: angle from forward at least 90 degrees.'
            primary=bpy.data.objects[rig['controls'][leg]['primary']]
            primary['Part023 angle from forward degrees']=0.
            animate(primary,'["Part023 angle from forward degrees"]',-1,[r['part023_OD_angle_from_forward_degrees'][i] for r in rows])
        # Place the side-view vertical in the yawed body frame, at the foot's lateral coordinate.
        foot_local_y=-(feet[:,i,0]-positions[:,0])*np.sin(yaw)+(feet[:,i,1]-positions[:,1])*np.cos(yaw)
        reference_x=(par['legs'][leg]['pivots_xy_mm']['O'][0]-datum[0]) if cfg.get('vertical_reference_joint')=='Part023_O' else hip[0]
        animate(ob,'location',0,positions[:,0]+reference_x*np.cos(yaw)-foot_local_y*np.sin(yaw))
        animate(ob,'location',1,positions[:,1]+reference_x*np.sin(yaw)+foot_local_y*np.cos(yaw))
        control=bpy.data.objects[rig['controls'][leg]['hip']]
        control['Foot pitch from vertical degrees']=0.
        animate(control,'["Foot pitch from vertical degrees"]',-1,[r['hip_to_foot_pitch_from_down_vertical_degrees'][i] for r in rows])
def follow_x(ob,offset):
    fc=ob.driver_add('location',0);fc.keyframe_points.clear()
    for m in list(fc.modifiers):fc.modifiers.remove(m)
    m=fc.modifiers.new('GENERATOR');m.poly_order=1;m.coefficients=(0.,1.)
    dr=fc.driver;dr.type='SCRIPTED'
    for v in list(dr.variables):dr.variables.remove(v)
    v=dr.variables.new();v.name='forward';v.type='SINGLE_PROP';v.targets[0].id=body;v.targets[0].data_path='location[0]'
    dr.expression=f'{offset}+forward'
follow_x(scene.camera,315.)
for name in ['CRAWL title','CRAWL status','CRAWL collision legend','CRAWL scale']:
    if name in scene.objects:follow_x(scene.objects[name],30.)
scene.objects['CRAWL title'].data.body='AINEKIO | '+cfg.get('display_label','EXTENDED STRIDE CRAWL')
cycle=cfg['cycle_seconds'] if 'cycle_seconds' in cfg else 4*(cfg['shift_seconds']+cfg['swing_seconds'])
gait_id=cfg.get('gait_id',('whole_body_' if whole_body else ('reach_' if reach_display else 'crawl_'))+f'{cfg["stride_mm"]:03g}mm_{cycle:g}s')
scene.objects['CRAWL status'].data.body=f'{cfg["stride_mm"]:g} mm STRIDE | {cycle:g} s CYCLE | {cfg["stride_mm"]/cycle:g} mm/s'
scene.objects['CRAWL scale'].data.body=f'{cfg["swing_clearance_mm"]:g} mm sole lift | research motion, loads unmeasured'
if 'CRAWL collision legend' in scene.objects:scene.objects['CRAWL collision legend'].data.body='REACH DISPLAY | BALANCE UNQUALIFIED' if reach_display else 'EXISTING MOUNT INTERFERENCE REMAINS'
if whole_body:
    scene.objects['CRAWL collision legend'].data.body='WHOLE BODY RESEARCH | BALANCE UNQUALIFIED'
    scene.objects['CRAWL scale'].data.body=f'BODY HEIGHT {cfg["body_height_mm"]:g} +/- {cfg["body_bob_mm"]:g} mm | SWAY +/- {cfg["body_sway_mm"]:g} mm'
floor=scene.objects.get('CRAWL - ground Z=0')
if floor:
    for v in floor.data.vertices:
        if v.co.x>0:v.co.x=cfg.get('preview_cycles',cfg['cycles'])*cfg['stride_mm']+240
for marker in list(scene.timeline_markers):
    if marker.frame>=cfg['gait_start_frame']:scene.timeline_markers.remove(marker)
scene.timeline_markers.new(command.upper(),frame=cfg['gait_start_frame'])
for phase in d['phases']:scene.timeline_markers.new(phase['kind'],frame=cfg['gait_start_frame']+round(phase['start']*scene.render.fps))
scene.name='AINEKIO - Maximum Stride Display' if reach_display else 'AINEKIO - Extended Stride Crawl';rig['research_scene']=scene.name
if whole_body:scene.name='AINEKIO - Whole Body Stride';rig['research_scene']=scene.name
if cfg.get('scene_name'):scene.name=cfg['scene_name'];rig['research_scene']=scene.name
scene.frame_end=round(frames[-1]);scene.use_preview_range=True
if looping:scene.frame_end=cfg['gait_start_frame']+round(cfg['cycle_seconds']*scene.render.fps*cfg['preview_cycles'])-1
scene.frame_preview_start=cfg['gait_start_frame'];scene.frame_preview_end=scene.frame_end
if 'FRAME_DROP' in {i.identifier for i in scene.bl_rna.properties['sync_mode'].enum_items}:scene.sync_mode='FRAME_DROP'
scene['Research status']='Extended stride animation; measured geometric joint envelope used. Existing mount interference, loads and physical energy efficiency remain unverified.'
if reach_display:scene['Research status']='MAXIMUM MECHANISM REACH DISPLAY. COM leaves the support polygon. Balance and physical walking are not qualified; existing structural interference remains.'
if whole_body:scene['Research status']='Whole-body upright stride with active shoulders and measured four-bar geometry. Combined-pose angle bounds are provisional; balance, collisions and physical capability are not qualified.'
scene['Stride mm']=cfg['stride_mm'];scene['Cycle seconds']=cycle
scene['Configuration file']=str(P/config_name)
scene['Trajectory file']=str(P/trajectory_name)
scene['Gait reference ID']=gait_id
scene['Versioned data directory']=str(P/'commands'/command)
if looping:
    scene['Loop behavior']='Native repeating joint curves; X translation accumulates by the stride each cycle. No standing or stopping phase. Timeline wrap rewinds world position.'
    scene['Loop frames']=round(cfg['cycle_seconds']*scene.render.fps)
    scene['Loop world translation mm']=[cfg['stride_mm'],0.,0.]
scene['Shoulder strategy']=cfg.get('shoulder_strategy','Shoulders follow body shifts through four-bar IK.')
scene['Current reference report']=str(P/cfg.get('reference_report','WHOLE_BODY_STRIDE.md' if whole_body else 'VALIDATION_REPORT.md'))
scene['Combined travel qualification']=cfg.get('angle_bounds_note','Geometric research only; hardware limits unverified.')
if 'steady_stance_hip_foot_pitch_min_degrees' in d['validation']:
    scene['Planted leg pitch minimum degrees CAD FL FR RL RR']=d['validation']['steady_stance_hip_foot_pitch_min_degrees']
body['COM assumption']='Assumed body datum; balance unqualified for maximum reach display.' if reach_display else 'Assumed body datum; 3 mm research margin. Not a measured dynamic stability result.'
if whole_body:body['COM assumption']='Assumed body datum; body shifts are animated but static balance is not qualified.'
for filename in dict.fromkeys([config_name,'README.md','STRIDE_CATALOG.md','HARDWARE_GAIT_HANDOFF.md','VALIDATION_REPORT.md','WHOLE_BODY_STRIDE.md',cfg.get('reference_report','VALIDATION_REPORT.md')]):
    if (P/filename).exists():
        text=bpy.data.texts.new('EXTENDED '+filename);text.write((P/filename).read_text())
scene.objects['CRAWL status'].data.body=f'{abs(cfg["yaw_degrees"]):g} DEGREES {cfg["direction"].upper()} | {d["validation"]["duration_s"]:g} s | {cfg["turn_cycles"]} TURN STEPS'
scene.objects['CRAWL scale'].data.body=f'{cfg["swing_clearance_mm"]:g} mm sole lift | {cfg["body_height_mm"]:g} mm body height'
scene.objects['CRAWL collision legend'].data.body='TURN RESEARCH | MASS / FRICTION / LOADS UNQUALIFIED'
scene['Research status']=f'{command}: twelve-servo geometric joint data. Calibration, measured balance, friction and collisions are unqualified.'
scene['Command']=command
scene['Heading change degrees']=cfg['yaw_degrees']
start_time=d['validation']['turn_time_range_s'][0]
scene.frame_set(cfg['gait_start_frame']+round(start_time*scene.render.fps))
bpy.context.view_layer.update()
# Control mapping is unchanged; retain the common rig map.
bpy.ops.wm.save_as_mainfile(filepath=str(P/cfg['output_blend']),compress=True)
(P/'commands'/command/'applied-gait.json').write_text(json.dumps(dict(gait_id=gait_id,blend_file=bpy.data.filepath,scene=scene.name,stride_mm=cfg['stride_mm'],cycle_seconds=cycle,trajectory_file=trajectory_name,versioned_data_directory=str(P/'commands'/command),command=command,heading_change_degrees=cfg['yaw_degrees'],shoulder_strategy=cfg.get('shoulder_strategy'),hardware_ready=False),indent=2))
if globals().get('PLAY',True):bpy.ops.screen.animation_play()
print(command,'APPLIED',d['validation']['duration_s'],'seconds',scene.frame_end,bpy.data.filepath)
