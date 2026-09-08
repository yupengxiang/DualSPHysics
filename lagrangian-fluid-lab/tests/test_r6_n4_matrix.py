from __future__ import annotations

import pytest

from scripts import r6_n4_matrix as n4


def test_n4_has_exactly_four_missing_cells_with_single_recipe():
    records = n4.records()
    assert len(records) == 4
    assert {(item["height_label"], item["resolution"]) for item in records} == {
        ("h09", "coarse"), ("h09", "medium"),
        ("h11", "coarse"), ("h11", "medium"),
    }
    assert {item["cfl_number"] for item in records} == {0.1}
    assert {item["time_max_s"] for item in records} == {1.5}
    assert {item["time_out_s"] for item in records} == {0.001}


def test_record_hash_ignores_preparation_derived_fields():
    record = n4.records()[0]
    prepared = {
        **record,
        "candidate_definition": "cases/example.xml",
        "generated_prefix": "artifacts/example",
        "record_hash": "old",
        "candidate_definition_sha256": "candidate",
        "generated_xml_sha256": "xml",
        "generated_bi4_sha256": "bi4",
        "gencase": {"elapsed_seconds": 1.0},
    }
    assert n4.record_hash(record) == n4.record_hash(prepared)


def test_new_solver_requires_explicit_owner_evidence(tmp_path, monkeypatch):
    report_path = tmp_path / "matrix.json"
    monkeypatch.setattr(n4, "MATRIX_REPORT", report_path)
    with pytest.raises(RuntimeError, match="owner-approval-evidence"):
        n4._approval_guard(None)


def test_owner_evidence_must_bind_bounded_scope(tmp_path, monkeypatch):
    report_path = tmp_path / "matrix.json"
    approval_path = tmp_path / "approval.json"
    monkeypatch.setattr(n4, "MATRIX_REPORT", report_path)
    monkeypatch.setattr(n4, "APPROVAL_RECORD", approval_path)
    n4.atomic_json(report_path, n4.load_matrix_report())
    with pytest.raises(RuntimeError, match="must explicitly bind"):
        n4._approval_guard("owner approves unlimited GPU work")


def test_owner_evidence_record_has_bound_digest():
    record = n4._approval_record(
        "Owner explicitly authorizes at most 0.5 GPU·h and four solver attempts "
        "for only h09/h11 coarse/medium."
    )
    assert record["scope"]["gpu_hours_max"] == 0.5
    assert record["scope"]["solver_attempts_max"] == 4
    assert len(record["evidence_sha256"]) == 64


def test_launch_set_requires_exact_canonical_records():
    with pytest.raises(RuntimeError, match="exactly the four canonical"):
        n4._validate_prepared_for_launch(n4.records()[:3])
    altered = n4.records()
    altered[0] = {**altered[0], "height_label": "h11"}
    with pytest.raises(RuntimeError, match="record hash mismatch"):
        n4._validate_prepared_for_launch(altered)


def test_matrix_reuses_persisted_audits_when_rebuilt(tmp_path, monkeypatch):
    report_path = tmp_path / "matrix.json"
    monkeypatch.setattr(n4, "MATRIX_REPORT", report_path)
    prepared = n4.records()
    audits = [{"case_id": item["case_id"], "r6_full_time_audit_status": "pass"} for item in prepared]
    report = n4.load_matrix_report()
    report.update({"prepared_cases": prepared, "audits": audits})
    n4.atomic_json(report_path, report)
    rebuilt = n4.build_matrix()
    new_cells = {item["case_id"]: item for item in rebuilt["cells"] if item.get("role") == "new_n4"}
    assert all(item["audit"]["r6_full_time_audit_status"] == "pass" for item in new_cells.values())


def test_native_exclusion_reconciliation_is_hard_gate(tmp_path):
    attempt = tmp_path / "attempt.complete"
    attempt.mkdir()
    (attempt / "RunPARTs.csv").write_text("native zero record")
    available = {"status": "available", "rows": [{"particle_id": 1}, {"particle_id": 2}, {"particle_id": 3},]}
    assert n4._native_exclusion_reconciliation({"solver_exclusion_evidence": available, "excluded_particles_from_solver_log": 3}, attempt)["status"] == "pass"
    assert n4._native_exclusion_reconciliation({"solver_exclusion_evidence": available, "excluded_particles_from_solver_log": 2}, attempt)["status"] == "failed"
    zero = n4._native_exclusion_reconciliation({"solver_exclusion_evidence": {"status": "no_partout_files"}, "excluded_particles_from_solver_log": 0}, attempt)
    assert zero["status"] == "pass"


