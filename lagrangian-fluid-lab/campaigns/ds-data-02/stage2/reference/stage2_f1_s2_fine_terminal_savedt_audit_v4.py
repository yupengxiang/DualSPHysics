#!/usr/bin/env python3
"""Audit the completed F1-S2 dp=0.017 SaveDt run.

This is a forward-only text audit.  It reads the request, execution receipt,
Run.out/Run.csv, RunPARTs.csv, DtAllInfo.csv and DtInfo.csv, plus small slices
of the official v5.4 source.  It does not open any BI4/HDF5/native particle
payload and it never starts a solver.

The audit keeps two notions of the endpoint separate:

* the last state written as a PART file, and
* the end of the integration loop described by the solver summary.

The official source shows why those are not required to be identical: the
loop stops after a step reaches ``TimeMax``, while the main PART save is only
inside the output-threshold branch and ``FinishRun`` does not call ``SaveData``.
The exact terminal state is therefore left UNKNOWN when it is absent from the
small text evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCHEMA = "ds02.stage2.f1-s2-fine-terminal-savedt-audit.v4"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
RUN_ROOT = DATA_ROOT / (
    "F1_S2_INTERVAL_DP0p017_FULL4S_SAMECFL_SAVEDT_DENSE/"
    "f1-s2-fine-dp017-samecfl-full4s-savedt-v5-primary-001"
)
REQUEST_PATH = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-f1-s2-reference-v5/f1_s2_fine_dp0p017_same_cfl_savedt_full4s.json"
)
OFFICIAL_ROOT = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/src/source"
)
GPU_SINGLE = OFFICIAL_ROOT / "JSphGpuSingle.cpp"
GPU_BASE = OFFICIAL_ROOT / "JSphGpu.cpp"
SAVE_DT = OFFICIAL_ROOT / "JDsSaveDt.cpp"
JSPH = OFFICIAL_ROOT / "JSph.cpp"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def source_range(path: Path, start: int, end: int) -> dict[str, Any]:
    """Record an immutable source range with its file digest and text."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if start < 1 or end < start or end > len(lines):
        raise ValueError(f"invalid source range {path}:{start}-{end}")
    return {
        "file": file_record(path),
        "line_start": start,
        "line_end": end,
        "text": lines[start - 1:end],
    }


