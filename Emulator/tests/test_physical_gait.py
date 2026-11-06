"""Physical replay/inference contract tests. All generated samples are fixtures."""
import base64
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

import numpy as np

from gateway.neural_gait.contract import HISTORY_SCHEMA, HISTORY_SIZE, PENDING_SCHEMA, pending_rows, vector
from gateway.neural_gait.physical import (camera_intervals, measured_transition, recording_data,
    create_run, train_run, migrate_pending_inputs, publish, pending_input,
    demonstration_data, imitate_run)


def row(sample, stamp, *, consumed=None):
    values = np.zeros(HISTORY_SIZE, dtype='<f4')
    values[72] = 1.
    values[60:72] = 1.
    values[82] = .08
    return dict(robot_id='fixture', epoch=1, walk=2, model_id='abc123', checkpoint_id='initial',
        revision=0, feedback_revision=1, sample=sample,
        consumed_sample=sample-1 if consumed is None else consumed,
        observation_device_us=round(stamp*1e6), observation_received_at=stamp,
        action=[.1]*12, policy_observation=dict(schema=HISTORY_SCHEMA,
            encoding='float32-le-zlib-base64', values=base64.b64encode(zlib.compress(values.tobytes())).decode()))


def pose(stamp, x, *, heading=0, reference='map', interval=1.):
    return dict(robotId='fixture', epoch=1, frameId=str(stamp), calibrationId='fixture-calibration',
        referenceId=reference, receivedAtMonotonic=stamp, motionIntervalS=interval,
        available=True, coordinateOrigin='body', metricAccuracyVerified=False,
        position=dict(xMetres=x, yMetres=0., headingDegrees=heading))


def environment():
    from Emulator.tests.test_neural_gait_sensors import robot_fixture
    return dict(robot=robot_fixture(), reference_joint_deg=[0., 3.46, -21.63]*4,
        target_limits_deg=[[-90., 90.]]*12, foot_action_scale_mm=[30.,20.,30.],
        joint_speed_deg_s=60/.11, control_hz=33)


