"""Iterative learning of periodic task-space gait residuals.

Training uses timestamp-aligned P4 linkage measurements, not camera distance,
foot contact, motor current, or raw AI servo targets. Fit runs on the host/Q6A;
the P4 evaluates five basis terms per foot coordinate through its existing IK.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path


def observations(batches):
    events = {}
    geometry = set()
    for batch in batches:
        records = batch['records']
        if not records or records[0].get('schema') != 'gait_trace_v1' or 'next' not in records[-1]:
            raise ValueError('Incomplete trace batch')
        if records[-1].get('lost'):
            raise ValueError('Trace contains lost records; record again for training')
        header = records[0]
        if header.get('geometry'):
            geometry.add(header['geometry'])
        for event in records[1:-1]:
            if event.get('kind') == 'tracking':
                events[(header['boot_id'], header['session'], event['sequence'])] = event
    if len(geometry) != 1:
        raise ValueError('Expected one recorded linkage geometry')
    rows = [[] for _ in range(4)]
    contexts = set()
    pulses = []
    for key, e in sorted(events.items()):
        if not e['eligible']:
            continue
        nominal = e.get('nominal_pulses_us')
        if (not isinstance(nominal, list) or len(nominal) != 12 or
                any(type(v) is not int or not 1 <= v <= 65535 for v in nominal)):
            raise ValueError('Recording needs twelve nominal pulse targets; record with firmware 0.8.82 or newer')
        pulses.append(nominal)
        for leg, data in enumerate(e['legs']):
            # The first two cycles are the existing gait's entry interpolation.
            if not e['valid_mask'] & (1 << leg) or data['phase'] < 2:
                continue
            values = data['target_mm'] + data['measured_mm'] + data['correction_mm'] + [data['phase']]
            if len(values) != 10 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                raise ValueError('Nonfinite or malformed tracking sample')
            contexts.add((e['signature'], round(e['stride'], 3)))
            rows[leg].append({**data, 'cycle': (*key[:2], e['command_sequence'], math.floor(data['phase']))})
    if len(contexts) != 1:
        raise ValueError('Record one stride and calibration context per model')
    return rows, next(iter(geometry)), next(iter(contexts)), pulses


def basis(phases):
    import numpy as np
    t = np.asarray(phases)*2*np.pi
    return np.column_stack((np.ones_like(t), np.sin(t), np.cos(t), np.sin(2*t), np.cos(2*t)))


POLICY_FEATURES = ('reference_error_x/10mm', 'reference_error_y/10mm', 'reference_error_z/10mm',
                   'roll_target_error/0.1rad', 'pitch_target_error/0.1rad',
                   'body_angular_rate_x/rad_s', 'body_angular_rate_y/rad_s', 'body_angular_rate_z/rad_s')
GAIT_PROFILE_FIELDS = (['duty_delta', 'sweep_delta_mm'] +
                      [f'phase_offset_{leg}' for leg in ('RL', 'RR', 'FL', 'FR')] +
                      [f'lift_delta_mm_{leg}' for leg in ('RL', 'RR', 'FL', 'FR')] +
                      [f'landing_mm_{leg}_{axis}' for leg in ('RL', 'RR', 'FL', 'FR') for axis in ('x', 'y')] +
                      [f'body_mm_{axis}_{term}' for axis in ('x', 'y', 'z') for term in range(5)])


def model_identity(model):
    """Hash the serialized policy, excluding the previous identity."""
    return hashlib.sha256(json.dumps({k: v for k, v in model.items() if k != 'id'},
                                    sort_keys=True, allow_nan=False).encode()).hexdigest()


def policy_seed(batches, *, gait=False):
    """Start physical policy search at the existing gait, with zero additions.

    This does not pretend that fitting tracking error optimizes locomotion. The
    search owner supplies candidate weights and evaluates separate physical runs.
    The input signature includes IMU mounting, bias and saved level reference.
    """
    import numpy as np
    if gait:
        geometry = set();pulses = [];strides = [];commands = []
    else:
        _, geometry, (_, stride), pulses = observations(batches)
    contexts = set()
    usable = 0
    seen = set()
    for batch in batches:
        header = batch['records'][0]
        if gait:
            if header.get('schema') != 'gait_trace_v1' or 'next' not in batch['records'][-1] or batch['records'][-1].get('lost'):
                raise ValueError('Expected a complete device trace without lost records')
            geometry.add(header.get('geometry'))
        for event in batch['records'][1:-1]:
            policy = event.get('policy') or {}
            if event.get('kind') != 'tracking' or not (policy.get('eligible') if gait else event.get('eligible')):
                continue
            key = header['boot_id'], header['session'], event['sequence']
            if key in seen:
                continue
            seen.add(key)
            if policy.get('schema') != 'gait_policy_input_v1':
                raise ValueError('Record with sensor-policy firmware; older traces do not contain decision-time inputs')
            contexts.add(policy.get('gait_signature') if gait else policy['signature'])
            if gait:
                if policy.get('command_schema') != 'gait_policy_command_v1':
                    raise ValueError('Record with learned gait-profile firmware for command features')
                if len(event.get('nominal_pulses_us', [])) != 12:
                    raise ValueError('Expected twelve nominal output pulses')
                pulses.append(event['nominal_pulses_us']);strides.append(event['stride'])
                command = np.asarray(policy['command'], dtype=float)
                if command.shape != (4,) or not np.isfinite(command).all():
                    raise ValueError('Expected four finite command features')
                commands.append(command)
            if policy.get('usable'):
                features = np.asarray(policy['features'], dtype=float)
                if features.shape != (32,) or not np.isfinite(features).all():
                    raise ValueError('Expected 32 finite decision-time policy inputs')
                usable += 1
    if len(contexts) != 1 or None in contexts or not usable:
        raise ValueError('Expected one policy calibration context with usable measurements')
    if gait:
        if len(geometry) != 1 or None in geometry:
            raise ValueError('Expected one linkage geometry')
        geometry = next(iter(geometry));stride = max(strides)
    model = {'schema': 'gait_learning_v4' if gait else 'gait_learning_v3', 'feature_schema': 'gait_policy_input_v1',
             'features': list(POLICY_FEATURES), 'geometry': geometry,
             'signature': next(iter(contexts)), 'stride': stride, 'command': 'forward Walk',
             'coordinates': 'body-frame lower-leg reference point mm; RL RR FL FR; x y z',
             'pulse_min_us': np.min(pulses, axis=0).tolist(), 'pulse_max_us': np.max(pulses, axis=0).tolist(),
             'coefficients': [0.]*60, 'feedback_coefficients': [0.]*96}
    if gait:
        model.update(command='Walk with operator direction/stride interpolation',
                     command_schema='gait_policy_command_v1', command_coefficients=[0.]*48,
                     command_features=['forward', 'turn', 'lateral', 'stride'],
                     observed_command_range=np.array([np.min(commands, axis=0), np.max(commands, axis=0)]).tolist(),
                     gait_profile_fields=GAIT_PROFILE_FIELDS, gait_profile=[0.]*33)
    model['id'] = model_identity(model)
    return {'model': model, 'training': {'method': 'zero-addition physical policy-search seed',
            'decision_samples': usable, 'physical_improvement_demonstrated': False}}


def policy_response(model, phases, features, commands=None):
    """Unfaded, pre-IK response in mm; reproduces the P4 policy, not its plant.

    Features are the exact decision-time values recorded on the P4, not a
    nearest future observation. Normal firmware operation performs no training.
    """
    import numpy as np
    x = np.asarray(features, dtype=float).reshape(-1, 4, 8)
    periodic = np.asarray(model['coefficients'], dtype=float).reshape(4, 3, 5)
    feedback = np.asarray(model['feedback_coefficients'], dtype=float).reshape(4, 3, 8)
    b = basis(phases)
    if len(x) != len(b):
        raise ValueError('Each decision phase needs its own sensor inputs')
    response = np.einsum('nt,lat->nla', b, periodic) + np.einsum('nlt,lat->nla', x, feedback)
    if model['schema'] == 'gait_learning_v4':
        command = np.asarray(commands, dtype=float)
        if command.shape != (len(b), 4):
            raise ValueError('Each version 4 decision needs its operator command features')
        weights = np.asarray(model['command_coefficients'], dtype=float).reshape(4, 3, 4)
        response += np.einsum('nt,lat->nla', command, weights)
    return response


def fit(batches, gain=0.5):
    """u_next = smooth(u_applied + gain*(nominal - measured)).

    This task-space ILC update assumes the local response has the same sign as
    the requested displacement. Its physical benefit must be measured on the
    next trial. No in-sample fit score is presented as improved walking.
    """
    import numpy as np
    if not math.isfinite(gain) or not 0 < gain <= 1:
        raise ValueError('Learning gain must be above zero and at most one')
    rows, geometry, (signature, stride), pulses = observations(batches)
    coefficients, report = [], []
    for leg, data in enumerate(rows):
        if len(data) < 5:
            raise ValueError(f'Leg {leg} has insufficient valid tracking samples')
        x = basis([r['phase'] for r in data])
        error = np.asarray([r['target_mm'] for r in data])-np.asarray([r['measured_mm'] for r in data])
        applied = np.asarray([r['correction_mm'] for r in data])
        # Equal phase-bin weighting avoids fitting mostly the slower stance.
        bins = np.floor(np.mod([r['phase'] for r in data], 1)*32).astype(int)
        weight = np.sqrt(1/np.bincount(bins, minlength=32)[bins])
        w = x*weight[:, None]
        if np.linalg.matrix_rank(w) != 5:
            raise ValueError(f'Leg {leg} lacks phase coverage for two harmonics')
        beta = np.linalg.lstsq(w, (applied+gain*error)*weight[:, None], rcond=None)[0]
        coefficients.extend(beta.T.flatten().tolist())
        smooth_error = np.linalg.lstsq(w, error*weight[:, None], rcond=None)[0]
        report.append({'leg': leg, 'samples': len(data), 'cycles_observed': len({r['cycle'] for r in data}),
                       'phase_bins': len(set(bins)), 'tracking_rms_mm': np.sqrt(np.mean(error**2, axis=0)).tolist(),
                       'periodic_error_rms_mm': np.sqrt(np.mean((x@smooth_error)**2, axis=0)).tolist(),
                       'fitted_residual_rms_mm': np.sqrt(np.mean((x@beta)**2, axis=0)).tolist()})
    model = {'schema': 'gait_learning_v2', 'geometry': geometry, 'signature': signature,
             'stride': stride, 'command': 'forward Walk', 'basis': ['1', 'sin(phase)', 'cos(phase)', 'sin(2phase)', 'cos(2phase)'],
             'coordinates': 'body-frame lower-leg reference point mm; RL RR FL FR; x y z',
             'pulse_min_us': np.min(pulses, axis=0).tolist(),
             'pulse_max_us': np.max(pulses, axis=0).tolist(),
             'coefficients': coefficients}
    model['id'] = hashlib.sha256(json.dumps(model, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {'model': model, 'training': {'method': 'two-harmonic task-space iterative learning', 'gain': gain,
            'legs': report, 'physical_improvement_demonstrated': False,
            'limitations': ['Shaft feedback and rigid-link geometry do not measure foot contact, slip or force.',
                           'Compare a separate physical candidate trial with the baseline before accepting improvement.']}}


def evaluate(batches):
    import numpy as np
    rows, geometry, context, _ = observations(batches)
    return {'geometry': geometry, 'signature': context[0], 'stride': context[1], 'legs': [
        {'leg': leg, 'samples': len(data), 'tracking_rms_mm': np.sqrt(np.mean((
            np.asarray([r['target_mm'] for r in data])-np.asarray([r['measured_mm'] for r in data]))**2, axis=0)).tolist()}
        for leg, data in enumerate(rows) if data]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path, nargs='+', help='trace.jsonl recordings; never overwritten')
    parser.add_argument('--gain', type=float, default=.5)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--evaluate', action='store_true')
    parser.add_argument('--policy-seed', action='store_true', help='Create a zero-addition sensor policy for physical search')
    args = parser.parse_args()
    batches = [json.loads(line) for path in args.trace for line in path.read_text().splitlines() if line.strip()]
    result = policy_seed(batches, gait=True) if args.policy_seed else evaluate(batches) if args.evaluate else fit(batches, args.gain)
    text = json.dumps(result, indent=2, allow_nan=False)+'\n'
    if args.output:
        with args.output.open('x') as stream: stream.write(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
