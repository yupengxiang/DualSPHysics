from __future__ import annotations

import math

import numpy as np
import pytest

from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts_v2
from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix_v2
from scripts import f8_r008_timestep_comparison_diagnostic_v1 as pair_v1


def _row(part: int, time_s: str, steps: int, dtmin: str, dtmax: str) -> str:
    cells = ["0"] * len(runparts_v2.RUNPARTS_HEADER)
    cells[0] = str(part)
    cells[1] = time_s
    cells[2] = str(steps)
    cells[19] = dtmin
    cells[20] = dtmax
    return ";".join(cells)


def _runparts(*, final_time: str = "10.0", dtmax: str = "0.002") -> bytes:
    return ("\n".join((
        ";".join(runparts_v2.RUNPARTS_HEADER),
        _row(0, "0", 0, "0", "0"),
        _row(1, final_time, 10, "0.001", dtmax),
        "",
        *runparts_v2.RUNPARTS_FOOTER,
        "",
    ))).encode("utf-8")


def _completion(**updates) -> dict:
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


def _case(case_id: str, *, dtmax: str = "0.002", algorithm: str = "verlet",
          final_time: str = "10.0", **completion_updates) -> dict:
    return {
        "case_id": case_id,
        "runparts_raw": _runparts(final_time=final_time, dtmax=dtmax),
        "effective_step_algorithm_claim": algorithm,
        "runtime_completion_evidence": _completion(**completion_updates),
    }


def _pair(*, baseline_dt: str = "0.002", refined_dt: str = "0.001",
          baseline_algorithm: str = "verlet", refined_algorithm: str = "verlet",
          baseline_time: str = "10.0", refined_time: str = "10.0",
          phase_difference: float = 0.02, baseline_completion_updates: dict | None = None,
          refined_completion_updates: dict | None = None) -> dict:
    baseline = _case(
        pair_v1.BASELINE_CASE_ID, dtmax=baseline_dt,
        algorithm=baseline_algorithm, final_time=baseline_time,
        **(baseline_completion_updates or {}),
    )
    refined = _case(
        pair_v1.REFINED_CASE_ID, dtmax=refined_dt,
        algorithm=refined_algorithm, final_time=refined_time,
        **(refined_completion_updates or {}),
    )
    return pair_v1.diagnose_frozen_timestep_comparison_pair_v1(
        baseline_case=baseline,
        refined_case=refined,
        wrapped_phase_difference_rad=phase_difference,
    )


def _all_keys(value):
    if type(value) is dict:
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif type(value) is list:
        for child in value:
            yield from _all_keys(child)


def test_best_matching_pair_remains_unverified_diagnostic_and_loads_frozen_contract(monkeypatch):
    original = matrix_v2._load_frozen_contract
    calls = []

    def tracked_loader():
        calls.append(True)
        return original()

    monkeypatch.setattr(matrix_v2, "_load_frozen_contract", tracked_loader)
    result = _pair()

    pair = result["untrusted_pair_observations"]
    assert calls == [True]
    assert result["schema"] == pair_v1.SCHEMA
    assert result["status"] == "untrusted_frozen_timestep_pair_diagnostic_only"
    assert result["frozen_pair_contract"] == {
        "baseline_case_id": "space-q0p5-dp0p0075",
        "refined_case_id": "time-q0p5-dp0p0075-cfl0p1",
        "phase_difference_absolute_max_rad": 0.05,
        "strict_refinement_required": True,
    }
    assert pair["completion_conditions_match"] == {"baseline": True, "refined": True}
    assert pair["runparts_endpoint_relations"] == {"baseline": True, "refined": True}
    assert pair["cpu_single_verlet_dtmax_candidates"] == {"baseline": True, "refined": True}
    assert pair["dtmax_relation_evaluated"] is True
    assert pair["refined_recorded_dtmax_strictly_less_than_baseline"] is True
    assert pair["phase_difference_within_frozen_limit"] is True
    assert pair["diagnostic_code"] == (
        "unverified_refinement_and_phase_observations_match_frozen_pair"
    )
    assert result["qualification_boundaries"] == {
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
    }
    assert "passed" not in set(_all_keys(result))


