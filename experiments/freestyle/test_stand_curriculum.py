import json
import unittest

from .stand_curriculum import program_rows


class StandCurriculumTests(unittest.TestCase):
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
