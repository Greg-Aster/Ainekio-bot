"""Physical recordings -> desktop upstream SAC or retained REDQ updates. This module cannot move a robot.

Camera displacement is allocated over its measured frame interval, not reported
as per-action ground truth. Missing intervals stay unscored. Normal deployment
loads only the immutable NumPy actor, never this training lifecycle.
"""
import argparse
import base64
from collections import Counter
import fcntl
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import uuid4
import zlib

import numpy as np

from .artifacts import save_json
from .contract import (SCHEMAS, HISTORY_SCHEMA, HISTORY_SCHEMAS, PENDING_SCHEMA,
                       CRITIC_FEATURES, observation_size, foot_offsets, pending_rows)

KIND = 'physical-redq'
ACTION = 'body-frame-foot-offsets-mm'


def physical_environment(value):
    """Reuse the live Walk action/calibration contract, without simulated physics."""
    keys = ('robot', 'reference_joint_deg', 'target_limits_deg',
            'foot_action_scale_mm', 'joint_speed_deg_s', 'control_hz')
    result = {key: value[key] for key in keys}
    result.update(observation_schema=PENDING_SCHEMA, execution_backend='physical')
    if len(result['reference_joint_deg']) != 12 or not np.isfinite(result['reference_joint_deg']).all():
        raise ValueError('Expected twelve reference joint angles')
    limits = np.asarray(result['target_limits_deg'])
    if limits.shape != (12, 2) or not np.isfinite(limits).all() or np.any(limits[:, 1] <= limits[:, 0]):
        raise ValueError('Expected twelve ordered joint ranges')
    for key in ('joint_speed_deg_s', 'control_hz'):
        if not math.isfinite(result[key]) or result[key] <= 0:
            raise ValueError(key + ' must be finite and positive')
    # New physical runs cover the robot's kinematic workspace, rather than
    # inheriting a simulator's former 30/20/30mm search box. Loading an existing
    # run never calls this constructor; its saved action coordinates stay exact.
    from .native import derive_foot_action_scale
    result['foot_action_scale_mm'] = derive_foot_action_scale(
        result['robot'], result['reference_joint_deg'], result['target_limits_deg'])
    foot_offsets([0.] * 12, result['foot_action_scale_mm'])
    return result


def decode_observation(packet):
    if packet.get('encoding') != 'float32-le-zlib-base64' or packet.get('schema') not in SCHEMAS:
        raise ValueError('Missing original policy observation')
    values = np.frombuffer(zlib.decompress(base64.b64decode(packet['values'], validate=True)), dtype='<f4').copy()
    if values.shape != (observation_size(packet['schema']),) or not np.isfinite(values).all():
        raise ValueError('Invalid recorded policy input')
    if packet['schema'] in HISTORY_SCHEMAS and np.any(values[-CRITIC_FEATURES:]):
        raise ValueError('Physical observations cannot contain simulated critic features')
    if packet['schema'] == PENDING_SCHEMA:
        pending_rows(packet['pending_actions'])
    return values


def _rows(path, *, envelopes=False):
    if not path.exists():
        return []
    with path.open() as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
        return rows if envelopes else [row['value'] for row in rows]


def camera_intervals(poses):
    """Keep source-clock intervals; legacy receipt times retain their provenance."""
    previous = {}
    seen = set()
    for pose in sorted(poses, key=lambda p: p.get('receivedAtMonotonic', -1)):
        identity = (pose.get('robotId'), pose.get('epoch'), pose.get('referenceId'), pose.get('calibrationId'))
        attitude = pose.get('attitude')
        clock, boot = 'gateway-receipt', None
        stamp = pose.get('receivedAtMonotonic')
        if attitude is not None:
            completed, boot = attitude.get('frame_completed_us'), attitude.get('boot_id')
            if (not attitude.get('available') or type(completed) is not int or completed <= 0
                    or type(boot) is not int or boot < 0):
                continue
            clock, stamp = 'esp_timer', completed/1e6
            identity += (clock, boot)
        frame = (*identity, pose.get('frameId'))
        if frame in seen:
            continue
        seen.add(frame)
        prior_entry = previous.get(identity)
        previous[identity] = (pose, stamp)
        if prior_entry is None:
            continue
        prior, start = prior_entry
        if not all(p.get('available') and p.get('coordinateOrigin') == 'body'
                   and p.get('position') for p in (prior, pose)):
            continue
        end = stamp
        seconds = pose.get('motionIntervalS')
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end, seconds)) or seconds <= 0:
            continue
        if not math.isclose(end-start, seconds, rel_tol=1e-6, abs_tol=1e-6):
            continue  # A missing archived frame is not a longer measured interval.
        positions = [np.array([p['position'][k] for k in ('xMetres', 'yMetres')]) for p in (prior, pose)]
        headings = [math.radians(p['position']['headingDegrees']) for p in (prior, pose)]
        turn = math.atan2(math.sin(headings[1]-headings[0]), math.cos(headings[1]-headings[0]))
        yield dict(identity=identity, start=start, end=end, seconds=seconds,
                   clock=clock, boot_id=boot,
                   velocity=(positions[1]-positions[0])/seconds, heading=headings[0], turn=turn,
                   frame_id=pose['frameId'], metric_verified=bool(pose.get('metricAccuracyVerified')))


