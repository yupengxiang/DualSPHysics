#!/usr/bin/env python3
"""Prepare and run a bounded scientific-field audit over typed lifecycle records.

The lifecycle products record saved-mask transitions and producer-declared unit
metadata.  That evidence does not, by itself, establish that every per-frame
value is finite, that units are independently authoritative, or that material
and MK fields are present.  This worker audits the small JSONL record product
after reservation and keeps those boundaries explicit.  It never opens HDF5,
BI4, native solver output, or trajectory payloads.

``prepare`` reads only bounded JSON metadata and file statistics.  The selected
JSONL is a deferred input; its known SHA/stat comes from the source-bound
terminal proof and is first hashed by ``audit`` after reservation.  ``audit``
performs a pre-hash, one streaming parse, and a post-hash, then emits a small
summary.  It can verify record identity, initial mass/type scalar fields, and
the lifecycle scalar schema.  Raw frame position/velocity/density/mass/pressure
finiteness, authoritative units, MK/material provenance, and scientific impact
remain explicitly unmeasured or UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
STAGE2_ROOT = LAB_ROOT / "campaigns/ds-data-02/stage2"
CURRENT_DEFAULT = STAGE2_ROOT / "CURRENT336.json"
CLOSURE_DEFAULT = STAGE2_ROOT / "checkpoints/ROOT304_ACTUAL_LIFECYCLE_METADATA_INDEPENDENT_CLOSURE_V1.json"
PROOF_DEFAULT = STAGE2_ROOT / "checkpoints/TYPED_LIFECYCLE_BATCH_F7_ACTUAL_ROOT_VERIFICATION_304.json"
VENV_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
CONFIG_DEFAULT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
RUNTIME_DEFAULT = LAB_ROOT / "scripts/ds_data02_runtime_v8.py"
DISPATCH_DEFAULT = LAB_ROOT / "scripts/ds_data02_stage2_dispatch_v8.py"
STRICT_DEFAULT = LAB_ROOT / "scripts/ds_data02_strict_dispatch_v8.py"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
PROOF_SHA256 = "38b26966e5d3c37753832bca1b553ca73d22a5bd88335324d8e2475ed8c408c7"
CLOSURE_SCHEMA = "ds02.stage2.root-lifecycle-metadata-independent-closure.v1"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.scientific-field-gap-audit-manifest.v1"
WORKER_SCHEMA = "ds02.stage2.scientific-field-gap-audit.v1"
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_RECORD_ROWS = 2_000_000


class FieldAuditError(ValueError):
    """Raised when the source-bound field-audit contract is open."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise FieldAuditError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise FieldAuditError(f"{label} is not hexadecimal")
    return value


