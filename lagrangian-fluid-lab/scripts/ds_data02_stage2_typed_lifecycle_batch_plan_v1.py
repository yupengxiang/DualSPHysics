#!/usr/bin/env python3
"""Metadata-only planner for future typed-lifecycle CURRENT336 batches.

This planner reads CURRENT336 and the completed scientific-audit JSON, then
stats each declared trajectory path.  It never opens or hashes a trajectory
HDF5/native file and it never creates a launch request.  The output is a
source-join inventory and an adaptive family/size grouping for a later
root-owned guarded request.

The producer-declared trajectory SHA is retained as a declaration.  An
observed trajectory content SHA is deliberately ``UNKNOWN`` until a worker
after reservation performs its own pre/stream/post checks.  Qualification,
attempt remaining, and hard-limit accounting remain root-owned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
AUDIT_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-batch-plan.v1"
DEFAULT_ALIAS_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
DEFAULT_PASSES = 3
DEFAULT_MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_MAX_GROUP_CASES = 8


class PlanError(ValueError):
    """Raised for an incomplete or mismatched source inventory."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PlanError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise PlanError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise PlanError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise PlanError(f"{label} is missing: {path}")
    return path


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be a JSON object")
    return value


def _stat(path_value: Any, label: str) -> dict[str, Any]:
    if not isinstance(path_value, (str, os.PathLike)) or not path_value:
        return {"status": "MISSING_PATH", "path": str(path_value) if path_value else None}
    declared = Path(path_value).expanduser()
    resolved = declared.resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        return {
            "status": "STAT_FAILED",
            "path": str(declared),
            "resolved_path": str(resolved),
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not resolved.is_file():
        return {"status": "NOT_A_FILE", "path": str(declared), "resolved_path": str(resolved)}
    return {
        "status": "STAT_ONLY",
        "path": str(declared),
        "resolved_path": str(resolved),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "content_sha256": "UNKNOWN_UNTIL_GUARDED_WORKER",
        "content_opened": False,
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise PlanError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_rows(current: dict[str, Any], audit: dict[str, Any], expected_current_sha: str, alias_case: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise PlanError("CURRENT schema differs")
    if audit.get("schema") != AUDIT_SCHEMA:
        raise PlanError("scientific audit schema differs")
    cases = current.get("cases")
    verified = audit.get("verified_cases")
    if not isinstance(cases, list) or not isinstance(verified, list):
        raise PlanError("CURRENT/audit case arrays are missing")
    if len(cases) != 336 or len(verified) != 336:
        raise PlanError(f"expected exact 336 rows, got CURRENT={len(cases)} audit={len(verified)}")
    current_catalog = audit.get("current_catalog")
    if not isinstance(current_catalog, dict) or _sha(current_catalog.get("sha256"), "audit CURRENT SHA") != expected_current_sha:
        raise PlanError("audit does not bind the expected CURRENT SHA")
    current_by_id: dict[str, dict[str, Any]] = {}
    audit_by_id: dict[str, dict[str, Any]] = {}
    for row in cases:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise PlanError("malformed CURRENT case")
        key = row["physical_case_id"]
        if key in current_by_id:
            raise PlanError(f"duplicate CURRENT case: {key}")
        current_by_id[key] = row
    for row in verified:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise PlanError("malformed audit case")
        key = row["physical_case_id"]
        if key in audit_by_id:
            raise PlanError(f"duplicate audit case: {key}")
        audit_by_id[key] = row
    if set(current_by_id) != set(audit_by_id):
        raise PlanError("CURRENT and audit case key sets differ")
    rows: list[dict[str, Any]] = []
    for index, (case_id, current_row) in enumerate(current_by_id.items()):
        audit_row = audit_by_id[case_id]
        trajectory = current_row.get("trajectory")
        if not isinstance(trajectory, dict):
            raise PlanError(f"{case_id}: trajectory metadata missing")
        trajectory_path = trajectory.get("path")
        current_sha = _sha(trajectory.get("producer_declared_sha256"), f"{case_id} producer trajectory SHA")
        audit_sha = audit_row.get("trajectory_verified_sha256")
        audit_path = audit_row.get("trajectory")
        path_match = isinstance(audit_path, str) and Path(audit_path).expanduser().resolve() == Path(str(trajectory_path)).expanduser().resolve()
        sha_match = isinstance(audit_sha, str) and audit_sha.lower() == current_sha
        stat = _stat(trajectory_path, f"{case_id} trajectory")
        bytes_declared = int(trajectory.get("bytes", -1))
        bytes_match = stat.get("status") == "STAT_ONLY" and int(stat["bytes"]) == bytes_declared
        audit_clean = audit_row.get("scan_status") == "SCANNED" and audit_row.get("field_failures") == [] and audit_row.get("exact_CURRENT_path_and_declared_sha_match") is True
        scan_path = audit_row.get("scan")
        receipt_path = audit_row.get("receipt")
        scan_sha = audit_row.get("scan_sha256")
        receipt_sha = audit_row.get("receipt_sha256")
        scan_edges = isinstance(scan_path, str) and isinstance(scan_sha, str) and len(scan_sha) == 64
        receipt_edges = isinstance(receipt_path, str) and isinstance(receipt_sha, str) and len(receipt_sha) == 64
        exact_join = bool(path_match and sha_match and bytes_match and audit_clean and scan_edges and receipt_edges)
        alias_status = "NONE"
        if alias_case is not None and case_id == alias_case:
            alias_status = "HISTORICAL_ALIAS_REVIEW_REQUIRED"
        source_join_status = "EXACT_CURRENT_AUDIT_METADATA_JOIN" if exact_join else "INCOMPLETE_OR_MISMATCHED"
        if alias_status != "NONE":
            source_join_status = "SEPARATE_HISTORICAL_ALIAS_UNRESOLVED"
        rows.append({
            "current_index": index,
            "physical_case_id": case_id,
            "family_id": current_row.get("family_id"),
            "runtime_case_alias": current_row.get("runtime_case_alias"),
            "frames": current_row.get("frames"),
            "particles": current_row.get("particles"),
            "trajectory": {
                "path": str(trajectory_path),
                "producer_declared_sha256": current_sha,
                "declared_bytes": bytes_declared,
                "stat": stat,
            },
            "audit_join": {
                "status": source_join_status,
                "trajectory_path_match": path_match,
                "trajectory_sha_match": sha_match,
                "declared_bytes_match_stat": bytes_match,
                "audit_row_clean": audit_clean,
                "scan_path": scan_path,
                "scan_sha256": scan_sha,
                "receipt_path": receipt_path,
                "receipt_sha256": receipt_sha,
                "scan_receipt_edges_present": bool(scan_edges and receipt_edges),
            },
            "historical_alias": alias_status,
            "observed_trajectory_sha256": "UNKNOWN_UNTIL_GUARDED_WORKER",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "launch_allowed_by_planner": False},
        })
    counts = {
        "current_cases": len(rows),
        "exact_current_audit_metadata_joins": sum(row["audit_join"]["status"] == "EXACT_CURRENT_AUDIT_METADATA_JOIN" for row in rows),
        "historical_alias_unresolved": sum(row["historical_alias"] != "NONE" for row in rows),
        "incomplete_or_mismatched": sum(row["audit_join"]["status"] == "INCOMPLETE_OR_MISMATCHED" for row in rows),
        "trajectory_stat_only_success": sum(row["trajectory"]["stat"].get("status") == "STAT_ONLY" for row in rows),
        "trajectory_stat_failures": sum(row["trajectory"]["stat"].get("status") != "STAT_ONLY" for row in rows),
        "families": {family: sum(row["family_id"] == family for row in rows) for family in sorted({row["family_id"] for row in rows})},
    }
    return rows, counts


def _groups(rows: list[dict[str, Any]], max_group_bytes: int, max_group_cases: int, passes: int) -> list[dict[str, Any]]:
    if max_group_bytes <= 0 or max_group_cases <= 0 or passes <= 0:
        raise PlanError("group limits and read passes must be positive")
    output: list[dict[str, Any]] = []
    for family in sorted({row["family_id"] for row in rows}):
        family_rows = sorted((row for row in rows if row["family_id"] == family), key=lambda row: (-int(row["trajectory"]["declared_bytes"]), row["physical_case_id"]))
        current_group: list[dict[str, Any]] = []
        current_bytes = 0
        family_group_number = 0
        for row in family_rows:
            size = int(row["trajectory"]["declared_bytes"])
            is_alias = row["historical_alias"] != "NONE"
            oversize = size > max_group_bytes
            force_single = oversize or is_alias or size >= max_group_bytes // 2
            if current_group and (force_single or len(current_group) >= max_group_cases or current_bytes + size > max_group_bytes):
                output.append(_group_record(family, family_group_number, current_group, current_bytes, passes, max_group_bytes))
                family_group_number += 1
                current_group, current_bytes = [], 0
            if force_single:
                output.append(_group_record(family, family_group_number, [row], size, passes, max_group_bytes))
                family_group_number += 1
            else:
                current_group.append(row)
                current_bytes += size
        if current_group:
            output.append(_group_record(family, family_group_number, current_group, current_bytes, passes, max_group_bytes))
    return output


def _group_record(family: str, number: int, rows: list[dict[str, Any]], total_bytes: int, passes: int, max_group_bytes: int) -> dict[str, Any]:
    return {
        "group_id": f"{family}-typed-lifecycle-meta-group-{number:03d}",
        "family_id": family,
        "case_ids": [row["physical_case_id"] for row in rows],
        "case_count": len(rows),
        "declared_source_bytes": total_bytes,
        "minimum_worker_read_bytes_if_later_authorized": total_bytes * passes,
        "minimum_source_passes_if_later_authorized": passes,
        "largest_case_bytes": max(int(row["trajectory"]["declared_bytes"]) for row in rows),
        "oversize_single_case": len(rows) == 1 and int(rows[0]["trajectory"]["declared_bytes"]) > max_group_bytes,
        "historical_alias_group": any(row["historical_alias"] != "NONE" for row in rows),
        "source_join_statuses": sorted({row["audit_join"]["status"] for row in rows}),
        "launch_allowed_by_planner": False,
        "root_guard_required": True,
        "attempt_remaining": "ROOT_OWNED_NOT_COMPUTED_BY_PLANNER",
        "hard_limits": "ROOT_OWNED_NOT_COMPUTED_BY_PLANNER",
    }


def build_plan(current_path: Path, audit_path: Path, output: Path, *, expected_current_sha256: str, expected_audit_sha256: str, alias_case: str | None = DEFAULT_ALIAS_CASE, max_group_bytes: int = DEFAULT_MAX_GROUP_BYTES, max_group_cases: int = DEFAULT_MAX_GROUP_CASES, passes: int = DEFAULT_PASSES) -> dict[str, Any]:
    current_path = _path(current_path, "CURRENT336")
    audit_path = _path(audit_path, "scientific audit verification")
    expected_current_sha256 = _sha(expected_current_sha256, "expected CURRENT SHA")
    expected_audit_sha256 = _sha(expected_audit_sha256, "expected audit SHA")
    current_sha256 = _sha256_file(current_path)
    audit_sha256 = _sha256_file(audit_path)
    if current_sha256 != expected_current_sha256:
        raise PlanError(f"CURRENT SHA differs: {current_sha256}")
    if audit_sha256 != expected_audit_sha256:
        raise PlanError(f"audit SHA differs: {audit_sha256}")
    current = _json(current_path, "CURRENT336")
    audit = _json(audit_path, "scientific audit verification")
    rows, counts = _validate_rows(current, audit, expected_current_sha256, alias_case)
    groups = _groups(rows, max_group_bytes, max_group_cases, passes)
    plan = {
        "schema": PLAN_SCHEMA,
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "current_catalog": {"path": str(current_path), "sha256": current_sha256},
        "scientific_audit": {"path": str(audit_path), "sha256": audit_sha256},
        "inventory_scope": {"exact_current_case_count": 336, "case_key_join": "physical_case_id exact set", "families": sorted(counts["families"])},
        "source_read_policy": {
            "json_inputs_opened": True,
            "trajectory_stat_only": True,
            "trajectory_content_opened": False,
            "trajectory_content_hashed": False,
            "native_or_bi4_opened": False,
            "solver_started": False,
            "request_created": False,
        },
        "source_hash_semantics": {
            "producer_declared_trajectory_sha256": "retained_as_declaration_only",
            "observed_trajectory_sha256": "UNKNOWN_UNTIL_GUARDED_WORKER",
            "small_json_input_sha256": "verified_by_planner",
        },
        "counts": counts,
        "group_policy": {
            "max_declared_source_bytes": max_group_bytes,
            "max_cases_per_group": max_group_cases,
            "minimum_worker_read_passes_if_later_authorized": passes,
            "families_are_never_mixed": True,
            "large_case_or_alias_is_single_case_group": True,
        },
        "groups": groups,
        "cases": rows,
        "qualification_scope": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "attempt_accounting": {"remaining_attempts": "ROOT_OWNED_NOT_COMPUTED_BY_PLANNER", "hard_limits": "ROOT_OWNED_NOT_COMPUTED_BY_PLANNER", "ledger_mutation": "FORBIDDEN_IN_METADATA_PLANNER"},
        "alias_scope": {"case_id": alias_case, "status": "SEPARATE_UNRESOLVED_ALIAS" if alias_case else "NOT_REQUESTED", "producer_sha256": "UNKNOWN_UNTIL_ALIAS_RECEIPT_BINDING" if alias_case else None},
    }
    _atomic_json(output, plan)
    return {"status": plan["status"], "output": str(output.expanduser().resolve()), "output_sha256": _sha256_file(output), "case_count": len(rows), "group_count": len(groups), "trajectory_content_opened": False, "trajectory_content_hashed": False}


def self_test() -> dict[str, Any]:
    if _group_record("F1", 0, [{"physical_case_id": "x", "family_id": "F1", "trajectory": {"declared_bytes": 11}, "historical_alias": "NONE", "audit_join": {"status": "EXACT"}}], 11, 3, 100)["minimum_worker_read_bytes_if_later_authorized"] != 33:
        raise AssertionError("group pass accounting failed")
    return {"status": "PASS", "schema": PLAN_SCHEMA, "trajectory_content_opened": False, "launch_allowed_by_planner": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--current", required=True, type=Path)
    prepare.add_argument("--audit-verification", required=True, type=Path)
    prepare.add_argument("--expected-current-sha256", required=True)
    prepare.add_argument("--expected-audit-sha256", required=True)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--historical-alias-case", default=DEFAULT_ALIAS_CASE)
    prepare.add_argument("--max-group-bytes", type=int, default=DEFAULT_MAX_GROUP_BYTES)
    prepare.add_argument("--max-group-cases", type=int, default=DEFAULT_MAX_GROUP_CASES)
    prepare.add_argument("--passes", type=int, default=DEFAULT_PASSES)
    args = parser.parse_args(argv)
    if args.action == "self-test":
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    try:
        result = build_plan(args.current, args.audit_verification, args.output, expected_current_sha256=args.expected_current_sha256, expected_audit_sha256=args.expected_audit_sha256, alias_case=args.historical_alias_case, max_group_bytes=args.max_group_bytes, max_group_cases=args.max_group_cases, passes=args.passes)
    except PlanError as exc:
        raise SystemExit(f"PlanError: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
