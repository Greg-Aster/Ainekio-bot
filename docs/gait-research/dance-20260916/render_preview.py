"""Render the saved Dance command in background Blender only."""
import bpy
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
camera.location=(280.,350.,200.);camera.rotation_euler=(Vector((0.,25.,65.))-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=350.
frames=P/'preview-frames';frames.mkdir(exist_ok=True)
for i in range(100):
    scene.frame_set(937+i*3);scene.render.filepath=str(frames/f'{i:04}.png');bpy.ops.render.render(write_still=True)
scene.frame_set(1005);scene.render.filepath=str(P/'dance-preview.png');bpy.ops.render.render(write_still=True)
print('DANCE PREVIEW COMPLETE',flush=True)
