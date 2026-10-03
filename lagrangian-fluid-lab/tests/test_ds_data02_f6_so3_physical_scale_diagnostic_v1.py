"""Unit tests for DS-DATA-02 F6 SO(3) Lie Group & Registered Physical Scales Diagnostic (v1).

Tests run entirely on synthetic mock data fixtures generated in pytest tmp_path.
Zero access to actual campaign data or actual solver CSVs.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from scripts.ds_data02_f6_so3_physical_scale_diagnostic_v1 import (
    compute_channel_diagnostics,
    compute_so3_geodesic_distance,
    euler_angles_to_rotation_matrix,
    evaluate_f6_so3_and_physical_scale_diagnostic,
    load_floating_info_csv,
    L_CHAR,
    THETA_CHAR,
    U_GRAVITY,
    OMEGA_GRAVITY,
    WINDOW_FRAMES,
)


def _write_synthetic_floating_csv(path: Path, amplitude_factor: float = 1.0, seed_offset: float = 0.0) -> None:
    """Generate synthetic 241-frame FloatingInfo CSV matching DualSPHysics schema."""
    header = [
        "part",
        "time [s]",
        "fvel.x [m/s]",
        "fvel.y [m/s]",
        "fvel.z [m/s]",
        "fomega.x [rad/s]",
        "fomega.y [rad/s]",
        "fomega.z [rad/s]",
        "center.x [m]",
        "center.y [m]",
        "center.z [m]",
        "surge [m]",
        "sway [m]",
        "heave [m]",
        "roll [deg]",
        "pitch [deg]",
        "yaw [deg]",
    ]

    t_values = np.linspace(0.0, 12.0, WINDOW_FRAMES)
    rows = []
    for i, t in enumerate(t_values):
        # Oscillatory synthetic response
        surge = 0.05 * amplitude_factor * np.sin(0.5 * t) + seed_offset * 0.001
        sway = 0.002 * amplitude_factor * np.sin(0.4 * t) + seed_offset * 0.0005  # low-amplitude off-axis
        heave = 0.40 * amplitude_factor * np.cos(1.2 * t) - 0.40

        roll_deg = 0.05 * amplitude_factor * np.sin(0.8 * t) + seed_offset * 0.01  # low-amplitude off-axis
        pitch_deg = 4.0 * amplitude_factor * np.sin(0.7 * t)
        yaw_deg = 0.08 * amplitude_factor * np.cos(0.6 * t) + seed_offset * 0.01  # low-amplitude off-axis

        cx = 2.4 + surge
        cy = 1.2 + sway
        cz = 1.08 + heave

        vx = 0.025 * amplitude_factor * np.cos(0.5 * t)
        vy = 0.0008 * amplitude_factor * np.cos(0.4 * t)
        vz = -0.48 * amplitude_factor * np.sin(1.2 * t)

        wx = 0.0007 * amplitude_factor * np.cos(0.8 * t)
        wy = 0.12 * amplitude_factor * np.cos(0.7 * t)
        wz = 0.0008 * amplitude_factor * np.sin(0.6 * t)

        row = {
            "part": str(i),
            "time [s]": f"{t:.6E}",
            "fvel.x [m/s]": f"{vx:.7E}",
            "fvel.y [m/s]": f"{vy:.7E}",
            "fvel.z [m/s]": f"{vz:.7E}",
            "fomega.x [rad/s]": f"{wx:.7E}",
            "fomega.y [rad/s]": f"{wy:.7E}",
            "fomega.z [rad/s]": f"{wz:.7E}",
            "center.x [m]": f"{cx:.12E}",
            "center.y [m]": f"{cy:.12E}",
            "center.z [m]": f"{cz:.12E}",
            "surge [m]": f"{surge:.7E}",
            "sway [m]": f"{sway:.7E}",
            "heave [m]": f"{heave:.7E}",
            "roll [deg]": f"{roll_deg:.7E}",
            "pitch [deg]": f"{pitch_deg:.7E}",
            "yaw [deg]": f"{yaw_deg:.7E}",
        }
        rows.append(row)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def test_rotation_matrix_and_so3_geodesic_distance() -> None:
    # 1. Identity rotation
    r_id = np.eye(3, dtype=np.float64)
    phi_zero = compute_so3_geodesic_distance(r_id, r_id)
    assert math.isclose(phi_zero, 0.0, abs_tol=1e-12)

    # 2. Pure pitch of 0.1 rad
    theta = 0.1
    r_pitch = euler_angles_to_rotation_matrix(0.0, theta, 0.0)
    phi_pitch = compute_so3_geodesic_distance(r_id, r_pitch)
    assert math.isclose(phi_pitch, theta, abs_tol=1e-7)

    # 3. Pure roll of 0.05 rad
    roll = 0.05
    r_roll = euler_angles_to_rotation_matrix(roll, 0.0, 0.0)
    phi_roll = compute_so3_geodesic_distance(r_id, r_roll)
    assert math.isclose(phi_roll, roll, abs_tol=1e-7)

    # 4. Pure yaw of 0.08 rad
    yaw = 0.08
    r_yaw = euler_angles_to_rotation_matrix(0.0, 0.0, yaw)
    phi_yaw = compute_so3_geodesic_distance(r_id, r_yaw)
    assert math.isclose(phi_yaw, yaw, abs_tol=1e-7)

    # 5. Symmetry: Phi(R1, R2) == Phi(R2, R1)
    phi_sym1 = compute_so3_geodesic_distance(r_pitch, r_roll)
    phi_sym2 = compute_so3_geodesic_distance(r_roll, r_pitch)
    assert math.isclose(phi_sym1, phi_sym2, abs_tol=1e-12)


def test_euler_chart_distortion_vs_so3_invariant_distance() -> None:
    # Under coupled multi-axis rotation, Euclidean norm of Euler angles deviates from Lie group geodesic
    roll = 0.3
    pitch = 0.4
    yaw = 0.2
    r_rot = euler_angles_to_rotation_matrix(roll, pitch, yaw)
    r_id = np.eye(3, dtype=np.float64)

    phi_so3 = compute_so3_geodesic_distance(r_id, r_rot)
    euler_norm = math.sqrt(roll**2 + pitch**2 + yaw**2)

    # Geodesic distance and Euler Euclidean norm must differ on the curved manifold
    assert not math.isclose(phi_so3, euler_norm, rel_tol=1e-4)
    assert phi_so3 > 0.0
    assert euler_norm > 0.0


def test_physical_scale_vs_root_dynamic_peak_demonstration() -> None:
    # Create a quiescent off-axis channel (e.g. sway or roll)
    # Peak amplitude is tiny: 0.001 m
    # Discrepancy is 0.0002 m (0.2 mm)
    t = np.linspace(0.0, 12.0, 100)
    ref_sway = 0.001 * np.sin(t)
    cand_sway = 0.0012 * np.sin(t)  # delta = 0.0002 m

    diag = compute_channel_diagnostics(ref_sway, cand_sway, physical_scale=L_CHAR, tol_rel=0.05)

    # Absolute RMSE is ~0.00014 m
    # Relative to physical scale L=0.8m: ~0.00014 / 0.8 = 0.0175% <= 5% (PASSES physical contract)
    assert diag["within_registered_5pct_physical_budget"] is True
    assert diag["rmse_relative_to_physical_scale"] < 0.001

    # But relative to Root dynamic-peak: ~0.00014 / 0.001 = 14% > 5% (FAILS dynamic peak!)
    assert diag["root_descriptive_dynamic_peak"]["within_5pct_dynamic_peak"] is False
    assert diag["root_descriptive_dynamic_peak"]["denominator_inflation_risk"] is True
    assert diag["root_descriptive_dynamic_peak"]["status"] == "descriptive_only_not_registered_gate"


def test_full_diagnostic_evaluation_synthetic(tmp_path: Path) -> None:
    coarse_csv = tmp_path / "coarse_floating.csv"
    medium_csv = tmp_path / "medium_floating.csv"
    fine_csv = tmp_path / "fine_floating.csv"

    _write_synthetic_floating_csv(coarse_csv, amplitude_factor=1.0, seed_offset=0.0)
    _write_synthetic_floating_csv(medium_csv, amplitude_factor=1.01, seed_offset=0.05)
    _write_synthetic_floating_csv(fine_csv, amplitude_factor=1.02, seed_offset=0.1)

    # Mock telemetry file
    telemetry_file = tmp_path / "native-interval-telemetry.json"
    tel_content = {
        "schema": "ds02.actual-F5-F6-native-interval-telemetry.v1",
        "cases": [
            {
                "family_id": "F6",
                "case_id": "F6_ANGULAR_RELEASE_DP025",
                "total_interval_steps": 41200,
                "total_DT_min_adjustments": 0,
                "interval_rows_with_DT_min_adjustments": 0,
                "symplectic_floor_incidence_fraction": 0.0,
                "native_NpOut_interval_sum": 0,
            },
            {
                "family_id": "F6",
                "case_id": "F6_ANGULAR_RELEASE_DP020",
                "total_interval_steps": 51500,
                "total_DT_min_adjustments": 0,
                "interval_rows_with_DT_min_adjustments": 0,
                "symplectic_floor_incidence_fraction": 0.0,
                "native_NpOut_interval_sum": 0,
            },
            {
                "family_id": "F6",
                "case_id": "F6_ANGULAR_RELEASE_DP0125",
                "total_interval_steps": 163707,
                "total_DT_min_adjustments": 273,
                "interval_rows_with_DT_min_adjustments": 2,
                "symplectic_floor_incidence_fraction": 0.0008338067400905276,
                "native_NpOut_interval_sum": 28,
            },
        ],
    }
    telemetry_file.write_text(json.dumps(tel_content), encoding="utf-8")

    config_file = tmp_path / "config.json"
    output_file = tmp_path / "report.json"

    config_data = {
        "schema": "ds02.f6.so3-physical-scale-diagnostic-config.v1",
        "tol_relative": 0.05,
        "telemetry_report": str(telemetry_file),
        "resolutions": {
            "coarse": {
                "case_id": "F6_ANGULAR_RELEASE_DP025",
                "dp_m": 0.025,
                "floating_csv": str(coarse_csv),
            },
            "medium": {
                "case_id": "F6_ANGULAR_RELEASE_DP020",
                "dp_m": 0.020,
                "floating_csv": str(medium_csv),
            },
            "fine": {
                "case_id": "F6_ANGULAR_RELEASE_DP0125",
                "dp_m": 0.0125,
                "floating_csv": str(fine_csv),
            },
        },
    }
    config_file.write_text(json.dumps(config_data), encoding="utf-8")

    report = evaluate_f6_so3_and_physical_scale_diagnostic(config_file, output_file)

    assert output_file.is_file()
    assert report["schema"] == "ds02.f6.so3-physical-scale-diagnostic-report.v1"
    assert report["case_family"] == "F6"

    # Verify physical reference scales
    scales = report["physical_reference_scales"]
    assert math.isclose(scales["characteristic_length_L_m"], 0.8)
    assert math.isclose(scales["gravitational_velocity_scale_U_m_s"], U_GRAVITY)
    assert math.isclose(scales["gravitational_angular_velocity_scale_omega_rad_s"], OMEGA_GRAVITY)

    # Verify mass semantics
    masses = report["mass_semantics_declaration"]
    assert masses["declared_physical_rigid_mass_kg"] == 128.0
    assert masses["fluid_density_lattice_support_weight_kg"] == 256.0

    # Verify telemetry evidence
    tel = report["telemetry_evidence"]
    assert tel["cases"]["F6_ANGULAR_RELEASE_DP0125"]["total_DT_min_adjustments"] == 273
    assert tel["cases"]["F6_ANGULAR_RELEASE_DP025"]["total_DT_min_adjustments"] == 0

    # Verify pairwise diagnostics
    assert "medium_vs_coarse" in report["pairwise_diagnostics"]
    assert "fine_vs_coarse" in report["pairwise_diagnostics"]
    assert "fine_vs_medium" in report["pairwise_diagnostics"]

    m_vs_c = report["pairwise_diagnostics"]["medium_vs_coarse"]
    assert "so3_invariant_orientation" in m_vs_c
    assert "translational_3dof" in m_vs_c
    assert "rotational_euler_channels" in m_vs_c
    assert "chart_distortion" in m_vs_c["so3_invariant_orientation"]
