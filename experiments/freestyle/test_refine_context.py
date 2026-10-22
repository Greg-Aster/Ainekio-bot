import json
import random
import unittest
from pathlib import Path

from refine_context import records, observation, leg_targets
from runtime import JOINTS


class ContextDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path('Slave/software/models/v2-12servo')
        cls.rows=records('train',cls.root)

    def test_ordinary_requests_have_full_body_context(self):
        ordinary=[r for r in self.rows if r['family']=='natural_gesture']
        self.assertTrue(ordinary)
        for r in ordinary:
            value=json.loads(r['query'])
            self.assertEqual(set(value['observation']['joints']),set(JOINTS))
            self.assertIsNone(value['event'])
            self.assertEqual(r['answers'][0]['name'],'gesture')
        wave=[r for r in ordinary if json.loads(r['query'])['request']=='wave']
        self.assertTrue(wave)
        self.assertTrue(all(r['answers']==[{'name':'gesture','arguments':{'name':'wave'}}] for r in wave))

    def test_speed_units_follow_requested_percent_not_sensor_rate(self):
        cases=[r for r in self.rows if r['family']=='speed_units']
        self.assertTrue(cases)
        for r in cases:
            value=json.loads(r['query'])
            percent=r['answers'][0]['arguments']['speed_pct']
            self.assertIn(f'{percent}%',value['request'])
            self.assertNotEqual(percent,value['observation']['joint_speed_limit_deg_s'])
        self.assertTrue(any(r['answers'][0]['arguments']['speed_pct']>100 for r in cases))

    def test_same_wave_goal_has_evidence_based_jam_targets(self):
        jam=[r for r in self.rows if r['family']=='natural_jam_smaller_wave' and json.loads(r['query'])['request']=='wave']
        self.assertTrue(jam)
        for r in jam:
            value=json.loads(r['query'])
            self.assertEqual(value['event']['type'],'servo_stall')
            self.assertEqual([a['name'] for a in r['answers']],['move','oscillate','reassess'])
            self.assertTrue(value['history'])

    def test_lift_targets_come_from_authored_sample_and_keep_order(self):
        targets,_=leg_targets(self.root)
        source=json.loads((self.root/'motions/gestures/wave/source.json').read_text())
        import math
        expected=[round(math.degrees(v),2) for v in source['samples'][192]['actuator_angles_rad'][2]]
        self.assertEqual(targets['left']['lift'],expected)
        for r in self.rows:
            if r['family']!='natural_leg_sequence':continue
            self.assertFalse(r['physical_qualification'])
            text=json.loads(r['query'])['request']
            if ' then ' in text and 'hold' not in text:
                self.assertEqual([a['name'] for a in r['answers']],['pose','pose'])
                first='right' if text.index('right')<text.index('left') else 'left'
                self.assertTrue(r['answers'][0]['arguments']['joints'][0].startswith('front_'+first))


if __name__=='__main__':unittest.main()
