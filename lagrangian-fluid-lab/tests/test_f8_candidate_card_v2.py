from __future__ import annotations

import json
from pathlib import Path

from scripts.f8_candidate_card_v2 import OUTPUT, SOURCE, build_card


ROOT = Path(__file__).resolve().parents[1]


def test_v2_card_renames_body_force_and_keeps_root_decision_pending() -> None:
    card = build_card()
    assert card["schema"] == "core.cfd.f8_oscillatory_body_force_channel_candidate.v2"
    assert card["status"] == "static_revision_pending_root_scope_ruling"
    assert card["mechanism"]["name"] == "body-force-driven oscillatory viscous channel"
    assert card["root_decision"]["status"] == "pending_formal_root_scope_ruling"
    assert card["root_decision"]["no_implicit_selection"] is True
    assert card["qualification_credit"] == 0
    assert card["execution_controls"]["definition_written"] is False
    assert card["execution_controls"]["solver_invoked"] is False
    assert card["execution_controls"]["registry_mutation"] == 0


def test_v2_card_is_versioned_without_overwriting_v1() -> None:
    assert OUTPUT.is_file()
    assert SOURCE.is_file()
    card = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert card["schema"].endswith("candidate.v2")
    assert card["supersedes_for_current_static_review"]["path"].endswith("candidate-card-v1.json")
    historical = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert historical["schema"] == "core.cfd.f8_oscillatory_pressure_channel_candidate.v1"
    assert all(item["path"] for item in card["current_static_evidence"])
