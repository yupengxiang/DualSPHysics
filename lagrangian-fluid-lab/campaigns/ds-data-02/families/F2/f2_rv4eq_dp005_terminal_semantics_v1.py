#!/usr/bin/env python3
"""Record terminal native time and exclusion semantics for RV4EQ DP005.

This is a read-only consumer of completed solver output.  It does not decode
PartOut, invoke PartVTKOut, convert BI4, or change any consumed artifact.  The
report deliberately keeps ``NpOut``/``NpOutPos`` as native numerical
exclusions: a position exclusion and its Motive are evidence to be classified
later, not proof of physical spill.  Event timing remains unqualified for the
0.01 s macro-save view.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FAMILY_ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = FAMILY_ROOT / "f2_rv4eq_dp005_terminal_semantics_v1.py"
MASS_PER_FLUID_PARTICLE_KG = 0.000125
CONTINUOUS_INITIAL_MASS_KG = 24.576
EXPECTED_SAVE_S = 0.01
EVENT_SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275
CASES = {
    "CENTER": "F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001",
    "OFFSET": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
}


class SemanticsError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def parse_number(value: str) -> float:
    return float(value.strip().replace(",", ""))


def parse_runparts(path: Path) -> list[dict[str, float]]:
    """Parse all numeric rows, retaining thousands-separated counters."""
    path = require_file(path, "RunPARTs.csv")
    header: list[str] | None = None
    rows: list[dict[str, float]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if header is None:
            header = [item.strip() for item in line.split(";")]
            continue
        values = [item.strip() for item in line.split(";")]
        if len(values) != len(header):
            continue
        record = dict(zip(header, values))
        try:
            rows.append({
                "part": parse_number(record["Part"]),
                "time_s": parse_number(record["TimeStep [s]"]),
                "steps": parse_number(record["Steps"]),
                "NpSave": parse_number(record["NpSave"]),
                "NpSim": parse_number(record["NpSim"]),
                "NpOut": parse_number(record["NpOut"]),
                "NpOutPos": parse_number(record["NpOutPos"]),
                "NpOutRho": parse_number(record["NpOutRho"]),
                "NpOutMov": parse_number(record["NpOutMov"]),
                "NpfSim": parse_number(record["NpfSim"]),
                "NpNormal": parse_number(record["NpNormal"]),
                "DtMin_s": parse_number(record["DtMin [s]"]),
                "DtMax_s": parse_number(record["DtMax [s]"]),
            })
        except (KeyError, ValueError):
            continue
    if not rows:
        raise SemanticsError(f"RunPARTs.csv has no numeric rows: {path}")
    rows.sort(key=lambda row: int(row["part"]))
    parts = [int(row["part"]) for row in rows]
    if parts != list(range(len(rows))):
        raise SemanticsError(f"RunPARTs parts are not contiguous: {path}")
    return rows


def parse_run_csv(path: Path) -> dict[str, Any]:
    """Parse the one-row semicolon Run.csv without treating commas as CSV."""
    path = require_file(path, "Run.csv")
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        raise SemanticsError(f"Run.csv is empty: {path}")
    # The file has a single data line followed by explanatory comments.  The
    # field names are in the line itself in this solver version, so retain
    # positional values that are needed by the audit.
    values = [item.strip() for item in lines[0].split(";")]
    if len(values) < 20:
        raise SemanticsError(f"Run.csv data row is unexpectedly short: {path}")
    return {
        "run_name": values[0],
        "np_total": int(values[3].replace(",", "")),
        "simulation_runtime_s": float(values[4]),
        "segment_runtime_s": float(values[5]),
        "total_runtime_s": float(values[6]),
        "steps": int(values[10].replace(",", "")),
        "physical_time_s": float(values[12]),
        "part_files": int(values[13].replace(",", "")),
        "parts_out": int(values[14].replace(",", "")),
        "max_particles": int(values[15].replace(",", "")),
        "max_cells": int(values[16].replace(",", "")),
        "configuration": values[19],
        "nbound": int(values[20].replace(",", "")),
        "nfixed": int(values[21].replace(",", "")),
        "dp_m": float(values[22]),
        "h_m": float(values[23]),
    }


def terminal_case(background: str, case_dir: Path) -> dict[str, Any]:
    attempts = sorted(case_dir.glob("*/solver_output/RunPARTs.csv"))
    if len(attempts) != 1:
        raise SemanticsError(f"expected exactly one terminal attempt for {background}, found {len(attempts)}")
    runparts_path = attempts[0]
    solver_output = runparts_path.parent
    attempt_root = solver_output.parent
    receipt_path = require_file(attempt_root / "execution-receipt.json", f"{background} execution receipt")
    run_path = require_file(solver_output / "Run.csv", f"{background} Run.csv")
    run_out_path = require_file(solver_output / "Run.out", f"{background} Run.out")
    partout_path = require_file(solver_output / "data/PartOut_000.obi4", f"{background} PartOut_000.obi4")
    part_files = sorted((solver_output / "data").glob("Part_*.bi4"))
    if len(part_files) != 401:
        raise SemanticsError(f"{background} expected 401 full native Part files, found {len(part_files)}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    rows = parse_runparts(runparts_path)
    run_csv = parse_run_csv(run_path)
    times = [row["time_s"] for row in rows]
    intervals = [b - a for a, b in zip(times, times[1:])]
    np_out_sum = int(sum(row["NpOut"] for row in rows))
    np_out_pos_sum = int(sum(row["NpOutPos"] for row in rows))
    np_out_rho_sum = int(sum(row["NpOutRho"] for row in rows))
    np_out_mov_sum = int(sum(row["NpOutMov"] for row in rows))
    row_partition_ok = all(
        row["NpOut"] == row["NpOutPos"] + row["NpOutRho"] + row["NpOutMov"]
        for row in rows
    )
    n_pf_delta = int(rows[0]["NpfSim"] - rows[-1]["NpfSim"])
    nonzero_rows = [row for row in rows if row["NpOut"] != 0]
    initial_fluid = int(rows[0]["NpfSim"])
    final_fluid = int(rows[-1]["NpfSim"])
    source_bindings = {
        str(path): {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
        for path in (receipt_path, run_path, run_out_path, runparts_path, partout_path)
    }
    return {
        "background": background,
        "case_id": case_dir.name,
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "started_at_utc": receipt.get("started_at_utc"),
        "finished_at_utc": receipt.get("finished_at_utc"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "receipt": source_bindings[str(receipt_path)],
        "run_csv": {**source_bindings[str(run_path)], **run_csv},
        "run_out": source_bindings[str(run_out_path)],
        "partout_raw": {
            **source_bindings[str(partout_path)],
            "tool": "PartVTKOut_linux64",
            "decode_status": "pending_partvtkout",
            "motive_status": "unobserved_until_official_partvtkout",
        },
        "native_timeline": {
            "rows": len(rows),
            "first_part": int(rows[0]["part"]),
            "last_part": int(rows[-1]["part"]),
            "first_time_s": times[0],
            "last_time_s": times[-1],
            "save_interval_expected_s": EXPECTED_SAVE_S,
            "save_interval_mean_s": statistics.mean(intervals),
            "save_interval_min_s": min(intervals),
            "save_interval_max_s": max(intervals),
            "save_interval_max_abs_error_s": max(abs(value - EXPECTED_SAVE_S) for value in intervals),
            "first_nonzero_exclusion": None if not nonzero_rows else {
                "part": int(nonzero_rows[0]["part"]),
                "time_s": nonzero_rows[0]["time_s"],
                "NpOut": int(nonzero_rows[0]["NpOut"]),
                "NpOutPos": int(nonzero_rows[0]["NpOutPos"]),
            },
            "last_nonzero_exclusion": None if not nonzero_rows else {
                "part": int(nonzero_rows[-1]["part"]),
                "time_s": nonzero_rows[-1]["time_s"],
                "NpOut": int(nonzero_rows[-1]["NpOut"]),
                "NpOutPos": int(nonzero_rows[-1]["NpOutPos"]),
            },
            "nonzero_exclusion_rows": len(nonzero_rows),
            "dt_min_s": {"first": rows[1]["DtMin_s"], "last": rows[-1]["DtMin_s"], "min": min(row["DtMin_s"] for row in rows[1:]), "max": max(row["DtMin_s"] for row in rows[1:])},
            "dt_max_s": {"first": rows[1]["DtMax_s"], "last": rows[-1]["DtMax_s"], "min": min(row["DtMax_s"] for row in rows[1:]), "max": max(row["DtMax_s"] for row in rows[1:])},
        },
        "native_exclusion_accounting": {
            "initial_fluid_particles": initial_fluid,
            "final_fluid_particles": final_fluid,
            "NpOut_sum": np_out_sum,
            "NpOutPos_sum": np_out_pos_sum,
            "NpOutRho_sum": np_out_rho_sum,
            "NpOutMov_sum": np_out_mov_sum,
            "NpOut_fraction_of_initial_fluid": np_out_sum / initial_fluid,
            "NpfSim_delta": n_pf_delta,
            "NpOut_equals_NpfSim_delta": np_out_sum == n_pf_delta,
            "NpOut_partition_rows_valid": row_partition_ok,
            "native_excluded_mass_kg_using_fluid_particle_mass": np_out_sum * MASS_PER_FLUID_PARTICLE_KG,
            "initial_mass_kg_using_fluid_particle_mass": initial_fluid * MASS_PER_FLUID_PARTICLE_KG,
            "continuous_initial_mass_kg_authority": CONTINUOUS_INITIAL_MASS_KG,
            "mass_is_unknown_until_typed_partvtkout_closure": True,
            "fate_interpretation": "NpOutPos is native numerical position exclusion; it is not physical spill without PartVTKOut Motive, pose, wall, and domain evidence.",
        },
        "qualification": {
            "full_window_completed": receipt.get("status") == "completed" and receipt.get("returncode") == 0 and len(rows) == 401 and abs(times[-1] - 4.0) < 1e-3,
            "timing_qualification": False,
            "timing_reason": "TimeOut=.01 s is a macro-spatial view; the frozen event save half-width is 0.0007336390799938275 s and requires an independently reviewed finer-save trajectory.",
            "q_i": "pending_fullstate_conversion_and_typed_partvtkout_closure",
            "q_n": "pending; native exclusions and coarse/medium/finer observable budgets remain under review",
            "production": "not_evaluated",
        },
    }


def build(data_root: Path = DATA_ROOT) -> dict[str, Any]:
    cases = [terminal_case(background, data_root / "families/F2" / case_id) for background, case_id in CASES.items()]
    return {
        "schema": "ds-data-02.f2.rv4eq-dp005-terminal-semantics.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generator": {"path": str(SCRIPT_PATH), "sha256": sha256(SCRIPT_PATH)},
        "scope": "RV4-equivalent DP005 CENTER/OFFSET terminal native solver semantics",
        "source_policy": "all consumed solver output is read-only; PartVTKOut/fullstate conversion remain separate deferred tasks",
        "continuous_initial_mass_kg": CONTINUOUS_INITIAL_MASS_KG,
        "fluid_particle_mass_kg": MASS_PER_FLUID_PARTICLE_KG,
        "event_save_half_width_budget_s": EVENT_SAVE_HALF_WIDTH_BUDGET_S,
        "cases": cases,
        "status": "terminal_native_semantics_recorded; typed_motive_closure_and_fullstate_conversion_deferred",
        "qualification_claim": "none",
        "production_claim": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.data_root.expanduser().resolve())
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "path": str(output), "sha256": sha256(output), "case_count": len(report["cases"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
