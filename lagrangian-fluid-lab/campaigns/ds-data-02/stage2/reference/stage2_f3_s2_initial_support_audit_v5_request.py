#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the additive F3-S2 v5 support request.

The v4 request and its v3 worker remain immutable.  This builder reuses the
v4 source/control contract, swaps only the worker and report filename, and
adds a strict producer tuple contract: the worker must verify
``receipt.request == q`` and ``receipt.request_sha256 == SHA256(q)`` before
reading any dynamic VTK payload.  The terminal receipt's actual output root
is authoritative; the request's planned output root is descriptive only.
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
V4_REQUEST = HERE / "stage2_f3_s2_initial_support_audit_v4_request.py"
V5_WORKER = HERE / "stage2_f3_s2_initial_support_audit_v5_worker.py"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v5-request"
V3_WORKER_SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v3"
V5_WORKER_SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v5"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V4 = load_module("stage2_f3_s2_initial_support_audit_v4_request_for_v5", V4_REQUEST)


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


def build(args: argparse.Namespace) -> dict[str, Any]:
    # V4 performs the existing q/receipt/source checks and creates a v3
    # support contract.  We stage its request output, then adapt the returned
    # in-memory payload without touching any already consumed v3/v4 artifact.
    staging = args.output.with_name(f".{args.output.name}.{os.getpid()}.v4-staging.json")
    adapted = argparse.Namespace(**vars(args))
    adapted.output = staging
    payload = V4.build(adapted)
    if staging.exists() or staging.is_symlink():
        staging.unlink()

    records = payload.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("v4 builder did not emit input_records")

    v4_worker = Path(V4.V3.WORKER).expanduser().resolve()
    v5_worker = regular(V5_WORKER, "F3 v5 support worker")
    v4_worker_key = str(v4_worker)
    v5_worker_key = str(v5_worker)
    if v4_worker_key not in records:
        raise ValueError("v4 input_records do not contain the delegated v3 worker")
    records[v5_worker_key] = record(v5_worker, "F3 v5 strict q/receipt support worker")

    command = [str(item) for item in payload.get("command", [])]
    replaced_worker = False
    for index, token in enumerate(command):
        try:
            token_path = Path(token).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if token_path == v4_worker:
            command[index] = str(v5_worker)
            replaced_worker = True
    if not replaced_worker:
        raise ValueError("v4 command does not contain the delegated v3 worker path")
    command = [
        token.replace("stage2_f3_s2_initial_support_audit_v3.json", "stage2_f3_s2_initial_support_audit_v5.json")
        for token in command
    ]

    payload["request_variant_schema"] = REQUEST_VARIANT_SCHEMA
    payload["status"] = "READY_FOR_PARENT_V8_F3_INITIAL_SUPPORT_V5"
    payload["worker_schema"] = V5_WORKER_SCHEMA
    payload["delegated_worker_schema"] = V3_WORKER_SCHEMA
    payload["qualification_stage"] = "stage2_f3_s2_initial_support_idp_axis_owner_audit_v5_pending_parent_guard"
    payload["command"] = command
    payload["input_records"] = records
    payload["input_files"] = sorted(records)
    payload["input_hashes"] = {path: records[path]["sha256"] for path in payload["input_files"]}
    payload["estimated_input_read_bytes"] = sum(int(records[path]["bytes"]) for path in payload["input_files"]) + sum(int(item["bytes"]) for item in payload.get("worker_owned_input_stats_at_build", {}).values())
    payload["strict_q_receipt_join_contract"] = {
        "worker_checks_before_dynamic_payload_read": True,
        "receipt_request_exact_q": True,
        "receipt_request_sha256_exact_q": True,
        "receipt_family_case_attempt_exact": True,
        "receipt_actual_output_root_authoritative": True,
        "planned_output_root_not_authoritative": True,
        "mismatch_is_nonzero_failure": True,
        "delegated_v3_worker_unchanged": True,
    }
    payload["source_binding"] = dict(payload.get("source_binding", {}))
    payload["source_binding"]["strict_q_receipt_join"] = payload["strict_q_receipt_join_contract"]
    payload["output"] = dict(payload.get("output", {}))
    output_path = str(payload["output"].get("path", ""))
    payload["output"]["path"] = output_path.replace("stage2_f3_s2_initial_support_audit_v3.json", "stage2_f3_s2_initial_support_audit_v5.json")
    payload["output"]["actual_receipt_output_root_authoritative"] = True
    payload["output"]["planned_request_output_root_is_metadata_only"] = True
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
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    result = V4.self_test()
    if result.get("status") != "PASS":
        raise AssertionError(result)
    worker = load_module("stage2_f3_s2_initial_support_audit_v5_worker_for_request_test", V5_WORKER)
    worker_result = worker.self_test()
    if worker_result.get("status") != "PASS":
        raise AssertionError(worker_result)
    return {
        "status": "PASS",
        "schema": REQUEST_SCHEMA,
        "request_variant_schema": REQUEST_VARIANT_SCHEMA,
        "worker_schema": V5_WORKER_SCHEMA,
        "delegated_worker_schema": V3_WORKER_SCHEMA,
        "strict_q_receipt_join": True,
        "receipt_actual_output_root_authoritative": True,
        "vtk_payload_read_by_builder": False,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "fluid-vtk", "bound-vtk", "source-xml", "source-control", "output", "support-contract"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_SUPPORT_ROOT_121_V5")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp015-support-v5-root-121-001")
    parser.add_argument("--launch-commit", required=False)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.fluid_vtk, args.bound_vtk, args.source_xml, args.source_control, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires q/receipt/generated/VTK/source/output and launch commit")
    payload = build(args)
    write_new(args.output, payload)
    print(json.dumps({"status": payload["status"], "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "output": str(args.output.resolve()), "strict_q_receipt_join": True, "receipt_actual_output_root_authoritative": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
