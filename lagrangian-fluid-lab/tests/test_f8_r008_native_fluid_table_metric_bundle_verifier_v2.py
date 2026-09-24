from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as integration_v1
from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as integration_v2
from scripts import f8_r008_t1_metric_adapter_v2 as metric_adapter
from scripts import f8_r008_native_fluid_table_bundle_verifier_v1 as table_bundle_v1
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle

from tests import test_f8_r008_native_fluid_table_bundle_verifier_v1 as table_fixtures
from tests import test_f8_r008_per_case_bundle_verifier_v1 as bundle_fixtures


def _metric_review_bytes() -> bytes:
    evidence = []
    for path in integration_v2.METRIC_CODE_PATHS.values():
        payload = (integration_v2.LAB / path).read_bytes()
        evidence.append({
            "path": path,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    receipt = {
        "schema": integration_v2.METRIC_REVIEW_SCHEMA,
        "record_id": integration_v2.METRIC_REVIEW_RECORD_ID,
        "status": "static_metric_implementation_review_passed_no_execution_or_t1_credit",
        "reviewer": {
            "model": "gpt-5.6-terra", "reasoning_effort": "high",
            "agent_id": "01234567-89ab-4cde-8fab-0123456789ab",
            "verdict": "PASS", "review_mode": "read_only_static_implementation_review",
            "execution_or_evidence_mutation": False,
        },
        "reviewed_scope": {
            "consumer_schema": table_v2.TABLE_SCHEMA,
            "B_C_D_chain_closed_on_held_table_fd": True,
            "v2_case_metric_gates": True,
            "15_case_matrix_adjudication": False,
            "native_integrity_or_T1_adjudication": False,
        },
        "review_boundary": {
            "production_bundle_read": False, "solver_or_worker_invoked": False,
            "gpu_or_queue_invoked": False, "registry_or_ledger_mutated": False,
            "native_integrity_evaluated": False, "T1_numerical": False,
            "qualification_credit": 0,
        },
        "execution_authority": {
            "solver": False, "worker": False, "gpu": False, "queue": False,
            "T1_numerical": False, "qualification_credit": 0,
        },
        "findings": [{"topic": "test fixture", "verdict": "PASS"}], "evidence": evidence,
    }
    return json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _inputs(roots, auth_bytes, auth):
    inputs = table_fixtures._verification_inputs(roots, auth_bytes, auth)
    metric_review = _metric_review_bytes()
    inputs.update({
        "trusted_metric_review_receipt_bytes": metric_review,
        "trusted_metric_review_receipt_sha256": hashlib.sha256(metric_review).hexdigest(),
    })
    return inputs


def _synthetic_bundle(tmp_path: Path):
    roots, auth_bytes, auth, _frames = bundle_fixtures._build_chain(tmp_path)
    table_fixtures._freeze_b_source_bindings(roots)
    table_fixtures._materialize_synthetic_v2_table(roots)
    return roots, auth_bytes, auth


def _valid_metric_result(case_id: str, table_verification: dict) -> dict:
    row, parameters = metric_adapter._frozen_inputs(case_id)
    half_height = float(parameters["geometry_and_fluid"]["half_height_m"])
    dp = float(row["dp_m"])
    planes = round(2.0 * half_height / dp) + 1
    profile_z = (-half_height + np.arange(planes) * dp).tolist()
    sample_count = int(row["observation_cycles"]) * int(row["native_output_samples_per_period"]) + 1
    selected_times = np.linspace(
        float(row["observation_start_s"]), float(row["observation_end_s"]), sample_count,
    ).tolist()
    coefficient_fields = (
        "mean_m_s", "sine_coefficient_a_m_s", "cosine_coefficient_b_m_s",
        "amplitude_m_s", "phase_rad",
    )
    zero_coefficients = {field: [0.0] * planes for field in coefficient_fields}
    center_coefficients = {field: 0.0 for field in coefficient_fields}
    u_ref = float(parameters["parameterization"]["acceleration_amplitude_m_s2"]) / float(row["omega_rad_s"])
    return {
        "schema": metric_adapter.SCHEMA,
        "scope_id": metric_adapter.SCOPE_ID,
        "frozen_scope_receipt_sha256": metric_adapter.metric_v1.FROZEN_INPUT_SHA256["scope"],
        "parameter_contract_sha256": metric_adapter.metric_v1.FROZEN_INPUT_SHA256["parameter_contract"],
        "case_id": case_id,
        "status": "case_metric_gates_evaluated_native_integrity_pending",
        "source_table_schema": table_v2.TABLE_SCHEMA,
        "source_table_bytes": table_verification["table_bytes"],
        "source_table_sha256": table_verification["table_sha256"],
        "semantic_source_checks": {
            "B_C_D_chain_required_by_caller": True,
            "full_time_axis_matches": True,
            "fluid_id_projection_matches": True,
            "position_velocity_density_mass_recomputed": True,
            "all_valid": True,
            "density_used_as_metric_input": False,
        },
        "selected_time_s": selected_times,
        "maximum_saved_output_dt_s": float(row["period_s"]) / int(row["native_output_samples_per_period"]),
        "profile_z_m": profile_z,
        "plane_coefficients": zero_coefficients,
        "center_coefficients": center_coefficients,
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
            "profile_amplitude": True, "profile_phase": True,
            "cycle_mean_flux": True, "transverse_velocity_rms": True,
        },
        "metric_gates_passed": True,
        "solver_max_dt_s": None,
        "solver_timestep_audit": None,
        "native_integrity_gates_evaluated": False,
        "full_t1_decision": False,
        "qualification_credit": 0,
    }


def test_v2_metric_bundle_keeps_d_table_fd_held_through_case_evaluation(tmp_path, monkeypatch) -> None:
    roots, auth_bytes, auth = _synthetic_bundle(tmp_path)
    called = {}

    def fake_metric_evaluation(fd, *, table_verification, expected_table_bytes, expected_table_sha256):
        named_table = roots["D"] / "outputs/native-fluid-frame-table-v2.h5"
        held = os.fstat(fd)
        named = named_table.stat()
        assert (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)
        assert table_verification["case_id"] == bundle_fixtures.CASE_ID
        assert table_verification["table_bytes"] == expected_table_bytes
        assert table_verification["table_sha256"] == expected_table_sha256
        called["fd"] = fd
        return _valid_metric_result(bundle_fixtures.CASE_ID, table_verification)

    monkeypatch.setattr(metric_adapter, "evaluate_case_metrics_fd", fake_metric_evaluation)
    result = integration_v2.verify_native_fluid_table_chain_and_metrics(
        **_inputs(roots, auth_bytes, auth),
    )

    assert called
    assert result["case_metrics"]["schema"] == metric_adapter.SCHEMA
    assert result["provenance_chain_references_closed"] is True
    assert result["native_fluid_table"]["raw_frames_recomputed"] == 321
    assert result["metrics_evaluated"] is True
    assert result["metric_gates_passed"] is True
    assert result["loaded_module_code_identity_verified"] is False
    assert result["native_integrity_evaluated"] is False
    assert result["readiness_pass"] is False
    assert result["T1_numerical"] is False
    assert result["qualification_credit"] == 0


def test_v2_metric_bundle_rejects_table_mutation_during_metric_consumer(tmp_path, monkeypatch) -> None:
    roots, auth_bytes, auth = _synthetic_bundle(tmp_path)

    def mutate_metric_consumer(fd, *, table_verification, **_kwargs):
        path = roots["D"] / "outputs/native-fluid-frame-table-v2.h5"
        writer = os.open(path, os.O_WRONLY)
        try:
            os.pwrite(writer, b"X", 128)
        finally:
            os.close(writer)
        return _valid_metric_result(bundle_fixtures.CASE_ID, table_verification)

    monkeypatch.setattr(metric_adapter, "evaluate_case_metrics_fd", mutate_metric_consumer)
    with pytest.raises(ValueError):
        integration_v2.verify_native_fluid_table_chain_and_metrics(
            **_inputs(roots, auth_bytes, auth),
        )


@pytest.mark.parametrize("mutation", ["replace", "symlink", "hardlink"])
def test_v2_metric_bundle_rejects_post_chain_d_table_path_rebinding(tmp_path, monkeypatch, mutation) -> None:
    roots, auth_bytes, auth = _synthetic_bundle(tmp_path)
    original_verifier = bundle.verify_provenance_chain

    def verify_then_rebind_path(*args, **kwargs):
        result = original_verifier(*args, **kwargs)
        path = roots["D"] / "outputs/native-fluid-frame-table-v2.h5"
        backup = path.with_name("native-fluid-frame-table-v2-held.h5")
        payload = path.read_bytes()
        path.rename(backup)
        if mutation == "replace":
            path.write_bytes(payload)
        elif mutation == "symlink":
            path.symlink_to(backup.name)
        else:
            os.link(backup, path)
        return result

    monkeypatch.setattr(bundle, "verify_provenance_chain", verify_then_rebind_path)
    monkeypatch.setattr(
        metric_adapter, "evaluate_case_metrics_fd",
        lambda _fd, *, table_verification, **_kwargs: _valid_metric_result(
            bundle_fixtures.CASE_ID, table_verification,
        ),
    )
    with pytest.raises((ValueError, OSError)):
        integration_v2.verify_native_fluid_table_chain_and_metrics(
            **_inputs(roots, auth_bytes, auth),
        )


def test_v2_metric_bundle_rejects_incomplete_adapter_result(tmp_path, monkeypatch) -> None:
    roots, auth_bytes, auth = _synthetic_bundle(tmp_path)
    monkeypatch.setattr(metric_adapter, "evaluate_case_metrics_fd", lambda *_args, **_kwargs: {
        "schema": metric_adapter.SCHEMA,
        "case_id": bundle_fixtures.CASE_ID,
        "metric_gates_passed": True,
    })
    with pytest.raises(integration_v2.NativeFluidMetricBundleError,
                       match="exact reviewed v2 case-result schema"):
        integration_v2.verify_native_fluid_table_chain_and_metrics(
            **_inputs(roots, auth_bytes, auth),
        )


def test_v2_metric_bundle_rejects_nonuniform_adapter_time_axis(tmp_path, monkeypatch) -> None:
    roots, auth_bytes, auth = _synthetic_bundle(tmp_path)

    def nonuniform_result(_fd, *, table_verification, **_kwargs):
        result = _valid_metric_result(bundle_fixtures.CASE_ID, table_verification)
        result["selected_time_s"][95] += 1e-6
        return result

    monkeypatch.setattr(metric_adapter, "evaluate_case_metrics_fd", nonuniform_result)
    with pytest.raises(integration_v2.NativeFluidMetricBundleError,
                       match="exact frozen closed observation window"):
        integration_v2.verify_native_fluid_table_chain_and_metrics(
            **_inputs(roots, auth_bytes, auth),
        )


def test_metric_review_receipt_must_bind_both_v2_code_sources() -> None:
    receipt = json.loads(_metric_review_bytes())
    receipt["evidence"] = receipt["evidence"][:1]
    payload = json.dumps(receipt).encode("utf-8")
    with pytest.raises(integration_v2.NativeFluidMetricBundleError,
                       match="bind the v2 verifier, adapter, and reviewed helper dependency"):
        integration_v2._validate_metric_review_document(payload, hashlib.sha256(payload).hexdigest())


def test_table_review_v1_artifacts_remain_unmodified_by_v2_metric_layer() -> None:
    assert integration_v1.SCHEMA == "core.cfd.f8.r008_native_fluid_table_bundle_verifier.v1"
    assert table_bundle_v1.verify_native_fluid_table_chain.__module__.endswith(
        "f8_r008_native_fluid_table_bundle_verifier_v1",
    )
