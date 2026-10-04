#!/usr/bin/env python3
"""test_f7_three_dp_frozen_macro.py

Unit and synthetic test suite for DS-DATA-02 Family F7:
Round 046 Three-DP All-Pairs Frozen Macro & Moving Paddle Actual Pose Worker.

Covers:
1. Analytic quintic polynomial formulation and exact zero boundary derivatives.
2. DualSPHysics piecewise linear motion reader and knot slope jumps (rejected native C2).
3. Non-constant refinement ratio (1.25 != 1.60) and UID match rejection across DPs.
4. Moving Type 1 marker pose extraction from actual positions around pivot [-0.04, 0.0, 0.05].
5. Frame macro extraction, positive mass enforcement, and native exclusion accounting.
6. Pairwise macro comparisons, frozen normalizers, and preservation of the KE 5% failure gate.
7. End-to-end worker execution on synthetic mock data for coarse, medium, fine across all 3 pairs.
8. Request builder CLI generation, schema verification, and input validation without reading .h5 files.
"""

import json
import math
from pathlib import Path
import sys
import tempfile

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from f7_three_dp_frozen_macro_worker import (
    OPERATORS,
    PHYSICAL_CONDITION_SHA256,
    PADDLE_AXIS_POINT,
    quintic_s,
    quintic_ds,
    quintic_d2s,
    evaluate_trajectory_analytic,
    evaluate_piecewise_linear_motion,
    extract_moving_paddle_pose,
    compute_frame_macro,
    interpolate_series_to_grid,
    compare_two_macro_series,
    compare_paddle_poses_to_analytic,
    run_three_dp_worker,
    sha256_file,
)
from request_builder_cli import (
    build_binding,
    build_runner_request,
    validate_pinned_inputs,
    THREE_DP_CASES,
)


# -----------------------------------------------------------------------------
# Test 1: Analytic Quintic Formulation & Boundary Derivatives
# -----------------------------------------------------------------------------

def test_analytic_quintic_boundary_derivatives():
    """Verifies that base quintic polynomial s(tau) satisfies strict C2 boundary conditions."""
    assert quintic_s(0.0) == 0.0
    assert quintic_s(1.0) == 1.0
    assert quintic_ds(0.0) == 0.0
    assert quintic_ds(1.0) == 0.0
    assert quintic_d2s(0.0) == 0.0
    assert quintic_d2s(1.0) == 0.0

    # Symmetric midpoint properties at tau = 0.5
    assert quintic_s(0.5) == 0.5
    assert quintic_ds(0.5) == 30.0 * (0.5 ** 2) * (0.5 ** 2)  # 1.875
    assert quintic_d2s(0.5) == 0.0


def test_full_12s_analytic_trajectory():
    """Verifies full 12s trajectory: 2 active cycles (0..8s) and neutral rest (8..12s)."""
    # Start at 0
    th0, v0, a0 = evaluate_trajectory_analytic(0.0)
    assert th0 == 0.0 and v0 == 0.0 and a0 == 0.0

    # First peak at t = 1.0s (+45 deg)
    th1, v1, a1 = evaluate_trajectory_analytic(1.0)
    assert math.isclose(th1, 45.0, abs_tol=1e-12)
    assert math.isclose(v1, 0.0, abs_tol=1e-12)
    assert math.isclose(a1, 0.0, abs_tol=1e-12)

    # First trough at t = 3.0s (-45 deg)
    th3, v3, a3 = evaluate_trajectory_analytic(3.0)
    assert math.isclose(th3, -45.0, abs_tol=1e-12)
    assert math.isclose(v3, 0.0, abs_tol=1e-12)

    # Neutral rest tail in 8..12s
    for t in [8.0, 9.5, 11.0, 12.0]:
        th, v, a = evaluate_trajectory_analytic(t)
        assert th == 0.0 and v == 0.0 and a == 0.0


# -----------------------------------------------------------------------------
# Test 2: Piecewise Linear Solver Forcing & Rejected Native C2 Claim
# -----------------------------------------------------------------------------

