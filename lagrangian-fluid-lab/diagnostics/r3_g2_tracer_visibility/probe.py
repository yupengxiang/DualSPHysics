#!/usr/bin/env python3
"""Adversarial, CFD-free visibility probes for the independent tracer.

The probes in this directory deliberately exercise only the exported-field
interpolator.  They do not run DualSPHysics and do not alter the production
``scripts.passive_tracers`` implementation.  Each case compares the current
24-neighbour inverse-distance result with the same result using the existing
finite-triangle visibility filter.

The final case is intentionally a limitation probe: two disconnected liquid
blobs have no solid triangle between them.  Geometry-only line-of-sight cannot
infer that the blobs are separate, so the wall-aware path is expected to be
identical to the legacy path.  A region-label gate is included as an explicit
candidate-only oracle, not as a production change.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

try:
    from scripts.passive_tracers import segment_visibility, shepard_velocity
except ModuleNotFoundError:  # direct invocation from the repository root
    _LAB = Path(__file__).resolve().parents[2]
    if str(_LAB) not in sys.path:
        sys.path.insert(0, str(_LAB))
    from scripts.passive_tracers import segment_visibility, shepard_velocity


LAB = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-g2-tracer-visibility.json"
DEFAULT_MARKDOWN = LAB / "campaigns" / "v0.1-candidate" / "R3-G2-TRACER-VISIBILITY.md"

NEIGHBOURS = 24
REGULARIZATION_M = 0.004
DP_M = 0.04
EPSILON = 1e-9


def _wall_plane(x: float, y0: float, y1: float, z0: float, z1: float) -> np.ndarray:
    """Return two finite triangles covering a rectangular plane patch."""
    quad = np.asarray(
        [[x, y0, z0], [x, y1, z0], [x, y1, z1], [x, y0, z1]],
        dtype=np.float64,
    )
    return quad[[[0, 1, 2], [0, 2, 3]]]


def _partition_case() -> dict[str, Any]:
    """A sparse left side and dense right side separated by a wall.

    Both sides carry a tangential velocity, but the right side has the
    opposite sign.  The deliberately asymmetric support makes the current
    24-neighbour selection choose mostly right-side samples for a left query.
    """
    y_left = np.asarray([-0.12, -0.04, 0.04, 0.12])
    z_left = np.asarray([-0.04, 0.04])
    yy, zz = np.meshgrid(y_left, z_left)
    left = np.column_stack((np.full(yy.size, -0.010), yy.ravel(), zz.ravel()))

    y_right = np.linspace(-0.12, 0.12, 7)
    yy, zz = np.meshgrid(y_right, y_right)
    right = np.column_stack((np.full(yy.size, 0.008), yy.ravel(), zz.ravel()))

    positions = np.vstack((left, right))
    velocities = np.vstack((
        np.tile([0.0, 1.0, 0.0], (len(left), 1)),
        np.tile([0.0, -1.0, 0.0], (len(right), 1)),
    ))
    queries = np.column_stack((
        np.full(16, -0.002),
        np.linspace(-0.06, 0.06, 16),
        np.zeros(16),
    ))
    return {
        "case_id": "partition_tangential_flow",
        "description": "finite x=0 partition; left/right tangential fields have opposite signs",
        "positions": positions,
        "velocities": velocities,
        "queries": queries,
        "truth": np.tile([0.0, 1.0, 0.0], (len(queries), 1)),
        "contaminant": np.r_[np.zeros(len(left), dtype=bool), np.ones(len(right), dtype=bool)],
        "region_labels": np.r_[np.full(len(left), "left"), np.full(len(right), "right")],
        "query_region_labels": np.full(len(queries), "left"),
        "barriers": _wall_plane(0.0, -0.20, 0.20, -0.20, 0.20),
        "geometry": {
            "type": "finite_partition",
            "plane_x_m": 0.0,
            "extent_y_m": [-0.20, 0.20],
            "extent_z_m": [-0.20, 0.20],
        },
    }


def _narrow_gap_case() -> dict[str, Any]:
    """A wall with a narrow y opening, near-wall blocked samples, and gap samples."""
    wall = np.vstack((
        _wall_plane(0.0, -0.20, -0.02, -0.10, 0.10),
        _wall_plane(0.0, 0.02, 0.20, -0.10, 0.10),
    ))

    y_left = np.asarray([0.045, 0.055, 0.065, 0.075])
    z_left = np.asarray([-0.045, 0.045])
    yy, zz = np.meshgrid(y_left, z_left)
    left = np.column_stack((np.full(yy.size, -0.010), yy.ravel(), zz.ravel()))

    # These are geometrically close, but every segment from the query to them
    # crosses the upper wall panel rather than the opening.
    y_blocked = y_left
    z_blocked = np.asarray([-0.06, -0.03, 0.0, 0.03, 0.06])
    yy, zz = np.meshgrid(y_blocked, z_blocked)
    blocked_right = np.column_stack((np.full(yy.size, 0.010), yy.ravel(), zz.ravel()))

    # These samples are farther away in y, but their segments cross x=0 inside
    # the real opening [-0.02, 0.02] and must remain visible.
    y_gap = np.asarray([-0.06, -0.05, -0.04])
    yy, zz = np.meshgrid(y_gap, z_blocked)
    gap_right = np.column_stack((np.full(yy.size, 0.010), yy.ravel(), zz.ravel()))

    positions = np.vstack((left, blocked_right, gap_right))
    velocities = np.vstack((
        np.tile([0.0, 1.0, 0.0], (len(left), 1)),
        np.tile([0.0, -2.0, 0.0], (len(blocked_right), 1)),
        np.tile([0.0, 1.0, 0.0], (len(gap_right), 1)),
    ))
    queries = np.column_stack((
        np.full(3, -0.015),
        np.full(3, 0.055),
        np.asarray([-0.02, 0.0, 0.02]),
    ))
    return {
        "case_id": "narrow_gap_visibility",
        "description": "two finite wall panels leave a narrow opening; near samples are blocked but gap rays are valid",
        "positions": positions,
        "velocities": velocities,
        "queries": queries,
        "truth": np.tile([0.0, 1.0, 0.0], (len(queries), 1)),
        "contaminant": np.r_[
            np.zeros(len(left), dtype=bool),
            np.ones(len(blocked_right), dtype=bool),
            np.zeros(len(gap_right), dtype=bool),
        ],
        "region_labels": np.r_[
            np.full(len(left), "left"),
            np.full(len(blocked_right), "blocked_right"),
            np.full(len(gap_right), "gap_right"),
        ],
        "query_region_labels": np.full(len(queries), "left"),
        "barriers": wall,
        "gap_sample_mask": np.r_[
            np.zeros(len(left), dtype=bool),
            np.zeros(len(blocked_right), dtype=bool),
            np.ones(len(gap_right), dtype=bool),
        ],
        "blocked_sample_mask": np.r_[
            np.zeros(len(left), dtype=bool),
            np.ones(len(blocked_right), dtype=bool),
            np.zeros(len(gap_right), dtype=bool),
        ],
        "geometry": {
            "type": "finite_partition_with_gap",
            "plane_x_m": 0.0,
            "wall_y_ranges_m": [[-0.20, -0.02], [0.02, 0.20]],
            "open_gap_y_range_m": [-0.02, 0.02],
        },
    }


def _separated_blob_case() -> dict[str, Any]:
    """Two compact liquid blobs separated by vacuum and no solid geometry."""
    axis = np.asarray([-0.02, 0.02])
    xx, yy, zz = np.meshgrid(axis, axis, axis)
    left = np.column_stack(((-0.06 + xx).ravel(), yy.ravel(), zz.ravel()))

    axis_dense = np.linspace(-0.05, 0.05, 5)
    xx, yy, zz = np.meshgrid(axis_dense, axis_dense, axis_dense)
    right = np.column_stack(((0.02 + xx).ravel(), yy.ravel(), zz.ravel()))

    positions = np.vstack((left, right))
    velocities = np.vstack((
        np.tile([0.0, 1.0, 0.0], (len(left), 1)),
        np.tile([0.0, -1.0, 0.0], (len(right), 1)),
    ))
    queries = np.asarray([
        [-0.045, 0.00, 0.00],
        [-0.045, 0.01, 0.00],
        [-0.045, -0.01, 0.01],
    ])
    return {
        "case_id": "separated_liquid_blob",
        "description": "two disconnected liquid blobs separated by a 0.01 m vacuum gap and no triangle barrier",
        "positions": positions,
        "velocities": velocities,
        "queries": queries,
        "truth": np.tile([0.0, 1.0, 0.0], (len(queries), 1)),
        "contaminant": np.r_[np.zeros(len(left), dtype=bool), np.ones(len(right), dtype=bool)],
        "region_labels": np.r_[np.full(len(left), "left_blob"), np.full(len(right), "right_blob")],
        "query_region_labels": np.full(len(queries), "left_blob"),
        "barriers": np.empty((0, 3, 3), dtype=np.float64),
        "geometry": {
            "type": "disconnected_liquid_blobs",
            "solid_barrier": False,
            "left_x_range_m": [-0.08, -0.04],
            "right_x_range_m": [-0.03, 0.07],
            "vacuum_gap_m": 0.01,
        },
    }


CASE_BUILDERS = (_partition_case, _narrow_gap_case, _separated_blob_case)


def _selection(
    query: np.ndarray,
    positions: np.ndarray,
    *,
    neighbours: int = NEIGHBOURS,
    regularization: float = REGULARIZATION_M,
    barriers: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mirror current Shepard selection to expose side/weight diagnostics."""
    query = np.asarray(query, dtype=np.float64)
    positions = np.asarray(positions, dtype=np.float64)
    distance2 = np.sum((positions - query[None, :]) ** 2, axis=1)
    visible = np.ones(len(positions), dtype=bool)
    if barriers is not None:
        visible = segment_visibility(query[None, :], positions, barriers)[0]
        distance2[~visible] = np.inf
    k = min(int(neighbours), len(positions))
    selected = np.argpartition(distance2, k - 1)[:k]
    selected_distance2 = distance2[selected]
    weights = np.where(
        np.isfinite(selected_distance2),
        1.0 / (selected_distance2 + float(regularization) ** 2),
        0.0,
    )
    return selected, weights, visible


