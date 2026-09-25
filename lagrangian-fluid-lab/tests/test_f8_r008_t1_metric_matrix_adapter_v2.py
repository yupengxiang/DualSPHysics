from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_bundle
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_t1_metric_matrix_adapter_v2 as matrix_v2


def _case_metrics(case_id: str, row: dict, parameters: dict, *, table_bytes: int, table_sha: str) -> dict:
    half_height = float(parameters["geometry_and_fluid"]["half_height_m"])
    acceleration = float(parameters["parameterization"]["acceleration_amplitude_m_s2"])
    dp = float(row["dp_m"])
    plane_count = round(2.0 * half_height / dp) + 1
    profile_z = [-half_height + index * dp for index in range(plane_count)]
    samples_per_period = int(row["native_output_samples_per_period"])
    sample_count = int(row["observation_cycles"]) * samples_per_period + 1
    output_dt = float(row["period_s"]) / samples_per_period
    selected_times = [float(row["observation_start_s"]) + index * output_dt
                      for index in range(sample_count)]
    u_ref = acceleration / float(row["omega_rad_s"])
    zero_plane = [0.0] * plane_count
    coefficients = {
        "mean_m_s": zero_plane,
        "sine_coefficient_a_m_s": [1.0] * plane_count,
        "cosine_coefficient_b_m_s": zero_plane,
        "amplitude_m_s": [1.0] * plane_count,
        "phase_rad": zero_plane,
    }
    return {
        "schema": "core.cfd.f8.r008_t1_metric_adapter.v2",
        "scope_id": matrix_v2.SCOPE_ID,
        "frozen_scope_receipt_sha256": matrix_v2.metric_v1.FROZEN_INPUT_SHA256["scope"],
        "parameter_contract_sha256": matrix_v2.metric_v1.FROZEN_INPUT_SHA256["parameter_contract"],
        "case_id": case_id,
        "status": "case_metric_gates_evaluated_native_integrity_pending",
        "source_table_schema": table_v2.TABLE_SCHEMA,
        "source_table_bytes": table_bytes,
        "source_table_sha256": table_sha,
        "semantic_source_checks": {
            "B_C_D_chain_required_by_caller": True,
            "full_time_axis_matches": True,
            "fluid_id_projection_matches": True,
            "position_velocity_density_mass_recomputed": True,
            "all_valid": True,
            "density_used_as_metric_input": False,
        },
        "selected_time_s": selected_times,
        "maximum_saved_output_dt_s": output_dt,
        "profile_z_m": profile_z,
        "plane_coefficients": coefficients,
        "center_coefficients": {
            "mean_m_s": 0.0,
            "sine_coefficient_a_m_s": 1.0,
            "cosine_coefficient_b_m_s": 0.0,
            "amplitude_m_s": 1.0,
            "phase_rad": 0.0,
        },
        "metrics": {
            "profile_amplitude_relative_error_max": 0.0,
            "profile_phase_absolute_error_max_rad": 0.0,
            "cycle_mean_fluxes_m3_s_per_m": [0.0, 0.0, 0.0],
            "cycle_mean_flux_ratio": 0.0,
            "transverse_velocity_rms_m_s": 0.0,
            "transverse_velocity_rms_ratio": 0.0,
            "u_ref_m_s": u_ref,
        },
        "metric_gates": {
            "profile_amplitude": True,
            "profile_phase": True,
            "cycle_mean_flux": True,
            "transverse_velocity_rms": True,
        },
        "metric_gates_passed": True,
        "solver_max_dt_s": None,
        "solver_timestep_audit": None,
        "native_integrity_gates_evaluated": False,
        "full_t1_decision": False,
        "qualification_credit": 0,
    }


