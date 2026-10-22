"""Measurement-only trial assessment; no actuator commands or motion decisions."""
from __future__ import annotations

import bisect
import math
from collections import defaultdict


def visual_summary(records):
    """Endpoint displacement, not integrated path length or wheel odometry.

    Preserve gaps and reference changes. Availability/freshness comes from the
    existing camera owner; this analysis cannot stop or restrict movement.
    """
    segments, current, identity = [], [], None
    unavailable = defaultdict(int)
    for row in records:
        m = row.get('locomotion_measurement') or {}
        p = m.get('position') or {}
        key = tuple(m.get(k) for k in ('robotId', 'epoch', 'gatewayInstance', 'calibrationId', 'referenceId'))
        valid = (m.get('available') and all(v is not None for v in key) and m.get('frameId') and
                 all(isinstance(p.get(k), (int, float)) and math.isfinite(p[k])
                     for k in ('xMetres', 'yMetres', 'headingDegrees')))
        if not valid or key != identity:
            if current:
                segments.append(current)
            current = []
        if not valid:
            unavailable[m.get('reason') or 'Metric position unavailable'] += 1
            identity = None
            continue
        identity = key
        if not current or current[-1]['frameId'] != m['frameId']:
            current.append(m)
    if current:
        segments.append(current)
    result = []
    for segment in segments:
        a, b = segment[0], segment[-1]
        first, last = a['position'], b['position']
        dx, dy = last['xMetres']-first['xMetres'], last['yMetres']-first['yMetres']
        yaw = math.radians(first['headingDegrees'])
        z = [m['position'].get('zMetres') for m in segment]
        z_available = all(isinstance(v, (int, float)) and math.isfinite(v) for v in z)
        result.append({'reference_id': a['referenceId'], 'calibration_id': a['calibrationId'],
                       'first_frame': a['frameId'], 'last_frame': b['frameId'], 'frames': len(segment),
                       'first_observed_at': a.get('observedAt'), 'last_observed_at': b.get('observedAt'),
                       'net_displacement_m': math.hypot(dx, dy) if len(segment) > 1 else None,
                       'forward_m': dx*math.cos(yaw)+dy*math.sin(yaw),
                       'left_m': -dx*math.sin(yaw)+dy*math.cos(yaw),
                       'heading_change_deg': (last['headingDegrees']-first['headingDegrees']+180)%360-180,
                       'body_z_change_m': z[-1]-z[0] if z_available else None,
                       'body_z_min_change_m': min(z)-z[0] if z_available else None,
                       'metric_uncertainty_m': None})
    return {'distance_m': result[0]['net_displacement_m'] if len(result) == 1 and not unavailable else None,
            'visual_motion': {'segments': result, 'unavailable_observations': dict(unavailable),
                              'distance_definition': 'Net displacement between recorded camera endpoints; not path length',
                              'height_definition': 'Change along starting body Z; not absolute floor clearance',
                              'clock': 'gateway camera receipt, not exposure time'}}


def support_summary(batches):
    """Phase-resolved shaft-derived extension deficits, optionally gravity projected.

    Positive shortfall means the measured leg reference is closer to the body
    than its applied target, including learned displacement. Planned support is
    not measured contact. Do not
    infer support from a fixed duty cycle: use recorded planner state when present.
    """
    events = {}
    for batch in batches:
        records = batch.get('records', [])
        if not records or records[0].get('schema') != 'gait_trace_v1':
            continue
        header = records[0]
        for event in records[1:]:
            if 'sequence' in event:
                events[(header['boot_id'], header['session'], event['sequence'])] = event
    groups, group, previous = [], [], None
    for key, event in sorted(events.items()):
        if previous and (key[:2] != previous[:2] or key[2] != previous[2]+1):
            groups.append(group);group = []
        group.append(event);previous = key
    if group:
        groups.append(group)
    bins = [defaultdict(lambda: defaultdict(list)) for _ in range(4)]
    unknown_support = 0
    for group in groups:
        imus = defaultdict(dict)
        for event in group:
            if event['kind'] != 'sample':
                continue
            imu, motion = event['imu'], event['motion']
            imus[motion['command_sequence']][imu['timestamp_us']] = imu
        for event in group:
            if event['kind'] != 'tracking' or not (event.get('policy') or {}).get('eligible', event.get('eligible')):
                continue
            samples = imus[event['command_sequence']]
            stamps = sorted(samples)
            for leg, data in enumerate(event['legs']):
                if not event['valid_mask'] & (1 << leg) or data['phase'] < 2:
                    continue
                delta = [m-t-c for m, t, c in zip(data['measured_mm'], data['target_mm'],
                                                 data.get('correction_mm', [0., 0., 0.]))]
                bucket = bins[leg][int((data['phase'] % 1)*32)]
                bucket['body_z_shortfall_mm'].append(delta[2])
                known, grounded = data.get('support_known'), data.get('planned_grounded')
                if not known:
                    unknown_support += 1
                if known and grounded:
                    bucket['support_body_z_shortfall_mm'].append(delta[2])
                stamp = data['sampled_us']
                i = bisect.bisect_left(stamps, stamp)
                if i == len(stamps) or (i == 0 and stamps[i] != stamp):
                    continue
                a = samples[stamps[i if stamps[i] == stamp else i-1]]
                b = samples[stamps[i]]
                if not all(s.get('available') and s.get('fresh') and s.get('calibration_applied') and
                           not s.get('startup') and not s.get('recovering') for s in (a, b)):
                    continue
                qa, qb = a['orientation_wxyz'], b['orientation_wxyz']
                u = (stamp-a['timestamp_us'])/(b['timestamp_us']-a['timestamp_us']) if a != b else 0
                sign = -1 if sum(x*y for x, y in zip(qa, qb)) < 0 else 1
                q = [(1-u)*x+u*sign*y for x, y in zip(qa, qb)]
                norm = math.sqrt(sum(x*x for x in q))
                if not norm or not math.isfinite(norm):
                    continue
                w, x, y, z = [v/norm for v in q]
                up = [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]
                projected = sum(d*v for d, v in zip(delta, up))
                bucket['gravity_shortfall_mm'].append(projected)
                if known and grounded:
                    bucket['support_gravity_shortfall_mm'].append(projected)
    legs = []
    for leg, table in enumerate(bins):
        phases = [{'bin': phase, **{key: {'mean': sum(v)/len(v), 'min': min(v), 'max': max(v), 'samples': len(v)}
                                  for key, v in values.items()}} for phase, values in sorted(table.items())]
        means = [p['support_gravity_shortfall_mm']['mean'] for p in phases if 'support_gravity_shortfall_mm' in p]
        legs.append({'leg': leg, 'phase_bins': phases,
                     'support_gravity_shortfall_mm': sum(means)/len(means) if means else None})
    return {'legs': legs, 'samples_without_planned_support': unknown_support,
            'contact_measured': False, 'sag_detected': None,
            'interpretation': 'Extension shortfall evidence, not a measured ground plane or confirmed body sag; no motion actions'}
