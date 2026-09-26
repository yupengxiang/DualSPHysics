"""Array-only F4 candidate using a local affine velocity predictor.

The candidate keeps the v3 visible k=32 support, Shepard geometry weights,
regularization, and every fixed gate.  Its predicted velocity is the weighted
local affine fit evaluated at the query.  To preserve the existing v3 error
gate semantics, the gate estimate remains the weighted fit residual plus the
absolute difference between the affine and Shepard predictions.  This is a
diagnostic proposal only: it is not registered in the production tracer and
cannot open native data or start a tracer, solver, GPU, worker, or queue.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from scripts.core_material import CurrentField, REGULARIZATION_M, _validate_walls
from scripts.f3_material_neighbors import _visible_support
from scripts.passive_tracers import _support_gate_pass, _support_metrics


CANDIDATE_ID = "f4_supportcap_local_affine_reconstruction_v4"
BACKEND = "f4_ckdtree_visible_shepard_ess32_local_affine_predictor_v4"
NEIGHBOURS = 32
ERROR_ESTIMATOR = "local_affine_residual_plus_shepard_disagreement"
MAXIMUM_SUPPORT_DISTANCE_M = 0.03
FIXED_GATE = {
    "minimum_effective_sample_size": 4.0,
    "minimum_geometry_rank": 3,
    "minimum_anisotropy": 0.005,
    "maximum_reconstruction_error_mps": 0.05 * np.sqrt(9.81 * 0.09),
}


def candidate_spec() -> dict[str, Any]:
    """Return the immutable algorithm and acceptance contract."""
    return {
        "candidate_id": CANDIDATE_ID,
        "backend": BACKEND,
        "support": {
            "neighbours": NEIGHBOURS,
            "visibility": "same finite-wall visible-support search as F4 v3",
            "weights": "1/(distance_squared+regularization_squared)",
            "regularization_m": REGULARIZATION_M,
            "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
        },
        "predictor": "weighted_local_affine_least_squares_at_query",
        "error_estimator": ERROR_ESTIMATOR,
        "fixed_gate": dict(FIXED_GATE),
        "gate_semantics": "F4 v3 weighted affine residual plus absolute affine-versus-Shepard prediction difference",
        "threshold_policy": "unchanged_registered_f4_gate",
        "denominator_policy": "all source seeds remain in denominator",
        "qualification_claim": "none",
        "credit": 0,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "production_tracer_registered": False,
        "native_started": False,
        "solver_started": False,
        "gpu_started": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
    }


def _empty_diagnostics() -> dict[str, Any]:
    return {
        "effective_sample_size": np.empty(0, dtype=np.float64),
        "geometry_rank": np.empty(0, dtype=np.int8),
        "anisotropy": np.empty(0, dtype=np.float64),
        "interpolation_reconstruction_error_mps": np.empty(0, dtype=np.float64),
        "local_affine_query_bias_mps": np.empty(0, dtype=np.float64),
        "estimated_interpolation_error_mps": np.empty(0, dtype=np.float64),
        "visible_neighbours": np.empty(0, dtype=np.int64),
        "selected_visible_neighbours": np.empty(0, dtype=np.int64),
        "visibility_search_width": np.empty(0, dtype=np.int64),
        "visibility_search_exhaustive": np.empty(0, dtype=bool),
        "support_distance": np.empty(0, dtype=np.float64),
        "backend": BACKEND,
        "error_estimator": ERROR_ESTIMATOR,
    }


def sample_candidate(
    position: np.ndarray,
    velocity: np.ndarray,
    query: np.ndarray,
    walls: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Predict query velocities from current arrays only.

    No nonfinite source row is silently dropped.  Support diagnostics and gate
    thresholds are exactly those used by the registered F4 v3 composition;
    only the value returned as the velocity predictor changes from Shepard to
    the weighted local affine fit.
    """
    position = np.asarray(position, dtype=np.float64)
    velocity = np.asarray(velocity, dtype=np.float64)
    query = np.asarray(query, dtype=np.float64)
    if position.ndim != 2 or position.shape[1:] != (3,) or len(position) == 0:
        raise ValueError("position must be a nonempty [N,3] array")
    if velocity.shape != position.shape:
        raise ValueError("velocity must have the same [N,3] shape as position")
    if query.ndim != 2 or query.shape[1:] != (3,):
        raise ValueError("query must have shape [Q,3]")
    if not all(np.isfinite(value).all() for value in (position, velocity, query)):
        raise ValueError("nonfinite source or query arrays are rejected; no rows are silently removed")

    triangles = _validate_walls(
        np.empty((0, 3, 3), dtype=np.float64) if walls is None else walls
    )
    field = CurrentField(position, velocity)
    if field.valid_count != field.input_count:
        raise ValueError("candidate input filtering changed the source denominator")

    count = len(query)
    predicted = np.full((count, 3), np.nan, dtype=np.float64)
    support = np.full(count, np.inf, dtype=np.float64)
    passed = np.zeros(count, dtype=bool)
    if count == 0:
        return predicted, support, passed, _empty_diagnostics()

    k = min(NEIGHBOURS, field.valid_count)
    selected, distance2, visible, width, exhaustive = _visible_support(
        field.tree, query, field.position, triangles, k
    )
    weights = np.where(
        np.isfinite(distance2), 1.0 / (distance2 + REGULARIZATION_M**2), 0.0
    )
    weight_sum = weights.sum(axis=1)
    local_position = field.position[selected]
    local_velocity = field.velocity[selected]
    center = np.sum(local_position * weights[..., None], axis=1) / weight_sum[:, None]
    offsets = local_position - center[:, None, :]
    design = np.concatenate((np.ones((count, k, 1)), offsets), axis=2)
    sqrt_weight = np.sqrt(weights)[..., None]
    coefficients = np.matmul(
        np.linalg.pinv(design * sqrt_weight), local_velocity * sqrt_weight
    )
    query_design = np.concatenate((np.ones((count, 1)), query - center), axis=1)
    affine_prediction = np.einsum("qi,qij->qj", query_design, coefficients)

    denominator = weight_sum
    shepard_prediction = np.divide(
        np.sum(weights[..., None] * local_velocity, axis=1),
        denominator[:, None],
        out=np.full((count, 3), np.nan, dtype=np.float64),
        where=denominator[:, None] > 0.0,
    )
    metrics = _support_metrics(
        query, field.position, field.velocity, selected, distance2, weights
    )
    residual = metrics["interpolation_reconstruction_error"]
    affine_shepard_delta = np.linalg.norm(affine_prediction - shepard_prediction, axis=1)
    estimated_error = residual + affine_shepard_delta

    predicted[:] = affine_prediction
    support[:] = np.sqrt(np.maximum(0.0, distance2.min(axis=1)))
    gate_metric = {
        "effective_sample_size": metrics["effective_sample_size"],
        "geometry_rank": metrics["geometry_rank"],
        "anisotropy": metrics["anisotropy"],
        "interpolation_reconstruction_error_mps": estimated_error,
    }
    passed[:] = _support_gate_pass(gate_metric, FIXED_GATE)
    diagnostics = {
        "effective_sample_size": metrics["effective_sample_size"],
        "geometry_rank": metrics["geometry_rank"],
        "anisotropy": metrics["anisotropy"],
        "interpolation_reconstruction_error_mps": residual,
        "local_affine_query_bias_mps": affine_shepard_delta,
        "estimated_interpolation_error_mps": estimated_error,
        "visible_neighbours": visible,
        "selected_visible_neighbours": np.isfinite(distance2).sum(axis=1),
        "visibility_search_width": width,
        "visibility_search_exhaustive": exhaustive,
        "support_distance": support,
        "backend": BACKEND,
        "error_estimator": ERROR_ESTIMATOR,
        "predictor": "weighted_local_affine_least_squares_at_query",
    }
    return predicted, support, passed, diagnostics