def test_symplectic_case_prevents_pair_dtmax_comparison():
    result = _pair(refined_algorithm="symplectic")

    observations = result["untrusted_pair_observations"]
    assert observations["completion_conditions_match"] == {"baseline": True, "refined": True}
    assert observations["runparts_endpoint_relations"] == {"baseline": True, "refined": True}
    assert observations["cpu_single_verlet_dtmax_candidates"] == {
        "baseline": True, "refined": False,
    }
    assert observations["dtmax_relation_evaluated"] is False
    assert observations["refined_recorded_dtmax_strictly_less_than_baseline"] is None
    assert observations["diagnostic_code"] == "not_evaluable_not_cpu_single_verlet_candidate_pair"


def test_early_stop_completion_claim_prevents_pair_dtmax_comparison():
    result = _pair(refined_completion_updates={"nstepsbreak_observed": True})

    observations = result["untrusted_pair_observations"]
    assert observations["completion_conditions_match"] == {"baseline": True, "refined": False}
    assert observations["dtmax_relation_evaluated"] is False
    assert observations["refined_recorded_dtmax_strictly_less_than_baseline"] is None
    assert observations["diagnostic_code"] == "not_evaluable_completion_conditions_not_matching"
    assert result["qualification_boundaries"]["normal_completion_verified"] is False


def test_refined_dtmax_must_be_strictly_less_than_baseline():
    result = _pair(baseline_dt="0.001", refined_dt="0.001")

    observations = result["untrusted_pair_observations"]
    assert observations["dtmax_relation_evaluated"] is True
    assert observations["refined_recorded_dtmax_strictly_less_than_baseline"] is False
    assert observations["diagnostic_code"] == "unverified_refinement_relation_not_observed"


def test_phase_difference_uses_frozen_limit_and_reports_excess():
    result = _pair(phase_difference=0.050001)

    observations = result["untrusted_pair_observations"]
    assert observations["phase_difference_within_frozen_limit"] is False
    assert observations["diagnostic_code"] == (
        "unverified_phase_difference_exceeds_frozen_limit"
    )
    assert result["frozen_pair_contract"]["phase_difference_absolute_max_rad"] == 0.05


def test_early_runparts_endpoint_remains_unresolved_and_dt_relation_is_not_computed():
    result = _pair(refined_time="9.9")

    observations = result["untrusted_pair_observations"]
    assert observations["completion_conditions_match"] == {"baseline": True, "refined": True}
    assert observations["runparts_endpoint_relations"] == {"baseline": True, "refined": None}
    assert observations["dtmax_relation_evaluated"] is False
    assert observations["refined_recorded_dtmax_strictly_less_than_baseline"] is None
    assert observations["diagnostic_code"] == "unresolved_runparts_endpoint_relation"
    assert "refined_runparts_endpoint_relation_unresolved" in result["unresolved_checks"]


@pytest.mark.parametrize("role,bad_id", [
    ("baseline", "wrong-baseline"),
    ("refined", "wrong-refined"),
])
def test_case_id_must_match_frozen_pair_role(role, bad_id):
    baseline = _case(pair_v1.BASELINE_CASE_ID)
    refined = _case(pair_v1.REFINED_CASE_ID)
    (baseline if role == "baseline" else refined)["case_id"] = bad_id

    with pytest.raises(pair_v1.TimestepComparisonDiagnosticError, match="frozen pair role"):
        pair_v1.diagnose_frozen_timestep_comparison_pair_v1(
            baseline_case=baseline,
            refined_case=refined,
            wrapped_phase_difference_rad=0.01,
        )