def _stats(values: np.ndarray) -> dict[str, float | int | None]:
    values = np.asarray(values, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if not len(finite):
        return {"mean": None, "median": None, "max": None, "min": None}
    return {
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "max": float(np.max(finite)),
        "min": float(np.min(finite)),
    }


def _velocity_mean(values: np.ndarray) -> list[float | None]:
    values = np.asarray(values, dtype=np.float64)
    finite = np.all(np.isfinite(values), axis=1)
    if not finite.any():
        return [None, None, None]
    return [float(value) for value in np.mean(values[finite], axis=0)]


def summarize_interpolant(
    case: dict[str, Any],
    *,
    barriers: np.ndarray | None,
    neighbours: int = NEIGHBOURS,
    regularization: float = REGULARIZATION_M,
) -> dict[str, Any]:
    """Summarize output, support, selected sides, and contaminant weights."""
    queries = case["queries"]
    positions = case["positions"]
    velocities = case["velocities"]
    truth = case["truth"]
    contaminant = np.asarray(case["contaminant"], dtype=bool)
    output, support, visible_count = shepard_velocity(
        queries,
        positions,
        velocities,
        neighbours=neighbours,
        regularization=regularization,
        barrier_triangles=barriers,
        return_diagnostics=True,
    )

    contaminant_weights: list[float] = []
    contaminant_counts: list[float] = []
    selected_counts: list[int] = []
    eligible_counts: list[int] = []
    rows: list[dict[str, Any]] = []
    for query, value, support_value in zip(queries, output, support):
        selected, weights, visible = _selection(
            query, positions, neighbours=neighbours,
            regularization=regularization, barriers=barriers,
        )
        finite = weights > 0
        denominator = float(np.sum(weights))
        weight_fraction = float(
            np.sum(weights[contaminant[selected]]) / denominator
        ) if denominator > 0 else 0.0
        selected_count = int(np.sum(finite))
        contaminant_count = int(np.sum(contaminant[selected] & finite))
        count_fraction = contaminant_count / selected_count if selected_count else 0.0
        contaminant_weights.append(weight_fraction)
        contaminant_counts.append(count_fraction)
        selected_counts.append(selected_count)
        eligible_counts.append(int(np.sum(visible)))
        rows.append({
            "contaminant_weight_fraction": weight_fraction,
            "contaminant_selected_fraction": float(count_fraction),
            "selected_finite_count": selected_count,
            "eligible_visible_count": int(np.sum(visible)),
            "support_distance_m": float(support_value) if np.isfinite(support_value) else None,
            "velocity_mps": [float(component) for component in value]
            if np.all(np.isfinite(value)) else [None, None, None],
        })

    finite_output = np.all(np.isfinite(output), axis=1)
    error = np.linalg.norm(output - truth, axis=1)
    finite_error = error[finite_output]
    truth_tangent = truth[:, 1]
    wrong_direction = finite_output & (output[:, 1] * truth_tangent < 0)
    return {
        "neighbours": int(neighbours),
        "regularization_m": float(regularization),
        "query_count": int(len(queries)),
        "output_velocity_mean_mps": _velocity_mean(output),
        "truth_velocity_mps": _velocity_mean(truth),
        "velocity_rmse_mps": float(np.sqrt(np.mean(finite_error ** 2)))
        if len(finite_error) else None,
        "wrong_tangential_direction_fraction": float(
            np.mean(wrong_direction[finite_output])
        ) if finite_output.any() else None,
        "finite_output_fraction": float(np.mean(finite_output)),
        "contaminant_weight_fraction": _stats(np.asarray(contaminant_weights)),
        "contaminant_selected_fraction": _stats(np.asarray(contaminant_counts)),
        "selected_finite_count": _stats(np.asarray(selected_counts, dtype=float)),
        "eligible_visible_count": _stats(np.asarray(eligible_counts, dtype=float)),
        "support_distance_m": _stats(np.asarray(support, dtype=float)),
        "query_rows": rows,
    }


def minimum_visible_support_guard(
    case: dict[str, Any],
    *,
    neighbours: int = NEIGHBOURS,
    regularization: float = REGULARIZATION_M,
) -> dict[str, Any]:
    """Evaluate a rejected candidate guard requiring a full visible support."""
    output, support, visible_count = shepard_velocity(
        case["queries"], case["positions"], case["velocities"],
        neighbours=neighbours, regularization=regularization,
        barrier_triangles=case["barriers"], return_diagnostics=True,
    )
    required = min(int(neighbours), len(case["positions"]))
    accepted = (visible_count >= required) & np.all(np.isfinite(output), axis=1)
    guarded = np.where(accepted[:, None], output, np.nan)
    return {
        "guard": "minimum_visible_support",
        "minimum_required_visible_neighbours": int(required),
        "accepted_query_count": int(np.sum(accepted)),
        "accepted_query_fraction": float(np.mean(accepted)),
        "guarded_velocity_mean_mps": _velocity_mean(guarded),
        "accepted_mask": [bool(value) for value in accepted],
        "support_distance_m": _stats(support),
        "status": "candidate_only_rejected",
        "rejection_reason": (
            "safe undersupport diagnostic only; rejecting a valid narrow opening "
            "cannot be promoted without an explicit open-face/support policy"
        ),
    }


def component_label_guard(
    case: dict[str, Any],
    *,
    neighbours: int = NEIGHBOURS,
    regularization: float = REGULARIZATION_M,
) -> dict[str, Any]:
    """Apply known synthetic region labels as an oracle, never production logic."""
    output = np.full_like(case["truth"], np.nan, dtype=np.float64)
    support = np.full(len(case["queries"]), np.nan, dtype=np.float64)
    retained = np.zeros(len(case["queries"]), dtype=np.int64)
    sample_labels = np.asarray(case["region_labels"])
    query_labels = np.asarray(case["query_region_labels"])
    for index, (query, label) in enumerate(zip(case["queries"], query_labels)):
        allowed = sample_labels == label
        retained[index] = int(np.sum(allowed))
        if not allowed.any():
            continue
        value, distance, _ = shepard_velocity(
            query[None, :], case["positions"][allowed], case["velocities"][allowed],
            neighbours=neighbours, regularization=regularization,
            barrier_triangles=None, return_diagnostics=True,
        )
        output[index] = value[0]
        support[index] = distance[0]
    finite = np.all(np.isfinite(output), axis=1)
    error = np.linalg.norm(output - case["truth"], axis=1)
    return {
        "guard": "known_region_label_gate",
        "output_velocity_mean_mps": _velocity_mean(output),
        "velocity_rmse_mps": float(np.sqrt(np.mean(error[finite] ** 2)))
        if finite.any() else None,
        "wrong_tangential_direction_fraction": float(
            np.mean(output[finite, 1] * case["truth"][finite, 1] < 0)
        ) if finite.any() else None,
        "finite_output_fraction": float(np.mean(finite)),
        "retained_same_region_sample_count": _stats(retained.astype(float)),
        "support_distance_m": _stats(support),
        "status": "candidate_only_rejected",
        "rejection_reason": (
            "synthetic region labels are not a production material-lineage or "
            "open-gap topology contract"
        ),
    }


def _gap_visibility_counts(case: dict[str, Any]) -> dict[str, Any]:
    visibility = segment_visibility(case["queries"], case["positions"], case["barriers"])
    gap = np.asarray(case["gap_sample_mask"], dtype=bool)
    blocked = np.asarray(case["blocked_sample_mask"], dtype=bool)
    return {
        "gap_samples_total": int(np.sum(gap)),
        "gap_samples_visible_per_query": [int(value) for value in visibility[:, gap].sum(axis=1)],
        "gap_samples_retention_fraction": float(np.mean(visibility[:, gap])) if gap.any() else None,
        "blocked_samples_total": int(np.sum(blocked)),
        "blocked_samples_visible_per_query": [int(value) for value in visibility[:, blocked].sum(axis=1)],
        "blocked_samples_retention_fraction": float(np.mean(visibility[:, blocked])) if blocked.any() else None,
    }


def _case_report(case: dict[str, Any]) -> dict[str, Any]:
    legacy = summarize_interpolant(case, barriers=None)
    wall_aware = summarize_interpolant(case, barriers=case["barriers"])
    result: dict[str, Any] = {
        "description": case["description"],
        "geometry": case["geometry"],
        "particle_count": int(len(case["positions"])),
        "query_count": int(len(case["queries"])),
        "barrier_triangle_count": int(len(case["barriers"])),
        "legacy_no_barrier": legacy,
        "existing_wall_aware": wall_aware,
        "minimum_visible_support_guard": minimum_visible_support_guard(case),
        "comparison": {
            "velocity_rmse_reduction_mps": (
                legacy["velocity_rmse_mps"] - wall_aware["velocity_rmse_mps"]
                if legacy["velocity_rmse_mps"] is not None
                and wall_aware["velocity_rmse_mps"] is not None else None
            ),
            "wrong_direction_fraction_reduction": (
                legacy["wrong_tangential_direction_fraction"]
                - wall_aware["wrong_tangential_direction_fraction"]
                if legacy["wrong_tangential_direction_fraction"] is not None
                and wall_aware["wrong_tangential_direction_fraction"] is not None else None
            ),
        },
    }
    if case["case_id"] == "separated_liquid_blob":
        result["known_region_label_gate"] = component_label_guard(case)
    if case["case_id"] == "narrow_gap_visibility":
        result["gap_visibility"] = _gap_visibility_counts(case)
    return result


def build_report() -> dict[str, Any]:
    """Run all deterministic probes and return a JSON-serializable report."""
    built_cases = [case_builder() for case_builder in CASE_BUILDERS]
    cases = {case["case_id"]: _case_report(case) for case in built_cases}
    partition = cases["partition_tangential_flow"]
    gap = cases["narrow_gap_visibility"]
    blob = cases["separated_liquid_blob"]
    return {
        "schema_version": 1,
        "scope": "R3 G2 CPU-only synthetic tracer visibility diagnostic",
        "execution_status": "complete",
        "acceptance_status": "candidate_only_rejected",
        "compute": {
            "backend": "NumPy + existing passive_tracers.py",
            "gpu_used": False,
            "cfd_solver_run": False,
            "neighbours": NEIGHBOURS,
            "regularization_m": REGULARIZATION_M,
            "regularization_over_dp": REGULARIZATION_M / DP_M,
            "synthetic_dp_m": DP_M,
        },
        "implementation_audit": {
            "requested_wall_aware_script": "r3_g2_tracer_wall_aware.py",
            "requested_script_present": False,
            "actual_wall_aware_implementation": "scripts/passive_tracers.py",
            "legacy_selection": (
                "24 nearest samples by Euclidean distance, inverse-distance weights; "
                "without triangles every sample is eligible"
            ),
            "wall_filter": (
                "segment_visibility masks finite triangle intersections before nearest selection"
            ),
            "path_guard": (
                "corresponding_segments_blocked rejects a Heun candidate crossing a supplied wall"
            ),
            "undersupport_behavior": (
                "fewer than 24 visible samples are allowed to interpolate with zero-weight inf slots"
            ),
            "disconnected_blob_behavior": (
                "no barrier triangles means geometry-only visibility cannot infer disconnected liquid regions"
            ),
        },
        "sources_read": [
            "scripts/passive_tracers.py",
            "campaigns/v0.1-candidate/r3-g2-tracer-wall-aware.json",
            "campaigns/v0.1-candidate/R3-G2-TRACER-WALL-AWARE.md",
            "campaigns/v0.1-candidate/r3-g2-tracer-convergence.json",
            "campaigns/v0.1-candidate/R3-G2-TRACER-CONVERGENCE.md",
            "campaigns/v0.1-candidate/r3-g2-tracer-neighbour-sensitivity.json",
            "campaigns/v0.1-candidate/R3-G2-TRACER-NEIGHBOUR-SENSITIVITY.md",
        ],
        "cases": cases,
        "headline": {
            "partition_legacy_wrong_direction_fraction": partition["legacy_no_barrier"]["wrong_tangential_direction_fraction"],
            "partition_wall_aware_wrong_direction_fraction": partition["existing_wall_aware"]["wrong_tangential_direction_fraction"],
            "partition_legacy_contaminant_weight_fraction": partition["legacy_no_barrier"]["contaminant_weight_fraction"],
            "partition_wall_aware_contaminant_weight_fraction": partition["existing_wall_aware"]["contaminant_weight_fraction"],
            "gap_legacy_blocked_weight_fraction": gap["legacy_no_barrier"]["contaminant_weight_fraction"],
            "gap_wall_aware_blocked_weight_fraction": gap["existing_wall_aware"]["contaminant_weight_fraction"],
            "blob_legacy_wrong_direction_fraction": blob["legacy_no_barrier"]["wrong_tangential_direction_fraction"],
            "blob_wall_aware_wrong_direction_fraction": blob["existing_wall_aware"]["wrong_tangential_direction_fraction"],
            "blob_region_gate_wrong_direction_fraction": blob["known_region_label_gate"]["wrong_tangential_direction_fraction"],
        },
        "candidate_decision": {
            "minimum_visible_support_guard": "rejected_candidate_only",
            "known_region_label_gate": "rejected_candidate_only",
            "reason": (
                "finite-wall visibility is effective only where wall geometry is supplied; "
                "undersupport/open-gap semantics and disconnected-liquid region labels are not frozen"
            ),
        },
        "limitations": [
            "Synthetic fields are not CFD validation and do not establish physical truth for any case.",
            "Finite triangle visibility cannot detect disconnected liquid blobs without a barrier or region contract.",
            "A minimum-visible-neighbour guard safely rejects the narrow-gap probe but may reject valid open-face transport.",
            "The region-label gate is an oracle requiring metadata absent from the current production tracer API.",
            "No production or upstream files were modified by this diagnostic.",
        ],
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "NA"
    if isinstance(value, dict):
        value = value.get("mean")
    return "NA" if value is None else f"{float(value):.{digits}f}"


def render_markdown(report: dict[str, Any]) -> str:
    """Render a concise Chinese handoff with the machine-readable numbers."""
    cases = report["cases"]
    partition = cases["partition_tangential_flow"]
    gap = cases["narrow_gap_visibility"]
    blob = cases["separated_liquid_blob"]
    lines = [
        "# R3 G2 示踪材料可见性 synthetic 诊断",
        "",
        "状态：**candidate-only / rejected；CPU-only，未运行 CFD、未使用 GPU，也未改生产代码。**",
        "",
        "## 结论",
        "",
        "当前仓库没有名为 `r3_g2_tracer_wall_aware.py` 的脚本；实际 wall-aware 路径是 "
        "`scripts/passive_tracers.py` 的 `segment_visibility` 和 `corresponding_segments_blocked`。"
        "合成反例确认：给出有限三角墙时，已有路径能阻止跨墙样本；没有墙几何时，它不能从空间分离本身推断液团拓扑。",
        "",
        "| Probe | legacy 24-neighbor 污染权重 | existing wall-aware 污染权重 | legacy 错向率 | wall-aware 错向率 |",
        "|---|---:|---:|---:|---:|",
        f"| 隔板两侧切向流 | {_fmt(partition['legacy_no_barrier']['contaminant_weight_fraction'])} | "
        f"{_fmt(partition['existing_wall_aware']['contaminant_weight_fraction'])} | "
        f"{_fmt(partition['legacy_no_barrier']['wrong_tangential_direction_fraction'])} | "
        f"{_fmt(partition['existing_wall_aware']['wrong_tangential_direction_fraction'])} |",
        f"| 窄间隙（仅统计被墙挡住的近样本） | {_fmt(gap['legacy_no_barrier']['contaminant_weight_fraction'])} | "
        f"{_fmt(gap['existing_wall_aware']['contaminant_weight_fraction'])} | "
        f"{_fmt(gap['legacy_no_barrier']['wrong_tangential_direction_fraction'])} | "
        f"{_fmt(gap['existing_wall_aware']['wrong_tangential_direction_fraction'])} |",
        f"| 分离液团（无 barrier） | {_fmt(blob['legacy_no_barrier']['contaminant_weight_fraction'])} | "
        f"{_fmt(blob['existing_wall_aware']['contaminant_weight_fraction'])} | "
        f"{_fmt(blob['legacy_no_barrier']['wrong_tangential_direction_fraction'])} | "
        f"{_fmt(blob['existing_wall_aware']['wrong_tangential_direction_fraction'])} |",
        "",
        "## 逐例观察",
        "",
        f"- 隔板：legacy 的平均错误侧权重为 `{_fmt(partition['legacy_no_barrier']['contaminant_weight_fraction'])}`，"
        f"16 个查询中错向率 `{_fmt(partition['legacy_no_barrier']['wrong_tangential_direction_fraction'])}`；"
        f"wall-aware 将错误侧权重降为 `{_fmt(partition['existing_wall_aware']['contaminant_weight_fraction'])}`，"
        f"错向率为 `{_fmt(partition['existing_wall_aware']['wrong_tangential_direction_fraction'])}`。"
        "这证明有限三角视线过滤确实参与了邻居选择。",
        f"- 窄间隙：wall-aware 对 {gap['gap_visibility']['blocked_samples_total']} 个墙后近样本的可见保留率为 "
        f"`{_fmt(gap['gap_visibility']['blocked_samples_retention_fraction'])}`，但对真实开口的 "
        f"{gap['gap_visibility']['gap_samples_total']} 个样本保留率为 `{_fmt(gap['gap_visibility']['gap_samples_retention_fraction'])}`。"
        f"每个查询只有 {gap['existing_wall_aware']['eligible_visible_count']['mean']:.0f} 个可见样本，少于 24；"
        "因此最小可见支撑 guard 会安全拒绝这组 probe，而不能在没有 open-face policy 时直接接纳。",
        f"- 分离液团：无 triangle 时 wall-aware 与 legacy 相同（错向率 "
        f"`{_fmt(blob['existing_wall_aware']['wrong_tangential_direction_fraction'])}`，错误侧权重 "
        f"`{_fmt(blob['existing_wall_aware']['contaminant_weight_fraction'])}`）。已知 synthetic region-label gate 可将错向率降为 "
        f"`{_fmt(blob['known_region_label_gate']['wrong_tangential_direction_fraction'])}`，但该标签不是当前生产 API 的材料 lineage，故标记 rejected candidate。",
        "",
        "## Candidate guard 决策",
        "",
        "本轮只保留两个独立 candidate-only 选项用于后续设计：",
        "",
        "1. `minimum_visible_support`：要求可见样本数至少达到 24；它对跨墙混合采取拒绝策略，但会把窄间隙合法 transport 也判为欠支撑。",
        "2. `known_region_label_gate`：在 synthetic 中按已知 blob 标签筛选同区域样本；它能修复分离液团，但缺少生产 region/lineage contract，且静态标签无法独立表达开口连通性。",
        "",
        "两者均为 **rejected candidate-only**，没有替换 `passive_tracers.py`。正式接纳前仍需冻结 wall component 的 open/closed/rim/supporting policy、材料 destination/region 语义，并在收敛矩阵中报告欠支撑拒绝率。",
        "",
        "机器可读证据：`r3-g2-tracer-visibility.json`；可重复入口：`diagnostics/r3_g2_tracer_visibility/probe.py`。",
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
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(report))
    print(json.dumps({
        "report": str(args.report),
        "markdown": str(args.markdown),
        "case_count": len(report["cases"]),
        "gpu_used": report["compute"]["gpu_used"],
        "acceptance_status": report["acceptance_status"],
    }, indent=2))


if __name__ == "__main__":
    main()