def parse_runparts(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            part = (row.get("Part") or "").strip()
            if part.isdigit():
                rows.append(row)
    if not rows:
        raise ValueError(f"no numeric rows in {path}")

    def integer(row: dict[str, str], name: str) -> int:
        return int((row[name] or "0").replace(",", "").strip())

    def real(row: dict[str, str], name: str) -> float:
        return float((row[name] or "0").strip())

    first = rows[0]
    last = rows[-1]
    times = [real(row, "TimeStep [s]") for row in rows]
    query_time = 4.0
    if any(abs(time - query_time) <= 1.0e-12 for time in times):
        query_binding: dict[str, Any] = {
            "query_time_s": query_time,
            "status": "EXACT",
            "exact_saved_time_s": next(time for time in times if abs(time - query_time) <= 1.0e-12),
        }
    elif query_time < times[0] or query_time > times[-1]:
        query_binding = {
            "query_time_s": query_time,
            "status": "OUTSIDE_SAVED_WINDOW",
            "saved_window_s": [times[0], times[-1]],
        }
    else:
        upper = next(index for index, time in enumerate(times) if time > query_time)
        lower = upper - 1
        query_binding = {
            "query_time_s": query_time,
            "status": "BRACKETED",
            "lower_part": int(rows[lower]["Part"]),
            "upper_part": int(rows[upper]["Part"]),
            "lower_time_s": times[lower],
            "upper_time_s": times[upper],
            "bracket_width_s": times[upper] - times[lower],
            "interpolation_fraction": (query_time - times[lower]) / (times[upper] - times[lower]),
        }
    return {
        "numeric_rows": len(rows),
        "first_part": integer(first, "Part"),
        "last_part": integer(last, "Part"),
        "first_time_s": real(first, "TimeStep [s]"),
        "last_time_s": real(last, "TimeStep [s]"),
        "last_part_nstep": integer(last, "Steps"),
        "sum_steps": sum(integer(row, "Steps") for row in rows),
        "sum_dtsmin_counts": sum(integer(row, "DTsMin") for row in rows),
        "last_part_dtmin_s": real(last, "DtMin [s]"),
        "last_part_dtmax_s": real(last, "DtMax [s]"),
        "last_part_npf_sim": integer(last, "NpfSim"),
        "last_part_np_out_mov": integer(last, "NpOutMov"),
        "query_4s_binding": query_binding,
    }


def parse_dtall(path: Path) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or not lines[0].startswith("Time [s];Dtf [s]"):
        raise ValueError(f"unexpected DtAllInfo header: {path}")
    for line in lines[1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split(";")
        if len(fields) != 2:
            raise ValueError(f"unexpected DtAllInfo row: {line!r}")
        rows.append((float(fields[0]), float(fields[1])))
    if not rows:
        raise ValueError(f"no DtAllInfo rows: {path}")
    continuity_error = max(
        abs(time + dt - rows[index + 1][0])
        for index, (time, dt) in enumerate(rows[:-1])
    ) if len(rows) > 1 else 0.0
    last_time, last_dt = rows[-1]
    return {
        "data_rows": len(rows),
        "first_start_s": rows[0][0],
        "last_start_s": last_time,
        "last_dt_s": last_dt,
        "last_row_endpoint_s": last_time + last_dt,
        "sum_dtf_s": sum(dt for _, dt in rows),
        "max_adjacent_continuity_error_s": continuity_error,
    }


def parse_runout(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    def number(pattern: str) -> int | str:
        match = re.search(pattern, text)
        return int(match.group(1).replace(",", "")) if match else "UNKNOWN"

    return {
        "reported_steps": number(r"Steps of simulation\.*:\s*([0-9,]+)"),
        "reported_dtmin_clamps": number(r"DTs adjusted to DtMin\.*:\s*([0-9,]+)"),
        "reported_part_files": number(r"PART files\.*:\s*([0-9,]+)"),
        "step_algorithm": (
            re.search(r"StepAlgorithm=\"([^\"]+)\"", text).group(1)
            if re.search(r"StepAlgorithm=\"([^\"]+)\"", text) else "UNKNOWN"
        ),
    }


def parse_run_csv(path: Path) -> dict[str, Any]:
    # Run.csv intentionally writes its header as a comment line.  Keep that
    # header, remove only its leading marker, and parse the single data row.
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines)
         if line.lstrip().startswith("#RunName;")),
        None,
    )
    if header_index is None:
        raise ValueError(f"Run.csv header not found: {path}")
    header = lines[header_index].lstrip()[1:]
    data_lines = [line for line in lines[header_index + 1:] if line.strip() and not line.lstrip().startswith("#")]
    rows = list(csv.DictReader([header, *data_lines], delimiter=";"))
    if len(rows) != 1:
        raise ValueError(f"expected one Run.csv data row, got {len(rows)}")
    row = rows[0]
    return {
        "reported_steps_text": row.get("Steps", "UNKNOWN"),
        "physical_time_text": row.get("PhysicalTime", "UNKNOWN"),
        "physical_time_semantics": "Run.csv formatted summary; precision is not the exact terminal state time",
        "part_files_text": row.get("PartFiles", "UNKNOWN"),
        "dp_m_text": row.get("Dp", "UNKNOWN"),
        "rcode_version_text": row.get("Rcode-VersionInfo", "UNKNOWN"),
        "output_row": row,
    }


def run_path_records(output_root: Path) -> dict[str, Any]:
    solver = output_root / "solver_output"
    names = {
        "receipt": output_root / "execution-receipt.json",
        "run_out": solver / "Run.out",
        "run_csv": solver / "Run.csv",
        "runparts": solver / "RunPARTs.csv",
        "dtall": solver / "DtAllInfo.csv",
        "dtinfo": solver / "DtInfo.csv",
    }
    return {name: file_record(path) for name, path in names.items()}


