import copy
import json
import unittest

from .challenge import replay
from .curriculum import source_state
from .face_contract import available_faces, extend_contract
from .semantic_teachers import call


class FaceContractTests(unittest.TestCase):
    def test_contract_uses_renderer_names_and_preserves_ending_policy(self):
        self.assertIn('wave',available_faces())
        system,tools=extend_contract('Instructions. Tools: []\nFinish standing unless asked otherwise.',[])
        self.assertEqual(tools[0]['parameters']['properties']['expr']['enum'],available_faces())
        self.assertIn('Finish standing unless asked otherwise.',system)
        self.assertEqual(json.JSONDecoder().raw_decode(system.split('Tools: ',1)[1])[0],tools)

    def test_faces_change_no_joint_observation_or_elapsed_motion_time(self):
        state=source_state(); original=copy.deepcopy(state)
        move=call('move',joint='front_left_shoulder',angle_deg=8,reference='current',speed_pct=50)
        plain=replay([move,call('hold',seconds=.7)],state)
        decorated=replay([call('face',expr='happy'),move,call('face',expr='thinking'),
                          call('hold',seconds=.7),call('face',expr='neutral')],state)
        self.assertEqual(decorated['status'],'replayed')
        self.assertEqual(decorated['completed_actions'],5)
        self.assertEqual(decorated['samples'][-1]['joints_deg'],plain['samples'][-1]['joints_deg'])
        self.assertEqual(decorated['samples'][-1]['time_s'],plain['samples'][-1]['time_s'])
        self.assertEqual([e['expr'] for e in decorated['face_events']],['happy','thinking','neutral'])
        self.assertEqual(state,original)

    def test_face_only_request_is_a_zero_time_nonmotion_program(self):
        trace=replay([call('face',expr='sad')],source_state())
        self.assertEqual(trace['status'],'replayed')
        self.assertEqual(trace['samples'][0]['joints_deg'],trace['samples'][-1]['joints_deg'])
        self.assertEqual(trace['samples'][-1]['time_s'],0)


if __name__=='__main__':unittest.main()