def transition_owner(row):
    return tuple(row.get(k) for k in ('robot_id', 'epoch', 'walk', 'model_id', 'checkpoint_id', 'revision', 'feedback_revision', 'observation_boot_id'))


def measured_transition(first, second, intervals, *, velocity_scale=.08, yaw_scale=.5, gamma=.99, hz=33.):
    """Time-integrated task reward from image displacement and measured attitude.

Forward progress is signed; standing still earns no travel credit. No torque,
foot contact, height or distance is inferred from joint commands. Dense credit
uses interval-average visual velocity and interpolated heading, explicitly an
estimate between camera observations. New records align device-clock frame
completion with device-clock feedback; legacy receipt attribution is preserved.
    """
    if 'action' not in first or first.get('outcome'):
        raise ValueError('not_an_action_transition')
    if second.get('outcome') == 'unknown':
        raise ValueError('unknown_outcome')
    if (transition_owner(first) != transition_owner(second)
            or second.get('consumed_sample', 0) < first.get('consumed_sample', 0)
            or second.get('consumed_sample', 0) > first['sample']):
        raise ValueError('ownership_or_consumption_gap')
    start, end = first['observation_received_at'], second['observation_received_at']
    dt = (second['observation_device_us']-first['observation_device_us'])/1e6
    clock, boot = 'gateway-receipt', None
    if 'observation_boot_id' in first or 'observation_boot_id' in second:
        boot = first.get('observation_boot_id')
        if type(boot) is not int or boot < 0 or boot != second.get('observation_boot_id'):
            raise ValueError('device_clock_identity_missing_or_changed')
        clock = 'esp_timer'
        start, end = first['observation_device_us']/1e6, second['observation_device_us']/1e6
    if end <= start or dt <= 0:
        raise ValueError('non_monotonic_sample')
    obs, nxt = decode_observation(first['policy_observation']), decode_observation(second['policy_observation'])
    if not np.array_equal(obs[82:85], nxt[82:85]):
        raise ValueError('command_changed')
    command = obs[82:85]
    covered, progress_reward = 0., 0.
    distance = np.zeros(2)
    turn = 0.
    frames = []
    for interval in intervals:
        if interval['identity'][:2] != (first['robot_id'], first['epoch']):
            continue
        if interval.get('clock', 'gateway-receipt') != clock:
            continue
        if clock == 'esp_timer' and interval.get('boot_id') != boot:
            continue
        lo, hi = max(start, interval['start']), min(end, interval['end'])
        if hi <= lo:
            continue
        duration = hi-lo
        heading = interval['heading'] + interval['turn']*((lo+hi)/2-interval['start'])/interval['seconds']
        c, s = math.cos(heading), math.sin(heading)
        velocity = np.array([[c, s], [-s, c]]) @ interval['velocity']
        yaw_rate = interval['turn']/interval['seconds']
        # Quadratic velocity tracking with its stationary baseline removed.
        # Exact requested velocity maximizes credit; backwards motion is negative.
        rate = (2*float(velocity @ command[:2])-float(velocity @ velocity))/velocity_scale**2
        rate += (2*yaw_rate*command[2]-yaw_rate**2)/yaw_scale**2
        progress_reward += rate*duration
        distance += velocity*duration
        turn += yaw_rate*duration
        covered += duration
        frames.append(dict(frame_id=interval['frame_id'], overlap_s=duration,
                           interval_s=interval['seconds'], metric_verified=interval['metric_verified']))
    terminal = second.get('outcome') == 'failure'
    visual_complete = math.isclose(covered, end-start, rel_tol=1e-5, abs_tol=1e-7)
    if not visual_complete and (not terminal or covered > end-start):
        raise ValueError('unknown_or_overlapping_visual_interval')
    # Roll/pitch cost uses the actual IMU quaternion. No artificial fall cutoff.
    w, x, y, z = nxt[72:76]
    upright = 1-2*(x*x+y*y)
    orientation_cost = (1-float(upright))*dt
    # Express integrated reward in nominal control-step units, matching the
    # discount's time base; slow transport cannot increase reward per second.
    reward = float((progress_reward-orientation_cost)*hz)
    return (obs, np.asarray(first['action'], np.float32), reward, nxt, 0. if terminal else gamma**(dt*hz)), dict(
        seconds=dt, visual_seconds=covered, displacement_body_m=distance.tolist() if covered else None,
        turn_rad=turn if covered else None,
        command=command.tolist(), reward=reward, orientation_cost=orientation_cost,
        action_semantics='requested action in delayed actuator environment',
        outcome=second.get('outcome', 'continuing'), outcome_evidence=second.get('outcome_evidence'),
        visual_complete=visual_complete, unmeasured_visual_seconds=max(0., end-start-covered),
        tracking_error_mean_deg=float(np.abs(nxt[:12]-nxt[24:36]).mean()*180/math.pi),
        measured_joint_speed_mean_deg_s=float(np.abs(nxt[12:24]).mean()*180/math.pi),
        usable_joint_fraction=float(nxt[60:72].mean()),
        frames=frames, attribution=('camera-interval-average; device frame-completion clock; not exposure-midpoint or per-action ground truth'
            if clock == 'esp_timer' else 'camera-interval-average; gateway-receipt clocks; not per-action ground truth'))


