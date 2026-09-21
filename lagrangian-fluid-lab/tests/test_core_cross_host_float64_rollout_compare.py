import copy
import hashlib
import json

import h5py
import numpy as np

from scripts import core_cross_host_float64_rollout_compare as compare


def _sha(label):
    return hashlib.sha256(label.encode()).hexdigest()


def _write_fixture(tmp_path, name, *, position_delta=0.0, physics_delta=0.0):
    frames, particles = 3, 2
    position = np.zeros((frames, particles, 3), dtype=np.float64)
    velocity = np.zeros((frames, particles, 3), dtype=np.float64)
    position[1] = .1
    position[2] = .2
    velocity[1] = .3
    velocity[2] = .4
    position[2, 0, 0] += position_delta
    times = np.array([0.0, .01, .02], dtype=np.float64)
    h5_path = tmp_path / f"{name}.h5"
    with h5py.File(h5_path, "w") as handle:
        handle.attrs.update(schema=compare.SCHEMA,
                            state_schema="core.state.native_velocity.v1",
                            storage_dtype="float64", future_state_inputs=False)
        handle["time"] = times
        handle["position"] = position
        handle["velocity"] = velocity
        handle["particle_id"] = np.array([10, 11], dtype=np.int64)
        handle["particle_zone"] = np.array([0, 0], dtype=np.int64)
        handle["mass"] = np.ones(particles, dtype=np.float64)
        handle["valid"] = np.ones((frames, particles), dtype=bool)
    bundle = {key: _sha(key) for key in compare.BUNDLE_KEYS}
    physics = []
    for index in range(frames - 1):
        physics.append({
            "predicted": {"active_mass_kg": 2.0, "active_particles": 2,
                          "registered_particles": 2, "kinetic_energy_j": 1.0 + physics_delta,
                          "center_of_mass_m": [0.1, 0.2, 0.3], "momentum_kg_mps": [0., 0., 0.]},
            "reference": {"active_mass_kg": 2.0, "active_particles": 2,
                          "registered_particles": 2, "kinetic_energy_j": 1.0,
                          "center_of_mass_m": [0.1, 0.2, 0.3], "momentum_kg_mps": [0., 0., 0.]},
            "mass_error_kg": 0.0, "kinetic_energy_error_j": physics_delta,
            "validity_mismatch_count": 0, "changed_particle_mass_count": 0,
            "wall_chord": {"status": "checked_static_saved_chords",
                           "particle_count": 0, "mass_kg": 0.0},
        })
    report = {
        "schema": compare.SCHEMA,
        "status": "complete",
        "variant": "float64_inference",
        "case_id": "fixture",
        "model_kind": "graph_residual",
        "inference_dtype": "float64",
        "maximum_steps": 2,
        "expected_transition_count": 2,
        "expected_state_frames": 3,
        "completed_transitions": 2,
        "dtype_contract": {
            "feature_construction_dtype": "float32 (core_models.node_features public contract)",
            "feature_promotion": True,
            "model_input_dtype": "float64", "parameter_compute_dtype": "float64",
            "normalization_dtype": "float64", "position_tensor_dtype": "float64",
            "prior_tensor_dtype": "float64", "neighbor_index_dtype": "int64",
            "output_dtype": "float64 numpy SI arrays",
        },
        "comparison_protocol": {
            "schema": "core.cross_host_comparison.v1",
            "position_absolute_tolerance_m": compare.POSITION_ATOL_M,
            "velocity_absolute_tolerance_mps": compare.VELOCITY_ATOL_MPS,
            "relative_tolerance": compare.RELATIVE_TOLERANCE,
            "tolerances_frozen": True,
        },
        "score_protocol": {"schema": "core.scoring_protocol.v1"},
        "bundle": {"identity": {
            "expected": bundle,
            "observed": {key: {"path": f"/{name}/{key}", "sha256": value}
                         for key, value in bundle.items()},
        }},
        "case": {"physical_case_id": "physical", "lineage_group_id": "lineage",
                 "family": "F3", "split": "validation",
                 "hdf5_sha256_declared": _sha("hdf5"),
                 "known_inputs_sha256": _sha("known"),
                 "particle_count": particles},
        "position_rmse": [.1, .2], "velocity_rmse": [.3, .4],
        "position_ade": [.1, .2], "velocity_ade": [.3, .4],
        "score": {"expected_frames": 2, "complete": True,
                  "finite_prefix_frames": 2, "fixed_denominator": True},
        "physics_frames": physics,
        "physics_summary": {"expected_frames": 2, "completed_frames": 2},
        "trajectory": {"path": str(h5_path), "sha256": compare.sha256_file(h5_path),
                        "frames": frames, "particle_count": particles, "dtype": "float64"},
    }
    report_path = tmp_path / f"{name}.json"
    report_path.write_text(json.dumps(report))
    return report_path


