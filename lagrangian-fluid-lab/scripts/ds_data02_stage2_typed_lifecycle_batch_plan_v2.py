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

V2 adds a conservative output-cost model to the source-only grouping.  It
uses the producer-declared particle count and an explicit bytes-per-particle
planning assumption; it does not open a trajectory or claim that the estimate
is an observed scientific result.  Groups are split when source bytes, case
count, estimated particles, or estimated JSONL output would exceed its
declared bound.  A single case that exceeds a bound is retained as an
explicit ``requires_split_or_cap_review`` group and is never made launchable.
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
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-batch-plan.v2"
DEFAULT_ALIAS_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
DEFAULT_PASSES = 3
DEFAULT_MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_MAX_GROUP_CASES = 8
# This is intentionally a planning assumption, not a measured HDF5/JSONL
# ratio.  It is recorded in every plan so a root-owned worker can replace it
# with an observed post-reservation report before any launch is considered.
DEFAULT_RECORD_BYTES_PER_PARTICLE = 1024
DEFAULT_MAX_RECORD_BYTES = 512 * 1024 * 1024
# Keep particle cost independently bounded even when a future record format
# becomes more compact than this planner's conservative estimate.
DEFAULT_MAX_GROUP_PARTICLES = 500_000


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


def _annotate_costs(rows: list[dict[str, Any]], record_bytes_per_particle: int) -> dict[str, int]:
    """Attach source-only particle/output estimates to each row.

    ``particles`` comes from CURRENT metadata and is never inferred by opening
    the trajectory.  A missing or non-integral value remains explicitly
    unknown; grouping then isolates that row and keeps it non-launchable.
    """
    if record_bytes_per_particle <= 0:
        raise PlanError("record bytes per particle must be positive")
    counts = {"known_particle_cost": 0, "unknown_particle_cost": 0}
    for row in rows:
        particles = row.get("particles")
        known = isinstance(particles, int) and not isinstance(particles, bool) and particles >= 0
        if known:
            particles = int(particles)
            estimated_bytes = particles * record_bytes_per_particle
            counts["known_particle_cost"] += 1
            row["planning_cost"] = {
                "status": "ESTIMATE_FROM_CURRENT_PARTICLE_COUNT",
                "particles": particles,
                "record_bytes_per_particle_assumption": record_bytes_per_particle,
                "estimated_jsonl_record_bytes": estimated_bytes,
                "observed_output_bytes": "UNKNOWN_UNTIL_GUARDED_WORKER",
            }
        else:
            counts["unknown_particle_cost"] += 1
            row["planning_cost"] = {
                "status": "UNKNOWN_PARTICLE_COUNT",
                "particles": "UNKNOWN",
                "record_bytes_per_particle_assumption": record_bytes_per_particle,
                "estimated_jsonl_record_bytes": "UNKNOWN",
                "observed_output_bytes": "UNKNOWN_UNTIL_GUARDED_WORKER",
            }
    return counts


def _row_cost(row: dict[str, Any]) -> tuple[int | None, int | None]:
    cost = row.get("planning_cost")
    if not isinstance(cost, dict):
        return None, None
    particles = cost.get("particles")
    output_bytes = cost.get("estimated_jsonl_record_bytes")
    if not isinstance(particles, int) or isinstance(particles, bool):
        particles = None
    if not isinstance(output_bytes, int) or isinstance(output_bytes, bool):
        output_bytes = None
    return particles, output_bytes


