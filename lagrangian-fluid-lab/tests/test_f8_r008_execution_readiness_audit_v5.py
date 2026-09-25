from __future__ import annotations

import json

import pytest

from scripts import f8_r008_execution_readiness_audit_v5 as audit


def test_v5_reconciles_the_stale_verifier_gap_and_current_review_drift() -> None:
    value = audit.build_audit()
    assert value["status"] == "static_verifiers_present_execution_trust_and_t1_pending"
    stack = value["verifier_stack"]
    assert stack["per_case_b_c_d_bundle"]["review_receipt_current_for_bound_sources"] is True
    assert stack["per_case_b_c_d_bundle"]["authenticates_execution_source"] is False
    assert stack["native_fluid_table_metric_bundle_v2"]["review_receipt_current_for_bound_sources"] is True
    matrix = stack["15_case_metric_matrix_v2"]
    assert matrix["review_archive_current"] is False
    assert matrix["implementation_source_drift_paths"] == []
    assert matrix["test_binding_drift_paths"] == [
        "tests/test_f8_r008_t1_metric_matrix_adapter_v2.py"
    ]
    assert matrix["counts_as_current_review_pass"] is False
    codes = {item["code"] for item in value["blocking_gaps"]}
    assert "reviewed_per_case_materialization_verifier_missing" not in codes
    assert {
        "matrix_implementation_review_binding_stale_after_test_update",
        "trusted_worker_execution_source_and_runtime_identity_missing",
        "real_provenance_verified_15_case_t1_results_missing",
        "native_integrity_and_solver_timestep_adjudication_missing",
    } == codes


def test_v5_never_admits_execution_or_t1() -> None:
    value = audit.build_audit()
    assert value["readiness_pass"] is False
    assert value["full_t1_decision"] is False
    assert value["T1_numerical"] is False
    assert value["qualification_credit"] == 0
    assert all(item is False or item == 0 for item in value["execution_authority"].values())
    assert all(item is False or item == 0 for item in value["execution_controls"].values())


def test_v5_binds_historical_and_current_zero_credit_evidence() -> None:
    value = audit.build_audit()
    evidence = {item["path"]: item for item in value["evidence"]}
    assert audit.V4_RECEIPT.as_posix() in evidence
    assert audit.matrix_review.OUTPUT.relative_to(audit.LAB).as_posix() in evidence
    assert "scripts/f8_r008_per_case_bundle_verifier_v1.py" in evidence
    assert "scripts/f8_r008_t1_metric_matrix_adapter_v2.py" in evidence
    assert all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in evidence.values())


def test_v5_writer_is_immutable_and_verifier_detects_tampering(tmp_path) -> None:
    target = tmp_path / "receipt.json"
    assert audit.write_audit(target) == target
    assert json.loads(target.read_text()) == audit.verify_audit(target)
    with pytest.raises(FileExistsError, match="immutable R008 execution-readiness audit v5"):
        audit.write_audit(target)
    value = json.loads(target.read_text())
    value["readiness_pass"] = True
    target.write_text(json.dumps(value))
    with pytest.raises(audit.ReadinessAuditError, match="no longer matches its pinned evidence"):
        audit.verify_audit(target)
