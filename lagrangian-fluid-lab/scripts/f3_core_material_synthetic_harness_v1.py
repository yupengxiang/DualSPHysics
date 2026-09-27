"""Bounded, synthetic-only diagnostics for the F3 core material path.

The harness exercises the existing ``CurrentField`` -> visible Shepard ->
RK2 -> censor path without opening a source file.  All particle frames and
queries are constructed in memory.  The temporal cases use the public
``trace(..., provider=...)`` injection point and place its short-lived HDF5
checkpoint/output under ``tempfile.gettempdir()``; the directory is removed
before the harness returns.

This is deliberately a diagnostic harness, not a material runner.  It does
not accept a source path, register a neighbour variant, alter the fixed
support gate, or emit qualification credit.  The optional JSON output path
is accepted only below the system temporary directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

import h5py
import numpy as np
from scipy.linalg import expm

from scripts.core_material import (
    CurrentField,
    GATE,
    MAXIMUM_SUPPORT_DISTANCE_M,
    REGULARIZATION_M,
    trace,
)


SCHEMA = "core.material.f3.synthetic_harness.v1"
UNKNOWN_FRACTION_LIMIT = 0.01
TEMPORAL_FRAME_COUNT = 5
TEMPORAL_GRID_SIDE = 15
TEMPORAL_SEED_COUNT = 4
SUPPORT_GRID_SIDE = 9
SUPPORT_QUERY_COUNT = 3
MAX_NEIGHBOURS = 24
K16_DIAGNOSTIC_NEIGHBOURS = 16


def _number(value):
    """Return JSON-safe numeric data, mapping non-finite values to null."""
    value = np.asarray(value).item() if isinstance(value, np.generic) else value
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (int, np.integer)):
        return int(value)
    return value


def _bool(value):
    return bool(np.asarray(value).item())


def canonical_json(value):
    """Serialize one report with stable key ordering and no NaN/Inf."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fixed_gate():
    return {
        "minimum_effective_sample_size": _number(GATE["minimum_effective_sample_size"]),
        "minimum_geometry_rank": _number(GATE["minimum_geometry_rank"]),
        "minimum_anisotropy": _number(GATE["minimum_anisotropy"]),
        "maximum_reconstruction_error_mps": _number(
            GATE["maximum_reconstruction_error_mps"]
        ),
        "maximum_support_distance_m": float(MAXIMUM_SUPPORT_DISTANCE_M),
        "unknown_fraction_limit": UNKNOWN_FRACTION_LIMIT,
    }


def _reason_rows(query, velocity, support, passed, diagnostics):
    """Explain each failed support without changing the production gate."""
    query = np.asarray(query, dtype=np.float64)
    velocity = np.asarray(velocity, dtype=np.float64)
    support = np.asarray(support, dtype=np.float64)
    passed = np.asarray(passed, dtype=bool)
    reasons = []
    for index in range(len(query)):
        row = []
        if not np.isfinite(query[index]).all():
            row.append("nonfinite_query")
        if int(diagnostics["selected_visible_neighbours"][index]) <= 0:
            row.append("no_visible_support")
        if not np.isfinite(velocity[index]).all():
            row.append("nonfinite_velocity")
        if not np.isfinite(support[index]):
            row.append("nonfinite_support_distance")
        if not np.isfinite(diagnostics["effective_sample_size"][index]) or diagnostics[
            "effective_sample_size"
        ][index] < GATE["minimum_effective_sample_size"]:
            row.append("effective_sample_size")
        if not np.isfinite(diagnostics["geometry_rank"][index]) or diagnostics[
            "geometry_rank"
        ][index] < GATE["minimum_geometry_rank"]:
            row.append("geometry_rank")
        if not np.isfinite(diagnostics["anisotropy"][index]) or diagnostics[
            "anisotropy"
        ][index] < GATE["minimum_anisotropy"]:
            row.append("anisotropy")
        if not np.isfinite(
            diagnostics["estimated_interpolation_error_mps"][index]
        ) or diagnostics["estimated_interpolation_error_mps"][index] > GATE[
            "maximum_reconstruction_error_mps"
        ]:
            row.append("reconstruction_error")
        if np.isfinite(support[index]) and support[index] > MAXIMUM_SUPPORT_DISTANCE_M:
            row.append("support_distance")
        if not passed[index] and not row:
            row.append("gate_failed")
        reasons.append(row)
    return reasons


