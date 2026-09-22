from __future__ import annotations

import json

from scripts.f8_oscillatory_pressure_channel_candidate_v1 import OUTPUT, build_card


def test_f8_is_static_proposal_only() -> None:
    card = build_card()
    assert card["status"] == "proposal_only_root_review_required"
    assert card["admission_granted"] is False
    assert card["qualification_credit"] == 0
    assert card["identity"]["production_case_count"] == 32
    assert card["identity"]["split"] == {"train": 16, "validation": 4, "id_test": 6, "ood_test": 6}


def test_f8_does_not_mutate_core_controls() -> None:
    controls = build_card()["execution_controls"]
    assert controls["definition_written"] is False
    assert controls["gencase_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["registry_mutation"] == 0
    assert controls["denominator_mutation"] == 0


def test_committed_card_is_hash_bound_and_still_unqualified() -> None:
    assert OUTPUT.is_file()
    card = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert card["status"] == "proposal_only_root_review_required"
    assert len(card["evidence"]) == 6
    assert all(row["sha256"] for row in card["evidence"])
    assert card["execution_controls"]["solver_invoked"] is False
