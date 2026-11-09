import copy
import unittest

from .compact_wire import ProgramEncoding
from .library_recovery import completion, deduplicate
from .migrate_targets import CONTRACT, STAND
from .runtime import JOINTS


class LibraryRecoveryTests(unittest.TestCase):
    def test_shared_recovery_keeps_every_source_without_duplicate_training_rows(self):
        rows=[{'id':'same-content','reference_example_id':p,'reference_source_hash':p+'-hash'} for p in ('a','b')]
        unique=deduplicate(rows)
        self.assertEqual(len(unique),1)
        self.assertEqual(unique[0]['reference_examples'],[
            {'id':'a','source_hash':'a-hash'},{'id':'b','source_hash':'b-hash'}])

    def test_recovery_keeps_original_absolute_goal_and_unfinished_tail(self):
        encoding=ProgramEncoding(CONTRACT)
        action=encoding.decode([['move',1,12,'current',50,0]])[0]
        goal={**STAND,JOINTS[1]:STAND[JOINTS[1]]+12}
        # A non-standing terminal posture detects the old unconditional finish.
        tail=encoding.decode([['pose',list(range(12)),[-32.52,33.34,50.91]*4,'absolute',50,0],['hold',1.8]])
        before=copy.deepcopy((action,goal,tail))
        program=completion(action,STAND,goal,tail,50)
        self.assertEqual(program[0]['arguments']['angles_deg'],[goal[j] for j in JOINTS])
        self.assertEqual(program[0]['arguments']['reference'],'absolute')
        self.assertEqual(program[1:],tail)
        self.assertEqual((action,goal,tail),before)
        self.assertIsNot(program[1],tail[0])

    def test_both_directions_keep_the_full_requested_joint_target(self):
        for joint in JOINTS:
            for direction in (-1,1):
                goal={**STAND,joint:STAND[joint]+direction*12}
                action={'name':'move','arguments':{'joint':joint,'angle_deg':direction*12,
                        'reference':'current','speed_pct':50,'taper_deg':0}}
                program=completion(action,STAND,goal,[],50)
                self.assertEqual(dict(zip(program[0]['arguments']['joints'],
                    program[0]['arguments']['angles_deg'])),goal)

    def test_simultaneous_targets_are_not_shortened_during_completion(self):
        goal={**STAND,JOINTS[1]:STAND[JOINTS[1]]+12,JOINTS[7]:STAND[JOINTS[7]]-12}
        action={'name':'pose','arguments':{'joints':[JOINTS[1],JOINTS[7]],
            'angles_deg':[12,-12],'reference':'current','speed_pct':75,'taper_deg':0}}
        program=completion(action,STAND,goal,[],75)
        args=program[0]['arguments']
        self.assertEqual(dict(zip(args['joints'],args['angles_deg'])),goal)
        self.assertEqual(args['speed_pct'],75)

    def test_oscillation_preserves_center_amplitude_and_complete_cycles(self):
        action={'name':'oscillate','arguments':{'joint':JOINTS[6],'amplitude_deg':12,
            'cycles':4,'speed_pct':50,'taper_deg':0}}
        program=completion(action,STAND,{**STAND,JOINTS[6]:12},[],50)
        self.assertEqual(program[0]['arguments']['angles_deg'],list(STAND.values()))
        self.assertEqual(program[1],action)
        self.assertEqual(program[-1]['arguments']['cycles'],4)

    def test_finite_gait_keeps_the_requested_cycles_and_following_hold(self):
        action={'name':'gait','arguments':{'command':'walk','cycles':3,'speed_pct':75}}
        tail=[{'name':'hold','arguments':{'seconds':2}}]
        self.assertEqual(completion(action,STAND,STAND,tail,75),[action,*tail])

    def test_standalone_and_error_recovery_scenarios_compile_cleanly(self):
        import json
        from .library_recovery import standalone_scenarios, validate_prefix
        rows=list(standalone_scenarios(False))
        self.assertEqual({json.loads(r['query'])['event']['type'] for r in rows},
                         {'servo_stall','servo_feedback_fault','slip','tipped','rapid_movement'})
        for r in rows:
            q=json.loads(r['query'])
            self.assertEqual(q['request'],'Recover from the reported body event using the available observations.')
            self.assertEqual(q['history'],[])
            self.assertNotIn('motion_goal',q)
            self.assertTrue(validate_prefix(r))
