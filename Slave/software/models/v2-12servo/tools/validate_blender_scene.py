"""Reopen proof: full joint/body key arrays and sampled evaluated linkage matrices."""
import bpy,json,math,hashlib,runpy,sys
from pathlib import Path
import numpy as np
from mathutils import Euler,Vector
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace',type=Path,default=Path('/home/greggles/blender-5.0.0-linux-x64/variable-gait'))
parser.add_argument('--report',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
ROOT=Path(__file__).resolve().parents[1];WS=args.workspace;report_path=args.report
cfg=json.loads((ROOT/'geometry.json').read_text());p=cfg['parameters'];pivot=np.array(cfg['continuous_walk']['body_rotation_pivot_mm'])
limits=runpy.run_path(str(ROOT/'tools/mechanical_limits.py'))['Limits'](ROOT)
def curves(obj):return [f for l in obj.animation_data.action.layers for s in l.strips for bag in s.channelbags for f in bag.fcurves]
def curve(obj,path,index):return next(f for f in curves(obj) if f.data_path==path and f.array_index==max(index,0))
def check(obj,path,index,fs,values):
    f=curve(obj,path,index);a=np.empty(len(f.keyframe_points)*2,dtype=np.float32);f.keyframe_points.foreach_get('co',a);a=a.reshape(-1,2)
    expected=np.c_[fs,values].astype(np.float32);assert a.shape==expected.shape,(obj.name,a.shape,expected.shape)
    assert np.array_equal(a[:,0],expected[:,0]) and np.max(abs(a[:,1]-expected[:,1]))<.0002,(obj.name,path,float(np.max(abs(a-expected))))
    assert all(k.interpolation==('CONSTANT' if float(k.co.x) in cuts else 'LINEAR') for k in f.keyframe_points),(obj.name,path,'interpolation')
    return len(a)
def rotation(axis,a):
    c,s=math.cos(a),math.sin(a)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]]) if axis=='x' else np.array([[c,0,s],[0,1,0],[-s,0,c]])
def expected(leg,q,body,e):
    alpha=p['alpha_neutral']+q[1];theta=p['new_theta_neutral']+q[2]
    D=np.array(p['O'])+p['primary_length']*np.array([math.cos(alpha),math.sin(alpha)])
    P=np.array(p['C_new'])+p['input_length']*np.array([math.cos(theta),math.sin(theta)])
    v=P-D;d=np.linalg.norm(v);b=p['pickup_length'];L=p['rod_length'];a=(b*b-L*L+d*d)/(2*d);height=math.sqrt(b*b-a*a)
    E=D+(a*v+p['assembly_branch']*height*np.array([-v[1],v[0]]))/d
    beta=math.atan2(E[1]-D[1],E[0]-D[0]);g=cfg['legs'][leg];S=np.array(g['shoulder_world']);M=np.array(g['mechanism_local'])
    R=S[:3,:3]@rotation('x',q[0]);T=S[:3,3]+R@M[:3,3];R=R@M[:3,:3]
    B=np.array(Euler(tuple(e),'XYZ').to_matrix());F=B@R@rotation('y',-(beta-p['beta_neutral']));T=body+pivot+B@(T+R@np.array([D[0],0,D[1]])-pivot)
    return F,T,height