def _audit(tmp_path: Path, case_id: str, max_dt: float) -> Path:
    source = tmp_path / f"{case_id}.synthetic.log"
    source.write_bytes(f"synthetic source for {case_id}\n".encode())
    audit_path = tmp_path / f"{case_id}.audit.json"
    audit_path.write_text(json.dumps({
        "schema": matrix_v2.SOLVER_TIMESTEP_AUDIT_SCHEMA,
        "status": "passed",
        "case_id": case_id,
        "max_solver_dt_s": max_dt,
        "checks": {"finite_positive_max_step": True},
        "source_log": {
            "path": source.name,
            "bytes": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
    }), encoding="utf-8")
    return audit_path


def _inputs(tmp_path: Path):
    scope, parameters, applicability, *_hashes = matrix_v2._load_frozen_contract()
    results = {}
    for row in scope["matrix"]["rows"]:
        case_id = row["case_id"]
        table_bytes = 4096
        table_sha = hashlib.sha256(case_id.encode()).hexdigest()
        metrics = _case_metrics(case_id, row, parameters,
                                table_bytes=table_bytes, table_sha=table_sha)
        results[case_id] = {
            "schema": metric_bundle.SCHEMA,
            "case_id": case_id,
            "provenance_chain_references_closed": True,
            "definition_control_bindings_match_frozen_pack_and_source_bytes": True,
            "reviewed_metric_code_sources_match": True,
            "native_table_review_authenticity": "caller_supplied_trust_not_authenticated_here",
            "metric_review_authenticity": "caller_supplied_trust_not_authenticated_here",
            "authorization_authenticity": "external_gate_not_checked_here",
            "runtime_environment_assumption": "caller_attested_not_independently_verified",
            "loaded_module_code_identity_verified": False,
            "native_integrity_evaluated": False,
            "metrics_evaluated": True,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
            "native_table_review_receipt_sha256": hashlib.sha256(
                matrix_v2.table_review.OUTPUT.read_bytes()).hexdigest(),
            "metric_review_receipt_sha256": hashlib.sha256(
                matrix_v2.metric_review_v2.OUTPUT.read_bytes()).hexdigest(),
            "stage_statuses": {stage: "passed" for stage in matrix_v2.STAGES},
            "receipt_sha256": {stage: hashlib.sha256(f"receipt:{case_id}:{stage}".encode()).hexdigest()
                               for stage in matrix_v2.STAGES},
            "manifest_sha256": {stage: hashlib.sha256(f"manifest:{case_id}:{stage}".encode()).hexdigest()
                                for stage in matrix_v2.STAGES},
            "native_fluid_table": {
                "schema": table_v2.SCHEMA,
                "table_schema": table_v2.TABLE_SCHEMA,
                "case_id": case_id,
                "full_time_axis_matches": True,
                "fluid_id_projection_matches": True,
                "position_velocity_density_mass_recomputed": True,
                "all_valid": True,
                "raw_frames_recomputed": row["observation_end_output_index"] + 1,
                "time_rows": row["observation_end_output_index"] + 1,
                "fluid_particle_count": 1,
                "native_integrity_evaluated": False,
                "T1_numerical": False,
                "qualification_credit": 0,
                "table_bytes": table_bytes,
                "table_sha256": table_sha,
            },
            "case_metrics": metrics,
            "metric_gates_passed": metrics["metric_gates_passed"],
        }
    time_comparison = applicability["time_step_comparison"]
    baseline_id, refined_id = time_comparison["baseline_case_id"], time_comparison["case_id"]
    audits = {
        baseline_id: _audit(tmp_path, baseline_id, 0.002),
        refined_id: _audit(tmp_path, refined_id, 0.001),
    }
    return results, audits


def test_v2_metric_matrix_evaluates_frozen_15_case_synthetic_matrix(tmp_path) -> None:
    results, audits = _inputs(tmp_path)

    result = matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)

    assert result["case_count"] == 15
    assert len(result["case_result_bindings"]) == 15
    assert len(result["cross_resolution"]) == 8
    assert result["case_metric_gates_passed"] is True
    assert result["cross_resolution_gates_passed"] is True
    assert result["time_step_comparison"]["passed"] is True
    assert result["output_cadence_comparison"]["passed"] is True
    assert result["all_metric_and_comparison_gates_passed"] is True
    assert result["native_integrity_evaluated"] is False
    assert result["full_t1_decision"] is False
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0


def test_synthetic_or_rewrapped_result_rejected_before_metric_parse(tmp_path, monkeypatch) -> None:
    results, audits = _inputs(tmp_path)
    first_id = next(iter(results))
    diagnostic = {
        "schema": "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v8",
        "mode": "synthetic_only",
        "evidence_class": "synthetic_non_qualifying",
        "diagnostic_outcome": "non_qualifying",
        "diagnostic_code": "synthetic_bindings_match",
        "payload_shape_valid": True,
        "scope_binding_matches": True,
        "qualification_row_binding_matches": True,
        "qualification_eligible": False,
        "qualification_authorized": False,
        "execution_authorized": False,
        "qualification_credit": 0,
        "gate_transition": "none",
        "registry_write": False,
        "harness_performed_external_io": False,
    }
    rewrapped = dict(results[first_id])
    rewrapped.update(diagnostic)
    # Test the deceptive wrapper case too: retain the canonical schema while
    # adding unregistered synthetic-diagnostic fields.
    rewrapped["schema"] = matrix_v2.CASE_RESULT_SCHEMA
    payloads = [diagnostic, rewrapped]

    def fail_if_metric_parser_reached(*args, **kwargs):
        raise AssertionError("synthetic input reached metric parsing")

    monkeypatch.setattr(metric_bundle, "_validate_case_metrics", fail_if_metric_parser_reached)
    for payload in payloads:
        supplied = dict(results)
        supplied[first_id] = payload
        with pytest.raises(
            matrix_v2.NativeFluidMetricMatrixError,
            match="per-case v2 result is absent, unclosed, or overstates T1",
        ):
            matrix_v2.evaluate_metric_matrix_v2(supplied, solver_timestep_audits=audits)


