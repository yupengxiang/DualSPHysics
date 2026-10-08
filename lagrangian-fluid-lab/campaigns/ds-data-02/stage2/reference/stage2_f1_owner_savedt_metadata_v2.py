#!/usr/bin/env python3
"""Audit a completed F1 owner Savedt run without reading native payloads.

The solver's ``RunPARTs.csv`` is a saved-window summary and ``DtAllInfo.csv``
is the flushed Savedt trace.  This worker records both scopes separately,
preserves non-zero ``DTsMin``/DtMin warnings, and leaves the exact terminal
integration state and scientific qualification UNKNOWN.  It never opens a
BI4/VTK/HDF5 payload and never starts a solver.
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
from typing import Any


SCHEMA = "ds02.stage2.f1.owner-savedt-metadata-audit.v1"
CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"required regular metadata file is missing or symlinked: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256_file(path),
    }


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable audit: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    match = re.match(r"^\s*([^#\s]+)", raw)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_runparts(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(lines, delimiter=";"):
        part = _number(row.get("Part"))
        time_s = _number(row.get("TimeStep [s]"))
        steps = _number(row.get("Steps"))
        dtsmin = _number(row.get("DTsMin"))
        dtmin = _number(row.get("DtMin [s]"))
        dtmax = _number(row.get("DtMax [s]"))
        npf = _number(row.get("NpfSim"))
        if part is None or time_s is None or steps is None:
            continue
        rows.append({
            "part": int(part), "time_s": time_s, "steps": int(steps),
            "dtsmin_count": int(dtsmin) if dtsmin is not None else None,
            "dtmin_s": dtmin, "dtmax_s": dtmax,
            "fluid_count": int(npf) if npf is not None else None,
        })
    if not rows:
        raise ValueError(f"RunPARTs has no numeric rows: {path}")
    rows.sort(key=lambda row: row["part"])
    if [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError("RunPARTs parts are not contiguous from zero")
    if any(b["time_s"] <= a["time_s"] for a, b in zip(rows, rows[1:])):
        raise ValueError("RunPARTs times are not strictly increasing")
    dtsmin_values = [row["dtsmin_count"] for row in rows if row["dtsmin_count"] is not None]
    return {
        "record": record(path),
        "numeric_rows": len(rows),
        "first_part": rows[0],
        "last_part": rows[-1],
        "sum_interval_steps": sum(row["steps"] for row in rows),
        "sum_dtsmin_counts": sum(dtsmin_values) if dtsmin_values else "UNKNOWN",
        "nonzero_dtsmin_parts": [row["part"] for row in rows if (row["dtsmin_count"] or 0) != 0],
        "dtsmin_semantics": "RunPARTs DTsMin is an interval count/summary, not seconds",
    }


def read_dtall(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    rows: list[tuple[float, float]] = []
    for row in csv.DictReader(lines, delimiter=";"):
        time_s = _number(row.get("Time [s]"))
        dt_s = _number(row.get("Dtf [s]"))
        if time_s is None or dt_s is None:
            continue
        rows.append((time_s, dt_s))
    if not rows:
        raise ValueError(f"DtAllInfo has no finite numeric rows: {path}")
    continuity = max(
        (abs(time_s + dt_s - rows[index + 1][0]) for index, (time_s, dt_s) in enumerate(rows[:-1])),
        default=0.0,
    )
    return {
        "record": record(path),
        "data_rows": len(rows),
        "first_start_s": rows[0][0],
        "last_start_s": rows[-1][0],
        "last_dt_s": rows[-1][1],
        "last_row_endpoint_s": rows[-1][0] + rows[-1][1],
        "sum_dtf_s": sum(dt for _, dt in rows),
        "max_adjacent_continuity_error_s": continuity,
        "semantics": "flushed Savedt rows closing the saved-window scope; not a complete per-step trace",
    }


def read_dtinfo(path: Path) -> dict[str, Any]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    rows = list(csv.DictReader(lines, delimiter=";"))
    if not rows:
        raise ValueError(f"DtInfo has no rows: {path}")
    finite_dtf: list[float] = []
    nonfinite_tokens = 0
    for row in rows:
        value = _number(row.get("Dtf_mean [s]"))
        if value is None:
            nonfinite_tokens += 1
        else:
            finite_dtf.append(value)
    return {
        "record": record(path),
        "data_rows": len(rows),
        "finite_dtf_mean_rows": len(finite_dtf),
        "dtf_mean_min_s": min(finite_dtf) if finite_dtf else "UNKNOWN",
        "dtf_mean_max_s": max(finite_dtf) if finite_dtf else "UNKNOWN",
        "nonfinite_or_unparsed_dtf_mean_rows": nonfinite_tokens,
        "semantics": "saved-window aggregate diagnostics; not a complete per-step trace",
    }


def read_runout(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    def find_int(pattern: str) -> int | str:
        match = re.search(pattern, text)
        return int(match.group(1).replace(",", "")) if match else "UNKNOWN"
    return {
        "record": record(path),
        "reported_steps": find_int(r"Steps of simulation\.*:\s*([0-9,]+)"),
        "reported_dtmin_clamps": find_int(r"DTs adjusted to DtMin\.*:\s*([0-9,]+)"),
        "reported_part_files": find_int(r"PART files\.*:\s*([0-9,]+)"),
    }


def build(*, receipt: Path, request: Path, output_root: Path, output: Path) -> dict[str, Any]:
    receipt = receipt.expanduser().resolve()
    request = request.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
    if receipt_value.get("status") not in {"COMPLETED_DEVELOPMENT_UNKNOWN", "completed"}:
        raise ValueError(f"receipt is not a completed development run: {receipt}")
    solver = output_root / "solver_output"
    runparts = read_runparts(solver / "RunPARTs.csv")
    dtall = read_dtall(solver / "DtAllInfo.csv")
    dtinfo = read_dtinfo(solver / "DtInfo.csv")
    runout = read_runout(solver / "Run.out")
    run_csv = record(solver / "Run.csv")
    runpart_steps = runparts["sum_interval_steps"]
    report_steps = runout["reported_steps"]
    warnings: list[str] = []
    if runparts["nonzero_dtsmin_parts"]:
        warnings.append("NONZERO_RUNPARTS_DTSMIN_COUNT_PRESERVED")
    if isinstance(runout["reported_dtmin_clamps"], int) and runout["reported_dtmin_clamps"]:
        warnings.append("NONZERO_RUNOUT_DTMIN_CLAMP_COUNT_PRESERVED")
    if isinstance(report_steps, int) and report_steps != runpart_steps:
        warnings.append("RUNOUT_VS_RUNPARTS_STEP_COUNT_DIFFERENCE_PRESERVED")
    return {
        "schema": SCHEMA,
        "status": "COMPLETED_TEXT_SAVEDT_AUDIT_NO_NATIVE_READ",
        "identity": {
            "family_id": "F1", "sentinel_id": "F1-S1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        },
        "source_binding": {
            "solver_receipt": record(receipt),
            "parent_request": record(request),
            "attempt_id": receipt_value.get("attempt_id", "UNKNOWN"),
            "output_root": str(output_root),
            "output_root_is_receipt_bound": receipt_value.get("filesystem", {}).get("output_root") == str(output_root),
            "launch_argv": receipt_value.get("execution", {}).get("launch_argv", "UNKNOWN"),
        },
        "saved_window": {
            "runparts": runparts,
            "last_saved_time_s": runparts["last_part"]["time_s"],
            "requested_tmax_s": next((float(value.split(":", 1)[1]) for value in receipt_value.get("execution", {}).get("launch_argv", [])
                                      if isinstance(value, str) and value.startswith("-tmax:")), "UNKNOWN"),
        },
        "savedt_trace": {"dtall": dtall, "dtinfo": dtinfo},
        "whole_execution_summary": {"run_out": runout, "run_csv": run_csv},
        "warnings": warnings,
        "interpretation": {
            "exact_terminal_integration_state": "UNKNOWN_NOT_EXPOSED_BY_TEXT_SCOPE",
            "terminal_step_count_after_last_saved_part": "UNKNOWN",
            "dtmin_clamp_history": "aggregate warnings only; no complete per-step clamp trace claimed",
            "DtAllInfo_scope": "saved-window flush scope; not a complete per-step integration trace",
        },
        "scope": {
            "native_payload_read": False, "bi4_decode": False,
            "hdf5_read": False, "partvtk_read": False, "solver_started_by_worker": False,
            "metadata_files": [runparts["record"], dtall["record"], dtinfo["record"], runout["record"], run_csv],
        },
        "qualification": {
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "reason": "Savedt text audit only; no field observer or integration truth claimed",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(receipt=args.receipt, request=args.request, output_root=args.output_root, output=args.output)
    atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output.resolve()), "warnings": value["warnings"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
