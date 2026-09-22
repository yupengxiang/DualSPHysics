from __future__ import annotations

import json

from scripts.core_third_t1_frontier_audit_v1 import OUTPUT, build_audit


def test_frontier_audit_preserves_closed_routes_and_f7_no_go() -> None:
    result = build_audit()
    assert result["status"] == "no_admissible_third_t1_candidate_at_current_state"
    assert result["third_family_established"] is False
    assert result["route_decisions"]["F1_F2"]["same_input_retry"] is False
    assert result["route_decisions"]["F6"]["solver_canary_cells_passed"] == 7
    assert result["route_decisions"]["F6"]["remaining_cells_authorized"] is False
    assert result["route_decisions"]["F7"]["admission_granted"] is False
    assert result["qualification_credit"] == 0


def test_committed_frontier_audit_is_hash_bound_and_non_mutating() -> None:
    assert OUTPUT.is_file()
    result = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert len(result["evidence"]) == 10
    assert all(row["sha256"] for row in result["evidence"])
    assert result["execution_controls"]["solver_invoked"] is False
    assert result["execution_controls"]["registry_mutation"] == 0
    assert result["route_decisions"]["F8"]["admission_granted"] is False
    assert result["route_decisions"]["F8"]["terra_high_review"] == "conditional_go_static_preparation_no_admission"
    assert result["route_decisions"]["F8"]["parameter_contract"] == "pre_admission_static_contract_frozen"
