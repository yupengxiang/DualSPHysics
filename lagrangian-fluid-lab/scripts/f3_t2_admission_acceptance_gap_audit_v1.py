#!/usr/bin/env python3
"""Read-only F3 macro-T2 admission/acceptance gap audit.

This audit closes the evidence gap between the retained F3 material receipts
and the acceptance surface that would have to consume them.  It reads JSON
receipts and source text only.  It does not open HDF5, start a solver or GPU,
submit a queue job, or mutate a registry, ledger, matrix, denominator, or
threshold.  A structurally complete receipt remains diagnostic evidence and
cannot grant material or macro T2 credit.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "core.material.f3.t2.admission_acceptance_gap_audit.v1"
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
NATIVE_INTERVAL_S = 0.002
NATIVE_CADENCE_TOLERANCE_S = 5.0e-5
FULL_WINDOW_S = 8.35

DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f3-t2-admission-acceptance-gap-audit-20260921.json"
)
DEFAULT_REPORT_NAME = "reports/F3-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-21.zh-CN.md"


INPUTS: dict[str, Path] = {
    "core_material": Path("scripts/core_material.py"),
    "core_material_acceptance": Path("scripts/core_material_acceptance.py"),
    "native_mls": Path("scripts/f3_native_volume_mls.py"),
    "native_mls_compare": Path("scripts/f3_native_volume_mls_compare.py"),
    "native_cadence_adapter": Path("scripts/f3_native_cadence_adapter_v1.py"),
    "source_window_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-f4-t2-cpu-source-window-audit-v1-20260920.json"
    ),
    "matrix_gap_audit": Path(
        "campaigns/core-v1/material/evidence/f3-native-mls-33-matrix-gap-audit-v1.json"
    ),
    "matrix_asset_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-volume-mls-f3-matrix-asset-audit-v3-20260919.json"
    ),
    "native_cadence_preflight": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-cadence-adapter-v1-preflight-20260920.json"
    ),
    "native_cadence_selection": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-cadence-adapter-v1-every-fifth-selection-20260920.json"
    ),
    "native_cadence_canary": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-cadence-bounded-canary-evidence-v1.json"
    ),
    "native_cadence_root_review": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-native-cadence-adapter-v1-root-review-20260920.json"
    ),
    "comparison": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-adapter-rows29-31-terminal-comparison-20260920.json"
    ),
    "six_row_diagnostic": Path(
        "campaigns/core-v1/material/evidence/f3-six-row-diagnostic-final.json"
    ),
    "unknown_gate_v1": Path(
        "campaigns/core-v1/material/evidence/f3-v1-seeds4096-unknown-gate-root-v1.json"
    ),
    "unknown_gate_v3": Path(
        "campaigns/core-v1/material/evidence/f3-v3-4096-unknown-gate-root-v1.json"
    ),
    "t1_qualification": Path("campaigns/core-v1/evidence/f3-inherited-qualification.json"),
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
    """Resolve lab-relative paths and historical absolute evidence paths."""
    value_path = Path(value)
    if value_path.is_absolute():
        return value_path
    root = Path(lab_root).resolve()
    candidates = (root / value_path, root.parent / value_path)
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
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _bool(value: Any) -> bool:
    return value is True


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def summarize_source_window(source_window: dict[str, Any]) -> dict[str, Any]:
    """Summarize the retained F3 source-window audit without reopening HDF5."""
    rows = source_window.get("f3", {}).get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("source-window audit has no F3 row list")
    summarized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("F3 source-window row is not an object")
        source = row.get("source_audit") or {}
        trace = row.get("trace_audit") or {}
        cdf_rows = row.get("cdf_comparison") or {}
        cdf_values = [
            float(item["maximum"])
            for item in cdf_rows.values()
            if isinstance(item, dict) and _number(item.get("maximum")) is not None
        ]
        source_rows = trace.get("source_rows") or []
        source_unknown = [
            {
                "source_id": item.get("source_id"),
                "denominator": item.get("seed_denominator"),
                "unknown_count": item.get("terminal_unknown_count"),
                "unknown_fraction": item.get("terminal_unknown_fraction"),
                "gate_pass": _bool(item.get("unknown_gate_pass")),
                "first_failure_frame": item.get("first_failure_frame"),
                "first_failure_time_s": item.get("first_failure_time_s"),
                "first_failure_reason_counts": item.get("first_failure_reason_counts", {}),
            }
            for item in source_rows
            if isinstance(item, dict)
        ]
        checkpoint = trace.get("checkpoint") or {}
        summarized.append(
            {
                "row": row.get("row"),
                "case_id": row.get("case_id"),
                "failure_classification": list(row.get("failure_classification", [])),
                "source_window": {
                    "frames": source.get("frames_scanned"),
                    "particles": source.get("particle_count"),
                    "time_end_s": (source.get("cadence") or {}).get("time_end_s"),
                    "integrity_pass": _bool(source.get("integrity_pass")),
                    "mass_closure_pass": _bool((source.get("mass") or {}).get("mass_closure_pass")),
                    "cadence_pass": _bool((source.get("cadence") or {}).get("cadence_pass")),
                    "max_timestamp_error_s": (source.get("cadence") or {}).get("max_abs_timestamp_error_s"),
                    "hash_pass": _bool((source.get("hash") or {}).get("pass")),
                },
                "trace": {
                    "schema": trace.get("binding_schema"),
                    "frames": trace.get("frames"),
                    "seeds": trace.get("seed_count"),
                    "integrity_pass": _bool(trace.get("integrity_pass")),
                    "mass_closure_pass": _bool((trace.get("seed_mass_closure") or {}).get("pass")),
                    "cadence_pass": _bool((trace.get("cadence") or {}).get("cadence_pass")),
                    "reader_reconstruction_pass": _bool(trace.get("reader_reconstruction_pass")),
                    "source_hash_pass": _bool(trace.get("source_hash_pass")),
                    "native_mass_match_pass": _bool((trace.get("native_mass_match") or {}).get("pass")),
                    "checkpoint_pass": _bool(checkpoint.get("pass"))
                    and _bool(checkpoint.get("state_hash_pass")),
                },
                "unknown": {
                    "maximum_fraction": (trace.get("unknown_gate") or {}).get(
                        "maximum_source_unknown_fraction"
                    ),
                    "limit": (trace.get("unknown_gate") or {}).get("limit", UNKNOWN_LIMIT),
                    "pass": _bool((trace.get("unknown_gate") or {}).get("pass")),
                    "source_rows": source_unknown,
                },
                "cdf": {
                    "source_count": len(cdf_rows),
                    "maximum": max(cdf_values) if cdf_values else None,
                    "limit": CDF_LIMIT,
                    "pass": bool(cdf_values) and max(cdf_values) <= CDF_LIMIT,
                },
            }
        )
    unknown_values = [
        _number(row["unknown"]["maximum_fraction"])
        for row in summarized
        if _number(row["unknown"]["maximum_fraction"]) is not None
    ]
    cdf_values = [
        _number(row["cdf"]["maximum"])
        for row in summarized
        if _number(row["cdf"]["maximum"]) is not None
    ]
    return {
        "row_count": len(summarized),
        "rows": summarized,
        "source_window_integrity_pass": bool(summarized)
        and all(
            row["source_window"]["integrity_pass"]
            and row["source_window"]["mass_closure_pass"]
            and row["source_window"]["cadence_pass"]
            and row["source_window"]["hash_pass"]
            and row["trace"]["integrity_pass"]
            and row["trace"]["mass_closure_pass"]
            and row["trace"]["reader_reconstruction_pass"]
            and row["trace"]["source_hash_pass"]
            and row["trace"]["native_mass_match_pass"]
            and row["trace"]["checkpoint_pass"]
            for row in summarized
        ),
        "unknown_mass": {
            "limit": UNKNOWN_LIMIT,
            "maximum_observed": max(unknown_values) if unknown_values else None,
            "failing_row_count": sum(not row["unknown"]["pass"] for row in summarized),
            "failing_source_count": sum(
                not source["gate_pass"]
                for row in summarized
                for source in row["unknown"]["source_rows"]
            ),
            "all_rows_pass": bool(summarized) and all(row["unknown"]["pass"] for row in summarized),
        },
        "cdf": {
            "limit": CDF_LIMIT,
            "maximum_observed": max(cdf_values) if cdf_values else None,
            "failing_row_count": sum(not row["cdf"]["pass"] for row in summarized),
            "all_rows_pass": bool(summarized) and all(row["cdf"]["pass"] for row in summarized),
        },
    }


def summarize_matrix(matrix_gap: dict[str, Any], matrix_assets: dict[str, Any]) -> dict[str, Any]:
    rows = matrix_gap.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("matrix gap audit has no rows")
    statuses = Counter(str(row.get("status")) for row in rows if isinstance(row, dict))
    stages = Counter(str(row.get("matrix_stage")) for row in rows if isinstance(row, dict))
    diagnostic_rows = [
        row.get("matrix_index")
        for row in rows
        if isinstance(row, dict) and str(row.get("status", "")).endswith("diagnostic_observed")
    ]
    asset_summary = matrix_assets.get("row_status_summary", {})
    return {
        "registered_row_count": len(rows),
        "registered_row_order": (matrix_gap.get("matrix_binding") or {}).get("canonical_row_order"),
        "stage_counts": dict(stages),
        "status_counts": dict(statuses),
        "diagnostic_terminal_rows": sorted(
            int(index) for index in diagnostic_rows if isinstance(index, int)
        ),
        "asset_status_summary": asset_summary,
        "formal_acceptance_receipt_count": 0,
        "material_matrix_ready": False,
        "qualification_credit": "none",
        "gap_groups": matrix_gap.get("gap_groups", []),
        "next_minimal_cpu_batch": matrix_gap.get("next_minimal_cpu_batch_after_source_resolution", {}),
        "interpretation": (
            "The 33 rows are a registered diagnostic overlay.  Row completion or a "
            "terminal receipt is not acceptance; every row still requires an independent "
            "fixed-gate material acceptance record."
        ),
    }


def summarize_cadence(
    preflight: dict[str, Any],
    selection: dict[str, Any],
    canary: dict[str, Any],
    root_review: dict[str, Any],
) -> dict[str, Any]:
    source = preflight.get("source", {})
    execution = canary.get("execution", {})
    source_cadence_pass = _bool(source.get("cadence_pass"))
    direct_selection = (
        selection.get("selection_mode") == "every_fifth_direct_native_frame"
        and selection.get("interpolation") is False
        and selection.get("source_native_saved_interval_s") == NATIVE_INTERVAL_S
        and selection.get("target_nominal_interval_s") == 0.01
    )
    return {
        "native_interval_s": NATIVE_INTERVAL_S,
        "source_integrity_tolerance_s": NATIVE_CADENCE_TOLERANCE_S,
        "source": {
            "frames": source.get("frames"),
            "time_end_s": source.get("time_end_s"),
            "cadence_pass": source_cadence_pass,
            "interpolation": source.get("interpolation"),
            "max_interval_error_s": source.get("max_interval_error_s"),
            "max_cumulative_time_error_s": source.get("max_cumulative_time_error_s"),
            "full_event_window_available": source.get("full_event_window_available"),
        },
        "direct_every_fifth_view": {
            "pass": direct_selection,
            "mode": selection.get("selection_mode"),
            "source_frame_count": selection.get("source_frame_count"),
            "logical_frame_count": selection.get("logical_frame_count"),
            "interpolation": selection.get("interpolation"),
            "interpretation": selection.get("derived_view_role"),
        },
        "bounded_canary": {
            "committed_frames": execution.get("committed_frames"),
            "time_end_s": execution.get("time_end_s"),
            "full_event_window": execution.get("full_event_window"),
            "right_censored": execution.get("right_censored"),
            "mass_closed": execution.get("mass_closed"),
            "matrix_credit": canary.get("matrix_credit"),
            "qualification_claim": canary.get("qualification_claim"),
        },
        "root_review": {
            "decision": root_review.get("decision"),
            "full_event_window_required_for_acceptance": (root_review.get("execution_policy") or {}).get(
                "full_event_window_required_for_acceptance"
            ),
            "right_censored_canary_credit": (root_review.get("execution_policy") or {}).get(
                "right_censored_canary_credit"
            ),
            "queue_mutation": (root_review.get("authorization") or {}).get("queue_mutation"),
            "solver_launch": (root_review.get("authorization") or {}).get("solver_launch"),
        },
        "source_preflight_pass": source_cadence_pass and direct_selection,
        "material_acceptance_pass": False,
        "interpretation": (
            "The native .002 source and direct every-fifth view are valid provenance. "
            "The recovered five-frame canary is right-censored and therefore cannot "
            "establish a full-window material acceptance gate."
        ),
    }


def inspect_code_contracts(
    core_material: str,
    acceptance: str,
    native_mls: str,
    native_compare: str,
    cadence_adapter: str,
) -> dict[str, Any]:
    """Inspect acceptance surfaces from source text without importing workers."""
    return {
        "core_material": {
            "weighted_cdf": "def weighted_cdf(" in core_material,
            "f3_residence_cdf_summary": "residence_cdf" in core_material,
            "f3_event_definition": "event_definition" in core_material,
            "f3_event_window_summary": "event_window_complete" in core_material,
            "content_addressed_checkpoint": "content-addressed" in core_material,
        },
        "native_mls": {
            "trace_schema_present": _contains(native_mls, "core.material.f3.native_volume_mls.trace.v1"),
            "native_checkpoint_schema_present": _contains(
                native_mls, "core.material.f3.native_volume_mls.checkpoint.v1"
            ),
            "event_definition_present": "event_definition" in native_mls,
            "residence_state_present": "residence_opposite" in native_mls,
            "qualification_claim_none": 'QUALIFICATION_CLAIM = "none"' in native_mls,
        },
        "native_mls_compare": {
            "first_passage_cdf_bounds": "first_passage_cdf_bounds" in native_compare,
            "return_cdf_bounds": "return_cdf_bounds" in native_compare,
            "residence_cdf_bounds": "residence_cdf_bounds" in native_compare,
            "right_censored_unknown_policy": "permanent_unknown" in native_compare
            and "right-censor" in native_compare,
        },
        "core_material_acceptance": {
            "per_source_unknown_gate": "validate_source_coverage(" in acceptance,
            "generic_cdf_difference_gate": "cdf_sup_abs_difference" in acceptance,
            "native_mls_trace_schema": "core.material.f3.native_volume_mls.trace.v1" in acceptance
            or "core.material.f3.native_volume_mls.trace.v2" in acceptance,
            "native_mls_checkpoint_schema": "core.material.f3.native_volume_mls.checkpoint.v1" in acceptance
            or "core.material.f3.native_volume_mls.checkpoint.v2" in acceptance,
            "residence_cdf_gate": "residence_cdf" in acceptance,
            "f3_event_definition_gate": "event_definition" in acceptance,
            "native_cadence_gate": "native_interval" in acceptance or "cadence_pass" in acceptance,
            "per_matrix_acceptance_gate": "matrix_review" in acceptance or "matrix_index" in acceptance,
            "acceptance_receipt_schema": "core.material.acceptance.v1" in acceptance,
            "audit_material_h5": "def audit_material_h5(" in acceptance,
        },
        "native_cadence_adapter": {
            "fixed_unknown_gate": "per_source_unknown_fraction_max" in cadence_adapter,
            "fixed_cdf_gate": "cdf_sup_abs_max" in cadence_adapter,
            "full_event_window_required": "full_event_window_required_for_acceptance" in cadence_adapter,
            "right_censored_zero_credit": "right_censored_counts_as_acceptance" in cadence_adapter,
            "direct_native_selection": "every_fifth_direct_native_frame" in cadence_adapter,
            "acceptance_receipt_bridge": "core.material.acceptance.v1" in cadence_adapter,
        },
    }


def summarize_comparison(comparison: dict[str, Any]) -> dict[str, Any]:
    source_comparison = comparison.get("source_comparison", {})
    rows: list[dict[str, Any]] = []
    for source_id, value in sorted(source_comparison.items(), key=lambda item: str(item[0])):
        if not isinstance(value, dict):
            continue
        differences = value.get("difference", {})
        cdf_bounds = value.get("cdf_sup_difference_bounds", {})
        rows.append(
            {
                "source": str(source_id),
                "first_passage_sup": differences.get("first_passage_cdf_sup_abs_difference_bound"),
                "return_sup": differences.get("return_cdf_sup_abs_difference_bound"),
                "residence_sup": differences.get("residence_cdf_sup_abs_difference_bound"),
                "has_residence_cdf_bounds": isinstance(cdf_bounds.get("residence"), dict),
            }
        )
    values = [
        _number(item.get("residence_sup"))
        for item in rows
        if _number(item.get("residence_sup")) is not None
    ]
    return {
        "schema": comparison.get("schema"),
        "status": comparison.get("status"),
        "qualification_claim": comparison.get("qualification_claim"),
        "source_count": len(rows),
        "sources": rows,
        "residence_cdf_present": bool(rows) and all(row["has_residence_cdf_bounds"] for row in rows),
        "maximum_residence_sup_observed": max(values) if values else None,
        "denominator_policy": comparison.get("denominator_policy"),
    }


def build_audit(lab_root: Path) -> dict[str, Any]:
    """Build the immutable gap receipt from JSON and source text only."""
    lab_root = Path(lab_root).resolve()
    input_bindings = {name: bind_file(lab_root, path) for name, path in INPUTS.items()}
    source_window = load_json(resolve_path(lab_root, INPUTS["source_window_audit"]))
    matrix_gap = load_json(resolve_path(lab_root, INPUTS["matrix_gap_audit"]))
    matrix_assets = load_json(resolve_path(lab_root, INPUTS["matrix_asset_audit"]))
    cadence_preflight = load_json(resolve_path(lab_root, INPUTS["native_cadence_preflight"]))
    cadence_selection = load_json(resolve_path(lab_root, INPUTS["native_cadence_selection"]))
    cadence_canary = load_json(resolve_path(lab_root, INPUTS["native_cadence_canary"]))
    cadence_root_review = load_json(resolve_path(lab_root, INPUTS["native_cadence_root_review"]))
    comparison = load_json(resolve_path(lab_root, INPUTS["comparison"]))
    six_row = load_json(resolve_path(lab_root, INPUTS["six_row_diagnostic"]))
    unknown_v1 = load_json(resolve_path(lab_root, INPUTS["unknown_gate_v1"]))
    unknown_v3 = load_json(resolve_path(lab_root, INPUTS["unknown_gate_v3"]))
    t1 = load_json(resolve_path(lab_root, INPUTS["t1_qualification"]))

    source_summary = summarize_source_window(source_window)
    matrix_summary = summarize_matrix(matrix_gap, matrix_assets)
    cadence_summary = summarize_cadence(
        cadence_preflight, cadence_selection, cadence_canary, cadence_root_review
    )
    comparison_summary = summarize_comparison(comparison)
    code_contracts = inspect_code_contracts(
        resolve_path(lab_root, INPUTS["core_material"]).read_text(encoding="utf-8"),
        resolve_path(lab_root, INPUTS["core_material_acceptance"]).read_text(encoding="utf-8"),
        resolve_path(lab_root, INPUTS["native_mls"]).read_text(encoding="utf-8"),
        resolve_path(lab_root, INPUTS["native_mls_compare"]).read_text(encoding="utf-8"),
        resolve_path(lab_root, INPUTS["native_cadence_adapter"]).read_text(encoding="utf-8"),
    )

    acceptance_gates = {
        "source_window_integrity": source_summary["source_window_integrity_pass"],
        "native_cadence_source_preflight": cadence_summary["source_preflight_pass"],
        "native_cadence_material_acceptance": cadence_summary["material_acceptance_pass"],
        "unknown_mass_scientific_gate": source_summary["unknown_mass"]["all_rows_pass"],
        "cdf_scientific_gate": source_summary["cdf"]["all_rows_pass"],
        "residence_cdf_emitted_by_comparison": comparison_summary["residence_cdf_present"],
        "residence_cdf_acceptance_gate": code_contracts["core_material_acceptance"]["residence_cdf_gate"],
        "event_window_acceptance_for_bounded_canary": bool(
            cadence_summary["bounded_canary"]["full_event_window"]
        ),
        "native_trace_schema_accepted": code_contracts["core_material_acceptance"][
            "native_mls_trace_schema"
        ],
        "native_checkpoint_schema_accepted": code_contracts["core_material_acceptance"][
            "native_mls_checkpoint_schema"
        ],
        "f3_event_definition_acceptance": code_contracts["core_material_acceptance"][
            "f3_event_definition_gate"
        ],
        "per_matrix_case_acceptance": matrix_summary["formal_acceptance_receipt_count"]
        == matrix_summary["registered_row_count"]
        and matrix_summary["registered_row_count"] > 0,
        "material_matrix_ready": matrix_summary["material_matrix_ready"],
    }
    admission_surface_pass = all(acceptance_gates.values())

    unknown_max = source_summary["unknown_mass"]["maximum_observed"]
    cdf_max = source_summary["cdf"]["maximum_observed"]
    blocking_reasons = [
        f"retained F3 source-window rows fail fixed per-source unknown mass: maximum {unknown_max} > {UNKNOWN_LIMIT}",
        f"retained F3 CDF comparison fails fixed sup limit: maximum {cdf_max} > {CDF_LIMIT}",
        "native .002 source cadence and direct every-fifth provenance pass, but the recovered five-frame canary is right-censored and has zero matrix credit",
        "native MLS comparison emits first-passage, return, and residence CDF bounds, while core_material.py exposes only residence means and core_material_acceptance has no residence-CDF gate",
        "core_material_acceptance does not admit the native-MLS trace/checkpoint schemas, so current native material receipts have no shared acceptance route",
        f"the registered 33-row overlay is diagnostic only: {matrix_summary['registered_row_count']} rows, {len(matrix_summary['diagnostic_terminal_rows'])} terminal diagnostics, and zero formal acceptance receipts",
        "exact source assets remain missing for rows 16-23, 29, 31 and native-dense amp=1.1 rows 26-27; development cases cannot substitute for exact controls",
    ]

    return {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "blocked_for_macro_t2" if not admission_surface_pass else "admission_surface_complete_but_no_t2_claim",
        "qualification_claim": "none",
        "qualification_credit": "none",
        "T2_macro": False,
        "T2_path": False,
        "scope": {
            "family": "F3",
            "focus": "F3 macro T2 admission/acceptance gap",
            "json_and_source_only": True,
            "terminal_h5_opened": False,
            "source_h5_opened": False,
        },
        "registered_gates": {
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
            "f3_cdf_sup_abs_difference_max": CDF_LIMIT,
            "native_source_interval_s": NATIVE_INTERVAL_S,
            "native_source_cadence_integrity_tolerance_s": NATIVE_CADENCE_TOLERANCE_S,
            "full_source_window_s": FULL_WINDOW_S,
            "denominator_policy": "all independent geometric seeds in each source; unknown and right-censored mass remain in the denominator",
            "right_censored_is_not_acceptance": True,
            "no_partial_credit": True,
        },
        "current_qualification_state": {
            "T1_numerical": _bool(t1.get("T1_numerical")),
            "T2_macro": _bool(t1.get("T2_macro")),
            "T2_path": _bool(t1.get("T2_path")),
            "matrix_complete_in_inherited_t1": _bool(t1.get("matrix_complete")),
            "overlay_matrix_rows": matrix_summary["registered_row_count"],
            "overall_T2_credit": 0,
            "core_gate_changed": False,
        },
        "observed_gate_comparison": {
            "source_window": source_summary,
            "native_cadence": cadence_summary,
            "comparison": comparison_summary,
            "six_row_diagnostic": {
                "completed": six_row.get("completed"),
                "unknown_gate_pass": six_row.get("decision", "").startswith("passed"),
                "T2_macro": six_row.get("T2_macro"),
                "qualification_matrix_33_complete": six_row.get("qualification_matrix_33_complete"),
            },
            "unknown_gate_v1": unknown_v1,
            "unknown_gate_v3": unknown_v3,
        },
        "matrix": matrix_summary,
        "code_contracts": code_contracts,
        "acceptance_gates": acceptance_gates,
        "admission_surface_pass": admission_surface_pass,
        "blocking_reasons": blocking_reasons,
        "minimal_next_executable_repair": {
            "status": "required_before_any_future_material_acceptance",
            "priority": "Core W0/W1",
            "action": "add one read-only native-MLS acceptance adapter and receipt bridge",
            "must_accept": [
                "core.material.f3.native_volume_mls.trace.v1/v2 binding and checkpoint schema",
                "full source-window and native-frame identity/cadence provenance",
                "per-source unknown mass with all geometric seeds retained",
                "first_passage_cdf_bounds, return_cdf_bounds, and residence_cdf_bounds",
                "right-censored event semantics and full-window completion",
            ],
            "must_preserve": [
                "unknown <= 0.01 and CDF sup <= 0.02",
                "all source denominators and no partial credit",
                "33-row matrix definition and exact source lineage",
                "qualification_claim=none until an independent collector grants credit",
            ],
            "follow_on_evidence": {
                "cpu_only_source_available_rows": [28, 32],
                "existing_dense_row_to_terminalize": [24],
                "exact_source_rows_requiring_root_owned_cfd": [16, 17, 18, 19, 20, 21, 22, 23, 26, 27, 29, 31],
                "qualification_effect": "none until all fixed gates and all 33 rows have independent acceptance receipts",
            },
            "audit_did_not_execute": True,
        },
        "execution_constraints": {
            "read_only": True,
            "json_and_source_only": True,
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
        "input_bindings": input_bindings,
        "interpretation_boundary": (
            "This is a read-only admission/acceptance gap audit.  It preserves negative "
            "scientific evidence and reports missing acceptance surfaces as fail-closed; "
            "it does not grant material or macro T2 credit."
        ),
    }


def render_report(audit: dict[str, Any], evidence_path: Path) -> str:
    source = audit["observed_gate_comparison"]["source_window"]
    cadence = audit["observed_gate_comparison"]["native_cadence"]
    matrix = audit["matrix"]
    gates = audit["acceptance_gates"]
    output_sha = sha256_file(evidence_path) if evidence_path.is_file() else "written-after-report"
    status = "通过" if audit["admission_surface_pass"] else "阻塞"
    lines = [
        "# F3 宏观 T2 admission/acceptance gap audit（2026-09-21）",
        "",
        f"结论：当前 `T2_macro=false`、`T2_path=false`，admission surface 为 `{status}`；本次审计保留 `qualification_claim=none` 和 zero credit。只读取 JSON 与源码，没有打开 HDF5、启动 solver/GPU/queue，或修改 registry、ledger、matrix、T1/T2 分母及阈值。",
        "",
        f"机器回执：`{evidence_path}`；SHA-256：`{output_sha}`。",
        "",
        "## 固定门与当前证据",
        "",
        "| 门 | 固定规则 | 审计结果 |",
        "|---|---:|---|",
        f"| source-window / 质量闭合 | 两条完整 F3 row，hash、reader、mass、checkpoint 通过 | `{str(gates['source_window_integrity']).lower()}`（{source['row_count']}/{source['row_count']}） |",
        f"| native cadence provenance | `.002 s` source，误差容差 `{NATIVE_CADENCE_TOLERANCE_S}` s；every-fifth 必须 direct、无插值 | `{str(gates['native_cadence_source_preflight']).lower()}`；短 canary 仍 right-censored |",
        f"| 每 source unknown mass | `<= {UNKNOWN_LIMIT}` | `{str(gates['unknown_mass_scientific_gate']).lower()}`；最大 `{source['unknown_mass']['maximum_observed']}`，{source['unknown_mass']['failing_source_count']} 个 source 半区失败 |",
        f"| F3 CDF sup | `<= {CDF_LIMIT}` | `{str(gates['cdf_scientific_gate']).lower()}`；最大 `{source['cdf']['maximum_observed']}` |",
        f"| residence CDF | 必须保留全分母与 censor bounds，并有 acceptance gate | 输出 `{str(gates['residence_cdf_emitted_by_comparison']).lower()}`；接纳 `{str(gates['residence_cdf_acceptance_gate']).lower()}` |",
        f"| event window | full source window；right-censor 不计 acceptance | bounded canary full-window `{str(gates['event_window_acceptance_for_bounded_canary']).lower()}` |",
        "",
        "两条 4096-seed source-window 的结构审计、质量闭合、native frame/cadence 结构和 checkpoint/hash 通过；row 29 的最大 source unknown 为 `0.01220703125`，row 31 为 `0.015625`。两行 CDF comparison 都超过 `0.02`，因此完整性通过不能转化为科学资格。",
        "",
        "## 33-row matrix",
        "",
        f"规范矩阵为 `{matrix['registered_row_count']}` 行（`{matrix['registered_row_order']}`）。当前状态计数：`{json.dumps(matrix['status_counts'], ensure_ascii=False, sort_keys=True)}`。终态诊断、matched-decimation 视图、running attempt 或 source-available-not-submitted 都不产生 acceptance receipt；当前 formal acceptance receipt 为 `0`，matrix ready 为 `false`。",
        "",
        "精确 amp=.95/.1.05 源与 native-dense amp=1.1 源仍缺失；development case 不能重命名或插值替代。row 24 的 dense material postprocess 和 row 30 的相关 v3 s2 诊断也不能填充 canonical s4 row。",
        "",
        "## 材料侧车接口缺口",
        "",
        "native MLS comparator 已输出 first-passage、return 和 residence CDF bounds，并保留 unknown/right-censor 分母；基础 `core_material.py` 只提供 residence 均值摘要。`core_material_acceptance.py` 有 per-source unknown 与通用 CDF difference 检查，但没有接纳 native-MLS trace/checkpoint schema、residence-CDF gate、F3 event definition 或 native cadence gate，因此现有 native material 结果没有共享 acceptance 路径。",
        "",
        "## 下一步最小可执行修复",
        "",
        "先落地一个只读 native-MLS acceptance adapter/receipt bridge：绑定 trace/checkpoint schema、完整 source-window/cadence provenance、逐 source unknown、三类 CDF bounds、right-censored event semantics 和 full-window 状态；固定 unknown/CDF 门、全分母、33-row 定义与 `qualification_claim=none` 不变。随后才可按 exact source lineage 处理 source-available rows `28,32` 或 terminalize row `24`；缺失 exact source 的 rows `16–23,26,27,29,31` 仍须 root-owned CFD source。该顺序不会由本 audit 自动执行，也不会把 diagnostic 升级为 T2。",
        "",
        "## 回执边界",
        "",
        "本回执只新增 JSON 与中文报告；旧 evidence 未覆盖，solver/GPU/queue 未启动，registry/ledger/matrix 及任何科学分母、阈值均未改变。",
        "",
        "## 输入哈希",
        "",
    ]
    for name, binding in audit["input_bindings"].items():
        lines.append(f"- `{name}`：`{binding['path']}` — `{binding['sha256']}`")
    return "\n".join(lines) + "\n"


def write_artifacts(audit: dict[str, Any], output: Path, report: Path) -> None:
    output = Path(output).resolve()
    report = Path(report).resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite an existing F3 gap audit artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(audit, output), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=default_root)
    parser.add_argument("--output", type=Path, default=default_root / DEFAULT_OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=default_root / DEFAULT_REPORT_NAME)
    args = parser.parse_args(argv)
    root = args.lab_root.resolve()
    audit = build_audit(root)
    write_artifacts(audit, args.output, args.report)
    print(
        json.dumps(
            {
                "schema": audit["schema"],
                "status": audit["status"],
                "T2_macro": audit["T2_macro"],
                "T2_path": audit["T2_path"],
                "admission_surface_pass": audit["admission_surface_pass"],
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
