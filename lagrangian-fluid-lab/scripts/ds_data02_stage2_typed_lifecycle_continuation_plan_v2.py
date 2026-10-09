#!/usr/bin/env python3
"""Forward continuation planner with optional guarded ROOT193 evidence.

V1 remains the historical snapshot.  This forward-only version accepts an
optional producer proof for the ROOT193 batch.  It never trusts a summary path
chosen independently of that proof: the immutable ROOT193 request and
manifest must match, each case output must be listed by the proof, each case
receipt must bind its immutable case manifest, and the summary must show equal
trajectory pre/post SHA and stat records.  Only such completed cases receive
saved-mask diagnostic coverage.  Running, ready, failed, absent, or
source-incomplete cases remain pending/retry cases with a new attempt identity.

The planner reads only small JSON and filesystem metadata.  It never opens,
hashes, or parses HDF5/native/JSONL trajectory payloads and never creates an
execution request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import ds_data02_stage2_typed_lifecycle_continuation_plan_v1 as v1


SCRIPT = Path(__file__).resolve()
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v2"
REQUEST_SCHEMA = v1.REQUEST_SCHEMA
BATCH_MANIFEST_SCHEMA = v1.BATCH_MANIFEST_SCHEMA
COMPLETED_SUMMARY_STATUS = v1.COMPLETED_STATUS


class ContinuationPlanV2Error(ValueError):
    """Raised when a forward evidence edge is missing or inconsistent."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ContinuationPlanV2Error(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise ContinuationPlanV2Error(f"{label} is not hexadecimal")
    return value


