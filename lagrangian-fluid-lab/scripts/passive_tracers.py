#!/usr/bin/env python3
"""Independent passive tracers advanced through exported SPH velocity samples."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
import os

import h5py
import numpy as np

try:  # Optional CPU acceleration for large no-barrier neighbour queries.
    import torch
except ModuleNotFoundError:  # pragma: no cover - exercised on minimal installs
    torch = None  # type: ignore[assignment]


EPSILON = 1e-10
_TORCH_NEIGHBOUR_CONFIGURED = False
_TORCH_NEIGHBOUR_DEVICE = None


def _torch_nearest_support(
    query: np.ndarray,
    particle_position: np.ndarray,
    k: int,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return exact Torch top-k distances/indices for the selected device.

    The default remains CPU and is byte-for-byte compatible with the previous
    optional accelerator contract.  A benchmark may set
    ``LAGRANGIAN_TRACER_TORCH_DEVICE=cuda:<index>`` to test a candidate CUDA
    implementation.  The candidate includes host/device transfers and an
    explicit synchronize in its measured call, and is only used for the
    no-finite-barrier path.  Finite-triangle visibility remains NumPy exact.
    """
    global _TORCH_NEIGHBOUR_CONFIGURED, _TORCH_NEIGHBOUR_DEVICE
    if torch is None:
        return None
    if not _TORCH_NEIGHBOUR_CONFIGURED:
        requested = os.environ.get("LAGRANGIAN_TRACER_TORCH_THREADS", "4")
        try:
            threads = max(1, int(requested))
        except ValueError:
            threads = 4
        torch.set_num_threads(threads)
        _TORCH_NEIGHBOUR_CONFIGURED = True
    requested_device = os.environ.get("LAGRANGIAN_TRACER_TORCH_DEVICE", "cpu").strip() or "cpu"
    try:
        device = torch.device(requested_device)
    except RuntimeError:
        return None
    if device.type == "cuda" and not torch.cuda.is_available():
        return None
    if _TORCH_NEIGHBOUR_DEVICE is None:
        _TORCH_NEIGHBOUR_DEVICE = device
    elif _TORCH_NEIGHBOUR_DEVICE != device:
        # A process should benchmark one backend at a time.  Refusing a
        # mid-process device switch avoids silently mixing cached CPU/CUDA
        # assumptions in a long tracer run.
        return None
    with torch.no_grad():
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        query_tensor = torch.from_numpy(np.ascontiguousarray(query, dtype=np.float64)).to(device=device)
        particle_tensor = torch.from_numpy(np.ascontiguousarray(particle_position, dtype=np.float64)).to(device=device)
        distance, selected = torch.topk(
            torch.cdist(query_tensor, particle_tensor),
            k=int(k), dim=1, largest=False, sorted=False,
        )
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        selected = selected.cpu()
        distance = distance.cpu()
    return (
        np.asarray(selected.numpy(), dtype=np.int64),
        np.asarray(distance.numpy(), dtype=np.float64) ** 2,
    )


# ---------------------------------------------------------------------------
# Rigid-pose motion primitives.
#
# These live in the production tracer module rather than in the synthetic
# geometry diagnostics.  A moving wall is a rigid body (or must provide an
# analytic pose callback); independently lerping its world-space vertices can
# shrink/expand a body during an interval and is therefore not a valid motion
# model.
# ---------------------------------------------------------------------------


def _unit_quaternion(value: Sequence[float]) -> np.ndarray:
    quaternion = np.asarray(value, dtype=np.float64).reshape(-1)
    if quaternion.shape != (4,):
        raise ValueError("quaternion must have shape (4,)")
    norm = float(np.linalg.norm(quaternion))
    if norm <= EPSILON or not np.isfinite(norm):
        raise ValueError("quaternion must be finite and non-zero")
    return quaternion / norm


def _rotation_to_quaternion(rotation: np.ndarray) -> np.ndarray:
    """Convert a proper 3x3 rotation to a ``[w,x,y,z]`` quaternion."""
    matrix = np.asarray(rotation, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError("rotation must be a finite 3x3 matrix")
    if not np.allclose(matrix @ matrix.T, np.eye(3), atol=1e-7, rtol=0.0):
        raise ValueError("transform rotation is not orthogonal")
    if np.linalg.det(matrix) <= 0.0:
        raise ValueError("transform rotation must have positive determinant")
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = 2.0 * np.sqrt(trace + 1.0)
        quaternion = np.asarray([
            0.25 * scale,
            (matrix[2, 1] - matrix[1, 2]) / scale,
            (matrix[0, 2] - matrix[2, 0]) / scale,
            (matrix[1, 0] - matrix[0, 1]) / scale,
        ])
    else:
        diagonal = np.diag(matrix)
        index = int(np.argmax(diagonal))
        if index == 0:
            scale = 2.0 * np.sqrt(max(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2], 0.0))
            quaternion = np.asarray([
                (matrix[2, 1] - matrix[1, 2]) / max(scale, EPSILON),
                0.25 * scale,
                (matrix[0, 1] + matrix[1, 0]) / max(scale, EPSILON),
                (matrix[0, 2] + matrix[2, 0]) / max(scale, EPSILON),
            ])
        elif index == 1:
            scale = 2.0 * np.sqrt(max(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2], 0.0))
            quaternion = np.asarray([
                (matrix[0, 2] - matrix[2, 0]) / max(scale, EPSILON),
                (matrix[0, 1] + matrix[1, 0]) / max(scale, EPSILON),
                0.25 * scale,
                (matrix[1, 2] + matrix[2, 1]) / max(scale, EPSILON),
            ])
        else:
            scale = 2.0 * np.sqrt(max(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1], 0.0))
            quaternion = np.asarray([
                (matrix[1, 0] - matrix[0, 1]) / max(scale, EPSILON),
                (matrix[0, 2] + matrix[2, 0]) / max(scale, EPSILON),
                (matrix[1, 2] + matrix[2, 1]) / max(scale, EPSILON),
                0.25 * scale,
            ])
    return _unit_quaternion(quaternion)


def _quaternion_to_rotation(quaternion: Sequence[float]) -> np.ndarray:
    w, x, y, z = _unit_quaternion(quaternion)
    return np.asarray([
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
    ], dtype=np.float64)


def _quaternion_slerp(first: Sequence[float], second: Sequence[float], alpha: float) -> np.ndarray:
    q0 = _unit_quaternion(first)
    q1 = _unit_quaternion(second)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    dot = float(np.clip(dot, -1.0, 1.0))
    if dot > 1.0 - 1e-8:
        return _unit_quaternion((1.0 - float(alpha)) * q0 + float(alpha) * q1)
    theta = float(np.arccos(dot))
    sine = float(np.sin(theta))
    return _unit_quaternion(
        (np.sin((1.0 - float(alpha)) * theta) / sine) * q0
        + (np.sin(float(alpha) * theta) / sine) * q1
    )


