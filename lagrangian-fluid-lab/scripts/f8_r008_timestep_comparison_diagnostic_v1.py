"""Untrusted frozen F8 R008 timestep-refinement pair diagnostic.

This downstream layer consumes raw per-case RunPARTs bytes and caller claims,
then delegates each case to the existing runtime/timestep adjudicator. It
compares recorded DtMax values only when both case diagnostics meet the narrow
CPU-single Verlet and endpoint conditions. Nothing here authenticates an
attempt or produces a solver, completion, T1, readiness, or qualification
decision.
"""
from __future__ import annotations

import math
from typing import Any

from scripts import f8_r008_runtime_timestep_adjudicator_v1 as case_adjudicator
from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix_v2


SCHEMA = "core.cfd.f8.r008_timestep_comparison_diagnostic.v1"
BASELINE_CASE_ID = "space-q0p5-dp0p0075"
REFINED_CASE_ID = "time-q0p5-dp0p0075-cfl0p1"
FROZEN_PHASE_LIMIT_RAD = 0.05
CASE_INPUT_FIELDS = frozenset({
    "case_id", "runparts_raw", "effective_step_algorithm_claim",
    "runtime_completion_evidence",
})
CASE_DIAGNOSTIC_FIELDS = frozenset({
    "schema", "status", "case_id_claim", "effective_step_algorithm_claim",
    "runtime_completion_diagnostic", "runparts_observation", "source_semantics",
    "recorded_dtmax_semantics", "dtmax_interpretable_as_applied_step_untrusted",
    "effective_step_algorithm_verified", "runtime_configuration_verified",
    "runparts_attempt_identity_verified", "runparts_footer_proves_normal_completion",
    "normal_completion_verified", "runparts_completion_evidence_sufficient",
    "runparts_runtime_claims_consistent_untrusted", "violations", "unresolved_checks",
    "solver_timestep_adjudicated", "native_integrity_adjudicated", "T1_numerical",
    "readiness_pass", "qualification_credit",
})
COMPLETION_DIAGNOSTIC_FIELDS = frozenset({
    "schema", "state", "conditions_satisfied_untrusted", "tolerance_s", "violations",
    "evidence_authenticated", "solver_timestep_adjudicated",
    "normal_completion_verified", "trusted_acceptance_verdict_issued",
})
RUNPARTS_OBSERVATION_FIELDS = frozenset({
    "schema", "input_scope", "bytes", "sha256", "data_row_count",
    "last_recorded_time_s", "footer_present", "maximum_recorded_part_dtmax_s",
    "all_26_fields_type_and_range_checked", "cross_field_native_semantics_verified",
})
SOURCE_SEMANTICS_FIELDS = frozenset({
    "schema", "source_authenticated", "runtime_binary_identity_verified",
    "effective_integrator_verified", "audited_backend", "source_files",
    "implementation", "test",
})
COMPARISON_FIELDS = frozenset({
    "baseline_case_id", "both_cases_must_pass_per_case_gates", "case_id",
    "phase_difference_absolute_max_rad",
    "refined_max_dt_must_be_strictly_less_than_baseline",
})
OUTPUT_FIELDS = frozenset({
    "schema", "status", "frozen_pair_contract", "case_diagnostics",
    "untrusted_pair_observations", "unresolved_checks", "qualification_boundaries",
})
PAIR_OBSERVATION_FIELDS = frozenset({
    "completion_conditions_match", "runparts_endpoint_relations",
    "cpu_single_verlet_dtmax_candidates", "dtmax_relation_evaluated",
    "refined_recorded_dtmax_strictly_less_than_baseline",
    "wrapped_phase_difference_rad", "phase_difference_within_frozen_limit",
    "diagnostic_code",
})