def test_v2_metric_matrix_rejects_omitted_case_instead_of_shrinking_denominator(tmp_path) -> None:
    results, audits = _inputs(tmp_path)
    results.pop(next(iter(results)))

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError, match="exactly the frozen 15 case results"):
        matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)


def test_v2_metric_matrix_preserves_failed_case_in_denominator_and_fails_dependents(tmp_path) -> None:
    results, audits = _inputs(tmp_path)
    failed_id = "space-q0p5-dp0p0090"
    failed = results[failed_id]
    failed["case_metrics"]["metrics"]["profile_amplitude_relative_error_max"] = 0.5
    failed["case_metrics"]["metric_gates"]["profile_amplitude"] = False
    failed["case_metrics"]["metric_gates_passed"] = False
    failed["metric_gates_passed"] = False

    result = matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)

    assert result["case_count"] == 15
    assert failed_id in result["failed_case_metric_gate_ids"]
    assert result["case_metric_gates_passed"] is False
    assert result["cross_resolution_gates_passed"] is False
    assert any(item["candidate_case_id"] == failed_id and item["passed"] is False
               for item in result["cross_resolution"])
    assert result["all_metric_and_comparison_gates_passed"] is False


def test_v2_metric_matrix_fails_cross_resolution_threshold_without_dropping_case(tmp_path) -> None:
    results, audits = _inputs(tmp_path)
    candidate_id = "space-q0-dp0p0090"
    results[candidate_id]["case_metrics"]["plane_coefficients"]["sine_coefficient_a_m_s"] = [1.5] * len(
        results[candidate_id]["case_metrics"]["profile_z_m"]
    )

    result = matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)

    assert result["case_count"] == 15
    assert result["case_metric_gates_passed"] is True
    assert result["cross_resolution_gates_passed"] is False
    assert any(item["candidate_case_id"] == candidate_id and item["passed"] is False
               for item in result["cross_resolution"])
    assert result["all_metric_and_comparison_gates_passed"] is False


def test_v2_metric_matrix_rejects_case_timestamp_grid_drift(tmp_path) -> None:
    results, audits = _inputs(tmp_path)
    case_id = "space-q0-dp0p0090"
    results[case_id]["case_metrics"]["selected_time_s"][12] += 1e-4

    with pytest.raises(ValueError, match="exact frozen closed observation window"):
        matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)


@pytest.mark.parametrize("refined_dt", [0.002, 0.003])
def test_v2_metric_matrix_rejects_non_refined_timestep_control(tmp_path, refined_dt) -> None:
    results, audits = _inputs(tmp_path)
    refined_id = "time-q0p5-dp0p0075-cfl0p1"
    audit_path = audits[refined_id]
    receipt = json.loads(audit_path.read_text(encoding="utf-8"))
    receipt["max_solver_dt_s"] = refined_dt
    audit_path.write_text(json.dumps(receipt), encoding="utf-8")

    result = matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)

    assert result["time_step_comparison"]["passed"] is False
    assert result["all_metric_and_comparison_gates_passed"] is False


def test_v2_metric_matrix_rejects_timestep_phase_difference_over_limit(tmp_path) -> None:
    results, audits = _inputs(tmp_path)
    results["time-q0p5-dp0p0075-cfl0p1"]["case_metrics"]["center_coefficients"]["phase_rad"] = 0.06

    result = matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)

    assert result["time_step_comparison"]["wrapped_center_phase_difference_rad"] == pytest.approx(0.06)
    assert result["time_step_comparison"]["passed"] is False
    assert result["all_metric_and_comparison_gates_passed"] is False


