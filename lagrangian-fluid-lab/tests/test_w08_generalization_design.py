import pytest

from scripts.protocol_metrics import validate_split_lineage
from scripts.w08_generalization_design import STUDIES, audit, build_cards, topology_holdout_cards


def test_w08_design_is_deterministic_and_leak_free():
    first = build_cards()
    second = build_cards()
    assert first == second
    result = audit(first)
    assert result["cards"] == 204
    assert result["cross_split_signature_leakage"] == {}
    assert result["cross_split_physical_case_leakage"] == {}
    assert result["cross_split_lineage_leakage"] == {}
    assert result["physical_case_count"] == result["unique_execution_units"] == 196
    assert result["paired_background_count"] == 4
    validate_split_lineage(first)


def test_w08_identity_namespaces_are_distinct_and_background_is_explicitly_shared():
    cards = build_cards()
    assert all(card["study_id"] != card["paired_background_id"] for card in cards)
    assert all(card["physical_case_id"] != card["lineage_group_id"] for card in cards)
    for family in STUDIES:
        family_cards = [card for card in cards if card["family"] == family]
        assert len({card["paired_background_id"] for card in family_cards}) == 1
        assert len({card["study_id"] for card in family_cards}) == 3


def test_w08_rejects_same_physical_case_in_different_splits():
    cards = build_cards()
    train = next(card for card in cards if card["split"] == "train")
    interpolation = next(card for card in cards if card["split"] == "interpolation")
    interpolation["physical_case_id"] = train["physical_case_id"]
    # Keep a distinct lineage label to exercise the independent physical-case
    # check rather than the lineage check alone.
    interpolation["lineage_group_id"] = "lineage_intentionally_different"
    with pytest.raises(ValueError, match="physical case crosses splits"):
        audit(cards)


def test_w08_has_two_single_axis_and_one_joint_study_per_family():
    cards = build_cards()
    for family, definition in STUDIES.items():
        ids = {card["study_id"] for card in cards if card["family"] == family}
        assert len(ids) == 3
        assert all(f"W08_{family}_single_{axis}" in ids for axis in definition["single_axes"])
        assert any("_joint_" in study_id for study_id in ids)


def test_topology_holdout_card_is_separate_from_continuous_matrix_and_has_unique_lineage():
    continuous = build_cards()
    topology = topology_holdout_cards()
    assert len(topology) == 4
    assert {card["family"] for card in topology} == {"F1", "F2", "F3", "F6"}
    assert all(card["split"] == "topology_extrapolation" for card in topology)
    assert {card["physics"]["obstacle_topology"] for card in topology if card["family"] == "F1"} == {"twin"}
    assert {card["physics"]["mouth_topology"] for card in topology if card["family"] == "F2"} == {"spout"}
    assert {card["physics"]["baffle_topology"] for card in topology if card["family"] == "F3"} == {"perforated_proxy"}
    assert {card["physics"]["body_configuration"] for card in topology if card["family"] == "F6"} == {"twin_free"}
    continuous_ids = {card["card_id"] for card in continuous}
    continuous_physical = {card["physical_case_id"] for card in continuous}
    continuous_lineage = {card["lineage_group_id"] for card in continuous}
    continuous_execution = {card["execution_unit_id"] for card in continuous}
    assert all(card["card_id"] not in continuous_ids for card in topology)
    assert all(card["physical_case_id"] not in continuous_physical for card in topology)
    assert all(card["lineage_group_id"] not in continuous_lineage for card in topology)
    assert all(card["execution_unit_id"] not in continuous_execution for card in topology)
