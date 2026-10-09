#!/usr/bin/env python3
"""Build a source-bound continuation plan from a producer-proof registry.

This is a forward-only metadata consumer.  It joins the exact CURRENT336 and
scientific-audit inventories to completed ROOT192/193/198 producer proofs.
Only a terminal proof whose request, manifest, receipt, case summaries, and
trajectory SHA/stat closures agree receives saved-mask *diagnostic* coverage.
Ready, running, failed, missing, or source-unclosed attempts remain pending or
retry rows and are never counted as completed.  The next same-family groups
are metadata candidates only; this command never creates a launchable job,
opens HDF5/native/JSONL trajectory payloads, or hashes deferred payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ds_data02_stage2_typed_lifecycle_continuation_plan_v1 as v1
import ds_data02_stage2_typed_lifecycle_continuation_plan_v2 as v2


SCRIPT = Path(__file__).resolve()
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v3"
REGISTRY_SCHEMA = "ds02.stage2.typed-lifecycle-evidence-registry.v3"
REQUEST_SCHEMA = v1.REQUEST_SCHEMA
BATCH_MANIFEST_SCHEMA = v1.BATCH_MANIFEST_SCHEMA
MAX_SMALL_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_CASES = 8
DEFAULT_MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
ROOT_CONFIG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")


class ContinuationPlanV3Error(ValueError):
    """Raised when a producer proof or continuation edge is not closed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ContinuationPlanV3Error(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise ContinuationPlanV3Error(f"{label} is not hexadecimal")
    return value


def _file(value: Any, label: str, *, deferred: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise ContinuationPlanV3Error(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not deferred and path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}:
        raise ContinuationPlanV3Error(f"{label} is deferred payload content: {path}")
    if not path.is_file():
        raise ContinuationPlanV3Error(f"{label} is missing: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    path = _file(path, label)
    if path.stat().st_size > MAX_SMALL_BYTES:
        raise ContinuationPlanV3Error(f"{label} exceeds bounded JSON size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuationPlanV3Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ContinuationPlanV3Error(f"{label} must be an object")
    return value


def _same_path(value: Any, path: Path) -> bool:
    try:
        return Path(str(value)).expanduser().resolve() == path.resolve()
    except (OSError, TypeError, ValueError):
        return False


def _small_ref(path: Path, label: str) -> dict[str, Any]:
    path = _file(path, label)
    stat = path.stat()
    if stat.st_size > MAX_SMALL_BYTES:
        raise ContinuationPlanV3Error(f"{label} exceeds bounded reference size: {path}")
    return {
        "role": label,
        "path": str(path),
        "sha256": _sha256_file(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "content_opened": True,
    }


def _registry_edge(value: Any, expected_path: Path, expected_sha: str, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not _same_path(value.get("path"), expected_path):
        raise ContinuationPlanV3Error(f"registry {label} path differs")
    declared = _sha(value.get("sha256"), f"registry {label} SHA")
    if declared != expected_sha or _sha256_file(expected_path) != expected_sha:
        raise ContinuationPlanV3Error(f"registry {label} SHA differs")
    return _small_ref(expected_path, label)


def _validate_batch_request_manifest(
    request_path: Path,
    manifest_path: Path,
    *,
    rows_by_id: dict[str, dict[str, Any]],
    root192_case_id: str,
    producer_id: str,
) -> tuple[set[str], dict[str, Any]]:
    """Validate a request/manifest without treating it as execution."""
    request_path = _file(request_path, f"{producer_id} request")
    manifest_path = _file(manifest_path, f"{producer_id} manifest")
    request = _json(request_path, f"{producer_id} request")
    manifest = _json(manifest_path, f"{producer_id} manifest")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ContinuationPlanV3Error(f"{producer_id} request schema differs")
    contract = request.get("manifest_contract")
    if not isinstance(contract, dict) or not _same_path(contract.get("path"), manifest_path):
        raise ContinuationPlanV3Error(f"{producer_id} request manifest path is not exact")
    if _sha(contract.get("sha256"), f"{producer_id} manifest contract SHA") != _sha256_file(manifest_path):
        raise ContinuationPlanV3Error(f"{producer_id} request manifest contract SHA differs")
    if manifest.get("schema") != BATCH_MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_BATCH":
        raise ContinuationPlanV3Error(f"{producer_id} manifest is not a ready batch manifest")
    request_ids = request.get("physical_case_ids")
    records = manifest.get("cases")
    if not isinstance(request_ids, list) or not all(isinstance(item, str) for item in request_ids):
        raise ContinuationPlanV3Error(f"{producer_id} request case IDs are missing")
    manifest_ids = [item.get("physical_case_id") for item in records] if isinstance(records, list) else []
    if not manifest_ids or any(not isinstance(item, str) for item in manifest_ids):
        raise ContinuationPlanV3Error(f"{producer_id} manifest cases are malformed")
    if len(set(request_ids)) != len(request_ids) or len(set(manifest_ids)) != len(manifest_ids) or set(request_ids) != set(manifest_ids):
        raise ContinuationPlanV3Error(f"{producer_id} request/manifest case sets differ")
    if manifest.get("case_count") != len(manifest_ids):
        raise ContinuationPlanV3Error(f"{producer_id} manifest case_count differs")
    pending = set(request_ids)
    family = request.get("family_id")
    for case_id in sorted(pending):
        row = rows_by_id.get(case_id)
        if row is None:
            raise ContinuationPlanV3Error(f"{producer_id} case is absent from CURRENT336: {case_id}")
        if row.get("historical_alias") != "NONE" or row.get("audit_join", {}).get("status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            raise ContinuationPlanV3Error(f"{producer_id} case is not exact/non-alias: {case_id}")
        if family != row.get("family_id"):
            raise ContinuationPlanV3Error(f"{producer_id} family differs for {case_id}")
    # A request can be the immutable producer request after execution; its
    # terminal status is recorded in the proof/receipt, never patched into the
    # request.  Reject embedded execution evidence to prevent arbitrary joins.
    if request.get("execution_receipt") or request.get("receipt") or request.get("completion_evidence"):
        raise ContinuationPlanV3Error(f"{producer_id} request embeds execution evidence")
    return pending, {
        "status": "REQUEST_MANIFEST_VALIDATED_NO_EXECUTION_CREDIT",
        "request": _small_ref(request_path, f"{producer_id}_request"),
        "manifest": _small_ref(manifest_path, f"{producer_id}_manifest"),
        "case_ids": sorted(pending),
        "family_id": family,
        "attempt_id": request.get("attempt_id"),
    }


def _validate_registry(
    registry_path: Path,
    *,
    current_path: Path,
    audit_path: Path,
    expected_current_sha256: str,
    expected_audit_sha256: str,
    rows_by_id: dict[str, dict[str, Any]],
    alias_case: str | None,
) -> dict[str, Any]:
    registry_path = _file(registry_path, "evidence registry")
    registry = _json(registry_path, "evidence registry")
    if registry.get("schema") != REGISTRY_SCHEMA or registry.get("status") != "SOURCE_METADATA_REGISTRY":
        raise ContinuationPlanV3Error("evidence registry schema/status differs")
    _registry_edge(registry.get("current"), current_path, expected_current_sha256, "CURRENT336")
    _registry_edge(registry.get("audit"), audit_path, expected_audit_sha256, "scientific audit")
    producers = registry.get("producers")
    if not isinstance(producers, list) or not producers:
        raise ContinuationPlanV3Error("evidence registry producers are missing")
    seen_producers: set[str] = set()
    seen_cases: set[str] = set()
    covered: set[str] = set()
    pending: set[str] = set()
    failed: set[str] = set()
    case_evidence: dict[str, dict[str, Any]] = {}
    producer_results: list[dict[str, Any]] = []
    root192_case: str | None = None
    for producer in producers:
        if not isinstance(producer, dict) or not isinstance(producer.get("producer_id"), str):
            raise ContinuationPlanV3Error("producer registry row is malformed")
        producer_id = producer["producer_id"]
        if producer_id in seen_producers:
            raise ContinuationPlanV3Error(f"duplicate producer: {producer_id}")
        seen_producers.add(producer_id)
        kind = producer.get("kind")
        status = str(producer.get("status", "")).upper()
        declared_ids = producer.get("case_ids")
        if not isinstance(declared_ids, list) or not all(isinstance(item, str) for item in declared_ids) or len(set(declared_ids)) != len(declared_ids):
            raise ContinuationPlanV3Error(f"{producer_id} case_ids are malformed")
        if seen_cases.intersection(declared_ids):
            raise ContinuationPlanV3Error(f"producer case overlap: {sorted(seen_cases.intersection(declared_ids))[:3]}")
        for case_id in declared_ids:
            row = rows_by_id.get(case_id)
            if row is None:
                raise ContinuationPlanV3Error(f"{producer_id} case absent from CURRENT336: {case_id}")
            if alias_case and case_id == alias_case:
                raise ContinuationPlanV3Error(f"historical alias cannot receive producer evidence: {case_id}")
        seen_cases.update(declared_ids)
        if kind == "single_typed_lifecycle":
            if producer_id != "ROOT192" or status != "COMPLETED" or len(declared_ids) != 1:
                raise ContinuationPlanV3Error("ROOT192 registry entry is malformed")
            proof_ref = producer.get("proof")
            summary_ref = producer.get("summary")
            proof_path = _file(proof_ref.get("path") if isinstance(proof_ref, dict) else None, "ROOT192 proof")
            summary_path = _file(summary_ref.get("path") if isinstance(summary_ref, dict) else None, "ROOT192 summary")
            if _sha(proof_ref.get("sha256") if isinstance(proof_ref, dict) else None, "ROOT192 proof registry SHA") != _sha256_file(proof_path):
                raise ContinuationPlanV3Error("ROOT192 proof registry SHA differs")
            if _sha(summary_ref.get("sha256") if isinstance(summary_ref, dict) else None, "ROOT192 summary registry SHA") != _sha256_file(summary_path):
                raise ContinuationPlanV3Error("ROOT192 summary registry SHA differs")
            case_id, evidence = v1._validate_root192(
                proof_path,
                summary_path,
                current_path=current_path,
                audit_path=audit_path,
                expected_current_sha256=expected_current_sha256,
                expected_audit_sha256=expected_audit_sha256,
                rows_by_id=rows_by_id,
            )
            if case_id != declared_ids[0]:
                raise ContinuationPlanV3Error("ROOT192 declared case differs from proof")
            root192_case = case_id
            covered.add(case_id)
            case_evidence[case_id] = evidence
            producer_results.append({"producer_id": producer_id, "kind": kind, "status": "ACTUAL_SAVED_MASK_COMPLETED", "case_ids": [case_id], "evidence": evidence})
            continue
        if kind != "typed_lifecycle_batch":
            raise ContinuationPlanV3Error(f"unsupported producer kind: {kind}")
        request_ref = producer.get("request")
        manifest_ref = producer.get("manifest")
        request_path = _file(request_ref.get("path") if isinstance(request_ref, dict) else None, f"{producer_id} request")
        manifest_path = _file(manifest_ref.get("path") if isinstance(manifest_ref, dict) else None, f"{producer_id} manifest")
        if _sha(request_ref.get("sha256") if isinstance(request_ref, dict) else None, f"{producer_id} request registry SHA") != _sha256_file(request_path):
            raise ContinuationPlanV3Error(f"{producer_id} request registry SHA differs")
        if _sha(manifest_ref.get("sha256") if isinstance(manifest_ref, dict) else None, f"{producer_id} manifest registry SHA") != _sha256_file(manifest_path):
            raise ContinuationPlanV3Error(f"{producer_id} manifest registry SHA differs")
        pending_ids, request_evidence = _validate_batch_request_manifest(
            request_path, manifest_path, rows_by_id=rows_by_id,
            root192_case_id=root192_case or "", producer_id=producer_id,
        )
        if pending_ids != set(declared_ids):
            raise ContinuationPlanV3Error(f"{producer_id} registry case_ids differ from immutable manifest")
        if status in {"READY_NOTRUN", "PENDING_NO_TERMINAL_PROOF", "RUNNING_NO_CREDIT"}:
            pending.update(pending_ids)
            for case_id in pending_ids:
                case_evidence[case_id] = {"status": status, "actual_saved_mask_coverage": False, "scientific_credit": "NONE", "request": request_evidence["request"], "manifest": request_evidence["manifest"]}
            producer_results.append({"producer_id": producer_id, "kind": kind, "status": status, "case_ids": sorted(pending_ids), "evidence": request_evidence})
            continue
        if status != "COMPLETED":
            raise ContinuationPlanV3Error(f"{producer_id} has unsupported status: {status}")
        proof_ref = producer.get("proof")
        proof_path = _file(proof_ref.get("path") if isinstance(proof_ref, dict) else None, f"{producer_id} proof")
        if _sha(proof_ref.get("sha256") if isinstance(proof_ref, dict) else None, f"{producer_id} proof registry SHA") != _sha256_file(proof_path):
            raise ContinuationPlanV3Error(f"{producer_id} proof registry SHA differs")
        proof_metadata = _json(proof_path, f"{producer_id} proof")
        proof_status = proof_metadata.get("status")
        if not isinstance(proof_status, str) or not proof_status.startswith("VERIFIED_ACTUAL_"):
            raise ContinuationPlanV3Error(f"{producer_id} proof is not terminal actual evidence")
        if proof_metadata.get("guarded_receipt_status") != "completed" or proof_metadata.get("parent_reservation_released") is not True:
            raise ContinuationPlanV3Error(f"{producer_id} proof lacks terminal guard/release evidence")
        try:
            actual = v2._validate_actual_proof(
                proof_path,
                root193_request=request_path,
                root193_manifest=manifest_path,
                pending_ids=pending_ids,
                rows_by_id=rows_by_id,
                expected_current_sha256=expected_current_sha256,
            )
        except (v1.ContinuationPlanError, v2.ContinuationPlanV2Error) as exc:
            raise ContinuationPlanV3Error(f"{producer_id} actual proof is not source-closed: {exc}") from exc
        for case_id, evidence in actual["case_results"].items():
            case_evidence[case_id] = evidence
            if evidence.get("actual_saved_mask_coverage") is True:
                covered.add(case_id)
            elif evidence.get("new_attempt_identity_required"):
                failed.add(case_id)
            else:
                pending.add(case_id)
        producer_results.append({"producer_id": producer_id, "kind": kind, "status": "ACTUAL_PROOF_BOUND", "case_ids": sorted(pending_ids), "evidence": actual})
    if root192_case is None:
        raise ContinuationPlanV3Error("registry lacks completed ROOT192 anchor")
    if covered & pending or covered & failed or pending & failed:
        raise ContinuationPlanV3Error("coverage/pending/failure sets overlap")
    return {
        "registry": _small_ref(registry_path, "evidence_registry"),
        "producer_results": producer_results,
        "case_evidence": case_evidence,
        "covered": covered,
        "pending": pending,
        "failed": failed,
        "seen_cases": seen_cases,
        "root192_case": root192_case,
    }


def _atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_SMALL_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ContinuationPlanV3Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise ContinuationPlanV3Error(f"output exceeds bounded size: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_plan(
    current_path: Path,
    audit_path: Path,
    registry_path: Path,
    output: Path,
    *,
    expected_current_sha256: str,
    expected_audit_sha256: str,
    alias_case: str | None = v1.DEFAULT_ALIAS_CASE,
    max_cases: int = DEFAULT_MAX_CASES,
    max_group_bytes: int = DEFAULT_MAX_GROUP_BYTES,
) -> dict[str, Any]:
    current_path = _file(current_path, "CURRENT336")
    audit_path = _file(audit_path, "scientific audit")
    expected_current_sha256 = _sha(expected_current_sha256, "expected CURRENT SHA")
    expected_audit_sha256 = _sha(expected_audit_sha256, "expected audit SHA")
    if _sha256_file(current_path) != expected_current_sha256:
        raise ContinuationPlanV3Error("CURRENT SHA differs")
    if _sha256_file(audit_path) != expected_audit_sha256:
        raise ContinuationPlanV3Error("scientific audit SHA differs")
    current = _json(current_path, "CURRENT336")
    audit = _json(audit_path, "scientific audit")
    if current.get("schema") != v1.CURRENT_SCHEMA or audit.get("schema") != v1.AUDIT_SCHEMA:
        raise ContinuationPlanV3Error("CURRENT/audit schema differs")
    try:
        rows, source_counts = v1.base._validate_rows(current, audit, expected_current_sha256, alias_case)
    except (v1.ContinuationPlanError, KeyError, TypeError) as exc:
        raise ContinuationPlanV3Error(str(exc)) from exc
    if len(rows) != 336:
        raise ContinuationPlanV3Error("planner requires exactly 336 CURRENT rows")
    rows_by_id = {row["physical_case_id"]: row for row in rows}
    evidence = _validate_registry(
        registry_path,
        current_path=current_path,
        audit_path=audit_path,
        expected_current_sha256=expected_current_sha256,
        expected_audit_sha256=expected_audit_sha256,
        rows_by_id=rows_by_id,
        alias_case=alias_case,
    )
    covered = set(evidence["covered"])
    pending = set(evidence["pending"])
    failed = set(evidence["failed"])
    groups_rows: list[dict[str, Any]] = []
    case_records: list[dict[str, Any]] = []
    for row in rows:
        case_id = row["physical_case_id"]
        if alias_case and case_id == alias_case:
            status = "HISTORICAL_ALIAS_UNRESOLVED"
            groupable = False
        elif case_id in covered:
            status = "ACTUAL_SAVED_MASK_COMPLETED"
            groupable = False
        elif case_id in failed:
            status = "FAILED_REQUIRES_NEW_ATTEMPT"
            groupable = False
        elif case_id in pending:
            status = "PENDING_NO_CREDIT"
            groupable = False
        elif row["audit_join"]["status"] == "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            status = "UNSCHEDULED_EXACT_CURRENT_AUDIT"
            groupable = True
            groups_rows.append(row)
        else:
            status = "SOURCE_JOIN_INCOMPLETE_REQUIRES_NEW_IDENTITY"
            groupable = False
        case_records.append({
            "current_index": row["current_index"],
            "physical_case_id": case_id,
            "family_id": row.get("family_id"),
            "source_join_status": row["audit_join"]["status"],
            "historical_alias": row["historical_alias"],
            "declared_source_bytes": int(row["trajectory"]["declared_bytes"]),
            "trajectory_path": row["trajectory"]["path"],
            "status": status,
            "actual_saved_mask_coverage": case_id in covered,
            "scientific_credit": "NONE_PHYSICAL" if case_id in covered else "NONE",
            "groupable": groupable,
            "new_attempt_identity_required": case_id in failed or status in {"SOURCE_JOIN_INCOMPLETE_REQUIRES_NEW_IDENTITY", "UNSCHEDULED_EXACT_CURRENT_AUDIT"},
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "producer_evidence": evidence["case_evidence"].get(case_id),
        })
    groups = v1._group_rows(groups_rows, max_cases, max_group_bytes)
    group_for_case = {case_id: group["group_id"] for group in groups for case_id in group["case_ids"]}
    for record in case_records:
        if record["physical_case_id"] in group_for_case:
            record["group_id"] = group_for_case[record["physical_case_id"]]
    grouped_ids = [case_id for group in groups for case_id in group["case_ids"]]
    if len(grouped_ids) != len(set(grouped_ids)) or set(grouped_ids) & (covered | pending | failed | ({alias_case} if alias_case else set())):
        raise ContinuationPlanV3Error("continuation groups overlap evidence or alias rows")
    next_candidate = groups[0] if groups else None
    plan = {
        "schema": PLAN_SCHEMA,
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "current_catalog": {"path": str(current_path), "sha256": expected_current_sha256},
        "scientific_audit": {"path": str(audit_path), "sha256": expected_audit_sha256},
        "evidence_registry": evidence["registry"],
        "inventory_scope": {"exact_current_case_count": 336, "case_key": "physical_case_id exact set", "families": sorted({str(row.get("family_id")) for row in rows}), "source_content_opened": False, "trajectory_content_hashed": False},
        "producer_evidence": evidence["producer_results"],
        "coverage": {
            "current_cases": len(rows),
            "exact_current_audit_rows": source_counts["exact_current_audit_metadata_joins"],
            "historical_alias_unresolved": source_counts["historical_alias_unresolved"],
            "incomplete_or_mismatched": source_counts["incomplete_or_mismatched"],
            "actual_saved_mask_cases": len(covered),
            "pending_no_credit_cases": len(pending),
            "failed_requires_new_attempt_cases": len(failed),
            "remaining_exact_unscheduled_cases": len(groups_rows),
            "physical_or_scientific_credit_cases": 0,
        },
        "case_records": case_records,
        "groups": groups,
        "next_batch_candidate": next_candidate,
        "group_policy": {"max_cases_per_group": max_cases, "max_declared_source_bytes": max_group_bytes, "families_never_mixed": True, "remaining_groups_are_metadata_only": True, "request_created": False, "launch_allowed_by_planner": False, "deferred_h5_content_opened": False, "root_request_config_declared_path": str(ROOT_CONFIG), "root_request_config_binding_deferred_to_guard": True},
        "retry_policy": {"failed_case_ids": sorted(failed), "failed_attempts_require_new_request_manifest_attempt": True, "pending_case_ids_not_completed": sorted(pending), "old_request_manifest_receipt_bytes_immutable": True, "future_failure_is_not_completion": True},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "source_read_policy": {"CURRENT_audit_registry_and_proof_json_opened": True, "trajectory_stat_only_via_audit_inventory": True, "trajectory_content_opened": False, "trajectory_content_hashed": False, "native_or_bi4_opened": False, "solver_started": False, "execution_request_created": False},
    }
    _atomic_json(Path(output), plan)
    return {"status": plan["status"], "output": str(Path(output).resolve()), "output_sha256": _sha256_file(Path(output)), "actual_saved_mask_cases": len(covered), "pending_no_credit_cases": len(pending), "failed_requires_new_attempt_cases": len(failed), "remaining_exact_unscheduled_cases": len(groups_rows), "group_count": len(groups), "trajectory_content_opened": False, "trajectory_content_hashed": False}


def self_test() -> dict[str, Any]:
    return {"status": "PASS", "schema": PLAN_SCHEMA, "launch_allowed_by_planner": False, "deferred_trajectory_content_opened": False, "completed_credit_requires_terminal_proof": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--current", required=True, type=Path)
    prepare.add_argument("--audit-verification", required=True, type=Path)
    prepare.add_argument("--evidence-registry", required=True, type=Path)
    prepare.add_argument("--expected-current-sha256", required=True)
    prepare.add_argument("--expected-audit-sha256", required=True)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--historical-alias-case", default=v1.DEFAULT_ALIAS_CASE)
    prepare.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
    prepare.add_argument("--max-group-bytes", type=int, default=DEFAULT_MAX_GROUP_BYTES)
    args = parser.parse_args(argv)
    if args.action == "self-test":
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    try:
        result = build_plan(args.current, args.audit_verification, args.evidence_registry, args.output, expected_current_sha256=args.expected_current_sha256, expected_audit_sha256=args.expected_audit_sha256, alias_case=args.historical_alias_case, max_cases=args.max_cases, max_group_bytes=args.max_group_bytes)
    except (ContinuationPlanV3Error, OSError) as exc:
        raise SystemExit(f"ContinuationPlanV3Error: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
