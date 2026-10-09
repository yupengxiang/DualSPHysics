from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f7_s1_fixed_owner_selector_geometry_v1.py"
SPEC = importlib.util.spec_from_file_location("fixed_owner_selector_geometry_v1", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_axis_cells_use_full_containment_without_target_fit() -> None:
    x = MODULE.axis_cells(-0.55, 0.55)
    y = MODULE.axis_cells(-0.35, 0.35)
    z = MODULE.axis_cells(0.05, 0.482)
    assert (len(x), len(y), len(z)) == (44, 28, 17)
    assert x[0] == pytest.approx((-0.55, -0.5375, -0.525))
    assert z[-1] == pytest.approx((0.45, 0.4625, 0.475))
    assert z[-1][2] < 0.482


def test_positive_volume_paddle_intersection_is_conservative() -> None:
    paddle_low = (-0.07, -0.24, 0.05)
    paddle_high = (-0.01, 0.24, 0.53)
    assert MODULE.cell_hits_paddle(((-0.075, -0.25, 0.05), (-0.05, -0.225, 0.075)), paddle_low, paddle_high)
    # A cell touching only at a face has no positive-volume overlap.
    assert not MODULE.cell_hits_paddle(((0.55, 0.0, 0.0), (0.575, 0.025, 0.025)), (0.575, 0.0, 0.0), (0.6, 0.025, 0.025))


def test_fixed_owner_lattice_is_not_mass_fit() -> None:
    owner = {
        "low": (-0.55, -0.35, 0.05),
        "high": (0.55, 0.35, 0.482),
        "paddle_low": (-0.07, -0.24, 0.05),
        "paddle_high": (-0.01, 0.24, 0.53),
        "owner_mass_kg": 320.1984,
    }
    control = {"paddle_low": owner["paddle_low"], "paddle_high": owner["paddle_high"]}
    result = MODULE.derive_owner_lattice(owner, control)
    assert result["mass_fit_search"] is False
    assert result["target_count_search"] is False
    assert result["axis_dimensions"] == {"x": 44, "y": 28, "z": 17}
    assert result["all_envelope_cells"] == 20944
    assert result["paddle_excluded_cells_center_rule"] == 1020
    assert result["selected_cells_center_rule"] == 19924
    assert result["paddle_excluded_cells_positive_volume_diagnostic"] == 1020
    assert result["selected_cells_positive_volume_diagnostic"] == 19924
    assert result["represented_mass_kg"] == pytest.approx(311.3125)
    assert result["represented_minus_owner_mass_kg"] == pytest.approx(-8.8859)