def path_value(value: Any, label: str, *, allow_missing: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise FieldAuditError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not allow_missing and not path.is_file():
        raise FieldAuditError(f"{label} is missing: {path}")
    return path


def json_object(path: Path, label: str) -> dict[str, Any]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise FieldAuditError(f"{label} exceeds bounded JSON limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FieldAuditError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FieldAuditError(f"{label} must be a JSON object")
    return value


def stat_ref(path: Path, label: str) -> dict[str, Any]:
    value = path.stat()
    return {
        "role": label,
        "path": str(path.resolve()),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def static_ref(path: Path, label: str, *, expected_sha: str | None = None) -> dict[str, Any]:
    ref = stat_ref(path, label)
    actual = sha256_file(path)
    if expected_sha is not None and actual != require_sha(expected_sha, f"{label} expected SHA"):
        raise FieldAuditError(f"{label} changed: {path}")
    ref["sha256"] = actual
    ref["content_read_by_preparer"] = True
    return ref


def deferred_ref(path: Path, label: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Capture proof-provided identity while hashing no deferred payload."""
    current = stat_ref(path, label)
    for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if key in expected and int(expected[key]) != int(current[key]):
            raise FieldAuditError(f"{label} stat changed before reservation: {key}")
    expected_sha = require_sha(expected.get("sha256"), f"{label} known SHA")
    current.update({"sha256": expected_sha, "known_sha256": expected_sha})
    current["content_read_by_preparer"] = False
    current["deferred_after_reservation"] = True
    return current


def atomic_json(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_JSON_BYTES) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FieldAuditError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > max_bytes:
            raise FieldAuditError(f"JSON output exceeds bounded limit: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


REQUIRED_ROW_FIELDS = {
    "zone", "idp", "initial_type_code", "initial_role", "initial_mass_kg",
    "initially_active", "new_id", "first_active_frame", "first_active_time_s",
    "last_active_frame", "last_active_time_s", "first_disappeared_frame",
    "first_disappeared_time_s", "first_disappeared_bracket_s", "reappearance_count",
    "first_reappearance_frame", "first_reappearance_time_s", "last_reappearance_frame",
    "last_reappearance_time_s", "missing_at_final", "censoring", "unknown",
    "native_exit_cause", "physical_fate", "legal_flux", "dynamical_impact",
}
TYPE_NAMES = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}


def _finite_optional(value: Any) -> bool:
    return value is None or _finite_number(value)


def validate_record(header: dict[str, Any], row: dict[str, Any], seen: set[tuple[int, int]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    missing = sorted(REQUIRED_ROW_FIELDS - set(row))
    if missing:
        errors.append(f"missing_fields:{','.join(missing)}")
    try:
        zone = row.get("zone")
        idp = row.get("idp")
        if not isinstance(zone, int) or isinstance(zone, bool) or not isinstance(idp, int) or isinstance(idp, bool):
            errors.append("identity_not_integer")
        else:
            key = (zone, idp)
            if key in seen:
                errors.append("duplicate_identity")
            seen.add(key)
    except TypeError:
        errors.append("identity_unhashable")
    type_code = row.get("initial_type_code")
    if type_code not in TYPE_NAMES:
        errors.append("initial_type_unknown")
    if row.get("initial_role") != TYPE_NAMES.get(type_code):
        errors.append("initial_role_mismatch")
    if not _finite_number(row.get("initial_mass_kg")) or float(row["initial_mass_kg"]) <= 0:
        errors.append("initial_mass_not_finite_positive")
    if not isinstance(row.get("unknown"), dict):
        errors.append("unknown_diagnostics_not_object")
    for field in ("first_active_time_s", "last_active_time_s", "first_disappeared_time_s", "first_reappearance_time_s", "last_reappearance_time_s"):
        if not _finite_optional(row.get(field)):
            errors.append(f"{field}_not_finite")
    bracket = row.get("first_disappeared_bracket_s")
    if bracket is not None and (not isinstance(bracket, list) or len(bracket) != 2 or not all(_finite_optional(v) for v in bracket)):
        errors.append("disappearance_bracket_invalid")
    if not isinstance(row.get("censoring"), str):
        errors.append("censoring_missing")
    return not errors, errors


def _case_row(proof: dict[str, Any], case_id: str) -> dict[str, Any]:
    rows = proof.get("case_verifications")
    if not isinstance(rows, list):
        raise FieldAuditError("terminal proof lacks case_verifications")
    matches = [row for row in rows if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise FieldAuditError(f"terminal proof case is not unique: {case_id}")
    return matches[0]


def _input_refs(*refs: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    by_path: dict[str, dict[str, Any]] = {}
    for ref in refs:
        path = str(Path(ref["path"]).resolve())
        existing = by_path.get(path)
        if existing is not None and existing["sha256"] != ref["sha256"]:
            raise FieldAuditError(f"conflicting input reference: {path}")
        by_path[path] = {**ref, "path": path}
    paths = sorted(by_path)
    return paths, {path: by_path[path]["sha256"] for path in paths}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    current_path = path_value(args.current, "CURRENT336")
    closure_path = path_value(args.closure, "ROOT304 closure")
    proof_path = path_value(args.terminal_proof, "ROOT304 terminal proof")
    closure = json_object(closure_path, "ROOT304 closure")
    proof = json_object(proof_path, "ROOT304 terminal proof")
    if closure.get("schema") != CLOSURE_SCHEMA:
        raise FieldAuditError("ROOT304 closure schema differs")
    if closure.get("status") != "PASS_ACTUAL_TERMINAL_METADATA_ACCOUNTING_AND_SOURCE_JOINS":
        raise FieldAuditError("ROOT304 closure is not terminal metadata PASS")
    if sha256_file(current_path) != CURRENT_SHA256:
        raise FieldAuditError("CURRENT336 SHA differs")
    if sha256_file(proof_path) != PROOF_SHA256:
        raise FieldAuditError("ROOT304 terminal proof SHA differs")
    closure_proof = closure.get("terminal_proof")
    if not isinstance(closure_proof, dict) or Path(closure_proof.get("path", "")).resolve() != proof_path:
        raise FieldAuditError("closure does not bind the supplied terminal proof path")
    if require_sha(closure_proof.get("sha256"), "closure terminal proof SHA") != PROOF_SHA256:
        raise FieldAuditError("closure terminal proof SHA differs")
    if proof.get("schema") != PROOF_SCHEMA or proof.get("guarded_receipt_status") != "completed":
        raise FieldAuditError("ROOT304 proof is not a completed root terminal proof")
    case_id = str(args.case_id).strip()
    if not case_id:
        raise FieldAuditError("case-id must be non-empty")
    row = _case_row(proof, case_id)
    if row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise FieldAuditError("selected ROOT304 row is not the expected saved-mask diagnostic")
    summary_path = path_value(row.get("summary"), f"{case_id} summary")
    if sha256_file(summary_path) != require_sha(row.get("summary_sha256"), f"{case_id} summary SHA"):
        raise FieldAuditError("selected summary changed")
    case_manifest_path = path_value(row.get("case_manifest"), f"{case_id} case manifest")
    if sha256_file(case_manifest_path) != require_sha(row.get("case_manifest_sha256"), f"{case_id} case manifest SHA"):
        raise FieldAuditError("selected case manifest changed")
    records = row.get("records_stat_only")
    if not isinstance(records, dict):
        raise FieldAuditError("selected case lacks records_stat_only")
    records_path = path_value(records.get("path"), f"{case_id} records JSONL")
    records_ref = deferred_ref(records_path, "records_jsonl", records)
    trajectory = row.get("source_trajectory")
    if not isinstance(trajectory, dict):
        raise FieldAuditError("selected case lacks source trajectory")
    trajectory_path = path_value(trajectory.get("path"), f"{case_id} trajectory HDF5")
    trajectory_ref = deferred_ref(trajectory_path, "trajectory_h5", {"sha256": trajectory.get("known_sha256"), **trajectory.get("pre_stat", {})})
    worker_path = path_value(args.worker, "field audit worker")
    runtime_path = path_value(args.runtime, "runtime v8")
    dispatch_path = path_value(args.dispatch, "dispatch v8")
    strict_path = path_value(args.strict, "strict dispatch v8")
    config_path = path_value(args.config, "official config")
    venv_declared = Path(args.python).expanduser()
    venv_path = path_value(venv_declared, "literal Python interpreter")
    current_ref = static_ref(current_path, "current336")
    closure_ref = static_ref(closure_path, "root304_closure")
    proof_ref = static_ref(proof_path, "root304_terminal_proof")
    summary_ref = static_ref(summary_path, f"{case_id}_typed_summary", expected_sha=row.get("summary_sha256"))
    manifest_ref = static_ref(case_manifest_path, f"{case_id}_typed_manifest", expected_sha=row.get("case_manifest_sha256"))
    code_ref = static_ref(worker_path, "field_audit_worker")
    runtime_ref = static_ref(runtime_path, "runtime_v8")
    dispatch_ref = static_ref(dispatch_path, "dispatch_v8")
    strict_ref = static_ref(strict_path, "strict_dispatch_v8")
    config_ref = static_ref(config_path, "official_runtime_config")
    python_ref = static_ref(venv_path, "literal_python")
    python_ref["literal_path"] = str(venv_declared)
    python_ref["resolved_path"] = str(venv_path)
    static_paths, static_hashes = _input_refs(
        current_ref, closure_ref, proof_ref, summary_ref, manifest_ref,
        code_ref, runtime_ref, dispatch_ref, strict_ref, config_ref, python_ref,
    )
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "scientific-field-gap-audit-manifest.json"
    request_path = output_dir / "scientific-field-gap-audit-request.json"
    gap_report_path = Path(args.gap_report).expanduser().resolve()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_GUARDED_TYPED_RECORD_FIELD_AUDIT",
        "physical_case_id": case_id,
        "family_id": row.get("family_id"),
        "current_catalog": {"path": str(current_path), "sha256": CURRENT_SHA256, "cases": 336},
        "source_closure": {
            "root304_closure": closure_ref,
            "terminal_proof": proof_ref,
            "case_manifest": manifest_ref,
            "typed_summary": summary_ref,
            "lifecycle_rows": int(closure["coverage"]["exact_current_audit_rows"]),
            "saved_mask_rows": int(closure["coverage"]["actual_saved_mask_cases"]),
        },
        "static_source_refs": [current_ref, closure_ref, proof_ref, manifest_ref, summary_ref, code_ref, runtime_ref, dispatch_ref, strict_ref, config_ref, python_ref],
        "deferred_source_refs": [records_ref, trajectory_ref],
        "records_contract": {
            "schema": "ds02.stage2.typed-lifecycle-records.v4",
            "path": records_ref["path"],
            "known_sha256": records_ref["sha256"],
            "rows": int(records.get("rows", -1)),
            "content_read_by_preparer": False,
            "read_after_reservation": True,
        },
        "trajectory_contract": {
            "path": trajectory_ref["path"],
            "known_sha256": trajectory_ref["sha256"],
            "content_read_by_preparer": False,
            "content_read_by_field_auditor": False,
            "read_after_reservation": False,
        },
        "audit_scope": {
            "checked_from_records": ["identity_uniqueness", "initial_type_role", "initial_mass_finite_positive", "lifecycle_scalar_times_and_brackets", "censoring_and_unknown_object_shape"],
            "not_checked_by_this_worker": ["raw_position_velocity_density_mass_pressure_finiteness", "HDF5_attribute_unit_authority", "MK_or_material_provenance", "continuous_event_time", "physical_fate", "legal_flux", "dynamical_impact"],
            "producer_declarations_only": ["units", "coordinate_frame", "saved_mask_lifecycle"],
        },
        "output": {"path": "{attempt_root}/scientific-field-gap-audit.json", "max_bytes": MAX_OUTPUT_BYTES},
        "read_policy": {"prepare_json_and_stat_only": True, "records_jsonl_opened_after_reservation": True, "trajectory_h5_opened": False, "raw_bi4_opened": False, "solver_started": False, "scientific_Q_credit": 0},
    }
    atomic_json(manifest_path, manifest)
    manifest_ref_for_request = static_ref(manifest_path, "field_audit_manifest")
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "request_id": "scientific-field-gap-audit-v1-root-next-001",
        "family_id": row.get("family_id"),
        "physical_case_id": case_id,
        "attempt_id": "scientific-field-gap-audit-v1-root-next-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "max_memory_bytes": 2 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": MAX_OUTPUT_BYTES,
        "estimated_cpu_core_hours": 0.25,
        "estimated_gpu_seconds": 0,
        "cwd": str(LAB_ROOT),
        "worktree_root": str(LAB_ROOT),
        "command": [str(venv_declared), "-B", str(worker_path), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/scientific-field-gap-audit.json"],
        "input_files": sorted(static_paths + [str(manifest_path)]),
        "input_sha256": {**static_hashes, str(manifest_path): manifest_ref_for_request["sha256"]},
        # The worker audits the already-produced JSONL only.  The HDF5 ref is
        # retained in the manifest as provenance/stat-only evidence, but is
        # deliberately absent from runtime deferred inputs so dispatch cannot
        # open it for this field audit.
        "deferred_input_files": [records_ref["path"]],
        "deferred_input_records": [records_ref],
        "output_files": ["{attempt_root}/scientific-field-gap-audit.json"],
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref_for_request["sha256"]},
        "runtime_binding": {"runtime_v8": runtime_ref, "dispatch_v8": dispatch_ref, "strict_dispatch_v8": strict_ref, "official_config": config_ref},
        "interpreter_binding": {"literal_path": str(venv_declared), "resolved_path": str(venv_path), "sha256": python_ref["sha256"]},
        "source_read_cost": {"records_bytes": records_ref["bytes"], "minimum_records_passes": 3, "minimum_records_bytes": records_ref["bytes"] * 3, "trajectory_h5_bytes_not_read": trajectory_ref["bytes"], "trajectory_h5_passes": 0, "output_cap_bytes": MAX_OUTPUT_BYTES},
        "read_policy": manifest["read_policy"],
        "claim_boundary": {"lifecycle_mask": "saved-record diagnostic only", "unit_authority": "UNKNOWN_UNVERIFIED", "raw_frame_finite_values": "UNKNOWN_NOT_EXPOSED_BY_RECORDS", "material_and_MK": "UNKNOWN_NOT_EXPOSED", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
        "shared_lease_required": True,
        "request_note": "Source-only field audit of one existing typed lifecycle JSONL. It must not open HDF5/BI4 or grant scientific qualification; root must reserve and independently verify terminal accounting.",
    }
    atomic_json(request_path, request)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    report = {
        "schema": "ds02.stage2.scientific-field-gap-report.v1",
        "status": "SOURCE_BOUND_GAP_INVENTORY_NOT_MEASURED",
        "generated_by": str(SCRIPT),
        "current_binding": {"path": str(current_path), "sha256": CURRENT_SHA256, "case_count": 336},
        "lifecycle_product_binding": {"closure": closure_ref, "terminal_proof": proof_ref, "terminal_proof_sha256": PROOF_SHA256, "exact_current_audit_rows": int(closure["coverage"]["exact_current_audit_rows"]), "saved_mask_rows": int(closure["coverage"]["actual_saved_mask_cases"]), "alias_rows": int(closure["coverage"]["historical_alias_unresolved"]), "physical_or_scientific_credit": 0},
        "selected_pilot": {"physical_case_id": case_id, "family_id": row.get("family_id"), "case_manifest": manifest_ref, "typed_summary": summary_ref, "records_stat_only": records_ref, "trajectory_h5_stat_only": trajectory_ref},
        "field_qualification": {
            "lifecycle_mask": {"status": "SOURCE_PRODUCT_PRESENT", "meaning": "saved-frame mask/lifecycle diagnostic", "scientific_credit": 0},
            "raw_frame_finite_values": {"status": "NOT_MEASURED", "reason": "ROOT304 records/stat product does not expose raw per-frame position/velocity/density/mass/pressure values"},
            "unit_authority": {"status": "PRODUCER_DECLARED_ONLY", "declared_status": metadata.get("units_status", "UNKNOWN"), "independent_verification": "NOT_MEASURED"},
            "identity_and_initial_role": {"status": "PRODUCER_RECORDS_REQUIRE_AUDIT", "declared_identity": metadata.get("identity_key", "UNKNOWN"), "MK_material": "NOT_EXPOSED"},
            "initial_mass": {"status": "RECORD_FIELD_AUDIT_PENDING", "source_field": "initial_mass_kg", "role_average_proxy": "FORBIDDEN"},
            "continuous_event_time": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "next_audit": {"request": {"path": str(request_path), "sha256": sha256_file(request_path)}, "manifest": {"path": str(manifest_path), "sha256": manifest_ref_for_request["sha256"]}, "worker_output": "one bounded summary after parent reservation", "deferred_content": ["typed lifecycle records JSONL only"], "forbidden_content": ["trajectory HDF5", "BI4/native output", "solver/CFD"], "expected_minimum_passes": 3},
        "source_read_policy": {"preparer_opened_payload": False, "preparer_hashed_payload": False, "worker_opens_h5": False, "worker_opens_bi4": False, "launch_performed": False},
        "scope_limit": "A lifecycle mask is not a quality, unit, active-finite, material, MK, flux, fate, dynamics, or scientific-qualification result.",
        "goal_complete": False,
    }
    atomic_json(gap_report_path, report)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": manifest_ref_for_request["sha256"], "request": str(request_path), "request_sha256": sha256_file(request_path), "gap_report": str(gap_report_path), "gap_report_sha256": sha256_file(gap_report_path), "physical_case_id": case_id, "records_content_read_by_preparer": False, "trajectory_content_read_by_preparer": False}


def audit(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    manifest = json_object(path_value(manifest_path, "field audit manifest"), "field audit manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_GUARDED_TYPED_RECORD_FIELD_AUDIT":
        raise FieldAuditError("field audit manifest is not guarded-ready")
    records_contract = manifest.get("records_contract")
    if not isinstance(records_contract, dict):
        raise FieldAuditError("records contract missing")
    records_path = path_value(records_contract.get("path"), "deferred records JSONL")
    expected_sha = require_sha(records_contract.get("known_sha256"), "deferred records SHA")
    expected_bytes = int(records_contract.get("bytes", -1))
    pre_stat = stat_ref(records_path, "records_pre")
    if pre_stat["bytes"] != expected_bytes:
        raise FieldAuditError("records byte count changed before audit")
    pre_sha = sha256_file(records_path)
    if pre_sha != expected_sha:
        raise FieldAuditError("records pre-read SHA differs from bound source")
    seen: set[tuple[int, int]] = set()
    header: dict[str, Any] | None = None
    row_count = 0
    invalid_count = 0
    errors: list[str] = []
    with records_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line_number > MAX_RECORD_ROWS + 1:
                raise FieldAuditError("records exceed bounded row limit")
            try:
                value = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise FieldAuditError(f"records line {line_number} is invalid JSON") from exc
            if line_number == 1:
                if not isinstance(value, dict) or value.get("schema") != "ds02.stage2.typed-lifecycle-records.v4":
                    raise FieldAuditError("records header schema differs")
                header = value
                continue
            if not isinstance(value, dict):
                invalid_count += 1
                errors.append(f"line_{line_number}:row_not_object")
                continue
            row_count += 1
            valid, row_errors = validate_record(header or {}, value, seen)
            if not valid:
                invalid_count += 1
                if len(errors) < 20:
                    errors.append(f"line_{line_number}:{'|'.join(row_errors)}")
    if header is None:
        raise FieldAuditError("records JSONL is empty")
    post_stat = stat_ref(records_path, "records_post")
    post_sha = sha256_file(records_path)
    stat_keys = ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
    if any(pre_stat.get(key) != post_stat.get(key) for key in stat_keys) or post_sha != pre_sha:
        raise FieldAuditError("records changed during field audit")
    output = {
        "schema": WORKER_SCHEMA,
        "status": "COMPLETED_RECORD_FIELD_AUDIT_NO_SCIENTIFIC_CREDIT" if invalid_count == 0 else "COMPLETED_RECORD_FIELD_AUDIT_WITH_SCHEMA_FAILURES",
        "physical_case_id": manifest.get("physical_case_id"),
        "family_id": manifest.get("family_id"),
        "records": {"path": str(records_path), "known_sha256": expected_sha, "pre_sha256": pre_sha, "post_sha256": post_sha, "pre_stat": pre_stat, "post_stat": post_stat, "rows": row_count, "unique_identity_rows": len(seen)},
        "checks": {"header_schema": header.get("schema"), "identity_unique": len(seen) == row_count, "initial_mass_and_role_scalar_fields": "CHECKED", "lifecycle_scalar_time_and_bracket_fields": "CHECKED", "raw_frame_value_finiteness": "NOT_EXPOSED_BY_RECORDS", "unit_authority": "PRODUCER_DECLARED_ONLY", "material_and_MK": "NOT_EXPOSED"},
        "invalid_row_count": invalid_count,
        "sample_errors": errors,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "claim_boundary": {"native_exit_cause": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN", "continuous_event_time": "UNKNOWN"},
        "read_policy": {"records_jsonl_opened_after_reservation": True, "records_hash_passes": 2, "trajectory_h5_opened": False, "raw_bi4_opened": False, "solver_started": False},
        "source_read_cost": {"records_pre_hash_bytes": pre_stat["bytes"], "records_stream_bytes_lower_bound": pre_stat["bytes"], "records_post_hash_bytes": post_stat["bytes"], "minimum_records_passes": 3, "wall_seconds": time.monotonic() - started},
    }
    atomic_json(output_path, output, max_bytes=MAX_OUTPUT_BYTES)
    return {"status": output["status"], "output": str(Path(output_path).resolve()), "rows": row_count, "invalid_rows": invalid_count, "records_sha256": pre_sha}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prepare_parser.add_argument("--closure", type=Path, default=CLOSURE_DEFAULT)
    prepare_parser.add_argument("--terminal-proof", type=Path, default=PROOF_DEFAULT)
    prepare_parser.add_argument("--case-id", default="F7_OBSTACLE_QUINTIC_B08_A036P5")
    prepare_parser.add_argument("--worker", type=Path, default=SCRIPT)
    prepare_parser.add_argument("--runtime", type=Path, default=RUNTIME_DEFAULT)
    prepare_parser.add_argument("--dispatch", type=Path, default=DISPATCH_DEFAULT)
    prepare_parser.add_argument("--strict", type=Path, default=STRICT_DEFAULT)
    prepare_parser.add_argument("--config", type=Path, default=CONFIG_DEFAULT)
    prepare_parser.add_argument("--python", type=Path, default=VENV_DEFAULT)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    prepare_parser.add_argument("--gap-report", type=Path, required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--manifest", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(args) if args.command == "prepare" else audit(args.manifest, args.output)
    except (FieldAuditError, OSError) as exc:
        print(f"scientific-field-gap-audit: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
