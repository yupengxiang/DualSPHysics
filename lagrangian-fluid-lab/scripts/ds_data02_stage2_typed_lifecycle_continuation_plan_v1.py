#!/usr/bin/env python3
"""Build a metadata-only continuation plan for typed-lifecycle audits.

The continuation is deliberately a *plan*, not a request builder.  It joins
the exact CURRENT336/audit inventory with one completed ROOT192 pilot and one
ROOT193 request that is still ready but has not run.  The pilot may receive
saved-mask diagnostic coverage; the pending request receives no execution or
scientific credit.  Remaining exact rows are grouped by family, with the
case-count and deferred-source-byte limits recorded for a later root-owned
request.

Only JSON and filesystem metadata are read here.  HDF5/native trajectory
content is never opened or hashed.  A failed, missing, or mismatched source
join is retained as an explicit retry row and requires a new request,
manifest, and attempt identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ds_data02_stage2_typed_lifecycle_batch_plan_v2 as base


SCRIPT = Path(__file__).resolve()
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v1"
REQUEST_SCHEMA = "ds02.request.v1"
BATCH_MANIFEST_SCHEMA = "ds02.stage2.typed-lifecycle-batch.v1"
CURRENT_SCHEMA = base.CURRENT_SCHEMA
AUDIT_SCHEMA = base.AUDIT_SCHEMA
DEFAULT_ALIAS_CASE = base.DEFAULT_ALIAS_CASE
DEFAULT_MAX_CASES = 8
DEFAULT_MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
COMPLETED_STATUS = "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT"
ROOT192_STATUS_PREFIX = "VERIFIED_ACTUAL_TYPED_LIFECYCLE_V4_SINGLE_CASE"


class ContinuationPlanError(ValueError):
    """Raised when an immutable evidence edge is missing or inconsistent."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ContinuationPlanError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise ContinuationPlanError(f"{label} is not hexadecimal")
    return value


