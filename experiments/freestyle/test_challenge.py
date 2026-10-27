import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path

from .challenge import assess, corrections, draw, exposure, import_bank, replay, trajectory_metrics, write_rows, read_rows
from .kinematics import ROOT
from .runtime import JOINTS


class ChallengeTests(unittest.TestCase):
    def test_retrained_source_group_is_reported_as_regression(self):
        case={'request':'a new wording of the corrected action','holdout_group':'corrected-source',
              'evaluation_split':'unseen_external_round2'}
        result=exposure(case,self.state(),set(),{'corrected-source'})
        self.assertEqual(result['evaluation_split'],'trained_source_regression')
        self.assertEqual(result['original_evaluation_split'],'unseen_external_round2')
        self.assertTrue(result['training_exposure']['source_group_seen'])
        self.assertFalse(result['training_exposure']['exact_query_seen'])
        fresh=exposure({**case,'holdout_group':'different-source'},self.state(),set(),{'corrected-source'})
        self.assertFalse(fresh['training_exposure']['source_group_seen'])

    def test_crops_mirrors_and_duplicate_captions_stay_in_same_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'index.csv').write_text('source_path,start_frame,end_frame,new_name\n'
                                         'motion-a,0,120,000001.npy\nmotion-a,120,240,000002.npy\n'
                                         'motion-b,0,120,000003.npy\nmotion-c,0,120,000004.npy\n')
            with zipfile.ZipFile(root/'texts.zip','w') as archive:
                for clip, text in [('000001','tap left'),('M000001','tap right'),
                                   ('000002','shake'),('000003','shake'),('000004','bow')]:
                    archive.writestr('texts/'+clip+'.txt',text+'#tap/VERB#nan#0.0\n')
            import_bank(root, root/'bank')
            rows = read_rows(root/'bank/bank.jsonl')
            groups = {r['clip']:r['holdout_group'] for r in rows}
            self.assertEqual(len({groups[c] for c in ['000001','M000001','000002','000003']}),1)
            self.assertNotEqual(groups['000001'],groups['000004'])
            self.assertIsNone(rows[0]['segment_s'][0])
            first = draw(root/'bank/bank.jsonl',[],1,1)
            write_rows(root/'first.jsonl',first)
            second = draw(root/'bank/bank.jsonl',[root/'first.jsonl'],1,2)
            self.assertNotEqual(first[0]['holdout_group'],second[0]['holdout_group'])
            self.assertTrue(second[0]['request'].endswith(second[0]['description']))

    def state(self):
        source = json.loads((ROOT/'motions/gestures/wave/source.json').read_text())
        angles = [math.degrees(q) for leg in source['samples'][0]['actuator_angles_rad'] for q in leg]
        return {'joints':{j:{'model_deg':q,'home_deg':q} for j,q in zip(JOINTS,angles)},
                'joint_speed_limit_deg_s':180}

    def test_trace_catches_wrong_direction_and_a_hold_is_not_movement(self):
        criteria = [{'metric':'foot.front_right.z.peak_delta','min':4.9},
                    {'metric':'foot.front_right.z.end_delta','min':-.05,'max':.05}]
        def operation(height):
            return {'name':'feet','arguments':{'legs':['front_right'],'offsets_mm':[[0,0,height]],'speed_pct':50}}
        good = replay([operation(5),operation(-5)],self.state())
        wrong = replay([operation(-5),operation(5)],self.state())
        hold = replay([{'name':'hold','arguments':{'seconds':.2}}],self.state())
        self.assertEqual(good['status'],'replayed')
        self.assertTrue(assess(trajectory_metrics(good),criteria)['criteria_passed'])
        self.assertFalse(assess(trajectory_metrics(wrong),criteria)['criteria_passed'])
        self.assertFalse(assess(trajectory_metrics(hold),criteria)['criteria_passed'])
        self.assertIsNone(assess(trajectory_metrics(good),[])['criteria_passed'])
        self.assertIsNone(assess(trajectory_metrics(good),criteria)['physical_success'])

    def test_firmware_gait_is_not_falsely_reported_as_replayed(self):
        trace = replay([{'name':'gait','arguments':{'command':'walk','cycles':1,'speed_pct':50}}],self.state())
        self.assertEqual(trace['status'],'not_fully_replayed')
        self.assertEqual(trace['completed_actions'],0)

    def test_repetitions_must_complete_returns_and_are_not_just_nonzero_range(self):
        state=self.state();start=replay([],state)['samples'][0]
        samples=[]
        import copy
        for i,height in enumerate([0,5,0,5,0,5]):
            sample=copy.deepcopy(start);sample['time_s']=i
            sample['feet_body_mm']['front_right'][2]+=height;samples.append(sample)
        trace={'samples':samples}
        criteria=[{'metric':'foot.front_right.z.excursions','excursion_mm':4,
                   'return_tolerance_mm':.5,'min':3,'max':3}]
        score=assess(trajectory_metrics(trace),criteria,trace)
        self.assertEqual(score['checks'][0]['actual'],2)
        self.assertFalse(score['criteria_passed'])
        samples.append({**copy.deepcopy(start),'time_s':6})
        self.assertTrue(assess(trajectory_metrics(trace),criteria,trace)['criteria_passed'])

    def test_correction_uses_reviewed_target_and_retires_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_rows(root/'trials.jsonl',[{'id':'one','holdout_group':'group-a','request':'lift',
                                           'observation':self.state(),'program':[]}])
            (root/'evidence.json').write_text('{"review":"lift restored in corrected trace"}')
            target = [{'name':'move','arguments':{'joint':'front_right_shoulder','angle_deg':5,
                                                 'reference':'current','speed_pct':50}}]
            write_rows(root/'reviews.jsonl',[{'id':'one','motion_family':'lift',
                                            'reviewer':'test','evidence':'evidence.json','corrected_program':target}])
            report = corrections(root/'trials.jsonl',root/'reviews.jsonl',root/'training.jsonl')
            self.assertEqual(report['retired_from_unseen_groups'],['group-a'])
            row = read_rows(root/'training.jsonl')[0]
            self.assertEqual(row['answers'],target)
            self.assertFalse(row['physical_qualification'])


if __name__ == '__main__':
    unittest.main()
