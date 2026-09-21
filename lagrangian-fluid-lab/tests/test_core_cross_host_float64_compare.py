import copy
import hashlib
import json

import numpy as np

from scripts import core_cross_host_canary_float64 as runner
from scripts.core_cross_host_float64_compare import compare_reports


def _sha(label):
    return hashlib.sha256(label.encode()).hexdigest()


def _report(tmp_path, name, *, position_delta=0.0, velocity_delta=0.0):
    positions = np.zeros((3, 2, 3), dtype=np.float64)
    velocities = np.zeros((3, 2, 3), dtype=np.float64)
    positions[1] = .1
    positions[2] = .2
    velocities[1] = .3
    velocities[2] = .4
    positions[2, 0, 0] += position_delta
    velocities[2, 1, 1] += velocity_delta
    times = np.array([0.0, .01, .02], dtype=np.float64)
    arrays_path = tmp_path / f"{name}.npz"
    with arrays_path.open("wb") as stream:
        np.savez_compressed(stream, position=positions, velocity=velocities, time_s=times)
    manifest, checkpoint, models = _sha("manifest"), _sha("checkpoint"), _sha("models")
    known = _sha("known")

    def state(frame):
        return {
            "time_s": float(times[frame]),
            "position": runner.array_digest(positions[frame]),
            "velocity": runner.array_digest(velocities[frame]),
        }

    return {
        "schema": runner.SCHEMA,
        "status": "complete",
        "variant": "float64_inference",
        "case_id": "fixture",
        "model_kind": "graph_residual",
        "maximum_steps": 2,
        "expected_frames": 3,
        "completed_steps": 2,
        "chunk_size": 256,
        "inference_dtype": "float64",
        "dtype_contract": runner.dtype_contract("float64"),
        "comparison_protocol": {
            "schema": "core.cross_host_comparison.v1",
            "identity_time_mass_valid": "exact",
            "position_absolute_tolerance_m": 1e-5,
            "velocity_absolute_tolerance_mps": 1e-4,
            "relative_tolerance": 1e-4,
            "tolerances_frozen": True,
        },
        "bundle": {"identity": {
            "expected": {"manifest": manifest, "checkpoint": checkpoint, "core_models": models},
            "observed": {
                "manifest": {"path": f"/{name}/dataset.json", "sha256": manifest},
                "checkpoint": {"path": f"/{name}/checkpoint.pt", "sha256": checkpoint},
                "core_models": {"path": f"/{name}/core_models.py", "sha256": models},
            },
        }},
        "case": {
            "physical_case_id": "fixture-physical",
            "lineage_group_id": "fixture-lineage",
            "family": "F3",
            "split": "validation",
            "hdf5_sha256_declared": _sha("hdf5"),
            "known_inputs_sha256": known,
        },
        "initial_state": state(0),
        "steps": [
            {"step": 0, "frame": 1, "state_after": state(1)},
            {"step": 1, "frame": 2, "state_after": state(2)},
        ],
        "trajectory_arrays": {
            "path": str(arrays_path),
            "sha256": runner.sha256_file(arrays_path),
            "frames": 3,
            "particle_count": 2,
            "dtype": "float64",
            "keys": ["position", "velocity", "time_s"],
        },
    }


def _write_pair(tmp_path, left, right):
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    left_path.write_text(json.dumps(left))
    right_path.write_text(json.dumps(right))
    return left_path, right_path


def test_float64_comparator_checks_actual_arrays_and_accepts_exact_pair(tmp_path):
    left = _report(tmp_path, "left")
    right = _report(tmp_path, "right")
    result = compare_reports(*_write_pair(tmp_path, left, right), expected_frames=3,
                             expected_particle_count=2)
    assert result["status"] == "pass"
    assert result["identity"]["passed"] is True
    assert result["arrays"]["passed"] is True
    assert result["arrays"]["numeric"]["position"]["violation_count"] == 0


def test_float64_comparator_reports_elementwise_position_and_velocity_failures(tmp_path):
    left = _report(tmp_path, "left")
    right = _report(tmp_path, "right", position_delta=5e-5, velocity_delta=2e-4)
    result = compare_reports(*_write_pair(tmp_path, left, right), expected_frames=3,
                             expected_particle_count=2)
    assert result["status"] == "fail"
    assert result["arrays"]["numeric"]["position"]["violation_count"] == 1
    assert result["arrays"]["numeric"]["velocity"]["violation_count"] == 1
    assert result["arrays"]["numeric"]["position"]["argmax_index"] == [2, 0, 0]


def test_float64_comparator_fails_closed_on_variant_identity_or_sidecar_metadata(tmp_path):
    left = _report(tmp_path, "left")
    right = copy.deepcopy(left)
    right["variant"] = "float32_regression"
    right["trajectory_arrays"]["dtype"] = "float32"
    result = compare_reports(*_write_pair(tmp_path, left, right), expected_frames=3,
                             expected_particle_count=2)
    assert result["status"] == "fail"
    assert "right:variant" in result["errors"]
    assert "right:trajectory_dtype_metadata" in result["errors"]
