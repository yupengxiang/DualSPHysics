"""Targeted static/synthetic checks for the integrated F4 v3 revision."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

from scripts.core_material import (
    ERROR_ESTIMATORS,
    F4_V3_BACKEND,
    F4_V3_ERROR_ESTIMATOR,
    F4_V3_NEIGHBOURS,
    NEIGHBOUR_VARIANTS,
    trace_f4_resting_pool,
)
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import candidate_spec


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3"
CARD = ROOT / "candidate-card-v2.json"
REVIEW = ROOT / "terra-high-root-review-v3.json"
CALIBRATION = LAB / "campaigns/core-v1/material/evidence/f4-reconstruction-calibration-v3-20260922-result.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v3_is_registered_as_a_new_variant_without_changing_old_bindings() -> None:
    assert NEIGHBOUR_VARIANTS["f4_supportcap_affine_query_bound_v3"] == (F4_V3_BACKEND, F4_V3_NEIGHBOURS)
    assert ERROR_ESTIMATORS["f4_supportcap_affine_query_bound_v3"] == F4_V3_ERROR_ESTIMATOR
    assert NEIGHBOUR_VARIANTS["f4_ess32_v2"] == ("f4_ckdtree_visible_shepard_ess32_v2", 32)
    assert NEIGHBOUR_VARIANTS["f4_affine_bound_v2"] == ("f4_ckdtree_visible_shepard_affine_bound_v2", 24)
    assert ERROR_ESTIMATORS["f4_ess32_v2"] == "local_residual"
    assert ERROR_ESTIMATORS["f4_affine_bound_v2"] == "residual_plus_local_affine_query_bias"
    assert candidate_spec()["fixed_gate"]["maximum_reconstruction_error_mps"] == 0.05 * np.sqrt(9.81 * 0.09)


def test_v3_trace_adapter_binds_only_the_new_namespace(tmp_path: Path) -> None:
    source = tmp_path / "reference.h5"
    points = np.array([[0.4, 0.2, z] for z in np.linspace(0.2, 0.6, 40)], dtype=float)
    with h5py.File(source, "w") as handle:
        handle["time"] = [0.0, 0.1]
        handle["position"] = np.tile(points, (2, 1, 1))
        handle["velocity"] = np.tile([0.0, 0.0, -0.2], (2, len(points), 1))
        handle["valid"] = np.ones((2, len(points)), dtype=bool)
        handle["type"] = np.full(len(points), 3, dtype=np.int32)
    result = trace_f4_resting_pool(
        source, tmp_path / "v3.h5", np.array([[0.4, 0.2, 0.5]]),
        q=0.5, dp_m=0.0075, walls=np.empty((0, 3, 3)), stop_after=1,
        neighbour_variant="f4_supportcap_affine_query_bound_v3",
    )
    assert result["binding"]["backend"] == F4_V3_BACKEND
    assert result["binding"]["neighbours"] == F4_V3_NEIGHBOURS
    assert result["binding"]["error_estimator"] == F4_V3_ERROR_ESTIMATOR
    assert result["qualified_T2_macro"] is False
    assert result["qualified_T2_path"] is False


def test_v3_card_and_static_review_are_hash_closed() -> None:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    assert card["status"] == "proposal_only_root_review_required"
    assert card["qualification_claim"] == "none"
    assert card["credit"] == 0
    for binding in card["input_bindings"].values():
        path = LAB / binding["path"]
        assert path.is_file(), binding["path"]
        assert _sha(path) == binding["sha256"], binding["path"]

    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert review["reviewer"]["model"] == "gpt-5.6-terra"
    assert review["reviewer"]["reasoning_effort"] == "high"
    assert review["review_method"]["runtime_execution"] is False
    assert review["authorized_one_cpu_only"] is False
    assert review["qualification_claim"] == "none"
    assert review["credit"] == 0
    assert review["T2_macro"] is False
    assert review["T2_path"] is False
    for binding in review["hash_bindings"].values():
        path = LAB / binding["path"]
        assert path.is_file(), binding["path"]
        assert _sha(path) == binding["sha256"], binding["path"]


def test_v3_held_out_calibration_is_exact_composition_and_zero_credit() -> None:
    result = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    assert result["composition"]["neighbours"] == 32
    assert result["composition"]["error_estimator"] == F4_V3_ERROR_ESTIMATOR
    assert result["held_out"]["q_cases"] == [0.375, 0.875]
    assert result["held_out"]["fields"] == ["quintic_shear", "gaussian_interface"]
    assert result["source_macro_budget_pass"] is True
    assert result["all_mass_closure_pass"] is True
    assert result["qualification_claim"] == "none"
    assert result["credit"] == 0
    assert result["T2_macro"] is False
    assert result["T2_path"] is False
    assert all(row["backend"] == F4_V3_BACKEND for row in result["rows"])
    assert all(row["neighbours"] == F4_V3_NEIGHBOURS for row in result["rows"])

