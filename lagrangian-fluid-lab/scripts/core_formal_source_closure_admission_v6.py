#!/usr/bin/env python3
"""Build and verify the strict, planning-only Core formal source closure v6.

The v6 namespace is deliberately independent from the v4/v5 historical
artifacts.  It re-hashes ``REQUIRED_CODE_FILES`` from the supplied workspace,
records the current readiness/launch/source-audit inputs, and keeps root
admission closed.  Creating these JSON receipts is an evidence-generation
operation only: this module never submits jobs, starts training/GPU/solver
work, or writes the central registry/ledger.  ``--verify`` is read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_formal_planner import REQUIRED_CODE_FILES
from scripts.core_formal_source_closure_audit import build_audit as build_historical_audit
from scripts.core_strict_json import (
    absolute_path_without_following_leaf,
    read_bounded_raw_json,
    strict_json_object,
)


V6_NAMESPACE = "core-formal-release-candidate-v6"
V6_DATE = "20260922"
CLOSURE_SCHEMA = "core.formal_source_closure.v2"
AUDIT_SCHEMA = "core.formal_source_closure_audit.v2"
RECEIPT_SCHEMA = "core.formal_source_closure_admission.v2"
REQUIRED_FORMAL_RUNS = 9
REQUIRED_T1_FAMILIES = 3
REQUIRED_VALIDATION_CASES = 12
REQUIRED_MATERIAL_CASE_RUNS = 288
FORMAL_UPDATES = 32000


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(value: str | Path, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return absolute_path_without_following_leaf(path)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _reference(path: Path, root: Path, *, digest: str | None = None,
               byte_count: int | None = None) -> dict[str, Any]:
    return {
        "path": _relative(path, root),
        "sha256": digest if digest is not None else sha256_file(path),
        "bytes": byte_count if byte_count is not None else path.stat().st_size,
    }


def _load_json(value: str | Path, *, root: Path, role: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    path = _resolve(value, root)
    raw = read_bounded_raw_json(path, label=f"{role} {path}")
    payload = strict_json_object(raw, label=f"{role} {path}")
    return payload, path, _reference(
        path, root, digest=sha256_bytes(raw), byte_count=len(raw)
    )


def _source_rows(code_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative in REQUIRED_CODE_FILES:
        path = (code_root / relative).resolve()
        if not path.is_file():
            missing.append(relative)
            continue
        files.append({
            "relative_path": relative,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    return files, missing


def materialize_source_closure(*, data_root: str | Path,
                               code_root: str | Path | None = None) -> dict[str, Any]:
    """Re-hash the current required code files into a strict v6 closure."""
    root = Path(data_root).expanduser().resolve()
    code = Path(code_root).expanduser().resolve() if code_root is not None else root
    files, missing = _source_rows(code)
    closure_sha256 = sha256_bytes(canonical([
        {"relative_path": row["relative_path"], "sha256": row["sha256"]}
        for row in files
    ]).encode())
    return {
        "schema": CLOSURE_SCHEMA,
        "namespace": V6_NAMESPACE,
        "closure_version": V6_NAMESPACE,
        "hash_algorithm": "sha256",
        "required_files": list(REQUIRED_CODE_FILES),
        "files": files,
        "missing_files": missing,
        "closure_sha256": closure_sha256,
        "complete": not missing,
        "source_snapshot_policy": "fresh_code_closure_at_formal_admission",
        "formal_release": False,
        "formal_training_ready": False,
        "planning_only": True,
        "planning_allowed": True,
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "root_admission_granted": False,
        "read_only_verification_supported": True,
        "generator": _reference(Path(__file__).resolve(), root),
    }


def _declared_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = payload.get("files")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def verify_source_closure(payload: Mapping[str, Any], *, data_root: str | Path,
                          code_root: str | Path | None = None) -> dict[str, Any]:
    """Verify v6 metadata and every file hash against the live workspace."""
    current = materialize_source_closure(data_root=data_root, code_root=code_root)
    declared = _declared_rows(payload)
    declared_by_name = {
        row.get("relative_path"): dict(row)
        for row in declared
        if isinstance(row.get("relative_path"), str)
    }
    current_by_name = {row["relative_path"]: row for row in current["files"]}
    mismatch_files = sorted(
        name for name in set(declared_by_name) | set(current_by_name)
        if declared_by_name.get(name, {}).get("sha256") != current_by_name.get(name, {}).get("sha256")
        or declared_by_name.get(name, {}).get("bytes") != current_by_name.get(name, {}).get("bytes")
    )
    declared_names = [row.get("relative_path") for row in declared]
    checks = {
        "schema": payload.get("schema") == CLOSURE_SCHEMA,
        "namespace": payload.get("namespace") == V6_NAMESPACE,
        "closure_version": payload.get("closure_version") == V6_NAMESPACE,
        "required_file_set": payload.get("required_files") == list(REQUIRED_CODE_FILES),
        "declared_order_and_set": declared_names == list(REQUIRED_CODE_FILES),
        "complete": payload.get("complete") is True and not payload.get("missing_files"),
        "all_workspace_hashes_match": not mismatch_files and declared_by_name == current_by_name,
        "closure_hash_matches": payload.get("closure_sha256") == current["closure_sha256"],
        "formal_release_is_closed": payload.get("formal_release") is False,
        "planning_only": payload.get("planning_only") is True
        and payload.get("planning_allowed") is True,
        "formal_training_is_closed": payload.get("formal_training_allowed") is False,
        "no_formal_jobs": payload.get("formal_job_count") == 0,
        "root_admission_is_closed": payload.get("root_admission_granted") is False,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "mismatch_files": mismatch_files,
        "declared_closure_sha256": payload.get("closure_sha256"),
        "current_closure_sha256": current["closure_sha256"],
        "current_files": current["files"],
    }


def _snapshot_comparison(current: Mapping[str, Any], snapshot: Mapping[str, Any],
                         reference: Mapping[str, Any]) -> dict[str, Any]:
    rows = snapshot.get("files")
    old: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping):
                name = row.get("relative_path", row.get("path"))
                digest = row.get("sha256")
                if isinstance(name, str) and isinstance(digest, str):
                    old[name] = digest
    now = {
        row["relative_path"]: row["sha256"]
        for row in current.get("files", ())
        if isinstance(row, Mapping)
    }
    mismatch = sorted(name for name in set(old) | set(now) if old.get(name) != now.get(name))
    return {
        "snapshot": dict(reference),
        "snapshot_version": snapshot.get("closure_version"),
        "snapshot_closure_sha256": snapshot.get("closure_sha256"),
        "current_closure_sha256": current.get("closure_sha256"),
        "mismatch_files": mismatch,
        "matches_current": bool(old) and not mismatch and set(old) == set(now),
        "fresh_snapshot_required": bool(mismatch),
        "comparison_type": "historical_baseline_only",
        "mismatch_semantics": (
            "mismatch_files compare the named historical baseline with the live workspace; "
            "they are not a failure of the freshly rehashed v6 file set"
        ),
        "v6_current_closure_is_not_historical_baseline": True,
    }


def _gate(code: str, *, observed: Any, required: Any, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "observed": observed,
        "required": required,
        "passed": observed == required,
    }


def _resource_frontier_proven(readiness: Mapping[str, Any], upstream: set[str]) -> bool:
    admission = readiness.get("admission_audit")
    admission = admission if isinstance(admission, Mapping) else {}
    evidence = admission.get("capacity_evidence")
    return (
        "RESOURCE_FRONTIER_UNPROVEN" not in upstream
        and isinstance(evidence, Mapping)
        and evidence.get("schema") == "core.formal_capacity_evidence.v1"
        and evidence.get("valid") is True
        and evidence.get("formal_capacity_evidence") is True
        and evidence.get("formal_runs_counted") == 0
        and evidence.get("observed_update_frontier") == FORMAL_UPDATES
    )


def build_audit(*, data_root: str | Path, source_closure: str | Path,
                historical_snapshot: str | Path, readiness: str | Path,
                launch_contract: str | Path) -> dict[str, Any]:
    """Create a v6 audit report with an explicitly historical comparison."""
    root = Path(data_root).expanduser().resolve()
    closure_payload, closure_path, closure_ref = _load_json(
        source_closure, root=root, role="v6 source closure")
    historical_payload, _, historical_ref = _load_json(
        historical_snapshot, root=root, role="historical source closure")
    readiness_payload, _, readiness_ref = _load_json(
        readiness, root=root, role="formal readiness")
    launch_payload, _, launch_ref = _load_json(
        launch_contract, root=root, role="formal launch contract")
    closure = materialize_source_closure(data_root=root)
    closure_check = verify_source_closure(closure_payload, data_root=root)
    comparison = _snapshot_comparison(closure, historical_payload, historical_ref)
    readiness_blockers = sorted({
        str(item)
        for item in list(readiness_payload.get("upstream_admission_blockers", ()))
        + [row.get("code") for row in readiness_payload.get("blockers", ())
           if isinstance(row, Mapping) and row.get("code")]
    })
    blockers: list[dict[str, Any]] = []
    if readiness_payload.get("status") != "ready":
        blockers.append({
            "code": "FORMAL_READINESS_BLOCKED",
            "message": "current formal readiness remains blocked",
            "observed": readiness_blockers,
            "required": "ready",
        })
    if launch_payload.get("launch_allowed") is not True:
        blockers.append({
            "code": "LAUNCH_CONTRACT_BLOCKED",
            "message": "current launch contract does not authorize formal jobs",
            "observed": {
                "launch_allowed": launch_payload.get("launch_allowed"),
                "formal_job_count": launch_payload.get("formal_job_count"),
            },
            "required": {"launch_allowed": True, "formal_job_count": REQUIRED_FORMAL_RUNS},
        })
    if not closure_check["ok"]:
        blockers.append({
            "code": "V6_SOURCE_CLOSURE_INVALID",
            "message": "v6 closure must pass live re-hash verification",
            "observed": closure_check,
            "required": True,
        })
    blockers.append({
        "code": "FRESH_CLOSURE_NOT_ADMITTED",
        "message": "v6 records a fresh closure but does not grant root admission",
        "observed": False,
        "required": True,
    })
    return {
        "schema": AUDIT_SCHEMA,
        "namespace": V6_NAMESPACE,
        "audit_version": V6_NAMESPACE,
        "record_id": f"core-formal-source-closure-audit-v6-{V6_DATE}",
        "status": "proposal_only_blocked",
        "proposal_only": True,
        "formal_release": False,
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "launch_allowed": False,
        "inputs": {
            "v6_source_closure": closure_ref,
            "historical_snapshot": historical_ref,
            "formal_readiness": readiness_ref,
            "formal_launch_contract": launch_ref,
        },
        "current_source_closure": closure,
        "v6_source_closure": {
            "path": closure_ref["path"],
            "sha256": closure_ref["sha256"],
            "closure_sha256": closure_payload.get("closure_sha256"),
            "verification": closure_check,
        },
        "historical_comparison": comparison,
        "historical_audit_semantics": {
            "baseline": comparison["snapshot"],
            "baseline_version": comparison["snapshot_version"],
            "mismatch_files_are_historical_only": True,
            "mismatch_files_do_not_replace_v6_hashes": True,
            "current_v6_hash_source": "live REQUIRED_CODE_FILES re-hash",
        },
        "checks": {
            "v6_source_closure_complete": closure["complete"],
            "v6_source_closure_rehashed": closure_check["checks"]["all_workspace_hashes_match"],
            "v6_source_closure_hash_matches": closure_check["checks"]["closure_hash_matches"],
            "historical_comparison_recorded": True,
            "historical_mismatch_is_labeled": comparison["comparison_type"] == "historical_baseline_only",
            "formal_readiness_unblocked": readiness_payload.get("status") == "ready",
            "launch_contract_unblocked": launch_payload.get("launch_allowed") is True,
            "launch_contract_emits_zero_jobs": launch_payload.get("formal_job_count") == 0,
            "root_admission_granted": False,
        },
        "readiness_blockers": readiness_blockers,
        "blockers": blockers,
        "nine_run_launch_contract": {
            "required_formal_job_count": REQUIRED_FORMAL_RUNS,
            "observed_formal_job_count": launch_payload.get("formal_job_count"),
            "launch_allowed": launch_payload.get("launch_allowed"),
            "run_ids": [row.get("run_id") for row in launch_payload.get("run_matrix", ())
                        if isinstance(row, Mapping)],
        },
        "execution_constraints": {
            "read_only": True,
            "source_snapshot_written": False,
            "source_snapshot_admitted": False,
            "formal_job_specs_written": False,
            "formal_jobs_submitted": False,
            "formal_runs_started": 0,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_written": False,
            "ledger_written": False,
            "future_state_inputs": False,
        },
        "admission_next_step": (
            "root may review the v6 hash-bound planning input; formal readiness, launch, and root "
            "admission must remain closed until all Core gates are independently satisfied"
        ),
        "generator": _reference(Path(__file__).resolve(), root),
    }


def _read_referenced_json(reference: Mapping[str, Any], *, root: Path,
                          role: str) -> tuple[dict[str, Any], Path, dict[str, Any], bool]:
    raw_path = reference.get("path")
    if not isinstance(raw_path, str):
        raise ValueError(f"{role} reference has no path")
    path = _resolve(raw_path, root)
    payload, _, actual = _load_json(path, root=root, role=role)
    return payload, path, actual, actual == dict(reference)


def _readiness_gates(readiness: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    admission = readiness.get("admission_audit")
    admission = admission if isinstance(admission, Mapping) else {}
    protocol = readiness.get("formal_protocol")
    protocol = protocol if isinstance(protocol, Mapping) else {}
    upstream = {str(item) for item in readiness.get("upstream_admission_blockers", ())}
    return {
        "third_t1_family": _gate(
            "THIRD_T1_FAMILY",
            observed=int(admission.get("t1_family_count", len(admission.get("t1_families", ())))),
            required=REQUIRED_T1_FAMILIES,
            message="formal admission needs three distinct T1 families",
        ),
        "validation_denominator": _gate(
            "VALIDATION_DENOMINATOR",
            observed=int(admission.get("validation_case_count", 0)),
            required=REQUIRED_VALIDATION_CASES,
            message="formal evaluator needs twelve validation cases",
        ),
        "formal_run_denominator": _gate(
            "FORMAL_RUN_DENOMINATOR",
            observed=int(len(protocol.get("observed_run_ids", ()))),
            required=REQUIRED_FORMAL_RUNS,
            message="formal training requires nine completed model/seed runs",
        ),
        "material_case_run_denominator": _gate(
            "MATERIAL_CASE_RUN_DENOMINATOR",
            observed=int(protocol.get("observed_material_case_runs", 0)),
            required=REQUIRED_MATERIAL_CASE_RUNS,
            message="Core retains a 288 case-run material target",
        ),
        "resource_frontier": _gate(
            "RESOURCE_FRONTIER_UNPROVEN",
            observed=_resource_frontier_proven(readiness, upstream),
            required=True,
            message="fresh full-field 32000-update resource evidence is required",
        ),
        "formal_release": _gate(
            "FORMAL_RELEASE_REQUIRED",
            observed=False,
            required=True,
            message="formal source manifests must explicitly declare formal_release=true",
        ),
        "phase_plan_denominator": _gate(
            "PHASE_PLAN_CONTRACT",
            observed=readiness.get("checks", {}).get("phase_plan_denominator_contract") is True,
            required=True,
            message="phase plan must retain the registered denominator",
        ),
        "evaluator_failure_penalty": _gate(
            "EVALUATOR_DENOMINATOR_CONTRACT",
            observed=readiness.get("checks", {}).get("evaluator_failure_penalty_contract") is True,
            required=True,
            message="failed rollout frames must retain a unit penalty",
        ),
    }


def build_receipt(*, data_root: str | Path, source_closure: str | Path,
                  source_audit: str | Path, readiness: str | Path,
                  launch_contract: str | Path) -> dict[str, Any]:
    """Bind the v6 closure to current blocked readiness/launch/audit inputs."""
    root = Path(data_root).expanduser().resolve()
    closure_payload, closure_path, closure_ref = _load_json(
        source_closure, root=root, role="v6 source closure")
    audit_payload, _, audit_ref = _load_json(
        source_audit, root=root, role="v6 source-closure audit")
    readiness_payload, _, readiness_ref = _load_json(
        readiness, root=root, role="formal readiness")
    launch_payload, _, launch_ref = _load_json(
        launch_contract, root=root, role="formal launch contract")
    closure_check = verify_source_closure(closure_payload, data_root=root)
    gates = _readiness_gates(readiness_payload)
    gates.update({
        "v6_source_audit_rebound": _gate(
            "V6_SOURCE_AUDIT_REBOUND",
            observed=(audit_payload.get("namespace") == V6_NAMESPACE
                      and audit_payload.get("current_source_closure", {}).get("closure_sha256")
                      == closure_payload.get("closure_sha256")),
            required=True,
            message="v6 audit must bind the freshly rehashed v6 closure",
        ),
        "formal_readiness": _gate(
            "FORMAL_READINESS_BLOCKED",
            observed=readiness_payload.get("status"),
            required="ready",
            message="formal readiness must be ready before formal admission",
        ),
        "launch_contract": _gate(
            "LAUNCH_CONTRACT_BLOCKED",
            observed=launch_payload.get("launch_allowed"),
            required=True,
            message="launch contract must authorize formal jobs before admission",
        ),
        "formal_release": _gate(
            "FORMAL_RELEASE_REQUIRED",
            observed=False,
            required=True,
            message="v6 remains planning-only and does not promote formal release",
        ),
        "root_admission": _gate(
            "ROOT_ADMISSION_REQUIRED",
            observed=False,
            required=True,
            message="root admission is intentionally not granted by v6",
        ),
    })
    historical = audit_payload.get("historical_comparison")
    historical = historical if isinstance(historical, Mapping) else {}
    active_blockers = [row for row in gates.values()
                       if isinstance(row, Mapping) and row.get("passed") is not True]
    return {
        "schema": RECEIPT_SCHEMA,
        "namespace": V6_NAMESPACE,
        "receipt_version": V6_NAMESPACE,
        "record_id": f"core-formal-source-closure-root-admission-v6-{V6_DATE}",
        "status": "planning_only_blocked",
        "proposal_only": True,
        "formal_release": False,
        "formal_training_ready": False,
        "planning_only": True,
        "planning_allowed": True,
        "formal_training_allowed": False,
        "formal_job_count": 0,
        "required_formal_job_count": REQUIRED_FORMAL_RUNS,
        "launch_allowed": False,
        "source_closure": {
            "path": closure_ref["path"],
            "sha256": closure_ref["sha256"],
            "bytes": closure_ref["bytes"],
            "closure_sha256": closure_payload.get("closure_sha256"),
            "closure_version": closure_payload.get("closure_version"),
            "complete": closure_payload.get("complete"),
            "verification": closure_check,
        },
        "inputs": {
            "formal_readiness": readiness_ref,
            "formal_launch_contract": launch_ref,
            "source_closure_audit": audit_ref,
        },
        "bound_current_state": {
            "formal_readiness": {
                "status": readiness_payload.get("status"),
                "formal_job_count": readiness_payload.get("formal_job_count"),
                "upstream_admission_blockers": readiness_payload.get("upstream_admission_blockers", []),
            },
            "formal_launch_contract": {
                "status": launch_payload.get("status"),
                "formal_job_count": launch_payload.get("formal_job_count"),
                "launch_allowed": launch_payload.get("launch_allowed"),
            },
            "source_closure_audit": {
                "status": audit_payload.get("status"),
                "formal_job_count": audit_payload.get("formal_job_count"),
                "launch_allowed": audit_payload.get("launch_allowed"),
                "current_closure_sha256": audit_payload.get("current_source_closure", {}).get("closure_sha256"),
                "historical_mismatch_files": historical.get("mismatch_files", []),
                "historical_mismatch_semantics": historical.get("mismatch_semantics"),
            },
        },
        "gate_evaluation": gates,
        "historical_audit": {
            "path": historical.get("snapshot", {}).get("path"),
            "sha256": historical.get("snapshot", {}).get("sha256"),
            "closure_version": historical.get("snapshot_version"),
            "mismatch_files": historical.get("mismatch_files", []),
            "comparison_type": historical.get("comparison_type"),
            "mismatch_files_are_historical_only": True,
        },
        "active_blockers": active_blockers,
        "root_admission": {
            "requested": True,
            "granted": False,
            "status": "required_not_granted",
            "authority": "root",
            "decision": "hold",
            "reason": "v6 is a hash-bound planning input; readiness and launch gates remain blocked",
        },
        "execution_constraints": {
            "read_only": True,
            "source_snapshot_written": True,
            "source_snapshot_admitted": False,
            "formal_job_specs_written": False,
            "formal_jobs_submitted": False,
            "formal_runs_started": 0,
            "optimizer_started": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_written": False,
            "ledger_written": False,
            "future_state_inputs": False,
        },
        "next_admission_checks": [
            "rebind the current readiness and launch contracts after all upstream gates change",
            "retain the v5/v4 mismatch reports as historical comparisons only",
            "obtain the missing third T1 family, validation denominator, material denominator, and resource evidence",
            "request a separate root decision before any formal job specification or execution",
        ],
        "generator": _reference(Path(__file__).resolve(), root),
    }


def _reference_matches(reference: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    return dict(reference) == dict(actual)


def verify_admission(*, data_root: str | Path, source_closure: str | Path,
                     receipt: str | Path) -> dict[str, Any]:
    """Verify v6 closure, receipt, and all hash-bound current inputs read-only."""
    root = Path(data_root).expanduser().resolve()
    closure_payload, closure_path, closure_ref = _load_json(
        source_closure, root=root, role="v6 source closure")
    receipt_payload, receipt_path, receipt_actual_ref = _load_json(
        receipt, root=root, role="v6 root-admission receipt")
    closure_check = verify_source_closure(closure_payload, data_root=root)
    receipt_source = receipt_payload.get("source_closure")
    receipt_source = receipt_source if isinstance(receipt_source, Mapping) else {}
    inputs = receipt_payload.get("inputs")
    inputs = inputs if isinstance(inputs, Mapping) else {}
    bound: dict[str, tuple[dict[str, Any], Path, dict[str, Any], bool]] = {}
    input_errors: list[str] = []
    for key, role in (
        ("formal_readiness", "formal readiness"),
        ("formal_launch_contract", "formal launch contract"),
        ("source_closure_audit", "v6 source-closure audit"),
    ):
        reference = inputs.get(key)
        if not isinstance(reference, Mapping):
            input_errors.append(key)
            continue
        try:
            bound[key] = _read_referenced_json(reference, root=root, role=role)
        except (OSError, ValueError, json.JSONDecodeError):
            input_errors.append(key)
    readiness = bound.get("formal_readiness", ({}, Path(), {}, False))[0]
    launch = bound.get("formal_launch_contract", ({}, Path(), {}, False))[0]
    audit = bound.get("source_closure_audit", ({}, Path(), {}, False))[0]
    audit_inputs = audit.get("inputs") if isinstance(audit.get("inputs"), Mapping) else {}
    audit_rebound = (
        audit.get("namespace") == V6_NAMESPACE
        and audit.get("current_source_closure", {}).get("closure_sha256")
        == closure_payload.get("closure_sha256")
        and _reference_matches(inputs.get("formal_readiness", {}), audit_inputs.get("formal_readiness", {}))
        and _reference_matches(inputs.get("formal_launch_contract", {}), audit_inputs.get("formal_launch_contract", {}))
    )
    historical = audit.get("historical_comparison")
    historical = historical if isinstance(historical, Mapping) else {}
    checks = {
        "closure_verification": closure_check["ok"],
        "receipt_schema": receipt_payload.get("schema") == RECEIPT_SCHEMA,
        "receipt_namespace": receipt_payload.get("namespace") == V6_NAMESPACE,
        "receipt_version": receipt_payload.get("receipt_version") == V6_NAMESPACE,
        "receipt_path_matches": receipt_source.get("path") == _relative(closure_path, root),
        "receipt_file_hash_matches": receipt_source.get("sha256") == closure_ref["sha256"],
        "receipt_closure_hash_matches": receipt_source.get("closure_sha256") == closure_payload.get("closure_sha256"),
        "receipt_file_bytes_match": receipt_source.get("bytes") == closure_ref["bytes"],
        "formal_release_closed": receipt_payload.get("formal_release") is False,
        "planning_only": receipt_payload.get("planning_only") is True
        and receipt_payload.get("planning_allowed") is True,
        "formal_training_closed": receipt_payload.get("formal_training_allowed") is False,
        "formal_jobs_closed": receipt_payload.get("formal_job_count") == 0
        and receipt_payload.get("launch_allowed") is False,
        "root_admission_not_granted": receipt_payload.get("root_admission", {}).get("granted") is False,
        "current_inputs_are_hash_bound": not input_errors
        and all(item[3] for item in bound.values()),
        "readiness_remains_blocked": readiness.get("status") == "blocked"
        and readiness.get("formal_job_count") == 0,
        "launch_remains_blocked": launch.get("launch_allowed") is False
        and launch.get("formal_job_count") == 0,
        "audit_is_v6_rebound": audit_rebound
        and audit.get("formal_job_count") == 0
        and audit.get("launch_allowed") is False,
        "historical_mismatch_is_explicit": historical.get("comparison_type") == "historical_baseline_only"
        and historical.get("v6_current_closure_is_not_historical_baseline") is True,
        "no_registry_or_ledger_write": receipt_payload.get("execution_constraints", {}).get("registry_written") is False
        and receipt_payload.get("execution_constraints", {}).get("ledger_written") is False,
        "no_training_execution": receipt_payload.get("execution_constraints", {}).get("formal_runs_started") == 0
        and receipt_payload.get("execution_constraints", {}).get("optimizer_started") is False
        and receipt_payload.get("execution_constraints", {}).get("gpu_started") is False
        and receipt_payload.get("execution_constraints", {}).get("solver_started") is False,
        "receipt_file_reference_is_current": _reference_matches(receipt_actual_ref, {
            "path": _relative(receipt_path, root),
            "sha256": receipt_actual_ref["sha256"],
            "bytes": receipt_actual_ref["bytes"],
        }),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "input_errors": input_errors,
        "closure": closure_check,
        "actual_source_closure_sha256": closure_ref["sha256"],
        "actual_receipt_sha256": receipt_actual_ref["sha256"],
        "historical_mismatch_files": historical.get("mismatch_files", []),
    }


def write_json(path: str | Path, payload: Mapping[str, Any], *, immutable: bool = False) -> None:
    target = Path(path).expanduser().resolve()
    if immutable and target.exists():
        raise FileExistsError(f"immutable output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
    temporary.replace(target)


def write_sha256(path: str | Path, *, source: str | Path, immutable: bool = False) -> None:
    target = Path(path).expanduser().resolve()
    if immutable and target.exists():
        raise FileExistsError(f"immutable output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(source).expanduser().resolve()
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(f"{sha256_file(source_path)}  {source_path.name}\n", encoding="utf-8")
    temporary.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--source-closure", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--historical-snapshot", type=Path)
    parser.add_argument("--readiness", type=Path)
    parser.add_argument("--launch-contract", type=Path)
    parser.add_argument("--source-closure-sha256-output", type=Path)
    parser.add_argument("--source-audit-sha256-output", type=Path)
    parser.add_argument("--receipt-sha256-output", type=Path)
    parser.add_argument("--verify", action="store_true",
                        help="verify the existing v6 artifacts without writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.data_root).expanduser().resolve()
    if args.verify:
        result = verify_admission(
            data_root=root, source_closure=args.source_closure, receipt=args.receipt)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.historical_snapshot is None or args.readiness is None or args.launch_contract is None:
        raise SystemExit(
            "--historical-snapshot, --readiness, and --launch-contract are required when creating"
        )
    closure = materialize_source_closure(data_root=root)
    write_json(args.source_closure, closure, immutable=True)
    audit = build_audit(
        data_root=root,
        source_closure=args.source_closure,
        historical_snapshot=args.historical_snapshot,
        readiness=args.readiness,
        launch_contract=args.launch_contract,
    )
    write_json(args.source_audit, audit, immutable=True)
    receipt = build_receipt(
        data_root=root,
        source_closure=args.source_closure,
        source_audit=args.source_audit,
        readiness=args.readiness,
        launch_contract=args.launch_contract,
    )
    write_json(args.receipt, receipt, immutable=True)
    if args.source_closure_sha256_output is not None:
        write_sha256(args.source_closure_sha256_output, source=args.source_closure, immutable=True)
    if args.source_audit_sha256_output is not None:
        write_sha256(args.source_audit_sha256_output, source=args.source_audit, immutable=True)
    if args.receipt_sha256_output is not None:
        write_sha256(args.receipt_sha256_output, source=args.receipt, immutable=True)
    print(json.dumps({
        "status": receipt["status"],
        "namespace": receipt["namespace"],
        "formal_release": receipt["formal_release"],
        "planning_only": receipt["planning_only"],
        "formal_training_allowed": receipt["formal_training_allowed"],
        "formal_job_count": receipt["formal_job_count"],
        "launch_allowed": receipt["launch_allowed"],
        "root_admission_granted": receipt["root_admission"]["granted"],
        "closure_sha256": closure["closure_sha256"],
        "historical_mismatch_files": audit["historical_comparison"]["mismatch_files"],
        "active_blockers": [item["code"] for item in receipt["active_blockers"]],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
