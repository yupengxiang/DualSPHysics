#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the additive ROOT124 F5 Y-zero diagnostic request.

The V9 request and reader are retained.  This adapter changes only the
worker/report path and adds strict q123/receipt identity closure.  The
builder records XML/source/request metadata and VTK stat-only records; it
never hashes or reads VTK payload bytes before the parent guard.
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
V9_REQUEST = HERE / "stage2_f5_s1_clipplane_yzero_geometry_diagnostic_v9_request.py"
V10_WORKER = HERE / "stage2_f5_s1_clipplane_yzero_geometry_diagnostic_v10_worker.py"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v10-request"
V9_WORKER_SCHEMA = "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v9"
V10_WORKER_SCHEMA = "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v10"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V9 = load_module("stage2_f5_yzero_geometry_v9_request_for_v10", V9_REQUEST)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {resolved}")
    return resolved


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path), "content_scope": "small_input_hashed_by_builder_and_parent_v8"}


def build(args: argparse.Namespace) -> dict[str, Any]:
    staging = args.output.with_name(f".{args.output.name}.{os.getpid()}.v9-staging.json")
    adapted = argparse.Namespace(**vars(args))
    adapted.output = staging
    payload = V9.build(adapted)
    if staging.exists() or staging.is_symlink():
        staging.unlink()
    records = payload.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("v9 builder did not emit input_records")
    v9_worker = Path(V9.V9_WORKER_PATH).expanduser().resolve()
    v10_worker = regular(V10_WORKER, "F5 V10 geometry worker")
    if str(v9_worker) not in records:
        raise ValueError("v9 input_records do not contain the delegated V9 worker")
    records[str(v10_worker)] = record(v10_worker, "F5 V10 strict q123 geometry worker")
    command = [str(item) for item in payload.get("command", [])]
    replaced_worker = False
    for index, token in enumerate(command):
        try:
            if Path(token).expanduser().resolve() == v9_worker:
                command[index] = str(v10_worker); replaced_worker = True
        except (OSError, RuntimeError):
            continue
    if not replaced_worker:
        raise ValueError("v9 command does not invoke the delegated V9 worker")
    command = [token.replace("stage2_f5_s1_clipplane_yzero_geometry_diagnostic_v9.json", "stage2_f5_s1_clipplane_yzero_geometry_diagnostic_v10.json") for token in command]
    payload["request_variant_schema"] = REQUEST_VARIANT_SCHEMA
    payload["worker_schema"] = V10_WORKER_SCHEMA
    payload["delegated_worker_schema"] = V9_WORKER_SCHEMA
    payload["status"] = "READY_FOR_PARENT_V8_F5_YZERO_GEOMETRY_DIAGNOSTIC_V10"
    payload["qualification_stage"] = "stage2_f5_s1_yzero_global_shape_idp_overlap_diagnostic_v10_pending_parent_guard"
    payload["command"] = command
    payload["input_records"] = records
    payload["input_files"] = sorted(records)
    payload["input_hashes"] = {path: records[path]["sha256"] for path in payload["input_files"]}
    output_path = "{attempt_root}/report/stage2_f5_s1_clipplane_yzero_geometry_diagnostic_v10.json"
    payload["output"] = dict(payload.get("output", {})); payload["output"]["path"] = output_path
    payload["output"]["actual_receipt_output_root_authoritative"] = True
    payload["source_binding"] = dict(payload.get("source_binding", {}))
    payload["source_binding"]["strict_q_receipt_join"] = {"worker_checks_before_dynamic_payload_read": True, "receipt_request_exact_q": True, "receipt_request_sha256_exact_q": True, "receipt_family_case_attempt_exact": True, "actual_receipt_output_root_authoritative": True}
    payload["source_binding"]["all_shapes_scope"] = ["fluid", "fixed_boundary", "moving_boundary", "forcing", "shape_operations"]
    payload["source_binding"]["all_shapes_require_comparison"] = True
    payload["source_binding"]["all_shapes_comparison_executed_by_worker"] = False
    payload["parent_v8_input_closure"] = dict(payload.get("parent_v8_input_closure", {}))
    payload["parent_v8_input_closure"]["worker_first_payload_hash_after_parent_reservation"] = True
    payload["parent_v8_input_closure"]["parent_v8_does_not_hash_worker_owned_vtk"] = True
    payload["worker_owned_input_hashes"] = dict(payload.get("worker_owned_input_hashes", {})); payload["worker_owned_input_hashes"]["hash_status"] = "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES"
    payload["strict_q_receipt_join_contract"] = {"q123_request_exact_receipt_request": True, "q123_request_sha256_exact": True, "actual_receipt_output_root_authoritative": True, "planned_root_non_authoritative": True, "all_shapes_comparison_deferred_to_json_only_worker": True}
    payload["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "Y-zero geometry diagnostic only; all-shape fixed/moving/fluid comparison is a separate JSON-only task"}
    payload["estimated_input_read_bytes"] = sum(int(item.get("bytes", 0)) for item in records.values()) + sum(int(item.get("bytes", 0)) for item in payload.get("worker_owned_input_stats_at_build", {}).values() if isinstance(item, dict))
    payload["sha256"] = hashlib.sha256(json.dumps({key: value for key, value in payload.items() if key != "sha256"}, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return payload


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    worker = load_module("stage2_f5_yzero_geometry_v10_worker_for_request_test", V10_WORKER)
    result = worker.self_test()
    if result.get("status") != "PASS":
        raise AssertionError(result)
    return {"status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "worker_schema": V10_WORKER_SCHEMA, "strict_q_receipt_join": True, "all_shapes_comparison_deferred": True, "vtk_payload_read_by_builder": False, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--grid", choices=("dp005",), default="dp005")
    for name in ("gencase-request", "receipt", "generated-xml", "candidate-def", "source-def", "candidate-motion", "source-motion", "fluid-vtk", "bound-vtk", "clip-evidence", "output", "support-contract"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id", default="F5_S1_YZERO_GEOMETRY_DIAGNOSTIC_ROOT_124_V10")
    parser.add_argument("--attempt-id", default="f5-s1-yzero-geometry-diagnostic-v10-root-124-001")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.fluid_vtk, args.bound_vtk, args.clip_evidence, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires q123 terminal inputs, clip evidence, output and launch commit")
    payload = build(args); write_new(args.output, payload)
    print(json.dumps({"status": payload["status"], "schema": payload["schema"], "worker_schema": payload["worker_schema"], "output": str(args.output.resolve()), "vtk_payload_read_by_builder": False}, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
