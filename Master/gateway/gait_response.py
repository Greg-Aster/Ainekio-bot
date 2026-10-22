"""Offline identification of measured joint response from gait_trace_v1 trials.

Fits short-horizon predictors, not a servo-command policy. No robot connection.
Use whole separate recordings for evaluation; adjacent frames are not a holdout.
NumPy is needed only on the analysis/training host.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .gait_trace import reconstruct

HISTORY_US = (0, 20000, 40000, 60000, 80000, 100000)
STATE_FEATURES = ['bias', 'target_error_0_us/100', 'target_error_40ms_us/100',
                  'target_error_80ms_us/100', 'filtered_velocity_us_s/1000',
                  'filtered_minus_raw_us/100']


def walking_imu_summary(batches):
    """Report sensor evidence without treating startup attitude as heading truth.

    Z-rate integration is a body-axis rotation approximation, not absolute yaw,
    odometry, or height. Never integrate across a trace gap or command boundary.
    """
    events = {}
    for batch in batches:
        records = batch['records']
        if not records or records[0].get('schema') != 'gait_trace_v1':
            continue
        header = records[0]
        for e in records[1:]:
            if 'sequence' in e:
                events[(header['boot_id'], header['session'], e['sequence'])] = e
    segments, segment, last_key, command = [], {}, None, None
    for key, event in sorted(events.items()):
        if last_key and (key[:2] != last_key[:2] or key[2] != last_key[2]+1):
            if segment: segments.append(segment)
            segment = {};command = None
        last_key = key
        if event['kind'] != 'sample':
            continue
        motion, imu = event['motion'], event['imu']
        usable = motion['walking'] and imu['available'] and imu['fresh']
        if not usable or command != motion['command_sequence']:
            if segment: segments.append(segment)
            segment = {}
        command = motion['command_sequence'] if usable else None
        if usable:
            segment[imu['timestamp_us']] = imu
    if segment: segments.append(segment)
    output = []
    for segment in segments:
        samples = [segment[t] for t in sorted(segment)]
        integral = sum((a['angular_rate_rad_s'][2]+b['angular_rate_rad_s'][2])*.5*
                       (b['timestamp_us']-a['timestamp_us'])/1e6
                       for a, b in zip(samples, samples[1:]))
        output.append({'unique_samples': len(samples),
                       'duration_s': (samples[-1]['timestamp_us']-samples[0]['timestamp_us'])/1e6,
                       'startup_samples': sum(s['startup'] for s in samples),
                       'recovering_samples': sum(s['recovering'] for s in samples),
                       'approximate_body_z_rotation_deg': math.degrees(integral),
                       'peak_sampled_acceleration_norm_m_s2': max(math.sqrt(sum(v*v for v in
                           s['acceleration_m_s2'])) for s in samples)})
    return output


def examples(rows, horizon_us=40000):
    """Causal inputs at t, raw measured label at first scan >= t+horizon.

    Separate invalid samples, scan gaps, commands, revisions and trace segments.
    These are dataset boundaries only; this module cannot restrict robot motion.
    Gyro and planned phase are not features: their scan-end timestamps can be
    later than the individual joint observation. No future target is an input.
    """
    groups = defaultdict(list)
    for row in rows:
        groups[row['joint_id']].append(row)
    result = []
    for joint, joint_rows in groups.items():
        segment = []
        previous = None

        def emit(part):
            stamps = [r['sampled_us'] for r in part]
            for i, row in enumerate(part):
                t = stamps[i]
                history = [bisect.bisect_right(stamps, t-lag)-1 for lag in HISTORY_US]
                end = bisect.bisect_left(stamps, t+horizon_us)
                if min(history) < 0 or end >= len(part):
                    continue
                commands = [part[k]['command_us'] for k in history]
                raw = row['raw_us']
                dt = (stamps[end]-t)/1e6
                state = [1., (commands[0]-raw)/100., (commands[2]-raw)/100.,
                         (commands[4]-raw)/100., row['velocity_us_s']/1000.,
                         (row['filtered_us']-raw)/100.]
                command_history = [1.]+[(u-1650.)/100. for u in commands]
                result.append({'joint_id': joint, 'joint': row['joint'], 'sampled_us': t,
                               'future_sampled_us': stamps[end],
                               'dt_s': dt, 'raw_us': raw, 'future_raw_us': part[end]['raw_us'],
                               'velocity_us_s': row['velocity_us_s'],
                               'state_features': state,
                               # Both predictors know the requested prediction
                               # interval; otherwise timing jitter confounds the
                               # measured-state versus command-only comparison.
                               'command_features': command_history+
                                   [v*dt/.04 for v in command_history]})

        for row in joint_rows:
            identity = tuple(row[k] for k in ('boot_id', 'session', 'segment', 'revision', 'command_sequence'))
            usable = (row['valid'] and row['walking'] and row['command_us'] is not None and
                      all(row[k] is not None and np.isfinite(row[k]) for k in
                          ('raw_us', 'filtered_us', 'velocity_us_s')))
            continuous = (previous is not None and identity == previous[0] and
                          row['scan'] == previous[1]['scan']+1 and
                          row['sampled_us'] > previous[1]['sampled_us'])
            if not usable or not continuous:
                emit(segment);segment = []
            if usable:
                segment.append(row);previous = (identity, row)
            else:
                previous = None
        emit(segment)
    return result


def load_trial(path: Path, horizon_us):
    trace = (path/'trace.jsonl').read_bytes()
    metadata_bytes = (path/'metadata.json').read_bytes()
    metadata = json.loads(metadata_bytes)
    batches = [json.loads(line) for line in trace.splitlines() if line.strip()]
    rows, quality = reconstruct(batches, metadata['feedback'])
    summary = json.loads((path/'summary.json').read_text())
    provenance = {'path': str(path.resolve()), 'trace_sha256': hashlib.sha256(trace).hexdigest(),
                  'metadata_sha256': hashlib.sha256(metadata_bytes).hexdigest(),
                  'firmware': metadata.get('firmware'), 'submitted': summary.get('submitted'),
                  'terminal_receipt': summary.get('terminal_receipt'), 'quality': quality,
                  'walking_imu': walking_imu_summary(batches),
                  'recording_errors': summary.get('errors', [])}
    return examples(rows, horizon_us), provenance


def least_squares(x, y, ridge):
    """Fixed regularization chosen before evaluation; intercept unpenalized."""
    x = np.asarray(x, dtype=float);y = np.asarray(y, dtype=float)
    penalty = np.eye(x.shape[1])*np.sqrt(ridge);penalty[0, 0] = 0
    return np.linalg.lstsq(np.vstack((x, penalty)),
                           np.concatenate((y, np.zeros(x.shape[1]))), rcond=None)[0]


def fit(records, ridge=0.001):
    models = {}
    for joint in sorted({r['joint_id'] for r in records}):
        rows = [r for r in records if r['joint_id'] == joint]
        # Predict change in position; actual sample interval scales the response.
        x = [np.asarray(r['state_features'])*r['dt_s'] for r in rows]
        y = [r['future_raw_us']-r['raw_us'] for r in rows]
        state = least_squares(x, y, ridge)
        # Ablation: the same fit method sees target history but no measured state.
        command = least_squares([r['command_features'] for r in rows],
                                [r['future_raw_us']-1650. for r in rows], ridge)
        models[str(joint)] = {'joint': rows[0]['joint'], 'training_examples': len(rows),
                              'state_coefficients': state.tolist(),
                              'command_only_coefficients': command.tolist()}
    return models


def predictions(model, row):
    return {
        'measured_state': row['raw_us'] + row['dt_s']*float(np.dot(model['state_coefficients'], row['state_features'])),
        'command_only': 1650. + float(np.dot(model['command_only_coefficients'], row['command_features'])),
        'hold_last_position': row['raw_us'],
        'constant_filtered_velocity': row['raw_us']+row['dt_s']*row['velocity_us_s'],
    }


def evaluate(models, records):
    output = []
    for joint in sorted({r['joint_id'] for r in records}):
        rows = [r for r in records if r['joint_id'] == joint]
        model = models[str(joint)]
        errors = defaultdict(list)
        for row in rows:
            for name, predicted in predictions(model, row).items():
                errors[name].append(predicted-row['future_raw_us'])
        output.append({'joint_id': joint, 'joint': model['joint'], 'evaluation_examples': len(rows),
                       'horizon_ms_min_max': [min(r['dt_s'] for r in rows)*1000,
                                              max(r['dt_s'] for r in rows)*1000],
                       'rmse_us': {name: float(np.sqrt(np.mean(np.square(e)))) for name, e in errors.items()}})
    return output


def train_and_evaluate(training_paths, evaluation_paths, horizon_us=40000, ridge=0.001):
    train, test, provenance = [], [], {'training': [], 'evaluation': []}
    for role, paths, records in [('training', training_paths, train), ('evaluation', evaluation_paths, test)]:
        for path in paths:
            rows, info = load_trial(Path(path), horizon_us)
            records.extend(rows);provenance[role].append(info)
    train_hashes = {p['trace_sha256'] for p in provenance['training']}
    if train_hashes.intersection(p['trace_sha256'] for p in provenance['evaluation']):
        raise ValueError('Training and evaluation contain the same recording')
    if not train or not test:
        raise ValueError('Need walking examples in separate training and evaluation recordings')
    models = fit(train, ridge)
    return {'schema': 'gait_response_v1', 'purpose': 'offline short-horizon prediction, not actuator commands',
            'horizon_us': horizon_us, 'ridge': ridge, 'state_features': STATE_FEATURES,
            'command_history_us': list(HISTORY_US), 'models': models,
            'command_feature_layout': '[bias, six centered/scaled targets] followed by the same values times dt_s/0.04',
            'evaluation': evaluate(models, test), 'provenance': provenance,
            'limitations': ['Measured raw position includes electrical noise and calibration error.',
                            'Predicts observed gait response, not counterfactual outcomes of new commands.',
                            'Not a contact, torque, distance, energy or walking-quality model.',
                            'No learned correction is applied to firmware.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', type=Path, nargs='+', required=True)
    parser.add_argument('--evaluate', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = train_and_evaluate(args.train, args.evaluate)
    # Reports contain captured trial provenance; keep them outside the repository.
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['evaluation'], indent=2))


if __name__ == '__main__':
    main()
