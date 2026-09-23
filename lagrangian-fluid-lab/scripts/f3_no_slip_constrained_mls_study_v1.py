"""Offline one-wall constrained-MLS study; not a registered F3 backend."""

from __future__ import annotations

import json

import numpy as np
from scipy.spatial import cKDTree

from scripts.f3_native_volume_mls import (
    F3CurrentFrame,
    F3NativeVolumeMLS,
    wendland_quintic_c2_3d,
)


def _cloud() -> np.ndarray:
    axes = (
        np.linspace(0.62, 0.99, 14),
        np.linspace(-0.12, 0.12, 9),
        np.linspace(-0.12, 0.12, 9),
    )
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def _frame(position: np.ndarray, velocity: np.ndarray) -> F3CurrentFrame:
    count = len(position)
    return F3CurrentFrame(
        position,
        velocity,
        np.full(count, 1.0e-3),
        np.full(count, 1000.0),
        np.ones(count, dtype=bool),
        frame_index=0,
        time_s=0.0,
    )


def _constrained_affine_fit(
    query: np.ndarray,
    frame: F3CurrentFrame,
    h_m: float,
    *,
    wall_x: float = 1.0,
) -> dict:
    """Fit affine velocity to F3 MLS support with u(projected wall point)=0."""
    tree = cKDTree(frame.position)
    pool = np.asarray(
        tree.query_ball_point(query, r=2.0 * h_m, p=2.0, eps=0.0,
                              workers=1, return_sorted=True),
        dtype=np.int64,
    )
    if not len(pool):
        raise ValueError("constrained fit has no particles in the 2h support")
    delta = frame.position[pool] - query
    distance = np.linalg.norm(delta, axis=1)
    weights = (frame.mass[pool] / frame.density[pool]) * wendland_quintic_c2_3d(
        distance, h_m
    )
    keep = np.isfinite(weights) & (weights > 0.0)
    pool, delta, weights = pool[keep], delta[keep], weights[keep]
    design = np.column_stack((np.ones(len(pool)), delta / h_m))
    sqrt_w = np.sqrt(weights)
    weighted_design = design * sqrt_w[:, None]
    weighted_values = frame.velocity[pool] * sqrt_w[:, None]

    # The unconstrained solution is retained only as a comparison baseline.
    free_coefficients, _, _, _ = np.linalg.lstsq(
        weighted_design, weighted_values, rcond=1e-12
    )

    wall_point = np.array(query, dtype=np.float64, copy=True)
    wall_point[0] = float(wall_x)
    constraint = np.concatenate(([1.0], (wall_point - query) / h_m))
    hessian = weighted_design.T @ weighted_design
    rhs = weighted_design.T @ weighted_values
    kkt = np.zeros((5, 5), dtype=np.float64)
    kkt[:4, :4] = hessian
    kkt[:4, 4] = constraint
    kkt[4, :4] = constraint
    constrained_rhs = np.vstack((rhs, np.zeros((1, 3), dtype=np.float64)))
    constrained_coefficients = np.linalg.solve(kkt, constrained_rhs)[:4]

    free_residual = design @ free_coefficients - frame.velocity[pool]
    constrained_residual = design @ constrained_coefficients - frame.velocity[pool]
    weight_total = float(np.sum(weights))
    free_rms = float(np.sqrt(np.sum(weights[:, None] * free_residual**2) / weight_total))
    constrained_rms = float(
        np.sqrt(np.sum(weights[:, None] * constrained_residual**2) / weight_total)
    )
    singular = np.linalg.svd(weighted_design, compute_uv=False)
    return {
        "free_velocity": free_coefficients[0],
        "constrained_velocity": constrained_coefficients[0],
        "free_wall_velocity": constraint @ free_coefficients,
        "constrained_wall_velocity": constraint @ constrained_coefficients,
        "support_count": int(len(pool)),
        "effective_sample_size": float(weight_total**2 / np.sum(weights**2)),
        "geometry_rank": int(np.count_nonzero(singular > singular[0] * 1e-12)),
        "condition_number": float(singular[0] / singular[-1]),
        "free_weighted_rms_residual": free_rms,
        "constrained_weighted_rms_residual": constrained_rms,
    }


