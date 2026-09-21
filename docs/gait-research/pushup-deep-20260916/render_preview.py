"""Render the saved Pushup command in background Blender only."""
import bpy,sys,json,math
from pathlib import Path
from mathutils import Vector
P=Path(__file__).resolve().parent
assert bpy.app.background
scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_x=640;scene.render.resolution_y=540;scene.render.resolution_percentage=100
scene.display.shading.show_shadows=False;scene.display.shading.show_cavity=False
if 'FXAA' in {x.identifier for x in scene.display.bl_rna.properties['render_aa'].enum_items}:scene.display.render_aa='FXAA'
if 'PNG' in {x.identifier for x in scene.render.image_settings.bl_rna.properties['file_format'].enum_items}:scene.render.image_settings.file_format='PNG'
camera=scene.camera
try:camera.driver_remove('location',0)
except (TypeError,RuntimeError):pass
camera.location=(280.,350.,300.);camera.rotation_euler=(Vector((0.,0.,40.))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=430.
frames=P/'preview-frames';frames.mkdir(exist_ok=True)
start_index=int(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else 0
data=json.loads((P/'source.json').read_text());cfg=data['metadata']['configuration']
for i in range(start_index,87):
    frame=cfg['gait_start_frame']+scene.render.fps*(i/6)
    scene.frame_set(math.floor(frame),subframe=frame%1);scene.render.filepath=str(frames/f'{i:04}.png');bpy.ops.render.render(write_still=True)
scene.frame_set(cfg['gait_start_frame']+round(3.*scene.render.fps));scene.render.filepath=str(P/'pushup-preview.png');bpy.ops.render.render(write_still=True)
print('PUSHUP PREVIEW COMPLETE',flush=True)
