"""Read-only comparison of current rig animation curves to every exported sample."""
import bpy,json,hashlib,math
from pathlib import Path
P=Path(__file__).resolve().parent
assert bpy.data.filepath==str(P/'Ainekio-Motion-Library.blend')
index=json.loads((P/'motion-index.json').read_text());rig=json.loads((P/'commands/cute/blender-rig.json').read_text());channels=[]
def curve(name,path,index):
 ad=bpy.data.objects[name].animation_data
 return next(f for layer in ad.action.layers for strip in layer.strips for f in strip.channelbag(ad.action_slot).fcurves if f.data_path==path and f.array_index==index)
for leg in ['FL','FR','RL','RR']:
 for group,axis in [('hip',0),('primary',2),('input',2)]:channels.append(curve(rig['controls'][leg][group],'rotation_euler',axis))
body_pos=[curve(rig['body'],'location',a) for a in range(3)];body_rot=[curve(rig['body'],'rotation_euler',a) for a in range(3)];reports=[]
for m in index['commands']:
 source=P/'commands'/m['command']/'source.json';raw=source.read_bytes();d=json.loads(raw);max_q=max_p=max_r=0.
 for row in d['samples']:
  frame=m['start_frame']+24*row['time_s'];q=[a for leg in row['actuator_angles_rad'] for a in leg]
  max_q=max(max_q,max(abs(fc.evaluate(frame)-v) for fc,v in zip(channels,q)))
  max_p=max(max_p,max(abs(fc.evaluate(frame)-v) for fc,v in zip(body_pos,row['body_position_world_mm'])))
  max_r=max(max_r,max(abs(fc.evaluate(frame)-v) for fc,v in zip(body_rot,row['body_rotation_euler_xyz_rad'])))
 reports.append(dict(command=m['command'],samples=len(d['samples']),source_sha256=hashlib.sha256(raw).hexdigest(),maximum_actuator_error_degrees=math.degrees(max_q),maximum_body_position_error_mm=max_p,maximum_body_euler_error_degrees=math.degrees(max_r),passed=max_q<1e-4 and max_p<.01 and max_r<1e-4))
result=dict(file=bpy.data.filepath,commands=reports,passed=all(r['passed'] for r in reports),scope='Every recorded actuator/body source sample compared to its Blender animation curve. No geometry or pose changed.')
(P/'current-curve-source-review.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
assert result['passed']
