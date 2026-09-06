#!/usr/bin/env python3
"""Independent passive tracers advanced through exported SPH velocity samples."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


def shepard_velocity(query, particle_position, particle_velocity, *, neighbours=24,
                     regularization=0.004, chunk_size=128):
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
    epsilon2 = float(regularization) ** 2
    for start in range(0, len(query), chunk_size):
        stop = min(start + chunk_size, len(query))
        delta = query[start:stop, None, :] - particle_position[None, :, :]
        distance2 = np.einsum("qpi,qpi->qp", delta, delta)
        selected = np.argpartition(distance2, k - 1, axis=1)[:, :k]
        selected_distance2 = np.take_along_axis(distance2, selected, axis=1)
        weights = 1.0 / (selected_distance2 + epsilon2)
        selected_velocity = particle_velocity[selected]
        result[start:stop] = np.sum(weights[..., None] * selected_velocity, axis=1) / weights.sum(axis=1)[:, None]
        support[start:stop] = np.sqrt(selected_distance2.min(axis=1))
    return result, support


def advect_hdf5(h5_path, initial_positions, *, neighbours=24, regularization=0.004,
                maximum_support_distance=None, frame_stride=1):
    """Heun-integrate passive tracers using only positions, velocities and times."""
    initial_positions = np.asarray(initial_positions, dtype=np.float64)
    trajectory = []
    reliable = np.ones(len(initial_positions), dtype=bool)
    support_history = []
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
            v0, support0 = shepard_velocity(
                query, h5["position"][frame0, valid0], h5["velocity"][frame0, valid0],
                neighbours=neighbours, regularization=regularization)
            predicted = query + v0 * dt
            v1, support1 = shepard_velocity(
                predicted, h5["position"][frame1, valid1], h5["velocity"][frame1, valid1],
                neighbours=neighbours, regularization=regularization)
            query = query + 0.5 * (v0 + v1) * dt
            support = np.maximum(support0, support1)
            if maximum_support_distance is not None:
                reliable &= support <= maximum_support_distance
            support_history.append(support)
            trajectory.append(query.copy())
    return {
        "time": times,
        "position": np.asarray(trajectory),
        "reliable": reliable,
        "nearest_support_distance": np.asarray(support_history),
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
