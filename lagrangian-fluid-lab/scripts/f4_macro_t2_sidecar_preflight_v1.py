#!/usr/bin/env python3
"""Read-only preflight for an independent F4 macro-T2 closure path.

The preflight joins retained F4 material negative evidence, the native004
cadence/stride source audit, the 33-row overlay mapping, and the static
15-cell CFD qualification evaluator.  It deliberately does not open active
H5 products, submit jobs, alter thresholds, or write a registry/ledger.  A
valid exact-stride sidecar is recorded as provenance only; it cannot grant a
material or macro-T2 claim while the material gates and event windows fail.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
from typing import Any


SCHEMA = "core.material.f4.macro_t2_sidecar_preflight.v1"
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
FULL_EVENT_WINDOW_S = 4.34
MAX_EVENT_WINDOW_S = 8.68

NEGATIVE_EVIDENCE = Path(
    "campaigns/core-v1/material/evidence/f4-material-negative-evidence-audit-20260920.json"
)
CADENCE_DIAGNOSIS = Path(
    "campaigns/core-v1/material/evidence/f4-native004-cadence-terminal-diagnosis-v1/"
    "cadence-terminal-diagnosis-v2.json"
)
CADENCE_SOURCE_AUDIT = Path(
    "campaigns/core-v1/material/evidence/f4-tallwall120-native004-cadence-source-audit-v1.json"
)
MATRIX_REVIEW = Path(
    "campaigns/core-v1/material/evidence/f4-resting-pool-33-to-15-matrix-review-2026-09-19.json"
)
QUALIFICATION_MANIFEST = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-qualification-evaluator-v2.json"
)
QUALIFICATION_EVALUATOR = Path("scripts/f4_tallwall_qualification_evaluator_v2.py")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def resolve_path(lab_root: Path, relative: Path) -> Path:
    path = Path(relative)
    if path.is_absolute():
        return path
    return (lab_root / path).resolve()


def bind_input(lab_root: Path, relative: Path) -> dict[str, Any]:
    path = resolve_path(lab_root, relative)
    result: dict[str, Any] = {
        "path": str(relative),
        "absolute_path": str(path),
        "exists": path.is_file(),
        "sha256": sha256_file(path) if path.is_file() else None,
    }
    if not result["exists"]:
        raise FileNotFoundError(path)
    return result


def _canary_row(
    item: dict[str, Any],
    *,
    variant: str | None = None,
    result_path: str | list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": item["id"] if variant is None else f"{item['id']}:{variant}",
        "unknown_fraction_max": item.get("unknown_fraction_max"),
        "common_reliable_path_coverage": item.get("common_reliable_path_coverage"),
        "mass_closed": item.get("mass_closed"),
        "event_window_complete": item.get("event_window_complete") is True,
        "event_window_status": item.get("event_window_status", "right_censored_or_unresolved"),
        "unknown_gate_pass": item.get("unknown_gate_pass") is True,
        "qualified_T2_macro": item.get("qualified_T2_macro") is True,
        "qualified_T2_path": item.get("qualified_T2_path") is True,
        "negative_finding": item.get("negative_finding"),
    }
    if variant is not None:
        values = item.get("unknown_fraction_max_by_variant", {})
        coverage = item.get("common_reliable_path_coverage_by_variant", {})
        row["unknown_fraction_max"] = values.get(variant)
        row["common_reliable_path_coverage"] = coverage.get(variant)
        row["unknown_gate_pass"] = bool(
            row["unknown_fraction_max"] is not None
            and float(row["unknown_fraction_max"]) <= UNKNOWN_LIMIT
        )
        row["result_path"] = result_path
    elif result_path is not None:
        row["result_path"] = result_path
    return row


def summarize_canaries(negative: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in negative.get("canaries", [])}
    rows = [
        _canary_row(
            by_id["f4_real_material_baseline_s2"],
            result_path=by_id["f4_real_material_baseline_s2"].get("result"),
        ),
        _canary_row(
            by_id["f4_native_dense_pair_s2_s4"],
            result_path=by_id["f4_native_dense_pair_s2_s4"].get("result"),
        ),
        _canary_row(
            by_id["f4_repair_canaries_ess32_and_affine_bound"],
            variant="f4_ess32_v2",
            result_path=by_id["f4_repair_canaries_ess32_and_affine_bound"].get("result", [])[0],
        ),
        _canary_row(
            by_id["f4_repair_canaries_ess32_and_affine_bound"],
            variant="f4_affine_bound_v2",
            result_path=by_id["f4_repair_canaries_ess32_and_affine_bound"].get("result", [])[1],
        ),
        _canary_row(
            by_id["f4_tallwall120_short_canary"],
            result_path=by_id["f4_tallwall120_short_canary"].get("execution"),
        ),
    ]
    return rows


def sidecar_summary(source_audit: dict[str, Any]) -> dict[str, Any]:
    pair = source_audit["pair"]
    axis = source_audit["time_axis"]
    boundary = source_audit["qualification_boundary"]
    view_attributes = axis["view_attributes"]
    return {
        "native_source": {
            "path": pair["cell14_h5"]["path"],
            "sha256": pair["cell14_h5"]["sha256"],
            "frame_count": axis["cell14_native_frame_count"],
            "window_s": axis["cell14_window_s"],
            "max_material_step_s": axis["cell14_native_max_material_step_s"],
            "role": pair["cell14_role"],
        },
        "exact_stride_view": {
            "path": pair["view_h5"]["path"],
            "sha256": pair["view_h5"]["sha256"],
            "manifest_path": pair["view_manifest"]["path"],
            "manifest_sha256": pair["view_manifest"]["sha256"],
            "frame_count": axis["stride5_view_frame_count"],
            "max_material_step_s": axis["stride5_view_max_material_step_s"],
            "role": pair["derived_view_role"],
            "exact_rows_no_interpolation": view_attributes["view_exact_rows_no_interpolation"],
            "selection_rule": view_attributes["view_selection_rule"],
            "same_terminal_lineage": pair["same_terminal_lineage"],
        },
        "physical_control_equal_after_cadence_normalisation": source_audit[
            "physical_control_comparison"
        ]["normalised_prepared_config_equal"],
        "sidecar_provenance_pass": bool(
            pair["same_terminal_lineage"]
            and view_attributes["view_exact_rows_no_interpolation"]
            and axis["cell14_every_fifth_equals_cell04"]
            and axis["view_time_equals_cell14_every_fifth"]
        ),
        "source_view_is_not_independent_cfd": boundary["source_view_is_not_independent_cfd"],
        "material_reliability_status": boundary["material_reliability_status"],
        "qualification_claim": boundary["qualification_claim"],
        "t2_status": boundary["t2_status"],
        "sidecar_can_qualify_t2": False,
        "interpretation": (
            "The exact stride view is a provenance/cadence control over one terminal "
            "source lineage. It is not an independent CFD solve and carries no material "
            "qualification credit."
        ),
    }


def matrix_summary(matrix: dict[str, Any]) -> dict[str, Any]:
    template = matrix["full_t2_33_overlay_template"]
    cadence_rows = template["cadence_rows"]
    unavailable_cadence = [row for row in cadence_rows if not row["source_available_exact"]]
    pending_resolution = [
        row for row in template["resolution_substep_rows"]
        if "pending" in str(row.get("status", ""))
    ]
    pending_seed_density = [
        row for row in template["seed_density_rows"]
        if "pending" in str(row.get("status", ""))
    ]
    existing = matrix["existing_f4_cfd_matrix"]
    return {
        "template_total_rows": template["total_count"],
        "cadence_rows": template["cadence_count"],
        "exact_cadence_rows_available": len(cadence_rows) - len(unavailable_cadence),
        "exact_cadence_rows_missing": len(unavailable_cadence),
        "exact_cadence_missing_reasons": [row["reason"] for row in unavailable_cadence],
        "resolution_substep_rows": template["resolution_substep_count"],
        "resolution_material_overlays_pending": len(pending_resolution),
        "seed_density_rows": template["seed_density_count"],
        "seed_density_material_overlays_pending": len(pending_seed_density),
        "existing_cfd_cell_count": existing["cell_count"],
        "existing_cfd_matrix_sha256": existing["matrix_sha256"],
        "coverage_notes": matrix["coverage"],
        "material_matrix_ready": False,
        "qualification_claim": "none",
        "interpretation": (
            "The template maps source cells and records pending material overlays; "
            "source-cell availability is not material qualification."
        ),
    }


def static_evaluation_summary(lab_root: Path) -> dict[str, Any]:
    """Run the existing static evaluator without runtime/archive inputs."""
    evaluator_path = resolve_path(lab_root, QUALIFICATION_EVALUATOR)
    manifest_path = resolve_path(lab_root, QUALIFICATION_MANIFEST)
    if not evaluator_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("F4 static evaluator or manifest is missing")
    if str(lab_root) not in sys.path:
        sys.path.insert(0, str(lab_root))
    from scripts.f4_tallwall_qualification_evaluator_v2 import verify_static_manifest

    evaluated = verify_static_manifest(manifest_path)
    return {
        "evaluator_path": str(QUALIFICATION_EVALUATOR),
        "evaluator_sha256": sha256_file(evaluator_path),
        "manifest_path": str(QUALIFICATION_MANIFEST),
        "manifest_sha256": sha256_file(manifest_path),
        "scope_id": evaluated.get("scope_id"),
        "revision_id": evaluated.get("revision_id"),
        "static_contract_pass": evaluated.get("static_contract_pass"),
        "matrix_complete": evaluated.get("matrix_complete"),
        "T1_numerical": evaluated.get("T1_numerical"),
        "cell_count": evaluated.get("cell_count"),
        "scheduled_solver_cells": evaluated.get("scheduled_solver_cells"),
        "reused_canary_cells": evaluated.get("reused_canary_cells"),
        "promotion_status": evaluated.get("promotion_status"),
        "qualification_claim": evaluated.get("qualification_claim"),
    }


def build_preflight(lab_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    negative_path = resolve_path(lab_root, NEGATIVE_EVIDENCE)
    diagnosis_path = resolve_path(lab_root, CADENCE_DIAGNOSIS)
    source_audit_path = resolve_path(lab_root, CADENCE_SOURCE_AUDIT)
    matrix_path = resolve_path(lab_root, MATRIX_REVIEW)
    negative = load_json(negative_path)
    diagnosis = load_json(diagnosis_path)
    source_audit = load_json(source_audit_path)
    matrix = load_json(matrix_path)
    canaries = summarize_canaries(negative)
    unknown_values = [
        float(row["unknown_fraction_max"])
        for row in canaries
        if row["unknown_fraction_max"] is not None
    ]
    event_complete = bool(canaries) and all(row["event_window_complete"] for row in canaries)
    unknown_pass = bool(unknown_values) and max(unknown_values) <= UNKNOWN_LIMIT
    all_mass_closed = bool(canaries) and all(row["mass_closed"] is True for row in canaries)
    static = static_evaluation_summary(lab_root)
    sidecar = sidecar_summary(source_audit)
    matrix_state = matrix_summary(matrix)
    diagnosis_conclusion = diagnosis["conclusion"]

    blocking_reasons = [
        (
            "all retained F4 material canaries fail the fixed per-source unknown-mass "
            f"gate ({max(unknown_values):.12g} maximum observed vs {UNKNOWN_LIMIT:g})"
        ),
        "all retained F4 material event windows are right-censored or unresolved; no terminal CDF qualification result exists",
        "native .002 cadence densification did not resolve the fixed reconstruction gate in the retained dense pair",
        "native004/stride5 sidecar is exact and hash-bound but is not independent CFD and remains uncalibrated with qualification claim none",
        "the 33-row F4 overlay template has four missing exact cadence rows and all 24 resolution plus five seed-density material overlays pending",
        "the static 15-cell F4 CFD evaluator is structurally valid but matrix_complete=false; this is a source-product state, not material T2 evidence",
    ]
    minimal_repair = {
        "hypothesis": (
            "The first-loss interval is dominated by the local reconstruction path near "
            "contact; cadence alone is insufficient. Reproduce the fixed reconstruction "
            "error with the existing geometry/wall binding and repair that implementation "
            "without changing its cap or unknown semantics."
        ),
        "diagnostic_anchor": {
            "native_first_failure_time_interval_s": diagnosis_conclusion[
                "native_first_failure_time_interval_s"
            ],
            "stride_first_failure_time_interval_s": diagnosis_conclusion[
                "stride_first_failure_time_interval_s"
            ],
            "reconstruction_error_gate_dominates": diagnosis_conclusion[
                "reconstruction_error_gate_dominates"
            ],
            "support_distance_or_wall_dominates": diagnosis_conclusion[
                "support_distance_or_wall_dominates"
            ],
        },
        "bounded_test_sequence": [
            "Run one fixed-seed, one-source-cell canary only across the native first-loss interval (~0.1600–0.1640 s), with the existing fixed reconstruction cap and unknown denominator.",
            "Require the corrected implementation to pass the fixed reconstruction gate at that interval while preserving source/destination mass closure and failure-event semantics.",
            "Only after that canary passes, resume one full 4.34 s F4 event window (extend to 8.68 s only under the registered right-censor policy) and require terminal unknown, CDF, residence, return, and coverage outputs.",
            "Then produce the missing exact cadence sources and the registered 33-row material overlays; a sidecar alone cannot substitute for these products.",
        ],
        "forbidden_shortcuts": [
            "do not raise or reinterpret the reconstruction cap",
            "do not relabel permanent unknown seeds as reliable",
            "do not treat the exact-stride view as an independent CFD solve",
            "do not call a .3/.4 s right-censored canary a full event result",
        ],
    }
    input_paths = [
        NEGATIVE_EVIDENCE,
        CADENCE_DIAGNOSIS,
        CADENCE_SOURCE_AUDIT,
        MATRIX_REVIEW,
        QUALIFICATION_MANIFEST,
        QUALIFICATION_EVALUATOR,
    ]
    input_evidence = [bind_input(lab_root, path) for path in input_paths]
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "blocked_for_qualification",
        "qualification_claim": "none",
        "t2_status": "not_qualified",
        "T2_macro": False,
        "T2_path": False,
        "audit_scope": (
            "Read-only F4 material/sidecar preflight. Existing JSON receipts and the "
            "static qualification manifest were hashed; no active H5 was opened and no "
            "solver, worker, registry, ledger, threshold, or historical score was changed."
        ),
        "execution_constraints": {
            "read_only": True,
            "cpu_only": True,
            "active_h5_opened": False,
            "new_job_submitted": False,
            "solver_started": False,
            "gpu_started": False,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "thresholds_changed": False,
            "historical_scores_modified": False,
        },
        "resource_accounting": {
            "runtime_seconds": time.perf_counter() - started,
            "max_rss_kib": int(max_rss),
            "active_h5_opened": False,
            "long_task_started": False,
        },
        "registered_gates": {
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
            "f3_cdf_sup_abs_difference_max": CDF_LIMIT,
            "full_event_window_s": FULL_EVENT_WINDOW_S,
            "maximum_right_censored_extension_s": MAX_EVENT_WINDOW_S,
            "gate_semantics": "all geometric seeds remain in the source denominator; right-censored events remain unresolved",
        },
        "canaries": canaries,
        "sidecar_status": sidecar,
        "matrix_status": matrix_state,
        "static_cfd_qualification_status": static,
        "gate_evaluation": {
            "all_mass_closed": all_mass_closed,
            "unknown_mass_pass": unknown_pass,
            "event_window_pass": event_complete,
            "cdf_gate_pass": False,
            "sidecar_provenance_pass": sidecar["sidecar_provenance_pass"],
            "sidecar_independent_cfd_pass": False,
            "f4_calibration_pass": False,
            "material_matrix_ready": matrix_state["material_matrix_ready"],
            "static_cfd_matrix_complete": static["matrix_complete"],
            "T2_macro": False,
            "T2_path": False,
        },
        "blocking_reasons": blocking_reasons,
        "minimal_repair_hypothesis": minimal_repair,
        "input_evidence": input_evidence,
        "interpretation_boundary": (
            "This record is a negative preflight and does not grant F4 T2 credit. "
            "A sidecar can establish source/view identity and cadence provenance, while "
            "material qualification still requires fixed-gate calibration, a complete "
            "event window, terminal unknown/CDF evidence, and the registered matrix."
        ),
    }


def render_report(evidence: dict[str, Any], evidence_path: Path) -> str:
    rows = evidence["canaries"]
    lines = [
        "# F4 Macro-T2 Sidecar Preflight (2026-09-20)",
        "",
        "结论：当前没有可接受的、独立于 F3 新原生 cadence 的 F4 宏观 T2 闭合路径。",
        "本次是只读 CPU preflight；`T2_macro=false`、`T2_path=false`，没有把 sidecar 或 right-censored canary 当作资格证据。",
        "",
        f"Evidence: `{evidence_path}`",
        f"Evidence SHA256: `{sha256_file(evidence_path) if evidence_path.is_file() else 'written-after-report'}`",
        "",
        "## 固定门值与 retained canaries",
        "",
        "| canary | unknown max | common reliable coverage | mass closed | event window |",
        "|---|---:|---:|---|---|",
    ]
    for row in rows:
        unknown = "NA" if row["unknown_fraction_max"] is None else f"{row['unknown_fraction_max']:.12g}"
        coverage = (
            "NA"
            if row["common_reliable_path_coverage"] is None
            else f"{row['common_reliable_path_coverage']:.12g}"
        )
        lines.append(
            f"| `{row['id']}` | {unknown} | {coverage} | "
            f"{str(row['mass_closed']).lower()} | {row['event_window_status']} |"
        )
    lines.extend(
        [
            "",
            f"The fixed unknown limit is `{evidence['registered_gates']['unknown_fraction_per_source_max']}`. "
            "All retained material rows fail it; mass closure alone does not qualify an event result.",
            "",
            "## Sidecar/source status",
            "",
            "The native004 source has a hash-bound exact-stride (every fifth row) view with no interpolation and matching terminal lineage. The audit also records that this view is not an independent CFD solve, the material reliability status is `uncalibrated`, and the qualification claim is `none`. It is usable for cadence/source provenance only.",
            "",
            "The retained native and stride terminal diagnosis places the first failure in the reconstruction gate (native interval "
            f"`{evidence['minimal_repair_hypothesis']['diagnostic_anchor']['native_first_failure_time_interval_s']}` s; stride interval "
            f"`{evidence['minimal_repair_hypothesis']['diagnostic_anchor']['stride_first_failure_time_interval_s']}` s). Cadence alone does not resolve it, while support distance/wall is not the dominant failure.",
            "",
            "## Matrix status",
            "",
            f"The 33-row template has `{evidence['matrix_status']['exact_cadence_rows_missing']}` exact cadence rows unavailable, `{evidence['matrix_status']['resolution_material_overlays_pending']}` resolution overlays pending, and `{evidence['matrix_status']['seed_density_material_overlays_pending']}` high-seed overlays pending. The static 15-cell CFD evaluator contract is valid but `matrix_complete=false`; source-cell availability is not material T2 evidence.",
            "",
            "## Smallest executable repair path",
            "",
        ]
    )
    for index, item in enumerate(evidence["minimal_repair_hypothesis"]["bounded_test_sequence"], start=1):
        lines.append(f"{index}. {item}")
    lines.extend(
        [
            "",
            "Thresholds, source/destination mass semantics, event-window semantics, historical scores, registry, and ledger remain unchanged.",
            "",
            "## Evidence inputs",
            "",
        ]
    )
    for item in evidence["input_evidence"]:
        lines.append(f"- `{item['path']}` — `{item['sha256']}`")
    lines.extend(
        [
            "",
            "The detailed machine-readable record is the evidence JSON above; its execution constraints and resource account explicitly record that no long task or active H5 read was started.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_lab_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=default_lab_root)
    parser.add_argument(
        "--output",
        type=Path,
        default=default_lab_root / "campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-20260920.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=default_lab_root / "reports/F4-MACRO-T2-SIDECAR-PREFLIGHT-2026-09-20.md",
    )
    args = parser.parse_args()
    lab_root = args.lab_root.resolve()
    evidence = build_preflight(lab_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(evidence, args.output), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "T2_macro": evidence["T2_macro"],
                "T2_path": evidence["T2_path"],
                "unknown_mass_pass": evidence["gate_evaluation"]["unknown_mass_pass"],
                "event_window_pass": evidence["gate_evaluation"]["event_window_pass"],
                "sidecar_provenance_pass": evidence["gate_evaluation"]["sidecar_provenance_pass"],
                "matrix_complete": evidence["static_cfd_qualification_status"]["matrix_complete"],
                "output": str(args.output),
                "report": str(args.report),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