def test_piecewise_linear_solver_forcing_and_knot_jumps():
    """Verifies piecewise linear interpolation (JMotionMovActive::DfGetNewAng) produces knot slope jumps."""
    dt = 0.001
    times = np.arange(0.0, 12.0 + dt, dt)
    angles = np.array([evaluate_trajectory_analytic(t)[0] for t in times])

    # Midpoint between t=0 and t=dt
    t_mid = 0.5 * dt
    ang_interp = evaluate_piecewise_linear_motion(times, angles, t_mid)
    expected_linear = angles[0] + 0.5 * (angles[1] - angles[0])
    assert math.isclose(ang_interp, expected_linear, rel_tol=1e-12)

    # Adjacent slopes (velocities) in solver space
    v_first = (angles[1] - angles[0]) / dt
    v_second = (angles[2] - angles[1]) / dt
    # First slope from rest is non-zero
    assert v_first > 0.0
    # Finite velocity jump at knot t1
    knot_jump = abs(v_second - v_first)
    assert knot_jump > 0.0


# -----------------------------------------------------------------------------
# Test 3: Refinement Ratio Boundary & Rejection of UID Match Across DP
# -----------------------------------------------------------------------------

def test_refinement_ratio_non_constant():
    """Verifies that refinement ratio between 0.02, 0.016, and 0.01 is non-constant."""
    dp_coarse = 0.020
    dp_medium = 0.016
    dp_fine = 0.010

    ratio_c_m = dp_coarse / dp_medium  # 1.25
    ratio_m_f = dp_medium / dp_fine    # 1.60

    assert math.isclose(ratio_c_m, 1.25, abs_tol=1e-12)
    assert math.isclose(ratio_m_f, 1.60, abs_tol=1e-12)
    # Refinement ratio is NOT constant!
    assert ratio_c_m != ratio_m_f

    # Total and fluid particle counts differ across resolutions
    counts = {k: v["expected_particles"] for k, v in THREE_DP_CASES.items()}
    assert counts["coarse"]["fluid"] == 40700
    assert counts["medium"]["fluid"] == 78732
    assert counts["fine"]["fluid"] == 318716

    # Moving Type 1 marker counts differ
    assert counts["coarse"]["type1_moving"] == 1984
    assert counts["medium"]["type1_moving"] == 3798
    assert counts["fine"]["type1_moving"] == 4899


# -----------------------------------------------------------------------------
# Test 4: Moving Paddle Type 1 Pose Extraction
# -----------------------------------------------------------------------------

def test_moving_paddle_pose_extraction_exact():
    """Verifies that extract_moving_paddle_pose recovers exact rigid rotation angle and centroid."""
    # Synthetic grid of Type 1 paddle particles around [-0.04, 0.0, 0.05]
    n_pts = 100
    np.random.seed(42)
    x0 = -0.04 + np.random.uniform(-0.03, 0.03, n_pts)
    y0 = np.random.uniform(-0.24, 0.24, n_pts)
    z0 = 0.05 + np.random.uniform(0.0, 0.48, n_pts)
    pos0 = np.column_stack([x0, y0, z0])

    # Rotate by +30 degrees
    test_angle_deg = 30.0
    th_rad = math.radians(test_angle_deg)
    cos_th, sin_th = math.cos(th_rad), math.sin(th_rad)

    dx = x0 - (-0.04)
    dy = y0 - 0.0
    x_rot = -0.04 + cos_th * dx - sin_th * dy
    y_rot = sin_th * dx + cos_th * dy
    pos_t = np.column_stack([x_rot, y_rot, z0])

    pose = extract_moving_paddle_pose(pos_t, pos0, axis_origin=(-0.04, 0.0))
    assert math.isclose(pose["angle_deg"], test_angle_deg, abs_tol=1e-12)
    assert math.isclose(pose["rigid_rms_m"], 0.0, abs_tol=1e-12)
    assert math.isclose(pose["centroid_z_m"], np.mean(z0), abs_tol=1e-12)


# -----------------------------------------------------------------------------
# Test 5: Frame Macro Extraction & Exclusions Accounting
# -----------------------------------------------------------------------------

