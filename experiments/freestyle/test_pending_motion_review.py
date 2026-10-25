import unittest
from unittest.mock import patch

from .curriculum import example, source_state
from .pending_motion_review import candidates, evidence_snapshot, proposal, qualify


class PendingMotionReviewTests(unittest.TestCase):
    def test_stretch_preserves_full_ranges_cycles_holds_and_all_leg_return(self):
        for family in ('stretch_forward', 'stretch_spread'):
            program, goals = proposal(source_state(), [0, 3.46, -21.63] * 4, family)
            first, last = goals[0], goals[-1]
            legs = ['front_left', 'front_right'] if family == 'stretch_forward' else list(first['before'])
            for leg in legs:
                self.assertAlmostEqual(first['after'][leg][2] - first['before'][leg][2], 30)
                self.assertEqual(last['after'][leg], first['before'][leg])
            self.assertEqual(len(goals), 8 if family == 'stretch_forward' else 6)
            self.assertAlmostEqual(sum(g['seconds'] for g in goals), 4.8 if family == 'stretch_forward' else 2.8)
            peaks = [g for g in goals if any(abs(g['after'][leg][0] - first['after'][leg][0]) > 19.9
                                            or abs(g['after'][leg][1] - first['after'][leg][1]) > 19.9
                                            for leg in ('front_left', 'front_right'))]
            self.assertEqual(len(peaks), 4 if family == 'stretch_forward' else 2)
            self.assertEqual(program[-1]['arguments']['angles_deg'], [0, 3.46, -21.63] * 4)

    def test_recorded_proposal_uses_reviewed_hand_and_explicit_ending(self):
        for side, ending in (('right', 'stand'), ('left', 'raised')):
            request = f'Raise your {side} hand.' + (' Keep it raised.' if ending == 'raised' else '')
            records = [dict(id='request', job_id='trial', kind='generation_requested',
                            payload={'request': {'request': request, 'observation': source_state()}}),
                       dict(id='output', job_id='trial', kind='generation_completed',
                            payload={'result': {'program': []}})]
            cases = {'trial': dict(family='hand', side=side, ending=ending, cycles=2)}
            with patch('experiments.freestyle.pending_motion_review.CASES', cases):
                row = next(candidates(records, [0, 3.46, -21.63] * 4))
            feet = [a for a in row['answers'] if a['name'] == 'feet']
            self.assertTrue(all(a['arguments']['legs'] == ['front_' + side] for a in feet))
            self.assertEqual(row['request_evidence_id'], 'request')
            self.assertEqual(row['answers'][-1]['name'], 'pose' if ending == 'stand' else 'hold')
            self.assertEqual(row['expected_final_model_deg'] is None, ending == 'raised')

    def test_bread_has_two_choices_before_lift_and_preserves_phase_timing(self):
        state = source_state()
        stand = [0, 3.46, -21.63] * 4
        program, goals = proposal(state, stand, 'bread', 'left', 'raised')
        points = [g['after']['front_left'] for g in goals]
        self.assertEqual(points[:3], [[80, 110, 65], [110, 110, 65], [95, 100, 65]])
        self.assertEqual(points[-1], [95, 100, 90])
        self.assertEqual([g['seconds'] for g in goals], [.6, .6, .6, .25, .279, .25])
        self.assertEqual(program[-1]['name'], 'hold')
        row = example('Choose bread and keep it raised.', state, program, 'test',
                      spatial_goals=goals, expected_final_model_deg=None)
        checked = qualify(row)
        self.assertTrue(checked['kinematic_evidence']['accepted'], checked['kinematic_evidence'])

    def test_wiggle_count_keeps_full_lateral_range_and_explicit_stand(self):
        program, goals = proposal(source_state(), [0, 3.46, -21.63] * 4, 'wiggle', cycles=3)
        shifts = [a['arguments']['translation_mm'][1] for a in program if a['name'] == 'body']
        self.assertEqual(shifts, [20, -40, 40, -40, 20])
        self.assertEqual(program[-1]['arguments']['angles_deg'], [0, 3.46, -21.63] * 4)
        self.assertAlmostEqual(sum(g['seconds'] for g in goals), 3.9)

    def test_evidence_association_excludes_reused_epoch_sequence(self):
        def record(identifier, when, kind, job=None):
            return dict(id=identifier, monotonic_ns=when, time_ns=when, kind=kind,
                        job_id=job, robot_id='robot', epoch=2, sequence=10)
        job = '3dd78d91-ab50-45a6-91eb-37d69effe5d6'
        rows = [record('old', 1, 'body_event'),
                record('start', 10, 'operation_started', job),
                record('command', 11, 'body_command'),
                record('event', 12, 'body_event'),
                record('receipt', 13, 'command_receipt', job),
                record('unrelated', 14, 'body_event')]
        self.assertEqual({r['id'] for r in evidence_snapshot(rows)},
                         {'start', 'command', 'event', 'receipt'})


if __name__ == '__main__':
    unittest.main()
