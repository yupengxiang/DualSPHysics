import json

import pytest

from scripts.l2_b2r_contract import (
    B2RContractError,
    StudySpec,
    B2RWaitingForR2,
    assert_execution_allowed,
    build_study_spec,
    evaluate_r2_dependency,
    validate_preparation_manifest,
)


def test_preparation_defaults_to_waiting_for_r2_and_declares_six_logical_runs():
    spec, manifest = build_study_spec()
    assert spec.evaluation_case_ids
    assert len(spec.evaluation_case_ids) == 16
    assert len(spec.logical_runs) == 6
    assert manifest["status"] == "waiting_for_R2"
    assert manifest["execution_status"] == "waiting_for_R2"
    assert manifest["launch_allowed"] is False
    assert manifest["acceptance"]["B2R_terminal"] is False
    assert manifest["historical_baseline_boundary"]["can_satisfy_B2R"] is False
    assert manifest["dependencies"]["R2"]["status"] == "waiting_for_R2"
    assert validate_preparation_manifest(manifest)["valid"] is True


def test_r2_gate_does_not_accept_old_b2_report_or_partial_evidence():
    assert evaluate_r2_dependency(None).status == "waiting_for_R2"
    assert evaluate_r2_dependency({"schema": "l2.b2.learning_baseline.v1"}).status == "waiting_for_R2"
    partial = {
        "schema": "l2r.r2.f3_contract.v1",
        "status": "complete_with_findings",
        "acceptance": {
            "current_f3_contract_recorded": True,
            "actual_oracle_runs_recorded": False,
            "legacy_reuse_boundary_explicit": True,
        },
    }
    gate = evaluate_r2_dependency(partial)
    assert gate.status == "waiting_for_R2"
    assert gate.launch_allowed is False
    assert "actual_oracle_runs" in gate.reason


def test_explicit_complete_r2_evidence_is_only_a_dependency_signal():
    evidence = {
        "schema": "l2r.r2.f3_contract.v1",
        "status": "complete_with_findings",
        "acceptance": {
            "current_f3_contract_recorded": True,
            "actual_oracle_runs_recorded": True,
            "legacy_reuse_boundary_explicit": True,
        },
    }
    gate = evaluate_r2_dependency(evidence)
    assert gate.status == "satisfied"
    assert gate.launch_allowed is True
    spec, manifest = build_study_spec(r2_evidence=evidence, r0_verified=False)
    assert spec.r2_gate.launch_allowed is True
    assert manifest["status"] == "prepared_not_launched"
    assert manifest["launch_allowed"] is False
    assert manifest["acceptance"]["B2R_terminal"] is False


def test_execution_guard_is_closed_without_r2():
    spec, _ = build_study_spec()
    with pytest.raises(B2RWaitingForR2, match="waiting_for_R2"):
        assert_execution_allowed(spec)


def test_study_does_not_claim_training_was_started():
    _, manifest = build_study_spec()
    assert manifest["study_design"]["no_training_started_by_preparation"] is True
    assert manifest["acceptance"]["new_training_attempts_executed"] is False
    assert manifest["attempt_contract"]["failed_and_retried_attempts_in_manifest"] is True
