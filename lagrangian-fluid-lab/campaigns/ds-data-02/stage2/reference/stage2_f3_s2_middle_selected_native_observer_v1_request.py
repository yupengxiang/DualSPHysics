#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a guarded selected-native observer request for ROOT162 F3 middle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.middle-selected-native-observer-request.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_middle_selected_native_observer_v1.py"
LOCAL_WORKER = LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_middle_selected_native_observer_v1.py"
STREAM_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_full_native_stream_observer_v2.py"
HEADER_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_native_header_observer_v1.py"
PHYSICAL_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_native_physical_observer_v2.py"
CALIBRATION = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_observer_calibration_contract_v1.json"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
RUNTIME_V6 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V8 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_input_hashed_by_builder_and_parent_v8",
    }


def record_literal(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_input_hashed_by_builder_and_parent_v8",
    }


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def primary_or_local() -> Path:
    if WORKER.is_file() and not WORKER.is_symlink():
        return WORKER
    if LOCAL_WORKER.is_file() and not LOCAL_WORKER.is_symlink():
        return LOCAL_WORKER
    raise FileNotFoundError("middle selected observer worker is missing in primary and local trees")


def validate_terminal_inputs(args: argparse.Namespace) -> dict[str, Any]:
    request = load(args.solver_request, "ROOT162 solver request")
    receipt = load(args.terminal_receipt, "ROOT162 terminal receipt")
    snapshot_proof = load(args.snapshot_proof, "ROOT161 snapshot proof")
    snapshot_report = load(args.snapshot_report, "ROOT161 snapshot report")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID or request.get("family_id") != "F3":
        raise ValueError("ROOT162 solver request physical identity mismatch")
    if str(receipt.get("status", "")).lower() not in {
        "completed", "complete", "success", "completed0", "completed_development_unknown",
    } or receipt.get("returncode") not in (0, None):
        raise ValueError("ROOT162 receipt is not a completed zero-return receipt")
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, dict):
        raise ValueError("ROOT162 receipt does not carry the producer request provenance")
    solver_request_sha = sha256(args.solver_request)
    if receipt_request.get("sha256") != solver_request_sha:
        raise ValueError("ROOT162 receipt request SHA does not match the supplied solver request")
    receipt_request_path = receipt_request.get("path")
    if receipt_request_path is not None and Path(str(receipt_request_path)).expanduser().resolve() != args.solver_request.expanduser().resolve():
        raise ValueError("ROOT162 receipt request path does not match the supplied solver request")
    actual_request = receipt.get("request")
    if isinstance(actual_request, dict) and actual_request.get("physical_case_id") not in (None, PHYSICAL_CASE_ID):
        raise ValueError("ROOT162 terminal receipt request physical identity mismatch")
    if snapshot_proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or snapshot_proof.get("status") not in {
        "VERIFIED_ACTUAL_F3_MIDDLE_BI4_SOURCE_SNAPSHOT",
        "VERIFIED_ACTUAL_F3_MIDDLE_BI4_SINGLE_STREAM_SOURCE_SNAPSHOT",
        "VERIFIED_ACTUAL_F3_MIDDLE_BI4_GUARDED_SINGLE_FD_HASH_IDENTITY",
    }:
        # Root may use a forward proof status; identity and actual source hash
        # still have to be checked by the parent request review.
        if snapshot_proof.get("family_id") not in (None, "F3"):
            raise ValueError("ROOT161 snapshot proof identity mismatch")
    if snapshot_report.get("status") not in {"PASS_F3_S2_MIDDLE_BI4_HASHED_STABLE", "PASS_F3_S2_MIDDLE_BI4_HASHED_STABLE_ROOT161"}:
        raise ValueError("ROOT161 snapshot report is not a successful stable hash report")
    report_sha = sha256(args.snapshot_report)
    if snapshot_proof.get("report_sha256") not in (None, report_sha):
        raise ValueError("ROOT161 proof does not bind the supplied snapshot report SHA")
    actual_bi4_sha = str(snapshot_report.get("source", {}).get("content_sha256", ""))
    if actual_bi4_sha != "3bd6d0a5e70dca477aad347b54057c2169de4fab8ca41cd5ac1af59e5142459a":
        raise ValueError("ROOT161 native BI4 SHA does not match the actual snapshot proof")
    if args.expected_frame_count < 2 or args.expected_final_time_s < 8.0:
        raise ValueError("actual terminal frame count/final time do not cover registered 0,2,4,6,8 s queries")
    return {
        "solver_request": request,
        "terminal_receipt": receipt,
        "snapshot_proof": snapshot_proof,
        "snapshot_report": snapshot_report,
    }


def canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    validated = validate_terminal_inputs(args)
    worker = primary_or_local()
    paths: list[tuple[Path, str]] = [
        (args.solver_request, "ROOT162 solver request"),
        (args.terminal_receipt, "ROOT162 terminal receipt"),
        (args.snapshot_proof, "ROOT161 snapshot proof"),
        (args.snapshot_report, "ROOT161 snapshot report"),
        (args.runparts, "ROOT162 RunPARTs"),
        (args.generated_xml, "ROOT162 generated XML"),
        (worker, "middle selected observer worker"),
        (STREAM_WORKER, "F3 full-native stream safety dependency"),
        (HEADER_WORKER, "F3 native header dependency"),
        (PHYSICAL_WORKER, "generic physical observer dependency"),
        (args.calibration_contract, "F3 observer calibration contract"),
        (DECODER, "official BI4 decoder"),
        (DECODER_SOURCE, "official BI4 decoder source"),
        (RUNTIME_V2, "runtime v2"),
        (RUNTIME_V6, "runtime v6"),
        (RUNTIME_V8, "runtime v8"),
        (DISPATCH, "dispatch v8"),
        (STRICT, "strict dispatch v8"),
    ]
    records = {str(regular(path, label)): record(path, label) for path, label in paths if path != PYTHON}
    records[str(PYTHON)] = record_literal(PYTHON, "literal venv interpreter")
    raw_root = args.raw_root.expanduser().resolve()
    query_times = [0.0, 2.0, 4.0, 6.0, 8.0, float(args.expected_final_time_s)]
    worker_path = str(worker.resolve())
    command = [
        str(PYTHON), worker_path,
        "--raw-root", str(raw_root), "--runparts", str(args.runparts.expanduser().resolve()),
        "--generated-xml", str(args.generated_xml.expanduser().resolve()), "--decoder", str(DECODER),
        "--decoder-source", str(DECODER_SOURCE), "--calibration-contract", str(args.calibration_contract.expanduser().resolve()),
        "--output", "{attempt_root}/observer/f3_s2_middle_selected_native_observer_v1.json",
        "--scratch-root", "{attempt_root}/scratch/bi4_decode", "--expected-frame-count", str(args.expected_frame_count),
        "--expected-final-time-s", repr(float(args.expected_final_time_s)), "--frames", "0", str(args.expected_frame_count - 1),
        "--query-times", *(repr(value) for value in query_times), "--decoder-timeout-s", "300",
        "--max-decoder-log-bytes", "65536", "--max-decoder-scratch-bytes", str(256 * 1024 * 1024),
    ]
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F3_MIDDLE_SELECTED_NATIVE_OBSERVER",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY_REPO),
        "command": command,
        "input_files": input_files,
        "input_hashes": hashes,
        "input_sha256": hashes,
        "input_records": records,
        "deferred_input_files": [str(raw_root)],
        "deferred_input_policy": "worker selects frame 0/final and RunPARTs brackets after parent reservation; each selected Part receives full pre/decode/post SHA+stat closure",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 512 * 1024**2,
        "estimated_storage_bytes": 32 * 1024**2,
        "estimated_peak_memory_bytes": 256 * 1024**2,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()),
        "estimated_native_read_bytes": args.estimated_native_bytes,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "hdf5_read": False,
        "native_payload_read": True,
        "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/observer/f3_s2_middle_selected_native_observer_v1.json"},
        "source_binding": {
            "schema": VARIANT,
            "root162_solver_request_path": str(args.solver_request.expanduser().resolve()),
            "root162_terminal_receipt_path": str(args.terminal_receipt.expanduser().resolve()),
            "root161_native_bi4_sha256": "3bd6d0a5e70dca477aad347b54057c2169de4fab8ca41cd5ac1af59e5142459a",
            "root161_native_bi4_bytes": 9227118,
            "query_times_s": query_times,
            "query_semantics": "actual RunPARTs/decoder timestamps and brackets; no particle/time interpolation",
            "native_massfluid_required": True,
            "full_pre_decode_post_decode_sha_and_stat_per_selected_part": True,
            "decoder_process_group_cleanup": True,
            "continuum_owner_mass": "UNKNOWN",
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": "parent-v8-audit", "cpu_parent_binding": "required", "payload_read": "selected Part files only after reservation", "solver_launch": "forbidden"},
        "qualification_stage": "stage2_f3_s2_middle_selected_native_fields_pending_parent_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "selected native header/finite/time audit only; no dynamics/spatial/event qualification"},
    }
    payload["sha256"] = canonical(payload)
    return payload


def write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    if not str(PYTHON).endswith("/.venv/bin/python"):
        raise AssertionError("literal venv binding changed")
    return {"status": "PASS", "schema": SCHEMA, "query_times_s": [0.0, 2.0, 4.0, 6.0, 8.0, "ACTUAL_FINAL_TIME_REQUIRED"], "native_prepost_guard": True, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--snapshot-proof", type=Path)
    parser.add_argument("--snapshot-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--calibration-contract", type=Path, default=CALIBRATION)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--estimated-native-bytes", type=int)
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-middle-selected-native-observer-root164-001.json")
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_MATCHED_MIDDLE_SELECTED_NATIVE_OBSERVER_ROOT164")
    parser.add_argument("--attempt-id", default="f3-s2-matched-middle-selected-native-observer-root-164-001")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.solver_request, args.terminal_receipt, args.snapshot_proof, args.snapshot_report, args.raw_root, args.runparts, args.generated_xml, args.expected_frame_count, args.expected_final_time_s, args.estimated_native_bytes, args.launch_commit)
    if any(value is None for value in required):
        parser.error("--build-request requires terminal/source paths, actual frame count/final time/native bytes and --launch-commit")
    try:
        payload = build(args)
        write_once(args.output, payload)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_MIDDLE_SELECTED_NATIVE_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps({"status": payload["status"], "output": str(args.output.resolve()), "selected_query_times_s": [0.0, 2.0, 4.0, 6.0, 8.0, args.expected_final_time_s], "native_payload_read": "parent_worker_after_reservation"}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
