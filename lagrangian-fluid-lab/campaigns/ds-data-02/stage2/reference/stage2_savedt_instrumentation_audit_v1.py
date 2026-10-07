#!/usr/bin/env python3
"""Audit official v5.4 per-step SaveDt evidence and one completed F4 canary.

This is a read-only preparation audit.  It reads the official XML/source
documents and the small F4 receipt/RunPARTs/Run.out metadata, never opens an
HDF5 file, never decodes a particle frame, and never starts a solver.  The
result records exactly which files would provide per-final-step dt values in a
future source-bound instrumentation rerun.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.savedt-instrumentation-audit.v1"
REPO = Path(__file__).resolve().parents[5]
OFFICIAL = REPO / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F4_ATTEMPT = DATA_ROOT / (
    "families/F4/F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/"
    "f4-s1-full-window-coarse-dp01230-v4-primary-001"
)
RECEIPT = F4_ATTEMPT / "execution-receipt.json"
RUNPARTS = F4_ATTEMPT / "solver_output/RunPARTs.csv"
RUNOUT = F4_ATTEMPT / "solver_output/Run.out"
DOC = OFFICIAL / "doc/xml_format/_FmtXML_SaveDt.xml"
SAMPLE = OFFICIAL / "examples/others/SaveDt/Case5aSvdt_8k.xml"
SAVE_DT_CPP = OFFICIAL / "src/source/JDsSaveDt.cpp"
SAVE_DT_H = OFFICIAL / "src/source/JDsSaveDt.h"
JSPH_CPP = OFFICIAL / "src/source/JSph.cpp"
JSPH_CPU_CPP = OFFICIAL / "src/source/JSphCpu.cpp"
JSPH_GPU_CPP = OFFICIAL / "src/source/JSphGpu.cpp"
QUERY_TIMES = (0.0, 0.3, 0.6, 0.9, 1.2)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def source_line(path: Path, needle: str) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    matches = [index + 1 for index, line in enumerate(lines) if needle in line]
    if not matches:
        raise ValueError(f"source needle not found: {path}: {needle}")
    return {"file": file_record(path), "needle": needle, "lines": matches}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def runparts_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    if not lines:
        raise ValueError("RunPARTs has no header/data")
    for row in csv.DictReader(lines, delimiter=";"):
        if row.get("Part", "").isdigit():
            rows.append(row)
    if not rows:
        raise ValueError("RunPARTs has no numeric rows")
    return rows


def parse_dt_summary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"DtMin=([0-9.eE+-]+)", text)
    clamp = re.search(r"DTs adjusted to DtMin\.*:\s*([0-9]+)", text)
    return {
        "run_out": file_record(path),
        "aggregate_dt_min_s": float(match.group(1)) if match else "UNKNOWN",
        "aggregate_clamp_count": int(clamp.group(1)) if clamp else "UNKNOWN",
        "per_step_sequence": "NOT_PRESENT_IN_RUN_OUT",
    }


def bracket(times: list[float], query: float) -> dict[str, Any]:
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW"}
    right = 0
    while right < len(times) and times[right] < query:
        right += 1
    if right == 0:
        return {
            "query_time_s": query,
            "status": "EXACT_OR_LEFT",
            "lower_index": 0,
            "upper_index": 0,
            "lower_time_s": times[0],
            "upper_time_s": times[0],
        }
    if right == len(times):
        right -= 1
    if times[right] == query:
        return {
            "query_time_s": query,
            "status": "EXACT",
            "lower_index": right,
            "upper_index": right,
            "lower_time_s": times[right],
            "upper_time_s": times[right],
        }
    left = right - 1
    return {
        "query_time_s": query,
        "status": "BRACKETED",
        "lower_index": left,
        "upper_index": right,
        "lower_time_s": times[left],
        "upper_time_s": times[right],
        "interpolation_fraction": (query - times[left]) / (times[right] - times[left]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    receipt = load_json(RECEIPT)
    rows = runparts_rows(RUNPARTS)
    times = [float(row["TimeStep [s]"]) for row in rows]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("RunPARTs physical times are not strictly increasing")
    raw_root = F4_ATTEMPT / "solver_output/data"
    parts = sorted(raw_root.glob("Part_*.bi4"))
    expected_count = 2401
    expected_raw_bytes = 3_649_738_491
    if len(parts) != expected_count:
        raise ValueError(f"F4 canary Part count changed: {len(parts)} != {expected_count}")
    if sum(path.stat().st_size for path in parts) != expected_raw_bytes:
        raise ValueError("F4 canary raw Part byte sum changed")
    if [path.name for path in parts] != [f"Part_{index:04d}.bi4" for index in range(expected_count)]:
        raise ValueError("F4 canary Part numbering is not contiguous")

    # The source snippets are deliberately represented by path/hash/line
    # references; this report does not copy a mutable source file.
    evidence = {
        "xml_contract": {
            "savedt_fields": ["start", "finish", "interval", "fullinfo", "alldt"],
            "finish_zero_semantics": "official Config maps finish<=0 to DBL_MAX (no time limit)",
            "interval_negative_semantics": "official Config maps interval<0 to TimeOut; use explicit positive interval here",
            "documentation": file_record(DOC),
            "sample": file_record(SAMPLE),
        },
        "source_semantics": {
            "config": source_line(SAVE_DT_CPP, "if(TimeFinish<=0)TimeFinish=DBL_MAX;"),
            "interval_grouping": source_line(SAVE_DT_CPP, "SizeValuesSave=max(1u,min(GetSizeValues(),unsigned(timeout/TimeInterval)));"),
            "dt_statistics_header": source_line(SAVE_DT_CPP, 'scsv << "Time [s];Values"'),
            "all_dt_header": source_line(SAVE_DT_CPP, 'scsv << "Time [s];Dtf [s]"'),
            "all_dt_write": source_line(SAVE_DT_CPP, "AllDts[CountAllDts]=TDouble2(timestep,dtfinal);"),
            "all_dt_final_save": source_line(SAVE_DT_CPP, "if(AllDt)SaveFileAllDts();"),
            "per_step_addvalues": {
                "cpu": source_line(JSPH_CPU_CPP, "if(SaveDt)SaveDt->AddValues(TimeStep,dt,dt1*CFLnumber"),
                "gpu": source_line(JSPH_GPU_CPP, "if(SaveDt)SaveDt->AddValues(TimeStep,dt,dt1*CFLnumber"),
            },
            "clamp_before_savedt": {
                "cpu": source_line(JSPH_CPU_CPP, "if(dt<double(DtMin))"),
                "gpu": source_line(JSPH_GPU_CPP, "if(dt<double(DtMin))"),
            },
            "runtime_configuration": source_line(JSPH_CPP, "SaveDt->Config(&xml,\"case.execution.special.savedt\",TimeMax,TimePart);"),
            "dtallparticles_parameter": source_line(JSPH_CPP, 'DtAllParticles=(eparms.GetValueInt("DtAllParticles",true,0)==1);'),
            "runparts_dtsmin_count": source_line(JSPH_CPP, '"# DTsMin:  Number of times the Dt is updated with the minimum allowed value'),
            "runparts_window_extrema": source_line(JSPH_CPP, '"# DtMin [s]:  Minimum value of Dt since the previous PART.'),
            "aggregate_clamp_summary": source_line(JSPH_CPP, '"DTs adjusted to DtMin............:'),
        },
    }
    actual_final = times[-1]
    nominal_cli_tmax = float(receipt["request"]["physical_window_s"][1])
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "AUDIT_COMPLETE",
        "current_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                                        capture_output=True, text=True).stdout.strip(),
        "solver_started_by_audit": False,
        "h5_read_by_audit": False,
        "official_binary_not_rebuilt": True,
        "official_v54": {
            "root": str(OFFICIAL),
            "source_contract": evidence,
            "recommended_overlay": {
                "xml_path": "case.execution.special.savedt",
                "start_value": 0.0,
                "finish_value": 0.0,
                "interval_value_s": "same as registered native output cadence, explicit positive value",
                "fullinfo_value": 0,
                "alldt_value": 1,
                "files": ["DtInfo.csv", "DtAllInfo.csv"],
                "DtAllInfo_semantics": "one row per final simulation step, columns Time [s];Dtf [s]",
                "clamp_join": "join DtAllInfo.csv with Run.out aggregate DTs adjusted to DtMin and DtMin; no per-row clamp flag exists",
                "preserve_source_parameters": ["DtAllParticles", "DtMin", "DtFixed", "CFLnumber"],
                "finish_zero_reason": "official Config treats finish<=0 as no limit, so the actual overshoot endpoint is retained",
            },
        },
        "actual_f4_canary": {
            "receipt": file_record(RECEIPT),
            "receipt_status": receipt.get("status"),
            "receipt_returncode": receipt.get("returncode"),
            "receipt_tree_bytes": receipt.get("bytes"),
            "raw_root": str(raw_root),
            "raw_part_count": len(parts),
            "raw_part_bytes": sum(path.stat().st_size for path in parts),
            "runparts": file_record(RUNPARTS),
            "runparts_numeric_rows": len(rows),
            "runparts_first_time_s": times[0],
            "runparts_last_time_s": actual_final,
            "runout_summary": parse_dt_summary(RUNOUT),
            "cli_tmax_s": nominal_cli_tmax,
            "actual_final_minus_cli_tmax_s": actual_final - nominal_cli_tmax,
            "actual_native_output_does_not_cover_cli_nominal_endpoint": actual_final < nominal_cli_tmax,
            "part_files_hashed_by_audit": False,
        },
        "query_brackets_from_RunPARTs_only": [bracket(times, query) for query in QUERY_TIMES],
        "limits": {
            "RunPARTs_DTsMin": "count per saved output interval, not seconds and not a complete step trace",
            "RunPARTs_DtMin_DtMax": "per-output-window extrema only",
            "Run.out_DtMin": "aggregate/summary evidence only",
            "scientific_field_values": "UNKNOWN; this audit does not decode BI4 or read HDF5",
            "scientific_qualification": "UNKNOWN",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"refuse to overwrite {args.output}")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "actual_final_s": actual_final, "frames": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
