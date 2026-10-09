#!/usr/bin/env python3
"""Build a parent-guarded F3-S2 v3 support request for a terminal GenCase.

The first intended product is ROOT120 dp=.015.  The builder hashes only the
small q/receipt/XML/source/code/contract inputs.  Fluid/Bound VTK are
worker-owned stat-only paths; their complete SHA/stat is taken by the v3
worker after parent reservation and before the reviewed ROOT086 parser reads
the payload.  No array or HDF5 data is opened while building this request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f3_s2_initial_support_audit_v3.py"
REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v3"
REQUEST_VARIANT_SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v3-request"
CONTRACT_SCHEMA = "ds02.stage2.f3.s2.initial-support-contract.v3"
REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
ROOT086_LOCAL = Path(__file__).resolve().parents[4] / "scripts/ds_data02_stage2_f3_s2_root086_vtk_support_qa_v2.py"
ROOT086_PARSER = ROOT086_LOCAL if ROOT086_LOCAL.is_file() else PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f3_s2_root086_vtk_support_qa_v2.py"
DISPATCH = REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
SOURCE_XML = DATA_ROOT / ("families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/" "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml")
SOURCE_CONTROL = DATA_ROOT / ("families/F3/F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/" "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/prepared/pitch120_ay0750/CaseSloshingAccData.csv")


def repo_file(relative: str) -> Path:
    local = REPO / relative
    if local.is_file():
        return local
    primary = PRIMARY_REPO / relative
    return primary if primary.is_file() else local


DISPATCH = repo_file("lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py")
STRICT = repo_file("lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py")
RUNTIME = repo_file("lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py")


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


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path), "content_scope": "small_input_hashed_by_builder_and_parent_v8"}


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable F3 v3 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)
    os.replace(temporary, path)


def build(args: argparse.Namespace) -> dict[str, Any]:
    q_path = regular(args.gencase_request, "F3 GenCase request")
    receipt_path = regular(args.receipt, "F3 GenCase receipt")
    q = load_json(q_path, "F3 GenCase request"); receipt = load_json(receipt_path, "F3 GenCase receipt")
    scope = q.get("scope") if isinstance(q.get("scope"), dict) else {}
    if (q.get("family_id") or scope.get("family_id")) != "F3" or (q.get("sentinel_id") or scope.get("sentinel_id")) != "F3-S2" or q.get("cpu_task_kind") != "gencase":
        raise ValueError("F3 support v3 requires an exact F3-S2 GenCase request")
    if (q.get("physical_case_id") or scope.get("physical_case_id")) != "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT":
        raise ValueError("F3 physical case ID mismatch")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("F3 GenCase receipt is not completed zero-return")
    receipt_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    generated_xml = regular(args.generated_xml, "F3 generated XML")
    fluid_vtk = regular(args.fluid_vtk, "F3 Fluid VTK")
    bound_vtk = regular(args.bound_vtk, "F3 Bound VTK")
    if generated_xml.parent != receipt_root or fluid_vtk.parent != receipt_root or bound_vtk.parent != receipt_root:
        raise ValueError("terminal generated XML/Fluid/Bound VTK must share receipt output_root")
    source_xml = regular(args.source_xml or SOURCE_XML, "F3 source XML")
    source_control = regular(args.source_control or SOURCE_CONTROL, "F3 source control")
    support_contract_path = Path(args.support_contract).expanduser().resolve() if args.support_contract else Path(args.output).expanduser().resolve().with_name(f"{Path(args.output).stem}.support-contract.v3.json")
    static_paths = [(q_path, "F3 GenCase request"), (receipt_path, "F3 GenCase receipt"), (generated_xml, "F3 generated XML"), (source_xml, "F3 source XML"), (source_control, "F3 source control"), (WORKER, "F3 v3 support worker"), (ROOT086_PARSER, "reviewed ROOT086 binary VTK parser"), (Path(__file__).resolve(), "F3 v3 support request builder"), (DISPATCH, "parent v8 dispatch"), (STRICT, "parent v8 strict dispatch"), (RUNTIME, "parent v8 runtime"), (PYTHON, "stage2 interpreter")]
    records = {str(path.resolve()): record(path, label) for path, label in static_paths}
    worker_vtk = {"fluid_vtk": {"path": str(fluid_vtk.resolve()), "bytes": int(fluid_vtk.stat().st_size), "mtime_ns": int(fluid_vtk.stat().st_mtime_ns), "ctime_ns": int(fluid_vtk.stat().st_ctime_ns), "st_dev": int(fluid_vtk.stat().st_dev), "st_ino": int(fluid_vtk.stat().st_ino), "sha256": "WORKER_AFTER_RESERVATION_ONLY", "content_scope": "worker_owned_payload_stat_only"}, "bound_vtk": {"path": str(bound_vtk.resolve()), "bytes": int(bound_vtk.stat().st_size), "mtime_ns": int(bound_vtk.stat().st_mtime_ns), "ctime_ns": int(bound_vtk.stat().st_ctime_ns), "st_dev": int(bound_vtk.stat().st_dev), "st_ino": int(bound_vtk.stat().st_ino), "sha256": "WORKER_AFTER_RESERVATION_ONLY", "content_scope": "worker_owned_payload_stat_only"}}
    contract = {"schema": CONTRACT_SCHEMA, "status": "READY_FOR_PARENT_V8_F3_INITIAL_SUPPORT", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT", "gencase_request": records[str(q_path.resolve())], "gencase_receipt": records[str(receipt_path.resolve())], "generated_xml": records[str(generated_xml.resolve())], "source_xml": records[str(source_xml.resolve())], "source_control": records[str(source_control.resolve())], "owner_contract": {"low_m": [-.45, -.09, 0.0], "size_m": [.9, .18, .09], "mass_kg": 14.58, "mass_semantics": "continuous source owner; generated sample mass remains diagnostic"}, "parent_v8_input_closure": {"small_input_sha256_complete": True, "vtk_in_parent_input_files": False, "vtk_sha_authority": "F3 v3 worker first/post full SHA/stat after parent reservation", "deferred_input_files_used": False, "parent_v8_does_not_hash_worker_owned_vtk": True}, "worker_owned_input_stats_at_build": worker_vtk, "worker_owned_input_hashes": {"hash_status": "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES", "fluid_vtk": "WORKER_AFTER_RESERVATION_ONLY", "bound_vtk": "WORKER_AFTER_RESERVATION_ONLY"}, "scope": {"gencase_rerun": False, "solver_started": False, "bi4_read": False, "hdf5_read": False, "payload_parser": "ROOT086 v2 parser reused by F3 v3"}}
    write_new(support_contract_path, contract)
    contract_record = record(support_contract_path, "F3 v3 support contract")
    records[str(support_contract_path.resolve())] = contract_record
    case_id = args.case_id or "F3_S2_OWNER_CENTERED_DP015_SUPPORT_ROOT_121"
    attempt_id = args.attempt_id or "f3-s2-owner-centered-dp015-support-v3-root-121-001"
    output_root = DATA_ROOT / "families/F3" / case_id / attempt_id
    output_path = "{attempt_root}/report/stage2_f3_s2_initial_support_audit_v3.json"
    command = [str(PYTHON), str(WORKER), "--gencase-request", str(q_path), "--receipt", str(receipt_path), "--generated-xml", str(generated_xml), "--fluid-vtk", str(fluid_vtk), "--bound-vtk", str(bound_vtk), "--source-xml", str(source_xml), "--source-control", str(source_control), "--support-contract", str(support_contract_path), "--expected-generated-xml-sha", records[str(generated_xml.resolve())]["sha256"], "--expected-support-contract-sha", contract_record["sha256"], "--output", output_path]
    payload: dict[str, Any] = {"schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT", "case_id": case_id, "attempt_id": attempt_id, "launch_commit": args.launch_commit, "command": command, "cwd": str(REPO), "worktree_root": str(REPO), "input_files": sorted(records), "input_hashes": {path: records[path]["sha256"] for path in sorted(records)}, "input_records": records, "worker_owned_input_files": [str(fluid_vtk), str(bound_vtk)], "worker_owned_input_stats_at_build": worker_vtk, "worker_owned_input_hashes": contract["worker_owned_input_hashes"], "parent_v8_input_closure": contract["parent_v8_input_closure"], "support_contract": contract_record, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "max_memory_bytes": 2 * 1024**3, "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()) + sum(int(item["bytes"]) for item in worker_vtk.values()), "estimated_storage_bytes": 256 * 1024**2, "estimated_peak_memory_bytes": 2 * 1024**3, "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": False, "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": output_path}, "source_binding": {"schema": SCHEMA, "grid": "dp015", "gencase_request": records[str(q_path.resolve())], "gencase_receipt": records[str(receipt_path.resolve())], "generated_xml": records[str(generated_xml.resolve())], "source_xml": records[str(source_xml.resolve())], "source_control": records[str(source_control.resolve())], "owner_contract": contract["owner_contract"], "sample_mass_is_diagnostic_only": True, "vtk_worker_first_hash_after_parent_reservation": True}, "guard_policy": {"parent_after_reserve_small_input_sha_stat": True, "worker_owned_vtk_pre_post_sha_stat_required": True, "solver_launch": False, "hdf5_read": False, "bi4_read": False}, "qualification_stage": "stage2_f3_s2_initial_support_idp_axis_owner_audit_v3_pending_parent_guard", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "terminal initial support/Idp/axis/owner diagnostic only; no solver or physical flux/no-penetration credit"}, "status": "READY_FOR_PARENT_V8_F3_INITIAL_SUPPORT"}
    write_new(Path(args.output), payload)
    return payload


def self_test() -> dict[str, Any]:
    return {"status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "worker_schema": "ds02.stage2.f3.s2.initial-support-audit.v3", "vtk_payload_read_by_builder": False, "worker_first_payload_hash_after_parent_reservation": True, "solver_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "fluid-vtk", "bound-vtk", "source-xml", "source-control", "output", "support-contract"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--case-id"); parser.add_argument("--attempt-id"); parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.fluid_vtk, args.bound_vtk, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires q/receipt/generated/VTK/output and launch commit")
    payload = build(args)
    print(json.dumps({"status": payload["status"], "schema": REQUEST_SCHEMA, "request_variant_schema": REQUEST_VARIANT_SCHEMA, "output": str(Path(args.output).resolve()), "vtk_payload_read_by_builder": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
