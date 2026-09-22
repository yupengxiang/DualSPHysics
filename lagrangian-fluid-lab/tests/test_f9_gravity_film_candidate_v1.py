from __future__ import annotations

import json

from scripts.f9_gravity_film_candidate_v1 import OUTPUT, build_card


def test_f9_is_free_surface_candidate_and_not_admitted() -> None:
    card = build_card()
    assert card["status"] == "proposal_only_root_review_required"
    assert card["admission_granted"] is False
    assert card["qualification_credit"] == 0
    assert card["physical_contract"]["surface_tension"] is False
    assert card["identity"]["production_case_count"] == 32
    assert card["identity"]["split"] == {"train": 16, "validation": 4, "id_test": 6, "ood_test": 6}


def test_f9_has_distinct_nusselt_falsifier_and_no_open_channel_reuse() -> None:
    card = build_card()
    assert "u(n)=g_s/nu*(h*n-n^2/2)" in card["mechanism"]["steady_prediction"]
    assert "no inlet/outlet" in card["physical_contract"]["domain"]["boundary"]
    assert card["independence_review"]["not_a_parameter_rename"]
    assert card["error_gates"]["U_ref_definition"].startswith("U_ref=")
    assert card["physical_contract"]["free_surface_speed_max_m_s"] > card["physical_contract"]["mean_speed_max_m_s"]


def test_f9_does_not_mutate_core_controls() -> None:
    controls = build_card()["execution_controls"]
    assert controls["definition_written"] is False
    assert controls["gencase_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["registry_mutation"] == 0
    assert controls["denominator_mutation"] == 0


def test_committed_f9_card_is_hash_bound_and_unqualified() -> None:
    assert OUTPUT.is_file()
    card = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert card["status"] == "proposal_only_root_review_required"
    assert len(card["evidence"]) == 10
    assert all(item["sha256"] for item in card["evidence"])
