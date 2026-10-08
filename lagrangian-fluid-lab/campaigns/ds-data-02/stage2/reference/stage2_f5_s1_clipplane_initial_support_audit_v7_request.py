#!/usr/bin/env python3
"""Build a V7 F5 support request from a completed GenCase request.

The original GenCase request and its terminal receipt are separate from the
support-audit envelope.  This builder hashes those small files, creates a
separate immutable support-contract sidecar, and leaves Fluid/Bound VTK bytes
for the V7 worker after parent reservation.  ``--clip-evidence`` is explicit
so the request never falls back to a missing or stale reference-worktree
path.
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
V5_PATH = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v5_request.py"
V7_PATH = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v7.py"
REQUEST_SCHEMA = "ds02.request.v1"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-audit.v7-request"
V7_WORKER_SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-audit.v7"
SUPPORT_CONTRACT_SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-contract.v7"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_DISCRETE_SAMPLE_MASS_KG = 254.4779834119572


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V5 = load_module("stage2_f5_support_request_v5_for_v7", V5_PATH)
V7 = load_module("stage2_f5_support_worker_v7_for_request", V7_PATH)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str, *, scope: str = "small_input_hashed_by_builder_and_parent_v8") -> dict[str, Any]:
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
        "content_scope": scope,
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable V7 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"refuse to reuse V7 temporary artifact: {temporary}")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def rebind_builder_record(payload: dict[str, Any]) -> None:
    records = payload.get("input_records")
    if not isinstance(records, dict):
        raise ValueError("V5 builder emitted no input_records")
    records.pop(str(V5_PATH.resolve()), None)
    builder = record(Path(__file__), "F5 V7 support request builder")
    records[builder["path"]] = builder
    payload["input_records"] = records


def append_expected(command: list[str], flag: str, value: str) -> None:
    if flag in command:
        index = command.index(flag)
        if index + 1 >= len(command):
            raise ValueError(f"malformed command flag: {flag}")
        command[index + 1] = value
    else:
        command.extend([flag, value])


def build(args: argparse.Namespace) -> dict[str, Any]:
    q_path = regular(args.gencase_request, "F5 GenCase request")
    receipt_path = regular(args.receipt, "F5 GenCase receipt")
    clip_evidence = regular(args.clip_evidence, "F5 official clip evidence")
    q = load_json(q_path, "F5 GenCase request")
    receipt = load_json(receipt_path, "F5 GenCase receipt")
    identity = V7.validate_gencase_request(q, receipt)
    if args.grid != identity["grid"]:
        raise ValueError("--grid does not match the original GenCase request")

    build_args = argparse.Namespace(**vars(args))
    if not build_args.case_id:
        build_args.case_id = f"F5_S1_CLIPPLANE_INITIAL_SUPPORT_AUDIT_V7_{args.grid.upper()}"
    if not build_args.attempt_id:
        build_args.attempt_id = f"f5-s1-clipplane-initial-support-audit-v7-{args.grid}-root-review-001"
    # The consumed V5 builder writes an artifact during build().  Isolate that
    # write, then adapt its in-memory payload and emit only V7 artifacts.
    target = Path(args.output).expanduser().resolve()
    base_tmp = target.with_name(f".{target.name}.{os.getpid()}.v5-base.tmp")
    if base_tmp.exists() or base_tmp.is_symlink():
        raise FileExistsError(f"refuse to reuse V5 adapter temporary path: {base_tmp}")
    V5.WORKER = V7_PATH
    V5.CLIP_EVIDENCE = clip_evidence
    V5.SCHEMA = V7_WORKER_SCHEMA
    build_args.output = base_tmp
    try:
        payload = V5.build(build_args)
    finally:
        base_tmp.unlink(missing_ok=True)
    if payload.get("schema") != REQUEST_SCHEMA:
        raise ValueError("support envelope must retain ds02.request.v1")
    rebind_builder_record(payload)

    q_record = payload["input_records"][str(q_path)]
    receipt_record = payload["input_records"][str(receipt_path)]
    generated_record = payload["input_records"][str(args.generated_xml.expanduser().resolve())]
    clip_record = payload["input_records"][str(clip_evidence)]
    binding = q["source_binding"]
    source_binding = {
        "schema": V7_WORKER_SCHEMA,
        "grid": identity["grid"],
        "dp_m": identity["expected_dp_m"],
        "pointref_m": identity["expected_pointref_m"],
        "continuous_region_mass_kg": CONTINUOUS_MASS_KG,
        "old_sample_mass_kg": OLD_DISCRETE_SAMPLE_MASS_KG,
        "old_sample_mass_is_diagnostic_only": True,
        "continuous_box_and_clip_unchanged": True,
        "controls_and_motion_unchanged": True,
        "mass_rescale": False,
        "official_clip_evidence": clip_record,
        "gencase_request": q_record,
        "gencase_receipt": receipt_record,
        "planned_output_root": identity["planned_output_root"],
        "actual_receipt_output_root": identity["actual_receipt_output_root"],
        "planned_root_matches_receipt": identity["planned_root_matches_receipt"],
    }
    closure = {
        "small_input_sha256_complete": True,
        "vtk_in_parent_input_files": False,
        "vtk_sha_authority": "V7 worker pre/post full SHA after parent reservation",
        "deferred_input_files_used": False,
        "parent_v8_does_not_hash_worker_owned_vtk": True,
    }
    worker_hashes = dict(payload["worker_owned_input_hashes"])
    worker_hashes["hash_status"] = "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES"
    worker_vtk = payload["worker_owned_input_stats_at_build"]
    contract = {
        "schema": SUPPORT_CONTRACT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_V7_SUPPORT_AUDIT",
        "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "grid": identity["grid"],
        "gencase_request": q_record,
        "gencase_receipt": receipt_record,
        "generated_xml": generated_record,
        "official_clip_evidence": clip_record,
        "source_binding": source_binding,
        "parent_v8_input_closure": closure,
        "worker_owned_input_stats_at_build": worker_vtk,
        "worker_owned_input_hashes": worker_hashes,
        "scope": {"solver_started": False, "bi4_read": False, "hdf5_read": False, "vtk_hash": "worker_after_reservation_only"},
    }
    contract_path = Path(args.support_contract).expanduser().resolve() if args.support_contract else target.with_name(f"{target.stem}.support-contract.v7.json")
    write_new(contract_path, contract)
    contract_record = record(contract_path, "F5 V7 support contract")

    command = list(payload["command"])
    output_path = "{attempt_root}/report/stage2_f5_s1_clipplane_initial_support_audit_v7.json"
    append_expected(command, "--output", output_path)
    append_expected(command, "--support-contract", str(contract_path))
    append_expected(command, "--expected-support-contract-sha", contract_record["sha256"])
    append_expected(command, "--expected-gencase-request-sha", q_record["sha256"])
    append_expected(command, "--expected-receipt-sha", receipt_record["sha256"])
    append_expected(command, "--expected-generated-xml-sha", generated_record["sha256"])
    append_expected(command, "--expected-clip-evidence-sha", clip_record["sha256"])
    for key in ("candidate_def", "source_def", "candidate_motion", "source_motion"):
        path = str(Path(args.__dict__[key]).expanduser().resolve())
        append_expected(command, f"--expected-{key.replace('_', '-')}-sha", payload["input_records"][path]["sha256"])
    payload["command"] = command
    payload["output"]["path"] = output_path
    payload["source_binding"] = source_binding
    payload["parent_v8_input_closure"] = closure
    payload["worker_owned_input_hashes"] = worker_hashes
    payload["worker_owned_input_stats_at_build"] = worker_vtk
    payload["support_contract"] = contract_record
    payload["worker_schema"] = V7_WORKER_SCHEMA
    payload["request_variant_schema"] = REQUEST_VARIANT_SCHEMA
    payload["qualification_stage"] = "stage2_f5_s1_initial_support_mass_control_audit_v7_pending_parent_guard"
    payload["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "GenCase terminal binding and support/mass/control audit only; no solver qualification"}
    payload["status"] = "READY_FOR_PARENT_V8_V7_SUPPORT_AUDIT"
    records = payload["input_records"]
    records[contract_record["path"]] = contract_record
    payload["input_records"] = records
    payload["input_files"] = sorted(records)
    payload["input_hashes"] = {path: records[path]["sha256"] for path in payload["input_files"]}
    payload["estimated_input_read_bytes"] = sum(int(item["bytes"]) for item in records.values()) + sum(int(item["bytes"]) for item in worker_vtk.values())
    return payload


def self_test() -> dict[str, Any]:
    base = V5.self_test()
    worker = V7.self_test()
    assert base["status"] == "PASS" and worker["status"] == "PASS"
    return {
        "status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA,
        "worker_schema": V7_WORKER_SCHEMA, "clip_evidence_cli_required": True,
        "support_contract_sidecar": True, "vtk_payload_read_by_builder": False,
        "worker_vtk_sha_after_reservation": True, "solver_started": False,
    }


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
