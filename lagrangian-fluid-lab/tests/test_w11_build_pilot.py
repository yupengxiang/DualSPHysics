from pathlib import Path

import h5py
import numpy as np

from scripts.w11_build_pilot import audit_case


def test_pilot_audit_accepts_closed_finite_case(tmp_path: Path):
    path = tmp_path / "tiny.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 0.1])
        h5.create_dataset("particle_id", data=[1, 2])
        h5.create_dataset("particle_zone", data=[0, 0])
        h5.create_dataset("valid", data=np.ones((2, 2), dtype=bool))
        for name in ("position", "velocity"):
            h5.create_dataset(name, data=np.zeros((2, 2, 3)))
        for name in ("density", "pressure", "mass"):
            h5.create_dataset(name, data=np.ones((2, 2)))
        for name in ("type", "mk"):
            h5.create_dataset(name, data=np.ones((2, 2), dtype=np.int16))
    result = audit_case(path, {"case_id": "tiny"})
    assert result["numerical_loss_fraction"] == 0
    assert result["frames"] == 2
