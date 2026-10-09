#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the additive F3-S2 V6 support request.

V6 is a forward request over the consumed V5 request.  It changes only the
worker/report path and records the static pre/post identity-field comparison
fix.  The worker's full fixture self-test exercises the delegated build
before this request is usable.  No GenCase, solver, BI4, HDF5, or VTK payload
is read while building the request; Fluid/Bound VTK remain worker-owned after
the parent reservation.
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
V5_REQUEST = HERE / "stage2_f3_s2_initial_support_audit_v5_request.py"
V6_WORKER = HERE / "stage2_f3_s2_initial_support_audit_v6_worker.py"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v6-request"
V5_WORKER_SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v5"
V6_WORKER_SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v6"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V5 = load_module("stage2_f3_s2_initial_support_audit_v5_request_for_v6", V5_REQUEST)


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
    return {
        "path": str(path), "label": label, "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino),
        "sha256": sha256(path), "content_scope": "small_input_hashed_by_builder_and_parent_v8",
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    staging = args.output.with_name(f".{args.output.name}.{os.getpid()}.v5-staging.json")
    adapted = argparse.Namespace(**vars(args))
    adapted.output = staging
    payload = V5.build(adapted)
    if staging.exists() or staging.is_symlink():
        staging.unlink()

    records = payload.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("v5 builder did not emit input_records")
    v5_worker = Path(V5.V5_WORKER).expanduser().resolve()
    v6_worker = regular(V6_WORKER, "F3 v6 support worker")
    if str(v5_worker) not in records:
        raise ValueError("v5 input_records do not contain the delegated v5 worker")
    records[str(v6_worker)] = record(v6_worker, "F3 v6 static-identity support worker")

    command = [str(item) for item in payload.get("command", [])]
    replaced_worker = False
    for index, token in enumerate(command):
        try:
            if Path(token).expanduser().resolve() == v5_worker:
                command[index] = str(v6_worker)
                replaced_worker = True
        except (OSError, RuntimeError):
            continue
    if not replaced_worker:
        raise ValueError("v5 command does not contain the delegated v5 worker path")
    command = [token.replace("stage2_f3_s2_initial_support_audit_v5.json", "stage2_f3_s2_initial_support_audit_v6.json") for token in command]

    payload["request_variant_schema"] = REQUEST_VARIANT_SCHEMA
    payload["status"] = "READY_FOR_PARENT_V8_F3_INITIAL_SUPPORT_V6"
    payload["worker_schema"] = V6_WORKER_SCHEMA
    payload["delegated_worker_schema"] = V5_WORKER_SCHEMA
    payload["qualification_stage"] = "stage2_f3_s2_initial_support_idp_axis_owner_audit_v6_pending_parent_guard"
    payload["command"] = command
    payload["input_records"] = records
    payload["input_files"] = sorted(records)
    payload["input_hashes"] = {path: records[path]["sha256"] for path in payload["input_files"]}
    payload["estimated_input_read_bytes"] = sum(int(records[path]["bytes"]) for path in payload["input_files"]) + sum(int(item["bytes"]) for item in payload.get("worker_owned_input_stats_at_build", {}).values())
    payload["static_record_comparison_contract"] = {
        "worker_schema": V6_WORKER_SCHEMA,
        "identity_fields_only": ["path", "bytes", "sha256", "mtime_ns", "ctime_ns", "st_dev", "st_ino"],
        "descriptive_fields_excluded": ["label"],
        "all_identity_fields_required_equal": True,
        "delegated_v5_q_receipt_join_preserved": True,
        "failed_v5_output_not_reused": True,
    }
    payload["source_binding"] = dict(payload.get("source_binding", {}))
    payload["source_binding"]["static_record_comparison_contract"] = payload["static_record_comparison_contract"]
    payload["output"] = dict(payload.get("output", {}))
    output_path = str(payload["output"].get("path", ""))
    payload["output"]["path"] = output_path.replace("stage2_f3_s2_initial_support_audit_v5.json", "stage2_f3_s2_initial_support_audit_v6.json")
    payload["output"]["actual_receipt_output_root_authoritative"] = True
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
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
            handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    # V5's self-test invokes the strict q/receipt fixture; V6 adds the full
    # delegated build_report fixture, which catches the original static-label
    # failure instead of testing only command assembly.
    worker = load_module("stage2_f3_s2_initial_support_audit_v6_worker_for_request_test", V6_WORKER)
    result = worker.self_test()
    if result.get("status") != "PASS":
        raise AssertionError(result)
    return {
        "status": "PASS", "schema": REQUEST_SCHEMA,
        "request_variant_schema": REQUEST_VARIANT_SCHEMA,
        "worker_schema": V6_WORKER_SCHEMA, "delegated_worker_schema": V5_WORKER_SCHEMA,
        "static_identity_fields_only": True, "full_build_report_fixture": True,
        "vtk_payload_read_by_builder": False, "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "fluid-vtk", "bound-vtk", "source-xml", "source-control", "output", "support-contract"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_SUPPORT_ROOT_128_V6")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp015-support-v6-root-128-001")
    parser.add_argument("--launch-commit", required=False)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.fluid_vtk, args.bound_vtk, args.source_xml, args.source_control, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires q/receipt/generated/VTK/source/output and launch commit")
    payload = build(args)
    write_new(args.output, payload)
    print(json.dumps({"status": payload["status"], "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "output": str(args.output.resolve()), "static_identity_fields_only": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
