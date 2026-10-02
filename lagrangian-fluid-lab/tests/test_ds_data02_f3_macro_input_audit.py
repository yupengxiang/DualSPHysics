from pathlib import Path

import h5py
import numpy as np

from scripts.ds_data02_f3_macro_input_audit import audit_many, audit_input


def _write(path: Path, *, bad: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=np.array([0.0, 1.0]))
        h5.create_dataset("initial_type", data=np.array([0, 3, 3], dtype=np.int8))
        h5.create_dataset("valid", data=np.ones((2, 3), dtype=np.bool_))
        mass = np.ones((2, 3), dtype=np.float32)
        position = np.zeros((2, 3, 3), dtype=np.float32)
        velocity = np.zeros((2, 3, 3), dtype=np.float32)
        if bad:
            mass[1, 1] = np.nan
            position[0, 2, 1] = np.nan
            velocity[1, 2, 2] = np.nan
        h5.create_dataset("mass", data=mass)
        h5.create_dataset("position", data=position)
        h5.create_dataset("velocity", data=velocity)


def test_valid_true_nonfinite_rows_fail_closed(tmp_path):
    path = tmp_path / "bad.h5"
    _write(path, bad=True)
    result = audit_input(path, particle_chunk=1)
    assert result["status"] == "failed"
    assert result["counts"]["valid_true_nonfinite_mass"] == 1
    assert result["counts"]["valid_true_nonfinite_position"] == 1
    assert result["counts"]["valid_true_nonfinite_velocity"] == 1
    assert result["bad_examples"]


def test_multiple_actual_inputs_pass_when_all_active_rows_are_finite_positive(tmp_path):
    first = tmp_path / "coarse" / "trajectory.h5"
    second = tmp_path / "fine" / "trajectory.h5"
    _write(first)
    _write(second)
    result = audit_many([first, second], particle_chunk=1)
    assert result["status"] == "pass"
    assert len(result["inputs"]) == 2
    assert all(row["all_valid_true_fluid_rows_finite_positive"] for row in result["inputs"])
