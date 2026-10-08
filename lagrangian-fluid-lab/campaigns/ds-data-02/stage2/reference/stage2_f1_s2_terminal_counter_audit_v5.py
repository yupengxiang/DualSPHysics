#!/usr/bin/env python3
"""Audit F1-S2 coarse/fine terminal counters against the official source.

The audit reads only RunPARTs, Run.csv, Run.out, DtAllInfo, and the local
official v5.4 source snippets.  It never opens BI4/H5 fields and never infers
an unsaved terminal state.  The coarse and fine runs are kept as separate
actual saved-time axes; the one-row counter convention remains UNKNOWN when
the text artifacts do not identify it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.f1-s2-terminal-counter-audit.v5"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
FINE_REPORT = REFERENCE / "stage2_f1_s2_fine_terminal_savedt_audit_v4.json"
OFFICIAL = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/src/source")
COARSE_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/"
    "F1_S2_SPATIAL_COARSE_DP0p022500_FULL4S_SAMECFL_SAVEDT/"
    "f1-s2-coarse-dp0225-samecfl-full4s-savedt-v6-primary-001"
)
FINE_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/"
    "F1_S2_INTERVAL_DP0p017_FULL4S_SAMECFL_SAVEDT_DENSE/"
    "f1-s2-fine-dp017-samecfl-full4s-savedt-v5-primary-001"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_runparts(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for item in csv.DictReader(lines, delimiter=";"):
        part_raw = (item.get("Part") or "").strip()
        time_raw = (item.get("TimeStep [s]") or "").strip().split()[0]
        if not part_raw.isdigit():
            continue
        steps_raw = (item.get("Steps") or "").strip().replace(",", "")
        dtmin_count_raw = (item.get("DTsMin") or "").strip().replace(",", "")
        try:
            row = {
                "part": int(part_raw),
                "time_s": float(time_raw),
                "steps": int(steps_raw),
                "dts_min_count": int(dtmin_count_raw),
                "dtmin_s": float((item.get("DtMin [s]") or "0").strip()),
                "dtmax_s": float((item.get("DtMax [s]") or "0").strip()),
            }
        except ValueError as exc:
            raise ValueError(f"invalid RunPARTs row in {path}: {item}") from exc
        if not all(math.isfinite(float(row[key])) for key in ("time_s", "dtmin_s", "dtmax_s")):
            raise ValueError(f"non-finite RunPARTs row in {path}")
        rows.append(row)
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs is not contiguous from zero: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs times are not increasing: {path}")
    return {
        "rows": rows,
        "count": len(rows),
        "terminal_part": rows[-1]["part"],
        "terminal_time_s": rows[-1]["time_s"],
        "steps_sum": sum(row["steps"] for row in rows),
        "dts_min_count_sum": sum(row["dts_min_count"] for row in rows),
        "terminal_interval_steps": rows[-1]["steps"],
        "terminal_dtmin_s": rows[-1]["dtmin_s"],
        "terminal_dtmax_s": rows[-1]["dtmax_s"],
    }


def parse_run_csv(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_line = next(line for line in lines if line.startswith("#RunName;"))
    data_line = next(line for line in lines if line.strip() and not line.startswith("#"))
    header = header_line[1:].split(";")
    values = data_line.split(";")
    if len(header) != len(values):
        raise ValueError(f"Run.csv header/data width mismatch: {path}")
    value = dict(zip(header, values))

    def integer(key: str) -> int | None:
        raw = value.get(key, "").replace(",", "").strip()
        return int(raw) if raw else None

    def number(key: str) -> float | None:
        raw = value.get(key, "").strip()
        return float(raw) if raw else None

    return {
        "run_name": value.get("RunName"),
        "steps": integer("Steps"),
        "physical_time_text": value.get("PhysicalTime"),
        "physical_time_s_rounded": number("PhysicalTime"),
        "part_files": integer("PartFiles"),
        "dp_m": number("Dp"),
        "h_m": number("H"),
        "version_text": value.get("Rcode-VersionInfo"),
        "raw_keys": sorted(value),
    }


def parse_run_out(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Steps of simulation\.*:\s*([0-9,]+)", text)
    if not match:
        raise ValueError(f"Run.out has no simulation step summary: {path}")
    return {"steps": int(match.group(1).replace(",", "")), "matched_text": match.group(0)}


def parse_dtall(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    reader = csv.DictReader(lines, delimiter=";")
    rows: list[dict[str, float]] = []
    for item in reader:
        raw_time = (item.get("Time [s]") or "").strip()
        raw_dt = (item.get("Dtf [s]") or "").strip()
        if not raw_time or not raw_dt:
            continue
        time_s = float(raw_time)
        dt_s = float(raw_dt)
        if not math.isfinite(time_s) or not math.isfinite(dt_s):
            raise ValueError(f"non-finite DtAllInfo row in {path}")
        rows.append({"time_s": time_s, "dt_s": dt_s})
    if not rows:
        raise ValueError(f"DtAllInfo has no numeric rows: {path}")
    return {
        "rows": len(rows),
        "first_time_s": rows[0]["time_s"],
        "last_start_time_s": rows[-1]["time_s"],
        "last_dt_s": rows[-1]["dt_s"],
        "last_end_time_s": rows[-1]["time_s"] + rows[-1]["dt_s"],
        "sum_dt_s": sum(row["dt_s"] for row in rows),
        "max_continuity_error_s": max(
            abs((left["time_s"] + left["dt_s"]) - right["time_s"])
            for left, right in zip(rows, rows[1:])
        ) if len(rows) > 1 else 0.0,
    }


def source_excerpt(path: Path, start: int, end: int) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {
        "file": record(path),
        "line_start": start,
        "line_end": end,
        "text": lines[start - 1:end],
    }


def audit_run(label: str, root: Path, report: Path | None = None) -> dict[str, Any]:
    output = root / "solver_output"
    runparts_path = output / "RunPARTs.csv"
    run_csv_path = output / "Run.csv"
    run_out_path = output / "Run.out"
    dtall_path = output / "DtAllInfo.csv"
    runparts = read_runparts(runparts_path)
    run_csv = parse_run_csv(run_csv_path)
    run_out = parse_run_out(run_out_path)
    dtall = parse_dtall(dtall_path)
    if abs(dtall["last_end_time_s"] - runparts["terminal_time_s"]) > 2.0e-9:
        raise ValueError(f"{label}: DtAllInfo endpoint does not close terminal saved Part")
    return {
        "label": label,
        "run_root": str(root.resolve()),
        "inputs": {name: record(path) for name, path in {
            "runparts": runparts_path,
            "run_csv": run_csv_path,
            "run_out": run_out_path,
            "dtall": dtall_path,
        }.items()},
        "runparts": {key: value for key, value in runparts.items() if key != "rows"},
        "run_csv": run_csv,
        "run_out": run_out,
        "dtall": dtall,
        "counter_relation": {
            "runparts_steps_sum_minus_dtall_rows": runparts["steps_sum"] - dtall["rows"],
            "runparts_steps_sum_minus_run_out_steps": runparts["steps_sum"] - run_out["steps"],
            "run_out_steps_minus_dtall_rows": run_out["steps"] - dtall["rows"],
            "status": "UNKNOWN_COUNTING_CONVENTION_NO_UNSAVED_TERMINAL_STATE_INFERRED",
        },
        "endpoint_relation": {
            "saved_part_time_s": runparts["terminal_time_s"],
            "dtall_last_start_plus_dt_s": dtall["last_end_time_s"],
            "delta_s": dtall["last_end_time_s"] - runparts["terminal_time_s"],
            "status": "PASS_SAVED_WINDOW_CLOSED_BY_DTALL_ENDPOINT",
        },
        "report_binding": record(report) if report and report.is_file() else "NOT_BOUND",
    }


def run() -> dict[str, Any]:
    jsph_single = OFFICIAL / "JSphGpuSingle.cpp"
    jsph_gpu = OFFICIAL / "JSphGpu.cpp"
    save_dt = OFFICIAL / "JDsSaveDt.cpp"
    output = {
        "schema": SCHEMA,
        "status": "ACTUAL_F1_S2_SAVEDT_COUNTER_AUDIT",
        "preparation_source_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "scope": {
            "native_or_h5_read_by_this_worker": False,
            "inputs": "RunPARTs.csv, Run.csv, Run.out, DtAllInfo.csv, official v5.4 source excerpts, prior fine audit JSON",
            "full_native_tree_scanned": False,
            "terminal_state_after_last_saved_part": "UNKNOWN_NOT_READ_FROM_NATIVE_PAYLOAD",
            "unsaved_terminal_step_inferred": False,
        },
        "official_source_provenance": "SOURCE_RANGES_AUDIT_ONLY; actual solver binary provenance remains UNKNOWN unless receipt closes it",
        "official_source_evidence": {
            "main_loop_and_save": source_excerpt(jsph_single, 998, 1047),
            "finish_run": source_excerpt(jsph_single, 1144, 1159),
            "dtvariable_records_before_step_increment": source_excerpt(jsph_gpu, 1103, 1146),
            "savedt_flush": source_excerpt(save_dt, 273, 284),
        },
        "runs": {
            "coarse_dp0225_same_cfl": audit_run("coarse_dp0225_same_cfl", COARSE_ROOT),
            "fine_dp017_same_cfl": audit_run("fine_dp017_same_cfl", FINE_ROOT, FINE_REPORT),
        },
        "terminal_semantics": {
            "saved_time_authority": "actual RunPARTs.csv Part/time rows",
            "DtAllInfo_role": "saved-window detailed dt rows; endpoint is checked against the last saved Part",
            "Run_out_and_Run_csv_role": "reported cumulative counters/rounded summary; not used to create an extra native frame",
            "counter_mismatch_policy": "preserve per-file counts and UNKNOWN counting convention; no extra terminal integration or state is claimed",
            "query_4s_policy": "EXACT only if RunPARTs timestamp equals 4.0 within declared tolerance; otherwise BRACKETED/UNKNOWN without extrapolation",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = run()
    atomic_json(args.output.resolve(), value)
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