def request_key(row, sample):
    return row.get('robot_id'), row.get('epoch'), row.get('walk'), sample


def pending_input(observed, prior, sent):
    """Reconstruct only requests known before this serialized policy decision.

    A prior request can be sent after the current sensor packet arrived, while
    its preceding inference was still running. File/producer order, not the
    sensor receipt cutoff, determines what the next decision already knew.
    """
    if observed['policy_observation']['schema'] == PENDING_SCHEMA:
        return pending_rows(observed['policy_observation']['pending_actions'])
    consumed = observed.get('consumed_sample', 0)
    candidates = {row['sample']: row for row in prior if 'action' in row
                  and request_key(row, 0) == request_key(observed, 0) and row['sample'] > consumed}
    end = observed.get('sample', max(candidates, default=consumed)+1)
    result = []
    for sample in range(consumed+1, end):
        request = candidates.get(sample)
        stamp = sent.get(request_key(observed, sample))
        if request is None or stamp is None:
            raise ValueError('missing_pending_request_history')
        result.append([*request['action'],
            (observed['observation_device_us']-request['observation_device_us'])/1e6,
            stamp-observed['observation_received_at']])
    return pending_rows(result)


def request_evidence(first, second, prior, sent, consumed):
    """Retain transport diagnostics separately from the causal policy input."""
    def pending(observed, candidates):
        result = []
        for row in candidates:
            if ('action' not in row or transition_owner(row) != transition_owner(observed)
                    or row['sample'] <= observed.get('consumed_sample', 0)):
                continue
            issued = sent.get(request_key(row, row['sample']))
            if issued is not None and issued > observed['observation_received_at']:
                continue  # The next sensor packet can arrive before this send.
            result.append(dict(sample=row['sample'], action=row['action'],
                source_input_age_s=(observed['observation_device_us']-row['observation_device_us'])/1e6,
                send_age_s=None if issued is None else observed['observation_received_at']-issued))
        return result
    sample = first.get('sample')
    return dict(requested_sample=sample, requested_action=first.get('action'),
        consumed_sample_at_input=first.get('consumed_sample'),
        consumed_sample_at_next_input=second.get('consumed_sample'),
        first_observed_consumption=consumed.get(request_key(first, sample)),
        requests_not_yet_observed_consumed_at_input=pending(first, prior),
        requests_not_yet_observed_consumed_at_next_input=pending(second, [*prior, first]))