def _reason_counts(reason_rows):
    counts = {}
    for row in reason_rows:
        for reason in row:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _support_case(name, field, query, truth=None, neighbours=MAX_NEIGHBOURS):
    velocity, support, passed, diagnostics = field.sample(
        query,
        walls=np.empty((0, 3, 3), dtype=np.float64),
        neighbours=neighbours,
        regularization=REGULARIZATION_M,
        return_diagnostics=True,
    )
    reason_rows = _reason_rows(query, velocity, support, passed, diagnostics)
    rows = []
    for index in range(len(query)):
        row = {
            "query_index": index,
            "passed": _bool(passed[index]),
            "support_distance_m": _number(support[index]),
            "effective_sample_size": _number(
                diagnostics["effective_sample_size"][index]
            ),
            "geometry_rank": _number(diagnostics["geometry_rank"][index]),
            "anisotropy": _number(diagnostics["anisotropy"][index]),
            "interpolation_reconstruction_error_mps": _number(
                diagnostics["interpolation_reconstruction_error_mps"][index]
            ),
            "estimated_interpolation_error_mps": _number(
                diagnostics["estimated_interpolation_error_mps"][index]
            ),
            "visible_neighbours": _number(diagnostics["visible_neighbours"][index]),
            "selected_visible_neighbours": _number(
                diagnostics["selected_visible_neighbours"][index]
            ),
            "failure_reasons": reason_rows[index],
        }
        if truth is not None:
            truth_velocity = np.asarray(truth, dtype=np.float64)[index]
            row["truth_velocity_error_mps"] = _number(
                np.linalg.norm(velocity[index] - truth_velocity)
            )
        rows.append(row)
    failed = np.flatnonzero(~passed)
    result = {
        "name": name,
        "neighbours": int(neighbours),
        "input_sample_count": int(field.input_count),
        "valid_sample_count": int(field.valid_count),
        "query_count": int(len(query)),
        "passed_count": int(np.count_nonzero(passed)),
        "all_passed": bool(np.all(passed)),
        "first_unreliable_query_index": int(failed[0]) if len(failed) else None,
        "failure_reason_counts": _reason_counts(reason_rows),
        "per_query": rows,
        "backend": diagnostics["backend"],
        "error_estimator": diagnostics["error_estimator"],
    }
    return result


def _support_suite():
    axis = np.linspace(-0.06, 0.06, SUPPORT_GRID_SIDE)
    points = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1).reshape(-1, 3)
    queries = np.array(
        [[0.013, -0.011, 0.017], [-0.021, 0.019, -0.013], [0.027, -0.015, 0.022]],
        dtype=np.float64,
    )

    shear = np.array(
        [[0.0, 0.7, -0.2], [-0.3, 0.0, 0.4], [0.2, -0.1, 0.0]],
        dtype=np.float64,
    )
    offset = np.array([0.03, -0.02, 0.01], dtype=np.float64)
    affine_velocity = points @ shear.T + offset
    affine_truth = queries @ shear.T + offset
    affine = _support_case(
        "affine_shear", CurrentField(points, affine_velocity), queries, affine_truth
    )

    quadratic_velocity = np.column_stack(
        (
            0.1 * points[:, 0] ** 2 + 0.05 * points[:, 1] * points[:, 2],
            0.2 * points[:, 1] ** 2,
            -0.15 * points[:, 2] ** 2,
        )
    )
    quadratic_truth = np.column_stack(
        (
            0.1 * queries[:, 0] ** 2 + 0.05 * queries[:, 1] * queries[:, 2],
            0.2 * queries[:, 1] ** 2,
            -0.15 * queries[:, 2] ** 2,
        )
    )
    quadratic_field = CurrentField(points, quadratic_velocity)
    quadratic = _support_case("quadratic", quadratic_field, queries, quadratic_truth)
    k16 = _support_case(
        "synthetic_k16_candidate",
        quadratic_field,
        queries,
        quadratic_truth,
        neighbours=K16_DIAGNOSTIC_NEIGHBOURS,
    )
    k16.update(
        {
            "registration_status": "not_registered",
            "formal_variant": False,
            "qualification_credit": 0,
        }
    )

    plane_axis = np.linspace(-0.06, 0.06, SUPPORT_GRID_SIDE)
    plane = np.stack(
        np.meshgrid(plane_axis, plane_axis, np.array([0.0]), indexing="ij"), axis=-1
    ).reshape(-1, 3)
    plane_velocity = np.column_stack(
        (0.2 * plane[:, 0], -0.1 * plane[:, 1], np.zeros(len(plane)))
    )
    degenerate = _support_case(
        "degenerate_planar_support",
        CurrentField(plane, plane_velocity),
        np.array([[0.013, -0.011, 0.004]], dtype=np.float64),
    )

    invalid = _support_case(
        "all_samples_invalid",
        CurrentField(points, affine_velocity, valid=np.zeros(len(points), dtype=bool)),
        queries[:1],
    )
    nonfinite = _support_case(
        "nonfinite_query",
        CurrentField(points, affine_velocity),
        np.array([[np.nan, 0.0, 0.0]], dtype=np.float64),
    )
    return {
        "affine_shear": affine,
        "quadratic": quadratic,
        "synthetic_k16_candidate": k16,
        "degenerate_planar_support": degenerate,
        "all_samples_invalid": invalid,
        "nonfinite_query": nonfinite,
    }


