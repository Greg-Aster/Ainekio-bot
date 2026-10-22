import unittest
from compact import records, TOOLS
from benchmark_compact import equivalent_program


class CompactDatasetTests(unittest.TestCase):
    def test_equivalence_preserves_joint_values_ordering_and_concurrency(self):
        one = {'name':'move','arguments':{'joint':'front_right_shoulder','angle_deg':20,'reference':'home','speed_pct':50}}
        pose = {'name':'pose','arguments':{'joints':['front_right_shoulder'],'angles_deg':[20],'reference':'home','speed_pct':50}}
        hold = {'name':'hold','arguments':{'seconds':2}}
        self.assertTrue(equivalent_program([pose,hold], [one,hold]))
        self.assertFalse(equivalent_program([hold,pose], [one,hold]))
        self.assertFalse(equivalent_program([pose], [one,hold]))
        pair = {'name':'pose','arguments':{'joints':['front_right_shoulder','front_left_shoulder'],'angles_deg':[20,-20],'reference':'home','speed_pct':50}}
        reversed_pair = {'name':'pose','arguments':{**pair['arguments'],'joints':['front_left_shoulder','front_right_shoulder'],'angles_deg':[-20,20]}}
        self.assertTrue(equivalent_program([pair], [reversed_pair]))
        other = {'name':'move','arguments':{**one['arguments'],'joint':'front_left_shoulder','angle_deg':-20}}
        self.assertFalse(equivalent_program([one,other], [pair]))
        wrong = {'name':'pose','arguments':{**pose['arguments'],'angles_deg':[25]}}
        self.assertFalse(equivalent_program([wrong], [one]))

    def test_split_requests_are_independent(self):
        groups = [{r['query'] for r in records(s)} for s in ('train', 'evaluation', 'test')]
        self.assertFalse(groups[0] & groups[1])
        self.assertFalse(groups[0] & groups[2])
        self.assertFalse(groups[1] & groups[2])

    def test_complete_move_hold_return_example(self):
        candidates = [r for r in records('train') if r['family']=='move_hold_return'
                      and 'front right shoulder 20 degrees' in r['query'] and '2 seconds' in r['query']]
        self.assertEqual(len(candidates), 1)
        actions = candidates[0]['answers']
        self.assertEqual([a['name'] for a in actions], ['move','hold','move'])
        self.assertEqual(actions[0]['arguments']['angle_deg'], 20)
        self.assertEqual(actions[1]['arguments']['seconds'], 2)
        self.assertEqual(actions[2]['arguments']['angle_deg'], 0)
        self.assertEqual(actions[2]['arguments']['reference'], 'home')

    def test_every_declared_action_and_argument_is_supported(self):
        definitions = {t['name']:t['parameters'] for t in TOOLS}
        for split in ('train','evaluation','test'):
            for row in records(split):
                for action in row['answers']:
                    schema = definitions[action['name']]
                    self.assertEqual(set(action['arguments']),set(schema['required']))
                    for key,value in action['arguments'].items():
                        spec = schema['properties'][key]
                        if 'enum' in spec: self.assertIn(value,spec['enum'])
                    if action['name']=='pose':
                        self.assertEqual(len(action['arguments']['joints']),len(action['arguments']['angles_deg']))


if __name__ == '__main__': unittest.main()
