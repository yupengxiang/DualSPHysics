"""Regression checks for the immutable, current F1/F2 route snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v3.json"
RECEIPT = ROOT / (
    "campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v3.json"
)
COMPLETION = ROOT / "campaigns/core-v1/completion.json"
HISTORICAL_CARD = ROOT / "campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