def build(output_root: Path = RUN_ROOT, request_path: Path = REQUEST_PATH) -> dict[str, Any]:
    output_root = output_root.resolve()
    request_path = request_path.resolve()
    receipt_path = output_root / "execution-receipt.json"
    receipt = load_json(receipt_path)
    request = load_json(request_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"receipt is not completed successfully: {receipt_path}")

    runparts = parse_runparts(output_root / "solver_output/RunPARTs.csv")
    dtall = parse_dtall(output_root / "solver_output/DtAllInfo.csv")
    runout = parse_runout(output_root / "solver_output/Run.out")
    run_csv = parse_run_csv(output_root / "solver_output/Run.csv")

    command = receipt.get("request", {}).get("command", request.get("command", []))
    tmax = next(
        (float(item.split(":", 1)[1]) for item in command
         if isinstance(item, str) and item.startswith("-tmax:")),
        None,
    )
    if tmax is None:
        raise ValueError("no -tmax in completed request command")
    last_saved = runparts["last_time_s"]
    shortfall = tmax - last_saved
    dtall_endpoint = dtall["last_row_endpoint_s"]
    dtall_vs_saved = dtall_endpoint - last_saved
    runpart_steps = runparts["sum_steps"]
    reported_steps = runout["reported_steps"]
    dtall_rows = dtall["data_rows"]

    if isinstance(reported_steps, int) and reported_steps != runpart_steps:
        raise ValueError("Run.out and RunPARTs step totals disagree")
    if abs(dtall["sum_dtf_s"] - last_saved) > 1e-9:
        raise ValueError("DtAllInfo sum does not close the last saved PART")

    # The exact terminal integration state is not in any text record used here.
    # Keep this explicit even though Run.csv's rounded PhysicalTime is larger
    # than the last saved PART time.
    # RunPARTs ``Steps`` is an interval count, not a cumulative Nstep
    # counter.  It cannot be subtracted from Run.out's cumulative summary.
    terminal_steps_after_saved = "UNKNOWN_NOT_DERIVABLE_FROM_INTERVAL_STEPS"
    source_evidence = {
        "main_loop_and_part_save": source_range(GPU_SINGLE, 998, 1047),
        "finish_run": source_range(GPU_SINGLE, 1144, 1159),
        "verlet_calls_dtvariable_final": source_range(GPU_SINGLE, 761, 775),
        "dtvariable_records_before_step_increment": source_range(GPU_BASE, 1103, 1146),
        "savedt_config": source_range(JSPH, 2328, 2333),
        "savedt_xml_and_finish_default": source_range(SAVE_DT, 72, 101),
        "savedt_all_rows": source_range(SAVE_DT, 175, 192),
        "savedt_add_and_flush": source_range(SAVE_DT, 239, 276),
    }

    return {
        "schema": SCHEMA,
        "status": "COMPLETED_TEXT_AUDIT_TERMINAL_ENDPOINT_SEPARATED",
        "generated_by": file_record(Path(__file__).resolve()),
        "scope": {
            "reads": [
                "completed execution receipt",
                "request JSON",
                "Run.out",
                "Run.csv",
                "RunPARTs.csv",
                "DtAllInfo.csv",
                "DtInfo.csv",
                "official DualSPHysics v5.4 source text ranges",
            ],
            "native_payload_read": False,
            "hdf5_read": False,
            "solver_started_by_audit": False,
        },
        "source_binding": {
            "sentinel_id": "F1-S2",
            "family_id": "F1",
            "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
            "request": file_record(request_path),
            "completed_receipt": file_record(receipt_path),
            "attempt_id": receipt.get("request", {}).get("attempt_id", "UNKNOWN"),
            "case_id": receipt.get("request", {}).get("case_id", "UNKNOWN"),
            "command": command,
            "requested_tmax_s": tmax,
            "requested_tout_s": next(
                (float(item.split(":", 1)[1]) for item in command
                 if isinstance(item, str) and item.startswith("-tout:")),
                "UNKNOWN",
            ),
            "input_hashes_at_launch": receipt.get("input_hashes_at_launch", "UNKNOWN"),
            "terminal_storage_guard": receipt.get("terminal_storage_guard", "UNKNOWN"),
            "solver_binary_sha256_from_receipt": receipt.get("binary_sha256", "UNKNOWN"),
            "solver_version_text_from_Run_csv": run_csv["rcode_version_text"],
            "official_source_to_binary_provenance": "UNKNOWN_NOT_CRYPTOGRAPHICALLY_LINKED_BY_RECEIPT; source ranges below are an audit reference for the local v5.4 source tree",
        },
        "evidence_files": run_path_records(output_root),
        "observed_saved_window": {
            "part_rows": runparts["numeric_rows"],
            "first_saved_part_time_s": runparts["first_time_s"],
            "last_saved_part": runparts["last_part"],
            "last_saved_part_time_s": last_saved,
            "requested_tmax_s": tmax,
            "last_saved_shortfall_s": shortfall,
            "classification": "OUTPUT_CADENCE_THRESHOLD_BELOW_REQUESTED_TMAX",
            "runpart_steps_sum": runpart_steps,
            "last_part_interval_steps": runparts["last_part_nstep"],
            "runpart_dtsmin_count_sum": runparts["sum_dtsmin_counts"],
            "last_part_dtmin_s": runparts["last_part_dtmin_s"],
            "last_part_dtmax_s": runparts["last_part_dtmax_s"],
            "last_part_fluid_count": runparts["last_part_npf_sim"],
            "last_part_excluded_movement_count": runparts["last_part_np_out_mov"],
            "run_csv_part_files_text": run_csv["part_files_text"],
        },
        "savedt_trace": {
            "dtall_data_rows": dtall_rows,
            "dtall_first_start_s": dtall["first_start_s"],
            "dtall_last_start_s": dtall["last_start_s"],
            "dtall_last_dt_s": dtall["last_dt_s"],
            "dtall_last_row_endpoint_s": dtall_endpoint,
            "dtall_sum_dtf_s": dtall["sum_dtf_s"],
            "dtall_last_row_vs_last_saved_s": dtall_vs_saved,
            "dtall_sum_vs_last_saved_s": dtall["sum_dtf_s"] - last_saved,
            "dtall_max_adjacent_continuity_error_s": dtall["max_adjacent_continuity_error_s"],
            "dtall_closes_last_saved_part": True,
            "dtinfo_semantics": "saved-window aggregate rows; not treated as a complete per-step trace",
        },
        "whole_execution_text_summary": {
            "run_out_reported_steps": reported_steps,
            "run_out_reported_dtmin_clamps": runout["reported_dtmin_clamps"],
            "run_out_reported_part_files": runout["reported_part_files"],
            "run_out_step_algorithm": runout["step_algorithm"],
            "run_csv_steps_text": run_csv["reported_steps_text"],
            "run_csv_physical_time_text": run_csv["physical_time_text"],
            "run_csv_physical_time_is_rounded_summary": True,
            "terminal_steps_after_last_saved_part": terminal_steps_after_saved,
            "exact_terminal_time_s": "UNKNOWN_NOT_EXPOSED_BY_TEXT_EVIDENCE",
            "terminal_state_saved_as_distinct_part": "UNKNOWN_NOT_EXPOSED_BY_TEXT_EVIDENCE",
            "terminal_closure": "UNKNOWN_COUNTING_CONVENTION_AND_TERMINAL_STATE",
        },
        "official_source_evidence": source_evidence,
        "interpretation": {
            "source_proven": [
                "the main loop integrates while TimeStep < TimeMax and increments TimeStep/Nstep after ComputeStep",
                "main PART output is conditional on TimeStep >= TimePartNext (or minimum-fluid stop)",
                "after SaveData, the next output threshold is scheduled; there is no unconditional SaveData after loop exit",
                "FinishRun writes the summary and final RunPARTs metadata but does not call SaveData",
                "Verlet ComputeStep calls DtVariable(true), and DtVariable records the dt against the current pre-increment TimeStep",
                "DtAllInfo rows are flushed by JDsSaveDt::SaveData and therefore close only the saved/flush scope visible in the file",
            ],
            "not_proven_from_available_text": [
                "the exact origin of the one-row difference between RunPARTs/Run.out step counts and DtAllInfo data rows",
                "the exact terminal step count, TimeStep and terminal state after the last saved PART",
                "a complete per-step clamp history beyond the aggregate RunPARTs/Run.out counters",
            ],
            "counter_count_relation": {
                "runparts_sum_steps": runpart_steps,
                "run_out_reported_steps": reported_steps,
                "dtall_data_rows": dtall_rows,
                "relation_status": "UNKNOWN_COUNTING_CONVENTION",
            },
        },
        "common_window_for_f1_s2_grid_comparison": {
            "saved_state_window_s": [0.0, last_saved],
            "query_time_4s_is_exact_saved": runparts["query_4s_binding"]["status"] == "EXACT",
            "query_time_4s_status": runparts["query_4s_binding"]["status"],
            "query_time_4s_binding": runparts["query_4s_binding"],
            "requested_source_endpoint_s": tmax,
            "endpoint_comparison_status": "UNKNOWN_PENDING_COARSE_COMPLETION_AND_EXACT_TERMINAL_STATE",
            "policy": "no extrapolation beyond last saved native frame; use actual RunPARTs timestamps",
        },
        "next_observer_preparation": {
            "status": "READY_METADATA_ONLY_PENDING_PARENT_CPU_GUARD",
            "source_output_root": str(output_root),
            "saved_part_count": runparts["numeric_rows"],
            "saved_part_path_pattern": str(output_root / "solver_output/data/Part_%04d.bi4"),
            "binding_rule": "derive frame times from RunPARTs.csv; never infer from frame index or request tmax",
            "query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0],
            "query_time_policy": "EXACT/EXACT_OR_LEFT/BRACKETED from actual RunPARTs timestamps; no extrapolation",
            "fields": ["position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"],
            "observer_scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--request", type=Path, default=REQUEST_PATH)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {output}")
    value = build(args.run_root, args.request)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": str(output), "schema": SCHEMA}, indent=2))


if __name__ == "__main__":
    main()
