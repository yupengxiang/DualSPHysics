"""Causal and interface checks for the shared F3 native-volume field."""

import h5py
import numpy as np
import pytest

from scripts.core_contract import State
from scripts.core_material import StateH5Provider
from scripts.f3_native_volume_mls_shared import (
    BACKEND,
    MODEL_ROLE,
    REFERENCE_ROLE,
    NativeVolumeField,
    from_predicted_state,
    from_reference_frame,
    shared_backend_contract,
)
from scripts.f3_native_volume_mls_temporal_v3 import F3CurrentFrame, F3NativeVolumeMLS


def _cloud():
    points = np.asarray([
        [-0.018, -0.012, -0.010], [-0.012, 0.015, -0.004], [0.000, -0.016, 0.012],
        [0.004, 0.010, 0.015], [0.014, -0.009, 0.006], [0.019, 0.013, -0.011],
        [-0.016, 0.002, 0.018], [0.011, -0.017, -0.016], [0.002, 0.002, -0.002],
    ], dtype=np.float64)
    velocity = np.column_stack((
        0.2 + 3.0 * points[:, 0] + 0.8 * points[:, 1] ** 2,
        -0.1 + 2.0 * points[:, 1] - 1.3 * points[:, 0] ** 2,
        0.4 + points[:, 2] + 0.5 * points[:, 0] * points[:, 1],
    ))
    mass = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float64)
    density = np.array([1000., 1000., 1000., 1000., 1000., 1000., 1000., 1000., 1000.])
    valid = np.ones(len(points), dtype=bool)
    return points, velocity, mass, density, valid


def _state(points, velocity, mass, valid, time_s=0.25):
    n = len(points)
    return State(
        time_s=time_s,
        position=points,
        velocity=velocity,
        particle_id=np.arange(n, dtype=np.int64),
        particle_zone=np.zeros(n, dtype=np.int64),
        mass=mass,
        valid=valid,
    )


def test_reference_and_model_adapters_share_the_same_native_volume_backend():
    points, velocity, mass, density, valid = _cloud()
    reference_frame = F3CurrentFrame(
        points, velocity, mass, density, valid, frame_index=4, time_s=0.25,
    )
    reference = from_reference_frame(
        reference_frame,
        source_semantics="registered_reference_native_saved_frame",
    )
    predicted = from_predicted_state(
        _state(points, velocity, mass, valid),
        density,
        density_semantics="model_density_estimate_v1",
        density_time_s=0.25,
    )
    assert reference.provider_role == REFERENCE_ROLE
    assert predicted.provider_role == MODEL_ROLE
    assert reference.binding["backend"] == predicted.binding["backend"] == BACKEND
    assert np.array_equal(reference.volume, predicted.volume)
    query = np.array([[0.001, -0.001, 0.002]], dtype=np.float64)
    walls = np.empty((0, 3, 3), dtype=np.float64)
    tracer = F3NativeVolumeMLS(0.02)
    reference_result = tracer.reconstruct(query, reference, walls)
    predicted_result = tracer.reconstruct(query, predicted, walls)
    np.testing.assert_allclose(reference_result.velocity, predicted_result.velocity, atol=1.0e-14)
    np.testing.assert_array_equal(reference_result.reliable, predicted_result.reliable)


def test_density_is_causal_input_and_changes_volume_weighted_reconstruction():
    points, velocity, mass, density, valid = _cloud()
    state = _state(points, velocity, mass, valid)
    uniform = from_predicted_state(
        state, density, density_semantics="model_density_estimate_v1", density_time_s=state.time_s,
    )
    changed_density = density.copy()
    changed_density[0] *= 12.0
    changed = from_predicted_state(
        state, changed_density, density_semantics="model_density_estimate_v1", density_time_s=state.time_s,
    )
    result_uniform = F3NativeVolumeMLS(0.02).reconstruct(
        np.array([[0.001, -0.001, 0.002]]), uniform, np.empty((0, 3, 3)),
    )
    result_changed = F3NativeVolumeMLS(0.02).reconstruct(
        np.array([[0.001, -0.001, 0.002]]), changed, np.empty((0, 3, 3)),
    )
    assert not np.allclose(result_uniform.velocity, result_changed.velocity, atol=1.0e-14)
    assert changed.volume[0] == pytest.approx(uniform.volume[0] / 12.0)


