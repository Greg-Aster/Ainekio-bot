import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from gateway.gait_response import examples, fit, evaluate, train_and_evaluate, walking_imu_summary


def trajectory(period=15, count=150):
    rows = []
    position = 1500.
    for i in range(count):
        command = 1500.+350.*(1 if (i//period)%2 else -1)
        velocity = (command-position)*8.
        rows.append({'joint_id': 1, 'joint': 'rear_left_carrier', 'sampled_us': i*20000,
                     'boot_id': 1, 'session': 1, 'segment': 0, 'revision': 1,
                     'command_sequence': 2, 'scan': i+1, 'valid': True, 'walking': True,
                     'command_us': command, 'raw_us': position, 'filtered_us': position,
                     'velocity_us_s': velocity})
        position += velocity*.02
    return rows


class ResponseTests(unittest.TestCase):
    def test_inputs_never_use_future_commands_or_measurements(self):
        rows = trajectory()
        original = next(r for r in examples(rows) if r['sampled_us'] == 200000)
        altered = copy.deepcopy(rows)
        for r in altered:
            if r['sampled_us'] > 200000:
                r['command_us'] += 500
                r['raw_us'] += 200
        changed = next(r for r in examples(altered) if r['sampled_us'] == 200000)
        self.assertEqual(original['state_features'], changed['state_features'])
        self.assertEqual(original['command_features'], changed['command_features'])
        self.assertNotEqual(original['future_raw_us'], changed['future_raw_us'])

    def test_no_examples_cross_missing_scan_invalid_sample_or_new_command(self):
        for mode in ('scan', 'invalid', 'command'):
            rows = trajectory()
            if mode == 'scan':
                del rows[30]
            elif mode == 'invalid':
                rows[30]['valid'] = False
            else:
                for row in rows[30:]:
                    row['command_sequence'] = 3
            for r in examples(rows):
                self.assertFalse(r['sampled_us'] < 600000 <= r['future_sampled_us'])
                self.assertFalse(600000 <= r['sampled_us'] < 700000)

    def test_learned_prediction_generalizes_to_separate_synthetic_trajectory(self):
        model = fit(examples(trajectory(period=15)))
        result = evaluate(model, examples(trajectory(period=23)))[0]
        self.assertTrue(np.isfinite(result['rmse_us']['measured_state']))
        self.assertLess(result['rmse_us']['measured_state'], result['rmse_us']['hold_last_position'])

    def test_variable_intervals_are_recorded_and_labels_are_not_interpolated(self):
        rows = trajectory()
        rows[10]['sampled_us'] += 2500
        r = next(r for r in examples(rows) if r['sampled_us'] == 160000)
        self.assertEqual(r['future_sampled_us'], 202500)
        self.assertAlmostEqual(r['dt_s'], .0425)
        self.assertEqual(r['future_raw_us'], rows[10]['raw_us'])
        self.assertAlmostEqual(r['command_features'][7], .0425/.04)

    def test_imu_summary_retains_startup_and_does_not_integrate_across_loss(self):
        def event(sequence, timestamp):
            return {'sequence': sequence, 'kind': 'sample',
                    'motion': {'walking': True, 'command_sequence': 1},
                    'imu': {'timestamp_us': timestamp, 'available': True, 'fresh': True,
                            'startup': True, 'recovering': False,
                            'angular_rate_rad_s': [0, 0, -1],
                            'acceleration_m_s2': [0, 0, 9.8]}}
        header = {'schema': 'gait_trace_v1', 'boot_id': 1, 'session': 1}
        result = walking_imu_summary([{'records': [header, event(1, 0), event(2, 1000000)]}])
        self.assertEqual(result[0]['startup_samples'], 2)
        self.assertAlmostEqual(result[0]['approximate_body_z_rotation_deg'], -180/np.pi)
        result = walking_imu_summary([{'records': [header, event(1, 0), event(3, 1000000)]}])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r['approximate_body_z_rotation_deg'] == 0 for r in result))

    def test_identical_recordings_cannot_be_called_independent_evaluation(self):
        with patch('gateway.gait_response.load_trial', return_value=(examples(trajectory()),
                                                                   {'trace_sha256': 'same'})):
            with self.assertRaisesRegex(ValueError, 'same recording'):
                train_and_evaluate([Path('a')], [Path('copy-of-a')])


if __name__ == '__main__':
    unittest.main()
