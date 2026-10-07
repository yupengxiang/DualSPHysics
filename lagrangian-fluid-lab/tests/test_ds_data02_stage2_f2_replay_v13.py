"""Independent hand-expected tests for the v13 F2 replay operators."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import shutil
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ds_data02_stage2_f2_replay_v13 import (  # noqa: E402
    ReplayV13BindingError,
    adapt_v4_first_passage,
    adapt_v4_saved_bracket_events,
    evaluate_manual_predictions,
    evaluate_receiver_manual_predictions,
    event_label,
    flux,
    mass_observation,
    moving_rim_relative_velocity,
    normalized_mass_velocity,
    read_initial_csv_semantics,
    relocate_source_bound_request,
    replay_trajectory,
    receiver_volume_event_label,
    receiver_volume_mass_observation,
    residence,
    select_fluid_cohort,
    validate_observer_profile,
    validate_replay_request,
)


MOTION = next(Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2").glob(
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/*actual-gencase*/prepared/*_motion.dat"
))


def _fixture_request() -> dict:
    return {
        "schema": "ds02.stage2.f2-s1-replay-request.v13",
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
        "event_surface": {"kind": "open_rim_front_halfspace_observation", "frame": "world",
                          "origin_m": [0.5, 0.0, 0.0], "normal": [1.0, 0.0, 0.0],
                          "positive_side": "x_ge_origin_plane", "target_claim": "DIAGNOSTIC_HALFSPACE_ONLY"},
        "receiver_geometry": {
            "frame": "world", "source_role": "generated_xml", "mkbound": 1,
            "boxfill": "bottom | left | right | front | back",
            "volume_low_m": [0.5, -0.5, -0.5], "volume_size_m": [1.0, 1.0, 1.0],
            "top_aperture_z_m": 0.5, "top_aperture_xy_m": [[0.5, -0.5], [1.5, 0.5]],
            "side_entry_claim": "NO_APERTURE_CREDIT",
        },
        "initial_mass_denominator": {
            "initial_fluid_mass_kg": 10.0, "initial_missing_mass_kg": 0.0,
            "denominator_kg": 10.0,
        },
        "window": {"frame_start": 0, "frame_stop": 3, "expected_times_s": [0.0, 1.0, 2.0, 3.0]},
        "observer": {"position_scale_m": 1.0, "mass_quantiles": [0.5, 0.75, 0.9, 1.0],
                     "normalized_bin_edges": [-2.0, -1.0, 0.0, 1.0, 2.0]},
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


def test_v13_normalized_mass_velocity_and_explicit_missing_bucket():
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


def test_v13_replay_hand_expected_states_weighted_residence_flux_and_valid_mask():
    result = replay_trajectory(_fixture_trajectory(), _fixture_request())
    assert result["model_invoked"] is False
    assert result["quality"]["qualification"] == "UNKNOWN"
    assert result["event_summary"]["label_counts"] == {
        "observed": 1, "right_censored": 1, "failed_before_observation": 1, "initially_inside": 1
    }
    labels = {item["idp"]: item for item in result["labels"]}
    assert labels[10]["event_time_s"] == pytest.approx(1.5)
    assert labels[10]["first_saved_bracket_s"] == [1.0, 2.0]
    assert result["event_summary"]["residence_known_mass_time_kg_s_by_label"]["observed"] == pytest.approx(1.5)
    # Particle 2 has a missing final endpoint.  Its one per-particle net
    # interval is retained once; the two invalid brackets do not double-count.
    assert result["event_summary"]["net_flux_mass_kg"] == pytest.approx(1.0)
    assert result["event_summary"]["net_flux_status"] == "UNKNOWN_ENDPOINT_MEMBERSHIP_INTERVAL"
    assert result["event_summary"]["net_flux_interval_kg"] == pytest.approx([0.0, 3.0])
    assert result["event_summary"]["gross_flux_mass_kg"] is None
    assert result["event_summary"]["observed_gross_flux_mass_kg"] == pytest.approx(1.0)
    assert len(result["event_summary"]["unknown_flux_intervals"]) == 2
    assert result["frame_observations"][2]["later_invalid_or_missing_mass_bucket_kg"] == pytest.approx(3.0)
    assert result["frame_observations"][0]["velocity_frame"] == "world_inertial"


def test_v13_finite_invalid_particle_is_unknown_and_denominator_stays_frozen():
    obs = mass_observation(
        np.array([[0, 0, 0], [0.4, 0, 0]], dtype=float),
        np.array([1.0, 99.0]), np.zeros((2, 3)), denominator=3.0, missing_mass=0.0,
        valid=np.array([True, False]), initial_masses=np.array([1.0, 2.0]), pose=None,
        scale_m=1.0, quantiles=[1.0], bin_edges=[-1.0, 1.0])
    assert obs["known_mass_kg"] == pytest.approx(1.0)
    assert obs["later_invalid_or_missing_mass_bucket_kg"] == pytest.approx(2.0)
    assert obs["initial_mass_denominator_kg"] == pytest.approx(3.0)


def test_v13_event_adapter_and_real_multi_bracket_repeats():
    times = np.array([0.0, 1.0, 2.0, 3.0])
    with pytest.raises(ReplayV13BindingError, match="wrong saved bracket"):
        event_label(times, np.array([-1.0, -0.5, 0.5, 1.0]), np.ones(4, dtype=bool),
                    explicit_crossing_times=[1.5], expected_first_bracket_s=[0.0, 1.0])
    repeated = event_label(times, np.array([-1.0, 0.5, -0.5, 0.5]), np.ones(4, dtype=bool))
    assert repeated["later_sampled_forward_crossings_s"] == [pytest.approx(2.5)]
    adapted = adapt_v4_saved_bracket_events(
        [{"bracket_index": 0, "candidate_times_s": [0.5]},
         {"bracket_index": 2, "candidate_times_s": [2.5]}],
        [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]], 2)
    assert adapted["status"] == "observed"
    assert adapted["later_saved_crossing_times_s"] == [2.5]
    ambiguous = adapt_v4_saved_bracket_events(
        [{"bracket_index": 0, "candidate_times_s": [0.2, 0.8]}], [[0, 1], [1, 2]], 2)
    assert ambiguous["status"] == "ambiguous_multiple_crossing"
    unknown = adapt_v4_first_passage([0.5], [[0, 1], [1, 2]], 3)
    assert unknown["unresolved_recross_count"] == 2
    assert unknown["crossing_candidate_times_s"] == [0.5]
    with pytest.raises(ReplayV13BindingError, match="no recorded first"):
        adapt_v4_saved_bracket_events([], [[0, 1], [1, 2]], 2)
    with pytest.raises(ReplayV13BindingError, match="sorted"):
        adapt_v4_saved_bracket_events([{"bracket_index": 0, "candidate_times_s": [0.8, 0.2]}], [[0, 1]], 2)


def test_v13_mass_distribution_buckets_and_moving_position_transform():
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


def test_v13_receiver_volume_aperture_and_unknown_counterexamples():
    geometry = {
        "volume_low_m": [0.0, 0.0, 0.0], "volume_size_m": [1.0, 1.0, 1.0],
    }
    times = np.arange(4, dtype=float)
    velocity = np.zeros((4, 3))
    top_down = np.array([[0.5, 0.5, 1.2], [0.5, 0.5, 0.8], [0.5, 0.5, 0.4], [0.5, 0.5, 0.2]])
    label = receiver_volume_event_label(times, top_down, np.ones(4, dtype=bool), velocity, geometry)
    assert label["status"] == "observed"
    assert label["first_entry_surface"] == "top_aperture"
    assert label["aperture_downward_first"]["status"] == "OBSERVED_FINITE_TOP_APERTURE"
    assert label["final_destination_status"] == "inside_receiver_volume"
    edge = receiver_volume_event_label(times, np.array([[0.0, 0.0, 1.2], [0.0, 0.0, 0.8], [0.0, 0.0, 0.4], [0.0, 0.0, 0.2]]),
                                        np.ones(4, dtype=bool), velocity, geometry)
    assert edge["first_entry_surface"] == "top_aperture"
    assert edge["aperture_downward_first"]["x_y_m"] == pytest.approx([0.0, 0.0])
    side = receiver_volume_event_label(times, np.array([[-.2, .5, .5], [.2, .5, .5], [.8, .5, .5], [1.2, .5, .5]]),
                                        np.ones(4, dtype=bool), velocity, geometry)
    assert side["first_entry_surface"] == "side_or_bottom_boundary"
    assert side["side_entry_not_aperture"] is True
    outside_y = receiver_volume_event_label(times, np.array([[.5, 1.2, 1.2], [.5, 1.2, .8], [.5, 1.2, .4], [.5, 1.2, .2]]),
                                             np.ones(4, dtype=bool), velocity, geometry)
    assert outside_y["status"] == "right_censored"
    outside_z = receiver_volume_event_label(times, np.array([[.5, .5, 1.2], [.5, .5, 1.1], [.5, .5, 1.05], [.5, .5, 1.01]]),
                                             np.ones(4, dtype=bool), velocity, geometry)
    assert outside_z["status"] == "right_censored"
    recross = receiver_volume_event_label(times, np.array([[.5, .5, 1.2], [.5, .5, .8], [.5, .5, 1.2], [.5, .5, .8]]),
                                           np.ones(4, dtype=bool), velocity, geometry)
    assert len(recross["aperture_downward_events"]) == 2
    missing = receiver_volume_event_label(times, np.array([[.5, .5, 1.2], [.5, .5, .8], [.5, .5, .7], [.5, .5, .6]]),
                                           np.array([True, True, False, False]), velocity, geometry)
    assert missing["final_destination_status"] == "unknown_final_destination"
    mass = receiver_volume_mass_observation(
        np.array([[.5, .5, .5], [.5, .5, .5], [2.0, .5, .5]]),
        np.array([1.0, 2.0, 3.0]), np.array([True, False, True]), geometry)
    assert mass["receiver_volume_mass_kg"] == pytest.approx(1.0)
    assert mass["receiver_volume_unknown_mass_kg"] == pytest.approx(2.0)


def test_v13_receiver_outside_outside_crossing_and_invalid_earlier_candidate_are_unknown():
    geometry = {"volume_low_m": [0.0, 0.0, 0.0], "volume_size_m": [1.0, 1.0, 1.0]}
    times = np.array([0.0, 1.0, 2.0])
    velocity = np.zeros((3, 3))
    through = receiver_volume_event_label(
        times, np.array([[0.5, 0.5, 1.2], [0.5, 0.5, -0.2], [0.5, 0.5, -0.3]]),
        np.ones(3, dtype=bool), velocity, geometry)
    assert through["status"] == "ambiguous_multiple_crossing"
    assert through["event_time_s"] == pytest.approx(1.0 / 7.0)
    assert through["aperture_downward_first"]["status"] == "CANDIDATE_HIDDEN_INTERVAL"
    assert through["aperture_first_arrival_status"] == "UNKNOWN_HIDDEN_INTERVAL"
    after_invalid = receiver_volume_event_label(
        times, np.array([[0.5, 0.5, 1.2], [0.5, 0.5, 1.2], [0.5, 0.5, 0.8]]),
        np.array([False, True, True]), velocity, geometry)
    assert after_invalid["status"] == "failed_before_observation"
    assert after_invalid["aperture_downward_first"]["status"] == "CANDIDATE_AFTER_INVALID_OBSERVATION"
    assert after_invalid["aperture_first_arrival_status"] == "UNKNOWN_EARLIER_INVALID_FRAME"


def test_v13_real_initial_csv_identity_and_float32_nominal_boundary():
    csv_path = next(Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2").glob(
        "F2_STAGE1*/*actual804-initial*/*/initial.csv"))
    semantics = read_initial_csv_semantics(csv_path, cohort={
        "source_low_m": [0.05, -0.11, 0.7], "source_size_m": [0.325, 0.22, 0.264],
    })
    assert semantics["fluid_identity_count"] == 21114
    assert semantics["fluid_mk_counts"] == {"1": 7038, "2": 7038, "3": 7038}
    assert semantics["fluid_identity_set_sha256"] == "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
    assert semantics["nominal_box_diagnostic"]["decimal_float64_decoded_count"] == 19734
    assert semantics["nominal_box_diagnostic"]["native_float32_count"] == 20493
    assert semantics["nominal_box_diagnostic"]["selection_use"].startswith("DIAGNOSTIC_ONLY")


def test_v13_identity_cohort_keeps_lattice_endpoint_outside_nominal_box():
    positions = np.array([[0.38, 0.0, 0.7], [0.1, 0.0, 0.8]], dtype=np.float32)
    types = np.array([3, 3], dtype=np.int8)
    mks = np.array([1, 2], dtype=np.int8)
    zones = np.array([0, 0], dtype=np.int32)
    ids = np.array([100, 101], dtype=np.int32)
    masses = np.array([1.0, 1.0])
    from ds_data02_stage2_f2_replay_v13 import _identity_set_sha256
    cohort = {
        "selection": "initial_csv_type_mk_identity_set", "initial_type_code": 3,
        "initial_mk_codes": [1, 2, 3], "source_low_m": [0.05, -0.11, 0.7],
        "source_size_m": [0.325, 0.22, 0.264], "expected_initial_fluid_count": 2,
        "max_particles": None, "source_identity_set_sha256": _identity_set_sha256(zones, ids),
    }
    selected, summary = select_fluid_cohort(positions, types, mks, zones, ids, masses, cohort)
    assert selected.tolist() == [0, 1]
    assert summary["nominal_box_candidate_count"] == 1
    assert summary["nominal_box_excluded_count"] == 1


def test_v13_moving_rim_relative_velocity_is_explicit_and_separate_from_receiver():
    pose = {"angular_velocity_world_rad_s": [0.0, 0.0, 2.0], "translation_velocity_m_s": [0.1, 0.0, 0.0]}
    relative = moving_rim_relative_velocity([1.0, 0.0, 0.0], [0.1, 2.0, 0.0], pose, [0.0, 0.0, 0.0])
    assert np.allclose(relative, [0.0, 0.0, 0.0])


def test_v13_full_source_request_validates_without_hdf5_content_read():
    path = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/replay/v13/f2-s1-replay-request-v13-001.json"
    request = json.loads(path.read_text())
    bound = validate_replay_request(request)
    assert bound["_verified_hdf5"]["content_sha256"] is None
    assert bound["window"]["frame_stop"] == 400
    assert bound["initial_mass_denominator"]["denominator_kg"] == pytest.approx(21.114001002861187)
    assert bound["initial_mass_denominator"]["initial_missing_mass_kg"] == 0.0
    assert bound["receiver_geometry"]["volume_high_m"] == [1.66, 0.44, 0.45]
    wrong = json.loads(path.read_text())
    wrong["initial_mass_denominator"]["initial_missing_mass_kg"] = 0.003000000142492354
    wrong["initial_mass_denominator"]["denominator_kg"] = 21.11700100300368
    with pytest.raises(ReplayV13BindingError, match="initially absent"):
        validate_replay_request(wrong)
    wrong_scale = json.loads(path.read_text())
    wrong_scale["observer"]["velocity_scale_m_s"] = 0.15
    with pytest.raises(ReplayV13BindingError, match="velocity_scale"):
        validate_replay_request(wrong_scale)


def test_v13_flux_hidden_gross_multi_gap_and_nonfinite_mass_are_conservative():
    times = np.arange(5, dtype=float)
    # Endpoints are known outside, so net is exact even though a hidden
    # recrossing could have happened inside a saved bracket.
    hidden = flux(times, np.full(5, -1.0), np.ones(5, dtype=bool),
                  np.ones(5), initial_mass=2.0)
    assert hidden["net_flux_mass_kg"] == pytest.approx(0.0)
    assert hidden["gross_flux_mass_kg"] is None
    assert hidden["gross_flux_status"].startswith("UNKNOWN")
    # Two disconnected invalid gaps still produce one endpoint interval, and
    # no finite current mass is fabricated from NaN values.
    valid = np.array([True, False, True, False, False])
    distance = np.array([-1.0, -0.5, -0.4, -0.3, -0.2])
    masses = np.array([1.0, np.nan, 1.0, np.nan, np.nan])
    unknown = flux(times, distance, valid, masses, initial_mass=1.0)
    assert unknown["net_flux_mass_kg"] is None
    assert unknown["net_flux_interval_kg"] == pytest.approx([0.0, 1.0])
    assert unknown["unknown_flux_net_bound_kg"] == pytest.approx(1.0)
    assert unknown["observed_gross_flux_mass_kg"] == pytest.approx(0.0)
    assert len(unknown["unknown_flux_intervals"]) == 4
    both_missing = flux(times, np.array([np.nan, -0.5, 0.5, -0.5, np.nan]),
                        np.array([False, True, True, True, False]),
                        np.ones(5), initial_mass=1.0)
    assert both_missing["net_flux_interval_kg"] == pytest.approx([-1.0, 1.0])


def _fixture_profile(result: dict) -> dict:
    source = result["source_binding"]
    profile = {
        "schema": "ds02.stage2.f2-s1-observer-profile.v13",
        "profile_id": "fixture-profile",
        "frozen_before_reference": True,
        "scientific_status": "DEVELOPMENT_PREREGISTERED_UNKNOWN",
        "case_identity": {"family_id": "F2", "physical_case_id": "fixture"},
        "current_binding_sha256": source["current_catalog_sha256"],
        "trajectory_producer_sha256": source["trajectory_h5_producer_sha256"],
        "source_file_sha256": source["source_files"],
        "query_frame_indices": [0, 1, 2, 3],
        "query_times_s": [0.0, 1.0, 2.0, 3.0],
        "position_scale_m": 1.0,
        "event_time_scale_s": 4.0,
        "mass_quantiles": [0.5, 0.75, 0.9, 1.0],
        "normalized_bin_edges": [-2.0, -1.0, 0.0, 1.0, 2.0],
        "observable_names": ["mass_weighted_com_m", "mass_weighted_mean_velocity_m_s",
                             "mass_weighted_kinetic_energy_J", "mass_quantile_front_m",
                             "mass_distribution_fraction", "event_status", "event_time_s"],
        "velocity_scale_m_s": 1.0,
        "kinetic_energy_scale_J": 1.0,
        "mass_denominator_kg": 10.0,
        "thresholds": {"position_relative": 0.02, "mass_fraction": 0.03, "event_time_fraction": 0.01,
                       "velocity_relative": 0.03, "kinetic_energy_relative": 0.03,
                       "mass_front_relative": 0.02},
        "scientific_error_budget": {"time_integration_fraction": 0.25, "output_sampling_fraction": 0.25},
    }
    profile["sha256"] = hashlib.sha256(json.dumps({k: v for k, v in profile.items() if k != "sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return profile


def test_v13_manual_evaluator_binds_shape_time_source_and_frozen_thresholds():
    result = replay_trajectory(_fixture_trajectory(), _fixture_request())
    profile = _fixture_profile(result)
    validate_observer_profile(profile)
    frames = result["frame_observations"]
    predictions = {
        "source_binding": result["source_binding"],
        "observer_profile_sha256": profile["sha256"],
        "query_times_s": [0.0, 1.0, 2.0, 3.0],
        "mass_weighted_com_m": [x["mass_weighted_com_m"] for x in frames],
        "mass_weighted_mean_velocity_m_s": [x["mass_weighted_mean_velocity_m_s"] for x in frames],
        "mass_weighted_kinetic_energy_J": [x["mass_weighted_kinetic_energy_J"] for x in frames],
        "mass_quantile_front_m": [[x["mass_quantile_front_m"].get(str(q), 0.0) for q in [0.5, 0.75, 0.9, 1.0]] for x in frames],
        "mass_distribution_fraction": [[v / 10.0 for v in x["mass_distribution_kg"]] for x in frames],
        "event_status": [x["status"] for x in result["labels"]],
        "event_time_s": [x["event_time_s"] if x["status"] == "observed" else float("nan") for x in result["labels"]],
        "scientific_error_budget_estimate": {"time_integration_fraction": 0.0, "output_sampling_fraction": 0.0},
        "runtime_seconds": 999999.0, "output_bytes": 999999999,
    }
    scored = evaluate_manual_predictions(result, predictions, profile)
    assert scored["status"] == "PASS"
    bad = dict(predictions)
    bad["query_times_s"] = [0.0, 1.0, 2.0, 3.1]
    with pytest.raises(ReplayV13BindingError, match="query times"):
        evaluate_manual_predictions(result, bad, profile)
    bad = dict(predictions)
    bad["mass_weighted_com_m"] = np.zeros((3, 3)).tolist()
    with pytest.raises(ReplayV13BindingError, match="shape"):
        evaluate_manual_predictions(result, bad, profile)
    bad_profile = dict(profile)
    bad_profile["thresholds"] = dict(profile["thresholds"], event_time_fraction=float("inf"))
    bad_profile["sha256"] = hashlib.sha256(json.dumps({k: v for k, v in bad_profile.items() if k != "sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ReplayV13BindingError, match="threshold"):
        validate_observer_profile(bad_profile)
    bad_profile = dict(profile)
    bad_profile["thresholds"] = dict(profile["thresholds"], mass_fraction=0.9)
    bad_profile["sha256"] = hashlib.sha256(json.dumps({k: v for k, v in bad_profile.items() if k != "sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ReplayV13BindingError, match="threshold"):
        validate_observer_profile(bad_profile)


def test_v13_scientific_error_shares_gate_science_not_runtime_or_output():
    result = replay_trajectory(_fixture_trajectory(), _fixture_request())
    profile = _fixture_profile(result)
    frames = result["frame_observations"]
    predictions = {
        "source_binding": result["source_binding"], "observer_profile_sha256": profile["sha256"],
        "query_times_s": [0.0, 1.0, 2.0, 3.0],
        "mass_weighted_com_m": [x["mass_weighted_com_m"] for x in frames],
        "mass_weighted_mean_velocity_m_s": [x["mass_weighted_mean_velocity_m_s"] for x in frames],
        "mass_weighted_kinetic_energy_J": [x["mass_weighted_kinetic_energy_J"] for x in frames],
        "mass_quantile_front_m": [[x["mass_quantile_front_m"].get(str(q), 0.0) for q in [0.5, .75, .9, 1.0]] for x in frames],
        "mass_distribution_fraction": [[v / 10.0 for v in x["mass_distribution_kg"]] for x in frames],
        "event_status": [x["status"] for x in result["labels"]],
        "event_time_s": [x["event_time_s"] if x["status"] == "observed" else float("nan") for x in result["labels"]],
        "scientific_error_budget_estimate": {"time_integration_fraction": .26, "output_sampling_fraction": 0.0},
        "runtime_seconds": 0.0, "output_bytes": 0,
    }
    scored = evaluate_manual_predictions(result, predictions, profile)
    assert scored["status"] == "FAIL"
    assert scored["checks"]["time_integration_budget"] is False


def test_v13_receiver_evaluator_binds_ids_unknown_candidates_and_mass_weights():
    result = replay_trajectory(_fixture_trajectory(), _fixture_request())
    profile = _fixture_profile(result)
    receiver = [item["receiver_volume_label"] for item in result["labels"]]
    predictions = {
        "observer_scope": "finite_receiver_volume_and_top_aperture_v13",
        "source_binding": result["source_binding"],
        "observer_profile_sha256": profile["sha256"],
        "identity": [[item["zone"], item["idp"]] for item in result["labels"]],
        "receiver_event_status": [item["status"] for item in receiver],
        "aperture_event_status": [item["aperture_first_arrival_status"] for item in receiver],
        "final_destination_status": [item["final_destination_status"] for item in receiver],
        "receiver_event_time_s": [item["event_time_s"] if item["status"] == "observed" else float("nan") for item in receiver],
        "aperture_event_time_s": [float("nan")] * len(receiver),
        "destination_mass_fraction": [0.5, 0.2, 0.3],
    }
    scored = evaluate_receiver_manual_predictions(result, predictions, profile)
    assert scored["status"] == "PASS"
    bad = dict(predictions)
    bad["identity"] = list(reversed(predictions["identity"]))
    with pytest.raises(ReplayV13BindingError, match="identity/order"):
        evaluate_receiver_manual_predictions(result, bad, profile)
    bad = dict(predictions)
    bad["aperture_event_time_s"] = [0.0] * len(receiver)
    with pytest.raises(ReplayV13BindingError, match="unknown aperture"):
        evaluate_receiver_manual_predictions(result, bad, profile)


def test_v13_portable_relocation_hashes_small_sources_and_rejects_mutations(tmp_path):
    source = MOTION.read_bytes()
    moved = tmp_path / "relocated" / "motion.dat"
    moved.parent.mkdir()
    moved.write_bytes(source)
    os.utime(moved, ns=(MOTION.stat().st_atime_ns, MOTION.stat().st_mtime_ns + 123456789))
    request = _fixture_request()
    relocated = relocate_source_bound_request(request, {"motion_dat": str(moved)})
    assert relocated["source_files"][0]["path"] == str(moved.resolve())
    assert relocated["relocation"]["status"].startswith("PORTABLE_STAT_MIGRATION")
    bad = tmp_path / "relocated" / "same-size-wrong.dat"
    altered = bytearray(source); altered[0] ^= 1; bad.write_bytes(altered)
    with pytest.raises(ReplayV13BindingError, match="SHA-256"):
        relocate_source_bound_request(request, {"motion_dat": str(bad)})
    with pytest.raises(ReplayV13BindingError, match="missing"):
        relocate_source_bound_request(request, {"motion_dat": str(tmp_path / "MOTION.DAT")})
    original_h5 = tmp_path / "original.h5"
    relocated_h5 = tmp_path / "relocated" / "trajectory.h5"
    original_h5.write_bytes(b"portable-hdf5-producer-attested-bytes")
    relocated_h5.write_bytes(original_h5.read_bytes())
    os.utime(original_h5, ns=(original_h5.stat().st_atime_ns, original_h5.stat().st_mtime_ns - 123456789))
    request["trajectory_h5"] = {
        "path": str(original_h5), "bytes": original_h5.stat().st_size,
        "mtime_ns": original_h5.stat().st_mtime_ns,
        "producer_declared_sha256": "a" * 64,
        "hash_mode": "producer_attested_only_no_content_hash",
    }
    request["portable_migration"] = {
        "expected_trajectory_content_sha256": hashlib.sha256(original_h5.read_bytes()).hexdigest(),
    }
    migrated = relocate_source_bound_request(request, {
        "motion_dat": str(moved), "trajectory_h5": str(relocated_h5)})
    assert migrated["trajectory_h5"]["path"] == str(relocated_h5.resolve())
    assert migrated["trajectory_h5"]["mtime_ns"] == relocated_h5.stat().st_mtime_ns
    assert migrated["relocation"]["trajectory_h5"]["producer_declared_sha256"] == "a" * 64
    wrong_h5 = tmp_path / "relocated" / "same-size-wrong.h5"
    altered_h5 = bytearray(original_h5.read_bytes()); altered_h5[0] ^= 1; wrong_h5.write_bytes(altered_h5)
    with pytest.raises(ReplayV13BindingError, match="content SHA-256"):
        relocate_source_bound_request(request, {"trajectory_h5": str(wrong_h5)})