@pytest.mark.parametrize("mutation", ["timestamp", "length"])
def test_v2_metric_matrix_cadence_gate_rejects_misaligned_dense_series(tmp_path, monkeypatch, mutation) -> None:
    results, audits = _inputs(tmp_path)
    dense_id = "cadence-q0p5-dp0p0075-output128"
    original_validator = matrix_v2._validate_case_result

    def validate_then_mutate(case_id, row, outer, **kwargs):
        checked = original_validator(case_id, row, outer, **kwargs)
        if case_id == dense_id:
            times = checked["case_metrics"]["selected_time_s"]
            if mutation == "timestamp":
                times[10] += 1e-4
            else:
                times.pop()
        return checked

    monkeypatch.setattr(matrix_v2, "_validate_case_result", validate_then_mutate)
    result = matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)

    assert result["output_cadence_comparison"]["passed"] is False
    assert result["all_metric_and_comparison_gates_passed"] is False


def test_v2_metric_matrix_rejects_cross_resolution_timestamp_disagreement(tmp_path, monkeypatch) -> None:
    results, audits = _inputs(tmp_path)
    candidate_id = "space-q0-dp0p0090"
    original_validator = matrix_v2._validate_case_result

    def validate_then_mutate(case_id, row, outer, **kwargs):
        checked = original_validator(case_id, row, outer, **kwargs)
        if case_id == candidate_id:
            checked["case_metrics"]["selected_time_s"][0] += 1e-4
        return checked

    monkeypatch.setattr(matrix_v2, "_validate_case_result", validate_then_mutate)
    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError, match="do not share the exact time grid"):
        matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)


@pytest.mark.parametrize("mutation", [
    "table_review", "metric_review", "receipt_hashes", "manifest_hashes",
    "native_table_review_authenticity", "metric_review_authenticity",
    "authorization_authenticity", "runtime_environment_assumption",
    "credit", "credit_bool", "credit_float",
    "table_credit_bool", "table_credit_float",
    "metric_credit_bool", "metric_credit_float", "t1",
])
def test_v2_metric_matrix_rejects_conflicting_receipts_or_overstated_result(tmp_path, mutation) -> None:
    results, audits = _inputs(tmp_path)
    first = results[next(iter(results))]
    if mutation == "table_review":
        first["native_table_review_receipt_sha256"] = "0" * 64
    elif mutation == "metric_review":
        first["metric_review_receipt_sha256"] = "0" * 64
    elif mutation == "receipt_hashes":
        first["receipt_sha256"]["C"] = "not-a-hash"
    elif mutation == "manifest_hashes":
        first["manifest_sha256"]["C"] = "not-a-hash"
    elif mutation == "native_table_review_authenticity":
        first["native_table_review_authenticity"] = "verified"
    elif mutation == "metric_review_authenticity":
        first["metric_review_authenticity"] = "verified"
    elif mutation == "authorization_authenticity":
        first["authorization_authenticity"] = "verified"
    elif mutation == "runtime_environment_assumption":
        first["runtime_environment_assumption"] = "verified"
    elif mutation == "credit":
        first["qualification_credit"] = 1
    elif mutation == "credit_bool":
        first["qualification_credit"] = False
    elif mutation == "credit_float":
        first["qualification_credit"] = 0.0
    elif mutation == "table_credit_bool":
        first["native_fluid_table"]["qualification_credit"] = False
    elif mutation == "table_credit_float":
        first["native_fluid_table"]["qualification_credit"] = 0.0
    elif mutation == "metric_credit_bool":
        first["case_metrics"]["qualification_credit"] = False
    elif mutation == "metric_credit_float":
        first["case_metrics"]["qualification_credit"] = 0.0
    else:
        first["T1_numerical"] = True

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError):
        matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)


@pytest.mark.parametrize("source_path", [
    "/etc/passwd", "../outside.log", "nested/source.log", ".", "..",
])
def test_v2_matrix_timestep_audit_rejects_non_sibling_source_path(tmp_path, source_path) -> None:
    _, audits = _inputs(tmp_path)
    case_id = "time-q0p5-dp0p0075-cfl0p1"
    audit_path = audits[case_id]
    receipt = json.loads(audit_path.read_text(encoding="utf-8"))
    receipt["source_log"]["path"] = source_path
    audit_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError,
                       match="single relative filename"):
        matrix_v2._read_bounded_audit(audit_path, case_id)


def test_v2_matrix_audit_requires_explicit_v2_path_contract(tmp_path) -> None:
    _, audits = _inputs(tmp_path)
    case_id = "time-q0p5-dp0p0075-cfl0p1"
    audit_path = audits[case_id]
    receipt = json.loads(audit_path.read_text(encoding="utf-8"))
    receipt["schema"] = "core.cfd.f8.r008_solver_timestep_audit.v1"
    receipt["source_log"]["path"] = str(audit_path.parent / receipt["source_log"]["path"])
    audit_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError,
                       match="audit is absent, failed, or bound to another case"):
        matrix_v2._read_bounded_audit(audit_path, case_id)


