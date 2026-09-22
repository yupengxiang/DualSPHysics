#!/usr/bin/env python3
"""Build a read-only F4 tallwall120 T2 acceptance bridge.

This bridge closes an engineering interface around the retained F4 material
evidence without turning that interface into a scientific qualification.  It
reads JSON receipts and source text only.  It deliberately does not open an
HDF5 path copied into an evidence record, start a solver/GPU/queue task, or
write an existing registry, ledger, matrix, threshold, denominator, or
evidence file.

The output has two distinct products:

* ``engineering_receipt`` records that the input hashes, case/matrix gap
  enumeration, and recovery semantics were bound into a reproducible
  read-only snapshot.
* ``formal_acceptance_receipt`` is the scientific result.  It is fail-closed
  and remains ``blocked`` with credit ``0`` while the registered unknown,
  event-window, CDF, residence, per-case, recovery, or matrix gates are
  missing or failing.

The F3 bridge is used only as a contract-design reference.  Its F3 CDF
threshold is never imported as an F4 threshold.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "core.material.f4.tallwall120.t2_acceptance_bridge.v1"
ENGINEERING_RECEIPT_SCHEMA = "core.material.f4.tallwall120.engineering_receipt.v1"
FORMAL_RECEIPT_SCHEMA = "core.material.f4.tallwall120.scientific_acceptance_receipt.v1"
GAP_SCHEMA = "core.material.f4.tallwall120.t2_admission_acceptance_gap_audit.v1"
MIGRATION_SCHEMA = "core.material.family_migration_spec.v1"
MATRIX_SCHEMA = "core.material.f4_matrix_mapping.v1"

UNKNOWN_LIMIT = 0.01
FULL_WINDOW_S = 4.34
MAXIMUM_WINDOW_S = 8.68
RESIDENCE_GRAVITY_TIME_S = 0.3497487083913345
EVENT_ENDPOINT_TOLERANCE_M = 1.0e-8
SAVED_CHORD_CROSSINGS_ALLOWED = 0
F3_REFERENCE_CDF_LIMIT = 0.02

TALLWALL_TRACE_SCHEMA = "core.material.f4.tallwall120.v1"
TALLWALL_CHECKPOINT_SCHEMA = "core.material.f4.tallwall120.checkpoint.v2"

DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260922-v3.json"
)
DEFAULT_REPORT_NAME = "reports/F4-TALLWALL120-T2-ACCEPTANCE-BRIDGE-2026-09-22-v3.zh-CN.md"


# These are intentionally a new namespace.  The bridge reads the old gap
# audit and retained material evidence, but never rewrites any of them.
INPUTS: dict[str, Path] = {
    "t2_gap_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f4-tallwall120-t2-admission-acceptance-gap-audit-20260922-v2.json"
    ),
    "macro_sidecar_preflight": Path(
        "campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-20260920.json"
    ),
    "migration_spec": Path(
        "campaigns/core-v1/material/evidence/f4-resting-pool-migration-spec-2026-09-19.json"
    ),
    "matrix_review": Path(
        "campaigns/core-v1/material/evidence/f4-resting-pool-33-to-15-matrix-review-2026-09-19.json"
    ),
    "material_preflight": Path(
        "campaigns/core-v1/material/evidence/"
        "f4-tallwall120-native-cell14-material-preflight-20260921.json"
    ),
    "trace_result": Path(
        "campaigns/core-v1/material/evidence/"
        "f4-tallwall120-native-cell14-material-preflight-20260921.trace.json"
    ),
    "trace_diagnosis": Path(
        "campaigns/core-v1/material/evidence/"
        "f4-tallwall120-native-cell14-material-preflight-20260921.diagnosis.json"
    ),
    "full_source_contract": Path(
        "campaigns/core-v1/material/evidence/"
        "f4-tallwall120-native-cell14-f4-ess32-full-source-canary-contract-20260921.json"
    ),
    "root_review": Path(
        "campaigns/core-v1/material/evidence/"
        "f4-tallwall120-native-cell14-f4-ess32-root-review-20260921.json"
    ),
    "candidate_contract": Path(
        "campaigns/core-v1/material/evidence/"
        "f4-tallwall120-native-cell14-candidate-contract-20260921.json"
    ),
    "negative_evidence": Path(
        "campaigns/core-v1/material/evidence/f4-material-negative-evidence-audit-20260920.json"
    ),
    "admission_contract": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-f4-t2-admission-root-review-contract-20260921.json"
    ),
    "core_material": Path("scripts/core_material.py"),
    "core_material_acceptance": Path("scripts/core_material_acceptance.py"),
    "macro_sidecar_preflight_code": Path("scripts/f4_macro_t2_sidecar_preflight_v1.py"),
    "tallwall_material_code": Path("scripts/f4_tallwall120_material.py"),
    "tallwall_preflight_code": Path("scripts/f4_tallwall120_material_preflight_v1.py"),
    "t1_evaluator_manifest": Path("campaigns/core-v1/cfd/f4-tallwall120-qualification-evaluator-v2.json"),
    "t1_evaluator_code": Path("scripts/f4_tallwall_qualification_evaluator_v2.py"),
    # Design reference only; the F3 threshold is explicitly not an F4 gate.
    "f3_bridge_reference": Path("scripts/f3_native_mls_acceptance_bridge_v1.py"),
    "f3_bridge_reference_receipt": Path(
        "campaigns/core-v1/material/evidence/f3-native-mls-acceptance-bridge-v1-20260921.json"
    ),
    "f3_bridge_report_reference": Path("reports/F3-NATIVE-MLS-ACCEPTANCE-BRIDGE-2026-09-21.zh-CN.md"),
    "gap_audit_report_reference": Path(
        "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-22-v2.zh-CN.md"
    ),
    "material_root_cause_report_reference": Path(
        "reports/F4-TALLWALL120-MATERIAL-ROOT-CAUSE-AUDIT-2026-09-21.zh-CN.md"
    ),
    "macro_preflight_report_reference": Path("reports/F4-MACRO-T2-SIDECAR-PREFLIGHT-2026-09-20.md"),
    "admission_report_reference": Path("reports/F3-F4-T2-ADMISSION-CONTRACT-2026-09-21.zh-CN.md"),
    "bridge_implementation": Path(__file__),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_path(lab_root: Path, value: str | Path) -> Path:
    value_path = Path(value)
    if value_path.is_absolute():
        return value_path
    root = Path(lab_root).resolve()
    candidates = (root / value_path, root.parent / value_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _display_path(lab_root: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(lab_root).resolve()))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _bind_file(lab_root: Path, value: str | Path, role: str) -> dict[str, Any]:
    path = _resolve_path(lab_root, value)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": _display_path(lab_root, path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "role": role,
    }


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be finite") from error
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _require_equal(actual: Any, expected: Any, name: str) -> None:
    if actual != expected:
        raise ValueError(f"{name} drifted: expected {expected!r}, got {actual!r}")


def _bool(value: Any) -> bool:
    return value is True


def _validate_read_only_constraints(value: dict[str, Any], label: str) -> None:
    constraints = value.get("execution_constraints")
    if not isinstance(constraints, dict):
        raise ValueError(f"{label} has no execution_constraints")
    for name in (
        "solver_started",
        "gpu_started",
        "new_job_submitted",
        "thresholds_changed",
        "old_evidence_overwritten",
        "scientific_denominator_changed",
    ):
        if constraints.get(name) is True:
            raise ValueError(f"{label} violates read-only boundary: {name}")
    for name in (
        "queue_mutation",
        "registry_mutation",
        "central_ledger_mutation",
        "ledger_mutation",
        "matrix_mutation",
    ):
        if constraints.get(name) not in (None, 0, False):
            raise ValueError(f"{label} has nonzero mutation: {name}")


def _validate_gap_identity(gap: dict[str, Any]) -> None:
    _require_equal(gap.get("schema"), GAP_SCHEMA, "upstream gap schema")
    _require_equal(gap.get("qualification_claim"), "none", "upstream qualification claim")
    _require_equal(gap.get("qualification_credit"), "none", "upstream qualification credit")
    _require_equal(gap.get("T2_macro"), False, "upstream T2_macro")
    _require_equal(gap.get("T2_path"), False, "upstream T2_path")
    _validate_read_only_constraints(gap, "upstream gap audit")


def _validate_registered_contracts(
    gap: dict[str, Any], migration: dict[str, Any], matrix_review: dict[str, Any]
) -> dict[str, Any]:
    _require_equal(migration.get("schema"), MIGRATION_SCHEMA, "migration schema")
    _require_equal(matrix_review.get("schema"), MATRIX_SCHEMA, "matrix schema")
    gates = gap.get("registered_gates")
    if not isinstance(gates, dict):
        raise ValueError("gap audit has no registered_gates")
    _require_equal(_finite(gates.get("unknown_fraction_per_source_max"), "unknown limit"), UNKNOWN_LIMIT, "unknown limit")
    _require_equal(_finite(gates.get("f4_full_event_window_s"), "F4 event window"), FULL_WINDOW_S, "F4 event window")
    _require_equal(
        _finite(gates.get("f4_maximum_right_censored_extension_s"), "F4 maximum window"),
        MAXIMUM_WINDOW_S,
        "F4 maximum window",
    )
    migration_gates = migration.get("f4_gates")
    if not isinstance(migration_gates, dict):
        raise ValueError("migration spec has no f4_gates")
    _require_equal(
        _finite(migration_gates.get("material_unknown_fraction_max"), "migration unknown limit"),
        UNKNOWN_LIMIT,
        "migration unknown limit",
    )
    event = migration.get("event_definition")
    if not isinstance(event, dict):
        raise ValueError("migration spec has no event_definition")
    post_return = event.get("post_return_window")
    if not isinstance(post_return, dict):
        raise ValueError("migration spec has no post_return_window")
    _require_equal(_finite(post_return.get("initial_horizon_s"), "initial horizon"), FULL_WINDOW_S, "initial horizon")
    _require_equal(
        _finite(post_return.get("maximum_extended_horizon_s"), "maximum horizon"),
        MAXIMUM_WINDOW_S,
        "maximum horizon",
    )
    _require_equal(
        _finite(migration_gates.get("closed_wall_endpoint_tolerance_m"), "endpoint tolerance"),
        EVENT_ENDPOINT_TOLERANCE_M,
        "endpoint tolerance",
    )
    _require_equal(
        migration_gates.get("saved_chord_crossings_allowed"),
        SAVED_CHORD_CROSSINGS_ALLOWED,
        "saved chord crossings",
    )
    observed_cdf = gap.get("observed_gate_comparison", {}).get("cdf", {})
    if not isinstance(observed_cdf, dict):
        raise ValueError("gap audit has no CDF comparison")
    # This is the important family boundary: an F3 limit must not be silently
    # promoted to an F4 limit.
    _require_equal(observed_cdf.get("f4_limit_registered"), False, "F4 CDF registration")
    _require_equal(observed_cdf.get("f4_acceptance_limit_available"), False, "F4 CDF availability")
    return {
        "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
        "f4_cdf_tolerance": None,
        "f4_cdf_tolerance_registered": False,
        "full_event_window_s": FULL_WINDOW_S,
        "maximum_right_censored_extension_s": MAXIMUM_WINDOW_S,
        "residence_gravity_time_s": RESIDENCE_GRAVITY_TIME_S,
        "closed_wall_endpoint_tolerance_m": EVENT_ENDPOINT_TOLERANCE_M,
        "saved_chord_crossings_allowed": SAVED_CHORD_CROSSINGS_ALLOWED,
        "right_censored_is_not_acceptance": True,
        "no_partial_credit": True,
        "denominator_policy": gates.get("denominator_policy"),
    }


def _verify_inherited_bindings(lab_root: Path, bindings: Any) -> dict[str, Any]:
    if not isinstance(bindings, dict):
        raise ValueError("upstream gap audit has no input_bindings")
    checked = 0
    failures: list[str] = []
    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            failures.append(f"{name}: binding is not an object")
            continue
        path_value = binding.get("path")
        path = _resolve_path(lab_root, path_value) if isinstance(path_value, str) else Path("<missing>")
        if not path.is_file():
            failures.append(f"{name}: missing {path}")
            continue
        checked += 1
        if path.stat().st_size != binding.get("bytes"):
            failures.append(f"{name}: byte count changed")
        if sha256_file(path) != binding.get("sha256"):
            failures.append(f"{name}: SHA-256 changed")
    return {
        "record_count": len(bindings),
        "checked_count": checked,
        "pass": not failures and checked == len(bindings),
        "failures": failures,
        "role": "revalidated upstream JSON/source/report hash closure; no HDF5 opened",
    }


def _result_field_presence(result: dict[str, Any]) -> dict[str, Any]:
    source_rows = result.get("by_source")
    source_rows = source_rows if isinstance(source_rows, list) else []
    cdf_names = ("contact_cdf", "upward_cdf", "return_cdf", "residence_cdf")
    cdf_complete = bool(source_rows) and all(
        isinstance(row, dict) and all(name in row for name in cdf_names) for row in source_rows
    )
    residence_complete = bool(source_rows) and all(
        isinstance(row, dict)
        and "residence_cdf" in row
        and "residence_mean_s" in row
        and "right_censored_fraction" in row
        for row in source_rows
    )
    return {
        "source_row_count": len(source_rows),
        "cdf_fields_present": cdf_complete,
        "residence_fields_present": residence_complete,
        "event_fields_present": all(
            name in result for name in ("event_window_complete", "event_window_status", "committed_time_s")
        ),
        "cdf_event_names": list(cdf_names) if cdf_complete else [],
    }


def _build_case_gaps(
    lab_root: Path, gap: dict[str, Any], material_preflight: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    cases = gap.get("case_sidecars", {}).get("cases")
    if not isinstance(cases, list) or len(cases) != 6:
        raise ValueError("F4 bridge expects the six retained gap-audit case rows")
    case_rows: list[dict[str, Any]] = []
    result_bindings: dict[str, Any] = {}
    checkpoint_bindings: dict[str, Any] = {}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} is not an object")
        result_path = case.get("result_path")
        result_file = _resolve_path(lab_root, result_path)
        result = _load_json(result_file) if result_file.is_file() else {}
        result_key = f"case_{index:02d}_result"
        result_bindings[result_key] = _bind_file(lab_root, result_path, "retained F4 case result sidecar")
        checkpoint = case.get("checkpoint") if isinstance(case.get("checkpoint"), dict) else {}
        checkpoint_path = checkpoint.get("manifest_path")
        checkpoint_key = f"case_{index:02d}_checkpoint_manifest"
        if isinstance(checkpoint_path, str) and checkpoint_path:
            checkpoint_file = _resolve_path(lab_root, checkpoint_path)
            if checkpoint_file.is_file():
                checkpoint_bindings[checkpoint_key] = _bind_file(
                    lab_root, checkpoint_path, "retained F4 checkpoint manifest"
                )
        presence = _result_field_presence(result)
        unknown = _finite(case.get("unknown_fraction_max"), f"case {index} unknown fraction")
        event_complete = _bool(case.get("event_window_complete"))
        recovery_integrity = _bool(checkpoint.get("checkpoint_pass_from_case_audit")) and _bool(
            checkpoint.get("state_hash_pass_from_case_audit")
        )
        case_blockers: list[str] = []
        if unknown > UNKNOWN_LIMIT:
            case_blockers.append(
                f"unknown fraction {unknown} exceeds the fixed {UNKNOWN_LIMIT} per-source limit"
            )
        if not event_complete:
            case_blockers.append(
                "event window is incomplete/right-censored; the retained result is not a terminal full-window result"
            )
        if not presence["cdf_fields_present"]:
            case_blockers.append("contact/upward/return/residence CDF fields are incomplete in the case sidecar")
        if not presence["residence_fields_present"]:
            case_blockers.append("residence CDF/mean/right-censor fields are incomplete in the case sidecar")
        case_blockers.append("no registered F4 numerical CDF tolerance is available; F3's 0.02 is not imported")
        if not recovery_integrity:
            case_blockers.append("checkpoint/hash integrity is not closed in the retained case audit")
        if not _bool(case.get("acceptance_receipt_present")):
            case_blockers.append("formal per-case material acceptance receipt is absent")
        case_rows.append(
            {
                "case_index": index,
                "canary_id": case.get("canary_id"),
                "case_id": case.get("case_id"),
                "result_binding_key": result_key,
                "result_schema": result.get("schema"),
                "result_status": result.get("status", case.get("result_status")),
                "seed_denominator": case.get("seed_denominator"),
                "unknown": {
                    "observed_fraction_max": unknown,
                    "limit": UNKNOWN_LIMIT,
                    "gate_pass": unknown <= UNKNOWN_LIMIT,
                    "denominator_policy": "all geometric seeds carrying the declared source label; unknown remains in denominator",
                },
                "event_window": {
                    "observed_complete": event_complete,
                    "observed_status": case.get("event_window_status"),
                    "required_initial_window_s": FULL_WINDOW_S,
                    "maximum_extension_s": MAXIMUM_WINDOW_S,
                    "gate_pass": event_complete,
                },
                "cdf": {
                    "fields_present": presence["cdf_fields_present"],
                    "event_names": presence["cdf_event_names"],
                    "f4_tolerance_registered": False,
                    "gate_pass": False,
                    "status": "blocked_missing_registered_f4_tolerance",
                    "numeric_comparison": "not_claimed_from_retained_sidecar",
                },
                "residence": {
                    "fields_present": presence["residence_fields_present"],
                    "gravity_time_s": RESIDENCE_GRAVITY_TIME_S,
                    "tolerance_registered": False,
                    "acceptance_gate_implemented": False,
                    "gate_pass": False,
                },
                "mass_closure": {
                    "observed": _bool(case.get("mass_closed")),
                    "gate_pass": _bool(case.get("mass_closed")),
                },
                "recovery": {
                    "checkpoint_binding_key": checkpoint_key if checkpoint_key in checkpoint_bindings else None,
                    "checkpoint_integrity_pass": recovery_integrity,
                    "committed_frame": checkpoint.get("committed_frame"),
                    "result_committed_frame": checkpoint.get("result_committed_frame"),
                    "committed_frame_matches_result": _bool(checkpoint.get("committed_frame_matches_result")),
                    "content_addressed_generation": _bool(checkpoint.get("content_addressed_generation")),
                    "generation_hash_pass": _bool(checkpoint.get("generation_hash_pass")),
                    "result_references_checkpoint": _bool(checkpoint.get("result_references_checkpoint")),
                },
                "formal_acceptance_receipt_present": _bool(case.get("acceptance_receipt_present")),
                "scientific_status": "blocked",
                "credit": 0,
                "blocking_gaps": case_blockers,
            }
        )
    summary = {
        "case_count": len(case_rows),
        "result_sidecar_count": len(result_bindings),
        "checkpoint_manifest_count": len(checkpoint_bindings),
        "unknown_maximum_observed": max(row["unknown"]["observed_fraction_max"] for row in case_rows),
        "unknown_all_pass": all(row["unknown"]["gate_pass"] for row in case_rows),
        "event_window_complete_count": sum(row["event_window"]["observed_complete"] for row in case_rows),
        "cdf_fields_complete_count": sum(row["cdf"]["fields_present"] for row in case_rows),
        "residence_fields_complete_count": sum(row["residence"]["fields_present"] for row in case_rows),
        "mass_closed_count": sum(row["mass_closure"]["observed"] for row in case_rows),
        "formal_acceptance_receipt_count": sum(
            row["formal_acceptance_receipt_present"] for row in case_rows
        ),
        "interpretation": (
            "A checkpoint/hash pass is engineering recovery evidence only. It does not replace a terminal "
            "full-window material result or a formal scientific acceptance receipt."
        ),
    }
    source_snapshot = {
        "trace_schema": material_preflight.get("code", {}).get("tracer", {}).get("role"),
        "preflight_status": material_preflight.get("status"),
        "preflight_scope_id": material_preflight.get("scope_id"),
    }
    return case_rows, summary, {
        "result_bindings": result_bindings,
        "checkpoint_bindings": checkpoint_bindings,
        "source_snapshot": source_snapshot,
    }


def _matrix_gaps(matrix_review: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    template = matrix_review.get("full_t2_33_overlay_template")
    if not isinstance(template, dict):
        raise ValueError("matrix review has no full_t2_33_overlay_template")
    resolution = template.get("resolution_substep_rows")
    cadence = template.get("cadence_rows")
    seeds = template.get("seed_density_rows")
    if not all(isinstance(rows, list) for rows in (resolution, cadence, seeds)):
        raise ValueError("matrix review has incomplete row lists")
    if len(resolution) != 24 or len(cadence) != 4 or len(seeds) != 5:
        raise ValueError("matrix review row counts drifted from the registered 24+4+5 template")
    rows: list[dict[str, Any]] = []
    for row_index, item in enumerate(resolution):
        rows.append(
            {
                "matrix_row": row_index,
                "axis": "resolution_substep",
                "registered": dict(item),
                "source_available": _bool(item.get("source_available")),
                "source_cfd_cell": item.get("source_cfd_cell"),
                "formal_acceptance_receipt_present": False,
                "status": "blocked_pending_material_overlay",
                "blocking_gap": (
                    "source CFD cell is mapped, but no completed material overlay and no formal receipt exist; "
                    "source availability is not qualification"
                ),
                "credit": 0,
            }
        )
    for offset, item in enumerate(cadence, start=24):
        rows.append(
            {
                "matrix_row": offset,
                "axis": "cadence",
                "registered": dict(item),
                "source_available": _bool(item.get("source_available_exact")),
                "source_cfd_cell": item.get("source_cfd_cell"),
                "formal_acceptance_receipt_present": False,
                "status": "blocked_missing_exact_cfd_source",
                "blocking_gap": item.get("reason") or "exact cadence source is not available",
                "credit": 0,
            }
        )
    for offset, item in enumerate(seeds, start=28):
        rows.append(
            {
                "matrix_row": offset,
                "axis": "seed_density",
                "registered": dict(item),
                "source_available": _bool(item.get("source_available")),
                "source_cfd_cell": item.get("source_cfd_cell"),
                "formal_acceptance_receipt_present": False,
                "status": "blocked_pending_seed_density_overlay",
                "blocking_gap": item.get("status") or "4096-seed material overlay is pending",
                "credit": 0,
            }
        )
    _require_equal(len(rows), 33, "registered material matrix row count")
    summary = {
        "registered_row_count": len(rows),
        "registered_row_order": [row["matrix_row"] for row in rows],
        "resolution_substep_rows": 24,
        "cadence_rows": 4,
        "seed_density_rows": 5,
        "formal_acceptance_receipt_count": 0,
        "material_matrix_ready": False,
        "gap_row_count": len(rows),
        "category_status_counts": {
            "resolution_substep": 24,
            "cadence": 4,
            "seed_density": 5,
        },
        "diagnostic_rows_do_not_upgrade_t2": True,
        "interpretation": matrix_review.get("interpretation"),
        "rows": rows,
    }
    return rows, summary


def _inspect_code_contracts(sources: dict[str, str]) -> dict[str, Any]:
    core = sources["core_material"]
    acceptance = sources["core_material_acceptance"]
    macro = sources["macro_sidecar_preflight_code"]
    tallwall = sources["tallwall_material_code"]
    preflight = sources["tallwall_preflight_code"]
    return {
        "core_material": {
            "residence_cdf_summary": "residence_cdf" in core,
            "event_window_summary": "event_window_complete" in core,
            "content_addressed_generation": "content-addressed" in core,
        },
        "core_material_acceptance": {
            "tallwall_schema": TALLWALL_TRACE_SCHEMA in acceptance,
            "tallwall_checkpoint_v2": TALLWALL_CHECKPOINT_SCHEMA in acceptance,
            "residence_gate": "residence_cdf" in acceptance,
            "event_tolerance_gate": "saved_chord_crossings_allowed" in acceptance
            or "closed_wall_endpoint_tolerance_m" in acceptance,
            "generation_gate": "generation_count_policy" in acceptance,
            "matrix_gate": "f4_matrix" in acceptance or "matrix_review" in acceptance,
        },
        "macro_sidecar_preflight": {
            "acceptance_adapter_called": "audit_material_h5" in macro,
            "f4_residence_gate": "residence_cdf" in macro,
            "f4_event_tolerance_gate": "closed_wall_endpoint_tolerance_m" in macro,
            "per_case_acceptance": "acceptance_receipt" in macro,
        },
        "tallwall_material": {
            "tallwall_schema": TALLWALL_TRACE_SCHEMA in tallwall,
            "tallwall_checkpoint_v2": TALLWALL_CHECKPOINT_SCHEMA in tallwall,
            "content_addressed_generation": "content-addressed" in tallwall,
        },
        "tallwall_preflight": {
            "read_only_source_contract": "read_only" in preflight,
            "event_window_gate": "event_window_complete" in preflight,
        },
        "bridge_boundary": {
            "existing_acceptance_surface_is_incomplete": not (
                TALLWALL_TRACE_SCHEMA in acceptance
                and TALLWALL_CHECKPOINT_SCHEMA in acceptance
                and "residence_cdf" in acceptance
                and "generation_count_policy" in acceptance
            ),
            "f3_cdf_threshold_imported_as_f4": False,
        },
    }


def _recovery_semantics(
    trace: dict[str, Any], full_source: dict[str, Any], root_review: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    execution = full_source.get("execution") if isinstance(full_source.get("execution"), dict) else {}
    resume = execution.get("resume_policy") if isinstance(execution.get("resume_policy"), dict) else {}
    source_window = full_source.get("source_window") if isinstance(full_source.get("source_window"), dict) else {}
    review_decision = root_review.get("review_decision") if isinstance(root_review.get("review_decision"), dict) else {}
    route = full_source.get("route_decision") if isinstance(full_source.get("route_decision"), dict) else {}
    contract_bound = bool(
        resume
        and source_window
        and resume.get("recovery_point") is not None
        and resume.get("checkpoint_every_native_frame") is True
        and "append-only" in str(resume.get("generation_policy", ""))
        and resume.get("rerun_from_zero_after_interruption") is False
    )
    authorized = _bool(review_decision.get("authorized_one_cpu_only")) and _bool(
        route.get("automatic_execution")
    )
    return {
        "contract_bound": contract_bound,
        "contract_schema": full_source.get("schema"),
        "frame_start": source_window.get("frame_start"),
        "frame_end": source_window.get("frame_end"),
        "required_time_end_s": source_window.get("time_end_s"),
        "recovery_boundary_frame": resume.get("recovery_point"),
        "checkpoint_every_native_frame": _bool(resume.get("checkpoint_every_native_frame")),
        "generation_policy": resume.get("generation_policy"),
        "rerun_from_zero_after_interruption": resume.get("rerun_from_zero_after_interruption"),
        "resume_rule": resume.get("after_interruption"),
        "old_trace_reuse": execution.get("existing_trace_reuse", {}).get("reason")
        if isinstance(execution.get("existing_trace_reuse"), dict)
        else None,
        "candidate_output_stem_is_new": _bool(execution.get("output_stem_is_new")),
        "execution_authorized_now": authorized,
        "root_review_authorized_one_cpu_only": _bool(review_decision.get("authorized_one_cpu_only")),
        "automatic_execution": _bool(route.get("automatic_execution")),
        "candidate_id": candidate.get("contracts", {}).get("f4_ess32_v2", {}).get("candidate_id", "f4_ess32_v2"),
        "candidate_status": full_source.get("status"),
        "counterfactual_survivors": full_source.get("candidate", {})
        .get("one_transition_counterfactual", {})
        .get("counterfactual_cohort_survivors"),
        "historical_trace": {
            "committed_frame": trace.get("committed_frame"),
            "committed_time_s": trace.get("committed_time_s"),
            "event_window_complete": _bool(trace.get("event_window_complete")),
            "event_window_status": trace.get("event_window_status"),
            "source_h5_reopened_by_bridge": False,
            "source_h5_rehashed_by_bridge": False,
        },
        "recovery_acceptance_receipt_present": False,
        "scientific_effect": "none; recovery contract binding is not a T2 qualification",
    }


def _reference_boundary(f3_bridge: dict[str, Any], f3_report: str) -> dict[str, Any]:
    # Only report the design boundary.  No F3 result is used to score F4.
    f3_limit = F3_REFERENCE_CDF_LIMIT
    _require_equal(
        f3_bridge.get("schema"),
        "core.material.f3.native_volume_mls.acceptance_bridge.v1",
        "F3 reference bridge schema",
    )
    # Keep the report argument in the function contract so the reference
    # report remains hash-bound even though its prose is not used for scoring.
    _ = f3_report
    return {
        "reference_schema": f3_bridge.get("schema"),
        "reference_receipt_status": f3_bridge.get("status"),
        "reference_f3_cdf_limit": f3_limit,
        "applied_to_f4": False,
        "reason": "F4 migration/gap evidence has no registered numerical CDF tolerance; borrowing F3's limit would change family gates",
    }


def build_bridge(lab_root: Path, created_at_utc: str | None = None) -> dict[str, Any]:
    """Build a fail-closed bridge from JSON/source inputs without opening HDF5."""
    lab_root = Path(lab_root).resolve()
    bound_inputs = {
        name: _bind_file(lab_root, value, "F4 bridge JSON/source/report input")
        for name, value in INPUTS.items()
    }
    loaded = {
        name: _load_json(_resolve_path(lab_root, value))
        for name, value in INPUTS.items()
        if name
        in {
            "t2_gap_audit",
            "macro_sidecar_preflight",
            "migration_spec",
            "matrix_review",
            "material_preflight",
            "trace_result",
            "full_source_contract",
            "root_review",
            "candidate_contract",
            "negative_evidence",
            "admission_contract",
        }
    }
    sources = {
        name: _resolve_path(lab_root, value).read_text(encoding="utf-8")
        for name, value in INPUTS.items()
        if name
        in {
            "core_material",
            "core_material_acceptance",
            "macro_sidecar_preflight_code",
            "tallwall_material_code",
            "tallwall_preflight_code",
        }
    }
    gap = loaded["t2_gap_audit"]
    migration = loaded["migration_spec"]
    matrix_review = loaded["matrix_review"]
    material_preflight = loaded["material_preflight"]
    trace = loaded["trace_result"]
    full_source = loaded["full_source_contract"]
    root_review = loaded["root_review"]
    candidate = loaded["candidate_contract"]
    macro_preflight = loaded["macro_sidecar_preflight"]
    f3_bridge = loaded["f3_bridge_reference_receipt"] if "f3_bridge_reference_receipt" in loaded else _load_json(
        _resolve_path(lab_root, INPUTS["f3_bridge_reference_receipt"])
    )
    f3_report_text = _resolve_path(lab_root, INPUTS["f3_bridge_report_reference"]).read_text(encoding="utf-8")

    _validate_gap_identity(gap)
    fixed_gates = _validate_registered_contracts(gap, migration, matrix_review)
    upstream_hash_closure = _verify_inherited_bindings(lab_root, gap.get("input_bindings"))
    code_contracts = _inspect_code_contracts(sources)
    case_rows, case_summary, case_bindings = _build_case_gaps(lab_root, gap, material_preflight)
    matrix_rows, matrix_summary = _matrix_gaps(matrix_review)
    recovery = _recovery_semantics(trace, full_source, root_review, candidate)

    observed = gap.get("observed_gate_comparison", {})
    observed_unknown = observed.get("unknown_mass", {}) if isinstance(observed, dict) else {}
    observed_event = observed.get("event_window", {}) if isinstance(observed, dict) else {}
    observed_residence = observed.get("residence", {}) if isinstance(observed, dict) else {}
    material_gate = material_preflight.get("gate_evaluation", {})
    trace_schema_binding = (
        trace.get("schema") == TALLWALL_TRACE_SCHEMA
        and trace.get("checkpoint_schema") == TALLWALL_CHECKPOINT_SCHEMA
    )
    f4_cdf_tolerance_registered = bool(fixed_gates["f4_cdf_tolerance_registered"])
    acceptance_gates = {
        "trace_checkpoint_schema_binding": trace_schema_binding,
        "upstream_hash_closure": upstream_hash_closure["pass"],
        "all_retained_cases_mass_closed": case_summary["mass_closed_count"] == case_summary["case_count"],
        "per_source_unknown_fraction": case_summary["unknown_all_pass"],
        "full_event_window": case_summary["event_window_complete_count"] == case_summary["case_count"],
        "f4_cdf_tolerance_registered": f4_cdf_tolerance_registered,
        "f4_cdf_qualification": False,
        "residence_fields_and_acceptance": (
            case_summary["residence_fields_complete_count"] == case_summary["case_count"]
            and bool(observed_residence.get("residence_tolerance_acceptance"))
        ),
        "event_tolerance_acceptance": bool(observed.get("event_tolerance", {}).get("acceptance_enforced")),
        "per_case_formal_acceptance_receipts": (
            case_summary["formal_acceptance_receipt_count"] == case_summary["case_count"]
        ),
        "recovery_contract_bound": recovery["contract_bound"],
        "recovery_acceptance_receipt": recovery["recovery_acceptance_receipt_present"],
        "material_matrix_formal_receipts": False,
        "material_matrix_ready": False,
        "root_authorized_execution": recovery["execution_authorized_now"],
    }
    scientific_pass = all(acceptance_gates.values())

    blocking_reasons = [
        f"per-case unknown gate fails: maximum observed {case_summary['unknown_maximum_observed']} > {UNKNOWN_LIMIT}",
        f"full event window fails: {case_summary['event_window_complete_count']}/{case_summary['case_count']} retained cases are complete; right-censored paths remain in the denominator",
        "F4 has no registered numerical CDF tolerance; the F3 bridge's 0.02 threshold is reference-only and is not applied",
        f"only {case_summary['cdf_fields_complete_count']}/{case_summary['case_count']} case sidecars expose all CDF fields, and no F4 reference comparison is available",
        "residence output/tolerance acceptance is incomplete; residence fields alone do not qualify a path",
        "registered endpoint/saved-chord event tolerances are not enforced by the existing acceptance surface",
        f"formal per-case acceptance receipts are {case_summary['formal_acceptance_receipt_count']}/{case_summary['case_count']}",
        f"the registered 33-row matrix has {len(matrix_rows)} explicit gaps and zero formal material receipts",
        "the full-source recovery contract is bound but root review has not authorized execution; the one-transition candidate cohort has zero survivors",
        "engineering receipt binding does not grant scientific T2 qualification or partial credit",
    ]
    if not upstream_hash_closure["pass"]:
        blocking_reasons.append("upstream gap-audit hash closure changed: " + "; ".join(upstream_hash_closure["failures"]))

    engineering_ready = bool(
        bound_inputs
        and upstream_hash_closure["pass"]
        and len(case_rows) == 6
        and len(matrix_rows) == 33
        and recovery["contract_bound"]
        and all("blocking_gaps" in row for row in case_rows)
    )
    engineering_receipt = {
        "schema": ENGINEERING_RECEIPT_SCHEMA,
        "status": "recorded" if engineering_ready else "blocked",
        "integrity_status": "hash_bound" if engineering_ready else "incomplete",
        "interface_scope": "F4 tallwall120 material T2 acceptance bridge",
        "read_only_snapshot": True,
        "input_hash_closure_pass": upstream_hash_closure["pass"],
        "per_case_gap_enumeration_complete": len(case_rows) == 6,
        "per_matrix_gap_enumeration_complete": len(matrix_rows) == 33,
        "recovery_semantics_bound": recovery["contract_bound"],
        "scientific_qualification_status": "blocked",
        "qualification_effect": "none",
        "credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "does_not_promote_diagnostic_evidence": True,
    }
    formal_receipt = {
        "schema": FORMAL_RECEIPT_SCHEMA,
        "status": "accepted" if scientific_pass else "blocked",
        "decision": "eligible_for_independent_collector" if scientific_pass else "blocked",
        "credit": 1 if scientific_pass else 0,
        "qualification_credit": 1 if scientific_pass else 0,
        "qualification_claim": "none",
        "T2_macro": False,
        "T2_path": False,
        "no_partial_credit": True,
        "engineering_receipt_is_not_qualification": True,
        "independent_collector_required": True,
    }
    source_provenance = {
        "path": gap.get("source_evidence_snapshot", {}).get("source_h5_path")
        or gap.get("source_evidence_snapshot", {}).get("path")
        or "inherited from hash-bound upstream evidence",
        "sha256": gap.get("source_evidence_snapshot", {}).get("source_h5_sha256")
        or gap.get("source_evidence_snapshot", {}).get("sha256"),
        "hash_origin": "upstream F4 evidence; bridge did not reopen or rehash HDF5",
        "h5_opened_by_bridge": False,
        "h5_rehashed_by_bridge": False,
        "source_scope": full_source.get("scope_id"),
    }
    return {
        "schema": SCHEMA,
        "created_at_utc": created_at_utc or utc_now(),
        "status": "blocked",
        "decision": "blocked",
        "credit": 0,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "engineering_status": engineering_receipt["status"],
        "scope": {
            "family": "F4",
            "scope_id": gap.get("scope", {}).get("scope_id"),
            "focus": "tallwall120 macro material acceptance interface",
            "source_h5_opened": False,
            "terminal_h5_opened": False,
            "json_and_source_only": True,
        },
        "engineering_receipt": engineering_receipt,
        "scientific_qualification": {
            "status": "qualified" if scientific_pass else "blocked",
            "decision": "eligible" if scientific_pass else "blocked",
            "credit": 1 if scientific_pass else 0,
            "qualification_claim": "none",
            "T2_macro": False,
            "T2_path": False,
            "acceptance_gates": acceptance_gates,
            "blocking_reasons": blocking_reasons,
            "unknown": {
                "limit": UNKNOWN_LIMIT,
                "maximum_observed": case_summary["unknown_maximum_observed"],
                "upstream_reported_maximum": observed_unknown.get("maximum_observed"),
                "all_cases_pass": case_summary["unknown_all_pass"],
                "denominator_policy": fixed_gates["denominator_policy"],
            },
            "event_window": {
                "initial_horizon_s": FULL_WINDOW_S,
                "maximum_extension_s": MAXIMUM_WINDOW_S,
                "complete_case_count": case_summary["event_window_complete_count"],
                "case_count": case_summary["case_count"],
                "upstream_all_cases_complete": observed_event.get("all_cases_complete"),
            },
            "cdf": {
                "f4_tolerance_registered": False,
                "tolerance": None,
                "gate_pass": False,
                "fields_complete_case_count": case_summary["cdf_fields_complete_count"],
                "numeric_comparison_claimed": False,
                "f3_reference_limit_not_applied": F3_REFERENCE_CDF_LIMIT,
            },
            "residence": {
                "fields_complete_case_count": case_summary["residence_fields_complete_count"],
                "gravity_time_s": RESIDENCE_GRAVITY_TIME_S,
                "tolerance_registered": False,
                "gate_pass": False,
            },
            "mass_closure": {
                "closed_case_count": case_summary["mass_closed_count"],
                "case_count": case_summary["case_count"],
                "gate_pass": acceptance_gates["all_retained_cases_mass_closed"],
                "not_sufficient_for_t2": True,
            },
        },
        "fixed_gates": fixed_gates,
        "case_gaps": case_rows,
        "case_summary": case_summary,
        "matrix_gaps": matrix_rows,
        "matrix_summary": matrix_summary,
        "recovery_semantics": recovery,
        "source_provenance": source_provenance,
        "code_contracts": code_contracts,
        "f3_reference_boundary": _reference_boundary(f3_bridge, f3_report_text),
        "formal_acceptance_receipt": formal_receipt,
        "acceptance_gates": acceptance_gates,
        "admission_surface_pass": scientific_pass,
        "upstream_hash_closure": upstream_hash_closure,
        "input_bindings": bound_inputs,
        "case_input_bindings": case_bindings["result_bindings"],
        "checkpoint_input_bindings": case_bindings["checkpoint_bindings"],
        "input_binding_policy": {
            "json_source_report_hashes_bound": True,
            "case_result_and_checkpoint_manifest_hashes_bound": True,
            "hdf5_paths_only_inherited": True,
            "hdf5_reopened_or_rehashed_by_bridge": False,
        },
        "execution_constraints": {
            "read_only": True,
            "json_and_source_only": True,
            "source_h5_opened": False,
            "terminal_h5_opened": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_started": False,
            "new_job_submitted": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_changed": False,
            "T2_denominator_changed": False,
            "scientific_denominator_changed": False,
            "thresholds_changed": False,
            "old_evidence_overwritten": False,
            "new_namespace_only": True,
        },
        "interpretation_boundary": (
            "engineering_receipt.status=recorded means only that this read-only bridge bound its JSON/source "
            "inputs, case gaps, matrix gaps, and recovery semantics. It is not a scientific acceptance. "
            "The formal scientific receipt is independently fail-closed and currently blocked with credit=0."
        ),
    }


def render_report(value: dict[str, Any], evidence_path: Path) -> str:
    engineering = value["engineering_receipt"]
    science = value["scientific_qualification"]
    case_summary = value["case_summary"]
    matrix = value["matrix_summary"]
    gates = science["acceptance_gates"]
    lines = [
        "# F4 tallwall120 T2 acceptance bridge/contract（2026-09-22）",
        "",
        f"结论：工程回执为 `{engineering['status']}`（仅表示输入、缺口和恢复语义已绑定）；科学 T2 qualification 为 `{science['status']}`，credit=`{science['credit']}`，`T2_macro=false`、`T2_path=false`。",
        "",
        "本次只读 bridge 只读取 JSON、源码和报告哈希；没有打开 HDF5，未启动 solver/GPU/queue，未修改既有 evidence、registry、ledger、matrix、阈值或分母。工程 receipt 与科学 qualification 是两个不同对象。",
        "",
        f"机器回执：`{evidence_path}`；SHA-256：`{sha256_file(evidence_path) if evidence_path.is_file() else 'written-after-report'}`。",
        "",
        "## 工程回执与科学结论边界",
        "",
        "| 对象 | 状态 | 含义 |",
        "|---|---|---|",
        f"| engineering receipt | `{engineering['status']}` | hash-bound 的只读接口快照；6 个案例和 33 个矩阵行均已枚举 |",
        f"| formal scientific receipt | `{value['formal_acceptance_receipt']['status']}` | blocked；credit=`{value['formal_acceptance_receipt']['credit']}`；不授予 T2 |",
        "",
        "## 固定门",
        "",
        "| 门 | 固定规则 | 当前 bridge 结果 |",
        "|---|---:|---|",
        f"| 每 source unknown | `<= {UNKNOWN_LIMIT}` | `{str(gates['per_source_unknown_fraction']).lower()}`；最大 `{science['unknown']['maximum_observed']}` |",
        f"| F4 事件窗 | `{FULL_WINDOW_S}` s，必要时一次延长至 `{MAXIMUM_WINDOW_S}` s | `{str(gates['full_event_window']).lower()}`；{case_summary['event_window_complete_count']}/{case_summary['case_count']} 完整 |",
        f"| F4 CDF 容差 | 必须由 F4 自己登记 | `{str(gates['f4_cdf_tolerance_registered']).lower()}`；未借用 F3 的 `{F3_REFERENCE_CDF_LIMIT}` |",
        f"| residence | CDF、驻留和 right-censor 语义及 acceptance 容差 | `{str(gates['residence_fields_and_acceptance']).lower()}` |",
        f"| 事件容差 | endpoint `{EVENT_ENDPOINT_TOLERANCE_M}` m；saved-chord crossings `{SAVED_CHORD_CROSSINGS_ALLOWED}` | `{str(gates['event_tolerance_acceptance']).lower()}` |",
        f"| 恢复 | frame-40 resume、每 native frame checkpoint、append-only generation | contract=`{str(gates['recovery_contract_bound']).lower()}`；receipt=`{str(gates['recovery_acceptance_receipt']).lower()}` |",
        f"| 矩阵 | 33 行均有 formal receipt | `{str(gates['material_matrix_formal_receipts']).lower()}`；当前 `0/{matrix['registered_row_count']}` |",
        "",
        "## 逐案例缺口",
        "",
        "| # | case | unknown | event window | CDF fields | residence | recovery | formal receipt |",
        "|---:|---|---:|---|---|---|---|---|",
    ]
    for row in value["case_gaps"]:
        recovery = row["recovery"]
        lines.append(
            f"| {row['case_index']} | `{row['canary_id']}` | `{row['unknown']['observed_fraction_max']}` / `{UNKNOWN_LIMIT}` | "
            f"{str(row['event_window']['observed_complete']).lower()} ({row['event_window']['observed_status']}) | "
            f"{str(row['cdf']['fields_present']).lower()} | {str(row['residence']['fields_present']).lower()} | "
            f"{str(recovery['checkpoint_integrity_pass']).lower()} | {str(row['formal_acceptance_receipt_present']).lower()} |"
        )
    lines.extend(
        [
            "",
            f"保留案例共 `{case_summary['case_count']}` 个；unknown 门通过 `{case_summary['unknown_all_pass']}`，事件窗完整 `{case_summary['event_window_complete_count']}/{case_summary['case_count']}`，CDF 字段完整 `{case_summary['cdf_fields_complete_count']}/{case_summary['case_count']}`，正式 receipt `{case_summary['formal_acceptance_receipt_count']}/{case_summary['case_count']}`。质量闭合 `{case_summary['mass_closed_count']}/{case_summary['case_count']}` 仍不足以抵销 unknown/right-censor。",
            "",
            "## 逐矩阵缺口",
            "",
            "矩阵行号沿用登记顺序：`0–23 resolution_substep`、`24–27 cadence`、`28–32 seed_density`。源 cell 可用不等于材料 overlay 完成；禁止插值、把独立 .02 s solve 当作 decimation，或把诊断行升级为 T2。",
            "",
            "| row | axis | source cell | source available | status | gap |",
            "|---:|---|---:|---|---|---|",
        ]
    )
    for row in value["matrix_gaps"]:
        lines.append(
            f"| {row['matrix_row']} | `{row['axis']}` | `{row['source_cfd_cell']}` | "
            f"{str(row['source_available']).lower()} | `{row['status']}` | {row['blocking_gap']} |"
        )
    recovery = value["recovery_semantics"]
    lines.extend(
        [
            "",
            "## 恢复语义",
            "",
            f"contract bound=`{str(recovery['contract_bound']).lower()}`；frame `{recovery['frame_start']}..{recovery['frame_end']}`；required end `{recovery['required_time_end_s']}` s；recovery boundary=`{recovery['recovery_boundary_frame']}`；每 native frame checkpoint=`{str(recovery['checkpoint_every_native_frame']).lower()}`。",
            "",
            f"恢复规则：`{recovery['resume_rule']}`；generation=`{recovery['generation_policy']}`；从零重跑禁止=`{str(recovery['rerun_from_zero_after_interruption'] is False).lower()}`。root review 当前授权=`{str(recovery['execution_authorized_now']).lower()}`，candidate 状态=`{recovery['candidate_status']}`，one-transition survivors=`{recovery['counterfactual_survivors']}`。旧 trace 只作 binding，不复制 candidate state；本 bridge 不执行恢复。",
            "",
            "## 阻塞原因",
            "",
        ]
    )
    lines.extend(f"{index}. {reason}" for index, reason in enumerate(science["blocking_reasons"], 1))
    lines.extend(["", "## 输入哈希", ""])
    for name, binding in value["input_bindings"].items():
        lines.append(f"- `{name}`：`{binding['path']}` — `{binding['sha256']}`")
    lines.extend(
        [
            "",
            f"另绑定逐案例结果 `{len(value['case_input_bindings'])}` 个、checkpoint manifest `{len(value['checkpoint_input_bindings'])}` 个；HDF5 路径/哈希仅继承上游证据，本 bridge 未重新打开或 rehash。",
            "",
            "该报告与 JSON 均属于新的 `f4-tallwall120-t2-acceptance-bridge-v1` 命名空间；旧 gap audit、registry、ledger、matrix、阈值、分母和历史 evidence 保持不变。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    output = Path(output).resolve()
    report = Path(report).resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite existing bridge evidence/report")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(value, output), encoding="utf-8")


def _verify_binding_group(lab_root: Path, bindings: Any, label: str) -> int:
    if not isinstance(bindings, dict):
        raise ValueError(f"{label} is not an object")
    count = 0
    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"{label}.{name} is not an object")
        path = _resolve_path(lab_root, binding.get("path", ""))
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != binding.get("bytes"):
            raise ValueError(f"{label}.{name} byte count changed")
        if sha256_file(path) != binding.get("sha256"):
            raise ValueError(f"{label}.{name} SHA-256 changed")
        count += 1
    return count


def verify_receipt(path: Path, lab_root: Path) -> dict[str, Any]:
    """Verify the JSON/source hash closure without opening any HDF5 path."""
    value = _load_json(Path(path))
    _require_equal(value.get("schema"), SCHEMA, "bridge schema")
    _require_equal(value.get("decision"), "blocked", "bridge decision")
    _require_equal(value.get("status"), "blocked", "bridge status")
    _require_equal(value.get("credit"), 0, "bridge credit")
    _require_equal(value.get("T2_macro"), False, "bridge T2_macro")
    _require_equal(value.get("T2_path"), False, "bridge T2_path")
    _require_equal(value.get("scientific_qualification", {}).get("status"), "blocked", "science status")
    _require_equal(value.get("scientific_qualification", {}).get("credit"), 0, "science credit")
    _require_equal(value.get("formal_acceptance_receipt", {}).get("status"), "blocked", "formal receipt status")
    _require_equal(value.get("formal_acceptance_receipt", {}).get("credit"), 0, "formal receipt credit")
    _require_equal(value.get("formal_acceptance_receipt", {}).get("T2_macro"), False, "formal T2_macro")
    _require_equal(value.get("formal_acceptance_receipt", {}).get("T2_path"), False, "formal T2_path")
    counts = {
        "input_bindings": _verify_binding_group(lab_root, value.get("input_bindings"), "input_bindings"),
        "case_input_bindings": _verify_binding_group(
            lab_root, value.get("case_input_bindings"), "case_input_bindings"
        ),
        "checkpoint_input_bindings": _verify_binding_group(
            lab_root, value.get("checkpoint_input_bindings"), "checkpoint_input_bindings"
        ),
    }
    if len(value.get("case_gaps", [])) != 6:
        raise ValueError("receipt case gap count is not six")
    if len(value.get("matrix_gaps", [])) != 33:
        raise ValueError("receipt matrix gap count is not 33")
    if not value.get("execution_constraints", {}).get("new_namespace_only"):
        raise ValueError("receipt is not marked new-namespace-only")
    return {"schema": value["schema"], "status": value["status"], "counts": counts, "value": value}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=default_root)
    parser.add_argument("--output", type=Path, default=default_root / DEFAULT_OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=default_root / DEFAULT_REPORT_NAME)
    parser.add_argument(
        "--created-at-utc",
        default=None,
        help="optional fixed timestamp for reproducible JSON/report generation",
    )
    parser.add_argument("--verify", type=Path, default=None, help="verify an existing bridge receipt and exit")
    args = parser.parse_args(argv)
    lab_root = args.lab_root.resolve()
    if args.verify is not None:
        value = verify_receipt(args.verify.resolve(), lab_root)
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    value = build_bridge(lab_root, created_at_utc=args.created_at_utc)
    write_artifacts(value, args.output, args.report)
    print(
        json.dumps(
            {
                "schema": value["schema"],
                "status": value["status"],
                "decision": value["decision"],
                "engineering_receipt": value["engineering_receipt"]["status"],
                "scientific_qualification": value["scientific_qualification"]["status"],
                "credit": value["formal_acceptance_receipt"]["credit"],
                "T2_macro": value["formal_acceptance_receipt"]["T2_macro"],
                "T2_path": value["formal_acceptance_receipt"]["T2_path"],
                "output": str(Path(args.output).resolve()),
                "report": str(Path(args.report).resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
