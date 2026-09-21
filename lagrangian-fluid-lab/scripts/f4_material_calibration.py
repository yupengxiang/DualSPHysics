#!/usr/bin/env python3
"""Pre-registered, F4-specific manufactured reconstruction calibration.

The calibration uses only the declared F4 source/destination geometry and
analytic velocity fields.  It does not read a CFD trajectory, fit a threshold,
or alter the production support gate.  A run reports the true analytic
velocity error beside the existing Shepard diagnostic and charges every failed
query to an explicit equal-mass unknown budget.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np

from scripts.core_material import (
    F4_DESTINATION_LOW_M,
    F4_DESTINATION_SIZE_M,
    F4_SOURCE_SIZE_M,
    GATE,
    MAXIMUM_SUPPORT_DISTANCE_M,
    NEIGHBOURS,
    REGULARIZATION_M,
    f4_destination_region,
    f4_resting_pool_definition,
    f4_source_region,
    f4_walls,
    seeds_f4,
    CurrentField,
    digest,
)
SCHEMA = "core.material.f4.reconstruction_calibration.v1"
CALIBRATION_REVISION = "F4_reconstruction_manufactured_v1"
DOMAIN_SIZE_M = np.array([1.2, 0.4, 0.6], dtype=np.float64)
VELOCITY_SCALE_MPS = float(np.sqrt(9.81 * F4_SOURCE_SIZE_M[2]))
DEFAULT_SUPPORT_SPACING_M = 0.015
DEFAULT_Q = (0.5, 1.0)
FIELD_IDS = ("constant", "affine_div_free", "quadratic_wall_normal", "smooth_interface")


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash_array(value) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    payload = _canonical({"dtype": array.dtype.str, "shape": array.shape}).encode() + array.tobytes()
    return hashlib.sha256(payload).hexdigest()


def _grid(low, size, counts):
    low = np.asarray(low, dtype=np.float64)
    size = np.asarray(size, dtype=np.float64)
    counts = tuple(int(x) for x in counts)
    axes = [low[i] + (np.arange(counts[i], dtype=np.float64) + 0.5) * size[i] / counts[i]
            for i in range(3)]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def _box_lattice(low, size, spacing):
    low = np.asarray(low, dtype=np.float64)
    size = np.asarray(size, dtype=np.float64)
    count = np.maximum(1, np.floor(size / float(spacing) + 1e-12).astype(int))
    return _grid(low, size, count)


def manufactured_velocity(points, field_id: str) -> np.ndarray:
    """Evaluate a fixed analytic F4 field at arbitrary points."""
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("points must be finite with shape [N,3]")
    normalized = points / DOMAIN_SIZE_M
    x, y, z = normalized.T
    base = VELOCITY_SCALE_MPS * np.array([0.10, -0.05, 0.02])
    affine_matrix = np.array(
        [[0.00, 0.30, 0.10], [-0.20, 0.00, 0.05], [0.15, -0.10, 0.00]],
        dtype=np.float64,
    )
    affine = base + VELOCITY_SCALE_MPS * (normalized @ affine_matrix.T)
    if field_id == "constant":
        return np.broadcast_to(base, points.shape).copy()
    if field_id == "affine_div_free":
        return affine
    if field_id == "quadratic_wall_normal":
        value = affine.copy()
        value[:, 0] += VELOCITY_SCALE_MPS * (0.12 * z * z + 0.08 * x * z)
        value[:, 1] += VELOCITY_SCALE_MPS * (0.05 * (y - 0.5) * z)
        value[:, 2] += VELOCITY_SCALE_MPS * 0.18 * (z - F4_DESTINATION_SIZE_M[2] / DOMAIN_SIZE_M[2]) ** 2
        return value
    if field_id == "smooth_interface":
        value = affine.copy()
        value[:, 0] += VELOCITY_SCALE_MPS * 0.10 * np.sin(2.0 * np.pi * z)
        value[:, 1] += VELOCITY_SCALE_MPS * 0.08 * np.cos(np.pi * x)
        value[:, 2] += VELOCITY_SCALE_MPS * 0.06 * np.sin(2.0 * np.pi * z) * np.cos(np.pi * y)
        return value
    raise ValueError(f"unknown manufactured field: {field_id}")


def query_regions(q: float) -> dict[str, np.ndarray]:
    """Return deterministic F4 source, pool, interface and wall query sets."""
    pool_low = np.asarray(F4_DESTINATION_LOW_M, dtype=np.float64)
    pool_size = np.asarray(F4_DESTINATION_SIZE_M, dtype=np.float64)
    return {
        "source": seeds_f4(512, q),
        "destination": _grid(pool_low, pool_size, (16, 8, 4)),
        "interface": _grid([0.0, 0.0, 0.15], [1.2, 0.4, 0.06], (16, 8, 3)),
        "closed_wall": _grid([0.0, 0.04, 0.03], [0.06, 0.32, 0.12], (3, 8, 4)),
    }


def _gate_failure_counts(diagnostics: dict, gate: dict) -> dict:
    estimated = np.asarray(diagnostics["estimated_interpolation_error_mps"], dtype=np.float64)
    return {
        "effective_sample_size": int(np.count_nonzero(~np.isfinite(diagnostics["effective_sample_size"]) |
                                                       (diagnostics["effective_sample_size"] < gate["minimum_effective_sample_size"]))),
        "geometry_rank": int(np.count_nonzero(~np.isfinite(diagnostics["geometry_rank"]) |
                                                (diagnostics["geometry_rank"] < gate["minimum_geometry_rank"]))),
        "anisotropy": int(np.count_nonzero(~np.isfinite(diagnostics["anisotropy"]) |
                                             (diagnostics["anisotropy"] < gate["minimum_anisotropy"]))),
        "reconstruction_error": int(np.count_nonzero(~np.isfinite(estimated) |
                                                        (estimated > gate["maximum_reconstruction_error_mps"]))),
    }


def _region_report(query, truth, interpolated, passed, diagnostics, weights, gate):
    query = np.asarray(query)
    truth = np.asarray(truth)
    interpolated = np.asarray(interpolated)
    passed = np.asarray(passed, dtype=bool)
    weights = np.asarray(weights, dtype=np.float64)
    if weights.shape != (len(query),) or not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError("calibration weights must be finite and nonnegative")
    total = float(weights.sum())
    if total <= 0:
        raise ValueError("calibration weights must have positive total")
    error = np.linalg.norm(interpolated - truth, axis=1)
    finite_error = np.isfinite(error)
    unknown = ~passed
    unknown_fraction = float(weights[unknown].sum() / total)
    reliable_fraction = float(weights[passed].sum() / total)
    error_gate = float(gate["maximum_reconstruction_error_mps"])
    true_bad = finite_error & (error > error_gate)
    false_safe = true_bad & passed
    false_alarm = finite_error & (error <= error_gate) & ~passed
    return {
        "query_count": int(len(query)),
        "query_hash": _hash_array(query),
        "truth_hash": _hash_array(truth),
        "weights_hash": _hash_array(weights),
        "reliable_count": int(passed.sum()),
        "unknown_count": int(unknown.sum()),
        "reliable_mass_fraction": reliable_fraction,
        "unknown_mass_fraction": unknown_fraction,
        "mass_closure": float(reliable_fraction + unknown_fraction),
        "unknown_budget_max": 0.01,
        "unknown_budget_pass": bool(unknown_fraction <= 0.01),
        "true_error_max_mps": float(np.nanmax(error)) if finite_error.any() else float("inf"),
        "true_error_p95_mps": float(np.nanpercentile(error[finite_error], 95)) if finite_error.any() else float("inf"),
        "true_error_mean_mps": float(np.nanmean(error)) if finite_error.any() else float("inf"),
        "true_error_over_gate_fraction": float(weights[true_bad].sum() / total),
        "diagnostic_false_safe_mass_fraction": float(weights[false_safe].sum() / total),
        "diagnostic_false_alarm_mass_fraction": float(weights[false_alarm].sum() / total),
        "diagnostic_reconstruction_p95_mps": float(np.nanpercentile(diagnostics["estimated_interpolation_error_mps"], 95)),
        "support_distance_p95_m": float(np.nanpercentile(diagnostics["support_distance"], 95)),
        "ess_p05": float(np.percentile(diagnostics["effective_sample_size"], 5)),
        "rank_min": int(np.min(diagnostics["geometry_rank"])),
        "anisotropy_p05": float(np.percentile(diagnostics["anisotropy"], 5)),
        "gate_failure_counts": _gate_failure_counts(diagnostics, gate),
    }


def design() -> dict:
    """Return the immutable calibration registration, without executing it."""
    return {
        "schema": SCHEMA,
        "revision_id": CALIBRATION_REVISION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "F4-specific independent reconstruction calibration; diagnostic only",
        "qualification_claim": "none",
        "source_policy": "analytic/manufactured samples only; no F3 or F4 CFD failure locations are used for fitting",
        "geometry": {
            "source_region": f4_source_region(0.5),
            "destination_region": f4_destination_region(),
            "wall_definition": "f4_walls(): bottom and four closed side faces; top open",
            "event_definition": f4_resting_pool_definition(0.5, dp_m=0.0075)["event_definition"],
            "q_cases": list(DEFAULT_Q),
            "dp_metadata_m": [0.0075],
            "support_spacing_m": DEFAULT_SUPPORT_SPACING_M,
        },
        "manufactured_fields": [
            {
                "id": "constant",
                "expression": "U*[0.10,-0.05,0.02]",
                "truth": "exact constant velocity",
            },
            {
                "id": "affine_div_free",
                "expression": "U*[0.10,-0.05,0.02] + U*A@[x/1.2,y/0.4,z/0.6]",
                "matrix_A": [[0.0, 0.30, 0.10], [-0.20, 0.0, 0.05], [0.15, -0.10, 0.0]],
                "truth": "analytic affine field with trace(A)=0",
            },
            {
                "id": "quadratic_wall_normal",
                "expression": "affine + U*[0.12*z^2+0.08*x*z, 0.05*(y-0.5)*z, 0.18*(z-z_interface)^2]",
                "truth": "analytic wall-normal/interface curvature field",
            },
            {
                "id": "smooth_interface",
                "expression": "affine + U*[0.10*sin(2*pi*z), 0.08*cos(pi*x), 0.06*sin(2*pi*z)*cos(pi*y)]",
                "truth": "analytic smooth interface-scale field",
            },
        ],
        "velocity_scale_mps": VELOCITY_SCALE_MPS,
        "query_regions": {
            "source": {"construction": "seeds_f4(512,q)", "mass_policy": "equal source seed mass; production macro budget"},
            "destination": {"construction": "16x8x4 cell-centre grid in the continuous pool box", "mass_policy": "diagnostic region budget"},
            "interface": {"construction": "16x8x3 cell-centre grid over z=[.15,.21] m", "mass_policy": "diagnostic region budget"},
            "closed_wall": {"construction": "3x8x4 cell-centre slab x=[0,.06] m", "mass_policy": "diagnostic region budget"},
        },
        "backend_binding": {
            "backend": "f3_ckdtree_visible_shepard_distance_v1",
            "weighting": "1/(d^2+eps^2)",
            "neighbours": NEIGHBOURS,
            "regularization_m": REGULARIZATION_M,
            "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
            "gate": dict(GATE),
            "gate_policy": "fixed inherited diagnostic gate; calibration cannot modify it",
        },
        "macro_unknown_budget": {
            "source_denominator": "all 512 equal-weight source seeds per q and field",
            "maximum_unknown_mass_fraction": 0.01,
            "closure_tolerance": 1e-12,
            "unknown_policy": "every failed support query remains unknown and is included in the denominator",
            "failure_policy": "budget failure is reported as calibration failure; never repair by changing the F3 gate",
        },
        "acceptance": {
            "constant_true_error_max_mps": 1e-12,
            "all_rows_mass_closure_abs_error_max": 1e-12,
            "source_rows_unknown_mass_fraction_max": 0.01,
            "report_required": ["true_error", "diagnostic_error", "false_safe_mass", "false_alarm_mass", "gate_failure_components"],
            "qualification": "none; this calibrates diagnostic observability and error budget only",
        },
        "execution": {
            "device": "CPU",
            "gpu": False,
            "ledger": False,
            "slot": False,
            "matrix_scope": "8 bounded q/field combinations (2 q values x 4 analytic fields, with 4 diagnostic regions each), not the 33-cell scientific matrix",
            "commands": {
                "write_design": ".venv/bin/python -m scripts.f4_material_calibration design --output <design.json>",
                "run": ".venv/bin/python -m scripts.f4_material_calibration run --design <design.json> --output <receipt.json>",
            },
        },
        "code_provenance": {
            "calibration_script": str(Path(__file__).resolve()),
            "calibration_script_sha256": digest(Path(__file__)),
        },
    }


def run(design_record: dict) -> dict:
    """Execute only the bounded manufactured calibration described by design."""
    if design_record.get("schema") != SCHEMA or design_record.get("qualification_claim") != "none":
        raise ValueError("unexpected or qualified calibration design")
    started = time.monotonic()
    gate = dict(design_record["backend_binding"]["gate"])
    rows = []
    walls = f4_walls()
    spacing = float(design_record["geometry"]["support_spacing_m"])
    for q in design_record["geometry"]["q_cases"]:
        cloud = np.concatenate([
            _box_lattice(f4_destination_region()["box_low_m"], f4_destination_region()["box_size_m"], spacing),
            _box_lattice(f4_source_region(q)["box_low_m"], f4_source_region(q)["box_size_m"], spacing),
        ])
        regions = query_regions(float(q))
        for field_id in FIELD_IDS:
            cloud_velocity = manufactured_velocity(cloud, field_id)
            field = CurrentField(cloud, cloud_velocity)
            for region, query in regions.items():
                truth = manufactured_velocity(query, field_id)
                interpolated, _, passed, diagnostics = field.sample(
                    query, walls, neighbours=NEIGHBOURS,
                    regularization=REGULARIZATION_M, gate=gate,
                    error_estimator="local_residual", return_diagnostics=True,
                )
                weights = np.full(len(query), 1.0 / len(query), dtype=np.float64)
                report = _region_report(query, truth, interpolated, passed, diagnostics, weights, gate)
                report.update({"q": float(q), "field": field_id, "region": region,
                               "cloud_count": int(len(cloud)), "cloud_hash": _hash_array(cloud),
                               "cloud_velocity_hash": _hash_array(cloud_velocity)})
                rows.append(report)
    source_rows = [row for row in rows if row["region"] == "source"]
    return {
        "schema": "core.material.f4.reconstruction_calibration.receipt.v1",
        "design_schema": SCHEMA,
        "design_revision": design_record["revision_id"],
        "design_hash": hashlib.sha256(_canonical(design_record).encode()).hexdigest(),
        "backend_binding": design_record["backend_binding"],
        "rows": rows,
        "source_macro_budget_pass": all(row["unknown_budget_pass"] for row in source_rows),
        "all_mass_closure_pass": all(abs(row["mass_closure"] - 1.0) <= 1e-12 for row in rows),
        "qualification_claim": "none",
        "execution": {
            "device": "CPU", "gpu_started": False, "ledger_touched": False, "slot_acquired": False,
            "elapsed_seconds": time.monotonic() - started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "script_sha256": digest(Path(__file__)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("design")
    d.add_argument("--output", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--design", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "design":
        value = design()
    else:
        value = run(json.loads(args.design.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(args.output)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
