"""Unit tests for DS-DATA-02 F6 Angular Release All 3DP Comparison Script (v2).

Tests run entirely on synthetic mock CSV data fixtures generated in pytest tmp_path.
Zero access to actual campaign data or actual solver CSVs.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.ds_data02_f6_angular_release_comparison_v2 import (
    compare_rigid_pair,
    compute_series_metrics,
    evaluate_angular_release_comparison,
    load_floating_info_csv,
    WINDOW_FRAMES,
)


def _write_synthetic_floating_csv(path: Path, amplitude_factor: float = 1.0) -> None:
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
        surge = 0.05 * amplitude_factor * np.sin(0.5 * t)
        sway = 0.03 * amplitude_factor * np.sin(0.4 * t)
        heave = 0.40 * amplitude_factor * np.cos(1.2 * t) - 0.40

        roll_deg = 5.0 * amplitude_factor * np.sin(0.8 * t)
        pitch_deg = 4.0 * amplitude_factor * np.sin(0.7 * t)
        yaw_deg = 6.0 * amplitude_factor * np.cos(0.6 * t)

        cx = 2.4 + surge
        cy = 1.2 + sway
        cz = 1.08 + heave

        vx = 0.025 * amplitude_factor * np.cos(0.5 * t)
        vy = 0.012 * amplitude_factor * np.cos(0.4 * t)
        vz = -0.48 * amplitude_factor * np.sin(1.2 * t)

        wx = 0.08 * amplitude_factor * np.cos(0.8 * t)
        wy = 0.12 * amplitude_factor * np.cos(0.7 * t)
        wz = 0.06 * amplitude_factor * np.sin(0.6 * t)

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


def test_load_floating_info_csv(tmp_path: Path) -> None:
    csv_file = tmp_path / "test_floating.csv"
    _write_synthetic_floating_csv(csv_file, amplitude_factor=1.0)

    data = load_floating_info_csv(csv_file)
    assert data["frames"] == 241
    assert np.isclose(data["time"][0], 0.0)
    assert np.isclose(data["time"][-1], 12.0)
    assert data["center_m"].shape == (241, 3)
    assert data["angles_rad"].shape == (241, 3)
    assert data["fomega_rad_s"].shape == (241, 3)
    assert np.isclose(data["initial_state"]["center_m"][0], 2.4)
    assert np.isclose(data["initial_state"]["center_m"][1], 1.2)
    assert np.isclose(data["initial_state"]["center_m"][2], 1.08)


def test_compute_series_metrics() -> None:
    t = np.linspace(0.0, 12.0, 241)
    ref = np.sin(t)
    # 2% perturbation
    cand = 1.02 * ref

    metrics = compute_series_metrics(ref, cand, t, t, tol_rel=0.05)
    emp_scale = np.sqrt(np.mean(ref**2)) / np.max(np.abs(ref))
    assert np.isclose(metrics["rmse_relative_to_reference_peak"], 0.02 * emp_scale, atol=1e-5)
    assert metrics["within_5pct_budget"] is True


    # 10% perturbation
    cand_fail = 1.10 * ref
    metrics_fail = compute_series_metrics(ref, cand_fail, t, t, tol_rel=0.05)
    assert np.isclose(metrics_fail["rmse_relative_to_reference_peak"], 0.10 * emp_scale, atol=1e-5)
    assert metrics_fail["within_5pct_budget"] is False  # > 0.05




def test_compare_rigid_pair(tmp_path: Path) -> None:
    ref_file = tmp_path / "ref.csv"
    cand_file = tmp_path / "cand.csv"

    _write_synthetic_floating_csv(ref_file, amplitude_factor=1.0)
    _write_synthetic_floating_csv(cand_file, amplitude_factor=1.02)  # within 5%

    ref_data = load_floating_info_csv(ref_file)
    cand_data = load_floating_info_csv(cand_file)

    comparison = compare_rigid_pair(ref_data, cand_data, tol_rel=0.05)
    summary = comparison["evaluation_summary"]
    assert summary["all_6dof_pass"] is True
    assert summary["translational_pass"] is True
    assert summary["rotational_pass"] is True
    assert summary["max_macro_relative_rmse"] < 0.05


def test_evaluate_angular_release_comparison_end_to_end(tmp_path: Path) -> None:
    coarse_csv = tmp_path / "coarse.csv"
    medium_csv = tmp_path / "medium.csv"
    fine_csv = tmp_path / "fine.csv"

    _write_synthetic_floating_csv(coarse_csv, amplitude_factor=1.0)
    _write_synthetic_floating_csv(medium_csv, amplitude_factor=1.03)
    _write_synthetic_floating_csv(fine_csv, amplitude_factor=1.04)

    config_path = tmp_path / "config.json"
    output_path = tmp_path / "report.json"

    config_data = {
        "tol_relative": 0.05,
        "resolutions": {
            "coarse": {
                "case_id": "MOCK_DP025",
                "dp_m": 0.025,
                "floating_csv": str(coarse_csv),
            },
            "medium": {
                "case_id": "MOCK_DP020",
                "dp_m": 0.020,
                "floating_csv": str(medium_csv),
            },
            "fine": {
                "case_id": "MOCK_DP0125",
                "dp_m": 0.0125,
                "floating_csv": str(fine_csv),
            },
        },
    }
    config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    report = evaluate_angular_release_comparison(config_path, output_path)
    assert output_path.is_file()
    assert report["schema"] == "ds02.f6.angular-release-3dp-comparison-report.v2"
    assert "medium_vs_fine" in report["pairwise_comparisons"]
    assert "mass_and_support_semantics" in report
    assert report["mass_and_support_semantics"]["declared_physical_rigid_mass_kg"] == 128.0
    assert report["mass_and_support_semantics"]["fluid_density_support_mass_kg"] == 256.0
