from __future__ import annotations

import json
from pathlib import Path

from scripts import f4_tallwall120_material_coarse_t2_rerun3_gap_audit_v1 as audit


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / audit.DEFAULT_JSON
ZH_REPORT = ROOT / audit.DEFAULT_ZH


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def test_rerun3_report_is_current_and_self_validating() -> None:
    report = _json(REPORT)
    assert audit.validate_report(report) == []
    assert report == audit.build_report(ROOT)
    assert report["artifact_class"] == "gap_report"
    assert report["receipt_created"] is False


def test_all_contract_checks_are_closed_without_a_repair() -> None:
    report = _json(REPORT)
    assert all(report["contract_checks"].values())
    assert report["finding"]["real_fail_closed_admission_vulnerability_found"] is False
    assert report["finding"]["repair_applied"] is False
    assert report["finding"]["code_mutation"] is False
    assert report["spec_boundary"]["scheduler_spec_created"] is False
    assert report["spec_boundary"]["submit_allowed"] is False


def test_missing_authority_terminal_sidecar_and_matrix_are_explicit() -> None:
    report = _json(REPORT)
    snapshot = report["contract_snapshot"]
    assert snapshot["root_scheduler"]["launch_admitted"] is False
    assert snapshot["host_io"]["probe_is_authorization"] is False
    assert snapshot["terminal_evidence"]["sidecar_present"] is False
    assert snapshot["material_sidecar"]["sidecar_present"] is False
    assert snapshot["sidecar_matrix"]["expected_case_count"] == 32
    assert snapshot["sidecar_matrix"]["missing_case_count"] == 32
    assert snapshot["sidecar_matrix"]["formal_acceptance_receipt_count"] == 0


def test_execution_boundary_has_no_forbidden_side_effects() -> None:
    report = _json(REPORT)
    boundary = report["execution_boundary"]
    for field in (
        "receipt_files_created", "fresh_namespace_created", "scheduler_spec_created",
        "queue_submitted", "queue_started", "worker_started", "solver_started", "gpu_started",
        "history_rewritten",
    ):
        assert boundary[field] is False
    for field in (
        "registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations",
        "completion_mutations", "plan_mutations", "update_411_mutations",
    ):
        assert boundary[field] == 0
    assert boundary["new_f4_paths_only"] is True
    assert all("F3" not in path and "A8" not in path and "F8" not in path for path in boundary["new_paths"])


def test_chinese_gap_report_is_present_and_non_authorizing() -> None:
    text = ZH_REPORT.read_text(encoding="utf-8")
    assert "F4 Tallwall120 material/T2 RERUN3 gap audit" in text
    assert "不是 receipt" in text
    assert "不创建或提交 scheduler spec" in text
    assert "UPDATE-411" in text
