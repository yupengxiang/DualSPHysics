"""CPU Shepard interpolation with exact finite-wall visible-neighbour search.

This is an injectable implementation, not an advection or calibration runner.
It preserves the Shepard weights, support metrics and open finite-triangle
visibility from ``passive_tracers``. Its prospective cutoff tie rule is squared
float64 distance, then original sample row. Historical ``np.argpartition`` and
Torch top-k do not promise that rule; this is not bitwise legacy equivalence.
Four manufactured calibration configurations must bind this implementation
before an outer driver uses it for qualified material results.

An index is built from the complete current sample frame. For each query the
candidate width doubles until k visible samples are found or all samples have
been tested. Every candidate cutoff shell is completed before selecting the
nearest visible support. All cKDTree operations explicitly use one CPU worker.
No sample identity, learned 8-NN features, support filtering or trajectory
update is involved. An unsupported query stays in the output with NaN velocity.

Search diagnostics describe this backend, not legacy chunk-wide work:
``visibility_search_width`` is the final candidate pool size for each query;
with barriers, ``visible_neighbours`` counts visible samples in that pool,
and is only a total for the frame when the pool is exhaustive. Without barriers
the full frame is known to be visible without testing every segment.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from scripts.passive_tracers import _support_metrics, segment_visibility


BACKEND = 'f3_ckdtree_visible_shepard_cpu1_v1'
TIE_RULE = 'float64_squared_euclidean_distance_then_original_sample_row'
_DISTANCE_MARGIN = 16 * np.finfo(np.float64).eps


def _positive_integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f'{name} must be a positive integer')
    return int(value)


def _arrays(query, particle_position, particle_velocity, barrier_triangles):
    query, position, velocity = (np.asarray(a, dtype=np.float64)
                                 for a in (query, particle_position, particle_velocity))
    if position.ndim != 2 or position.shape[1:] != (3,):
        raise ValueError('particle_position must have shape [N,3]')
    if not len(position):
        raise ValueError('cannot interpolate an empty particle frame')
    if query.ndim != 2 or query.shape[1:] != (3,) or velocity.shape != position.shape:
        raise ValueError('expected query [Q,3] and matching particle velocity [N,3]')
    if not all(np.isfinite(a).all() for a in (query, position, velocity)):
        raise ValueError('nonfinite query or particle data; no samples are silently removed')
    triangles = np.empty((0, 3, 3)) if barrier_triangles is None else np.asarray(barrier_triangles, dtype=np.float64)
    if triangles.size == 0:
        triangles = np.empty((0, 3, 3))
    elif triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not np.isfinite(triangles).all():
        raise ValueError('finite barrier_triangles with shape [T,3,3] required')
    return query, position, velocity, triangles


def _candidate_pools(tree, query, position, width):
    """Complete the geometric cutoff shell; the margin cannot change the top-k.

    cKDTree's returned distances are not used as Shepard weights. We recompute
    squared distances in float64, enlarge the search radius to include possible
    roundoff at its boundary, then sort the resulting support by exact computed
    squared distance and row. Including slightly farther candidates is harmless.
    """
    if width == len(position):
        all_rows = np.arange(width, dtype=np.int64)
        return [all_rows] * len(query)
    _, index = tree.query(query, k=width, eps=0., p=2., workers=1)
    index = np.asarray(index, dtype=np.int64).reshape(len(query), width)
    if np.any(index >= len(position)):
        raise ValueError('nonfinite Euclidean distance from finite input coordinates')
    delta = query[:, None, :] - position[index]
    with np.errstate(over='ignore', invalid='ignore'):
        distance2 = np.einsum('qki,qki->qk', delta, delta)
    if not np.isfinite(distance2).all():
        raise ValueError('squared Euclidean distance overflow')
    radius = np.sqrt(distance2.max(axis=1))
    radius = np.nextafter(radius, np.inf) + _DISTANCE_MARGIN * np.maximum(1., radius)
    pools = tree.query_ball_point(query, r=radius, p=2., eps=0., workers=1, return_sorted=False)
    result = [np.asarray(pool, dtype=np.int64) for pool in pools]
    if any(len(pool) < width for pool in result):
        raise ValueError('spatial index did not return a complete candidate cutoff shell')
    return result


def _visible_support(tree, query, position, triangles, k):
    count, n = len(query), len(position)
    selected = np.empty((count, k), dtype=np.int64)
    selected_distance2 = np.empty((count, k), dtype=np.float64)
    visible_count = np.empty(count, dtype=np.int64)
    search_width = np.empty(count, dtype=np.int64)
    exhaustive = np.empty(count, dtype=bool)
    active = np.arange(count, dtype=np.int64)
    width = min(4 * k if len(triangles) else k, n)
    while len(active):
        pools = _candidate_pools(tree, query[active], position, width)
        sizes = np.asarray([len(pool) for pool in pools], dtype=np.int64)
        unresolved = np.zeros(len(active), dtype=bool)
        # Most pools have one width. Grouping avoids padding a small support to
        # a different query's unusually large tie shell, and batches visibility.
        for size in np.unique(sizes):
            local = np.flatnonzero(sizes == size)
            rows = active[local]
            pool = np.stack([pools[i] for i in local])
            delta = query[rows, None, :] - position[pool]
            with np.errstate(over='ignore', invalid='ignore'):
                distance2 = np.einsum('qki,qki->qk', delta, delta)
            if not np.isfinite(distance2).all():
                raise ValueError('squared Euclidean distance overflow')
            visible = (segment_visibility(query[rows], position[pool], triangles)
                       if len(triangles) else np.ones(pool.shape, dtype=bool))
            found = visible.sum(axis=1)
            ready = (found >= k) | (size == n)
            unresolved[local[~ready]] = True
            if not ready.any():
                continue
            done = rows[ready]
            key = np.where(visible[ready], distance2[ready], np.inf)
            ordering = np.lexsort((pool[ready], key), axis=1)[:, :k]
            selected[done] = np.take_along_axis(pool[ready], ordering, axis=1)
            selected_distance2[done] = np.take_along_axis(key, ordering, axis=1)
            visible_count[done] = found[ready] if len(triangles) else n
            search_width[done] = size
            exhaustive[done] = size == n
        active = active[unresolved]
        width = min(2 * width, n)
    return selected, selected_distance2, visible_count, search_width, exhaustive


def shepard_velocity_with_diagnostics(query, particle_position, particle_velocity, *, neighbours=24,
                                      regularization=0.004, chunk_size=128, barrier_triangles=None):
    """Return velocity, nearest support distance, visible count and diagnostics.

    Signature and support-quality fields match the passive-tracer interpolator.
    Weights are 1 / (distance² + regularization²); default regularization is
    0.004 m. The returned support distance is the nearest visible sample's
    distance, not the farthest selected distance. Gates remain caller-owned and
    can consume these unchanged ESS/rank/anisotropy/reconstruction fields.
    Empty sample frames fail; empty query arrays retain shape [0,3].
    """
    query, position, velocity, triangles = _arrays(query, particle_position, particle_velocity, barrier_triangles)
    neighbours = _positive_integer(neighbours, 'neighbours')
    chunk_size = _positive_integer(chunk_size, 'chunk_size')
    if not math.isfinite(regularization) or regularization <= 0:
        raise ValueError('positive finite regularization required')
    epsilon2 = float(regularization) * float(regularization)
    if not math.isfinite(epsilon2) or epsilon2 == 0:
        raise ValueError('regularization squared must be positive and finite')
    k = min(neighbours, len(position))
    result = np.empty_like(query)
    support = np.empty(len(query), dtype=np.float64)
    visible = np.empty(len(query), dtype=np.int64)
    width = np.empty(len(query), dtype=np.int64)
    exhaustive = np.empty(len(query), dtype=bool)
    effective = np.empty(len(query), dtype=np.float64)
    rank = np.empty(len(query), dtype=np.int8)
    anisotropy = np.empty(len(query), dtype=np.float64)
    reconstruction = np.empty(len(query), dtype=np.float64)
    selected_count = np.empty(len(query), dtype=np.int64)
    tree = cKDTree(position) if len(query) else None
    for start in range(0, len(query), chunk_size):
        stop = min(start + chunk_size, len(query))
        selected, distance2, visible[start:stop], width[start:stop], exhaustive[start:stop] = _visible_support(
            tree, query[start:stop], position, triangles, k)
        weights = np.where(np.isfinite(distance2), 1. / (distance2 + epsilon2), 0.)
        denominator = weights.sum(axis=1)
        numerator = np.sum(weights[..., None] * velocity[selected], axis=1)
        result[start:stop] = np.divide(numerator, denominator[:, None],
                                       out=np.full_like(numerator, np.nan), where=denominator[:, None] > 0)
        support[start:stop] = np.sqrt(distance2.min(axis=1))
        selected_count[start:stop] = np.isfinite(distance2).sum(axis=1)
        metrics = _support_metrics(query[start:stop], position, velocity, selected, distance2, weights)
        effective[start:stop] = metrics['effective_sample_size']
        rank[start:stop] = metrics['geometry_rank']
        anisotropy[start:stop] = metrics['anisotropy']
        reconstruction[start:stop] = metrics['interpolation_reconstruction_error']
    diagnostics = dict(
        effective_sample_size=effective, geometry_rank=rank, anisotropy=anisotropy,
        interpolation_reconstruction_error_mps=reconstruction, visible_neighbours=visible,
        support_distance=support, visibility_search_width=width,
        visibility_mode=f'{BACKEND}_finite_barrier' if len(triangles) else f'{BACKEND}_no_barrier',
        neighbour_tie_rule=TIE_RULE, visibility_search_exhaustive=exhaustive,
        selected_visible_neighbours=selected_count,
    )
    return result, support, visible, diagnostics
