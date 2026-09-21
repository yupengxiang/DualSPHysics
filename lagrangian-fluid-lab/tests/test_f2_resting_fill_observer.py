import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.core_f2_resting_fill import observe_static_hold


LAB = Path(__file__).resolve().parents[1]


def _prepared(path: Path, count: int = 4) -> Path:
    prepared = {
        "config": {
            "case_id": "fixture",
            "cup": {"low": [0.0, -0.15, 0.65], "size": [0.425, 0.3, 0.45]},
            "runtime_domain": {"posmin": [-0.7, -0.65, -0.4], "posmax": [2.2, 0.8, 1.8]},
        },
        "sampling": {"expected_fluid_particles": count},
        "static_preflight": {
            "generated_particle_groups": {
                "fluid": [{"begin": 100, "count": count}],
            },
        },
    }
    path.write_text(json.dumps(prepared))
    return path


def _trajectory(path: Path, *, times=(0.0, 0.2, 0.4, 0.6), lost_frame=None,
                wall_frame=None, transient_frame=None, spill_frame=None) -> Path:
    nt = len(times)
    n = 4
    ids = np.arange(100, 100 + n, dtype=np.uint32)
    positions = np.tile(np.asarray([[0.1, -0.05, 0.8], [0.2, -0.05, 0.8],
                                    [0.1, 0.05, 0.8], [0.2, 0.05, 0.8]], dtype=float), (nt, 1, 1))
    velocities = np.zeros((nt, n, 3), dtype=np.float32)
    density = np.full((nt, n), 1000.0, dtype=np.float32)
    pressure = np.zeros((nt, n), dtype=np.float32)
    mass = np.full((nt, n), 0.001, dtype=np.float32)
    valid = np.ones((nt, n), dtype=bool)
    if lost_frame is not None:
        valid[lost_frame, 0] = False
        mass[lost_frame:, 0] = np.nan
        positions[lost_frame:, 0] = np.nan
        velocities[lost_frame:, 0] = np.nan
        density[lost_frame:, 0] = np.nan
        pressure[lost_frame:, 0] = np.nan
    if wall_frame is not None:
        positions[wall_frame, 0, 0] = -0.01
    if transient_frame is not None:
        velocities[transient_frame, :, 0] = 0.2
    if spill_frame is not None:
        positions[spill_frame, 0, 2] = 1.2
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=np.asarray(times, dtype=float))
        handle.create_dataset("particle_id", data=ids)
        handle.create_dataset("position", data=positions)
        handle.create_dataset("velocity", data=velocities)
        handle.create_dataset("density", data=density)
        handle.create_dataset("pressure", data=pressure)
        handle.create_dataset("mass", data=mass)
        handle.create_dataset("valid", data=valid)
    return path


def test_all_retained_zero_velocity_reaches_final_settled_hold(tmp_path):
    observations = observe_static_hold(_prepared(tmp_path / "prepared.json"), _trajectory(tmp_path / "trajectory.h5"))
    assert observations["native_axis_exact"] is True
    assert observations["minimum_cup_retention_mass_fraction"] == 1.0
    assert observations["native_missing_count_max"] == 0
    assert observations["native_axis_particle_count"] == 4
    assert observations["native_axis_exact"] is True
    assert observations["hard_integrity_pass"] is True
    assert observations["static_settled"] is True
    assert observations["event_window_complete"] is True
    assert observations["center_of_mass_m"][0] == [0.15, 0.0, 0.8]


def test_midrun_loss_fails_identity_and_mass_gates(tmp_path):
    observations = observe_static_hold(
        _prepared(tmp_path / "prepared.json"), _trajectory(tmp_path / "trajectory.h5", lost_frame=2)
    )
    assert observations["no_unexpected_native_ids"] is True
    assert observations["hard_checks"]["no_missing_native_ids"] is False
    assert observations["hard_checks"]["native_mass_unchanged"] is False
    assert observations["minimum_cup_retention_mass_fraction"] == 0.75
    assert observations["hard_integrity_pass"] is False


def test_closed_wall_endpoint_and_saved_chord_are_hard_failures(tmp_path):
    observations = observe_static_hold(
        _prepared(tmp_path / "prepared.json"), _trajectory(tmp_path / "trajectory.h5", wall_frame=1)
    )
    assert observations["cup_closed_wall_endpoint_particle_frames"] > 0
    assert observations["cup_saved_chord_crossings"] > 0
    assert observations["hard_checks"]["no_cup_closed_wall_endpoint_penetrations"] is False
    assert observations["hard_checks"]["no_cup_saved_chord_crossings"] is False
    assert observations["hard_integrity_pass"] is False


def test_transient_low_speed_does_not_claim_final_settling(tmp_path):
    observations = observe_static_hold(
        _prepared(tmp_path / "prepared.json"), _trajectory(tmp_path / "trajectory.h5", transient_frame=2)
    )
    assert observations["maximum_speed_p95_m_s"] == pytest.approx(0.2)
    assert observations["static_settled"] is False
    assert observations["event_window_complete"] is False


def test_short_window_and_zero_speed_spill_do_not_pass(tmp_path):
    short = observe_static_hold(
        _prepared(tmp_path / "prepared-short.json"),
        _trajectory(tmp_path / "trajectory-short.h5", times=(0.0, 0.2, 0.4)),
    )
    assert short["static_settled"] is True
    assert short["requested_horizon_reached"] is False
    assert short["event_window_complete"] is False

    spill = observe_static_hold(
        _prepared(tmp_path / "prepared-spill.json"),
        _trajectory(tmp_path / "trajectory-spill.h5", spill_frame=1),
    )
    assert spill["maximum_speed_p95_m_s"] == 0.0
    assert spill["maximum_outside_cup_mass_fraction"] == 0.25
    assert spill["hard_checks"]["no_open_cup_escape"] is False
    assert spill["hard_checks"]["no_open_top_saved_chord_crossings"] is False
    assert spill["event_window_complete"] is False
