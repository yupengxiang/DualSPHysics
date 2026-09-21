#!/usr/bin/env python3
"""Independent F4 manufactured validation for two bounded backend candidates.

The v2 candidates keep the existing F3 gate and Shepard weights.  One expands
the support cap from 24 to 32 samples to address an ESS-only manufactured
false positive; the other retains 24 samples and adds the local affine query
bias estimate.  This module uses held-out q values and new analytic fields so
the candidates are not selected from the original 32-row result by a fitted
threshold.
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
    F4_AFFINE_BACKEND,
    F4_AFFINE_NEIGHBOURS,
    F4_DESTINATION_SIZE_M,
    F4_ESS32_BACKEND,
    F4_ESS32_NEIGHBOURS,
    F4_SOURCE_SIZE_M,
    GATE,
    MAXIMUM_SUPPORT_DISTANCE_M,
    NEIGHBOUR_BACKEND,
    NEIGHBOURS,
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


SCHEMA = "core.material.f4.reconstruction_calibration.v2"
REVISION = "F4_reconstruction_manufactured_v2"
Q_CASES = (0.25, 0.75)
SUPPORT_SPACING_M = 0.015
VELOCITY_SCALE_MPS = float(np.sqrt(9.81 * F4_SOURCE_SIZE_M[2]))
FIELD_IDS = ("constant_offset", "cubic_shear", "vortex_interface")
VARIANTS = {
    "baseline24": (NEIGHBOUR_BACKEND, NEIGHBOURS, "local_residual"),
    "f4_ess32_v2": (F4_ESS32_BACKEND, F4_ESS32_NEIGHBOURS, "local_residual"),
    "f4_affine_bound_v2": (F4_AFFINE_BACKEND, F4_AFFINE_NEIGHBOURS,
                            "residual_plus_local_affine_query_bias"),
}


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def manufactured_velocity_v2(points, field_id: str) -> np.ndarray:
    """Evaluate fields absent from the original v1 calibration registration."""
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("points must be finite with shape [N,3]")
    x, y, z = (points / np.array([1.2, 0.4, 0.6], dtype=np.float64)).T
    base = VELOCITY_SCALE_MPS * np.array([0.07, 0.03, -0.04])
    if field_id == "constant_offset":
        return np.broadcast_to(base, points.shape).copy()
    if field_id == "cubic_shear":
        value = np.broadcast_to(base, points.shape).copy()
        value[:, 0] += VELOCITY_SCALE_MPS * (0.13 * x**3 + 0.06 * x * z)
        value[:, 1] += VELOCITY_SCALE_MPS * (-0.09 * y**3 + 0.04 * y * z)
        value[:, 2] += VELOCITY_SCALE_MPS * (0.11 * z**3 - 0.05 * x * y)
        return value
    if field_id == "vortex_interface":
        value = np.broadcast_to(base, points.shape).copy()
        value[:, 0] += VELOCITY_SCALE_MPS * 0.11 * np.sin(2 * np.pi * z) * np.cos(np.pi * y)
        value[:, 1] -= VELOCITY_SCALE_MPS * 0.09 * np.sin(2 * np.pi * z) * np.cos(np.pi * x)
        value[:, 2] += VELOCITY_SCALE_MPS * 0.07 * np.cos(2 * np.pi * x) * np.sin(np.pi * y)
        return value
    raise ValueError(f"unknown v2 manufactured field: {field_id}")


def query_regions(q: float) -> dict[str, np.ndarray]:
    """Held-out source and interface queries, independent of v1 locations."""
    pool = f4_destination_region()
    return {
        "source": seeds_f4(512, q),
        "interface": _grid([0.015, 0.0125, 0.1525], [1.17, 0.375, 0.055], (13, 5, 3)),
    }


def design() -> dict:
    return {
        "schema": SCHEMA,
        "revision_id": REVISION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "independent F4 manufactured backend validation after v1 ESS false-positive diagnosis",
        "qualification_claim": "none",
        "source_policy": "analytic/manufactured fields only; held-out q=.25/.75; no F4 failure positions or dev00 data",
        "geometry": {
            "source_region": f4_source_region(0.25),
            "destination_region": f4_destination_region(),
            "wall_definition": "f4_walls(): bottom and four closed side faces; top open",
            "event_definition": f4_resting_pool_definition(0.25, dp_m=0.0075)["event_definition"],
            "q_cases": list(Q_CASES),
            "dp_metadata_m": 0.0075,
            "support_spacing_m": SUPPORT_SPACING_M,
            "query_regions": {
                "source": "seeds_f4(512,q)",
                "interface": "13x5x3 cell-centre grid in z=[.1525,.2075] m",
            },
        },
        "manufactured_fields": [
            {"id": "constant_offset", "expression": "U*[.07,.03,-.04]", "purpose": "ESS geometry sanity with zero true residual"},
            {"id": "cubic_shear", "expression": "base + U*[.13*x^3+.06*x*z, -.09*y^3+.04*y*z, .11*z^3-.05*x*y]", "purpose": "nonlinear query error"},
            {"id": "vortex_interface", "expression": "base + trigonometric interface-scale swirl", "purpose": "smooth interface query bias"},
        ],
        "backend_candidates": {
            name: {"backend": backend, "neighbours": neighbours, "error_estimator": estimator,
                   "gate": dict(GATE), "weights": "1/(d^2+eps^2)"}
            for name, (backend, neighbours, estimator) in VARIANTS.items()
        },
        "hypotheses": [
            {
                "id": "F4-H1-ess32-support-cap",
                "candidate": "f4_ess32_v2",
                "evidence": "v1 constant source rows had 16/512 ESS-only failures with true error <=1.1e-16, rank=3, anisotropy>=.46, visible=96; fixed k=32 clears those ESS values in the same geometry check",
                "repair": "retain visible cKDTree and Shepard weights; use fixed k=32; retain ESS>=4, rank>=3, anisotropy>=.005, reconstruction cap and unknown<=.01",
            },
            {
                "id": "F4-H2-affine-query-bound",
                "candidate": "f4_affine_bound_v2",
                "evidence": "v1 affine/quadratic/interface fields had true p95 errors .0075-.0146 m/s while local residual p95 was ~1e-16-.00082; affine query-bias estimate tracks .0075-.0143 p95 without a gate change",
                "repair": "retain visible cKDTree, k=24, Shepard weights and fixed gate; use residual_plus_local_affine_query_bias as the reconstruction estimate",
            },
        ],
        "macro_unknown_budget": {
            "source_denominator": "all 512 equal-weight source seeds for each held-out q and field",
            "maximum_unknown_mass_fraction": 0.01,
            "closure_tolerance": 1e-12,
            "failure_policy": "candidate fails if source unknown exceeds .01; no threshold relaxation",
        },
        "acceptance": {
            "all_rows_mass_closure_abs_error_max": 1e-12,
            "constant_source_candidate_unknown_max": 0.01,
            "candidate_gate_is_unchanged": True,
            "report_required": ["true_error", "estimated_error", "ESS/rank/anisotropy/support failures", "false_safe_mass", "false_alarm_mass"],
            "qualification": "none; manufactured calibration only",
        },
        "execution": {
            "device": "CPU", "gpu": False, "ledger": False, "slot": False,
            "bounded_rows": 12,
            "not_the_33_cell_scientific_matrix": True,
            "commands": {
                "write_design": ".venv/bin/python -m scripts.f4_material_calibration_v2 design --output <design.json>",
                "run": ".venv/bin/python -m scripts.f4_material_calibration_v2 run --design <design.json> --output <result.json>",
            },
        },
        "code_provenance": {"calibration_script": str(Path(__file__).resolve()),
                            "calibration_script_sha256": digest(Path(__file__))},
    }


def run(design_record: dict) -> dict:
    if design_record.get("schema") != SCHEMA or design_record.get("qualification_claim") != "none":
        raise ValueError("unexpected or qualified v2 design")
    started = time.monotonic()
    walls = f4_walls()
    rows = []
    for q in design_record["geometry"]["q_cases"]:
        destination = f4_destination_region()
        source = f4_source_region(q)
        cloud = np.concatenate([
            _box_lattice(destination["box_low_m"], destination["box_size_m"], SUPPORT_SPACING_M),
            _box_lattice(source["box_low_m"], source["box_size_m"], SUPPORT_SPACING_M),
        ])
        for field_id in FIELD_IDS:
            cloud_velocity = manufactured_velocity_v2(cloud, field_id)
            fields = {name: CurrentField(cloud, cloud_velocity) for name in VARIANTS}
            for region, query in query_regions(float(q)).items():
                truth = manufactured_velocity_v2(query, field_id)
                variants = {}
                for name, (backend, neighbours, estimator) in VARIANTS.items():
                    interpolated, _, passed, diagnostics = fields[name].sample(
                        query, walls, neighbours=neighbours, regularization=REGULARIZATION_M,
                        gate=GATE, error_estimator=estimator, return_diagnostics=True,
                    )
                    report = _region_report(
                        query, truth, interpolated, passed, diagnostics,
                        np.full(len(query), 1.0 / len(query), dtype=np.float64), GATE,
                    )
                    report.update({"backend": backend, "neighbours": neighbours, "error_estimator": estimator})
                    variants[name] = report
                rows.append({"q": float(q), "field": field_id, "region": region,
                             "query_count": int(len(query)), "cloud_count": int(len(cloud)),
                             "query_hash": _hash_array(query), "cloud_hash": _hash_array(cloud),
                             "truth_hash": _hash_array(truth), "variants": variants})
    source_rows = [row for row in rows if row["region"] == "source"]
    budget = {
        name: all(row["variants"][name]["unknown_budget_pass"] for row in source_rows)
        for name in VARIANTS
    }
    return {
        "schema": "core.material.f4.reconstruction_calibration.v2.receipt",
        "design_schema": SCHEMA,
        "design_revision": design_record["revision_id"],
        "design_hash": hashlib.sha256(_canonical(design_record).encode()).hexdigest(),
        "backend_candidates": design_record["backend_candidates"],
        "rows": rows,
        "source_macro_budget_pass_by_variant": budget,
        "all_mass_closure_pass": all(
            all(abs(row["variants"][name]["mass_closure"] - 1.0) <= 1e-12 for name in VARIANTS)
            for row in rows
        ),
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
    design_parser = sub.add_parser("design")
    design_parser.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--design", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = design() if args.command == "design" else run(json.loads(args.design.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(args.output)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
