from __future__ import annotations

import json
from pathlib import Path

from scripts import f4_tallwall120_material_cpu_diagnostic_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / intake.DEFAULT_JSON
ZH_REPORT = ROOT / intake.DEFAULT_ZH_CN


def _json(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def test_current_bound_intake_is_self_validating_and_blocked_before_execution() -> None:
    report = _json(REPORT)
    assert intake.validate_report(report) == []
    assert report == intake.build_report(ROOT)
    assert report["status"] == "blocked_before_execution"
    assert report["receipt_created"] is False
    assert report["selected_input"]["diagnostic"]["checks"]["report_readable"] is True
    assert report["selected_input"]["diagnostic"]["historical_negative_only"] is True


def test_current_gap_and_entry_bindings_are_explicit() -> None:
    report = _json(REPORT)
    checks = report["checks"]
    assert checks["gap_report_current_and_valid"] is True
    assert checks["core_runtime_entry_contract_valid"] is True
    assert checks["material_entry_contract_valid"] is True
    assert checks["sidecar_entry_contract_valid"] is True
    assert checks["terminal_entry_contract_valid"] is True
    assert checks["fresh_root_receipt_present"] is False
    assert checks["scheduler_host_io_receipt_present"] is False
    assert checks["terminal_sidecar_present"] is False
    assert checks["material_case_sidecar_present"] is False
    assert checks["launch_admitted"] is False
    assert checks["all_execution_prerequisites_closed"] is False
    assert "fresh_root_receipt_missing_or_invalid" in report["blocking_reasons"]
    assert "scheduler_owned_host_io_reservation_missing_or_invalid" in report["blocking_reasons"]


def test_hdf5_and_formal_boundaries_remain_closed() -> None:
    report = _json(REPORT)
    source = report["selected_input"]["source_hdf5"]
    assert source["metadata_contract_valid"] is True
    assert source["content_opened"] is False
    assert source["content_read"] is False
    assert source["hash_recomputed"] is False
    assert report["authorization"] == {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "qualification": False,
        "T1": False,
        "T2": False,
        "T2_macro": False,
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "credit": 0,
    }
    boundary = report["execution_boundary"]
    for key in (
        "diagnostic_executed", "runner_invoked", "source_hdf5_opened", "source_hdf5_read",
        "source_hdf5_hash_recomputed", "fresh_namespace_created", "material_sidecar_written",
        "terminal_receipt_created", "solver_started", "worker_started", "native_started",
        "gpu_started", "queue_started", "history_rewritten",
    ):
        assert boundary[key] is False
    for key in (
        "registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations",
        "completion_mutations", "plan_mutations",
    ):
        assert boundary[key] == 0


def test_chinese_artifact_reports_the_safe_stop() -> None:
    text = ZH_REPORT.read_text(encoding="utf-8")
    assert "不是 receipt、不是 launch authorization" in text
    assert "DEV_07" in text
    assert "没有把历史结果伪造成 fresh receipt" in text
    assert "没有启动 solver/worker/native/GPU/queue" in text
