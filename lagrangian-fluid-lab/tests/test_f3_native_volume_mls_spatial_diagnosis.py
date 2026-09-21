"""Focused tests for spatial CDF exceedance attribution."""

import numpy as np

from scripts.f3_native_volume_mls_spatial_diagnosis import _difference_windows, _seed_contributions


def _trace(left_event_count: int, right_event_count: int) -> dict:
    labels = np.r_[np.zeros(256, dtype=np.int8), np.ones(256, dtype=np.int8)]
    left = np.full(512, np.nan, dtype=np.float64)
    right = np.full(512, np.nan, dtype=np.float64)
    left[:left_event_count] = 0.1
    right[:right_event_count] = 0.1
    return {
        "time": np.asarray([0.0, 0.1, 0.2]),
        "source_label": labels,
        "first_passage": left if left_event_count >= 0 else right,
        "permanent_unknown": np.zeros((3, 512), dtype=bool),
    }


def test_cdf_exceedance_keeps_seed_direction_and_fixed_source_denominator():
    left = _trace(0, 0)
    right = _trace(6, 0)
    # The helper deliberately uses each trace's first_passage field.
    right["first_passage"] = np.full(512, np.nan, dtype=np.float64)
    right["first_passage"][:6] = 0.1
    windows = _difference_windows(left, right, 0)
    assert windows
    assert max(row["peak"]["sup_abs_difference_bound"] for row in windows) == 6 / 256
    peak = max(windows, key=lambda row: row["peak"]["sup_abs_difference_bound"])
    contribution = _seed_contributions(left, right, 0, peak["peak_time_s"])
    assert contribution["right_earlier_count"] == 6
    assert contribution["left_earlier_count"] == 0
    assert contribution["right_unresolved_eligible_at_peak_count"] == 0
