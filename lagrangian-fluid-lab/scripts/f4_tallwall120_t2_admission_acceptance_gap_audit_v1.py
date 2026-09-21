#!/usr/bin/env python3
"""Read-only F4 tallwall120 material T2 admission/acceptance gap audit.

The retained tallwall120 material artifacts are diagnostic JSON/sidecar
receipts.  This audit compares their fixed gates and recovery contract with
the code paths that are meant to accept them.  It reads JSON and source text
only; it never opens a terminal H5, starts a solver/GPU/queue task, or changes
the registry, ledger, matrix, denominator, or an existing evidence file.

The result is intentionally a gap record.  A structurally valid receipt still
keeps ``T2_macro`` and ``T2_path`` false when the scientific gates, matrix, or
acceptance contract are incomplete.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "core.material.f4.tallwall120.t2_admission_acceptance_gap_audit.v1"
UNKNOWN_LIMIT = 0.01
F3_CDF_LIMIT = 0.02
FULL_WINDOW_S = 4.34
MAXIMUM_WINDOW_S = 8.68
RESIDENCE_GRAVITY_TIME_S = 0.3497487083913345
EVENT_ENDPOINT_TOLERANCE_M = 1.0e-8
SAVED_CHORD_CROSSINGS_ALLOWED = 0

DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-admission-acceptance-gap-audit-20260921.json"
)
DEFAULT_REPORT_NAME = "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-21.zh-CN.md"


INPUTS: dict[str, Path] = {
    "core_material": Path("scripts/core_material.py"),
    "core_material_acceptance": Path("scripts/core_material_acceptance.py"),
    "macro_sidecar_preflight_code": Path("scripts/f4_macro_t2_sidecar_preflight_v1.py"),
    "tallwall_material_code": Path("scripts/f4_tallwall120_material.py"),
    "tallwall_preflight_code": Path("scripts/f4_tallwall120_material_preflight_v1.py"),
    "migration_spec": Path(
        "campaigns/core-v1/material/evidence/f4-resting-pool-migration-spec-2026-09-19.json"
    ),
    "matrix_review": Path(
        "campaigns/core-v1/material/evidence/f4-resting-pool-33-to-15-matrix-review-2026-09-19.json"
    ),
    "macro_sidecar_preflight": Path(
        "campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-20260920.json"
    ),
    "negative_evidence": Path(
        "campaigns/core-v1/material/evidence/f4-material-negative-evidence-audit-20260920.json"
    ),
    "source_window_audit": Path(
        "campaigns/core-v1/material/evidence/f3-f4-t2-cpu-source-window-audit-v1-20260920.json"
    ),
    "tallwall_preflight": Path(
        "campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.json"
    ),
    "tallwall_trace_result": Path(
        "campaigns/core-v1/material/evidence/f4-tallwall120-native-cell14-material-preflight-20260921.trace.json"
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
    "admission_contract": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-f4-t2-admission-root-review-contract-20260921.json"
    ),
    "report_material_preflight": Path(
        "reports/F4-TALLWALL120-MATERIAL-PREFLIGHT-2026-09-21.zh-CN.md"
    ),
    "report_full_source_contract": Path(
        "reports/F4-TALLWALL120-FULL-SOURCE-CANARY-CONTRACT-2026-09-21.zh-CN.md"
    ),
    "report_admission_contract": Path(
        "reports/F3-F4-T2-ADMISSION-CONTRACT-2026-09-21.zh-CN.md"
    ),
    "report_root_cause": Path(
        "reports/F4-TALLWALL120-MATERIAL-ROOT-CAUSE-AUDIT-2026-09-21.zh-CN.md"
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(lab_root: Path, value: str | Path) -> Path:
    """Resolve current lab-relative and historical absolute evidence paths."""
    value_path = Path(value)
    if value_path.is_absolute():
        return value_path
    lab_root = Path(lab_root).resolve()
    candidates = (lab_root / value_path, lab_root.parent / value_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def display_path(lab_root: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(lab_root).resolve()))
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def bind_file(lab_root: Path, relative: Path) -> dict[str, Any]:
    path = resolve_path(lab_root, relative)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": display_path(lab_root, path),
        "absolute_path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _bool(value: Any) -> bool:
    return value is True


def _numeric(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and result not in (float("inf"), float("-inf")) else default


def _read_case_result(lab_root: Path, result_path: str | Path) -> tuple[Path, dict[str, Any] | None]:
    path = resolve_path(lab_root, result_path)
    if not path.is_file():
        return path, None
    return path, load_json(path)


def _read_checkpoint_manifest(
    lab_root: Path, path_value: Any
) -> tuple[Path | None, dict[str, Any] | None]:
    if not isinstance(path_value, str) or not path_value:
        return None, None
    path = resolve_path(lab_root, path_value)
    if not path.is_file():
        return path, None
    return path, load_json(path)


def _checkpoint_summary(
    lab_root: Path,
    trace_audit: dict[str, Any],
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    checkpoint = trace_audit.get("checkpoint") if isinstance(trace_audit, dict) else None
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    manifest_path, manifest = _read_checkpoint_manifest(lab_root, checkpoint.get("manifest_path"))
    generation_path: Path | None = None
    generation_exists = False
    generation_hash_pass = False
    content_addressed = False
    if manifest is not None and manifest_path is not None:
        generation = manifest.get("generation")
        generation_dir = manifest.get("generation_dir")
        content_addressed = bool(generation and generation_dir and manifest.get("generation_count_policy"))
        if content_addressed:
            generation_path = manifest_path.parent / str(generation_dir) / str(generation)
        else:
            generation_path = manifest_path.with_name(manifest_path.name.replace(".json", ".npz"))
            if not generation_path.is_file():
                generation_path = manifest_path.with_name(
                    manifest_path.name.replace(".checkpoint.json", ".checkpoint.npz")
                )
        generation_exists = generation_path.is_file()
        if generation_exists and manifest.get("state_sha256"):
            generation_hash_pass = sha256_file(generation_path) == manifest["state_sha256"]

    committed = checkpoint.get("committed_frame", checkpoint.get("committed"))
    result_committed = result.get("committed_frame") if isinstance(result, dict) else None
    return {
        "manifest_exists": bool(manifest_path and manifest_path.is_file()),
        "manifest_path": display_path(lab_root, manifest_path) if manifest_path else None,
        "manifest_schema": manifest.get("schema") if manifest else None,
        "checkpoint_pass_from_case_audit": _bool(checkpoint.get("pass")),
        "state_hash_pass_from_case_audit": _bool(checkpoint.get("state_hash_pass")),
        "committed_frame": int(committed) if isinstance(committed, int) else committed,
        "result_committed_frame": result_committed,
        "committed_frame_matches_result": committed == result_committed,
        "content_addressed_generation": content_addressed,
        "generation_exists": generation_exists,
        "generation_hash_pass": generation_hash_pass,
        "generation_policy": manifest.get("generation_count_policy") if manifest else None,
        "result_references_checkpoint": bool(isinstance(result, dict) and result.get("checkpoint_manifest")),
    }


def summarize_case_sidecars(lab_root: Path, source_window_audit: dict[str, Any]) -> dict[str, Any]:
    """Summarize every retained F4 case without opening its H5 trace."""
    cases = source_window_audit.get("f4", {}).get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("source-window audit has no F4 case list")
    rows: list[dict[str, Any]] = []
    required_cdf = ("contact_cdf", "upward_cdf", "return_cdf", "residence_cdf")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("F4 case row is not an object")
        trace_audit = case.get("trace_audit") if isinstance(case.get("trace_audit"), dict) else {}
        result_path, result = _read_case_result(lab_root, case.get("result_path", ""))
        source_rows = result.get("by_source", []) if isinstance(result, dict) else []
        source_rows = source_rows if isinstance(source_rows, list) else []
        cdf_complete = bool(
            source_rows
            and all(isinstance(row, dict) and all(name in row for name in required_cdf) for row in source_rows)
        )
        residence_complete = bool(
            source_rows
            and all(
                isinstance(row, dict)
                and "residence_cdf" in row
                and "residence_mean_s" in row
                and "right_censored_fraction" in row
                for row in source_rows
            )
        )
        event_fields = bool(
            isinstance(result, dict)
            and "event_window_complete" in result
            and "event_window_status" in result
            and "committed_time_s" in result
        )
        acceptance_receipt = bool(
            isinstance(result, dict)
            and result.get("schema") == "core.material.acceptance.v1"
        )
        checkpoint = _checkpoint_summary(lab_root, trace_audit, result)
        rows.append(
            {
                "canary_id": case.get("canary_id"),
                "case_id": case.get("case_id"),
                "result_path": display_path(lab_root, result_path),
                "result_exists": result is not None,
                "result_schema": result.get("schema") if isinstance(result, dict) else None,
                "result_status": result.get("status") if isinstance(result, dict) else None,
                "seed_denominator": case.get("seed_denominator"),
                "unknown_fraction_max": case.get("unknown_fraction_max"),
                "unknown_gate_pass": _bool(case.get("trace_audit", {}).get("unknown_gate", {}).get("pass")),
                "mass_closed": _bool(case.get("mass_closed")),
                "event_window_complete": _bool(case.get("event_window_complete")),
                "event_window_status": case.get("trace_audit", {}).get("event_window", {}).get("status"),
                "cdf_fields_present": cdf_complete,
                "residence_fields_present": residence_complete,
                "event_fields_present": event_fields,
                "acceptance_receipt_present": acceptance_receipt,
                "checkpoint": checkpoint,
                "qualification_credit": case.get("qualification_credit"),
            }
        )
    return {
        "case_count": len(rows),
        "cases": rows,
        "result_sidecars_present": sum(row["result_exists"] for row in rows),
        "cdf_complete_case_count": sum(row["cdf_fields_present"] for row in rows),
        "residence_complete_case_count": sum(row["residence_fields_present"] for row in rows),
        "event_fields_complete_case_count": sum(row["event_fields_present"] for row in rows),
        "formal_acceptance_receipt_count": sum(row["acceptance_receipt_present"] for row in rows),
        "checkpoint_integrity_pass_count": sum(
            row["checkpoint"]["checkpoint_pass_from_case_audit"]
            and row["checkpoint"]["state_hash_pass_from_case_audit"]
            for row in rows
        ),
        "content_addressed_checkpoint_count": sum(
            row["checkpoint"]["content_addressed_generation"] for row in rows
        ),
        "interpretation": (
            "The retained source-window audit has six case rows and checkpoint hashes, "
            "but a case result sidecar is accepted only when its terminal CDF/residence "
            "fields and event status are present. A checkpoint hash alone is recovery "
            "evidence, not a material acceptance receipt."
        ),
    }


def inspect_code_contracts(
    core_material: str,
    acceptance: str,
    macro_preflight: str,
    tallwall_material: str,
) -> dict[str, Any]:
    """Check code surfaces without importing or executing a material worker."""
    return {
        "core_material": {
            "weighted_cdf": "def weighted_cdf(" in core_material,
            "f4_residence_cdf_summary": "residence_cdf" in core_material,
            "f4_event_window_summary": "event_window_complete" in core_material,
            "tallwall_schema": "core.material.f4.tallwall120.v1" in core_material,
            "content_addressed_generation_checkpoint": "content_addressed" in core_material,
        },
        "core_material_acceptance": {
            "per_source_unknown_gate": "validate_source_coverage(" in acceptance,
            "generic_cdf_difference_gate": "cdf_sup_abs_difference" in acceptance,
            "tallwall_schema": "core.material.f4.tallwall120.v1" in acceptance,
            "tallwall_checkpoint_v2": "core.material.f4.tallwall120.checkpoint.v2" in acceptance,
            "residence_cdf_gate": "residence_cdf" in acceptance,
            "f4_event_tolerance_gate": (
                "closed_wall_endpoint_tolerance_m" in acceptance
                or "saved_chord_crossings_allowed" in acceptance
            ),
            "content_addressed_generation_gate": "generation_count_policy" in acceptance,
            "per_case_matrix_gate": "f4_matrix" in acceptance or "matrix_review" in acceptance,
        },
        "macro_sidecar_preflight": {
            "unknown_gate": "UNKNOWN_LIMIT" in macro_preflight,
            "f3_cdf_gate_named": "f3_cdf_sup_abs_difference_max" in macro_preflight,
            "f4_residence_gate": "residence_cdf" in macro_preflight,
            "f4_event_tolerance_gate": "closed_wall_endpoint_tolerance_m" in macro_preflight,
            "acceptance_adapter_called": "audit_material_h5" in macro_preflight,
            "per_case_acceptance": "acceptance_receipt" in macro_preflight,
        },
        "tallwall_material": {
            "tallwall_schema": "core.material.f4.tallwall120.v1" in tallwall_material,
            "tallwall_checkpoint_v2": "core.material.f4.tallwall120.checkpoint.v2" in tallwall_material,
            "content_addressed_generation": "content-addressed" in tallwall_material,
            "residence_event_summary": "event_summary(" in tallwall_material
            and "cm.f4_event_summary" in tallwall_material,
        },
    }


def compare_registered_gates(
    migration: dict[str, Any],
    macro_preflight: dict[str, Any],
    tallwall_preflight: dict[str, Any],
    source_window_audit: dict[str, Any],
) -> dict[str, Any]:
    migration_gates = migration.get("f4_gates", {})
    event_definition = migration.get("event_definition", {})
    registered = macro_preflight.get("registered_gates", {})
    cases = source_window_audit.get("f4", {}).get("cases", [])
    unknown_values = [
        float(row["unknown_fraction_max"])
        for row in cases
        if isinstance(row, dict) and _numeric(row.get("unknown_fraction_max")) is not None
    ]
    event_complete = [
        _bool(row.get("event_window_complete"))
        for row in cases
        if isinstance(row, dict)
    ]
    return {
        "unknown_mass": {
            "registered_limit": migration_gates.get("material_unknown_fraction_max"),
            "preflight_limit": registered.get("unknown_fraction_per_source_max"),
            "limits_match": migration_gates.get("material_unknown_fraction_max")
            == registered.get("unknown_fraction_per_source_max")
            == UNKNOWN_LIMIT,
            "maximum_observed": max(unknown_values) if unknown_values else None,
            "all_cases_pass": bool(unknown_values) and max(unknown_values) <= UNKNOWN_LIMIT,
        },
        "cdf": {
            "f3_limit_in_preflight": registered.get("f3_cdf_sup_abs_difference_max"),
            "f4_limit_in_migration": migration_gates.get("cdf_sup_abs_difference_max"),
            "f4_limit_registered": "cdf_sup_abs_difference_max" in migration_gates,
            "f4_acceptance_limit_available": False,
            "gap": "F4 declares CDF distributions but no F4 numerical CDF tolerance; 0.02 is explicitly named as an F3 limit.",
        },
        "residence": {
            "distribution_declared": "destination residence weighted CDF"
            in event_definition.get("reported_distributions", []),
            "right_censored_duration_declared": "right-censored"
            in str(event_definition.get("residence", {})).lower(),
            "gravity_time_s": event_definition.get("post_return_window", {}).get(
                "gravity_time_s", RESIDENCE_GRAVITY_TIME_S
            ),
            "residence_tolerance_registered": False,
            "residence_acceptance_implemented": False,
        },
        "event_window": {
            "initial_horizon_s": registered.get("full_event_window_s"),
            "maximum_extension_s": registered.get("maximum_right_censored_extension_s"),
            "migration_initial_horizon_s": event_definition.get("post_return_window", {}).get("initial_horizon_s"),
            "migration_maximum_extension_s": event_definition.get("post_return_window", {}).get(
                "maximum_extended_horizon_s"
            ),
            "all_cases_complete": bool(event_complete) and all(event_complete),
            "preflight_gate_pass": _bool(macro_preflight.get("gate_evaluation", {}).get("event_window_pass")),
            "tallwall_canary_gate_pass": _bool(tallwall_preflight.get("gate_evaluation", {}).get("event_window_complete")),
        },
        "event_tolerance": {
            "closed_wall_endpoint_tolerance_m": migration_gates.get(
                "closed_wall_endpoint_tolerance_m", EVENT_ENDPOINT_TOLERANCE_M
            ),
            "saved_chord_crossings_allowed": migration_gates.get(
                "saved_chord_crossings_allowed", SAVED_CHORD_CROSSINGS_ALLOWED
            ),
            "registered": (
                migration_gates.get("closed_wall_endpoint_tolerance_m") == EVENT_ENDPOINT_TOLERANCE_M
                and migration_gates.get("saved_chord_crossings_allowed") == SAVED_CHORD_CROSSINGS_ALLOWED
            ),
            "acceptance_enforced": False,
            "macro_preflight_enforced": False,
        },
        "mass_closure": {
            "all_retained_cases_closed": all(
                _bool(row.get("mass_closed")) for row in cases if isinstance(row, dict)
            ),
            "preflight_all_mass_closed": _bool(macro_preflight.get("gate_evaluation", {}).get("all_mass_closed")),
        },
    }


def summarize_matrix(matrix: dict[str, Any], case_sidecars: dict[str, Any]) -> dict[str, Any]:
    template = matrix.get("full_t2_33_overlay_template", {})
    existing = matrix.get("existing_f4_cfd_matrix", {})
    return {
        "registered_overlay_rows": template.get("total_count"),
        "registered_cadence_rows": template.get("cadence_count"),
        "registered_resolution_substep_rows": template.get("resolution_substep_count"),
        "registered_seed_density_rows": template.get("seed_density_count"),
        "existing_f4_cfd_cell_count": existing.get("cell_count"),
        "exact_cadence_rows_available": 0,
        "exact_cadence_rows_missing": template.get("cadence_count"),
        "material_resolution_rows_pending": template.get("resolution_substep_count"),
        "material_seed_density_rows_pending": template.get("seed_density_count"),
        "material_matrix_ready": False,
        "retained_case_sidecar_count": case_sidecars.get("case_count", 0),
        "formal_acceptance_receipt_count": case_sidecars.get("formal_acceptance_receipt_count", 0),
        "interpretation": matrix.get("interpretation"),
    }


def build_audit(lab_root: Path) -> dict[str, Any]:
    """Build the gap receipt using only JSON/source/report inputs."""
    lab_root = Path(lab_root).resolve()
    bound_inputs = {name: bind_file(lab_root, path) for name, path in INPUTS.items()}
    core_material = resolve_path(lab_root, INPUTS["core_material"]).read_text(encoding="utf-8")
    acceptance_code = resolve_path(lab_root, INPUTS["core_material_acceptance"]).read_text(encoding="utf-8")
    macro_code = resolve_path(lab_root, INPUTS["macro_sidecar_preflight_code"]).read_text(encoding="utf-8")
    tallwall_code = resolve_path(lab_root, INPUTS["tallwall_material_code"]).read_text(encoding="utf-8")
    migration = load_json(resolve_path(lab_root, INPUTS["migration_spec"]))
    matrix = load_json(resolve_path(lab_root, INPUTS["matrix_review"]))
    macro_preflight = load_json(resolve_path(lab_root, INPUTS["macro_sidecar_preflight"]))
    source_window = load_json(resolve_path(lab_root, INPUTS["source_window_audit"]))
    tallwall_preflight = load_json(resolve_path(lab_root, INPUTS["tallwall_preflight"]))
    tallwall_trace = load_json(resolve_path(lab_root, INPUTS["tallwall_trace_result"]))
    full_contract = load_json(resolve_path(lab_root, INPUTS["full_source_contract"]))
    root_review = load_json(resolve_path(lab_root, INPUTS["root_review"]))
    candidate_contract = load_json(resolve_path(lab_root, INPUTS["candidate_contract"]))
    admission_contract = load_json(resolve_path(lab_root, INPUTS["admission_contract"]))

    code_contracts = inspect_code_contracts(core_material, acceptance_code, macro_code, tallwall_code)
    case_sidecars = summarize_case_sidecars(lab_root, source_window)
    gates = compare_registered_gates(migration, macro_preflight, tallwall_preflight, source_window)
    matrix_summary = summarize_matrix(matrix, case_sidecars)

    execution = full_contract.get("execution", {})
    resume_policy = execution.get("resume_policy", {})
    source_window_contract = full_contract.get("source_window", {})
    root_decision = root_review.get("review_decision", {})
    output_stem = Path(str(execution.get("output_stem", ""))) if execution.get("output_stem") else None
    recovery_contract = {
        "contract_present": bool(resume_policy),
        "frame_start": source_window_contract.get("frame_start"),
        "frame_end": source_window_contract.get("frame_end"),
        "full_window_s": source_window_contract.get("time_end_s"),
        "recovery_point": resume_policy.get("recovery_point"),
        "checkpoint_every_native_frame": _bool(resume_policy.get("checkpoint_every_native_frame")),
        "generation_policy": resume_policy.get("generation_policy"),
        "append_only_required": "append-only" in str(resume_policy.get("generation_policy", "")),
        "rerun_from_zero_forbidden": resume_policy.get("rerun_from_zero_after_interruption") is False,
        "candidate_output_stem_absent": bool(output_stem and not output_stem.exists()),
        "root_authorized_one_cpu_only": _bool(root_decision.get("authorized_one_cpu_only")),
        "automatic_execution": _bool(full_contract.get("route_decision", {}).get("automatic_execution")),
        "core_material_generation_support": code_contracts["core_material"]["content_addressed_generation_checkpoint"],
        "acceptance_generation_support": code_contracts["core_material_acceptance"]["content_addressed_generation_gate"],
        "tallwall_generation_support": code_contracts["tallwall_material"]["content_addressed_generation"],
        "status": "contract_bound_but_not_authorized",
    }

    blocking_reasons = [
        (
            "all six retained F4 cases fail the fixed per-source unknown-mass gate: "
            f"maximum {gates['unknown_mass']['maximum_observed']} > {UNKNOWN_LIMIT}"
        ),
        "all six retained F4 cases are right-censored or unresolved before the required event window completes",
        "the migration spec declares contact/upward/return/residence CDF outputs, but no F4 CDF numerical tolerance is registered; the preflight's 0.02 value is explicitly an F3 CDF limit",
        "residence CDF and right-censored residence are emitted by the tracer result, but core_material_acceptance has no residence acceptance gate or tolerance",
        "closed-wall endpoint and saved-chord event tolerances are registered in the migration spec but are not enforced by core_material_acceptance or the macro sidecar preflight",
        (
            "the six retained case rows have checkpoint integrity evidence, but only "
            f"{case_sidecars['cdf_complete_case_count']} case result sidecars expose complete CDF/residence fields and "
            f"{case_sidecars['formal_acceptance_receipt_count']} carry a formal acceptance receipt"
        ),
        (
            f"the registered overlay is not ready: {matrix_summary['registered_overlay_rows']} rows are planned over "
            f"{matrix_summary['existing_f4_cfd_cell_count']} CFD cells, with 24 resolution/substep and 5 seed-density overlays pending"
        ),
        "the ESS32 full-source candidate is proposal-only and root review has authorized_one_cpu_only=false; its counterfactual first-loss cohort has zero survivors",
        "core_material_acceptance does not admit the tallwall120 schema/checkpoint-v2 used by the versioned tallwall sidecar, so a complete future sidecar has no shared acceptance route",
    ]

    # These booleans are deliberately admission booleans, not claims about
    # source quality.  Any missing acceptance surface fails closed.
    acceptance_gates = {
        "unknown_mass_gate": gates["unknown_mass"]["all_cases_pass"],
        "f4_cdf_tolerance_registered": gates["cdf"]["f4_limit_registered"],
        "residence_distribution_present_in_all_retained_results": (
            case_sidecars["residence_complete_case_count"] == case_sidecars["case_count"]
        ),
        "residence_tolerance_acceptance": gates["residence"]["residence_acceptance_implemented"],
        "event_window_gate": gates["event_window"]["all_cases_complete"],
        "event_tolerance_acceptance": gates["event_tolerance"]["acceptance_enforced"],
        "per_case_sidecar_acceptance": (
            case_sidecars["formal_acceptance_receipt_count"] == case_sidecars["case_count"]
        ),
        "recovery_contract_bound": recovery_contract["contract_present"] and recovery_contract["append_only_required"],
        "recovery_contract_accepted": recovery_contract["acceptance_generation_support"],
        "material_matrix_ready": matrix_summary["material_matrix_ready"],
        "tallwall_schema_accepted": code_contracts["core_material_acceptance"]["tallwall_schema"],
        "sidecar_preflight_bridges_acceptance": code_contracts["macro_sidecar_preflight"]["acceptance_adapter_called"],
    }
    admission_pass = all(acceptance_gates.values())

    return {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "blocked_for_macro_t2" if not admission_pass else "admission_surface_complete_but_no_t2_claim",
        "qualification_claim": "none",
        "qualification_credit": "none",
        "T2_macro": False,
        "T2_path": False,
        "scope": {
            "family": "F4",
            "scope_id": tallwall_preflight.get("scope_id"),
            "focus": "tallwall120 macro material admission/acceptance",
            "source_h5_opened": False,
            "terminal_h5_opened": False,
            "json_and_source_only": True,
        },
        "registered_gates": {
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
            "f3_cdf_sup_abs_difference_max": F3_CDF_LIMIT,
            "f4_full_event_window_s": FULL_WINDOW_S,
            "f4_maximum_right_censored_extension_s": MAXIMUM_WINDOW_S,
            "residence_gravity_time_s": RESIDENCE_GRAVITY_TIME_S,
            "closed_wall_endpoint_tolerance_m": EVENT_ENDPOINT_TOLERANCE_M,
            "saved_chord_crossings_allowed": SAVED_CHORD_CROSSINGS_ALLOWED,
            "denominator_policy": "all geometric seeds carrying the declared source label; unknown/right-censored remains in denominator",
        },
        "observed_gate_comparison": gates,
        "code_contracts": code_contracts,
        "case_sidecars": case_sidecars,
        "recovery_contract": recovery_contract,
        "matrix": matrix_summary,
        "acceptance_gates": acceptance_gates,
        "admission_surface_pass": admission_pass,
        "blocking_reasons": blocking_reasons,
        "current_qualification_state": {
            "tallwall_preflight_T2_macro": tallwall_preflight.get("qualification", {}).get("T2_macro") is True,
            "tallwall_preflight_T2_path": tallwall_preflight.get("qualification", {}).get("T2_path") is True,
            "macro_preflight_T2_macro": macro_preflight.get("T2_macro") is True,
            "macro_preflight_T2_path": macro_preflight.get("T2_path") is True,
            "candidate_id": candidate_contract.get("contracts", {}).get("f4_ess32_v2", {}).get("candidate_id", "f4_ess32_v2"),
            "candidate_counterfactual_survivors": full_contract.get("candidate", {}).get("one_transition_counterfactual", {}).get("counterfactual_cohort_survivors"),
            "root_authorized_one_cpu_only": _bool(root_decision.get("authorized_one_cpu_only")),
            "overall_T2_credit": 0,
            "core_gate_changed": False,
        },
        "execution_constraints": {
            "read_only": True,
            "json_and_source_only": True,
            "source_h5_opened": False,
            "terminal_h5_opened": False,
            "solver_started": False,
            "gpu_started": False,
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
        },
        "input_bindings": bound_inputs,
        "interpretation_boundary": (
            "This audit closes an admission/acceptance review only. It does not grant material or macro T2 credit. "
            "The absence of a gate implementation is reported as a fail-closed gap; it is not treated as a passing gate."
        ),
        "source_evidence_snapshot": {
            "tallwall_trace_schema": tallwall_trace.get("schema"),
            "tallwall_checkpoint_schema": tallwall_trace.get("checkpoint_schema"),
            "tallwall_committed_frame": tallwall_trace.get("committed_frame"),
            "tallwall_committed_time_s": tallwall_trace.get("committed_time_s"),
            "tallwall_unknown_fraction_max": tallwall_trace.get("by_source", [{}])[0].get("unknown_fraction_max")
            if tallwall_trace.get("by_source")
            else None,
            "tallwall_event_window_status": tallwall_trace.get("event_window_status"),
        },
    }


def render_report(audit: dict[str, Any], evidence_path: Path) -> str:
    sidecars = audit["case_sidecars"]
    gates = audit["observed_gate_comparison"]
    code = audit["code_contracts"]
    lines = [
        "# F4 tallwall120 宏观 T2 材料 admission/acceptance gap audit（2026-09-21）",
        "",
        "结论：当前 `T2_macro=false`、`T2_path=false`，材料资格仍被科学门、逐例侧车闭合、矩阵覆盖和 acceptance 接口缺口共同阻塞。本次只读检查没有打开 terminal H5，也没有启动 solver/GPU/queue。",
        "",
        f"机器回执：`{evidence_path}`；SHA-256：`{sha256_file(evidence_path) if evidence_path.is_file() else 'written-after-report'}`。",
        "",
        "## 固定门与当前证据",
        "",
        "| 门 | 注册计划 | 当前审计结果 |",
        "|---|---:|---|",
        f"| 每 source 未知质量 | `<= {UNKNOWN_LIMIT}` | 最大 `{gates['unknown_mass']['maximum_observed']}`，6/6 case 不通过 |",
        f"| F3 CDF sup（仅 F3 命名） | `<= {F3_CDF_LIMIT}` | preflight 的 `0.02` 没有被登记为 F4 CDF 容差 |",
        f"| F4 事件窗 | `{FULL_WINDOW_S}` s，必要时一次延长至 `{MAXIMUM_WINDOW_S}` s | 6/6 case right-censored/unresolved |",
        f"| residence | gravity-time `{RESIDENCE_GRAVITY_TIME_S}` s；输出 residence CDF | 只有 `{sidecars['residence_complete_case_count']}/{sidecars['case_count']}` 结果侧车含完整字段，无 acceptance 容差 |",
            f"| 事件容差 | endpoint `{EVENT_ENDPOINT_TOLERANCE_M}` m；saved-chord crossings `0` | migration spec 已登记，acceptance/preflight 未执行 |",
            "",
            "质量闭合在保留的六个 case 中为 true，但质量闭合不能抵销未知质量和 right-censor。所有几何 seed 继续留在 source 分母中。",
        "",
        "## 逐例侧车与恢复",
        "",
        "| case | result 侧车 | CDF/residence | event 字段 | checkpoint integrity | generation |",
        "|---|---|---|---|---|---|",
    ]
    for row in sidecars["cases"]:
        checkpoint = row["checkpoint"]
        lines.append(
            f"| `{row['canary_id']}` | {str(row['result_exists']).lower()} | "
            f"{str(row['cdf_fields_present'] and row['residence_fields_present']).lower()} | "
            f"{str(row['event_fields_present']).lower()} | "
            f"{str(checkpoint['checkpoint_pass_from_case_audit'] and checkpoint['state_hash_pass_from_case_audit']).lower()} | "
            f"{str(checkpoint['content_addressed_generation']).lower()} |"
        )
    lines.extend(
        [
            "",
            f"source-window audit 记录了 `{sidecars['case_count']}` 个 case 和 `{sidecars['checkpoint_integrity_pass_count']}` 个 checkpoint hash pass；但只有 `{sidecars['formal_acceptance_receipt_count']}` 个结果带 `core.material.acceptance.v1` 回执。checkpoint 可恢复性证据不等于材料 acceptance。",
            "",
            "full-source contract 要求 frame `0..1085`、frame-40 recovery、每 native frame checkpoint 和 content-addressed append-only generation。当前 root review 的 `authorized_one_cpu_only=false`，候选 output stem 仍为空；这次 audit 不会执行它。",
            "",
            "## 接口缺口",
            "",
            f"- `core_material.py` 已产生 F4 `residence_cdf` 和 event-window 摘要，但没有 tallwall120 schema 或 content-addressed generation checkpoint；版本化 tallwall tracer 自己具备 schema/checkpoint-v2/generation。",
            f"- `core_material_acceptance.py` 的 per-source unknown 与通用 CDF difference 检查存在，但没有 tallwall120 schema/checkpoint-v2、residence CDF、F4 event tolerance、generation history 或逐矩阵 case acceptance。",
            f"- `f4_macro_t2_sidecar_preflight_v1.py` 保留 unknown/event/matrix negative 状态和 sidecar provenance，但没有调用 `audit_material_h5`，也没有逐例 residence/CDF、事件容差或 recovery receipt 汇总。",
            "",
            "## 仍阻塞宏观 T2 的条件",
            "",
        ]
    )
    for index, reason in enumerate(audit["blocking_reasons"], start=1):
        lines.append(f"{index}. {reason}")
    lines.extend(
        [
            "",
            "本回执只新增一份 JSON 和中文报告；registry、ledger、T1/T2 分母、阈值和旧 evidence 均未修改。",
            "",
            "## 输入哈希",
            "",
        ]
    )
    for name, item in audit["input_bindings"].items():
        lines.append(f"- `{name}`：`{item['path']}` — `{item['sha256']}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_lab_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=default_lab_root)
    parser.add_argument("--output", type=Path, default=default_lab_root / DEFAULT_OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=default_lab_root / DEFAULT_REPORT_NAME)
    args = parser.parse_args()
    lab_root = args.lab_root.resolve()
    evidence = build_audit(lab_root)
    output = args.output.resolve()
    report = args.report.resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite an existing gap audit artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(evidence, output), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": evidence["schema"],
                "status": evidence["status"],
                "T2_macro": evidence["T2_macro"],
                "T2_path": evidence["T2_path"],
                "admission_surface_pass": evidence["admission_surface_pass"],
                "output": str(output),
                "report": str(report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
