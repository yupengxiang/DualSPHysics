#!/usr/bin/env python3
"""Held-out synthetic validation of the exact F4 v3 composition.

This is a bounded analytic-array calibration only.  It validates the exact
``k=32 + residual_plus_local_affine_query_bias`` composition on q and field
families not used by the v2 calibration.  It cannot qualify a native case or
change the fixed F4 gate, denominator, cadence, or event semantics.
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
    F4_DESTINATION_SIZE_M,
    F4_SOURCE_SIZE_M,
    F4_V3_BACKEND,
    F4_V3_ERROR_ESTIMATOR,
    F4_V3_NEIGHBOURS,
    GATE,
    MAXIMUM_SUPPORT_DISTANCE_M,
    REGULARIZATION_M,
    CurrentField,
    digest,
    f4_destination_region,
    f4_resting_pool_definition,
    f4_source_region,
    f4_walls,
    seeds_f4,
)
from scripts.f4_material_calibration import (
    _box_lattice,
    _grid,
    _hash_array,
    _region_report,
)


SCHEMA = "core.material.f4.reconstruction_calibration.v3"
RECEIPT_SCHEMA = "core.material.f4.reconstruction_calibration.v3.receipt"
REVISION = "F4_supportcap_affine_query_bound_v3_heldout_20260922"
Q_CASES = (0.375, 0.875)
FIELD_IDS = ("quintic_shear", "gaussian_interface")
SUPPORT_SPACING_M = 0.015
VELOCITY_SCALE_MPS = float(np.sqrt(9.81 * F4_SOURCE_SIZE_M[2]))


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def manufactured_velocity_v3(points: np.ndarray, field_id: str) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("points must be finite with shape [N,3]")
    x, y, z = (points / np.array([1.2, 0.4, 0.6], dtype=np.float64)).T
    base = VELOCITY_SCALE_MPS * np.array([0.05, -0.04, 0.03])
    if field_id == "quintic_shear":
        value = np.broadcast_to(base, points.shape).copy()
        value[:, 0] += VELOCITY_SCALE_MPS * (0.12 * x**5 - 0.07 * x * y * z)
        value[:, 1] += VELOCITY_SCALE_MPS * (0.09 * y**5 + 0.05 * x * z**2)
        value[:, 2] += VELOCITY_SCALE_MPS * (0.08 * z**5 - 0.04 * x**2 * y)
        return value
    if field_id == "gaussian_interface":
        envelope = np.exp(-((z - 0.30) / 0.12) ** 2)
        value = np.broadcast_to(base, points.shape).copy()
        value[:, 0] += VELOCITY_SCALE_MPS * 0.13 * envelope * np.sin(3.0 * np.pi * x)
        value[:, 1] += VELOCITY_SCALE_MPS * 0.08 * envelope * np.cos(2.0 * np.pi * y)
        value[:, 2] += VELOCITY_SCALE_MPS * 0.10 * envelope * np.sin(2.0 * np.pi * x * y)
        return value
    raise ValueError(f"unknown held-out field: {field_id}")


def query_regions(q: float) -> dict[str, np.ndarray]:
    destination = f4_destination_region()
    return {
        "source": seeds_f4(512, q),
        "interface": _grid([0.0, 0.0, 0.15], [1.2, 0.4, 0.06], (16, 8, 3)),
        "destination": _grid(destination["box_low_m"], destination["box_size_m"], (16, 8, 4)),
    }


def design() -> dict:
    return {
        "schema": SCHEMA,
        "revision_id": REVISION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "held-out analytic validation of the exact F4 v3 reconstruction composition",
        "qualification_claim": "none",
        "source_policy": "held-out analytic fields and q=.375/.875 only; no native failure rows or fitted thresholds",
        "composition": {
            "candidate_id": "f4_supportcap_affine_query_bound_v3",
            "backend": F4_V3_BACKEND,
            "neighbours": F4_V3_NEIGHBOURS,
            "error_estimator": F4_V3_ERROR_ESTIMATOR,
            "weights": "1/(distance_squared+regularization_squared)",
            "regularization_m": REGULARIZATION_M,
            "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
            "gate": dict(GATE),
        },
        "geometry": {
            "source_region": f4_source_region(0.375),
            "destination_region": f4_destination_region(),
            "wall_definition": "f4_walls(): bottom and four closed side faces; top open",
            "event_definition": f4_resting_pool_definition(0.375, dp_m=0.0075)["event_definition"],
            "q_cases": list(Q_CASES),
            "support_spacing_m": SUPPORT_SPACING_M,
        },
        "held_out_fields": [
            {"id": "quintic_shear", "truth": "analytic degree-five shear with cross terms"},
            {"id": "gaussian_interface", "truth": "analytic localized interface-scale field"},
        ],
        "denominator_policy": {
            "source": "all 512 source seeds per q and field",
            "unknown_limit": 0.01,
            "failure_policy": "unknown support remains in the fixed denominator; no survivor renormalization",
        },
        "semantic_invariants": {
            "cadence": "native saved-frame cadence; unchanged",
            "event_semantics": "F4 continuous linear-segment contact/upward/return/residence; unchanged",
            "event_horizon_s": {"initial": 4.34, "maximum_extended": 8.68},
            "t2_macro": False,
            "t2_path": False,
        },
        "execution": {
            "device": "CPU analytic arrays only",
            "native_started": False,
            "gencase_started": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "code_provenance": {"calibration_script": str(Path(__file__).resolve()), "calibration_script_sha256": digest(Path(__file__))},
    }


def run(design_record: dict) -> dict:
    if design_record.get("schema") != SCHEMA or design_record.get("qualification_claim") != "none":
        raise ValueError("unexpected or qualified v3 design")
    composition = design_record["composition"]
    if composition["neighbours"] != F4_V3_NEIGHBOURS or composition["error_estimator"] != F4_V3_ERROR_ESTIMATOR:
        raise ValueError("v3 calibration must bind the exact registered composition")
    started = time.monotonic()
    rows = []
    walls = f4_walls()
    for q in design_record["geometry"]["q_cases"]:
        destination = f4_destination_region()
        source = f4_source_region(float(q))
        cloud = np.concatenate([
            _box_lattice(destination["box_low_m"], destination["box_size_m"], SUPPORT_SPACING_M),
            _box_lattice(source["box_low_m"], source["box_size_m"], SUPPORT_SPACING_M),
        ])
        for field_id in FIELD_IDS:
            cloud_velocity = manufactured_velocity_v3(cloud, field_id)
            field = CurrentField(cloud, cloud_velocity)
            for region, query in query_regions(float(q)).items():
                truth = manufactured_velocity_v3(query, field_id)
                interpolated, _, passed, diagnostics = field.sample(
                    query, walls, neighbours=F4_V3_NEIGHBOURS,
                    regularization=REGULARIZATION_M, gate=GATE,
                    error_estimator=F4_V3_ERROR_ESTIMATOR, return_diagnostics=True,
                )
                report = _region_report(
                    query, truth, interpolated, passed, diagnostics,
                    np.full(len(query), 1.0 / len(query), dtype=np.float64), GATE,
                )
                report.update({
                    "q": float(q), "field": field_id, "region": region,
                    "cloud_count": int(len(cloud)), "cloud_hash": _hash_array(cloud),
                    "truth_hash": _hash_array(truth), "backend": F4_V3_BACKEND,
                    "neighbours": F4_V3_NEIGHBOURS, "error_estimator": F4_V3_ERROR_ESTIMATOR,
                })
                rows.append(report)
    source_rows = [row for row in rows if row["region"] == "source"]
    return {
        "schema": RECEIPT_SCHEMA,
        "design_schema": SCHEMA,
        "design_revision": design_record["revision_id"],
        "design_hash": hashlib.sha256(_canonical(design_record).encode()).hexdigest(),
        "composition": composition,
        "rows": rows,
        "held_out": {"q_cases": list(Q_CASES), "fields": list(FIELD_IDS)},
        "source_macro_budget_pass": all(row["unknown_budget_pass"] for row in source_rows),
        "all_mass_closure_pass": all(abs(row["mass_closure"] - 1.0) <= 1e-12 for row in rows),
        "qualification_claim": "none",
        "credit": 0,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "execution": {
            "device": "CPU analytic arrays only", "native_started": False, "gencase_started": False,
            "solver_started": False, "gpu_started": False, "queue_mutation": 0,
            "registry_mutation": 0, "ledger_mutation": 0,
            "elapsed_seconds": time.monotonic() - started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "script_sha256": digest(Path(__file__)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("design"); d.add_argument("--output", type=Path, required=True)
    r = sub.add_parser("run"); r.add_argument("--design", type=Path, required=True); r.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = design() if args.command == "design" else run(json.loads(args.design.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
