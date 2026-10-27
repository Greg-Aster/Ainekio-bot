import json
import unittest

from .curriculum import example, source_state
from .program import compile_motion
from .semantic_teachers import call
from .speed_curriculum import migrate
from .stand_curriculum import program_rows


class StandCurriculumTests(unittest.TestCase):
    def row(self, request, program, **kw):
        return example(request, source_state(), program, 'test', **kw)

    def test_speed_migration_preserves_requested_hold_and_oscillation_duration(self):
        action = call('oscillate', joint='front_right_shoulder', amplitude_deg=9,
                      cycles=2, period_s=2)
        row = self.row('Wave with a 2 second cycle, then hold for 3 seconds.',
                       [action, call('hold', seconds=3)])
        revised, evidence = migrate(row)
        self.assertTrue(evidence['accepted'], evidence)
        self.assertEqual(revised['answers'][1], row['answers'][1])
        self.assertEqual(revised['answers'][0]['arguments']['speed_pct'], 10)
        self.assertNotIn('period_s', revised['answers'][0]['arguments'])
        frames = compile_motion(revised['answers'][0], json.loads(revised['query'])['observation'])
        self.assertEqual(len(frames['frames']), 8)

    def test_unspecified_legacy_travel_is_50_and_history_matches_runtime(self):
        action = call('oscillate', joint='front_right_shoulder', amplitude_deg=9,
                      cycles=2, period_s=2)
        row = self.row('Wave.', [action], history=[{'action':action}])
        revised, evidence = migrate(row)
        self.assertTrue(evidence['accepted'])
        self.assertEqual(revised['answers'][0]['arguments']['speed_pct'], 50)
        self.assertEqual(json.loads(revised['query'])['history'][0]['action']['arguments']['speed_pct'], 50)
        self.assertEqual(revised['original_answers'], row['answers'])

    def test_ambiguous_slow_request_is_retained_for_review(self):
        row = self.row('Wave slowly.', [call('oscillate', joint='front_right_shoulder',
                       amplitude_deg=9, cycles=2, period_s=2)])
        result, evidence = migrate(row)
        self.assertFalse(evidence['accepted'])
        self.assertEqual(result, row)

    def test_old_model_comparison_preserves_authored_period_without_request_duration(self):
        row=self.row('Wave.',[call('oscillate',joint='front_right_shoulder',
                                  amplitude_deg=9,cycles=2,period_s=2)])
        revised,evidence=migrate(row,preserve_durations=True)
        self.assertTrue(evidence['accepted'])
        self.assertEqual(revised['answers'][0]['arguments']['speed_pct'],10)
        self.assertEqual(migrate(row)[0]['answers'][0]['arguments']['speed_pct'],50)


    def test_stand_training_has_the_whole_program_in_one_response(self):
        pose=lambda value:{'model_deg':[value]*12,'sole_height_mm':[0]*4,'euler_rad':[0,0,0]}
        case={'case':'complete-example','order':0,'start_pose':'stand','valid':True,
              'start_mapping':{'in_travel':True},'fit_delta_deg':0,'all_targets_in_travel':True,
              'start':pose(0),'high_stand':pose(17),'nominal_stand':pose(18),
              'stages':[{'phase':'target','target':pose(i+1)} for i in range(17)]}
        calibration={'joints':[{'id':i,'home_cd':0,'home_us':1500,'invert':False,'us_per_degree':10} for i in range(12)]}
        rows=list(program_rows([case],calibration))
        self.assertEqual(len(rows),1)
        query=json.loads(rows[0]['query'])
        self.assertIsNone(query['event'])
        self.assertEqual([a['arguments']['angles_deg'][0] for a in rows[0]['answers']],list(range(1,19)))
        self.assertEqual({a['name'] for a in rows[0]['answers']},{'pose'})
        self.assertFalse(rows[0]['physical_qualification'])


if __name__ == '__main__':
    unittest.main()
