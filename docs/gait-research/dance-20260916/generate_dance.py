"""Twelve-servo Dance: grounded paired-leg rocks, shoulders, bob and twist.

Geometric millimeters/radians only. Reversible rolling-contact primitives keep
each beat and the final standing pose exactly repeatable.
"""
import copy
import json
import math
from pathlib import Path

import numpy as np
import plan_crawl as k

P = Path(__file__).resolve().parent


def orientation(euler):
    x, y, z = euler
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    R = k.rz(z) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ k.rx(x)
    cx, sx, cy, sy, cz, sz = math.cos(x/2), math.sin(x/2), math.cos(y/2), math.sin(y/2), math.cos(z/2), math.sin(z/2)
    quat = [cx*cy*cz+sx*sy*sz, sx*cy*cz-cx*sy*sz, cx*sy*cz+sx*cy*sz, cx*cy*sz-sx*sy*cz]
    return R, quat


def generate(settings=None):
    base = json.loads((P / 'base-config.json').read_text())
    cfg = dict(command='dance', sample_hz=120, preview_fps=24, gait_start_frame=937,
        existing_animation_end_frame=913, cycles=5, entry_seconds=1.5,
        quarter_cycle_seconds=.45, exit_seconds=1.5, hold_seconds=.5,
        ready_drop_mm=9., bob_mm=6., lateral_sway_mm=12., foreaft_sway_mm=3.,
        roll_degrees=6., pitch_degrees=3., yaw_degrees=5.,
        com=base['com'], geometric_research_angle_bounds_degrees=base['geometric_research_angle_bounds_degrees'],
        source_blend='Before-Dance.blend', output_blend='Ainekio-Dance.blend',
        scene_name='AINEKIO - Dance', part023_forward_limit_degrees=90.,
        contact_model='Four grounded convex soles; material contact vertex stays fixed until supporting-feature transfer. Reverse each solved primitive exactly; small finite-step rolling normal corrections are recorded.',
        completion='Return through the recorded exit to the exact standing joint pose, then hold; restore the stand face.',
        adaptation='V1 alternates right knee channels R4/R3 and left L3/L4 five times. V2 retains five left/right paired-leg beats, adding coordinated shoulder sway, body roll, yaw and bob with four grounded feet.',
        hardware_qualified=False)
    cfg.update(settings or {})
    hz = cfg['sample_hz']
    neutral_z = max(-k.sole_world(l, np.zeros(3), np.zeros(3))[:, 2].min() for l in k.LEGS)
    neutral = np.array([0., 0., neutral_z, 0., 0., 0.])
    ready = neutral.copy(); ready[2] -= cfg['ready_drop_mm']
    com = k.configured_body_com(cfg)
    body_mesh = np.load(P / 'body-samples.npz')['vertices']
    max_correction = 0.

    def primitive(start, goal, duration, initial=None):
        nonlocal max_correction
        state = copy.deepcopy(initial)
        result = []
        for n in range(round(duration * hz) + 1):
            pose = start + (goal-start) * k.smooth(n / round(duration * hz))
            body, euler = pose[:3], pose[3:]
            R, quat = orientation(euler)
            def sole(l, q):
                bolt, rot, beta = k.foot_pose(l, q, np.zeros(3))
                return (k.SOLE[l]-k.F0[l]) @ (R @ rot).T + body + R @ bolt
            if state is None:
                state = {}
                for l in k.LEGS:
                    vv = sole(l, np.zeros(3)); idx = int(vv[:, 2].argmin())
                    anchor = vv[idx].copy(); anchor[2] = 0.
                    state[l] = dict(q=np.zeros(3), index=idx, anchor=anchor)
            qrow, betas, feet, contacts, clear, errors, indices, carriers = [], [], [], [], [], [], [], []
            for l in k.LEGS:
                st = state[l]
                def inverse(anchor, seed, index):
                    return k.inverse(l, R.T @ (anchor-body), np.zeros(3), seed, k.SOLE[l][index])
                q = inverse(st['anchor'], st['q'], st['index']) if n else st['q'].copy()
                for _ in range(20):
                    vv = sole(l, q); idx = int(vv[:, 2].argmin()); low = vv[idx, 2]
                    if low >= -2e-8:
                        break
                    max_correction = max(max_correction, float(-low))
                    anchor = vv[idx].copy(); anchor[2] = 0.
                    q = inverse(anchor, q, idx)
                    st = dict(q=q, index=idx, anchor=anchor)
                else:
                    raise ValueError(('rolling did not converge', l, low))
                for j, name in enumerate(('h', 'alpha', 'theta')):
                    low, high = cfg['geometric_research_angle_bounds_degrees'][name]
                    if not low-1e-6 <= math.degrees(q[j]) <= high+1e-6:
                        raise ValueError((l, name, math.degrees(q[j]), 'outside bounds'))
                st['q'] = q; state[l] = st
                bolt, _, beta = k.foot_pose(l, q, np.zeros(3)); vv = sole(l, q)
                qrow.append(q.tolist()); betas.append(beta); feet.append((body+R@bolt).tolist())
                contacts.append(st['anchor'].tolist()); clear.append(float(vv[:, 2].min()))
                errors.append(float(np.linalg.norm(vv[st['index']]-st['anchor']))); indices.append(st['index'])
                par = k.g.PARAMETERS['legs'][l]
                od = np.array(k.g.fk(l, *q)['planar_pivots']['D']) - par['pivots_xy_mm']['O']
                angle = math.degrees(math.atan2(od[1]*math.cos(q[0]), od[0])) % 360
                carriers.append(angle)
            cw = body + R @ com
            body_low = float((body_mesh @ R[2, :] + body[2]).min())
            if body_low < 1.:
                raise ValueError(('body clearance', body_low))
            result.append(dict(body_position_world_mm=body.tolist(), body_rotation_euler_xyz_rad=euler.tolist(),
                body_orientation_world_quaternion_wxyz=quat, actuator_angles_rad=qrow, passive_beta_rad=betas,
                foot_bolt_world_mm=feet, contact_world_mm=contacts, contact_active=[True]*4,
                contact_vertex_index=indices, sole_clearance_mm=clear, stance_constraint_error_mm=errors,
                assumed_com_world_mm=cw.tolist(), support_margin_mm=k.margin([c[:2] for c in contacts], cw[:2]),
                body_ground_clearance_mm=body_low, part023_OD_angle_from_forward_degrees=carriers))
        return result, state

    entry, ready_state = primitive(neutral, ready, cfg['entry_seconds'])
    assert cfg['exit_seconds'] == cfg['entry_seconds'], 'Change exit timing through the execution profile'
    sides = []
    for sign in (1, -1):
        goal = ready.copy()
        goal[:3] += [sign*cfg['foreaft_sway_mm'], sign*cfg['lateral_sway_mm'], -cfg['bob_mm']]
        goal[3:] = np.radians([sign*cfg['roll_degrees'], sign*cfg['pitch_degrees'], -sign*cfg['yaw_degrees']])
        solved, _ = primitive(ready, goal, cfg['quarter_cycle_seconds'], ready_state)
        sides.append(solved)
    rows, phases = [], []
    def append(sequence, name, cycle=-1):
        start = (len(rows)-1)/hz if rows else 0.
        duration = (len(sequence)-1)/hz
        phases.append(dict(start=start, end=start+duration, kind=name, cycle=cycle))
        for i, old in enumerate(sequence):
            if rows and i == 0:
                continue
            row = copy.deepcopy(old)
            row.update(time_s=len(rows)/hz, phase=name, phase_fraction=i/(len(sequence)-1), cycle=cycle, swing_leg=None)
            rows.append(row)
    append(entry, 'settle_into_dance')
    for cycle in range(cfg['cycles']):
        for label, sequence in zip(('left', 'right'), sides):
            append(sequence, 'rock_'+label, cycle)
            append(list(reversed(sequence)), 'rebound_'+label, cycle)
    append(list(reversed(entry)), 'return_to_standing')
    motion_end = rows[-1]['time_s']
    append([copy.deepcopy(rows[-1]) for _ in range(round(cfg['hold_seconds']*hz)+1)], 'hold_standing')
    cfg['face_cues'] = [dict(time_s=0., name='dance', mode='loop', fps=1), dict(time_s=motion_end, name='stand', mode='once', fps=1)]
    qd = np.degrees([r['actuator_angles_rad'] for r in rows]); vel = np.gradient(qd, 1/hz, axis=0); acc = np.gradient(vel, 1/hz, axis=0)
    report = dict(duration_s=rows[-1]['time_s'], motion_end_s=motion_end, sample_hz=hz, samples=len(rows),
        cycles=cfg['cycles'], cycle_seconds=4*cfg['quarter_cycle_seconds'],
        actuator_min_degrees=qd.min(0).tolist(), actuator_max_degrees=qd.max(0).tolist(),
        actuator_peak_speed_degrees_s=np.abs(vel).max(0).tolist(), actuator_peak_acceleration_degrees_s2=np.abs(acc).max(0).tolist(),
        final_actuator_degrees=qd[-1].tolist(), maximum_return_error_degrees=float(np.abs(qd[-1]-qd[0]).max()),
        minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows),
        minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),
        min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
        max_stance_material_vertex_constraint_error_mm=max(max(r['stance_constraint_error_mm']) for r in rows),
        maximum_rolling_normal_correction_mm=max_correction, minimum_stance_contacts=4,
        maximum_adjacent_joint_step_degrees=float(np.abs(np.diff(qd, axis=0)).max()),
        research_angle_bounds_satisfied=True,
        part023_forward_limit_satisfied=min(min(r['part023_OD_angle_from_forward_degrees']) for r in rows)>=90.,
        collision_checked=False, measured_mass_balance_verified=False, hardware_qualified=False)
    assert report['minimum_support_margin_mm'] > 5
    assert report['part023_forward_limit_satisfied']
    return dict(metadata=dict(configuration=cfg, leg_order=k.LEGS,
        joint_order=['h_Part002', 'alpha_Part006', 'theta_Part005'], position_units='mm', angle_units='radian',
        time_units='second', world_axes='X forward, Y left, Z up', source_geometry=k.g.PARAMETERS['source_blend']),
        samples=rows, phases=phases, validation=report)


if __name__ == '__main__':
    data = generate()
    for name, value in [('source.json', data), ('config.json', data['metadata']['configuration']), ('validation.json', data['validation'])]:
        (P/name).write_text(json.dumps(value, indent=None if name=='source.json' else 2)+'\n')
    print(json.dumps(data['validation'], indent=2))
