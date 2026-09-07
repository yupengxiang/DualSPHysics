"""Independent CPU-only tests for the R3 geometry contract probes."""

from __future__ import annotations

import numpy as np

from diagnostics.r3_geometry_contracts.probe import (
    build_g4_model_input,
    build_report,
    build_support_diagnostic,
    dynamic_triangle_diagnostic,
    run_mixed_label_diagnostic,
    swept_wall_diagnostic,
    validate_model_input_contract,
)


def test_rigid_triangle_uses_pose_interpolation_and_preserves_geometry():
    result = dynamic_triangle_diagnostic()
    assert result["incorrect_vertex_lerp"]["rigidity_preserved"] is False
    assert result["incorrect_vertex_lerp"]["max_edge_length_abs_error_m"] > 0.2
    assert result["candidate_rigid_pose"]["rigidity_preserved"] is True
    assert result["candidate_rigid_pose"]["max_edge_length_abs_error_m"] < 1e-10
    assert result["interpolation_methods"]["candidate_rigid_pose"]


def test_midpoint_wall_snapshot_misses_swept_collision():
    result = swept_wall_diagnostic()
    assert result["endpoint_hits"] == {"t0": False, "t1": False}
    assert result["midpoint_wall_hit"] is False
    assert result["swept_wall_hit"] is True
    assert result["failure_detected_by_midpoint_only"] is True
    assert 0.20 < result["first_hit_time_normalized"] < 0.30
    assert result["check_kind"] == "space_time_swept_wall_candidate_check"


def test_support_reports_effective_size_geometry_and_reconstruction_not_count_gate():
    result = build_support_diagnostic()
    assert result["formal_gate"]["neighbour_count_used_as_gate"] is False
    assert result["formal_gate"]["threshold"] is None
    for case in result["cases"].values():
        assert case["effective_sample_size"] > 0.0
        assert "support_geometry" in case
        assert "absolute_error_mps" in case["interpolation_reconstruction"]
        assert case["formal_neighbour_threshold"] is None
    comparison = result["count_comparison"]
    assert comparison["isotropic_23_selected"] == 23
    assert comparison["one_sided_24_selected"] == 24
    assert comparison["one_sided_24_error_mps"] > comparison["isotropic_23_error_mps"]
    assert comparison["one_sided_24_anisotropy"] < comparison["isotropic_23_anisotropy"]


def test_mixed_labels_are_not_a_permanent_filter_and_counterexamples_are_present():
    result = run_mixed_label_diagnostic()
    assert result["source_label_contract"]["permanent_post_mixing_filter"] is False
    disconnected = result["disconnected_blobs"]
    assert disconnected["geometry_only_non_identifiable"] is True
    assert disconnected["all_visible_interpolation"]["visible_cross_source_count"] > 0
    assert disconnected["same_blob_label_oracle"]["estimated_velocity_mps"] == [0.0, 1.0, 0.0]
    blocked = result["blocked_samples"]
    assert blocked["blocked_cross_source_samples"] > 0
    assert blocked["wall_aware_interpolation"]["source_label_filter_applied"] is False
    opening = result["open_samples"]
    assert opening["cross_source_sample_through_opening_retained"] is True
    assert opening["wall_aware_interpolation"]["source_label_filter_applied"] is False


def test_g4_same_aabb_is_non_identifiable_but_component_features_are_explicit():
    result = build_g4_model_input()
    names = result["same_aabb_cases"]
    assert result["aabb_summary"][names[0]] == result["aabb_summary"][names[1]]
    assert result["aabb_only_boundary_summary_non_identifiable"] is True
    assert result["component_feature_difference_detected"] is True
    for name in names:
        assert result["model_input_validation"][name]["valid"] is True
        features = result["model_inputs"][name]["boundary_component_features"]
        assert features
        assert {
            "distance_to_boundary_component_m",
            "boundary_normal",
            "boundary_type",
            "wall_velocity_mps",
        }.issubset(features[0])
    assert result["prescribed_control_validation"]["accepted"] is True
    assert result["future_state_negative_control"]["valid"] is False
    assert result["future_state_negative_control"]["forbidden_future_state_keys"]
    stats = result["validation_statistics"]
    assert stats["reported_from_all_checks"] is True
    assert stats["success_only_summary_forbidden"] is True
    assert stats["failure_count"] == len(stats["failed_check_ids"])
    assert stats["failure_count"] == 1
    assert stats["candidate_representation_failure_count"] == 1
    assert result["aabb_only_failure_statistics"]["aabb_only_failure_count"] == 1


def test_model_input_contract_rejects_future_fluid_or_free_body_state():
    valid = {
        "particle_position_m": [0.0, 0.0, 0.0],
        "boundary_component_features": [{
            "distance_to_boundary_component_m": 0.1,
            "boundary_normal": [1.0, 0.0, 0.0],
            "boundary_type": "baffle",
            "wall_velocity_mps": [0.0, 0.0, 0.0],
        }],
        "control": {"prescribed_angular_velocity_radps": [0.0, 0.0, 0.5]},
    }
    assert validate_model_input_contract(valid)["valid"] is True
    invalid = dict(valid)
    invalid["future_free_body_state"] = {"pose": [1.0, 0.0, 0.0]}
    check = validate_model_input_contract(invalid)
    assert check["valid"] is False
    assert "future_free_body_state" in check["forbidden_future_state_keys"]


def test_full_report_is_cpu_only_candidate_only_and_serializable():
    report = build_report()
    assert report["candidate_only"] is True
    assert report["acceptance_status"] == "candidate_only_rejected"
    assert report["compute"]["gpu_used"] is False
    assert report["compute"]["cfd_solver_run"] is False
    assert report["compute"]["production_tracer_imported"] is False
    assert report["headline"]["swept_wall_midpoint_failure_detected"] is True
    assert report["headline"]["g4_aabb_only_non_identifiable"] is True
