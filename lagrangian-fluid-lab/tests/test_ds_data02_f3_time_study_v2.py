import math
from pathlib import Path

import h5py
import numpy as np

from scripts import ds_data02_f3_time_study_v2 as study


def _h5(path: Path, *, offset: float = 0.0, invalid_second: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    times = np.array([0.0, 5.0, 10.0])
    position = np.zeros((3, 5, 3), dtype=np.float64)
    position[:, 1, 0] = np.array([0.0, 0.5, 1.0]) + offset
    position[:, 2, 0] = np.array([1.0, 1.5, 2.0]) + offset
    position[:, 3, 0] = np.array([2.0, 2.5, 3.0]) + offset
    velocity = np.zeros_like(position)
    velocity[:, 1, 0] = 0.1
    velocity[:, 2, 0] = 0.2
    velocity[:, 3, 0] = 0.3
    valid = np.ones((3, 5), dtype=np.bool_)
    if invalid_second:
        valid[:, 2] = False
        position[:, 2, :] = np.nan
        velocity[:, 2, :] = np.nan
        # A nonfinite payload in an inactive row must not enter weighted sums.
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("initial_type", data=np.array([0, 3, 3, 3, 0], dtype=np.int8))
        handle.create_dataset("initial_mass", data=np.full(5, 0.5))
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("mass", data=np.full((3, 5), 0.5))
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)


def test_v2_keeps_same_named_variants_under_unique_source_keys(tmp_path):
    baseline = tmp_path / "baseline" / "trajectory.h5"
    coarse = tmp_path / "coarse" / "trajectory.h5"
    fine = tmp_path / "fine" / "trajectory.h5"
    output = tmp_path / "comparison.json"
    _h5(baseline)
    _h5(coarse, offset=0.1)
    _h5(fine, offset=0.2)

    result = study.compare_fixed_window(type("Args", (), {
        "baseline": baseline, "variant": [coarse, fine], "grid_step": 2.5, "output": output,
    })())

    rows = result["comparisons"]
    assert len(rows) == 2
    assert {row["source_path"] for row in rows.values()} == {str(coarse.resolve()), str(fine.resolve())}
    assert len({row["source_key"] for row in rows.values()}) == 2
    assert result["schema"].endswith(".v2")


def test_v2_filters_inactive_nonfinite_rows_before_weighted_arithmetic(tmp_path):
    path = tmp_path / "trajectory.h5"
    _h5(path, invalid_second=True)
    with h5py.File(path, "r") as handle:
        times, series = study._macro_series_v2(path)

    assert times[-1] == 10.0
    assert np.isfinite(series["active_mass_kg"]).all()
    assert np.isfinite(series["com_x_m"]).all()
    assert np.isfinite(series["kinetic_energy_j"]).all()
    # Two valid fluid particles remain, so the inactive NaN row is excluded.
    assert np.allclose(series["active_mass_kg"], 1.0)
    assert math.isclose(series["com_x_m"][0], 1.0, rel_tol=0.0, abs_tol=1e-12)

