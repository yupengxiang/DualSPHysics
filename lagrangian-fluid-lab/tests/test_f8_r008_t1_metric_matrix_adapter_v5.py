from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from scripts import f8_r008_runparts_timestep_diagnostic_v2 as runparts_v2
from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix_v2
from scripts import f8_r008_t1_metric_matrix_adapter_v4 as matrix_v4
from scripts import f8_r008_t1_metric_matrix_adapter_v5 as matrix_v5
from scripts import f8_r008_runtime_timestep_adjudicator_v1 as case_adjudicator
from scripts import f8_r008_timestep_comparison_diagnostic_v1 as pair_v1
from scripts import f8_r008_timestep_source_semantics_v1 as source_semantics_v1


_fixture_path = Path(__file__).with_name("test_f8_r008_t1_metric_matrix_adapter_v2.py")
_fixture_spec = importlib.util.spec_from_file_location("_r008_matrix_v2_test_fixtures", _fixture_path)
assert _fixture_spec is not None and _fixture_spec.loader is not None
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)


@pytest.fixture(autouse=True)
def _reuse_immutable_static_audit_within_test(monkeypatch):
    """Keep these synthetic composition tests focused and avoid 17 duplicate scans."""
    original = source_semantics_v1.build_audit
    cached: list[dict] = []

    def build_once():
        if not cached:
            cached.append(original())
        return cached[0]

    monkeypatch.setattr(source_semantics_v1, "build_audit", build_once)


def _runparts_bytes(final_time: float, dtmax: float) -> bytes:
    initial = ["0"] * len(runparts_v2.RUNPARTS_HEADER)
    initial[0], initial[1], initial[2] = "0", "0", "0"
    initial[19], initial[20] = "0", "0"
    observed = ["0"] * len(runparts_v2.RUNPARTS_HEADER)
    observed[0] = "1"
    observed[1] = repr(final_time)
    observed[2] = "10"
    observed[19] = repr(dtmax / 2.0)
    observed[20] = repr(dtmax)
    return "\n".join((
        ";".join(runparts_v2.RUNPARTS_HEADER),
        ";".join(initial),
        ";".join(observed),
        "",
        *runparts_v2.RUNPARTS_FOOTER,
        "",
    )).encode("utf-8")


