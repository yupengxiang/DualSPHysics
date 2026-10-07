#!/usr/bin/env python3
"""Compare SaveDt row-count and endpoint semantics for the F4 CFL pair.

This forward-only companion reads only the two completed execution receipts,
their ``DtAllInfo.csv``, ``RunPARTs.csv`` and ``Run.out`` text files, and the
official v5.4 source proof used by the v1 helper.  It does not open HDF5 or
native Part payloads and never launches a solver.  The v1 analyzer is imported
unchanged so its conservative GPU/Verlet row-count interpretation remains the
source of the per-run measurements.

The half-CFL result is deliberately kept separate from the same-CFL result:
its endpoint is short of the requested/source endpoint and it reports
aggregate DtMin clamps.  The pair therefore supplies logging/cost evidence and
an explicit timestep/clamp diagnostic, not an unconditional temporal
qualification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

from stage2_savedt_row_count_semantics_v1 import analyze, parse_dtall, record


SCHEMA = "ds02.stage2.savedt-row-count-semantics.v2"
REPO = Path(__file__).resolve().parents[5]
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
SAME_OUTPUT_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/"
    "f4-s1-dp0-savedt-same_cfl-primary-001"
)
HALF_OUTPUT_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/"
    "F4_S1_DP0_SAVEDT_HALF_CFL_DENSE_T1P2/"
    "f4-s1-dp0-savedt-half_cfl-primary-001"
)
SAME_REQUEST = REQUEST_ROOT / "stage2-f4-dp0-savedt-pair-v1/same_cfl.json"
HALF_REQUEST = REQUEST_ROOT / "stage2-f4-dp0-savedt-pair-v1/half_cfl.json"


def with_dt_bounds(result: dict[str, Any]) -> dict[str, Any]:
    dt_path = Path(result["output_text"]["DtAllInfo"]["path"])
    rows = parse_dtall(dt_path)
    result["dt_bounds"] = {
        "min_s": min((dt for _, dt in rows), default=None),
        "max_s": max((dt for _, dt in rows), default=None),
        "row_count_used": len(rows),
    }
    return result


def pair_comparison(same: dict[str, Any], half: dict[str, Any]) -> dict[str, Any]:
    same_counts = same["counts"]
    half_counts = half["counts"]
    same_time = same["time_integrity"]
    half_time = half["time_integrity"]
    return {
        "same_cfl": {
            "dt_rows": same_counts["DtAllInfo_data_rows"],
            "reported_steps": same_counts["Run.out_reported_steps"],
            "runparts_sum_steps": same_counts["RunPARTs_sum_Steps"],
            "aggregate_clamp_count": same_counts["Run.out_aggregate_clamp_count"],
            "endpoint_s": same_time["RunPARTs_final_time_s"],
            "endpoint_minus_requested_s": same_time["RunPARTs_final_time_s"] - same["request"]["requested_window_s"][1],
            "sum_dtf_s": same_time["sum_Dtf_s"],
            "sum_dtf_endpoint_error_s": same_time["sum_Dtf_minus_RunPARTs_endpoint_s"],
            "dt_min_s": same.get("dt_bounds", {}).get("min_s", "UNKNOWN"),
            "dt_max_s": same.get("dt_bounds", {}).get("max_s", "UNKNOWN"),
        },
        "half_cfl": {
            "dt_rows": half_counts["DtAllInfo_data_rows"],
            "reported_steps": half_counts["Run.out_reported_steps"],
            "runparts_sum_steps": half_counts["RunPARTs_sum_Steps"],
            "aggregate_clamp_count": half_counts["Run.out_aggregate_clamp_count"],
            "endpoint_s": half_time["RunPARTs_final_time_s"],
            "endpoint_minus_requested_s": half_time["RunPARTs_final_time_s"] - half["request"]["requested_window_s"][1],
            "sum_dtf_s": half_time["sum_Dtf_s"],
            "sum_dtf_endpoint_error_s": half_time["sum_Dtf_minus_RunPARTs_endpoint_s"],
            "dt_min_s": half.get("dt_bounds", {}).get("min_s", "UNKNOWN"),
            "dt_max_s": half.get("dt_bounds", {}).get("max_s", "UNKNOWN"),
        },
        "pair_diagnostic": {
            "same_vs_half_endpoint_delta_s": same_time["RunPARTs_final_time_s"] - half_time["RunPARTs_final_time_s"],
            "half_endpoint_shortfall_s": half["request"]["requested_window_s"][1] - half_time["RunPARTs_final_time_s"],
            "half_has_aggregate_dtmin_clamps": half_counts["Run.out_aggregate_clamp_count"] not in (0, "UNKNOWN"),
            "same_has_aggregate_dtmin_clamps": same_counts["Run.out_aggregate_clamp_count"] not in (0, "UNKNOWN"),
            "interpretation": "The pair is a logging/cost and timestep/clamp diagnostic. Half-CFL endpoint shortfall and aggregate DtMin clamps prevent unconditional same/half temporal qualification; no per-row clamp locations are inferred.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--same-output-root", type=Path, default=SAME_OUTPUT_ROOT)
    parser.add_argument("--half-output-root", type=Path, default=HALF_OUTPUT_ROOT)
    parser.add_argument("--same-request", type=Path, default=SAME_REQUEST)
    parser.add_argument("--half-request", type=Path, default=HALF_REQUEST)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    same = with_dt_bounds(analyze(args.same_output_root, args.same_request))
    half = with_dt_bounds(analyze(args.half_output_root, args.half_request))
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "ACTUAL_SAME_AND_HALF_TEXT_RECEIPTS_ANALYZED",
        "current_head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
            capture_output=True, text=True,
        ).stdout.strip(),
        "runs": {"same_cfl": same, "half_cfl": half},
        "pair_comparison": pair_comparison(same, half),
        "scope": {
            "reads_hdf5": False,
            "reads_native_payloads": False,
            "starts_solver": False,
            "source_proof_scope": "official v5.4 GPU single / Verlet row-count convention only",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    if args.output.exists():
        raise FileExistsError(f"refuse to overwrite {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "output": str(args.output),
        "same_dt_rows": same["counts"]["DtAllInfo_data_rows"],
        "half_dt_rows": half["counts"]["DtAllInfo_data_rows"],
        "same_clamps": same["counts"]["Run.out_aggregate_clamp_count"],
        "half_clamps": half["counts"]["Run.out_aggregate_clamp_count"],
        "solver_started": False,
        "hdf5_read": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
