import copy
import unittest

from .compact_wire import ProgramEncoding, model_query
from .runtime import JOINTS


class RecoveryContextTests(unittest.TestCase):
    def test_failed_target_retains_the_body_rejection_without_claiming_it_is_pending(self):
        from .motion_space import TOOLS
        encoding=ProgramEncoding(TOOLS)
        action={'name':'move','arguments':{'joint':JOINTS[1],'angle_deg':25,
            'reference':'absolute','speed_pct':50}}
        rejection={'t':'done','seq':24,'position_verified':False,'target_adjusted_joints':3072}
        query={'request':'finish the gesture','event':{'type':'servo_feedback_fault'},
            'observation':{},'history':[{'program_state':'error','failed_action':action,
                'error':'Body did not verify the requested motion target',
                'error_evidence':rejection,'remaining_program':[]}]}
        projected=model_query(query,encoding)
        context=projected['history'][0]
        self.assertEqual(context['failed_action'],encoding.encode([action])[0])
        self.assertNotIn('interrupted_action',context)
        self.assertEqual(context['error_evidence'],rejection)
        self.assertEqual(context['error'],query['history'][0]['error'])
        self.assertEqual(projected,model_query(projected,encoding))

    def test_completed_motion_keeps_completion_empty_remainder_and_measured_effect(self):
        from .motion_space import TOOLS
        encoding=ProgramEncoding(TOOLS)
        pose={'name':'pose','arguments':{'joints':list(JOINTS),
            'angles_deg':[0,3.46,-21.63]*4,'reference':'absolute','speed_pct':50}}
        receipt={'t':'done','seq':27,'position_verified':True}
        effect={'delta_deg':[[0,0]],'before':{'available':True},
                'after':{'available':True},'receipts':[receipt]}
        for event in ('rapid_movement','tipped','servo_stall','servo_feedback_fault','slip'):
            query={'request':'Stand up, stretch, and finish standing.',
                'event':{'type':event},'observation':{},
                'history':[{'program_state':'completed','completed_action':pose,
                    'remaining_program':[],'last_correction':effect}]}
            original=copy.deepcopy(query)
            projected=model_query(query,encoding)
            self.assertEqual(projected['history'],[{'program_state':'completed',
                'completed_action':encoding.encode([pose])[0],
                'remaining_program':[],'last_correction':effect}])
            self.assertEqual(projected,model_query(projected,encoding))
            self.assertEqual(query,original)

    def test_unknown_pending_plan_is_not_changed_to_a_completed_empty_plan(self):
        query={'request':'continue','event':{'type':'rapid_movement'},
               'observation':{},'history':[{'program_state':'generating'}]}
        projected=model_query(query,ProgramEncoding([]))
        self.assertEqual(projected['history'],[{'program_state':'generating'}])
        self.assertEqual(projected,model_query(projected,ProgramEncoding([])))

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

    def test_original_goal_survives_a_different_failed_recovery_plan(self):
        from .library_recovery import CONTRACT
        encoding=ProgramEncoding(CONTRACT)
        goal={'request':'Please lie down.','interrupted_action':['pose',[1],[.94],'absolute',50,0],
              'remaining_program':[['pose',list(range(12)),[-32.52,33.34,50.91]*4,'absolute',50,0],['hold',1.8]]}
        current={'name':'feet','arguments':{'legs':['rear_left'],'offsets_mm':[[0,0,10]],
                 'speed_pct':50,'taper_deg':0}}
        query={'request':'Please lie down.','event':{'type':'servo_stall','joints':[1]},
            'motion_goal':goal,'observation':{},'history':[{'program_state':'executing',
                'interrupted_action':current,'remaining_program':[['hold',.1]]}]}
        before=copy.deepcopy(query)
        projected=model_query(query,encoding)
        self.assertEqual(projected['motion_goal'],goal)
        self.assertEqual(projected['history'][0]['interrupted_action'],encoding.encode([current])[0])
        self.assertEqual(projected['history'][0]['remaining_program'],[['hold',.1]])
        self.assertEqual(query,before)
        self.assertEqual(model_query(projected,encoding),projected)
