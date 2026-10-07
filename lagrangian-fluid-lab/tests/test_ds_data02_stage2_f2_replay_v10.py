"""Independent hand-expected tests for the v10 F2 replay operators."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ds_data02_stage2_f2_replay_v10 import (  # noqa: E402
    ReplayV10BindingError,
    event_label,
    adapt_v4_first_passage,
    flux,
    mass_observation,
    normalized_mass_velocity,
    read_motion_dat,
    replay_trajectory,
    residence,
    validate_replay_request,
)


MOTION = next(Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2").glob(
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/*actual-gencase*/prepared/*_motion.dat"
))


def _fixture_request() -> dict:
    return {
        "schema": "ds02.stage2.f2-s1-replay-request.v10",
        "status": "MANUFACTURED_ONLY",
        "fixture_mode": True,
        "role": "DEVELOPMENT",
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "case_identity": {"family_id": "manufactured", "physical_case_id": "fixture", "runtime_case_alias": "fixture"},
        "source_files": [{"role": "motion_dat", "path": str(MOTION),
                          "sha256": hashlib.sha256(MOTION.read_bytes()).hexdigest()}],
        "cohort": {
            "selection": "all_fluid_in_initial_source_region", "initial_type_code": 3,
            "initial_mk_codes": [1, 2, 3], "source_low_m": [-2.0, -2.0, -2.0],
            "source_size_m": [5.0, 5.0, 5.0], "expected_initial_fluid_count": None,
            "max_particles": None,
        },
        "geometry": {
            "fluid_source_low_m": [-2.0, -2.0, -2.0], "fluid_source_size_m": [5.0, 5.0, 5.0],
            "moving_axis_p1_m": [0.0, -1.0, 0.65], "moving_axis_p2_m": [0.0, 1.0, 0.65],
            "motion_angles_units": "degrees", "motion_duration_s": 4.0,
        },
        "event_surface": {"kind": "receiver_front_halfspace", "frame": "world",
                          "origin_m": [0.5, 0.0, 0.0], "normal": [1.0, 0.0, 0.0],
                          "positive_side": "receiver_target"},
        "initial_mass_denominator": {
            "initial_fluid_mass_kg": 10.0, "initial_missing_mass_kg": 0.0,
            "denominator_kg": 10.0,
        },
        "window": {"frame_start": 0, "frame_stop": 3, "expected_times_s": [0.0, 1.0, 2.0, 3.0]},
        "observer": {"position_scale_m": 1.0, "mass_quantiles": [0.5, 1.0],
                     "normalized_bin_edges": [-2.0, 0.0, 2.0]},
    }


def _fixture_trajectory() -> dict:
    # Particle 0 crosses at 1.5 s; 1 is right-censored; 2 becomes missing;
    # 3 starts on the target side.  This is independent of the implementation.
    x = np.array([
        [-1.0, -1.0, -1.0, 1.0],
        [0.0, -0.8, -0.5, 1.0],
        [1.0, -0.7, np.nan, 1.0],
        [1.5, -0.6, np.nan, 1.0],
    ])
    positions = np.zeros((4, 4, 3))
    positions[:, :, 0] = x
    velocity = np.zeros_like(positions)
    velocity[:, 0, 0] = 1.0
    velocity[:, 1, 0] = 0.1
    velocity[:, 2, 0] = 0.1
    velocity[:, 3, 0] = 0.0
    return {
        "time": np.arange(4, dtype=float),
        "position": positions, "velocity": velocity,
        "mass": np.ones((4, 4), dtype=float) * np.array([1.0, 2.0, 3.0, 4.0]),
        "valid": np.array([[1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 0, 1], [1, 1, 0, 1]], dtype=bool),
        "initial_position": positions[0],
        "initial_type": np.array([3, 3, 3, 3], dtype=np.int8),
        "initial_mk": np.array([1, 2, 1, 3], dtype=np.int16),
        "particle_zone": np.zeros(4, dtype=np.int16),
        "particle_id": np.array([10, 11, 12, 13], dtype=np.uint32),
        "initial_mass": np.array([1.0, 2.0, 3.0, 4.0]),
    }


def test_v10_normalized_mass_velocity_and_explicit_missing_bucket():
    velocities = np.array([[1.0, 0, 0], [3.0, 0, 0], [5.0, 0, 0]])
    masses = np.array([1.0, 2.0, 7.0])
    mean, ke, known, missing = normalized_mass_velocity(velocities, masses)
    assert np.allclose(mean, [4.2, 0, 0])
    assert ke == pytest.approx(97.0)
    assert known == pytest.approx(10.0)
    assert missing == pytest.approx(0.0)
    scaled_mean, scaled_ke, _, _ = normalized_mass_velocity(velocities, masses * 7)
    assert np.allclose(scaled_mean, mean)
    assert scaled_ke == pytest.approx(679.0)
    velocities[1, :] = np.nan
    partial, partial_ke, partial_mass, partial_missing = normalized_mass_velocity(velocities, masses)
    assert np.allclose(partial, [4.5, 0, 0])
    assert partial_ke == pytest.approx(88.0)
    assert partial_mass == pytest.approx(8.0)
    assert partial_missing == pytest.approx(2.0)


def test_v10_replay_hand_expected_states_residence_flux_and_body_velocity_semantics():
    result = replay_trajectory(_fixture_trajectory(), _fixture_request())
    assert result["model_invoked"] is False
    assert result["quality"]["qualification"] == "UNKNOWN"
    assert result["event_summary"]["label_counts"] == {
        "observed": 1, "right_censored": 1, "failed_before_observation": 1, "initially_inside": 1
    }
    labels = {item["idp"]: item for item in result["labels"]}
    assert labels[10]["event_time_s"] == pytest.approx(1.5)
    assert labels[10]["first_saved_bracket_s"] == [1.0, 2.0]
    assert result["event_summary"]["residence_known_s_by_label"]["observed"] == pytest.approx(1.5)
    assert result["event_summary"]["net_flux_mass_kg"] == pytest.approx(1.0)
    assert result["event_summary"]["unknown_flux_mass_kg"] > 0.0
    assert result["event_summary"]["unknown_flux_intervals"]
    assert result["frame_observations"][0]["velocity_frame"] == "world_inertial"
    assert "never relabeled" in result["frame_observations"][0]["velocity_semantics"]


def test_v10_event_adapter_rejects_wrong_first_bracket_and_time_but_keeps_later_recross_unknown():
    times = np.array([0.0, 1.0, 2.0, 3.0])
    initial_missing = event_label(times, np.array([-1.0, -0.5, 0.5, 1.0]),
                                  np.array([False, False, False, False]))
    assert initial_missing["status"] == "failed_before_observation"
    with pytest.raises(ReplayV10BindingError, match="wrong saved bracket"):
        event_label(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool),
                    explicit_crossing_times=[1.5], expected_first_bracket_s=[0.0, 1.0])
    with pytest.raises(ReplayV10BindingError, match="event time"):
        event_label(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool),
                    explicit_crossing_times=[1.5], expected_event_time_s=1.4)
    repeated = event_label(times, np.array([-1.0, 0.5, -0.5, 0.5]), np.ones(4, dtype=bool))
    assert repeated["status"] == "observed"
    assert repeated["first_saved_bracket_s"] == [0.0, 1.0]
    assert repeated["later_sampled_forward_crossings_s"] == [pytest.approx(2.5)]
    unknown_speed = event_label(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool),
                                velocities=np.array([[0, 0, 0], [np.nan, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=float))
    assert unknown_speed["status"] == "observed"
    assert unknown_speed["relative_normal_speed_m_s"] is None
    assert unknown_speed["velocity_status"] == "UNKNOWN_VELOCITY"
    ambiguous = event_label(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool),
                            explicit_crossing_times=[1.2, 1.8])
    assert ambiguous["status"] == "ambiguous_multiple_crossing"
    adapted = adapt_v4_first_passage([0.5], [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]], crossing_count=3)
    assert adapted["status"] == "observed"
    assert adapted["unresolved_recross_count"] == 2
    with pytest.raises(ReplayV10BindingError, match="outside first"):
        adapt_v4_first_passage([1.5], [[0.0, 1.0], [1.0, 2.0]], crossing_count=1)
    assert adapt_v4_first_passage([1.2, 1.8], [[0.0, 2.0], [2.0, 3.0]], crossing_count=2)["status"] == "ambiguous_multiple_crossing"


def test_v10_mass_distribution_buckets_and_moving_position_transform():
    result = mass_observation(
        np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=float),
        np.array([1.0, 2.0, 7.0]), np.array([[1, 0, 0], [3, 0, 0], [5, 0, 0]], dtype=float),
        denominator=10.0, missing_mass=0.0,
        pose={"rotation_matrix": np.eye(3), "translation_m": [0, 0, 0]},
        scale_m=1.0, quantiles=[0.5, 1.0], bin_edges=[0.0, 1.0, 2.0],
    )
    assert result["mass_distribution_kg"] == [1.0, 9.0]
    assert result["mass_quantile_front_m"]["0.5"] == pytest.approx(2.0)
    assert result["mass_weighted_mean_velocity_m_s"] == [4.2, 0.0, 0.0]
    assert result["velocity_frame"] == "world_inertial"
    assert result["position_frame"] == "body"


def test_v10_source_request_validates_without_hdf5_content_read():
    path = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/replay/v10/f2-s1-replay-request-v10-001.json"
    request = json.loads(path.read_text())
    bound = validate_replay_request(request)
    assert bound["_verified_hdf5"]["content_sha256"] is None
    assert bound["window"]["frame_stop"] == 21
