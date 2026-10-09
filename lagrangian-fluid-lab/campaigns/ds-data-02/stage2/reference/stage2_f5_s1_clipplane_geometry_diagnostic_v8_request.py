#!/usr/bin/env python3
"""Build the forward-only F5 V8 geometry/Idp diagnostic request.

The consumed V7 builder is loaded as an adapter, never edited.  Its small
input/source checks and worker-owned VTK stat-only records are retained, then
the adapter output is rewritten into a new V8 support contract and command.
The builder does not read VTK payload bytes or start GenCase/solver work.
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
V7_REQUEST_PATH = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v7_request.py"
V8_WORKER_PATH = HERE / "stage2_f5_s1_clipplane_geometry_diagnostic_v8.py"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f5-s1.clipplane-geometry-diagnostic.v8-request"
WORKER_SCHEMA = "ds02.stage2.f5-s1.clipplane-geometry-diagnostic.v8"
SUPPORT_CONTRACT_SCHEMA = "ds02.stage2.f5-s1.clipplane-geometry-diagnostic-contract.v8"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V7REQ = load_module("stage2_f5_geometry_request_v7_adapter", V7_REQUEST_PATH)


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str, *, scope: str = "small_input_hashed_by_builder_and_parent_v8") -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path), "content_scope": scope}


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable V8 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"refuse to reuse V8 temporary artifact: {temporary}")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def _replace_command_value(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError:
        command.extend([flag, value])
        return
    if index + 1 >= len(command):
        raise ValueError(f"malformed command flag {flag}")
    command[index + 1] = value


def _adapt_contract(temp_path: Path, final_path: Path) -> dict[str, Any]:
    contract = json.loads(temp_path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("V7 adapter wrote a non-object contract")
    contract["schema"] = SUPPORT_CONTRACT_SCHEMA
    contract["status"] = "READY_FOR_PARENT_V8_F5_GEOMETRY_DIAGNOSTIC"
    binding = contract.get("source_binding")
    if isinstance(binding, dict):
        binding["schema"] = WORKER_SCHEMA
    closure = contract.setdefault("parent_v8_input_closure", {})
    closure.update({
        "vtk_sha_authority": "V8 worker first payload full SHA/stat after parent reservation",
        "deferred_input_files_used": False,
        "parent_v8_does_not_hash_worker_owned_vtk": True,
        "worker_first_payload_hash_after_parent_reservation": True,
    })
    hashes = contract.setdefault("worker_owned_input_hashes", {})
    hashes["hash_status"] = "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES"
    scope = contract.setdefault("scope", {})
    scope.update({"vtk_hash": "worker_first_payload_full_sha_after_reservation", "solver_started": False, "bi4_read": False, "hdf5_read": False})
    write_new(final_path, contract)
    return contract


def build(args: argparse.Namespace) -> dict[str, Any]:
    final_contract = Path(args.support_contract).expanduser().resolve() if args.support_contract else Path(args.output).expanduser().resolve().with_name(f"{Path(args.output).stem}.support-contract.v8.json")
    temp_contract = final_contract.with_name(f".{final_contract.name}.{os.getpid()}.v7-adapter.tmp")
    if temp_contract.exists() or temp_contract.is_symlink():
        raise FileExistsError(f"refuse to reuse temporary V8 contract: {temp_contract}")
    adapted_args = argparse.Namespace(**vars(args))
    adapted_args.support_contract = temp_contract
    # V7REQ.build writes the V5-shaped envelope to memory but routes the V5
    # command to this new worker through its V7_PATH global.
    V7REQ.V7_PATH = V8_WORKER_PATH
    V7REQ.V7_WORKER_SCHEMA = WORKER_SCHEMA
    V7REQ.REQUEST_VARIANT_SCHEMA = REQUEST_VARIANT_SCHEMA
    V7REQ.SUPPORT_CONTRACT_SCHEMA = SUPPORT_CONTRACT_SCHEMA
    try:
        payload = V7REQ.build(adapted_args)
        contract = _adapt_contract(temp_contract, final_contract)
    finally:
        temp_contract.unlink(missing_ok=True)
    contract_record = record(final_contract, "F5 V8 support contract")
    command = list(payload["command"])
    # The adapter command already points to V8 after V7REQ.V7_PATH rebinding;
    # verify instead of silently accepting a stale worker path.
    if str(V8_WORKER_PATH.resolve()) not in command:
        raise ValueError("V8 command does not invoke the new geometry worker")
    output_path = "{attempt_root}/report/stage2_f5_s1_clipplane_geometry_diagnostic_v8.json"
    _replace_command_value(command, "--output", output_path)
    _replace_command_value(command, "--support-contract", str(final_contract))
    _replace_command_value(command, "--expected-support-contract-sha", contract_record["sha256"])
    payload["command"] = command
    # Replace the adapter's temporary contract record with the final immutable
    # record, and replace the adapter script record with this builder's bytes.
    records = payload.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("V7 adapter emitted no input_records")
    records.pop(str(temp_contract), None)
    records.pop(str(V7_REQUEST_PATH.resolve()), None)
    records[str(Path(__file__).resolve())] = record(Path(__file__), "F5 V8 geometry request builder")
    records[str(final_contract)] = contract_record
    payload["input_records"] = records
    payload["input_files"] = sorted(records)
    payload["input_hashes"] = {path: records[path]["sha256"] for path in payload["input_files"]}
    payload["request_variant_schema"] = REQUEST_VARIANT_SCHEMA
    payload["worker_schema"] = WORKER_SCHEMA
    payload["status"] = "READY_FOR_PARENT_V8_F5_GEOMETRY_DIAGNOSTIC"
    payload["qualification_stage"] = "stage2_f5_s1_geometry_idp_overlap_diagnostic_v8_pending_parent_guard"
    payload["output"]["path"] = output_path
    payload["support_contract"] = contract_record
    payload["source_binding"]["schema"] = WORKER_SCHEMA
    payload["parent_v8_input_closure"] = contract["parent_v8_input_closure"]
    payload["worker_owned_input_hashes"] = contract["worker_owned_input_hashes"]
    payload["worker_owned_input_stats_at_build"] = contract.get("worker_owned_input_stats_at_build", payload.get("worker_owned_input_stats_at_build", {}))
    payload["estimated_input_read_bytes"] = sum(int(item.get("bytes", 0)) for item in records.values()) + sum(int(item.get("bytes", 0)) for item in payload.get("worker_owned_input_stats_at_build", {}).values() if isinstance(item, dict))
    payload["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "bounded source/selector/Idp/overlap diagnostic only; no solver or physical contact/flux qualification"}
    return payload


def self_test() -> dict[str, Any]:
    worker = json.loads(__import__("subprocess").check_output([sys.executable, str(V8_WORKER_PATH), "--self-test"], text=True))
    if worker.get("status") != "PASS":
        raise AssertionError(worker)
    return {"status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "worker_schema": WORKER_SCHEMA, "support_contract_schema": SUPPORT_CONTRACT_SCHEMA, "vtk_payload_read_by_builder": False, "worker_first_payload_hash_after_parent_reservation": True, "parent_v8_does_not_hash_worker_owned_vtk": True, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--grid", choices=("dp010", "dp005"))
    for name in ("gencase-request", "receipt", "generated-xml", "candidate-def", "source-def", "candidate-motion", "source-motion", "fluid-vtk", "bound-vtk", "clip-evidence", "output", "support-contract"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.grid, args.gencase_request, args.receipt, args.generated_xml, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.fluid_vtk, args.bound_vtk, args.clip_evidence, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires grid, terminal inputs, --clip-evidence, output and launch commit")
    payload = build(args)
    write_new(args.output, payload)
    print(json.dumps({"status": payload["status"], "schema": payload["schema"], "request_variant_schema": payload["request_variant_schema"], "worker_schema": payload["worker_schema"], "grid": args.grid, "support_contract": payload["support_contract"]["path"], "output": str(args.output.resolve()), "vtk_payload_read_by_builder": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
