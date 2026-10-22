"""Explicit host-side search of the P4's compact walking policy.

Training proposes policies; existing body-control owners execute trials. This
module never writes PWM, sends movement, resets the robot or runs in firmware.
Results must include measured progress and repeated comparisons. Tracking error
alone is not the reward. The next search centre is distinct from the best policy
actually evaluated, and neither is described as globally optimal.

Paired parameter perturbations follow the random-search policy-optimization
approach of Mania, Guy and Recht (https://arxiv.org/abs/1803.07055). Feature scales
are fixed by the P4 contract; exploration scales and objective weights are
explicit training settings, not actuator limits.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import struct
from datetime import datetime
from pathlib import Path

from .gait_learning import model_identity


def profile_signature(profile):
    value = 2166136261
    for byte in struct.pack('<33f', *profile):
        value = ((value ^ byte)*16777619) & 0xffffffff
    return value


def recorded_metrics(batches, visual, model=None):
    """Score evidence from the existing trace and visual-measurement owners.

    Tracking is against the applied target, including the learned displacement;
    penalizing error to the old uncorrected gait would reward preserving it.
    This estimates kinematic following, not torque or electrical efficiency.
    """
    import numpy as np
    segments = visual.get('visual_motion', {}).get('segments', [])
    if visual.get('distance_m') is None or len(segments) != 1 or segments[0].get('frames', 0) < 2:
        raise ValueError('Metric visual progress is unavailable; tracking is not a substitute')
    segment = segments[0]
    start = datetime.fromisoformat(segment['first_observed_at'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(segment['last_observed_at'].replace('Z', '+00:00'))
    elapsed = (end-start).total_seconds()
    if elapsed <= 0:
        raise ValueError('Visual endpoint times must advance')
    errors, tilts, seen, contexts = [], [], set(), set()
    for batch in batches:
        records = batch['records']
        if records[-1].get('lost'):
            raise ValueError('Trace loss prevents a complete policy evaluation')
        header = records[0]
        for event in records[1:-1]:
            policy = event.get('policy') or {}
            if event.get('kind') != 'tracking' or not policy.get('eligible', event.get('eligible')):
                continue
            key = header['boot_id'], header['session'], event['sequence']
            if key in seen:
                continue
            seen.add(key)
            if not policy.get('usable') or policy.get('phase', 0) < 2:
                continue
            contexts.add((policy.get('gait_signature', policy['signature']), header['boot_id'], event['command_sequence']))
            if model and model['schema'] == 'gait_learning_v4' and (
                    policy.get('gait_signature') != model['signature'] or
                    policy.get('profile_signature') != profile_signature(model['gait_profile'])):
                raise ValueError('Recorded command did not select the evaluated gait profile/context')
            features = np.asarray(policy['features'], dtype=float).reshape(4, 8)
            tilts.append(features[0, 3:5]*.1)
            for leg, observed in enumerate(event['legs']):
                if event['valid_mask'] & (1 << leg) and observed['phase'] >= 2:
                    errors.append(np.asarray(observed['target_mm']) + observed['correction_mm'] - observed['measured_mm'])
    if len(contexts) != 1 or not errors or not tilts:
        raise ValueError('Evaluation needs one recorded command with calibrated policy measurements')
    result = {'forward_m_s': segment['forward_m']/elapsed,
              'tilt_rms_rad': float(np.sqrt(np.mean(np.square(tilts)))),
              'actuator_error_rms_mm': float(np.sqrt(np.mean(np.square(errors))))}
    if not all(math.isfinite(v) for v in result.values()):
        raise ValueError('Recorded metrics must be finite')
    return result


def vector(model):
    import numpy as np
    if model.get('schema') not in ('gait_learning_v3', 'gait_learning_v4'):
        raise ValueError('Training requires a sensor-conditioned policy')
    periodic = np.asarray(model['coefficients'], dtype=float)
    feedback = np.asarray(model['feedback_coefficients'], dtype=float)
    if periodic.shape != (60,) or feedback.shape != (96,):
        raise ValueError('Expected 60 periodic and 96 sensor coefficients')
    result = np.concatenate((periodic, feedback))
    if model['schema'] == 'gait_learning_v4':
        command, profile = np.asarray(model['command_coefficients'], dtype=float), np.asarray(model['gait_profile'], dtype=float)
        if command.shape != (48,) or profile.shape != (33,):
            raise ValueError('Version 4 needs 48 command coefficients and 33 gait-profile parameters')
        result = np.concatenate((result, command, profile))
    if not np.isfinite(result).all():
        raise ValueError('Policy coefficients must be finite')
    return result


def with_vector(model, values):
    import numpy as np
    # Hash and compare the actual float32 weights that the P4 will execute.
    values = np.asarray(values, dtype=np.float32)
    count = 237 if model['schema'] == 'gait_learning_v4' else 156
    if values.shape != (count,) or not np.isfinite(values).all():
        raise ValueError(f'Expected {count} finite float32 policy parameters')
    result = copy.deepcopy(model)
    result['coefficients'] = values[:60].tolist()
    result['feedback_coefficients'] = values[60:156].tolist()
    if model['schema'] == 'gait_learning_v4':
        result['command_coefficients'] = values[156:204].tolist()
        result['gait_profile'] = values[204:].tolist()
    result['id'] = model_identity(result)
    return result


def start(model, *, periodic_scale_mm, feedback_scale_mm, directions, step_size, weights, seed,
          command_scale_mm=None, gait_scales=None):
    """Return serializable training state. Nothing is installed or moved."""
    vector(model)
    if any(not math.isfinite(v) or v < 0 for v in (periodic_scale_mm, feedback_scale_mm)) or not math.isfinite(step_size) or step_size <= 0:
        raise ValueError('Exploration scales must be nonnegative and optimizer step positive')
    scales = [periodic_scale_mm]*60 + [feedback_scale_mm]*96
    if model['schema'] == 'gait_learning_v4':
        if command_scale_mm is None or not math.isfinite(command_scale_mm) or command_scale_mm < 0 or gait_scales is None or len(gait_scales) != 33 or any(not math.isfinite(v) or v < 0 for v in gait_scales):
            raise ValueError('Version 4 needs nonnegative command exploration and 33 explicit gait-profile scales')
        scales += [command_scale_mm]*48 + list(gait_scales)
    if not any(scales):
        raise ValueError('At least one parameter must vary during training')
    if type(directions) is not int or directions < 1:
        raise ValueError('At least one search direction is needed')
    required = {'forward_m_s', 'tilt_rms_rad', 'actuator_error_rms_mm'}
    if set(weights) != required or not all(math.isfinite(v) for v in weights.values()):
        raise ValueError('Specify speed, tilt and shaft-derived command-error objective weights')
    if weights['forward_m_s'] <= 0:
        raise ValueError('The walking objective must reward measured forward progress')
    parent = with_vector(model, vector(model))
    return {'schema': 'gait_training_v1', 'generation': 0, 'seed': int(seed),
            'centre': parent, 'incumbent': parent, 'incumbent_evidence': None,
            'scales': scales,
            'directions': directions, 'step_size': step_size, 'weights': dict(weights), 'history': []}


def propose(state):
    """Deterministic mirrored candidates, plus centre and current incumbent."""
    import numpy as np
    rng = np.random.default_rng(np.random.SeedSequence([state['seed'], state['generation']]))
    directions = rng.normal(size=(state['directions'], len(state['scales'])))
    centre, scales = vector(state['centre']), np.asarray(state['scales'])
    candidates = {m['id']: copy.deepcopy(m) for m in (state['incumbent'], state['centre'])}
    pairs = []
    for direction in directions:
        pair = []
        for sign in (1, -1):
            model = with_vector(state['centre'], centre+sign*scales*direction)
            candidates[model['id']] = model
            pair.append(model['id'])
        pairs.append(pair)
    return {'generation': state['generation'], 'centre_id': state['centre']['id'],
            'incumbent_id': state['incumbent']['id'], 'candidates': list(candidates.values()),
            'pairs': pairs, 'directions': directions.tolist()}


def reward(metrics, weights):
    """Missing metric distance is unknown, never zero or inferred from joints."""
    if any(not isinstance(metrics.get(k), (int, float)) or not math.isfinite(metrics[k]) for k in weights):
        raise ValueError('Measured progress, tilt and shaft command error are required for scoring')
    return sum(metrics[k]*w for k, w in weights.items())


def advance(state, generation, trials):
    """Consume repeated, matched-block evaluations without auto-installing.

    Each trial identifies its candidate, comparison block, recording and measured
    metrics. Every candidate is compared in the same blocks to expose run-to-run
    variation. Report the paired differences and their uncertainty, rather than
    treating the best single noisy run as an optimum. An incomplete evaluation
    leaves the input state untouched and has no effect on robot motion.
    """
    import numpy as np
    expected = propose(state)
    if generation != expected:
        raise ValueError('Candidate generation does not match this training state')
    models = {m['id']: m for m in generation['candidates']}
    scores = {key: {} for key in models}
    recordings = set()
    for trial in trials:
        key, block, recording = trial['model_id'], str(trial['block']), trial['recording']
        if key not in scores or block in scores[key] or not recording or recording in recordings:
            raise ValueError('Each candidate/block needs a distinct recorded trial')
        scores[key][block] = reward(trial['metrics'], state['weights'])
        recordings.add(recording)
    blocks = set(scores[state['incumbent']['id']])
    if len(blocks) < 2 or any(set(values) != blocks for values in scores.values()):
        raise ValueError('Repeat every candidate and incumbent in the same comparison blocks')
    order = sorted(blocks)
    base = np.array([scores[state['incumbent']['id']][b] for b in order])
    means, comparisons = {}, []
    for key, values in scores.items():
        sample = np.array([values[b] for b in order]);delta = sample-base
        means[key] = float(sample.mean())
        comparisons.append({'model_id': key, 'mean_reward': means[key],
                            'paired_improvements': delta.tolist(),
                            'mean_improvement': float(delta.mean()),
                            'improvement_standard_error': float(delta.std(ddof=1)/math.sqrt(len(delta)))})
    winner = max(means, key=means.get)
    # Keep the incumbent on a tie. A proposed gradient step is never promoted
    # here: it has not been evaluated on the robot.
    if means[winner] <= means[state['incumbent']['id']]:
        winner = state['incumbent']['id']
    differences = np.array([means[plus]-means[minus] for plus, minus in generation['pairs']])
    pair_rewards = [means[key] for pair in generation['pairs'] for key in pair]
    spread = float(np.std(pair_rewards))
    centre = vector(state['centre'])
    if spread > 0:
        centre += state['step_size']*np.asarray(state['scales'])*(differences @ np.asarray(generation['directions']))/(len(differences)*spread)
    result = copy.deepcopy(state)
    result['generation'] += 1
    result['centre'] = with_vector(state['centre'], centre)
    result['incumbent'] = copy.deepcopy(models[winner])
    report = {'generation': state['generation'], 'selected_model_id': winner,
              'comparisons': comparisons, 'trials': copy.deepcopy(trials), 'global_optimum_demonstrated': False}
    result['incumbent_evidence'] = report
    result['history'].append(report)
    return result


def export_model(state):
    """Export the evaluated incumbent for the existing model-install API/UI."""
    return {'model': copy.deepcopy(state['incumbent']),
            'training': {'method': 'paired physical policy search',
                         'generations': state['generation'], 'objective_weights': copy.deepcopy(state['weights']),
                         'evaluation': copy.deepcopy(state['incumbent_evidence']),
                         'global_optimum_demonstrated': False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='op', required=True)
    init = commands.add_parser('start')
    init.add_argument('model', type=Path)
    init.add_argument('--periodic-scale-mm', type=float, required=True)
    init.add_argument('--feedback-scale-mm', type=float, required=True)
    init.add_argument('--command-scale-mm', type=float)
    init.add_argument('--gait-scales', type=Path, help='33 exploration scales in gait_profile_fields order')
    init.add_argument('--directions', type=int, required=True)
    init.add_argument('--step-size', type=float, required=True)
    init.add_argument('--weights', type=Path, required=True)
    init.add_argument('--seed', type=int, required=True)
    ask = commands.add_parser('propose');ask.add_argument('state', type=Path)
    tell = commands.add_parser('advance');tell.add_argument('state', type=Path)
    tell.add_argument('generation', type=Path);tell.add_argument('trials', type=Path)
    export = commands.add_parser('export');export.add_argument('state', type=Path)
    for command in (init, ask, tell, export):
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    def read(path):
        return json.loads(path.read_text())
    if args.op == 'start':
        model = read(args.model)
        result = start(model.get('model', model), periodic_scale_mm=args.periodic_scale_mm,
                       feedback_scale_mm=args.feedback_scale_mm, directions=args.directions,
                       step_size=args.step_size, weights=read(args.weights), seed=args.seed,
                       command_scale_mm=args.command_scale_mm, gait_scales=read(args.gait_scales) if args.gait_scales else None)
    elif args.op == 'propose':
        result = propose(read(args.state))
    elif args.op == 'export':
        result = export_model(read(args.state))
    else:
        result = advance(read(args.state), read(args.generation), read(args.trials))
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False);stream.write('\n')


if __name__ == '__main__':
    main()
