from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / (
    "reports/F4-TALLWALL120-MATERIAL-COARSE-T2-READINESS-SECURITY-AUDIT-"
    "2026-09-29-RERUN2.json"
)


def _report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _path(value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def test_current_f4_bindings_are_present_and_unchanged() -> None:
    report = _report()
    assert report["schema"] == "core.material.f4.tallwall120.coarse_t2.readiness_security_audit.v1"
    assert report["decision"]["status"] == "blocked_fail_closed"
    assert report["decision"]["readiness_status"] == (
        "blocked_missing_external_admission_and_terminal_receipts"
    )
    assert report["decision"]["T1"] is False
    assert report["decision"]["T2"] is False
    assert report["decision"]["T2_macro"] is False
    assert report["decision"]["T2_path"] is False
    assert report["decision"]["formal"] is False
    assert report["decision"]["formal_eligible"] is False
    assert report["decision"]["credit"] == 0
    assert report["decision"]["promotion_allowed"] is False

    assert report["scope"]["family"] == "F4"
    assert report["scope"]["case_id"].startswith("F4_")
    for name, binding in report["input_bindings"].items():
        path = _path(binding["path"])
        assert path.is_file(), name
        assert "F3" not in binding["path"], name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload.get("schema") == binding["schema"], name
        assert payload.get("status") == binding["status"], name
        assert binding["credit"] == 0, name


def test_external_admission_and_terminal_receipts_are_still_missing() -> None:
    report = _report()
    probes = report["receipt_probes"]
    for name, probe in probes.items():
        path = _path(probe["path"])
        assert probe["exists"] is False, name
        assert probe["regular_file"] is False, name
        assert probe["symlink"] is False, name
        assert not path.exists(), name
        assert not path.is_symlink(), name

    assert report["input_bindings"]["root_scheduler_intake"]["status"] == (
        "blocked_missing_fresh_root_scheduler_receipts"
    )
    assert report["input_bindings"]["fresh_root_scheduler_contract"]["status"] == (
        "blocked_missing_fresh_root_scheduler_receipts"
    )
    assert report["input_bindings"]["external_receipt_intake"]["status"] == (
        "blocked_missing_external_receipts"
    )
    assert report["input_bindings"]["host_io_projection"]["status"] == (
        "diagnostic_admission_blocked"
    )


def test_existing_diagnostics_cannot_satisfy_current_t2() -> None:
    report = _report()
    current = report["terminal_diagnostics"]["current_dev07_baseline24"]
    assert current["classification"] == "diagnostic_negative"
    assert current["source_trace_completed"] is True
    assert current["event_window_complete"] is False
    assert current["unknown_fraction_max"] == 1.0
    assert current["common_reliable_path_coverage"] == 0.0
    assert current["mass_closed"] is True
    assert current["T2"] is False
    assert current["credit"] == 0
    assert current["promote"] is False

    canary = report["terminal_diagnostics"]["historical_canary"]
    assert canary["event_window_complete"] is False
    assert canary["reusable_for_current_formal_admission"] is False
    dense = report["terminal_diagnostics"]["historical_dense_s2_s4"]
    assert dense["event_window_complete"] is False
    assert dense["reusable_for_current_formal_admission"] is False
    assert report["decision"]["minimum_safe_next_step"].startswith("Obtain real")


def test_security_boundary_has_no_execution_or_state_mutation() -> None:
    report = _report()
    boundary = report["security_boundary"]
    for field in (
        "production_hdf5_content_opened",
        "production_hdf5_content_rehashed",
        "receipt_files_created",
        "fresh_namespace_created",
        "scheduler_spec_created",
        "queue_submitted",
        "queue_started",
        "worker_started",
        "solver_started",
        "native_started",
        "gpu_started",
    ):
        assert boundary[field] is False, field
    for field in (
        "registry_mutations",
        "ledger_mutations",
        "denominator_mutations",
        "gate_mutations",
        "completion_mutations",
        "plan_mutations",
    ):
        assert boundary[field] == 0, field
    assert boundary["read_only_audit"] is True
    assert boundary["bounded_json_inputs_only"] is True
    assert boundary["history_rewritten"] is False
    assert boundary["f3_files_touched"] is False

    next_action = report["next_action_boundary"]
    assert next_action["scheduler_spec"] == "not_added_because_external_receipts_are_missing"
    assert all("submit" not in item for item in next_action["safe_now"])
    assert any("scheduler workload" in item for item in next_action["unsafe_or_not_admitted_now"])
