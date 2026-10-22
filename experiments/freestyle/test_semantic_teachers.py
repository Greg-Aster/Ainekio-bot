import json
import math
import unittest

from .challenge import assess, replay, trajectory_metrics
from .kinematics import ROOT
from .runtime import JOINTS
from .semantic_teachers import demonstration


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


if __name__=='__main__':unittest.main()