def _pair(tmp_path, left, right):
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    left_path.write_text(json.dumps(left))
    right_path.write_text(json.dumps(right))
    return left_path, right_path


def test_full_rollout_comparator_checks_h5_score_and_physics_fixture(tmp_path):
    left = json.loads(_write_fixture(tmp_path, "left").read_text())
    right = json.loads(_write_fixture(tmp_path, "right").read_text())
    result = compare.compare_rollouts(*_pair(tmp_path, left, right),
                                      expected_steps=2, expected_state_frames=3,
                                      expected_particles=2)
    assert result["status"] == "pass"
    assert result["hdf5"]["passed"] is True
    assert result["score"]["passed"] is True
    assert result["physics"]["passed"] is True


def test_full_rollout_comparator_reports_registered_state_tolerance_failure(tmp_path):
    left = json.loads(_write_fixture(tmp_path, "left").read_text())
    right_path = _write_fixture(tmp_path, "right", position_delta=5e-5)
    right = json.loads(right_path.read_text())
    result = compare.compare_rollouts(*_pair(tmp_path, left, right),
                                      expected_steps=2, expected_state_frames=3,
                                      expected_particles=2)
    assert result["status"] == "fail"
    assert result["hdf5"]["comparison"]["numeric"]["position"]["violation_count"] == 1
    assert "h5:position:tolerance" in result["errors"]


def test_full_rollout_comparator_keeps_physics_failure_separate_from_state_pass(tmp_path):
    left = json.loads(_write_fixture(tmp_path, "left").read_text())
    right_path = _write_fixture(tmp_path, "right", physics_delta=1e-3)
    right = json.loads(right_path.read_text())
    result = compare.compare_rollouts(*_pair(tmp_path, left, right),
                                      expected_steps=2, expected_state_frames=3,
                                      expected_particles=2)
    assert result["status"] == "fail"
    assert result["hdf5"]["passed"] is True
    assert result["physics"]["passed"] is False
    assert "physics:numeric_tolerance" in result["errors"]


def test_registered_physics_tolerance_accepts_small_roundoff(tmp_path):
    left = _write_fixture(tmp_path, "left")
    right = _write_fixture(tmp_path, "right", physics_delta=1e-8)
    result = compare.compare_rollouts(left, right, expected_steps=2, expected_state_frames=3, expected_particles=2)
    assert result["status"] == "pass"


def test_score_summary_cannot_disagree_when_frame_errors_match(tmp_path):
    left = json.loads(_write_fixture(tmp_path, "left").read_text())
    right = json.loads(_write_fixture(tmp_path, "right").read_text())
    left["score"]["normalized_error"] = 0.2
    right["score"]["normalized_error"] = 0.3
    result = compare.compare_rollouts(*_pair(tmp_path, left, right), expected_steps=2, expected_state_frames=3, expected_particles=2)
    assert "score:summary:tolerance_or_contract" in result["errors"]


def test_integer_physics_counts_remain_exact_at_large_counts(tmp_path):
    left = json.loads(_write_fixture(tmp_path, "left").read_text())
    right = json.loads(_write_fixture(tmp_path, "right").read_text())
    left["physics_frames"][0]["wall_chord"]["particle_count"] = 100000
    right["physics_frames"][0]["wall_chord"]["particle_count"] = 100001
    result = compare.compare_rollouts(*_pair(tmp_path, left, right), expected_steps=2, expected_state_frames=3, expected_particles=2)
    assert result["physics"]["passed"] is False
