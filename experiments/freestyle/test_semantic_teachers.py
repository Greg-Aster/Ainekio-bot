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

    def test_all_native_motions_preserve_paths_phase_boundaries_and_completion(self):
        from .trajectory import track_sample
        compiler,clips=legacy_sources()
        catalog=json.loads((ROOT/'motions/gestures/catalog.json').read_text())
        self.assertEqual(set(clips),{entry['command'] for entry in catalog['commands']})
        for name,clip in clips.items():
            with self.subTest(motion=name):
                taught=source_motion(name);action=taught['program'][1]
                self.assertEqual([p['name'] for p in taught['program']],['face','trajectory'])
                required=set(compiler.gesture_targets(clip['positions'],clip['phases']))
                self.assertEqual(required,{round(t*120) for t in action['arguments']['checkpoints_s']})
                self.assertEqual(taught['semantic_end_s'],clip['duration_s'])
                state={'joints':{j:{'model_deg':v,'home_deg':None} for j,v in zip(JOINTS,taught['entry_model_deg'])},
                       'joint_speed_limit_deg_s':180}
                compiled=compile_motion(action,state)
                self.assertAlmostEqual(compiled['curve']['clock'][-1][2],taught['intentional_hold_s'],places=6)
                for j,value in zip(JOINTS,taught['final_model_deg']):
                    self.assertAlmostEqual(compiled['end'][j],value,places=6)
                curve=compiled['curve'];times=curve['times']
                tracks=[[[t,q[j]/100,v[j]/100] for t,q,v in zip(times,curve['positions'],curve['velocities'])]
                        for j in range(12)]
                worst=0.
                # Compare every original twelve-joint sample to the actual
                # expanded upload, independently of the author's fitted bound.
                for i,row in enumerate(clip['positions']):
                    for j,track in enumerate(tracks):
                        actual,_=track_sample(track,i/120,times)
                        worst=max(worst,abs(actual-row[j]/100))
                # Same certified fitting + numeric allowance as the maintained
                # native source comparison (0.502 centidegrees).
                self.assertLess(worst,.502/100)

    def test_training_snapshot_contains_the_complete_original_stretch(self):
        import hashlib
        from .compact_wire import ProgramEncoding
        dataset=Path(__file__).with_name('training-data')
        tools=json.loads((dataset/'tools.json').read_text())
        encoding=ProgramEncoding(tools)
        rows=[json.loads(line) for line in (dataset/'train.jsonl').read_text().splitlines() if line]
        stretch=[r for r in rows if r['family']=='legacy_asset_stretch']
        self.assertEqual(len({r['source_id'] for r in stretch}),3)
        self.assertEqual({json.loads(r['query'])['request'] for r in stretch},
                         {'Please stretch','Perform stretch.','Stand up, stretch, and finish standing.'})
        original=source_motion('stretch')
        for row in stretch:
            program=encoding.decode(row['answers'])
            self.assertEqual(program,original['program'])
            self.assertEqual(row['canonical_source_motion_sha256'],original['source_sha256'])
            self.assertEqual(row['source_alignment']['source_samples'],805)
            self.assertFalse(row['physical_qualification'])
            self.assertEqual(row['qualification_basis'],'catalog_source_path_not_a_new_physical_trial')
            self.assertNotIn('original_program',row)
            observation={'joints':{j:{'model_deg':v,'home_deg':None} for j,v in
                                    zip(JOINTS,original['entry_model_deg'])},'joint_speed_limit_deg_s':180}
            compiled=compile_motion(program[1],observation)
            for j,value in zip(JOINTS,original['final_model_deg']):
                self.assertAlmostEqual(compiled['end'][j],value,places=6)
            actual_holds=[b-a for a,b in program[1]['arguments']['holds_s']]
            for a,b in zip(actual_holds,[.9,.7,.5]):self.assertAlmostEqual(a,b,places=8)
        manifest=json.loads((dataset/'manifest.json').read_text())
        for filename in ('train.jsonl','tools.json'):
            self.assertEqual(manifest['files'][filename],hashlib.sha256((dataset/filename).read_bytes()).hexdigest())

    def test_native_bow_stretch_holds_and_freaky_semantic_end(self):
        for name,durations in [('bow',[5.,.2]),('stretch',[.9,.7,.5])]:
            actual=[b-a for a,b in source_motion(name)['program'][1]['arguments']['holds_s']]
            self.assertEqual(len(actual),len(durations))
            for a,b in zip(actual,durations):self.assertAlmostEqual(a,b,places=8)
        full=json.loads((ROOT/'motions/gestures/freaky/source.json').read_text())
        contract=json.loads((ROOT/'motions/gestures/freaky/execution-contract.json').read_text())
        taught=source_motion('freaky')
        self.assertLess(taught['semantic_end_s'],full['samples'][-1]['time_s'])
        self.assertEqual(taught['semantic_end_s'],contract['completion']['semantic_end_s'])
        expected=[math.degrees(v) for leg in contract['completion']['joint_angles_rad'] for v in leg]
        for a,b in zip(taught['final_model_deg'],expected):self.assertAlmostEqual(a,b,places=6)

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
