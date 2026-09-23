"""Synthetic checks for a one-wall hard-constrained MLS design candidate."""

import numpy as np

from scripts.f3_no_slip_constrained_mls_study_v1 import study


def test_wall_constraint_preserves_affine_no_slip_field():
    result = study()["affine_no_slip"]
    assert result["raw_reliable"] is True
    np.testing.assert_allclose(
        result["raw_velocity"], result["exact_velocity"], atol=1e-11, rtol=0.0
    )
    np.testing.assert_allclose(
        result["constrained_velocity"], result["exact_velocity"], atol=1e-11, rtol=0.0
    )
    np.testing.assert_allclose(
        result["constrained_wall_velocity"], np.zeros(3), atol=1e-11, rtol=0.0
    )


def test_wall_constraint_improves_quadratic_extrapolation_over_tested_supports():
    result = study()
    for row in result["quadratic_no_slip_h_sweep"]:
        assert row["raw_reliable"] is True
        assert row["support_count"] >= 4
        assert row["geometry_rank"] == 4
        assert row["constrained_x_absolute_error"] < row["raw_x_absolute_error"]
        assert row["raw_wall_x_velocity"] > 0.0
        assert abs(row["constrained_wall_x_velocity"]) < 1e-11
        assert row["constrained_weighted_rms_residual"] > row["raw_weighted_rms_residual"]


def test_hard_constraint_materially_changes_wall_incompatible_samples():
    result = study()["incompatible_constant_outward_samples"]
    assert result["raw_reliable"] is True
    assert abs(result["raw_velocity"][0] - 1.0) < 1e-12
    assert abs(result["constrained_wall_velocity"][0]) < 1e-11
    assert abs(result["x_velocity_change"]) > 0.8