def test_compute_frame_macro_and_exclusions():
    """Verifies active mass, COM, kinetic energy, and native exclusion accounting."""
    n_particles = 10
    masses = np.ones(n_particles) * 10.0
    positions = np.zeros((n_particles, 3))
    positions[:, 0] = np.linspace(-0.5, 0.5, n_particles)
    velocities = np.zeros((n_particles, 3))
    velocities[:, 0] = 2.0  # vx = 2 m/s

    valid_flags = np.ones(n_particles, dtype=bool)
    fluid_mask = np.ones(n_particles, dtype=bool)

    # Frame 0: all valid
    vals, excl_cnt, excl_m = compute_frame_macro(masses, positions, velocities, valid_flags, fluid_mask)
    assert vals[0] == 100.0  # total mass = 10 * 10
    assert math.isclose(vals[1], 0.0, abs_tol=1e-12)  # com_x = 0
    # KE = 0.5 * 100 * (2^2) = 200 J
    assert math.isclose(vals[4], 200.0, abs_tol=1e-12)
    assert excl_cnt == 0
    assert excl_m == 0.0

    # Frame 1: 2 particles become invalid (native exclusions)
    valid_flags[0] = False
    valid_flags[1] = False
    vals1, excl_cnt1, excl_m1 = compute_frame_macro(masses, positions, velocities, valid_flags, fluid_mask)
    assert vals1[0] == 80.0  # 8 particles remaining
    assert excl_cnt1 == 2
    assert excl_m1 == 20.0
    assert vals1[4] == 0.5 * 80.0 * 4.0  # 160 J


def test_positive_mass_enforcement():
    """Verifies that non-positive masses raise ValueError."""
    masses = np.array([-1.0, 10.0])
    pos = np.zeros((2, 3))
    vel = np.zeros((2, 3))
    valid = np.array([True, True])
    fluid = np.array([True, True])

    with pytest.raises(ValueError, match="Non-finite or non-positive"):
        compute_frame_macro(masses, pos, vel, valid, fluid)


# -----------------------------------------------------------------------------
# Test 6: Pairwise Macro Comparison Engine & KE 5% Failure Preservation
# -----------------------------------------------------------------------------

def test_pairwise_macro_comparison_passing():
    """Verifies pairwise comparison passes when errors are within 5% budget."""
    grid = np.linspace(0.0, 12.0, 601)
    scales = np.array([320.1984, 1.1, 0.7, 0.432, 50.0])

    base = np.zeros((601, 5))
    base[:, 0] = 320.0
    base[:, 4] = 40.0

    cand = np.zeros((601, 5))
    cand[:, 0] = 320.0 + 1.0  # delta mass = 1.0 kg (1/320.1984 = 0.31% < 5%)
    cand[:, 4] = 40.0 + 1.0   # delta KE = 1.0 J (1/50 = 2% < 5%)

    res = compare_two_macro_series(base, cand, grid, scales, budget_rel=0.05)
    assert res["macro_budget_pass"] is True
    assert res["metrics"]["active_mass_kg"]["budget_pass"] is True
    assert res["metrics"]["kinetic_energy_j"]["budget_pass"] is True


def test_pairwise_macro_comparison_ke_failure_preserved():
    """Verifies that when KE error exceeds 5% (e.g. ~43% historical discrepancy), budget fails."""
    grid = np.linspace(0.0, 12.0, 601)
    scales = np.array([320.1984, 1.1, 0.7, 0.432, 50.0])

    base = np.zeros((601, 5))
    base[:, 0] = 320.0
    base[:, 4] = 40.0

    cand = np.zeros((601, 5))
    cand[:, 0] = 320.0
    # Introduce 43% discrepancy in KE (historical spatial negative)
    cand[:, 4] = 40.0 + 0.43 * 50.0

    res = compare_two_macro_series(base, cand, grid, scales, budget_rel=0.05)
    # The failure MUST NOT be waived!
    assert res["macro_budget_pass"] is False
    assert res["metrics"]["kinetic_energy_j"]["budget_pass"] is False
    assert math.isclose(res["metrics"]["kinetic_energy_j"]["max_scaled_error"], 0.43, abs_tol=1e-4)


# -----------------------------------------------------------------------------
# Test 7: End-to-End Worker on Synthetic 3DP Mock Data
# -----------------------------------------------------------------------------

