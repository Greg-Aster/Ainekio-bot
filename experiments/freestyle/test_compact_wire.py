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
from .prepare_wire import build


class CompactWireTests(unittest.TestCase):
    def test_recovery_keeps_goal_and_unfinished_complex_plan_without_copied_logs(self):
        encoding=ProgramEncoding([*TOOLS,face_tool()])
        move={'name':'move','arguments':{'joint':JOINTS[6],'angle_deg':-60,'reference':'absolute','speed_pct':20}}
        wave={'name':'oscillate','arguments':{'joint':JOINTS[6],'amplitude_deg':4,'cycles':3,'period_s':.8}}
        query={'request':'Wave then stand','event':{'type':'servo_stall','joints':[6],
               'outputs_released':False,'event_id':'diagnostic','thresholds':{'unused':10}},
               'observation':{'joints':{JOINTS[6]:{'model_deg':-50.,'commanded_model_deg':-60.,
                   'calibrated':True,'in_calibrated_range':True}},
                   'imu':{'available':True,'fresh':True,'orientation_wxyz':[1.,0.,0.,0.]},
                   'feedback':{'enabled':True,'no_progress_ms':3000,'device_us':123456}},
               'history':[{'imu':{'old':True}}]*20+[{'interrupted_action':move,
                    'remaining_program':[wave,{'name':'pose','arguments':{'joints':list(JOINTS),'angles_deg':[0]*12,'reference':'home','speed_pct':20}}],
                    'interrupted_program':{'program':[move]*100},'packet_progress':{'frames':[0]*1000}}]}
        original=copy.deepcopy(query)
        projected=model_query(query,encoding)
        self.assertEqual(query,original)
        self.assertEqual(projected['request'],'Wave then stand')
        self.assertFalse(projected['event']['outputs_released'])
        self.assertEqual(projected['history'],[{'interrupted_action':encoding.encode([move])[0],
            'remaining_program':encoding.encode([wave,{'name':'pose','arguments':{'joints':list(JOINTS),'angles_deg':[0]*12,'reference':'home','speed_pct':20}}])}])
        self.assertEqual(projected,model_query(projected,encoding))
        self.assertNotIn('device_us',projected['observation']['feedback'])
        self.assertNotIn('thresholds',projected['event'])

    def test_missing_faces_are_balanced_and_explicit_without_rewriting_motion_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source'; source.mkdir()
            contract=root/'contract'; contract.mkdir()
            tools=[*TOOLS,face_tool()]
            (contract/'tools.json').write_text(json.dumps(tools))
            (source/'manifest.json').write_text('{}')
            faces=tools[-1]['parameters']['properties']['expr']['enum']
            move={'name':'move','arguments':{'joint':JOINTS[0],'angle_deg':12.123456,
                                           'reference':'current','speed_pct':50}}
            rows=[{'id':str(i),'query':json.dumps({'request':'Move the rear left shoulder.'}),
                   'answers':[copy.deepcopy(move)],'family':'move'} for i in range(2*len(faces))]
            existing={'id':'expressive','query':json.dumps({'request':'Greet me.'}),
                      'answers':[{'name':'face','arguments':{'expr':'happy'}},copy.deepcopy(move)],'family':'greeting'}
            rows.append(existing)
            (source/'train.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            report=build(source,contract,root/'output')
            self.assertEqual(set(report['added_faces']['train'].values()),{2})
            self.assertEqual(set(report['added_faces']['train']),set(faces))
            converted=[json.loads(s) for s in (root/'output/train.jsonl').read_text().splitlines()]
            encoding=ProgramEncoding(tools)
            for row in converted[:-1]:
                program=encoding.decode(row['answers'])
                self.assertEqual(program[1:], [move])
                expression=program[0]['arguments']['expr']
                self.assertIn('Use the '+expression.replace('_',' ')+' face.',json.loads(row['query'])['request'])
            self.assertEqual(converted[-1]['query'],json.dumps({'request':'Greet me.'},separators=(',',':')))
            self.assertEqual(encoding.decode(converted[-1]['answers']),existing['answers'])

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
                    'content':'[["face","happy"],["move",0,12.5,"current",50]]'}}]}).encode()
            def response(req):
                captured.update(json.loads(req.data))
                return Reply()
            with patch('urllib.request.urlopen',response):
                result=generator.generate('Lift the rear left shoulder',{'joints':{JOINTS[0]:{'model_deg':3.5}}})
            self.assertEqual([m['role'] for m in captured['messages']],['user'])
            state=json.loads(captured['messages'][0]['content'])['observation']
            self.assertEqual(state['joints']['model_deg'],[3.5])
            self.assertEqual(result['program'][1],{'name':'move','arguments':{
                'joint':JOINTS[0],'angle_deg':12.5,'reference':'current','speed_pct':50}})
            self.assertNotIn('max_tokens',captured)

    def test_program_roundtrip_keeps_generated_targets_timing_and_face_changes(self):
        encoding = ProgramEncoding([*TOOLS,face_tool()])
        program = [
            {'name':'face','arguments':{'expr':'wave'}},
            {'name':'pose','arguments':{'joints':[JOINTS[0],JOINTS[11]],'angles_deg':[-3.14159265,42.1234567],
                                       'reference':'current','speed_pct':72}},
            {'name':'feet','arguments':{'legs':['front_left','rear_right'],'offsets_mm':[[1,2,3],[-1,-2,-3]],'seconds':.327}},
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


if __name__ == '__main__': unittest.main()
