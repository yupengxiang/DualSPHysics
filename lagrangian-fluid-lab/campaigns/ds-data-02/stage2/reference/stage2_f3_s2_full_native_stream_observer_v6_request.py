#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the v6 full-native request for the schema-correct v5 worker.

This forward request keeps the consumed v4 and v5 requests immutable.  It
reuses v5's corrected Part/tree byte accounting, then changes only the
worker, output names, and compact-summary semantic binding.  The v5 worker
keeps the large full report in the consumed v3 schema so existing comparison
consumers remain compatible; its compact sidecar is a distinct v5 schema.
No solver or native payload is read while building this request.
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
V5_REQUEST_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v5_request.py"
V5_WORKER_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v5.py"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.full-native-stream-observer-request.v6"


def _load_v5_request():
    spec = importlib.util.spec_from_file_location(
        "stage2_f3_s2_full_native_stream_observer_v5_request_dependency",
        V5_REQUEST_PATH,
    )
    if spec is None or spec.loader is None:
        raise ImportError(V5_REQUEST_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V5_REQUEST = _load_v5_request()


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _record(path: Path, label: str) -> dict[str, Any]:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": digest,
        "content_scope": "small_v5_worker_source_hashed_by_builder_and_parent_v8",
    }


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()
    ).hexdigest()


def _set_after_flag(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError as exc:
        raise ValueError(f"base v5 command lacks {flag}") from exc
    if index + 1 >= len(command):
        raise ValueError(f"base v5 command has no value after {flag}")
    command[index + 1] = value


def build(args: argparse.Namespace) -> dict[str, Any]:
    base = V5_REQUEST.build(args)
    worker = _path(V5_WORKER_PATH)
    worker_record = _record(worker, "full native v5 schema-correct compact-summary worker")

    records = dict(base.get("input_records", {}))
    records[worker_record["path"]] = worker_record
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files if records[path].get("sha256") is not None}

    command = list(base.get("command", []))
    if len(command) < 2:
        raise ValueError("base v5 command has no worker operand")
    command[1] = str(worker)
    output_path = "{attempt_root}/observer/f3_s2_full_native_stream_observer_v5.json"
    summary_path = "{attempt_root}/observer/f3_s2_full_native_stream_observer_v5.summary.json"
    _set_after_flag(command, "--output", output_path)
    _set_after_flag(command, "--summary-output", summary_path)

    value: dict[str, Any] = dict(base)
    value.update({
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F3_FULL_NATIVE_STREAM_V6",
        "command": command,
        "input_files": input_files,
        "input_hashes": hashes,
        "input_sha256": hashes,
        "input_records": records,
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "path": output_path,
            "compact_summary_path": summary_path,
            "full_report_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v3",
            "compact_summary_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5",
        },
        "qualification_stage": "stage2_f3_s2_full_native_stream_v6_pending_parent_guard",
    })
    value["source_binding"] = dict(base.get("source_binding", {}))
    value["source_binding"].update({
        "observer_worker_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5",
        "full_report_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v3",
        "compact_summary_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5",
        "compact_summary_path": summary_path,
        "compact_summary_max_selected_observations": 12,
        "compact_summary_scope": "full report exact path/bytes/SHA plus header/count/lifecycle/query endpoint index generated in the same guard",
        "query_bracket_frame_keys": ["lower_frame", "upper_frame"],
        "query_bracket_index_keys": "legacy fallback only when frame keys are absent",
        "first_missing_semantics": "derived from first per-frame disappeared_idp event; consumed v2 first_missing_frame is not used",
        "lifecycle_event_summary": "fluid/fixed/moving/floating XML-range diagnostics, active sample mass, censoring; physical fate/flux UNKNOWN",
        "native_read_passes": int(base.get("source_binding", {}).get("native_read_passes", 4)),
    })
    value["resource_guard"] = dict(base.get("resource_guard", {}))
    value["resource_guard"].update({
        "summary_written_in_same_guard": True,
        "full_report_payload_not_reopened_for_summary": True,
        "summary_schema_checked_against_full_report_v3": True,
    })
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
    base = V5_REQUEST.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    worker_spec = importlib.util.spec_from_file_location("stage2_f3_s2_full_native_stream_observer_v5_selftest", V5_WORKER_PATH)
    if worker_spec is None or worker_spec.loader is None:
        raise ImportError(V5_WORKER_PATH)
    worker = importlib.util.module_from_spec(worker_spec)
    sys.modules[worker_spec.name] = worker
    worker_spec.loader.exec_module(worker)
    worker_result = worker.self_test()
    if worker_result.get("status") != "PASS":
        raise AssertionError("v5 worker self-test failed")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "worker_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5",
        "full_report_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v3",
        "compact_summary_schema": "ds02.stage2.f3-s2.full-native-stream-observer.v5",
        "query_bracket_frame_keys": ["lower_frame", "upper_frame"],
        "first_missing_derived_from_events": True,
        "native_read_passes": 4,
        "payload_read": False,
        "solver_started": False,
    }


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
    parser.add_argument("--calibration-contract", type=Path, default=V5_REQUEST.V4_REQUEST.V3_REQUEST.CALIBRATION)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--expected-dp-m", type=float)
    parser.add_argument("--expected-initial-fluid-count", type=int)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-9)
    parser.add_argument("--estimated-part-bytes", type=int)
    parser.add_argument("--estimated-native-tree-bytes", type=int)
    parser.add_argument("--estimated-output-records", type=int)
    parser.add_argument("--estimated-storage-bytes", type=int)
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_FULL_NATIVE_STREAM_ROOT177_OR_ROOT178_V6")
    parser.add_argument("--attempt-id", default="f3-s2-full-native-stream-root177-or-root178-v6-001")
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE.parents[5] / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-full-native-stream-observer-v6-root177-or-root178-001.json",
    )
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (
        args.solver_request, args.terminal_receipt, args.terminal_proof, args.source_snapshot_proof,
        args.source_snapshot_report, args.raw_root, args.runparts, args.generated_xml,
        args.expected_frame_count, args.expected_final_time_s, args.expected_dp_m,
        args.expected_initial_fluid_count, args.estimated_part_bytes, args.estimated_native_tree_bytes,
        args.estimated_storage_bytes, args.launch_commit,
    )
    if any(item is None for item in required):
        parser.error("--build-request requires terminal/source paths, frame contract, Part/tree byte estimates, and launch commit")
    try:
        value = build(args)
        _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_FULL_NATIVE_STREAM_V6_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": value["status"], "output": str(_path(args.output)), "compact_summary": value["output"]["compact_summary_path"], "native_read_passes": 4, "payload_read": "parent_after_reservation", "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
