import copy
import json
import math
import unittest

from .curriculum import (Author, audit, composition_group, composition_split,
                         compositions, example, imu, prune_rehearsal,
                         recovery_examples, source_state)
from .curriculum_split import motion_structure, isolate
from .curriculum_recovery import grounded_examples


class CurriculumTests(unittest.TestCase):
    def test_composition_variants_stay_together(self):
        rows = list(compositions(8101, 12))
        groups = {}
        for row in rows:
            groups.setdefault(row['composition_group'], set()).add(row['split'])
        self.assertTrue(all(len(splits)==1 for splits in groups.values()))
        self.assertEqual(composition_group(('wave', 'bow')), 'composition:wave,bow')
        self.assertEqual(len({r['id'] for r in rows}), len(rows))

    def test_compiler_replay_must_reach_authored_goals_and_keep_holds(self):
        state = source_state(); author = Author(state)
        author.task('salute', 'right', 1, 16)
        row = example('Salute', state, author.program, 'test', goals=author.goals)
        _, evidence = audit(row)
        self.assertTrue(evidence['accepted'], evidence)
        # A valid but shortened motion must fail the geometry checks.
        wrong = copy.deepcopy(row)
        wrong['answers'][0]['arguments']['offsets_mm'][0][2] /= 2
        _, evidence = audit(wrong)
        self.assertFalse(evidence['accepted'], evidence)
        wrong = copy.deepcopy(row)
        hold = next(a for a in wrong['answers'] if a['name']=='hold')
        hold['arguments']['seconds'] += .3
        _, evidence = audit(wrong)
        self.assertFalse(evidence['accepted'], evidence)

    def test_unrequested_other_hand_motion_fails_the_goal(self):
        state=source_state(); author=Author(state)
        author.task('point', 'left', 1, 16)
        row=example('Point left',state,author.program,'test',goals=author.goals)
        row['answers'][0]['arguments']['legs'].append('front_right')
        row['answers'][0]['arguments']['offsets_mm'].append([0,0,10])
        self.assertFalse(audit(row)[1]['accepted'])

    def test_source_pose_homes_do_not_change_with_sitting(self):
        stand, sit = source_state(), source_state('sit')
        self.assertEqual([v['home_deg'] for v in stand['joints'].values()],
                         [v['home_deg'] for v in sit['joints'].values()])
        self.assertNotEqual([v['model_deg'] for v in stand['joints'].values()],
                            [v['model_deg'] for v in sit['joints'].values()])

    def test_recovery_is_coherent_front_arm_evidence_and_unknown_outcome(self):
        rows=list(recovery_examples())
        self.assertEqual(len(rows),112)
        for row in rows:
            q=json.loads(row['query'])
            stamps=[h['time_us'] for h in q['history']]
            self.assertEqual(stamps,sorted(set(stamps)))
            self.assertFalse(row['physical_qualification'])
            self.assertEqual(row['answers'][-1]['name'],'reassess')
            if row['family']=='recovery_wave':
                self.assertTrue(row['answers'][0]['arguments']['joint'].startswith('front_'))
            else:
                acceleration=q['observation']['imu']['acceleration_m_s2']
                self.assertAlmostEqual(math.sqrt(sum(v*v for v in acceleration)),9.80665,places=5)

    def test_rehearsal_deduplicates_targets_and_removes_bad_recovery(self):
        state=source_state(); author=Author(state); author.task('point','left',1,16)
        original=example('Point',state,author.program,'point')
        alias=example('Point please',state,author.program,'point')
        bad=example('Recover',state,author.program,'fall_correction',event={'type':'fallen'})
        selected, decisions=prune_rehearsal([original,alias,bad,original])
        self.assertEqual(len(selected),1)
        self.assertEqual(len(decisions),4)

    def test_structure_groups_ignore_magnitude_time_and_mirror(self):
        left=[{'name':'feet','arguments':{'legs':['front_left'],'offsets_mm':[[10,20,30]],'seconds':.5}}]
        right=[{'name':'feet','arguments':{'legs':['front_right'],'offsets_mm':[[20,-40,60]],'seconds':1}}]
        self.assertEqual(motion_structure(left),motion_structure(right))
        two=[{'name':'feet','arguments':{'legs':['front_left','front_right'],'offsets_mm':[[10,20,30],[10,-20,30]],'seconds':.5}}]
        reverse=copy.deepcopy(two)
        reverse[0]['arguments']['legs'].reverse();reverse[0]['arguments']['offsets_mm'].reverse()
        self.assertEqual(motion_structure(two),motion_structure(reverse))
        rows=[{'id':str(i),'family':'open_composition','answers':program,'composition_group':group}
              for i,(program,group) in enumerate(((left,'a'),(right,'b'),(two,'b'),(reverse,'c')))]
        self.assertEqual(len({r['split_component_sha256'] for r in isolate(rows)}),1)

    def test_one_figure_eight_is_one_period_and_shuffle_slides_before_lifting(self):
        author=Author(source_state());author.task('figure_eight','left',1,16)
        signs=[]
        for goal in author.goals[1:17]:
            y=goal['after']['front_left'][1]-100
            if abs(y)<1e-6:continue
            sign=1 if y>0 else -1
            if not signs or signs[-1]!=sign:signs.append(sign)
        self.assertEqual(signs,[1,-1])
        author=Author(source_state());author.task('shuffle','left',1,16)
        first,second,third,fourth=author.goals[:4]
        self.assertLess(first['after']['front_left'][0],first['before']['front_left'][0])
        self.assertEqual(first['after']['front_left'][2],first['before']['front_left'][2])
        self.assertGreater(second['after']['front_left'][2],second['before']['front_left'][2])
        self.assertGreater(third['after']['front_left'][0],third['before']['front_left'][0])
        self.assertLess(fourth['after']['front_left'][2],fourth['before']['front_left'][2])

    def test_grounded_wave_starts_extended_and_probes_are_not_training(self):
        rows=list(grounded_examples())
        self.assertEqual(sum(r['split']=='recovery-probe' for r in rows),28)
        self.assertEqual(sum(r['split']=='train' for r in rows),84)
        for row in rows:
            if row['family']!='recovery_wave':continue
            q=json.loads(row['query']);joint=row['answers'][0]['arguments']['joint'];limb=joint.rsplit('_',1)[0]
            self.assertGreater(q['observation']['joints'][limb+'_carrier']['model_deg'],40)
            first,last=q['history'][0]['joints'][joint],q['history'][-1]['joints'][joint]
            center=row['answers'][0]['arguments']['angle_deg']
            self.assertAlmostEqual(center,(first+last)/2,places=4)


if __name__=='__main__': unittest.main()
