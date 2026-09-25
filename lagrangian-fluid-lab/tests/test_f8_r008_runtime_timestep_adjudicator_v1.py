from __future__ import annotations

import pytest

from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts
from scripts import f8_r008_runtime_timestep_adjudicator_v1 as adjudicator
from scripts import f8_r008_timestep_source_semantics_v1 as source_semantics


def _row(part: int, time_s: str, steps: int, dtmin: str, dtmax: str) -> str:
    cells = ["0"] * len(runparts.RUNPARTS_HEADER)
    cells[0] = str(part)
    cells[1] = time_s
    cells[2] = str(steps)
    cells[19] = dtmin
    cells[20] = dtmax
    return ";".join(cells)


def _runparts(*, final_recorded_time: str = "9.9", dtmax: str = "0.002") -> bytes:
    return ("\n".join((
        ";".join(runparts.RUNPARTS_HEADER),
        _row(0, "0", 0, "0", "0"),
        _row(1, final_recorded_time, 10, "0.001", dtmax),
        "",
        *runparts.RUNPARTS_FOOTER,
        "",
    ))).encode("utf-8")


def _completion(**updates):
    evidence = {
        "backend": "standard_cpu_single",
        "frozen_time_max_s": 10.0,
        "effective_time_max_s": 10.0,
        "final_time_s": 10.0,
        "absolute_tolerance_s": 0.001,
        "relative_tolerance": 0.001,
        "tolerance_preregistration_claim": True,
        "tolerance_receipt_sha256": "a" * 64,
        "process_exit_code": 0,
        "nstepsbreak_observed": False,
        "minimum_fluid_stop_observed": False,
        "terminate_file_observed": False,
        "terminate_applied": False,
        "terminate_warning_observed": False,
        "unregistered_control_override_observed": False,
        "gpu_enabled": False,
        "openmp_enabled": False,
        "vres_enabled": False,
    }
    evidence.update(updates)
    return evidence


def test_verlet_case_composes_runparts_source_and_completion_without_authorizing():
    result = adjudicator.diagnose_runtime_timestep_case_v1(
        case_id="time-q0p5-dp0p0075-cfl0p1",
        runparts_raw=_runparts(final_recorded_time="10.0"),
        effective_step_algorithm_claim="verlet",
        runtime_completion_evidence=_completion(),
    )

    assert result["schema"] == adjudicator.SCHEMA
    assert result["status"] == "untrusted_per_case_runtime_timestep_diagnostic_only"
    assert result["runparts_observation"]["footer_present"] is True
    assert result["runparts_observation"]["maximum_recorded_part_dtmax_s"] == pytest.approx(0.002)
    assert result["dtmax_interpretable_as_applied_step_untrusted"] is True
    assert result["runparts_runtime_claims_consistent_untrusted"] is True
    assert result["effective_step_algorithm_verified"] is False
    assert result["runparts_footer_proves_normal_completion"] is False
    assert result["normal_completion_verified"] is False
    assert result["solver_timestep_adjudicated"] is False
    assert result["native_integrity_adjudicated"] is False
    assert result["T1_numerical"] is False
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0
    assert "passed" not in result
    assert result["source_semantics"]["source_authenticated"] is False


def test_symplectic_part_dtmax_is_never_reported_as_applied_step():
    result = adjudicator.diagnose_runtime_timestep_case_v1(
        case_id="time-q0p5-dp0p0075-cfl0p1",
        runparts_raw=_runparts(final_recorded_time="10.0"),
        effective_step_algorithm_claim="symplectic",
        runtime_completion_evidence=_completion(),
    )

    assert result["dtmax_interpretable_as_applied_step_untrusted"] is False
    assert "corrector_candidate_not_this_parts_applied_step" in result["recorded_dtmax_semantics"]
    assert result["runparts_runtime_claims_consistent_untrusted"] is True
    assert result["solver_timestep_adjudicated"] is False


@pytest.mark.parametrize("field,value", [
    ("nstepsbreak_observed", True),
    ("minimum_fluid_stop_observed", True),
    ("terminate_file_observed", True),
    ("terminate_applied", True),
    ("terminate_warning_observed", True),
    ("unregistered_control_override_observed", True),
    ("process_exit_code", 1),
])
def test_early_stop_or_runtime_control_claim_mismatch_is_diagnostic_failure(field, value):
    result = adjudicator.diagnose_runtime_timestep_case_v1(
        case_id="time-q0p5-dp0p0075-cfl0p1",
        runparts_raw=_runparts(),
        effective_step_algorithm_claim="verlet",
        runtime_completion_evidence=_completion(**{field: value}),
    )

    assert result["runtime_completion_diagnostic"]["conditions_satisfied_untrusted"] is False
    assert result["runparts_runtime_claims_consistent_untrusted"] is False
    assert result["normal_completion_verified"] is False
    assert result["qualification_credit"] == 0


