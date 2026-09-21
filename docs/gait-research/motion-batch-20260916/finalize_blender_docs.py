"""Refresh only embedded handoff documents and preserve the live model on save."""
import bpy,json,time,traceback
from pathlib import Path
P=Path(__file__).resolve().parent
def finalize():
    try:
        assert Path(bpy.data.filepath)==P/'Ainekio-Motion-Library.blend',bpy.data.filepath
        scene=bpy.context.scene
        before=dict(filepath=bpy.data.filepath,frame=scene.frame_current,subframe=scene.frame_subframe,objects=len(bpy.data.objects),dirty=bpy.data.is_dirty)
        backup=P/'Before-Final-Documentation.blend'
        assert not backup.exists(),'Backup exists; inspect before rerunning.'
        bpy.ops.wm.save_as_mainfile(filepath=str(backup),copy=True,compress=True)
        index=json.loads((P/'motion-index.json').read_text())
        for m in index['commands']:
            for name in ['README.md','config.json','execution-contract.json']:
                label=m['command'].upper()+' '+name
                t=bpy.data.texts.get(label) or bpy.data.texts.new(label)
                t.clear();t.write((P/'commands'/m['command']/name).read_text())
        for name in ['README.md','motion-index.json','select_motion.py','validation-report.md','current-curve-source-review.json','resource-policy.md','cautious-render-status.json']:
            label='BATCH '+name;t=bpy.data.texts.get(label) or bpy.data.texts.new(label)
            t.clear();t.write((P/name).read_text())
        scene['Firmware handoff index']='/home/greggles/Ainekio/docs/MOTION_LIBRARY_12SERVO.md'
        scene['Geometry snapshot note']='Current front/display revisions retained. Earlier body-contact geometry is a research snapshot; visor checks deferred.'
        bpy.ops.wm.save_as_mainfile(filepath=str(P/'Ainekio-Motion-Library.blend'),compress=True)
        result=dict(saved=True,filepath=bpy.data.filepath,dirty=bpy.data.is_dirty,before=before,frame=scene.frame_current,objects=len(bpy.data.objects),time_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),backup=str(backup),scope='Embedded documentation and scene handoff metadata only; model and animation untouched.')
        (P/'final-blender-save.json').write_text(json.dumps(result,indent=2)+'\n')
    except Exception:
        (P/'final-blender-save.json').write_text(json.dumps(dict(saved=False,error=traceback.format_exc()),indent=2)+'\n')
    return None
bpy.app.timers.register(finalize,first_interval=0.5)
print('Scheduled documentation-only backup and final save.')
