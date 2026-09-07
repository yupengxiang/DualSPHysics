import pytest

from scripts.protocol_metrics import validate_split_lineage
from scripts.r3_g1_lineage_contract import (
    candidate_w08_contract,
    historical_w08_cards,
    run_diagnostic,
    signature_only_w08_audit,
)
from scripts.w08_generalization_design import build_cards


def test_current_w08_cards_pass_both_contracts():
    cards = build_cards()
    assert candidate_w08_contract(cards)["status"] == "pass"
    validate_split_lineage(cards)


def test_historical_signature_audit_passes_but_w10_lineage_gate_rejects():
    historical = historical_w08_cards(build_cards())
    signature_result = signature_only_w08_audit(historical)
    assert signature_result["status"] == "pass"
    assert signature_result["cross_split_signature_leakage"] == {}
    with pytest.raises(ValueError, match="lineage crosses splits"):
        validate_split_lineage(historical)


def test_candidate_contract_requires_w08_physical_identity():
    cards = build_cards()
    cards[0].pop("physical_case_id")
    with pytest.raises(ValueError, match="identity fields missing"):
        candidate_w08_contract(cards)


def test_candidate_contract_rejects_one_physical_case_mapped_to_two_lineages():
    cards = build_cards()
    cards[1]["physical_case_id"] = cards[0]["physical_case_id"]
    # Keep the records in one split so the failure is specifically the
    # candidate one-to-one physical-to-lineage rule, not the W10 split gate.
    cards[1]["lineage_group_id"] = "lineage_candidate_bad"
    with pytest.raises(ValueError, match="one-to-one"):
        candidate_w08_contract(cards)


def test_report_marks_current_tree_fixed_and_historical_reproduction():
    report = run_diagnostic()
    assert report["status"] == "candidate-only"
    assert report["cpu_only"] is True
    assert report["solver_invoked"] is False
    assert report["current_tree"]["w08_audit"]["status"] == "pass"
    assert report["current_tree"]["w10_validate_split_lineage"]["status"] == "accept"
    assert report["historical_reproduction"]["w08_signature_only_audit"]["status"] == "pass"
    assert report["historical_reproduction"]["w10_validate_split_lineage"]["status"] == "reject"
