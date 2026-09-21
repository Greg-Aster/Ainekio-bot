"""Background-only, resumable preview renderer; bounded frames per process."""
import bpy,json,sys,math,os
from pathlib import Path
from mathutils import Vector
P=Path(__file__).resolve().parent
assert bpy.app.background
index=json.loads((P/'motion-index.json').read_text());items=index['commands']
if '--' in sys.argv:
 names=sys.argv[sys.argv.index('--')+1:];items=[m for m in items if m['command'] in names]
# Rendering needs assigned actions only. Drop unused historical action copies in
# this disposable process; never save these cleanup changes to the working model.
used=set()
for ob in bpy.data.objects:
 ad=ob.animation_data
 if ad:
  if ad.action:used.add(ad.action)
  for track in ad.nla_tracks:
   for strip in track.strips:
    if strip.action:used.add(strip.action)
for act in list(bpy.data.actions):
 if act not in used:bpy.data.actions.remove(act)
s=bpy.context.scene;s.render.engine='BLENDER_WORKBENCH';s.render.resolution_x=480;s.render.resolution_y=400;s.render.resolution_percentage=100;s.display.shading.show_shadows=False;s.display.shading.show_cavity=False
choices={v.identifier for v in s.display.bl_rna.properties['render_aa'].enum_items}
for mode in ['OFF','FXAA']:
 if mode in choices:s.display.render_aa=mode;break
s.render.image_settings.file_format='PNG';camera=s.camera
try:camera.driver_remove('location',0)
except (TypeError,RuntimeError):pass
camera.location=(280.,350.,300.);camera.rotation_euler=(Vector((0.,0.,40.))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=430.
def valid_png(path):
 try:
  with path.open('rb') as f:
   start=f.read(8);f.seek(-12,2);end=f.read(12)
  return start==b'\x89PNG\r\n\x1a\n' and end==b'\x00\x00\x00\x00IEND\xaeB`\x82'
 except (OSError,ValueError):return False

def render():
 budget=int(os.environ.get('AINEKIO_MAX_RENDER_FRAMES','12'));count=0
 for m in items:
  folder=P/'commands'/m['command'];frames=folder/'preview-frames';frames.mkdir(exist_ok=True)
  targets=[(m['start_frame']+4*j,frames/f'{j:04}.png') for j in range(math.ceil(m['duration_s']*6))]
  targets += [(f,folder/f'pose-{j+1}.png') for j,f in enumerate(m['review_frames'])]
  for frame,path in targets:
   if valid_png(path):continue
   if count>=budget:return count
   s.frame_set(math.floor(frame),subframe=frame%1)
   temp=path.with_name(path.stem+'.partial.png');s.render.filepath=str(temp);bpy.ops.render.render(write_still=True)
   assert valid_png(temp),str(temp)
   temp.replace(path);count+=1;print('COMMITTED',path,flush=True)
  print('PREVIEW COMPLETE',m['command'],flush=True)
 return count
print('CHUNK COMPLETE',render(),flush=True)
