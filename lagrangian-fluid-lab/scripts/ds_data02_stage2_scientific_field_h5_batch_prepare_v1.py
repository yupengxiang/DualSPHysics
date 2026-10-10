#!/usr/bin/env python3
"""Prepare a metadata-only index for the completed CURRENT336 field-audit scope.

This utility is deliberately an index builder, not an HDF5 worker.  It consumes
the small ROOT307 continuation plan and evidence registry, validates their exact
CURRENT/source bindings, and records one deferred trajectory reference per
canonical case.  It may stat trajectory files to bind declared byte counts, but
it never opens or hashes an HDF5 trajectory.  The resulting groups are useful
inputs for a later, root-authorized streaming audit; they do not grant field,
physical, or scientific qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2_ROOT = PRIMARY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT_DEFAULT = STAGE2_ROOT / "CURRENT336.json"
PLAN_DEFAULT = STAGE2_ROOT / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY_DEFAULT = STAGE2_ROOT / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
PLAN_SHA256 = "2d7ac52f5e3afd5b76b112fdc9dff4a9a8fc6bf4e7c1e045294f0fa93843febd"
REGISTRY_SHA256 = "396118a33c568f04393e95ff549aba3783dc85d3674b2776d18ffb0c08d6b6fc"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
REGISTRY_SCHEMA = "ds02.stage2.typed-lifecycle-evidence-registry.v4"
OUTPUT_SCHEMA = "ds02.stage2.scientific-field-h5-batch-source.v1"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_CASES_PER_GROUP = 8
MAX_GROUP_BYTES = 20 * 1024 * 1024 * 1024
H5_PASSES_MINIMUM = 3
PER_CASE_RECORD_CAP_BYTES = 512 * 1024 * 1024
PER_CASE_SUMMARY_CAP_BYTES = 2 * 1024 * 1024


class BatchPrepareError(ValueError):
    """Raised when immutable metadata bindings or scope invariants fail."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise BatchPrepareError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise BatchPrepareError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool | None = None) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise BatchPrepareError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if directory is True and not path.is_dir():
        raise BatchPrepareError(f"{label} is not a directory: {path}")
    if directory is False and not path.is_file():
        raise BatchPrepareError(f"{label} is not a file: {path}")
    return path


