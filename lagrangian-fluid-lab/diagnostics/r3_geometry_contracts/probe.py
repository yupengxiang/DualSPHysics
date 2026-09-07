#!/usr/bin/env python3
"""Adversarial synthetic diagnostics for tracer and G4 geometry contracts.

This file is intentionally self-contained.  It uses NumPy on CPU and does
not import a solver, a production tracer, a trained model, or a release
schema.  The output is therefore evidence about data/geometry contracts only,
not a physical acceptance result.

The probes cover four failure modes:

* a triangle is a rigid body and must be interpolated through a rigid pose,
  not by independently lerping its three world vertices;
* a wall can intersect a query--sample segment between saved frames even when
  a midpoint wall snapshot misses it, so visibility needs a space-time swept
  check;
* support count is only one observation: effective sample size, support
  geometry, and reconstruction error expose very different 23/24-sample
  situations;
* source labels are initial metadata, not a permanent post-mixing filter.
  Barrier, opening, and disconnected-blob counterexamples are kept separate.

The G4 part constructs two scenes with the same AABB but different internal
topology.  It shows that an AABB-only boundary summary is non-identifiable and
builds candidate model inputs containing per-component distance, normal, type,
and wall velocity.  Prescribed angular velocity is accepted as a control;
future fluid/free-body state is rejected.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np


LAB = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = Path(__file__).with_name("r3-geometry-contracts.json")
DEFAULT_MARKDOWN = Path(__file__).with_name("R3-GEOMETRY-CONTRACTS.md")

EPSILON = 1e-10
SUPPORT_REGULARIZATION_M = 0.004


# ---------------------------------------------------------------------------
# Small geometry primitives.  They are intentionally independent of the
# production tracer's implementation.
# ---------------------------------------------------------------------------


def _as_vector(value: Sequence[float], width: int = 3) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (width,):
        raise ValueError(f"expected a {width}-vector, got {result.shape}")
    return result


def axis_angle_quaternion(axis: Sequence[float], angle_rad: float) -> np.ndarray:
    """Return a unit ``[w, x, y, z]`` quaternion for an axis-angle pose."""
    axis_array = _as_vector(axis)
    norm = float(np.linalg.norm(axis_array))
    if norm <= EPSILON:
        raise ValueError("a rotation axis must be non-zero")
    half = float(angle_rad) / 2.0
    return np.concatenate(
        ([np.cos(half)], axis_array / norm * np.sin(half))
    )


def quaternion_normalize(quaternion: Sequence[float]) -> np.ndarray:
    quaternion_array = _as_vector(quaternion, width=4)
    norm = float(np.linalg.norm(quaternion_array))
    if norm <= EPSILON:
        raise ValueError("a quaternion must be non-zero")
    return quaternion_array / norm


def quaternion_slerp(
    first: Sequence[float], second: Sequence[float], alpha: float
) -> np.ndarray:
    """Spherical-linear interpolation for unit quaternions.

    The sign flip chooses the shortest representation of the same rotation;
    this makes the diagnostic deterministic for equivalent endpoint
    quaternions.
    """
    q0 = quaternion_normalize(first)
    q1 = quaternion_normalize(second)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    dot = float(np.clip(dot, -1.0, 1.0))
    alpha = float(alpha)
    if dot > 1.0 - 1e-8:
        return quaternion_normalize((1.0 - alpha) * q0 + alpha * q1)
    theta = float(np.arccos(dot))
    sine = float(np.sin(theta))
    return quaternion_normalize(
        (np.sin((1.0 - alpha) * theta) / sine) * q0
        + (np.sin(alpha * theta) / sine) * q1
    )


def quaternion_to_rotation(quaternion: Sequence[float]) -> np.ndarray:
    """Convert a ``[w, x, y, z]`` quaternion to a proper 3x3 rotation."""
    w, x, y, z = quaternion_normalize(quaternion)
    return np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def apply_rigid_pose(
    vertices: np.ndarray,
    translation: Sequence[float],
    quaternion: Sequence[float],
) -> np.ndarray:
    """Apply a world-from-body rigid pose to ``(..., 3)`` vertices."""
    points = np.asarray(vertices, dtype=np.float64)
    if points.shape[-1] != 3:
        raise ValueError("vertices must end in a 3-vector")
    return points @ quaternion_to_rotation(quaternion).T + _as_vector(translation)


def _triangle_edges(triangle: np.ndarray) -> np.ndarray:
    triangle = np.asarray(triangle, dtype=np.float64).reshape(3, 3)
    return np.asarray(
        [triangle[1] - triangle[0], triangle[2] - triangle[1], triangle[0] - triangle[2]],
        dtype=np.float64,
    )


def _triangle_area(triangle: np.ndarray) -> float:
    triangle = np.asarray(triangle, dtype=np.float64).reshape(3, 3)
    return float(0.5 * np.linalg.norm(np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])))


def dynamic_triangle_diagnostic(alpha: float = 0.5) -> dict[str, Any]:
    """Compare vertex lerp with analytic rigid-pose interpolation.

    The body triangle is rotated 90 degrees around ``z`` and translated at
    the second frame.  At ``alpha=0.5`` the independently lerped triangle is
    visibly contracted, while quaternion slerp preserves every body-space
    edge and area.
    """
    body_triangle = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64
    )
    q0 = np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    q1 = axis_angle_quaternion([0.0, 0.0, 1.0], np.pi / 2.0)
    translation0 = np.asarray([0.0, 0.0, 0.0], dtype=np.float64)
    translation1 = np.asarray([0.2, -0.1, 0.0], dtype=np.float64)
    world0 = apply_rigid_pose(body_triangle, translation0, q0)
    world1 = apply_rigid_pose(body_triangle, translation1, q1)

    q_mid = quaternion_slerp(q0, q1, alpha)
    translation_mid = (1.0 - alpha) * translation0 + alpha * translation1
    rigid_mid = apply_rigid_pose(body_triangle, translation_mid, q_mid)
    vertex_lerp_mid = (1.0 - alpha) * world0 + alpha * world1

    reference_edges = np.linalg.norm(_triangle_edges(body_triangle), axis=1)
    bad_edges = np.linalg.norm(_triangle_edges(vertex_lerp_mid), axis=1)
    rigid_edges = np.linalg.norm(_triangle_edges(rigid_mid), axis=1)
    rigid_edge_error = np.abs(rigid_edges - reference_edges)
    bad_edge_error = np.abs(bad_edges - reference_edges)
    reference_area = _triangle_area(body_triangle)
    return {
        "case_id": "dynamic_rigid_triangle_pose",
        "description": "same body triangle at two poses; midpoint is evaluated by quaternion slerp",
        "alpha": float(alpha),
        "body_triangle": body_triangle.tolist(),
        "endpoint_quaternions_wxyz": [q0.tolist(), q1.tolist()],
        "midpoint_quaternion_wxyz": q_mid.tolist(),
        "endpoint_translations_m": [translation0.tolist(), translation1.tolist()],
        "interpolation_methods": {
            "incorrect_vertex_lerp": "independent world-space vertex lerp",
            "candidate_rigid_pose": "linear translation + quaternion SLERP rotation",
        },
        "incorrect_vertex_lerp": {
            "vertices_m": vertex_lerp_mid.tolist(),
            "edge_lengths_m": bad_edges.tolist(),
            "max_edge_length_abs_error_m": float(np.max(bad_edge_error)),
            "area_m2": _triangle_area(vertex_lerp_mid),
            "area_abs_error_m2": float(abs(_triangle_area(vertex_lerp_mid) - reference_area)),
            "rigidity_preserved": bool(np.allclose(bad_edges, reference_edges, atol=1e-10)),
        },
        "candidate_rigid_pose": {
            "vertices_m": rigid_mid.tolist(),
            "edge_lengths_m": rigid_edges.tolist(),
            "max_edge_length_abs_error_m": float(np.max(rigid_edge_error)),
            "area_m2": _triangle_area(rigid_mid),
            "area_abs_error_m2": float(abs(_triangle_area(rigid_mid) - reference_area)),
            "rigidity_preserved": bool(np.allclose(rigid_edges, reference_edges, atol=1e-10)),
        },
        "endpoint_geometry_invariant": {
            "reference_edge_lengths_m": reference_edges.tolist(),
            "reference_area_m2": reference_area,
            "rotation_determinant": float(np.linalg.det(quaternion_to_rotation(q_mid))),
            "rotation_orthogonality_error": float(
                np.max(np.abs(quaternion_to_rotation(q_mid) @ quaternion_to_rotation(q_mid).T - np.eye(3)))
            ),
        },
        "status": "candidate_only",
        "formal_schema_change": False,
    }


def _rectangle_triangles(
    x: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
    *,
    component_id: str = "wall",
) -> dict[str, Any]:
    """Return a rectangle on ``x=constant`` with component metadata."""
    corners = np.asarray(
        [[x, y0, z0], [x, y1, z0], [x, y1, z1], [x, y0, z1]],
        dtype=np.float64,
    )
    # The normal points +x; orientation does not affect the symmetric hit test
    # but is useful as an explicit contract feature.
    return {
        "component_id": component_id,
        "type": "moving_wall",
        "triangles": corners[np.asarray([[0, 1, 2], [0, 2, 3]], dtype=np.int64)],
        "normal": np.asarray([1.0, 0.0, 0.0], dtype=np.float64),
    }


def _segment_triangle_intersection(
    start: Sequence[float],
    end: Sequence[float],
    triangle: np.ndarray,
    *,
    epsilon: float = EPSILON,
) -> bool:
    """Closed finite triangle test for a segment interior.

    End-point hits are included.  A wall-collision diagnostic should be
    conservative, so a segment touching a triangle edge is considered a hit.
    """
    origin = _as_vector(start)
    direction = _as_vector(end) - origin
    tri = np.asarray(triangle, dtype=np.float64).reshape(3, 3)
    edge1 = tri[1] - tri[0]
    edge2 = tri[2] - tri[0]
    cross_direction = np.cross(direction, edge2)
    determinant = float(np.dot(edge1, cross_direction))
    if abs(determinant) <= epsilon:
        return False
    inverse = 1.0 / determinant
    offset = origin - tri[0]
    u = inverse * float(np.dot(offset, cross_direction))
    if u < -epsilon or u > 1.0 + epsilon:
        return False
    qvec = np.cross(offset, edge1)
    v = inverse * float(np.dot(direction, qvec))
    if v < -epsilon or u + v > 1.0 + epsilon:
        return False
    distance = inverse * float(np.dot(edge2, qvec))
    return bool(-epsilon <= distance <= 1.0 + epsilon)


def segment_hits_triangles(
    start: Sequence[float], end: Sequence[float], triangles: np.ndarray
) -> bool:
    """Return whether a segment hits any finite triangle."""
    array = np.asarray(triangles, dtype=np.float64)
    if array.size == 0:
        return False
    return any(_segment_triangle_intersection(start, end, triangle) for triangle in array.reshape(-1, 3, 3))


def swept_wall_segment_intersects(
    segment_start: Sequence[float],
    segment_end: Sequence[float],
    wall_provider: Callable[[float], np.ndarray],
    *,
    time_samples: int = 401,
) -> dict[str, Any]:
    """Check a segment against a moving wall over the whole time interval.

    ``wall_provider(t)`` returns the finite triangle set at normalized time
    ``t``.  A production implementation may replace this deterministic
    sampling oracle with a continuous conservative CCD routine; this probe's
    purpose is to make the required space-time dimension observable.  The
    sample count is deliberately exposed and the synthetic event is broad
    enough to be caught with far fewer samples.
    """
    if int(time_samples) < 3:
        raise ValueError("time_samples must be at least three")
    times = np.linspace(0.0, 1.0, int(time_samples), dtype=np.float64)
    midpoint_triangles = np.asarray(wall_provider(0.5), dtype=np.float64)
    midpoint_hit = segment_hits_triangles(segment_start, segment_end, midpoint_triangles)
    hits: list[tuple[float, np.ndarray]] = []
    for time in times:
        triangles = np.asarray(wall_provider(float(time)), dtype=np.float64)
        if segment_hits_triangles(segment_start, segment_end, triangles):
            hits.append((float(time), triangles))
    # AABB over the sampled trajectory is a broad-phase diagnostic, not a
    # substitute for the finite triangle hit test.
    sampled_vertices = [
        np.asarray(wall_provider(float(time)), dtype=np.float64).reshape(-1, 3)
        for time in times
    ]
    nonempty_vertices = [vertices for vertices in sampled_vertices if len(vertices)]
    if nonempty_vertices:
        all_vertices = np.concatenate(nonempty_vertices, axis=0)
        wall_lower = np.min(all_vertices, axis=0)
        wall_upper = np.max(all_vertices, axis=0)
    else:
        wall_lower = np.full(3, np.nan, dtype=np.float64)
        wall_upper = np.full(3, np.nan, dtype=np.float64)
    segment_points = np.asarray([segment_start, segment_end], dtype=np.float64)
    segment_lower = np.min(segment_points, axis=0)
    segment_upper = np.max(segment_points, axis=0)
    broad_phase_overlap = bool(
        bool(nonempty_vertices)
        and np.all(wall_upper >= segment_lower)
        and np.all(segment_upper >= wall_lower)
    )
    first_time, _ = hits[0] if hits else (None, None)
    last_time, _ = hits[-1] if hits else (None, None)
    sampled_hit = bool(hits)
    # The swept AABB is deliberately conservative: it can flag a possible
    # contact that a narrow finite triangle does not actually realize at the
    # same time, but it cannot silently miss a trajectory that enters the
    # segment's swept broad phase.  Exact sample hits remain separately
    # disclosed in ``hit_sample_count``.
    swept_hit = bool(sampled_hit or broad_phase_overlap)
    return {
        "segment_start_m": _as_vector(segment_start).tolist(),
        "segment_end_m": _as_vector(segment_end).tolist(),
        "time_samples": int(time_samples),
        "endpoint_hits": {
            "t0": bool(segment_hits_triangles(segment_start, segment_end, wall_provider(0.0))),
            "t1": bool(segment_hits_triangles(segment_start, segment_end, wall_provider(1.0))),
        },
        "midpoint_wall_hit": bool(midpoint_hit),
        "sampled_wall_hit": sampled_hit,
        "swept_wall_hit": swept_hit,
        "first_hit_time_normalized": first_time,
        "last_hit_time_normalized": last_time,
        "hit_sample_count": int(len(hits)),
        "wall_swept_aabb_lower_m": wall_lower.tolist(),
        "wall_swept_aabb_upper_m": wall_upper.tolist(),
        "segment_aabb_overlap_broad_phase": broad_phase_overlap,
        "failure_detected_by_midpoint_only": bool(swept_hit and not midpoint_hit),
        "hit_evidence": "temporal_triangle_hit" if sampled_hit else (
            "conservative_swept_aabb_overlap" if broad_phase_overlap else "none"
        ),
        "check_kind": "space_time_swept_wall_candidate_check",
        "status": "candidate_only",
    }


def swept_wall_diagnostic() -> dict[str, Any]:
    """Construct a moving-wall pulse that midpoint geometry cannot see."""
    base = _rectangle_triangles(-0.0, -0.30, 0.30, -0.30, 0.30)["triangles"]

    def provider(time: float) -> np.ndarray:
        # The wall translates in x with a smooth out-and-back pulse.  At the
        # saved endpoints and midpoint it is outside the tracer segment; at
        # quarter points it sweeps through it.
        translated = base.copy()
        translated[..., 0] += 0.80 * np.cos(2.0 * np.pi * float(time))
        return translated

    result = swept_wall_segment_intersects(
        [-0.20, 0.0, 0.0], [0.20, 0.0, 0.0], provider, time_samples=401
    )
    result.update(
        {
            "case_id": "moving_wall_swept_between_frames",
            "wall_motion": "x(t) = 0.80 cos(2 pi t) m; finite y/z patch",
            "midpoint_wall_x_m": float(0.80 * np.cos(np.pi)),
            "interpretation": (
                "a midpoint snapshot is clear although the wall crosses the segment near t=0.25 and 0.75"
            ),
            "required_consumer_behavior": (
                "evaluate visibility in space-time (or use a conservative swept-wall CCD), not a midpoint snapshot only"
            ),
        }
    )
    return result


# ---------------------------------------------------------------------------
# Finite-support diagnostics.
# ---------------------------------------------------------------------------


def shepard_interpolate(
    query: Sequence[float],
    sample_positions: np.ndarray,
    sample_values: np.ndarray,
    *,
    neighbours: int,
    regularization_m: float = SUPPORT_REGULARIZATION_M,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a deterministic inverse-distance estimate and its support."""
    query_array = _as_vector(query)
    positions = np.asarray(sample_positions, dtype=np.float64)
    values = np.asarray(sample_values, dtype=np.float64)
    if positions.ndim != 2 or positions.shape[1] != 3 or len(positions) == 0:
        raise ValueError("sample_positions must have shape (N, 3), N > 0")
    if values.shape != positions.shape:
        raise ValueError("sample_values must have the same shape as sample_positions")
    k = min(max(int(neighbours), 1), len(positions))
    distances2 = np.sum((positions - query_array[None, :]) ** 2, axis=1)
    selected = np.argsort(distances2, kind="mergesort")[:k]
    selected_distances2 = distances2[selected]
    weights = 1.0 / (selected_distances2 + float(regularization_m) ** 2)
    normalized = weights / np.sum(weights)
    estimate = np.sum(normalized[:, None] * values[selected], axis=0)
    return estimate, selected, normalized