class PhysicalReplayTests(unittest.TestCase):
    def test_imitation_uses_original_inputs_contiguous_holdout_and_no_rewards(self):
        from gateway.neural_gait.physical import physical_environment
        from gateway.neural_gait.contract import foot_offsets
        import shutil
        config = physical_environment(environment())
        with tempfile.TemporaryDirectory() as root:
            recording = Path(root)/'recording'; recording.mkdir()
            examples = [row(i+1, 1+i/10) for i in range(10)]
            for r in examples:
                r['policy_observation'].update(schema=PENDING_SCHEMA, pending_actions=[])
                r['action'] = [0.]*12
                r['demonstration'] = dict(source='native-c', nominal_joint_deg=config['reference_joint_deg'])
                r['requested_foot_offset_mm'] = foot_offsets(r['action'], config['foot_action_scale_mm'])
            examples[-2]['revision'] = examples[-1]['revision'] = 2
            path = recording/'neural.jsonl'
            path.write_text(''.join(json.dumps(dict(value=r))+'\n' for r in examples))
            copied = Path(root)/'copied'; shutil.copytree(recording, copied)
            arrays, evidence = demonstration_data([recording, copied], model_id='abc123', environment=config)
            self.assertEqual(evidence['rows'], 10)
            self.assertFalse(evidence['reward_used'])
            np.testing.assert_array_equal(arrays[3], [False]*8+[True]*2)
            self.assertEqual([r['sample'] for r in evidence['sources']], list(range(1,11)))
            # A second trajectory is held out whole, rather than shuffling adjacent observations.
            examples[-3]['walk'] = examples[-2]['walk'] = examples[-1]['walk'] = 5
            path.write_text(''.join(json.dumps(dict(value=r))+'\n' for r in examples))
            arrays, evidence = demonstration_data([recording], model_id='abc123', environment=config)
            np.testing.assert_array_equal(arrays[3], [False]*7+[True]*3)
            examples[0]['requested_foot_offset_mm'][0] += 1
            path.write_text(''.join(json.dumps(dict(value=r))+'\n' for r in examples))
            with self.assertRaisesRegex(ValueError, 'action coordinates'):
                demonstration_data([recording], model_id='abc123', environment=config)

    def test_legacy_teacher_relabel_preserves_real_inputs_and_request_history(self):
        from gateway.neural_gait.physical import physical_environment, decode_observation
        from gateway.neural_gait.contract import foot_offsets
        from gateway.neural_gait.native import BodyModel
        source = environment()
        source['robot']['calibration'][4]['home_us'] = 765
        source['robot']['calibration'][5]['home_us'] = 1900
        source['target_limits_deg'] = [[-180., 180.]]*12
        config = physical_environment(source)
        native = BodyModel(config['robot'])
        raw = [0., -25.56, -117.68]*4
        try:
            original = (native.foot_offsets_for_angles(raw, config['reference_joint_deg']) /
                        np.asarray(config['foot_action_scale_mm'])).reshape(12).tolist()
            goal = native.target(raw, config['reference_joint_deg'], config['joint_speed_deg_s'], 0.)[1]
            corrected = (native.foot_offsets_for_angles(goal, config['reference_joint_deg']) /
                         np.asarray(config['foot_action_scale_mm'])).reshape(12)
        finally:
            native.close()
        self.assertFalse(np.allclose(original, corrected))
        with tempfile.TemporaryDirectory() as root:
            recording = Path(root)
            examples = [row(i+1, 1+i/10) for i in range(4)]
            pending = [[*original, .03, -.01]]
            for r in examples:
                r['action'] = original
                r['policy_observation'].update(schema=PENDING_SCHEMA, pending_actions=pending)
                r['demonstration'] = dict(source='native-c', nominal_joint_deg=raw)
                r['requested_foot_offset_mm'] = foot_offsets(original, config['foot_action_scale_mm'])
            path = recording/'neural.jsonl'
            path.write_text(''.join(json.dumps(dict(value=r))+'\n' for r in examples))
            before = path.read_bytes()
            arrays, evidence = demonstration_data([recording], model_id='abc123', environment=config)
            self.assertEqual(evidence['corrected_target_rows'], 4)
            np.testing.assert_allclose(arrays[1][0], corrected, atol=1e-7)
            np.testing.assert_array_equal(arrays[0][0], decode_observation(examples[0]['policy_observation']))
            self.assertEqual(arrays[2][0], pending)
            self.assertEqual(before, path.read_bytes())
            self.assertTrue(evidence['sources'][0]['expert_relabeled'])

    def test_imitation_publication_recovers_without_retraining_or_reward_replay(self):
        from gateway.neural_gait.redq import REDQLearner, NumpyActor
        from gateway.neural_gait.contract import foot_offsets
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)/'abc123'; create_run(run, environment(), algorithm='REDQ')
            config = json.loads((run/'manifest.json').read_text())['environment']
            recording = Path(root)/'recording'; recording.mkdir()
            examples = [row(i+1, 1+i/10) for i in range(10)]
            for r in examples:
                r['policy_observation'].update(schema=PENDING_SCHEMA, pending_actions=[])
                r['action'] = [0.]*12
                r['demonstration'] = dict(source='native-c', nominal_joint_deg=config['reference_joint_deg'])
                r['requested_foot_offset_mm'] = foot_offsets(r['action'], config['foot_action_scale_mm'])
            (recording/'neural.jsonl').write_text(''.join(json.dumps(dict(value=r))+'\n' for r in examples))
            with patch('gateway.neural_gait.physical.publish', side_effect=OSError('fixture publication failure')):
                with self.assertRaisesRegex(OSError, 'publication failure'):
                    imitate_run(run, [recording], 8, 'cpu')
            committed = (run/'learner.pt').read_bytes()
            result = imitate_run(run, [recording], 8, 'cpu')
            self.assertTrue(result['recovered_publication'])
            self.assertEqual(committed, (run/'learner.pt').read_bytes())
            learner = REDQLearner.load(run/'learner.pt', 'cpu')
            self.assertEqual(learner.extra_state['imitation_updates'], 8)
            self.assertEqual((learner.total_updates, learner.total_transitions, learner.replay_size), (0,0,0))
            checkpoint = json.loads((run/'checkpoints.json').read_text())[-1]
            actor = NumpyActor.load(run/checkpoint['policy'])
            arrays, _ = demonstration_data([recording], model_id='abc123', environment=config)
            np.testing.assert_allclose(actor.act(arrays[0], pending_actions=arrays[2]),
                learner.act(arrays[0], deterministic=True, pending_actions=arrays[2]), atol=1e-6)
            self.assertEqual(json.loads((run/'progress.json').read_text())['state'], 'ready')
            self.assertFalse(checkpoint['physical_qualified'])
            self.assertEqual(np.asarray(result['heldout_after']['foot_rmse_mm']).shape, (4,3))
            self.assertFalse((Path(root)/'selected.json').exists())
            all_fit = imitate_run(run, [recording], 2, 'cpu', fit_all=True)
            self.assertEqual((all_fit['training_rows'], all_fit['heldout_rows']), (10, 0))
            self.assertIsNone(all_fit['heldout_after'])
            self.assertIsNone(all_fit['heldout_before'])
            self.assertEqual(len(all_fit['training_ids']), 10)
            self.assertEqual(all_fit['heldout_ids'], [])

    def test_source_clock_reward_is_independent_of_receipt_jitter(self):
        first, second = row(1,10.), row(2,10.1)
        for item, received in ((first,101.), (second,103.)):
            item.update(observation_boot_id=71, observation_received_at=received)
        poses = [pose(100.,0.,interval=.3), pose(104.,.024,interval=.3)]
        for item, completed in zip(poses,(9900000,10200000)):
            item['attitude'] = dict(available=True, frame_completed_us=completed, boot_id=71)
        intervals = list(camera_intervals(poses))
        self.assertEqual(len(intervals),1)
        transition, evidence = measured_transition(first,second,intervals)
        self.assertAlmostEqual(transition[2],3.3,places=5)
        self.assertAlmostEqual(evidence['visual_seconds'],.1)
        self.assertAlmostEqual(evidence['displacement_body_m'][0],.008)
        self.assertIn('device frame-completion clock',evidence['attribution'])
        poses[0]['receivedAtMonotonic'], poses[1]['receivedAtMonotonic'] = 200.,201.
        second['observation_received_at'] = 300.
        repeated, _ = measured_transition(first,second,list(camera_intervals(poses)))
        for original, changed in zip(transition,repeated):
            np.testing.assert_array_equal(original,changed)

    def test_source_clock_rewards_do_not_fall_back_or_cross_boots(self):
        first, second = row(1,1.), row(2,1.1)
        first['observation_boot_id'] = second['observation_boot_id'] = 71
        poses = [pose(.9,0.,interval=.3),pose(1.2,.024,interval=.3)]
        with self.assertRaisesRegex(ValueError,'unknown_or_overlapping_visual_interval'):
            measured_transition(first,second,list(camera_intervals(poses)))
        for item, completed in zip(poses,(900000,1200000)):
            item['attitude'] = dict(available=True,frame_completed_us=completed,boot_id=72)
        with self.assertRaisesRegex(ValueError,'unknown_or_overlapping_visual_interval'):
            measured_transition(first,second,list(camera_intervals(poses)))
        poses[0]['attitude']['boot_id'] = 71
        self.assertEqual(list(camera_intervals(poses)),[])
        poses[1]['attitude']['boot_id'] = 71
        poses[1]['attitude']['available'] = False
        self.assertEqual(list(camera_intervals(poses)),[])

    def test_author_pink_noise_is_correlated_and_profile_preserves_buffer(self):
        from pink.cnrl import PinkNoiseProcess
        from gateway.neural_gait.client import walking_profile
        pink = PinkNoiseProcess((12,1000), rng=np.random.default_rng(47))
        samples = np.asarray([pink.sample() for _ in range(3000)])
        self.assertTrue(np.isfinite(samples).all())
        self.assertEqual(samples.shape, (3000,12))
        self.assertGreater(np.corrcoef(samples[:-1].ravel(), samples[1:].ravel())[0,1], .5)
        self.assertGreater(samples.max(), 2.)
        self.assertLess(samples.min(), -2.)
        profile = dict(source='neural',forward_m_s=.08,lateral_m_s=.04,yaw_rad_s=.5,exploration_buffer_steps=500)
        self.assertEqual(walking_profile(profile), profile)
        for value in (True, 1, 2.5, '1000'):
            with self.assertRaisesRegex(ValueError, 'exploration_buffer_steps'):
                walking_profile({**profile,'exploration_buffer_steps':value})

    def test_pending_reconstruction_uses_prior_decisions_not_future_receipts(self):
        first, second, third = row(1, 1, consumed=0), row(2, 1.1, consumed=0), row(3, 1.2, consumed=0)
        first['action'], second['action'] = [.2]*12, [.3]*12
        sent = {('fixture',1,2,1):1.12, ('fixture',1,2,2):1.22}
        # The first send followed the second sensor receipt during inference,
        # but is known before the second decision. The future second action is not.
        result = pending_input(second, [first], sent)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][:12], [.2]*12)
        self.assertAlmostEqual(result[0][12], .1)
        self.assertAlmostEqual(result[0][13], .02)
        self.assertEqual(len(pending_input(third, [first,second], sent)), 2)
        with self.assertRaisesRegex(ValueError, 'missing_pending_request_history'):
            pending_input(third, [second], sent)
        with self.assertRaisesRegex(ValueError, 'missing_pending_request_history'):
            pending_input(second, [first], {})
        # New packets retain the exact decision-time input, without reconstruction.
        third['policy_observation'].update(schema=PENDING_SCHEMA, pending_actions=result)
        self.assertEqual(pending_input(third, [], {}), result)
        self.assertEqual(len(pending_rows([result[0]]*257)), 257)

    def test_pending_migration_preserves_wrapped_replay_and_recovers_publication(self):
        from gateway.neural_gait.redq import REDQConfig, REDQLearner
        from gateway.neural_gait.artifacts import save_json
        from gateway.neural_gait.server import Runtime
        with tempfile.TemporaryDirectory() as root:
            run, recording = Path(root)/'abc123', Path(root)/'recording'
            run.mkdir(); recording.mkdir()
            config = dict(environment(), observation_schema=HISTORY_SCHEMA, execution_backend='physical')
            save_json(run/'manifest.json', dict(kind='physical-redq', schema=HISTORY_SCHEMA,
                action_contract='body-frame-foot-offsets-mm', environment=config))
            learner = REDQLearner(REDQConfig(observation_dim=HISTORY_SIZE, replay_capacity=7, batch_size=4), 'cpu')
            learner.save(run/'learner.pt'); publish(run, learner, None)
            requests = [row(i+1, 1+i/10, consumed=max(0,i-2)) for i in range(11)]
            (recording/'neural.jsonl').write_text(''.join(json.dumps(dict(value=r))+'\n' for r in requests))
            (recording/'poses.jsonl').write_text(''.join(json.dumps(dict(value=p))+'\n' for p in [pose(1,0),pose(2,.08)]))
            (recording/'commands.jsonl').write_text(''.join(json.dumps(dict(host_monotonic_s=r['observation_received_at']+.12,
                value=dict(t='walk_target',robot_id='fixture',epoch=1,walk=2,sample=r['sample'])))+'\n' for r in requests))
            train_run(run, [recording], 2, 'cpu')
            before = REDQLearner.load(run/'learner.pt', 'cpu')
            old = json.loads((run/'checkpoints.json').read_text())[-1]
            old_bytes = (run/old['policy']).read_bytes()
            checkpoint_bytes = (run/'learner.pt').read_bytes()
            commands = (recording/'commands.jsonl').read_bytes()
            (recording/'commands.jsonl').unlink()
            with self.assertRaisesRegex(ValueError, 'No new physical transitions|Missing causal recording'):
                migrate_pending_inputs(run)
            self.assertEqual((run/'learner.pt').read_bytes(), checkpoint_bytes)
            self.assertEqual(json.loads((run/'manifest.json').read_text())['schema'], HISTORY_SCHEMA)
            (recording/'commands.jsonl').write_bytes(commands)
            with patch('gateway.neural_gait.physical.publish', side_effect=OSError('fixture interrupted publication')):
                with self.assertRaisesRegex(OSError, 'fixture interrupted publication'):
                    migrate_pending_inputs(run)
            result = migrate_pending_inputs(run)
            self.assertTrue(result['recovered_publication'])
            after = REDQLearner.load(run/'learner.pt', 'cpu')
            self.assertEqual(after.config.pending_input_dim, 14)
            self.assertEqual((after.total_updates,after.total_transitions,after.replay_cursor), (2,10,3))
            self.assertEqual(after.extra_state['physical_imported'], before.extra_state['physical_imported'])
            for key in before.replay:
                np.testing.assert_array_equal(after.replay[key][:7], before.replay[key][:7])
            np.testing.assert_array_equal(before.act(before.replay['observations'][:7], deterministic=True),
                after.act(after.replay['observations'][:7], deterministic=True,
                          pending_actions=after.pending_replay['pending_actions'][:7]))
            self.assertEqual((run/old['policy']).read_bytes(), old_bytes)
            checkpoints = json.loads((run/'checkpoints.json').read_text())
            self.assertEqual(len(checkpoints), 3)
            migrate_pending_inputs(run)
            self.assertEqual(json.loads((run/'checkpoints.json').read_text()), checkpoints)
            runtime = Runtime(root)
            runtime.load('abc123', old['id'])
            self.assertEqual(runtime.environment['observation_schema'], HISTORY_SCHEMA)
            runtime.load('abc123', checkpoints[-1]['id'])
            self.assertEqual(runtime.environment['observation_schema'], PENDING_SCHEMA)
            from gateway.neural_gait.client import observation
            from gateway.neural_gait.contract import JOINTS
            source = dict(joints={name:dict(filtered_model_deg=0., velocity_deg_s=0.,
                feedback_usable=True, commanded_model_deg=0.) for name in JOINTS},
                imu=dict(orientation_wxyz=[1.,0.,0.,0.], angular_rate_rad_s=[0.,0.,0.],
                         acceleration_m_s2=[0.,0.,9.81]), feedback=dict(device_us=1000000))
            pending = [[.2]*12+[.03,.002]]*17
            packet = observation(source, runtime.environment, [.08,0,0], pending_actions=pending)
            with self.assertRaisesRegex(ValueError, 'pending action rows'):
                observation(source, runtime.environment, [.08,0,0])
            missing = dict(packet); missing.pop('pending_actions')
            with self.assertRaises(KeyError):
                runtime.infer(missing)
            with patch.object(runtime.model, 'act', wraps=runtime.model.act) as infer:
                output = runtime.infer(packet)
                self.assertEqual(infer.call_args.kwargs['pending_actions'], pending)
                self.assertEqual(len(output['action']), 12)
            noise = np.linspace(-2.,2.,12).tolist()
            expected = runtime.model.act(np.asarray(vector(packet), np.float32),
                deterministic=False, noise=noise, pending_actions=pending)
            np.testing.assert_array_equal(runtime.infer(packet, explore=True, noise=noise)['action'], expected)
            for invalid in ([0.]*11, [float('nan')]*12, [True]*12, ['1']*12):
                with self.assertRaisesRegex(ValueError, 'twelve finite'):
                    runtime.infer(packet, explore=True, noise=invalid)
            with self.assertRaisesRegex(ValueError, 'exploratory physical'):
                runtime.infer(packet, noise=noise)
            runtime.load('abc123', old['id'])
            legacy_packet = {**packet, 'schema':HISTORY_SCHEMA}
            legacy_packet.pop('pending_actions')
            legacy_expected = runtime.model.act(np.asarray(vector(legacy_packet), np.float32), deterministic=False, noise=noise)
            np.testing.assert_array_equal(runtime.infer(legacy_packet, explore=True, noise=noise)['action'], legacy_expected)
            later = Path(root)/'later'; later.mkdir()
            later_rows = [{**row(i+1, 3+i/10), 'walk':3} for i in range(4)]
            (later/'neural.jsonl').write_text(''.join(json.dumps(dict(value=r))+'\n' for r in later_rows))
            (later/'poses.jsonl').write_text(''.join(json.dumps(dict(value=p))+'\n' for p in [pose(3,0),pose(4,.08)]))
            train_run(run, [later], 2, 'cpu')
            progress = json.loads((run/'progress.json').read_text())
            self.assertEqual((progress['steps'],progress['transitions']), (4,13))
            migrate_pending_inputs(run)  # Idempotence must not restore the old migration selection.
            self.assertEqual(json.loads((run/'progress.json').read_text()), progress)

    def test_camera_distance_is_conserved_not_repeated_for_each_inference(self):
        intervals = list(camera_intervals([pose(1, 0), pose(2, .08), pose(2, .08)]))
        self.assertEqual(len(intervals), 1)
        results = [measured_transition(row(i+1, 1+i/10), row(i+2, 1+(i+1)/10), intervals)
                   for i in range(10)]
        self.assertAlmostEqual(sum(outcome['displacement_body_m'][0] for _, outcome in results), .08)
        self.assertAlmostEqual(sum(outcome['visual_seconds'] for _, outcome in results), 1.)
        self.assertAlmostEqual(sum(transition[2] for transition, _ in results), 33., places=4)
        self.assertTrue(all(not outcome['frames'][0]['metric_verified'] for _, outcome in results))

    def test_backward_and_stationary_measurements_cannot_earn_forward_progress(self):
        rewards = []
        for distance in (-.08, 0, .08):
            intervals = list(camera_intervals([pose(1, 0), pose(2, distance)]))
            rewards.append(measured_transition(row(1, 1), row(2, 2), intervals)[0][2])
        self.assertLess(rewards[0], 0)
        self.assertEqual(rewards[1], 0)
        self.assertGreater(rewards[2], 0)

    def test_reference_losses_missing_frames_and_invalid_consumption_remain_unknown(self):
        self.assertEqual(list(camera_intervals([pose(1, 0), pose(2, .08, reference='new')])), [])
        self.assertEqual(list(camera_intervals([pose(1, 0), pose(3, .08)])), [])
        intervals = list(camera_intervals([pose(1, 0), pose(2, .08)]))
        for change in ({'consumed_sample':2}, {'consumed_sample':-1}, {'walk':3}, {'feedback_revision':2}, {'epoch':2}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'ownership_or_consumption'):
                measured_transition(row(1, 1), {**row(2, 2), **change}, intervals)
        with self.assertRaisesRegex(ValueError, 'unknown_or_overlapping'):
            measured_transition(row(1, .9), row(2, 2), intervals)

    def test_delayed_requested_actions_keep_consecutive_inputs_and_conserve_distance(self):
        # Real trial ordering: consumption commonly trails the prior request by
        # one to three samples. A jump can leave a sent sample unobserved.
        observed_consumption = [0, 0, 1, 1, 2, 3, 3, 5, 6, 7, 9]
        rows = [row(i+1, 1+i/10, consumed=consumed) for i, consumed in enumerate(observed_consumption)]
        for i, request in enumerate(rows):
            request['action'] = [(i+1)/20]*12
            values = np.frombuffer(zlib.decompress(base64.b64decode(request['policy_observation']['values'])), dtype='<f4').copy()
            values[0] = (i+1)/100
            request['policy_observation']['values'] = base64.b64encode(zlib.compress(values.tobytes())).decode()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root/'neural.jsonl').write_text(''.join(json.dumps({'value':r})+'\n' for r in rows))
            (root/'poses.jsonl').write_text(''.join(json.dumps({'value':p})+'\n' for p in [pose(1,0),pose(2,.08)]))
            (root/'commands.jsonl').write_text(''.join(json.dumps({'host_monotonic_s':r['observation_received_at']+.004,
                'value':{'t':'walk_target', 'robot_id':r['robot_id'], 'epoch':r['epoch'],
                         'walk':r['walk'], 'sample':r['sample'], 'seq':100+i}})+'\n' for i,r in enumerate(rows)))
            (root/'events.jsonl').write_text(json.dumps({'value':{'t':'imu', 'robot_id':'fixture', 'epoch':1,
                'imu':{'motion':{'sequence':2, 'walk_source':'host', 'nominal_sample':4},
                       'joint_feedback':{'device_us':1650000}, 'received_monotonic_s':1.65}}})+'\n')
            arrays, evidence = recording_data([root], model_id='abc123',
                environment={**environment(), 'observation_schema':HISTORY_SCHEMA})
            self.assertEqual(evidence['transitions'], 10)
            np.testing.assert_array_equal(arrays[1], np.asarray([r['action'] for r in rows[:-1]], np.float32))
            np.testing.assert_allclose(arrays[0][:,0], np.arange(1,11)/100)
            np.testing.assert_array_equal(arrays[3][:-1], arrays[0][1:])
            self.assertAlmostEqual(evidence['seconds'], 1.)
            self.assertAlmostEqual(sum(r['displacement_body_m'][0] for r in evidence['reward_attribution']), .08)
            self.assertAlmostEqual(sum(r['visual_seconds'] for r in evidence['reward_attribution']), 1.)
            self.assertAlmostEqual(float(arrays[2].sum()), 33., places=4)
            self.assertFalse(evidence['policy_pending_request_inputs'])
            self.assertIn('not policy inputs', evidence['partial_observability'])
            delayed = evidence['reward_attribution'][5]['request_evidence']
            self.assertEqual((delayed['requested_sample'], delayed['consumed_sample_at_input'],
                              delayed['consumed_sample_at_next_input']), (6,3,3))
            pending = delayed['requests_not_yet_observed_consumed_at_input']
            self.assertEqual([p['sample'] for p in pending], [4,5])
            self.assertAlmostEqual(pending[0]['source_input_age_s'], .2)
            self.assertAlmostEqual(pending[0]['send_age_s'], .196)
            consumed = evidence['reward_attribution'][3]['request_evidence']['first_observed_consumption']
            self.assertEqual(consumed, {'device_us':1650000, 'received_monotonic_s':1.65, 'source':'imu telemetry'})
            self.assertIsNone(evidence['reward_attribution'][7]['request_evidence']['first_observed_consumption'],
                              'A sample absent from telemetry stays unobserved, not rejected or executed')
            self.assertTrue(all('ack' not in key for r in evidence['reward_attribution']
                                for key in r['request_evidence']))
            (root/'commands.jsonl').unlink()
            _, without_sends = recording_data([root], model_id='abc123',
                environment={**environment(), 'observation_schema':HISTORY_SCHEMA})
            self.assertIsNone(without_sends['reward_attribution'][5]['request_evidence']
                              ['requests_not_yet_observed_consumed_at_input'][0]['send_age_s'])

    def test_heading_projection_uses_camera_reference_not_end_frame_velocity(self):
        intervals = list(camera_intervals([pose(1, 0, heading=90), pose(2, .08, heading=90)]))
        _, outcome = measured_transition(row(1, 1), row(2, 2), intervals)
        self.assertAlmostEqual(outcome['displacement_body_m'][0], 0., places=6)
        self.assertAlmostEqual(outcome['displacement_body_m'][1], -.08)

    def test_final_sensor_outcome_distinguishes_failure_truncation_and_unknown(self):
        first, final = row(1, 1), row(2, 2)
        final.pop('action')
        final.pop('sample')
        final.update(outcome='failure', outcome_evidence={'kind':'tipped'})
        values = np.frombuffer(zlib.decompress(base64.b64decode(final['policy_observation']['values'])), dtype='<f4').copy()
        values[72:76] = [math.sqrt(.5), math.sqrt(.5), 0, 0]
        final['policy_observation']['values'] = base64.b64encode(zlib.compress(values.tobytes())).decode()
        transition, evidence = measured_transition(first, final, [])
        self.assertEqual(transition[4], 0., 'A known failed episode must not bootstrap future walking value')
        self.assertLess(transition[2], 0., 'Measured tilt still contributes when the camera interval is unavailable')
        self.assertEqual(evidence['outcome_evidence'], {'kind':'tipped'})
        self.assertFalse(evidence['visual_complete'])
        self.assertEqual(evidence['unmeasured_visual_seconds'], 1.)
        self.assertIsNone(evidence['displacement_body_m'], 'Missing visual movement is unknown, not zero distance')
        self.assertIsNone(evidence['turn_rad'])
        intervals = list(camera_intervals([pose(1, 0), pose(2, .08)]))
        truncated, evidence = measured_transition(first, {**final, 'outcome':'truncated'}, intervals)
        self.assertGreater(truncated[4], 0., 'Normal Finish/Stop/replacement truncations retain bootstrap')
        self.assertEqual(evidence['outcome'], 'truncated')
        with self.assertRaisesRegex(ValueError, 'unknown_outcome'):
            measured_transition(first, {**final, 'outcome':'unknown'}, intervals)

    def test_import_keeps_sensor_only_failure_without_claiming_unmeasured_distance(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            first, final = row(1, 1), row(2, 2)
            final.pop('action'); final.pop('sample')
            final.update(outcome='failure', outcome_evidence={'kind':'servo_stall'})
            (root/'neural.jsonl').write_text(''.join(json.dumps({'value':r})+'\n' for r in (first, final)))
            arrays, evidence = recording_data([root], model_id='abc123',
                environment={**environment(), 'observation_schema':HISTORY_SCHEMA})
            self.assertEqual(len(arrays[0]), 1)
            self.assertEqual(arrays[4].tolist(), [0.])
            self.assertEqual(evidence['outcomes'], {'failure':1})
            self.assertEqual(evidence['command_results'], [])
            self.assertFalse(evidence['metric_accuracy_verified'])
            self.assertIsNone(evidence['reward_attribution'][0]['displacement_body_m'])

    def test_delayed_terminal_keeps_requested_action_and_counts_final_sensor_frame_once(self):
        # Captured ordering: request 1036 starts with 1034 consumed, while its
        # final sensor endpoint has advanced to 1035, still behind request 1036.
        # Also cover an unchanged consumed target without substituting its action.
        for outcome in ('failure', 'truncated'):
            for consumed in (1034, 1035):
                with self.subTest(outcome=outcome, consumed=consumed), tempfile.TemporaryDirectory() as root:
                    root = Path(root)
                    first = row(1035, 1, consumed=1034)
                    requested = row(1036, 1.5, consumed=1034)
                    requested['action'] = [.9]*12
                    last_request = row(1037, 2, consumed=consumed)
                    final = {k:v for k,v in last_request.items() if k not in ('action', 'sample')}
                    final.update(outcome=outcome, outcome_evidence={'kind':'tipped'} if outcome == 'failure' else None)
                    rows = [first, requested, last_request, final]
                    (root/'neural.jsonl').write_text(''.join(json.dumps({'value':r})+'\n' for r in rows))
                    (root/'poses.jsonl').write_text(''.join(json.dumps({'value':p})+'\n' for p in [pose(1,0), pose(2,.08)]))
                    config = {**environment(), 'observation_schema':HISTORY_SCHEMA}
                    arrays, evidence = recording_data([root], model_id='abc123', environment=config)
                    np.testing.assert_array_equal(arrays[1], np.asarray([first['action'], requested['action']], np.float32))
                    self.assertGreater(arrays[4][0], 0.)
                    self.assertAlmostEqual(arrays[4][1], 0. if outcome == 'failure' else .99**(33*.5), places=6)
                    self.assertEqual(evidence['outcomes'], {'continuing':1, outcome:1})
                    self.assertEqual([x['sample'] for x in evidence['sources']], [1035, 1036])
                    ending = evidence['reward_attribution'][-1]
                    self.assertEqual(ending['action_semantics'], 'requested action in delayed actuator environment')
                    self.assertNotIn('held_consumed_sample', ending)
                    request = ending['request_evidence']
                    self.assertEqual(request['requested_sample'], 1036)
                    self.assertEqual(request['requested_action'], requested['action'])
                    self.assertEqual(request['consumed_sample_at_input'], 1034)
                    self.assertEqual(request['consumed_sample_at_next_input'], consumed)
                    self.assertIsNone(request['first_observed_consumption'], 'Do not invent consumption of the pending request')
                    self.assertAlmostEqual(evidence['seconds'], 1.)
                    self.assertAlmostEqual(sum(r['visual_seconds'] for r in evidence['reward_attribution']), 1.)
                    self.assertAlmostEqual(sum(r['displacement_body_m'][0] for r in evidence['reward_attribution']), .08)
                    self.assertAlmostEqual(float(arrays[2].sum()), 33., places=4)
                    # An earlier import omitted this final interval. Its ordinary
                    # transition identity stays unchanged and cannot be duplicated.
                    added, extra = recording_data([root], model_id='abc123', environment=config,
                        imported=[evidence['sources'][0]['id']])
                    self.assertEqual(extra['transitions'], 1)
                    self.assertEqual(extra['outcomes'], {outcome:1})
                    np.testing.assert_array_equal(added[1][0], np.asarray(requested['action'], np.float32))
                    if outcome == 'failure':
                        (root/'poses.jsonl').unlink()
                        _, unmeasured = recording_data([root], model_id='abc123', environment=config)
                        self.assertEqual(unmeasured['outcomes'], {'failure':1})
                        self.assertIsNone(unmeasured['reward_attribution'][0]['displacement_body_m'])
                        self.assertFalse(unmeasured['reward_attribution'][0]['visual_complete'])

    def test_training_reuses_replay_and_publishes_without_selecting_or_moving(self):
        from gateway.neural_gait.redq import REDQLearner
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)/'abc123'
            create_run(run, environment(), algorithm='REDQ')
            recording = Path(root)/'recording'
            recording.mkdir()
            def write(name, rows):
                (recording/name).write_text(''.join(json.dumps(dict(value=r))+'\n' for r in rows))
            write('neural.jsonl', [row(i+1, 1+i/10) for i in range(11)])
            write('poses.jsonl', [pose(1, 0), pose(2, .08)])
            summary = train_run(run, [recording], 2, 'cpu')
            self.assertEqual(summary['transitions'], 10)
            self.assertFalse((Path(root)/'selected.json').exists())
            learner = REDQLearner.load(run/'learner.pt', 'cpu')
            self.assertEqual(learner.total_updates, 2)
            self.assertEqual(len(learner.extra_state['physical_imported']), 10)
            with self.assertRaisesRegex(ValueError, 'No new physical transitions'):
                train_run(run, [recording], 2, 'cpu')
            import shutil
            copied = Path(root)/'copied-from-q6a'
            shutil.copytree(recording, copied)
            with self.assertRaisesRegex(ValueError, 'No new physical transitions'):
                train_run(run, [copied], 2, 'cpu')
            checkpoints = json.loads((run/'checkpoints.json').read_text())
            self.assertEqual(len(checkpoints), 2)
            self.assertFalse(checkpoints[-1]['physical_qualified'])

    def test_interrupted_publication_finishes_committed_training_without_retraining(self):
        from gateway.neural_gait.redq import REDQLearner
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)/'abc123'
            create_run(run, environment(), algorithm='REDQ')
            recording = Path(root)/'recording'
            recording.mkdir()
            (recording/'neural.jsonl').write_text(''.join(json.dumps(dict(value=row(i+1, 1+i/10)))+'\n' for i in range(11)))
            (recording/'poses.jsonl').write_text(''.join(json.dumps(dict(value=p))+'\n' for p in [pose(1,0),pose(2,.08)]))
            with patch('gateway.neural_gait.physical.publish', side_effect=OSError('fixture disk interruption')):
                with self.assertRaisesRegex(OSError, 'fixture disk interruption'):
                    train_run(run, [recording], 2, 'cpu')
            summary = train_run(run, [recording], 2, 'cpu')
            self.assertTrue(summary['recovered_publication'])
            learner = REDQLearner.load(run/'learner.pt', 'cpu')
            self.assertEqual(learner.total_updates, 2)
            self.assertEqual(learner.total_transitions, 10)
            self.assertEqual(len(json.loads((run/'checkpoints.json').read_text())), 2)

    def test_selected_actor_runtime_does_not_import_torch_simulator_or_training(self):
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)/'abc123'
            create_run(run, environment(), algorithm='REDQ')
            rows = json.loads((run/'checkpoints.json').read_text())
            (Path(root)/'selected.json').write_text(json.dumps(dict(model_id='abc123', checkpoint_id=rows[0]['id'])))
            script = '''
import sys
from gateway.neural_gait.server import Runtime
r = Runtime(sys.argv[1]); s = r.status()
assert s['kind'] == 'physical-redq'
assert not s['training_running']
assert s['runs'][0]['has_policy']
assert not any(name in sys.modules for name in ('torch','mujoco','stable_baselines3','gateway.neural_gait.training'))
'''
            result = subprocess.run([sys.executable, '-c', script, root], text=True, capture_output=True, env=os.environ)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
