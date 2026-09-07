#!/usr/bin/env python3
"""Independent passive tracers advanced through exported SPH velocity samples."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


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
    visible = np.ones((len(query), len(particle_position)), dtype=bool)
    if triangles.size == 0:
        return visible
    origins = query[:, None, :]
    direction = particle_position[None, :, :] - origins
    for triangle in triangles.reshape(-1, 3, 3):
        vertex, edge1, edge2 = triangle[0], triangle[1] - triangle[0], triangle[2] - triangle[0]
        h = np.cross(direction, edge2)
        determinant = np.einsum("...i,i->...", h, edge1)
        nonparallel = np.abs(determinant) > epsilon
        inverse = np.zeros_like(determinant)
        inverse[nonparallel] = 1.0 / determinant[nonparallel]
        offset = origins - vertex
        u = inverse * np.einsum("...i,...i->...", offset, h)
        qvec = np.cross(offset, edge1)
        v = inverse * np.einsum("...i,...i->...", direction, qvec)
        distance = inverse * np.einsum("...i,i->...", qvec, edge2)
        blocked = nonparallel & (u >= -epsilon) & (v >= -epsilon) & (u + v <= 1 + epsilon)
        blocked &= (distance > epsilon) & (distance < 1 - epsilon)
        visible &= ~blocked
    return visible


def corresponding_segments_blocked(start, end, barrier_triangles, *, epsilon=1e-9):
    """Check Q corresponding start/end segments against finite triangles."""
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
        hit &= (distance > epsilon) & (distance < 1 - epsilon)
        blocked |= hit
    return blocked


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
    transform = np.asarray(transform, dtype=np.float64)
    homogeneous = np.concatenate((triangles, np.ones((*triangles.shape[:-1], 1))), axis=-1)
    return (homogeneous @ transform.T)[..., :3]


def rigid_barrier_provider(transform_dataset, body_triangles, static_triangles=()):
    """Create an advector callback for linearly interpolated moving triangles."""
    body_triangles = np.asarray(body_triangles, dtype=np.float64).reshape(-1, 3, 3)
    static_triangles = np.asarray(static_triangles, dtype=np.float64).reshape(-1, 3, 3)

    def provider(h5, frame0, frame1, alpha):
        first = transform_triangles(body_triangles, h5[transform_dataset][frame0])
        second = transform_triangles(body_triangles, h5[transform_dataset][frame1])
        moving = (1 - alpha) * first + alpha * second
        return np.concatenate((moving, static_triangles), axis=0)

    return provider


def shepard_velocity(query, particle_position, particle_velocity, *, neighbours=24,
                     regularization=0.004, chunk_size=128, barrier_triangles=None,
                     return_diagnostics=False):
    """Interpolate velocity without using SPH particle identity.

    This intentionally uses a generic inverse-distance Shepard interpolant rather
    than DualSPHysics kernel internals, making the tracer integration an
    independent check of exported trajectories rather than an Idp lookup.
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
    epsilon2 = float(regularization) ** 2
    for start in range(0, len(query), chunk_size):
        stop = min(start + chunk_size, len(query))
        delta = query[start:stop, None, :] - particle_position[None, :, :]
        distance2 = np.einsum("qpi,qpi->qp", delta, delta)
        if barrier_triangles is not None:
            visible = segment_visibility(query[start:stop], particle_position, barrier_triangles)
            distance2[~visible] = np.inf
            visible_neighbours[start:stop] = visible.sum(axis=1)
        else:
            visible_neighbours[start:stop] = len(particle_position)
        selected = np.argpartition(distance2, k - 1, axis=1)[:, :k]
        selected_distance2 = np.take_along_axis(distance2, selected, axis=1)
        weights = np.where(np.isfinite(selected_distance2), 1.0 / (selected_distance2 + epsilon2), 0.0)
        selected_velocity = particle_velocity[selected]
        denominator = weights.sum(axis=1)
        numerator = np.sum(weights[..., None] * selected_velocity, axis=1)
        result[start:stop] = np.divide(numerator, denominator[:, None], out=np.full_like(numerator, np.nan), where=denominator[:, None] > 0)
        support[start:stop] = np.sqrt(selected_distance2.min(axis=1))
    if return_diagnostics:
        return result, support, visible_neighbours
    return result, support


def advect_hdf5(h5_path, initial_positions, *, neighbours=24, regularization=0.004,
                maximum_support_distance=None, frame_stride=1, substeps_per_interval=1,
                barrier_provider=None):
    """Heun-integrate passive tracers using only positions, velocities and times."""
    initial_positions = np.asarray(initial_positions, dtype=np.float64)
    trajectory = []
    reliable = np.ones(len(initial_positions), dtype=bool)
    support_history = []
    reliability_history = [reliable.copy()]
    visibility_history = []
    wall_crossing_history = []
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
                wall_crossing_history.append(np.zeros(len(query), dtype=bool))
                trajectory.append(query.copy())
                reliability_history.append(reliable.copy())
                continue
            position0, position1 = h5["position"][frame0, common], h5["position"][frame1, common]
            velocity0, velocity1 = h5["velocity"][frame0, common], h5["velocity"][frame1, common]
            interval_support = np.zeros(len(query))
            interval_visible = np.full(len(query), np.iinfo(np.int64).max)
            interval_crossing = np.zeros(len(query), dtype=bool)
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
                v0, support0, visible0 = shepard_velocity(
                    query, samples0, values0, neighbours=neighbours, regularization=regularization,
                    barrier_triangles=barriers0, return_diagnostics=True)
                predicted = query + np.nan_to_num(v0) * subdt
                v1, support1, visible1 = shepard_velocity(
                    predicted, samples1, values1, neighbours=neighbours, regularization=regularization,
                    barrier_triangles=barriers1, return_diagnostics=True)
                candidate = query + 0.5 * np.nan_to_num(v0 + v1) * subdt
                barriers_mid = barrier_provider(h5, frame0, frame1, 0.5 * (alpha0 + alpha1)) if barrier_provider else np.empty((0, 3, 3))
                crossing = corresponding_segments_blocked(query, candidate, barriers_mid)
                finite = np.all(np.isfinite(v0), axis=1) & np.all(np.isfinite(v1), axis=1)
                query = np.where((finite & ~crossing)[:, None], candidate, query)
                support = np.maximum(support0, support1)
                reliable &= finite & ~crossing
                if maximum_support_distance is not None:
                    reliable &= support <= maximum_support_distance
                interval_support = np.maximum(interval_support, support)
                interval_visible = np.minimum(interval_visible, np.minimum(visible0, visible1))
                interval_crossing |= crossing
            support_history.append(interval_support)
            visibility_history.append(interval_visible)
            wall_crossing_history.append(interval_crossing)
            trajectory.append(query.copy())
            reliability_history.append(reliable.copy())
    return {
        "time": times,
        "position": np.asarray(trajectory),
        "reliable": reliable,
        "nearest_support_distance": np.asarray(support_history),
        "reliability_history": np.asarray(reliability_history),
        "minimum_visible_neighbours": np.asarray(visibility_history),
        "wall_crossing": np.asarray(wall_crossing_history),
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
