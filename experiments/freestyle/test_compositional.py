import json
import unittest
from pathlib import Path

from compositional import records, wave_demonstrations
from motion_space import TOOLS


class GenerativeDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=records('evaluation',Path('Slave/software/models/v2-12servo'))

    def test_generated_programs_have_no_named_emote_lookup(self):
        tools={t['name']:t['parameters'] for t in TOOLS}
        self.assertNotIn('gesture',tools)
        for row in self.rows:
            for action in row['answers']:
                self.assertIn(action['name'],tools)
                self.assertEqual(set(action['arguments']),set(tools[action['name']]['required']))
        self.assertTrue({'spatial_sequence','spatial_whole_body','generated_path','generated_rhythm'} <= {r['family'] for r in self.rows})

    def test_full_context_includes_previous_action_and_explicit_speed_units(self):
        for row in self.rows:
            value=json.loads(row['query'])
            self.assertEqual(len(value['observation']['joints']),12)
            self.assertIn('joint_speed_limit_deg_s',value['observation'])

    def test_wave_is_a_generated_sequence_with_all_three_cycles(self):
        rows=[r for r in self.rows if r['family']=='generated_wave_demonstration']
        self.assertTrue(rows)
        for row in rows:
            self.assertGreater(len(row['answers']),5)
            swings=[a for a in row['answers'] if a['name']=='oscillate']
            self.assertEqual(len(swings),1)
            self.assertEqual(swings[0]['arguments']['cycles'],3)
            self.assertEqual(row['answers'][-1],{'name':'hold','arguments':{'seconds':.2}})


if __name__=='__main__':unittest.main()
