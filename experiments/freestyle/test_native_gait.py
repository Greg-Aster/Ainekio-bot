"""Run with FREESTYLE_NATIVE_GAIT pointing at the compiled offline sampler."""
import json
import math
import os
import unittest
from pathlib import Path

from .challenge import replay
from .gait_replay import sample_gait
from .kinematics import ROOT
from .runtime import JOINTS


@unittest.skipUnless(os.environ.get('FREESTYLE_NATIVE_GAIT'), 'native gait executable not configured')
class NativeGaitTests(unittest.TestCase):
    def setUp(self):
        self.executable = Path(os.environ['FREESTYLE_NATIVE_GAIT']).resolve()
        source = json.loads((ROOT/'motions/gestures/wave/source.json').read_text())
        angles = [math.degrees(q) for leg in source['samples'][0]['actuator_angles_rad'] for q in leg]
        self.state = {'joints':{j:{'model_deg':q,'home_deg':q} for j,q in zip(JOINTS,angles)},
                      'joint_speed_limit_deg_s':180}

    def test_twelve_cycles_preserve_both_packets_and_terminal_targets(self):
        result = sample_gait({'command':'walk','speed_pct':50,'cycles':12},180,self.executable)
        self.assertEqual(result['status'],'replayed')
        self.assertEqual([s['command']['steps'] for s in result['segments']],[10,2])
        for segment in result['segments']:
            self.assertTrue(segment['samples'][-1]['complete'])
            self.assertGreater(segment['samples'][-1]['body_mm'][0],0)
            self.assertEqual(segment['samples'][0]['time_us'],0)

    def test_following_hold_and_relative_move_use_native_final_pose(self):
        gait = {'name':'gait','arguments':{'command':'backward','speed_pct':50,'cycles':1}}
        program = [gait, {'name':'hold','arguments':{'seconds':.7}},
                   {'name':'move','arguments':{'joint':JOINTS[0],'angle_deg':5,
                                              'reference':'current','speed_pct':50}}]
        trace = replay(program,self.state,self.executable)
        self.assertEqual(trace['status'],'replayed')
        self.assertEqual(trace['completed_actions'],3)
        native = trace['native_gait_segments'][0]['samples'][-1]
        self.assertLess(native['body_mm'][0],0)
        held = [s for s in trace['samples'] if s['action_index']==1][-1]
        self.assertAlmostEqual(held['time_s'],native['time_us']/1e6+.7)
        for j,q in zip(JOINTS,native['model_deg']):
            self.assertAlmostEqual(held['joints_deg'][j],q)
            self.assertAlmostEqual(trace['samples'][-1]['joints_deg'][j],q+(5 if j==JOINTS[0] else 0),places=2)

    def test_ongoing_command_does_not_fabricate_completion_or_later_motion(self):
        program = [{'name':'hold','arguments':{'seconds':.3}},
                   {'name':'gait','arguments':{'command':'walk','speed_pct':50,'cycles':0}},
                   {'name':'hold','arguments':{'seconds':4}}]
        trace = replay(program,self.state,self.executable)
        self.assertEqual(trace['status'],'not_fully_replayed')
        self.assertEqual(trace['completed_actions'],1)
        self.assertEqual(trace['samples'][-1]['time_s'],.3)
        self.assertEqual(trace['native_gait_segments'][0]['samples'],[])


if __name__ == '__main__':
    unittest.main()
