"""Compare the existing model and earlier action samples without changing pose."""
import bpy,json,hashlib
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
before=json.loads((P/'preservation-before.json').read_text())
changed=[];missing=[];errors=[]
for name,h in before['meshes'].items():
    ob=bpy.data.objects.get(name)
    if ob is None:missing.append(name);continue
    vv=np.empty(len(ob.data.vertices)*3,dtype=np.float32);ob.data.vertices.foreach_get('co',vv)
    if hashlib.sha256(vv.tobytes()).hexdigest()!=h:changed.append(name)
for key,values in before['curves'].items():
    name,path,index=key.rsplit('|',2);ob=bpy.data.objects[name];ad=ob.animation_data
    fc=next(fc for layer in ad.action.layers for strip in layer.strips for fc in strip.channelbag(ad.action_slot).fcurves if fc.data_path==path and fc.array_index==int(index))
    errors.extend(abs(fc.evaluate(f)-v) for f,v in zip(before['frames'],values))
report=dict(model_meshes_compared=len(before['meshes']),changed_meshes=changed,missing_meshes=missing,
    prior_animation_curves=len(before['curves']),prior_sample_frames=before['frames'],maximum_prior_animation_difference=max(errors))
(P/'preservation-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
assert max(errors)<1e-6
