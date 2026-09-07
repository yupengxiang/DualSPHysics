from __future__ import annotations

import numpy as np
import pytest

from scripts.r3_g2_tracer_convergence import (
    _frame_indices,
    _trajectory_summary,
    compare_traces,
)


def _trace(offset: float = 0.0):
    time = np.asarray([0.0, 0.5, 1.0])
    position = np.zeros((3, 2, 3), dtype=float)
    position[:, :, 0] = np.asarray([[0.0, 1.0], [0.2, 1.2], [0.4, 1.4]]) + offset
    return {
        "time": time,
        "position": position,
        "reliable": np.asarray([True, True]),
        "reliability_history": np.ones((3, 2), dtype=bool),
        "nearest_support_distance": np.full((2, 2), 0.02),
        "minimum_visible_neighbours": np.full((2, 2), 8),
        "wall_crossing": np.zeros((2, 2), dtype=bool),
    }


def test_frame_indices_always_include_final_frame():
    np.testing.assert_array_equal(_frame_indices(11, 5), [0, 5, 10])
    np.testing.assert_array_equal(_frame_indices(10, 5), [0, 5, 9])


def test_compare_traces_reports_common_time_delta():
    result = compare_traces(_trace(), _trace(offset=0.1), 0.05)
    assert result["common_time_samples"] == 3
    assert result["trajectory_delta_rmse_over_dp"] == pytest.approx(2.0)
    assert result["endpoint_delta_rmse_over_dp"] == pytest.approx(2.0)


def test_trajectory_summary_uses_vector_rmse_and_mass_weights():
    trace = _trace()
    reference = _trace()["position"]
    # A displacement of 0.1 m for one of two particles, with the first
    # particle carrying three quarters of the represented mass.
    trace["position"] = trace["position"].copy()
    trace["position"][:, 0, 1] = 0.1
    trace["reliability_history"] = np.ones((3, 2), dtype=bool)
    trace["reliable"] = np.ones(2, dtype=bool)
    seeds = {"indices": np.asarray([0, 1]), "mass_weight": np.asarray([3.0, 1.0]),
             "initial_fluid_mass": 4.0}
    summary = _trajectory_summary(trace, reference, np.ones((3, 2), dtype=bool), seeds, 0.1, 0.0)
    assert summary["mass_weight_closure_error_kg"] == 0.0
    assert summary["mass_weight_closure_relative_error"] == 0.0
    assert summary["reliable_final_fraction_by_initial_mass"] == 1.0
    assert summary["solver_valid_fraction_by_initial_mass"] == 1.0
    # 0.1 m error / 0.1 m dp, weighted over three time frames and two seeds.
    assert summary["position_rmse_over_dp"] == pytest.approx(np.sqrt(3.0 / 4.0))
    assert summary["position_ade_over_dp"] == pytest.approx(3.0 / 4.0)
