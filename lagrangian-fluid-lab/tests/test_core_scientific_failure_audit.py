import json

import h5py
import numpy as np

from scripts.core_scientific_failure_audit import (
    POLICY,
    _closed_face_endpoint_events,
    audit_host,
    compare_failure_aware,
)


BOUNDS = {"xmin": -0.45, "xmax": 0.45, "ymin": -0.09, "ymax": 0.09, "zmin": 0.0, "zmax": 0.51}


def test_closed_faces_filter_open_top_and_inactive_particles():
    position = np.array([
        [-0.5, 0.0, 0.2],  # closed left face
        [0.0, 0.0, 0.8],   # open top
        [-0.5, 0.0, 0.2],  # inactive
    ])
    result = _closed_face_endpoint_events(position, np.array([True, True, False]), bounds=BOUNDS, tolerance=1e-9)
    assert result["count"] == 1
    assert result["by_face"]["left"] == 1
    assert result["by_face"]["bottom"] == 0


def test_audit_censors_after_first_wall_event_with_fixed_denominator(tmp_path):
    receipt_path = tmp_path / "rollout.json"
    trajectory_path = tmp_path / "rollout.h5"
    expected = 4
    receipt_path.write_text(json.dumps({
        "status": "complete",
        "position_rmse": [0.0] * expected,
        "velocity_rmse": [0.0] * expected,
        "physics_frames": [{"wall_chord": {"particle_count": 1 if frame == 2 else 0}} for frame in range(1, expected + 1)],
        "score": {"expected_frames": expected, "executed": True, "complete": True},
    }))
    position = np.zeros((expected + 1, 2, 3), dtype=np.float32)
    position[:, :, 2] = 0.2
    position[1:, :, 0] = 0.0
    position[2, 0, 0] = -0.5
    velocity = np.zeros_like(position)
    valid = np.ones((expected + 1, 2), dtype=np.bool_)
    with h5py.File(trajectory_path, "w") as handle:
        handle.create_dataset("time", data=np.arange(expected + 1, dtype=np.float64))
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("mass", data=np.ones(2, dtype=np.float64))

    result = audit_host(receipt_path, trajectory_path, bounds=BOUNDS, length_m=0.9, speed_mps=2.0)
    score = result["failure_aware_score"]
    assert result["events"]["selected"]["category"] == "finite_wall_penetration"
    assert result["events"]["selected"]["first_failure_frame"] == 2
    assert score["finite_prefix_frames"] == 1
    assert score["censored_after_first_failure_frames"] == 3
    assert score["selection_score"] == 0.75
    assert score["complete"] is False
    assert result["execution_complete"] is True
    assert result["finite_rollout_complete"] is True
    assert result["failure_category"] is None
    assert result["first_failure_frame"] is None
    assert result["scientific_status"] == "failed"
    assert result["scientific_failure_category"] == "finite_wall_penetration"
    assert result["scientific_first_failure_frame"] == 2


def test_failure_identity_uses_first_event_even_if_later_counts_diverge():
    def row(total):
        return {
            "events": {"selected": {
                "category": "finite_wall_penetration",
                "first_failure_frame": 15,
                "wall_chord_particle_count": 124,
                "wall_chord_particle_count_total": total,
            }},
            "failure_aware_score": {
                "selection_score": 0.9,
                "raw_position_rmse_frame_mean_m": 0.1,
                "raw_velocity_rmse_frame_mean_mps": 0.2,
            },
        }

    result = compare_failure_aware(row(39038), row(39040))
    assert result["failure_event_identity_equal"] is True
    assert result["score_within_registered_comparison_atol"] is True


def test_state_magnitude_has_no_implicit_scientific_threshold():
    assert POLICY["release_state"].startswith("candidate_only")
    assert POLICY["state_magnitude"]["status"] == "diagnostic_only"
    assert POLICY["state_magnitude"]["threshold"] is None
