from pathlib import Path

import h5py
import numpy as np

from scripts.ds_data02_f3_macro_input_audit_v2 import _contiguous_spans, audit_many, audit_input


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


def test_v2_uses_contiguous_identity_spans_and_preserves_bad_rows(tmp_path):
    assert _contiguous_spans(np.array([1, 2, 5, 8, 9])) == [(1, 3), (5, 6), (8, 10)]
    path = tmp_path / "bad-v2.h5"
    _write(path, bad=True)
    result = audit_input(path, particle_chunk=2)
    assert result["read_strategy"] == "contiguous_hyperslab_slices_over_sorted_initial_fluid_axis"
    assert result["contiguous_identity_spans"] == [[1, 3]]
    assert result["status"] == "failed"
    assert result["counts"]["valid_true_nonfinite_mass"] == 1