def study() -> dict:
    position = _cloud()
    query = np.array([0.995, 0.0, 0.0], dtype=np.float64)
    direction = np.array([1.0, 0.2, -0.1], dtype=np.float64)
    distance_to_wall = 1.0 - position[:, 0]

    affine_values = distance_to_wall[:, None] * direction
    affine_frame = _frame(position, affine_values)
    affine_fit = _constrained_affine_fit(query, affine_frame, 0.08)
    affine_raw = F3NativeVolumeMLS(0.08).reconstruct(
        query[None, :], affine_frame, np.empty((0, 3, 3), dtype=np.float64)
    )
    affine_exact = (1.0 - query[0]) * direction

    # This concave near-wall profile remains positive on the entire sample
    # cloud yet can yield a spurious positive (outward) affine wall intercept.
    quadratic_values = (
        distance_to_wall - 2.0 * distance_to_wall**2
    )[:, None] * direction
    quadratic_frame = _frame(position, quadratic_values)
    quadratic_sweep = []
    for h_m in (0.08, 0.12, 0.16, 0.20):
        fitted = _constrained_affine_fit(query, quadratic_frame, h_m)
        raw = F3NativeVolumeMLS(h_m).reconstruct(
            query[None, :], quadratic_frame, np.empty((0, 3, 3), dtype=np.float64)
        )
        exact = (1.0 - query[0] - 2.0 * (1.0 - query[0]) ** 2) * direction
        quadratic_sweep.append({
            "h_m": h_m,
            "raw_reliable": bool(raw.reliable[0]),
            "raw_velocity": raw.velocity[0].tolist(),
            "constrained_velocity": fitted["constrained_velocity"].tolist(),
            "exact_velocity": exact.tolist(),
            "raw_x_absolute_error": float(abs(raw.velocity[0, 0] - exact[0])),
            "constrained_x_absolute_error": float(
                abs(fitted["constrained_velocity"][0] - exact[0])
            ),
            "raw_wall_x_velocity": float(fitted["free_wall_velocity"][0]),
            "constrained_wall_x_velocity": float(
                fitted["constrained_wall_velocity"][0]
            ),
            "support_count": fitted["support_count"],
            "effective_sample_size": fitted["effective_sample_size"],
            "geometry_rank": fitted["geometry_rank"],
            "condition_number": fitted["condition_number"],
            "raw_weighted_rms_residual": fitted["free_weighted_rms_residual"],
            "constrained_weighted_rms_residual": fitted[
                "constrained_weighted_rms_residual"
            ],
        })

    incompatible_values = np.tile(np.array([1.0, 0.0, 0.0]), (len(position), 1))
    incompatible_frame = _frame(position, incompatible_values)
    incompatible_fit = _constrained_affine_fit(query, incompatible_frame, 0.08)
    incompatible_raw = F3NativeVolumeMLS(0.08).reconstruct(
        query[None, :], incompatible_frame, np.empty((0, 3, 3), dtype=np.float64)
    )

    return {
        "schema": "f3_no_slip_constrained_mls_study_v1",
        "production_code_modified": False,
        "campaign_state_modified": False,
        "scope": "single stationary planar wall x=1; no wall-visibility crossing",
        "query": query.tolist(),
        "particle_count": int(len(position)),
        "affine_no_slip": {
            "raw_reliable": bool(affine_raw.reliable[0]),
            "exact_velocity": affine_exact.tolist(),
            "raw_velocity": affine_raw.velocity[0].tolist(),
            "constrained_velocity": affine_fit["constrained_velocity"].tolist(),
            "raw_wall_velocity": affine_fit["free_wall_velocity"].tolist(),
            "constrained_wall_velocity": affine_fit[
                "constrained_wall_velocity"
            ].tolist(),
        },
        "quadratic_no_slip_h_sweep": quadratic_sweep,
        "incompatible_constant_outward_samples": {
            "raw_reliable": bool(incompatible_raw.reliable[0]),
            "raw_velocity": incompatible_raw.velocity[0].tolist(),
            "constrained_velocity": incompatible_fit[
                "constrained_velocity"
            ].tolist(),
            "constrained_wall_velocity": incompatible_fit[
                "constrained_wall_velocity"
            ].tolist(),
            "x_velocity_change": float(
                incompatible_fit["constrained_velocity"][0]
                - incompatible_raw.velocity[0, 0]
            ),
        },
    }


def main() -> None:
    print(json.dumps(study(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
