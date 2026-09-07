"""CPU regressions for the C1/C2 contracts on production custom paths.

The synthetic geometry diagnostic is intentionally not imported here.  These
tests exercise the tracer, sidecar, G4 input, and aggregate implementations
that the campaign scripts actually call.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.boundary_sidecars import sidecar_provider
from scripts.passive_tracers import (
    advect_hdf5,
    box_surface_triangles,
    corresponding_segments_blocked,
    rigid_barrier_provider,
    shepard_velocity,
    shepard_velocity_with_diagnostics,
    spacetime_swept_wall_blocked,
    transform_triangles,
)


ROOT = Path(__file__).parents[1]


def _load_g4():
    path = ROOT / "experiments/r3_g4_baselines.py"
    spec = importlib.util.spec_from_file_location("r3_g4_baselines_c1_c2", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rotation_z(angle: float) -> np.ndarray:
    return np.asarray([
        [np.cos(angle), -np.sin(angle), 0.0, 0.0],
        [np.sin(angle), np.cos(angle), 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ])


def test_rigid_pose_provider_fails_legacy_vertex_lerp_and_preserves_edges(tmp_path):
    body = np.asarray([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]])
    first = np.eye(4)
    second = _rotation_z(np.pi / 2.0)
    second[:3, 3] = [0.2, -0.1, 0.0]
    world0 = body.copy()
    world1 = body @ second[:3, :3].T + second[:3, 3]
    legacy = 0.5 * (world0 + world1)
    with h5py.File(tmp_path / "poses.h5", "w") as h5:
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("pose", data=[first, second])
        provider = rigid_barrier_provider("pose", body)
        candidate = provider(h5, 0, 1, 0.5)
    reference_edges = np.linalg.norm(np.diff(np.concatenate((body, body[:, :1]), axis=1), axis=1), axis=-1)
    legacy_edges = np.linalg.norm(np.diff(np.concatenate((legacy, legacy[:, :1]), axis=1), axis=1), axis=-1)
    candidate_edges = np.linalg.norm(np.diff(np.concatenate((candidate, candidate[:, :1]), axis=1), axis=1), axis=-1)
    assert np.max(np.abs(legacy_edges - reference_edges)) > 1e-5
    np.testing.assert_allclose(candidate_edges, reference_edges, atol=1e-10)
    assert provider.motion_interpolation == "rigid_pose_quaternion_slerp"


def test_sidecar_provider_uses_component_rigid_fit_not_world_vertex_lerp(tmp_path):
    body = np.asarray([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]])
    first = body.copy()
    rotation = _rotation_z(np.pi / 2.0)
    second = body @ rotation[:3, :3].T + np.asarray([0.2, -0.1, 0.0])
    path = tmp_path / "sidecar.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("triangles_world", data=np.asarray([first, second]))
        h5.create_dataset("triangle_mk", data=[7])
        h5.create_dataset("triangle_type", data=[1])
    provider = sidecar_provider(path)
    with h5py.File(path, "r") as h5:
        candidate = provider(h5, 0, 1, 0.5)
    reference_edges = np.linalg.norm(np.diff(np.concatenate((body, body[:, :1]), axis=1), axis=1), axis=-1)
    candidate_edges = np.linalg.norm(np.diff(np.concatenate((candidate, candidate[:, :1]), axis=1), axis=1), axis=-1)
    np.testing.assert_allclose(candidate_edges, reference_edges, atol=1e-10)
    assert provider.motion_interpolation == "sidecar_component_rigid_pose_kabsch_slerp"


def test_swept_wall_negative_midpoint_control_and_production_advector(tmp_path):
    # The wall is represented once in body coordinates and moved by prescribed
    # rigid poses.  The old negative control below only sees a midpoint mesh;
    # the production advector receives the rigid provider and swept endpoints.
    body = box_surface_triangles([0.0, -0.2, -0.2], [0.0, 0.2, 0.2], sides=("xmin",))
    pose0 = np.eye(4)
    pose0[:3, 3] = [0.4, 0.0, 0.0]
    pose1 = np.eye(4)
    pose1[:3, 3] = [-0.5, 0.0, 0.0]
    wall0 = transform_triangles(body, pose0)
    wall1 = transform_triangles(body, pose1)
    start = np.asarray([[0.0, 0.0, 0.0]])
    end = start.copy()
    midpoint = 0.5 * (wall0 + wall1)
    assert not corresponding_segments_blocked(start, end, midpoint)[0]
    assert spacetime_swept_wall_blocked(start, end, wall0, wall1)[0]

    path = tmp_path / "trajectory.h5"
    particles = np.asarray([
        [-0.2, -0.1, 0.0], [-0.2, 0.1, 0.0], [-0.1, -0.1, 0.0], [-0.1, 0.1, 0.0],
    ])
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("valid", data=np.ones((2, 4), dtype=bool))
        h5.create_dataset("type", data=np.full((2, 4), 3, dtype=np.int8))
        h5.create_dataset("position", data=np.asarray([particles, particles + [1.0, 0.0, 0.0]]))
        h5.create_dataset("velocity", data=np.full((2, 4, 3), [1.0, 0.0, 0.0]))
        h5.create_dataset("pose", data=np.asarray([pose0, pose1]))
    barrier = rigid_barrier_provider("pose", body)
    traced = advect_hdf5(path, [[-0.15, 0.0, 0.0]], neighbours=4, regularization=0.001,
                         barrier_provider=barrier)
    assert traced["wall_crossing"][0, 0]
    assert not traced["reliable"][0]
    assert traced["motion_interpolation"] == "rigid_pose_quaternion_slerp"


def test_support_gate_reports_quality_and_can_reject_without_count_threshold(tmp_path):
    points = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    velocities = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    value, _, _, diagnostics = shepard_velocity_with_diagnostics(
        [[0.2, 0.2, 0.2]], points, velocities, neighbours=4, regularization=0.01
    )
    assert np.isfinite(value).all()
    assert diagnostics["effective_sample_size"][0] > 1.0
    assert diagnostics["geometry_rank"][0] == 3
    assert diagnostics["anisotropy"][0] > 0.0
    assert np.isfinite(diagnostics["interpolation_reconstruction_error_mps"])[0]

    # The old path returns no quality gate and therefore cannot reject this
    # intentionally one-sided/high-residual support by contract.
    legacy, _ = shepard_velocity([[0.2, 0.2, 0.2]], points, velocities, neighbours=4, regularization=0.01)
    assert np.isfinite(legacy).all()

    # Exercise the actual HDF5 advector gate.  A deliberately nonlinear fifth
    # sample gives a finite but large affine reconstruction residual.  The old
    # interpolation path remains finite and would accept it; the production
    # gate rejects it using the observable residual rather than ``23/24``.
    points = np.asarray([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0], [1.0, 1.0, 1.0],
    ])
    velocities = np.asarray([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0], [10.0, -4.0, 3.0],
    ])
    path = tmp_path / "support_gate.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("valid", data=np.ones((2, len(points)), dtype=bool))
        h5.create_dataset("type", data=np.full((2, len(points)), 3, dtype=np.int8))
        h5.create_dataset("position", data=np.asarray([points, points]))
        h5.create_dataset("velocity", data=np.asarray([velocities, velocities]))
    gated = advect_hdf5(
        path, [[0.2, 0.2, 0.2]], neighbours=5, regularization=0.01,
        support_gate={
            "minimum_effective_sample_size": 1.0,
            "minimum_geometry_rank": 1,
            "minimum_anisotropy": 0.0,
            "maximum_reconstruction_error_mps": 1e-12,
        },
    )
    assert not gated["support_gate_pass"][0, 0]
    assert not gated["reliable"][0]


def test_source_labels_are_not_a_post_mixing_visibility_filter():
    query = np.asarray([[-0.1, 0.0, 0.0]])
    particles = np.asarray([[-0.2, 0.0, 0.0], [0.1, 0.0, 0.0]])
    velocities = np.asarray([[1.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
    wall = box_surface_triangles([0.0, -1.0, -1.0], [0.0, 1.0, 1.0], sides=("xmin",))
    # A source label may be retained as initial metadata, but it is not an
    # argument to the production visibility/interpolation path.
    separated, _, count = shepard_velocity(
        query, particles, velocities, neighbours=2, regularization=0.001,
        barrier_triangles=wall, return_diagnostics=True,
    )
    assert separated[0, 0] == pytest.approx(1.0)
    assert count[0] == 1
    opened, _, count = shepard_velocity(
        query, particles, velocities, neighbours=2, regularization=0.001,
        barrier_triangles=np.empty((0, 3, 3)), return_diagnostics=True,
    )
    assert opened[0, 0] > 1.0
    assert count[0] == 2


def test_g4_component_inputs_angular_control_and_future_rejection(tmp_path):
    module = _load_g4()
    sidecar = tmp_path / "components.h5"
    triangles = np.asarray([[[[0.0, -1.0, -1.0], [0.0, 1.0, -1.0], [0.0, -1.0, 1.0]]],
                            [[[0.1, -1.0, -1.0], [0.1, 1.0, -1.0], [0.1, -1.0, 1.0]]]])
    with h5py.File(sidecar, "w") as h5:
        h5.create_dataset("time", data=[0.0, 1.0])
        h5.create_dataset("triangles_world", data=triangles)
        h5.create_dataset("triangle_mk", data=[11])
        h5.create_dataset("triangle_type", data=[1])
        h5.attrs.update({"schema_version": "boundary-sidecar-v1", "coordinate_frame": "world", "case_id": "tiny",
                         "source_geometry_sha256": "a" * 64})
    case = {
        "case_id": "tiny", "family": "F1", "length_scale": 1.0, "time_scale": 1.0,
        "gravity": np.asarray([0.0, 0.0, -9.81]), "time": np.asarray([0.0, 1.0]),
        "boundary_components": module._boundary_component_series(sidecar, np.asarray([0.0, 1.0])),
    }
    named = module.boundary_component_features(case, 1, np.asarray([[0.2, 0.0, 0.0]]), dt=1.0)
    assert {"distance_to_boundary_component_m", "normal", "type", "wall_velocity_mps"}.issubset(named[0][0])
    assert named[0][0]["wall_velocity_mps"][0] == pytest.approx(0.1)

    controls = np.zeros((2, 3), dtype=np.float32)
    with h5py.File(tmp_path / "control.h5", "w") as h5:
        group = h5.create_group("control")
        group.create_dataset("cup_angle_degrees", data=[0.0, 5.0])
        group.create_dataset("prescribed_angular_velocity_radps", data=controls + [0.0, 0.0, 0.5])
        result, source, available = module._control_features(h5, np.asarray([0.0, 1.0]))
    assert available and source == "known_prescribed_angular_control_schedule"
    np.testing.assert_allclose(result[:, 6:9], controls + [0.0, 0.0, 0.5])
    with pytest.raises(ValueError, match="future fluid/free-body"):
        module.validate_model_input_contract({"control": {"prescribed_angular_velocity_radps": [0.0, 0.0, 0.5]},
                                              "future_free_body_state": {"pose": [1.0, 0.0, 0.0]}})


def test_aggregate_keeps_failed_rollouts_in_population_denominator():
    path = ROOT / "experiments/r3_g4_aggregate.py"
    spec = importlib.util.spec_from_file_location("r3_g4_aggregate_c1_c2", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def run(seed, status, value):
        return {"route": "local_interaction", "seed": seed, "test_rollout": {"case": {
            "case_id": "case", "family": "F1", "background_id": "bg", "split": "test",
            "status": status, "learned_rmse_over_dp": value,
            "learned_ade_m": value, "learned_fde_m": value,
            "learned_velocity_rmse_mps": value, "learned_com_rmse_m": value,
            "boundary_source": "missing", "boundary_available": False,
            "mass_identity_preserved": status == "completed",
        }}}
    result = module.aggregate_route("local_interaction", [run(17, "completed", 1.0), run(29, "nonfinite_prediction", None)])
    population = result["evaluation_population"]
    assert population["sample_count"] == 2
    assert population["successful_count"] == 1
    assert population["failure_count"] == 1
    assert population["failure_fraction"] == pytest.approx(0.5)
    assert result["per_case"]["case"]["learned_position_rmse_over_dp"]["failure_count"] == 1
    completed_missing_metric = module.mean_std(
        [1.0, None], ["completed", "completed"], expected_count=2
    )
    assert completed_missing_metric["successful_count"] == 1
    assert completed_missing_metric["failure_count"] == 1