class TimestepComparisonDiagnosticError(ValueError):
    """The frozen pair contract or pair diagnostic input is malformed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TimestepComparisonDiagnosticError(message)


def _load_frozen_pair_contract() -> tuple[str, str, float]:
    try:
        loaded = matrix_v2._load_frozen_contract()
    except Exception as error:
        raise TimestepComparisonDiagnosticError(
            f"matrix_v2 frozen contract could not be loaded: {error}"
        ) from error
    _require(type(loaded) is tuple and len(loaded) == 7,
             "matrix_v2 frozen contract has an unexpected return shape")
    scope = loaded[0]
    _require(type(scope) is dict and type(scope.get("matrix")) is dict,
             "matrix_v2 frozen scope is malformed")
    applicability = scope["matrix"].get("gate_applicability")
    _require(type(applicability) is dict
             and type(applicability.get("time_step_comparison")) is dict,
             "frozen time_step_comparison is absent or malformed")
    comparison = applicability["time_step_comparison"]
    _require(set(comparison) == COMPARISON_FIELDS,
             "frozen time_step_comparison fields do not match the expected contract")

    baseline_id = comparison["baseline_case_id"]
    refined_id = comparison["case_id"]
    phase_limit = comparison["phase_difference_absolute_max_rad"]
    _require(type(baseline_id) is str and baseline_id == BASELINE_CASE_ID
             and type(refined_id) is str and refined_id == REFINED_CASE_ID,
             "frozen timestep pair case IDs differ from the R008 contract")
    _require(type(comparison["both_cases_must_pass_per_case_gates"]) is bool
             and comparison["both_cases_must_pass_per_case_gates"] is True
             and type(comparison["refined_max_dt_must_be_strictly_less_than_baseline"]) is bool
             and comparison["refined_max_dt_must_be_strictly_less_than_baseline"] is True,
             "frozen timestep pair relation requirements are malformed")
    _require(type(phase_limit) in (int, float)
             and math.isfinite(phase_limit)
             and phase_limit == FROZEN_PHASE_LIMIT_RAD,
             "frozen phase-difference limit is not the expected finite 0.05 rad")
    return baseline_id, refined_id, float(phase_limit)


def _snapshot_case(case: Any, expected_case_id: str, label: str) -> dict[str, Any]:
    _require(type(case) is dict and set(case) == CASE_INPUT_FIELDS,
             f"{label} case input fields do not match the exact raw-evidence schema")
    _require(type(case["case_id"]) is str and case["case_id"] == expected_case_id,
             f"{label} case_id does not match its frozen pair role")
    _require(type(case["runparts_raw"]) is bytes,
             f"{label} RunPARTs evidence must be original raw bytes")
    _require(type(case["effective_step_algorithm_claim"]) is str
             and case["effective_step_algorithm_claim"] in {"verlet", "symplectic"},
             f"{label} StepAlgorithm claim must be exactly verlet or symplectic")
    _require(type(case["runtime_completion_evidence"]) is dict,
             f"{label} runtime completion evidence must be a builtin dict")
    result = {
        "case_id": case["case_id"],
        "runparts_raw": case["runparts_raw"],
        "effective_step_algorithm_claim": case["effective_step_algorithm_claim"],
        "runtime_completion_evidence": case["runtime_completion_evidence"].copy(),
    }
    return result


def _diagnose_case(case: dict[str, Any], label: str) -> dict[str, Any]:
    try:
        diagnostic = case_adjudicator.diagnose_runtime_timestep_case_v1(
            case_id=case["case_id"],
            runparts_raw=case["runparts_raw"],
            effective_step_algorithm_claim=case["effective_step_algorithm_claim"],
            runtime_completion_evidence=case["runtime_completion_evidence"],
        )
    except case_adjudicator.RuntimeTimestepAdjudicatorError as error:
        raise TimestepComparisonDiagnosticError(
            f"{label} per-case runtime/timestep diagnostic failed: {error}"
        ) from error
    _require(type(diagnostic) is dict
             and set(diagnostic) == CASE_DIAGNOSTIC_FIELDS
             and diagnostic.get("schema") == case_adjudicator.SCHEMA
             and diagnostic.get("status")
             == "untrusted_per_case_runtime_timestep_diagnostic_only"
             and diagnostic.get("case_id_claim") == case["case_id"]
             and diagnostic.get("effective_step_algorithm_claim")
             == case["effective_step_algorithm_claim"]
             and type(diagnostic.get("runtime_completion_diagnostic")) is dict
             and set(diagnostic["runtime_completion_diagnostic"])
             == COMPLETION_DIAGNOSTIC_FIELDS
             and type(diagnostic["runtime_completion_diagnostic"].get(
                 "conditions_satisfied_untrusted")) is bool
             and type(diagnostic.get("runparts_runtime_claims_consistent_untrusted"))
             in (bool, type(None))
             and type(diagnostic.get("runparts_observation")) is dict
             and set(diagnostic["runparts_observation"]) == RUNPARTS_OBSERVATION_FIELDS
             and type(diagnostic["runparts_observation"].get(
                 "maximum_recorded_part_dtmax_s")) in (int, float)
             and math.isfinite(diagnostic["runparts_observation"][
                 "maximum_recorded_part_dtmax_s"])
             and diagnostic["runparts_observation"][
                 "maximum_recorded_part_dtmax_s"] > 0.0
             and type(diagnostic.get("dtmax_interpretable_as_applied_step_untrusted")) is bool,
             f"{label} per-case diagnostic no longer matches the expected v1 contract")
    expected_step_semantics = {
        "verlet": "recorded_part_dtmax_matches_applied_step_only_if_unverified_runtime_claim_is_verlet",
        "symplectic": "recorded_part_dtmax_is_symplectic_corrector_candidate_not_this_parts_applied_step",
    }[case["effective_step_algorithm_claim"]]
    _require(type(diagnostic.get("source_semantics")) is dict
             and set(diagnostic["source_semantics"]) == SOURCE_SEMANTICS_FIELDS
             and diagnostic["source_semantics"].get("audited_backend")
             == "standard_cpu_single_only"
             and diagnostic["source_semantics"].get("source_authenticated") is False
             and diagnostic["source_semantics"].get("runtime_binary_identity_verified") is False
             and diagnostic["source_semantics"].get("effective_integrator_verified") is False
             and diagnostic.get("recorded_dtmax_semantics") == expected_step_semantics
             and diagnostic.get("effective_step_algorithm_verified") is False
             and diagnostic.get("runtime_configuration_verified") is False
             and diagnostic.get("runparts_attempt_identity_verified") is False
             and diagnostic.get("runparts_footer_proves_normal_completion") is False
             and diagnostic.get("normal_completion_verified") is False
             and diagnostic.get("runparts_completion_evidence_sufficient") is False
             and diagnostic.get("solver_timestep_adjudicated") is False
             and diagnostic.get("native_integrity_adjudicated") is False
             and diagnostic.get("T1_numerical") is False
             and diagnostic.get("readiness_pass") is False
             and type(diagnostic.get("qualification_credit")) is int
             and diagnostic["qualification_credit"] == 0,
             f"{label} per-case diagnostic contains unexpected semantic or qualification fields")
    return diagnostic


def diagnose_frozen_timestep_comparison_pair_v1(
    *,
    baseline_case: dict[str, Any],
    refined_case: dict[str, Any],
    wrapped_phase_difference_rad: int | float,
) -> dict[str, Any]:
    """Diagnose the frozen baseline/refined pair without granting qualification.

    ``wrapped_phase_difference_rad`` is an untrusted scalar observation supplied
    by the caller. Pairwise DtMax comparison is deliberately left unresolved
    unless each delegated per-case diagnostic reports untrusted completion
    conditions, an endpoint relation of exactly ``True``, and CPU-single
    Verlet semantics with DtMax marked only as an untrusted applied-step
    candidate.
    """
    baseline_id, refined_id, phase_limit = _load_frozen_pair_contract()
    baseline_input = _snapshot_case(baseline_case, baseline_id, "baseline")
    refined_input = _snapshot_case(refined_case, refined_id, "refined")
    _require(type(wrapped_phase_difference_rad) in (int, float)
             and math.isfinite(wrapped_phase_difference_rad)
             and 0.0 <= wrapped_phase_difference_rad <= math.pi,
             "wrapped phase difference must be a finite builtin number in [0, pi]")
    phase_difference = float(wrapped_phase_difference_rad)

    baseline = _diagnose_case(baseline_input, "baseline")
    refined = _diagnose_case(refined_input, "refined")

    completion_conditions = {
        "baseline": baseline["runtime_completion_diagnostic"][
            "conditions_satisfied_untrusted"
        ],
        "refined": refined["runtime_completion_diagnostic"][
            "conditions_satisfied_untrusted"
        ],
    }
    endpoint_relations = {
        "baseline": baseline["runparts_runtime_claims_consistent_untrusted"],
        "refined": refined["runparts_runtime_claims_consistent_untrusted"],
    }
    cpu_single_verlet_candidates = {
        "baseline": (
            baseline["effective_step_algorithm_claim"] == "verlet"
            and baseline_input["runtime_completion_evidence"]["backend"]
            == "standard_cpu_single"
            and baseline_input["runtime_completion_evidence"]["gpu_enabled"] is False
            and baseline_input["runtime_completion_evidence"]["openmp_enabled"] is False
            and baseline_input["runtime_completion_evidence"]["vres_enabled"] is False
            and baseline["source_semantics"]["audited_backend"]
            == "standard_cpu_single_only"
            and baseline["dtmax_interpretable_as_applied_step_untrusted"] is True
        ),
        "refined": (
            refined["effective_step_algorithm_claim"] == "verlet"
            and refined_input["runtime_completion_evidence"]["backend"]
            == "standard_cpu_single"
            and refined_input["runtime_completion_evidence"]["gpu_enabled"] is False
            and refined_input["runtime_completion_evidence"]["openmp_enabled"] is False
            and refined_input["runtime_completion_evidence"]["vres_enabled"] is False
            and refined["source_semantics"]["audited_backend"]
            == "standard_cpu_single_only"
            and refined["dtmax_interpretable_as_applied_step_untrusted"] is True
        ),
    }

    comparison_eligible = (
        all(value is True for value in completion_conditions.values())
        and all(value is True for value in endpoint_relations.values())
        and all(value is True for value in cpu_single_verlet_candidates.values())
    )
    refined_dt_is_less: bool | None = None
    if comparison_eligible:
        baseline_dt = baseline["runparts_observation"][
            "maximum_recorded_part_dtmax_s"
        ]
        refined_dt = refined["runparts_observation"][
            "maximum_recorded_part_dtmax_s"
        ]
        refined_dt_is_less = refined_dt < baseline_dt

    if any(value is None for value in endpoint_relations.values()):
        pair_code = "unresolved_runparts_endpoint_relation"
    elif not all(value is True for value in completion_conditions.values()):
        pair_code = "not_evaluable_completion_conditions_not_matching"
    elif not all(value is True for value in endpoint_relations.values()):
        pair_code = "not_evaluable_runparts_endpoint_relation_not_true"
    elif not all(value is True for value in cpu_single_verlet_candidates.values()):
        pair_code = "not_evaluable_not_cpu_single_verlet_candidate_pair"
    elif refined_dt_is_less is not True:
        pair_code = "unverified_refinement_relation_not_observed"
    elif phase_difference > phase_limit:
        pair_code = "unverified_phase_difference_exceeds_frozen_limit"
    else:
        pair_code = "unverified_refinement_and_phase_observations_match_frozen_pair"

    unresolved_checks: list[str] = []
    for label, relation in endpoint_relations.items():
        if relation is None:
            unresolved_checks.append(f"{label}_runparts_endpoint_relation_unresolved")
    if not comparison_eligible and not unresolved_checks:
        unresolved_checks.append("pairwise_dtmax_relation_not_evaluated")

    result = {
        "schema": SCHEMA,
        "status": "untrusted_frozen_timestep_pair_diagnostic_only",
        "frozen_pair_contract": {
            "baseline_case_id": baseline_id,
            "refined_case_id": refined_id,
            "phase_difference_absolute_max_rad": phase_limit,
            "strict_refinement_required": True,
        },
        "case_diagnostics": {"baseline": baseline, "refined": refined},
        "untrusted_pair_observations": {
            "completion_conditions_match": completion_conditions,
            "runparts_endpoint_relations": endpoint_relations,
            "cpu_single_verlet_dtmax_candidates": cpu_single_verlet_candidates,
            "dtmax_relation_evaluated": comparison_eligible,
            "refined_recorded_dtmax_strictly_less_than_baseline": refined_dt_is_less,
            "wrapped_phase_difference_rad": phase_difference,
            "phase_difference_within_frozen_limit": phase_difference <= phase_limit,
            "diagnostic_code": pair_code,
        },
        "unresolved_checks": unresolved_checks,
        "qualification_boundaries": {
            "input_evidence_authenticated": False,
            "execution_attempt_identity_verified": False,
            "runtime_configuration_verified": False,
            "effective_step_algorithm_verified": False,
            "native_integrity_adjudicated": False,
            "normal_completion_verified": False,
            "solver_timestep_adjudicated": False,
            "T1_numerical": False,
            "readiness_pass": False,
            "qualification_credit": 0,
        },
    }
    _require(set(result) == OUTPUT_FIELDS
             and set(result["untrusted_pair_observations"]) == PAIR_OBSERVATION_FIELDS,
             "internal pair diagnostic output fields drifted from the v1 schema")
    return result


__all__ = [
    "SCHEMA",
    "TimestepComparisonDiagnosticError",
    "diagnose_frozen_timestep_comparison_pair_v1",
]
