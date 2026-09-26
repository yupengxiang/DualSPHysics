from __future__ import annotations

import numpy as np
import pytest

from scripts.core_material import F4_V3_ERROR_ESTIMATOR, GATE, REGULARIZATION_M
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import sample_candidate as sample_v3
from scripts.f4_supportcap_affine_reconstruction_candidate_v4 import sample_candidate as sample_v4
from scripts.f4_supportcap_affine_shepard_blend_candidate_v5 import (
    BACKEND,
    CANDIDATE_ID,
    candidate_spec,
    sample_candidate,
)


def test_proposal_contract_keeps_support_gate_and_zero_credit() -> None:
    spec = candidate_spec()
    assert spec["candidate_id"] == CANDIDATE_ID
    assert spec["backend"] == BACKEND
    assert spec["support_and_weights"].startswith("identical F4 v3/v4")
    assert spec["fixed_gate"] == GATE
    assert spec["threshold_policy"] == "unchanged_registered_f4_gate"
    assert spec["production_tracer_registered"] is False
    assert spec["native_started"] is False
    assert spec["worker_or_queue_started"] is False
    assert spec["qualification_claim"] == "none"
    assert spec["credit"] == 0


def test_blend_formula_and_gate_are_recomputed_from_v3_and_v4() -> None:
    axis = np.linspace(-0.05, 0.05, 11)
    xx, yy, zz = np.meshgrid(axis, axis, axis, indexing="ij")
    position = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
    velocity = np.column_stack((position[:, 0] ** 2, position[:, 1] ** 2, position[:, 2] ** 2))
    query = np.array([[0.003, -0.004, 0.002], [0.012, 0.006, -0.009]])
    walls = np.empty((0, 3, 3), dtype=np.float64)

    shepard, support3, pass3, diag3 = sample_v3(position, velocity, query, walls)
    affine, support4, pass4, diag4 = sample_v4(position, velocity, query, walls)
    blended, support5, pass5, diag5 = sample_candidate(position, velocity, query, walls)

    maximum = float(GATE["maximum_reconstruction_error_mps"])
    alpha = np.clip(1.0 - diag4["local_affine_query_bias_mps"] / maximum, 0.0, 1.0)
    np.testing.assert_array_equal(support5, support3)
    np.testing.assert_array_equal(support5, support4)
    np.testing.assert_array_equal(pass5, pass3)
    np.testing.assert_array_equal(pass5, pass4)
    np.testing.assert_allclose(blended, shepard + alpha[:, None] * (affine - shepard), rtol=1e-13, atol=1e-14)
    np.testing.assert_array_equal(diag5["blend_alpha"], alpha)
    np.testing.assert_allclose(diag5["estimated_interpolation_error_mps"], diag4["estimated_interpolation_error_mps"], rtol=1e-12, atol=1e-14)
    assert diag3["error_estimator"] == F4_V3_ERROR_ESTIMATOR


def test_no_disagreement_returns_affine_and_empty_queries_keep_shapes() -> None:
    axis = np.linspace(-0.03, 0.03, 9)
    xx, yy, zz = np.meshgrid(axis, axis, axis, indexing="ij")
    position = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
    velocity = np.tile([0.2, -0.1, 0.3], (len(position), 1))
    query = np.array([[0.001, 0.002, -0.003]])
    predicted, _, _, diagnostics = sample_candidate(position, velocity, query)
    np.testing.assert_allclose(predicted, np.tile([0.2, -0.1, 0.3], (1, 1)), rtol=0, atol=1e-14)
    np.testing.assert_allclose(diagnostics["blend_alpha"], [1.0], rtol=0, atol=2e-15)

    empty, support, passed, empty_diag = sample_candidate(position, velocity, np.empty((0, 3)))
    assert empty.shape == (0, 3)
    assert support.shape == passed.shape == (0,)
    assert empty_diag["blend_alpha"].shape == (0,)


@pytest.mark.parametrize(
    "position,velocity,query",
    [(np.array([[np.nan, 0, 0]]), np.zeros((1, 3)), np.zeros((1, 3)))],
)
def test_nonfinite_inputs_fail_closed(position, velocity, query) -> None:
    with pytest.raises(ValueError, match="nonfinite"):
        sample_candidate(position, velocity, query)
