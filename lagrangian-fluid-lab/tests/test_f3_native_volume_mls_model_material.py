"""Tests for the causal model-material rho0 adapter and evaluator."""

import h5py
import numpy as np

from scripts.f3_native_volume_mls_model_material import (
    BACKEND,
    MODEL_ROLE,
    PublicRho0DensityEstimator,
    ModelRho0CurrentProvider,
    ReferenceRho0CurrentProvider,
    run_material_trace,
)


def _cloud():
    axis = np.asarray([-0.015, 0.0, 0.015], dtype=np.float64)
    return np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1).reshape(-1, 3)


def _write_model(path, *, frames=3):
    points = _cloud()
    velocity = np.column_stack((
        np.full(len(points), -0.10),
        0.2 * points[:, 1],
        -0.1 * points[:, 2],
    ))
    times = np.arange(frames, dtype=np.float64) * 0.01
    with h5py.File(path, "w") as handle:
        handle.attrs.update(
            schema_version=1,
            state_schema="core.state.native_velocity.v1",
            velocity_semantics="native saved numerical velocity",
            future_state_inputs=False,
            autonomous_prediction=True,
            identity_semantics="particle_zone,particle_id",
        )
        handle["time"] = times
        handle["position"] = np.stack([points + i * 0.0001 * velocity for i in range(frames)])
        handle["velocity"] = np.stack([velocity for _ in range(frames)])
        handle["particle_id"] = np.arange(len(points), dtype=np.int64)
        handle["particle_zone"] = np.zeros(len(points), dtype=np.int64)
        handle["mass"] = np.full(len(points), 1.0e-6)
        handle["valid"] = np.ones((frames, len(points)), dtype=bool)


def _write_reference(path, *, frames=3):
    points = _cloud()
    velocity = np.column_stack((
        np.full(len(points), -0.10),
        0.2 * points[:, 1],
        -0.1 * points[:, 2],
    ))
    times = np.arange(frames, dtype=np.float64) * 0.01
    with h5py.File(path, "w") as handle:
        handle["time"] = times
        handle["position"] = np.stack([points + i * 0.0001 * velocity for i in range(frames)])
        handle["velocity"] = np.stack([velocity for _ in range(frames)])
        handle["mass"] = np.full((frames, len(points)), 1.0e-6)
        handle["density"] = np.full((frames, len(points)), 997.0)
        handle["valid"] = np.ones((frames, len(points)), dtype=bool)
        handle["type"] = np.full((frames, len(points)), 3.0)


def test_public_rho0_estimator_is_versioned_and_current_state_only():
    points = _cloud()
    from scripts.core_contract import State

    state = State(
        time_s=0.1,
        position=points,
        velocity=np.zeros_like(points),
        particle_id=np.arange(len(points)),
        particle_zone=np.zeros(len(points), dtype=np.int64),
        mass=np.ones(len(points)),
        valid=np.ones(len(points), dtype=bool),
    )
    estimator = PublicRho0DensityEstimator(1000.0)
    density = estimator.estimate(state)
    assert estimator.binding["strategy"] == "rho0_constant_public_current_state_v1"
    assert np.all(density == 1000.0)
    assert density.flags.writeable is False


def test_model_provider_holds_current_frame_and_never_reads_next_frame(tmp_path):
    source = tmp_path / "model.h5"
    _write_model(source)
    with ModelRho0CurrentProvider(source, rho0_kgm3=1000.0) as provider:
        field = provider.field_at(0, 0.005)
        assert field.binding["provider_role"] == "predicted_model"
        assert field.density_semantics == "model_rho0_constant_public_v1"
        assert provider.loaded_indices == [0]
        with np.testing.assert_raises(PermissionError):
            provider.future(1)
        with np.testing.assert_raises(ValueError):
            provider.field_at(0, 0.011)


def test_reference_control_replaces_native_density_with_same_rho0_policy(tmp_path):
    source = tmp_path / "reference.h5"
    _write_reference(source)
    with ReferenceRho0CurrentProvider(source, rho0_kgm3=1000.0) as provider:
        field = provider.field_at(0, 0.005)
        assert field.density_semantics == "reference_rho0_constant_public_v1"
        assert np.all(field.density == 1000.0)
        assert provider.binding["native_reference_density_used"] is False
        assert provider.binding["native_density_read_for_weight"] is False


def test_small_model_source_integrates_and_scores_events_end_to_end(tmp_path):
    source = tmp_path / "model.h5"
    output = tmp_path / "trace.h5"
    _write_model(source, frames=3)
    seeds = np.asarray([
        [-0.001, 0.0, 0.0], [0.001, 0.0, 0.0],
    ])
    report = run_material_trace(
        source,
        output,
        role=MODEL_ROLE,
        rho0_kgm3=1000.0,
        dp_m=0.015,
        seeds=seeds,
        intervals=2,
        substeps=1,
        walls=np.empty((0, 3, 3), dtype=np.float64),
    )
    assert report["backend"] == BACKEND
    assert report["qualification_claim"] == "none"
    assert report["density_policy"]["strategy"] == "rho0_constant_public_current_state_v1"
    assert report["source"]["future_state_inputs"] is False
    assert report["seed_count"] == 2
    assert report["common_reliable_path_fraction"] == 1.0
    with h5py.File(output, "r") as handle:
        assert handle.attrs["backend"] == BACKEND
        assert handle["time"].shape == (3,)
        assert handle["first_passage"].shape == (3, 2)
