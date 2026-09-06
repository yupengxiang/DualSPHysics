from __future__ import annotations

import h5py
import numpy as np

from scripts.passive_tracers import advect_hdf5, shepard_velocity


def test_shepard_reproduces_uniform_velocity():
    particles = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
    velocity = np.repeat([[2.0, -1.0, 0.5]], 4, axis=0)
    interpolated, support = shepard_velocity([[0.3, 0.4, 0]], particles, velocity,
                                              neighbours=4, regularization=0.01)
    np.testing.assert_allclose(interpolated, [[2.0, -1.0, 0.5]])
    assert support[0] > 0


def test_heun_advects_uniform_field(tmp_path):
    path = tmp_path / "uniform.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 0.5, 1.0])
        h5.create_dataset("valid", data=np.ones((3, 4), dtype=bool))
        h5.create_dataset("type", data=np.full((3, 4), 3))
        position = np.repeat(np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]]), 3, axis=0)
        h5.create_dataset("position", data=position)
        velocity = np.repeat(np.array([[[0.2, 0.0, 0.0]] * 4]), 3, axis=0)
        h5.create_dataset("velocity", data=velocity)
    traced = advect_hdf5(path, [[0.3, 0.4, 0]], neighbours=4, regularization=0.01)
    np.testing.assert_allclose(traced["position"][-1], [[0.5, 0.4, 0]], atol=1e-12)
