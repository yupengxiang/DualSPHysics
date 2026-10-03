"""Unit tests for DS-DATA-02 F6 Geometry-Based Orientation Reader & Cross-DP Evaluator (v1).

Tests execute exclusively on deterministic synthetic mock fixtures generated in pytest tmp_path.
Zero access to actual campaign data or actual solver CSVs.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from scripts.ds_data02_f6_geometry_orientation_reader_v1 import (
    build_geometry_orientation_report,
    compute_kabsch_svd,
    compute_so3_geodesic_distance,
    interpolate_pose_at_physical_time,
    load_partvtk_series,
    parse_partvtk_floating_csv,
    quaternion_slerp,
    quaternion_to_matrix,
    matrix_to_quaternion,
    validate_center_against_floating_info,
    compare_trajectories_physical_time,
    L_CHAR_M,
    U_CHAR_M_S,
)
from tests.fixtures.synthetic_floating_fixtures import (
    create_full_window_fixture,
    create_nonrigid_deformation_fixture,
    create_reflection_fixture,
    create_rigid_rotation_fixture,
    create_uid_permutation_fixture,
)


def test_rigid_pure_rotation(tmp_path: Path) -> None:
    """Verify Kabsch SVD recovers known 3D rigid rotation and translation to float precision."""
    angle_rad = 0.42
    axis = (1.0, 2.0, -1.0)
    translation = (0.08, -0.05, 0.12)

    r_true, t_true, f0_path, f1_path = create_rigid_rotation_fixture(
        tmp_path, angle_rad=angle_rad, axis=axis, translation=translation
    )

    f0_data = parse_partvtk_floating_csv(f0_path)
    f1_data = parse_partvtk_floating_csv(f1_path)

    assert f0_data["node_count"] > 0
    assert f1_data["node_count"] == f0_data["node_count"]
    assert np.array_equal(f0_data["idps"], f1_data["idps"])

    kabsch = compute_kabsch_svd(f0_data["coords"], f1_data["coords"])

    # Verify rank 3
    assert kabsch["is_rank_3"] is True

    # Verify proper rotation det(R) = +1.0
    assert abs(kabsch["det_R"] - 1.0) < 1e-6
    assert kabsch["reflection_detected"] is False

    # Verify rotation recovery error < 1e-6 (accounting for 7-digit ASCII CSV formatting)
    r_est = kabsch["rotation_matrix"]
    assert np.linalg.norm(r_est - r_true) < 1e-6

    # Verify centroid displacement recovery error < 1e-6
    d_est = kabsch["displacement_m"]
    assert np.linalg.norm(d_est - t_true) < 1e-6

    # Verify SE(3) transformation consistency: q = R p + t
    t_est = kabsch["translation_m"]
    p_c0 = kabsch["ref_centroid_m"]
    q_c1 = kabsch["target_centroid_m"]
    assert np.linalg.norm(q_c1 - (r_est @ p_c0 + t_est)) < 1e-6

    # Verify rigidity RMS is near single precision noise (< 1e-6 m)
    assert kabsch["rigidity_rms_m"] < 1e-6
    assert kabsch["rigidity_max_m"] < 1e-6

    # Verify SO(3) geodesic distance to true rotation is near zero (< 1e-6 rad)
    geo_dist = compute_so3_geodesic_distance(r_est, r_true)
    assert geo_dist < 1e-6


def test_reflection_detection_and_proper_so3(tmp_path: Path) -> None:
    """Verify reflection detection and proper det(R) = +1 enforcement."""
    f0_path, f1_path = create_reflection_fixture(tmp_path)

    f0_data = parse_partvtk_floating_csv(f0_path)
    f1_data = parse_partvtk_floating_csv(f1_path)

    kabsch = compute_kabsch_svd(f0_data["coords"], f1_data["coords"])

    # Reflection must be detected in V @ U^T
    assert kabsch["reflection_detected"] is True

    # But output rotation matrix must be a proper rotation with det(R) = +1
    assert abs(kabsch["det_R"] - 1.0) < 1e-6

    # Because it is an improper reflection, a proper rigid rotation cannot achieve zero residual
    assert kabsch["rigidity_rms_m"] > 0.01


def test_nonrigid_deformation_residual(tmp_path: Path) -> None:
    """Verify rigidity RMS and max residuals strictly measure structural deformation."""
    f0_path, f1_path = create_nonrigid_deformation_fixture(tmp_path, amplitude=0.05)

    f0_data = parse_partvtk_floating_csv(f0_path)
    f1_data = parse_partvtk_floating_csv(f1_path)

    kabsch = compute_kabsch_svd(f0_data["coords"], f1_data["coords"])

    # Proper rotation must still be maintained
    assert abs(kabsch["det_R"] - 1.0) < 1e-6

    # Rigidity residuals must strictly register the deformation
    assert kabsch["rigidity_rms_m"] > 0.01
    assert kabsch["rigidity_max_m"] > 0.02


def test_uid_permutation_invariance(tmp_path: Path) -> None:
    """Verify node sorting by exact UID ensures invariance to row permutation."""
    angle_rad = 0.30
    r_true, f0_path, f1_shuffled_path = create_uid_permutation_fixture(tmp_path, angle_rad=angle_rad)

    f0_data = parse_partvtk_floating_csv(f0_path)
    f1_data = parse_partvtk_floating_csv(f1_shuffled_path)

    # After parsing, idps must be sorted and match exactly
    assert np.array_equal(f0_data["idps"], f1_data["idps"])

    kabsch = compute_kabsch_svd(f0_data["coords"], f1_data["coords"])

    # Recovered rotation must match r_true
    assert np.linalg.norm(kabsch["rotation_matrix"] - r_true) < 1e-6
    assert kabsch["rigidity_rms_m"] < 1e-6


def test_quaternion_slerp_and_roundtrip() -> None:
    """Verify quaternion conversions and SLERP geodesic interpolation."""
    # Test identity rotation
    r_id = np.eye(3)
    q_id = matrix_to_quaternion(r_id)
    assert np.allclose(q_id, [1.0, 0.0, 0.0, 0.0])
    assert np.allclose(quaternion_to_matrix(q_id), r_id)

    # Test 90-degree rotation around Z
    theta = math.pi / 2.0
    r_90z = np.array(
        [[math.cos(theta), -math.sin(theta), 0.0], [math.sin(theta), math.cos(theta), 0.0], [0.0, 0.0, 1.0]]
    )
    q_90z = matrix_to_quaternion(r_90z)
    r_rec = quaternion_to_matrix(q_90z)
    assert np.allclose(r_rec, r_90z)

    # Half-way SLERP (alpha=0.5) must give exactly 45-degree rotation around Z
    q_mid = quaternion_slerp(q_id, q_90z, 0.5)
    r_mid = quaternion_to_matrix(q_mid)

    theta_mid = math.pi / 4.0
    r_45z = np.array(
        [[math.cos(theta_mid), -math.sin(theta_mid), 0.0], [math.sin(theta_mid), math.cos(theta_mid), 0.0], [0.0, 0.0, 1.0]]
    )
    assert np.allclose(r_mid, r_45z)

    # Geodesic distances
    dist_total = compute_so3_geodesic_distance(r_id, r_90z)
    dist_half = compute_so3_geodesic_distance(r_id, r_mid)
    assert abs(dist_total - math.pi / 2.0) < 1e-12
    assert abs(dist_half - math.pi / 4.0) < 1e-12


def test_full_window_pipeline_and_floating_info(tmp_path: Path) -> None:
    """Verify full 241-frame series processing, FloatingInfo center validation, and SLERP comparison."""
    csv_paths, fi_path = create_full_window_fixture(tmp_path, n_frames=241, dt=0.05)
    assert len(csv_paths) == 241

    traj = load_partvtk_series(csv_paths)
    assert traj["frame_count"] == 241
    assert traj["node_count"] > 0
    assert traj["times"][0] == 0.0
    assert abs(traj["times"][-1] - 12.0) < 1e-6

    # Verify all det(R) = +1.0
    assert np.allclose(traj["det_R"], 1.0, atol=1e-5)

    # Rigidity RMS should be near single precision noise (< 1e-6 m)
    assert np.max(traj["rigidity_rms"]) < 1e-6

    # Validate against FloatingInfo
    fi_val = validate_center_against_floating_info(traj, fi_path)
    assert fi_val["matched_frames"] == 241
    assert fi_val["center_diff_rmse_m"] < 1e-5
    assert fi_val["center_diff_max_m"] < 1e-5

    # Cross-DP comparison between traj and a perturbed trajectory
    perturbed_paths, _ = create_full_window_fixture(tmp_path / "cand", n_frames=241, dt=0.05)
    cand_traj = load_partvtk_series(perturbed_paths)

    comparison = compare_trajectories_physical_time(traj, cand_traj)
    assert comparison["evaluated_time_points"] == 241
    assert comparison["orientation_geodesic_metrics"]["geodesic_rmse_rad"] < 1e-6
    assert comparison["translational_center_metrics"]["center_rmse_m"] < 1e-6

    # Check inviolable governance in report
    report = build_geometry_orientation_report(
        traj,
        floating_info_validation=fi_val,
        cross_dp_comparison=comparison,
        extra_metadata={"case_id": "F6_SYNTHETIC_TEST", "attempt_id": "test-001"},
    )

    gov = report["governance_and_budget_status"]
    assert gov["orientation_budget"] is None
    assert gov["orientation_budget_status"] == "unregistered"
    assert gov["orientation_qualification_claim"] is None
    assert gov["case_qualification_status"] == "not_assessed"
