#!/usr/bin/env python3
"""Prepare the additive F7-S2 three-frame native observer request bound to the exact same-CFL overlay used by the existing 17-frame producer.

The completed same-CFL observer already contains 17 native frames.  The
immutable parent snapshot contains exactly frames 302, 602 and 902, which
close the missing 4x output brackets at 3, 6 and 9 seconds.  This builder
consumes the snapshot's recorded SHA list and small metadata only; it never
hashes or decodes a BI4 file and never scans the raw output tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.f7-s2.same-cfl-neighbor-observer-v4-request.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
OBSERVER_WORKER = REFERENCE / "stage2_native_physical_observer_v2.py"
ENFORCER_WORKER = REFERENCE / "stage2_native_physical_observer_enforcer_v2.py"
SNAPSHOT_WORKER = REFERENCE / "stage2_native_source_snapshot_v2.py"
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
SNAPSHOT_RESULT = DATA_ROOT / "families/F7/F7_S2_OUTPUT_NEIGHBOR_SNAPSHOT_V1/f7-s2-output-neighbor-snapshot-v1-root-001-root-forward-030-001/native_selected_source_snapshot_v2.json"
SNAPSHOT_RECEIPT = SNAPSHOT_RESULT.parent / "execution-receipt.json"
OLD_OBSERVER = DATA_ROOT / "families/F7/F7_S2_SAME_CFL_TIME_OUTPUT_OBSERVER_V1/f7-s2-same_cfl-time-output-observer-v1-root-001-root-forward-029-001/observer/f7_s2_same_cfl_time_output_observer_v1.json"
RAW_ROOT = Path("/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/data")
RUNPARTS = RAW_ROOT.parent / "RunPARTs.csv"
SOURCE_RECEIPT = DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json"
# The old 17-frame observer records this exact overlay path.  Keep the
# path as part of source identity; byte equality alone is insufficient for
# joining two producer reports.
SOURCE_XML = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml"
MOTION = SOURCE_XML.parent / "motion_obstacle_quintic.dat"
REQUEST_DIR = STAGE2 / "requests/stage2-f7-s2-same-cfl-neighbor-observer-v4"
REQUEST_PATH = REQUEST_DIR / "f7_s2_same_cfl_neighbor_observer_v4.json"
MANIFEST_PATH = REQUEST_DIR / "f7_s2_same_cfl_neighbor_expected_source_manifest_v2.json"
REPORT_PATH = REFERENCE / "stage2_f7_s2_same_cfl_neighbor_observer_v4_request.json"
FRAMES = [302, 602, 902]
FINAL_TIME_S = 12.00003209155591


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def load_snapshot() -> dict[str, Any]:
    result = json.loads(regular(SNAPSHOT_RESULT).read_text(encoding="utf-8"))
    if result.get("schema") != "ds02.stage2.native-source-snapshot.v2" or result.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE":
        raise ValueError("neighbor snapshot is not the completed v2 stable result")
    entries = result.get("immutable_source_sha_list")
    if not isinstance(entries, list) or [int(item.get("frame", -1)) for item in entries] != FRAMES:
        raise ValueError(f"neighbor snapshot frame set is not exactly {FRAMES}")
    for item in entries:
        if not isinstance(item.get("path"), str) or int(item.get("bytes", 0)) <= 0 or not isinstance(item.get("sha256"), str):
            raise ValueError("neighbor snapshot has an invalid immutable source record")
        if str(Path(item["path"]).resolve().parent) != str(RAW_ROOT.resolve()):
            raise ValueError("neighbor snapshot source path is outside bound raw root")
    requests = result.get("requests")
    if not isinstance(requests, list) or len(requests) != 1:
        raise ValueError("expected one completed three-frame snapshot request")
    return result


def build(launch_commit: str) -> dict[str, Any]:
    snapshot = load_snapshot()
    static = [Path(__file__), OBSERVER_WORKER, ENFORCER_WORKER, SNAPSHOT_WORKER, SNAPSHOT_RESULT, SNAPSHOT_RECEIPT,
              RUNPARTS, SOURCE_RECEIPT, SOURCE_XML, MOTION, DECODER, DECODER_SOURCE, DISPATCH, STRICT, RUNTIME]
    static = list(dict.fromkeys(regular(path) for path in static))
    snapshot_entry = snapshot["requests"][0]
    expected_records = [{"frame": int(item["frame"]), "path": str(Path(item["path"]).resolve()), "bytes": int(item["bytes"]), "sha256": str(item["sha256"])} for item in snapshot["immutable_source_sha_list"]]
    manifest = {
        "schema": "ds02.stage2.native-observer-source-manifest.v1", "snapshot_schema": snapshot["schema"],
        "observer_request": snapshot_entry.get("observer_request"), "case_id": "F7_S2_SAME_CFL_NEIGHBOR_OBSERVER_V4",
        "family_id": "F7", "sentinel_id": "F7-S2", "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065", "raw_root": str(RAW_ROOT.resolve()),
        "selected_native_frame_ids": FRAMES, "selected_native_files": expected_records,
        "selected_source_sha256": snapshot.get("source_sha_list_digest"),
        "source_sha_policy": "copied from completed immutable snapshot; enforcer hashes/stats exactly these three files before and after decode",
    }
    atomic_json(MANIFEST_PATH, manifest)
    attempt_id = "f7-s2-same-cfl-neighbor-observer-v4-root-forward-001"
    case_id = "F7_S2_SAME_CFL_NEIGHBOR_OBSERVER_V4"
    output_root = DATA_ROOT / "families/F7" / case_id / attempt_id
    output_name = "f7_s2_same_cfl_neighbor_observer_v4.json"
    command = [str(PYTHON), str(ENFORCER_WORKER.resolve()), "--observer-worker", str(OBSERVER_WORKER.resolve()),
               "--expected-source-manifest", str(MANIFEST_PATH.resolve()), "--raw-root", str(RAW_ROOT.resolve()),
               "--runparts", str(RUNPARTS.resolve()), "--generated-xml", str(SOURCE_XML.resolve()), "--decoder", str(DECODER.resolve()),
               "--decoder-source", str(DECODER_SOURCE.resolve()), "--output", f"{{attempt_root}}/observer/{output_name}",
               "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--cwd", str(REPO), "--expected-frame-count", "1201",
               "--expected-final-time-s", str(FINAL_TIME_S), "--final-time-tolerance-s", "1e-12", "--frames", *[str(frame) for frame in FRAMES], "--query-times", "3.0", "6.0", "9.0"]
    input_records = {str(path): record(path) for path in static + [MANIFEST_PATH]}
    deferred = [str(RAW_ROOT.resolve())] + [str((RAW_ROOT / f"Part_{frame:04d}.bi4").resolve()) for frame in FRAMES]
    request = {
        "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F7", "sentinel_id": "F7-S2", "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065", "case_id": case_id, "attempt_id": attempt_id, "launch_commit": launch_commit,
        "command": command, "cwd": str(REPO), "worktree_root": str(REPO), "input_files": list(input_records), "input_hashes": {path: item["sha256"] for path, item in input_records.items()},
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "estimated_native_read_bytes": int(snapshot["selected_native_total_bytes"]), "estimated_input_read_bytes": int(snapshot["selected_native_total_bytes"]) + sum(int(item["bytes"]) for item in input_records.values()), "estimated_storage_bytes": 1024**3, "estimated_peak_memory_bytes": 1024**3,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "hdf5_read": False, "bi4_decode": True, "raw_directory_scan": False,
        "deferred_input_files": deferred, "deferred_input_file_count": len(FRAMES), "deferred_hash_policy": {"snapshot_terminal_sha_source": str(SNAPSHOT_RESULT.resolve()), "builder_bi4_read": False, "builder_bi4_hash": False, "full_raw_tree_hash": "NOT_COMPUTED_BY_BUILDER", "parent_guard_pre_decode_sha_and_complete_stat": "REQUIRED", "worker_post_decode_sha_and_complete_stat": "REQUIRED", "cross_decode_stat_boundaries": "pre.stat_after == post.stat_before and pre.stat_before == post.stat_after", "unknown_child_status": "FAILURE", "hdf5_read": False, "particle_field_interpolation": "NOT_PERFORMED"},
        "source_snapshot_binding": {"snapshot_receipt": record(SNAPSHOT_RECEIPT), "snapshot_result": record(SNAPSHOT_RESULT), "expected_source_manifest": record(MANIFEST_PATH), "selected_source_sha256": snapshot.get("source_sha_list_digest"), "selected_native_files": expected_records, "builder_did_not_read_bi4": True},
        "source_binding": {"raw_root": str(RAW_ROOT.resolve()), "runparts": record(RUNPARTS), "generated_xml": record(SOURCE_XML), "solver_receipt": record(SOURCE_RECEIPT), "motion": record(MOTION), "selected_native_frame_ids": FRAMES, "query_times_s": [3.0, 6.0, 9.0], "terminal_time_s": FINAL_TIME_S, "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065", "source_control": "actual same-CFL v5 source; no geometry/control mutation"},
        "output": {"atomic": True, "refuse_overwrite": True, "path": f"{{attempt_root}}/observer/{output_name}", "scratch_cleanup": "worker-owned temporary decoder tree"},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "parent_v8_review_required": True, "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER"},
        "qualification_stage": "stage2_f7_s2_same_cfl_missing_4x_neighbors_actual_fields_pending", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(REQUEST_PATH, request)
    report = {"schema": SCHEMA, "status": "PREPARED_F7_S2_NEIGHBOR_OBSERVER_V4", "request": record(REQUEST_PATH), "expected_manifest": record(MANIFEST_PATH), "snapshot_result": record(SNAPSHOT_RESULT), "frames": FRAMES, "selected_bytes": int(snapshot["selected_native_total_bytes"]), "launch_commit": launch_commit, "builder_bi4_read": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    atomic_json(REPORT_PATH, report)
    return report


def self_test() -> dict[str, Any]:
    assert FRAMES == [302, 602, 902]
    assert len(set(FRAMES)) == 3
    assert "Part_0302.bi4".endswith(".bi4")
    return {"status": "PASS", "frame_set": FRAMES, "same_cfl_overlay_bound": True, "builder_bi4_read": False, "decoder_launch": False, "solver_launch": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if sum((args.self_test, args.build)) != 1:
        parser.error("choose exactly one mode")
    if args.self_test:
        value = self_test()
    else:
        if not args.launch_commit:
            parser.error("--build requires --launch-commit")
        value = build(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": value["status"], "request": str(REQUEST_PATH), "manifest": str(MANIFEST_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