def _stat(path: Path, role: str) -> dict[str, Any]:
    value = path.stat()
    return {
        "role": role,
        "path": str(path.resolve()),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    path = _path(path, label, directory=False)
    before = _stat(path, label)
    if before["bytes"] > MAX_JSON_BYTES:
        raise BatchPrepareError(f"{label} exceeds bounded JSON size")
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchPrepareError(f"{label} is invalid JSON") from exc
    after = _stat(path, label)
    if before != after:
        raise BatchPrepareError(f"{label} changed during metadata read")
    if not isinstance(value, dict):
        raise BatchPrepareError(f"{label} must be a JSON object")
    return value, after, _sha256_bytes(payload)


def _static_ref(path_value: Any, expected_sha: Any, role: str) -> dict[str, Any]:
    path = _path(path_value, role, directory=False)
    if path.suffix.lower() in {".h5", ".hdf5"}:
        raise BatchPrepareError(f"HDF5 cannot be a static metadata input: {path}")
    actual = _sha256_file(path)
    expected = _require_sha(expected_sha, f"{role} SHA")
    if actual != expected:
        raise BatchPrepareError(f"{role} changed: {path}")
    ref = _stat(path, role)
    ref.update({"sha256": actual, "content_read_by_preparer": True})
    return ref


def _deferred_h5_ref(row: dict[str, Any], current_row: dict[str, Any]) -> dict[str, Any]:
    case_id = row.get("physical_case_id")
    raw_path = row.get("trajectory_path")
    if not isinstance(raw_path, str) or not raw_path:
        raise BatchPrepareError(f"{case_id}: trajectory_path is missing")
    path = _path(raw_path, f"{case_id} trajectory HDF5", directory=False)
    if path.suffix.lower() not in {".h5", ".hdf5"}:
        raise BatchPrepareError(f"{case_id}: trajectory is not HDF5")
    declared = row.get("declared_source_bytes")
    if not isinstance(declared, int) or isinstance(declared, bool) or declared <= 0:
        raise BatchPrepareError(f"{case_id}: declared_source_bytes is invalid")
    current = _stat(path, f"{case_id} trajectory HDF5")
    if current["bytes"] != declared:
        raise BatchPrepareError(
            f"{case_id}: trajectory byte count differs from declared source ({current['bytes']} != {declared})"
        )
    current_trajectory = current_row.get("trajectory")
    if not isinstance(current_trajectory, dict):
        raise BatchPrepareError(f"{case_id}: CURRENT trajectory binding is missing")
    current_path = _path(current_trajectory.get("path"), f"{case_id} CURRENT trajectory", directory=False)
    if current_path != path:
        raise BatchPrepareError(f"{case_id}: plan/CURRENT trajectory path mismatch")
    current_declared = current_trajectory.get("bytes")
    if isinstance(current_declared, int) and current_declared != declared:
        raise BatchPrepareError(f"{case_id}: plan/CURRENT trajectory byte mismatch")
    evidence = row.get("producer_evidence")
    if not isinstance(evidence, dict):
        raise BatchPrepareError(f"{case_id}: producer evidence is missing")
    known_sha = evidence.get("trajectory_source_sha256")
    known_sha_source = "ROOT307_PLAN_PRODUCER_EVIDENCE"
    if not isinstance(known_sha, str) or len(known_sha) != 64:
        # ROOT192's older single-case plan stores the declared trajectory SHA
        # in CURRENT336 rather than repeating it in producer_evidence.  This is
        # still a producer declaration; it is not a new H5 content hash.
        known_sha = current_trajectory.get("producer_declared_sha256")
        known_sha_source = "CURRENT336_PRODUCER_DECLARED_SHA256"
    if not isinstance(known_sha, str) or len(known_sha) != 64:
        raise BatchPrepareError(f"{case_id}: producer trajectory SHA is missing")
    # Deliberately do not call _sha256_file(path).  The path is only stat-bound.
    return {
        "role": "deferred_trajectory_h5",
        "path": str(path),
        "bytes": declared,
        "mtime_ns": current["mtime_ns"],
        "ctime_ns": current["ctime_ns"],
        "st_dev": current["st_dev"],
        "st_ino": current["st_ino"],
        "known_sha256": _require_sha(known_sha, f"{case_id} producer trajectory SHA"),
        "known_sha_source": known_sha_source,
        "content_read_by_preparer": False,
        "content_hashed_by_preparer": False,
        "deferred_until_parent_reservation": True,
    }


def _coverage(plan: dict[str, Any]) -> None:
    expected = {
        "actual_saved_mask_cases": 335,
        "current_cases": 336,
        "exact_current_audit_rows": 335,
        "failed_requires_new_attempt_cases": 0,
        "historical_alias_unresolved": 1,
        "incomplete_or_mismatched": 0,
        "pending_no_credit_cases": 0,
        "physical_or_scientific_credit_cases": 0,
        "remaining_exact_unscheduled_cases": 0,
    }
    actual = plan.get("coverage")
    if not isinstance(actual, dict):
        raise BatchPrepareError("ROOT307 plan coverage is missing")
    for key, value in expected.items():
        if actual.get(key) != value:
            raise BatchPrepareError(f"ROOT307 coverage mismatch: {key}={actual.get(key)!r}, expected {value!r}")


def _case_shape(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = plan.get("case_records")
    if not isinstance(rows, list) or len(rows) != 336:
        raise BatchPrepareError("ROOT307 plan must contain exactly 336 case records")
    indexes = [row.get("current_index") for row in rows if isinstance(row, dict)]
    if len(indexes) != 336 or sorted(indexes) != list(range(336)):
        raise BatchPrepareError("CURRENT case indexes are not a unique 0..335 sequence")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise BatchPrepareError("case record lacks physical_case_id")
        case_id = row["physical_case_id"]
        if case_id in by_id:
            raise BatchPrepareError(f"duplicate CURRENT case: {case_id}")
        by_id[case_id] = row
    aliases = [row for row in rows if row.get("historical_alias") != "NONE"]
    if len(aliases) != 1:
        raise BatchPrepareError(f"expected exactly one historical alias, got {len(aliases)}")
    alias = aliases[0]
    if alias.get("status") != "HISTORICAL_ALIAS_UNRESOLVED" or alias.get("actual_saved_mask_coverage") is not False:
        raise BatchPrepareError("historical alias is not explicitly unresolved")
    canonical = [row for row in rows if row.get("historical_alias") == "NONE"]
    for row in canonical:
        case_id = row["physical_case_id"]
        if row.get("status") != "ACTUAL_SAVED_MASK_COMPLETED" or row.get("actual_saved_mask_coverage") is not True:
            raise BatchPrepareError(f"{case_id}: canonical saved-mask status is not completed")
        if row.get("source_join_status") != "EXACT_CURRENT_AUDIT_METADATA_JOIN":
            raise BatchPrepareError(f"{case_id}: source join is not exact CURRENT metadata")
        if row.get("family_id") not in {f"F{i}" for i in range(1, 8)}:
            raise BatchPrepareError(f"{case_id}: invalid family")
    return canonical, by_id


def _registry_shape(registry: dict[str, Any], canonical_ids: set[str]) -> dict[str, dict[str, Any]]:
    if registry.get("schema") != REGISTRY_SCHEMA or registry.get("status") != "SOURCE_METADATA_REGISTRY":
        raise BatchPrepareError("registry schema/status is not ROOT307 v4")
    current = registry.get("current")
    if not isinstance(current, dict) or current.get("sha256") != CURRENT_SHA256:
        raise BatchPrepareError("registry CURRENT binding is not frozen")
    producers = registry.get("producers")
    if not isinstance(producers, list):
        raise BatchPrepareError("registry producers are missing")
    history_by_id: dict[str, list[dict[str, Any]]] = {}
    for producer in producers:
        if not isinstance(producer, dict) or producer.get("status") not in {"COMPLETED", "FAILED"}:
            raise BatchPrepareError("registry has an invalid producer status")
        ids = producer.get("case_ids")
        if not isinstance(ids, list) or not ids:
            raise BatchPrepareError("registry producer has no case_ids")
        for case_id in ids:
            if not isinstance(case_id, str):
                raise BatchPrepareError(f"registry case identity is invalid: {case_id!r}")
            history_by_id.setdefault(case_id, []).append(producer)
    if set(history_by_id) != canonical_ids:
        missing = sorted(canonical_ids - set(history_by_id))[:3]
        extra = sorted(set(history_by_id) - canonical_ids)[:3]
        raise BatchPrepareError(f"registry/CURRENT case set mismatch: missing={missing}, extra={extra}")
    selected: dict[str, dict[str, Any]] = {}
    for case_id, history in history_by_id.items():
        completed = [producer for producer in history if producer.get("status") == "COMPLETED"]
        if not completed:
            raise BatchPrepareError(f"{case_id}: registry has no completed producer")
        # Registry order is the producer chronology.  The latest completed
        # producer is the source candidate; failed predecessors stay visible
        # in producer_history and do not create a second physical case.
        selected[case_id] = {
            "selected": completed[-1],
            "producer_history": [
                {"producer_id": item.get("producer_id"), "status": item.get("status"), "kind": item.get("kind")}
                for item in history
            ],
        }
    return selected


def _producer_static_refs(producer: dict[str, Any], case_id: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "producer_id": producer.get("producer_id"),
        "kind": producer.get("kind"),
        "attempt_id": producer.get("attempt_id"),
        "status": producer.get("status"),
    }
    for field in ("proof", "request", "manifest", "summary"):
        value = producer.get(field)
        if not isinstance(value, dict):
            # Batch registry rows keep the per-case summary in the ROOT plan's
            # producer_evidence row; a top-level summary is optional there.
            if field == "summary" or (field == "manifest" and producer.get("kind") == "single_typed_lifecycle"):
                continue
            raise BatchPrepareError(f"{case_id}: registry producer lacks {field}")
        path = value.get("path")
        expected = value.get("sha256")
        key = f"{Path(str(path)).expanduser().resolve()}|{expected}"
        if key not in cache:
            cache[key] = _static_ref(path, expected, f"{case_id} registry {field}")
        output[field] = cache[key]
    return output


def _plan_evidence_refs(row: dict[str, Any], case_id: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evidence = row.get("producer_evidence")
    if not isinstance(evidence, dict):
        raise BatchPrepareError(f"{case_id}: plan producer_evidence missing")
    output: dict[str, Any] = {"attempt_id": evidence.get("attempt_id"), "status": evidence.get("status")}
    # These are small reports/manifests/receipts.  Hash them as static metadata;
    # the large H5 trajectory is handled separately by _deferred_h5_ref.
    for source_key, output_key in (("case_manifest", "case_manifest"), ("case_receipt", "case_receipt"), ("summary", "typed_summary")):
        value = evidence.get(source_key)
        if source_key == "case_receipt" and not isinstance(value, dict):
            value = evidence.get("receipt")
        if not isinstance(value, dict):
            if source_key == "case_manifest":
                output[output_key] = None
                continue
            raise BatchPrepareError(f"{case_id}: plan producer_evidence lacks {source_key}")
        expected = value.get("sha256")
        key = f"{Path(str(value.get('path'))).expanduser().resolve()}|{expected}"
        if key not in cache:
            cache[key] = _static_ref(value.get("path"), expected, f"{case_id} plan {source_key}")
        output[output_key] = cache[key]
    return output


def _groups(canonical: list[dict[str, Any]], h5_refs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {f"F{i}": [] for i in range(1, 8)}
    for row in canonical:
        grouped[row["family_id"]].append(row)
    groups: list[dict[str, Any]] = []
    for family, rows in grouped.items():
        rows = sorted(rows, key=lambda row: int(row["current_index"]))
        chunks: list[list[dict[str, Any]]] = []
        current_chunk: list[dict[str, Any]] = []
        current_bytes = 0
        for row in rows:
            row_bytes = h5_refs[row["physical_case_id"]]["bytes"]
            if row_bytes > MAX_GROUP_BYTES:
                raise BatchPrepareError(f"{family}: one trajectory exceeds source byte bound")
            if current_chunk and (len(current_chunk) >= MAX_CASES_PER_GROUP or current_bytes + row_bytes > MAX_GROUP_BYTES):
                chunks.append(current_chunk)
                current_chunk = []
                current_bytes = 0
            current_chunk.append(row)
            current_bytes += row_bytes
        if current_chunk:
            chunks.append(current_chunk)
        for group_index, chunk in enumerate(chunks):
            source_bytes = sum(h5_refs[row["physical_case_id"]]["bytes"] for row in chunk)
            if source_bytes > MAX_GROUP_BYTES:
                raise BatchPrepareError(f"{family} metadata group exceeds source byte bound")
            groups.append({
                "group_id": f"{family}-scientific-field-h5-metadata-{group_index:03d}",
                "family_id": family,
                "case_ids": [row["physical_case_id"] for row in chunk],
                "current_indexes": [int(row["current_index"]) for row in chunk],
                "case_count": len(chunk),
                "declared_source_bytes": source_bytes,
                "minimum_h5_read_bytes_if_later_authorized": source_bytes * H5_PASSES_MINIMUM,
                "minimum_h5_passes_per_case": H5_PASSES_MINIMUM,
                "one_case_at_a_time": True,
                "request_created": False,
                "launch_allowed_by_this_index": False,
                "field_audit_status": "NOT_RUN",
                "scientific_credit": "NONE",
            })
    return groups


def _atomic_json(path: Path, value: dict[str, Any], max_bytes: int = MAX_OUTPUT_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise BatchPrepareError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise BatchPrepareError(f"output exceeds bounded metadata size: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_metadata(current_path: Path, plan_path: Path, registry_path: Path, output_dir: Path, report_path: Path) -> dict[str, Any]:
    current_path = _path(current_path, "CURRENT336", directory=False)
    plan_path = _path(plan_path, "ROOT307 plan", directory=False)
    registry_path = _path(registry_path, "ROOT307 registry", directory=False)
    current, current_stat, current_actual_sha = _read_json(current_path, "CURRENT336")
    plan, plan_stat, plan_actual_sha = _read_json(plan_path, "ROOT307 plan")
    registry, registry_stat, registry_actual_sha = _read_json(registry_path, "ROOT307 registry")
    if current_actual_sha != CURRENT_SHA256:
        raise BatchPrepareError("CURRENT336 SHA differs from frozen source")
    if plan_actual_sha != PLAN_SHA256:
        raise BatchPrepareError("ROOT307 plan SHA differs from frozen source")
    if registry_actual_sha != REGISTRY_SHA256:
        raise BatchPrepareError("ROOT307 registry SHA differs from frozen source")
    if current.get("schema") != CURRENT_SCHEMA:
        raise BatchPrepareError("CURRENT336 schema differs")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise BatchPrepareError("ROOT307 plan schema/status differs")
    if plan.get("current_catalog") != {"path": str(current_path), "sha256": CURRENT_SHA256}:
        raise BatchPrepareError("ROOT307 plan current_catalog is not bound to CURRENT336")
    if registry.get("current") != {"path": str(current_path), "sha256": CURRENT_SHA256}:
        raise BatchPrepareError("ROOT307 registry current binding is not exact")
    _coverage(plan)
    canonical, rows_by_id = _case_shape(plan)
    current_rows = current.get("cases")
    if not isinstance(current_rows, list):
        raise BatchPrepareError("CURRENT336 cases are missing")
    current_by_id = {row.get("physical_case_id"): row for row in current_rows if isinstance(row, dict)}
    if set(current_by_id) != {row["physical_case_id"] for row in plan["case_records"]}:
        raise BatchPrepareError("CURRENT336 and ROOT307 plan case sets differ")
    registry_by_id = _registry_shape(registry, {row["physical_case_id"] for row in canonical})
    cache: dict[str, dict[str, Any]] = {}
    h5_refs: dict[str, dict[str, Any]] = {}
    case_rows: list[dict[str, Any]] = []
    for row in sorted(canonical, key=lambda item: int(item["current_index"])):
        case_id = row["physical_case_id"]
        h5_ref = _deferred_h5_ref(row, current_by_id[case_id])
        h5_refs[case_id] = h5_ref
        case_rows.append({
            "physical_case_id": case_id,
            "family_id": row["family_id"],
            "current_index": int(row["current_index"]),
            "declared_source_bytes": int(row["declared_source_bytes"]),
            "trajectory_h5": h5_ref,
            "producer_id": registry_by_id[case_id]["selected"].get("producer_id"),
            "producer": _producer_static_refs(registry_by_id[case_id]["selected"], case_id, cache),
            "producer_history": registry_by_id[case_id]["producer_history"],
            "typed_lifecycle_evidence": _plan_evidence_refs(row, case_id, cache),
            "source_join_status": row["source_join_status"],
            "saved_mask_status": row["status"],
            "field_audit_status": "NOT_RUN",
            "scientific_credit": "NONE",
        })
    alias = next(row for row in plan["case_records"] if row.get("historical_alias") != "NONE")
    alias_path = _path(alias["trajectory_path"], "historical alias trajectory HDF5", directory=False)
    alias_stat = _stat(alias_path, "historical alias trajectory HDF5")
    groups = _groups(canonical, h5_refs)
    total_source = sum(row["declared_source_bytes"] for row in case_rows)
    metadata = {
        "schema": OUTPUT_SCHEMA,
        "status": "SOURCE_PREPARED_335_CANONICAL_METADATA_ONLY",
        "as_of_plan": plan.get("as_of_utc"),
        "current_binding": {"path": str(current_path), "sha256": CURRENT_SHA256, "stat": current_stat},
        "root307_plan": {"path": str(plan_path), "sha256": PLAN_SHA256, "stat": plan_stat},
        "evidence_registry": {"path": str(registry_path), "sha256": REGISTRY_SHA256, "stat": registry_stat},
        "scope": {
            "current_case_count": 336,
            "canonical_case_count": 335,
            "historical_alias_count": 1,
            "families": [f"F{i}" for i in range(1, 8)],
            "canonical_case_ids_are_exact_current_records": True,
            "alias_excluded_from_field_audit": True,
            "alias": {
                "physical_case_id": alias["physical_case_id"],
                "current_index": int(alias["current_index"]),
                "status": alias["status"],
                "source_join_status": alias["source_join_status"],
                "trajectory_h5": {**alias_stat, "content_read_by_preparer": False, "content_hashed_by_preparer": False},
                "scientific_credit": "NONE",
            },
        },
        "cases": case_rows,
        "groups": groups,
        "source_read_cost": {
            "declared_h5_bytes_total": total_source,
            "minimum_h5_read_bytes_if_later_authorized": total_source * H5_PASSES_MINIMUM,
            "minimum_h5_passes_per_case": H5_PASSES_MINIMUM,
            "sequential_one_case_at_a_time": True,
            "max_cases_per_future_group": MAX_CASES_PER_GROUP,
            "max_declared_bytes_per_future_group": MAX_GROUP_BYTES,
            "per_case_record_cap_bytes": PER_CASE_RECORD_CAP_BYTES,
            "per_case_summary_cap_bytes": PER_CASE_SUMMARY_CAP_BYTES,
            "preparer_opened_h5": False,
            "preparer_hashed_h5": False,
        },
        "qualification_boundary": {
            "saved_mask_lifecycle": "metadata scope only; field audit NOT_RUN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "initial_mass_field": "NOT_AUDITED",
            "units": "NOT_AUDITED",
            "material_and_mk": "NOT_AUDITED",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "native_massfluid_binding": "UNKNOWN",
        },
        "execution": {
            "request_created": False,
            "launch_allowed_by_this_index": False,
            "root_rebinding_required_for_any_future_worker": True,
            "raw_h5_deferred_until_parent_reservation": True,
            "raw_bi4_opened": False,
            "solver_started": False,
        },
        "source_refs_hashed_by_preparer": len(cache),
    }
    output_dir = output_dir.expanduser().resolve()
    output_path = output_dir / "scientific-field-h5-335-batch-manifest.json"
    _atomic_json(output_path, metadata)
    output_sha = _sha256_file(output_path)
    report = {
        "schema": "ds02.stage2.scientific-field-h5-batch-source-report.v1",
        "status": "SOURCE_PREPARED_335_CANONICAL_METADATA_ONLY",
        "manifest": {"path": str(output_path), "sha256": output_sha, "bytes": output_path.stat().st_size},
        "current_binding": metadata["current_binding"],
        "plan_binding": metadata["root307_plan"],
        "registry_binding": metadata["evidence_registry"],
        "counts": {"current": 336, "canonical": 335, "historical_alias_excluded": 1, "field_audit_completed": 0, "scientific_credit_cases": 0},
        "family_counts": {family: sum(1 for row in case_rows if row["family_id"] == family) for family in [f"F{i}" for i in range(1, 8)]},
        "group_count": len(groups),
        "declared_h5_bytes_total": total_source,
        "minimum_h5_read_bytes_if_later_authorized": total_source * H5_PASSES_MINIMUM,
        "read_policy": metadata["execution"],
        "qualification_boundary": metadata["qualification_boundary"],
    }
    _atomic_json(report_path, report)
    return {
        "status": metadata["status"],
        "manifest": str(output_path),
        "manifest_sha256": output_sha,
        "report": str(report_path.resolve()),
        "report_sha256": _sha256_file(report_path.resolve()),
        "canonical_cases": 335,
        "historical_alias_excluded": 1,
        "group_count": len(groups),
        "declared_h5_bytes_total": total_source,
        "minimum_h5_read_bytes_if_later_authorized": total_source * H5_PASSES_MINIMUM,
        "trajectory_content_opened": False,
        "trajectory_content_hashed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepare", nargs="?", choices=["prepare"], default="prepare")
    parser.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    parser.add_argument("--plan", type=Path, default=PLAN_DEFAULT)
    parser.add_argument("--registry", type=Path, default=REGISTRY_DEFAULT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_metadata(args.current, args.plan, args.registry, args.output_dir, args.report)
    except (BatchPrepareError, OSError, ValueError) as exc:
        print(f"batch metadata prepare failed: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
