import json
import unittest
from collections import Counter

from .recovery_curriculum import examples, calibrated_stretch, calibrated_fault_examples, calibrated_wave, tracking_recovery_examples
from .migrate_targets import CONTRACT, compact_speed, standing_pose
from .compact_wire import ProgramEncoding
from .program import compile_motion
from .runtime import JOINTS


class RecoveryCurriculumTests(unittest.TestCase):
    def test_tracking_corrections_retreat_from_measurement_on_every_joint(self):
        from .curriculum import source_state
        state=source_state()
        rows=list(tracking_recovery_examples(state));held=list(tracking_recovery_examples(state,True))
        self.assertFalse({r['query'] for r in rows}&{r['query'] for r in held})
        self.assertEqual(len(rows),72)
        for row in rows+held:
            q=json.loads(row['query']);a=row['answers'][0]['arguments']
            j=q['observation']['joints'][a['joint']]
            self.assertLess(a['angle_deg']*(j['commanded_model_deg']-j['model_deg']),0)
            self.assertEqual(a['reference'],'current')
            self.assertEqual(row['answers'][-1],standing_pose())
            self.assertFalse(row['physical_qualification'])

    def test_spatial_wave_lifts_before_sweep_and_restores_stand(self):
        from .curriculum import source_state
        nominal=[0,3.46,-21.63]*4
        obs=source_state()
        for j,a in zip(JOINTS,nominal):obs['joints'][j].update(model_deg=a,commanded_model_deg=a)
        for side in ('left','right'):
            plan=calibrated_wave(nominal,side,cycles=2)
            self.assertEqual(plan[2]['name'],'feet')
            self.assertEqual(plan[3]['arguments']['cycles'],2)
            self.assertEqual(plan[-1]['arguments']['angles_deg'],nominal)
            current=None
            for action in plan:
                if action['name'] in ('pose','feet','oscillate'):
                    compiled=compile_motion(action,obs,current)
                    current=compiled['end']
            self.assertEqual(list(current.values()),nominal)


    def test_calibration_fault_retreats_all_joint_roles_and_retains_unknown_outcome(self):
        from .curriculum import source_state
        state=source_state();nominal=[state['joints'][j]['model_deg'] for j in JOINTS]
        rows=list(calibrated_fault_examples(state,nominal))
        held=list(calibrated_fault_examples(state,nominal,True))
        self.assertEqual(len(rows),72)
        self.assertFalse({r['query'] for r in rows}&{r['query'] for r in held})
        self.assertEqual({json.loads(r['query'])['event']['joints'][0]['id'] for r in rows},set(range(12)))
        for row in rows+held:
            q=json.loads(row['query']);a=row['answers'][0]['arguments']
            joint=q['observation']['joints'][a['joint']]
            self.assertFalse(joint['feedback_usable'])
            low,high=joint['feedback_range_deg']
            self.assertTrue(low<a['angle_deg']<high)
            self.assertEqual(row['answers'][-1],standing_pose())
            self.assertFalse(row['physical_qualification'])

    def test_calibrated_stretch_restores_excursions_and_returns_to_nominal(self):
        nominal=[0,3.46,-21.63]*4;high=[0,6.045,-22.178]*4
        program=calibrated_stretch(nominal,high)
        self.assertEqual(program[-2]['arguments']['angles_deg'],high)
        self.assertEqual(program[-1]['arguments']['angles_deg'],nominal)
        displacement={leg:[0,0,0] for leg in ('front_left','front_right','rear_left','rear_right')}
        for action in program:
            if action['name']=='feet':
                args=action['arguments']
                for leg,delta in zip(args['legs'],args['offsets_mm']):
                    displacement[leg]=[a+b for a,b in zip(displacement[leg],delta)]
        self.assertTrue(all(v==[0,0,0] for v in displacement.values()))
        self.assertEqual([a['arguments']['seconds'] for a in program if a['name']=='hold'],[.6]*4)

    def test_shorter_speed_values_preserve_the_actual_wire_command(self):
        from .program import target
        positions=dict.fromkeys(JOINTS,0)
        for base in (1,90,180,1000,3600):
            for original in (.000001,.062133,12.345678,116.666667,300.123456):
                shortened=compact_speed(original,base)
                self.assertGreater(shortened,0)
                self.assertEqual(target(base*original/100,positions),target(base*shortened/100,positions))

    def test_adaptation_retreats_then_finishes_the_goal_without_repeating_the_failed_extreme(self):
        train=list(examples());evaluation=list(examples(True))
        self.assertEqual(len(train),24)
        self.assertFalse({r['id'] for r in train}&{r['id'] for r in evaluation})
        self.assertEqual(Counter(r['answers'][0][1] for r in train),{'angry':8,'confused':8,'sad':8})
        encoding=ProgramEncoding(CONTRACT)
        for row in train+evaluation:
            query=json.loads(row['query']);obs=query['observation'];packed=obs['joints']
            obs['joints']={JOINTS[j]:{k:v[n] for k,v in packed.items() if k!='ids'} for n,j in enumerate(packed['ids'])}
            joint=JOINTS[query['event']['joints'][0]]
            failed=obs['joints'][joint]['model_deg']
            direction=1 if obs['joints'][joint]['commanded_model_deg']>failed else -1
            program=encoding.decode(row['answers']);planned=None
            for action in program:
                if action['name'] in ('move','oscillate'):
                    result=compile_motion(action,obs,planned);planned=result['end']
                    for _,targets in result['frames']:
                        self.assertLess(direction*(targets[JOINTS.index(joint)]/100-failed),0)
            self.assertEqual(program[-1]['name'],'pose' if 'standing' in query['request'] else 'oscillate')
            if 'standing' in query['request']:
                self.assertEqual(program[-1]['name'],'pose')
                self.assertEqual(program[-1]['arguments']['joints'],list(JOINTS))
            self.assertFalse(row['physical_qualification'])

    def test_checked_in_training_snapshot_matches_current_motion_contract(self):
        from pathlib import Path
        from jsonschema import Draft202012Validator
        from .generator import argument_schema
        root=Path(__file__).with_name('training-data')
        encoding=ProgramEncoding(CONTRACT)
        validator=Draft202012Validator(encoding.schema(argument_schema))
        for path in root.glob('*.jsonl'):
            for line in path.read_text().splitlines():
                row=json.loads(line)
                with self.subTest(split=path.name, example=row['id']):
                    self.assertNotIn('reassess',line.lower())
                    validator.validate(row['answers'])
        for name in ('system.txt','tools.json'):
            self.assertNotIn('reassess',(root/name).read_text().lower())
