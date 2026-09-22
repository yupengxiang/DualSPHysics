from __future__ import annotations

import json

from scripts.core_third_t1_frontier_audit_v2 import OUTPUT, ORACLE_CONTRACT, build_audit


def test_frontier_v2_keeps_zero_credit_and_adds_only_static_f8_oracle() -> None:
    result = build_audit()
    assert result["schema"] == "core.third_t1.frontier_audit.v2"
    assert result["status"] == "no_admissible_third_t1_candidate_at_current_state"
    assert result["current_t1_families"] == ["F3", "F4"]
    assert result["qualification_credit"] == 0
    f8 = result["route_decisions"]["F8"]
    assert f8["admission_granted"] is False
    assert f8["reference_oracle"]["status"] == "static_reference_only_no_admission"
    assert f8["reference_oracle"]["qualification_credit"] == 0
    assert result["execution_controls"]["reference_oracle_materialized"] is True
    assert result["execution_controls"]["definition_written"] is False
    assert result["execution_controls"]["solver_invoked"] is False
    assert result["execution_controls"]["registry_mutation"] == 0
    assert result["execution_controls"]["denominator_mutation"] == 0


def test_committed_frontier_v2_is_new_and_hash_bound() -> None:
    assert OUTPUT.is_file()
    result = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert result["schema"] == "core.third_t1.frontier_audit.v2"
    assert result["evidence"][-1]["path"] == str(ORACLE_CONTRACT)
    assert result["evidence"][-1]["sha256"]
    assert result["evidence"][-1]["bytes"] == ORACLE_CONTRACT.stat().st_size
    assert result["execution_controls"]["solver_invoked"] is False
    assert result["execution_controls"]["registry_mutation"] == 0
    assert result["execution_controls"]["ledger_mutation"] == 0
