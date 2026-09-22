"""Static, synthetic-only implementation of a new F4 reconstruction candidate.

This module composes two independently motivated *mechanisms* from the v2
manufactured calibration: a fixed k=32 visible support cap and the existing
local affine query-bias estimator.  It is intentionally not a native/source
runner and has no HDF5, solver, GPU, queue, registry, or ledger entry points.
The candidate remains proposal-only until a separately hash-bound root review
authorizes a future CPU canary.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from scripts.core_material import (
    CurrentField,
    F4_V3_BACKEND,
    F4_V3_ERROR_ESTIMATOR,
    F4_V3_NEIGHBOURS,
)


CANDIDATE_ID = "f4_supportcap_affine_query_bound_v3"
BACKEND = F4_V3_BACKEND
ERROR_ESTIMATOR = F4_V3_ERROR_ESTIMATOR
NEIGHBOURS = F4_V3_NEIGHBOURS
REGULARIZATION_M = 0.004
MAXIMUM_SUPPORT_DISTANCE_M = 0.03

# These values are copied from the registered F4 fixed gate.  They are not
# candidate parameters and must not be tuned by this module.
FIXED_GATE = {
    "minimum_effective_sample_size": 4.0,
    "minimum_geometry_rank": 3,
    "minimum_anisotropy": 0.005,
    "maximum_reconstruction_error_mps": 0.05 * np.sqrt(9.81 * 0.09),
}


def candidate_spec() -> dict[str, Any]:
    """Return the immutable candidate contract used by synthetic tests."""
    return {
        "candidate_id": CANDIDATE_ID,
        "backend": BACKEND,
        "mechanisms": [
            {
                "id": "support_cap",
                "registered_basis": "F4-H1-ess32-support-cap",
                "neighbours": NEIGHBOURS,
                "purpose": "increase local visible support without changing weights or gates",
            },
            {
                "id": "affine_query_bound",
                "registered_basis": "F4-H2-affine-query-bound",
                "error_estimator": ERROR_ESTIMATOR,
                "purpose": "include conservative local affine query bias in the existing error estimate",
            },
        ],
        "regularization_m": REGULARIZATION_M,
        "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
        "fixed_gate": dict(FIXED_GATE),
        "threshold_policy": "unchanged_registered_f4_gate",
        "denominator_policy": "all source seeds remain in denominator",
        "qualification_claim": "none",
        "credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "root_review_only": True,
        "authorized_one_cpu_only": False,
    }


def sample_candidate(
    position: np.ndarray,
    velocity: np.ndarray,
    query: np.ndarray,
    walls: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Sample only synthetic/current arrays with the fixed candidate contract.

    The API deliberately accepts arrays rather than a source path or provider.
    Thus a caller cannot accidentally turn the static candidate into a native
    material execution path.  ``CurrentField`` supplies the existing visible
    cKDTree and Shepard implementation; this wrapper fixes k=32 and the
    affine query-bound estimator together as one new versioned candidate.
    """
    field = CurrentField(position, velocity)
    sampled, support, passed, diagnostics = field.sample(
        query,
        np.empty((0, 3, 3), dtype=np.float64) if walls is None else walls,
        neighbours=NEIGHBOURS,
        regularization=REGULARIZATION_M,
        gate=FIXED_GATE,
        error_estimator=ERROR_ESTIMATOR,
        return_diagnostics=True,
    )
    diagnostics = dict(diagnostics)
    diagnostics.update(
        {
            "candidate_id": CANDIDATE_ID,
            "backend": BACKEND,
            "support_cap": NEIGHBOURS,
            "error_estimator": ERROR_ESTIMATOR,
            "fixed_gate": dict(FIXED_GATE),
            "qualification_claim": "none",
            "credit": 0,
        }
    )
    return sampled, support, passed, diagnostics


def static_review_contract() -> dict[str, Any]:
    """Return execution controls for a root-review-only static receipt."""
    return {
        "status": "proposal_only_root_review_required",
        "candidate_id": CANDIDATE_ID,
        "qualification_claim": "none",
        "credit": 0,
        "formal_scientific_admission": False,
        "authorized_one_cpu_only": False,
        "execution_controls": {
            "synthetic_arrays_only": True,
            "native_started": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "old_ess32_rerun": False,
            "old_affine_rerun": False,
        },
    }
