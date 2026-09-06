from scripts.w08_generalization_design import STUDIES, audit, build_cards


def test_w08_design_is_deterministic_and_leak_free():
    first = build_cards()
    second = build_cards()
    assert first == second
    result = audit(first)
    assert result["cards"] == 204
    assert result["cross_split_signature_leakage"] == {}


def test_w08_has_two_single_axis_and_one_joint_study_per_family():
    cards = build_cards()
    for family, definition in STUDIES.items():
        ids = {card["study_id"] for card in cards if card["family"] == family}
        assert len(ids) == 3
        assert all(f"W08_{family}_single_{axis}" in ids for axis in definition["single_axes"])
        assert any("_joint_" in study_id for study_id in ids)
