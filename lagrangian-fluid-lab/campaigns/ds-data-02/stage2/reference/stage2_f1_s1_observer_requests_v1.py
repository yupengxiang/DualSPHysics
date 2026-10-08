#!/usr/bin/env python3
"""Prepare bounded v2-observer requests for the completed F1-S1 CFL pair.

The same-CFL and half-CFL solver outputs are separate saved-time axes.  This
builder selects native Part IDs from each axis around the common physical
queries 0, .4, .8, 1.2, and 1.6 s; it never pairs a frame number across runs.
The request is launch-disabled and binds the exact F1-S1 source XML, producer
receipts, RunPARTs CSV, decoder source contract, and v2 observer worker.
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


SCHEMA = "ds02.stage2.f1-s1-native-observer-request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
SOURCE_XML = DATA_ROOT / (
    "F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/"
    "prepared/F1_FALLBACK_ECC_COARSE.xml"
)
SOURCE_GENCASE_RECEIPT = SOURCE_XML.parent.parent / "execution-receipt.json"
WORKER = REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_native_physical_observer_v2.py"
)
BUILDER = Path(__file__).resolve()
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/"
    "l1-resume/artifacts/bi4_dump"
)
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
DISPATCH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
)
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v4.py"
QUERY_TIMES = (0.0, 0.4, 0.8, 1.2, 1.6)
RUNS = {
    "same_cfl": DATA_ROOT / (
        "F1_S1_ORIGINAL_SAMECFL_DENSE_SAVEDT_V2/"
        "f1-s1-samecfl-dense-savedt-v2-primary-001-v5"
    ),
    "half_cfl": DATA_ROOT / (
        "F1_S1_ORIGINAL_HALFCFL_DENSE_SAVEDT_V2/"
        "f1-s1-halfcfl-dense-savedt-v2-primary-001-v5"
    ),
}


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


def read_runparts(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for item in csv.DictReader(lines, delimiter=";"):
        raw_part = (item.get("Part") or "").strip()
        raw_time = (item.get("TimeStep [s]") or "").strip().split()[0]
        if not raw_part.isdigit():
            continue
        time_s = float(raw_time)
        if not math.isfinite(time_s):
            raise ValueError(f"non-finite RunPARTs time: {path}")
        rows.append({"part": int(raw_part), "time_s": time_s})
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs is not contiguous from zero: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs times are not strictly increasing: {path}")
    return rows


def bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if query < rows[0]["time_s"] or query > rows[-1]["time_s"]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW"}
    for index, row in enumerate(rows):
        if row["time_s"] == query:
            return {"query_time_s": query, "status": "EXACT", "lower_frame": row["part"], "upper_frame": row["part"], "lower_time_s": row["time_s"], "upper_time_s": row["time_s"]}
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
    raise AssertionError("query bracket fell through")


def build(mode: str) -> dict[str, Any]:
    if mode not in RUNS:
        raise ValueError(f"unsupported F1-S1 mode: {mode}")
    run_root = RUNS[mode]
    runparts = run_root / "solver_output/RunPARTs.csv"
    solver_receipt = run_root / "execution-receipt.json"
    rows = read_runparts(runparts)
    brackets = {str(query): bracket(rows, query) for query in QUERY_TIMES}
    if any(value["status"] == "OUTSIDE_SAVED_WINDOW" for value in brackets.values()):
        raise ValueError(f"registered query outside {mode} saved window: {brackets}")
    selected = sorted({
        frame
        for value in brackets.values()
        for frame in (value.get("lower_frame"), value.get("upper_frame"))
        if frame is not None
    })
    input_paths = [
        BUILDER, WORKER, PYTHON, DISPATCH, STRICT, RUNTIME,
        runparts, SOURCE_XML, SOURCE_GENCASE_RECEIPT, solver_receipt,
        DECODER, DECODER_SOURCE,
    ]
    input_files = [str(path.resolve()) for path in input_paths]
    input_hashes = {
        str(path.resolve()): ("PARENT_V4_GUARD_HASH_REQUIRED" if path == DECODER else sha256_file(path))
        for path in input_paths
    }
    case_suffix = mode.upper()
    output_path = f"{{attempt_root}}/observer/f1_s1_dp010_{mode}_selected_native_observer_v1.json"
    command = [
        str(PYTHON), str(WORKER),
        "--raw-root", str((run_root / "solver_output/data").resolve()),
        "--runparts", str(runparts.resolve()),
        "--generated-xml", str(SOURCE_XML.resolve()),
        "--decoder", str(DECODER.resolve()),
        "--decoder-source", str(DECODER_SOURCE.resolve()),
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
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": f"F1_S1_DP010_{case_suffix}_SELECTED_NATIVE_OBSERVER_V1",
        "attempt_id": f"f1-s1-dp010-{mode}-selected-native-observer-v1-root-001",
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
        "qualification_stage": "stage2_f1_s1_selected_native_observer_pending_parent_cpu_guard",
        "source_binding": {
            "schema": SCHEMA,
            "sentinel_id": "F1-S1",
            "family_id": "F1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
            "cfl_variant": mode,
            "source_gencase_receipt": file_record(SOURCE_GENCASE_RECEIPT),
            "generated_xml": file_record(SOURCE_XML),
            "solver_receipt": file_record(solver_receipt),
            "runparts": file_record(runparts),
            "raw_root": str((run_root / "solver_output/data").resolve()),
            "frame_count": len(rows),
            "selected_native_frame_ids": selected,
            "query_brackets": brackets,
            "last_saved_time_s": rows[-1]["time_s"],
            "native_part_ids_from_this_run_only": True,
            "no_frame_index_pairing": True,
            "no_extrapolation": True,
        },
        "query_times_s": list(QUERY_TIMES),
        "selected_native_frame_ids": selected,
        "input_files": input_files,
        "input_hashes": input_hashes,
        "deferred_input_files": [
            str((run_root / "solver_output/data").resolve()),
            *[str((run_root / f"solver_output/data/Part_{frame:04d}.bi4").resolve()) for frame in selected],
        ],
        "deferred_hash_policy": "parent v4 must hash exactly selected native Part files immediately before CPU launch; do not scan/hash the full tree in this worker",
        "output": {
            "path": output_path,
            "refuse_overwrite": True,
            "atomic": True,
            "decoded_fields": ["Idp", "position", "velocity", "density/Rhop", "derived_sample_mass", "kind", "mkfluid_relative", "mk_absolute"],
            "pressure_status": "NOT_DECODED_BY_WORKER",
            "eos_pressure_status": "UNKNOWN_NOT_DECODED",
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
    parser.add_argument("--mode", choices=sorted(RUNS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite request: {output}")
    value = build(args.mode)
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
    print(json.dumps({"output": str(output), "mode": args.mode, "selected_native_frame_ids": value["selected_native_frame_ids"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