def _analytic_velocity(points: np.ndarray) -> np.ndarray:
    """Affine field with all three components contributing to reconstruction."""
    points = np.asarray(points, dtype=np.float64)
    return np.column_stack(
        [
            0.8 + 1.4 * points[:, 0] - 0.3 * points[:, 1],
            -0.2 + 0.6 * points[:, 0] + 1.1 * points[:, 1] + 0.2 * points[:, 2],
            0.4 - 0.5 * points[:, 0] + 0.25 * points[:, 1] + 1.7 * points[:, 2],
        ]
    )


def _support_points() -> dict[str, np.ndarray]:
    # Eight corners plus deterministic face/interior points give a well-
    # conditioned 24-sample support around the query.
    grid = np.asarray(
        [[x, y, z] for x in (-0.06, 0.06) for y in (-0.06, 0.06) for z in (-0.06, 0.06)],
        dtype=np.float64,
    )
    extra = np.asarray(
        [
            [0.00, -0.08, -0.04], [0.00, -0.08, 0.04], [0.00, 0.08, -0.04], [0.00, 0.08, 0.04],
            [-0.08, 0.00, -0.04], [-0.08, 0.00, 0.04], [0.08, 0.00, -0.04], [0.08, 0.00, 0.04],
            [-0.04, -0.04, 0.00], [-0.04, 0.04, 0.00], [0.04, -0.04, 0.00], [0.04, 0.04, 0.00],
            [-0.10, 0.02, 0.00], [0.10, -0.02, 0.00], [0.02, -0.10, 0.00], [-0.02, 0.10, 0.00],
        ],
        dtype=np.float64,
    )
    isotropic = np.vstack((grid, extra))
    # The same count, but one-sided and very thin in z: count is unchanged
    # while geometry and affine reconstruction are degraded.
    one_sided = np.asarray(
        [[0.025 + 0.004 * (index % 6), -0.045 + 0.018 * ((index // 2) % 6), -0.006 + 0.002 * (index % 3)] for index in range(24)],
        dtype=np.float64,
    )
    planar = np.asarray(
        [[-0.09 + 0.018 * (index % 10), -0.08 + 0.016 * ((index // 2) % 10), 0.0] for index in range(24)],
        dtype=np.float64,
    )
    return {
        "isotropic_24": isotropic,
        "isotropic_23": isotropic[:23],
        "one_sided_24": one_sided,
        "planar_24": planar,
    }


def _finite_float(value: float | np.floating[Any]) -> float:
    value = float(value)
    return value if np.isfinite(value) else float("nan")


def support_geometry_diagnostic(
    case_id: str,
    positions: np.ndarray,
    *,
    query: Sequence[float] = (0.0, 0.0, 0.025),
    neighbours: int = 24,
) -> dict[str, Any]:
    """Measure effective support, geometry, and known-field error."""
    points = np.asarray(positions, dtype=np.float64)
    values = _analytic_velocity(points)
    query_array = _as_vector(query)
    estimate, selected, weights = shepard_interpolate(
        query_array, points, values, neighbours=neighbours
    )
    selected_points = points[selected]
    weighted_centroid = np.sum(weights[:, None] * selected_points, axis=0)
    centered = selected_points - weighted_centroid[None, :]
    covariance = (centered * weights[:, None]).T @ centered
    eigenvalues = np.linalg.eigvalsh(covariance)
    eigenvalues = np.maximum(eigenvalues, 0.0)
    largest = float(np.max(eigenvalues)) if len(eigenvalues) else 0.0
    rank_tolerance = max(largest * 1e-8, 1e-14)
    rank = int(np.sum(eigenvalues > rank_tolerance))
    smallest_positive = float(np.min(eigenvalues[eigenvalues > rank_tolerance])) if rank else 0.0
    anisotropy = float(smallest_positive / largest) if largest > 0.0 and rank else 0.0
    effective_sample_size = float(1.0 / np.sum(weights ** 2))
    exact = _analytic_velocity(query_array[None, :])[0]
    error_vector = estimate - exact
    distance = np.linalg.norm(selected_points - query_array[None, :], axis=1)
    return {
        "case_id": case_id,
        "sample_count": int(len(points)),
        "requested_neighbours": int(neighbours),
        "selected_neighbour_count": int(len(selected)),
        "support_distance_min_m": float(np.min(distance)),
        "support_distance_max_m": float(np.max(distance)),
        "effective_sample_size": effective_sample_size,
        "effective_sample_size_definition": "(sum w)^2 / sum(w^2), with normalized weights equivalent to 1/sum(w^2)",
        "support_geometry": {
            "weighted_centroid_m": weighted_centroid.tolist(),
            "weighted_centroid_offset_from_query_m": (weighted_centroid - query_array).tolist(),
            "weighted_centroid_offset_norm_m": float(np.linalg.norm(weighted_centroid - query_array)),
            "covariance_eigenvalues_m2": eigenvalues.tolist(),
            "rank": rank,
            "anisotropy_smallest_to_largest": anisotropy,
            "rank_tolerance_m2": rank_tolerance,
        },
        "interpolation_reconstruction": {
            "analytic_velocity_at_query_mps": exact.tolist(),
            "estimated_velocity_mps": estimate.tolist(),
            "error_vector_mps": error_vector.tolist(),
            "absolute_error_mps": float(np.linalg.norm(error_vector)),
        },
        "formal_neighbour_threshold": None,
        "assessment": "candidate_only_informational; neighbour count alone is not an acceptance criterion",
    }


def build_support_diagnostic() -> dict[str, Any]:
    """Run support probes and explicitly contrast 23/24 with geometry."""
    points = _support_points()
    cases = {
        case_id: support_geometry_diagnostic(case_id, samples)
        for case_id, samples in points.items()
    }
    good23 = cases["isotropic_23"]
    bad24 = cases["one_sided_24"]
    good24 = cases["isotropic_24"]
    return {
        "scope": "finite-support effective sample size and reconstruction diagnostic",
        "cases": cases,
        "count_is_not_formal_threshold": True,
        "count_comparison": {
            "isotropic_23_selected": good23["selected_neighbour_count"],
            "isotropic_23_error_mps": good23["interpolation_reconstruction"]["absolute_error_mps"],
            "isotropic_24_selected": good24["selected_neighbour_count"],
            "isotropic_24_error_mps": good24["interpolation_reconstruction"]["absolute_error_mps"],
            "one_sided_24_selected": bad24["selected_neighbour_count"],
            "one_sided_24_error_mps": bad24["interpolation_reconstruction"]["absolute_error_mps"],
            "one_sided_24_anisotropy": bad24["support_geometry"]["anisotropy_smallest_to_largest"],
            "isotropic_23_anisotropy": good23["support_geometry"]["anisotropy_smallest_to_largest"],
            "interpretation": (
                "23 isotropic samples can be better supported than 24 one-sided samples; "
                "effective sample size, geometry rank/anisotropy, and known-field error must be reported together"
            ),
        },
        "required_metrics": [
            "effective_sample_size",
            "support_geometry",
            "interpolation_reconstruction.absolute_error_mps",
        ],
        "formal_gate": {
            "neighbour_count_used_as_gate": False,
            "threshold": None,
            "status": "candidate_only",
        },
    }


# ---------------------------------------------------------------------------
# Mixed source-label / geometry counterexamples.
# ---------------------------------------------------------------------------


def _visibility_matrix(
    queries: np.ndarray, positions: np.ndarray, triangles: np.ndarray
) -> np.ndarray:
    queries = np.asarray(queries, dtype=np.float64)
    positions = np.asarray(positions, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.float64)
    result = np.ones((len(queries), len(positions)), dtype=bool)
    if triangles.size == 0:
        return result
    for qi, query in enumerate(queries):
        for pi, position in enumerate(positions):
            result[qi, pi] = not segment_hits_triangles(query, position, triangles)
    return result


def _label_case_interpolation(
    query: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    labels: np.ndarray,
    barriers: np.ndarray,
) -> dict[str, Any]:
    visible = _visibility_matrix(query[None, :], positions, barriers)[0]
    if not np.any(visible):
        estimate = np.full(3, np.nan)
    else:
        estimate, selected, weights = shepard_interpolate(
            query, positions[visible], velocities[visible], neighbours=min(24, int(np.sum(visible)))
        )
        visible_indices = np.flatnonzero(visible)
        selected = visible_indices[selected]
    finite = np.isfinite(estimate).all()
    if not finite:
        selected = np.asarray([], dtype=np.int64)
        weights = np.asarray([], dtype=np.float64)
    if len(selected):
        label_weight = {
            str(label): float(np.sum(weights[labels[selected] == label]))
            for label in np.unique(labels)
        }
    else:
        label_weight = {str(label): 0.0 for label in np.unique(labels)}
    return {
        "visible_sample_count": int(np.sum(visible)),
        "visible_cross_source_count": int(np.sum(visible & (labels != labels[0]))),
        "selected_sample_count": int(len(selected)),
        "selected_source_labels": [str(label) for label in labels[selected]],
        "source_label_weight_fraction": label_weight,
        "estimated_velocity_mps": estimate.tolist() if finite else [None, None, None],
        "source_label_filter_applied": False,
    }


def _wall_with_gap() -> np.ndarray:
    panels = []
    for y0, y1 in ((-0.50, -0.10), (0.10, 0.50)):
        panels.append(_rectangle_triangles(0.0, y0, y1, -0.30, 0.30)["triangles"])
    return np.concatenate(panels, axis=0)


def _wall_full() -> np.ndarray:
    return _rectangle_triangles(0.0, -0.50, 0.50, -0.30, 0.30)["triangles"]


def run_mixed_label_diagnostic() -> dict[str, Any]:
    """Show why labels cannot be frozen, and where geometry is insufficient."""
    # Disconnected blobs deliberately have no triangles.  The synthetic
    # region-label oracle is included only to expose the unidentifiability.
    disconnected_positions = np.asarray(
        [[-0.08, 0.0, 0.0], [-0.06, 0.02, 0.0], [-0.04, -0.02, 0.0],
         [0.04, 0.0, 0.0], [0.06, 0.02, 0.0], [0.08, -0.02, 0.0]], dtype=np.float64
    )
    disconnected_labels = np.asarray(["blob_A"] * 3 + ["blob_B"] * 3)
    disconnected_velocities = np.asarray(
        [[0.0, 1.0, 0.0]] * 3 + [[0.0, -1.0, 0.0]] * 3, dtype=np.float64
    )
    disconnected_query = np.asarray([-0.045, 0.0, 0.0], dtype=np.float64)
    disconnected_all = _label_case_interpolation(
        disconnected_query, disconnected_positions, disconnected_velocities,
        disconnected_labels, np.empty((0, 3, 3), dtype=np.float64)
    )
    same_blob = disconnected_labels == "blob_A"
    disconnected_oracle = _label_case_interpolation(
        disconnected_query, disconnected_positions[same_blob], disconnected_velocities[same_blob],
        disconnected_labels[same_blob], np.empty((0, 3, 3), dtype=np.float64)
    )

    # A full finite wall blocks the B-side samples.  Their source label is not
    # consulted; the geometric segment test is the only exclusion.
    barrier_positions = np.asarray(
        [[-0.08, 0.0, 0.0], [-0.06, 0.12, 0.0], [0.06, 0.0, 0.0], [0.08, 0.12, 0.0]], dtype=np.float64
    )
    barrier_labels = np.asarray(["source_A", "source_A", "source_B", "source_B"])
    barrier_velocities = np.asarray(
        [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, -1.0, 0.0], [0.0, -1.0, 0.0]], dtype=np.float64
    )
    barrier_query = np.asarray([-0.05, 0.0, 0.0], dtype=np.float64)
    blocked = _label_case_interpolation(
        barrier_query, barrier_positions, barrier_velocities, barrier_labels, _wall_full()
    )

    # Two panels leave an opening.  A cross-label sample through the opening is
    # valid and must remain eligible; a permanent source filter would erase it.
    open_positions = np.asarray(
        [[-0.08, 0.0, 0.0], [0.08, 0.0, 0.0], [0.08, 0.25, 0.0], [-0.08, 0.25, 0.0]], dtype=np.float64
    )
    open_labels = np.asarray(["source_A", "source_B", "source_B", "source_A"])
    open_velocities = np.asarray(
        [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, -2.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64
    )
    open_query = np.asarray([-0.05, 0.0, 0.0], dtype=np.float64)
    opening = _label_case_interpolation(
        open_query, open_positions, open_velocities, open_labels, _wall_with_gap()
    )
    return {
        "case_id": "mixed_source_label_geometry_counterexamples",
        "source_label_contract": {
            "labels_are": "initial source metadata / lineage annotation",
            "permanent_post_mixing_filter": False,
            "filtering_policy": "never use source label as a permanent visibility gate after mixing",
        },
        "disconnected_blobs": {
            "geometry": "no barrier triangles; two blobs separated by a gap",
            "all_visible_interpolation": disconnected_all,
            "same_blob_label_oracle": disconnected_oracle,
            "geometry_only_non_identifiable": True,
            "counterexample": (
                "geometry-only visibility gives the same result with or without a disconnected-region label; "
                "the label oracle is candidate-only and cannot be silently promoted"
            ),
        },
        "blocked_samples": {
            "geometry": "finite wall between query and source_B samples",
            "wall_aware_interpolation": blocked,
            "blocked_cross_source_samples": int(
                len(barrier_positions) - blocked["visible_sample_count"]
            ),
            "counterexample": "source labels are not needed to reject a sample whose segment crosses a supplied wall",
        },
        "open_samples": {
            "geometry": "finite wall panels with y=-0.10..0.10 opening",
            "wall_aware_interpolation": opening,
            "cross_source_sample_through_opening_retained": bool(
                any(label == "source_B" for label in opening["selected_source_labels"])
            ),
            "counterexample": (
                "an open sample from another source label is valid; permanent label filtering would discard legal transport"
            ),
        },
        "status": "candidate_only",
        "formal_schema_change": False,
    }


# ---------------------------------------------------------------------------
# G4 model-input geometry contract.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundaryComponent:
    """Small serializable boundary component used by the G4 probe."""

    component_id: str
    boundary_type: str
    triangles: np.ndarray
    wall_velocity_mps: np.ndarray
    normal: np.ndarray

    def as_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "boundary_type": self.boundary_type,
            "triangles": np.asarray(self.triangles, dtype=np.float64).tolist(),
            "wall_velocity_mps": _as_vector(self.wall_velocity_mps).tolist(),
            "normal": _as_vector(self.normal).tolist(),
        }


def _box_face(
    lower: Sequence[float], upper: Sequence[float], side: str
) -> np.ndarray:
    lo = _as_vector(lower)
    hi = _as_vector(upper)
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    quads = {
        "xmin": [[x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]],
        "xmax": [[x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]],
        "ymin": [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]],
        "ymax": [[x0, y1, z0], [x0, y1, z1], [x1, y1, z1], [x1, y1, z0]],
        "zmin": [[x0, y0, z0], [x0, y0, z1], [x1, y0, z1], [x1, y0, z0]],
        "zmax": [[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]],
    }
    quad = np.asarray(quads[side], dtype=np.float64)
    return quad[np.asarray([[0, 1, 2], [0, 2, 3]], dtype=np.int64)]


def _component_from_triangles(
    component_id: str,
    boundary_type: str,
    triangles: np.ndarray,
    wall_velocity_mps: Sequence[float],
    normal: Sequence[float],
) -> BoundaryComponent:
    return BoundaryComponent(
        component_id=component_id,
        boundary_type=boundary_type,
        triangles=np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3),
        wall_velocity_mps=_as_vector(wall_velocity_mps),
        normal=_as_vector(normal),
    )


def build_g4_topology_cases() -> dict[str, list[BoundaryComponent]]:
    """Return same-AABB scenes with and without an internal baffle opening."""
    lower = (-1.0, -1.0, -1.0)
    upper = (1.0, 1.0, 1.0)
    outer_sides = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")

    def outer_components() -> list[BoundaryComponent]:
        return [
            _component_from_triangles(
                f"outer_{side}", "container", _box_face(lower, upper, side),
                (0.0, 0.0, 0.0),
                {"xmin": (1.0, 0.0, 0.0), "xmax": (-1.0, 0.0, 0.0),
                 "ymin": (0.0, 1.0, 0.0), "ymax": (0.0, -1.0, 0.0),
                 "zmin": (0.0, 0.0, 1.0), "zmax": (0.0, 0.0, -1.0)}[side],
            ) for side in outer_sides
        ]

    plain = outer_components()
    # An interior x=0 baffle has a central opening in y.  The split panels
    # carry a small prescribed wall velocity to exercise the dynamic field.
    baffle_panels = []
    for y0, y1 in ((-0.90, -0.15), (0.15, 0.90)):
        baffle_panels.append(_rectangle_triangles(0.0, y0, y1, -0.75, 0.75)["triangles"])
    baffle = _component_from_triangles(
        "internal_baffle_opening", "baffle", np.concatenate(baffle_panels, axis=0),
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
    )
    moving_baffle = _component_from_triangles(
        "moving_baffle_rim", "baffle_rim", _rectangle_triangles(0.0, -0.15, 0.15, -0.75, 0.75)["triangles"],
        (0.0, 0.0, 0.25), (1.0, 0.0, 0.0)
    )
    return {"plain_outer_box": plain, "baffled_with_opening": plain + [baffle, moving_baffle]}


def _component_aabb(components: Iterable[BoundaryComponent]) -> tuple[np.ndarray, np.ndarray]:
    vertices = np.concatenate([np.asarray(component.triangles).reshape(-1, 3) for component in components], axis=0)
    return np.min(vertices, axis=0), np.max(vertices, axis=0)


def boundary_aabb_summary(components: Iterable[BoundaryComponent]) -> dict[str, Any]:
    lower, upper = _component_aabb(components)
    return {
        "lower_m": lower.tolist(),
        "upper_m": upper.tolist(),
        "extent_m": (upper - lower).tolist(),
        "center_m": ((upper + lower) / 2.0).tolist(),
    }


def _topology_fingerprint(components: Iterable[BoundaryComponent]) -> str:
    normalized = []
    for component in components:
        normalized.append(
            {
                "component_id": component.component_id,
                "boundary_type": component.boundary_type,
                "triangles": np.asarray(component.triangles, dtype=np.float64).round(12).tolist(),
                "wall_velocity_mps": np.asarray(component.wall_velocity_mps, dtype=np.float64).round(12).tolist(),
            }
        )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _point_triangle_distance_and_normal(
    point: np.ndarray, triangle: np.ndarray, fallback_normal: np.ndarray
) -> tuple[float, np.ndarray]:
    """Return a stable plane-distance/normal feature for a finite triangle.

    The probe needs a per-component distance feature; a plane projection is
    sufficient because the model-input contract is the subject, not a mesh
    distance implementation.  The finite-triangle edge distance is added via
    a simple vertex/edge fallback for points outside the triangle.
    """
    tri = np.asarray(triangle, dtype=np.float64).reshape(3, 3)
    normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
    normal_norm = float(np.linalg.norm(normal))
    normal = normal / normal_norm if normal_norm > EPSILON else _as_vector(fallback_normal)
    signed_plane = float(np.dot(point - tri[0], normal))
    projection = point - signed_plane * normal

    # Barycentric test for projection inside the triangle.
    v0, v1, v2 = tri[1] - tri[0], tri[2] - tri[0], projection - tri[0]
    d00, d01, d11 = np.dot(v0, v0), np.dot(v0, v1), np.dot(v1, v1)
    d20, d21 = np.dot(v2, v0), np.dot(v2, v1)
    denominator = d00 * d11 - d01 * d01
    if abs(float(denominator)) > EPSILON:
        u = (d11 * d20 - d01 * d21) / denominator
        v = (d00 * d21 - d01 * d20) / denominator
        if u >= -EPSILON and v >= -EPSILON and u + v <= 1.0 + EPSILON:
            return abs(signed_plane), normal

    def point_segment_distance(segment_start: np.ndarray, segment_end: np.ndarray) -> float:
        direction = segment_end - segment_start
        denominator_segment = float(np.dot(direction, direction))
        fraction = float(np.dot(point - segment_start, direction) / denominator_segment) if denominator_segment > EPSILON else 0.0
        fraction = float(np.clip(fraction, 0.0, 1.0))
        return float(np.linalg.norm(point - (segment_start + fraction * direction)))

    edge_distance = min(
        point_segment_distance(tri[0], tri[1]),
        point_segment_distance(tri[1], tri[2]),
        point_segment_distance(tri[2], tri[0]),
    )
    return float(np.sqrt(signed_plane * signed_plane + edge_distance * edge_distance)), normal


def boundary_component_features(
    particle_position: Sequence[float], components: Iterable[BoundaryComponent]
) -> list[dict[str, Any]]:
    """Build required per-particle/per-boundary component features."""
    point = _as_vector(particle_position)
    features = []
    for component in components:
        distances_normals = [
            _point_triangle_distance_and_normal(point, triangle, component.normal)
            for triangle in np.asarray(component.triangles).reshape(-1, 3, 3)
        ]
        distance, normal = min(distances_normals, key=lambda pair: pair[0])
        features.append(
            {
                "component_id": component.component_id,
                "distance_to_boundary_component_m": float(distance),
                "distance_m": float(distance),
                "boundary_normal": normal.tolist(),
                "normal": normal.tolist(),
                "boundary_type": component.boundary_type,
                "type": component.boundary_type,
                "wall_velocity_mps": _as_vector(component.wall_velocity_mps).tolist(),
                "wall_velocity": _as_vector(component.wall_velocity_mps).tolist(),
            }
        )
    return features


FORBIDDEN_FUTURE_STATE_KEYS = frozenset(
    {
        "future_fluid_state", "future_free_body_state", "future_state", "next_state",
        "fluid_state_t1", "free_body_state_t1", "particle_velocity_t1", "body_pose_t1",
        "future_fluid_velocity", "future_free_body_velocity", "future_body_pose",
    }
)


def _is_forbidden_future_key(key: str) -> bool:
    """Catch explicit and obvious aliases for future fluid/body state."""
    normalized = key.lower().replace("-", "_")
    if normalized in FORBIDDEN_FUTURE_STATE_KEYS:
        return True
    future_marker = any(marker in normalized for marker in ("future", "next", "t1", "frame1"))
    state_marker = any(marker in normalized for marker in ("state", "velocity", "pose", "position", "acceleration"))
    body_or_fluid_marker = any(marker in normalized for marker in ("fluid", "free_body", "freebody", "rigid_body", "body"))
    return bool(future_marker and state_marker and body_or_fluid_marker)


def _find_forbidden_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_string = str(key)
            current = f"{path}.{key_string}" if path else key_string
            if _is_forbidden_future_key(key_string):
                found.append(current)
            found.extend(_find_forbidden_keys(nested, current))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            found.extend(_find_forbidden_keys(nested, f"{path}[{index}]"))
    return found


def validate_model_input_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate candidate G4 geometry fields and reject future-state leakage."""
    required = {"particle_position_m", "boundary_component_features", "control"}
    missing = sorted(required.difference(payload.keys()))
    forbidden = _find_forbidden_keys(payload)
    feature_errors: list[str] = []
    features = payload.get("boundary_component_features", [])
    if not isinstance(features, list) or not features:
        feature_errors.append("boundary_component_features must be a non-empty list")
    else:
        for index, feature in enumerate(features):
            if not isinstance(feature, Mapping):
                feature_errors.append(f"boundary_component_features[{index}] is not an object")
                continue
            for key in (
                "distance_to_boundary_component_m", "boundary_normal",
                "boundary_type", "wall_velocity_mps",
            ):
                if key not in feature:
                    feature_errors.append(f"boundary_component_features[{index}] missing {key}")
    control = payload.get("control", {})
    if not isinstance(control, Mapping):
        feature_errors.append("control must be an object")
    elif "prescribed_angular_velocity_radps" in control:
        try:
            _as_vector(control["prescribed_angular_velocity_radps"])
        except ValueError as error:
            feature_errors.append(str(error))
    errors = missing + feature_errors + [f"forbidden future-state key: {key}" for key in forbidden]
    return {
        "valid": not errors,
        "missing_required_fields": missing,
        "forbidden_future_state_keys": forbidden,
        "field_errors": feature_errors,
        "allowed_control_fields": ["prescribed_angular_velocity_radps", "prescribed_linear_velocity_mps"],
        "future_fluid_or_free_body_state_allowed": False,
    }


def is_valid_model_input(payload: Mapping[str, Any]) -> bool:
    """Boolean convenience wrapper for callers writing a contract test."""
    return bool(validate_model_input_contract(payload)["valid"])


def build_g4_model_input() -> dict[str, Any]:
    """Run AABB identifiability and feature/causality checks for G4."""
    cases = build_g4_topology_cases()
    names = tuple(cases)
    aabb = {name: boundary_aabb_summary(cases[name]) for name in names}
    fingerprints = {name: _topology_fingerprint(cases[name]) for name in names}
    particle_position = np.asarray([0.15, 0.0, 0.0], dtype=np.float64)
    control = {"prescribed_angular_velocity_radps": [0.0, 0.0, 0.50]}
    payloads = {}
    validation = {}
    for name, components in cases.items():
        payloads[name] = {
            "particle_position_m": particle_position.tolist(),
            "boundary_component_features": boundary_component_features(particle_position, components),
            "control": dict(control),
            "input_semantics": "current particle + current boundary component geometry + prescribed control only",
        }
        validation[name] = validate_model_input_contract(payloads[name])
    forged_future = dict(payloads[names[0]])
    forged_future["future_fluid_state"] = {"velocity_mps": [99.0, 0.0, 0.0]}
    future_rejection = validate_model_input_contract(forged_future)
    aabb_equal = bool(aabb[names[0]] == aabb[names[1]])
    topology_different = bool(fingerprints[names[0]] != fingerprints[names[1]])
    component_features_different = bool(
        payloads[names[0]]["boundary_component_features"] != payloads[names[1]]["boundary_component_features"]
    )
    # Count the deliberately ambiguous AABB-only representation as an
    # observed failure.  This is not silently converted to a success fraction.
    observed_checks = [
        # This is intentionally a failed candidate representation: a single
        # AABB cannot identify the two topologies.  Keeping it in the failure
        # denominator is important; reporting only the four successful
        # feature/control checks would hide the limitation.
        ("aabb_only_summary_identifies_topology", not (aabb_equal and topology_different)),
        ("component_features_distinguish_topology", component_features_different),
        ("plain_model_input_valid", validation[names[0]]["valid"]),
        ("baffled_model_input_valid", validation[names[1]]["valid"]),
        ("future_state_rejected", not future_rejection["valid"]),
    ]
    failures = [check_id for check_id, passed in observed_checks if not passed]
    return {
        "scope": "G4 current-geometry model-input contract diagnostic",
        "same_aabb_cases": list(names),
        "same_aabb": aabb_equal,
        "topology_fingerprints_differ": topology_different,
        "topology_description": {
            "plain_outer_box": "outer container only; no internal baffle",
            "baffled_with_opening": "same outer container plus split internal baffle panels and a central opening",
        },
        "aabb_summary": aabb,
        "topology_fingerprint_sha256": fingerprints,
        "aabb_only_boundary_summary_non_identifiable": bool(aabb_equal and topology_different),
        "component_feature_difference_detected": component_features_different,
        "required_boundary_component_feature_fields": [
            "distance_to_boundary_component_m",
            "boundary_normal",
            "boundary_type",
            "wall_velocity_mps",
        ],
        "model_inputs": payloads,
        "model_input_validation": validation,
        "prescribed_control_validation": {
            "angular_velocity_key": "prescribed_angular_velocity_radps",
            "accepted": all(result["valid"] for result in validation.values()),
            "future_fluid_or_free_body_state_allowed": False,
        },
        "future_state_negative_control": future_rejection,
        "observed_checks": [
            {
                "check_id": check_id,
                "passed": bool(passed),
                "expected_failure": bool(check_id == "aabb_only_summary_identifies_topology"),
            }
            for check_id, passed in observed_checks
        ],
        "validation_statistics": {
            "check_count": int(len(observed_checks)),
            "success_count": int(sum(bool(passed) for _, passed in observed_checks)),
            "failure_count": int(len(failures)),
            "failed_check_ids": failures,
            "failure_rate": float(len(failures) / len(observed_checks)),
            "candidate_representation_failure_count": 1 if aabb_equal and topology_different else 0,
            "input_contract_failure_count": int(
                sum(not result["valid"] for result in validation.values())
            ),
            "failure_count_including_candidate_representation": int(len(failures)),
            "reported_from_all_checks": True,
            "success_only_summary_forbidden": True,
        },
        "aabb_only_failure_statistics": {
            "ambiguous_scene_pair_count": 1 if aabb_equal and topology_different else 0,
            "aabb_only_success_count": 0,
            "aabb_only_failure_count": 1 if aabb_equal and topology_different else 0,
        },
        "status": "candidate_only",
        "formal_schema_change": False,
    }


# ---------------------------------------------------------------------------
# Report assembly / rendering.
# ---------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(nested) for nested in value]
    return value


def build_report() -> dict[str, Any]:
    """Run every deterministic CPU-only contract diagnostic."""
    triangle = dynamic_triangle_diagnostic()
    swept = swept_wall_diagnostic()
    support = build_support_diagnostic()
    mixed = run_mixed_label_diagnostic()
    g4 = build_g4_model_input()
    return _json_safe(
        {
            "schema_version": 1,
            "scope": "R3 tracer + G4 model-input geometry contracts",
            "execution_status": "complete",
            "acceptance_status": "candidate_only_rejected",
            "candidate_only": True,
            "formal_schema_change": False,
            "compute": {
                "backend": "NumPy CPU",
                "gpu_used": False,
                "cuda_used": False,
                "cfd_solver_run": False,
                "production_tracer_imported": False,
                "production_agent_files_modified": False,
            },
            "diagnostics": {
                "dynamic_rigid_triangle": triangle,
                "swept_wall": swept,
                "finite_support": support,
                "mixed_source_labels": mixed,
                "g4_model_input_geometry": g4,
            },
            "headline": {
                "vertex_lerp_rigidity_preserved": triangle["incorrect_vertex_lerp"]["rigidity_preserved"],
                "rigid_pose_rigidity_preserved": triangle["candidate_rigid_pose"]["rigidity_preserved"],
                "midpoint_wall_hit": swept["midpoint_wall_hit"],
                "swept_wall_hit": swept["swept_wall_hit"],
                "swept_wall_midpoint_failure_detected": swept["failure_detected_by_midpoint_only"],
                "support_count_is_formal_threshold": support["formal_gate"]["neighbour_count_used_as_gate"],
                "disconnected_blob_geometry_only_non_identifiable": mixed["disconnected_blobs"]["geometry_only_non_identifiable"],
                "open_cross_source_sample_retained": mixed["open_samples"]["cross_source_sample_through_opening_retained"],
                "g4_aabb_only_non_identifiable": g4["aabb_only_boundary_summary_non_identifiable"],
                "g4_validation_failure_count": g4["validation_statistics"]["failure_count_including_candidate_representation"],
            },
            "limitations": [
                "All scenes are deterministic synthetic contract probes, not CFD or physical validation.",
                "The swept-wall check uses a disclosed temporal sampling oracle; a production CCD must provide its own conservative guarantee.",
                "Disconnected liquid components require an explicit topology/region contract; finite wall visibility alone cannot infer them.",
                "Support metrics are diagnostics and intentionally do not define a universal neighbour-count threshold.",
                "G4 boundary features are candidate input fields; no formal release schema is changed.",
            ],
        }
    )


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise handoff with explicit candidate-only conclusions."""
    diagnostics = report["diagnostics"]
    triangle = diagnostics["dynamic_rigid_triangle"]
    swept = diagnostics["swept_wall"]
    support = diagnostics["finite_support"]
    mixed = diagnostics["mixed_source_labels"]
    g4 = diagnostics["g4_model_input_geometry"]
    rows = []
    for case_id, case in support["cases"].items():
        reconstruction = case["interpolation_reconstruction"]
        geometry = case["support_geometry"]
        rows.append(
            f"| `{case_id}` | {case['sample_count']} | {_fmt(case['effective_sample_size'])} | "
            f"{geometry['rank']} | {_fmt(geometry['anisotropy_smallest_to_largest'])} | "
            f"{_fmt(reconstruction['absolute_error_mps'])} |"
        )
    lines = [
        "# R3 geometry contracts synthetic diagnostics",
        "",
        "状态：**candidate-only / rejected；CPU-only，未运行 CFD，未导入生产 tracer，未改变正式 schema。**",
        "",
        "## 关键结论",
        "",
        f"- 动态三角形：逐顶点线性插值保持刚性的结论为 `{triangle['incorrect_vertex_lerp']['rigidity_preserved']}`，"
        f"最大边长误差 `{_fmt(triangle['incorrect_vertex_lerp']['max_edge_length_abs_error_m'])} m`；"
        f"线性平移 + quaternion SLERP 保持刚性 `{triangle['candidate_rigid_pose']['rigidity_preserved']}`，"
        f"误差 `{_fmt(triangle['candidate_rigid_pose']['max_edge_length_abs_error_m'])} m`。",
        f"- 移动壁：端点和 midpoint 都未命中（`{swept['midpoint_wall_hit']}`），但 swept-wall 在 "
        f"`t={_fmt(swept['first_hit_time_normalized'])}` 起检测到命中；midpoint-only 漏检为 `{swept['failure_detected_by_midpoint_only']}`。",
        f"- G4：两个场景 AABB 完全相同而拓扑 fingerprint 不同，因此 AABB-only boundary summary non-identifiable = "
        f"`{g4['aabb_only_boundary_summary_non_identifiable']}`。",
        "",
        "## 有限支撑（观察量，不是 23/24 正式阈值）",
        "",
        "| 支撑 | 样本数 | effective sample size | 几何 rank | 各向异性比 | 重构误差 [m/s] |",
        "|---|---:|---:|---:|---:|---:|",
        *rows,
        "",
        f"对照：23-sample isotropic 与 24-sample one-sided 的质量不能按数量排序；"
        f"正式 neighbour-count gate = `{support['formal_gate']['neighbour_count_used_as_gate']}`。",
        "",
        "## 混合后 source label 反例",
        "",
        f"- 分离液团且无 barrier：geometry-only non-identifiable = `{mixed['disconnected_blobs']['geometry_only_non_identifiable']}`；"
        "同源 label oracle 仅作 candidate 反事实，不能成为永久过滤。",
        f"- 阻挡样本：有限 wall segment test 排除跨墙样本；source label filter applied = "
        f"`{mixed['blocked_samples']['wall_aware_interpolation']['source_label_filter_applied']}`。",
        f"- 开放样本：跨 source label 的开口样本保留 = `{mixed['open_samples']['cross_source_sample_through_opening_retained']}`；"
        "永久按初始 source label 过滤会误删合法 transport。",
        "",
        "## G4 当前几何输入契约",
        "",
        "每个粒子—boundary component feature 明确包含 `distance_to_boundary_component_m`、"
        "`boundary_normal`、`boundary_type`、`wall_velocity_mps`；control 可含"
        "`prescribed_angular_velocity_radps`，不含未来 fluid/free-body state。",
        f"模型输入验证：plain={g4['model_input_validation']['plain_outer_box']['valid']}，"
        f"baffled={g4['model_input_validation']['baffled_with_opening']['valid']}；"
        f"未来状态 negative control accepted? `{g4['future_state_negative_control']['valid']}`。",
        f"统计完整报告失败数：candidate AABB representation failure=`{g4['validation_statistics']['candidate_representation_failure_count']}`，"
        f"input-contract failure=`{g4['validation_statistics']['input_contract_failure_count']}`，"
        f"总计 observed failure=`{g4['validation_statistics']['failure_count_including_candidate_representation']}`；"
        f"contract assertions 为 `{g4['validation_statistics']['failure_count']}` / "
        f"`{g4['validation_statistics']['check_count']}`，failed ids = "
        f"`{', '.join(g4['validation_statistics']['failed_check_ids']) or 'none'}`。",
        "",
        "## 边界",
        "",
        "这些结果是 candidate-only 契约证据，不是物理验收，也没有修改生产 tracer、agent 或正式 schema。"
        "时空扫掠探针明确公开了采样 oracle；生产实现仍需提供保守 CCD/运动边界语义。",
        "",
        "机器可读证据：`r3-geometry-contracts.json`；可重复入口："
        "`diagnostics/r3_geometry_contracts/probe.py`。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    report = build_report()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(report))
    print(json.dumps({
        "report": str(args.report),
        "markdown": str(args.markdown),
        "status": report["acceptance_status"],
        "gpu_used": report["compute"]["gpu_used"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