def test_late_runparts_timestamp_conflicts_with_claimed_process_final_time():
    result = adjudicator.diagnose_runtime_timestep_case_v1(
        case_id="time-q0p5-dp0p0075-cfl0p1",
        runparts_raw=_runparts(final_recorded_time="10.1"),
        effective_step_algorithm_claim="verlet",
        runtime_completion_evidence=_completion(final_time_s=10.0),
    )

    assert result["runparts_runtime_claims_consistent_untrusted"] is False
    assert "runparts_recorded_time_exceeds_claimed_final_time" in result["violations"]


def test_early_last_runparts_record_is_unresolved_without_output_coverage_evidence():
    result = adjudicator.diagnose_runtime_timestep_case_v1(
        case_id="time-q0p5-dp0p0075-cfl0p1",
        runparts_raw=_runparts(final_recorded_time="9.9"),
        effective_step_algorithm_claim="verlet",
        runtime_completion_evidence=_completion(final_time_s=10.0),
    )

    assert result["runparts_runtime_claims_consistent_untrusted"] is None
    assert result["runparts_completion_evidence_sufficient"] is False
    assert result["normal_completion_verified"] is False
    assert any("output_coverage_is_unverified" in item
               for item in result["unresolved_checks"])


def test_runparts_footer_does_not_override_early_final_time_claim():
    result = adjudicator.diagnose_runtime_timestep_case_v1(
        case_id="time-q0p5-dp0p0075-cfl0p1",
        runparts_raw=_runparts(),
        effective_step_algorithm_claim="verlet",
        runtime_completion_evidence=_completion(final_time_s=9.0),
    )

    assert result["runparts_observation"]["footer_present"] is True
    assert result["runtime_completion_diagnostic"]["conditions_satisfied_untrusted"] is False
    assert result["normal_completion_verified"] is False
    assert result["solver_timestep_adjudicated"] is False


def test_missing_footer_is_rejected_even_when_completion_claims_look_valid():
    raw = _runparts().split(b"\n# TimeStep")[0] + b"\n"
    with pytest.raises(adjudicator.RuntimeTimestepAdjudicatorError, match="fresh-segment v2 parser"):
        adjudicator.diagnose_runtime_timestep_case_v1(
            case_id="time-q0p5-dp0p0075-cfl0p1",
            runparts_raw=raw,
            effective_step_algorithm_claim="verlet",
            runtime_completion_evidence=_completion(),
        )


def test_unknown_algorithm_claim_fails_closed():
    with pytest.raises(adjudicator.RuntimeTimestepAdjudicatorError, match="StepAlgorithm claim"):
        adjudicator.diagnose_runtime_timestep_case_v1(
            case_id="time-q0p5-dp0p0075-cfl0p1",
            runparts_raw=_runparts(),
            effective_step_algorithm_claim="automatic",
            runtime_completion_evidence=_completion(),
        )


def test_runtime_evidence_is_copied_before_diagnostics(monkeypatch):
    evidence = _completion()
    diagnose = source_semantics.diagnose_runtime_completion_evidence

    def diagnose_then_mutate(snapshot):
        result = diagnose(snapshot)
        evidence["backend"] = "gpu"
        evidence["final_time_s"] = 1.0
        return result

    monkeypatch.setattr(source_semantics, "diagnose_runtime_completion_evidence",
                        diagnose_then_mutate)
    result = adjudicator.diagnose_runtime_timestep_case_v1(
        case_id="time-q0p5-dp0p0075-cfl0p1",
        runparts_raw=_runparts(final_recorded_time="10.0"),
        effective_step_algorithm_claim="verlet",
        runtime_completion_evidence=evidence,
    )

    assert result["runtime_completion_diagnostic"]["conditions_satisfied_untrusted"] is True
    assert result["runparts_runtime_claims_consistent_untrusted"] is True
    assert result["dtmax_interpretable_as_applied_step_untrusted"] is True


def test_static_source_read_error_is_wrapped_as_adjudicator_error(monkeypatch):
    def fail_audit():
        raise OSError("synthetic source read error")

    monkeypatch.setattr(source_semantics, "build_audit", fail_audit)
    with pytest.raises(adjudicator.RuntimeTimestepAdjudicatorError,
                       match="current static source audit is invalid"):
        adjudicator.diagnose_runtime_timestep_case_v1(
            case_id="time-q0p5-dp0p0075-cfl0p1",
            runparts_raw=_runparts(final_recorded_time="10.0"),
            effective_step_algorithm_claim="verlet",
            runtime_completion_evidence=_completion(),
        )
