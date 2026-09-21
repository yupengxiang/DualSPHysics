#!/usr/bin/env python3
"""One bounded F4 reconstruction-query repair candidate.

The native trajectory is Lagrangian: each saved velocity belongs to the
particle position at the same saved frame.  The baseline provider linearly
blends both positions and velocities before constructing a spatial query.  In
the retained frame-40 -> frame-41 interval that creates a synthetic mixed
velocity field at the evolving interface and is the direct source of the
reconstruction-gate loss.

This candidate keeps the baseline visible cKDTree, nearest-24 support,
Shepard weights, all support gates, the error cap, and the full seed
denominator.  It changes one implementation detail only: positions remain
linearly interpolated for the interval geometry, while the native velocity is
held at the interval-start frame (a causal zero-order hold).  A new saved
frame starts a new held interval.  This is a bounded implementation
hypothesis, not a qualification result.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from scripts import core_material as cm
from scripts import f4_tallwall120_material as tw


CANDIDATE_ID = "f4_native_velocity_zoh_query_v1"
REVISION_ID = "F4_tallwall120_material_velocity_zoh_query_v1"
MATERIAL_RECIPE_ID = "F4_tallwall120_material_overlay_velocity_zoh_query_v1"
TEMPORAL_INTERPOLATION = "linear_native_position_interval_start_velocity_zoh"
PATH_INTERPOLATION = (
    "native support particle positions are linearly interpolated between the "
    "two registered reference frames; interval-start native velocity is held "
    "for the causal query; the independent tracer path is integrated by RK2 substeps"
)


class HeldVelocityReferenceFrames(cm.ReferenceFrames):
    """Reference provider with a causal interval-start velocity hold.

    The provider still opens only the two native frames bracketing the current
    query, and positions follow the baseline linear Lagrangian interpolation.
    No future trajectory, density, or solver state is materialized.
    """

    temporal_interpolation = TEMPORAL_INTERPOLATION
    path_interpolation = PATH_INTERPOLATION
    candidate_id = CANDIDATE_ID
    revision_id = REVISION_ID
    material_recipe_id = MATERIAL_RECIPE_ID
    implementation_path = Path(__file__).resolve()

    def field(self, index, alpha=0.0):
        index = self._check_index(index)
        if not np.isfinite(alpha) or not 0.0 <= alpha <= 1.0:
            raise ValueError("interpolation alpha must be in [0,1]")
        first = self.frame(index)
        if alpha == 0.0:
            return cm.CurrentField(first[0], first[1], first[2])
        if index + 1 >= len(self.times):
            raise IndexError("future bracket is unavailable at the last frame")
        second = self.frame(index + 1)
        common = first[2] & second[2]
        position = (1.0 - float(alpha)) * first[0] + float(alpha) * second[0]
        # The saved velocity is a native Lagrangian field value.  Hold the
        # interval-start value instead of blending it at a spatially moved
        # support point; this is the sole candidate change.
        return cm.CurrentField(position, first[1], common)


def trace_repair(source, output, *, q=0.5, dp_m=0.0075, seeds=512,
                 substeps=2, stop_after=41, resume=False, kill_after=None):
    """Run the candidate through the existing bounded tall-wall overlay."""
    provider = HeldVelocityReferenceFrames(Path(source).resolve(), fluid_type=3)
    try:
        return tw.trace_tallwall120(
            Path(source).resolve(),
            Path(output).resolve(),
            q=q,
            dp_m=dp_m,
            seeds=seeds,
            substeps=substeps,
            stop_after=stop_after,
            resume=resume,
            kill_after=kill_after,
            provider=provider,
        )
    finally:
        provider.close()


def candidate_contract() -> dict:
    """Return the immutable candidate contract for preflight/evidence."""
    return {
        "candidate_id": CANDIDATE_ID,
        "revision_id": REVISION_ID,
        "material_recipe_id": MATERIAL_RECIPE_ID,
        "temporal_interpolation": TEMPORAL_INTERPOLATION,
        "neighbour_variant": "baseline24",
        "neighbours": tw.NEIGHBOURS,
        "error_estimator": "local_residual",
        "regularization_m": tw.REGULARIZATION_M,
        "maximum_support_distance_m": tw.MAXIMUM_SUPPORT_DISTANCE_M,
        "support_gate": dict(tw.GATE),
        "unknown_denominator": "all 512 independent source seeds",
        "event_semantics": "baseline tallwall120 definition unchanged",
        "qualification_claim": "none",
    }


__all__ = [
    "CANDIDATE_ID",
    "REVISION_ID",
    "MATERIAL_RECIPE_ID",
    "TEMPORAL_INTERPOLATION",
    "HeldVelocityReferenceFrames",
    "candidate_contract",
    "trace_repair",
]
