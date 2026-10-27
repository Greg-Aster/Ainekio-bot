import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .curriculum import source_state
from .runtime import JOINTS
from .semantic_teachers import call
from .stand_evaluation import rollout, trajectory_evidence, score, feedback_domain_evidence


class StandEvaluationTests(unittest.TestCase):
    def test_feedback_domain_reports_extrapolated_targets_without_claiming_travel_limits(self):
        obs={'joints':{JOINTS[10]:{'feedback_range_deg':[-36.27,170.73]}}}
        target=dict.fromkeys(JOINTS,0);target[JOINTS[10]]=-39.57
        report=feedback_domain_evidence([target],obs)
        self.assertEqual(report['known_joints'],1)
        self.assertEqual(report['outside_calibration'][0]['joint'],JOINTS[10])
        self.assertEqual(report['outside_calibration'][0]['target_deg'],-39.57)
        self.assertEqual(feedback_domain_evidence([target],{'joints':{}})['known_joints'],0)

    def test_rollout_fault_interrupts_first_unverifiable_target_and_requests_recovery(self):
        obs=source_state();joint=JOINTS[10]
        obs['joints'][joint].update(model_deg=0,commanded_model_deg=0,feedback_range_deg=[-36.27,170.73])
        obs['feedback']={'device_us':3000000};seen=[]
        class Generator:
            schema={'type':'array'}
            def generate(self,request,observation,event,history):
                seen.append(copy.deepcopy((observation,event)))
                program=([call('move',joint=joint,angle_deg=-39.57,reference='absolute',speed_pct=50),
                          call('move',joint=joint,angle_deg=10,reference='absolute',speed_pct=50)]
                         if len(seen)==1 else
                         [call('move',joint=joint,angle_deg=0,reference='absolute',speed_pct=50)]
                         if len(seen)==2 else [])
                return {'program':program,'elapsed_s':.2}
        with tempfile.TemporaryDirectory() as directory:
            geometry=Path(directory);(geometry/'mapping.txt').write_text('mapping')
            calibration={'joints':[{'id':i,'home_us':1500,'home_cd':0,'invert':False,'us_per_degree':10} for i in range(12)]}
            (geometry/'calibration-evidence.json').write_text(json.dumps({'payload':{'result':calibration}}))
            case={'case':'reference','nominal_stand':{'model_deg':[obs['joints'][j]['model_deg'] for j in JOINTS]}}
            row={'query':json.dumps({'request':'stretch','observation':obs,'event':None,'history':[]})}
            with patch('experiments.freestyle.stand_evaluation.native_pose',return_value={'valid':True,'in_travel':True}),patch('experiments.freestyle.stand_evaluation.read_rows',return_value=[case]):
                result=rollout(Generator(),row,geometry,4)
        self.assertEqual(seen[1][1]['type'],'servo_feedback_fault')
        self.assertFalse(seen[1][0]['joints'][joint]['feedback_usable'])
        self.assertEqual(seen[1][0]['feedback']['waiting_joints'],1<<10)
        self.assertEqual(len(seen),2)
        self.assertEqual(result['inference_rounds'],2)
        self.assertEqual(len(result['generated_targets_model_deg']),2)
        self.assertEqual(result['state'],'model_finished')

    def test_legacy_ik_failure_is_not_reported_as_invalid_model_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('mapping.txt','native-cases.jsonl','stand-geometry'):
                (root/name).write_text('')
            row={'id':'legacy-ik','family':'spatial','query':json.dumps({'observation':source_state()}),
                 'answers':[call('face',expr='stand')]}
            prediction={'id':row['id'],'elapsed_s':.1,'program':None,
                        'original_contract_schema_valid':True,
                        'duration_migration':{'accepted':False,'reason':'explicit_timing_compile_error',
                                              'error':'Requested foot target has no IK solution'}}
            (root/'data.jsonl').write_text(json.dumps(row)+'\n')
            (root/'prediction.jsonl').write_text(json.dumps(prediction)+'\n')
            with patch('experiments.freestyle.stand_evaluation.Generator') as generator:
                generator.return_value.schema={'type':'array'}
                score(root/'data.jsonl',root/'prediction.jsonl',root,root,root/'score.jsonl')
            result=json.loads((root/'score.jsonl').read_text())
            self.assertEqual(result['error_stage'],'legacy_target_translation')
            self.assertTrue(result['original_contract_schema_valid'])
            self.assertFalse(result['next_step_matches'])

    def test_retained_pose_without_requested_hold_is_a_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('mapping.txt','native-cases.jsonl','stand-geometry'):
                (root/name).write_text('')
            row={'id':'hold-check','family':'hold','query':json.dumps({'observation':source_state()}),
                 'answers':[call('hold',seconds=2),call('face',expr='stand')]}
            (root/'data.jsonl').write_text(json.dumps(row)+'\n')
            (root/'prediction.jsonl').write_text(json.dumps({'id':row['id'],'elapsed_s':.1,
                                                        'program':[call('face',expr='stand')]})+'\n')
            with patch('experiments.freestyle.stand_evaluation.Generator') as generator:
                generator.return_value.schema={'type':'array'}
                score(root/'data.jsonl',root/'prediction.jsonl',root,root,root/'score.jsonl')
            result=json.loads((root/'score.jsonl').read_text())
            self.assertTrue(result['target_matches'])
            self.assertFalse(result['hold_sequence_matches'])
            self.assertFalse(result['next_step_matches'])

    def test_nominal_endpoint_alone_does_not_prove_rise_and_settle(self):
        reference={'case':'standing','high_stand':{'model_deg':[2.]*12},
                   'nominal_stand':{'model_deg':[0.]*12}}
        self.assertFalse(trajectory_evidence([[0.]*12]*3,reference)['commanded_high_then_nominal'])
        self.assertFalse(trajectory_evidence([[0.]*12,[2.]*12],reference)['commanded_high_then_nominal'])
        self.assertTrue(trajectory_evidence([[2.]*12,[0.]*12],reference)['commanded_high_then_nominal'])

    def test_direct_stand_jump_does_not_count_as_lifted_inward_step(self):
        stages=[]
        for phase,angle,x in [('lift',1.,0.),('place',2.,10.),('lower',3.,10.)]:
            stages.append({'phase':phase,'moving_joints':7,
                           'target':{'model_deg':[angle]*12,'feet_mm_flat':[x,0,0]+[0]*9}})
        reference={'case':'spread','stages':stages,'high_stand':{'model_deg':[4.]*12},
                   'nominal_stand':{'model_deg':[5.]*12}}
        direct=trajectory_evidence([[4.]*12,[5.]*12],reference)
        self.assertTrue(direct['commanded_high_then_nominal'])
        self.assertFalse(direct['placement_landmarks'][0]['ordered_triplet_observed'])
        ordered=trajectory_evidence([[i]*12 for i in range(1,6)],reference)
        self.assertTrue(ordered['placement_landmarks'][0]['ordered_triplet_observed'])
        self.assertEqual(ordered['placement_landmarks'][0]['reference_translation_mm'],10.)
        reversed_steps=trajectory_evidence([[3.]*12,[2.]*12,[1.]*12],reference)
        self.assertFalse(reversed_steps['placement_landmarks'][0]['ordered_triplet_observed'])



if __name__=='__main__':
    unittest.main()