def test_decision_requires_audits_and_resolution_pairs(tmp_path, monkeypatch):
    monkeypatch.setattr(n4, "DECISION_REPORT", tmp_path / "decision.json")
    monkeypatch.setattr(n4, "DECISION_MARKDOWN", tmp_path / "decision.md")
    monkeypatch.setattr(n4, "RESOURCE_REPORT", tmp_path / "resource.json")
    pair = {"status": "pass_diagnostic", "maxima": {"distribution_tv": 0.01}}
    matrix = {
        "cells": [
            {"role": "new_n4", "matrix_status": "completed", "audit": {"r6_full_time_audit_status": "pass"}}
            for _ in range(4)
        ],
        "height_comparisons": {
            "h09": {"comparisons": {"coarse_to_medium": pair, "medium_to_fine": pair}},
            "h10": {"comparisons": {"coarse_to_medium": {"status": "fail_diagnostic", "maxima": {"distribution_tv": 0.0569}}}},
            "h11": {"comparisons": {"coarse_to_medium": pair, "medium_to_fine": pair}},
        },
    }
    decision = n4.write_decision(matrix, {"peak": {}}, {})
    assert decision["same_cfl_matrix_complete"] is True
    matrix["cells"][0]["audit"] = {"r6_full_time_audit_status": "failed_or_unknown"}
    decision = n4.write_decision(matrix, {"peak": {}}, {})
    assert decision["same_cfl_matrix_complete"] is False


def test_durable_attempt_summary_counts_completed_and_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(n4, "RUN_ROOT", tmp_path / "runs")
    for case_id, suffix, status, elapsed in (
        ("case-a", ".complete", "completed", 1.25),
        ("case-b", ".failed", "failed", 2.5),
    ):
        attempt = n4.RUN_ROOT / case_id / "attempts" / f"attempt{suffix}"
        attempt.mkdir(parents=True)
        n4.atomic_json(attempt / "attempt.json", {"case_id": case_id, "status": status, "elapsed_seconds": elapsed})
    summary = n4._durable_attempt_summary()
    assert summary["attempts_started"] == 2
    assert summary["attempts_completed"] == 1
    assert summary["attempts_failed"] == 1
    assert summary["device_seconds"] == pytest.approx(3.75)


def test_solver_timeout_stays_within_proposed_gpu_cap():
    assert n4.SOLVER_ATTEMPT_TIMEOUT_SECONDS * n4.MAX_NEW_SOLVER_ATTEMPTS < n4.PROPOSED_GPU_HOURS * 3600


def test_resource_ledger_uses_zero_for_unstarted_solver_phase(tmp_path, monkeypatch):
    report_path = tmp_path / "matrix.json"
    resource_path = tmp_path / "resource.json"
    monkeypatch.setattr(n4, "MATRIX_REPORT", report_path)
    monkeypatch.setattr(n4, "RESOURCE_REPORT", resource_path)
    n4.atomic_json(report_path, n4.load_matrix_report())
    ledger = n4.update_resource_ledger()
    assert ledger["new_n4"]["solver_attempts_started"] == 0
    assert ledger["new_n4"]["solver_device_seconds"] == 0.0


def test_h10_comparison_failure_is_not_hidden_by_other_metrics():
    left = {"status": "complete", "distribution": {"a": 0.2, "b": 0.8}, "com_m": [0.0, 0.0, 0.0],
            "front_quantiles_m": {"q50": 0.0, "q90": 0.0, "q99": 0.0},
            "kinetic_energy_proxy_j": 1.0, "mass_fraction": 1.0, "initial_mass_kg": 1.0,
            "actual_time_s": 1.0, "requested_time_s": 1.05}
    right = {**left, "distribution": {"a": 0.314, "b": 0.686}}
    result = n4._compare_metrics(left, right)
    assert result["distribution_tv"] == pytest.approx(0.114)
    assert result["com_l2_m"] == 0.0
    assert result["front_quantile_abs_delta_m"]["q90"] == 0.0