def test_serialized_diagnostic_is_rejected_instead_of_raw_runparts_bytes():
    baseline = _case(pair_v1.BASELINE_CASE_ID)
    refined = _case(pair_v1.REFINED_CASE_ID)
    baseline["runparts_raw"] = {"schema": "pretend.per.case.diagnostic"}

    with pytest.raises(pair_v1.TimestepComparisonDiagnosticError, match="raw bytes"):
        pair_v1.diagnose_frozen_timestep_comparison_pair_v1(
            baseline_case=baseline,
            refined_case=refined,
            wrapped_phase_difference_rad=0.01,
        )


def test_extra_or_missing_case_fields_fail_closed():
    baseline = _case(pair_v1.BASELINE_CASE_ID)
    refined = _case(pair_v1.REFINED_CASE_ID)
    baseline["serialized_diagnostic"] = {"passed": True}

    with pytest.raises(pair_v1.TimestepComparisonDiagnosticError, match="exact raw-evidence"):
        pair_v1.diagnose_frozen_timestep_comparison_pair_v1(
            baseline_case=baseline,
            refined_case=refined,
            wrapped_phase_difference_rad=0.01,
        )


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -0.001, math.pi + 0.001])
def test_phase_difference_requires_exact_finite_wrapped_builtin_number(value):
    baseline = _case(pair_v1.BASELINE_CASE_ID)
    refined = _case(pair_v1.REFINED_CASE_ID)

    with pytest.raises(pair_v1.TimestepComparisonDiagnosticError, match="wrapped phase difference"):
        pair_v1.diagnose_frozen_timestep_comparison_pair_v1(
            baseline_case=baseline,
            refined_case=refined,
            wrapped_phase_difference_rad=value,
        )


def test_numpy_scalar_is_not_accepted_as_exact_numeric_input():
    baseline = _case(pair_v1.BASELINE_CASE_ID)
    refined = _case(pair_v1.REFINED_CASE_ID)

    with pytest.raises(pair_v1.TimestepComparisonDiagnosticError, match="wrapped phase difference"):
        pair_v1.diagnose_frozen_timestep_comparison_pair_v1(
            baseline_case=baseline,
            refined_case=refined,
            wrapped_phase_difference_rad=np.float64(0.01),
        )


def test_non_cpu_single_runtime_claim_prevents_dtmax_comparison():
    result = _pair(refined_completion_updates={"openmp_enabled": True})

    observations = result["untrusted_pair_observations"]
    assert observations["completion_conditions_match"]["refined"] is False
    assert observations["cpu_single_verlet_dtmax_candidates"]["refined"] is False
    assert observations["dtmax_relation_evaluated"] is False
    assert observations["refined_recorded_dtmax_strictly_less_than_baseline"] is None


def test_frozen_contract_schema_drift_fails_closed(monkeypatch):
    scope, *rest = matrix_v2._load_frozen_contract()
    changed_scope = {
        **scope,
        "matrix": {
            **scope["matrix"],
            "gate_applicability": {
                **scope["matrix"]["gate_applicability"],
                "time_step_comparison": {
                    **scope["matrix"]["gate_applicability"]["time_step_comparison"],
                    "unexpected": 1,
                },
            },
        },
    }
    monkeypatch.setattr(matrix_v2, "_load_frozen_contract", lambda: (changed_scope, *rest))

    with pytest.raises(pair_v1.TimestepComparisonDiagnosticError, match="fields do not match"):
        _pair()


def test_completion_evidence_shape_errors_are_wrapped_and_fail_closed():
    baseline = _case(pair_v1.BASELINE_CASE_ID)
    refined = _case(pair_v1.REFINED_CASE_ID)
    refined["runtime_completion_evidence"]["extra"] = False

    with pytest.raises(pair_v1.TimestepComparisonDiagnosticError,
                       match="per-case runtime/timestep diagnostic failed"):
        pair_v1.diagnose_frozen_timestep_comparison_pair_v1(
            baseline_case=baseline,
            refined_case=refined,
            wrapped_phase_difference_rad=0.01,
        )
