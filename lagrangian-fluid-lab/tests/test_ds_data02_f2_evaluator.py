from pathlib import Path
import shutil
import sys

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from ds_data02_f2_evaluator import evaluate_f2


def create_f2_trajectory(tmp_path: Path):
    reference = tmp_path / "ref_f2.h5"
    candidate = tmp_path / "cand_f2.h5"
    with h5py.File(reference, "w") as h:
        h.attrs.update(
            coordinate_frame="DualSPHysics case Cartesian coordinates (x,y,z)",
            geometry_sha256="f2_geometry_hash_12345",
            control_sha256="f2_control_hash_67890",
        )
        datasets = {
            "time": [0.0, 0.5, 1.0],
            "particle_id": [101, 102],
            "particle_zone": [0, 0],
            "valid": [[1, 1], [1, 1], [1, 1]],
            "type": [[3, 3], [3, 3], [3, 3]],
            "mass": [[2.5, 7.5], [2.5, 7.5], [2.5, 7.5]],
            "position": [
                [[0.10, 0.0, 0.70], [0.20, 0.0, 0.70]],
                [[0.12, 0.01, 0.68], [0.22, -0.01, 0.68]],
                [[0.15, 0.02, 0.65], [0.25, -0.02, 0.65]],
            ],
            "velocity": [
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
                [[0.04, 0.02, -0.04], [0.04, -0.02, -0.04]],
                [[0.06, 0.02, -0.06], [0.06, -0.02, -0.06]],
            ],
        }
        for name, data in datasets.items():
            h.create_dataset(name, data=data)

    shutil.copyfile(reference, candidate)
    return reference, candidate


def test_f2_self_comparison_and_condition_binding(tmp_path):
    r, c = create_f2_trajectory(tmp_path)
    res = evaluate_f2(r, r, mechanism="center_catch")
    assert res["valid"]
    assert res["failures"] == []
    assert res["metrics"]["max_position_error_per_mass"] == 0.0
    assert res["metrics"]["max_velocity_error_per_mass"] == 0.0
    assert res["model_invoked"] is False
    assert res["checks"]["containment_compliant"] is True

    # Mutate condition
    with h5py.File(c, "r+") as h:
        h.attrs["control_sha256"] = "different_control"
    res_mismatch = evaluate_f2(r, c)
    assert not res_mismatch["valid"]
    assert "condition_mismatch:control_sha256" in res_mismatch["failures"]


def test_f2_saved_time_mismatch(tmp_path):
    r, c = create_f2_trajectory(tmp_path)
    with h5py.File(c, "r+") as h:
        h["time"][2] = 1.05
    res = evaluate_f2(r, c)
    assert not res["valid"]
    assert res["failures"] == ["saved_time_mismatch"]


def test_f2_missing_reference_mass(tmp_path):
    r, c = create_f2_trajectory(tmp_path)
    with h5py.File(c, "r+") as h:
        h["valid"][1, 1] = 0  # Particle 102 inactive at t=1
    res = evaluate_f2(r, c)
    assert not res["valid"]
    assert "missing_reference_mass:frame_1" in res["failures"]


def test_f2_closed_wall_crossing(tmp_path):
    r, c = create_f2_trajectory(tmp_path)
    # Particle crosses basin floor at z=-0.20 (starts at z=0.70, moves to z=-0.25 at t=1)
    with h5py.File(c, "r+") as h:
        h["position"][1, 0] = [0.10, 0.0, -0.25]
    res = evaluate_f2(r, c, mechanism="center_catch")
    assert not res["valid"]
    assert any("finite_closed_wall_crossing" in f for f in res["failures"])
