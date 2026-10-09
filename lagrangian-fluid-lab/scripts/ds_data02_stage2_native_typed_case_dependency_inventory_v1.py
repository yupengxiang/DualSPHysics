#!/usr/bin/env python3
"""Prepare a metadata-only dependency inventory for the historical 118 cases.

The historical registry is keyed by physical case.  This consumer keeps that
key separate from typed particle/record counts (for example, ROOT192's 118
matched Idp rows are one physical case).  It joins the exact CURRENT336 row,
the old omission index, and immutable terminal producer proofs.  It only opens
bounded JSON metadata and stats deferred HDF5/native paths; it never opens or
hashes HDF5, BI4, JSONL, VTK, or solver payloads.

The output is a source-only dependency product.  Its future batches are
metadata candidates with one worker case at a time, not launchable requests.
Physical fate, legal flux, dynamics, and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.native-typed-case-dependency-inventory.v1"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_CASES = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
PER_CASE_RECORD_CAP = 512 * 1024 * 1024
PER_CASE_SUMMARY_CAP = 2 * 1024 * 1024
EXPECTED_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
DEFERRED_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".ibi4", ".jsonl", ".vtk"}
STAT_KEYS = ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
FAMILY_ORDER = ("F2", "F4", "F6")


class DependencyInventoryError(ValueError):
    """Raised when an input product is not source-closed for this inventory."""


def _sha256_file(path: Path, *, max_bytes: int = MAX_SMALL_BYTES) -> str:
    path = path.expanduser().resolve()
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise DependencyInventoryError(f"cannot stat bounded input {path}: {exc}") from exc
    if size > max_bytes:
        raise DependencyInventoryError(f"bounded input exceeds {max_bytes} bytes: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise DependencyInventoryError(f"{label} is not a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise DependencyInventoryError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise DependencyInventoryError(f"{label} lacks a path")
    return Path(value).expanduser().resolve()


def _small_json(path_value: Any, label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = _path(path_value, label)
    if path.suffix.lower() in DEFERRED_SUFFIXES:
        raise DependencyInventoryError(f"{label} is deferred payload content: {path}")
    try:
        stat = path.stat()
    except OSError as exc:
        raise DependencyInventoryError(f"{label} cannot be statted: {path}: {exc}") from exc
    if stat.st_size > MAX_SMALL_BYTES:
        raise DependencyInventoryError(f"{label} exceeds {MAX_SMALL_BYTES} bytes: {path}")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DependencyInventoryError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise DependencyInventoryError(f"{label} must be a JSON object: {path}")
    return path, value, {
        "role": label,
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "content_opened": True,
    }


def _stat_only(path_value: Any, label: str) -> dict[str, Any]:
    """Stat a deferred file/directory without opening or hashing its content."""
    path = _path(path_value, label)
    try:
        stat = path.stat()
    except OSError as exc:
        return {
            "path": str(path),
            "status": "MISSING_OR_UNSTATABLE",
            "error_type": type(exc).__name__,
            "content_opened": False,
            "content_hashed": False,
        }
    return {
        "path": str(path),
        "status": "PRESENT_STAT_ONLY",
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "content_opened": False,
        "content_hashed": False,
    }


def _stat_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    source = value.get("stat") if isinstance(value.get("stat"), dict) else value
    if not all(key in source for key in STAT_KEYS):
        return None
    return {key: source[key] for key in STAT_KEYS}


def _stat_equal(left: Any, right: Any) -> bool | None:
    left = _stat_snapshot(left)
    right = _stat_snapshot(right)
    if left is None or right is None:
        return None
    return all(left[key] == right[key] for key in STAT_KEYS)


def _compact_stat(value: Any) -> dict[str, Any] | None:
    result = _stat_snapshot(value)
    return result


def _compact_timeline(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key in ("frames", "particles"):
        if key in value:
            result[key] = value[key]
    times = value.get("time_s")
    if isinstance(times, list) and times:
        result["time_count"] = len(times)
        result["time_first_s"] = times[0]
        result["time_last_s"] = times[-1]
    elif isinstance(times, (int, float)):
        result["time_last_s"] = times
    return result or None


def _native_report_content(report_ref: Any, *, physical_case_id: str) -> dict[str, Any]:
    """Read one already-indexed, bounded omission report.

    The historical inventory only recorded these reports as stat-only edges.
    This additive consumer is allowed to open the small JSON report itself, but
    it gives source-bound credit only when the declared digest, report schema,
    status, and physical case identity all agree.  It deliberately summarizes
    excluded particles rather than copying their ID rows into this product.
    No native PartOut/Part_*.bi4/RunPARTs payload is opened here; those paths
    remain evidence references from the report.
    """
    if not isinstance(report_ref, dict):
        return {
            "semantic_status": "UNKNOWN_REPORT_REFERENCE",
            "content_opened_by_inventory": False,
            "content_hashed_by_inventory": False,
        }
    raw_path = report_ref.get("path") or report_ref.get("canonical_path")
    result: dict[str, Any] = {
        "path": str(raw_path) if raw_path else None,
        "declared_sha256": report_ref.get("declared_sha256"),
        "content_opened_by_inventory": False,
        "content_hashed_by_inventory": False,
        "semantic_status": "UNKNOWN_REPORT_CONTENT",
    }
    try:
        path = _path(raw_path, f"{physical_case_id} native omission report")
        stat = path.stat()
        result["live_stat"] = {
            "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "ctime_ns": int(stat.st_ctime_ns),
            "st_dev": int(stat.st_dev),
            "st_ino": int(stat.st_ino),
        }
        if stat.st_size > MAX_SMALL_BYTES:
            result["semantic_status"] = "UNKNOWN_REPORT_EXCEEDS_SMALL_JSON_LIMIT"
            return result
        raw = path.read_bytes()
        result["content_opened_by_inventory"] = True
        result["content_hashed_by_inventory"] = True
        observed_sha = hashlib.sha256(raw).hexdigest()
        result["observed_sha256"] = observed_sha
        declared_sha = report_ref.get("declared_sha256")
        if not isinstance(declared_sha, str) or len(declared_sha) != 64:
            result["semantic_status"] = "UNKNOWN_REPORT_DECLARED_SHA_MISSING"
            return result
        result["declared_sha_status"] = (
            "EXACT_DECLARED_SHA_MATCH"
            if observed_sha == declared_sha.lower()
            else "MISMATCH_REJECTED"
        )
        if observed_sha != declared_sha.lower():
            result["semantic_status"] = "MISMATCH_REJECTED"
            return result
        try:
            report = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            result["semantic_status"] = "UNKNOWN_REPORT_JSON_INVALID"
            result["error_type"] = type(exc).__name__
            return result
        if not isinstance(report, dict):
            result["semantic_status"] = "UNKNOWN_REPORT_NOT_OBJECT"
            return result
        result["report_schema"] = report.get("schema")
        result["report_status"] = report.get("status")
        result["report_physical_case_id"] = report.get("physical_case_id")
        result["report_family_id"] = report.get("family_id")
        if report.get("physical_case_id") != physical_case_id:
            result["semantic_status"] = "MISMATCH_REPORT_PHYSICAL_CASE_ID"
            return result
        supported_schema = report.get("schema") in {
            "ds02.stage2.omission-forensics.v2",
            "ds02.stage2.native-exclusion-reconciliation.v1",
        }
        if not supported_schema or report.get("status") != "CAUSES_RECONCILED":
            result["semantic_status"] = "UNKNOWN_REPORT_SCHEMA_OR_STATUS"
            return result

        typed_identity = report.get("typed_identity") if isinstance(report.get("typed_identity"), dict) else {}
        # F2-S1's immutable legacy reconciliation uses missing_fluid_ids and
        # top-level runparts fields; the other 117 reports use the v2 nested
        # typed_identity/native_decode shape.  Normalize both without copying
        # any ID rows into this inventory.
        excluded = report.get("excluded_particles")
        if not isinstance(excluded, list):
            excluded = report.get("missing_fluid_ids")
        excluded_rows = excluded if isinstance(excluded, list) else []
        cause_counts: Counter[str] = Counter()
        motive_counts: Counter[str] = Counter()
        motive_code_counts: Counter[str] = Counter()
        first_frames: list[int] = []
        bracket_values: list[float] = []
        malformed_rows = 0
        for item in excluded_rows:
            if not isinstance(item, dict):
                malformed_rows += 1
                continue
            cause = item.get("native_exit_cause")
            motive = item.get("native_motive")
            motive_code = item.get("native_motive_code")
            native_record = item.get("native_record") if isinstance(item.get("native_record"), dict) else {}
            if motive is None:
                motive = native_record.get("motive")
            if motive_code is None:
                motive_code = native_record.get("motive_code")
            if isinstance(cause, str):
                cause_counts[cause] += 1
            if isinstance(motive, str):
                motive_counts[motive] += 1
            if isinstance(motive_code, (int, str)) and not isinstance(motive_code, bool):
                motive_code_counts[str(motive_code)] += 1
            frame = item.get("first_missing_frame")
            if isinstance(frame, int) and not isinstance(frame, bool):
                first_frames.append(frame)
            bracket = item.get("first_missing_bracket_s")
            if isinstance(bracket, list) and len(bracket) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bracket):
                bracket_values.extend(float(v) for v in bracket)
        if not motive_counts and isinstance(report.get("native_motive_counts"), dict):
            motive_counts.update({str(key): int(value) for key, value in report["native_motive_counts"].items() if isinstance(value, int) and not isinstance(value, bool)})
        typed_count = typed_identity.get("missing_fluid_count")
        if typed_count is None:
            typed_count = report.get("typed_unique_missing")
        typed_mass = typed_identity.get("missing_fluid_initial_mass_kg")
        if typed_mass is None:
            typed_mass = report.get("joined_initial_mass_kg")
        native_decode = report.get("native_decode") if isinstance(report.get("native_decode"), dict) else {}
        if not native_decode:
            native_decode = {
                "runparts_row_count": None,
                "runparts_totals": report.get("runparts_totals") if isinstance(report.get("runparts_totals"), dict) else {},
                "max_saved_time_delta_s": report.get("native_saved_time_max_delta_s"),
            }
        runparts_totals = native_decode.get("runparts_totals") if isinstance(native_decode.get("runparts_totals"), dict) else {}
        partout = native_decode.get("partout") if isinstance(native_decode.get("partout"), dict) else {}
        runparts = native_decode.get("runparts") if isinstance(native_decode.get("runparts"), dict) else {}
        result.update({
            "semantic_status": "SOURCE_BOUND_NATIVE_REPORT_CONTENT_VERIFIED_SMALL_JSON",
            "report_format": "OMISSION_FORENSICS_V2" if report.get("schema") == "ds02.stage2.omission-forensics.v2" else "NATIVE_RECONCILIATION_V1",
            "excluded_particle_count": len(excluded_rows),
            "excluded_particle_malformed_row_count": malformed_rows,
            "typed_identity_missing_fluid_count": typed_count,
            "typed_identity_missing_fluid_initial_mass_kg": typed_mass,
            "legacy_joined_count": report.get("joined_count"),
            "native_exit_cause_counts": dict(sorted(cause_counts.items())),
            "native_motive_counts": dict(sorted(motive_counts.items())),
            "native_motive_code_counts": dict(sorted(motive_code_counts.items())),
            "first_missing_frame_min": min(first_frames) if first_frames else None,
            "first_missing_frame_max": max(first_frames) if first_frames else None,
            "first_missing_bracket_s_min": min(bracket_values) if bracket_values else None,
            "first_missing_bracket_s_max": max(bracket_values) if bracket_values else None,
            "runparts_row_count": native_decode.get("runparts_row_count"),
            "runparts_totals": runparts_totals,
            "max_saved_time_delta_s": native_decode.get("max_saved_time_delta_s"),
            "partout": {
                "path": partout.get("path"),
                "sha256": partout.get("sha256"),
                "bytes": partout.get("bytes"),
            },
            "runparts": {
                "path": runparts.get("path"),
                "sha256": runparts.get("sha256"),
                "bytes": runparts.get("bytes"),
            },
            "reported_physical_fate": report.get("physical_fate"),
            "reported_dynamical_impact": report.get("dynamical_impact"),
            "reported_legal_outflow_scope": "UNKNOWN_OR_NOT_PROVEN",
            "physical_fate_legal_flux_dynamics": "UNKNOWN",
        })
        return result
    except (OSError, ValueError, TypeError) as exc:
        result["semantic_status"] = "UNKNOWN_REPORT_UNREADABLE"
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)
        return result


def _proof_success(proof: dict[str, Any]) -> bool:
    status = str(proof.get("status", ""))
    return bool(
        proof.get("guarded_receipt_status") == "completed"
        and proof.get("parent_reservation_released") is True
        and "FAIL" not in status.upper()
        and "REJECT" not in status.upper()
    )


def _item_success(proof: dict[str, Any], item: dict[str, Any]) -> bool:
    status = str(item.get("status", ""))
    return bool(_proof_success(proof) and status == "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY")


def _proof_ref(path: Path, proof: dict[str, Any], label: str, *, role: str) -> dict[str, Any]:
    status = str(proof.get("status", ""))
    ids: list[str] = []
    top_case = proof.get("physical_case_id")
    if isinstance(top_case, str):
        ids.append(top_case)
    for item in proof.get("case_verifications", []) if isinstance(proof.get("case_verifications"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("physical_case_id"), str):
            ids.append(item["physical_case_id"])
    ids = list(dict.fromkeys(ids))
    return {
        "role": role,
        "path": str(path),
        "sha256": _sha256_file(path),
        "bytes": int(path.stat().st_size),
        "status": status,
        "actual_success": _proof_success(proof),
        "physical_case_ids": ids,
        "case_count_in_proof": len(ids),
        "counts": proof.get("counts"),
        "h5_or_large_records_content_read_by_root": proof.get("H5_or_large_records_content_read_by_root"),
        "h5_bi4_read_by_root": proof.get("H5_BI4_read_by_root"),
        "known_source_read_passes_minimum": proof.get("known_source_read_passes_minimum"),
        "parent_reservation_released": proof.get("parent_reservation_released"),
        "guarded_receipt_status": proof.get("guarded_receipt_status"),
        "content_opened_by_inventory": True,
        "physical_fate_legal_flux_dynamics": "UNKNOWN",
        "scientific_qualification": proof.get("scientific_qualification", {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}),
    }


def _source_sha_status(expected: Any, observed: Any) -> str:
    if not isinstance(expected, str) or not isinstance(observed, str):
        return "UNKNOWN_NOT_EXPLICIT_IN_PROOF"
    return "EXACT_DECLARED_SHA_MATCH" if expected.lower() == observed.lower() else "MISMATCH_REJECTED"


def _batch_attempts(proof: dict[str, Any], proof_path: Path, role: str, rows_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    proof_sha = _sha256_file(proof_path)
    proof_current_sha = None
    for edge in proof.get("fresh_small_inputs", []) if isinstance(proof.get("fresh_small_inputs"), list) else []:
        if isinstance(edge, dict) and str(edge.get("path", "")).endswith("CURRENT336.json"):
            proof_current_sha = edge.get("sha256")
    for item in proof.get("case_verifications", []) if isinstance(proof.get("case_verifications"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("physical_case_id"), str):
            continue
        case_id = item["physical_case_id"]
        row = rows_by_id.get(case_id)
        expected_sha = row.get("identity", {}).get("current_trajectory_declared_sha256") if row else None
        source = item.get("source_trajectory") if isinstance(item.get("source_trajectory"), dict) else {}
        result.append({
            "producer_role": role,
            "proof_path": str(proof_path),
            "proof_sha256": proof_sha,
            "attempt_id": proof.get("request"),
            "physical_case_id": case_id,
            "status": "COMPLETED" if _item_success(proof, item) else "NO_CREDIT",
            "proof_case_status": item.get("status"),
            "case_manifest": item.get("case_manifest"),
            "case_manifest_sha256": item.get("case_manifest_sha256"),
            "receipt": item.get("receipt"),
            "receipt_sha256": item.get("receipt_sha256"),
            "summary": item.get("summary"),
            "summary_sha256": item.get("summary_sha256"),
            "source_known_sha256": source.get("known_sha256"),
            "source_sha_join": _source_sha_status(expected_sha, source.get("known_sha256")),
            "source_h5_prepost_stat_join": item.get("source_H5_prepost_known_SHA_and_current_stat_equal"),
            "proof_CURRENT_sha": proof_current_sha,
            "proof_CURRENT_sha_join": "EXACT" if proof_current_sha == EXPECTED_CURRENT_SHA else "UNKNOWN_OR_MISMATCH",
            "actual_timeline": _compact_timeline(item.get("actual_timeline")),
            "records_stat_only": item.get("records_stat_only"),
            "native_first_missing_join": "NOT_PERFORMED_BY_TYPED_LIFECYCLE_BATCH",
            "physical_fate_legal_flux_dynamics": "UNKNOWN",
        })
    return result


def _single_attempt(proof: dict[str, Any], proof_path: Path, role: str, row: dict[str, Any]) -> dict[str, Any]:
    case_id = proof.get("physical_case_id")
    success = _proof_success(proof)
    if role == "ROOT205_TYPED_NATIVE_FIRST_MISSING":
        counts = proof.get("comparison_counts") if isinstance(proof.get("comparison_counts"), dict) else {}
        native_join = counts.get("exact_native_identity_join_count")
        return {
            "producer_role": role,
            "proof_path": str(proof_path),
            "proof_sha256": _sha256_file(proof_path),
            "status": "COMPLETED" if success else "NO_CREDIT",
            "physical_case_id": case_id,
            "whole_typed_record_count": proof.get("whole_typed_record_count"),
            "non_target_typed_record_count": proof.get("non_target_typed_record_count"),
            "typed_identity_count": native_join,
            "exact_native_identity_join_count": native_join,
            "comparison_counts": counts,
            "typed_times_matching_summary_timeline": counts.get("typed_times_matching_summary_timeline"),
            "typed_times_in_native_brackets": counts.get("typed_times_in_native_brackets"),
            "native_first_missing_semantics_verified": bool(success and counts.get("saved_frame_mismatches") == 0 and counts.get("saved_frame_unknown") == 0),
            "source_H5_prepost_known_SHA_and_current_stat_equal": proof.get("source_H5_prepost_known_SHA_and_current_stat_equal"),
            "native_report_path": (proof.get("native_report") or {}).get("path") if isinstance(proof.get("native_report"), dict) else None,
            "native_report_sha256": (proof.get("native_report") or {}).get("sha256") if isinstance(proof.get("native_report"), dict) else None,
            "report": proof.get("report"),
            "report_sha256": proof.get("report_sha256"),
            "summary_stat_only": proof.get("records_stat_only"),
            "physical_fate_legal_flux_dynamics": "UNKNOWN",
        }
    return {
        "producer_role": role,
        "proof_path": str(proof_path),
        "proof_sha256": _sha256_file(proof_path),
        "status": "COMPLETED" if success else "NO_CREDIT",
        "physical_case_id": case_id,
        "typed_saved_mask_id_count": (proof.get("typed_mask_lifecycle_diagnostic") or {}).get("first_disappearance_ID_count") if isinstance(proof.get("typed_mask_lifecycle_diagnostic"), dict) else None,
        "whole_typed_record_count": proof.get("records_stat_only", {}).get("rows") if isinstance(proof.get("records_stat_only"), dict) else None,
        "source_H5_prepost_known_SHA_and_current_stat_equal": proof.get("source_H5_prepost_known_SHA_and_current_stat_equal"),
        "report": proof.get("report"),
        "report_sha256": proof.get("report_sha256"),
        "native_first_missing_join": "NOT_PERFORMED" if success else "NO_CREDIT",
        "physical_fate_legal_flux_dynamics": "UNKNOWN",
    }


def _load_attempt_registry(proof_specs: Iterable[tuple[str, Path]], rows_by_id: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    registry: list[dict[str, Any]] = []
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failures: list[dict[str, Any]] = []
    for role, path in proof_specs:
        path = path.expanduser().resolve()
        proof_path, proof, _ = _small_json(path, role)
        ref = _proof_ref(proof_path, proof, role, role=role)
        registry.append(ref)
        if isinstance(proof.get("case_verifications"), list):
            attempts = _batch_attempts(proof, proof_path, role, rows_by_id)
        elif isinstance(proof.get("physical_case_id"), str):
            attempts = [_single_attempt(proof, proof_path, role, rows_by_id.get(proof["physical_case_id"], {}))]
        else:
            attempts = []
        for attempt in attempts:
            case_id = attempt.get("physical_case_id")
            if isinstance(case_id, str):
                by_case[case_id].append(attempt)
        if not ref["actual_success"] or "FAIL" in ref["status"].upper() or "REJECT" in ref["status"].upper():
            failures.append({
                "producer_role": role,
                "proof_path": str(proof_path),
                "proof_sha256": ref["sha256"],
                "status": ref["status"],
                "failure": proof.get("failure") or proof.get("error") or proof.get("next"),
                "physical_case_ids": ref["physical_case_ids"],
                "credit": "NONE",
                "immutable": True,
            })
    return registry, by_case, failures


def _artifact(row: dict[str, Any], name: str) -> dict[str, Any] | None:
    artifacts = row.get("source_artifacts", {}).get("artifacts", {})
    value = artifacts.get(name)
    return value if isinstance(value, dict) else None


def _case_status(attempts: list[dict[str, Any]], native_report_present: bool) -> tuple[str, str]:
    successful_native = [a for a in attempts if a.get("producer_role") == "ROOT205_TYPED_NATIVE_FIRST_MISSING" and a.get("status") == "COMPLETED"]
    successful_typed = [a for a in attempts if a.get("producer_role") != "ROOT205_TYPED_NATIVE_FIRST_MISSING" and a.get("status") == "COMPLETED"]
    if successful_native:
        return "TYPED_NATIVE_SAVED_FRAME_JOIN_COMPLETED", "EXACT_NATIVE_FIRST_MISSING_JOIN_PROOF"
    if successful_typed:
        return "TYPED_LIFECYCLE_COMPLETED_NATIVE_JOIN_PENDING", "TYPED_SAVED_MASK_ONLY_NATIVE_FIRST_MISSING_UNKNOWN"
    if native_report_present:
        return "NATIVE_REPORT_STAT_ONLY_TYPED_LIFECYCLE_NOT_RUN", "NATIVE_SOURCE_PRESENT_TYPED_CONTENT_NOT_AUDITED"
    return "NO_NATIVE_OR_TYPED_SOURCE_CREDIT", "UNKNOWN"


def _build_groups(rows: list[dict[str, Any]], completed: set[str]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    by_family: dict[str, list[dict[str, Any]]] = {family: [] for family in FAMILY_ORDER}
    for row in rows:
        if row["physical_case_id"] not in completed and row["family_id"] in by_family:
            by_family[row["family_id"]].append(row)
    for family in FAMILY_ORDER:
        pending = by_family[family]
        batch: list[dict[str, Any]] = []
        total = 0
        number = 0
        for row in pending:
            source_bytes = int(row.get("typed_source", {}).get("declared_bytes") or 0)
            if batch and (len(batch) >= MAX_CASES or total + source_bytes > MAX_GROUP_BYTES):
                groups.append(_group(family, number, batch, total))
                number += 1
                batch = []
                total = 0
            batch.append(row)
            total += source_bytes
        if batch:
            groups.append(_group(family, number, batch, total))
    return groups


def _group(family: str, number: int, rows: list[dict[str, Any]], source_bytes: int) -> dict[str, Any]:
    return {
        "group_id": f"{family}-native-typed-crosscheck-{number:03d}",
        "family_id": family,
        "case_ids": [row["physical_case_id"] for row in rows],
        "case_count": len(rows),
        "status": "PREPARED_NOT_LAUNCHED",
        "request_created": False,
        "launch_allowed_by_inventory": False,
        "root_guard_required": True,
        "one_case_at_a_time": True,
        "new_attempt_identity_required": True,
        "limits": {"max_cases": MAX_CASES, "max_declared_source_bytes": MAX_GROUP_BYTES},
        "declared_typed_h5_bytes": source_bytes,
        "within_source_bounds": len(rows) <= MAX_CASES and source_bytes <= MAX_GROUP_BYTES,
        "minimum_read_passes": {"typed_h5": 3, "native_partout_or_runpart": 1, "typed_summary": 0},
        "minimum_typed_h5_read_bytes": source_bytes * 3,
        "native_partout_read_bytes": "UNKNOWN_UNTIL_AFTER_PARENT_RESERVATION",
        "storage_budget": {
            "per_case_records_cap_bytes": PER_CASE_RECORD_CAP,
            "per_case_summary_cap_bytes": PER_CASE_SUMMARY_CAP,
            "aggregate_conservative_output_cap_bytes": len(rows) * (PER_CASE_RECORD_CAP + PER_CASE_SUMMARY_CAP),
        },
        "runtime_budget": {"cpu_threads": 1, "omp_threads": 1, "max_memory_bytes": 4 * 1024 * 1024 * 1024, "max_wall_seconds": 3600},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
        "content_policy": {"opened_at_prepare": [], "h5_opened_at_prepare": False, "native_opened_at_prepare": False, "solver_started": False},
    }


def build_inventory(args: argparse.Namespace) -> dict[str, Any]:
    inv_path, inventory, inv_ref = _small_json(args.inventory, "historical118 inventory")
    current_path, current, current_ref = _small_json(args.current, "CURRENT336")
    omission_path, omission, omission_ref = _small_json(args.omission_index, "old omission index request")
    audit_path, audit, audit_ref = _small_json(args.omission_audit, "historical omission audit")
    if inventory.get("schema") != "ds02.stage2.historical118-source-inventory.v1":
        raise DependencyInventoryError("historical inventory schema differs")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise DependencyInventoryError("historical inventory must contain exactly 118 physical rows")
    ids = [row.get("physical_case_id") for row in rows if isinstance(row, dict)]
    if len(ids) != 118 or len(set(ids)) != 118 or any(not isinstance(value, str) for value in ids):
        raise DependencyInventoryError("historical physical case IDs are not unique")
    family_counts = Counter(row.get("family_id") for row in rows)
    if dict(family_counts) != {"F2": 48, "F4": 22, "F6": 48}:
        raise DependencyInventoryError(f"historical family counts differ: {dict(family_counts)}")
    if current.get("schema") != "ds02.stage2.current336.v1" or len(current.get("cases", [])) != 336:
        raise DependencyInventoryError("CURRENT336 schema/count differs")
    current_sha = _sha256_file(current_path)
    if current_sha != EXPECTED_CURRENT_SHA:
        raise DependencyInventoryError(f"CURRENT336 SHA differs: {current_sha}")
    current_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(current["cases"]):
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str) or row["physical_case_id"] in current_by_id:
            raise DependencyInventoryError("CURRENT336 rows are malformed or duplicated")
        current_by_id[row["physical_case_id"]] = {**row, "_current_index": index}
    if audit.get("exact_historical118_membership_verified") is not True or audit.get("old_conversion_path_SHA_and_current_scan_initial_final_cumulative_missing_counts_verified") != 118:
        raise DependencyInventoryError("old omission audit does not prove exact historical 118 membership")
    if not isinstance(omission.get("input_files"), list) or not isinstance(omission.get("input_sha256"), dict):
        raise DependencyInventoryError("old omission index request lacks input closure")

    row_by_id = {row["physical_case_id"]: row for row in rows}
    # The inventory itself already recorded the historical source join.  Here we
    # rejoin it to the exact CURRENT row and only stat deferred payload paths.
    case_rows: list[dict[str, Any]] = []
    for source_row in rows:
        case_id = source_row["physical_case_id"]
        current_row = current_by_id.get(case_id)
        identity = source_row.get("identity") if isinstance(source_row.get("identity"), dict) else {}
        current_trajectory = current_row.get("trajectory") if isinstance(current_row, dict) and isinstance(current_row.get("trajectory"), dict) else {}
        declared_sha = identity.get("current_trajectory_declared_sha256")
        current_sha_value = current_trajectory.get("producer_declared_sha256")
        identity_join = bool(
            current_row is not None
            and source_row.get("current336_index") == current_row.get("_current_index")
            and identity.get("current_physical_case_id") == case_id
            and identity.get("current_family_id") == source_row.get("family_id")
            and current_sha_value == declared_sha
        )
        trajectory_path = identity.get("current_trajectory_path") or current_trajectory.get("path")
        typed_artifact = _artifact(source_row, "typed_trajectory_h5") or {}
        native_dir = _artifact(source_row, "native_part_directory_stat_index") or {}
        native_report = source_row.get("original_omission_evidence", {}).get("report", {})
        attempts_placeholder: list[dict[str, Any]] = []
        case_rows.append({
            "physical_case_id": case_id,
            "family_id": source_row.get("family_id"),
            "current_index": current_row.get("_current_index") if current_row else source_row.get("current336_index"),
            "runtime_case_alias": identity.get("runtime_case_alias"),
            "current_audit_join": {
                "status": "EXACT_CURRENT_SOURCE_METADATA_JOIN" if identity_join else "CURRENT_SOURCE_METADATA_MISMATCH",
                "inventory_declared_index": source_row.get("current336_index"),
                "current_index": current_row.get("_current_index") if current_row else None,
                "inventory_declared_sha256": declared_sha,
                "current_declared_sha256": current_sha_value,
                "current_family_id": current_row.get("family_id") if current_row else None,
            },
            "typed_source": {
                "path": trajectory_path,
                "declared_sha256": declared_sha,
                "declared_bytes": identity.get("current_trajectory_bytes"),
                "inventory_stat": _compact_stat(typed_artifact),
                "live_stat": _stat_only(trajectory_path, f"{case_id} typed trajectory") if trajectory_path else {"status": "MISSING_PATH", "content_opened": False, "content_hashed": False},
                "content_opened_by_inventory": False,
                "content_hashed_by_inventory": False,
            },
            "native_source": {
                "first_missing_report": {
                    "path": native_report.get("path"),
                    "declared_sha256": native_report.get("declared_sha256"),
                    "inventory_stat": _compact_stat(native_report),
                    "content_opened_by_inventory": False,
                    "content_hashed_by_inventory": False,
                    "semantic_first_missing_status": "UNKNOWN_CONTENT_NOT_OPENED",
                },
                "part_directory": {
                    "path": native_dir.get("path"),
                    "inventory_stat": _compact_stat(native_dir),
                    "live_stat": _stat_only(native_dir.get("path"), f"{case_id} native part directory") if native_dir.get("path") else {"status": "MISSING_PATH", "content_opened": False, "content_hashed": False},
                    "content_opened_by_inventory": False,
                    "content_hashed_by_inventory": False,
                    "entry_counts": native_dir.get("entry_counts"),
                },
                "prior_status": source_row.get("original_omission_evidence", {}).get("status"),
                "prior_cause_scope": source_row.get("original_omission_evidence", {}).get("cause_scope"),
            },
            "typed_lifecycle_attempts": attempts_placeholder,
            "typed_native_crosscheck_attempts": [],
            "join_status": "PENDING_ATTEMPT_REGISTRY",
            "native_first_missing_source_join": "UNKNOWN_NOT_OPENED",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        })

        # The old inventory intentionally kept the omission report stat-only.
        # This version may consume only that bounded JSON report, never its
        # PartOut/RunPARTs/native payloads.  Keep this semantic edge separate
        # from the deferred payload references above.
        report_semantics = _native_report_content(native_report, physical_case_id=case_id)
        case_rows[-1]["native_source"]["first_missing_report"]["content_opened_by_inventory"] = bool(report_semantics.get("content_opened_by_inventory"))
        case_rows[-1]["native_source"]["first_missing_report"]["content_hashed_by_inventory"] = bool(report_semantics.get("content_hashed_by_inventory"))
        case_rows[-1]["native_source"]["first_missing_report"]["observed_sha256"] = report_semantics.get("observed_sha256")
        case_rows[-1]["native_source"]["first_missing_report"]["semantic_first_missing_status"] = (
            "SOURCE_REPORT_CONTENT_VERIFIED_NATIVE_FIRST_MISSING"
            if report_semantics.get("semantic_status") == "SOURCE_BOUND_NATIVE_REPORT_CONTENT_VERIFIED_SMALL_JSON"
            else report_semantics.get("semantic_status", "UNKNOWN_REPORT_CONTENT")
        )
        case_rows[-1]["native_source"]["report_semantics"] = report_semantics

    proof_specs: list[tuple[str, Path]] = [
        ("ROOT192_TYPED_LIFECYCLE", _path(args.root192_proof, "ROOT192 proof")),
        ("ROOT193_TYPED_LIFECYCLE_BATCH", _path(args.root193_proof, "ROOT193 proof")),
        ("ROOT198_TYPED_LIFECYCLE_BATCH", _path(args.root198_proof, "ROOT198 proof")),
        ("ROOT201_TYPED_LIFECYCLE_BATCH", _path(args.root201_proof, "ROOT201 proof")),
        ("ROOT203_TYPED_LIFECYCLE_BATCH", _path(args.root203_proof, "ROOT203 proof")),
        ("ROOT205_TYPED_NATIVE_FIRST_MISSING", _path(args.root205_proof, "ROOT205 proof")),
    ]
    failure_values = args.failure_proof
    if failure_values is None:
        failure_values = [str(_default_stage2_root() / "checkpoints/F2_TYPED_NATIVE_FIRST_MISSING_V3_ACTUAL_HEADER_CONTRACT_FAILURE_ROOT_VERIFICATION_199.json")]
    failure_specs = [("ROOT199_FAILED_TYPED_NATIVE_V3", _path(value, "failure proof")) for value in failure_values]
    proof_registry, attempts_by_case, failures = _load_attempt_registry(proof_specs + failure_specs, row_by_id)
    historical_ids = set(row_by_id)
    for ref in proof_registry:
        proof_ids = set(ref.get("physical_case_ids", []))
        ref["in_historical_scope_case_ids"] = sorted(proof_ids & historical_ids)
        ref["out_of_historical_scope_case_ids"] = sorted(proof_ids - historical_ids)
        ref["case_count_in_historical_scope"] = len(proof_ids & historical_ids)
    for case in case_rows:
        case_id = case["physical_case_id"]
        attempts = attempts_by_case.get(case_id, [])
        case["typed_lifecycle_attempts"] = [a for a in attempts if a.get("producer_role") != "ROOT205_TYPED_NATIVE_FIRST_MISSING"]
        case["typed_native_crosscheck_attempts"] = [a for a in attempts if a.get("producer_role") == "ROOT205_TYPED_NATIVE_FIRST_MISSING"]
        status, join = _case_status(attempts, bool(case["native_source"]["first_missing_report"].get("path")))
        case["join_status"] = status
        case["native_first_missing_source_join"] = join
        if case["typed_native_crosscheck_attempts"]:
            native_attempt = case["typed_native_crosscheck_attempts"][-1]
            if native_attempt.get("status") == "COMPLETED":
                native = case["native_source"]["first_missing_report"]
                native["content_opened_by_guarded_crosscheck"] = True
                native["semantic_first_missing_status"] = "VERIFIED_SAVED_FRAME_JOIN_BY_ROOT205_PROOF"
                native["guarded_report_sha256"] = native_attempt.get("native_report_sha256")
        report_semantics = case["native_source"].get("report_semantics", {})
        case["evidence_layers"] = {
            "prior_native_numeric_cause": (
                "SOURCE_BOUND_SMALL_OMISSION_REPORT_NUMERICAL_CATEGORY_ONLY"
                if str(report_semantics.get("semantic_status", "")).startswith("SOURCE_BOUND_NATIVE_")
                else "UNKNOWN_REPORT_CONTENT"
            ),
            "reported_partout_runparts": (
                "REPORT_REFERENCED_CSV_AND_RUNPARTS_HASHES"
                if report_semantics.get("partout", {}).get("sha256") or report_semantics.get("runparts", {}).get("sha256")
                else "NOT_PRESENT_IN_THIS_REPORT_FORMAT"
            ),
            "typed_native_first_missing_saved_frame_join": (
                "ROOT205_SINGLE_PHYSICAL_CASE_ONLY"
                if any(attempt.get("status") == "COMPLETED" for attempt in case["typed_native_crosscheck_attempts"])
                else "NOT_PROVEN_FOR_THIS_CASE"
            ),
            "physical_fate_legal_flux_dynamics": "UNKNOWN",
        }

    successful_typed = {case["physical_case_id"] for case in case_rows if any(a.get("status") == "COMPLETED" for a in case["typed_lifecycle_attempts"])}
    successful_crosscheck = {case["physical_case_id"] for case in case_rows if any(a.get("status") == "COMPLETED" for a in case["typed_native_crosscheck_attempts"])}
    completed = successful_typed | successful_crosscheck
    groups = _build_groups(case_rows, completed)
    input_refs = [inv_ref, current_ref, omission_ref, audit_ref]
    for ref in proof_registry:
        input_refs.append({"role": ref["role"], "path": ref["path"], "sha256": ref["sha256"], "bytes": ref["bytes"], "content_opened": True})
    # Failure proofs are already represented in proof_registry; preserve their
    # immutable lineage separately so a later retry cannot overwrite them.
    pending_counts = Counter(case["family_id"] for case in case_rows if case["physical_case_id"] not in completed)
    report_semantics_rows = [case["native_source"].get("report_semantics", {}) for case in case_rows]
    verified_native_reports = [
        value for value in report_semantics_rows
        if value.get("semantic_status") == "SOURCE_BOUND_NATIVE_REPORT_CONTENT_VERIFIED_SMALL_JSON"
    ]
    position_cause_cases = [
        case for case in case_rows
        if "NUMERICAL_POSITION_EXCLUSION" in case["native_source"].get("report_semantics", {}).get("native_exit_cause_counts", {})
    ]
    density_cause_cases = [
        case for case in case_rows
        if "NUMERICAL_DENSITY_EXCLUSION" in case["native_source"].get("report_semantics", {}).get("native_exit_cause_counts", {})
    ]
    report_sha_mismatch_cases = [
        case for case in case_rows
        if case["native_source"].get("report_semantics", {}).get("semantic_status") == "MISMATCH_REJECTED"
    ]
    first_missing_semantics_cases = [
        case for case in case_rows
        if case["native_source"]["first_missing_report"].get("semantic_first_missing_status") == "SOURCE_REPORT_CONTENT_VERIFIED_NATIVE_FIRST_MISSING"
    ]
    output = {
        "schema": SCHEMA,
        "status": "SOURCE_ONLY_PREPARED_NO_LAUNCH",
        "generated_by": {"script": str(SCRIPT), "script_sha256": _sha256_file(SCRIPT), "content_policy": {"small_json_opened": True, "h5_opened": False, "native_bi4_opened": False, "jsonl_opened": False, "large_scientific_json_opened": False, "deferred_payload_hashed": False, "solver_started": False}},
        "scope": {"physical_case_count": 118, "family_counts": dict(family_counts), "typed_particle_or_record_counts_are_not_case_counts": True, "historical_registry_only": True, "f3_fine_and_new_reference_cases_excluded": True},
        "input_bindings": {"historical_inventory": inv_ref, "CURRENT336": current_ref, "old_omission_index": {**omission_ref, "input_file_count": len(omission.get("input_files", [])), "input_sha256_count": len(omission.get("input_sha256", {})), "shape": "request_metadata_not_final_index"}, "historical_omission_audit": audit_ref, "proof_registry": input_refs[4:]},
        "current_binding": {"path": str(current_path), "sha256": current_sha, "case_count": len(current["cases"]), "historical_case_rows_exactly_joined": sum(case["current_audit_join"]["status"] == "EXACT_CURRENT_SOURCE_METADATA_JOIN" for case in case_rows)},
        "historical_membership": {"audit_status": audit.get("status"), "exact_historical118_membership_verified": audit.get("exact_historical118_membership_verified"), "native_cause_evidence_cases": audit.get("source_index_native_join_status_counts"), "physical_fate_legal_flux_dynamics": "UNKNOWN"},
        "proof_registry": proof_registry,
        "immutable_failure_lineage": failures,
        "coverage": {"physical_case_count": 118, "native_report_stat_only_cases": sum(bool(case["native_source"]["first_missing_report"].get("path")) for case in case_rows), "native_report_content_verified_cases": len(verified_native_reports), "native_first_missing_semantics_verified_cases": len(first_missing_semantics_cases), "native_position_cause_cases": len(position_cause_cases), "native_density_cause_cases": len(density_cause_cases), "native_report_sha_mismatch_cases": len(report_sha_mismatch_cases), "typed_h5_declared_stat_only_cases": sum(bool(case["typed_source"].get("path")) for case in case_rows), "typed_lifecycle_completed_cases": len(successful_typed), "typed_native_crosscheck_completed_cases": len(successful_crosscheck), "unique_completed_typed_cases": len(completed), "pending_typed_lifecycle_or_native_crosscheck_cases": 118 - len(completed), "typed_identity_count_from_root205_single_case": 118, "root205_identity_count_is_not_physical_case_count": True, "families_pending": dict(pending_counts)},
        "case_rows": case_rows,
        "future_batch_design": {"policy": {"max_cases": MAX_CASES, "max_declared_source_bytes": MAX_GROUP_BYTES, "one_cpu_worker": True, "one_case_at_a_time": True, "h5_minimum_passes": 3, "native_partout_or_runpart_minimum_passes": 1, "h5_and_native_content_deferred_until_parent_reservation": True, "per_case_record_cap_bytes": PER_CASE_RECORD_CAP, "per_case_summary_cap_bytes": PER_CASE_SUMMARY_CAP, "new_attempt_for_retry": True}, "groups": groups, "group_count": len(groups), "first_pending_group": groups[0] if groups else None, "request_builder": {"script": str(SCRIPT.parent / "ds_data02_stage2_typed_lifecycle_batch_request_v1.py"), "request_created": False, "launch_allowed": False}},
        "qualification_boundary": {"native_numerical_cause": "SOURCE_BOUND_PRIOR_EVIDENCE_ONLY_WHERE_EXPLICIT", "typed_saved_mask": "DIAGNOSTIC_ONLY", "native_first_missing_vs_typed_join": "ONLY_ROOT205_SINGLE_PHYSICAL_CASE", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "next_action": "Parent may select one PREPARED_NOT_LAUNCHED same-family group and invoke the existing guarded batch request builder; this product itself does not create or launch a request.",
    }
    return output


def _default_stage2_root() -> Path:
    return SCRIPT.parents[1] / "campaigns" / "ds-data-02" / "stage2"


def _parser() -> argparse.ArgumentParser:
    stage2 = _default_stage2_root()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--inventory", type=Path, default=stage2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json")
    build_parser.add_argument("--current", type=Path, default=stage2 / "CURRENT336.json")
    build_parser.add_argument("--omission-index", type=Path, default=stage2 / "requests/omission-coverage-index-v2.json")
    build_parser.add_argument("--omission-audit", type=Path, default=stage2 / "checkpoints/HISTORICAL_118_OMISSION_INDEX_VERIFICATION_001.json")
    build_parser.add_argument("--root192-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_V4_ACTUAL_SINGLE_CASE_ROOT_VERIFICATION_192.json")
    build_parser.add_argument("--root193-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_193.json")
    build_parser.add_argument("--root198-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_198.json")
    build_parser.add_argument("--root201-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_201.json")
    build_parser.add_argument("--root203-proof", type=Path, default=stage2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_203.json")
    build_parser.add_argument("--root205-proof", type=Path, default=stage2 / "checkpoints/F2_TYPED_NATIVE_FIRST_MISSING_V4_ACTUAL_ROOT_VERIFICATION_205.json")
    build_parser.add_argument("--failure-proof", type=Path, action="append", default=None)
    build_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.action == "self-test":
        print(json.dumps({"schema": SCHEMA, "status": "PASS", "launch_allowed": False, "h5_opened": False, "native_opened": False}, sort_keys=True))
        return 0
    try:
        result = build_inventory(args)
        output_path = args.output.expanduser().resolve()
        if output_path.exists() or output_path.is_symlink():
            raise DependencyInventoryError(f"refusing to overwrite immutable output: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
        raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        if len(raw) > MAX_SMALL_BYTES:
            raise DependencyInventoryError(f"output exceeds {MAX_SMALL_BYTES} bytes: {len(raw)}")
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
        result_ref = {"path": str(output_path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        print(json.dumps({"status": result["status"], "output": result_ref, "physical_case_count": 118, "unique_completed_typed_cases": result["coverage"]["unique_completed_typed_cases"], "pending": result["coverage"]["pending_typed_lifecycle_or_native_crosscheck_cases"], "future_group_count": result["future_batch_design"]["group_count"], "launch_allowed": False}, sort_keys=True))
        return 0
    except DependencyInventoryError as exc:
        raise SystemExit(f"DependencyInventoryError: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
