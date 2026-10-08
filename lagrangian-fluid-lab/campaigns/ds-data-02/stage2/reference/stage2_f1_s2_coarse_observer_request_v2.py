#!/usr/bin/env python3
"""Build a launch-disabled native observer request for the F1-S2 coarse run.

This is a source-bound metadata builder.  It reads only the completed coarse
RunPARTs axis, generated XML, and the two small execution receipts.  It does
not inspect any BI4/H5 payload and never starts a solver or decoder.  Query
brackets are reported using native Part IDs from this run's own RunPARTs axis;
there is no frame-index pairing with the F1-S2 fine run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-s2-coarse-native-observer-request.v2"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
RUN_ROOT = DATA_ROOT / (
    "F1_S2_SPATIAL_COARSE_DP0p022500_FULL4S_SAMECFL_SAVEDT/"
    "f1-s2-coarse-dp0225-samecfl-full4s-savedt-v6-primary-001"
)
RUNPARTS = RUN_ROOT / "solver_output/RunPARTs.csv"
SOURCE_XML = DATA_ROOT / (
    "F1_S2_SPATIAL_COARSE_DP0p022500/"
    "f1-s2-spatial-coarse-dp0p022500-v5-primary-001/generated.xml"
)
SOURCE_GENCASE_RECEIPT = SOURCE_XML.parent / "execution-receipt.json"
SOLVER_RECEIPT = RUN_ROOT / "execution-receipt.json"
WORKER = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_native_physical_observer_v1.py"
)
BUILDER = Path(__file__).resolve()
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
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256_file(path),
    }


def read_runparts(path: Path) -> list[dict[str, Any]]:
    lines = [
        line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(lines, delimiter=";"):
        raw_part = (row.get("Part") or "").strip()
        raw_time = (row.get("TimeStep [s]") or "").strip().split()[0]
        if not raw_part.isdigit():
            continue
        time_s = float(raw_time)
        if not math.isfinite(time_s):
            raise ValueError(f"non-finite RunPARTs timestamp at Part {raw_part}")
        rows.append({"part": int(raw_part), "time_s": time_s})
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs is not a contiguous 0-based axis: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs timestamps are not strictly increasing: {path}")
    return rows


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        return {
            "query_time_s": query,
            "status": "OUTSIDE_SAVED_WINDOW",
            "saved_window_s": [rows[0]["time_s"], rows[-1]["time_s"]],
        }
    for index, row in enumerate(rows):
        if row["time_s"] == query:
            return {
                "query_time_s": query,
                "status": "EXACT",
                "lower_frame": row["part"],
                "upper_frame": row["part"],
                "lower_time_s": row["time_s"],
                "upper_time_s": row["time_s"],
                "bracket_width_s": 0.0,
            }
        if row["time_s"] > query:
            lower = rows[index - 1]
            return {
                "query_time_s": query,
                "status": "BRACKETED",
                "lower_frame": lower["part"],
                "upper_frame": row["part"],
                "lower_time_s": lower["time_s"],
                "upper_time_s": row["time_s"],
                "bracket_width_s": row["time_s"] - lower["time_s"],
            }
    raise AssertionError("query bracket search fell through")


def build() -> dict[str, Any]:
    rows = read_runparts(RUNPARTS)
    brackets = {str(query): bracket(rows, query) for query in QUERY_TIMES}
    outside = [query for query, value in brackets.items() if value["status"] == "OUTSIDE_SAVED_WINDOW"]
    if outside:
        raise ValueError(f"registered query outside completed saved window: {outside}")
    selected = sorted({
        frame
        for value in brackets.values()
        for frame in (value.get("lower_frame"), value.get("upper_frame"))
        if frame is not None
    })
    input_paths = [
        BUILDER,
        WORKER,
        PYTHON,
        DISPATCH,
        STRICT,
        RUNTIME,
        RUNPARTS,
        SOURCE_XML,
        SOURCE_GENCASE_RECEIPT,
        SOLVER_RECEIPT,
        DECODER,
    ]
    input_files = [str(path.resolve()) for path in input_paths]
    input_hashes: dict[str, str] = {}
    for path in input_paths:
        input_hashes[str(path.resolve())] = (
            "PARENT_V4_GUARD_HASH_REQUIRED" if path == DECODER else sha256_file(path)
        )
    output_path = "{attempt_root}/observer/f1_s2_coarse_dp0225_selected_native_observer_v2.json"
    command = [
        str(PYTHON),
        str(WORKER),
        "--raw-root", str((RUN_ROOT / "solver_output/data").resolve()),
        "--runparts", str(RUNPARTS.resolve()),
        "--generated-xml", str(SOURCE_XML.resolve()),
        "--decoder", str(DECODER.resolve()),
        "--output", output_path,
        "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--expected-frame-count", str(len(rows)),
        "--expected-final-time-s", repr(rows[-1]["time_s"]),
        "--final-time-tolerance-s", "1e-12",
        "--frames", *(str(frame) for frame in selected),
        "--query-times", *(repr(query) for query in QUERY_TIMES),
    ]
    return {
        "schema": "ds02.request.v1",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_COARSE_DP0225_SELECTED_NATIVE_OBSERVER_V2",
        "attempt_id": "f1-s2-coarse-dp0225-selected-native-observer-v2-root-001",
        "kind": "cpu",
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
        "qualification_stage": "stage2_f1_s2_coarse_selected_native_observer_pending_parent_cpu_guard",
        "source_binding": {
            "schema": SCHEMA,
            "sentinel_id": "F1-S2",
            "family_id": "F1",
            "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
            "source_gencase_receipt": file_record(SOURCE_GENCASE_RECEIPT),
            "generated_xml": file_record(SOURCE_XML),
            "solver_receipt": file_record(SOLVER_RECEIPT),
            "runparts": file_record(RUNPARTS),
            "raw_root": str((RUN_ROOT / "solver_output/data").resolve()),
            "frame_count": len(rows),
            "selected_native_frame_ids": selected,
            "query_brackets": brackets,
            "last_saved_time_s": rows[-1]["time_s"],
            "query_4s_is_exact_saved": brackets["4.0"]["status"] == "EXACT",
            "native_part_ids_from_this_run_only": True,
            "no_frame_index_pairing": True,
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
        "deferred_hash_policy": "parent v4 must hash exactly selected native Part files immediately before CPU launch; do not scan/hash the full tree in this worker",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite request: {output}")
    value = build()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    print(json.dumps({"output": str(output), "selected_native_frame_ids": value["selected_native_frame_ids"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
