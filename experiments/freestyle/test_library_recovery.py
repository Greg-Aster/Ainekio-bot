import copy
import json
import unittest
from unittest.mock import patch

from .compact_wire import ProgramEncoding
from .library_recovery import scenarios, validate_prefix, deduplicate
from .migrate_targets import CONTRACT, STAND
from .runtime import JOINTS


class LibraryRecoveryTests(unittest.TestCase):
    def test_shared_recovery_keeps_every_source_without_duplicate_training_rows(self):
        rows=[{'id':'same-content','parent_example_id':p,'parent_source_hash':p+'-hash'} for p in ('a','b')]
        unique=deduplicate(rows)
        self.assertEqual(len(unique),1)
        self.assertEqual(unique[0]['parent_examples'],[
            {'id':'a','source_hash':'a-hash'},{'id':'b','source_hash':'b-hash'}])

    def source(self, operation):
        state={'joints':{j:{'model_deg':q,'commanded_model_deg':q,'home_deg':q} for j,q in STAND.items()},
               'joint_speed_limit_deg_s':180}
        return {'id':'0102030405060708','source_hash':'current-reviewed-example',
                'query':json.dumps({'request':'Perform my motion and then stand','observation':state}),
                'answers':[['face','happy'],operation,['stand']]}

    def test_every_joint_direction_retreats_and_preserves_goal_and_tail(self):
        for joint in range(12):
            for direction in (-1,1):
                source=self.source(['move',joint,direction*12,'current',50])
                original=copy.deepcopy(source)
                with patch('experiments.freestyle.library_recovery.foot_positions',return_value={'foot':[0,0,0]}):
                    train=list(scenarios(source,None));probe=list(scenarios(source,None,True))
                    jam=train[0]; targets=validate_prefix(jam)
                self.assertEqual(source,original)
                self.assertFalse({r['id'] for r in train}&{r['id'] for r in probe})
                self.assertEqual(jam['parent_source_hash'],source['source_hash'])
                self.assertEqual(jam['recovery_evidence']['joint'],joint)
                self.assertTrue(all(direction*(p[JOINTS[joint]]-jam['recovery_evidence']['blocked_deg'])<0 for p in targets))
                self.assertEqual(jam['answers'][-1],['reassess'])
                query=json.loads(jam['query'])
                self.assertEqual(query['request'],'Perform my motion and then stand')
                self.assertEqual(query['history'][0]['remaining_program'],[['stand']])
                self.assertNotIn('stop',[a[0] for a in jam['answers']])

    def test_fall_changes_direction_when_measured_effect_worsens(self):
        source=self.source(['move',0,12,'current',50])
        with patch('experiments.freestyle.library_recovery.foot_positions',return_value={'foot':[0,0,0]}):
            rows=[list(scenarios(source,None,probe))[1] for probe in (False,True)]
        self.assertEqual({r['recovery_evidence']['improved'] for r in rows},{True,False})
        for row in rows:
            query=json.loads(row['query']);effect=query['history'][0]['last_correction']
            correction=row['answers'][1]
            expected=[v*(1 if row['recovery_evidence']['improved'] else -1) for _,v in effect['delta_deg']]
            self.assertEqual(correction[2],expected)
            self.assertEqual(row['answers'][2],['reassess'])
            self.assertEqual(query['event']['type'],'tipped')
            self.assertFalse(row['physical_qualification'])

    def test_simultaneous_targets_and_oscillation_cycles_survive_adaptation(self):
        sources=[self.source(['pose',[1,7],[12,-12],'current',50]),
                 self.source(['oscillate',6,12,4,50])]
        with patch('experiments.freestyle.library_recovery.foot_positions',return_value={'foot':[0,0,0]}):
            pose,oscillation=[list(scenarios(s,None))[0] for s in sources]
        adapted=pose['answers'][2]
        self.assertEqual(adapted[0],'pose')
        self.assertEqual(set(adapted[1]),{1,7})
        self.assertEqual(oscillation['answers'][2][0],'oscillate')
        self.assertEqual(oscillation['answers'][2][3],4)
        self.assertLess(oscillation['answers'][2][2],12)

    def test_jam_feedback_retains_all_commanded_targets_distinct_from_measurements(self):
        source=self.source(['pose',[1,7],[12,-12],'current',50])
        with patch('experiments.freestyle.library_recovery.foot_positions',return_value={'foot':[0,0,0]}):
            jam=list(scenarios(source,None))[0]
        joints=json.loads(jam['query'])['observation']['joints']
        for joint,delta in ((1,12),(7,-12)):
            self.assertAlmostEqual(joints['commanded_model_deg'][joint],STAND[JOINTS[joint]]+delta)
            self.assertAlmostEqual(joints['model_deg'][joint],STAND[JOINTS[joint]]+.75*delta)

    def test_fall_magnitude_varies_and_tracks_the_supplied_effect(self):
        magnitudes={False:set(),True:set()}
        with patch('experiments.freestyle.library_recovery.foot_positions',return_value={'foot':[0,0,0]}):
            for seed in range(30):
                source=self.source(['move',0,12,'current',50])
                source['id']=format(seed,'08x')+'00000000'
                for probe in (False,True):
                    fall=list(scenarios(source,None,probe))[1]
                    effect=json.loads(fall['query'])['history'][0]['last_correction']
                    expected=[v*(1 if fall['recovery_evidence']['improved'] else -1)
                              for _,v in effect['delta_deg']]
                    self.assertEqual(fall['answers'][1][2],expected)
                    magnitudes[probe].add(abs(expected[0]))
        self.assertEqual(magnitudes[False],{1,2,3,4,6})
        self.assertEqual(magnitudes[True],{1.5,2.5,3.5,4.5,6.5})
