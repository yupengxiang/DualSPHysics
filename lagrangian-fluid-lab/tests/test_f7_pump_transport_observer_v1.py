from __future__ import annotations

import hashlib

import h5py
import numpy as np

from scripts.f7_pump_transport_observer_v1 import (
    ANGULAR_CONTROL_SEMANTICS,
    BODY_FRAME_SEMANTICS,
    SCHEMA,
    audit_pump_transport,
    canonical_hash,
    sha256_array,
    sha256_file,
)


def _write_case(path):
    times = np.asarray([0.0, 0.5, 1.0], dtype=float)
    transforms = np.repeat(np.eye(4, dtype=float)[None], len(times), axis=0)
    angular = np.asarray([[0.0, 0.0, 1.0], [0.0, 0.0, 2.0], [0.0, 0.0, 1.0]], dtype=float)
    positions = np.asarray([
        [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [2.0, 0.0, 0.0]],
        [[1.0, 0.0, 0.0], [0.5, 0.0, 0.0], [2.0, 0.0, 0.0]],
        [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [2.0, 0.0, 0.0]],
    ])
    valid = np.ones((3, 3), dtype=bool)
    with h5py.File(path, "w") as h5:
        h5.attrs["case_id"] = "f7-observer-test"
        h5["time"] = times
        h5["position"] = positions
        h5["valid"] = valid
        h5["type"] = np.full((3, 3), 3, dtype=np.int8)
        h5["mass"] = np.asarray([2.0, 1.0, 4.0])
        h5["particle_id"] = np.asarray([10, 11, 12], dtype=np.int64)
        h5["particle_zone"] = np.zeros(3, dtype=np.int16)
        h5["particle_id_by_frame"] = np.broadcast_to(np.asarray([10, 11, 12], dtype=np.int64), (len(times), 3))
        h5["particle_zone_by_frame"] = np.zeros((len(times), 3), dtype=np.int16)
        h5["control/pump_world_from_body"] = transforms
        h5["control/pump_angular_velocity_rad_s"] = angular
    return times, transforms, angular


def _spec(path, transforms, angular):
    spec = {
        "schema": SCHEMA,
        "lifecycle_model": "closed",
        "source_mode": "all_initial_fluid",
        "intake_region": {"name": "intake", "type": "aabb", "min": [-0.2, -0.2, -0.2], "max": [0.2, 0.2, 0.2]},
        "discharge_region": {"name": "discharge", "type": "aabb", "min": [0.8, -0.2, -0.2], "max": [1.2, 0.2, 0.2]},
        "return_region": {"name": "return", "type": "aabb", "min": [-0.2, -0.2, -0.2], "max": [0.2, 0.2, 0.2]},
        "residence_region": {"name": "residence", "type": "aabb", "min": [0.2, -0.2, -0.2], "max": [0.8, 0.2, 0.2]},
        "body_frame_dataset": "control/pump_world_from_body",
        "angular_control_dataset": "control/pump_angular_velocity_rad_s",
        "body_frame_semantics": BODY_FRAME_SEMANTICS,
        "angular_control_semantics": ANGULAR_CONTROL_SEMANTICS,
        "body_frame_time_dataset": "time",
        "angular_control_time_dataset": "time",
        "identity_semantics": "fixed_particle_columns",
        "particle_id_frame_dataset": "particle_id_by_frame",
        "particle_zone_frame_dataset": "particle_zone_by_frame",
        "body_frame_sha256": sha256_array(transforms),
        "angular_control_sha256": sha256_array(angular),
        "trajectory_sha256": sha256_file(path),
        "event_window_s": [0.0, 1.0],
        "unknown_exit_max_fraction": 0.0,
    }
    spec["region_contract_sha256"] = canonical_hash({
        key: spec[key] for key in ("intake_region", "discharge_region", "return_region", "residence_region")
    })
    return spec


