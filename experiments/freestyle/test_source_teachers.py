import unittest
import numpy as np

from .source_teachers import simplify
from .source_review import densify, ordered_distance


class SourceTeacherTests(unittest.TestCase):
    def test_repeated_collinear_motion_is_not_deleted_by_zero_chord_error(self):
        points=np.array([[0.],[10.],[0.],[10.],[0.],[10.]])
        self.assertEqual(simplify(points,{0,5},.25),list(range(6)))

    def test_phase_boundary_survives_even_on_a_straight_path(self):
        points=np.array([[0.],[1.],[2.],[3.],[4.]])
        self.assertEqual(simplify(points,{0,2,4},.25),[0,2,4])

    def test_closed_excursion_keeps_its_peak_and_return(self):
        points=np.array([[0.,0.],[1.,2.],[2.,4.],[1.,2.],[0.,0.]])
        self.assertEqual(simplify(points,{0,4},.25),[0,2,4])

    def test_ordered_distance_detects_removed_repetition(self):
        self.assertEqual(ordered_distance([[0.],[10.],[0.],[10.]], [[0.],[10.]]), 10.)

    def test_ordered_distance_allows_repeated_samples_and_retains_error(self):
        self.assertEqual(ordered_distance([[0.],[0.],[2.],[4.]], [[0.],[2.],[2.],[4.]]), 0.)
        self.assertEqual(ordered_distance([[0.],[2.],[4.]], [[1.],[3.],[5.]]), 1.)

    def test_densification_keeps_reversal_and_handles_unequal_sample_rates(self):
        sparse = densify([[0.],[4.],[0.]], .25)
        self.assertEqual(sparse[16,0], 4.)
        self.assertEqual(sparse[-1,0], 0.)
        self.assertEqual(ordered_distance(sparse, densify([[0.],[1.],[2.],[3.],[4.],[2.],[0.]], .25)), 0.)


if __name__=='__main__':unittest.main()
