from __future__ import annotations

import json

from scripts.f2_h2_mdbc_static_range_prepare import _draw_extent, _sampling_for_cell


def test_gencase_endpoint_guards_are_minimal_and_targeted() -> None:
    z_extent, z_guard = _draw_extent("z", 11, 0.01)
    y_extent, y_guard = _draw_extent("y", 44, 0.005)
    ordinary, ordinary_guard = _draw_extent("x", 43, 0.0075)

    assert z_extent > 0.1
    assert z_guard > 0.0
    assert y_extent < 0.215
    assert y_guard < 0.0
    assert ordinary == (43 - 1) * 0.0075
    assert ordinary_guard == 0.0


def test_sampling_records_endpoint_guards_without_changing_continuous_contract() -> None:
    with open("campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-candidate-v2.json") as stream:
        card = json.load(stream)
    cells = card["qualification_design"]["cells"]

    dp01 = _sampling_for_cell(cells[0], card)
    dp005 = _sampling_for_cell(cells[2], card)
    q0_dp01 = _sampling_for_cell(cells[0], card)
    q05_dp01 = _sampling_for_cell(cells[3], card)
    q075_dp0075 = _sampling_for_cell(cells[11], card)

    assert dp01["continuous_size_m"][0:2] == [0.325, 0.22]
    assert dp01["continuous_size_m"][-1] > 0.3
    assert dp005["continuous_size_m"][1] == 0.22
    assert dp01["fluid_boxes"][0]["drawbox_endpoint_guard_m"][2] > 0.0
    assert dp005["fluid_boxes"][0]["drawbox_endpoint_guard_m"][1] < 0.0
    assert dp01["mass_policy"] == "native rho*dp^3; no mass rescaling"
    assert q0_dp01["selected_third_layer_count"] == 10
    assert q05_dp01["selected_third_layer_count"] == 11
    assert q075_dp0075["selected_third_layer_count"] == 16
