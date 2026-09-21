"""Load in Blender Text Editor, then select_motion('cute', play=True)."""
import bpy,json
from pathlib import Path
P=Path(__file__).resolve().parent if '__file__' in globals() else Path(bpy.context.scene['Motion index']).parent
MOTIONS=json.loads((P/'motion-index.json').read_text())['commands']
def select_motion(name,play=False,include_demo_recovery=False):
 name={'strech':'stretch'}.get(name.lower(),name.lower());m=next(x for x in MOTIONS if x['command']==name);s=bpy.context.scene
 if bpy.context.screen and bpy.context.screen.is_animation_playing:bpy.ops.screen.animation_cancel(restore_frame=False)
 s.use_preview_range=True;s.frame_preview_start=m['start_frame'];s.frame_preview_end=m['end_frame'] if include_demo_recovery else m['semantic_end_frame'];s.frame_set(m['start_frame'])
 if play:
  bpy.ops.screen.animation_play()
  end=s.frame_preview_end;file=bpy.data.filepath
  def finish():
   if bpy.data.filepath==file and bpy.context.screen and bpy.context.screen.is_animation_playing:bpy.ops.screen.animation_cancel(restore_frame=False);s.frame_set(end)
   return None
  bpy.app.timers.register(finish,first_interval=(end-m['start_frame'])/24+.05)
 return (s.frame_preview_start,s.frame_preview_end)
print('Commands:',', '.join(m['command'] for m in MOTIONS))