@pytest.mark.parametrize("mutation", [
    "max_dt_string", "max_dt_boolean", "check_unknown_key", "check_missing_key", "check_false",
])
def test_v2_matrix_audit_requires_exact_numeric_and_check_contract(tmp_path, mutation) -> None:
    _, audits = _inputs(tmp_path)
    case_id = "time-q0p5-dp0p0075-cfl0p1"
    audit_path = audits[case_id]
    receipt = json.loads(audit_path.read_text(encoding="utf-8"))
    if mutation == "max_dt_string":
        receipt["max_solver_dt_s"] = "0.001"
        error = "must be a JSON number"
    elif mutation == "max_dt_boolean":
        receipt["max_solver_dt_s"] = True
        error = "must be a JSON number"
    elif mutation == "check_unknown_key":
        receipt["checks"]["caller_asserted_complete"] = True
        error = "audit is absent, failed, or bound to another case"
    elif mutation == "check_missing_key":
        receipt["checks"] = {}
        error = "audit is absent, failed, or bound to another case"
    else:
        receipt["checks"]["finite_positive_max_step"] = False
        error = "audit is absent, failed, or bound to another case"
    audit_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError, match=error):
        matrix_v2._read_bounded_audit(audit_path, case_id)


@pytest.mark.parametrize("mutation", ["oversized", "symlink", "fifo", "hardlink"])
def test_v2_matrix_timestep_source_log_is_bounded_single_link_and_nofollow(tmp_path, mutation) -> None:
    _, audits = _inputs(tmp_path)
    case_id = "time-q0p5-dp0p0075-cfl0p1"
    audit_path = audits[case_id]
    receipt = json.loads(audit_path.read_text(encoding="utf-8"))
    source = audit_path.parent / receipt["source_log"]["path"]
    if mutation == "oversized":
        with source.open("r+b") as stream:
            stream.truncate(matrix_v2.MAX_AUDIT_SOURCE_LOG_BYTES + 1)
        receipt["source_log"]["bytes"] = 1024
    elif mutation == "symlink":
        target = source.with_name(source.name + ".target")
        source.rename(target)
        source.symlink_to(target.name)
    elif mutation == "fifo":
        source.unlink()
        os.mkfifo(source)
    else:
        source.with_name(source.name + ".hardlink").hardlink_to(source)
    audit_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError):
        matrix_v2._read_bounded_audit(audit_path, case_id)


def test_v2_matrix_timestep_audit_parent_symlink_is_rejected(tmp_path) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    audit_path = _audit(real_directory, "case-parent-link", 0.001)
    alias = tmp_path / "alias"
    alias.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError,
                       match="parent must be a real, no-follow directory path"):
        matrix_v2._read_bounded_audit(alias / audit_path.name, "case-parent-link")


@pytest.mark.parametrize("mutation", ["oversized", "symlink", "fifo"])
def test_v2_matrix_timestep_audit_reader_is_bounded_and_nofollow(tmp_path, mutation) -> None:
    results, audits = _inputs(tmp_path)
    case_id = "space-q0p5-dp0p0075"
    audit_path = audits[case_id]
    if mutation == "oversized":
        audit_path.write_bytes(b"x" * (matrix_v2.MAX_AUDIT_RECEIPT_BYTES + 1))
    elif mutation == "symlink":
        target = audit_path.with_suffix(".target.json")
        audit_path.rename(target)
        audit_path.symlink_to(target.name)
    else:
        audit_path.unlink()
        os.mkfifo(audit_path)

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError):
        matrix_v2._read_bounded_audit(audit_path, case_id)


@pytest.mark.parametrize("mutation", ["boolean_bytes", "boolean_time_rows"])
def test_v2_metric_matrix_rejects_boolean_integer_bindings(tmp_path, mutation) -> None:
    results, audits = _inputs(tmp_path)
    first_id = next(iter(results))
    table = results[first_id]["native_fluid_table"]
    if mutation == "boolean_bytes":
        table["table_bytes"] = True
        results[first_id]["case_metrics"]["source_table_bytes"] = True
    else:
        table["time_rows"] = True
        table["raw_frames_recomputed"] = True

    with pytest.raises(matrix_v2.NativeFluidMetricMatrixError):
        matrix_v2.evaluate_metric_matrix_v2(results, solver_timestep_audits=audits)