def test_three_dp_worker_synthetic_e2e():
    """Runs run_three_dp_worker end-to-end with synthetic 3DP mock data across all 3 pairs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Write normalizers and budget files
        norm_file = tmp / "normalizers.json"
        norm_file.write_text(json.dumps({
            "continuous_initial_mass_kg": 320.1984,
            "com_axis_scales_m": [1.1, 0.7, 0.432],
            "macro_relative_budget": 0.05,
        }))

        budget_file = tmp / "budget.json"
        budget_file.write_text(json.dumps({
            "macro_relative_budget": 0.05,
            "event_time_relative": 0.02,
            "save_or_integration_share": 0.20,
        }))

        # Create synthetic series for coarse, medium, fine
        t = np.linspace(0.0, 12.0, 121)
        mock_pre_extracted = {}
        for role, mass_val, ke_val in [
            ("coarse", 325.6, 25.0),
            ("medium", 322.5, 26.0),
            ("fine", 318.7, 27.0),
        ]:
            vals = []
            poses = []
            for time_pt in t:
                # Slight variation over time
                ke = ke_val + 2.0 * math.sin(time_pt) ** 2
                vals.append([mass_val, 0.0, 0.0, 0.2, ke])
                th_tgt = evaluate_trajectory_analytic(time_pt)[0]
                poses.append({
                    "time_s": float(time_pt),
                    "angle_deg": th_tgt,
                    "centroid_x_m": -0.04,
                    "centroid_y_m": 0.0,
                    "centroid_z_m": 0.25,
                    "rigid_rms_m": 0.0,
                })
            mock_pre_extracted[role] = {
                "source": f"synthetic_{role}",
                "source_sha256": "0" * 64,
                "physical_condition_sha256": PHYSICAL_CONDITION_SHA256,
                "time_s": t.tolist(),
                "values": vals,
                "moving_paddle_poses": poses,
                "exclusions": [{"frame": 0, "time_s": 0.0, "excluded_count": 0, "excluded_mass_kg": 0.0}],
            }

        binding_file = tmp / "binding.json"
        binding_file.write_text(json.dumps({
            "schema": "ds02.f7.three-dp-binding.v1",
            "physical_condition_sha256": PHYSICAL_CONDITION_SHA256,
            "normalizers": str(norm_file),
            "budget": str(budget_file),
            "cases": {
                "coarse": {"case_id": "F7_COARSE"},
                "medium": {"case_id": "F7_MEDIUM"},
                "fine": {"case_id": "F7_FINE"},
            },
        }))

        output_file = tmp / "output_review.json"
        result = run_three_dp_worker(
            binding_path=binding_file,
            output_path=output_file,
            pre_extracted_data=mock_pre_extracted,
        )

        assert output_file.is_file()
        assert result["schema"] == "ds02.f7.three-dp-frozen-macro-review.v1"
        assert result["grid_points"] == 601
        assert "coarse_vs_medium" in result["pairwise_macro_comparisons"]
        assert "medium_vs_fine" in result["pairwise_macro_comparisons"]
        assert "coarse_vs_fine" in result["pairwise_macro_comparisons"]

        # Governance & gaps
        gov = result["governance_and_explicit_gaps"]
        assert gov["q_n_status"] == "not_granted"
        assert gov["production_approval"] == "none"
        assert gov["residence_specific_registered_budget"] is None

        # Moving pose evaluation
        pose_res = result["moving_paddle_pose_analysis"]
        assert pose_res["fine"]["rest_tail_held"] is True
        assert math.isclose(pose_res["fine"]["max_abs_analytic_error_deg"], 0.0, abs_tol=1e-12)


# -----------------------------------------------------------------------------
# Test 8: Request Builder CLI & Input Audit (Source-Only, No H5 Reading)
# -----------------------------------------------------------------------------

def test_request_builder_binding_and_request_generation():
    """Verifies that request_builder_cli builds valid binding and runner request schemas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        binding_out = tmp / "binding.json"
        request_out = tmp / "request.json"
        worker_dummy = tmp / "worker.py"
        worker_dummy.write_text("# dummy\n")

        binding = build_binding()
        binding_out.write_text(json.dumps(binding, indent=2))

        req = build_runner_request(binding_out, worker_dummy, attempt_id="test-attempt-001")
        request_out.write_text(json.dumps(req, indent=2))

        # Validate schemas
        assert binding["schema"] == "ds02.f7.three-dp-binding.v1"
        assert set(binding["cases"].keys()) == {"coarse", "medium", "fine"}
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["attempt_id"] == "test-attempt-001"
        assert req["kind"] == "cpu"
        assert req["cpu_task_kind"] == "audit"

        # Check that no .h5 files were hashed into input_sha256 (source-only boundary)
        for path_str in req["input_sha256"].keys():
            assert not path_str.endswith(".h5"), f"H5 file found in source input_sha256: {path_str}"
