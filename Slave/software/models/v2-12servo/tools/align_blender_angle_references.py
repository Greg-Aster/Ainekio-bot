"""Convert the edited Wireless rig to firmware joint offsets without moving it.

Run inside Blender with MODEL_ROOT pointing to the matching geometry profile.
Caller owns the recovery copy and save. Mesh authoring angles are not motor zeros.
"""
import json
import math
from pathlib import Path

import bpy


def align(model_root):
    cfg = json.loads((Path(model_root) / 'geometry.json').read_text())
    params = cfg['parameters']
    text = bpy.data.texts['WIRELESS | 35-20-28-38 linkage parameters.json']
    cad = json.loads(text.as_string())
    cad_zero = cad.get('cad_neutral_theta_rad', cad['new_theta_neutral'])
    firmware_zero = params['new_theta_neutral']
    offset = math.remainder(firmware_zero - cad_zero, 2 * math.pi)
    # Keep the same unwrapped branch for the mesh rotation drivers.
    driver_zero = cad_zero + offset
    delta_deg = math.degrees(offset)
    scene = bpy.data.scenes['Wireless']
    bpy.context.view_layer.update()
    before = {o.name: o.matrix_world.copy() for o in scene.objects}
    converted_actions = {}

    def convert_action(action):
        if action.name in converted_actions:
            return converted_actions[action.name]
        # Detached manual-preview actions may also belong to another scene.
        new = action.copy()
        new.name = action.name + ' | Firmware reference'
        new.use_fake_user = True  # Manual posing retains its action by name.
        for layer in new.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        if curve.data_path == '["theta_deg"]':
                            for key in curve.keyframe_points:
                                key.co.y -= delta_deg
                                key.handle_left.y -= delta_deg
                                key.handle_right.y -= delta_deg
                            curve.update()
        converted_actions[action.name] = new
        return new

    for leg in ['FL', 'FR', 'RL', 'RR']:
        control = scene.objects[f'REFINED | {leg} | h alpha theta']
        calc = scene.objects[f'REFINED | {leg} | linkage calculation']
        if control.get('Angle reference') == 'firmware geometric offsets, degrees':
            continue
        control['theta_deg'] -= delta_deg
        if 'Manual posing previous angles' in control:
            angles = list(control['Manual posing previous angles'])
            angles[2] -= delta_deg
            control['Manual posing previous angles'] = angles
        previous = control.get('Manual posing previous action', '')
        if previous:
            control['Manual posing previous action'] = convert_action(bpy.data.actions[previous]).name
        animation = control.animation_data
        if animation and animation.action:
            slot = animation.action_slot.identifier
            animation.action = convert_action(animation.action)
            animation.action_slot = next(s for s in animation.action.slots if s.identifier == slot)
        # This scene's edited controls currently have no NLA tracks.
        # An additive NLA stack would require conversion of its base only.
        assert not animation or not animation.nla_tracks
        for curve in calc.animation_data.drivers:
            if curve.data_path == '["t_requested"]':
                curve.driver.expression = f'{driver_zero!r}+theta_deg*pi/180'
        control['Angle reference'] = 'firmware geometric offsets, degrees'
        control['CAD theta = firmware theta + degrees'] = delta_deg
        control['Motion status'] = '35/20/28/38 linkage; firmware angle reference; legacy previews retain their existing physical motion.'
        control['Kinematic parameters'] = 'Blender Text: WIRELESS | 35-20-28-38 linkage parameters.json'
        control.update_tag()
        calc.update_tag()
    cad.update(cad_neutral_theta_rad=cad_zero,
               firmware_theta_zero_rad=firmware_zero,
               control_theta_zero_rad=driver_zero,
               cad_theta_minus_firmware_theta_deg=delta_deg,
               control_angle_reference='Firmware geometric offsets; radians in source, degrees in Blender controls',
               scope='Wireless geometry and joint references aligned; recorded motion migration is separate')
    text.clear()
    text.write(json.dumps(cad, indent=2))
    bpy.context.view_layer.update()
    maximum = max(abs(o.matrix_world[i][j] - before[o.name][i][j])
                  for o in scene.objects for i in range(4) for j in range(4))
    return dict(scene=scene.name, geometry_id=cfg['geometry_id'],
                cad_theta_minus_firmware_theta_deg=delta_deg,
                firmware_theta_zero_rad=firmware_zero,
                driver_theta_zero_rad=driver_zero,
                maximum_world_matrix_change=maximum,
                preserved_objects=len(before),
                copied_actions=[a.name for a in converted_actions.values()])


if __name__ == '__main__':
    print(json.dumps(align(globals().get('MODEL_ROOT', Path(__file__).resolve().parents[1]))))
