from __future__ import annotations

import h5py
import numpy as np
import pytest

from scripts.passive_tracers import (
    advect_hdf5,
    box_surface_triangles,
    rigid_barrier_provider,
    shepard_velocity,
    weighted_stratified_seeds,
)


def make_uniform_h5(path):
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 0.5, 1.0])
        h5.create_dataset("valid", data=np.ones((3, 4), dtype=bool))
        h5.create_dataset("type", data=np.full((3, 4), 3))
        position = np.repeat(np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]]), 3, axis=0)
        h5.create_dataset("position", data=position)
        velocity = np.repeat(np.array([[[0.2, 0.0, 0.0]] * 4]), 3, axis=0)
        h5.create_dataset("velocity", data=velocity)
        h5.create_dataset("mass", data=np.ones((3, 4)))
        h5.create_dataset("mk", data=np.zeros((3, 4), dtype=np.int16))
        h5.create_dataset("particle_id", data=np.arange(4))
        h5.create_dataset("particle_zone", data=np.zeros(4, dtype=np.int16))


def test_shepard_reproduces_uniform_velocity():
    particles = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
    velocity = np.repeat([[2.0, -1.0, 0.5]], 4, axis=0)
    interpolated, support = shepard_velocity([[0.3, 0.4, 0]], particles, velocity,
                                              neighbours=4, regularization=0.01)
    np.testing.assert_allclose(interpolated, [[2.0, -1.0, 0.5]])
    assert support[0] > 0


def test_heun_advects_uniform_field(tmp_path):
    path = tmp_path / "uniform.h5"
    make_uniform_h5(path)
    traced = advect_hdf5(path, [[0.3, 0.4, 0]], neighbours=4, regularization=0.01)
    np.testing.assert_allclose(traced["position"][-1], [[0.5, 0.4, 0]], atol=1e-12)


def test_visibility_filter_rejects_samples_across_wall():
    query = np.asarray([[-0.05, 0.0, 0.0]])
    left = np.column_stack((np.full(12, -0.1), np.linspace(-0.3, 0.3, 12), np.zeros(12)))
    right = np.column_stack((np.full(12, 0.02), np.linspace(-0.3, 0.3, 12), np.zeros(12)))
    positions = np.vstack((left, right))
    velocities = np.vstack((np.tile([0, 1, 0], (12, 1)), np.tile([0, -1, 0], (12, 1))))
    wall = np.asarray([[[0, -1, -1], [0, 1, -1], [0, 1, 1]], [[0, -1, -1], [0, 1, 1], [0, -1, 1]]])
    legacy, _ = shepard_velocity(query, positions, velocities, neighbours=24, regularization=0.001)
    visible, _, count = shepard_velocity(query, positions, velocities, neighbours=24, regularization=0.001,
                                          barrier_triangles=wall, return_diagnostics=True)
    assert abs(legacy[0, 1] - 1) > 0.5
    assert visible[0, 1] == pytest.approx(1.0)
    assert count[0] == 12


def test_finite_wall_leaves_real_gap_visible():
    query = np.asarray([[-0.1, 0.0, 0.0]])
    positions = np.asarray([[0.1, 0.0, 0.0]])
    lower = box_surface_triangles([-0.001, -1, -1], [0.001, -0.2, 1], sides=("xmin",))
    upper = box_surface_triangles([-0.001, 0.2, -1], [0.001, 1, 1], sides=("xmin",))
    value, support, count = shepard_velocity(query, positions, [[0, 2, 0]], neighbours=1,
                                              barrier_triangles=np.vstack((lower, upper)), return_diagnostics=True)
    assert value[0, 1] == pytest.approx(2.0)
    assert np.isfinite(support[0])
    assert count[0] == 1


def test_weighted_seeds_close_initial_mass_by_source(tmp_path):
    path = tmp_path / "weighted.h5"
    make_uniform_h5(path)
    with h5py.File(path, "r+") as h5:
        h5["mass"][:] = 2.0
        h5["mk"][:, :2] = 1
        h5["mk"][:, 2:] = 2
    seeds = weighted_stratified_seeds(path, maximum=3)
    assert seeds["mass_weight"].sum() == pytest.approx(8.0)
    for source in (1, 2):
        assert seeds["mass_weight"][seeds["source_mk"] == source].sum() == pytest.approx(4.0)


def test_moving_wall_provider_tracks_body_transform(tmp_path):
    path = tmp_path / "moving.h5"
    make_uniform_h5(path)
    body = box_surface_triangles([0, -1, -1], [0.01, 1, 1], sides=("xmin",))
    with h5py.File(path, "r+") as h5:
        transforms = np.repeat(np.eye(4)[None], 2, axis=0)
        transforms[1, 0, 3] = 1.0
        h5.create_dataset("control/wall", data=transforms)
    provider = rigid_barrier_provider("control/wall", body)
    with h5py.File(path) as h5:
        middle = provider(h5, 0, 1, 0.5)
    assert middle[..., 0].mean() == pytest.approx(0.5)


def test_advector_invalidates_intermediate_wall_crossing(tmp_path):
    path = tmp_path / "crossing.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("valid", data=np.ones((2, 4), dtype=bool))
        h5.create_dataset("type", data=np.full((2, 4), 3))
        initial = np.asarray([[-0.2, -0.1, 0], [-0.2, 0.1, 0], [-0.1, -0.1, 0], [-0.1, 0.1, 0]])
        h5.create_dataset("position", data=np.asarray([initial, initial + [1.0, 0.0, 0.0]]))
        h5.create_dataset("velocity", data=np.full((2, 4, 3), [1.0, 0.0, 0.0]))
        h5.create_dataset("control/wall", data=np.repeat(np.eye(4)[None], 2, axis=0))
    wall = box_surface_triangles([0, -1, -1], [0, 1, 1], sides=("xmin",))
    traced = advect_hdf5(
        path, [[-0.15, 0.0, 0.0]], neighbours=4,
        barrier_provider=rigid_barrier_provider("control/wall", wall),
    )
    assert traced["wall_crossing"][0, 0]
    assert not traced["reliable"][0]
    np.testing.assert_allclose(traced["position"][-1], [[-0.15, 0.0, 0.0]])
