"""Regression checks for the immutable, current F1/F2 route snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import f1_f2_third_t1_route_closed_v3_refresh as refresh


ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v3.json"
RECEIPT = ROOT / (
    "campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v3.json"
)
COMPLETION = ROOT / "campaigns/core-v1/completion.json"
HISTORICAL_CARD = ROOT / "campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json"
HISTORICAL_RECEIPT = ROOT / (
    "campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v2.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_refresh_builder_is_additive_and_preserves_historical_inputs() -> None:
    historical_bytes = {
        HISTORICAL_CARD: HISTORICAL_CARD.read_bytes(),
        HISTORICAL_RECEIPT: HISTORICAL_RECEIPT.read_bytes(),
    }
    completion_bytes = COMPLETION.read_bytes()

    card, receipt = refresh.build()

    assert HISTORICAL_CARD.read_bytes() == historical_bytes[HISTORICAL_CARD]
    assert HISTORICAL_RECEIPT.read_bytes() == historical_bytes[HISTORICAL_RECEIPT]
    assert COMPLETION.read_bytes() == completion_bytes
    assert card["refresh"] == {
        "historical_source": "campaigns/core-v1/cfd/"
        "f1-f2-third-t1-route-closed-v2.json",
        "historical_receipt_preserved": True,
        "current_completion_bound": True,
    }
    assert card["evidence"]["core_completion"]["sha256"] == _sha256(COMPLETION)
    assert card["evidence"]["core_completion"]["bytes"] == COMPLETION.stat().st_size
    assert receipt["candidate_card"]["sha256"] is None
    assert receipt["candidate_card"]["bytes"] is None


def test_refresh_builder_keeps_route_closed_and_all_mutations_zero() -> None:
    card, receipt = refresh.build()

    assert card["status"] == "route_closed_no_new_hypothesis"
    assert card["core_gate"]["qualification_credit_added"] == 0
    assert card["core_gate"]["registry_mutation"] == 0
    assert card["core_gate"]["ledger_mutation"] == 0
    assert card["core_gate"]["T1_denominator_mutation"] == 0
    assert card["core_gate"]["T2_denominator_mutation"] == 0
    assert card["execution_controls"]["gpu_launched"] is False
    assert card["execution_controls"]["queue_mutation"] == 0
    assert card["execution_controls"]["qualification_credit"] == 0
    assert receipt["root_review"]["authorized_now"] is False
    assert receipt["root_review"]["qualification_credit"] == 0
    assert receipt["route_decision"]["new_physical_definition_found"] is False


def test_current_snapshot_rebinds_completion_without_granting_credit() -> None:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    completion = json.loads(COMPLETION.read_text(encoding="utf-8"))

    assert card["schema"] == "core.third_t1.f1_f2_route_closed.candidate_card.v3"
    assert card["execution_host"] == "Terra High"
    assert card["status"] == "route_closed_no_new_hypothesis"
    assert card["core_gate"]["qualification_credit_added"] == 0
    assert card["core_gate"]["third_t1_family_established"] is False
    assert card["evidence"]["core_completion"]["sha256"] == _sha256(COMPLETION)
    assert card["evidence"]["core_completion"]["bytes"] == COMPLETION.stat().st_size

    assert receipt["schema"] == "core.third_t1.f1_f2.route_decision_receipt.v3"
    assert receipt["execution_host"] == "Terra High"
    assert receipt["route_decision"]["new_physical_definition_found"] is False
    assert receipt["root_review"]["authorized_now"] is False
    assert receipt["root_review"]["qualification_credit"] == 0
    assert receipt["candidate_card"]["sha256"] == _sha256(CARD)
    assert receipt["candidate_card"]["bytes"] == CARD.stat().st_size

    assert HISTORICAL_CARD.exists()
    assert card["refresh"]["historical_receipt_preserved"] is True
