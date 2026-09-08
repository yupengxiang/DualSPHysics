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
