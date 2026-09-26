from __future__ import annotations

import numpy as np
import pytest

from scripts import f4_supportcap_affine_shepard_blend_heldout_v1 as heldout_v1
from scripts import f4_supportcap_affine_shepard_blend_heldout_v2 as heldout_v2


def test_design_is_prospective_not_external_and_binds_complete_candidate_closure() -> None:
    record = heldout_v2.design()
    paths = {binding["path"] for binding in record["code_bindings"].values()}
    assert record["schema"] == heldout_v2.SCHEMA
    assert record["geometry"]["q_cases"] == [0.05, 0.975]
    assert record["geometry"]["q_domain_audit"]["disjoint_from_pinned_prior_records"] is True
    assert record["geometry"]["q_domain_audit"]["prior_q_cases_by_source"]["superseded_unscored_heldout_design_v1"] == [0.75, 0.95]
    assert record["holdout_status"].endswith("not_external_independent_validation")
    assert record["candidates"]["predictor_superiority_claim"] is False
    assert record["acceptance"]["rmse"].endswith("no non-regression requirement")
    assert record["acceptance"]["maximum_source_unknown_fraction"] == 0.01
    assert record["acceptance"]["truth_error_limit_semantics"].startswith("hard pass condition for this synthetic screen only")
    assert "scripts/f4_supportcap_affine_reconstruction_candidate_v4.py" in paths
    assert "scripts/f3_material_neighbors.py" in paths
    assert "scripts/passive_tracers.py" in paths
    assert "tests/test_f4_supportcap_affine_shepard_blend_heldout_v2.py" in paths
    assert "requirements.txt" in paths
    assert "scripts/f4_material_calibration.py" in paths
    assert "scripts/f4_material_calibration_v2.py" in paths
    assert "scripts/f4_material_calibration_v3.py" in paths
    audit_paths = {binding["path"] for binding in record["audit_source_bindings"].values()}
    assert "campaigns/core-v1/material/candidates/f4-supportcap-affine-shepard-blend-v5/synthetic-calibration-v1/heldout-design-v1.json" in audit_paths
    assert record["held_out_field"]["physical_scope"].endswith("not a DualSPHysics solution")
    assert record["qualification_claim"] == "none"


def test_box_mode_is_divergence_free_and_zero_on_all_box_faces() -> None:
    interior = np.array([[0.31, 0.13, 0.22], [0.73, 0.27, 0.41], [0.91, 0.08, 0.52]])
    epsilon = 1e-6
    divergence = []
    for point in interior:
        dx = np.array([epsilon, 0.0, 0.0])
        dz = np.array([0.0, 0.0, epsilon])
        du_dx = (heldout_v2._box_mode_velocity((point + dx)[None, :])[0, 0]
                 - heldout_v2._box_mode_velocity((point - dx)[None, :])[0, 0]) / (2 * epsilon)
        dw_dz = (heldout_v2._box_mode_velocity((point + dz)[None, :])[0, 2]
                 - heldout_v2._box_mode_velocity((point - dz)[None, :])[0, 2]) / (2 * epsilon)
        divergence.append(du_dx + dw_dz)
    np.testing.assert_allclose(divergence, 0.0, rtol=0, atol=2e-10)

    x = np.linspace(0.0, heldout_v2.X_LENGTH_M, 5)
    y = np.linspace(0.0, heldout_v2.Y_LENGTH_M, 5)
    z = np.linspace(0.0, heldout_v2.Z_HEIGHT_M, 5)
    for points in (
        np.column_stack((np.zeros_like(y), y, np.full_like(y, 0.21))),
        np.column_stack((np.full_like(y, heldout_v2.X_LENGTH_M), y, np.full_like(y, 0.21))),
        np.column_stack((x, np.zeros_like(x), np.full_like(x, 0.21))),
        np.column_stack((x, np.full_like(x, heldout_v2.Y_LENGTH_M), np.full_like(x, 0.21))),
        np.column_stack((x, np.full_like(x, 0.19), np.zeros_like(x))),
        np.column_stack((x, np.full_like(x, 0.19), np.full_like(x, heldout_v2.Z_HEIGHT_M))),
    ):
        np.testing.assert_allclose(heldout_v2._box_mode_velocity(points), 0.0, rtol=0, atol=2e-15)


def test_nonfinite_truth_error_is_reported_as_failed_without_dropping_denominator() -> None:
    summary = heldout_v2._error_record(np.array([[np.nan, 0.0, 0.0]]), np.zeros((1, 3)))
    assert summary["query_count"] == 1
    assert summary["finite_prediction_count"] == 0
    assert summary["truth_vector_rmse_mps"] is None
    assert summary["truth_vector_max_error_mps"] is None
    assert summary["within_fixed_truth_error_limit"] is False


def test_load_gate_defers_before_support_cloud_construction(monkeypatch) -> None:
    monkeypatch.setattr(heldout_v2.heldout_v1_helpers, "_load_snapshot", lambda: (129.0, 128))
    monkeypatch.setattr(heldout_v2.heldout_v1_helpers, "_support_cloud", lambda q: pytest.fail("cloud built before load gate"))
    with pytest.raises(heldout_v1.ProfileDeferred, match="exceeds process-visible CPU capacity"):
        heldout_v2.run(heldout_v2.design())


def test_design_verification_rejects_modified_dependency_hash() -> None:
    record = heldout_v2.design()
    record["code_bindings"]["support_gate"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="complete code closure"):
        heldout_v2.verify_design(record)
