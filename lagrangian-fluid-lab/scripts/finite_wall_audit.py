#!/usr/bin/env python3
"""Finite physical-wall geometry checks used by the F1 audit chain.

The solver's simulation domain and a case's physical container are different
objects.  This module deliberately models only finite closed faces and finite
obstacle boxes.  In particular, the top of the F1 tank is open: a point that
is above the rim and outside a side-plane is not a side-wall penetration.

Segment events are reported against saved-frame intervals.  The interpolated
fraction is a useful diagnostic locator, not a claim that the saved-frame
chord is the exact particle path between solver outputs.
"""

from __future__ import annotations

from typing import Any

import numpy as np


FACE_ORDER = ("bottom", "left", "right", "front", "back")
FACE_AXIS = {
    "bottom": (2, 0),
    "left": (0, 0),
    "right": (0, 1),
    "front": (1, 0),
    "back": (1, 1),
}


def _points(points: np.ndarray) -> np.ndarray:
    value = np.asarray(points, dtype=np.float64)
    if value.ndim != 2 or value.shape[1] != 3:
        raise ValueError(f"points must have shape [N,3], got {value.shape}")
    return value


def _bounds(spec: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    try:
        container = spec["container_interior"]
        lower = np.asarray([container["xmin"], container["ymin"], container["zmin"]], dtype=np.float64)
        upper = np.asarray([container["xmax"], container["ymax"], container["zmax"]], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "finite wall specs must declare xmin/xmax, ymin/ymax, and zmin/zmax"
        ) from error
    if not np.all(np.isfinite(np.concatenate((lower, upper)))) or np.any(upper <= lower):
        raise ValueError(f"invalid finite container bounds: lower={lower}, upper={upper}")
    return lower, upper


def _closed_faces(spec: dict[str, Any]) -> tuple[str, ...]:
    declared = spec.get("closed_faces", FACE_ORDER)
    faces = tuple(str(face).lower() for face in declared)
    unknown = sorted(set(faces) - set(FACE_ORDER))
    if unknown:
        raise ValueError(f"unknown closed physical faces: {unknown}")
    return tuple(face for face in FACE_ORDER if face in faces)


def _face_masks(points: np.ndarray, spec: dict[str, Any], tolerance: float) -> dict[str, np.ndarray]:
    """Return endpoint masks for points beyond each finite closed face."""
    points = _points(points)
    lower, upper = _bounds(spec)
    tol = float(tolerance)
    if not np.isfinite(tol) or tol < 0:
        raise ValueError(f"tolerance must be finite and non-negative, got {tolerance!r}")
    result: dict[str, np.ndarray] = {}
    for face in _closed_faces(spec):
        axis, side = FACE_AXIS[face]
        other = [index for index in range(3) if index != axis]
        plane = lower[axis] if side == 0 else upper[axis]
        outward = points[:, axis] < plane - tol if side == 0 else points[:, axis] > plane + tol
        projected = np.ones(len(points), dtype=bool)
        for index in other:
            projected &= (points[:, index] >= lower[index] - 1e-12) & (points[:, index] <= upper[index] + 1e-12)
        result[face] = outward & projected
    return result


def outside_closed_face_masks(points: np.ndarray, spec: dict[str, Any], tolerance: float) -> dict[str, np.ndarray]:
    """Public endpoint classification for finite closed physical faces."""
    return _face_masks(points, spec, tolerance)


def _box_penetration(points: np.ndarray, box: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    points = _points(points)
    lower = np.asarray([box["xmin"], box["ymin"], box["zmin"]], dtype=np.float64)
    upper = np.asarray([box["xmax"], box["ymax"], box["zmax"]], dtype=np.float64)
    inside = np.all((points > lower) & (points < upper), axis=1)
    penetration = np.zeros(len(points), dtype=np.float64)
    if inside.any():
        selected = points[inside]
        penetration[inside] = np.min(
            np.stack((selected - lower, upper - selected), axis=1), axis=(1, 2)
        )
    return inside, penetration


def _segment_face_hits(
    p0: np.ndarray,
    p1: np.ndarray,
    spec: dict[str, Any],
    tolerance: float,
) -> list[dict[str, Any]]:
    lower, upper = _bounds(spec)
    delta = p1 - p0
    hits: list[dict[str, Any]] = []
    tol = float(tolerance)
    for face in _closed_faces(spec):
        axis, side = FACE_AXIS[face]
        other = [index for index in range(3) if index != axis]
        plane = lower[axis] if side == 0 else upper[axis]
        direction = delta[:, axis]
        valid_direction = direction < 0 if side == 0 else direction > 0
        # Locate the nominal plane independently of the endpoint tolerance.
        # Otherwise subdividing a chord inside the tolerance band loses its
        # crossing. Contact alone is not outward motion; departure from exact
        # contact is located at fraction zero. Initially outward points are
        # endpoint states, not newly observed crossings.
        start_near_or_inside = p0[:, axis] >= plane if side == 0 else p0[:, axis] <= plane
        end_outward = p1[:, axis] < plane if side == 0 else p1[:, axis] > plane
        valid = valid_direction & start_near_or_inside & end_outward
        fraction = np.full(len(p0), np.nan, dtype=np.float64)
        nonzero = valid_direction
        fraction[nonzero] = (plane - p0[nonzero, axis]) / direction[nonzero]
        valid &= np.isfinite(fraction) & (fraction >= 0.0) & (fraction <= 1.0)
        crossing = p0 + fraction[:, None] * delta
        for index in other:
            valid &= (crossing[:, index] >= lower[index] - 1e-12) & (crossing[:, index] <= upper[index] + 1e-12)
        for index in np.flatnonzero(valid):
            hits.append({
                "point_index": int(index),
                "kind": "closed_face",
                "face": face,
                "fraction": float(fraction[index]),
                "crossing_position_m": crossing[index].tolist(),
            })
    return hits


def _segment_box_hits(
    p0: np.ndarray,
    p1: np.ndarray,
    box: dict[str, Any],
    tolerance: float,
) -> list[dict[str, Any]]:
    lower = np.asarray([box["xmin"], box["ymin"], box["zmin"]], dtype=np.float64)
    upper = np.asarray([box["xmax"], box["ymax"], box["zmax"]], dtype=np.float64)
    tol = float(tolerance)
    effective_lower = lower + tol
    effective_upper = upper - tol
    if np.any(effective_upper <= effective_lower):
        effective_lower, effective_upper = lower, upper
    delta = p1 - p0
    t_enter = np.full(len(p0), -np.inf, dtype=np.float64)
    t_exit = np.full(len(p0), np.inf, dtype=np.float64)
    for axis in range(3):
        direction = delta[:, axis]
        parallel = np.isclose(direction, 0.0, atol=1e-15, rtol=0.0)
        outside_parallel = parallel & ((p0[:, axis] <= effective_lower[axis]) | (p0[:, axis] >= effective_upper[axis]))
        t_enter[outside_parallel] = np.inf
        t_exit[outside_parallel] = -np.inf
        moving = ~parallel
        first = np.full(len(p0), np.nan, dtype=np.float64)
        second = np.full(len(p0), np.nan, dtype=np.float64)
        first[moving] = (effective_lower[axis] - p0[moving, axis]) / direction[moving]
        second[moving] = (effective_upper[axis] - p0[moving, axis]) / direction[moving]
        lo = np.minimum(first, second)
        hi = np.maximum(first, second)
        t_enter = np.maximum(t_enter, np.where(moving, lo, -np.inf))
        t_exit = np.minimum(t_exit, np.where(moving, hi, np.inf))
    hit = (t_enter < t_exit) & (t_exit >= 0.0) & (t_enter <= 1.0)
    fraction = np.clip(t_enter, 0.0, 1.0)
    crossing = p0 + fraction[:, None] * delta
    return [
        {
            "point_index": int(index),
            "kind": "obstacle",
            "obstacle_id": str(box["id"]),
            "fraction": float(fraction[index]),
            "crossing_position_m": crossing[index].tolist(),
        }
        for index in np.flatnonzero(hit)
    ]


def segment_crossing_events(
    p0: np.ndarray,
    p1: np.ndarray,
    spec: dict[str, Any],
    tolerance: float,
) -> list[dict[str, Any]]:
    """Return finite wall/obstacle crossings for saved-frame segments."""
    first = _points(p0)
    second = _points(p1)
    if first.shape != second.shape:
        raise ValueError(f"segment endpoints must have the same shape, got {first.shape} and {second.shape}")
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError("segment endpoints must be finite")
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and non-negative")
    events = _segment_face_hits(first, second, spec, tolerance)
    for obstacle in spec.get("obstacles", ()):  # finite solid inserts
        events.extend(_segment_box_hits(first, second, obstacle, tolerance))
    return sorted(events, key=lambda item: (item["point_index"], item["fraction"], item["kind"], item.get("face", item.get("obstacle_id", ""))))


def outside_runtime_domain_mask(
    points: np.ndarray,
    domain: dict[str, Any] | None,
    tolerance: float,
) -> np.ndarray | None:
    """Classify points outside an explicitly supplied runtime AABB.

    No runtime-domain inference is performed when ``domain`` is absent.  This
    prevents a physical-wall audit from silently turning a generated-particle
    envelope into a solver-domain claim.
    """
    points = _points(points)
    if domain is None:
        return None
    lower = np.asarray([domain["xmin"], domain["ymin"], domain["zmin"]], dtype=np.float64)
    upper = np.asarray([domain["xmax"], domain["ymax"], domain["zmax"]], dtype=np.float64)
    tol = float(tolerance)
    if not np.isfinite(np.r_[lower, upper, tol]).all() or np.any(upper <= lower) or tol < 0:
        raise ValueError("runtime domain and tolerance must be finite and ordered")
    return np.any((points < lower - tol) | (points > upper + tol), axis=1)


def wall_penetration(
    points: np.ndarray,
    mass: np.ndarray,
    spec: dict[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    """Summarize endpoint penetration against finite physical geometry."""
    points = _points(points)
    weights = np.asarray(mass, dtype=np.float64)
    if weights.ndim != 1 or len(weights) != len(points):
        raise ValueError(f"mass must have shape [{len(points)}], got {weights.shape}")
    faces = _face_masks(points, spec, tolerance)
    outside = np.zeros(len(points), dtype=bool)
    counts: dict[str, int] = {}
    masses: dict[str, float] = {}
    for face, mask in faces.items():
        outside |= mask
        counts[face] = int(mask.sum())
        masses[face] = float(weights[mask].sum(dtype=np.float64))

    obstacle_counts: dict[str, int] = {}
    obstacle_masses: dict[str, float] = {}
    obstacle_max_depth = 0.0
    inside_any = np.zeros(len(points), dtype=bool)
    for obstacle in spec.get("obstacles", ()):
        inside, penetration = _box_penetration(points, obstacle)
        inside_any |= inside
        obstacle_id = str(obstacle["id"])
        obstacle_counts[obstacle_id] = int(inside.sum())
        obstacle_masses[obstacle_id] = float(weights[inside].sum(dtype=np.float64))
        obstacle_max_depth = max(obstacle_max_depth, float(penetration.max(initial=0.0)))

    runtime_domain = spec.get("runtime_domain")
    runtime_outside = outside_runtime_domain_mask(points, runtime_domain, tolerance)
    return {
        "outside_closed_container_count": int(outside.sum()),
        "outside_closed_container_mass_kg": float(weights[outside].sum(dtype=np.float64)),
        "outside_closed_container_by_face": counts,
        "outside_closed_container_mass_by_face_kg": masses,
        "obstacle_penetration_count": int(inside_any.sum()),
        "obstacle_penetration_mass_kg": float(weights[inside_any].sum(dtype=np.float64)),
        "obstacle_penetration_max_depth_m": obstacle_max_depth,
        "obstacle_counts_by_id": obstacle_counts,
        "obstacle_mass_by_id_kg": obstacle_masses,
        "runtime_domain_status": "checked" if runtime_outside is not None else "not_checked",
        "runtime_domain_outside_count": int(runtime_outside.sum()) if runtime_outside is not None else None,
        "runtime_domain_outside_mass_kg": float(weights[runtime_outside].sum(dtype=np.float64)) if runtime_outside is not None else None,
        "closed_faces": list(_closed_faces(spec)),
        "open_faces": list(spec.get("open_faces", ())),
        "geometry_semantics": "finite_closed_faces_and_finite_obstacles",
    }
