"""Prospective synthetic holdout for the frozen F4 v5 blend candidate.

This diagnostic evaluates the unchanged v5 and v3 predictors on a new smooth,
periodic, divergence-free channel mode and two q values not used in the v4/v5/v6
candidate screens.  It is a prospective stress set, not external validation or
qualification.  A load gate is checked before constructing clouds or queries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import time
from typing import Any

import numpy as np
import scipy

from scripts import core_material
from scripts.core_material import (
    GATE,
    f4_destination_region,
    f4_source_region,
    f4_walls,
    seeds_f4,
)
from scripts.f4_material_calibration import _box_lattice, _grid
from scripts.f4_supportcap_affine_query_bound_candidate_v3 import (
    CANDIDATE_ID as BASELINE_ID,
    sample_candidate as sample_v3,
)
from scripts.f4_supportcap_affine_shepard_blend_candidate_v5 import (
    CANDIDATE_ID as CANDIDATE_ID_V5,
    sample_candidate as sample_v5,
)


SCHEMA = "core.material.f4.supportcap.affine_shepard_blend.heldout.v1"
RECEIPT_SCHEMA = "core.material.f4.supportcap.affine_shepard_blend.heldout_receipt.v1"
REVISION = "f4-v5-prospective-channel-mode-holdout-20260926-v1"
Q_CASES = (0.75, 0.95)
FIELD_ID = "periodic_no_slip_divergence_free_channel_mode"
SUPPORT_SPACING_M = 0.015
X_PERIOD_M = 1.2
CHANNEL_HEIGHT_M = 0.6
STREAMFUNCTION_AMPLITUDE_M2PS = 0.025
INTERFACE_LOW_M = (0.0, 0.0, 0.15)
INTERFACE_SIZE_M = (1.2, 0.4, 0.06)
INTERFACE_COUNTS = (16, 8, 3)
SOURCE_QUERY_COUNT = 512
DESTINATION_COUNTS = (16, 8, 4)
EXPECTED_QUERY_COUNT = 2 * (SOURCE_QUERY_COUNT + math.prod(INTERFACE_COUNTS) + math.prod(DESTINATION_COUNTS))
MAXIMUM_TRUTH_ERROR_MPS = float(GATE["maximum_reconstruction_error_mps"])
LOAD_GATE_SCHEMA = "one_minute_system_load_le_process_visible_cpu_count"

REPO_ROOT = Path(__file__).resolve().parents[1]


class ProfileDeferred(RuntimeError):
    """The bounded synthetic evaluation declined to add work on a loaded host."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    header = _canonical({"dtype": array.dtype.str, "shape": list(array.shape)})
    return hashlib.sha256(header + array.tobytes()).hexdigest()


def _code_bindings() -> dict[str, dict[str, str]]:
    paths = {
        "validation_script": Path(__file__).resolve(),
        "v3_baseline": Path(sample_v3.__code__.co_filename).resolve(),
        "v5_candidate": Path(sample_v5.__code__.co_filename).resolve(),
        "f4_geometry_and_gate": Path(core_material.__file__).resolve(),
        "calibration_geometry_helpers": Path(_box_lattice.__code__.co_filename).resolve(),
    }
    return {
        role: {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": _sha256_file(path),
        }
        for role, path in paths.items()
    }


