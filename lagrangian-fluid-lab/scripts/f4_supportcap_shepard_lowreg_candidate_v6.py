"""F4 synthetic-array-only Shepard predictor with sharper distance weights.

The F4 v3 support selection and all support/gate diagnostics remain fixed at
their registered 32-neighbour composition. Only the value predictor uses a
smaller regularization length. This proposal is not registered in a production
tracer and cannot open native inputs or start a solver/worker.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from scripts.core_material import (
    CurrentField,
    _local_affine_query_bias,
    _validate_walls,
)
from scripts.f3_material_neighbors import _visible_support
from scripts.passive_tracers import _normalise_support_gate, _support_gate_pass, _support_metrics
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import (
    BACKEND as GATE_BACKEND,
    ERROR_ESTIMATOR,
    FIXED_GATE,
    NEIGHBOURS,
)


CANDIDATE_ID = "f4_supportcap_shepard_lowreg_predictor_v6"
BACKEND = "f4_v3_fixed_support_gate_low_regularization_shepard_predictor_v6"
PREDICTOR_REGULARIZATION_M = 0.00025


def candidate_spec() -> dict[str, Any]:
    """Return the proposal-only algorithm and unchanged acceptance contract."""
    return {
        "candidate_id": CANDIDATE_ID,
        "backend": BACKEND,
        "predictor": "inverse_distance_squared_shepard",
        "predictor_regularization_m": PREDICTOR_REGULARIZATION_M,
        "support_and_gate": {
            "source_candidate": "f4_supportcap_affine_query_bound_v3",
            "backend": GATE_BACKEND,
            "neighbours": NEIGHBOURS,
            "selection_rule": "same deterministic visible k-neighbour selection as v3",
            "metric_weights_regularization_m": PREDICTOR_REGULARIZATION_M,
            "error_estimator": ERROR_ESTIMATOR,
            "fixed_gate": dict(FIXED_GATE),
            "decisions_reused_exactly": False,
            "decisions_recomputed_from_candidate_prediction": True,
        },
        "threshold_policy": "unchanged_registered_f4_gate",
        "denominator_policy": "all source seeds remain in denominator; no filtering",
        "tuning_note": "synthetic screen only; selected after inspecting the prior analytic calibration corpus",
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
    """Use one visible support set for both low-reg prediction and its gate."""
    position = np.asarray(position, dtype=np.float64)
    velocity = np.asarray(velocity, dtype=np.float64)
    query = np.asarray(query, dtype=np.float64)
    if position.ndim != 2 or position.shape[1:] != (3,) or velocity.shape != position.shape:
        raise ValueError("position and velocity must both have shape [N,3]")
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
    if count == 0:
        empty = np.empty(0, dtype=np.float64)
        result = {
            "candidate_id": CANDIDATE_ID,
            "backend": BACKEND,
            "predictor": "inverse_distance_squared_shepard",
            "predictor_regularization_m": PREDICTOR_REGULARIZATION_M,
            "effective_sample_size": empty.copy(),
            "geometry_rank": np.empty(0, dtype=np.int8),
            "anisotropy": empty.copy(),
            "interpolation_reconstruction_error_mps": empty.copy(),
            "local_affine_query_bias_mps": empty.copy(),
            "estimated_interpolation_error_mps": empty.copy(),
            "visible_neighbours": np.empty(0, dtype=np.int64),
            "selected_visible_neighbours": np.empty(0, dtype=np.int64),
            "visibility_search_width": np.empty(0, dtype=np.int64),
            "visibility_search_exhaustive": np.empty(0, dtype=bool),
            "selected_support_indices": np.empty((0, min(NEIGHBOURS, field.valid_count)), dtype=np.int64),
            "error_estimator": ERROR_ESTIMATOR,
            "qualification_claim": "none",
            "credit": 0,
        }
        return np.empty((0, 3), dtype=np.float64), empty.copy(), np.empty(0, dtype=bool), result

    k = min(NEIGHBOURS, field.valid_count)
    selected, distance2, visible_count, search_width, exhaustive = _visible_support(
        field.tree, query, field.position, triangles, k
    )
    weights = np.where(
        np.isfinite(distance2),
        1.0 / (distance2 + PREDICTOR_REGULARIZATION_M**2),
        0.0,
    )
    weight_sum = weights.sum(axis=1)
    prediction = np.divide(
        np.sum(weights[..., None] * field.velocity[selected], axis=1),
        weight_sum[:, None],
        out=np.full((count, 3), np.nan, dtype=np.float64),
        where=weight_sum[:, None] > 0.0,
    )
    support = np.sqrt(np.maximum(0.0, distance2.min(axis=1)))
    metrics = _support_metrics(query, field.position, field.velocity, selected, distance2, weights)
    affine_bias = _local_affine_query_bias(
        query, field.position, field.velocity, selected, distance2, weights, prediction
    )
    estimated_error = metrics["interpolation_reconstruction_error"] + affine_bias
    gate_metrics = dict(metrics)
    gate_metrics["interpolation_reconstruction_error_mps"] = estimated_error
    passed = _support_gate_pass(gate_metrics, _normalise_support_gate(FIXED_GATE))
    result = {
        "effective_sample_size": metrics["effective_sample_size"],
        "geometry_rank": metrics["geometry_rank"],
        "anisotropy": metrics["anisotropy"],
        "interpolation_reconstruction_error_mps": metrics["interpolation_reconstruction_error"],
        "local_affine_query_bias_mps": affine_bias,
        "estimated_interpolation_error_mps": estimated_error,
        "visible_neighbours": visible_count,
        "selected_visible_neighbours": np.isfinite(distance2).sum(axis=1),
        "visibility_search_width": search_width,
        "visibility_search_exhaustive": exhaustive,
        "selected_support_indices": selected,
        "support_distance": support,
        "error_estimator": ERROR_ESTIMATOR,
    }
    result.update({
        "candidate_id": CANDIDATE_ID,
        "backend": BACKEND,
        "predictor": "inverse_distance_squared_shepard",
        "predictor_regularization_m": PREDICTOR_REGULARIZATION_M,
        "low_regularization_prediction": prediction,
        "qualification_claim": "none",
        "credit": 0,
    })
    return prediction, support, passed, result


__all__ = ["BACKEND", "CANDIDATE_ID", "PREDICTOR_REGULARIZATION_M", "candidate_spec", "sample_candidate"]