def test_xv_only_predicted_state_cannot_enter_native_volume_mls():
    points, velocity, mass, _, valid = _cloud()
    state = _state(points, velocity, mass, valid)
    with pytest.raises(ValueError, match="explicit current-state density_estimate"):
        from_predicted_state(state)
    with pytest.raises(ValueError, match="density_semantics"):
        from_predicted_state(
            state, np.full(len(points), 1000.0), density_semantics="native_saved_density",
            density_time_s=state.time_s,
        )


def test_existing_predicted_state_h5_contract_has_no_density_adapter_input(tmp_path):
    """The current model H5 contract is x/v/mass only, so it must fail closed."""
    points, velocity, mass, _, valid = _cloud()
    path = tmp_path / "predicted-without-density.h5"
    with h5py.File(path, "w") as handle:
        handle.attrs.update(
            schema_version=1,
            state_schema="core.state.native_velocity.v1",
            velocity_semantics="native saved numerical velocity",
            future_state_inputs=False,
            autonomous_prediction=True,
            identity_semantics="particle_zone,particle_id",
        )
        handle["time"] = np.array([0.0, 0.1])
        handle["position"] = np.stack((points, points + 0.001), axis=0)
        handle["velocity"] = np.stack((velocity, velocity), axis=0)
        handle["particle_id"] = np.arange(len(points), dtype=np.int64)
        handle["particle_zone"] = np.zeros(len(points), dtype=np.int64)
        handle["mass"] = mass
        handle["valid"] = np.stack((valid, valid), axis=0)
    with StateH5Provider(path) as provider:
        assert "density" not in provider.h5
        state = provider.state(0)
        with pytest.raises(ValueError, match="explicit current-state density_estimate"):
            from_predicted_state(state)
        with pytest.raises(PermissionError):
            provider.future(1)


def test_model_adapter_rejects_reference_provenance_and_has_no_future_reader():
    points, velocity, mass, _, valid = _cloud()
    state = _state(points, velocity, mass, valid)
    with pytest.raises(ValueError, match="reference CFD source"):
        from_predicted_state(
            state,
            np.full(len(points), 1000.0),
            source_semantics="reference CFD native H5",
            density_time_s=state.time_s,
        )
    field = from_predicted_state(
        state, np.full(len(points), 1000.0), density_semantics="model_density_estimate_v1",
        density_time_s=state.time_s,
    )
    assert not hasattr(field, "future")
    with pytest.raises(AttributeError):
        field.future()  # type: ignore[attr-defined]


def test_model_density_must_be_for_the_same_current_time():
    points, velocity, mass, _, valid = _cloud()
    state = _state(points, velocity, mass, valid, time_s=0.25)
    with pytest.raises(ValueError, match="density_time_s must equal"):
        from_predicted_state(
            state, np.full(len(points), 1000.0),
            density_semantics="model_density_estimate_v1", density_time_s=0.35,
        )


def test_contract_requires_explicit_positive_arrays_and_immutable_inputs():
    points, velocity, mass, density, valid = _cloud()
    field = NativeVolumeField(
        points, velocity, mass, density, valid,
        provider_role=REFERENCE_ROLE,
        source_semantics="registered_reference_native_saved_frame",
        density_semantics="native_saved_density",
    )
    with pytest.raises(ValueError, match="density is required"):
        NativeVolumeField(
            points, velocity, mass, None, valid,
            provider_role=REFERENCE_ROLE,
            source_semantics="registered_reference_native_saved_frame",
            density_semantics="native_saved_density",
        )
    assert not field.position.flags.writeable
    assert not field.volume.flags.writeable
    with pytest.raises(ValueError):
        field.position[0, 0] = 1.0
    assert shared_backend_contract()["model_adapter"]["future_state_inputs"] is False
