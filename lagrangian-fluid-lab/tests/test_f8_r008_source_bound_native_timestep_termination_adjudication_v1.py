from __future__ import annotations

import copy

import pytest

from scripts import f8_r008_source_bound_native_timestep_termination_adjudication_v1 as contract
from scripts import f8_r008_native_integrity_registry_v1 as registry


def _fixture() -> dict:
    return contract.build_synthetic_input()


def _rebind_case(case: dict) -> None:
    native = case["native"]
    timestep = case["timestep"]
    termination = case["termination"]
    expected = {
        "native_sha256": contract._json_sha256(native, "test native"),
        "timestep_sha256": contract._json_sha256(
            contract._timestep_projection(timestep), "test timestep",
        ),
        "termination_sha256": contract._json_sha256(termination, "test termination"),
    }
    case["evidence_bindings"] = {
        **expected,
        "bundle_sha256": contract._json_sha256(
            contract._case_bundle_projection(
                case["case_id"],
                case["attempt_nonce_hex"],
                case["source_binding_sha256"],
                expected,
            ),
            "test bundle",
        ),
    }


def test_valid_source_bound_fixture_is_cross_bound_but_not_authorized() -> None:
    result = contract.adjudicate_source_bound_synthetic_input(_fixture())

    assert result["schema"] == contract.SCHEMA
    assert result["status"] == "source_bound_synthetic_observations_consistent_untrusted"
    assert result["case_count"] == 15
    assert result["consistent_case_count_untrusted"] == 15
    assert result["native_registry"]["aggregation_status"] == "incomplete"
    assert result["native_registry"]["denominator_cells"] == 120
    assert result["source_binding"]["binding_verified_against_current_static_audit"] is True
    assert result["source_binding"]["production_source_authenticated"] is False
    assert result["source_binding"]["runtime_identity_verified"] is False
    assert result["native_integrity_adjudicated"] is False
    assert result["solver_timestep_adjudicated"] is False
    assert result["termination_adjudicated"] is False
    assert result["normal_completion_verified"] is False
    assert result["T1_numerical"] is False
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0
    assert result["execution_authority"] == {
        "solver": False,
        "worker": False,
        "gpu": False,
        "queue": False,
        "root_or_capability_probe": False,
    }
    assert result["registry_mutations"] == 0
    assert result["ledger_mutations"] == 0
    assert result["gate_mutations"] == 0
    assert all(
        row["diagnostic_status"]
        == "source_bound_synthetic_observations_consistent_untrusted"
        for row in result["cases"]
    )


def test_source_binding_rejects_projection_drift() -> None:
    value = _fixture()
    value["source_binding"]["source_projection_sha256"] = "b" * 64

    with pytest.raises(contract.SourceBoundAdjudicationError, match="source_binding"):
        contract.adjudicate_source_bound_synthetic_input(value)


def test_source_binding_rejects_static_source_snapshot_drift(monkeypatch) -> None:
    value = _fixture()
    original = contract.source_semantics.build_audit

    def drifted_audit():
        observed = copy.deepcopy(original())
        first = next(iter(observed["source_evidence"].values()))
        first["sha256"] = "b" * 64
        return observed

    monkeypatch.setattr(contract.source_semantics, "build_audit", drifted_audit)
    with pytest.raises(contract.SourceBoundAdjudicationError, match="source_binding"):
        contract.adjudicate_source_bound_synthetic_input(value)


def test_case_source_binding_rebind_fails_closed() -> None:
    value = _fixture()
    value["cases"][3]["source_binding_sha256"] = "b" * 64

    with pytest.raises(contract.SourceBoundAdjudicationError, match="source_binding_sha256"):
        contract.adjudicate_source_bound_synthetic_input(value)


def test_duplicate_attempt_nonce_fails_closed() -> None:
    value = _fixture()
    value["cases"][1]["attempt_nonce_hex"] = value["cases"][0]["attempt_nonce_hex"]
    _rebind_case(value["cases"][1])

    with pytest.raises(contract.SourceBoundAdjudicationError, match="nonce_hex is reused"):
        contract.adjudicate_source_bound_synthetic_input(value)


