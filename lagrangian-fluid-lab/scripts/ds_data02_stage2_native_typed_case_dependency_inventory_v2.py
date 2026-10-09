#!/usr/bin/env python3
"""Refine native-cause scope for the historical 118-case dependency product.

V1 deliberately summarized every bounded omission report, which made a
report-level position/density category easy to confuse with the historical
index's narrower per-fluid-ID native-cause credit.  This additive consumer
joins V1 to the immutable historical coverage index and emits an explicit
scope for each physical case:

* ``NATIVE_CAUSE_BOUND_PER_FLUID_ID`` only when the historical index says the
  exact missing-fluid IDs joined and the compact report counts agree;
* ``CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN`` when a completed scan has a
  report-level category or RunPARTs statistic without that ID-level credit;
* ``SCAN_COMPLETED_NO_NATIVE_TARGETS`` for an empty report (a manufactured
  counterexample is covered by the tests); and
* ``UNKNOWN_SOURCE_OR_IDENTITY`` when the scan/report contract is incomplete.

The product reads only bounded JSON metadata, never H5/native/BI4 payloads,
and retains physical fate, legal flux, dynamics, and QI/QN/QE as UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.native-typed-case-dependency-inventory.v2"
V1_SCHEMA = "ds02.stage2.native-typed-case-dependency-inventory.v1"
INDEX_SCHEMA = "ds02.stage2.omission-coverage-index.v1"
MAX_SMALL_BYTES = 10 * 1024 * 1024
EXPECTED_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
EXPECTED_AUDIT_SHA = "541f7d695a63a2e9c34a13a1cae68d2252d14221c7398e0c418c1b10f5d99931"
EXPECTED_INDEX_SHA = "8d0f99c1ae72fcae236bdadef80bd9d431e951b0d15b05e0f041c3d694048dae"


class ScopeRefinementError(ValueError):
    """Raised when the immutable scope inputs do not join exactly."""


def _sha256(path: Path) -> str:
    path = path.expanduser().resolve()
    stat = path.stat()
    if stat.st_size > MAX_SMALL_BYTES:
        raise ScopeRefinementError(f"bounded JSON exceeds {MAX_SMALL_BYTES} bytes: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path_value: Any, label: str) -> tuple[Path, dict[str, Any], str]:
    if not isinstance(path_value, (str, os.PathLike)) or not path_value:
        raise ScopeRefinementError(f"{label} lacks a path")
    path = Path(path_value).expanduser().resolve()
    if path.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".ibi4", ".jsonl", ".vtk"}:
        raise ScopeRefinementError(f"{label} is deferred payload content: {path}")
    try:
        stat = path.stat()
        if stat.st_size > MAX_SMALL_BYTES:
            raise ScopeRefinementError(f"{label} exceeds bounded size: {path}")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScopeRefinementError(f"{label} is not readable bounded JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ScopeRefinementError(f"{label} must be a JSON object: {path}")
    return path, value, hashlib.sha256(raw).hexdigest()


def _verified_report_semantics(case_row: dict[str, Any]) -> dict[str, Any]:
    native = case_row.get("native_source") if isinstance(case_row.get("native_source"), dict) else {}
    semantics = native.get("report_semantics")
    return semantics if isinstance(semantics, dict) else {}


def _scan_completed(old_row: dict[str, Any]) -> bool | None:
    current_scan = old_row.get("current_scan", {})
    if not isinstance(current_scan, dict):
        return None
    status = current_scan.get("scan_status")
    return True if status == "SCANNED" else (False if isinstance(status, str) else None)


def classify_case(case_row: dict[str, Any], old_row: dict[str, Any]) -> dict[str, Any]:
    """Classify one physical case without promoting report counts to ID credit."""
    semantics = _verified_report_semantics(case_row)
    semantic_status = semantics.get("semantic_status")
    report_verified = isinstance(semantic_status, str) and semantic_status.startswith("SOURCE_BOUND_NATIVE_")
    scan_completed = _scan_completed(old_row)
    cause = old_row.get("cause") if isinstance(old_row.get("cause"), dict) else {}
    history_cause = cause.get("history_cause")
    ids_match = cause.get("ids_match_scan") is True
    joined_count = cause.get("joined_count")
    excluded_count = semantics.get("excluded_particle_count")
    typed_count = semantics.get("typed_identity_missing_fluid_count")
    cause_counts = semantics.get("native_exit_cause_counts") if isinstance(semantics.get("native_exit_cause_counts"), dict) else {}
    runparts = semantics.get("runparts_totals") if isinstance(semantics.get("runparts_totals"), dict) else {}
    report_category_observed = bool(cause_counts) or any(isinstance(value, (int, float)) and value > 0 for value in runparts.values())
    strict_id_join = bool(
        report_verified
        and history_cause == "NATIVE_NUMERICAL_EXCLUSION_RECONCILED"
        and ids_match
        and isinstance(joined_count, int)
        and isinstance(excluded_count, int)
        and isinstance(typed_count, int)
        and joined_count > 0
        and joined_count == excluded_count == typed_count
    )
    if strict_id_join:
        classification = "NATIVE_CAUSE_BOUND_PER_FLUID_ID"
        category_scope = "PER_FLUID_ID_NATIVE_NUMERICAL_CAUSE"
        credit_reason = "HISTORICAL_INDEX_IDS_MATCH_SCAN_AND_COMPACT_REPORT_COUNTS_AGREE"
    elif scan_completed is True and report_verified and not report_category_observed and (excluded_count in (0, None) and typed_count in (0, None)):
        classification = "SCAN_COMPLETED_NO_NATIVE_TARGETS"
        category_scope = "NO_NATIVE_TARGETS_OBSERVED"
        credit_reason = "EMPTY_REPORT_OR_ZERO_RUNPARTS_DOES_NOT_IDENTIFY_A_MISSING_FLUID"
    elif scan_completed is True and report_verified and report_category_observed:
        classification = "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN"
        category_scope = "NATIVE_REPORT_CATEGORY_OR_RUNPARTS_STAT_ONLY_UNRESOLVED"
        credit_reason = "REPORT_LEVEL_CATEGORY_PRESENT_BUT_HISTORICAL_FLUID_ID_JOIN_NOT_CREDITED"
    elif scan_completed is True and report_verified:
        classification = "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN"
        category_scope = "REPORT_CONTENT_PRESENT_BUT_NO_TARGET_ID_JOIN"
        credit_reason = "COMPLETED_SCAN_WITHOUT_SOURCE_BOUND_FLUID_ID_CAUSE"
    else:
        classification = "UNKNOWN_SOURCE_OR_IDENTITY"
        category_scope = "UNKNOWN"
        credit_reason = "REQUIRED_SCAN_OR_REPORT_SOURCE_CONTRACT_UNAVAILABLE"
    typed_join = case_row.get("evidence_layers", {}).get("typed_native_first_missing_saved_frame_join") if isinstance(case_row.get("evidence_layers"), dict) else None
    return {
        "physical_case_id": case_row.get("physical_case_id"),
        "family_id": case_row.get("family_id"),
        "classification": classification,
        "reported_native_category_scope": category_scope,
        "credit_reason": credit_reason,
        "historical_history_cause": history_cause,
        "historical_ids_match_scan": ids_match,
        "historical_joined_count": joined_count,
        "scan_completed": scan_completed,
        "report_content_verified": report_verified,
        "report_semantic_status": semantic_status,
        "report_excluded_particle_count": excluded_count,
        "report_typed_missing_fluid_count": typed_count,
        "report_native_exit_cause_counts": dict(sorted(cause_counts.items())),
        "report_runparts_totals": dict(sorted(runparts.items())),
        "report_category_observed": report_category_observed,
        "typed_native_first_missing_join_scope": typed_join or "NOT_PROVEN_FOR_THIS_CASE",
        "physical_fate_legal_flux_dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    v1_path, v1, v1_sha = _read_json(args.inventory_v1, "V1 dependency inventory")
    audit_path, audit, audit_sha = _read_json(args.omission_audit, "historical omission audit")
    index_path, index, index_sha = _read_json(args.historical_index, "historical omission coverage index")
    if v1.get("schema") != V1_SCHEMA or v1.get("status") != "SOURCE_ONLY_PREPARED_NO_LAUNCH":
        raise ScopeRefinementError("V1 inventory schema/status is not the immutable source-only product")
    if v1.get("current_binding", {}).get("sha256") != EXPECTED_CURRENT_SHA:
        raise ScopeRefinementError("V1 does not bind the expected CURRENT336 SHA")
    if audit.get("schema") != "ds02.stage2.historical-omission-index-independent-verification.v1":
        raise ScopeRefinementError("historical omission audit schema differs")
    if audit_sha != EXPECTED_AUDIT_SHA:
        raise ScopeRefinementError(f"historical omission audit SHA differs: {audit_sha}")
    if index.get("schema") != INDEX_SCHEMA or index_sha != EXPECTED_INDEX_SHA:
        raise ScopeRefinementError(f"historical coverage index schema/SHA differs: {index.get('schema')} {index_sha}")
    case_rows = v1.get("case_rows")
    old_rows = index.get("rows")
    if not isinstance(case_rows, list) or len(case_rows) != 118 or not isinstance(old_rows, list) or len(old_rows) != 118:
        raise ScopeRefinementError("both V1 and historical index must contain exactly 118 physical rows")
    v1_by_id = {row.get("physical_case_id"): row for row in case_rows if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str)}
    old_by_id = {row.get("physical_case_id"): row for row in old_rows if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str)}
    if len(v1_by_id) != 118 or len(old_by_id) != 118 or set(v1_by_id) != set(old_by_id):
        raise ScopeRefinementError("V1 and historical index physical case keys differ")
    expected_audit_counts = {
        "F2": {"NATIVE_CAUSE_RECONCILED": 48},
        "F4": {"NATIVE_CAUSE_RECONCILED": 3, "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN": 19},
        "F6": {"NATIVE_CAUSE_RECONCILED": 2, "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN": 46},
    }
    if audit.get("source_index_native_join_status_counts") != expected_audit_counts:
        raise ScopeRefinementError("historical audit cause scope counts changed")

    rows: list[dict[str, Any]] = []
    for physical_case_id in sorted(v1_by_id, key=lambda value: (str(v1_by_id[value].get("family_id")), value)):
        case_row = v1_by_id[physical_case_id]
        old_row = old_by_id[physical_case_id]
        classification = classify_case(case_row, old_row)
        rows.append(classification)
    classification_counts = Counter(row["classification"] for row in rows)
    scope_counts = Counter(row["reported_native_category_scope"] for row in rows)
    family_classification: dict[str, dict[str, int]] = {}
    for family in ("F2", "F4", "F6"):
        family_classification[family] = dict(Counter(row["classification"] for row in rows if row["family_id"] == family))
    input_refs = [
        {"role": "V1_dependency_inventory", "path": str(v1_path), "sha256": v1_sha, "bytes": int(v1_path.stat().st_size), "content_opened": True},
        {"role": "historical_omission_audit", "path": str(audit_path), "sha256": audit_sha, "bytes": int(audit_path.stat().st_size), "content_opened": True},
        {"role": "historical_omission_coverage_index", "path": str(index_path), "sha256": index_sha, "bytes": int(index_path.stat().st_size), "content_opened": True},
    ]
    return {
        "schema": SCHEMA,
        "status": "SOURCE_ONLY_SCOPE_REFINED_NO_LAUNCH",
        "generated_by": {"script": str(SCRIPT), "script_sha256": _sha256(SCRIPT), "content_policy": {"bounded_json_opened": True, "h5_opened": False, "native_bi4_opened": False, "jsonl_opened": False, "solver_started": False}},
        "scope": {"physical_case_count": 118, "family_counts": {"F2": 48, "F4": 22, "F6": 48}, "typed_identity_counts_are_not_physical_case_counts": True, "new_reference_cases_excluded": True},
        "input_bindings": input_refs,
        "classification_counts": dict(sorted(classification_counts.items())),
        "reported_category_scope_counts": dict(sorted(scope_counts.items())),
        "family_classification_counts": family_classification,
        "coverage": {
            "native_report_category_observed_cases": sum(row["report_category_observed"] for row in rows),
            "native_cause_bound_per_fluid_id_cases": classification_counts.get("NATIVE_CAUSE_BOUND_PER_FLUID_ID", 0),
            "cause_not_located_after_completed_scan_cases": classification_counts.get("CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN", 0),
            "scan_completed_no_native_targets_cases": classification_counts.get("SCAN_COMPLETED_NO_NATIVE_TARGETS", 0),
            "unknown_source_or_identity_cases": classification_counts.get("UNKNOWN_SOURCE_OR_IDENTITY", 0),
            "root205_typed_native_join_cases": sum(row["typed_native_first_missing_join_scope"] == "ROOT205_SINGLE_PHYSICAL_CASE_ONLY" for row in rows),
            "physical_fate_legal_flux_dynamics_unknown_cases": 118,
            "QI_QN_QE_unknown_cases": 118,
        },
        "case_rows": rows,
        "qualification_boundary": {
            "native_cause": "Only NATIVE_CAUSE_BOUND_PER_FLUID_ID has historical source-bound numeric-cause credit; report-level category counts remain diagnostic.",
            "typed_native_first_missing": "ROOT205 single physical case only; no expansion to 118 physical cases.",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "next_action": "The 65 CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN cases require new source-bound native ID joins; no category count or RunPARTs total grants that credit.",
    }


def _default_stage2_root() -> Path:
    return SCRIPT.parents[1] / "campaigns" / "ds-data-02" / "stage2"


def _parser() -> argparse.ArgumentParser:
    stage2 = _default_stage2_root()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--inventory-v1", type=Path, required=True)
    build_parser.add_argument("--omission-audit", type=Path, default=stage2 / "checkpoints/HISTORICAL_118_OMISSION_INDEX_VERIFICATION_001.json")
    build_parser.add_argument("--historical-index", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "self-test":
        print(json.dumps({"schema": SCHEMA, "status": "PASS", "launch_allowed": False, "payload_opened": False, "checks": ["strict_scope_categories", "physical_case_key_join"]}, sort_keys=True))
        return 0
    try:
        result = build(args)
        output_path = args.output.expanduser().resolve()
        if output_path.exists() or output_path.is_symlink():
            raise ScopeRefinementError(f"refusing to overwrite immutable output: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        if len(raw) > MAX_SMALL_BYTES:
            raise ScopeRefinementError(f"output exceeds bounded size: {len(raw)}")
        temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
        print(json.dumps({"status": result["status"], "output": {"path": str(output_path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}, "coverage": result["coverage"], "launch_allowed": False}, sort_keys=True))
        return 0
    except ScopeRefinementError as exc:
        raise SystemExit(f"ScopeRefinementError: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
