#!/usr/bin/env python3
"""Prepare a launch-disabled bounded F1-S2 native observer request.

The request binds the completed dp=0.017 source to its actual 801-row
RunPARTs time axis and selects only the native frames needed for 0, 1, 2, 3,
and 4 s query brackets.  It is metadata preparation only: the parent guard
must hash the binary inputs immediately before any CPU decode, and this
builder never opens a BI4/HDF5 payload.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-s2-fine-native-observer-request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
RUN_ROOT = DATA_ROOT / (
    "F1_S2_INTERVAL_DP0p017_FULL4S_SAMECFL_SAVEDT_DENSE/"
    "f1-s2-fine-dp017-samecfl-full4s-savedt-v5-primary-001"
)
RUNPARTS = RUN_ROOT / "solver_output/RunPARTs.csv"
SOURCE_XML = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/"
    "F1_S2_SPATIAL_INTERVAL_DP0p017000/"
    "f1-s2-spatial-interval-dp0p017000-v2-primary-001/generated.xml"
)
SOURCE_GENCASE_RECEIPT = SOURCE_XML.parent / "execution-receipt.json"
SOLVER_RECEIPT = RUN_ROOT / "execution-receipt.json"
AUDIT_REPORT = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f1_s2_fine_terminal_savedt_audit_v4.json"
)
WORKER = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_native_physical_observer_v1.py"
)
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/"
    "l1-resume/artifacts/bi4_dump"
)
DISPATCH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
)
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v4.py"
QUERY_TIMES = (0.0, 1.0, 2.0, 3.0, 4.0)
OUT_ROOT = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-f1-s2-fine-observer-v1"
)


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
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_runparts(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(lines, delimiter=";"):
        part = (row.get("Part") or "").strip()
        if not part.isdigit():
            continue
        rows.append({"part": int(part), "time_s": float((row.get("TimeStep [s]") or "").strip())})
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs is not a contiguous 0-based axis: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs times are not increasing: {path}")
    return rows


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if any(abs(row["time_s"] - query) <= 1.0e-12 for row in rows):
        row = next(row for row in rows if abs(row["time_s"] - query) <= 1.0e-12)
        return {"status": "EXACT", "lower_frame": row["part"], "upper_frame": row["part"], "time_s": row["time_s"]}
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        return {"status": "OUTSIDE_SAVED_WINDOW", "query_time_s": query}
    upper = next(index for index, row in enumerate(rows) if row["time_s"] > query)
    lower = upper - 1
    return {
        "status": "BRACKETED",
        "lower_frame": rows[lower]["part"],
        "upper_frame": rows[upper]["part"],
        "lower_time_s": rows[lower]["time_s"],
        "upper_time_s": rows[upper]["time_s"],
        "bracket_width_s": rows[upper]["time_s"] - rows[lower]["time_s"],
    }


def build() -> dict[str, Any]:
    rows = read_runparts(RUNPARTS)
    audit = load_json(AUDIT_REPORT)
    if audit.get("schema") != "ds02.stage2.f1-s2-fine-terminal-savedt-audit.v4":
        raise ValueError("F1 terminal audit v4 is not the bound source")
    brackets = {str(query): bracket(rows, query) for query in QUERY_TIMES}
    if any(value["status"] == "OUTSIDE_SAVED_WINDOW" for value in brackets.values()):
        raise ValueError(f"a registered query is outside the saved window: {brackets}")
    selected = sorted({
        frame
        for value in brackets.values()
        for frame in (value.get("lower_frame"), value.get("upper_frame"))
        if frame is not None
    })
    expected_final = rows[-1]["time_s"]
    attempt_id = "f1-s2-fine-dp017-selected-native-observer-v1-root-001"
    case_id = "F1_S2_FINE_DP017_SELECTED_NATIVE_OBSERVER_V1"
    output_path = "{attempt_root}/observer/f1_s2_fine_dp017_selected_native_observer_v1.json"
    scratch_path = "{attempt_root}/scratch/bi4_decode"
    command = [
        str(PYTHON), str(WORKER),
        "--raw-root", str(RUN_ROOT / "solver_output/data"),
        "--runparts", str(RUNPARTS),
        "--generated-xml", str(SOURCE_XML),
        "--decoder", str(DECODER),
        "--output", output_path,
        "--scratch-root", scratch_path,
        "--expected-frame-count", str(len(rows)),
        "--expected-final-time-s", repr(expected_final),
        "--final-time-tolerance-s", "1e-12",
        "--frames", *(str(frame) for frame in selected),
        "--query-times", *(repr(query) for query in QUERY_TIMES),
    ]
    input_paths = [
        WORKER, PYTHON, DISPATCH, STRICT, RUNTIME, RUNPARTS, SOURCE_XML,
        SOURCE_GENCASE_RECEIPT, SOLVER_RECEIPT, AUDIT_REPORT, DECODER,
    ]
    input_files = [str(path.resolve()) for path in input_paths]
    input_hashes: dict[str, str] = {}
    for path in input_paths:
        if path == DECODER:
            input_hashes[str(path.resolve())] = "PARENT_V4_GUARD_HASH_REQUIRED"
        else:
            input_hashes[str(path.resolve())] = sha256_file(path)
    return {
        "schema": "ds02.request.v1",
        "family_id": "F1",
        "case_id": case_id,
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "attempt_id": attempt_id,
        "kind": "cpu",
        "qualification_stage": "stage2_f1_s2_fine_selected_native_observer_pending_parent_cpu_guard",
        "cpu_task_kind": "native_observer",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 1073741824,
        "estimated_peak_memory_bytes": 1073741824,
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_SELECTED_FRAME_BYTES",
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "source_binding": {
            "schema": SCHEMA,
            "sentinel_id": "F1-S2",
            "family_id": "F1",
            "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
            "solver_attempt": file_record(SOLVER_RECEIPT),
            "source_gencase_receipt": file_record(SOURCE_GENCASE_RECEIPT),
            "generated_xml": file_record(SOURCE_XML),
            "runparts": file_record(RUNPARTS),
            "terminal_audit": file_record(AUDIT_REPORT),
            "raw_root": str((RUN_ROOT / "solver_output/data").resolve()),
            "frame_count": len(rows),
            "selected_native_frame_ids": selected,
            "query_brackets": brackets,
            "last_saved_time_s": expected_final,
            "query_4s_is_exact_saved": brackets["4.0"]["status"] == "EXACT",
            "no_frame_index_assumption": True,
            "no_extrapolation": True,
        },
        "query_times_s": list(QUERY_TIMES),
        "selected_native_frame_ids": selected,
        "input_files": input_files,
        "input_hashes": input_hashes,
        "deferred_input_files": [
            str((RUN_ROOT / "solver_output/data").resolve()),
            *[str((RUN_ROOT / f"solver_output/data/Part_{frame:04d}.bi4").resolve()) for frame in selected],
        ],
        "deferred_hash_policy": "parent v4 must hash exactly selected native Part files before CPU launch; do not scan/hash the full 801-frame tree in this worker",
        "output": {
            "path": output_path,
            "refuse_overwrite": True,
            "atomic": True,
            "fields": ["position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"],
            "time_policy": "actual RunPARTs timestamps; EXACT/BRACKETED status retained; no interpolation or extrapolation",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "launch_disabled": True,
        },
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refuse to overwrite existing request: {output}")
    value = build()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": str(output), "selected_frames": value["selected_native_frame_ids"]}, indent=2))


if __name__ == "__main__":
    main()