def _groups(
    rows: list[dict[str, Any]],
    max_group_bytes: int,
    max_group_cases: int,
    passes: int,
    max_group_particles: int,
    max_record_bytes: int,
) -> list[dict[str, Any]]:
    if min(max_group_bytes, max_group_cases, passes, max_group_particles, max_record_bytes) <= 0:
        raise PlanError("group, output, and read-pass limits must be positive")
    output: list[dict[str, Any]] = []
    for family in sorted({row["family_id"] for row in rows}):
        family_rows = sorted((row for row in rows if row["family_id"] == family), key=lambda row: (-int(row["trajectory"]["declared_bytes"]), row["physical_case_id"]))
        current_group: list[dict[str, Any]] = []
        current_bytes = 0
        current_particles = 0
        current_output_bytes = 0
        current_cost_known = True
        family_group_number = 0
        for row in family_rows:
            size = int(row["trajectory"]["declared_bytes"])
            is_alias = row["historical_alias"] != "NONE"
            oversize = size > max_group_bytes
            particles, estimated_output = _row_cost(row)
            unknown_cost = particles is None or estimated_output is None
            row_over_particles = particles is not None and particles > max_group_particles
            row_over_output = estimated_output is not None and estimated_output > max_record_bytes
            force_single = (
                oversize
                or is_alias
                or unknown_cost
                or row_over_particles
                or row_over_output
                or size >= max_group_bytes // 2
                or (particles is not None and particles >= max_group_particles // 2)
                or (estimated_output is not None and estimated_output >= max_record_bytes // 2)
            )
            candidate_particles = current_particles + (particles or 0)
            candidate_output_bytes = current_output_bytes + (estimated_output or 0)
            candidate_cost_known = current_cost_known and not unknown_cost
            candidate_exceeds = (
                current_group
                and (
                    force_single
                    or len(current_group) >= max_group_cases
                    or current_bytes + size > max_group_bytes
                    or (candidate_cost_known and candidate_particles > max_group_particles)
                    or (candidate_cost_known and candidate_output_bytes > max_record_bytes)
                )
            )
            if candidate_exceeds:
                output.append(_group_record(family, family_group_number, current_group, passes, max_group_bytes, max_group_particles, max_record_bytes))
                family_group_number += 1
                current_group, current_bytes = [], 0
                current_particles, current_output_bytes, current_cost_known = 0, 0, True
            if force_single:
                output.append(_group_record(family, family_group_number, [row], passes, max_group_bytes, max_group_particles, max_record_bytes))
                family_group_number += 1
            else:
                current_group.append(row)
                current_bytes += size
                current_particles += particles or 0
                current_output_bytes += estimated_output or 0
                current_cost_known = candidate_cost_known
        if current_group:
            output.append(_group_record(family, family_group_number, current_group, passes, max_group_bytes, max_group_particles, max_record_bytes))
    return output


def _group_record(
    family: str,
    number: int,
    rows: list[dict[str, Any]],
    passes: int,
    max_group_bytes: int,
    max_group_particles: int,
    max_record_bytes: int,
) -> dict[str, Any]:
    total_bytes = sum(int(row["trajectory"]["declared_bytes"]) for row in rows)
    particle_values = [_row_cost(row)[0] for row in rows]
    output_values = [_row_cost(row)[1] for row in rows]
    particle_cost_known = all(value is not None for value in particle_values)
    output_cost_known = all(value is not None for value in output_values)
    estimated_particles = sum(value or 0 for value in particle_values) if particle_cost_known else "UNKNOWN"
    estimated_output_bytes = sum(value or 0 for value in output_values) if output_cost_known else "UNKNOWN"
    reasons: list[str] = []
    if total_bytes > max_group_bytes:
        reasons.append("SOURCE_BYTES_OVER_GROUP_CAP")
    if not particle_cost_known:
        reasons.append("PARTICLE_COST_UNKNOWN")
    elif estimated_particles > max_group_particles:
        reasons.append("PARTICLES_OVER_GROUP_CAP")
    if not output_cost_known:
        reasons.append("JSONL_OUTPUT_COST_UNKNOWN")
    elif estimated_output_bytes > max_record_bytes:
        reasons.append("JSONL_OUTPUT_OVER_RECORD_CAP")
    if any(row["historical_alias"] != "NONE" for row in rows):
        reasons.append("HISTORICAL_ALIAS_REVIEW_REQUIRED")
    if any(row["audit_join"]["status"] != "EXACT_CURRENT_AUDIT_METADATA_JOIN" for row in rows):
        reasons.append("SOURCE_JOIN_NOT_EXACT")
    within_bounds = not reasons
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
        "estimated_particle_count": estimated_particles,
        "estimated_jsonl_record_bytes": estimated_output_bytes,
        "particle_cost_known": particle_cost_known,
        "jsonl_output_cost_known": output_cost_known,
        "planning_bounds": {
            "max_group_source_bytes": max_group_bytes,
            "max_group_particles": max_group_particles,
            "max_jsonl_record_bytes": max_record_bytes,
        },
        "planning_status": "WITHIN_DECLARED_BOUNDS" if within_bounds else "REQUIRES_SPLIT_OR_CAP_REVIEW",
        "planning_reasons": reasons,
        "requires_split_or_cap_review": not within_bounds,
        "historical_alias_group": any(row["historical_alias"] != "NONE" for row in rows),
        "source_join_statuses": sorted({row["audit_join"]["status"] for row in rows}),
        "launch_allowed_by_planner": False,
        "root_guard_required": True,
        "attempt_remaining": "ROOT_OWNED_NOT_COMPUTED_BY_PLANNER",
        "hard_limits": "ROOT_OWNED_NOT_COMPUTED_BY_PLANNER",
    }


def build_plan(
    current_path: Path,
    audit_path: Path,
    output: Path,
    *,
    expected_current_sha256: str,
    expected_audit_sha256: str,
    alias_case: str | None = DEFAULT_ALIAS_CASE,
    max_group_bytes: int = DEFAULT_MAX_GROUP_BYTES,
    max_group_cases: int = DEFAULT_MAX_GROUP_CASES,
    passes: int = DEFAULT_PASSES,
    record_bytes_per_particle: int = DEFAULT_RECORD_BYTES_PER_PARTICLE,
    max_group_particles: int = DEFAULT_MAX_GROUP_PARTICLES,
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES,
) -> dict[str, Any]:
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
    cost_counts = _annotate_costs(rows, record_bytes_per_particle)
    counts.update(cost_counts)
    groups = _groups(rows, max_group_bytes, max_group_cases, passes, max_group_particles, max_record_bytes)
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
        "planner_assumptions": {
            "record_bytes_per_particle": record_bytes_per_particle,
            "record_bytes_per_particle_is_observed": False,
            "max_jsonl_record_bytes": max_record_bytes,
            "max_group_particles": max_group_particles,
            "particle_count_source": "CURRENT336 producer-declared metadata",
            "output_cost_requires_guarded_worker_replacement": True,
        },
        "counts": counts,
        "group_policy": {
            "max_declared_source_bytes": max_group_bytes,
            "max_cases_per_group": max_group_cases,
            "max_particles_per_group": max_group_particles,
            "max_jsonl_record_bytes": max_record_bytes,
            "record_bytes_per_particle_assumption": record_bytes_per_particle,
            "particle_cost_semantics": "CURRENT producer-declared particle count; planning estimate only",
            "jsonl_cost_semantics": "particle count times explicit assumption; observed output remains UNKNOWN",
            "minimum_worker_read_passes_if_later_authorized": passes,
            "families_are_never_mixed": True,
            "large_case_or_alias_or_cost_boundary_is_single_case_group": True,
            "unknown_particle_cost_is_isolated_and_nonlaunchable": True,
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
    row = {
        "physical_case_id": "x",
        "family_id": "F1",
        "trajectory": {"declared_bytes": 11},
        "planning_cost": {
            "particles": 2,
            "estimated_jsonl_record_bytes": 20,
        },
        "historical_alias": "NONE",
        "audit_join": {"status": "EXACT_CURRENT_AUDIT_METADATA_JOIN"},
    }
    group = _group_record("F1", 0, [row], 3, 100, 100, 100)
    if group["minimum_worker_read_bytes_if_later_authorized"] != 33:
        raise AssertionError("group pass accounting failed")
    if group["estimated_particle_count"] != 2 or group["estimated_jsonl_record_bytes"] != 20:
        raise AssertionError("group particle/output accounting failed")
    rows = [dict(row, planning_cost={"particles": "UNKNOWN", "estimated_jsonl_record_bytes": "UNKNOWN"})]
    unknown = _group_record("F1", 1, rows, 3, 100, 100, 100)
    if "PARTICLE_COST_UNKNOWN" not in unknown["planning_reasons"] or not unknown["requires_split_or_cap_review"]:
        raise AssertionError("unknown particle cost was not isolated")
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
    prepare.add_argument("--max-group-particles", type=int, default=DEFAULT_MAX_GROUP_PARTICLES)
    prepare.add_argument("--max-record-bytes", type=int, default=DEFAULT_MAX_RECORD_BYTES)
    prepare.add_argument("--record-bytes-per-particle", type=int, default=DEFAULT_RECORD_BYTES_PER_PARTICLE)
    prepare.add_argument("--passes", type=int, default=DEFAULT_PASSES)
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
            alias_case=args.historical_alias_case,
            max_group_bytes=args.max_group_bytes,
            max_group_cases=args.max_group_cases,
            passes=args.passes,
            record_bytes_per_particle=args.record_bytes_per_particle,
            max_group_particles=args.max_group_particles,
            max_record_bytes=args.max_record_bytes,
        )
    except PlanError as exc:
        raise SystemExit(f"PlanError: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
