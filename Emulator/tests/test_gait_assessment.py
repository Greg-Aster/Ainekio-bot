import math
import unittest

from gateway.gait_assessment import visual_summary, support_summary


def position(frame, x=0., y=0., z=0., heading=0., **changes):
    return {'locomotion_measurement': {'available': True, 'robotId': 'robot', 'epoch': 1,
        'gatewayInstance': 'gateway', 'calibrationId': 'cal', 'referenceId': 'start', 'frameId': frame,
        'position': {'xMetres': x, 'yMetres': y, 'zMetres': z, 'headingDegrees': heading}, **changes}}


class AssessmentTests(unittest.TestCase):
    def test_visual_signed_displacement_height_and_heading_wrap(self):
        result = visual_summary([position('a', heading=179), position('a', heading=179),
                                 position('b', x=-.4, y=.1, z=-.02, heading=-179)])
        self.assertAlmostEqual(result['distance_m'], math.hypot(.4, .1))
        s = result['visual_motion']['segments'][0]
        self.assertEqual(s['frames'], 2)
        self.assertEqual(s['heading_change_deg'], 2)
        self.assertEqual(s['body_z_change_m'], -.02)
        self.assertGreater(s['forward_m'], .39)
        self.assertIsNone(s['metric_uncertainty_m'])

    def test_unavailable_or_changed_reference_does_not_become_zero_or_distance(self):
        for middle in [position('b', available=False, reason='Tracking lost'),
                       position('b', referenceId='different')]:
            result = visual_summary([position('a'), middle, position('c', x=1)])
            self.assertIsNone(result['distance_m'])
            self.assertEqual(len(result['visual_motion']['segments']), 2 if not middle['locomotion_measurement']['available'] else 3)
        self.assertIsNone(visual_summary([{}])['distance_m'])

    def trace(self, calibrated=True, known=True, grounded=True, tilt=0., gap=False):
        imu = {'available': True, 'fresh': True, 'startup': False, 'recovering': False,
               'calibration_applied': calibrated, 'orientation_wxyz': [math.cos(tilt/2), 0, math.sin(tilt/2), 0]}
        def sample(seq, stamp):
            return {'kind': 'sample', 'sequence': seq, 'imu': {**imu, 'timestamp_us': stamp},
                    'motion': {'command_sequence': 7}}
        leg = {'sampled_us': 150, 'phase': 2.25, 'support_known': known, 'planned_grounded': grounded,
               'measured_mm': [0, 0, -90], 'target_mm': [0, 0, -100]}
        return [{'records': [{'schema': 'gait_trace_v1', 'boot_id': 1, 'session': 1}, sample(1, 100),
                 {'kind': 'tracking', 'sequence': 2, 'command_sequence': 7, 'eligible': True,
                  'valid_mask': 15, 'legs': [leg.copy() for _ in range(4)]},
                 sample(4 if gap else 3, 200), {'next': 4 if gap else 3, 'lost': int(gap)}]}]

    def test_extension_is_phase_and_gravity_aware_without_claiming_contact(self):
        result = support_summary(self.trace(tilt=math.pi/3))
        for leg in result['legs']:
            self.assertAlmostEqual(leg['support_gravity_shortfall_mm'], 5.)
            self.assertEqual(leg['phase_bins'][0]['body_z_shortfall_mm']['mean'], 10.)
        self.assertFalse(result['contact_measured'])
        self.assertIsNone(result['sag_detected'])

    def test_missing_calibration_support_swing_or_trace_gap_is_not_support_evidence(self):
        for options in ({'calibrated': False}, {'known': False}, {'grounded': False}, {'gap': True}):
            result = support_summary(self.trace(**options))
            self.assertTrue(all(l['support_gravity_shortfall_mm'] is None for l in result['legs']))

    def test_learned_target_and_other_walk_commands_are_assessed(self):
        trace = self.trace()
        event = trace[0]['records'][2]
        event['eligible'] = False  # Old phase-only model excludes this command.
        event['policy'] = {'eligible': True}
        for leg in event['legs']:
            leg['correction_mm'] = [0., 0., 10.]
        result = support_summary(trace)
        for leg in result['legs']:
            self.assertAlmostEqual(leg['support_gravity_shortfall_mm'], 0.)
        self.assertIsNone(result['sag_detected'])


if __name__ == '__main__':
    unittest.main()
