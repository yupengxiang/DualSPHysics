#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the forward ROOT177/178 full-native v4 request.

The v3 request is immutable.  This additive builder reuses its strict
terminal/source join and changes only the observer worker, compact-summary
output, and native read accounting.  The decoder path performs four complete
raw-file passes per Part: the v2 pre-hash, the decoder's internal hash, the
official decoder input read, and the v2 post-hash.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V3_REQUEST_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v3_request.py"
V4_WORKER_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v4.py"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.full-native-stream-observer-request.v4"


def _load_v3_request():
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_full_native_stream_observer_v3_request_dependency", V3_REQUEST_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V3_REQUEST_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V3_REQUEST = _load_v3_request()


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": digest, "content_scope": "small_v4_worker_source_hashed_by_builder_and_parent_v8"}


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def _set_after_flag(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError as exc:
        raise ValueError(f"base v3 command lacks {flag}") from exc
    if index + 1 >= len(command):
        raise ValueError(f"base v3 command has no value after {flag}")
    command[index + 1] = value


def build(args: argparse.Namespace) -> dict[str, Any]:
    base = V3_REQUEST.build(args)
    worker = V4_WORKER_PATH.expanduser().resolve()
    worker_record = _record(worker, "full native v4 compact-summary worker")
    records = dict(base["input_records"])
    records[worker_record["path"]] = worker_record
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files if records[path].get("sha256") is not None}
    output_path = "{attempt_root}/observer/f3_s2_full_native_stream_observer_v4.json"
    summary_path = "{attempt_root}/observer/f3_s2_full_native_stream_observer_v4.summary.json"
    command = list(base["command"])
    if len(command) < 2:
        raise ValueError("base v3 command has no worker operand")
    command[1] = str(worker)
    _set_after_flag(command, "--output", output_path)
    command.extend(["--summary-output", summary_path])

    native_bytes = int(args.estimated_native_bytes)
    static_bytes = sum(int(item.get("bytes", 0)) for item in records.values())
    deferred_records = dict(base.get("deferred_input_records", {}))
    raw_record = dict(deferred_records.get("raw_root", {}))
    raw_record["estimated_passes"] = 4
    raw_record["pass_semantics"] = ["v2 pre-decode checked_hash", "decoder internal sha256_file", "official decoder input read", "v2 post-decode checked_hash"]
    deferred_records["raw_root"] = raw_record

    value: dict[str, Any] = dict(base)
    value.update({
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F3_FULL_NATIVE_STREAM_V4",
        "command": command,
        "input_files": input_files,
        "input_hashes": hashes,
        "input_sha256": hashes,
        "input_records": records,
        "deferred_input_records": deferred_records,
        "estimated_native_read_bytes": native_bytes * 4,
        "estimated_native_read_passes": 4,
        "estimated_input_read_bytes": native_bytes * 4 + static_bytes,
        "estimated_native_read_budget_note": "four raw passes per native Part: pre-hash, decoder internal hash, official decoder input, post-hash; output JSON hashing is separate",
        "output": {"atomic": True, "refuse_overwrite": True, "path": output_path, "compact_summary_path": summary_path},
        "source_binding": dict(base.get("source_binding", {})),
        "qualification_stage": "stage2_f3_s2_full_native_stream_v4_pending_parent_guard",
    })
    value["source_binding"].update({
        "observer_worker_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v4",
        "compact_summary_path": summary_path,
        "compact_summary_max_selected_observations": 12,
        "compact_summary_scope": "full report exact path/bytes/SHA plus header/count/lifecycle/query endpoint index generated in the same guard",
        "native_read_passes": 4,
        "native_read_pass_semantics": ["v2 pre-decode checked_hash", "decoder internal sha256_file", "official decoder input read", "v2 post-decode checked_hash"],
        "native_read_estimate": "four raw source/decoder passes per native Part; output JSON hashing is separate",
    })
    value["resource_guard"] = dict(base.get("resource_guard", {}))
    value["resource_guard"].update({"summary_written_in_same_guard": True, "full_report_payload_not_reopened_for_summary": True})
    value["sha256"] = _canonical(value)
    return value


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    base = V3_REQUEST.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    worker = importlib.util.spec_from_file_location("stage2_f3_s2_full_native_stream_observer_v4_selftest", V4_WORKER_PATH)
    if worker is None or worker.loader is None:
        raise ImportError(V4_WORKER_PATH)
    module = importlib.util.module_from_spec(worker)
    sys.modules[worker.name] = module
    worker.loader.exec_module(module)
    if module.self_test().get("status") != "PASS":
        raise AssertionError("v4 worker self-test failed")
    return {"status": "PASS", "schema": SCHEMA, "variant_schema": VARIANT, "native_read_passes": 4, "compact_summary_max_observations": 12, "full178_memory_floor_bytes": 4 * 1024**3, "payload_read": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--terminal-proof", type=Path)
    parser.add_argument("--source-snapshot-proof", type=Path)
    parser.add_argument("--source-snapshot-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--calibration-contract", type=Path, default=V3_REQUEST.CALIBRATION)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--expected-dp-m", type=float)
    parser.add_argument("--expected-initial-fluid-count", type=int)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-9)
    parser.add_argument("--estimated-native-bytes", type=int)
    parser.add_argument("--estimated-output-records", type=int)
    parser.add_argument("--estimated-storage-bytes", type=int)
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_FULL_NATIVE_STREAM_ROOT177_OR_ROOT178_V4")
    parser.add_argument("--attempt-id", default="f3-s2-full-native-stream-root177-or-root178-v4-001")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[5] / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-full-native-stream-observer-v4-root177-or-root178-001.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.solver_request, args.terminal_receipt, args.terminal_proof, args.source_snapshot_proof, args.source_snapshot_report, args.raw_root, args.runparts, args.generated_xml, args.expected_frame_count, args.expected_final_time_s, args.expected_dp_m, args.expected_initial_fluid_count, args.estimated_native_bytes, args.estimated_storage_bytes, args.launch_commit)
    if any(item is None for item in required):
        parser.error("--build-request requires terminal/source paths, grid/frame contract, byte estimates, and launch commit")
    try:
        value = build(args)
        _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_FULL_NATIVE_STREAM_V4_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False)); return 1
    print(json.dumps({"status": value["status"], "output": str(_path(args.output)), "native_read_passes": 4, "compact_summary": value["output"]["compact_summary_path"], "payload_read": "parent_after_reservation", "solver_started": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
