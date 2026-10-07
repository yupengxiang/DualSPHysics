"""Independent v9 mass, SO(3), source-contract, and counterexample tests."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ds_data02_stage2_observer_v9 import (  # noqa: E402
    ObserverV9BindingError,
    bind_first_passage_first_bracket,
    euler_wrap_error_degrees,
    manufactured_mass_calibration,
    manufactured_so3_calibration,
    observe_mass_point_cloud,
    observe_rigid_pose,
    points_in_frame,
    quaternion_to_matrix,
    so3_geodesic_angle_rad,
    validate_observation_contract,
    validate_profile,
)


def _profile() -> dict:
    return {
        "schema": "ds02.stage2.reference-observer-profile.v9",
        "profile_id": "manufactured-v9",
        "role": "DEVELOPMENT",
        "frozen": True,
        "family_id": "infra",
        "physical_case_id": "manufactured",
        "source_files": [{"role": "fixture", "path": "/tmp/fixture.json", "sha256": "a" * 64}],
        "characteristic_scales_m": {"position": 2.0, "mass_distribution": 2.0, "feature_time": 4.0},
        "mass_quantiles": [0.5, 0.75, 1.0],
        "mass_distribution": {
            "axis": "x", "normalized_bin_edges": [-1.0, 0.0, 1.0],
            "physical_scale_m": 2.0,
            "boundary_policy": "lower-inclusive and upper-exclusive except final upper-inclusive",
        },
        "frame_policy": {"moving_frame": "REQUIRE_EXPLICIT_POSE"},
        "observation_contract": {
            "query_times_s": [0.0, 1.0], "feature_time_s": 4.0,
            "fixed_observation_names": ["mass", "com"],
            "shapes": {"mass": [2], "com": [2, 3]},
            "fixed_scales": {"position_m": 2.0, "mass_distribution_m": 2.0, "feature_time_s": 4.0},
        },
        "tolerance_profile": {"mutable": False},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def test_v9_mass_calibration_has_hand_calculated_buckets_and_unequal_weights():
    calibration = manufactured_mass_calibration()
    assert calibration["mass_status"] == "PASS"
    observed = observe_mass_point_cloud(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], [1.0, 3.0], axis="x",
        quantiles=[0.5, 1.0], physical_scale_m=1.0,
        normalized_bin_edges=[0.0, 1.0, 2.0], initial_mass_denominator_kg=4.0,
        velocities=[[1.0, 0.0, 0.0], [float("nan"), 0.0, 0.0]],
    )
    assert observed["mass_distribution_kg"] == [1.0, 3.0]
    assert observed["velocity_observation_status"] == "PARTIAL_VELOCITY_OBSERVATION_EXPLICIT_BUCKET"
    assert observed["velocity_missing_mass_from_rows_kg"] == 3.0


def test_v9_mass_rejects_wrong_shape_denominator_and_bad_moving_pose():
    with pytest.raises(ObserverV9BindingError, match="shape"):
        observe_mass_point_cloud([[0.0, 0.0]], [1.0], axis="x", quantiles=[0.5],
                                 physical_scale_m=1.0, normalized_bin_edges=[0.0, 1.0],
                                 initial_mass_denominator_kg=1.0)
    with pytest.raises(ObserverV9BindingError, match="exceeds"):
        observe_mass_point_cloud([[0.0, 0.0, 0.0]], [2.0], axis="x", quantiles=[0.5],
                                 physical_scale_m=1.0, normalized_bin_edges=[0.0, 1.0],
                                 initial_mass_denominator_kg=1.0)
    with pytest.raises(ObserverV9BindingError, match="orthonormal"):
        points_in_frame([[1.0, 0.0, 0.0]], source_frame="world", target_frame="body",
                        pose={"rotation_matrix": [[1.0, 0.1, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                              "translation_m": [0.0, 0.0, 0.0]})


def test_v9_moving_frame_translation_rotation_is_explicit_and_reproducible():
    angle = np.pi / 2.0
    rotation = [[np.cos(angle), -np.sin(angle), 0.0],
                [np.sin(angle), np.cos(angle), 0.0], [0.0, 0.0, 1.0]]
    body = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    world = (np.asarray(rotation) @ body.T).T + np.asarray([2.0, 3.0, 4.0])
    recovered = points_in_frame(world, source_frame="world", target_frame="body",
                                pose={"rotation_matrix": rotation, "translation_m": [2.0, 3.0, 4.0]})
    assert np.allclose(recovered, body, atol=1e-12)
    with pytest.raises(ObserverV9BindingError, match="pose cannot"):
        points_in_frame(world, pose={"rotation_matrix": rotation, "translation_m": [2.0, 3.0, 4.0]})


def test_v9_so3_calibration_and_pose_errors_reject_nonorthogonal_data():
    calibration = manufactured_so3_calibration()
    assert calibration["so3_status"] == "PASS"
    q = [np.sqrt(0.5), 0.0, 0.0, np.sqrt(0.5)]
    assert np.allclose(quaternion_to_matrix(q), quaternion_to_matrix([-x for x in q]))
    assert np.isclose(so3_geodesic_angle_rad(np.eye(3), quaternion_to_matrix([0.0, 1.0, 0.0, 0.0])), np.pi)
    assert euler_wrap_error_degrees([359.0, 0.0, -179.0], [-1.0, 0.0, 181.0]) == [0.0, 0.0, 0.0]
    with pytest.raises(ObserverV9BindingError, match="orthonormal"):
        observe_rigid_pose({"position_m": [0, 0, 0], "rotation_matrix": np.eye(3)},
                           {"position_m": [0, 0, 0], "rotation_matrix": [[1, .1, 0], [0, 1, 0], [0, 0, 1]]})


def test_v9_contract_rejects_empty_short_wrong_shape_scale_and_feature_time():
    profile = _profile()
    assert validate_profile(profile)["profile_id"] == "manufactured-v9"
    good = {"query_times_s": [0.0, 1.0], "mass": [1.0, 2.0],
            "com": [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
            "scales": {"position_m": 2.0, "mass_distribution_m": 2.0, "feature_time_s": 4.0},
            "feature_time_s": 4.0}
    assert validate_observation_contract(profile, good)["status"] == "PASS_FROZEN_CONTRACT"
    for key, value, error in (
        ("query_times_s", [], "query_times"),
        ("query_times_s", [0.0], "differ"),
        ("mass", [1.0], "shape"),
        ("scales", {"position_m": 4.0, "mass_distribution_m": 2.0, "feature_time_s": 4.0}, "scale"),
        ("feature_time_s", 3.0, "feature_time"),
    ):
        bad = dict(good)
        bad[key] = value
        with pytest.raises(ObserverV9BindingError, match=error):
            validate_observation_contract(profile, bad)


def test_v9_first_passage_requires_first_candidate_first_bracket_and_no_ambiguous_pair():
    good = bind_first_passage_first_bracket(crossing_times_s=[0.4, 1.5],
                                            saved_brackets=[[0.0, 1.0], [1.0, 2.0]])
    assert good["event_time_s"] == 0.4
    with pytest.raises(ObserverV9BindingError, match="first saved bracket"):
        bind_first_passage_first_bracket(crossing_times_s=[1.4], saved_brackets=[[0.0, 1.0], [1.0, 2.0]])
    with pytest.raises(ObserverV9BindingError, match="multiple"):
        bind_first_passage_first_bracket(crossing_times_s=[0.4, 0.8], saved_brackets=[[0.0, 1.0], [1.0, 2.0]])
    with pytest.raises(ObserverV9BindingError, match="first crossing"):
        bind_first_passage_first_bracket(crossing_times_s=[0.4], saved_brackets=[[0.0, 0.3], [0.3, 1.0]])