def design() -> dict[str, Any]:
    """Return the fixed protocol; no candidate or threshold is fit here."""
    return {
        "schema": SCHEMA,
        "revision_id": REVISION,
        "purpose": "prospective synthetic stress evaluation of the frozen F4 v5 blend",
        "holdout_status": "prospective_unscored_stress_set_not_external_independent_validation",
        "qualification_claim": "none",
        "credit": 0,
        "candidates": {
            "baseline": BASELINE_ID,
            "candidate": CANDIDATE_ID_V5,
            "candidate_parameters_fitted_for_this_set": False,
            "thresholds_or_candidate_parameters_may_change_after_scoring": False,
        },
        "geometry": {
            "q_cases": list(Q_CASES),
            "support_spacing_m": SUPPORT_SPACING_M,
            "source_queries": {"count": SOURCE_QUERY_COUNT, "generator": "core_material.seeds_f4"},
            "interface_queries": {
                "low_m": list(INTERFACE_LOW_M),
                "size_m": list(INTERFACE_SIZE_M),
                "counts": list(INTERFACE_COUNTS),
                "generator": "cell_centers_in_fixed_registered_interface_box",
            },
            "destination_queries": {
                "counts": list(DESTINATION_COUNTS),
                "generator": "cell_centers_in_f4_destination_region",
            },
            "support_cloud": "union_of_destination_and_q_specific_source_cell_center_lattices",
            "expected_query_count": EXPECTED_QUERY_COUNT,
        },
        "held_out_field": {
            "id": FIELD_ID,
            "type": "two_dimensional_incompressible_streamfunction_mode_in_xz",
            "streamfunction": "A*sin(2*pi*x/Lx)*sin(pi*z/H)^2",
            "streamfunction_amplitude_m2ps": STREAMFUNCTION_AMPLITUDE_M2PS,
            "x_period_m": X_PERIOD_M,
            "channel_height_m": CHANNEL_HEIGHT_M,
            "velocity": {
                "u_x": "A*(pi/H)*sin(2*pi*x/Lx)*sin(2*pi*z/H)",
                "u_y": "0",
                "u_z": "-A*(2*pi/Lx)*cos(2*pi*x/Lx)*sin(pi*z/H)^2",
            },
            "analytic_invariants": ["divergence_free", "x_periodic", "no_slip_at_z_0_and_H"],
        },
        "acceptance": {
            "gate_decisions_must_match_v3_exactly": True,
            "candidate_truth_error_limit_mps": MAXIMUM_TRUTH_ERROR_MPS,
            "truth_error_limit_basis": "existing_registered_F4_maximum_reconstruction_error",
            "rmse": "reported_by_q_and_region; diagnostic_only_not_a_new_gate",
            "fixed_denominator": EXPECTED_QUERY_COUNT,
            "unknown_or_nonfinite_predictions": "fail_candidate_screen_without_dropping_rows",
        },
        "resource_gate": {
            "schema": LOAD_GATE_SCHEMA,
            "maximum_one_minute_load": "process_visible_cpu_count",
            "load_gate_precedes_cloud_and_query_construction": True,
        },
        "execution_boundary": {
            "analytic_arrays_only": True,
            "native_or_tracer_started": False,
            "solver_started": False,
            "gpu_started": False,
            "worker_or_queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
        },
        "code_bindings": _code_bindings(),
    }


def design_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def verify_design(value: dict[str, Any]) -> None:
    if value != design():
        raise ValueError("holdout design differs from the current frozen protocol or code closure")


def check_load_gate(one_minute_load: float, cpu_capacity: int) -> None:
    if not np.isfinite(one_minute_load) or one_minute_load < 0:
        raise ValueError("one-minute load must be finite and nonnegative")
    if isinstance(cpu_capacity, bool) or not isinstance(cpu_capacity, int) or cpu_capacity < 1:
        raise ValueError("process-visible CPU capacity must be a positive integer")
    if one_minute_load > cpu_capacity:
        raise ProfileDeferred(
            f"heldout synthetic validation deferred: one-minute load {one_minute_load:.3f} "
            f"exceeds process-visible CPU capacity {cpu_capacity}"
        )


def _load_snapshot() -> tuple[float, int]:
    try:
        load = float(os.getloadavg()[0])
    except (AttributeError, OSError) as exc:
        raise ProfileDeferred("cannot inspect one-minute host load; refusing synthetic validation") from exc
    capacity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    return load, max(1, int(capacity))


