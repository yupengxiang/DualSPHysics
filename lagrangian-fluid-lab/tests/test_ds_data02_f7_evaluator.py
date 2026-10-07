from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import h5py
import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_f7_evaluator import (
    evaluate_f7,
    get_f7_closed_walls,
    get_f7_open_top,
)
from ds_data02_f7_stage8_labels import materialize_f7


def create_f7_obstacle_trajectory(tmp_path: Path) -> tuple[Path, Path]:
    reference = tmp_path / "ref_obstacle.h5"
    candidate = tmp_path / "cand_obstacle.h5"
    with h5py.File(reference, "w") as h:
        h.attrs.update(
            coordinate_frame="DualSPHysics case Cartesian coordinates (x,y,z)",
            geometry_sha256="obstacle_geometry_hash_12345",
            control_sha256="obstacle_control_hash_67890",
        )
        datasets = {
            "time": [0.0, 0.5, 1.0],
            "particle_id": [101, 102],
            "particle_zone": [0, 0],
            "valid": [[1, 1], [1, 1], [1, 1]],
            "type": [[3, 3], [3, 3], [3, 3]],
            "mass": [[2.5, 7.5], [2.5, 7.5], [2.5, 7.5]],
            "position": [
                [[-0.20, 0.0, 0.20], [0.20, 0.0, 0.20]],
                [[-0.10, 0.01, 0.22], [0.15, -0.01, 0.21]],
                [[0.05, 0.02, 0.25], [0.10, -0.02, 0.23]],
            ],
            "velocity": [
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                [[0.20, 0.02, 0.04], [-0.10, -0.02, 0.02]],
                [[0.30, 0.02, 0.06], [-0.10, -0.02, 0.04]],
            ],
        }
        for name, data in datasets.items():
            h.create_dataset(name, data=data)

    shutil.copyfile(reference, candidate)
    return reference, candidate


def create_f7_pump_trajectory(tmp_path: Path) -> tuple[Path, Path]:
    reference = tmp_path / "ref_pump.h5"
    candidate = tmp_path / "cand_pump.h5"
    with h5py.File(reference, "w") as h:
        h.attrs.update(
            coordinate_frame="DualSPHysics case Cartesian coordinates (x,y,z)",
            geometry_sha256="pump_geometry_hash_abcde",
            control_sha256="pump_control_hash_fghij",
        )
        datasets = {
            "time": [0.0, 0.5, 1.0],
            "particle_id": [201, 202],
            "particle_zone": [0, 0],
            "valid": [[1, 1], [1, 1], [1, 1]],
            "type": [[3, 3], [3, 3], [3, 3]],
            "mass": [[1.2, 3.8], [1.2, 3.8], [1.2, 3.8]],
            "position": [
                [[-0.05, -0.35, -0.70], [0.05, -0.10, -0.50]],
                [[-0.03, -0.28, -0.65], [0.06, -0.08, -0.48]],
                [[-0.01, -0.22, -0.60], [0.07, -0.06, -0.46]],
            ],
            "velocity": [
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                [[0.04, 0.14, 0.10], [0.02, 0.04, 0.04]],
                [[0.04, 0.12, 0.10], [0.02, 0.04, 0.04]],
            ],
        }
        for name, data in datasets.items():
            h.create_dataset(name, data=data)

    shutil.copyfile(reference, candidate)
    return reference, candidate


def test_f7_obstacle_self_comparison_and_condition_binding(tmp_path: Path):
    r, c = create_f7_obstacle_trajectory(tmp_path)
    res = evaluate_f7(r, r, mechanism="moving_obstacle_exchange")
    assert res["valid"] is True
    assert res["failures"] == []
    assert res["position_error_per_initial_mass"] == [0.0, 0.0, 0.0]
    assert res["velocity_error_per_initial_mass"] == [0.0, 0.0, 0.0]
    assert res["model_invoked"] is False
    assert res["containment_compliant"] is True
    assert res["mechanism"] == "moving_obstacle_exchange"

    # Mutate condition
    with h5py.File(c, "r+") as h:
        h.attrs["control_sha256"] = "different_control"
    res_mismatch = evaluate_f7(r, c, mechanism="moving_obstacle_exchange")
    assert not res_mismatch["valid"]
    assert "condition_mismatch:control_sha256" in res_mismatch["failures"]


def test_f7_pump_self_comparison_and_condition_binding(tmp_path: Path):
    r, c = create_f7_pump_trajectory(tmp_path)
    res = evaluate_f7(r, r, mechanism="pump_recirculation")
    assert res["valid"] is True
    assert res["failures"] == []
    assert res["position_error_per_initial_mass"] == [0.0, 0.0, 0.0]
    assert res["velocity_error_per_initial_mass"] == [0.0, 0.0, 0.0]
    assert res["model_invoked"] is False
    assert res["containment_compliant"] is True
    assert res["mechanism"] == "pump_recirculation"

    # Missing condition binding
    with h5py.File(c, "r+") as h:
        del h.attrs["geometry_sha256"]
    res_missing = evaluate_f7(r, c, mechanism="pump_recirculation")
    assert not res_missing["valid"]
    assert "missing_condition_binding:geometry_sha256" in res_missing["failures"]