class SyntheticFrames:
    """Small in-memory provider implementing only the public trace contract."""

    provider_role = "synthetic_memory"
    source_sha256 = "synthetic-memory-f3-core-material-v1"

    def __init__(self, *, drop_frame=None):
        self.times = np.linspace(0.0, 0.12, TEMPORAL_FRAME_COUNT)
        axis = np.linspace(-0.12, 0.12, TEMPORAL_GRID_SIDE)
        self.position = np.stack(
            np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1
        ).reshape(-1, 3)
        self.valid = np.ones((len(self.times), len(self.position)), dtype=bool)
        if drop_frame is not None:
            if not 0 <= int(drop_frame) < len(self.times):
                raise ValueError("synthetic drop_frame is outside the bounded frame range")
            self.valid[int(drop_frame)] = False

    @staticmethod
    def velocity_at(position, time_s):
        value = np.array(
            [
                0.08 + 0.3 * time_s + 0.7 * time_s**2,
                -0.01 + 0.1 * time_s**2,
                0.015 - 0.05 * time_s + 0.2 * time_s**2,
            ],
            dtype=np.float64,
        )
        return np.broadcast_to(value, np.asarray(position).shape).copy()

    def field(self, index, alpha=0.0):
        index = int(index)
        if not 0 <= index < len(self.times) - (1 if alpha else 0):
            raise IndexError("synthetic field index outside bounded frame range")
        alpha = float(alpha)
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("synthetic interpolation alpha must be in [0,1]")
        time_s = self.times[index]
        valid = self.valid[index]
        if alpha:
            time_s += alpha * (self.times[index + 1] - self.times[index])
            valid = valid & self.valid[index + 1]
        velocity = self.velocity_at(self.position, time_s)
        return CurrentField(self.position, velocity, valid)

    def close(self):
        """Match the provider lifecycle without owning a file or descriptor."""


def _temporal_truth(seeds, horizon_s):
    """Exact solution for the bounded spatially uniform quadratic velocity."""
    displacement = np.array(
        [
            0.08 * horizon_s + 0.15 * horizon_s**2 + (0.7 / 3.0) * horizon_s**3,
            -0.01 * horizon_s + (0.1 / 3.0) * horizon_s**3,
            0.015 * horizon_s - 0.025 * horizon_s**2 + (0.2 / 3.0) * horizon_s**3,
        ],
        dtype=np.float64,
    )
    return np.asarray(seeds, dtype=np.float64) + displacement


def _compact_trace_result(result, final_position, truth, *, substeps, drop_frame=None):
    errors = np.linalg.norm(np.asarray(final_position) - np.asarray(truth), axis=1)
    first_unreliable = [
        row["first_unreliable_frame"]
        for row in result["by_source"]
        if row["first_unreliable_frame"] is not None
    ]
    return {
        "substeps": int(substeps),
        "status": result["status"],
        "native_frame_count": int(result["native_frame_count"]),
        "committed_frame": int(result["committed_frame"]),
        "unknown_gate_pass": bool(result["unknown_gate_pass"]),
        "unknown_full_denominator": True,
        "common_reliable_path_coverage": float(result["common_reliable_path_coverage"]),
        "first_unreliable_step_overall": min(first_unreliable) if first_unreliable else None,
        "by_source": [
            {
                "source": row["source"],
                "unknown_fraction_max": float(row["unknown_fraction_max"]),
                "reliable_path_coverage": float(row["reliable_path_coverage"]),
                "first_unreliable_step": row["first_unreliable_frame"],
                "first_unreliable_time_s": row["first_unreliable_time_s"],
            }
            for row in result["by_source"]
        ],
        "final_position_error_m": [_number(value) for value in errors],
        "final_position_rmse_m": _number(np.sqrt(np.mean(errors**2))),
        "final_position_max_error_m": _number(np.max(errors)),
        "drop_frame": None if drop_frame is None else int(drop_frame),
        "temporary_output_only": True,
        "qualification_claim": result["qualification_claim"],
        "qualified_T2_macro": bool(result["qualified_T2_macro"]),
    }