def _channel_mode_velocity(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("points must be finite with shape [N,3]")
    x = points[:, 0]
    z = points[:, 2]
    kx = 2.0 * np.pi / X_PERIOD_M
    kz = np.pi / CHANNEL_HEIGHT_M
    sin_z = np.sin(kz * z)
    ux = STREAMFUNCTION_AMPLITUDE_M2PS * kz * np.sin(kx * x) * np.sin(2.0 * kz * z)
    uz = -STREAMFUNCTION_AMPLITUDE_M2PS * kx * np.cos(kx * x) * sin_z**2
    return np.column_stack((ux, np.zeros_like(ux), uz))


def _query_regions(q: float) -> dict[str, np.ndarray]:
    destination = f4_destination_region()
    return {
        "source": seeds_f4(SOURCE_QUERY_COUNT, q),
        "interface": _grid(INTERFACE_LOW_M, INTERFACE_SIZE_M, INTERFACE_COUNTS),
        "destination": _grid(
            destination["box_low_m"], destination["box_size_m"], DESTINATION_COUNTS
        ),
    }


def _support_cloud(q: float) -> np.ndarray:
    destination = f4_destination_region()
    source = f4_source_region(q)
    return np.concatenate((
        _box_lattice(destination["box_low_m"], destination["box_size_m"], SUPPORT_SPACING_M),
        _box_lattice(source["box_low_m"], source["box_size_m"], SUPPORT_SPACING_M),
    ))


def _error_summary(prediction: np.ndarray, truth: np.ndarray) -> dict[str, Any]:
    if prediction.shape != truth.shape or prediction.ndim != 2 or prediction.shape[1] != 3:
        raise ValueError("prediction and truth must share shape [N,3]")
    finite = np.isfinite(prediction).all(axis=1)
    errors = np.full(len(truth), np.inf, dtype=np.float64)
    errors[finite] = np.linalg.norm(prediction[finite] - truth[finite], axis=1)
    return {
        "finite_prediction_count": int(finite.sum()),
        "query_count": int(len(truth)),
        "truth_vector_rmse_mps": float(np.sqrt(np.mean(errors[finite]**2))) if finite.all() and len(errors) else (0.0 if not len(errors) else None),
        "truth_vector_max_error_mps": float(errors[finite].max(initial=0.0)) if finite.all() else None,
        "within_fixed_truth_error_limit": bool(np.isfinite(errors).all() and np.all(errors <= MAXIMUM_TRUTH_ERROR_MPS)),
    }


def _evaluate(design_record: dict[str, Any], load_one: float, cpu_capacity: int) -> dict[str, Any]:
    verify_design(design_record)
    check_load_gate(load_one, cpu_capacity)
    start = time.monotonic()
    rows: list[dict[str, Any]] = []
    gate_equal = True
    support_distance_equal = True
    candidate_error_limit_pass = True
    totals = {"query_count": 0, "v3_gate_pass_count": 0, "v5_gate_pass_count": 0}
    all_v3_errors: list[np.ndarray] = []
    all_v5_errors: list[np.ndarray] = []
    walls = f4_walls()

    for q in Q_CASES:
        cloud = _support_cloud(q)
        cloud_velocity = _channel_mode_velocity(cloud)
        cloud_sha256 = _array_sha256(cloud)
        for region, query in _query_regions(q).items():
            truth = _channel_mode_velocity(query)
            prediction_v3, support_v3, pass_v3, _ = sample_v3(
                cloud, cloud_velocity, query, walls
            )
            prediction_v5, support_v5, pass_v5, _ = sample_v5(
                cloud, cloud_velocity, query, walls
            )
            same_gate = bool(np.array_equal(pass_v3, pass_v5))
            same_support = bool(np.array_equal(support_v3, support_v5))
            gate_equal &= same_gate
            support_distance_equal &= same_support
            errors_v3 = np.linalg.norm(prediction_v3 - truth, axis=1)
            errors_v5 = np.linalg.norm(prediction_v5 - truth, axis=1)
            all_v3_errors.append(errors_v3)
            all_v5_errors.append(errors_v5)
            summary_v3 = _error_summary(prediction_v3, truth)
            summary_v5 = _error_summary(prediction_v5, truth)
            candidate_error_limit_pass &= summary_v5["within_fixed_truth_error_limit"]
            rows.append({
                "q": q,
                "field": FIELD_ID,
                "region": region,
                "cloud_count": int(len(cloud)),
                "cloud_sha256": cloud_sha256,
                "query_count": int(len(query)),
                "query_sha256": _array_sha256(query),
                "truth_sha256": _array_sha256(truth),
                "v3_gate_pass_count": int(pass_v3.sum()),
                "v5_gate_pass_count": int(pass_v5.sum()),
                "gate_decisions_equal": same_gate,
                "support_distance_equal": same_support,
                "v3": summary_v3,
                "v5": summary_v5,
                "v5_minus_v3_rmse_mps": (
                    summary_v5["truth_vector_rmse_mps"] - summary_v3["truth_vector_rmse_mps"]
                    if summary_v5["truth_vector_rmse_mps"] is not None and summary_v3["truth_vector_rmse_mps"] is not None
                    else None
                ),
                "v5_relative_rmse_change_pct": (
                    100.0 * (summary_v5["truth_vector_rmse_mps"] / summary_v3["truth_vector_rmse_mps"] - 1.0)
                    if summary_v3["truth_vector_rmse_mps"] is not None
                    and summary_v5["truth_vector_rmse_mps"] is not None
                    and summary_v3["truth_vector_rmse_mps"] > 0.0 else None
                ),
            })
            totals["query_count"] += len(query)
            totals["v3_gate_pass_count"] += int(pass_v3.sum())
            totals["v5_gate_pass_count"] += int(pass_v5.sum())

    if totals["query_count"] != EXPECTED_QUERY_COUNT:
        raise AssertionError("the frozen holdout denominator changed")
    v3_all = np.concatenate(all_v3_errors)
    v5_all = np.concatenate(all_v5_errors)
    all_errors_finite = bool(np.isfinite(v3_all).all() and np.isfinite(v5_all).all())
    v3_global_rmse = float(np.sqrt(np.mean(v3_all**2))) if all_errors_finite else None
    v5_global_rmse = float(np.sqrt(np.mean(v5_all**2))) if all_errors_finite else None
    return {
        "schema": RECEIPT_SCHEMA,
        "design_schema": SCHEMA,
        "design_revision": REVISION,
        "design_sha256": design_sha256(design_record),
        "candidate_id": CANDIDATE_ID_V5,
        "baseline_id": BASELINE_ID,
        "design": design_record,
        "rows": rows,
        "summary": {
            **totals,
            "gate_decisions_equal": gate_equal,
            "support_distance_equal": support_distance_equal,
            "v5_fixed_truth_error_limit_pass": candidate_error_limit_pass,
            "all_predictions_finite": all_errors_finite,
            "v3_all_query_truth_vector_rmse_mps": v3_global_rmse,
            "v5_all_query_truth_vector_rmse_mps": v5_global_rmse,
            "v5_relative_rmse_change_pct": (
                float((v5_global_rmse / v3_global_rmse - 1.0) * 100.0)
                if v3_global_rmse is not None and v5_global_rmse is not None and v3_global_rmse > 0.0
                else None
            ),
            "candidate_screen_pass": bool(gate_equal and support_distance_equal and candidate_error_limit_pass),
            "preflight_recommendation": (
                "requires_independent_review" if gate_equal and support_distance_equal and candidate_error_limit_pass
                else "not_justified"
            ),
        },
        "interpretation": {
            "scope": "prospective synthetic analytic-array stress set only",
            "external_independent_validation": False,
            "native_or_event_validation": False,
            "qualification_claim": "none",
            "credit": 0,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
        },
        "execution": {
            "device": "CPU analytic arrays only",
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "one_minute_load_at_start": float(load_one),
            "process_visible_cpu_capacity": int(cpu_capacity),
            "resource_gate": LOAD_GATE_SCHEMA,
            "elapsed_seconds": float(time.monotonic() - start),
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "native_or_tracer_started": False,
            "solver_started": False,
            "gpu_started": False,
            "worker_or_queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "code_bindings": design_record["code_bindings"],
    }


def run(design_record: dict[str, Any]) -> dict[str, Any]:
    verify_design(design_record)
    load_one, cpu_capacity = _load_snapshot()
    return _evaluate(design_record, load_one, cpu_capacity)


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    design_parser = subparsers.add_parser("design")
    design_parser.add_argument("--output", type=Path, required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--design", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "design":
        value = design()
        _write_new_json(args.output, value)
        print(json.dumps({"status": "design_frozen", "design_sha256": design_sha256(value), "path": str(args.output)}, sort_keys=True))
        return 0

    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing file: {args.output}")
    if not args.output.parent.is_dir():
        raise FileNotFoundError(f"parent directory does not exist: {args.output.parent}")
    try:
        profile = run(json.loads(args.design.read_text(encoding="utf-8")))
    except ProfileDeferred as exc:
        print(json.dumps({"status": "deferred_resource_gate", "profile_started": False, "reason": str(exc)}, sort_keys=True))
        return 2
    _write_new_json(args.output, profile)
    print(json.dumps({
        "status": "completed_synthetic_only",
        "receipt": str(args.output),
        "summary": profile["summary"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