def recording_data(recordings, *, model_id, environment, imported=()):
    batches, evidence, sources, skipped = [], [], [], Counter()
    known = set(imported)
    for name in recordings:
        root = Path(name).expanduser().resolve()
        rows = _rows(root/'neural.jsonl')
        intervals = list(camera_intervals(_rows(root/'poses.jsonl')))
        selected = [row for row in rows if row.get('model_id') == model_id and row.get('policy_observation')]
        sent = {request_key(row['value'], row['value']['sample']):
                row['value'].get('sent_monotonic_s', row.get('host_monotonic_s'))
                for row in _rows(root/'commands.jsonl', envelopes=True)
                if row['value'].get('t') == 'walk_target'}
        consumed = {}
        for event in _rows(root/'events.jsonl'):
            imu = event.get('imu') or {}
            motion, feedback = imu.get('motion') or {}, imu.get('joint_feedback') or {}
            if event.get('t') == 'imu' and motion.get('walk_source') == 'host':
                key = (event.get('robot_id'), event.get('epoch'), motion.get('sequence'), motion.get('nominal_sample'))
                consumed.setdefault(key, dict(device_us=feedback.get('device_us'),
                    received_monotonic_s=imu.get('received_monotonic_s'), source='imu telemetry'))
        for row in selected:
            consumed.setdefault(request_key(row, row.get('consumed_sample')), dict(
                device_us=row['observation_device_us'], received_monotonic_s=row['observation_received_at'],
                source='recorded policy input'))
        snapshot = lambda row: (transition_owner(row), row['observation_device_us'], row.get('consumed_sample'))
        boundaries = {}
        priority = {'truncated':1, 'unknown':2, 'failure':3}
        for row in selected:
            if row.get('outcome') in priority:
                key = snapshot(row)
                if priority[row['outcome']] > priority.get(boundaries.get(key, {}).get('outcome'), 0):
                    boundaries[key] = row
        # Keep file order: sorting by clock could hide a reset or reorder ownership.
        for index, (recorded_first, recorded_second) in enumerate(zip(selected, selected[1:])):
            # A recording copied from Q6A to desktop is the same experience.
            identity = hashlib.sha256(json.dumps(recorded_first, sort_keys=True, allow_nan=False).encode()).hexdigest()
            if identity in known:
                continue
            first = boundaries.get(snapshot(recorded_first), recorded_first)
            second = boundaries.get(snapshot(recorded_second), recorded_second)
            try:
                allowed = ({HISTORY_SCHEMA, PENDING_SCHEMA} if environment['observation_schema'] == PENDING_SCHEMA
                           else {environment['observation_schema']})
                if first['policy_observation']['schema'] not in allowed or second['policy_observation']['schema'] not in allowed:
                    raise ValueError('observation_schema_changed')
                transition, outcome = measured_transition(first, second, intervals, hz=environment['control_hz'])
                if len(transition[0]) != observation_size(environment['observation_schema']):
                    raise ValueError('observation_schema_changed')
                if environment['observation_schema'] == PENDING_SCHEMA:
                    transition = (*transition,
                        pending_input(first, selected[:index], sent),
                        pending_input(second, selected[:index+1], sent))
            except (ValueError, KeyError, TypeError) as error:
                skipped[str(error)] += 1
                continue
            known.add(identity)
            outcome['request_evidence'] = request_evidence(recorded_first, recorded_second,
                selected[:index], sent, consumed)
            batches.append(transition)
            evidence.append(dict(id=identity, **outcome))
            sources.append(dict(id=identity, recording=str(root), robot_id=first['robot_id'],
                                epoch=first['epoch'], walk=first['walk'], sample=first['sample']))
    if not batches:
        raise ValueError('No new physical transitions with attributable requests and measured outcomes: '+json.dumps(dict(skipped)))
    columns = list(zip(*batches))
    arrays = [np.asarray(values, np.float32) for values in columns[:5]]
    arrays += [list(values) for values in columns[5:]]
    groups = {}
    for row in evidence:
        if row['visual_seconds'] <= 0:
            continue
        key = tuple(row['command'])
        group = groups.setdefault(key, dict(command=list(key), seconds=0., distance=np.zeros(2), turn=0.))
        group['seconds'] += row['visual_seconds']
        group['distance'] += row['displacement_body_m']
        group['turn'] += row['turn_rad']
    results = [dict(command=g['command'], seconds=g['seconds'],
                    measured_velocity_command_m_s=(g['distance']/g['seconds']).tolist(),
                    measured_yaw_rate_rad_s=g['turn']/g['seconds']) for g in groups.values()]
    return arrays, dict(transitions=len(batches), sources=sources, skipped=dict(skipped),
                       seconds=sum(row['seconds'] for row in evidence),
                       command_results=results,
                       tracking_error_mean_deg=float(np.mean([row['tracking_error_mean_deg'] for row in evidence])),
                       measured_joint_speed_mean_deg_s=float(np.mean([row['measured_joint_speed_mean_deg_s'] for row in evidence])),
                       outcomes=dict(Counter(row['outcome'] for row in evidence)),
                       policy_pending_request_inputs=environment['observation_schema'] == PENDING_SCHEMA,
                       partial_observability=('Policy includes every recorded sent request not yet observed consumed.'
                           if environment['observation_schema'] == PENDING_SCHEMA else
                           'Policy history contains consumed actions; pending requests are replay evidence only, not policy inputs.')
                           +' Consumption is observed telemetry, not an exact first-output timestamp. ACKs are not inferred.',
                       unmeasured_visual_seconds=sum(row['unmeasured_visual_seconds'] for row in evidence),
                       metric_accuracy_verified=bool(results) and all(
                           frame['metric_verified'] for row in evidence for frame in row['frames']),
                       reward_attribution=evidence)