def validate_rigid_transform(transform: Sequence[Sequence[float]]) -> np.ndarray:
    """Validate and return a homogeneous rigid transform."""
    value = np.asarray(transform, dtype=np.float64)
    if value.shape != (4, 4) or not np.all(np.isfinite(value)):
        raise ValueError("rigid transform must be a finite 4x4 matrix")
    if not np.allclose(value[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8, rtol=0.0):
        raise ValueError("rigid transform must have homogeneous final row [0,0,0,1]")
    # This also rejects scale/shear, which cannot be represented by a pose.
    _rotation_to_quaternion(value[:3, :3])
    return value


def interpolate_rigid_transform(first: Sequence[Sequence[float]], second: Sequence[Sequence[float]], alpha: float) -> np.ndarray:
    """Interpolate translation linearly and rotation by quaternion SLERP."""
    first = validate_rigid_transform(first)
    second = validate_rigid_transform(second)
    translation = (1.0 - float(alpha)) * first[:3, 3] + float(alpha) * second[:3, 3]
    quaternion = _quaternion_slerp(
        _rotation_to_quaternion(first[:3, :3]),
        _rotation_to_quaternion(second[:3, :3]),
        float(alpha),
    )
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = _quaternion_to_rotation(quaternion)
    result[:3, 3] = translation
    return result


def segment_visibility(query, particle_position, barrier_triangles, *, epsilon=1e-9):
    """Return line-of-sight visibility for every query/particle pair.

    A neighbour is hidden when the open segment from the tracer to the sample
    intersects any finite barrier triangle.  The test is recomputed at every
    substep, so two liquid regions may become neighbours after a barrier moves
    away or after contact occurs; no initial connected component is frozen.
    """
    query = np.asarray(query, dtype=np.float64)
    particle_position = np.asarray(particle_position, dtype=np.float64)
    triangles = np.asarray(barrier_triangles, dtype=np.float64)
    if particle_position.ndim == 2:
        if particle_position.shape[1:] != (3,):
            raise ValueError("particle_position must have shape [N,3] or [Q,N,3]")
        pair_shape = (len(query), len(particle_position))
        origins = query[:, None, :]
        direction = particle_position[None, :, :] - origins
    elif particle_position.ndim == 3:
        if particle_position.shape[0] != len(query) or particle_position.shape[2:] != (3,):
            raise ValueError("per-query particle_position must have shape [Q,N,3]")
        pair_shape = particle_position.shape[:2]
        origins = query[:, None, :]
        direction = particle_position - origins
    else:
        raise ValueError("particle_position must have shape [N,3] or [Q,N,3]")
    visible = np.ones(pair_shape, dtype=bool)
    if triangles.size == 0:
        return visible
    pair_origins = np.broadcast_to(origins, direction.shape)
    segment_lower = np.minimum(pair_origins, particle_position)
    segment_upper = np.maximum(pair_origins, particle_position)
    for triangle in triangles.reshape(-1, 3, 3):
        # A segment can only intersect a finite triangle when their axis-
        # aligned bounding boxes overlap.  This broad phase is exact as a
        # rejection test (it cannot hide a possible intersection), and is
        # especially important for dense trajectory frames where most
        # particle pairs are far from a wall component.
        triangle_lower = np.min(triangle, axis=0) - epsilon
        triangle_upper = np.max(triangle, axis=0) + epsilon
        candidate = np.all(segment_upper >= triangle_lower, axis=-1)
        candidate &= np.all(segment_lower <= triangle_upper, axis=-1)
        if not candidate.any():
            continue
        candidate_indices = np.argwhere(candidate)
        candidate_origins = pair_origins[candidate]
        candidate_direction = direction[candidate]
        vertex, edge1, edge2 = triangle[0], triangle[1] - triangle[0], triangle[2] - triangle[0]
        h = np.cross(candidate_direction, edge2)
        determinant = np.einsum("...i,i->...", h, edge1)
        nonparallel = np.abs(determinant) > epsilon
        inverse = np.zeros_like(determinant)
        inverse[nonparallel] = 1.0 / determinant[nonparallel]
        offset = candidate_origins - vertex
        u = inverse * np.einsum("...i,...i->...", offset, h)
        qvec = np.cross(offset, edge1)
        v = inverse * np.einsum("...i,...i->...", candidate_direction, qvec)
        distance = inverse * np.einsum("...i,i->...", qvec, edge2)
        blocked = nonparallel & (u >= -epsilon) & (v >= -epsilon) & (u + v <= 1 + epsilon)
        blocked &= (distance > epsilon) & (distance < 1 - epsilon)
        visible[candidate_indices[:, 0], candidate_indices[:, 1]] &= ~blocked
    return visible


def corresponding_segments_blocked(start, end, barrier_triangles, *, epsilon=1e-9):
    """Conservatively check closed tracer segments against finite triangles.

    Non-tangential endpoint contact is unsafe for trusted advection: otherwise
    subdividing a crossing exactly at the wall makes both open segments miss.
    Neighbour visibility intentionally retains its separate open-segment rule.
    """
    start = np.asarray(start, dtype=np.float64)
    end = np.asarray(end, dtype=np.float64)
    triangles = np.asarray(barrier_triangles, dtype=np.float64)
    blocked = np.zeros(len(start), dtype=bool)
    if triangles.size == 0:
        return blocked
    direction = end - start
    for triangle in triangles.reshape(-1, 3, 3):
        vertex, edge1, edge2 = triangle[0], triangle[1] - triangle[0], triangle[2] - triangle[0]
        h = np.cross(direction, edge2)
        determinant = h @ edge1
        nonparallel = np.abs(determinant) > epsilon
        inverse = np.zeros_like(determinant)
        inverse[nonparallel] = 1.0 / determinant[nonparallel]
        offset = start - vertex
        u = inverse * np.einsum("qi,qi->q", offset, h)
        qvec = np.cross(offset, edge1)
        v = inverse * np.einsum("qi,qi->q", direction, qvec)
        distance = inverse * (qvec @ edge2)
        hit = nonparallel & (u >= -epsilon) & (v >= -epsilon) & (u + v <= 1 + epsilon)
        hit &= (distance >= -epsilon) & (distance <= 1 + epsilon)
        blocked |= hit
    return blocked


def _fit_rigid_transform_for_sweep(reference: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float]:
    """Small Kabsch fit used only by the swept-wall collision oracle."""
    source = np.asarray(reference, dtype=np.float64).reshape(-1, 3)
    destination = np.asarray(target, dtype=np.float64).reshape(-1, 3)
    source_center = source.mean(axis=0)
    destination_center = destination.mean(axis=0)
    covariance = (source - source_center).T @ (destination - destination_center)
    left, _, right_transpose = np.linalg.svd(covariance)
    rotation = right_transpose.T @ left.T
    if np.linalg.det(rotation) < 0.0:
        right_transpose[-1] *= -1.0
        rotation = right_transpose.T @ left.T
    translation = destination_center - rotation @ source_center
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rotation
    transform[:3, 3] = translation
    fitted = source @ rotation.T + translation
    residual = float(np.max(np.linalg.norm(fitted - destination, axis=1)))
    return transform, residual


def _point_triangle_distance(point: np.ndarray, triangle: np.ndarray) -> float:
    """Return Euclidean distance from a point to a finite triangle."""
    point = np.asarray(point, dtype=np.float64)
    tri = np.asarray(triangle, dtype=np.float64).reshape(3, 3)
    a, b, c = tri
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    norm = float(np.linalg.norm(normal))
    if norm <= EPSILON:
        return float(np.min(np.linalg.norm(tri - point, axis=1)))
    normal /= norm
    signed = float(np.dot(point - a, normal))
    projection = point - signed * normal
    v0, v1, v2 = b - a, c - a, projection - a
    d00, d01, d11 = np.dot(v0, v0), np.dot(v0, v1), np.dot(v1, v1)
    d20, d21 = np.dot(v2, v0), np.dot(v2, v1)
    denominator = d00 * d11 - d01 * d01
    if abs(float(denominator)) > EPSILON:
        u = (d11 * d20 - d01 * d21) / denominator
        v = (d00 * d21 - d01 * d20) / denominator
        if u >= -EPSILON and v >= -EPSILON and u + v <= 1.0 + EPSILON:
            return abs(signed)
    edge_distances = []
    for first, second in ((a, b), (b, c), (c, a)):
        edge = second - first
        fraction = float(np.dot(point - first, edge) / max(np.dot(edge, edge), EPSILON))
        closest = first + np.clip(fraction, 0.0, 1.0) * edge
        edge_distances.append(float(np.linalg.norm(point - closest)))
    return min(edge_distances)


def _signed_triangle_plane_distance(point: np.ndarray, triangle: np.ndarray) -> float:
    tri = np.asarray(triangle, dtype=np.float64).reshape(3, 3)
    normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
    norm = float(np.linalg.norm(normal))
    return float(np.dot(np.asarray(point, dtype=np.float64) - tri[0], normal) / norm) if norm > EPSILON else np.nan


def _rigid_sweep_bounds(points: np.ndarray, transform: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bound every vertex during identity-to-pose rotation plus translation.

    Each coordinate of ``R(theta) p`` is ``a cos(theta) + b sin(theta) + c``
    under quaternion SLERP's fixed axis, so evaluating its endpoints and
    stationary points gives an exact rotational bound.  Translation is linear
    and is bounded independently; the resulting box is conservative for the
    coupled rigid motion while remaining much tighter than a vertex-radius box.
    """
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    transform = validate_rigid_transform(transform)
    quaternion = _rotation_to_quaternion(transform[:3, :3])
    if quaternion[0] < 0.0:
        quaternion = -quaternion
    theta = float(2.0 * np.arccos(np.clip(quaternion[0], -1.0, 1.0)))
    half_sine = float(np.linalg.norm(quaternion[1:]))
    translation = np.asarray(transform[:3, 3], dtype=np.float64)
    if theta <= 1e-12 or half_sine <= EPSILON:
        rotated_lower = np.min(points, axis=0)
        rotated_upper = np.max(points, axis=0)
    else:
        axis = quaternion[1:] / half_sine
        values = []
        for point in points:
            parallel = axis * float(np.dot(axis, point))
            cosine_term = point - parallel
            sine_term = np.cross(axis, point)
            angles = [0.0, theta]
            for coordinate in range(3):
                phase = float(np.arctan2(sine_term[coordinate], cosine_term[coordinate]))
                for multiple in range(-2, 4):
                    candidate = phase + multiple * np.pi
                    if -1e-12 <= candidate <= theta + 1e-12:
                        angles.append(float(np.clip(candidate, 0.0, theta)))
            angles = np.asarray(angles, dtype=np.float64)
            values.append(
                parallel[None, :] + np.cos(angles)[:, None] * cosine_term[None, :]
                + np.sin(angles)[:, None] * sine_term[None, :]
            )
        rotated = np.concatenate(values, axis=0)
        rotated_lower = np.min(rotated, axis=0)
        rotated_upper = np.max(rotated, axis=0)
    translation_lower = np.minimum(np.zeros(3, dtype=np.float64), translation)
    translation_upper = np.maximum(np.zeros(3, dtype=np.float64), translation)
    return rotated_lower + translation_lower, rotated_upper + translation_upper


def spacetime_swept_wall_blocked(start, end, barrier_start, barrier_end=None, *, epsilon=1e-9):
    """Conservatively reject tracer paths intersecting a wall during an interval.

    A midpoint wall snapshot is not a space-time collision test: a finite wall
    can cross a tracer segment, then move away before the midpoint.  This
    routine combines exact endpoint checks with a conservative swept bounding
    box broad phase for every corresponding wall triangle.  The broad phase is
    intentionally conservative (false positives invalidate a tracer rather
    than allowing a possible wall crossing), and does not define the moving
    wall geometry used for interpolation.  The latter is supplied by a rigid
    pose or analytic provider.

    ``start`` and ``end`` are corresponding tracer positions for one
    substep.  ``barrier_start``/``barrier_end`` are finite triangles at the
    two substep endpoints.  When the wall is static this reduces to the exact
    segment/triangle test.
    """
    start = np.asarray(start, dtype=np.float64)
    end = np.asarray(end, dtype=np.float64)
    first = np.asarray(barrier_start, dtype=np.float64)
    second = first if barrier_end is None else np.asarray(barrier_end, dtype=np.float64)
    if start.ndim != 2 or end.shape != start.shape or start.shape[-1] != 3:
        raise ValueError("tracer endpoints must both have shape [Q,3]")
    if first.size == 0 and second.size == 0:
        return np.zeros(len(start), dtype=bool)
    if first.size == 0 or second.size == 0:
        # A topology change cannot be safely interpolated without an explicit
        # swept-wall representation; conservatively invalidate the interval.
        return np.ones(len(start), dtype=bool)
    first = first.reshape(-1, 3, 3)
    second = second.reshape(-1, 3, 3)
    if first.shape != second.shape:
        raise ValueError("barrier endpoint triangle axes differ")
    if np.allclose(first, second, atol=epsilon, rtol=0.0):
        return corresponding_segments_blocked(start, end, first, epsilon=epsilon)

    segment_lower = np.minimum(start, end)
    segment_upper = np.maximum(start, end)
    blocked = np.zeros(len(start), dtype=bool)
    for triangle0, triangle1 in zip(first, second):
        # Fit the endpoint pose and bound the complete rigid rotational arc,
        # not just the endpoint vertex union.  Candidate intervals are then
        # checked at rigid-pose samples; this avoids both rotational false
        # negatives and the very large radius box that invalidated most cup
        # tracers in the original broad-phase prototype.
        transform, residual = _fit_rigid_transform_for_sweep(triangle0, triangle1)
        center_lower, center_upper = _rigid_sweep_bounds(triangle0, transform)
        overlap = np.all(segment_upper >= center_lower - epsilon, axis=1)
        overlap &= np.all(segment_lower <= center_upper + epsilon, axis=1)
        if not overlap.any():
            continue
        if np.allclose(triangle0, triangle1, atol=epsilon, rtol=0.0):
            blocked |= overlap & corresponding_segments_blocked(
                start, end, triangle0[None, ...], epsilon=epsilon
            )
            continue
        if residual > max(1e-7, 1e-6 * max(float(np.ptp(triangle0, axis=0).max()), 1.0)):
            # A deforming wall has no safe implicit interpolation contract.
            # The broad phase is the only defensible fallback for this
            # malformed input; production sidecars reject it earlier.
            blocked |= overlap
            continue
        sampled_hit = np.zeros(len(start), dtype=bool)
        previous_distance = None
        for sample_alpha in np.linspace(0.0, 1.0, 17):
            pose = interpolate_rigid_transform(np.eye(4), transform, float(sample_alpha))
            triangle = transform_triangles(triangle0[None, ...], pose)[0]
            candidate = corresponding_segments_blocked(start, end, triangle[None, ...], epsilon=epsilon)
            sampled_hit |= overlap & candidate
            # Also test the instantaneous tracer position.  This catches a
            # stationary tracer crossed by a zero-thickness moving panel,
            # where a segment/triangle test has no direction to intersect.
            point = start + float(sample_alpha) * (end - start)
            distance = np.asarray([_point_triangle_distance(item, triangle) for item in point])
            signed_distance = np.asarray([_signed_triangle_plane_distance(item, triangle) for item in point])
            sampled_hit |= overlap & (distance <= max(epsilon, 1e-8))
            if previous_distance is not None:
                crossing = (previous_distance * signed_distance <= 0.0) & (
                    np.isfinite(previous_distance) & np.isfinite(signed_distance)
                )
                # A sign change between samples is a conservative swept-plane
                # hit.  Do not require either sampled distance to be near zero:
                # a fast wall can cross between samples while both snapshots
                # remain visibly separated from the tracer.
                sampled_hit |= overlap & crossing
            previous_distance = signed_distance
        blocked |= sampled_hit
    return blocked


# Descriptive aliases used by downstream custom scripts.
swept_wall_segment_blocked = spacetime_swept_wall_blocked
swept_segments_blocked = spacetime_swept_wall_blocked


def box_surface_triangles(lower, upper, sides=("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")):
    """Triangulate selected faces of an axis-aligned box."""
    x0, y0, z0 = map(float, lower)
    x1, y1, z1 = map(float, upper)
    quads = {
        "xmin": [[x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]],
        "xmax": [[x1, y0, z0], [x1, y0, z1], [x1, y1, z1], [x1, y1, z0]],
        "ymin": [[x0, y0, z0], [x0, y0, z1], [x1, y0, z1], [x1, y0, z0]],
        "ymax": [[x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]],
        "zmin": [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]],
        "zmax": [[x0, y0, z1], [x0, y1, z1], [x1, y1, z1], [x1, y0, z1]],
    }
    triangles = []
    for side in sides:
        quad = np.asarray(quads[side], dtype=np.float64)
        triangles.extend([quad[[0, 1, 2]], quad[[0, 2, 3]]])
    return np.asarray(triangles)


def transform_triangles(triangles, transform):
    triangles = np.asarray(triangles, dtype=np.float64)
    transform = validate_rigid_transform(transform)
    homogeneous = np.concatenate((triangles, np.ones((*triangles.shape[:-1], 1))), axis=-1)
    return (homogeneous @ transform.T)[..., :3]


def rigid_barrier_provider(transform_dataset, body_triangles, static_triangles=()):
    """Create an advector callback using a rigid pose at every substep.

    ``transform_dataset`` contains world-from-body homogeneous poses.  The
    callback interpolates the pose (translation + quaternion SLERP) and only
    then transforms the body triangles.  In particular, it never interpolates
    the three world-space vertices independently.
    """
    body_triangles = np.asarray(body_triangles, dtype=np.float64).reshape(-1, 3, 3)
    static_triangles = np.asarray(static_triangles, dtype=np.float64).reshape(-1, 3, 3)

    def provider(h5, frame0, frame1, alpha):
        first = validate_rigid_transform(h5[transform_dataset][frame0])
        second = validate_rigid_transform(h5[transform_dataset][frame1])
        moving = transform_triangles(body_triangles, interpolate_rigid_transform(first, second, alpha))
        return np.concatenate((moving, static_triangles), axis=0)

    provider.motion_interpolation = "rigid_pose_quaternion_slerp"  # type: ignore[attr-defined]
    provider.supports_spacetime_sweep = True  # type: ignore[attr-defined]
    return provider


def analytic_barrier_provider(body_triangles, pose_at_time: Callable[[float], Sequence[Sequence[float]]],
                              static_triangles=()):
    """Create a barrier callback from an analytic world-from-body pose.

    The solver-frame callback receives only the current interval endpoints and
    asks ``pose_at_time`` for each physical substep time.  This is the second
    supported production motion path for prescribed moving walls; callers do
    not need to materialize linearly interpolated wall vertices.
    """
    body_triangles = np.asarray(body_triangles, dtype=np.float64).reshape(-1, 3, 3)
    static_triangles = np.asarray(static_triangles, dtype=np.float64).reshape(-1, 3, 3)

    def provider(h5, frame0, frame1, alpha):
        times = np.asarray(h5["time"], dtype=np.float64)
        t0 = float(times[int(frame0)])
        t1 = float(times[int(frame1)])
        transform = validate_rigid_transform(pose_at_time((1.0 - float(alpha)) * t0 + float(alpha) * t1))
        moving = transform_triangles(body_triangles, transform)
        return np.concatenate((moving, static_triangles), axis=0)

    provider.motion_interpolation = "analytic_pose_callback"  # type: ignore[attr-defined]
    provider.supports_spacetime_sweep = True  # type: ignore[attr-defined]
    return provider


def _support_metrics(query: np.ndarray, particle_position: np.ndarray,
                     particle_velocity: np.ndarray, selected: np.ndarray,
                     selected_distance2: np.ndarray, weights: np.ndarray) -> dict[str, np.ndarray]:
    """Compute support quality without treating a neighbour count as a gate."""
    # Keep the same metrics as the scalar implementation, but evaluate the
    # fixed-size neighbour support in batches.  This is algebraically the
    # same weighted covariance/affine fit and avoids one Python-level SVD per
    # tracer per frame.
    count = len(query)
    finite = np.isfinite(selected_distance2) & (weights > 0.0)
    safe_weights = np.where(finite, np.asarray(weights, dtype=np.float64), 0.0)
    local_position = np.asarray(particle_position[selected], dtype=np.float64)
    local_velocity = np.asarray(particle_velocity[selected], dtype=np.float64)
    weight_sum = safe_weights.sum(axis=1)
    effective = np.divide(
        weight_sum * weight_sum,
        np.maximum(np.sum(safe_weights * safe_weights, axis=1), EPSILON),
        out=np.zeros(count, dtype=np.float64),
        where=weight_sum > 0.0,
    )
    center = np.divide(
        np.sum(local_position * safe_weights[..., None], axis=1),
        np.maximum(weight_sum, EPSILON)[:, None],
    )
    offsets = local_position - center[:, None, :]
    covariance = np.einsum("qki,qkj,qk->qij", offsets, offsets, safe_weights)
    covariance = covariance / np.maximum(weight_sum, EPSILON)[:, None, None]
    eigenvalues = np.linalg.eigvalsh(covariance)
    largest = np.max(eigenvalues, axis=1)
    tolerance = np.maximum(largest * 1e-8, 1e-14)
    ranks = np.sum(eigenvalues > tolerance[:, None], axis=1).astype(np.int8)
    positive = np.where(eigenvalues > tolerance[:, None], eigenvalues, np.inf)
    smallest_positive = np.min(positive, axis=1)
    anisotropy = np.divide(
        smallest_positive, largest,
        out=np.zeros(count, dtype=np.float64),
        where=(largest > 0.0) & np.isfinite(smallest_positive),
    )

    # A weighted local affine reconstruction error is an observable of the
    # support geometry/field, not a hard sample-count heuristic.  Batched
    # pseudoinverse has the same least-squares semantics as the old scalar
    # path and retains finite diagnostics for underdetermined supports.
    design = np.concatenate((np.ones((count, local_position.shape[1], 1)), offsets), axis=2)
    square_root = np.sqrt(safe_weights)[..., None]
    weighted_design = design * square_root
    weighted_velocity = local_velocity * square_root
    coefficients = np.matmul(np.linalg.pinv(weighted_design), weighted_velocity)
    predicted = np.matmul(design, coefficients)
    residual = predicted - local_velocity
    residual_energy = np.sum(safe_weights * np.sum(residual * residual, axis=2), axis=1)
    reconstruction = np.sqrt(
        np.divide(residual_energy, np.maximum(weight_sum, EPSILON), out=np.zeros(count), where=weight_sum > 0.0)
    )
    reconstruction[weight_sum <= 0.0] = np.inf
    return {
        "effective_sample_size": effective,
        "geometry_rank": ranks,
        "anisotropy": anisotropy,
        "interpolation_reconstruction_error": reconstruction,
    }


def shepard_velocity_with_diagnostics(query, particle_position, particle_velocity, *, neighbours=24,
                                      regularization=0.004, chunk_size=128,
                                      barrier_triangles=None):
    """Interpolate velocity and return support-quality diagnostics.

    The returned diagnostics are per-query arrays.  Consumers should gate on
    effective sample size, weighted geometry rank/anisotropy, and local
    reconstruction error together; ``neighbours`` only controls the candidate
    support size and is never itself a reliability threshold.  The interpolant
    uses no SPH particle identity: it is a generic inverse-distance Shepard
    check over exported trajectory samples.
    """
    query = np.asarray(query, dtype=np.float64)
    particle_position = np.asarray(particle_position, dtype=np.float64)
    particle_velocity = np.asarray(particle_velocity, dtype=np.float64)
    if not len(particle_position):
        raise ValueError("cannot interpolate an empty particle frame")
    k = min(int(neighbours), len(particle_position))
    result = np.empty_like(query)
    support = np.empty(len(query), dtype=np.float64)
    visible_neighbours = np.empty(len(query), dtype=np.int64)
    visibility_search_width = np.empty(len(query), dtype=np.int64)
    effective_sample_size = np.empty(len(query), dtype=np.float64)
    geometry_rank = np.empty(len(query), dtype=np.int8)
    anisotropy = np.empty(len(query), dtype=np.float64)
    reconstruction_error = np.empty(len(query), dtype=np.float64)
    visibility_mode = "no_barrier"
    epsilon2 = float(regularization) ** 2
    for start in range(0, len(query), chunk_size):
        stop = min(start + chunk_size, len(query))
        triangles = None if barrier_triangles is None else np.asarray(barrier_triangles, dtype=np.float64)
        accelerated = triangles is None or triangles.size == 0
        selected_distance2 = None
        selected = None
        if accelerated:
            nearest = _torch_nearest_support(query[start:stop], particle_position, k)
            if nearest is not None:
                selected, selected_distance2 = nearest
                visible_neighbours[start:stop] = len(particle_position)
                visibility_search_width[start:stop] = len(particle_position)
                visibility_mode = "torch_exact_no_barrier"
        if selected is None:
            delta = query[start:stop, None, :] - particle_position[None, :, :]
            distance2 = np.einsum("qpi,qpi->qp", delta, delta)
            if triangles is not None:
                if triangles.size and len(particle_position) > max(4 * k, 128):
                    # Find the exact top-k visible support without testing
                    # every query against every finite triangle.  The first
                    # candidate pool contains 4k nearest samples; if fewer
                    # than k remain visible, the pool is expanded.  Once k
                    # visible samples are present, every unsearched sample is
                    # no closer than the pool boundary, so the selected
                    # visible top-k is exact.
                    candidate_width = min(max(4 * k, k), len(particle_position))
                    candidate_indices = None
                    candidate_visible = None
                    while True:
                        candidate_indices = np.argpartition(
                            distance2, candidate_width - 1, axis=1
                        )[:, :candidate_width]
                        candidate_position = particle_position[candidate_indices]
                        candidate_visible = segment_visibility(
                            query[start:stop], candidate_position, triangles
                        )
                        visible_count = candidate_visible.sum(axis=1)
                        if candidate_width == len(particle_position) or np.all(visible_count >= k):
                            break
                        candidate_width = min(len(particle_position), candidate_width * 2)
                    visible = np.zeros_like(distance2, dtype=bool)
                    rows = np.arange(stop - start)[:, None]
                    visible[rows, candidate_indices] = candidate_visible
                    visible_neighbours[start:stop] = visible_count
                    visibility_mode = "adaptive_exact_visible_top_k"
                    visibility_search_width[start:stop] = candidate_width
                else:
                    visible = segment_visibility(query[start:stop], particle_position, triangles)
                    visible_neighbours[start:stop] = visible.sum(axis=1)
                    visibility_mode = "full_pairwise_exact"
                    visibility_search_width[start:stop] = len(particle_position)
            else:
                visible = np.ones_like(distance2, dtype=bool)
                visible_neighbours[start:stop] = len(particle_position)
                visibility_mode = "no_barrier"
                visibility_search_width[start:stop] = len(particle_position)
            distance2[~visible] = np.inf
            selected = np.argpartition(distance2, k - 1, axis=1)[:, :k]
            selected_distance2 = np.take_along_axis(distance2, selected, axis=1)
        weights = np.where(np.isfinite(selected_distance2), 1.0 / (selected_distance2 + epsilon2), 0.0)
        selected_velocity = particle_velocity[selected]
        denominator = weights.sum(axis=1)
        numerator = np.sum(weights[..., None] * selected_velocity, axis=1)
        result[start:stop] = np.divide(numerator, denominator[:, None], out=np.full_like(numerator, np.nan), where=denominator[:, None] > 0)
        support[start:stop] = np.sqrt(selected_distance2.min(axis=1))
        metrics = _support_metrics(
            query[start:stop], particle_position, particle_velocity,
            selected, selected_distance2, weights,
        )
        effective_sample_size[start:stop] = metrics["effective_sample_size"]
        geometry_rank[start:stop] = metrics["geometry_rank"]
        anisotropy[start:stop] = metrics["anisotropy"]
        reconstruction_error[start:stop] = metrics["interpolation_reconstruction_error"]
    diagnostics = {
        "effective_sample_size": effective_sample_size,
        "geometry_rank": geometry_rank,
        "anisotropy": anisotropy,
        "interpolation_reconstruction_error_mps": reconstruction_error,
        "visible_neighbours": visible_neighbours,
        "support_distance": support,
        "visibility_search_width": visibility_search_width,
        "visibility_mode": visibility_mode,
    }
    return result, support, visible_neighbours, diagnostics


def shepard_velocity(query, particle_position, particle_velocity, *, neighbours=24,
                     regularization=0.004, chunk_size=128, barrier_triangles=None,
                     return_diagnostics=False, return_support_diagnostics=False):
    """Backward-compatible velocity interpolator.

    Set ``return_diagnostics=True`` for the historical three-array return
    value.  New production callers should use
    :func:`shepard_velocity_with_diagnostics` so support gates can inspect
    ESS/geometry/reconstruction quality.
    """
    result, support, visible, diagnostics = shepard_velocity_with_diagnostics(
        query, particle_position, particle_velocity, neighbours=neighbours,
        regularization=regularization, chunk_size=chunk_size,
        barrier_triangles=barrier_triangles,
    )
    if return_support_diagnostics or return_diagnostics == "full":
        return result, support, visible, diagnostics
    if return_diagnostics:
        return result, support, visible
    return result, support


DEFAULT_SUPPORT_GATE = {
    # One finite weighted sample is the minimum usable support.  Higher
    # quality thresholds remain caller-configurable; this permissive default
    # preserves exact-particle seed trajectories while still rejecting empty,
    # rank-zero, or non-finite supports.
    "minimum_effective_sample_size": 1.0,
    "minimum_geometry_rank": 1,
    "minimum_anisotropy": 1e-8,
    "maximum_reconstruction_error_mps": None,
}


def _normalise_support_gate(support_gate: Mapping[str, Any] | None) -> dict[str, Any]:
    gate = dict(DEFAULT_SUPPORT_GATE)
    if support_gate is not None:
        gate.update(dict(support_gate))
    ess = float(gate["minimum_effective_sample_size"])
    rank = int(gate["minimum_geometry_rank"])
    anisotropy = float(gate["minimum_anisotropy"])
    reconstruction = gate.get("maximum_reconstruction_error_mps")
    if not np.isfinite(ess) or ess < 0.0:
        raise ValueError("minimum_effective_sample_size must be finite and non-negative")
    if rank < 0 or rank > 3:
        raise ValueError("minimum_geometry_rank must be in [0,3]")
    if not np.isfinite(anisotropy) or anisotropy < 0.0:
        raise ValueError("minimum_anisotropy must be finite and non-negative")
    if reconstruction is not None:
        reconstruction = float(reconstruction)
        if not np.isfinite(reconstruction) or reconstruction < 0.0:
            raise ValueError("maximum_reconstruction_error_mps must be finite and non-negative")
    return {
        "minimum_effective_sample_size": ess,
        "minimum_geometry_rank": rank,
        "minimum_anisotropy": anisotropy,
        "maximum_reconstruction_error_mps": reconstruction,
    }


def _support_gate_pass(diagnostics: Mapping[str, np.ndarray], gate: Mapping[str, Any]) -> np.ndarray:
    effective = np.asarray(diagnostics["effective_sample_size"], dtype=float)
    rank = np.asarray(diagnostics["geometry_rank"], dtype=float)
    anisotropy = np.asarray(diagnostics["anisotropy"], dtype=float)
    reconstruction = np.asarray(diagnostics["interpolation_reconstruction_error_mps"], dtype=float)
    passed = np.isfinite(effective) & (effective >= float(gate["minimum_effective_sample_size"]))
    passed &= np.isfinite(rank) & (rank >= float(gate["minimum_geometry_rank"]))
    passed &= np.isfinite(anisotropy) & (anisotropy >= float(gate["minimum_anisotropy"]))
    maximum_reconstruction = gate.get("maximum_reconstruction_error_mps")
    if maximum_reconstruction is not None:
        passed &= np.isfinite(reconstruction) & (reconstruction <= float(maximum_reconstruction))
    else:
        # A finite interpolant remains usable when no reconstruction cap was
        # configured; the error is still returned for downstream auditing.
        passed &= np.isfinite(reconstruction)
    return passed


def _visibility_barriers(barrier_provider: Callable[..., Any] | None, barriers: np.ndarray | None) -> np.ndarray | None:
    """Return the exact finite barriers used for interpolation visibility.

    A provider may expose ``visibility_triangle_indices`` when a closed,
    convex container component is already guaranteed to contain all solver
    samples.  Such a component cannot intersect an open segment between two
    interior samples, but it must still remain in the full collision set used
    by the swept-wall check below.  The opt-in filter therefore changes only
    an exact broad-phase shortcut, never wall-crossing classification.
    """
    if barriers is None or barrier_provider is None:
        return barriers
    indices = getattr(barrier_provider, "visibility_triangle_indices", None)
    if indices is None:
        return barriers
    indices = np.asarray(indices, dtype=np.int64).reshape(-1)
    if np.any(indices < 0) or np.any(indices >= len(barriers)):
        raise ValueError("barrier visibility indices are outside the triangle axis")
    return np.asarray(barriers)[indices]


def advect_hdf5(h5_path, initial_positions, *, neighbours=24, regularization=0.004,
                maximum_support_distance=None, frame_stride=1, substeps_per_interval=1,
                barrier_provider=None, support_gate: Mapping[str, Any] | None = None,
                velocity_interpolator: Callable[..., Any] | None = None):
    """Heun-integrate passive tracers using positions, velocities and times.

    Reliability is determined by finite velocity values, finite support
    distance, and the configured ESS/geometry/anisotropy/reconstruction gate.
    ``neighbours`` remains a candidate support-size knob and is never treated
    as a magic acceptance count.  Moving walls are checked over the full
    space-time substep through :func:`spacetime_swept_wall_blocked`.
    """
    initial_positions = np.asarray(initial_positions, dtype=np.float64)
    interpolator = (shepard_velocity_with_diagnostics
                    if velocity_interpolator is None else velocity_interpolator)
    if not callable(interpolator):
        raise TypeError("velocity_interpolator must be callable")
    gate = _normalise_support_gate(support_gate)
    if int(frame_stride) < 1:
        raise ValueError("frame_stride must be positive")
    if int(substeps_per_interval) < 1:
        raise ValueError("substeps_per_interval must be positive")
    trajectory = []
    reliable = np.ones(len(initial_positions), dtype=bool)
    support_history = []
    reliability_history = [reliable.copy()]
    visibility_history = []
    visibility_width_history = []
    wall_crossing_history = []
    effective_history = []
    rank_history = []
    anisotropy_history = []
    reconstruction_history = []
    support_gate_history = []
    visibility_mode = "no_barrier"
    with h5py.File(Path(h5_path), "r") as h5:
        frame_indices = list(range(0, len(h5["time"]), int(frame_stride)))
        if frame_indices[-1] != len(h5["time"]) - 1:
            frame_indices.append(len(h5["time"]) - 1)
        times = h5["time"][frame_indices]
        query = initial_positions.copy()
        trajectory.append(query.copy())
        for step, dt in enumerate(np.diff(times)):
            frame0, frame1 = frame_indices[step], frame_indices[step + 1]
            valid0 = h5["valid"][frame0] & (h5["type"][frame0] == 3)
            valid1 = h5["valid"][frame1] & (h5["type"][frame1] == 3)
            common = valid0 & valid1
            if not common.any():
                reliable[:] = False
                support_history.append(np.full(len(query), np.inf))
                visibility_history.append(np.zeros(len(query), dtype=np.int64))
                visibility_width_history.append(np.zeros(len(query), dtype=np.int64))
                wall_crossing_history.append(np.zeros(len(query), dtype=bool))
                effective_history.append(np.zeros(len(query), dtype=np.float64))
                rank_history.append(np.zeros(len(query), dtype=np.int8))
                anisotropy_history.append(np.zeros(len(query), dtype=np.float64))
                reconstruction_history.append(np.full(len(query), np.inf))
                support_gate_history.append(np.zeros(len(query), dtype=bool))
                trajectory.append(query.copy())
                reliability_history.append(reliable.copy())
                continue
            position0, position1 = h5["position"][frame0, common], h5["position"][frame1, common]
            velocity0, velocity1 = h5["velocity"][frame0, common], h5["velocity"][frame1, common]
            interval_support = np.zeros(len(query))
            interval_visible = np.full(len(query), np.iinfo(np.int64).max)
            interval_visibility_width = np.zeros(len(query), dtype=np.int64)
            interval_crossing = np.zeros(len(query), dtype=bool)
            interval_effective = np.full(len(query), np.inf)
            interval_rank = np.full(len(query), np.iinfo(np.int8).max, dtype=np.int8)
            interval_anisotropy = np.full(len(query), np.inf)
            interval_reconstruction = np.zeros(len(query))
            interval_gate = np.ones(len(query), dtype=bool)
            subdt = float(dt) / int(substeps_per_interval)
            for substep in range(int(substeps_per_interval)):
                alpha0 = substep / int(substeps_per_interval)
                alpha1 = (substep + 1) / int(substeps_per_interval)
                samples0 = (1 - alpha0) * position0 + alpha0 * position1
                samples1 = (1 - alpha1) * position0 + alpha1 * position1
                values0 = (1 - alpha0) * velocity0 + alpha0 * velocity1
                values1 = (1 - alpha1) * velocity0 + alpha1 * velocity1
                barriers0 = barrier_provider(h5, frame0, frame1, alpha0) if barrier_provider else None
                barriers1 = barrier_provider(h5, frame0, frame1, alpha1) if barrier_provider else None
                visibility0 = _visibility_barriers(barrier_provider, barriers0)
                visibility1 = _visibility_barriers(barrier_provider, barriers1)
                v0, support0, visible0, metrics0 = interpolator(
                    query, samples0, values0, neighbours=neighbours, regularization=regularization,
                    barrier_triangles=visibility0)
                predicted = query + np.nan_to_num(v0) * subdt
                v1, support1, visible1, metrics1 = interpolator(
                    predicted, samples1, values1, neighbours=neighbours, regularization=regularization,
                    barrier_triangles=visibility1)
                visibility_mode = str(metrics0.get("visibility_mode", metrics1.get("visibility_mode", "unknown")))
                candidate = query + 0.5 * np.nan_to_num(v0 + v1) * subdt
                crossing = spacetime_swept_wall_blocked(
                    query, candidate,
                    barriers0 if barriers0 is not None else np.empty((0, 3, 3)),
                    barriers1 if barriers1 is not None else np.empty((0, 3, 3)),
                )
                gate0 = _support_gate_pass(metrics0, gate)
                gate1 = _support_gate_pass(metrics1, gate)
                finite = np.all(np.isfinite(v0), axis=1) & np.all(np.isfinite(v1), axis=1)
                usable = finite & gate0 & gate1 & ~crossing
                query = np.where(usable[:, None], candidate, query)
                support = np.maximum(support0, support1)
                reliable &= usable
                if maximum_support_distance is not None:
                    support_ok = np.isfinite(support) & (support <= maximum_support_distance)
                    reliable &= support_ok
                else:
                    support_ok = np.isfinite(support)
                interval_gate &= gate0 & gate1 & support_ok
                interval_support = np.maximum(interval_support, support)
                interval_visible = np.minimum(interval_visible, np.minimum(visible0, visible1))
                interval_visibility_width = np.maximum(
                    interval_visibility_width,
                    np.maximum(
                        metrics0["visibility_search_width"],
                        metrics1["visibility_search_width"],
                    ),
                )
                interval_crossing |= crossing
                interval_effective = np.minimum(interval_effective, np.minimum(
                    metrics0["effective_sample_size"], metrics1["effective_sample_size"]))
                interval_rank = np.minimum(interval_rank, np.minimum(
                    metrics0["geometry_rank"], metrics1["geometry_rank"]))
                interval_anisotropy = np.minimum(interval_anisotropy, np.minimum(
                    metrics0["anisotropy"], metrics1["anisotropy"]))
                interval_reconstruction = np.maximum(interval_reconstruction, np.maximum(
                    metrics0["interpolation_reconstruction_error_mps"],
                    metrics1["interpolation_reconstruction_error_mps"]))
            support_history.append(interval_support)
            visibility_history.append(interval_visible)
            visibility_width_history.append(interval_visibility_width)
            wall_crossing_history.append(interval_crossing)
            effective_history.append(interval_effective)
            rank_history.append(interval_rank)
            anisotropy_history.append(interval_anisotropy)
            reconstruction_history.append(interval_reconstruction)
            support_gate_history.append(interval_gate)
            trajectory.append(query.copy())
            reliability_history.append(reliable.copy())
    return {
        "time": times,
        "position": np.asarray(trajectory),
        "reliable": reliable,
        "nearest_support_distance": np.asarray(support_history),
        "reliability_history": np.asarray(reliability_history),
        "minimum_visible_neighbours": np.asarray(visibility_history),
        "visibility_search_width": np.asarray(visibility_width_history),
        "visibility_mode": visibility_mode if barrier_provider is not None else "no_barrier",
        "wall_crossing": np.asarray(wall_crossing_history),
        "effective_sample_size": np.asarray(effective_history),
        "support_geometry_rank": np.asarray(rank_history),
        "support_anisotropy": np.asarray(anisotropy_history),
        "interpolation_reconstruction_error_mps": np.asarray(reconstruction_history),
        "support_gate_pass": np.asarray(support_gate_history),
        "support_gate": gate,
        "velocity_interpolator": (
            f"{getattr(interpolator, '__module__', type(interpolator).__module__)}."
            f"{getattr(interpolator, '__qualname__', type(interpolator).__qualname__)}"
        ),
        "motion_interpolation": getattr(barrier_provider, "motion_interpolation", "none")
        if barrier_provider is not None else "none",
    }


def deterministic_seeds(h5_path, maximum=256):
    """Choose reproducible initial fluid particles and retain their metadata."""
    with h5py.File(Path(h5_path), "r") as h5:
        candidates = np.flatnonzero(h5["valid"][0] & (h5["type"][0] == 3))
        if len(candidates) > maximum:
            offsets = np.linspace(0, len(candidates) - 1, maximum).round().astype(int)
            candidates = candidates[offsets]
        return {
            "indices": candidates,
            "position": h5["position"][0, candidates].astype(np.float64),
            "particle_id": h5["particle_id"][candidates],
            "particle_zone": h5["particle_zone"][candidates],
            "source_mk": h5["mk"][0, candidates],
        }


def _farthest_indices(points, count):
    if count >= len(points):
        return np.arange(len(points), dtype=int)
    center = points.mean(axis=0)
    first = int(np.argmin(np.linalg.norm(points - center, axis=1)))
    chosen = [first]
    nearest2 = np.sum((points - points[first]) ** 2, axis=1)
    for _ in range(1, count):
        next_index = int(np.argmax(nearest2))
        chosen.append(next_index)
        nearest2 = np.minimum(nearest2, np.sum((points - points[next_index]) ** 2, axis=1))
    return np.asarray(chosen, dtype=int)


def weighted_stratified_seeds(h5_path, maximum=256):
    """Select spatially spread source-stratified tracers and exact mass weights."""
    with h5py.File(Path(h5_path), "r") as h5:
        candidates = np.flatnonzero(h5["valid"][0] & (h5["type"][0] == 3))
        positions = h5["position"][0, candidates].astype(np.float64)
        masses = h5["mass"][0, candidates].astype(np.float64)
        sources = h5["mk"][0, candidates]
        unique = np.unique(sources)
        maximum = min(int(maximum), len(candidates))
        if maximum < len(unique):
            raise ValueError("maximum tracer count must cover every source stratum")
        source_mass = np.asarray([masses[sources == source].sum() for source in unique])
        raw = maximum * source_mass / source_mass.sum()
        quotas = np.maximum(1, np.floor(raw).astype(int))
        while quotas.sum() < maximum:
            residual = raw - quotas
            quotas[int(np.argmax(residual))] += 1
        while quotas.sum() > maximum:
            removable = np.where(quotas > 1, quotas - raw, -np.inf)
            quotas[int(np.argmax(removable))] -= 1
        selected_local = []
        weights = []
        for source, quota in zip(unique, quotas):
            group = np.flatnonzero(sources == source)
            chosen_in_group = _farthest_indices(positions[group], min(int(quota), len(group)))
            chosen = group[chosen_in_group]
            delta = positions[group, None, :] - positions[chosen][None, :, :]
            assignment = np.argmin(np.sum(delta * delta, axis=2), axis=1)
            group_weights = np.bincount(assignment, weights=masses[group], minlength=len(chosen))
            selected_local.extend(chosen.tolist())
            weights.extend(group_weights.tolist())
        selected_local = np.asarray(selected_local, dtype=int)
        indices = candidates[selected_local]
        return {
            "indices": indices,
            "position": positions[selected_local],
            # Farthest-point order is deliberately spatial rather than sorted;
            # index an in-memory vector because h5py fancy indices must increase.
            "particle_id": h5["particle_id"][:][indices],
            "particle_zone": h5["particle_zone"][:][indices],
            "source_mk": sources[selected_local],
            "mass_weight": np.asarray(weights, dtype=np.float64),
            "represented_initial_mass": float(np.sum(weights)),
            "selection": "source-stratified farthest-point seeds; nearest-seed mass assignment within source",
        }
