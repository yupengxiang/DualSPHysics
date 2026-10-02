from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f6_heave_geometry_diagnostic_v1 import compare


class FrozenScale(unittest.TestCase):
    def test_original_scale_used_even_when_candidate_is_larger(self):
        time = np.array([0., 12.])
        result = compare((time, np.array([1., 1.])),
                         (time, np.array([2., 2.])), 1.)
        self.assertEqual(result['rmse_relative_to_frozen_dp025_peak'], 1.)

    def test_partial_window_cannot_be_extrapolated(self):
        with self.assertRaisesRegex(ValueError, 'Extrapolation'):
            compare((np.array([0., 11.]), np.array([1., 1.])),
                    (np.array([0., 12.]), np.array([1., 1.])), 1.)

    def test_zero_scale_cannot_make_a_spurious_pass(self):
        with self.assertRaisesRegex(ValueError, 'Positive frozen'):
            compare((np.array([0., 12.]), np.zeros(2)),
                    (np.array([0., 12.]), np.zeros(2)), 0.)


if __name__ == '__main__':
    unittest.main()
