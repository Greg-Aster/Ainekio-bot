import json
import unittest
from collections import Counter

from .recovery_curriculum import examples
from .migrate_targets import CONTRACT
from .compact_wire import ProgramEncoding
from .program import compile_motion
from .runtime import JOINTS


class RecoveryCurriculumTests(unittest.TestCase):
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
            self.assertEqual(program[-1]['name'],'stand' if 'standing' in query['request'] else 'oscillate')
            self.assertFalse(row['physical_qualification'])
