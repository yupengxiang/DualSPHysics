from __future__ import annotations

import numpy as np
import pytest

from scripts import f4_supportcap_affine_shepard_blend_heldout_v1 as heldout


def test_design_freezes_unscored_cases_field_and_existing_gates() -> None:
    record = heldout.design()
    assert record["schema"] == heldout.SCHEMA
    assert record["revision_id"] == heldout.REVISION
    assert record["geometry"]["q_cases"] == [0.75, 0.95]
    assert record["held_out_field"]["id"] == heldout.FIELD_ID
    assert record["holdout_status"] == "prospective_unscored_stress_set_not_external_independent_validation"
    assert record["candidates"]["candidate_parameters_fitted_for_this_set"] is False
    assert record["candidates"]["thresholds_or_candidate_parameters_may_change_after_scoring"] is False
    assert record["acceptance"]["gate_decisions_must_match_v3_exactly"] is True
    assert record["acceptance"]["candidate_truth_error_limit_mps"] == heldout.MAXIMUM_TRUTH_ERROR_MPS
    assert record["geometry"]["expected_query_count"] == heldout.EXPECTED_QUERY_COUNT
    assert record["qualification_claim"] == "none"


def test_channel_mode_has_declared_periodicity_no_slip_and_divergence() -> None:
    x = np.linspace(0.03, 1.17, 7)
    z = np.linspace(0.07, 0.53, 7)
    points = np.column_stack((x, np.zeros_like(x), z))
    values = heldout._channel_mode_velocity(points)
    periodic = heldout._channel_mode_velocity(points + np.array([heldout.X_PERIOD_M, 0.0, 0.0]))
    np.testing.assert_allclose(values, periodic, rtol=0, atol=2e-16)

    walls = np.array([[0.1, 0.0, 0.0], [0.1, 0.0, heldout.CHANNEL_HEIGHT_M]])
    wall_values = heldout._channel_mode_velocity(walls)
    np.testing.assert_allclose(wall_values, 0.0, rtol=0, atol=1e-15)

    epsilon = 1e-6
    divergence = np.empty(len(points))
    for index, point in enumerate(points):
        dx = np.array([epsilon, 0.0, 0.0])
        dz = np.array([0.0, 0.0, epsilon])
        du_dx = (heldout._channel_mode_velocity((point + dx)[None, :])[0, 0]
                 - heldout._channel_mode_velocity((point - dx)[None, :])[0, 0]) / (2 * epsilon)
        dw_dz = (heldout._channel_mode_velocity((point + dz)[None, :])[0, 2]
                 - heldout._channel_mode_velocity((point - dz)[None, :])[0, 2]) / (2 * epsilon)
        divergence[index] = du_dx + dw_dz
    np.testing.assert_allclose(divergence, 0.0, rtol=0, atol=2e-10)


def test_load_gate_defers_before_evaluation(monkeypatch) -> None:
    monkeypatch.setattr(heldout, "_load_snapshot", lambda: (129.0, 128))
    monkeypatch.setattr(heldout, "_support_cloud", lambda q: pytest.fail("cloud built before load gate"))
    with pytest.raises(heldout.ProfileDeferred, match="exceeds process-visible CPU capacity"):
        heldout.run(heldout.design())


def test_invalid_load_gate_inputs_fail_closed() -> None:
    with pytest.raises(ValueError, match="finite and nonnegative"):
        heldout.check_load_gate(float("nan"), 8)
    with pytest.raises(ValueError, match="positive integer"):
        heldout.check_load_gate(0.0, True)
