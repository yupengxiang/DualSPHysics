"""Synthetic regression tests for the F4 v3 proposal-only candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from scripts.f4_supportcap_affine_query_bound_candidate_v3 import (
    BACKEND,
    CANDIDATE_ID,
    ERROR_ESTIMATOR,
    FIXED_GATE,
    NEIGHBOURS,
    candidate_spec,
    sample_candidate,
    static_review_contract,
)


def _cloud() -> tuple[np.ndarray, np.ndarray]:
    axes = np.linspace(-0.04, 0.04, 5)
    position = np.array([(x, y, z) for x in axes for y in axes for z in axes], dtype=float)
    velocity = np.column_stack(
        (
            0.2 + 0.7 * position[:, 0] - 0.3 * position[:, 1],
            -0.1 + 0.4 * position[:, 1] + 0.2 * position[:, 2],
            0.3 - 0.2 * position[:, 0] + 0.5 * position[:, 2],
        )
    )
    return position, velocity


def test_candidate_is_new_composition_and_keeps_registered_gate() -> None:
    spec = candidate_spec()
    assert spec["candidate_id"] == CANDIDATE_ID
    assert spec["backend"] == BACKEND
    assert spec["mechanisms"][0]["neighbours"] == NEIGHBOURS
    assert spec["mechanisms"][1]["error_estimator"] == ERROR_ESTIMATOR
    assert spec["fixed_gate"] == FIXED_GATE
    assert spec["qualification_claim"] == "none"
    assert spec["credit"] == 0
    assert spec["authorized_one_cpu_only"] is False


def test_constant_field_is_a_finite_synthetic_smoke_case() -> None:
    position, _ = _cloud()
    velocity = np.broadcast_to(np.array([1.0, -2.0, 0.5]), position.shape).copy()
    query = np.array([[0.003, 0.004, -0.005], [0.013, -0.011, 0.017]])
    sampled, support, passed, diagnostics = sample_candidate(position, velocity, query)
    assert np.isfinite(sampled).all()
    assert np.isfinite(support).all()
    assert np.allclose(sampled, [1.0, -2.0, 0.5], atol=1e-12)
    assert passed.all()
    assert np.all(diagnostics["estimated_interpolation_error_mps"] >= 0.0)


def test_affine_synthetic_case_reports_query_bound_without_relaxing_gate() -> None:
    position, velocity = _cloud()
    query = np.array([[0.021, -0.017, 0.019], [-0.023, 0.014, -0.018]])
    sampled, _, _, diagnostics = sample_candidate(position, velocity, query)
    assert np.isfinite(sampled).all()
    assert np.isfinite(diagnostics["local_affine_query_bias_mps"]).all()
    assert np.all(
        diagnostics["estimated_interpolation_error_mps"]
        >= diagnostics["interpolation_reconstruction_error_mps"]
    )
    assert diagnostics["support_cap"] == NEIGHBOURS
    assert diagnostics["fixed_gate"] == FIXED_GATE


def test_static_review_is_fail_closed_and_has_no_execution_authority() -> None:
    review = static_review_contract()
    controls = review["execution_controls"]
    assert review["status"] == "proposal_only_root_review_required"
    assert review["qualification_claim"] == "none"
    assert review["credit"] == 0
    assert review["authorized_one_cpu_only"] is False
    assert controls["native_started"] is False
    assert controls["solver_started"] is False
    assert controls["gpu_started"] is False
    assert controls["queue_mutation"] == 0
    assert controls["old_ess32_rerun"] is False
    assert controls["old_affine_rerun"] is False


def test_root_review_receipt_closes_candidate_card_hash() -> None:
    lab_root = Path(__file__).resolve().parents[1]
    receipt_path = lab_root / (
        "campaigns/core-v1/material/candidates/"
        "f4-supportcap-affine-query-bound-v3/root-review-receipt-v1.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    reference = receipt["candidate_card"]
    card_path = lab_root / reference["path"]
    actual = hashlib.sha256(card_path.read_bytes()).hexdigest()
    assert actual == reference["sha256"]
