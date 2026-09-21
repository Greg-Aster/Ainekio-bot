"""Belly-supported Swim gesture: mirrored 90-degree shoulders, four paddles.

Geometric coordinates only. The evaluated bottom-cover plane supplies support
while all four feet are airborne; this is a dry-floor motion demonstration.
"""
import copy
import json
import math
from pathlib import Path

import numpy as np
import plan_crawl as k
import generate_lower_reference as lower

P = Path(__file__).resolve().parent
LEGS = k.LEGS


def hull(points):
    points = sorted(set(tuple(round(float(v), 7) for v in point) for point in points))
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out
    return np.array(half(points)[:-1] + half(reversed(points))[:-1])


def generate(settings=None):
    mesh = np.load(P/'body-samples.npz')['vertices']
    belly_height = float(-mesh[:, 2].min())
    footprint = hull(mesh[mesh[:, 2] <= -belly_height+.01, :2])
    assert len(footprint) >= 3
    cfg = dict(command='swim', display_label='SWIM', cycles=4, lower_seconds=2.5,
        lift_seconds=1.5, reach_seconds=1., stroke_seconds=3., stroke_ramp_seconds=.8, hold_seconds=.7,
        rear_phase_lag_cycles=.25,
        shoulder_outward_degrees=90., shoulder_signs=[1., -1., 1., -1.],
        paddle_alpha_start_degrees=-20., paddle_alpha_end_degrees=25., paddle_theta_center_degrees=15., paddle_theta_amplitude_degrees=30.,
        target_body_height_mm=belly_height, bottom_contact_tolerance_mm=.01,
        bottom_contact_polygon_body_xy_mm=footprint.tolist(),
        bottom_contact_geometry='CRAWL | Body - Bottom Cover - Compact',
        sample_hz=120, preview_fps=24, gait_start_frame=1261, existing_animation_end_frame=1237,
        source_blend='Before-Swim.blend', output_blend='Ainekio-Swim.blend', scene_name='AINEKIO - Swim',
        part023_forward_limit_degrees=None,
        completion='Replace all four soles while the belly remains supported, reverse the lowering motion to exact standing, and hold; restore the stand face.',
        adaptation='Continuous breaststroke refinement: mirrored +/-90-degree shoulders, coordinated Part006 and Part005 loops, and a quarter-cycle rear phase lag. Both front arms and rear legs remain in motion during the steady swim, with no inter-stroke rests. Physical front pair is CAD RL/RR; rear pair FL/FR.',
        stroke_model='Continuous coordinated alpha/theta ellipses. Front: alpha=center-amplitude*cos(phi), theta=center+amplitude*sin(phi). Rear uses phi-2*pi*rear_phase_lag_cycles, alpha=center+amplitude*cos(phi_rear), theta=center-amplitude*sin(phi_rear). A shared integrated quintic rate ramp eases only the whole swim start/end; the steady phase advances at constant speed across all cycle boundaries. Phase lag is choreography, separate from PWM staggering.',
        contact_model='Grounded rolling soles during lowering/standing; measured flat bottom-cover contact polygon supports the fixed body during shoulder lift and airborne paddling. Foot contact flags are false while lifted; no water or buoyancy model.',
        hardware_qualified=False)
    cfg.update(settings or {})
    lowered = lower.generate(dict(target_body_height_mm=cfg['target_body_height_mm'], lower_seconds=cfg['lower_seconds'], hold_seconds=0.))
    base = lowered['metadata']['configuration']
    cfg['com'] = base['com']
    cfg['geometric_research_angle_bounds_degrees'] = copy.deepcopy(base['geometric_research_angle_bounds_degrees'])
    cfg['geometric_research_angle_bounds_degrees']['h'] = [-95., 95.]
    cfg['shoulder_bounds_basis'] = 'Research envelope for the requested +/-90-degree pose; not calibrated electrical travel or collision proof.'
    hz = cfg['sample_hz']; rows = copy.deepcopy(lowered['samples'])
    for r in rows:
        r['phase'] = 'lower_onto_belly'; r['body_contact_active'] = False
        r['support_source'] = 'feet'; r['body_contact_polygon_world_mm'] = []
    now = rows[-1]['time_s']; phases = [dict(start=0., end=now, kind='lower_onto_belly')]
    standing_rows = copy.deepcopy(rows)
    belly_row = rows[-1]; body = np.array(belly_row['body_position_world_mm'])
    q = np.array(belly_row['actuator_angles_rad']); folded = q.copy()
    support = np.column_stack([footprint+body[:2], np.zeros(len(footprint))])
    com = k.configured_body_com(cfg)
    belly_margin = k.margin(footprint+body[:2], (body+com)[:2])
    assert belly_margin > 5., ('Assumed COM outside useful bottom-cover support', belly_margin)
    belly_row.update(body_contact_active=True, support_source='belly_and_feet', body_contact_polygon_world_mm=support.tolist())

    def record(time, phase, u):
        row = copy.deepcopy(belly_row)
        row.update(time_s=time, phase=phase, phase_fraction=u, actuator_angles_rad=q.tolist(),
            swing_leg=None, contact_active=[False]*4, stance_constraint_error_mm=[None]*4,
            body_contact_active=True, support_source='belly', support_margin_mm=belly_margin)
        for i, leg in enumerate(LEGS):
            bolt, rotation, beta = k.foot_pose(leg, q[i], body)
            vv = (k.SOLE[leg]-k.F0[leg]) @ rotation.T + bolt
            low = int(vv[:, 2].argmin())
            if vv[low, 2] < -1e-5:
                raise ValueError(('Foot penetrates floor', leg, time, float(vv[low, 2])))
            row['foot_bolt_world_mm'][i] = bolt.tolist(); row['passive_beta_rad'][i] = beta
            row['contact_world_mm'][i] = vv[low].tolist(); row['contact_vertex_index'][i] = low
            row['sole_clearance_mm'][i] = float(vv[low, 2])
            v = k.g.PARAMETERS['legs'][leg]['pivots_xy_mm']
            od = np.array(k.g.fk(leg, *q[i])['planar_pivots']['D']) - v['O']
            row['part023_OD_angle_from_forward_degrees'][i] = math.degrees(math.atan2(od[1]*math.cos(q[i, 0]), od[0])) % 360
        rows.append(row)

    def segment(target, duration, name):
        nonlocal now, q
        start = q.copy(); steps = round(duration*hz)
        phases.append(dict(start=now, end=round((now+duration)*hz)/hz, kind=name))
        for i in range(1, steps+1):
            q = start+(target-start)*k.smooth(i/steps)
            record(round(now*hz+i)/hz, name, i/steps)
        now = rows[-1]['time_s']

    raised = folded.copy()
    raised[:, 0] = np.radians(cfg['shoulder_signs'])*cfg['shoulder_outward_degrees']
    segment(raised, cfg['lift_seconds'], 'raise_shoulders_to_90')
    center = (cfg['paddle_alpha_start_degrees']+cfg['paddle_alpha_end_degrees'])/2
    amplitude = (cfg['paddle_alpha_end_degrees']-cfg['paddle_alpha_start_degrees'])/2
    def stroke_pose(phi):
        result = raised.copy()
        for pair,angle,sign in [(slice(2,4),phi,1),(slice(0,2),phi-2*math.pi*cfg['rear_phase_lag_cycles'],-1)]:
            result[pair,1] = math.radians(center-sign*amplitude*math.cos(angle))
            result[pair,2] = math.radians(cfg['paddle_theta_center_degrees']+sign*cfg['paddle_theta_amplitude_degrees']*math.sin(angle))
        return result
    ready = stroke_pose(0.)
    segment(ready, cfg['reach_seconds'], 'set_paddle_pose')
    stroke_start = now
    ramp = cfg['stroke_ramp_seconds']; duration = cfg['cycles']*cfg['stroke_seconds']+ramp
    assert 0 < 2*ramp < duration
    cuts = [0.,ramp,duration-ramp,duration]
    names = ['ease_into_continuous_strokes','continuous_breaststroke','ease_out_of_continuous_strokes']
    for a,b,name in zip(cuts,cuts[1:],names):
        phases.append(dict(start=round((now+a)*hz)/hz,end=round((now+b)*hz)/hz,kind=name))
    def ramp_integral(u):
        return 2.5*u**4-3*u**5+u**6
    for i in range(1,round(duration*hz)+1):
        t = i/hz
        if t < ramp:
            turns = ramp*ramp_integral(t/ramp)/cfg['stroke_seconds']
        elif t <= duration-ramp:
            turns = (t-ramp/2)/cfg['stroke_seconds']
        else:
            turns = cfg['cycles']-ramp*ramp_integral((duration-t)/ramp)/cfg['stroke_seconds']
        q = stroke_pose(2*math.pi*turns)
        phase_index = min(2,int(np.searchsorted(cuts[1:],t,side='right')))
        record(round(now*hz+i)/hz,names[phase_index],(t-cuts[phase_index])/(cuts[phase_index+1]-cuts[phase_index]))
        rows[-1].update(cycle=min(cfg['cycles']-1,int(turns)),front_phase_cycles=float(turns),rear_phase_cycles=float(turns-cfg['rear_phase_lag_cycles']))
    now = rows[-1]['time_s']
    cfg['steady_stroke_source_seconds'] = [stroke_start+ramp,stroke_start+duration-ramp]
    stroke_end = now
    segment(raised, cfg['reach_seconds'], 'fold_for_touchdown')
    segment(folded, cfg['lift_seconds'], 'replace_all_feet')
    row = copy.deepcopy(belly_row); row.update(time_s=now, phase='replace_all_feet', phase_fraction=1.)
    rows[-1] = row
    phases.append(dict(start=now, end=now+cfg['lower_seconds'], kind='return_to_standing'))
    for i, original in enumerate(reversed(standing_rows[:-1]), 1):
        row = copy.deepcopy(original)
        row.update(time_s=round(now*hz+i)/hz, phase='return_to_standing', phase_fraction=i/(len(standing_rows)-1))
        rows.append(row)
    now = rows[-1]['time_s']; motion_end = now
    phases.append(dict(start=now, end=now+cfg['hold_seconds'], kind='hold_standing'))
    for i in range(1, round(cfg['hold_seconds']*hz)+1):
        row = copy.deepcopy(rows[-1]); row.update(time_s=round(now*hz+i)/hz, phase='hold_standing', phase_fraction=1.)
        rows.append(row)
    cfg['face_cues'] = [dict(time_s=0., name='swim', mode='once', fps=1), dict(time_s=motion_end, name='stand', mode='once', fps=1)]
    angles = np.degrees([r['actuator_angles_rad'] for r in rows]); speed = np.gradient(angles, 1/hz, axis=0); acceleration = np.gradient(speed, 1/hz, axis=0)
    for j, name in enumerate(('h', 'alpha', 'theta')):
        lo, hi = cfg['geometric_research_angle_bounds_degrees'][name]
        assert angles[:, :, j].min() >= lo-1e-6 and angles[:, :, j].max() <= hi+1e-6
    v = dict(duration_s=rows[-1]['time_s'], motion_end_s=motion_end, sample_hz=hz, samples=len(rows),
        cycles=cfg['cycles'], paddle_start_s=stroke_start, paddle_end_s=stroke_end,
        actuator_min_degrees=angles.min(0).tolist(), actuator_max_degrees=angles.max(0).tolist(),
        actuator_peak_speed_degrees_s=np.abs(speed).max(0).tolist(), actuator_peak_acceleration_degrees_s2=np.abs(acceleration).max(0).tolist(),
        maximum_adjacent_joint_step_degrees=float(abs(np.diff(angles, axis=0)).max()), final_actuator_degrees=angles[-1].tolist(),
        final_joint_return_error_degrees=float(abs(angles[-1]-angles[0]).max()),
        minimum_support_margin_mm=min(r['support_margin_mm'] for r in rows), belly_support_margin_mm=belly_margin,
        minimum_stance_contacts=0, belly_support_required=True, belly_contact_plane_body_z_mm=-belly_height,
        minimum_body_ground_clearance_mm=min(r['body_ground_clearance_mm'] for r in rows),
        min_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows),
        minimum_paddling_sole_height_mm=min(min(r['sole_clearance_mm']) for r in rows if stroke_start <= r['time_s'] <= stroke_end),
        max_stance_material_vertex_constraint_error_mm=max(e for r in rows for e in r['stance_constraint_error_mm'] if e is not None),
        maximum_rolling_normal_correction_mm=lowered['validation']['maximum_rolling_normal_correction_mm'],
        research_angle_bounds_satisfied=True, collision_checked=False, body_contact_strength_verified=False,
        hardware_servo_limits_verified=False, measured_mass_balance_verified=False, hardware_qualified=False)
    metadata = copy.deepcopy(lowered['metadata']); metadata['configuration'] = cfg
    return dict(metadata=metadata, phases=phases, samples=rows, validation=v)


if __name__ == '__main__':
    data = generate()
    for name, value in [('source.json', data), ('config.json', data['metadata']['configuration']), ('validation.json', data['validation'])]:
        (P/name).write_text(json.dumps(value, indent=None if name=='source.json' else 2)+'\n')
    print(json.dumps(data['validation'], indent=2))