def _run_trace(*, substeps, drop_frame=None):
    seeds = np.array(
        [[-0.035, 0.013, 0.017], [0.027, -0.017, 0.023],
         [-0.013, 0.027, 0.031], [0.019, 0.021, 0.037]],
        dtype=np.float64,
    )
    provider = SyntheticFrames(drop_frame=drop_frame)
    truth = _temporal_truth(seeds, float(provider.times[-1]))
    with tempfile.TemporaryDirectory(prefix="f3-core-material-harness-") as directory:
        output = Path(directory) / "synthetic-trace.h5"
        result = trace(
            None,
            output,
            seeds,
            np.empty((0, 3, 3), dtype=np.float64),
            substeps=substeps,
            provider=provider,
        )
        with h5py.File(output, "r") as handle:
            final_position = np.asarray(handle["position"][-1], dtype=np.float64)
    return _compact_trace_result(
        result,
        final_position,
        truth,
        substeps=substeps,
        drop_frame=drop_frame,
    )


def _temporal_suite():
    substeps2 = _run_trace(substeps=2)
    substeps4 = _run_trace(substeps=4)
    censor = _run_trace(substeps=2, drop_frame=2)
    censor["support_failure_reason"] = "frame_2_all_support_samples_invalid"
    censor["first_unreliable_step_expected"] = 2
    return {
        "substeps_2": substeps2,
        "substeps_4": substeps4,
        "censor_probe": censor,
        "comparison": {
            "substeps_4_rmse_not_greater_than_substeps_2": bool(
                substeps4["final_position_rmse_m"] <= substeps2["final_position_rmse_m"]
            ),
            "substeps_2_rmse_m": substeps2["final_position_rmse_m"],
            "substeps_4_rmse_m": substeps4["final_position_rmse_m"],
        },
    }


def run_harness():
    """Run the complete bounded in-memory diagnostic and return its receipt."""
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(variable, "1")
    return {
        "schema": SCHEMA,
        "diagnostic_only": True,
        "qualification_credit": 0,
        "qualified_T2_macro": False,
        "production_artifacts_touched": False,
        "input_contract": {
            "source_path_accepted": False,
            "source_path_opened": False,
            "source_semantics": "in_memory_synthetic_arrays_only",
            "provider_role": SyntheticFrames.provider_role,
        },
        "execution": {
            "device": "cpu",
            "workers": 1,
            "gpu_started": False,
            "solver_started": False,
            "worker_started": False,
            "queue_mutated": False,
            "output_policy": "temporary_directory_only_then_removed",
        },
        "fixed_gate": _fixed_gate(),
        "denominator_policy": {
            "unknown_kept_in_full_seed_denominator": True,
            "unknown_rows_dropped": False,
            "gate_relaxed": False,
        },
        "workload_bound": {
            "max_native_frames": TEMPORAL_FRAME_COUNT,
            "max_particle_count": TEMPORAL_GRID_SIDE**3,
            "max_seed_count": TEMPORAL_SEED_COUNT,
            "max_neighbours": MAX_NEIGHBOURS,
            "k16_candidate_is_unregistered": True,
        },
        "support_cases": _support_suite(),
        "temporal_cases": _temporal_suite(),
    }


def _safe_output(path):
    path = Path(path)
    temporary_root = Path(tempfile.gettempdir()).resolve()
    resolved = path.resolve()
    if resolved == temporary_root or temporary_root not in resolved.parents:
        raise ValueError("--output must be below the system temporary directory")
    if path.exists() and path.is_symlink():
        raise ValueError("--output must not be a symlink")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="optional canonical JSON path; it must be below the system temporary directory",
    )
    args = parser.parse_args(argv)
    report = run_harness()
    text = canonical_json(report)
    if args.output is not None:
        output = _safe_output(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
