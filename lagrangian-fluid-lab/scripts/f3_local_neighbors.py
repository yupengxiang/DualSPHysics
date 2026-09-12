"""F3 v2 neighbour features: exact distances, explicit identities, stable ties.

This is a prospective engineering replacement, not bitwise legacy equivalence.
The spatial index and all features use only the complete current particle state.
CPU float64 search is intentional; outputs return to the input dtype/device.
"""
import math
import numpy as np
import torch
from scipy.spatial import cKDTree


def neighbour_indices(position, particle_id, *, neighbours=8):
    x = np.asarray(position, dtype=np.float64)
    ids = np.asarray(particle_id)
    if (x.ndim != 2 or x.shape[1] != 3 or not len(x) or not np.isfinite(x).all()
            or ids.shape != (len(x),) or ids.dtype.kind not in 'iu'
            or len(np.unique(ids)) != len(ids)):
        raise ValueError('expected finite current positions and unique integer IDs')
    if isinstance(neighbours, bool) or not isinstance(neighbours, int) or neighbours < 1:
        raise ValueError('positive integer neighbour count required')
    n = len(x); k = min(neighbours, n - 1)
    if k == 0:
        return np.empty((n, 0), dtype=np.int64), np.empty((n, 0), dtype=float)
    tree = cKDTree(x)
    # Most moving-fluid rows have no tie at the cutoff. Query one extra
    # nonself candidate, then expand only ambiguous cutoff shells.
    _, candidates = tree.query(x, k=min(n, k + 2), workers=1)
    exact = np.linalg.norm(x[candidates] - x[:, None], axis=2)
    exact[ids[candidates] == ids[:, None]] = np.inf
    ordering = np.lexsort((ids[candidates], exact), axis=1)
    sorted_pool = np.take_along_axis(candidates, ordering, axis=1)
    sorted_distance = np.take_along_axis(exact, ordering, axis=1)
    indices = sorted_pool[:, :k].copy()
    chosen_distances = sorted_distance[:, :k].copy()
    if sorted_distance.shape[1] > k:
        cutoff = sorted_distance[:, k - 1]
        tolerance = 8 * np.finfo(float).eps * np.maximum(1., cutoff)
        ambiguous = np.flatnonzero(sorted_distance[:, k] <= cutoff + tolerance)
    else:
        ambiguous = np.empty(0, dtype=int)
    for i in ambiguous:
        # Include the entire kth shell; arbitrary index-query tie ordering
        # must not change the physical neighbourhood after a shuffle.
        radius = np.nextafter(chosen_distances[i, -1], np.inf)
        radius += 8 * np.finfo(float).eps * max(1., radius)
        pool = np.asarray(tree.query_ball_point(x[i], radius, workers=1), dtype=np.int64)
        pool = pool[ids[pool] != ids[i]]
        distance = np.linalg.norm(x[pool] - x[i], axis=1)
        order = np.lexsort((ids[pool], distance))[:k]
        if len(order) != k:
            raise ValueError('spatial index did not return complete neighbour shell')
        indices[i] = pool[order]
        chosen_distances[i] = distance[order]
    return indices, chosen_distances


def exact_local_summary(position, velocity, particle_id, *, dp_m, interval_s):
    if (not isinstance(position, torch.Tensor) or not isinstance(velocity, torch.Tensor)
            or position.shape != velocity.shape or position.dtype != velocity.dtype
            or position.device != velocity.device or not position.is_floating_point()
            or not math.isfinite(dp_m) or dp_m <= 0
            or not math.isfinite(interval_s) or interval_s <= 0):
        raise ValueError('invalid current state, resolution or interval')
    x = position.detach().cpu().numpy().astype(np.float64)
    v = velocity.detach().cpu().numpy().astype(np.float64)
    if not np.isfinite(v).all():
        raise ValueError('nonfinite current velocity')
    index, distance = neighbour_indices(x, particle_id)
    n, k = index.shape
    result = np.zeros((n, 8), dtype=np.float64)
    if k:
        weight = 1 / np.maximum(distance, 1e-5)
        weight /= weight.sum(axis=1, keepdims=True)
        result[:, :3] = np.sum(weight[..., None] * (x[index] - x[:, None]), axis=1) / dp_m
        result[:, 3:6] = np.sum(weight[..., None] * (v[index] - v[:, None]), axis=1) * interval_s / dp_m
        result[:, 6] = distance.mean(axis=1) / dp_m
        result[:, 7] = k / n
    return torch.as_tensor(result, dtype=position.dtype, device=position.device)
