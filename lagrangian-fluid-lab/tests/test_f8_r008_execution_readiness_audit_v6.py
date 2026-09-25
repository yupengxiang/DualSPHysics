from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_execution_readiness_audit_v6 as audit


def test_v6_reconciles_the_stale_matrix_review_without_clearing_execution_gaps() -> None:
    value = audit.build_audit()

    assert value["schema"] == audit.SCHEMA
    assert value["status"] == "static_diagnostic_matrix_reviewed_execution_trust_and_t1_pending"
    matrix = value["verifier_stack"]["15_case_metric_matrix_v4"]
    assert matrix["review_archive_current"] is True
    assert matrix["counts_as_current_static_review_pass"] is True
    assert matrix["execution_attempt_identity_verified"] is False
    assert matrix["normal_completion_verified"] is False
    assert matrix["cross_field_native_semantics_verified"] is False
    assert value["historical_v5"]["matrix_review_was_current"] is False
    codes = {item["code"] for item in value["blocking_gaps"]}
    assert "matrix_implementation_review_binding_stale_after_test_update" not in codes
    assert codes == audit.EXPECTED_PENDING_GAPS


def test_v6_never_admits_solver_t1_or_credit() -> None:
    value = audit.build_audit()
    assert value["readiness_pass"] is False
    assert value["full_t1_decision"] is False
    assert value["T1_numerical"] is False
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert all(item is False or item == 0 for item in value["execution_authority"].values())
    assert all(item is False or item == 0 for item in value["execution_controls"].values())


def test_v6_binds_current_review_and_preserves_historical_v5() -> None:
    value = audit.build_audit()
    evidence = {item["path"]: item for item in value["evidence"]}
    assert audit.V5_RECEIPT.as_posix() in evidence
    assert "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/native-fluid-table-schema-v2/metric-matrix-review-v3/receipt.json" in evidence
    assert "scripts/f8_r008_runparts_timestep_diagnostic_v2.py" in evidence
    assert "scripts/f8_r008_t1_metric_matrix_adapter_v4.py" in evidence
    assert all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in evidence.values())
    assert value["supersedes"]["sha256"] == evidence[audit.V5_RECEIPT.as_posix()]["sha256"]
    assert len(evidence) == len(value["evidence"])


def test_v6_writer_is_immutable_and_verifier_detects_tampering(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    assert audit.write_audit(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == audit.verify_audit(target)
    with pytest.raises(FileExistsError, match="immutable R008 execution-readiness audit v6"):
        audit.write_audit(target)
    value = json.loads(target.read_text(encoding="utf-8"))
    value["readiness_pass"] = True
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(audit.ReadinessAuditError, match="no longer matches its pinned evidence"):
        audit.verify_audit(target)