def _file(value: Any, label: str, *, reject_h5: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise ContinuationPlanError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if reject_h5 and path.suffix.lower() in {".h5", ".hdf5"}:
        raise ContinuationPlanError(f"{label} is a deferred HDF5 path")
    if not path.is_file():
        raise ContinuationPlanError(f"{label} is missing: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuationPlanError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ContinuationPlanError(f"{label} must be a JSON object")
    return value


def _same_path(left: Any, right: Path) -> bool:
    return isinstance(left, (str, os.PathLike)) and Path(left).expanduser().resolve() == right


def _small_ref(path: Path, role: str) -> dict[str, Any]:
    """Hash a known-small JSON/source record, never a deferred trajectory."""
    if path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4"}:
        raise ContinuationPlanError(f"{role} cannot be a native/trajectory payload")
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "sha256": _sha256_file(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "content_opened": True,
    }


def _find_small_input(entries: Any, path: Path) -> dict[str, Any] | None:
    if not isinstance(entries, list):
        return None
    for item in entries:
        if not isinstance(item, dict):
            continue
        candidate = item.get("path")
        if _same_path(candidate, path):
            return item
    return None


def _validate_root192(
    proof_path: Path,
    summary_path: Path,
    *,
    current_path: Path,
    audit_path: Path,
    expected_current_sha256: str,
    expected_audit_sha256: str,
    rows_by_id: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    proof_path = _file(proof_path, "ROOT192 proof", reject_h5=True)
    summary_path = _file(summary_path, "ROOT192 summary", reject_h5=True)
    proof_sha = _sha256_file(proof_path)
    summary_sha = _sha256_file(summary_path)
    proof = _json(proof_path, "ROOT192 proof")
    summary = _json(summary_path, "ROOT192 summary")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise ContinuationPlanError("ROOT192 proof schema differs")
    if not isinstance(proof.get("status"), str) or not proof["status"].startswith(ROOT192_STATUS_PREFIX):
        raise ContinuationPlanError("ROOT192 proof is not the completed typed-lifecycle pilot")
    if proof.get("report") is None or not _same_path(proof.get("report"), summary_path):
        raise ContinuationPlanError("ROOT192 proof report does not bind the supplied summary")
    if _sha(proof.get("report_sha256"), "ROOT192 report SHA") != summary_sha:
        raise ContinuationPlanError("ROOT192 report SHA differs")
    case_id = proof.get("physical_case_id")
    if not isinstance(case_id, str) or case_id not in rows_by_id:
        raise ContinuationPlanError("ROOT192 physical case is absent from CURRENT336")
    if rows_by_id[case_id]["historical_alias"] != "NONE":
        raise ContinuationPlanError("ROOT192 cannot credit the historical alias")
    request_path = _file(proof.get("request"), "ROOT192 request", reject_h5=True)
    request_sha = _sha256_file(request_path)
    if _sha(proof.get("request_sha256"), "ROOT192 request SHA") != request_sha:
        raise ContinuationPlanError("ROOT192 request SHA differs")
    request = _json(request_path, "ROOT192 request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("physical_case_id") != case_id:
        raise ContinuationPlanError("ROOT192 request does not bind its physical case")
    if request.get("family_id") != rows_by_id[case_id].get("family_id"):
        raise ContinuationPlanError("ROOT192 request family differs from CURRENT")
    receipt_path = _file(proof.get("receipt"), "ROOT192 execution receipt", reject_h5=True)
    receipt_sha = _sha256_file(receipt_path)
    if _sha(proof.get("receipt_sha256"), "ROOT192 receipt SHA") != receipt_sha:
        raise ContinuationPlanError("ROOT192 receipt SHA differs")
    receipt = _json(receipt_path, "ROOT192 execution receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ContinuationPlanError("ROOT192 execution receipt is not completed/zero")
    if proof.get("guarded_receipt_status") != "completed" or proof.get("parent_reservation_released") is not True:
        raise ContinuationPlanError("ROOT192 guard completion/release is not proven")
    if proof.get("H5_BI4_read_by_root") is not False:
        raise ContinuationPlanError("ROOT192 proof has unexpected root native-read claim")
    if summary.get("schema") != "ds02.stage2.typed-lifecycle-sidecar.v4":
        raise ContinuationPlanError("ROOT192 summary schema differs")
    if summary.get("status") != COMPLETED_STATUS:
        raise ContinuationPlanError("ROOT192 summary is not completed without physical credit")
    if summary.get("physical_case_id") != case_id or summary.get("family_id") != rows_by_id[case_id].get("family_id"):
        raise ContinuationPlanError("ROOT192 summary case/family differs from CURRENT")
    source = summary.get("source")
    if not isinstance(source, dict) or source.get("current336_sha256") != expected_current_sha256:
        raise ContinuationPlanError("ROOT192 summary does not bind expected CURRENT SHA")
    # The actual ROOT192 proof carries the scope diagnostic; a few pilot
    # summaries carry the same object instead.  Accept either exact producer
    # location while requiring one of them, so a generic completed receipt
    # cannot silently receive saved-mask coverage.
    saved_mask_diagnostic = proof.get("typed_mask_lifecycle_diagnostic")
    if not isinstance(saved_mask_diagnostic, dict):
        saved_mask_diagnostic = summary.get("typed_mask_lifecycle_diagnostic")
    if not isinstance(saved_mask_diagnostic, dict):
        raise ContinuationPlanError("ROOT192 proof/summary lacks saved-mask diagnostic")
    fresh = proof.get("fresh_small_inputs")
    current_edge = _find_small_input(fresh, current_path)
    audit_edge = _find_small_input(fresh, audit_path)
    if not current_edge or current_edge.get("sha256") != expected_current_sha256:
        raise ContinuationPlanError("ROOT192 proof fresh inputs lack expected CURRENT edge")
    if not audit_edge or audit_edge.get("sha256") != expected_audit_sha256:
        raise ContinuationPlanError("ROOT192 proof fresh inputs lack expected audit edge")
    return case_id, {
        "status": "ACTUAL_SAVED_MASK_COMPLETED",
        "actual_saved_mask_coverage": True,
        "scientific_credit": "NONE_PHYSICAL",
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "proof": _small_ref(proof_path, "root192_proof"),
        "summary": _small_ref(summary_path, "root192_summary"),
        "request": {"path": str(request_path), "sha256": request_sha},
        "receipt": {"path": str(receipt_path), "sha256": receipt_sha},
        "summary_status": summary.get("status"),
        "saved_mask_diagnostic_source": "proof" if isinstance(proof.get("typed_mask_lifecycle_diagnostic"), dict) else "summary",
        "scope": "one exact CURRENT case saved-mask lifecycle only; no native/physical credit",
    }


def _validate_root193(
    request_path: Path,
    manifest_path: Path,
    *,
    rows_by_id: dict[str, dict[str, Any]],
    root192_case_id: str,
) -> tuple[set[str], dict[str, Any]]:
    request_path = _file(request_path, "ROOT193 request", reject_h5=True)
    manifest_path = _file(manifest_path, "ROOT193 manifest", reject_h5=True)
    request_sha = _sha256_file(request_path)
    manifest_sha = _sha256_file(manifest_path)
    request = _json(request_path, "ROOT193 request")
    manifest = _json(manifest_path, "ROOT193 manifest")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ContinuationPlanError("ROOT193 request schema differs")
    contract = request.get("manifest_contract")
    if not isinstance(contract, dict) or not _same_path(contract.get("path"), manifest_path):
        raise ContinuationPlanError("ROOT193 request manifest path is not exact")
    if _sha(contract.get("sha256"), "ROOT193 manifest contract SHA") != manifest_sha:
        raise ContinuationPlanError("ROOT193 manifest contract SHA differs")
    if manifest.get("schema") != BATCH_MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_BATCH":
        raise ContinuationPlanError("ROOT193 manifest is not a ready batch manifest")
    if request.get("status") in {"completed", "COMPLETED", "failed", "FAILED"}:
        raise ContinuationPlanError("ROOT193 request already carries a terminal status")
    if request.get("execution_receipt") or request.get("receipt") or request.get("completion_evidence"):
        raise ContinuationPlanError("ROOT193 request carries execution evidence and cannot be marked READY_NOTRUN")
    request_ids = request.get("physical_case_ids")
    records = manifest.get("cases")
    if not isinstance(request_ids, list) or not all(isinstance(value, str) for value in request_ids):
        raise ContinuationPlanError("ROOT193 request physical_case_ids are missing")
    if len(set(request_ids)) != len(request_ids):
        raise ContinuationPlanError("ROOT193 request contains duplicate case IDs")
    if not isinstance(records, list) or not records:
        raise ContinuationPlanError("ROOT193 manifest cases are missing")
    manifest_ids: list[str] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("physical_case_id"), str):
            raise ContinuationPlanError("ROOT193 manifest case row is malformed")
        manifest_ids.append(record["physical_case_id"])
    if len(set(manifest_ids)) != len(manifest_ids) or set(manifest_ids) != set(request_ids):
        raise ContinuationPlanError("ROOT193 request/manifest case sets differ")
    if manifest.get("case_count") != len(manifest_ids):
        raise ContinuationPlanError("ROOT193 manifest case_count differs")
    pending = set(request_ids)
    if root192_case_id in pending:
        raise ContinuationPlanError("ROOT193 pending group overlaps ROOT192 actual pilot")
    for case_id in pending:
        row = rows_by_id.get(case_id)
        if row is None:
            raise ContinuationPlanError(f"ROOT193 case is absent from CURRENT336: {case_id}")
        if row["historical_alias"] != "NONE" or row["audit_join"]["status"] != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            raise ContinuationPlanError(f"ROOT193 case is not an exact non-alias row: {case_id}")
        if row.get("family_id") != request.get("family_id"):
            raise ContinuationPlanError(f"ROOT193 family mismatch: {case_id}")
    return pending, {
        "status": "READY_NOTRUN",
        "actual_saved_mask_coverage": False,
        "scientific_credit": "NONE",
        "request": _small_ref(request_path, "root193_request"),
        "manifest": _small_ref(manifest_path, "root193_manifest"),
        "request_declared_attempt_id": request.get("attempt_id"),
        "manifest_declared_status": manifest.get("status"),
        "execution_evidence_supplied": False,
        "request_presence_is_not_completion": True,
        "scope": "ready request only; no execution, saved-mask, native, or physical credit",
        "case_ids": sorted(pending),
    }


def _group_rows(rows: list[dict[str, Any]], max_cases: int, max_bytes: int) -> list[dict[str, Any]]:
    if max_cases <= 0 or max_bytes <= 0:
        raise ContinuationPlanError("group limits must be positive")
    groups: list[dict[str, Any]] = []
    group_number: dict[str, int] = {}
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        family = str(row.get("family_id"))
        by_family.setdefault(family, []).append(row)
    for family in sorted(by_family):
        active: list[dict[str, Any]] = []
        active_bytes = 0
        number = 0
        for row in sorted(by_family[family], key=lambda item: (int(item["current_index"]), item["physical_case_id"])):
            size = int(row["trajectory"]["declared_bytes"])
            if active and (len(active) >= max_cases or active_bytes + size > max_bytes):
                groups.append(_group_record(family, number, active, active_bytes, max_cases, max_bytes))
                number += 1
                active, active_bytes = [], 0
            if size > max_bytes:
                groups.append(_group_record(family, number, [row], size, max_cases, max_bytes))
                number += 1
                continue
            active.append(row)
            active_bytes += size
        if active:
            groups.append(_group_record(family, number, active, active_bytes, max_cases, max_bytes))
        group_number[family] = number
    return groups


def _group_record(family: str, number: int, rows: list[dict[str, Any]], source_bytes: int, max_cases: int, max_bytes: int) -> dict[str, Any]:
    ids = [row["physical_case_id"] for row in rows]
    return {
        "group_id": f"{family}-typed-lifecycle-continuation-{number:03d}",
        "family_id": family,
        "case_ids": ids,
        "case_count": len(ids),
        "declared_source_bytes": source_bytes,
        "minimum_worker_read_bytes_if_later_authorized": source_bytes * 3,
        "limits": {"max_cases": max_cases, "max_declared_source_bytes": max_bytes},
        "within_metadata_bounds": len(ids) <= max_cases and source_bytes <= max_bytes,
        "status": "UNSCHEDULED_METADATA_ONLY",
        "launch_allowed_by_planner": False,
        "request_created": False,
        "root_guard_required": True,
        "new_attempt_identity_required": True,
        "physical_fate": "UNKNOWN",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build_plan(
    current_path: Path,
    audit_path: Path,
    output: Path,
    *,
    expected_current_sha256: str,
    expected_audit_sha256: str,
    root192_proof: Path,
    root192_summary: Path,
    root193_request: Path,
    root193_manifest: Path,
    alias_case: str | None = DEFAULT_ALIAS_CASE,
    max_cases: int = DEFAULT_MAX_CASES,
    max_group_bytes: int = DEFAULT_MAX_GROUP_BYTES,
) -> dict[str, Any]:
    current_path = _file(current_path, "CURRENT336", reject_h5=True)
    audit_path = _file(audit_path, "scientific audit verification", reject_h5=True)
    expected_current_sha256 = _sha(expected_current_sha256, "expected CURRENT SHA")
    expected_audit_sha256 = _sha(expected_audit_sha256, "expected audit SHA")
    current_sha = _sha256_file(current_path)
    audit_sha = _sha256_file(audit_path)
    if current_sha != expected_current_sha256:
        raise ContinuationPlanError(f"CURRENT SHA differs: {current_sha}")
    if audit_sha != expected_audit_sha256:
        raise ContinuationPlanError(f"audit SHA differs: {audit_sha}")
    current = _json(current_path, "CURRENT336")
    audit = _json(audit_path, "scientific audit verification")
    if current.get("schema") != CURRENT_SCHEMA or audit.get("schema") != AUDIT_SCHEMA:
        raise ContinuationPlanError("CURRENT/audit schema differs")
    rows, source_counts = base._validate_rows(current, audit, expected_current_sha256, alias_case)
    rows_by_id = {row["physical_case_id"]: row for row in rows}
    if len(rows) != 336:
        raise ContinuationPlanError("continuation requires exactly 336 CURRENT rows")
    root192_case, actual = _validate_root192(
        root192_proof,
        root192_summary,
        current_path=current_path,
        audit_path=audit_path,
        expected_current_sha256=expected_current_sha256,
        expected_audit_sha256=expected_audit_sha256,
        rows_by_id=rows_by_id,
    )
    pending_ids, pending = _validate_root193(root193_request, root193_manifest, rows_by_id=rows_by_id, root192_case_id=root192_case)
    if alias_case and alias_case not in rows_by_id:
        raise ContinuationPlanError("configured historical alias is absent from CURRENT336")
    if max_cases <= 0 or max_group_bytes <= 0:
        raise ContinuationPlanError("group limits must be positive")
    groups_rows: list[dict[str, Any]] = []
    case_records: list[dict[str, Any]] = []
    for row in rows:
        case_id = row["physical_case_id"]
        if row["historical_alias"] != "NONE":
            status = "HISTORICAL_ALIAS_UNRESOLVED"
            credit = False
            groupable = False
        elif case_id == root192_case:
            status = actual["status"]
            credit = True
            groupable = False
        elif case_id in pending_ids:
            status = pending["status"]
            credit = False
            groupable = False
        elif row["audit_join"]["status"] == "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            status = "UNSCHEDULED_EXACT_CURRENT_AUDIT"
            credit = False
            groupable = True
            groups_rows.append(row)
        else:
            status = "SOURCE_JOIN_INCOMPLETE_REQUIRES_NEW_IDENTITY"
            credit = False
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
            "actual_saved_mask_coverage": credit,
            "scientific_credit": actual["scientific_credit"] if case_id == root192_case else "NONE",
            "groupable": groupable,
            "new_attempt_identity_required": status in {"SOURCE_JOIN_INCOMPLETE_REQUIRES_NEW_IDENTITY", "UNSCHEDULED_EXACT_CURRENT_AUDIT"},
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        })
    groups = _group_rows(groups_rows, max_cases, max_group_bytes)
    group_for_case = {case_id: group["group_id"] for group in groups for case_id in group["case_ids"]}
    for record in case_records:
        if record["physical_case_id"] in group_for_case:
            record["group_id"] = group_for_case[record["physical_case_id"]]
    all_ids = [record["physical_case_id"] for record in case_records]
    grouped_ids = [case_id for group in groups for case_id in group["case_ids"]]
    if len(all_ids) != len(set(all_ids)) or len(grouped_ids) != len(set(grouped_ids)):
        raise ContinuationPlanError("continuation case IDs are duplicated")
    if set(grouped_ids) & (pending_ids | {root192_case} | ({alias_case} if alias_case else set())):
        raise ContinuationPlanError("continuation groups overlap actual, pending, or alias rows")
    plan = {
        "schema": PLAN_SCHEMA,
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "current_catalog": {"path": str(current_path), "sha256": current_sha},
        "scientific_audit": {"path": str(audit_path), "sha256": audit_sha},
        "inventory_scope": {
            "exact_current_case_count": 336,
            "case_key": "physical_case_id exact set",
            "families": sorted({str(row.get("family_id")) for row in rows}),
            "source_content_opened": False,
            "trajectory_content_hashed": False,
        },
        "evidence_bindings": {
            "root192_actual_saved_mask": actual,
            "root193_pending_request": pending,
        },
        "coverage": {
            "current_cases": len(rows),
            "exact_current_audit_rows": source_counts["exact_current_audit_metadata_joins"],
            "historical_alias_unresolved": source_counts["historical_alias_unresolved"],
            "incomplete_or_mismatched": source_counts["incomplete_or_mismatched"],
            "root192_actual_saved_mask_cases": 1,
            "root193_ready_notrun_cases": len(pending_ids),
            "remaining_exact_unscheduled_cases": len(groups_rows),
            "physical_or_scientific_credit_cases": 0,
        },
        "case_records": case_records,
        "groups": groups,
        "group_policy": {
            "max_cases_per_group": max_cases,
            "max_declared_source_bytes": max_group_bytes,
            "families_never_mixed": True,
            "remaining_groups_are_metadata_only": True,
            "request_created": False,
            "launch_allowed_by_planner": False,
            "deferred_h5_content_opened": False,
        },
        "retry_policy": {
            "missing_or_failed_case_ids": [record["physical_case_id"] for record in case_records if record["status"] == "SOURCE_JOIN_INCOMPLETE_REQUIRES_NEW_IDENTITY"],
            "failed_attempt_receipts_supplied": False,
            "failed_or_missing_cases_require_new_request_identity": True,
            "new_identity_fields": ["request_sha256", "manifest_sha256", "attempt_id", "output_root"],
            "old_request_manifest_receipt_bytes_immutable": True,
            "future_failure_is_not_completion": True,
        },
        "qualification_boundary": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "native_exit_cause": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "source_read_policy": {
            "CURRENT_audit_and_small_evidence_json_opened": True,
            "trajectory_stat_only_via_base_inventory": True,
            "trajectory_content_opened": False,
            "trajectory_content_hashed": False,
            "native_or_bi4_opened": False,
            "solver_started": False,
            "execution_request_created": False,
        },
    }
    output = output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise ContinuationPlanError(f"refusing to overwrite immutable output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(plan, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "status": plan["status"],
        "output": str(output),
        "output_sha256": _sha256_file(output),
        "remaining_exact_unscheduled_cases": len(groups_rows),
        "group_count": len(groups),
        "root193_status": pending["status"],
        "trajectory_content_opened": False,
        "trajectory_content_hashed": False,
    }


def self_test() -> dict[str, Any]:
    sample = _group_record("F1", 0, [{"physical_case_id": "A" , "current_index": 0, "trajectory": {"declared_bytes": 5}, "family_id": "F1"}], 5, 8, 20)
    if not sample["within_metadata_bounds"] or sample["launch_allowed_by_planner"]:
        raise AssertionError("group metadata boundary failed")
    return {"status": "PASS", "schema": PLAN_SCHEMA, "launch_allowed_by_planner": False, "trajectory_content_opened": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--current", required=True, type=Path)
    prepare.add_argument("--audit-verification", required=True, type=Path)
    prepare.add_argument("--expected-current-sha256", required=True)
    prepare.add_argument("--expected-audit-sha256", required=True)
    prepare.add_argument("--root192-proof", required=True, type=Path)
    prepare.add_argument("--root192-summary", required=True, type=Path)
    prepare.add_argument("--root193-request", required=True, type=Path)
    prepare.add_argument("--root193-manifest", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--historical-alias-case", default=DEFAULT_ALIAS_CASE)
    prepare.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
    prepare.add_argument("--max-group-bytes", type=int, default=DEFAULT_MAX_GROUP_BYTES)
    args = parser.parse_args(argv)
    if args.action == "self-test":
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    try:
        result = build_plan(
            args.current,
            args.audit_verification,
            args.output,
            expected_current_sha256=args.expected_current_sha256,
            expected_audit_sha256=args.expected_audit_sha256,
            root192_proof=args.root192_proof,
            root192_summary=args.root192_summary,
            root193_request=args.root193_request,
            root193_manifest=args.root193_manifest,
            alias_case=args.historical_alias_case,
            max_cases=args.max_cases,
            max_group_bytes=args.max_group_bytes,
        )
    except ContinuationPlanError as exc:
        raise SystemExit(f"ContinuationPlanError: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
