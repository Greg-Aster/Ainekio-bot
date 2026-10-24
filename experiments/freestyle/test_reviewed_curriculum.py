import copy
import unittest
from unittest.mock import patch

from .curriculum import Author, example, source_state
from .ending_curriculum import replace_wave_ending
from .reviewed_curriculum import add_faces, recorded_proposals, eating_program
from .challenge import replay
from .runtime import JOINTS
from .semantic_teachers import source_wave, feet


class ReviewedCurriculumTests(unittest.TestCase):
    def test_eating_mime_reaches_face_twice_and_finishes_exact_stand(self):
        state=source_state();stand=[0,3.46,-21.63]*4
        state['joints']['front_right_shoulder']['model_deg']=-31.05
        program=eating_program(state,stand)
        trace=replay(program,state)
        self.assertEqual(trace['status'],'replayed',trace.get('error'))
        self.assertEqual(trace['completed_actions'],len(program))
        self.assertEqual(list(trace['samples'][-1]['joints_deg'].values()),stand)
        bites=[i for i,a in enumerate(program) if a['name']=='hold' and a['arguments']['seconds']==.25]
        self.assertEqual(len(bites),2)
        for index in bites:
            sample=next(s for s in reversed(trace['samples']) if s['action_index']==index)
            for actual,expected in zip(sample['feet_body_mm']['front_right'],[95,-90,105]):
                self.assertAlmostEqual(actual,expected,delta=.15)
        self.assertTrue(all(a['arguments']['legs']==['front_right'] for a in program if a['name']=='feet'))

    def test_eating_explicit_endings_and_repetitions_are_preserved(self):
        state=source_state();stand=[0,3.46,-21.63]*4
        start=[state['joints'][j]['model_deg'] for j in JOINTS]
        returned=eating_program(state,stand,'left',1,'start')
        self.assertEqual(returned[-1]['arguments']['angles_deg'],start)
        raised=eating_program(state,stand,'left',3,'raised')
        self.assertEqual(raised[-1]['name'],'feet')
        self.assertEqual(sum(a['name']=='hold' and a['arguments']['seconds']==.25 for a in raised),3)

    def test_wave_endpoint_controls_all_joints_and_can_return_measured_start(self):
        original=source_wave('right',2)
        stand=[0,3.46,-21.63]*4
        fixed=replace_wave_ending(original,stand)
        last=next(a for a in reversed(fixed) if a['name']=='pose')
        self.assertEqual(last['arguments']['joints'],list(JOINTS))
        self.assertEqual(last['arguments']['angles_deg'],stand)
        self.assertEqual(fixed[:6],original[:6])
        self.assertEqual(fixed[-1],original[-1])
        start=stand[:];start[6]=-35
        returned=replace_wave_ending(original,start)
        self.assertEqual(returned[-2]['arguments']['angles_deg'][6],-35)
        self.assertNotEqual(original[-2]['arguments']['joints'],list(JOINTS))

    def test_face_annotation_preserves_every_motion_target_hold_and_goal(self):
        state=source_state();author=Author(state);author.task('wave','left',1,16)
        row=example('wave',state,author.program,'open_task',goals=author.goals)
        result=add_faces(row,{0:'wave',2:'happy'})
        self.assertEqual([a for a in result['answers'] if a['name']!='face'],row['answers'])
        self.assertEqual([g for g in result['goals'] if g['kind']!='face'],row['goals'])
        self.assertEqual(len(result['answers']),len(result['goals']))

    def test_recorded_stretch_fixes_four_leg_return_without_trimming_excursion(self):
        legs=['rear_left','rear_right','front_left','front_right']
        original=[feet(legs,[[0,0,30]]*4,.6),feet(['front_left','front_right'],[[0,0,-30]]*4,.6)]
        request={'request':'stretch','observation':source_state(),'event':None,'history':[{'note':'preserve me'}]}
        records=[{'id':'request','job_id':'job','kind':'generation_requested','payload':{'request':request}},
                 {'id':'output','job_id':'job','kind':'generation_completed','payload':{'result':{'program':original}}}]
        with patch('experiments.freestyle.reviewed_curriculum.read_records',return_value=records):
            row=next(recorded_proposals('unused',[0,3.46,-21.63]*4))
        actions=row['answers'];self.assertEqual(actions[0]['name'],'face')
        self.assertEqual(actions[1],original[0])
        self.assertEqual(actions[2]['arguments']['legs'],legs)
        self.assertEqual(actions[2]['arguments']['offsets_mm'],[[0,0,-30]]*4)
        self.assertEqual(actions[-1]['arguments']['joints'],list(JOINTS))
        self.assertFalse(row['physical_qualification'])
        self.assertEqual(row['qualification_basis'],'proposed_correction_not_executed')


if __name__=='__main__':unittest.main()