def test_evidence_hash_rebinding_fails_closed() -> None:
    value = _fixture()
    value["cases"][0]["native"]["mass_error_kg"] = 1.0

    with pytest.raises(contract.SourceBoundAdjudicationError, match="native_sha256"):
        contract.adjudicate_source_bound_synthetic_input(value)


def test_open_native_gate_cannot_be_upgraded_by_the_sidecar() -> None:
    value = _fixture()
    value["cases"][0]["native"]["gate_results"]["native_state_finite"] = {
        "status": "defined_pass",
        "evidence_sha256": "a" * 64,
    }
    _rebind_case(value["cases"][0])

    with pytest.raises(contract.SourceBoundAdjudicationError, match="native gate registry rejected"):
        contract.adjudicate_source_bound_synthetic_input(value)


def test_termination_rebind_is_reported_negative_not_authorized() -> None:
    value = _fixture()
    value["cases"][0]["termination"]["observed_final_time_s"] = 9.0
    _rebind_case(value["cases"][0])

    result = contract.adjudicate_source_bound_synthetic_input(value)
    row = result["cases"][0]
    assert result["status"] == "source_bound_synthetic_observations_inconsistent_untrusted"
    assert row["diagnostic_status"] == "source_bound_synthetic_observations_inconsistent_untrusted"
    assert "final_time_rebound_between_timestep_and_termination" in row["termination"]["violations"]
    assert row["termination"]["normal_completion_verified"] is False
    assert row["termination"]["termination_adjudicated"] is False
    assert result["qualification_credit"] == 0


def test_early_stop_claim_is_cross_checked_and_cannot_become_completion() -> None:
    value = _fixture()
    case = value["cases"][0]
    case["timestep"]["runtime_completion_evidence"]["nstepsbreak_observed"] = True
    case["termination"]["early_stop_flags"]["nstepsbreak_observed"] = True
    _rebind_case(case)

    result = contract.adjudicate_source_bound_synthetic_input(value)
    row = result["cases"][0]
    assert row["solver_timestep"]["diagnostic"]["runparts_runtime_claims_consistent_untrusted"] is False
    assert "synthetic_early_stop_or_control_override_observed" in row["termination"]["violations"]
    assert row["termination"]["normal_completion_verified"] is False
    assert result["solver_timestep_adjudicated"] is False


def test_timestep_source_evidence_is_carried_into_the_cross_binding() -> None:
    result = contract.adjudicate_source_bound_synthetic_input(_fixture())
    row = result["cases"][0]
    source_semantics = row["solver_timestep"]["diagnostic"]["source_semantics"]

    assert source_semantics["source_authenticated"] is False
    assert source_semantics["runtime_binary_identity_verified"] is False
    assert source_semantics["effective_integrator_verified"] is False
    assert source_semantics["source_files"]
    assert row["solver_timestep"]["solver_timestep_adjudicated"] is False


def test_extra_authority_fields_are_rejected_instead_of_ignored() -> None:
    value = _fixture()
    value["cases"][0]["native"]["native_integrity_adjudicated"] = True

    with pytest.raises(contract.SourceBoundAdjudicationError, match="exact synthetic native schema"):
        contract.adjudicate_source_bound_synthetic_input(value)


def test_report_is_json_serializable_and_keeps_all_authority_holds() -> None:
    report = contract.build_synthetic_report()

    assert report["schema"] == contract.REPORT_SCHEMA
    assert report["audit"]["increment_is_non_duplicate"] is True
    assert report["contract"]["caller_supplied_inputs_cannot_authenticate_production"] is True
    assert report["result"]["native_integrity_adjudicated"] is False
    assert report["result"]["solver_timestep_adjudicated"] is False
    assert report["result"]["termination_adjudicated"] is False
    assert report["result"]["qualification_credit"] == 0
    assert report["safety_boundary"]["solver_started"] is False
    assert report["safety_boundary"]["worker_started"] is False
    assert report["safety_boundary"]["gpu_started"] is False
    assert report["safety_boundary"]["queue_started"] is False


def test_frozen_registry_still_owns_the_case_order_used_by_the_sidecar() -> None:
    value = _fixture()
    assert [row["case_id"] for row in value["cases"]] == list(
        registry.EXPECTED_QUALIFICATION_CASE_IDS
    )
