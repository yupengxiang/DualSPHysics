from __future__ import annotations

import numpy as np
import pytest

from scripts.core_material import CurrentField, GATE
from scripts.f3_material_neighbors import _visible_support
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import sample_candidate as sample_v3
from scripts.f4_supportcap_shepard_lowreg_candidate_v6 import (
    BACKEND,
    CANDIDATE_ID,
    PREDICTOR_REGULARIZATION_M,
    candidate_spec,
    sample_candidate,
)
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import (
    ERROR_ESTIMATOR,
    FIXED_GATE,
    NEIGHBOURS,
)


def _cloud() -> tuple[np.ndarray, np.ndarray]:
    axis = np.linspace(-0.05, 0.05, 11)
    xx, yy, zz = np.meshgrid(axis, axis, axis, indexing="ij")
    position = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
    velocity = np.column_stack((position[:, 0] ** 2, position[:, 1] ** 2, position[:, 2] ** 2))
    return position, velocity


def test_candidate_keeps_v3_gate_policy_and_zero_credit() -> None:
    spec = candidate_spec()
    assert spec["candidate_id"] == CANDIDATE_ID
    assert spec["backend"] == BACKEND
    assert spec["predictor_regularization_m"] == PREDICTOR_REGULARIZATION_M
    assert spec["support_and_gate"]["metric_weights_regularization_m"] == PREDICTOR_REGULARIZATION_M
    assert spec["support_and_gate"]["fixed_gate"] == GATE
    assert spec["support_and_gate"]["decisions_reused_exactly"] is False
    assert spec["support_and_gate"]["decisions_recomputed_from_candidate_prediction"] is True
    assert spec["threshold_policy"] == "unchanged_registered_f4_gate"
    assert spec["production_tracer_registered"] is False
    assert spec["native_started"] is False
    assert spec["solver_started"] is False
    assert spec["worker_or_queue_started"] is False
    assert spec["qualification_claim"] == "none"
    assert spec["credit"] == 0
    assert spec["T1_numerical"] is False


def test_low_regularization_predictor_recomputes_gate_on_same_support_indices() -> None:
    position, velocity = _cloud()
    query = np.array([[0.003, -0.004, 0.002], [0.012, 0.006, -0.009]])
    walls = np.empty((0, 3, 3), dtype=np.float64)
    _, support3, _, _ = sample_v3(position, velocity, query, walls)
    predicted, support6, pass6, diagnostics = sample_candidate(position, velocity, query, walls)

    np.testing.assert_array_equal(support6, support3)
    field = CurrentField(position, velocity)
    selected, distance2, visible, search_width, exhaustive = _visible_support(
        field.tree, query, field.position, walls, min(NEIGHBOURS, field.valid_count)
    )
    np.testing.assert_array_equal(diagnostics["selected_support_indices"], selected)
    np.testing.assert_array_equal(diagnostics["selected_visible_neighbours"], np.isfinite(distance2).sum(axis=1))
    np.testing.assert_array_equal(diagnostics["visible_neighbours"], visible)
    np.testing.assert_array_equal(diagnostics["visibility_search_width"], search_width)
    np.testing.assert_array_equal(diagnostics["visibility_search_exhaustive"], exhaustive)
    reference, reference_support, reference_pass, reference_diag = field.sample(
        query,
        walls,
        neighbours=NEIGHBOURS,
        regularization=PREDICTOR_REGULARIZATION_M,
        gate=FIXED_GATE,
        error_estimator=ERROR_ESTIMATOR,
        return_diagnostics=True,
    )
    np.testing.assert_allclose(predicted, reference, rtol=0, atol=0)
    np.testing.assert_array_equal(support6, reference_support)
    np.testing.assert_array_equal(pass6, reference_pass)
    np.testing.assert_allclose(
        diagnostics["estimated_interpolation_error_mps"],
        reference_diag["estimated_interpolation_error_mps"],
        rtol=0,
        atol=0,
    )
    assert np.isfinite(predicted).all()
    assert diagnostics["predictor_regularization_m"] == PREDICTOR_REGULARIZATION_M


def test_constant_field_and_empty_query_are_stable() -> None:
    position, _ = _cloud()
    velocity = np.tile([0.2, -0.1, 0.3], (len(position), 1))
    query = np.array([[0.001, 0.002, -0.003]])
    predicted, support, passed, _ = sample_candidate(position, velocity, query)
    np.testing.assert_allclose(predicted, velocity[:1], rtol=0, atol=2e-15)

    empty, empty_support, empty_pass, diagnostics = sample_candidate(
        position, velocity, np.empty((0, 3))
    )
    assert empty.shape == (0, 3)
    assert empty_support.shape == empty_pass.shape == (0,)
    assert diagnostics["selected_visible_neighbours"].shape == (0,)


def test_nonfinite_input_fails_closed() -> None:
    with pytest.raises(ValueError, match="nonfinite"):
        sample_candidate(np.array([[np.nan, 0, 0]]), np.zeros((1, 3)), np.zeros((1, 3)))
