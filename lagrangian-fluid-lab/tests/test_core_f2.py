from pathlib import Path

import pytest

from scripts.core_f2 import (
    CASE_ID,
    RETENTION_MIN,
    _nearest_native_box,
    prepare_static_hold,
    static_config,
)


def test_f2_static_hold_registration_is_zero_motion_and_unqualified():
    config = static_config()
    assert config["family"] == "F2"
    assert config["parameter"]["value"] == 0.0
    assert config["hold_gate"]["cup_retention_mass_fraction_min"] == RETENTION_MIN
    assert config["qualification_claim"] == "none"
    sample = _nearest_native_box(config["fluid_boxes"][0], config["dp_m"])
    assert sample["particle_count"] == 18705
    assert sample["discrete_mass_kg"] / sample["continuous_mass_kg"] - 1.0 == pytest.approx(.00332763827)


def test_f2_static_hold_cpu_preflight_materializes_native_case(tmp_path):
    lab = Path(__file__).resolve().parents[1]
    prepared = prepare_static_hold(lab, tmp_path / "f2-static")
    assert prepared["config"]["case_id"] == CASE_ID
    assert prepared["preflight_pass"] is True
    assert prepared["static_hold_preflight"]["motion_file_zero_and_finite"] is True
    assert prepared["static_hold_preflight"]["mass_gate"] is True
    assert prepared["native_initial"]["fluid_particles"] == 56115
