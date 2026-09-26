"""Synthetic-array-only adaptive blend of the existing F4 v3/v4 predictors.

The predictor moves from Shepard toward the weighted local affine estimate in
proportion to their agreement. It introduces no new acceptance threshold and
is not registered in the production tracer or any execution path.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from scripts.f4_supportcap_affine_query_bound_candidate_v3 import sample_candidate as sample_v3
from scripts.f4_supportcap_affine_reconstruction_candidate_v4 import (
    FIXED_GATE,
    sample_candidate as sample_v4,
)


CANDIDATE_ID = "f4_supportcap_affine_shepard_blend_v5"
BACKEND = "f4_v3_shepard_v4_weighted_affine_disagreement_blend_v5"
PREDICTOR = "shepard_plus_clipped_affine_correction_scaled_by_one_minus_normalized_disagreement"


def candidate_spec() -> dict[str, Any]:
    """Return the proposal-only, fixed-gate algorithm contract."""
    return {
        "candidate_id": CANDIDATE_ID,
        "backend": BACKEND,
        "predictor": PREDICTOR,
        "blend": {
            "delta": "norm(weighted_local_affine_prediction - F4_v3_Shepard_prediction)",
            "alpha": "clip(1 - delta / existing_maximum_reconstruction_error, 0, 1)",
            "prediction": "Shepard + alpha * (weighted_local_affine - Shepard)",
            "fitted_parameters": [],
        },
        "support_and_weights": "identical F4 v3/v4 fixed k=32 visible support, Shepard geometry weights and regularization",
        "error_estimator": "unchanged F4 v4 weighted residual + affine-versus-Shepard delta",
        "fixed_gate": dict(FIXED_GATE),
        "threshold_policy": "unchanged_registered_f4_gate",
        "denominator_policy": "all source seeds remain in denominator; no silent filtering",
        "status": "proposal_only_synthetic_screen_only",
        "production_tracer_registered": False,
        "native_started": False,
        "tracer_started": False,
        "solver_started": False,
        "gpu_started": False,
        "worker_or_queue_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "qualification_claim": "none",
        "credit": 0,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
    }


def sample_candidate(
    position: np.ndarray,
    velocity: np.ndarray,
    query: np.ndarray,
    walls: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Blend the v3 Shepard and v4 affine values while preserving their gate."""
    shepard, support_v3, pass_v3, diag_v3 = sample_v3(position, velocity, query, walls)
    affine, support_v4, pass_v4, diag_v4 = sample_v4(position, velocity, query, walls)
    if not np.array_equal(support_v3, support_v4) or not np.array_equal(pass_v3, pass_v4):
        raise RuntimeError("F4 v3/v4 support or gate semantics diverged")
    if not np.allclose(
        diag_v3["estimated_interpolation_error_mps"],
        diag_v4["estimated_interpolation_error_mps"],
        rtol=1e-12,
        atol=1e-14,
        equal_nan=True,
    ):
        raise RuntimeError("F4 v3/v4 fixed error-estimator semantics diverged")

    delta = np.asarray(diag_v4["local_affine_query_bias_mps"], dtype=np.float64)
    maximum = float(FIXED_GATE["maximum_reconstruction_error_mps"])
    alpha = np.clip(1.0 - delta / maximum, 0.0, 1.0)
    prediction = shepard + alpha[:, None] * (affine - shepard)
    diagnostics = dict(diag_v4)
    diagnostics.update({
        "candidate_id": CANDIDATE_ID,
        "backend": BACKEND,
        "predictor": PREDICTOR,
        "blend_alpha": alpha,
        "blended_prediction": prediction,
        "qualification_claim": "none",
        "credit": 0,
    })
    return prediction, support_v4, pass_v4, diagnostics


__all__ = ["BACKEND", "CANDIDATE_ID", "PREDICTOR", "candidate_spec", "sample_candidate"]