def _runtime_evidence(end_time: float, **updates) -> dict:
    evidence = {
        "backend": "standard_cpu_single",
        "frozen_time_max_s": end_time,
        "effective_time_max_s": end_time,
        "final_time_s": end_time,
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


def _prepared(tmp_path: Path) -> dict:
    # Reuse the repository's established fully synthetic v2 matrix fixture.
    results, audit_paths = _fixture_module._inputs(tmp_path)
    frozen_scope = matrix_v2._load_frozen_contract()[0]
    rows = frozen_scope["matrix"]["rows"]
    case_ids = [row["case_id"] for row in rows]
    rows_by_id = {row["case_id"]: row for row in rows}
    raw_by_case: dict[str, bytes] = {}
    algorithms = {case_id: "verlet" for case_id in case_ids}
    runtime = {
        case_id: _runtime_evidence(float(rows_by_id[case_id]["observation_end_s"]))
        for case_id in case_ids
    }
    pair_ids = (pair_v1.BASELINE_CASE_ID, pair_v1.REFINED_CASE_ID)
    sources = {
        case_id: audit_paths[case_id].parent / "RunPARTs.csv"
        for case_id in pair_ids
    }
    for case_id in case_ids:
        dtmax = 0.002 if case_id == pair_v1.BASELINE_CASE_ID else 0.001
        raw = _runparts_bytes(float(rows_by_id[case_id]["observation_end_s"]), dtmax)
        raw_by_case[case_id] = raw
        if case_id in sources:
            sources[case_id].write_bytes(raw)
    return {
        "case_results": results,
        "solver_timestep_sources": sources,
        "runparts_raw_by_case": raw_by_case,
        "effective_step_algorithm_claims": algorithms,
        "runtime_completion_evidence": runtime,
        "rows_by_id": rows_by_id,
    }


def _evaluate(inputs: dict) -> dict:
    return matrix_v5.evaluate_metric_matrix_v5(
        inputs["case_results"],
        solver_timestep_sources=inputs["solver_timestep_sources"],
        runparts_raw_by_case=inputs["runparts_raw_by_case"],
        effective_step_algorithm_claims=inputs["effective_step_algorithm_claims"],
        runtime_completion_evidence=inputs["runtime_completion_evidence"],
    )


def _all_keys(value):
    if type(value) is dict:
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif type(value) is list:
        for child in value:
            yield from _all_keys(child)


def _replace_raw(inputs: dict, case_id: str, raw: bytes) -> None:
    inputs["runparts_raw_by_case"][case_id] = raw
    if case_id in inputs["solver_timestep_sources"]:
        inputs["solver_timestep_sources"][case_id].write_bytes(raw)


def test_v5_calls_matrix_v4_and_emits_only_non_authorizing_projection(tmp_path, monkeypatch):
    inputs = _prepared(tmp_path)
    original = matrix_v4.evaluate_metric_matrix_v4
    calls = []

    def tracked(case_results, *, solver_timestep_sources):
        calls.append((case_results, solver_timestep_sources))
        return original(case_results, solver_timestep_sources=solver_timestep_sources)

    monkeypatch.setattr(matrix_v4, "evaluate_metric_matrix_v4", tracked)
    result = _evaluate(inputs)

    assert len(calls) == 1
    assert calls[0][0] is not inputs["case_results"]  # v5 supplies a bounded snapshot.
    assert result["schema"] == matrix_v5.SCHEMA
    assert result["case_count"] == 15
    assert len(result["case_ids"]) == 15
    assert result["case_failure_denominator_fixed"] is True
    matrix_projection = result["matrix_v4_observations"]
    assert matrix_projection["schema"] == matrix_v4.SCHEMA
    assert matrix_projection["case_count"] == 15
    assert set(matrix_projection["case_result_bindings"]) == set(result["case_ids"])
    assert matrix_projection["runparts_binding_case_ids"] == [
        pair_v1.BASELINE_CASE_ID, pair_v1.REFINED_CASE_ID,
    ]
    assert matrix_projection["pair_runparts_observations"][
        pair_v1.BASELINE_CASE_ID
    ]["sha256"] == hashlib.sha256(
        inputs["runparts_raw_by_case"][pair_v1.BASELINE_CASE_ID]
    ).hexdigest()
    assert matrix_projection["wrapped_center_phase_difference_rad_from_matrix_v4"] == 0.0
    assert set(result["case_diagnostics"]) == set(result["case_ids"])
    pair = result["frozen_pair_diagnostic"]
    assert pair["untrusted_pair_observations"]["dtmax_relation_evaluated"] is True
    assert pair["untrusted_pair_observations"][
        "refined_recorded_dtmax_strictly_less_than_baseline"
    ] is True
    assert set(result["runtime_horizon_claim_alignment_untrusted"]) == set(result["case_ids"])
    assert all("caller_claim_consistency_only_not_authenticated_completion" == entry["semantics"]
               for entry in result["runtime_horizon_claim_alignment_untrusted"].values())
    assert result["qualification_boundaries"] == {
        "input_evidence_authenticated": False,
        "execution_source_identity_verified": False,
        "runtime_configuration_verified": False,
        "effective_step_algorithm_verified": False,
        "native_integrity_evaluated": False,
        "native_integrity_adjudicated": False,
        "normal_completion_verified": False,
        "solver_completion_verified": False,
        "solver_timestep_adjudicated": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }
    assert "passed" not in set(_all_keys(result))


@pytest.mark.parametrize("drift", ["nested_passed", "unexpected_status"])
def test_v5_rejects_matrix_v4_nested_or_status_semantic_drift(
    tmp_path, monkeypatch, drift,
):
    inputs = _prepared(tmp_path)
    original = matrix_v4.evaluate_metric_matrix_v4

    def drift_v4(case_results, *, solver_timestep_sources):
        result = original(case_results, solver_timestep_sources=solver_timestep_sources)
        if drift == "nested_passed":
            case_id = next(iter(result["case_result_bindings"]))
            result["case_result_bindings"][case_id]["passed"] = True
        else:
            result["status"] = "qualified"
        return result

    monkeypatch.setattr(matrix_v4, "evaluate_metric_matrix_v4", drift_v4)
    with pytest.raises(matrix_v5.MetricMatrixV5Error):
        _evaluate(inputs)


@pytest.mark.parametrize("mapping_name", [
    "case_results", "runparts_raw_by_case", "effective_step_algorithm_claims",
    "runtime_completion_evidence",
])
@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_v5_rejects_missing_or_extra_case_rows_before_matrix_call(
    tmp_path, monkeypatch, mapping_name, mutation,
):
    inputs = _prepared(tmp_path)
    mapping = inputs[mapping_name]
    case_id = next(iter(mapping))
    if mutation == "missing":
        mapping.pop(case_id)
    else:
        mapping["unexpected-case"] = next(iter(mapping.values()))

    def should_not_call(*args, **kwargs):
        raise AssertionError("invalid cardinality reached matrix-v4 evaluation")

    monkeypatch.setattr(matrix_v4, "evaluate_metric_matrix_v4", should_not_call)
    with pytest.raises(matrix_v5.MetricMatrixV5Error, match="exactly the frozen 15 case IDs"):
        _evaluate(inputs)


def test_v5_rejects_serialized_caller_diagnostic_and_has_no_v4_result_input(tmp_path):
    inputs = _prepared(tmp_path)
    case_id = inputs["case_ids"][0] if "case_ids" in inputs else next(
        iter(inputs["runparts_raw_by_case"])
    )
    inputs["runparts_raw_by_case"][case_id] = {
        "schema": "core.cfd.f8.r008_runtime_timestep_adjudicator.v1",
        "status": "diagnostic_only",
    }
    with pytest.raises(matrix_v5.MetricMatrixV5Error, match="exact original bytes"):
        _evaluate(inputs)

    second_tmp_path = tmp_path / "second"
    second_tmp_path.mkdir()
    inputs = _prepared(second_tmp_path)
    with pytest.raises(TypeError):
        matrix_v5.evaluate_metric_matrix_v5(
            inputs["case_results"],
            solver_timestep_sources=inputs["solver_timestep_sources"],
            runparts_raw_by_case=inputs["runparts_raw_by_case"],
            effective_step_algorithm_claims=inputs["effective_step_algorithm_claims"],
            runtime_completion_evidence=inputs["runtime_completion_evidence"],
            matrix_v4_result={"schema": matrix_v4.SCHEMA},
        )


@pytest.mark.parametrize("case_id", [pair_v1.BASELINE_CASE_ID, pair_v1.REFINED_CASE_ID])
def test_v5_rejects_raw_bytes_that_do_not_match_matrix_v4_path(tmp_path, case_id):
    inputs = _prepared(tmp_path)
    inputs["runparts_raw_by_case"][case_id] += b"\n"
    role = "baseline" if case_id == pair_v1.BASELINE_CASE_ID else "refined"
    with pytest.raises(
        matrix_v5.MetricMatrixV5Error,
        match=f"do not match matrix-v4 {role} source path",
    ):
        _evaluate(inputs)


def test_v5_rejects_runtime_horizon_claims_shorter_than_frozen_row(tmp_path):
    inputs = _prepared(tmp_path)
    case_id = pair_v1.BASELINE_CASE_ID
    frozen_end = float(inputs["rows_by_id"][case_id]["observation_end_s"])
    shorter = frozen_end - 0.1
    inputs["runtime_completion_evidence"][case_id].update({
        "frozen_time_max_s": shorter,
        "effective_time_max_s": shorter,
        "final_time_s": shorter,
    })
    with pytest.raises(matrix_v5.MetricMatrixV5Error, match="do not match frozen observation_end_s"):
        _evaluate(inputs)


@pytest.mark.parametrize("drift", [
    "source_authenticated", "runtime_completion_verified", "extra_completion_field",
    "runparts_schema", "runparts_input_scope", "runparts_26_field_check",
])
def test_v5_rejects_upstream_nested_diagnostic_drift_on_non_pair_case(
    tmp_path, monkeypatch, drift,
):
    inputs = _prepared(tmp_path)
    non_pair_case = next(
        case_id for case_id in inputs["runparts_raw_by_case"]
        if case_id not in {pair_v1.BASELINE_CASE_ID, pair_v1.REFINED_CASE_ID}
    )
    original = case_adjudicator.diagnose_runtime_timestep_case_v1

    def drift_one_non_pair_case(**kwargs):
        diagnostic = original(**kwargs)
        if kwargs["case_id"] == non_pair_case:
            if drift == "source_authenticated":
                diagnostic["source_semantics"]["source_authenticated"] = True
            elif drift == "runtime_completion_verified":
                diagnostic["runtime_completion_diagnostic"][
                    "normal_completion_verified"
                ] = True
            elif drift == "extra_completion_field":
                diagnostic["runtime_completion_diagnostic"][
                    "unexpected_future_signal"
                ] = True
            elif drift == "runparts_schema":
                diagnostic["runparts_observation"]["schema"] = "unexpected.v1"
            elif drift == "runparts_input_scope":
                diagnostic["runparts_observation"]["input_scope"] = "restart_or_append"
            else:
                diagnostic["runparts_observation"][
                    "all_26_fields_type_and_range_checked"
                ] = False
        return diagnostic

    monkeypatch.setattr(
        case_adjudicator, "diagnose_runtime_timestep_case_v1", drift_one_non_pair_case,
    )
    with pytest.raises(matrix_v5.MetricMatrixV5Error, match="drifted"):
        _evaluate(inputs)


def test_v5_rejects_upstream_tolerance_drift_against_original_runtime_claims(
    tmp_path, monkeypatch,
):
    inputs = _prepared(tmp_path)
    case_id = next(
        case for case in inputs["runparts_raw_by_case"]
        if case not in {pair_v1.BASELINE_CASE_ID, pair_v1.REFINED_CASE_ID}
    )
    end = float(inputs["rows_by_id"][case_id]["observation_end_s"])
    inputs["runtime_completion_evidence"][case_id]["final_time_s"] = end + 0.1
    original = case_adjudicator.diagnose_runtime_timestep_case_v1

    def widen_tolerance(**kwargs):
        diagnostic = original(**kwargs)
        if kwargs["case_id"] == case_id:
            diagnostic["runtime_completion_diagnostic"]["tolerance_s"] *= 100.0
        return diagnostic

    monkeypatch.setattr(case_adjudicator, "diagnose_runtime_timestep_case_v1", widen_tolerance)
    with pytest.raises(matrix_v5.MetricMatrixV5Error,
                       match="does not match the original runtime claims"):
        _evaluate(inputs)


def test_v5_endpoint_none_remains_unresolved_after_row_horizon_alignment(tmp_path):
    inputs = _prepared(tmp_path)
    baseline_id = pair_v1.BASELINE_CASE_ID
    end = float(inputs["rows_by_id"][baseline_id]["observation_end_s"])
    tolerance = 0.001 + 0.001 * abs(end)
    raw = _runparts_bytes(end - 2.0 * tolerance, 0.002)
    _replace_raw(inputs, baseline_id, raw)

    result = _evaluate(inputs)
    observations = result["frozen_pair_diagnostic"]["untrusted_pair_observations"]
    assert observations["runparts_endpoint_relations"]["baseline"] is None
    assert observations["dtmax_relation_evaluated"] is False
    assert "baseline_runparts_endpoint_relation_unresolved" in result[
        "frozen_pair_diagnostic"
    ]["unresolved_checks"]
    assert result["runtime_horizon_claim_alignment_untrusted"][baseline_id][
        "final_time_matches_frozen_row_within_claimed_tolerance_untrusted"
    ] is True


def test_v5_symplectic_claim_prevents_pair_dtmax_comparison(tmp_path):
    inputs = _prepared(tmp_path)
    inputs["effective_step_algorithm_claims"][pair_v1.REFINED_CASE_ID] = "symplectic"
    result = _evaluate(inputs)
    observations = result["frozen_pair_diagnostic"]["untrusted_pair_observations"]
    assert observations["cpu_single_verlet_dtmax_candidates"] == {
        "baseline": True, "refined": False,
    }
    assert observations["dtmax_relation_evaluated"] is False
    assert observations["refined_recorded_dtmax_strictly_less_than_baseline"] is None


def test_v5_early_stop_claim_prevents_pair_dtmax_comparison(tmp_path):
    inputs = _prepared(tmp_path)
    inputs["runtime_completion_evidence"][pair_v1.REFINED_CASE_ID][
        "nstepsbreak_observed"
    ] = True
    result = _evaluate(inputs)
    observations = result["frozen_pair_diagnostic"]["untrusted_pair_observations"]
    assert observations["completion_conditions_match"] == {
        "baseline": True, "refined": False,
    }
    assert observations["dtmax_relation_evaluated"] is False
    assert result["qualification_boundaries"]["normal_completion_verified"] is False


def test_v5_refined_dtmax_relation_is_strict(tmp_path):
    inputs = _prepared(tmp_path)
    refined_id = pair_v1.REFINED_CASE_ID
    end = float(inputs["rows_by_id"][refined_id]["observation_end_s"])
    _replace_raw(inputs, refined_id, _runparts_bytes(end, 0.002))
    result = _evaluate(inputs)
    observations = result["frozen_pair_diagnostic"]["untrusted_pair_observations"]
    assert observations["dtmax_relation_evaluated"] is True
    assert observations["refined_recorded_dtmax_strictly_less_than_baseline"] is False
    assert observations["diagnostic_code"] == "unverified_refinement_relation_not_observed"


def test_v5_exact_frozen_phase_boundary_is_accepted_and_stays_untrusted(tmp_path):
    inputs = _prepared(tmp_path)
    inputs["case_results"][pair_v1.REFINED_CASE_ID]["case_metrics"][
        "center_coefficients"
    ]["phase_rad"] = 0.05
    result = _evaluate(inputs)
    observations = result["frozen_pair_diagnostic"]["untrusted_pair_observations"]
    assert observations["wrapped_phase_difference_rad"] == pytest.approx(0.05, abs=1e-15)
    assert observations["phase_difference_within_frozen_limit"] is True
    assert result["matrix_v4_observations"][
        "wrapped_center_phase_difference_rad_from_matrix_v4"
    ] == observations["wrapped_phase_difference_rad"]
    assert all(value is False for key, value in result["qualification_boundaries"].items()
               if key != "qualification_credit")
    assert result["qualification_boundaries"]["qualification_credit"] == 0
    assert "passed" not in set(_all_keys(result))
