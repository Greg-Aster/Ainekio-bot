import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from .compact_wire import ProgramEncoding, observation, model_query
from .generator import argument_schema, Generator
from .runtime import JOINTS
from .motion_space import TOOLS
from .face_contract import face_tool


class CompactWireTests(unittest.TestCase):
    def test_tapered_target_recovery_preserves_compact_action_and_actual_player_progress(self):
        encoding=ProgramEncoding(TOOLS)
        action={'name':'move','arguments':{'joint':JOINTS[0],'angle_deg':20,'reference':'current','speed_pct':50,'taper_deg':5}}
        progress={'source_us':1250000,'checkpoint':2,'waiting':False,'sequence':27,'sampled_us':2000000}
        q={'request':'finish the bow','event':{'type':'servo_stall','joints':[0]},
           'observation':{'joints':{},'features':['motion_curves_v1'],'trajectory_progress':progress},
           'history':[{'program_state':'executing','interrupted_action':action,'remaining_program':[]}]}
        result=model_query(q,encoding)
        self.assertEqual(result['observation']['trajectory_progress'],progress)
        self.assertEqual(encoding.decode([result['history'][0]['interrupted_action']]),[action])
        self.assertEqual(result['history'][0]['remaining_program'],[])
        self.assertNotIn('trajectory',encoding.tools)

    def test_recovery_projection_preserves_current_measurements_and_correlated_receipts(self):
        from .observations import enrich
        encoding=ProgramEncoding([*TOOLS,face_tool()])
        imu={'orientation_wxyz':[1,0,0,0],'available':True,'fresh':True}
        receipt={'t':'done','seq':7,'position_verified':True}
        query=enrich({'request':'recover','event':{'type':'servo_stall'},
            'observation':{'imu':imu,'joints':{JOINTS[0]:{'model_deg':4,'commanded_model_deg':5,
                'arrival_tolerance_deg':2,'feedback_usable':True}}},
            'history':[{'imu':imu,'correction_delta_deg':{JOINTS[0]:2}},
                       {'imu':imu,'receipts':[receipt]}]})
        projected=model_query(query,encoding)
        self.assertEqual(projected['observation']['joints']['tracking_error_deg'],[1])
        self.assertEqual(projected['observation']['joints']['within_arrival_tolerance'],[True])
        self.assertEqual(projected['observation']['imu']['derived_orientation']['tilt_degrees'],0)
        self.assertEqual(projected['history'][0]['last_correction']['receipts'],[receipt])

    def test_feedback_fault_keeps_calibrated_domain_and_interrupted_goal(self):
        encoding=ProgramEncoding([*TOOLS,face_tool()])
        action={'name':'feet','arguments':{'legs':['front_right'],
            'offsets_mm':[[0,0,30]],'speed_pct':50,'taper_deg':0}}
        query={'request':'stretch then stand','event':{'type':'servo_feedback_fault',
            'joints':[{'id':10,'reasons':['below_calibration']}],'outputs_released':False},
            'observation':{'joints':{JOINTS[10]:{'model_deg':-39.57,
                'feedback_range_deg':[-36.27,170.73],'feedback_usable':False,
                'feedback_faults':['below_calibration'],'arrival_tolerance_deg':9}},
                'feedback':{'enabled':True,'waiting_joints':1024}},
            'history':[{'interrupted_action':action,'remaining_program':[{'name':'hold','arguments':{'seconds':.6}}]}]}
        packed=model_query(query,encoding)
        self.assertEqual(packed['observation']['joints']['feedback_range_deg'],[[-36.27,170.73]])
        self.assertEqual(packed['observation']['joints']['feedback_usable'],[False])
        self.assertEqual(packed['observation']['feedback']['waiting_joints'],1024)
        self.assertEqual(packed['event']['joints'][0]['reasons'],['below_calibration'])
        self.assertEqual(packed['history'][0]['interrupted_action'],encoding.encode([action])[0])
        self.assertEqual(packed,model_query(packed,encoding))

    def test_recovery_keeps_goal_and_unfinished_complex_plan_without_copied_logs(self):
        encoding=ProgramEncoding([*TOOLS,face_tool()])
        move={'name':'move','arguments':{'joint':JOINTS[6],'angle_deg':-60,'reference':'absolute','speed_pct':20,'taper_deg':0}}
        wave={'name':'oscillate','arguments':{'joint':JOINTS[6],'amplitude_deg':4,'cycles':3,'speed_pct':15,'taper_deg':0}}
        finish={'name':'pose','arguments':{'joints':list(JOINTS),
            'angles_deg':[0,3.46,-21.63]*4,'reference':'absolute','speed_pct':50,'taper_deg':0}}
        query={'request':'Wave then stand','event':{'type':'servo_stall','joints':[6],
               'outputs_released':False,'event_id':'diagnostic','thresholds':{'unused':10}},
               'observation':{'joints':{JOINTS[6]:{'model_deg':-50.,'commanded_model_deg':-60.,
                   'calibrated':True,'in_calibrated_range':True}},
                   'imu':{'available':True,'fresh':True,'orientation_wxyz':[1.,0.,0.,0.]},
                   'feedback':{'enabled':True,'no_progress_ms':3000,'device_us':123456}},
               'history':[{'imu':{'old':True}}]*20+[{'interrupted_action':move,
                    'remaining_program':[wave,finish],
                    'interrupted_program':{'program':[move]*100},'packet_progress':{'frames':[0]*1000}}]}
        original=copy.deepcopy(query)
        projected=model_query(query,encoding)
        self.assertEqual(query,original)
        self.assertEqual(projected['request'],'Wave then stand')
        self.assertFalse(projected['event']['outputs_released'])
        self.assertEqual(projected['history'],[{'interrupted_action':encoding.encode([move])[0],
            'remaining_program':encoding.encode([wave,finish])}])
        self.assertEqual(projected,model_query(projected,encoding))
        self.assertNotIn('device_us',projected['observation']['feedback'])
        self.assertNotIn('thresholds',projected['event'])

    def test_candidate_generator_uses_no_system_prompt_and_decodes_into_existing_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'system.txt').write_text('')
            (root/'tools.json').write_text(json.dumps([*TOOLS,face_tool()]))
            (root/'wire.json').write_text('{"format":"motion-arrays-v1"}')
            generator=Generator('http://model/v1','candidate',root)
            captured={}
            class Reply:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self):return json.dumps({'choices':[{'finish_reason':'stop','message':{
                    'content':'[["face","happy"],["move",0,12.5,"current",50,0]]'}}]}).encode()
            def response(req):
                captured.update(json.loads(req.data))
                return Reply()
            with patch('urllib.request.urlopen',response):
                result=generator.generate('Lift the rear left shoulder',{'joints':{JOINTS[0]:{'model_deg':3.5}}})
            self.assertEqual([m['role'] for m in captured['messages']],['user'])
            state=json.loads(captured['messages'][0]['content'])['observation']
            self.assertEqual(state['joints']['model_deg'],[3.5])
            self.assertEqual(result['program'][1],{'name':'move','arguments':{
                'joint':JOINTS[0],'angle_deg':12.5,'reference':'current','speed_pct':50,'taper_deg':0}})
            self.assertNotIn('max_tokens',captured)

    def test_program_roundtrip_keeps_generated_targets_timing_and_face_changes(self):
        encoding = ProgramEncoding([*TOOLS,face_tool()])
        program = [
            {'name':'face','arguments':{'expr':'wave'}},
            {'name':'pose','arguments':{'joints':[JOINTS[0],JOINTS[11]],'angles_deg':[-3.14159265,42.1234567],
                                       'reference':'current','speed_pct':72,'taper_deg':0}},
            {'name':'feet','arguments':{'legs':['front_left','rear_right'],'offsets_mm':[[1,2,3],[-1,-2,-3]],'speed_pct':32.7,'taper_deg':0}},
            {'name':'hold','arguments':{'seconds':2.45}},
            {'name':'face','arguments':{'expr':'happy'}}]
        original = copy.deepcopy(program)
        wire = encoding.encode(program)
        Draft202012Validator(encoding.schema(argument_schema)).validate(wire)
        self.assertEqual(encoding.decode(wire),program)
        self.assertEqual(program,original)
        with self.assertRaises(ValueError): encoding.decode([['move',-1,5,'current',50]])

    def test_compact_state_keeps_unknowns_and_recovery_evidence_without_mutating_recordings(self):
        state = {'joints':{JOINTS[0]:{'model_deg':12.123456789,'home_deg':0,'command_us':1700,
                                     'calibrated':False,'custom_measurement':8},
                           JOINTS[1]:{'model_deg':None}},
                 'imu':{'available':False,'fresh':False,'age_us':500,'orientation_wxyz':[1.,0.,0.,0.],
                        'accepted_samples':100,'acquisition':{'io_errors':3}},
                 'event':{'type':'servo_stall','joints':[1]}, 'history':[{'time_us':123,'note':'retain this'}]}
        original = copy.deepcopy(state)
        packed = observation(state)
        self.assertEqual(packed['joints']['model_deg'],[12.12346,None])
        self.assertEqual(packed['joints']['calibrated'],[False,None])
        self.assertEqual(packed['joints']['extra'],{'0':{'custom_measurement':8}})
        self.assertEqual(packed['event'],state['event'])
        self.assertEqual(packed['history'],state['history'])
        self.assertFalse(packed['imu']['available'])
        self.assertEqual(packed['imu']['age_us'],500)
        self.assertEqual(state,original)

    def test_ordinary_request_projects_live_p4_telemetry_through_recovery_state_idempotently(self):
        encoding = ProgramEncoding([*TOOLS, face_tool()])
        query = {
            'request': 'do the sprinkler dance',
            'event': None,
            'history': [],
            'observation': {
                'epoch': 1,
                'model': 'v2-12servo',
                'joint_speed_limit_deg_s': 2000,
                'features': ['motion_targets_v1', 'motion_curves_v1', 'servo_feedback_v1'],
                'action': {'t': 'motion_plan', 'frames': [[100000, [0]*12]]},
                'joints': {
                    JOINTS[i]: {
                        'model_deg': -3.871531561299767 + i * 0.111,
                        'commanded_model_deg': 0.9000012119293679,
                        'filtered_model_deg': -3.701365698961365 + i * 0.111,
                        'home_deg': -30.87,
                        'velocity_deg_s': -4.568392178912447,
                        'sampled_us': 133788647 + i * 700,
                        'command_us': 1760,
                        'calibrated': True,
                        'in_calibrated_range': True,
                        'feedback_range_deg': [-113.40000432586686, 93.60000357055678],
                        'arrival_tolerance_deg': 16.20000061798098,
                        'feedback_usable': True,
                        'feedback_faults': [],
                    }
                    for i in range(len(JOINTS))
                },
                'imu': {
                    'available': True,
                    'fresh': True,
                    'age_us': 1702,
                    'timestamp_us': 133800999,
                    'frame': 'body_nominal',
                    'orientation_wxyz': [0.997298, 0.025149, 0.013837, -0.067623],
                    'angular_rate_rad_s': [-0.006338, 0.002801, -0.005822],
                    'acceleration_m_s2': [-0.229711, 0.631705, 9.82493],
                    'calibration_applied': True,
                    'joint_feedback': {'filtered_model_deg': [0.1] * 12, 'sampled_us': [1] * 12},
                },
                'feedback': {
                    'enabled': True,
                    'device_us': 133800000,
                    'stall_clock_us': 17482100,
                    'stalled_joints': 64,
                    'no_progress_ms': 3000,
                    'waiting_joints': 0,
                    'health': {'signal_millivolts': [1800] * 12},
                },
            },
        }
        projected = model_query(query, encoding)
        obs = projected['observation']
        self.assertEqual(obs['model'], 'v2-12servo')
        self.assertEqual(len(obs['joints']['filtered_model_deg']), 12)
        self.assertEqual(obs['joints']['filtered_model_deg'][0], -3.7)
        self.assertNotIn('extra', obs['joints'])
        self.assertNotIn('action', obs)
        self.assertNotIn('joint_feedback', obs['imu'])
        self.assertNotIn('health', obs['feedback'])
        self.assertEqual(obs['feedback']['last_reported_stalled_joints'], 64)
        self.assertEqual(obs['feedback']['last_stall_age_ms'], 116317.9)
        self.assertEqual(projected, model_query(projected, encoding))


if __name__ == '__main__': unittest.main()
