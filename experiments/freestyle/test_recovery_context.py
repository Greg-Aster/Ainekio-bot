import copy
import unittest

from .compact_wire import ProgramEncoding, model_query
from .runtime import JOINTS


class RecoveryContextTests(unittest.TestCase):
    def test_jam_keeps_traversed_range_without_sensor_log(self):
        query={'request':'Finish waving','event':{'type':'servo_stall','joints':[JOINTS[6]]},
            'observation':{},'history':[{'joints':{JOINTS[6]:v}} for v in (10,18,18,18)]}
        result=model_query(query,ProgramEncoding([]))
        self.assertEqual(result['history'][0]['joint_progress'],[
            {'ids':[6],'model_deg':[10]},{'ids':[6],'model_deg':[18]}])
        self.assertEqual(result,model_query(result,ProgramEncoding([])))

    def test_latest_measured_effect_survives_compression_and_event_recovery(self):
        before={'available':True,'fresh':True,'orientation_wxyz':[.8,0,.6,0]}
        after={'available':True,'fresh':True,'orientation_wxyz':[.9,0,.43589,0]}
        history=[{'imu':before,'correction_delta_deg':{JOINTS[1]:3,JOINTS[7]:-3}},
                 {'imu':after}]
        for event in ('tipped','servo_stall','servo_feedback_fault'):
            query={'request':'Finish the original motion','event':{'type':event},
                   'observation':{'imu':after,'pending_actions':[['stand']]},'history':history}
            original=copy.deepcopy(query)
            projected=model_query(query,ProgramEncoding([]))
            effect=projected['history'][0]['last_correction']
            self.assertEqual(effect['delta_deg'],[[1,3],[7,-3]])
            self.assertEqual(effect['before']['orientation_wxyz'],before['orientation_wxyz'])
            self.assertEqual(effect['after']['orientation_wxyz'],after['orientation_wxyz'])
            self.assertEqual(projected['history'][0]['remaining_program'],[['stand']])
            self.assertEqual(projected,model_query(projected,ProgramEncoding([])))
            self.assertEqual(query,original)
