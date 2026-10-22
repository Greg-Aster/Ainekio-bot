import json
import math
import unittest

from experiments.freestyle.kinematics import ROOT, foot_positions, frames_for_spatial, mechanism
from experiments.freestyle.runtime import JOINTS


class SpatialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=json.loads((ROOT/'motions/gestures/wave/source.json').read_text())
        cls.start=dict(zip(JOINTS,[math.degrees(q) for leg in source['samples'][0]['actuator_angles_rad'] for q in leg]))

    def test_new_foot_translation_reaches_target_and_keeps_other_joints(self):
        before=foot_positions(self.start)
        action={'name':'feet','arguments':{'legs':['front_right'],'offsets_mm':[[3,2,5]],'seconds':.5}}
        frames=frames_for_spatial(action,self.start)
        self.assertEqual(sum(f[0] for f in frames),500)
        after=dict(zip(JOINTS,[v/100 for v in frames[-1][1]]))
        target=foot_positions(after)['front_right']
        for a,b,d in zip(target,before['front_right'],[3,2,5]):self.assertAlmostEqual(a-b,d,delta=.03)
        for j in JOINTS[:9]:self.assertAlmostEqual(after[j],self.start[j],delta=.0051)

    def test_body_translation_holds_foot_targets_in_the_reference_frame(self):
        import numpy as np
        before=foot_positions(self.start)
        action={'name':'body','arguments':{'translation_mm':[1,1,-2],'rotation_deg':[0,1,0],
                                         'legs':[],'foot_offsets_mm':[],'seconds':.4}}
        frames=frames_for_spatial(action,self.start)
        self.assertEqual(sum(f[0] for f in frames),400)
        positions=dict(zip(JOINTS,[v/100 for v in frames[-1][1]]))
        model=mechanism();model.body_euler=np.deg2rad([0,1,0])
        for leg,cad in [('rear_left','FL'),('rear_right','FR'),('front_left','RL'),('front_right','RR')]:
            q=np.deg2rad([positions[f'{leg}_{axis}'] for axis in ('shoulder','carrier','crank')])
            after=model.reference(cad,q,np.array([1,1,-2]))
            self.assertLess(np.linalg.norm(after-before[leg]),.03)

    def test_compiled_path_matches_requested_line_between_packet_targets(self):
        import numpy as np
        before=foot_positions(self.start)
        action={'name':'feet','arguments':{'legs':['front_left'],'offsets_mm':[[9,-3,12]],'seconds':2}}
        frames=frames_for_spatial(action,self.start)
        elapsed=0;start=np.array([self.start[j] for j in JOINTS])
        for milliseconds,angles in frames:
            target=np.array(angles)/100
            # Independent dense fractional points, not compiler refinement probes.
            for u in np.linspace(.03,.97,13):
                pose=dict(zip(JOINTS,start+u*(target-start)))
                foot=np.array(foot_positions(pose)['front_left'])
                expected=np.array(before['front_left'])+np.array([9,-3,12])*(elapsed+u*milliseconds)/2000
                self.assertLess(np.linalg.norm(foot-expected),.04)
            elapsed+=milliseconds;start=target
        self.assertEqual(elapsed,2000)

    def test_long_duration_does_not_multiply_identical_geometric_work(self):
        from unittest.mock import patch
        from experiments.freestyle.kinematics import solve_reference
        action={'name':'body','arguments':{'translation_mm':[0,0,0],
                'rotation_deg':[.01,.02,.04],'legs':[],'foot_offsets_mm':[],'seconds':3274}}
        with patch('experiments.freestyle.kinematics.solve_reference',wraps=solve_reference) as solver:
            frames=frames_for_spatial(action,self.start)
        self.assertEqual(sum(f[0] for f in frames),3274000)
        self.assertLess(solver.call_count,100)


if __name__=='__main__':unittest.main()
