from __future__ import annotations

import json
from pathlib import Path

from scripts.f7_pump_force_gauge_capability_audit_v1 import OUTPUT, build_audit


ROOT = Path(__file__).resolve().parents[1]


def test_force_gauge_audit_keeps_torque_gate_closed() -> None:
    result = build_audit()
    capability = result["official_capability"]
    assert capability["aggregate_force_on_moving_mkbound"] is True
    assert capability["pump_moving_mkbound"] == 2
    assert capability["direct_torque_output"] is False
    assert capability["torque_provenance_available"] is False
    assert result["qualification_credit"] == 0
    assert all(value == 0 for value in result["protected_state_mutation"].values())


def test_committed_audit_binds_current_root_review() -> None:
    assert OUTPUT.is_file()
    result = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert result["schema"] == "core.f7.pump.force_gauge_capability_audit.v1"
    assert result["status"] == "root_review_only_instrumentation_gap"
    assert result["bindings"]["root_review"]["path"].endswith("root-review-receipt-v1.json")
