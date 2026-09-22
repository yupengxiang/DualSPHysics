from __future__ import annotations

import json

from scripts.f7_pump_direct_torque_admission_proposal_v1 import OUTPUT, build_proposal


def test_proposal_requests_one_cpu_anchor_without_core_mutation() -> None:
    result = build_proposal()
    assert result["status"] == "proposal_pending_root_review_not_authorized"
    permissions = result["requested_permissions_exactly_one_anchor"]
    assert permissions["native_cpu_solver_one_anchor_only"] is True
    assert permissions["compute_forces_cpu_one_anchor_only"] is True
    assert permissions["gpu"] is False
    assert permissions["registry_mutation"] == 0
    assert permissions["ledger_mutation"] == 0
    assert permissions["T1_denominator_mutation"] == 0
    assert result["root_review_decision_required"]["admit_15_row_matrix"] is False


def test_committed_proposal_binds_current_contract_and_binary() -> None:
    assert OUTPUT.is_file()
    result = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert result["schema"] == "core.f7.pump.direct_torque_admission_proposal.v1"
    assert result["bindings"]["compute_forces_contract"]["sha256"]
    assert result["bindings"]["compute_forces_binary"]["sha256"]
