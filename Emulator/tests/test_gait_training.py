import copy
import json
import unittest

import numpy as np

from gateway.gait_learning import policy_seed
from gateway.gait_training import start, propose, advance, vector, reward, recorded_metrics, export_model, profile_signature
from test_gait_learning import policy_recording


class TrainingTests(unittest.TestCase):
    def initial(self):
        return start(policy_seed(policy_recording())['model'], periodic_scale_mm=.2,
                     feedback_scale_mm=.05, directions=3, step_size=.1,
                     weights={'forward_m_s': 1., 'tilt_rms_rad': -.2, 'actuator_error_rms_mm': -.001}, seed=17)

    def trials(self, generation):
        trials = []
        # Synthetic objective: tests optimizer arithmetic, not robot improvement.
        target = np.linspace(-.2, .2, 156)
        for model in generation['candidates']:
            performance = 1-np.mean((vector(model)-target)**2)
            for block, floor_effect in enumerate((-.2, .3)):
                trials.append({'model_id': model['id'], 'block': block,
                               'recording': f'synthetic/{model["id"]}/{block}',
                               'metrics': {'forward_m_s': performance+floor_effect,
                                           'tilt_rms_rad': .03, 'actuator_error_rms_mm': 2.}})
        return trials

    def test_search_round_trip_and_only_evaluated_incumbent(self):
        state = self.initial();unchanged = copy.deepcopy(state)
        generation = propose(state)
        self.assertEqual(generation, propose(json.loads(json.dumps(state))))
        trials = self.trials(generation)
        result = advance(state, generation, trials)
        self.assertEqual(state, unchanged)
        self.assertEqual(result['generation'], 1)
        self.assertIn(result['incumbent'], generation['candidates'])
        self.assertNotEqual(result['centre']['id'], state['centre']['id'])
        self.assertFalse(result['history'][0]['global_optimum_demonstrated'])
        # A shared floor/run effect cancels in the paired comparison.
        for comparison in result['history'][0]['comparisons']:
            self.assertLess(comparison['improvement_standard_error'], 1e-15)
        self.assertEqual(propose(result), propose(json.loads(json.dumps(result))))
        exported = export_model(result)
        self.assertEqual(exported['model'], result['incumbent'])
        self.assertNotEqual(exported['model']['id'], result['centre']['id'])
        self.assertEqual(exported['training']['evaluation'], result['incumbent_evidence'])

    def test_missing_progress_cannot_turn_into_a_tracking_only_reward(self):
        weights = self.initial()['weights']
        for missing in (None, float('nan')):
            with self.assertRaises(ValueError):
                reward({'forward_m_s': missing, 'tilt_rms_rad': 0., 'actuator_error_rms_mm': 0.}, weights)

    def test_profile_search_changes_actual_gait_and_round_trips(self):
        seed = policy_seed(policy_recording(), gait=True)['model']
        state = start(seed, periodic_scale_mm=0., feedback_scale_mm=.01, command_scale_mm=.02,
                      gait_scales=[.001, .5]+[.002]*4+[.3]*4+[.2]*8+[.1]*15,
                      directions=1, step_size=.1, weights=self.initial()['weights'], seed=5)
        generation = propose(state)
        plus, minus = [next(m for m in generation['candidates'] if m['id'] == key) for key in generation['pairs'][0]]
        self.assertEqual(len(vector(plus)), 237)
        np.testing.assert_array_equal(np.array(plus['gait_profile']), -np.array(minus['gait_profile']))
        self.assertNotEqual(plus['gait_profile'], seed['gait_profile'])
        self.assertEqual(plus['coefficients'], seed['coefficients'])
        self.assertNotEqual(plus['command_coefficients'], seed['command_coefficients'])
        self.assertEqual(generation, propose(json.loads(json.dumps(state))))

    def test_metric_profile_identity_is_not_assumed_from_requested_model(self):
        batches = policy_recording();model = policy_seed(batches, gait=True)['model']
        visual = {'distance_m': .5, 'visual_motion': {'segments': [{
            'frames': 3, 'forward_m': .4, 'first_observed_at': '2026-10-19T12:00:00+00:00',
            'last_observed_at': '2026-10-19T12:00:10+00:00'}]}}
        for event in batches[0]['records'][1:-1]:
            event['policy']['profile_signature'] = profile_signature(model['gait_profile'])
        self.assertGreater(recorded_metrics(batches, visual, model)['forward_m_s'], 0)
        model['gait_profile'][0] = .01
        with self.assertRaisesRegex(ValueError, 'did not select'):
            recorded_metrics(batches, visual, model)

    def test_incomplete_reused_or_wrong_generation_does_not_advance(self):
        state = self.initial();generation = propose(state);trials = self.trials(generation)
        for bad in (trials[:-1], trials+trials[:1]):
            with self.assertRaises(ValueError):
                advance(state, generation, bad)
        generation['generation'] += 1
        with self.assertRaises(ValueError):
            advance(state, generation, trials)
        self.assertEqual(state['generation'], 0)

    def test_all_equal_results_preserve_centre_and_incumbent(self):
        state = self.initial();generation = propose(state);trials = self.trials(generation)
        for trial in trials:
            trial['metrics']['forward_m_s'] = .1
        result = advance(state, generation, trials)
        self.assertEqual(result['centre'], state['centre'])
        self.assertEqual(result['incumbent'], state['incumbent'])

    def test_metrics_use_applied_target_and_measured_progress(self):
        batches = policy_recording()
        for event in batches[0]['records'][1:-1]:
            for leg in event['legs']:
                leg['target_mm'] = [0., 0., 0.]
                leg['correction_mm'] = [0., 0., 10.]
                leg['measured_mm'] = [0., 0., 10.]
        visual = {'distance_m': .5, 'visual_motion': {'segments': [{
            'frames': 3, 'forward_m': .4, 'first_observed_at': '2026-10-19T12:00:00+00:00',
            'last_observed_at': '2026-10-19T12:00:10+00:00'}]}}
        measured = recorded_metrics(batches, visual)
        self.assertAlmostEqual(measured['forward_m_s'], .04)
        self.assertAlmostEqual(measured['actuator_error_rms_mm'], 0)
        self.assertAlmostEqual(measured['tilt_rms_rad'], np.sqrt((.03**2+.02**2)/2))
        visual['distance_m'] = None
        with self.assertRaisesRegex(ValueError, 'Metric visual progress'):
            recorded_metrics(batches, visual)


if __name__ == '__main__':
    unittest.main()
