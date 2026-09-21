from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts.f2_h2_mdbc_static_range_v5_observer import observe


LAB = Path(__file__).resolve().parents[1]
PREPARED = LAB / (
    "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
    "runtime-batch8-v3/cell00/prepared.json"
)


def _trajectory(path: Path, *, escape: bool = False) -> None:
    nframe, n = 31, 4
    times = np.linspace(0.0, 0.6, nframe)
    position = np.zeros((nframe, n, 3), dtype=np.float64)
    position[:, :, 0] = 0.1
    position[:, :, 1] = -0.05
    position[:, :, 2] = 0.8
    if escape:
        position[-1, 0, 2] = 1.2
    velocity = np.zeros_like(position)
    mass = np.full((nframe, n), 1.0, dtype=np.float64)
    valid = np.ones((nframe, n), dtype=np.bool_)
    particle_id = np.arange(n, dtype=np.uint32)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("mass", data=mass)
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("particle_id", data=particle_id)


def test_static_hold_observer_accepts_closed_zero_motion(tmp_path: Path) -> None:
    trajectory = tmp_path / "trajectory.h5"
    _trajectory(trajectory)
    result = observe(PREPARED, trajectory)
    assert result["hard_integrity_pass"] is True
    assert result["static_settled"] is True
    assert result["event_window_complete"] is True
    assert result["matrix_credit"] == 0
    assert result["registry_mutation"] == 0
    assert result["ledger_mutation"] == 0


def test_static_hold_observer_rejects_open_escape(tmp_path: Path) -> None:
    trajectory = tmp_path / "trajectory.h5"
    _trajectory(trajectory, escape=True)
    result = observe(PREPARED, trajectory)
    assert result["hard_integrity_pass"] is False
    assert result["event_window_complete"] is False
    assert result["hard_checks"]["no_open_cup_escape"] is False
