from scripts.w07_mechanism_screen import FAMILY_SPECS, assert_design, build_family_cards


def test_w07_design_is_deterministic_and_valid():
    first = [card for family in FAMILY_SPECS for card in build_family_cards(family)]
    second = [card for family in FAMILY_SPECS for card in build_family_cards(family)]
    assert first == second
    assert_design(first)


def test_w07_negative_controls_override_lhs_values():
    for family, spec in FAMILY_SPECS.items():
        card = build_family_cards(family)[0]
        assert card["design_role"] == "negative_control"
        for key, value in spec["negative_control"].items():
            assert card["physics"][key] == value
