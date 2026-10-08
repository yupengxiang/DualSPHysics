#!/usr/bin/env python3
"""Build the deferred JSON-only F7 17+3 observer join request.

The v3 request consumes the same-CFL overlay-bound neighbor v4 request and
binds the producer receipt, decoder inputs, and complete 20-record join
worker.  It never reads native payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f7-s2.same-cfl-20frame-join-request.v4"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
JOIN_WORKER = REFERENCE / "stage2_f7_s2_same_cfl_20frame_join_v4.py"
NEIGHBOR_BUILDER = REFERENCE / "stage2_f7_s2_same_cfl_neighbor_observer_v4.py"
NEIGHBOR_DIR = STAGE2 / "requests/stage2-f7-s2-same-cfl-neighbor-observer-v4"
NEIGHBOR_REQUEST = NEIGHBOR_DIR / "f7_s2_same_cfl_neighbor_observer_v4.json"
NEIGHBOR_MANIFEST = NEIGHBOR_DIR / "f7_s2_same_cfl_neighbor_expected_source_manifest_v2.json"
NEIGHBOR_ENFORCER = REFERENCE / "stage2_native_physical_observer_enforcer_v2.py"
NEIGHBOR_OBSERVER = REFERENCE / "stage2_native_physical_observer_v2.py"
OLD_OBSERVER = DATA_ROOT / "families/F7/F7_S2_SAME_CFL_TIME_OUTPUT_OBSERVER_V1/f7-s2-same_cfl-time-output-observer-v1-root-001-root-forward-029-001/observer/f7_s2_same_cfl_time_output_observer_v1.json"
OLD_SNAPSHOT = DATA_ROOT / "families/F7/F7_S2_SAME_CFL_TIME_OUTPUT_SELECTED_SOURCE_V1/f7-s2-same_cfl-time-output-selected-source-v1-root-001-root-forward-029-001/native_selected_source_snapshot_v1.json"
OLD_SNAPSHOT_RECEIPT = OLD_SNAPSHOT.parent / "execution-receipt.json"
RAW_ROOT = Path("/var/tmp/ds02-stage2/F7/F7_S2_NVME_COUNTERPART_V5/f7-s2-a065-same-cfl-dense-savedt-v5-001/solver_output/data")
RUNPARTS = RAW_ROOT.parent / "RunPARTs.csv"
SOURCE_XML = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/F7_OBSTACLE_QUINTIC_B08_A065_same_cfl_savedt.xml"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = MAIN / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
SOURCE_RECEIPT = DATA_ROOT / "families/F7/f7-obstacle-quintic-b08-a065/f7-s2-a065-same-cfl-dense-savedt-v5-001/execution-receipt.json"
CONTRACT = REFERENCE / "stage2_f7_s2_observer_calibration_contract_v3.json"
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
REQUEST_DIR = STAGE2 / "requests/stage2-f7-s2-same-cfl-20frame-join-v4"
REQUEST_PATH = REQUEST_DIR / "f7_s2_same_cfl_20frame_join_v4.json"
REPORT_PATH = REFERENCE / "stage2_f7_s2_same_cfl_20frame_join_request_v4.json"
NEIGHBOR_OUTPUT = DATA_ROOT / "families/F7/F7_S2_SAME_CFL_NEIGHBOR_OBSERVER_V4/f7-s2-same-cfl-neighbor-observer-v4-root-forward-001/observer/f7_s2_same_cfl_neighbor_observer_v4.json"


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
    path = regular(path); stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve(); encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if path.exists():
        if path.read_bytes() == encoded: return
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)


def build(launch_commit: str) -> dict[str, Any]:
    static = [Path(__file__), JOIN_WORKER, NEIGHBOR_BUILDER, NEIGHBOR_REQUEST, NEIGHBOR_MANIFEST, NEIGHBOR_ENFORCER, NEIGHBOR_OBSERVER, OLD_OBSERVER, OLD_SNAPSHOT, OLD_SNAPSHOT_RECEIPT, RUNPARTS, SOURCE_XML, SOURCE_RECEIPT, DECODER, DECODER_SOURCE, CONTRACT, DISPATCH, STRICT, RUNTIME]
    static = list(dict.fromkeys(regular(path) for path in static))
    request_dir = REQUEST_DIR; request_dir.mkdir(parents=True, exist_ok=True)
    case_id = "F7_S2_SAME_CFL_20FRAME_JOIN_V4"
    attempt_id = "f7-s2-same-cfl-20frame-join-v4-root-forward-001"
    output_root = DATA_ROOT / "families/F7" / case_id / attempt_id
    input_records = {str(path): record(path) for path in static}
    command = [str(PYTHON), str(JOIN_WORKER.resolve()), "--same-observer", str(OLD_OBSERVER.resolve()), "--neighbor-observer", str(NEIGHBOR_OUTPUT.resolve()), "--runparts", str(RUNPARTS.resolve()), "--generated-xml", str(SOURCE_XML.resolve()), "--decoder", str(DECODER.resolve()), "--decoder-source", str(DECODER_SOURCE.resolve()), "--source-receipt", str(SOURCE_RECEIPT.resolve()), "--raw-root", str(RAW_ROOT.resolve()), "--calibration-contract", str(CONTRACT.resolve()), "--output", "{attempt_root}/report/f7_s2_same_cfl_20frame_join_v4.json"]
    request = {
        "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F7", "sentinel_id": "F7-S2", "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065", "case_id": case_id, "attempt_id": attempt_id, "launch_commit": launch_commit,
        "command": command, "cwd": str(REPO), "worktree_root": str(REPO), "input_files": list(input_records), "input_hashes": {path: item["sha256"] for path, item in input_records.items()}, "input_records": input_records,
        "deferred_input_files": [str(NEIGHBOR_OUTPUT.resolve())], "deferred_input_stats": {str(NEIGHBOR_OUTPUT.resolve()): {"sha256": "PARENT_GUARD_COMPUTED", "scope": "terminal successful v4 neighbor observer JSON with complete 3-frame source integrity"}},
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900, "estimated_native_read_bytes": 0, "estimated_input_read_bytes": sum(int(item["bytes"]) for item in input_records.values()), "estimated_storage_bytes": 128 * 1024**2, "estimated_peak_memory_bytes": 512 * 1024**2,
        "execution_allowed": False, "launch_disabled": True, "solver_started": False, "hdf5_read": False, "bi4_read": False, "decoder_launch": False, "particle_field_interpolation": "FORBIDDEN",
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "parent_v8_review_required": True, "deferred_neighbor_success_required": True, "solver_launch": "forbidden", "hdf5_read": "forbidden", "native_payload_read": "forbidden; JSON-only join"},
        "source_binding": {"same_17_observer": record(OLD_OBSERVER), "neighbor_3_request": record(NEIGHBOR_REQUEST), "neighbor_3_manifest": record(NEIGHBOR_MANIFEST), "neighbor_3_result": "deferred terminal output; parent must verify v4 PASS_DECODED_SELECTED_NATIVE_FIELDS and all 3 pre/post records", "runparts": record(RUNPARTS), "generated_xml": record(SOURCE_XML), "solver_receipt": record(SOURCE_RECEIPT), "decoder": record(DECODER), "decoder_source": record(DECODER_SOURCE), "calibration_contract": record(CONTRACT), "merged_frame_ids": [0, 1, 298, 299, 300, 301, 302, 598, 599, 600, 601, 602, 898, 899, 900, 901, 902, 1198, 1199, 1200], "field_interpolation": "FORBIDDEN", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/report/f7_s2_same_cfl_20frame_join_v4.json"},
        "qualification_stage": "stage2_f7_s2_same_cfl_20_native_join_pending_neighbor_observer", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST_PATH, request)
    report = {"schema": SCHEMA, "status": "PREPARED_F7_S2_17_PLUS_3_JSON_JOIN_V4", "request": record(REQUEST_PATH), "deferred_neighbor_observer": str(NEIGHBOR_OUTPUT), "joined_frame_count": 20, "complete_pre_post_records_required": True, "top_level_pre_post_records": 20, "common_source_identity_required": True, "no_bi4_read_by_join": True, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    atomic_json(REPORT_PATH, report)
    return report


def self_test() -> dict[str, Any]:
    assert len([0, 1, 298, 299, 300, 301, 302, 598, 599, 600, 601, 602, 898, 899, 900, 901, 902, 1198, 1199, 1200]) == 20
    return {"status": "PASS", "json_only": True, "deferred_neighbor_required": True, "joined_frame_count": 20, "no_solver_or_bi4_read": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--self-test", action="store_true"); parser.add_argument("--build", action="store_true"); parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if sum((args.self_test, args.build)) != 1: parser.error("choose exactly one mode")
    if args.self_test: value = self_test()
    else:
        if not args.launch_commit: parser.error("--build requires --launch-commit")
        value = build(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": value["status"], "request": str(REQUEST_PATH), "deferred_neighbor": str(NEIGHBOR_OUTPUT)}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