def demonstration_data(recordings, *, model_id, environment):
    """Real pre-action inputs with calibrated expert targets, never invented sensors.

    Legacy pre-calibration labels are corrected deterministically through the run's
    recorded mapping. Original actions/history/pending requests remain untouched.
    Such relabeling does not claim the corrected target was physically executed.
    """
    from contextlib import closing
    from .native import BodyModel
    examples, sources, seen = [], [], set()
    corrected = 0
    label_contract = 'native-c-calibrated-target-v1'
    with closing(BodyModel(environment['robot'])) as native:
        for name in recordings:
            root = Path(name).expanduser().resolve()
            for row in _rows(root/'neural.jsonl'):
                teacher = row.get('demonstration', {})
                if (row.get('model_id') != model_id or 'action' not in row
                        or teacher.get('source') != 'native-c'):
                    continue
                identity = hashlib.sha256(json.dumps(row, sort_keys=True, allow_nan=False).encode()).hexdigest()
                if identity in seen:
                    continue
                packet = row['policy_observation']
                if packet['schema'] != environment['observation_schema']:
                    raise ValueError('Demonstration observation schema differs from the run')
                observed = decode_observation(packet)
                original = np.asarray(row['action'], np.float32)
                if original.shape != (12,) or not np.isfinite(original).all() or np.any(np.abs(original) > 1):
                    raise ValueError('Demonstration exceeds the recorded action domain')
                expected = foot_offsets(original, environment['foot_action_scale_mm'])
                if not np.allclose(expected, row['requested_foot_offset_mm'], atol=1e-4, rtol=1e-6):
                    raise ValueError('Demonstration action coordinates differ from the run')
                if any(teacher.get(key) for key in ('heading_enabled', 'balance_enabled', 'learned_corrections_enabled')):
                    raise ValueError('Teacher labels must precede physical feedback corrections')
                if teacher.get('label_contract') not in (None, label_contract):
                    raise ValueError('Unknown demonstrated target contract')
                raw = teacher['nominal_joint_deg']
                fitted = native.target(raw, environment['reference_joint_deg'], environment['joint_speed_deg_s'], 0.)
                if fitted is None:
                    raise ValueError('Recorded teacher target cannot be calibrated')
                target = fitted[1]  # Existing joint_fit goal, not ramped/quantized output.
                offsets = native.foot_offsets_for_angles(target, environment['reference_joint_deg'])
                action = (offsets / np.asarray(environment['foot_action_scale_mm'])).reshape(12).astype(np.float32)
                if np.any(np.abs(action) > 1):
                    raise ValueError('Calibrated teacher exceeds recorded action domain')
                relabeled = teacher.get('label_contract') is None
                if not relabeled and (not np.allclose(target, teacher['target_joint_deg'], atol=1e-4, rtol=1e-6)
                        or not np.allclose(action, original, atol=1e-6, rtol=1e-6)):
                    raise ValueError('Calibrated teacher provenance does not match its recorded action')
                corrected += int(relabeled and not np.allclose(action, original, atol=1e-6, rtol=1e-6))
                pending = pending_rows(packet['pending_actions'])
                seen.add(identity)
                examples.append((observed, action, pending))
                sources.append(dict(id=identity, recording=str(root), robot_id=row['robot_id'],
                    epoch=row['epoch'], walk=row['walk'], sample=row['sample'],
                    device_us=row['observation_device_us'],
                    owner=[row.get(key) for key in ('robot_id', 'epoch', 'walk', 'observation_boot_id')],
                    label_contract=label_contract, expert_relabeled=relabeled,
                    recorded_action=original.tolist(), target_action=action.tolist(),
                    target_joint_deg=target.tolist()))
    if len(examples) < 2:
        raise ValueError('Need recorded native-c demonstrations for training and held-out comparison')
    groups = list(dict.fromkeys(tuple(row['owner']) for row in sources))
    if len(groups) > 1:
        heldout = np.array([tuple(row['owner']) == groups[-1] for row in sources])
        split = 'last recorded Walk; other Walks used for fitting'
    else:
        boundary = min(len(examples)-1, max(1, int(len(examples)*.8)))
        heldout = np.arange(len(examples)) >= boundary
        split = 'final contiguous 20 percent; within-recording validation, not independent-session generalization'
    columns = list(zip(*examples))
    return (np.asarray(columns[0], np.float32), np.asarray(columns[1], np.float32),
            list(columns[2]), heldout), dict(sources=sources, rows=len(examples), split=split,
                training_rows=int((~heldout).sum()), heldout_rows=int(heldout.sum()),
                corrected_target_rows=corrected, label_contract=label_contract,
                reward_used=False, source='calibrated expert labels on real physical host Walk observations',
                qualification='Relabeled targets were not necessarily executed; observations and pending actions are unchanged')