report=dict(file=bpy.data.filepath,servo_profile_id=limits.profile['profile_id'],hardware_qualified=False,modeled_envelope_conflicts=[],key_values_checked=0,evaluated_poses=0,max_foot_position_error_mm=0.,max_foot_rotation_error=0.,minimum_evaluated_sole_z_mm=1e9,chapters=[])
for name,prefix,legs in [('Gait - Stride and Rate','VG | ',cfg['leg_order']),('Motions - Current Geometry','ML | ',['FL','FR','RL','RR'])]:
    scene=bpy.data.scenes[name];bpy.context.window.scene=scene
    if prefix=='VG | ':
        bpy.context.window.view_layer=scene.view_layers['Gait playback'];d=dict(np.load(WS/'gait-data.npz'));fs=1+d['time_s']*scene.render.fps/scene.render.fps_base;b=d['body'];e=d['body_euler'];q=d['q'];cuts=set();groups=[dict(command='stride_rate_demo',frames=fs)]
    else:
        bpy.context.window.view_layer=scene.view_layers['Motion playback'];fs=[];b=[];e=[];q=[];groups=[];chapters=json.loads(scene['ainekio_motion_chapters']);assert len(chapters)>=39 and len({c['command'] for c in chapters})==len(chapters);cuts={c['end_frame'] for c in chapters}
        for c in chapters:
            path=ROOT/c['source'];d=json.loads(path.read_text())
            if c['command']=='walk':
                x=d['columns'];t=np.array(x['time_s']);bs=np.array(x['body']);es=np.array(x['body_euler']);qs=np.array(x['q'])[:,[2,3,0,1]]
            else:
                x=d['samples'];t=np.array([r['time_s'] for r in x]);bs=np.array([r['body_translation_world_mm'] for r in x]);es=np.array([r['body_rotation_euler_xyz_rad'] for r in x]);qs=np.array([r['actuator_angles_rad'] for r in x])
            f=c['start_frame']+30*t;fs.extend(f);fs.append(c['end_frame'])
            for dest,a in [(b,bs),(e,es),(q,qs)]:dest.extend(a);dest.append(a[-1])
            groups.append(dict(command=c['command'],frames=f,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source=c['source']))
        fs=np.array(fs);b=np.array(b);e=np.array(e);q=np.array(q)
    for i,leg in enumerate(legs):
        rig=bpy.data.objects[prefix+'REFINED | '+leg+' | h alpha theta']
        for j,key in enumerate(['h_deg','alpha_deg','theta_deg']):report['key_values_checked']+=check(rig,f'["{key}"]',-1,fs,np.rad2deg(q[:,i,j]))
    root=bpy.data.objects[prefix+'Body motion'];locations=np.array([Vector(x)+Vector(pivot)-Euler(tuple(y),'XYZ').to_matrix()@Vector(pivot) for x,y in zip(b,e)])
    for i in range(3):
        report['key_values_checked']+=check(root,'location',i,fs,locations[:,i]);report['key_values_checked']+=check(root,'rotation_euler',i,fs,e[:,i])
    for group in groups:
        f=group['frames'];indices=np.unique(np.linspace(0,len(f)-1,17,dtype=int));samples=list(f[indices]);samples.extend((f[indices[:-1]]+f[np.minimum(indices[:-1]+1,len(f)-1)])/2)
        group_min=1e9;poserr=0.
        for frame in samples:
            scene.frame_set(int(frame),subframe=float(frame-int(frame)));dg=bpy.context.evaluated_depsgraph_get()
            actual_root=root.evaluated_get(dg);euler=np.array(actual_root.rotation_euler);B=np.array(Euler(tuple(euler),'XYZ').to_matrix());body=np.array(actual_root.location)-pivot+B@pivot
            for leg in legs:
                rig=bpy.data.objects[prefix+'REFINED | '+leg+' | h alpha theta'];angles=np.deg2rad([rig[k] for k in ['h_deg','alpha_deg','theta_deg']])
                if not limits.allowed_degrees(np.rad2deg(angles),tolerance=0.002):report['modeled_envelope_conflicts'].append(dict(command=group['command'],leg=leg,frame=frame,q_deg=np.rad2deg(angles).tolist()))
                R,T,height=expected(leg,angles,body,euler);foot=bpy.data.objects[prefix+'REFINED | '+leg+' | foot'].evaluated_get(dg);matrix=np.array(foot.matrix_world)
                err=float(np.max(abs(T-matrix[:3,3])));poserr=max(poserr,err);report['max_foot_position_error_mm']=max(report['max_foot_position_error_mm'],err);report['max_foot_rotation_error']=max(report['max_foot_rotation_error'],float(np.max(abs(R-matrix[:3,:3]))))
                for key in ['2','10','11','12']:
                    obj=bpy.data.objects[prefix+cfg['legs'][leg]['objects'][key]].evaluated_get(dg);coords=np.empty(len(obj.data.vertices)*3,dtype=np.float32);obj.data.vertices.foreach_get('co',coords);mat=np.array(obj.matrix_world);z=float((coords.reshape(-1,3)@mat[2,:3]+mat[2,3]).min());group_min=min(group_min,z)
            report['evaluated_poses']+=1
        report['minimum_evaluated_sole_z_mm']=min(report['minimum_evaluated_sole_z_mm'],group_min)
        report['chapters'].append({k:v for k,v in group.items() if k!='frames'}|dict(evaluated_poses=len(samples),minimum_sole_z_mm=group_min,max_foot_position_error_mm=poserr))
        print('VERIFIED',prefix,group['command'],len(samples),group_min,poserr,flush=True)
assert report['max_foot_position_error_mm']<.005,report['max_foot_position_error_mm']
assert report['max_foot_rotation_error']<.0001,report['max_foot_rotation_error']
assert report['minimum_evaluated_sole_z_mm']>-.03,report['minimum_evaluated_sole_z_mm']
report['passed']=True;report_path.write_text(json.dumps(report,indent=2));print('VERIFICATION_PASSED',report['key_values_checked'],report['evaluated_poses'],flush=True)
