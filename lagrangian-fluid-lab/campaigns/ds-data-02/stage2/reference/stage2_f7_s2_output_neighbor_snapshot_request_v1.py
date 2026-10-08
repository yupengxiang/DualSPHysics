#!/usr/bin/env python3
"""Build a bounded F7-S2 native-neighbor snapshot request.

The completed F7-S2 output calibration has valid same-run 2x diagnostics at
queries 3, 6, and 9 s, but its 4x diagnostics remain UNKNOWN because the
selected native set omitted frames 302, 602, and 902 (and endpoints cannot be
extrapolated).  This additive request asks the parent v8 guard to hash only
those three exact BI4 files.  It does not decode them, read H5, scan the raw
directory, or start a solver.  A later observer request may consume the
immutable snapshot and compare only same-run observables with the pre-registered
output-share gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.f7-s2.output-neighbor-snapshot-request.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
RAW_ROOT = Path("/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/"
                "f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/data")
SOURCE_RECEIPT = DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/"
SOURCE_RECEIPT = SOURCE_RECEIPT / "f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json"
SOURCE_RUNPARTS = RAW_ROOT.parent / "RunPARTs.csv"
SOURCE_XML = DATA_ROOT / "families/F7/F7_OBSTACLE_QUINTIC_B08_A065/"
SOURCE_XML = SOURCE_XML / "root-stage1-f7-angle065-genuine-gencase-085/prepared/F7_OBSTACLE_QUINTIC_B08_A065.xml"
MOTION = SOURCE_XML.parent / "motion_obstacle_quintic.dat"
SNAPSHOT_WORKER = REFERENCE / "stage2_native_source_snapshot_v2.py"
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
REQUEST_PATH = STAGE2 / "requests/stage2-f7-s2-output-neighbor-snapshot-v1/" \
    "f7_s2_output_neighbor_snapshot_v1.json"
REPORT_PATH = REFERENCE / "stage2_f7_s2_output_neighbor_snapshot_request_v1.json"
ATTEMPT_ID = "f7-s2-output-neighbor-snapshot-v1-root-001"
FRAMES = [302, 602, 902]


def sha256(path: Path) -> str:
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
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def build() -> dict[str, Any]:
    for path in (SNAPSHOT_WORKER, DISPATCH, STRICT, RUNTIME, SOURCE_RECEIPT, SOURCE_RUNPARTS, SOURCE_XML, MOTION):
        if not path.is_file():
            raise FileNotFoundError(path)
    source_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    deferred = [str((RAW_ROOT / f"Part_{frame:04d}.bi4").resolve()) for frame in FRAMES]
    small_inputs = [SNAPSHOT_WORKER, DISPATCH, STRICT, RUNTIME, SOURCE_RECEIPT, SOURCE_RUNPARTS, SOURCE_XML, MOTION]
    input_files = [str(path.resolve()) for path in small_inputs] + deferred
    input_hashes = {str(path.resolve()): sha256(path) for path in small_inputs}
    input_hashes.update({path: "PARENT_V8_GUARD_REQUIRED" for path in deferred})
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F7",
        "sentinel_id": "F7-S2",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "case_id": "F7_S2_OUTPUT_NEIGHBOR_SNAPSHOT_V1",
        "attempt_id": ATTEMPT_ID,
        "qualification_stage": "stage2_f7_s2_missing_4x_output_neighbors_source_snapshot_pending_parent_v8",
        "launch_commit": source_commit,
        "command": [
            "/usr/bin/python3.10", str(SNAPSHOT_WORKER), "--observer-request", str(REQUEST_PATH),
            "--output", "{attempt_root}/native_selected_source_snapshot_v2.json",
        ],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "selected_native_frame_ids": FRAMES,
        "query_times_s": [3.0, 6.0, 9.0],
        "query_brackets": {
            "3.0": {"required_missing_neighbor_frame": 302, "paired_selected_frames": [298, 299, 300, 301], "purpose": "4x same-run output diagnostic"},
            "6.0": {"required_missing_neighbor_frame": 602, "paired_selected_frames": [598, 599, 600, 601], "purpose": "4x same-run output diagnostic"},
            "9.0": {"required_missing_neighbor_frame": 902, "paired_selected_frames": [898, 899, 900, 901], "purpose": "4x same-run output diagnostic"},
        },
        "source_binding": {
            "schema": SCHEMA,
            "raw_root": str(RAW_ROOT.resolve()),
            "source_solver_receipt": record(SOURCE_RECEIPT),
            "source_runparts": record(SOURCE_RUNPARTS),
            "source_xml": record(SOURCE_XML),
            "motion": record(MOTION),
            "source_terminal_time_s": 12.00003209155591,
            "selected_frames_are_additive_only": True,
            "already_observed_set": [0, 1, 298, 299, 300, 301, 598, 599, 600, 601, 898, 899, 900, 901, 1198, 1199, 1200],
            "endpoint_policy": "frame2/1201 are not requested; no endpoint extrapolation and 12 s 4x remains UNKNOWN",
        },
        "deferred_input_files": deferred,
        "estimated_input_read_bytes": "PARENT_GUARD_MEASURE_EXACT_THREE_SELECTED_PARTS",
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_EXACT_THREE_SELECTED_PARTS",
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "hdf5_read": False,
        "bi4_decode": False,
        "raw_directory_scan": False,
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": "{attempt_root}/native_selected_source_snapshot_v2.json",
            "scope": "stable pre/post SHA/stat manifest for exactly three selected Part files; no field decode",
        },
        "next_stage": {
            "worker": "stage2_native_physical_observer_enforcer_v2 plus source-bound observer builder",
            "input": "immutable snapshot SHA list from this request",
            "fields": ["weighted_centroid_m", "weighted_velocity_m_per_s", "kinetic_energy_j"],
            "comparison": "same-run output sampling only; retain actual RunPARTs times and bracket widths; no cross-grid truth",
            "expected_gain": "4x diagnostics at 3/6/9 s; endpoints remain UNKNOWN",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "parent_v8_review_required": True,
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST_PATH, request)
    report = {
        "schema": SCHEMA,
        "status": "PREPARED_F7_S2_OUTPUT_NEIGHBOR_SNAPSHOT_REQUEST",
        "request": record(REQUEST_PATH),
        "frames": FRAMES,
        "purpose": "close only the missing 4x neighbor diagnostics at 3/6/9 s",
        "source_receipt": record(SOURCE_RECEIPT),
        "no_solver_or_h5": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REPORT_PATH, report)
    return {"request": REQUEST_PATH, "report": REPORT_PATH, "sha256": sha256(REQUEST_PATH)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        parser.error("use --prepare")
    result = build()
    print(json.dumps({"status": "PREPARED_F7_S2_OUTPUT_NEIGHBOR_SNAPSHOT_REQUEST", **{k: str(v) for k, v in result.items()}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