def imitation_metrics(learner, observations, actions, pending, scale):
    predicted = learner.act(observations, deterministic=True, pending_actions=pending)
    expected = actions.reshape(-1, 4, 3)*np.asarray(scale)
    actual = predicted.reshape(-1, 4, 3)*np.asarray(scale)
    error = actual-expected
    return dict(rows=len(actions), action_rmse=float(np.sqrt(np.mean((predicted-actions)**2))),
        foot_rmse_mm=np.sqrt(np.mean(error**2, axis=0)).tolist(),
        foot_max_error_mm=np.max(np.abs(error), axis=0).tolist(),
        demonstrated_excursion_mm=np.ptp(expected, axis=0).tolist(),
        predicted_excursion_mm=np.ptp(actual, axis=0).tolist(),
        leg_order=['rear_left','rear_right','front_left','front_right'], axis_order=['x','y','z'],
        timing='predictions paired with original observation/action timestamps; no time warping',
        qualification='Target imitation only; not physical walking qualification')


def imitate_run(directory, recordings, updates, device='cuda', *, fit_all=False):
    """Fit and publish through the same learner transaction as physical REDQ."""
    from .redq import REDQLearner
    directory = Path(directory)
    with (directory/'training.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads((directory/'manifest.json').read_text())
        if manifest.get('kind') != KIND or type(updates) is not int or updates <= 0:
            raise ValueError('Select a physical REDQ run and positive update count')
        learner = REDQLearner.load(directory/'learner.pt', device=device)
        journal_path = directory/'physical-data.json'
        prior = json.loads(journal_path.read_text()) if journal_path.exists() else dict(imported=[], rounds=[])
        current = learner.extra_state.get('physical_round')
        checkpoints = json.loads((directory/'checkpoints.json').read_text())
        if current and (not any(row['id'] == current['id'] for row in prior['rounds'])
                or not any(row['id'] == current['checkpoint_id'] for row in checkpoints)):
            finish_round(directory, learner, prior)
            return dict(current['summary'], recovered_publication=True)
        arrays, evidence = demonstration_data(recordings, model_id=directory.name,
                                              environment=manifest['environment'])
        observations, actions, pending, heldout = arrays
        if fit_all:
            heldout = np.zeros(len(actions), dtype=bool)
            evidence.update(split='All supplied examples used for fitting; independent physical actor trial required',
                            training_rows=len(actions), heldout_rows=0)
        evidence['training_ids'] = [row['id'] for row, test in zip(evidence['sources'], heldout) if not test]
        evidence['heldout_ids'] = [row['id'] for row, test in zip(evidence['sources'], heldout) if test]
        train_pending = [p for p, test in zip(pending, heldout) if not test]
        test_pending = [p for p, test in zip(pending, heldout) if test]
        scale = manifest['environment']['foot_action_scale_mm']
        before = (imitation_metrics(learner, observations[heldout], actions[heldout], test_pending, scale)
                  if heldout.any() else None)
        save_json(directory/'progress.json', dict(kind=KIND, state='training', method='imitation',
            steps=learner.total_updates, demonstration_rows=len(actions), device=device))
        metrics = learner.imitate(observations[~heldout], actions[~heldout], updates,
                                  pending_actions=train_pending)
        after = (imitation_metrics(learner, observations[heldout], actions[heldout], test_pending, scale)
                 if heldout.any() else None)
        fit = imitation_metrics(learner, observations[~heldout], actions[~heldout], train_pending, scale)
        summary = {key: value for key, value in evidence.items() if key != 'sources'}
        summary.update(method='imitation', metrics=metrics, training=fit,
                       heldout_before=before, heldout_after=after)
        round_id = uuid4().hex
        learner.extra_state.setdefault('physical_imported', prior['imported'])
        learner.extra_state['physical_round'] = dict(id=round_id, device=device, updates=updates,
            method='imitation', metrics=metrics, evidence={**evidence, 'evaluation':summary}, summary=summary,
            checkpoint_id='imitation-%012d-%s' % (learner.extra_state['imitation_updates'], round_id[:8]))
        learner.save(directory/'learner.pt')
        finish_round(directory, learner, prior)
        return summary


def create_run(directory, environment, seed=0, algorithm='REDQ'):
    from .redq import REDQConfig, REDQLearner
    directory = Path(directory)
    config = physical_environment(environment)
    if algorithm != 'REDQ':
        raise ValueError('Unknown physical learning algorithm')
    learner = REDQLearner(REDQConfig(observation_dim=observation_size(config['observation_schema']),
                                   pending_input_dim=14, seed=seed), device='cpu')
    directory.mkdir(parents=True, exist_ok=True)
    save_json(directory/'manifest.json', dict(kind=KIND, schema=config['observation_schema'],
        action_contract=ACTION, environment=config, created_at=time.time(), algorithm=algorithm,
        evidence='untrained; no physical walking qualification'))
    learner.save(directory/'learner.pt')
    publish(directory, learner, evaluation=None)
    return dict(run_id=directory.name, state='untrained', movement_started=False)


def publish(directory, learner, evaluation, checkpoint_id=None):
    manifest = json.loads((directory/'manifest.json').read_text())
    checkpoint_id = checkpoint_id or '%012d-%s' % (learner.total_updates, uuid4().hex[:8])
    filename = 'actors/'+checkpoint_id+'.npz'
    (directory/'actors').mkdir(exist_ok=True)
    if not (directory/filename).exists():
        learner.export_actor(directory/filename, metadata=dict(model_id=directory.name, checkpoint_id=checkpoint_id,
            environment=manifest['environment'], action_contract=ACTION))
    rows_path = directory/'checkpoints.json'
    rows = json.loads(rows_path.read_text()) if rows_path.exists() else []
    if not any(row['id'] == checkpoint_id for row in rows):
        rows.append(dict(id=checkpoint_id, policy=filename, steps=learner.total_updates,
                         evaluation=evaluation or {}, physical_qualified=False))
    save_json(rows_path, rows)
    save_json(directory/'progress.json', dict(state='ready' if learner.total_updates or learner.extra_state.get('imitation_updates') else 'untrained',
        kind=KIND, steps=learner.total_updates, imitation_updates=learner.extra_state.get('imitation_updates', 0),
        transitions=learner.total_transitions,
        selected_checkpoint_id=checkpoint_id, evaluation=evaluation,
        qualification='Recorded experience is not an evaluation of the updated actor'))


def finish_round(directory, learner, prior):
    """Complete publication from the atomically committed learner after a crash."""
    current = learner.extra_state['physical_round']
    prior['imported'] = learner.extra_state['physical_imported']
    save_json(directory/('physical-round-'+current['id']+'.json'), current['evidence'])
    if not any(row['id'] == current['id'] for row in prior['rounds']):
        prior['rounds'].append({key: value for key, value in current.items() if key != 'evidence'})
    save_json(directory/'physical-data.json', prior)
    publish(directory, learner, current['summary'], current['checkpoint_id'])


def finish_pending_migration(directory, learner):
    """Recover sidecars from the atomically committed learner transaction."""
    migration = learner.extra_state['pending_input_migration']
    if json.loads((directory/'manifest.json').read_text())['schema'] != PENDING_SCHEMA:
        save_json(directory/'manifest.json', migration['manifest'])
    checkpoints = json.loads((directory/'checkpoints.json').read_text())
    progress = json.loads((directory/'progress.json').read_text())
    identifier = migration['checkpoint_id']
    if (not any(row['id'] == identifier for row in checkpoints)
            or checkpoints[-1]['id'] == identifier and progress.get('selected_checkpoint_id') != identifier):
        publish(directory, learner, dict(migration='pending action inputs',
            transitions_preserved=learner.replay_size, training_performed=False), identifier)


def migrate_pending_inputs(directory, *, recordings=None, device='cpu'):
    """Explicit, lossless v5 replay/learner upgrade; never selects or trains it.

    The saved original observations and rewards must agree exactly with current
    replay. Missing causal recordings are a migration error, not empty inputs.
    """
    from .redq import REDQLearner
    directory = Path(directory)
    with (directory/'training.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        learner = REDQLearner.load(directory/'learner.pt', device=device)
        if learner.extra_state.get('pending_input_migration'):
            finish_pending_migration(directory, learner)
            return dict(migrated=True, recovered_publication=True, training_performed=False)
        manifest = json.loads((directory/'manifest.json').read_text())
        if manifest.get('kind') != KIND or manifest.get('schema') != HISTORY_SCHEMA:
            raise ValueError('Pending-input migration requires a physical v5 run')
        imported = learner.extra_state.get('physical_imported', [])
        if len(imported) != learner.total_transitions or len(set(imported)) != len(imported):
            raise ValueError('Replay import provenance does not match learner transitions')
        config = dict(manifest['environment'], observation_schema=PENDING_SCHEMA)
        retained = imported[max(0, learner.total_transitions-learner.replay_size):]
        pending, next_pending = [None]*learner.replay_size, [None]*learner.replay_size
        if retained:
            journal_path = directory/'physical-data.json'
            journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'rounds':[]}
            sources = []
            for item in journal['rounds']:
                sources += json.loads((directory/('physical-round-'+item['id']+'.json')).read_text())['sources']
            current = learner.extra_state.get('physical_round')
            if current:
                sources += current['evidence']['sources']
            paths = list(dict.fromkeys(str(Path(p).expanduser().resolve()) for p in (
                recordings if recordings is not None else [source['recording'] for source in sources])))
            arrays, evidence = recording_data(paths, model_id=directory.name, environment=config)
            by_id = {source['id']: index for index, source in enumerate(evidence['sources'])}
            start = learner.total_transitions-learner.replay_size
            keys = ('observations', 'actions', 'rewards', 'next_observations', 'discounts')
            for chronological, identity in enumerate(retained, start):
                if identity not in by_id:
                    raise ValueError('Missing causal recording for retained replay '+identity)
                index, slot = by_id[identity], chronological % learner.config.replay_capacity
                for column, key in enumerate(keys):
                    original = learner.replay[key][slot]
                    rebuilt = np.asarray(arrays[column][index], np.float32).reshape(original.shape)
                    if not np.array_equal(rebuilt, original):
                        raise ValueError('Migration would change original replay '+key+' for '+identity)
                pending[slot], next_pending[slot] = arrays[5][index], arrays[6][index]
        learner.upgrade_pending_inputs(pending, next_pending)
        checkpoint_id = '%012d-%s' % (learner.total_updates, uuid4().hex[:8])
        learner.extra_state['pending_input_migration'] = dict(
            source_schema=HISTORY_SCHEMA, manifest={**manifest, 'schema':PENDING_SCHEMA, 'environment':config},
            checkpoint_id=checkpoint_id)
        # This single commit owns weights, optimizer, RNG, replay, provenance and
        # publication intent. A failed sidecar write is recoverable on rerun.
        learner.save(directory/'learner.pt')
        finish_pending_migration(directory, learner)
        return dict(migrated=True, transitions_preserved=learner.replay_size,
                    checkpoint_id=checkpoint_id, training_performed=False)


def train_run(directory, recordings, updates, device='cuda'):
    directory = Path(directory)
    with (directory/'training.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads((directory/'manifest.json').read_text())
        if manifest.get('kind') != KIND or type(updates) is not int or updates <= 0:
            raise ValueError('Select a physical REDQ run and positive update count')
        journal_path = directory/'physical-data.json'
        prior = json.loads(journal_path.read_text()) if journal_path.exists() else dict(imported=[], rounds=[])
        from .redq import REDQLearner as Learner
        learner = Learner.load(directory/'learner.pt', device=device)
        migration = learner.extra_state.get('pending_input_migration')
        if migration:
            finish_pending_migration(directory, learner)
            manifest = json.loads((directory/'manifest.json').read_text())
        current = learner.extra_state.get('physical_round')
        checkpoints = json.loads((directory/'checkpoints.json').read_text())
        progress = json.loads((directory/'progress.json').read_text())
        recovered = current is not None and (not any(row['id'] == current['id'] for row in prior['rounds'])
            or not any(row['id'] == current['checkpoint_id'] for row in checkpoints)
            or not any(row['id'] == progress.get('selected_checkpoint_id') for row in checkpoints))
        if recovered:
            finish_round(directory, learner, prior)
        # Import identities belong to the learner transaction, so an interrupted
        # journal write cannot duplicate already committed experience.
        imported = learner.extra_state.get('physical_imported', prior['imported'])
        try:
            arrays, evidence = recording_data(recordings, model_id=directory.name,
                environment=manifest['environment'], imported=imported)
        except ValueError as error:
            if recovered and str(error).startswith('No new physical transitions'):
                return dict(current['summary'], recovered_publication=True)
            raise
        learner.add_transitions(*arrays[:5], **(dict(pending_actions=arrays[5],
            next_pending_actions=arrays[6]) if len(arrays) == 7 else {}))
        learner.extra_state['physical_imported'] = [*imported, *(row['id'] for row in evidence['sources'])]
        save_json(directory/'progress.json', dict(kind=KIND, state='training', steps=learner.total_updates,
                                                  new_transitions=evidence['transitions'], device=device))
        metrics = learner.update(updates)
        summary = {key: value for key, value in evidence.items() if key not in ('sources', 'reward_attribution')}
        round_id = uuid4().hex
        learner.extra_state['physical_round'] = dict(id=round_id, device=device, updates=updates,
            metrics=metrics, evidence=evidence, summary=summary,
            checkpoint_id='%012d-%s' % (learner.total_updates, round_id[:8]))
        learner.save(directory/'learner.pt')
        finish_round(directory, learner, prior)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--create-config')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--algorithm', choices=('REDQ',), default='REDQ')
    parser.add_argument('--recordings', nargs='+')
    parser.add_argument('--updates', type=int)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--migrate-pending', action='store_true')
    parser.add_argument('--imitate', action='store_true')
    parser.add_argument('--fit-all', action='store_true')
    args = parser.parse_args()
    try:
        if args.migrate_pending:
            result = migrate_pending_inputs(args.directory, recordings=args.recordings, device=args.device)
        elif args.imitate:
            imitate_run(Path(args.directory), args.recordings, args.updates, args.device, fit_all=args.fit_all)
        elif args.create_config:
            create_run(Path(args.directory), json.loads(Path(args.create_config).read_text()), args.seed, args.algorithm)
        else:
            train_run(Path(args.directory), args.recordings, args.updates, args.device)
    except Exception as error:
        save_json(Path(args.directory)/'progress.json', dict(kind=KIND, state='error', error=str(error)))
        raise


if __name__ == '__main__':
    main()
