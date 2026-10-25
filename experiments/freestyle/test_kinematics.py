import json
import math
import unittest

from experiments.freestyle.kinematics import ROOT, foot_positions, target_for_spatial, mechanism
from experiments.freestyle.runtime import JOINTS


class SpatialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=json.loads((ROOT/'motions/gestures/wave/source.json').read_text())
        cls.start=dict(zip(JOINTS,[math.degrees(q) for leg in source['samples'][0]['actuator_angles_rad'] for q in leg]))

    def test_new_foot_translation_reaches_target_and_keeps_other_joints(self):
        before=foot_positions(self.start)
        action={'name':'feet','arguments':{'legs':['front_right'],'offsets_mm':[[3,2,5]],'speed_pct':50}}
        target_angles=target_for_spatial(action,self.start)
        after=dict(zip(JOINTS,[v/100 for v in target_angles]))
        target=foot_positions(after)['front_right']
        for a,b,d in zip(target,before['front_right'],[3,2,5]):self.assertAlmostEqual(a-b,d,delta=.03)
        for j in JOINTS[:9]:self.assertAlmostEqual(after[j],self.start[j],delta=.0051)

    def test_body_translation_holds_foot_targets_in_the_reference_frame(self):
        import numpy as np
        before=foot_positions(self.start)
        action={'name':'body','arguments':{'translation_mm':[1,1,-2],'rotation_deg':[0,1,0],
                                         'legs':[],'foot_offsets_mm':[],'speed_pct':40}}
        target_angles=target_for_spatial(action,self.start)
        positions=dict(zip(JOINTS,[v/100 for v in target_angles]))
        model=mechanism();model.body_euler=np.deg2rad([0,1,0])
        for leg,cad in [('rear_left','FL'),('rear_right','FR'),('front_left','RL'),('front_right','RR')]:
            q=np.deg2rad([positions[f'{leg}_{axis}'] for axis in ('shoulder','carrier','crank')])
            after=model.reference(cad,q,np.array([1,1,-2]))
            self.assertLess(np.linalg.norm(after-before[leg]),.03)

    def test_speed_does_not_change_spatial_target_or_create_timed_frames(self):
        targets=[]
        for speed in (1,50,100,200):
            action={'name':'feet','arguments':{'legs':['front_right'],
                    'offsets_mm':[[0,0,35]],'speed_pct':speed}}
            targets.append(target_for_spatial(action,self.start))
        self.assertTrue(all(t==targets[0] for t in targets))
        self.assertEqual(len(targets[0]),12)


if __name__=='__main__':unittest.main()
