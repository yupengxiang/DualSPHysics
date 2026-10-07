#!/usr/bin/env python3
"""Bind a low-storage observer request to the completed F4 2401-frame canary.

The generated request is CPU-only and launch-disabled.  Its worker streams
the exact native Part tree once, registers temporal brackets from RunPARTs,
and writes per-frame hashes.  It deliberately does not create HDF5 or claim
field-observer/scientific qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.f4-canary-stream-observer-request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F4_ATTEMPT = DATA_ROOT / (
    "families/F4/F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2/"
    "f4-s1-full-window-coarse-dp01230-v4-primary-001"
)
RAW_ROOT = F4_ATTEMPT / "solver_output/data"
RECEIPT = F4_ATTEMPT / "execution-receipt.json"
RUNPARTS = F4_ATTEMPT / "solver_output/RunPARTs.csv"
RUNOUT = F4_ATTEMPT / "solver_output/Run.out"
PARTINFO = RAW_ROOT / "PartInfo.ibi4"
PARTOUT = RAW_ROOT / "PartOut_000.obi4"
PART0 = RAW_ROOT / "Part_0000.bi4"
PART_LAST = RAW_ROOT / "Part_2400.bi4"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_canary_stream_observer_v1.py"
AUDIT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_savedt_instrumentation_audit_v1.json"
DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
RUNTIME_V2 = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OUTPUT_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-stream-observer-v1"
REQUEST_PATH = OUTPUT_DIR / "f4_s1_canary_stream_observer_v1.json"
REPORT_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_canary_stream_observer_binding_v1.json"
QUERY_TIMES = [0.0, 0.3, 0.6, 0.9, 1.2, 1.200084396929538]
EXPECTED_FRAMES = 2401
EXPECTED_RAW_BYTES = 3_649_738_491
EXPECTED_FINAL_TIME = 1.200061449336894
EXPECTED_TREE_BYTES = 3_652_593_064


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    # The interpreter is a stable venv symlink; the guard hashes its resolved
    # target just as it hashes any executable input.
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(path)}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def input_records() -> tuple[list[str], dict[str, str]]:
    paths = [DISPATCH, STRICT, RUNTIME, RUNTIME_V2, PYTHON, WORKER, AUDIT,
             RECEIPT, RUNPARTS, RUNOUT, PARTINFO, PARTOUT, PART0, PART_LAST]
    records: list[str] = []
    hashes: dict[str, str] = {}
    for path in paths:
        item = record(path)
        resolved = item["path"]
        records.append(resolved)
        hashes[resolved] = item["sha256"]
    return records, hashes


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = load_json(RECEIPT)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("F4 canary receipt is not a completed zero-returncode receipt")
    if int(receipt.get("bytes", -1)) != EXPECTED_TREE_BYTES:
        raise ValueError("F4 canary receipt tree bytes changed")
    parts = sorted(RAW_ROOT.glob("Part_*.bi4"), key=lambda path: path.name)
    expected_names = [f"Part_{index:04d}.bi4" for index in range(EXPECTED_FRAMES)]
    if [path.name for path in parts] != expected_names:
        raise ValueError("F4 canary native Part files are not exactly 0000..2400")
    raw_bytes = sum(path.stat().st_size for path in parts)
    if raw_bytes != EXPECTED_RAW_BYTES:
        raise ValueError(f"F4 canary raw bytes changed: {raw_bytes}")
    input_files, input_hashes = input_records()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                            capture_output=True, text=True).stdout.strip()
    command = [
        str(PYTHON), str(WORKER),
        "--raw-root", str(RAW_ROOT),
        "--runparts", str(RUNPARTS),
        "--runout", str(RUNOUT),
        "--output", "{attempt_root}/observer/f4_s1_canary_stream_observer.json",
        "--expected-frame-count", str(EXPECTED_FRAMES),
        "--expected-raw-bytes", str(EXPECTED_RAW_BYTES),
        "--expected-final-time-s", repr(EXPECTED_FINAL_TIME),
        "--final-time-tolerance-s", "1e-12",
        "--query-times", *(repr(value) for value in QUERY_TIMES),
    ]
    request: dict[str, Any] = {
        "schema": "ds02.request.v1",
        "family_id": "F4",
        "case_id": "F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2_STREAM_OBSERVER",
        "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "attempt_id": "f4-s1-canary-stream-observer-v1-root-001",
        "kind": "cpu",
        "qualification_stage": "stage2_native_temporal_observer_preparation",
        "cpu_task_kind": "conversion",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "candidate_solver_receipt": str(RECEIPT),
        "candidate_solver_receipt_sha256": sha256_file(RECEIPT),
        "expected_native_frames": EXPECTED_FRAMES,
        "expected_raw_part_bytes": EXPECTED_RAW_BYTES,
        "expected_solver_tree_bytes": EXPECTED_TREE_BYTES,
        "expected_actual_saved_window_s": [0.0, EXPECTED_FINAL_TIME],
        "nominal_cli_tmax_s": 1.200084396929538,
        "query_times_s": QUERY_TIMES,
        "source_binding": {
            "source_role": "immutable completed F4 native canary output",
            "raw_root": str(RAW_ROOT),
            "raw_tree_hash_policy": "worker streams and hashes all 2401 Part files; guard binds receipt, RunPARTs, Run.out, metadata anchors and first/last Part",
            "expected_part_naming": "Part_0000.bi4 through Part_2400.bi4, no gaps or extras",
            "expected_raw_part_bytes": EXPECTED_RAW_BYTES,
            "expected_solver_tree_bytes": EXPECTED_TREE_BYTES,
            "actual_final_time_s": EXPECTED_FINAL_TIME,
            "nominal_cli_endpoint_status": "OUTSIDE_ACTUAL_SAVED_WINDOW; never extrapolate",
        },
        "observer_scope": {
            "native_stream": "one sequential byte/hash pass over complete raw Part tree",
            "temporal_anchors": "RunPARTs saved times, statuses EXACT_OR_LEFT/EXACT/BRACKETED/OUTSIDE_SAVED_WINDOW",
            "queries": QUERY_TIMES,
            "field_observables": "UNKNOWN_NOT_DECODED",
            "typed_conversion": "NOT_PERFORMED",
            "hdf5": "NOT_READ_OR_CREATED",
            "interpolation": "no particle interpolation; brackets only",
            "scientific_qualification": "UNKNOWN",
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        "resource_guard": {
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "consumed_runtime": str(RUNTIME_V2),
            "cpu_only": True,
            "gpu_uuid": "NONE",
            "protected_gpu": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec/PID601689 untouched",
            "storage_reservation_reason": "observer JSON and logs only; no H5 and no native copy",
            "raw_read_estimate_bytes": EXPECTED_RAW_BYTES,
        },
        "scope": {
            "study": "F4-S1 same actual-window temporal provenance observer",
            "grid": "coarse dp=0.01230",
            "physical_window_status": "actual [0,1.200061449336894]; nominal CLI endpoint 1.200084396929538 is not saved",
        },
        "launch_commit": commit,
        "launch_disabled": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "primary_gpu_dispatch_required": False,
        "dispatch_status": "PENDING_PARENT_CPU_GUARD_REVIEW",
        "do_not_execute_from_preparation_worktree": True,
        "foreign_process_protection_required": True,
    }
    report = {
        "schema": SCHEMA,
        "status": "PREPARED_NOT_RUN",
        "current_head": commit,
        "request": {"path": str(REQUEST_PATH), "case_id": request["case_id"],
                    "attempt_id": request["attempt_id"]},
        "candidate_receipt": record(RECEIPT),
        "native_source": {
            "raw_root": str(RAW_ROOT),
            "frame_count": EXPECTED_FRAMES,
            "raw_part_bytes": EXPECTED_RAW_BYTES,
            "solver_tree_bytes": EXPECTED_TREE_BYTES,
            "first_part": record(PART0),
            "last_part": record(PART_LAST),
            "runparts": record(RUNPARTS),
            "runout": record(RUNOUT),
        },
        "actual_window": {"start_s": 0.0, "end_s": EXPECTED_FINAL_TIME,
                          "nominal_cli_tmax_s": 1.200084396929538,
                          "endpoint_status": "NOT_SAVED; no extrapolation"},
        "planned_cost": {
            "cpu_threads": 2,
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 64 * 1024 * 1024,
            "raw_stream_read_bytes": EXPECTED_RAW_BYTES,
            "output": "per-frame digest JSON plus anchors; no raw/typed duplicate",
            "scientific_field_values": "UNKNOWN until an independently reviewed decoder/typed query task",
        },
        "input_count": len(input_files),
        "hdf5_read_by_preparation": False,
        "solver_started_by_preparation": False,
    }
    return request, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=REQUEST_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    request, report = build()
    atomic_json(args.request, request)
    atomic_json(args.report, report)
    print(json.dumps({"status": report["status"], "request": str(args.request),
                      "report": str(args.report), "inputs": report["input_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
