from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f1_f2_third_t1_route_audit_v1 import LAB, OUTPUT, REPORT, verify


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audit() -> dict:
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


def test_route_audit_is_hash_bound_and_current() -> None:
    audit = verify(OUTPUT)
    assert audit["schema"] == "core.third_t1.f1_f2_route_audit.v1"
    for item in audit["hash_bindings"].values():
        path = LAB / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert _sha256(path) == item["sha256"]


def test_f1_and_receiver_weir_failures_are_retained() -> None:
    audit = _audit()
    f1 = audit["f1_audit"]
    assert f1["qualified"] is False
    assert f1["T1_numerical"] is False
    assert f1["h1_h2_decision"].startswith("stop this F1 repair mechanism")
    assert f1["suspended_obstacle_hard_integrity"] is False
    assert f1["suspended_obstacle_event_complete"] is True
    assert f1["matrix_credit"] == 0
    assert f1["same_input_retry"] is False

    f2 = audit["f2_receiver_overflow_weir_audit"]
    assert f2["planned"] == 15
    assert f2["executed"] == 1
    assert f2["failed"] == 1
    assert f2["event_censored"] == 1
    assert f2["unattempted"] == 14
    assert f2["matrix_credit"] == 0
    assert f2["hard_integrity_pass"] is False
    assert f2["event_window_complete"] is False
    assert f2["same_input_retry"] is False


def test_selected_orifice_step_is_proposal_only_and_zero_credit() -> None:
    audit = _audit()
    selected = audit["selected_next_step"]
    assert selected["family"] == "F2"
    assert selected["scope_id"] == "F2_submerged_orifice_transfer_v1"
    assert selected["status"] == "proposal_only_root_review_required"
    assert selected["future_case_id"].endswith("normalremediation_v2")
    assert selected["old_failed_input_reused"] is False
    assert selected["old_failed_trajectory_reused"] is False
    assert selected["denominator"] == {
        "planned": 15,
        "executed": 0,
        "passed": 0,
        "failed": 0,
        "event_censored": 0,
        "unattempted": 15,
        "credit": 0,
        "same_input_retry": False,
        "threshold_relaxation": False,
        "survivor_renormalization": False,
    }
    controls = selected["authorization_now"]
    assert controls["definition_writer"] is False
    assert controls["cpu_gencase"] is False
    assert controls["native_decode"] is False
    assert controls["solver"] is False
    assert controls["gpu"] is False
    assert controls["queue_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["qualification_credit"] == 0


def test_core_gate_and_report_are_unchanged() -> None:
    audit = _audit()
    gate = audit["core_gate"]
    assert gate["current_registered_t1_families"] == ["F3", "F4"]
    assert gate["third_t1_family_established"] is False
    assert gate["qualification_credit_added"] == 0
    assert gate["core_gate_changed"] is False
    assert gate["registry_mutation"] == 0
    assert gate["ledger_mutation"] == 0
    text = REPORT.read_text(encoding="utf-8")
    assert "没有重跑同一输入" in text
    assert "core_gate_changed=false" in text
