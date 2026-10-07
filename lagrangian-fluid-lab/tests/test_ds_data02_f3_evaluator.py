from pathlib import Path
import shutil
import sys

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from ds_data02_f3_evaluator import evaluate_f3


def create_f3_trajectory(tmp_path: Path):
    reference = tmp_path / "ref_f3.h5"
    candidate = tmp_path / "cand_f3.h5"
    with h5py.File(reference, "w") as h:
        h.attrs.update(
            coordinate_frame="DualSPHysics case Cartesian coordinates (x,y,z)",
            geometry_sha256="f3_geometry_hash_12345",
            control_sha256="f3_control_hash_67890",
        )
        datasets = {
            "time": [0.0, 0.5, 1.0],
            "particle_id": [101, 102],
            "particle_zone": [0, 0],
            "valid": [[1, 1], [1, 1], [1, 1]],
            "type": [[3, 3], [3, 3], [3, 3]],
            "mass": [[2.5, 7.5], [2.5, 7.5], [2.5, 7.5]],
            "position": [
                [[-0.10, 0.0, 0.10], [0.10, 0.0, 0.10]],
                [[-0.08, 0.01, 0.12], [0.12, -0.01, 0.11]],
                [[-0.05, 0.02, 0.15], [0.15, -0.02, 0.13]],
            ],
            "velocity": [
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                [[0.04, 0.02, 0.04], [0.04, -0.02, 0.02]],
                [[0.06, 0.02, 0.06], [0.06, -0.02, 0.04]],
            ],
        }
        for name, data in datasets.items():
            h.create_dataset(name, data=data)

    shutil.copyfile(reference, candidate)
    return reference, candidate


def test_f3_self_comparison_and_condition_binding(tmp_path):
    r, c = create_f3_trajectory(tmp_path)
    res = evaluate_f3(r, r, mechanism="dual_axis_phase")
    assert res["valid"]
    assert res["failures"] == []
    assert res["position_error_per_initial_mass"] == [0.0, 0.0, 0.0]
    assert res["velocity_error_per_initial_mass"] == [0.0, 0.0, 0.0]
    assert res["model_invoked"] is False
    assert res["containment_compliant"] is True

    # Mutate condition
    with h5py.File(c, "r+") as h:
        h.attrs["control_sha256"] = "different_control"
    res_mismatch = evaluate_f3(r, c)
    assert not res_mismatch["valid"]
    assert "condition_mismatch:control_sha256" in res_mismatch["failures"]


def test_f3_saved_time_mismatch(tmp_path):
    r, c = create_f3_trajectory(tmp_path)
    with h5py.File(c, "r+") as h:
        h["time"][2] = 1.05
    res = evaluate_f3(r, c)
    assert not res["valid"]
    assert res["failures"] == ["saved_time_mismatch"]


def test_f3_missing_mass_negative_mass_and_nonfinite(tmp_path):
    r, c = create_f3_trajectory(tmp_path)
    with h5py.File(c, "r+") as h:
        h["valid"][1, 1] = 0  # Particle 102 inactive at t=1
    res = evaluate_f3(r, c)
    assert not res["valid"]
    assert "missing_reference_mass" in res["failures"]
    assert res["missing_reference_mass_fraction"][1] == 0.75  # 7.5 / 10.0

    # Invalidate candidate mass and position
    with h5py.File(c, "r+") as h:
        h["valid"][1, 1] = 1
        h["mass"][1, 1] = -5.0
        h["position"][1, 0] = [np.nan, 0.0, 0.0]
    res2 = evaluate_f3(r, c)
    assert not res2["valid"]
    assert "invalid_candidate_mass" in res2["failures"]
    assert "nonfinite_candidate_state" in res2["failures"]
    assert res2["unknown_reference_mass_fraction"][1] == 1.0


def test_f3_closed_wall_crossing(tmp_path):
    r, c = create_f3_trajectory(tmp_path)
    # Particle crosses tank bottom z=0 (starts at z=0.10, moves to z=-0.05 at t=1)
    with h5py.File(c, "r+") as h:
        h["position"][1, 0] = [-0.10, 0.0, -0.05]
    res = evaluate_f3(r, c, mechanism="dual_axis_phase")
    assert res["finite_wall_crossing_count"] >= 1
    assert "finite_closed_wall_crossing" in res["failures"]


def test_f3_open_top_containment_violation(tmp_path):
    r, c = create_f3_trajectory(tmp_path)
    # Particle crosses z=0.51 (open top exit)
    with h5py.File(c, "r+") as h:
        h["position"][1, 0] = [-0.10, 0.0, 0.55]
    res = evaluate_f3(r, c, mechanism="dual_axis_phase")
    assert res["open_top_exit_count"] >= 1
    assert res["containment_compliant"] is False
    assert "containment_violation:open_top_exit" in res["failures"]
