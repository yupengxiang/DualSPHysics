import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ds_data02_f7_passage_quantiles_v1 import quantile_bounds


def test_censored_majority_is_not_dropped_from_quantile_denominator():
    r = quantile_bounds([[1, 2], [np.nan, np.nan]], [2, 8], [True, False], [False, False], 12, [.1, .5])
    assert r[0]['lower_s'] == 1 and r[0]['upper_s'] == 2
    assert r[1]['lower_s'] == 12 and r[1]['upper_s'] is None


def test_unknown_history_broadens_bounds_without_inventing_an_event():
    r = quantile_bounds([[1, 2], [np.nan, np.nan]], [8, 2], [True, False], [False, True], 12, [.1])
    assert r[0]['lower_s'] == 0 and r[0]['upper_s'] == 2


def test_weighted_interval_rank_is_invariant_to_input_order():
    r = quantile_bounds([[5, 6], [1, 2], [9, 10]], [6, 2, 2], [True] * 3, [False] * 3, 12, [.5])
    assert r[0]['lower_s'] == 5 and r[0]['upper_s'] == 6