def test_observer_keeps_all_initial_fluid_mass_and_detects_return(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    result = audit_pump_transport(path, _spec(path, transforms, angular))
    assert result["status"] == "observer_complete_but_root_gate_blocked"
    assert result["source_denominator"] == {
        "mode": "all_initial_fluid",
        "initial_fluid_count": 3,
        "initial_fluid_mass_kg": 7.0,
        "survivor_renormalization": False,
    }
    classification = result["classification"]
    assert classification["mass_kg"]["returned"] == 2.0
    assert classification["mass_kg"]["observed_without_target"] == 5.0
    assert classification["residence_event_mass_kg"] == 3.0
    assert classification["mass_kg"]["unknown_exit"] == 0.0
    assert classification["closure_error_kg"] == 0.0
    assert classification["unknown_exit_bound_pass"] is True
    assert result["qualification_credit"] == 0


def test_observer_requires_hash_bound_frame_and_angular_control(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    spec = _spec(path, transforms, angular)
    spec["body_frame_sha256"] = hashlib.sha256(b"wrong").hexdigest()
    failed = audit_pump_transport(path, spec)
    assert failed["status"] == "blocked_body_frame_hash_mismatch"
    spec = _spec(path, transforms, angular)
    spec["angular_control_sha256"] = hashlib.sha256(b"wrong").hexdigest()
    failed = audit_pump_transport(path, spec)
    assert failed["status"] == "blocked_angular_control_hash_mismatch"


def test_missing_control_is_blocked_without_inference(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        del h5["control/pump_world_from_body"]
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    failed = audit_pump_transport(path, spec)
    assert failed["status"] == "blocked_missing_causal_control"


def test_unknown_exit_is_not_renormalized(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        h5["valid"][2, 0] = False
        h5["position"][2, 0] = np.nan
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["classification"]["mass_kg"]["unknown_exit"] == 2.0
    assert result["classification"]["unknown_exit_count"] == 1
    assert result["classification"]["unknown_exit_fraction"] == 2.0 / 7.0
    assert result["classification"]["unknown_exit_bound_pass"] is False
    assert result["classification"]["closure_error_kg"] == 0.0
    assert result["source_denominator"]["initial_fluid_mass_kg"] == 7.0


def test_initial_invalid_fluid_remains_in_all_initial_denominator(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        h5["valid"][0, 2] = False
        h5["position"][0, 2] = np.nan
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["source_denominator"]["initial_fluid_count"] == 3
    assert result["source_denominator"]["initial_fluid_mass_kg"] == 7.0
    assert result["classification"]["unknown_exit_count"] == 1
    assert result["classification"]["mass_kg"]["unknown_exit"] == 4.0


def test_event_window_limits_material_events(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    spec = _spec(path, transforms, angular)
    spec["event_window_s"] = [0.75, 1.0]
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["classification"]["first_discharge_frame_count"] == 0
    assert result["classification"]["first_return_frame_count"] == 0


def test_cross_frame_identity_reordering_is_blocked(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        h5["particle_id_by_frame"][1] = np.asarray([11, 10, 12], dtype=np.int64)
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["status"] == "blocked_identity_reordering"


def test_nonbinary_valid_dataset_is_blocked(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        del h5["valid"]
        h5["valid"] = np.ones((3, 3), dtype=np.float64)
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["status"] == "blocked_invalid_valid_dtype"


def test_valid_nonfinite_position_fails_closed(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        h5["position"][2, 0] = np.nan
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["status"] == "blocked_nonfinite_valid_position"


def test_invalid_then_revalidated_particle_cannot_create_late_event(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        h5["valid"][1, 0] = False
        h5["position"][1, 0] = np.nan
        h5["valid"][2, 0] = True
        h5["position"][2, 0] = [1.0, 0.0, 0.0]
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["classification"]["unknown_exit_count"] == 1
    assert result["classification"]["first_discharge_frame_count"] == 0
    assert result["classification"]["mass_kg"]["unknown_exit"] == 2.0


def test_nontrivial_world_from_body_frame_is_hash_bound(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    angle = np.pi / 2.0
    rotation = np.asarray([[np.cos(angle), -np.sin(angle), 0.0],
                           [np.sin(angle), np.cos(angle), 0.0],
                           [0.0, 0.0, 1.0]])
    transforms[:] = np.eye(4)
    transforms[:, :3, :3] = rotation
    transforms[:, :3, 3] = [1.0, 2.0, 0.0]
    with h5py.File(path, "a") as h5:
        body = np.asarray(h5["position"][:])
        h5["position"][:] = body @ rotation.T + np.asarray([1.0, 2.0, 0.0])
        h5["control/pump_world_from_body"][:] = transforms
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["status"] == "observer_complete_but_root_gate_blocked"
    assert result["body_frame_binding"]["semantics"] == BODY_FRAME_SEMANTICS
    assert result["classification"]["mass_kg"]["returned"] == 2.0


def test_unknown_exit_bound_blocks_contract_even_with_declared_torque(tmp_path):
    path = tmp_path / "case.h5"
    times, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        h5["valid"][1, 0] = False
        h5["position"][1, 0] = np.nan
        h5["valid"][2, 0] = False
        h5["position"][2, 0] = np.nan
        h5["position"][1, 1] = [1.0, 0.0, 0.0]
        h5["position"][2, 1] = [0.0, 0.0, 0.0]
        h5["control/pump_torque"] = np.ones((len(times), 3), dtype=float)
    spec = _spec(path, transforms, angular)
    torque = np.ones((len(times), 3), dtype=float)
    spec.update({
        "trajectory_sha256": sha256_file(path),
        "torque_dataset": "control/pump_torque",
        "torque_sha256": sha256_array(torque),
        "torque_time_dataset": "time",
        "torque_time_sha256": sha256_array(times),
        "torque_units": "N m",
        "torque_body_id": 2,
        "torque_semantics": "pump_body_external_torque_n_m_world_frame",
    })
    result = audit_pump_transport(path, spec)
    gate = result["pump_control_observation"]["gate"]
    assert result["classification"]["unknown_exit_bound_pass"] is False
    assert gate["torque_dataset_hash_bound"] is True
    assert gate["physical_independence_contract_satisfied"] is False
    assert gate["physical_independence_proven"] is False


def test_zero_torque_never_satisfies_independence_contract(tmp_path):
    path = tmp_path / "case.h5"
    times, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        h5["position"][1, 1] = [1.0, 0.0, 0.0]
        h5["position"][2, 1] = [0.0, 0.0, 0.0]
        h5["control/pump_torque"] = np.zeros((len(times), 3), dtype=float)
    spec = _spec(path, transforms, angular)
    torque = np.zeros((len(times), 3), dtype=float)
    spec.update({
        "trajectory_sha256": sha256_file(path),
        "torque_dataset": "control/pump_torque",
        "torque_sha256": sha256_array(torque),
        "torque_time_dataset": "time",
        "torque_time_sha256": sha256_array(times),
        "torque_units": "N m",
        "torque_body_id": 2,
        "torque_semantics": "pump_body_external_torque_n_m_world_frame",
    })
    result = audit_pump_transport(path, spec)
    gate = result["pump_control_observation"]["gate"]
    assert gate["torque_dataset_present_and_finite"] is True
    assert gate["torque_nonzero"] is False
    assert gate["physical_independence_contract_satisfied"] is False


def test_linear_segment_crossing_detects_unsaved_discharge_passage(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    with h5py.File(path, "a") as h5:
        h5["position"][:, 2] = np.asarray([
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ])
    spec = _spec(path, transforms, angular)
    spec["trajectory_sha256"] = sha256_file(path)
    result = audit_pump_transport(path, spec)
    assert result["classification"]["first_discharge_frame_count"] == 2
    assert result["classification"]["first_return_frame_count"] == 2
    assert result["classification"]["linear_segment_crossing_detection"] is True


def test_pump_gate_does_not_claim_independence_without_torque(tmp_path):
    path = tmp_path / "case.h5"
    _, transforms, angular = _write_case(path)
    result = audit_pump_transport(path, _spec(path, transforms, angular))
    gate = result["pump_control_observation"]["gate"]
    assert gate["angular_control_nonzero"] is True
    assert gate["discharge_first_passage_observed"] is True
    assert gate["return_passage_observed"] is True
    assert gate["torque_dataset_present_and_finite"] is False
    assert gate["physical_independence_proven"] is False
    assert result["pump_control_observation"]["correlation_is_causal_claim"] is False


def test_invalid_spec_is_fail_closed():
    result = audit_pump_transport("does-not-exist.h5", {"schema": "wrong"})
    assert result["status"] == "blocked_invalid_spec"
    assert result["qualification_credit"] == 0
