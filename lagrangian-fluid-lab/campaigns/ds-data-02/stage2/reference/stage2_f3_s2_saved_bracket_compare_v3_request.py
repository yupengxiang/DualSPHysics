#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the forward v3 saved-bracket comparison request.

This additive request preserves the v2 proof/source closure and switches to
the v3 comparison worker.  Full middle/fine observer JSON is read only under
the parent guard; the request reserves 8GiB (4GiB minimum) for parsing the
fine full report and does not read native payloads.
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
V2_REQUEST_PATH = HERE / "stage2_f3_s2_saved_bracket_compare_v2_request.py"
V3_WORKER_PATH = HERE / "stage2_f3_s2_saved_bracket_compare_v3.py"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.saved-bracket-comparison-request.v3"


def _load_v2_request():
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_saved_bracket_compare_v2_request_consumed", V2_REQUEST_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V2_REQUEST_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2_REQUEST = _load_v2_request()


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": digest, "content_scope": "small_v3_comparison_worker_hashed_by_builder_and_parent_v8"}


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    base = V2_REQUEST.build(args)
    worker = V3_WORKER_PATH.expanduser().resolve()
    worker_record = _record(worker, "F3 saved-bracket comparison v3 worker")
    records = dict(base["input_records"])
    records[worker_record["path"]] = worker_record
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files}
    output_path = "{attempt_root}/comparison/f3_s2_saved_bracket_comparison_v3.json"
    command = list(base["command"])
    if len(command) < 2:
        raise ValueError("base v2 comparison command has no worker operand")
    command[1] = str(worker)
    try:
        output_index = command.index("--output")
    except ValueError as exc:
        raise ValueError("base v2 comparison command lacks --output") from exc
    command[output_index + 1] = output_path
    value: dict[str, Any] = dict(base)
    value.update({"schema": SCHEMA, "variant_schema": VARIANT, "status": "READY_FOR_PARENT_V8_F3_SAVED_BRACKET_COMPARISON_V3", "command": command, "input_files": input_files, "input_hashes": hashes, "input_sha256": hashes, "input_records": records, "max_memory_bytes": 8 * 1024**3, "estimated_peak_memory_bytes": 8 * 1024**3, "estimated_storage_bytes": 64 * 1024**2, "estimated_input_read_passes": 1, "output": {"atomic": True, "refuse_overwrite": True, "path": output_path}, "qualification_stage": "stage2_f3_s2_saved_bracket_report_only_diagnostics_v3"})
    value["source_binding"] = dict(base.get("source_binding", {}))
    value["source_binding"].update({"comparison_worker_schema": "ds02.stage2.f3-s2.saved-bracket-comparison.v3", "full_report_read_strategy": "one stable bytes read followed by json.loads; bytes released after parse", "full_report_memory_floor_bytes": 4 * 1024**3, "requested_memory_bytes": 8 * 1024**3, "interpolation": False, "adjacent_grid_truth": False})
    value["resource_guard"] = dict(base.get("resource_guard", {}))
    value["resource_guard"].update({"full_report_json_read_after_parent_reservation": True, "native_payload_read": False})
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
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    base = V2_REQUEST.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    return {"status": "PASS", "schema": SCHEMA, "variant_schema": VARIANT, "minimum_memory_bytes": 4 * 1024**3, "requested_memory_bytes": 8 * 1024**3, "single_json_read": True, "native_payload_read": False, "interpolation": False, "truth_credit": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--coarse-report", type=Path); parser.add_argument("--coarse-proof", type=Path); parser.add_argument("--coarse-report-sha256"); parser.add_argument("--estimated-coarse-bytes", type=int)
    parser.add_argument("--middle-report", type=Path); parser.add_argument("--middle-proof", type=Path); parser.add_argument("--middle-report-sha256"); parser.add_argument("--estimated-middle-bytes", type=int)
    parser.add_argument("--fine-report", type=Path); parser.add_argument("--fine-proof", type=Path); parser.add_argument("--fine-report-sha256"); parser.add_argument("--estimated-fine-bytes", type=int)
    parser.add_argument("--launch-commit")
    parser.add_argument("--output", type=Path, default=HERE.parents[5] / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-saved-bracket-comparison-v3-root172-001.json")
    parser.add_argument("--case-id", default="F3_S2_SAVED_BRACKET_COMPARISON_ROOT172_V3")
    parser.add_argument("--attempt-id", default="f3-s2-saved-bracket-comparison-root-172-v3-001")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.coarse_report, args.coarse_proof, args.coarse_report_sha256, args.estimated_coarse_bytes, args.middle_report, args.middle_proof, args.middle_report_sha256, args.estimated_middle_bytes, args.fine_report, args.fine_proof, args.fine_report_sha256, args.estimated_fine_bytes, args.launch_commit)
    if any(value is None for value in required):
        parser.error("--build-request requires all three deferred report/proof paths, SHA/size estimates, and --launch-commit")
    try:
        value = build(args); _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_SAVED_BRACKET_V3_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False)); return 1
    print(json.dumps({"status": value["status"], "output": str(_path(args.output)), "requested_memory_bytes": 8 * 1024**3, "native_payload_read": False, "interpolation": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