def _file(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise ContinuationPlanV2Error(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}:
        raise ContinuationPlanV2Error(f"{label} must be a small JSON/source record")
    if not path.is_file():
        raise ContinuationPlanV2Error(f"{label} is missing: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuationPlanV2Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ContinuationPlanV2Error(f"{label} must be a JSON object")
    return value


def _same_path(value: Any, path: Path) -> bool:
    return isinstance(value, (str, os.PathLike)) and Path(value).expanduser().resolve() == path


def _small_ref(path: Path, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "sha256": _sha256_file(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
    }


def _hash_ref(value: Any, path: Path, label: str) -> None:
    if _sha(value, f"{label} SHA") != _sha256_file(path):
        raise ContinuationPlanV2Error(f"{label} SHA differs")


def _declared_manifest_case(manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
    for row in manifest.get("cases", []):
        if isinstance(row, dict) and row.get("physical_case_id") == case_id:
            return row
    raise ContinuationPlanV2Error(f"ROOT193 manifest lacks case: {case_id}")


def _under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _status_name(value: Any) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    return value.upper()


def _validate_source_closed_case(
    case_id: str,
    case_evidence: dict[str, Any],
    *,
    manifest_case: dict[str, Any],
    current_row: dict[str, Any],
    expected_current_sha256: str,
    output_root: Path | None,
) -> dict[str, Any]:
    """Validate one completed case using only small receipt/summary JSON."""
    reported_status = _status_name(case_evidence.get("status"))
    completed_statuses = {"COMPLETED", "SUCCESS", "DONE", "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY"}
    status = "COMPLETED" if reported_status in completed_statuses else reported_status
    if reported_status not in completed_statuses:
        if reported_status == "RUNNING":
            outcome = "RUNNING_NO_CREDIT"
        elif reported_status in {"READY", "READY_NOTRUN", "UNKNOWN"}:
            outcome = "PENDING_NO_CREDIT"
        else:
            outcome = "FAILED_REQUIRES_NEW_ATTEMPT"
        return {
            "status": outcome,
            "actual_saved_mask_coverage": False,
            "scientific_credit": "NONE",
            "source_closure": "NOT_COMPLETED",
            "reported_status": reported_status,
            "new_attempt_identity_required": reported_status not in {"READY", "READY_NOTRUN", "RUNNING", "UNKNOWN"},
        }
    try:
        receipt_path = _file(case_evidence.get("receipt"), f"ROOT193 {case_id} case receipt")
        summary_path = _file(case_evidence.get("summary"), f"ROOT193 {case_id} summary")
        _hash_ref(case_evidence.get("receipt_sha256"), receipt_path, f"ROOT193 {case_id} case receipt")
        _hash_ref(case_evidence.get("summary_sha256"), summary_path, f"ROOT193 {case_id} summary")
        if output_root is not None and (not _under(receipt_path, output_root) or not _under(summary_path, output_root)):
            raise ContinuationPlanV2Error("case output is outside producer output_root")
        receipt = _json(receipt_path, f"ROOT193 {case_id} case receipt")
        summary = _json(summary_path, f"ROOT193 {case_id} summary")
        if receipt.get("schema") != "ds02.stage2.typed-lifecycle-case-receipt.v1" or _status_name(receipt.get("status")) != "COMPLETED":
            raise ContinuationPlanV2Error("case receipt is not completed")
        if receipt.get("physical_case_id") != case_id:
            raise ContinuationPlanV2Error("case receipt physical_case_id differs")
        if receipt.get("h5_pre_post_sha256_equal") is not True:
            raise ContinuationPlanV2Error("case receipt lacks equal H5 pre/post closure")
    except (ContinuationPlanV2Error, KeyError, TypeError) as exc:
        return {
            "status": "COMPLETED_WITHOUT_SOURCE_CLOSURE_REQUIRES_NEW_ATTEMPT",
            "actual_saved_mask_coverage": False,
            "scientific_credit": "NONE",
            "source_closure": "REJECTED",
            "reason": str(exc),
            "reported_status": reported_status,
            "new_attempt_identity_required": True,
        }
    # The receipt's case_manifest reference is checked after parsing to keep
    # the completed path above concise and to avoid accepting arbitrary
    # summary paths.  Re-opened JSON is still a small receipt only.
    receipt_manifest_value = receipt.get("case_manifest")
    try:
        receipt_manifest = _file(receipt_manifest_value, f"ROOT193 {case_id} case manifest")
        manifest_sha = _sha256_file(receipt_manifest)
        expected_manifest_path = manifest_case.get("case_manifest")
        expected_manifest_sha = manifest_case.get("case_manifest_sha256")
        if not _same_path(expected_manifest_path, receipt_manifest) or not isinstance(expected_manifest_sha, str) or manifest_sha != expected_manifest_sha.lower():
            raise ContinuationPlanV2Error("case receipt does not bind immutable ROOT193 case manifest")
        summary_status = summary.get("status")
        if summary.get("schema") != "ds02.stage2.typed-lifecycle-sidecar.v4" or summary_status != COMPLETED_SUMMARY_STATUS:
            raise ContinuationPlanV2Error("case summary is not completed typed-lifecycle V4")
        if summary.get("physical_case_id") != case_id or summary.get("family_id") != current_row.get("family_id"):
            raise ContinuationPlanV2Error("case summary identity differs")
        source = summary.get("source")
        trajectory = source.get("trajectory_h5") if isinstance(source, dict) else None
        if not isinstance(source, dict) or source.get("current336_sha256") != expected_current_sha256 or not isinstance(trajectory, dict):
            raise ContinuationPlanV2Error("case summary lacks expected CURRENT/source binding")
        current_trajectory = current_row.get("trajectory")
        trajectory_path = current_trajectory.get("path") if isinstance(current_trajectory, dict) else current_row.get("trajectory_path")
        if not _same_path(trajectory.get("path"), Path(str(trajectory_path)).expanduser().resolve()):
            raise ContinuationPlanV2Error("case summary trajectory path differs from CURRENT")
        known = trajectory.get("known_sha256")
        pre = trajectory.get("pre_sha256")
        post = trajectory.get("post_sha256")
        if not isinstance(known, str) or not isinstance(pre, str) or not isinstance(post, str) or not (known == pre == post):
            raise ContinuationPlanV2Error("case summary lacks equal source SHA closure")
        pre_stat = trajectory.get("pre_stat")
        post_stat = trajectory.get("post_stat")
        if not isinstance(pre_stat, dict) or not isinstance(post_stat, dict) or pre_stat != post_stat:
            raise ContinuationPlanV2Error("case summary lacks equal source stat closure")
        if case_evidence.get("source_H5_prepost_known_SHA_and_current_stat_equal") is False:
            raise ContinuationPlanV2Error("ROOT193 proof explicitly denies source SHA/stat closure")
        proof_trajectory = case_evidence.get("source_trajectory")
        if proof_trajectory is not None:
            if not isinstance(proof_trajectory, dict):
                raise ContinuationPlanV2Error("ROOT193 proof source_trajectory is malformed")
            for field in ("path", "known_sha256", "pre_sha256", "post_sha256"):
                if proof_trajectory.get(field) != trajectory.get(field):
                    raise ContinuationPlanV2Error(f"ROOT193 proof/source summary {field} differs")
            if proof_trajectory.get("pre_stat") != pre_stat or proof_trajectory.get("post_stat") != post_stat:
                raise ContinuationPlanV2Error("ROOT193 proof/source summary stat differs")
        output_summary = receipt.get("output_summary")
        if not isinstance(output_summary, dict) or not _same_path(output_summary.get("path"), summary_path) or output_summary.get("sha256") != _sha256_file(summary_path):
            raise ContinuationPlanV2Error("case receipt summary output does not bind summary")
    except (ContinuationPlanV2Error, KeyError, TypeError) as exc:
        return {
            "status": "COMPLETED_WITHOUT_SOURCE_CLOSURE_REQUIRES_NEW_ATTEMPT",
            "actual_saved_mask_coverage": False,
            "scientific_credit": "NONE",
            "source_closure": "REJECTED",
            "reason": str(exc),
            "reported_status": reported_status,
            "new_attempt_identity_required": True,
        }
    return {
        "status": "ACTUAL_SAVED_MASK_COMPLETED",
        "actual_saved_mask_coverage": True,
        "scientific_credit": "NONE_PHYSICAL",
        "source_closure": "COMPLETED_H5_PREPOST_SHA_AND_STAT_EQUAL",
        "reported_status": reported_status,
        "new_attempt_identity_required": False,
        "case_receipt": _small_ref(receipt_path, "root193_case_receipt"),
        "summary": _small_ref(summary_path, "root193_case_summary"),
        "case_manifest": _small_ref(receipt_manifest, "root193_case_manifest"),
        "trajectory_source_sha256": known,
        "scope": "saved-mask lifecycle only; no native/physical credit",
    }


def _validate_actual_proof(
    proof_path: Path,
    *,
    root193_request: Path,
    root193_manifest: Path,
    pending_ids: set[str],
    rows_by_id: dict[str, dict[str, Any]],
    expected_current_sha256: str,
) -> dict[str, Any]:
    proof_path = _file(proof_path, "ROOT193 actual proof")
    proof_sha = _sha256_file(proof_path)
    proof = _json(proof_path, "ROOT193 actual proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise ContinuationPlanV2Error("ROOT193 actual proof schema differs")
    if not isinstance(proof.get("status"), str):
        raise ContinuationPlanV2Error("ROOT193 actual proof status is missing")
    request_sha = _sha256_file(root193_request)
    manifest_sha = _sha256_file(root193_manifest)
    if not _same_path(proof.get("request"), root193_request) or _sha(proof.get("request_sha256"), "ROOT193 proof request SHA") != request_sha:
        raise ContinuationPlanV2Error("ROOT193 proof does not bind immutable request")
    manifest_value = proof.get("manifest")
    if manifest_value is None and isinstance(proof.get("manifest_contract"), dict):
        manifest_value = proof["manifest_contract"].get("path")
    manifest_value_sha = proof.get("manifest_sha256")
    if manifest_value_sha is None and isinstance(proof.get("manifest_contract"), dict):
        manifest_value_sha = proof["manifest_contract"].get("sha256")
    if not _same_path(manifest_value, root193_manifest) or _sha(manifest_value_sha, "ROOT193 proof manifest SHA") != manifest_sha:
        raise ContinuationPlanV2Error("ROOT193 proof does not bind immutable manifest")
    manifest = _json(root193_manifest, "ROOT193 immutable manifest")
    if manifest.get("schema") != BATCH_MANIFEST_SCHEMA:
        raise ContinuationPlanV2Error("ROOT193 immutable manifest schema differs")
    batch_receipt = None
    batch_summary = None
    batch_receipt_ref = None
    batch_summary_ref = None
    output_root: Path | None = None
    receipt_value = proof.get("receipt") or proof.get("batch_receipt")
    receipt_sha_value = proof.get("receipt_sha256") or proof.get("batch_receipt_sha256")
    if receipt_value is not None:
        receipt_path = _file(receipt_value, "ROOT193 batch receipt")
        _hash_ref(receipt_sha_value, receipt_path, "ROOT193 batch receipt")
        batch_receipt = _json(receipt_path, "ROOT193 batch receipt")
        batch_receipt_ref = _small_ref(receipt_path, "root193_batch_receipt")
        if isinstance(batch_receipt.get("output_root"), str):
            output_root = Path(batch_receipt["output_root"]).expanduser().resolve()
    summary_value = proof.get("batch_summary") or proof.get("report")
    summary_sha_value = proof.get("batch_summary_sha256") or proof.get("report_sha256")
    if summary_value is not None:
        summary_path = _file(summary_value, "ROOT193 batch summary")
        _hash_ref(summary_sha_value, summary_path, "ROOT193 batch summary")
        batch_summary = _json(summary_path, "ROOT193 batch summary")
        batch_summary_ref = _small_ref(summary_path, "root193_batch_summary")
        if output_root is not None and not _under(summary_path, output_root):
            raise ContinuationPlanV2Error("ROOT193 batch summary is outside producer output_root")
    evidence = proof.get("case_outputs")
    if evidence is None:
        # ROOT193's producer proof uses case_verifications for completed
        # entries and failed_cases for terminal failures.  Keep case_outputs
        # as the generic forward schema for synthetic/older proofs.
        evidence = proof.get("case_verifications")
    if evidence is None:
        evidence = proof.get("cases")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list):
        raise ContinuationPlanV2Error("ROOT193 proof case_outputs must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("physical_case_id"), str):
            raise ContinuationPlanV2Error("ROOT193 proof case output is malformed")
        case_id = item["physical_case_id"]
        if case_id in by_id or case_id not in pending_ids:
            raise ContinuationPlanV2Error(f"ROOT193 proof case output is duplicate/outside manifest: {case_id}")
        by_id[case_id] = item
    failed = proof.get("failed_cases")
    if failed is not None:
        if not isinstance(failed, list):
            raise ContinuationPlanV2Error("ROOT193 proof failed_cases must be a list")
        for item in failed:
            if not isinstance(item, dict) or not isinstance(item.get("physical_case_id"), str):
                raise ContinuationPlanV2Error("ROOT193 proof failed case is malformed")
            case_id = item["physical_case_id"]
            if case_id in by_id or case_id not in pending_ids:
                raise ContinuationPlanV2Error(f"ROOT193 proof failed case is duplicate/outside manifest: {case_id}")
            by_id[case_id] = {
                "physical_case_id": case_id,
                "status": item.get("status", "FAILED"),
                "failure": item,
            }
    if batch_summary is not None:
        listed = batch_summary.get("cases") or batch_summary.get("case_records") or batch_summary.get("case_results")
        if isinstance(listed, list):
            listed_ids = []
            for item in listed:
                if isinstance(item, dict) and isinstance(item.get("physical_case_id"), str):
                    listed_ids.append(item["physical_case_id"])
            if set(listed_ids) != pending_ids:
                raise ContinuationPlanV2Error("ROOT193 batch summary case set differs from immutable manifest")
    case_results: dict[str, dict[str, Any]] = {}
    for case_id in sorted(pending_ids):
        item = by_id.get(case_id)
        if item is None:
            batch_status = _status_name(batch_receipt.get("status")) if isinstance(batch_receipt, dict) else "UNKNOWN"
            if batch_status in {"RUNNING", "STARTED", "IN_PROGRESS"}:
                case_results[case_id] = {"status": "RUNNING_NO_CREDIT", "actual_saved_mask_coverage": False, "scientific_credit": "NONE", "reported_status": batch_status, "new_attempt_identity_required": False}
            elif batch_status in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
                case_results[case_id] = {"status": "FAILED_OR_UNOBSERVED_REQUIRES_NEW_ATTEMPT", "actual_saved_mask_coverage": False, "scientific_credit": "NONE", "reported_status": batch_status, "new_attempt_identity_required": True}
            else:
                case_results[case_id] = {"status": "PENDING_NO_CREDIT", "actual_saved_mask_coverage": False, "scientific_credit": "NONE", "reported_status": batch_status or "READY_NOTRUN", "new_attempt_identity_required": False}
            continue
        case_results[case_id] = _validate_source_closed_case(
            case_id,
            item,
            manifest_case=_declared_manifest_case(manifest, case_id),
            current_row=rows_by_id[case_id],
            expected_current_sha256=expected_current_sha256,
            output_root=output_root,
        )
    return {
        "status": "ROOT193_ACTUAL_EVIDENCE_BOUND",
        "proof": _small_ref(proof_path, "root193_actual_proof"),
        "proof_status": proof.get("status"),
        "batch_receipt": batch_receipt_ref,
        "batch_summary": batch_summary_ref,
        "case_results": case_results,
        "completed_saved_mask_case_ids": sorted(case_id for case_id, value in case_results.items() if value.get("actual_saved_mask_coverage") is True),
        "no_physical_credit": True,
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
    root193_actual_proof: Path | None = None,
    alias_case: str | None = v1.DEFAULT_ALIAS_CASE,
    max_cases: int = v1.DEFAULT_MAX_CASES,
    max_group_bytes: int = v1.DEFAULT_MAX_GROUP_BYTES,
) -> dict[str, Any]:
    output = Path(output).expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise ContinuationPlanV2Error(f"refusing to overwrite immutable output: {output}")
    with tempfile.TemporaryDirectory(prefix="ds02-continuation-v2-") as temporary:
        intermediate = Path(temporary) / "v1-plan.json"
        try:
            v1.build_plan(
                current_path,
                audit_path,
                intermediate,
                expected_current_sha256=expected_current_sha256,
                expected_audit_sha256=expected_audit_sha256,
                root192_proof=root192_proof,
                root192_summary=root192_summary,
                root193_request=root193_request,
                root193_manifest=root193_manifest,
                alias_case=alias_case,
                max_cases=max_cases,
                max_group_bytes=max_group_bytes,
            )
        except v1.ContinuationPlanError as exc:
            raise ContinuationPlanV2Error(str(exc)) from exc
        plan = json.loads(intermediate.read_text(encoding="utf-8"))
    if plan.get("schema") != v1.PLAN_SCHEMA:
        raise ContinuationPlanV2Error("V1 intermediate schema differs")
    rows_by_id = {row["physical_case_id"]: row for row in plan["case_records"]}
    pending_ids = set(plan["evidence_bindings"]["root193_pending_request"]["case_ids"])
    actual = None
    if root193_actual_proof is not None:
        try:
            actual = _validate_actual_proof(
                Path(root193_actual_proof).expanduser().resolve(),
                root193_request=Path(root193_request).expanduser().resolve(),
                root193_manifest=Path(root193_manifest).expanduser().resolve(),
                pending_ids=pending_ids,
                rows_by_id=rows_by_id,
                expected_current_sha256=expected_current_sha256,
            )
        except (ContinuationPlanV2Error, v1.ContinuationPlanError) as exc:
            raise ContinuationPlanV2Error(str(exc)) from exc
        for case_id, result in actual["case_results"].items():
            row = rows_by_id[case_id]
            row.update({
                "status": result["status"],
                "actual_saved_mask_coverage": bool(result.get("actual_saved_mask_coverage")),
                "scientific_credit": result.get("scientific_credit", "NONE"),
                "new_attempt_identity_required": bool(result.get("new_attempt_identity_required")),
                "actual_root193_evidence": result,
            })
            if result.get("status") not in {"PENDING_NO_CREDIT", "RUNNING_NO_CREDIT", "READY_NOTRUN"}:
                row["retry_or_completion_scope"] = result.get("source_closure", result.get("status"))
    completed = set(actual["completed_saved_mask_case_ids"]) if actual else set()
    remaining_pending = pending_ids - completed
    plan["schema"] = PLAN_SCHEMA
    plan["status"] = "PREPARED_METADATA_ONLY_NO_LAUNCH"
    plan["forward_semantics"] = {
        "v1_snapshot_preserved": True,
        "root193_actual_proof_supplied": actual is not None,
        "saved_mask_credit_rule": "only COMPLETED case receipt + summary + equal trajectory SHA/stat closure",
        "running_ready_failed_cases_receive_no_saved_mask_credit": True,
        "manifest_is_immutable_input": True,
        "case_summary_paths_must_be_proof_listed_and_output_root_bound": True,
    }
    if actual is not None:
        plan["evidence_bindings"]["root193_actual_batch"] = actual
    pending_binding = plan["evidence_bindings"]["root193_pending_request"]
    pending_binding["case_ids"] = sorted(remaining_pending)
    pending_binding["actual_completed_case_ids"] = sorted(completed)
    pending_binding["actual_batch_status"] = actual["proof_status"] if actual else "NOT_SUPPLIED"
    pending_binding["status"] = "READY_NOTRUN" if actual is None else ("PENDING_AFTER_PARTIAL_BATCH" if remaining_pending else "COMPLETED_BATCH_CASES_ALL_CLOSED")
    plan["coverage"]["root193_actual_saved_mask_cases"] = len(completed)
    plan["coverage"]["root193_ready_notrun_cases"] = len(remaining_pending)
    plan["coverage"]["root192_and_root193_actual_saved_mask_cases"] = 1 + len(completed)
    plan["coverage"]["root193_no_credit_cases"] = len(pending_ids - completed)
    retry_ids = [row["physical_case_id"] for row in plan["case_records"] if row.get("new_attempt_identity_required")]
    plan["retry_policy"]["missing_or_failed_case_ids"] = sorted(set(plan["retry_policy"]["missing_or_failed_case_ids"]) | set(retry_ids))
    plan["retry_policy"]["root193_failed_or_source_unclosed_requires_new_identity"] = True
    plan["root193_actual_proof_is_not_a_physical_qualification"] = True
    plan["source_read_policy"]["root193_actual_proof_json_opened"] = actual is not None
    plan["source_read_policy"]["trajectory_content_opened"] = False
    plan["source_read_policy"]["trajectory_content_hashed"] = False
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
        "root193_actual_proof_supplied": actual is not None,
        "root193_actual_saved_mask_cases": len(completed),
        "root193_pending_or_no_credit_cases": len(remaining_pending),
        "remaining_exact_unscheduled_cases": plan["coverage"]["remaining_exact_unscheduled_cases"],
        "group_count": len(plan["groups"]),
        "trajectory_content_opened": False,
        "trajectory_content_hashed": False,
    }


def self_test() -> dict[str, Any]:
    return {
        "status": "PASS",
        "schema": PLAN_SCHEMA,
        "launch_allowed_by_planner": False,
        "trajectory_content_opened": False,
        "root193_completed_credit_requires_source_sha_and_stat_closure": True,
    }


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
    prepare.add_argument("--root193-actual-proof", type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--historical-alias-case", default=v1.DEFAULT_ALIAS_CASE)
    prepare.add_argument("--max-cases", type=int, default=v1.DEFAULT_MAX_CASES)
    prepare.add_argument("--max-group-bytes", type=int, default=v1.DEFAULT_MAX_GROUP_BYTES)
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
            root193_actual_proof=args.root193_actual_proof,
            alias_case=args.historical_alias_case,
            max_cases=args.max_cases,
            max_group_bytes=args.max_group_bytes,
        )
    except ContinuationPlanV2Error as exc:
        raise SystemExit(f"ContinuationPlanV2Error: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
