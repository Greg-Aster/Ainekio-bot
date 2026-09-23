"""Packed motion selector for the current-geometry Blender demonstration."""
import bpy,json

def chapters(scene):return json.loads(scene.get('ainekio_motion_chapters','[]'))
class AINEKIO_OT_motion_select(bpy.types.Operator):
    bl_idname='ainekio.motion_select';bl_label='Show motion'
    command:bpy.props.StringProperty()
    play:bpy.props.BoolProperty(default=False)
    def execute(self,context):
        scene=context.scene;items=chapters(scene)
        if self.command=='ALL':start,end=scene.frame_start,scene.frame_end
        else:
            item=next(x for x in items if x['command']==self.command);start,end=item['start_frame'],item['end_frame']
        if context.screen.is_animation_playing:bpy.ops.screen.animation_cancel(restore_frame=False)
        scene.use_preview_range=True;scene.frame_preview_start=start;scene.frame_preview_end=end;scene.frame_set(start)
        if self.play:bpy.ops.screen.animation_play()
        return {'FINISHED'}
class AINEKIO_PT_motions(bpy.types.Panel):
    bl_label='Motion library';bl_idname='AINEKIO_PT_motions';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Ainekio'
    @classmethod
    def poll(cls,context):return 'ainekio_motion_chapters' in context.scene
    def draw(self,context):
        layout=self.layout;row=layout.row(align=True)
        for text,play in [('Show all',False),('Play all',True)]:
            op=row.operator('ainekio.motion_select',text=text);op.command='ALL';op.play=play
        layout.label(text='Select a motion, then press Space.')
        for item in chapters(context.scene):
            row=layout.row(align=True);op=row.operator('ainekio.motion_select',text=item['label']);op.command=item['command']
            op=row.operator('ainekio.motion_select',text='',icon='PLAY');op.command=item['command'];op.play=True

def register():
    for cls in [AINEKIO_OT_motion_select,AINEKIO_PT_motions]:
        if hasattr(bpy.types,cls.__name__):bpy.utils.unregister_class(getattr(bpy.types,cls.__name__))
        bpy.utils.register_class(cls)
if __name__=='__main__':register()
