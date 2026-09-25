"""Evaluate the F8 R008 matrix with fresh-segment RunPARTs diagnostics only."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts
from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix_v2


SCHEMA = "core.cfd.f8.r008_t1_metric_matrix_adapter.v4"


def _read_runparts_diagnostic(path: Path | str, case_id: str) -> tuple[float, dict[str, Any]]:
    receipt = runparts.build_diagnostic_receipt(path, case_id)
    return receipt["maximum_recorded_part_dtmax_s"], receipt


def evaluate_metric_matrix_v4(
    case_results: Mapping[str, Mapping[str, Any]],
    *,
    solver_timestep_sources: Mapping[str, Path | str],
) -> dict[str, Any]:
    """Evaluate all frozen rows with a source parser scoped to fresh R008 runs."""
    try:
        result = matrix_v2._evaluate_metric_matrix(
            case_results,
            solver_timestep_audits=solver_timestep_sources,
            audit_reader=_read_runparts_diagnostic,
        )
    except runparts.RunPartsDiagnosticError as error:
        raise matrix_v2.NativeFluidMetricMatrixError(
            f"RunPARTs source is not a valid fresh-segment diagnostic input: {error}"
        ) from error

    comparison = result["time_step_comparison"]
    comparison["baseline_observed_recorded_part_dtmax_s"] = comparison.pop(
        "baseline_claimed_solver_max_dt_s"
    )
    comparison["refined_observed_recorded_part_dtmax_s"] = comparison.pop(
        "refined_claimed_solver_max_dt_s"
    )
    comparison["baseline_runparts_parse_diagnostic"] = comparison.pop(
        "baseline_solver_timestep_audit"
    )
    comparison["refined_runparts_parse_diagnostic"] = comparison.pop(
        "refined_solver_timestep_audit"
    )
    comparison["adjudication_status"] = "diagnostic_only_fresh_segment_identity_and_completion_unverified"
    relation_code = comparison.pop("caller_claimed_relation_code")
    comparison["unverified_source_observation_relation_code"] = (
        "unverified_observed_refinement_and_phase_relation"
        if relation_code == "unverified_refinement_and_phase_relation_claimed"
        else "unverified_observed_relation_not_met"
    )
    comparison["runparts_source_content_recomputed"] = True
    comparison["input_scope"] = runparts.INPUT_SCOPE
    comparison["all_26_fields_type_and_range_checked"] = True
    comparison["cross_field_native_semantics_verified"] = False
    comparison["execution_attempt_identity_verified"] = False
    comparison["runtime_configuration_verified"] = False
    comparison["normal_completion_verified"] = False
    comparison["frozen_end_time_reached"] = False
    comparison["passed"] = False

    result["schema"] = SCHEMA
    result["status"] = "fresh_segment_matrix_diagnostics_evaluated_execution_provenance_pending"
    result["execution_source_identity_verified"] = False
    result["solver_completion_verified"] = False
    result["readiness_pass"] = False
    result["full_t1_decision"] = False
    result["qualification_credit"] = 0
    return result


__all__ = ["SCHEMA", "evaluate_metric_matrix_v4"]
