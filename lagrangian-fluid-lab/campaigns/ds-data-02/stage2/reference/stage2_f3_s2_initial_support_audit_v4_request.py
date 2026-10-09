#!/usr/bin/env python3
"""Forward the F3-S2 support request without pre-reading the forcing CSV.

The consumed v3 builder is retained byte-for-byte.  This additive wrapper
uses the completed ROOT120 receipt's existing control-file SHA as provenance,
records only the current CSV stat at build time, and leaves the complete
control-file SHA/pre/post read to the parent guard and v3 worker.  XML/code
inputs remain small builder-hashed inputs; Fluid/Bound VTK remain worker-owned
payloads.  No GenCase, solver, BI4, HDF5 or CSV content is read here.
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
V3_REQUEST = HERE / "stage2_f3_s2_initial_support_audit_v3_request.py"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v4-request"
V3_CONTRACT_SCHEMA = "ds02.stage2.f3.s2.initial-support-contract.v3"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V3 = load_module("stage2_f3_s2_support_v3_request_for_v4", V3_REQUEST)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def control_provenance(receipt_path: Path, control: Path) -> tuple[str, dict[str, Any]]:
    """Get the producer SHA without opening the current forcing payload."""
    receipt = load_json(receipt_path, "F3 GenCase receipt")
    # ROOT120 already completed the producer-side pre/post input checks.  Use
    # both terminal maps and require them to agree before carrying that SHA
    # forward.  This builder only stats the current path; it never re-reads
    # the CSV.  The parent v8/v5 guard must still hash it after reservation.
    producer_shas: dict[str, str] = {}
    for key in ("input_hashes_at_launch", "input_hashes_after_run"):
        mapping = receipt.get(key)
        if not isinstance(mapping, dict):
            continue
        for path, value in mapping.items():
            if (isinstance(path, str) and Path(path).name == control.name
                    and isinstance(value, str) and len(value) == 64):
                producer_shas[key] = value
                break
    if set(producer_shas) != {"input_hashes_at_launch", "input_hashes_after_run"}:
        raise ValueError("ROOT120 receipt lacks both control-file launch/end SHA records")
    if len(set(producer_shas.values())) != 1:
        raise ValueError("ROOT120 control-file launch/end SHA records differ")
    expected = producer_shas["input_hashes_at_launch"]
    resolved = control.expanduser().resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"F3 source control must be a regular file: {resolved}")
    stat = resolved.stat()
    return expected, {
        "path": str(resolved),
        "label": "F3 source control",
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": expected,
        "producer_receipt_sha256_at_launch": producer_shas["input_hashes_at_launch"],
        "producer_receipt_sha256_after_run": producer_shas["input_hashes_after_run"],
        "producer_receipt_pre_post_sha_equal": True,
        "content_scope": "parent_after_reservation_pre_post_hash",
        "content_read_by_builder": False,
        "sha_authority": "ROOT120_execution_receipt_input_hashes_at_launch_and_after_run",
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    receipt = args.receipt.expanduser().resolve()
    control = args.source_control.expanduser().resolve()
    expected_sha, control_record = control_provenance(receipt, control)
    original_record = V3.record

    def forward_record(path: Path, label: str) -> dict[str, Any]:
        resolved = path.expanduser().resolve()
        if resolved == control:
            return dict(control_record)
        return original_record(path, label)

    # V3 remains the worker and contract implementation.  Only its builder
    # record function is redirected for this one large source control file.
    V3.record = forward_record
    try:
        adapted = argparse.Namespace(**vars(args))
        # V3 writes its own immutable request as part of build().  Give it a
        # disposable metadata-only staging path, then write the corrected v4
        # envelope exactly once at the caller's requested destination.
        adapted.output = args.output.with_name(f".{args.output.name}.{os.getpid()}.v3-staging.json")
        if adapted.support_contract is None:
            adapted.support_contract = args.output.with_name(f"{args.output.stem}.support-contract.v3.json")
        payload = V3.build(adapted)
    finally:
        V3.record = original_record

    records = payload.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("v3 builder did not emit input_records")
    control_key = str(control)
    if records.get(control_key, {}).get("sha256") != expected_sha or records[control_key].get("content_read_by_builder") is not False:
        raise ValueError("v4 forcing record is not receipt-bound/stat-only")
    payload["request_variant_schema"] = REQUEST_VARIANT_SCHEMA
    payload["status"] = "READY_FOR_PARENT_V8_F3_INITIAL_SUPPORT_V4"
    payload["qualification_stage"] = "stage2_f3_s2_initial_support_idp_axis_owner_audit_v4_pending_parent_guard"
    payload["source_binding"] = dict(payload.get("source_binding", {}))
    payload["source_binding"]["forcing_control"] = {
        "path": control_key,
        "expected_sha256_from_root120_receipt": expected_sha,
        "builder_content_read": False,
        "parent_pre_post_hash_required": True,
        "missing_control_in_root120_generated_output": True,
    }
    payload["parent_v8_input_closure"] = dict(payload.get("parent_v8_input_closure", {}))
    payload["parent_v8_input_closure"].update({
        "forcing_control_sha_authority": "ROOT120_execution_receipt_input_hashes_at_launch_and_after_run",
        "forcing_control_producer_pre_post_sha_equal": True,
        "forcing_control_builder_read": False,
        "forcing_control_parent_pre_post_hash_required": True,
    })
    payload["input_content_scope"] = dict(payload.get("input_content_scope", {}))
    payload["input_content_scope"][control_key] = "parent_after_reservation_pre_post_hash"
    payload["input_hashes"][control_key] = expected_sha
    payload["input_records"][control_key] = control_record
    payload["input_files"] = sorted(payload["input_records"])
    payload["input_hashes"] = {key: payload["input_records"][key]["sha256"] for key in payload["input_files"]}
    payload["command"] = [str(item) for item in payload["command"]]
    payload["sha256"] = hashlib.sha256(json.dumps({key: value for key, value in payload.items() if key != "sha256"}, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return payload


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
            handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temp, path)


def self_test() -> dict[str, Any]:
    result = V3.self_test()
    if result.get("status") != "PASS":
        raise AssertionError(result)
    return {
        "status": "PASS",
        "schema": REQUEST_SCHEMA,
        "request_variant_schema": REQUEST_VARIANT_SCHEMA,
        "forcing_csv_builder_read": False,
        "forcing_csv_sha_authority": "ROOT120_execution_receipt_input_hashes",
        "forcing_csv_parent_pre_post_hash_required": True,
        "vtk_payload_read_by_builder": False,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "fluid-vtk", "bound-vtk", "source-xml", "source-control", "output", "support-contract"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_SUPPORT_ROOT_121_V4")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp015-support-v4-root-121-001")
    parser.add_argument("--launch-commit", required=False)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.fluid_vtk, args.bound_vtk, args.source_xml, args.source_control, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires q/receipt/generated/VTK/source/output/launch commit")
    # V3's defaults are overridden so the new root121 identity and contract
    # output are unambiguous; all terminal payload paths remain caller-bound.
    payload = build(args)
    write_new(args.output, payload)
    print(json.dumps({"status": payload["status"], "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "output": str(args.output.resolve()), "forcing_csv_builder_read": False, "forcing_csv_expected_sha256": payload["source_binding"]["forcing_control"]["expected_sha256_from_root120_receipt"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
