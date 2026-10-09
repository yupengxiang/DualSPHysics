#!/usr/bin/env python3
"""Prepare and audit one exact CURRENT row as an array-only lifecycle product.

ROOT311 exists for the historical F2 alias at CURRENT index 78.  The row's
trajectory path and producer-declared SHA are checked against CURRENT and the
completed scientific-audit row, but the canonical producer binding is
intentionally unresolved.  The worker may therefore produce saved-frame typed
lifecycle observations after the parent guard, while it cannot add canonical
CURRENT336 coverage or substitute the runtime alias for that row.

Preparation reads bounded JSON and file statistics only.  The deferred HDF5
is hashed and streamed only by ``audit`` after the root-owned reservation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
AUDIT_DEFAULT = STAGE2 / "checkpoints/SCIENTIFIC_AUDIT_VERIFICATION_023.json"
SCAN_DEFAULT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_SCIENCE/scan-F2-S1-001/scientific-scan.json")
RECEIPT_DEFAULT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_SCIENCE/scan-F2-S1-001/execution-receipt.json")
ALIAS_DEFAULT = STAGE2 / "checkpoints/F2_HISTORICAL_ALIAS_RESOLUTION_V1.json"
MISMATCH_DEFAULT = STAGE2 / "checkpoints/CURRENT_ALIAS_MISMATCH_INDEX_ACTUAL_ROOT_VERIFICATION_185.json"
CASE_DEFAULT = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
EXPECTED_CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CURRENT_INDEX = 78
ARRAY_ONLY_MANIFEST_SCHEMA = "ds02.stage2.current-array-only-lifecycle-manifest.v1"
ARRAY_ONLY_REQUEST_SCHEMA = "ds02.request.v1"
ARRAY_ONLY_RECORD_SCHEMA = "ds02.stage2.current-array-only-records.v1"
ARRAY_ONLY_SUMMARY_SCHEMA = "ds02.stage2.current-array-only-summary.v1"
ARRAY_ONLY_STATUS = "READY_PARENT_GUARDED_CURRENT_ARRAY_ONLY"
V4_PATH = SCRIPT.with_name("ds_data02_stage2_typed_lifecycle_sidecar_v4.py")


class CurrentArrayOnlyError(ValueError):
    """Raised for a non-closed CURRENT array-only contract."""


def _load_v4() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_typed_lifecycle_v4_for_root311", V4_PATH)
    if spec is None or spec.loader is None:
        raise CurrentArrayOnlyError(f"cannot load typed lifecycle V4 core: {V4_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V4 = _load_v4()


def sha256_file(path: Path) -> str:
    return V4.sha256_file(path)


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CurrentArrayOnlyError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise CurrentArrayOnlyError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, allow_payload: bool = False) -> Path:
    try:
        return V4._path(value, label, allow_payload=allow_payload)
    except V4.LifecycleError as exc:
        raise CurrentArrayOnlyError(str(exc)) from exc


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        return V4._json(path, label)
    except V4.LifecycleError as exc:
        raise CurrentArrayOnlyError(str(exc)) from exc


def _stat(path: Path, label: str, *, allow_payload: bool = False) -> dict[str, Any]:
    try:
        return V4._stat(path, label, allow_payload=allow_payload)
    except V4.LifecycleError as exc:
        raise CurrentArrayOnlyError(str(exc)) from exc


def _hash_ref(path: Path, label: str) -> dict[str, Any]:
    try:
        return V4._hash_ref(path, label)
    except V4.LifecycleError as exc:
        raise CurrentArrayOnlyError(str(exc)) from exc


def _literal_file(value: Any, label: str) -> tuple[Path, Path, dict[str, Any]]:
    try:
        return V4._literal_file(value, label)
    except V4.LifecycleError as exc:
        raise CurrentArrayOnlyError(str(exc)) from exc


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = V4.MAX_SUMMARY_BYTES) -> None:
    try:
        V4._atomic_json(path, value, max_bytes=max_bytes)
    except V4.LifecycleError as exc:
        raise CurrentArrayOnlyError(str(exc)) from exc


def _atomic_jsonl(path: Path, header: dict[str, Any], rows: Any, *, max_bytes: int = V4.MAX_RECORD_BYTES) -> dict[str, Any]:
    try:
        return V4._atomic_jsonl(path, header, rows, max_bytes=max_bytes)
    except V4.LifecycleError as exc:
        raise CurrentArrayOnlyError(str(exc)) from exc


def _load_source_catalog(
    current_path: Path,
    audit_path: Path,
    scan_path: Path,
    receipt_path: Path,
    alias_path: Path,
    mismatch_path: Path,
    case_id: str,
    expected_current_sha256: str,
) -> dict[str, Any]:
    expected_current_sha256 = _sha(expected_current_sha256, "expected CURRENT SHA")
    current_sha = sha256_file(current_path)
    if current_sha != expected_current_sha256:
        raise CurrentArrayOnlyError(f"CURRENT SHA differs: {current_sha}")
    current = _json(current_path, "CURRENT336")
    if current.get("schema") != "ds02.stage2.current336.v1" or not isinstance(current.get("cases"), list):
        raise CurrentArrayOnlyError("CURRENT schema/cases are not closed")
    indexed = [(index, row) for index, row in enumerate(current["cases"]) if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(indexed) != 1:
        raise CurrentArrayOnlyError(f"CURRENT case is not unique: {case_id}")
    index, current_row = indexed[0]
    if index != CURRENT_INDEX:
        raise CurrentArrayOnlyError(f"CURRENT index differs: expected {CURRENT_INDEX}, got {index}")
    if current_row.get("family_id") != "F2":
        raise CurrentArrayOnlyError("CURRENT array-only pilot must be F2")
    trajectory = current_row.get("trajectory")
    if not isinstance(trajectory, dict):
        raise CurrentArrayOnlyError("CURRENT trajectory metadata missing")
    h5_path = _path(trajectory.get("path"), "CURRENT trajectory", allow_payload=True)
    if h5_path.suffix.lower() not in V4.H5_SUFFIXES:
        raise CurrentArrayOnlyError(f"CURRENT trajectory is not HDF5: {h5_path}")
    declared_h5_sha = _sha(trajectory.get("producer_declared_sha256"), "CURRENT producer-declared trajectory SHA")
    h5_stat = _stat(h5_path, "CURRENT trajectory stat", allow_payload=True)
    if int(trajectory.get("bytes", -1)) != h5_stat["bytes"]:
        raise CurrentArrayOnlyError("CURRENT trajectory byte count differs from stat")

    audit = _json(audit_path, "scientific audit verification")
    if audit.get("schema") != "ds02.stage2.scientific-audit-independent-verification.v23":
        raise CurrentArrayOnlyError("scientific audit schema differs")
    audit_catalog = audit.get("current_catalog")
    if not isinstance(audit_catalog, dict) or audit_catalog.get("sha256") != expected_current_sha256:
        raise CurrentArrayOnlyError("scientific audit is not bound to exact CURRENT SHA")
    audit_rows = [row for row in audit.get("verified_cases", []) if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(audit_rows) != 1:
        raise CurrentArrayOnlyError("scientific audit case is not unique")
    audit_row = audit_rows[0]
    if audit_row.get("exact_CURRENT_path_and_declared_sha_match") is not True:
        raise CurrentArrayOnlyError("scientific audit row is not exact CURRENT-bound")
    if audit_row.get("trajectory") != str(h5_path) or _sha(audit_row.get("trajectory_verified_sha256"), "audit trajectory SHA") != declared_h5_sha:
        raise CurrentArrayOnlyError("audit trajectory identity differs from CURRENT")
    if audit_row.get("scan_status") != "SCANNED" or audit_row.get("field_failures"):
        raise CurrentArrayOnlyError("scientific audit row is not completed/field-clean")

    scan = _json(scan_path, "scientific scan")
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1" or scan.get("scan_status") != "SCANNED":
        raise CurrentArrayOnlyError("scientific scan is not completed")
    if scan.get("physical_case_id") != case_id or scan.get("trajectory") != str(h5_path):
        raise CurrentArrayOnlyError("scientific scan identity differs")
    if int(scan.get("source_bytes", -1)) != h5_stat["bytes"] or int(scan.get("frames", -1)) != int(current_row.get("frames", -2)):
        raise CurrentArrayOnlyError("scientific scan HDF5 metadata differs")
    receipt = _json(receipt_path, "scientific scan receipt")
    if str(receipt.get("status", "")).lower() != "completed" or receipt.get("returncode", 0) not in (0, None):
        raise CurrentArrayOnlyError("scientific scan receipt is not completed")
    if audit_row.get("scan") != str(scan_path) or audit_row.get("receipt") != str(receipt_path):
        raise CurrentArrayOnlyError("scientific audit scan/receipt paths differ")
    if audit_row.get("scan_sha256") != sha256_file(scan_path) or audit_row.get("receipt_sha256") != sha256_file(receipt_path):
        raise CurrentArrayOnlyError("scientific audit scan/receipt SHA differs")

    alias = _json(alias_path, "historical alias resolution")
    alias_meta = alias.get("alias")
    if not isinstance(alias_meta, dict) or alias_meta.get("current_index") != CURRENT_INDEX or alias_meta.get("physical_case_id") != case_id:
        raise CurrentArrayOnlyError("alias sidecar does not bind exact CURRENT index/case")
    if alias_meta.get("scientific_credit") != "NONE" or alias_meta.get("plan_status") != "HISTORICAL_ALIAS_UNRESOLVED":
        raise CurrentArrayOnlyError("alias sidecar is not unresolved/no-credit")
    alias_evidence = alias.get("evidence")
    if not isinstance(alias_evidence, dict) or alias_evidence.get("audit_023_exact_current_path_and_declared_sha_match") is not True:
        raise CurrentArrayOnlyError("alias sidecar lacks exact CURRENT path/SHA evidence")
    if alias_evidence.get("canonical_binding_present") is not False or alias_evidence.get("registry_has_target_producer") is not False:
        raise CurrentArrayOnlyError("alias sidecar unexpectedly claims canonical producer binding")

    mismatch = _json(mismatch_path, "alias mismatch verification")
    if mismatch.get("scientific_credit") != "NONE" or mismatch.get("original_producer_exact_current_binding") is not False:
        raise CurrentArrayOnlyError("alias mismatch proof does not preserve unresolved producer identity")
    return {
        "current": current,
        "current_row": current_row,
        "current_index": index,
        "current_path": str(current_path),
        "current_sha256": current_sha,
        "audit_path": str(audit_path),
        "audit_sha256": sha256_file(audit_path),
        "audit_row": audit_row,
        "scan_path": str(scan_path),
        "scan_sha256": sha256_file(scan_path),
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "alias_path": str(alias_path),
        "alias_sha256": sha256_file(alias_path),
        "alias_evidence": alias_evidence,
        "mismatch_path": str(mismatch_path),
        "mismatch_sha256": sha256_file(mismatch_path),
        "h5_path": h5_path,
        "h5_stat": h5_stat,
        "declared_h5_sha256": declared_h5_sha,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    current_path = _path(args.current, "CURRENT336")
    audit_path = _path(args.audit_verification, "scientific audit verification")
    scan_path = _path(args.scan, "scientific scan")
    receipt_path = _path(args.receipt, "scientific scan receipt")
    alias_path = _path(args.alias_resolution, "historical alias resolution")
    mismatch_path = _path(args.mismatch_verification, "alias mismatch verification")
    source = _load_source_catalog(current_path, audit_path, scan_path, receipt_path, alias_path, mismatch_path, args.case_id, args.expected_current_sha256)

    worker_declared, worker_resolved, worker_ref = _literal_file(args.worker, "worker")
    # The worker delegates the lifecycle stream to the immutable V4 core.  It
    # is a distinct input edge so a root rebind cannot silently substitute a
    # different core implementation under the ROOT311 wrapper.
    v4_core_ref = {**_hash_ref(V4_PATH, "typed_lifecycle_v4_core"), "role": "typed_lifecycle_v4_core"}
    python_declared, python_resolved, python_ref = _literal_file(args.python, "python")
    config_declared, config_resolved, config_ref = _literal_file(args.runtime_config, "runtime_config")
    runtime_files: list[tuple[str, Path, Path, dict[str, Any]]] = []
    for role, value in (("runtime_v2", args.runtime_v2), ("runtime_v6", args.runtime_v6), ("runtime_v8", args.runtime_v8), ("dispatch_v8", args.dispatch_v8), ("strict_v8", args.strict_v8)):
        declared, resolved, ref = _literal_file(value, role)
        runtime_files.append((role, declared, resolved, ref))
    cwd = Path(args.cwd).expanduser().resolve()
    worktree = Path(args.worktree_root).expanduser().resolve()
    if not cwd.is_dir() or not worktree.is_dir():
        raise CurrentArrayOnlyError("cwd/worktree_root closure is invalid")
    try:
        cwd.relative_to(worktree)
    except ValueError as exc:
        raise CurrentArrayOnlyError("cwd/worktree_root closure is invalid") from exc

    small_refs = [
        {**_hash_ref(current_path, "current336"), "role": "current336"},
        {**_hash_ref(audit_path, "scientific_audit"), "role": "scientific_audit"},
        {**_hash_ref(scan_path, "scientific_scan"), "role": "scientific_scan"},
        {**_hash_ref(receipt_path, "scan_receipt"), "role": "scan_receipt"},
        {**_hash_ref(alias_path, "historical_alias_resolution"), "role": "historical_alias_resolution"},
        {**_hash_ref(mismatch_path, "alias_mismatch_verification"), "role": "alias_mismatch_verification"},
        worker_ref, v4_core_ref, python_ref, config_ref,
        *[ref for _role, _declared, _resolved, ref in runtime_files],
    ]
    h5_ref = {
        **source["h5_stat"],
        "role": "trajectory_h5",
        "sha256": source["declared_h5_sha256"],
        "content_read_by_preparer": False,
        "read_after_reservation": True,
        "deferred": True,
    }
    manifest_path = output_dir / "current-array-only-manifest.json"
    summary_path = output_dir / "current-array-only-summary.json"
    records_path = output_dir / "current-array-only-records.jsonl"
    manifest = {
        "schema": ARRAY_ONLY_MANIFEST_SCHEMA,
        "status": ARRAY_ONLY_STATUS,
        "family_id": source["current_row"]["family_id"],
        "physical_case_id": args.case_id,
        "current_index": CURRENT_INDEX,
        "runtime_case_alias": source["current_row"].get("runtime_case_alias"),
        "current_catalog": {"path": source["current_path"], "sha256": source["current_sha256"]},
        "trajectory_h5": h5_ref,
        "source_refs": [*small_refs, h5_ref],
        "frames": int(source["current_row"]["frames"]),
        "particles": int(source["current_row"]["particles"]),
        "producer_identity": {
            "status": "UNKNOWN_CANONICAL_PRODUCER_BINDING",
            "producer_declared_trajectory_sha256": source["declared_h5_sha256"],
            "canonical_registry_membership": False,
            "canonical_binding_fields": None,
            "alias_substitution": "FORBIDDEN",
        },
        "coverage_credit": {
            "current336_case_credit": "NONE",
            "canonical_335_coverage_credit": "NONE",
            "historical_118_credit": "NONE_FROM_ARRAY_ONLY_AUDIT",
            "reason": "Exact CURRENT path/SHA is verified, but canonical producer identity is unresolved.",
        },
        "alias_evidence": {
            "path": source["alias_path"], "sha256": source["alias_sha256"],
            "exact_current_path_and_declared_sha_match": True,
            "canonical_binding_present": False,
            "scientific_credit": "NONE",
        },
        "mismatch_evidence": {"path": source["mismatch_path"], "sha256": source["mismatch_sha256"], "exact_current_binding": False},
        "outputs": {"summary": str(summary_path), "records": str(records_path), "summary_max_bytes": V4.MAX_SUMMARY_BYTES, "records_max_bytes": V4.MAX_RECORD_BYTES},
        "read_policy": {
            "prepare_json_and_stat_only": True,
            "trajectory_h5_opened_by_preparer": False,
            "trajectory_h5_hashed_by_preparer": False,
            "worker_after_reservation_pre_hash_stream_post_hash": True,
            "canonical_producer_readback": "NOT_ATTEMPTED",
            "raw_bi4_opened": False,
            "solver_started": False,
        },
        "semantic_contract": {
            "identity_key": "(Zone, Idp)",
            "saved_mask_lifecycle_only": True,
            "continuous_event_time": "UNKNOWN",
            "native_exit_cause": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "runtime_contract": {
            "interpreter": {"literal_path": str(python_declared), "resolved_path": str(python_resolved), "sha256": python_ref["sha256"]},
            "config": {"literal_path": str(config_declared), "resolved_path": str(config_resolved), "sha256": config_ref["sha256"]},
        },
    }
    _atomic_json(manifest_path, manifest)
    manifest_ref = {**_hash_ref(manifest_path, "manifest_contract"), "role": "manifest_contract"}
    input_refs = {ref["path"]: ref["sha256"] for ref in [*small_refs, manifest_ref]}
    runtime_binding = {
        role: {"literal_path": str(declared), "resolved_path": str(resolved), "sha256": ref["sha256"]}
        for role, declared, resolved, ref in runtime_files
    }
    runtime_binding["runtime_config"] = {"literal_path": str(config_declared), "resolved_path": str(config_resolved), "sha256": config_ref["sha256"]}
    request_path = Path(args.request_output).expanduser().resolve() if getattr(args, "request_output", None) else output_dir / "current-array-only-request.json"
    command = [str(python_declared), str(worker_declared), "audit", "--manifest", str(manifest_path), "--summary", "{attempt_root}/current-array-only-summary.json", "--records", "{attempt_root}/current-array-only-records.jsonl", "--chunk", "65536"]
    request = {
        "schema": ARRAY_ONLY_REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": source["current_row"]["family_id"],
        "case_id": "ROOT311_CURRENT_ARRAY_ONLY_INDEX078",
        "physical_case_id": args.case_id,
        "current_index": CURRENT_INDEX,
        "runtime_case_alias": source["current_row"].get("runtime_case_alias"),
        "attempt_id": "current-array-only-root311-001-root-forward",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 1800, "max_memory_bytes": 2 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": V4.MAX_RECORD_BYTES + V4.MAX_SUMMARY_BYTES,
        "estimated_hdf5_read_bytes": int(source["h5_stat"]["bytes"] * 3),
        "estimated_deferred_read_passes": 3, "estimated_deferred_read_bytes": int(source["h5_stat"]["bytes"] * 3),
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in [*small_refs, manifest_ref]),
        "estimated_deferred_source_bytes": int(source["h5_stat"]["bytes"]),
        "cwd": str(cwd), "worktree_root": str(worktree), "command": command,
        "input_files": sorted(input_refs), "input_sha256": dict(sorted(input_refs.items())),
        "deferred_input_files": [str(source["h5_path"])], "deferred_input_records": [h5_ref],
        "output_files": ["{attempt_root}/current-array-only-summary.json", "{attempt_root}/current-array-only-records.jsonl"],
        "runtime_binding": runtime_binding,
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]},
        "interpreter_binding": {"literal_path": str(python_declared), "resolved_executable_path": str(python_resolved), "sha256": python_ref["sha256"]},
        "producer_identity": manifest["producer_identity"],
        "coverage_credit": manifest["coverage_credit"],
        "guarded_payload_binding": {"trajectory_h5": "deferred_after_reservation_pre_hash_stream_post_hash", "raw_bi4_content_read": False, "solver_started": False},
        "claim_boundary": manifest["semantic_contract"],
        "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "shared_lease_required": True,
        "request_note": "Exact CURRENT index 78 array-only diagnostic. Canonical producer identity is unresolved; alias substitution and CURRENT336/canonical coverage credit are forbidden.",
    }
    _atomic_json(request_path, request)
    return {"status": ARRAY_ONLY_STATUS, "manifest": str(manifest_path), "request": str(request_path), "manifest_sha256": sha256_file(manifest_path), "request_sha256": sha256_file(request_path), "physical_case_id": args.case_id, "current_index": CURRENT_INDEX, "trajectory_bytes": source["h5_stat"]["bytes"], "trajectory_sha256_declared": source["declared_h5_sha256"], "h5_content_opened_by_preparer": False, "canonical_coverage_credit": "NONE", "producer_identity": "UNKNOWN_CANONICAL_PRODUCER_BINDING"}


def _validate_manifest(manifest_path: Path) -> tuple[dict[str, Any], Path, str, int, dict[str, Any], dict[str, Any]]:
    manifest = _json(manifest_path, "current array-only manifest")
    if manifest.get("schema") != ARRAY_ONLY_MANIFEST_SCHEMA or manifest.get("status") != ARRAY_ONLY_STATUS:
        raise CurrentArrayOnlyError("manifest is not ROOT311 current-array-only ready")
    if manifest.get("current_index") != CURRENT_INDEX or manifest.get("coverage_credit", {}).get("canonical_335_coverage_credit") != "NONE":
        raise CurrentArrayOnlyError("manifest does not preserve ROOT311 no-credit boundary")
    producer = manifest.get("producer_identity")
    if not isinstance(producer, dict) or producer.get("status") != "UNKNOWN_CANONICAL_PRODUCER_BINDING" or producer.get("canonical_registry_membership") is not False:
        raise CurrentArrayOnlyError("manifest unexpectedly claims canonical producer identity")
    alias_evidence = manifest.get("alias_evidence")
    if not isinstance(alias_evidence, dict) or alias_evidence.get("exact_current_path_and_declared_sha_match") is not True or alias_evidence.get("canonical_binding_present") is not False or alias_evidence.get("scientific_credit") != "NONE":
        raise CurrentArrayOnlyError("manifest alias evidence does not preserve unresolved/no-credit status")
    mismatch_evidence = manifest.get("mismatch_evidence")
    if not isinstance(mismatch_evidence, dict) or mismatch_evidence.get("exact_current_binding") is not False:
        raise CurrentArrayOnlyError("manifest mismatch evidence does not preserve unresolved producer identity")
    refs = manifest.get("source_refs")
    if not isinstance(refs, list):
        raise CurrentArrayOnlyError("manifest source_refs missing")
    by_role: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("role"), str):
            raise CurrentArrayOnlyError("malformed source reference")
        role = ref["role"]
        if role in by_role:
            raise CurrentArrayOnlyError(f"duplicate source role: {role}")
        by_role[role] = ref
        if role != "trajectory_h5":
            path = _path(ref.get("path"), role)
            expected = _sha(ref.get("sha256"), f"{role} SHA")
            if sha256_file(path) != expected:
                raise CurrentArrayOnlyError(f"source changed: {role}")
    # The manifest contract is the file being validated and therefore cannot
    # be a self-referential source_ref.  The request binds its path/SHA after
    # this manifest is written; all independent source roles are checked here.
    required = {"current336", "scientific_audit", "scientific_scan", "scan_receipt", "historical_alias_resolution", "alias_mismatch_verification", "worker", "typed_lifecycle_v4_core", "python", "runtime_config", "runtime_v2", "runtime_v6", "runtime_v8", "dispatch_v8", "strict_v8", "trajectory_h5"}
    if not required.issubset(by_role):
        raise CurrentArrayOnlyError(f"manifest lacks roles: {sorted(required - set(by_role))}")
    current_path = _path(by_role["current336"]["path"], "CURRENT336")
    current_sha = _sha(by_role["current336"].get("sha256"), "manifest CURRENT SHA")
    if sha256_file(current_path) != current_sha:
        raise CurrentArrayOnlyError("manifest CURRENT SHA does not match the current catalog bytes")
    current = _json(current_path, "CURRENT336")
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) <= CURRENT_INDEX:
        raise CurrentArrayOnlyError("CURRENT index 78 is unavailable")
    row = cases[CURRENT_INDEX]
    if not isinstance(row, dict) or row.get("physical_case_id") != manifest.get("physical_case_id"):
        raise CurrentArrayOnlyError("manifest is not bound to CURRENT index 78")
    if row.get("family_id") != manifest.get("family_id") or row.get("family_id") != "F2":
        raise CurrentArrayOnlyError("manifest family is not the exact F2 CURRENT row family")
    if row.get("runtime_case_alias") != manifest.get("runtime_case_alias"):
        raise CurrentArrayOnlyError("manifest runtime alias differs from CURRENT index 78")
    if sum(isinstance(item, dict) and item.get("physical_case_id") == manifest.get("physical_case_id") for item in cases) != 1:
        raise CurrentArrayOnlyError("CURRENT physical case is not unique")
    h5_ref = by_role["trajectory_h5"]
    h5_path = _path(h5_ref.get("path"), "trajectory_h5", allow_payload=True)
    expected_h5 = _sha(h5_ref.get("sha256"), "trajectory HDF5 declared SHA")
    if row.get("trajectory", {}).get("path") != str(h5_path) or row.get("trajectory", {}).get("producer_declared_sha256") != expected_h5:
        raise CurrentArrayOnlyError("CURRENT trajectory does not match deferred HDF5 reference")
    h5_stat = _stat(h5_path, "trajectory HDF5", allow_payload=True)
    if int(h5_ref.get("bytes", -1)) != h5_stat["bytes"]:
        raise CurrentArrayOnlyError("trajectory HDF5 stat changed before worker")
    if manifest.get("frames") != row.get("frames") or manifest.get("particles") != row.get("particles"):
        raise CurrentArrayOnlyError("CURRENT dimensions differ")
    return manifest, h5_path, expected_h5, int(row["frames"]), by_role, row


def audit(manifest_path: Path, summary_path: Path, records_path: Path, *, chunk: int = 65536) -> dict[str, Any]:
    started = time.monotonic()
    manifest, h5_path, expected_h5, expected_frames, refs, row = _validate_manifest(Path(manifest_path).expanduser().resolve())
    pre_stat = _stat(h5_path, "trajectory HDF5 pre-read", allow_payload=True)
    pre_sha = sha256_file(h5_path)
    if pre_sha != expected_h5:
        raise CurrentArrayOnlyError("trajectory HDF5 pre-read SHA differs from CURRENT declared SHA")
    lifecycle_meta, records = V4._lifecycle_records(h5_path, expected_frames, chunk)
    post_stat = _stat(h5_path, "trajectory HDF5 post-read", allow_payload=True)
    post_sha = sha256_file(h5_path)
    if pre_stat != post_stat or pre_sha != post_sha:
        raise CurrentArrayOnlyError("trajectory HDF5 changed during array-only stream")
    record_header = {
        "schema": ARRAY_ONLY_RECORD_SCHEMA,
        "status": "COMPLETED_CURRENT_ARRAY_ONLY_RECORDS_NO_CANONICAL_CREDIT",
        "family_id": manifest.get("family_id"),
        "physical_case_id": manifest.get("physical_case_id"),
        "current_index": CURRENT_INDEX,
        "runtime_case_alias": manifest.get("runtime_case_alias"),
        "source_trajectory": str(h5_path),
        "source_trajectory_sha256": pre_sha,
        "record_fields": "one row per static (Zone, Idp); saved-frame lifecycle only",
        "producer_identity": "UNKNOWN_CANONICAL_PRODUCER_BINDING",
        "coverage_credit": "NONE",
    }
    records_ref = _atomic_jsonl(records_path, record_header, records)
    summary = {
        "schema": ARRAY_ONLY_SUMMARY_SCHEMA,
        "status": "COMPLETED_CURRENT_ARRAY_ONLY_NO_CANONICAL_CREDIT",
        "family_id": manifest.get("family_id"),
        "physical_case_id": manifest.get("physical_case_id"),
        "current_index": CURRENT_INDEX,
        "runtime_case_alias": manifest.get("runtime_case_alias"),
        "producer_identity": {
            "status": "UNKNOWN_CANONICAL_PRODUCER_BINDING",
            "declared_trajectory_sha256": expected_h5,
            "canonical_registry_membership": False,
            "canonical_binding_fields": None,
        },
        "coverage_credit": {
            "current336_case_credit": "NONE",
            "canonical_335_coverage_credit": "NONE",
            "historical_118_credit": "NONE_FROM_ARRAY_ONLY_AUDIT",
            "alias_substitution": "FORBIDDEN",
        },
        "source": {
            "current336_path": refs["current336"]["path"],
            "current336_sha256": refs["current336"]["sha256"],
            "trajectory_h5": {"path": str(h5_path), "declared_sha256": expected_h5, "pre_sha256": pre_sha, "post_sha256": post_sha, "pre_stat": pre_stat, "post_stat": post_stat},
            "current_index": CURRENT_INDEX,
            "alias_resolution_path": refs["historical_alias_resolution"]["path"],
            "alias_resolution_sha256": refs["historical_alias_resolution"]["sha256"],
            "alias_exact_current_path_and_declared_sha_match": True,
            "alias_canonical_binding": "ABSENT",
        },
        "timeline": {"frames": lifecycle_meta["frame_count"], "particles": lifecycle_meta["particle_count"], "time_s": lifecycle_meta["time_s"]},
        "metadata": lifecycle_meta["metadata"],
        "role_ledgers": lifecycle_meta["role_ledgers"],
        "records": records_ref,
        "lifecycle_semantics": {
            "saved_frame_mask_observation": True,
            "continuous_event_time": "UNKNOWN",
            "native_exit_cause": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"h5_opened_by_worker_after_reservation": True, "h5_content_opened_by_preparer": False, "raw_bi4_opened": False, "solver_started": False},
        "source_read_cost": {"h5_pre_hash_bytes": pre_stat["bytes"], "h5_stream_lower_bound_bytes": pre_stat["bytes"], "h5_post_hash_bytes": post_stat["bytes"], "h5_minimum_passes": 3, "records_output_bytes": records_ref["bytes"], "wall_seconds": time.monotonic() - started},
        "scope_limits": ["This is an exact CURRENT index-78 array observation only.", "The producer-declared trajectory SHA is verified, but canonical producer identity remains unresolved.", "It does not revise CURRENT336/335 coverage, historical 118 causes, or alias membership.", "Physical fate, legal flux, continuous event time, dynamics, and QI/QN/QE remain UNKNOWN."],
    }
    _atomic_json(summary_path, summary)
    return {"status": summary["status"], "summary": str(Path(summary_path).resolve()), "records": str(Path(records_path).resolve()), "record_count": len(records), "h5_pre_post_sha256_equal": True, "canonical_coverage_credit": "NONE", "producer_identity": "UNKNOWN_CANONICAL_PRODUCER_BINDING"}


def self_test() -> dict[str, Any]:
    return {"status": "PASS", "schema": ARRAY_ONLY_SUMMARY_SCHEMA, "current_index": CURRENT_INDEX, "canonical_coverage_credit": "NONE", "producer_identity": "UNKNOWN_CANONICAL_PRODUCER_BINDING", "payload_opened": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--audit-verification", type=Path, default=AUDIT_DEFAULT)
    prep.add_argument("--scan", type=Path, default=SCAN_DEFAULT)
    prep.add_argument("--receipt", type=Path, default=RECEIPT_DEFAULT)
    prep.add_argument("--alias-resolution", type=Path, default=ALIAS_DEFAULT)
    prep.add_argument("--mismatch-verification", type=Path, default=MISMATCH_DEFAULT)
    prep.add_argument("--case-id", default=CASE_DEFAULT)
    prep.add_argument("--expected-current-sha256", default=EXPECTED_CURRENT_SHA256)
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--request-output", type=Path)
    prep.add_argument("--worker", type=Path, default=SCRIPT)
    prep.add_argument("--python", type=Path, default=V4.VENV)
    prep.add_argument("--runtime-config", type=Path, required=True)
    for option in ("runtime-v2", "runtime-v6", "runtime-v8", "dispatch-v8", "strict-v8", "cwd", "worktree-root"):
        prep.add_argument(f"--{option}", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--summary", type=Path, required=True)
    run.add_argument("--records", type=Path, required=True)
    run.add_argument("--chunk", type=int, default=65536)
    args = parser.parse_args(argv)
    try:
        if args.action == "self-test":
            result = self_test()
        elif args.action == "prepare":
            result = prepare(args)
        else:
            result = audit(args.manifest, args.summary, args.records, chunk=args.chunk)
    except (CurrentArrayOnlyError, V4.LifecycleError, OSError, ValueError) as exc:
        print(f"CURRENT_ARRAY_ONLY_ROOT311_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
