"""Compose F8 R008 RunPARTs and runtime claims into a non-authorizing diagnostic.

This checker joins the bounded fresh-segment RunPARTs parser, the static CPU
timestep source audit, and the caller-claimed runtime-completion diagnostic.
It never authenticates an attempt, executable, loaded source, effective
configuration, or event source, and it cannot issue completion, timestep, T1,
readiness, or qualification decisions.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Mapping

from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts_v2
from scripts import f8_r008_timestep_source_semantics_v1 as source_semantics_v1


SCHEMA = "core.cfd.f8.r008_runtime_timestep_adjudicator.v1"
CASE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z", re.ASCII)
ALGORITHMS = {"verlet", "symplectic"}


class RuntimeTimestepAdjudicatorError(ValueError):
    """The per-case runtime/timestep diagnostic input is malformed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeTimestepAdjudicatorError(message)


def diagnose_runtime_timestep_case_v1(
    *,
    case_id: str,
    runparts_raw: bytes,
    effective_step_algorithm_claim: str,
    runtime_completion_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Cross-check one RunPARTs log against untrusted runtime claims.

    ``effective_step_algorithm_claim`` and all runtime-completion fields are
    caller claims. The result deliberately distinguishes a value that could
    represent an applied timestep under an unverified Verlet claim from a
    Symplectic ``PartDtMax`` corrector candidate, which is not the timestep
    used for that PART. A valid footer is retained as a structural observation
    only; it never establishes normal completion.
    """
    _require(type(case_id) is str and bool(CASE_ID.fullmatch(case_id)),
             "case_id must be a bounded lowercase identifier")
    _require(type(runparts_raw) is bytes,
             "RunPARTs input must be exact raw bytes")
    _require(type(effective_step_algorithm_claim) is str
             and effective_step_algorithm_claim in ALGORITHMS,
             "effective StepAlgorithm claim must be exactly verlet or symplectic")
    _require(type(runtime_completion_evidence) is dict,
             "runtime completion evidence must be a builtin dict")
    # Capture the flat, exact-field caller input once. All later parsing and
    # cross-checking uses this snapshot rather than rereading a mutable map.
    runtime_evidence = runtime_completion_evidence.copy()

    try:
        parsed = runparts_v2.parse_runparts_csv(runparts_raw)
    except runparts_v2.RunPartsDiagnosticError as error:
        raise RuntimeTimestepAdjudicatorError(
            f"RunPARTs input failed the fresh-segment v2 parser: {error}"
        ) from error

    try:
        completion = source_semantics_v1.diagnose_runtime_completion_evidence(
            runtime_evidence,
        )
        static_audit = source_semantics_v1.build_audit()
    except (source_semantics_v1.TimestepSemanticsError, OSError) as error:
        raise RuntimeTimestepAdjudicatorError(
            f"runtime evidence or current static source audit is invalid: {error}"
        ) from error

    _require(static_audit.get("schema") == source_semantics_v1.SCHEMA
             and static_audit.get("backend_scope", {}).get("audited_backend")
             == "standard_cpu_single_only"
             and static_audit.get("static_findings", {}).get(
                 "cpu_verlet_dtmax_equals_applied_step_when_runtime_integrator_is_verified"
             ) is True
             and static_audit.get("static_findings", {}).get(
                 "cpu_symplectic_recorded_part_dtmax_is_actual_used_dt_max"
             ) is False,
             "current source audit does not match the frozen CPU timestep semantic contract")

    recorded_dtmax = parsed["maximum_recorded_part_dtmax_s"]
    recorded_time = parsed["last_recorded_time_s"]
    final_time = runtime_evidence["final_time_s"]
    tolerance = completion["tolerance_s"]
    _require(type(recorded_dtmax) in (int, float) and math.isfinite(recorded_dtmax)
             and recorded_dtmax > 0.0,
             "RunPARTs parser returned an invalid recorded maximum DtMax")
    _require(type(recorded_time) in (int, float) and math.isfinite(recorded_time)
             and type(final_time) in (int, float) and math.isfinite(final_time)
             and math.isfinite(tolerance),
             "RunPARTs/runtime time claims are not finite numbers")

    violations = list(completion["violations"])
    endpoint_delta = float(recorded_time) - float(final_time)
    unresolved_checks: list[str] = []
    if endpoint_delta > tolerance:
        violations.append("runparts_recorded_time_exceeds_claimed_final_time")
    elif endpoint_delta < -tolerance:
        unresolved_checks.append(
            "runparts_last_record_precedes_claimed_final_time_and_output_coverage_is_unverified"
        )

    algorithm = effective_step_algorithm_claim
    cpu_runtime_claim = (
        runtime_evidence["backend"] == "standard_cpu_single"
        and runtime_evidence["gpu_enabled"] is False
        and runtime_evidence["openmp_enabled"] is False
        and runtime_evidence["vres_enabled"] is False
    )
    if algorithm == "verlet":
        timestep_semantics = (
            "recorded_part_dtmax_matches_applied_step_only_if_unverified_runtime_claim_is_verlet"
        )
        dtmax_interpretable_as_applied_step_untrusted = cpu_runtime_claim
    else:
        timestep_semantics = (
            "recorded_part_dtmax_is_symplectic_corrector_candidate_not_this_parts_applied_step"
        )
        dtmax_interpretable_as_applied_step_untrusted = False

    claims_consistent: bool | None
    if violations:
        claims_consistent = False
    elif unresolved_checks:
        claims_consistent = None
    else:
        claims_consistent = True
    source_hashes = {
        name: {
            "path": evidence["path"],
            "bytes": evidence["bytes"],
            "sha256": evidence["sha256"],
        }
        for name, evidence in static_audit["source_evidence"].items()
    }
    return {
        "schema": SCHEMA,
        "status": "untrusted_per_case_runtime_timestep_diagnostic_only",
        "case_id_claim": case_id,
        "effective_step_algorithm_claim": algorithm,
        "runtime_completion_diagnostic": completion,
        "runparts_observation": {
            "schema": runparts_v2.SCHEMA,
            "input_scope": parsed["input_scope"],
            "bytes": len(runparts_raw),
            "sha256": hashlib.sha256(runparts_raw).hexdigest(),
            "data_row_count": parsed["data_row_count"],
            "last_recorded_time_s": recorded_time,
            "footer_present": parsed["footer_present"],
            "maximum_recorded_part_dtmax_s": recorded_dtmax,
            "all_26_fields_type_and_range_checked": parsed[
                "all_26_fields_type_and_range_checked"
            ],
            "cross_field_native_semantics_verified": False,
        },
        "source_semantics": {
            "schema": static_audit["schema"],
            "source_authenticated": False,
            "runtime_binary_identity_verified": False,
            "effective_integrator_verified": False,
            "audited_backend": static_audit["backend_scope"]["audited_backend"],
            "source_files": source_hashes,
            "implementation": static_audit["implementation"],
            "test": static_audit["test"],
        },
        "recorded_dtmax_semantics": timestep_semantics,
        "dtmax_interpretable_as_applied_step_untrusted": (
            dtmax_interpretable_as_applied_step_untrusted
        ),
        "effective_step_algorithm_verified": False,
        "runtime_configuration_verified": False,
        "runparts_attempt_identity_verified": False,
        "runparts_footer_proves_normal_completion": False,
        "normal_completion_verified": False,
        "runparts_completion_evidence_sufficient": False,
        "runparts_runtime_claims_consistent_untrusted": claims_consistent,
        "violations": violations,
        "unresolved_checks": unresolved_checks,
        "solver_timestep_adjudicated": False,
        "native_integrity_adjudicated": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


__all__ = ["RuntimeTimestepAdjudicatorError", "SCHEMA", "diagnose_runtime_timestep_case_v1"]