def test_f7_saved_time_mismatch(tmp_path: Path):
    r, c = create_f7_obstacle_trajectory(tmp_path)
    with h5py.File(c, "r+") as h:
        h["time"][2] = 1.05
    res = evaluate_f7(r, c, mechanism="moving_obstacle_exchange")
    assert not res["valid"]
    assert res["failures"] == ["saved_time_mismatch"]


def test_f7_missing_mass_negative_mass_and_nonfinite(tmp_path: Path):
    r, c = create_f7_obstacle_trajectory(tmp_path)
    with h5py.File(c, "r+") as h:
        h["valid"][1, 1] = 0  # Particle 102 inactive at t=1
    res = evaluate_f7(r, c, mechanism="moving_obstacle_exchange")
    assert not res["valid"]
    assert "missing_reference_mass" in res["failures"]
    assert res["missing_reference_mass_fraction"][1] == 0.75  # 7.5 / 10.0

    # Invalidate candidate mass and position
    with h5py.File(c, "r+") as h:
        h["valid"][1, 1] = 1
        h["mass"][1, 1] = -5.0
        h["position"][1, 0] = [np.nan, 0.0, 0.0]
    res2 = evaluate_f7(r, c, mechanism="moving_obstacle_exchange")
    assert not res2["valid"]
    assert "invalid_candidate_mass" in res2["failures"]
    assert "nonfinite_candidate_state" in res2["failures"]
    assert res2["unknown_reference_mass_fraction"][1] == 1.0


def test_f7_obstacle_closed_wall_crossing(tmp_path: Path):
    r, c = create_f7_obstacle_trajectory(tmp_path)
    # Particle crosses tank bottom z=0 (starts at z=0.20, moves to z=-0.05 at t=1)
    with h5py.File(c, "r+") as h:
        h["position"][1, 0] = [-0.10, 0.0, -0.05]
    res = evaluate_f7(r, c, mechanism="moving_obstacle_exchange")
    assert res["finite_wall_crossing_count"] >= 1
    assert "finite_closed_wall_crossing" in res["failures"]


def test_f7_obstacle_open_top_containment_violation(tmp_path: Path):
    r, c = create_f7_obstacle_trajectory(tmp_path)
    # Particle crosses z=1.80 (open top exit)
    with h5py.File(c, "r+") as h:
        h["position"][1, 0] = [-0.10, 0.0, 1.85]
    res = evaluate_f7(r, c, mechanism="moving_obstacle_exchange")
    assert res["open_top_exit_count"] >= 1
    assert res["containment_compliant"] is False
    assert "containment_violation:open_top_exit" in res["failures"]


def test_f7_pump_closed_casing_exit(tmp_path: Path):
    r, c = create_f7_pump_trajectory(tmp_path)
    # Particle escapes through casing top z > -0.07
    with h5py.File(c, "r+") as h:
        h["position"][1, 0] = [-0.05, -0.35, 0.05]
    res = evaluate_f7(r, c, mechanism="pump_recirculation")
    assert res["open_top_exit_count"] >= 1
    assert res["containment_compliant"] is False
    assert "containment_violation:open_top_exit" in res["failures"]


def test_f7_materialize_labels_and_cyclic_recrossings(tmp_path: Path):
    source, _ = create_f7_obstacle_trajectory(tmp_path)
    output = tmp_path / "native-labels.h5"
    config = {
        "schema": "ds-data-02.static-event-config.v1",
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "physical_mechanism": "moving_obstacle_exchange",
        "source_assignment": "initial_regions",
        "source_regions": [
            {"id": "left_half", "bounds": [[-0.60, 0.0], [-0.40, 0.40], [0.0, 0.60]]},
            {"id": "right_half", "bounds": [[0.0, 0.60], [-0.40, 0.40], [0.0, 0.60]]},
        ],
        "destination_regions": [
            {"id": "left_half", "bounds": [[-0.60, 0.0], [-0.40, 0.40], [0.0, 0.60]]},
            {"id": "right_half", "bounds": [[0.0, 0.60], [-0.40, 0.40], [0.0, 0.60]]},
        ],
        "events": [
            {"id": "midplane", "axis": 0, "value": 0.0, "aperture_bounds": [[-0.40, 0.40], [0.0, 0.60]]}
        ],
    }

    res = materialize_f7(source, output, config, particle_chunk=2)
    assert res["initial_fluid_mass_kg"] == 10.0
    assert res["fluid_particles"] == 2
    assert res["frames"] == 3

    with h5py.File(output, "r") as h:
        assert h.attrs["schema"] == "ds02.f7.native-event-labels.v1"
        assert h.attrs["standard_schema"] == "ds-data-02.native-labels.v1"
        assert bool(h.attrs["complete"]) is True
        assert bool(h.attrs["model_invoked"]) is False

        # Particle 101 starts at x = -0.20, moves to -0.10 at t=0.5, then +0.05 at t=1.0 -> crosses x=0 between t=0.5 and t=1.0!
        assert h["source_zone"][0] == 1  # left_half
        assert h["source_zone"][1] == 2  # right_half
        assert not np.isnan(h["first_crossing_time_s"][0, 0])
        assert h["first_passage_censor"][0, 0] == 0
        assert h["first_passage_censor"][1, 0] == 1  # Particle 102 stayed on right side

        assert h["total_crossing_count"][0, 0] == 1
        assert h["cyclic_recrossing_count"][0, 0] == 0  # 1 crossing = 0 recrossings beyond the first
        assert h["residence_time_s"].shape == (2, 2)
