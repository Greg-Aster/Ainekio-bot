import json
import math
import unittest
from pathlib import Path

from .challenge import assess, replay, trajectory_metrics
from .kinematics import ROOT
from .runtime import JOINTS
from .semantic_teachers import demonstration, legacy_sources, source_motion
from .program import compile_motion


class SemanticTeacherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=json.loads((ROOT/'motions/gestures/wave/source.json').read_text())
        q=[math.degrees(angle) for leg in source['samples'][0]['actuator_angles_rad'] for angle in leg]
        cls.state={'joints':{joint:{'model_deg':angle,'home_deg':angle} for joint,angle in zip(JOINTS,q)},
                   'joint_speed_limit_deg_s':180}

    def test_five_claps_have_five_full_symmetric_closures_and_returns(self):
        trace=replay(demonstration('clapping',cycles=5),self.state)
        self.assertEqual(trace['status'],'replayed')
        metrics=trajectory_metrics(trace)
        criteria=[{'metric':f'foot.front_{side}.y.excursions','excursion_mm':sign*19,
                   'return_tolerance_mm':.2,'min':5,'max':5}
                  for side,sign in [('left',-1),('right',1)]]
        self.assertTrue(assess(metrics,criteria,trace)['criteria_passed'])
        self.assertLess(metrics['foot.front_left.return_error'],.05)
        self.assertLess(metrics['foot.front_right.return_error'],.05)

    def test_circle_trace_has_area_and_closes_instead_of_merely_wiggling(self):
        trace=replay(demonstration('hand_circle',side='right',cycles=1),self.state)
        self.assertEqual(trace['status'],'replayed')
        metrics=trajectory_metrics(trace)
        self.assertGreater(abs(metrics['foot.front_right.xy.signed_area']),250)
        self.assertLess(metrics['foot.front_right.return_error'],.05)
        self.assertLess(metrics['foot.front_left.return_error'],.05)

    def test_unspecified_hand_metrics_do_not_assume_the_right_side(self):
        values=[]
        for side in ('left','right'):
            trace=replay(demonstration('tapping',side=side,cycles=1),self.state)
            self.assertEqual(trace['status'],'replayed')
            values.append(trajectory_metrics(trace)['front.any.z.range'])
        self.assertAlmostEqual(values[0],values[1],delta=.05)
        self.assertGreater(min(values),29.9)

    def test_drinking_and_repeated_salutes_reach_head_height_and_return(self):
        for family in ('drinking','saluting'):
            for side in ('left','right'):
                program=demonstration(family,side,cycles=2,observation=self.state)
                trace=replay(program,self.state)
                self.assertEqual(trace['status'],'replayed')
                holds=[i for i,a in enumerate(program) if a['name']=='hold']
                self.assertEqual(len(holds),2 if family=='saluting' else 1)
                for index in holds:
                    sample=next(s for s in trace['samples'] if s['action_index']==index)
                    hand=sample['feet_body_mm']['front_'+side]
                    self.assertAlmostEqual(hand[0],95,delta=.02)
                    self.assertAlmostEqual(hand[1],90 if side=='left' else -90,delta=.02)
                    self.assertAlmostEqual(hand[2],105,delta=.02)
                for leg in ('front_left','front_right','rear_left','rear_right'):
                    self.assertLess(math.dist(trace['samples'][0]['feet_body_mm'][leg],
                                              trace['samples'][-1]['feet_body_mm'][leg]),.05)

    def test_native_motions_export_compact_stages_and_complete_endpoints(self):
        compiler,clips=legacy_sources()
        for name,clip in clips.items():
            taught=source_motion(name)
            self.assertFalse(any(a['name']=='trajectory' for a in taught['program']))
            self.assertLess(len(taught['program']),30)
            state={'joints':{j:{'model_deg':v,'commanded_model_deg':v,'home_deg':0} for j,v in zip(JOINTS,taught['entry_model_deg'])},
                   'joint_speed_limit_deg_s':180}
            planned=None
            for action in taught['program']:
                if action['name'] not in ('face','hold'):planned=compile_motion(action,state,planned)['end']
            for j,value in zip(JOINTS,taught['final_model_deg']):self.assertAlmostEqual(planned[j],value,places=2)

    def test_compact_stretch_crouches_extends_front_limbs_and_finishes_standing(self):
        from .semantic_teachers import stretch_program
        from .kinematics import foot_positions
        program=stretch_program();entry=program[1]['arguments']['angles_deg']
        state={'joints':{j:{'model_deg':v,'commanded_model_deg':v,'home_deg':0} for j,v in zip(JOINTS,entry)},'joint_speed_limit_deg_s':180}
        planned=None;feet=[]
        for action in program:
            if action['name'] not in ('face','hold'):
                planned=compile_motion(action,state,planned)['end'];feet.append(foot_positions(planned))
        self.assertAlmostEqual(feet[1]['front_left'][2]-feet[0]['front_left'][2],18,delta=.04)
        self.assertAlmostEqual(feet[3]['front_right'][2]-feet[2]['front_right'][2],18,delta=.04)
        for leg in ('front_left','front_right'):
            self.assertAlmostEqual(feet[5][leg][2]-feet[4][leg][2],16,delta=.04)
            self.assertAlmostEqual(feet[6][leg][0]-feet[0][leg][0],35,delta=.04)
        for j,value in zip(JOINTS,entry):self.assertAlmostEqual(planned[j],value,places=2)
        self.assertEqual([a['arguments']['seconds'] for a in program if a['name']=='hold'],[.9,.7,.5])

    def test_fresh_snapshot_has_three_natural_requests_per_reference_motion(self):
        from collections import Counter
        from .compact_wire import ProgramEncoding
        dataset=Path(__file__).with_name('training-data')
        rows=[json.loads(line) for line in (dataset/'train.jsonl').read_text().splitlines() if line]
        recovery=[row for row in rows if row.get('recovery_evidence')]
        self.assertEqual({json.loads(row['query'])['event']['type'] for row in recovery},
                         {'servo_stall','servo_feedback_fault','tipped','rapid_movement','slip'})
        rows=[row for row in rows if row.get('reference_motion')]
        counts=Counter(row['reference_motion'] for row in rows)
        self.assertEqual(len(rows),72)
        self.assertEqual(set(counts),set(legacy_sources()[1])|{'stand'})
        self.assertEqual(set(counts.values()),{3})
        self.assertEqual(len({row['query'] for row in rows}),72)
        encoding=ProgramEncoding(json.loads((dataset/'tools.json').read_text()))
        self.assertNotIn('trajectory',encoding.tools)
        for row in rows:
            query=json.loads(row['query'])
            self.assertIn('request',query)
            self.assertNotIn('degrees',query['request'])
            self.assertNotIn('%',query['request'])
            self.assertFalse(row['physical_qualification'])
            program=encoding.decode(row['answers'])
            self.assertLess(len(program),30)
            if row['reference_motion']=='stand':
                self.assertEqual(program,[{'name':'stand','arguments':{}}])
                continue
            state={'joints':{j:{'model_deg':q,'commanded_model_deg':q,'home_deg':0}
                    for j,q in zip(JOINTS,row['reference_entry_model_deg'])},'joint_speed_limit_deg_s':180}
            planned=None
            for action in program:
                if action['name'] in ('pose','move','feet','body','oscillate'):
                    planned=compile_motion(action,state,planned)['end']
            for joint,q in zip(JOINTS,row['reference_final_model_deg']):
                self.assertAlmostEqual(planned[joint],q,places=2)
        held_out=[json.loads(line) for line in (dataset/'evaluation.jsonl').read_text().splitlines() if line]
        self.assertTrue(held_out)
        self.assertFalse({row['id'] for row in held_out}&{row['id'] for row in rows})

    def test_crouch_training_matches_legacy_with_operating_band(self):
        from .compact_wire import ProgramEncoding
        fixture=json.loads((ROOT/'tests/fixtures/crouch-mapping.json').read_text())
        dataset=Path(__file__).with_name('training-data')
        encoding=ProgramEncoding(json.loads((dataset/'tools.json').read_text()))
        rows=[json.loads(line) for line in (dataset/'train.jsonl').read_text().splitlines() if line]
        rows=[row for row in rows if row.get('reference_motion')=='crouch']
        self.assertEqual(len(rows),3)
        original=source_motion('crouch')
        low,high=fixture['pulse_window_us']
        for row in rows:
            program=encoding.decode(row['answers'])
            self.assertEqual(program,original['program'])
            self.assertEqual([a['arguments']['seconds'] for a in program if a['name']=='hold'],[2])
            observation={'joint_speed_limit_deg_s':180,'joints':{
                joint:{'model_deg':q,'commanded_model_deg':q,'home_deg':0}
                for joint,q in zip(JOINTS,original['entry_model_deg'])}}
            planned=None
            for action in program:
                if action['name']!='pose':continue
                self.assertEqual(action['arguments']['speed_pct'],50)
                compiled=compile_motion(action,observation,planned);planned=compiled['end']
                for mapping,joint in zip(fixture['joints'],JOINTS):
                    pulse=mapping['home_us']+(-1 if mapping['invert'] else 1)*(planned[joint]-mapping['home_cd']/100)*mapping['us_per_degree']
                    self.assertGreaterEqual(pulse,low-.1)
                    self.assertLessEqual(pulse,high+.1)

    def test_compact_wave_preserves_all_three_source_cycles(self):
        program=source_motion('wave')['program']
        oscillations=[action['arguments'] for action in program if action['name']=='oscillate']
        self.assertEqual(len(oscillations),1)
        self.assertEqual(oscillations[0]['cycles'],3)
        self.assertEqual(oscillations[0]['joint'],JOINTS[6])
        self.assertEqual(oscillations[0]['amplitude_deg'],42)

    def test_contextual_source_teacher_retains_compact_stages_and_enters_from_supplied_state(self):
        import copy
        from experiments.freestyle.compact_wire import ProgramEncoding
        from experiments.freestyle.legacy_curriculum import contextual_example
        from experiments.freestyle.motion_space import TOOLS
        from experiments.freestyle.face_contract import face_tool
        tools=[*TOOLS,face_tool()]
        original=source_motion('stretch');encoding=ProgramEncoding(tools)
        source={'id':'source','family':'legacy_asset_stretch','legacy_motion':'stretch',
                'answers':encoding.encode(original['program']),
                'canonical_source_motion_sha256':original['source_sha256'],
                'source_alignment':{k:v for k,v in original.items() if k!='program'},
                'physical_qualification':True}
        snapshot=copy.deepcopy(source);observation=copy.deepcopy(self.state)
        for state in observation['joints'].values():state['commanded_model_deg']=state['model_deg']
        observation['joints'][JOINTS[0]].update(model_deg=15,commanded_model_deg=None)
        row=contextual_example(source,observation,'Please stretch',tools)
        program=encoding.decode(row['answers'])
        self.assertEqual(source,snapshot)
        self.assertEqual(program[0],original['program'][0])
        self.assertEqual(program[1]['arguments']['angles_deg'],original['entry_model_deg'])
        self.assertEqual(program,original['program'])
        self.assertEqual(json.loads(row['query'])['observation']['joints']['model_deg'][0],15)
        planned=None
        for action in program:
            if action['name'] not in ('face','hold'):planned=compile_motion(action,observation,planned)['end']
        for j,value in zip(JOINTS,original['final_model_deg']):self.assertAlmostEqual(planned[j],value,places=6)
        other=contextual_example(source,observation,'Perform stretch.',tools)
        self.assertNotEqual(row['source_id'],other['source_id'])
        self.assertFalse(row['physical_qualification'])

    def test_native_bow_stretch_holds_and_freaky_semantic_end(self):
        for name,durations in [('bow',[5.,.2]),('stretch',[.9,.7,.5])]:
            actual=[a['arguments']['seconds'] for a in source_motion(name)['program'] if a['name']=='hold']
            self.assertEqual(len(actual),len(durations))
            for a,b in zip(actual,durations):self.assertAlmostEqual(a,b,places=8)
        full=json.loads((ROOT/'motions/gestures/freaky/source.json').read_text())
        contract=json.loads((ROOT/'motions/gestures/freaky/execution-contract.json').read_text())
        taught=source_motion('freaky')
        self.assertLess(taught['semantic_end_s'],full['samples'][-1]['time_s'])
        self.assertEqual(taught['semantic_end_s'],contract['completion']['semantic_end_s'])
        expected=[math.degrees(v) for leg in contract['completion']['joint_angles_rad'] for v in leg]
        for a,b in zip(taught['final_model_deg'],expected):self.assertEqual(round(a*100),round(b*100))

    def test_retirement_follows_provenance_and_preserves_unrelated_commands(self):
        from .legacy_curriculum import obsolete_rows
        rows = [
            {'id':'bad','family':'semantic_bowing','parent_example_id':'old-bad'},
            {'id':'derived','family':'library_jam_recovery','parent_examples':[{'id':'old-bad'}]},
            {'id':'face','family':'face_only','query':'Show the bow face.'},
            {'id':'spatial','family':'spatial_rotation','query':'Pitch six degrees.'},
            {'id':'compound','family':'open_composition','task_families':['bow','circle']},
            {'id':'current','family':'legacy_asset_bow'},
        ]
        selected,aliases = obsolete_rows(rows,[{'id':'current'}])
        self.assertEqual(selected,{'bad','derived','compound'})
        self.assertIn('old-bad',aliases)


if __name__=='__main__':unittest.main()
