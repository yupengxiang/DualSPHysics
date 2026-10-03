#!/usr/bin/env python3
"""DS-DATA-02 F6 Angular Release All 3DP Full 12s Rigid Response Comparison (v2).

Source-reader and comparison evaluator for the actual full 3D free 6DOF rigid
angular-release case across all 3 resolutions (Coarse DP 0.025, Medium DP 0.020, Fine DP 0.0125):
1. Evaluates all 6 degrees of freedom (surge, sway, heave, roll, pitch, yaw) over the full 12.0s window (241 frames).
2. Preserves frozen F6 quality contract: Relative RMSE <= 5% (0.05) evaluated against reference peak amplitude.
3. Rejects heave-only narrowing, 3s window truncation, and post-hoc relaxed orientation budgets.
4. Correctly distinguishes internal angular velocity initialization from initial translational node velocities.
5. Strictly separates physical rigid body mass (128 kg), lattice support particle mass (~256 kg), and solver interaction weight.
6. Operates boundedly on completed official FloatingInfo_mk60.csv files; CPU only (<=2 threads, <=1800s).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

SCHEMA_REPORT = "ds02.f6.angular-release-3dp-comparison-report.v2"
DEFAULT_TOL_RELATIVE = 0.05
WINDOW_FRAMES = 241
EXPECTED_WINDOW_S = 12.0


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_floating_info_csv(path: Path | str) -> dict[str, Any]:
    """Parse official DualSPHysics FloatingInfo CSV with full 6DOF fields."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"FloatingInfo CSV not found: {p}")

    with p.open("r", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        rows = list(reader)

    if len(rows) != WINDOW_FRAMES:
        raise ValueError(f"Expected {WINDOW_FRAMES} frames, found {len(rows)} in {p}")

    times = np.array([float(r["time [s]"]) for r in rows], dtype=np.float64)
    if times[-1] < EXPECTED_WINDOW_S - 0.01:
        raise ValueError(f"CSV does not cover full {EXPECTED_WINDOW_S}s window: final time is {times[-1]}")

    # Position and Displacements (Translations in meters)
    center = np.array(
        [[float(r["center.x [m]"]), float(r["center.y [m]"]), float(r["center.z [m]"])] for r in rows],
        dtype=np.float64,
    )
    surge = np.array([float(r["surge [m]"]) for r in rows], dtype=np.float64)
    sway = np.array([float(r["sway [m]"]) for r in rows], dtype=np.float64)
    heave = np.array([float(r["heave [m]"]) for r in rows], dtype=np.float64)

    # Orientation (Rotations in degrees and converted to radians)
    angles_deg = np.array(
        [[float(r["roll [deg]"]), float(r["pitch [deg]"]), float(r["yaw [deg]"])] for r in rows],
        dtype=np.float64,
    )
    angles_rad = np.deg2rad(angles_deg)

    # Velocities (Linear in m/s, Angular in rad/s)
    fvel = np.array(
        [[float(r["fvel.x [m/s]"]), float(r["fvel.y [m/s]"]), float(r["fvel.z [m/s]"])] for r in rows],
        dtype=np.float64,
    )
    fomega = np.array(
        [[float(r["fomega.x [rad/s]"]), float(r["fomega.y [rad/s]"]), float(r["fomega.z [rad/s]"])] for r in rows],
        dtype=np.float64,
    )

    return {
        "path": str(p.resolve()),
        "sha256": sha256_file(p),
        "frames": len(rows),
        "time": times,
        "center_m": center,
        "surge_m": surge,
        "sway_m": sway,
        "heave_m": heave,
        "angles_deg": angles_deg,
        "angles_rad": angles_rad,
        "fvel_m_s": fvel,
        "fomega_rad_s": fomega,
        "initial_state": {
            "time_s": float(times[0]),
            "center_m": center[0].tolist(),
            "displacements_m": [float(surge[0]), float(sway[0]), float(heave[0])],
            "angles_deg": angles_deg[0].tolist(),
            "angles_rad": angles_rad[0].tolist(),
            "fvel_m_s": fvel[0].tolist(),
            "fomega_rad_s": fomega[0].tolist(),
        },
        "final_state": {
            "time_s": float(times[-1]),
            "center_m": center[-1].tolist(),
            "displacements_m": [float(surge[-1]), float(sway[-1]), float(heave[-1])],
            "angles_deg": angles_deg[-1].tolist(),
            "angles_rad": angles_rad[-1].tolist(),
            "fvel_m_s": fvel[-1].tolist(),
            "fomega_rad_s": fomega[-1].tolist(),
        },
    }


def compute_series_metrics(
    ref_series: np.ndarray,
    cand_series: np.ndarray,
    ref_time: np.ndarray,
    cand_time: np.ndarray,
    tol_rel: float = DEFAULT_TOL_RELATIVE,
) -> dict[str, Any]:
    """Compute absolute and relative RMSE against reference peak scale."""
    if len(ref_time) != len(cand_time) or not np.allclose(ref_time, cand_time, atol=1e-5):
        # Interpolate candidate onto reference time grid
        interp_cand = np.interp(ref_time, cand_time, cand_series)
    else:
        interp_cand = cand_series

    delta = interp_cand - ref_series
    rmse_abs = float(np.sqrt(np.mean(delta * delta)))
    max_abs = float(np.max(np.abs(delta)))

    ref_peak = float(np.max(np.abs(ref_series)))
    cand_peak = float(np.max(np.abs(interp_cand)))
    ref_scale = max(ref_peak, 1e-12)

    rmse_rel = rmse_abs / ref_scale
    max_rel = max_abs / ref_scale
    within_budget = bool(rmse_rel <= tol_rel)

    return {
        "rmse_absolute": rmse_abs,
        "max_abs_difference": max_abs,
        "reference_peak_abs": ref_peak,
        "candidate_peak_abs": cand_peak,
        "rmse_relative_to_reference_peak": rmse_rel,
        "max_relative_to_reference_peak": max_rel,
        "within_5pct_budget": within_budget,
    }


def compare_rigid_pair(
    ref_data: dict[str, Any],
    cand_data: dict[str, Any],
    tol_rel: float = DEFAULT_TOL_RELATIVE,
) -> dict[str, Any]:
    """Compare all 6 DOFs and velocities between reference and candidate trajectories."""
    ref_t = ref_data["time"]
    cand_t = cand_data["time"]

    # 1. Translational 3DOF (surge, sway, heave)
    surge_metrics = compute_series_metrics(ref_data["surge_m"], cand_data["surge_m"], ref_t, cand_t, tol_rel)
    sway_metrics = compute_series_metrics(ref_data["sway_m"], cand_data["sway_m"], ref_t, cand_t, tol_rel)
    heave_metrics = compute_series_metrics(ref_data["heave_m"], cand_data["heave_m"], ref_t, cand_t, tol_rel)

    # 2. Rotational 3DOF (roll, pitch, yaw in radians)
    roll_metrics = compute_series_metrics(ref_data["angles_rad"][:, 0], cand_data["angles_rad"][:, 0], ref_t, cand_t, tol_rel)
    pitch_metrics = compute_series_metrics(ref_data["angles_rad"][:, 1], cand_data["angles_rad"][:, 1], ref_t, cand_t, tol_rel)
    yaw_metrics = compute_series_metrics(ref_data["angles_rad"][:, 2], cand_data["angles_rad"][:, 2], ref_t, cand_t, tol_rel)

    # 3. Linear Velocities (fvel.x, fvel.y, fvel.z)
    fvel_x_metrics = compute_series_metrics(ref_data["fvel_m_s"][:, 0], cand_data["fvel_m_s"][:, 0], ref_t, cand_t, tol_rel)
    fvel_y_metrics = compute_series_metrics(ref_data["fvel_m_s"][:, 1], cand_data["fvel_m_s"][:, 1], ref_t, cand_t, tol_rel)
    fvel_z_metrics = compute_series_metrics(ref_data["fvel_m_s"][:, 2], cand_data["fvel_m_s"][:, 2], ref_t, cand_t, tol_rel)

    # 4. Angular Velocities (fomega.x, fomega.y, fomega.z)
    fomega_x_metrics = compute_series_metrics(ref_data["fomega_rad_s"][:, 0], cand_data["fomega_rad_s"][:, 0], ref_t, cand_t, tol_rel)
    fomega_y_metrics = compute_series_metrics(ref_data["fomega_rad_s"][:, 1], cand_data["fomega_rad_s"][:, 1], ref_t, cand_t, tol_rel)
    fomega_z_metrics = compute_series_metrics(ref_data["fomega_rad_s"][:, 2], cand_data["fomega_rad_s"][:, 2], ref_t, cand_t, tol_rel)

    all_dof_rel_rmse = [
        surge_metrics["rmse_relative_to_reference_peak"],
        sway_metrics["rmse_relative_to_reference_peak"],
        heave_metrics["rmse_relative_to_reference_peak"],
        roll_metrics["rmse_relative_to_reference_peak"],
        pitch_metrics["rmse_relative_to_reference_peak"],
        yaw_metrics["rmse_relative_to_reference_peak"],
    ]
    max_macro_rel_rmse = max(all_dof_rel_rmse)

    translational_pass = bool(
        surge_metrics["within_5pct_budget"] and sway_metrics["within_5pct_budget"] and heave_metrics["within_5pct_budget"]
    )
    rotational_pass = bool(
        roll_metrics["within_5pct_budget"] and pitch_metrics["within_5pct_budget"] and yaw_metrics["within_5pct_budget"]
    )
    all_6dof_pass = bool(translational_pass and rotational_pass)

    return {
        "translational_3dof": {
            "surge_m": surge_metrics,
            "sway_m": sway_metrics,
            "heave_m": heave_metrics,
            "within_5pct_budget": translational_pass,
        },
        "rotational_3dof": {
            "roll_rad": roll_metrics,
            "pitch_rad": pitch_metrics,
            "yaw_rad": yaw_metrics,
            "within_5pct_budget": rotational_pass,
        },
        "linear_velocity_m_s": {
            "fvel_x": fvel_x_metrics,
            "fvel_y": fvel_y_metrics,
            "fvel_z": fvel_z_metrics,
        },
        "angular_velocity_rad_s": {
            "fomega_x": fomega_x_metrics,
            "fomega_y": fomega_y_metrics,
            "fomega_z": fomega_z_metrics,
        },
        "evaluation_summary": {
            "heave_only_pass": heave_metrics["within_5pct_budget"],
            "translational_pass": translational_pass,
            "rotational_pass": rotational_pass,
            "all_6dof_pass": all_6dof_pass,
            "max_macro_relative_rmse": max_macro_rel_rmse,
            "macro_budget_5pct_overall_pass": all_6dof_pass,
        },
    }


def evaluate_angular_release_comparison(config_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    """Execute full 3DP comparison on authoritative FloatingInfo CSVs."""
    c_path = Path(config_path)
    if not c_path.is_file():
        raise FileNotFoundError(f"Config file not found: {c_path}")

    config = json.loads(c_path.read_text(encoding="utf-8"))
    tol_rel = float(config.get("tol_relative", DEFAULT_TOL_RELATIVE))

    resolutions_config = config.get("resolutions", {})
    loaded = {}
    for role in ("coarse", "medium", "fine"):
        if role not in resolutions_config:
            raise KeyError(f"Missing required resolution config: {role}")
        entry = resolutions_config[role]
        csv_path = Path(entry["floating_csv"])
        flt = load_floating_info_csv(csv_path)
        flt["dp_m"] = float(entry.get("dp_m", 0.0))
        flt["case_id"] = str(entry.get("case_id", ""))
        loaded[role] = flt

    pairwise = {
        "medium_vs_coarse": compare_rigid_pair(loaded["coarse"], loaded["medium"], tol_rel),
        "fine_vs_coarse": compare_rigid_pair(loaded["coarse"], loaded["fine"], tol_rel),
        "medium_vs_fine": compare_rigid_pair(loaded["fine"], loaded["medium"], tol_rel),
    }

    # Summary of individual resolution kinematics
    resolution_summaries = {}
    for role, data in loaded.items():
        resolution_summaries[role] = {
            "case_id": data["case_id"],
            "dp_m": data["dp_m"],
            "floating_csv": data["path"],
            "floating_csv_sha256": data["sha256"],
            "frames": data["frames"],
            "time_window_s": [float(data["time"][0]), float(data["time"][-1])],
            "initial_state": data["initial_state"],
            "final_state": data["final_state"],
            "peak_amplitudes": {
                "surge_m": float(np.max(np.abs(data["surge_m"]))),
                "sway_m": float(np.max(np.abs(data["sway_m"]))),
                "heave_m": float(np.max(np.abs(data["heave_m"]))),
                "roll_rad": float(np.max(np.abs(data["angles_rad"][:, 0]))),
                "pitch_rad": float(np.max(np.abs(data["angles_rad"][:, 1]))),
                "yaw_rad": float(np.max(np.abs(data["angles_rad"][:, 2]))),
                "fomega_rad_s": [
                    float(np.max(np.abs(data["fomega_rad_s"][:, 0]))),
                    float(np.max(np.abs(data["fomega_rad_s"][:, 1]))),
                    float(np.max(np.abs(data["fomega_rad_s"][:, 2]))),
                ],
            },
        }

    # Frozen Quality Contract and Physical Semantic Ledger
    report = {
        "schema": SCHEMA_REPORT,
        "case_id": "F6_ANGULAR_RELEASE_ALL3DP_SUPPORT",
        "family_id": "F6",
        "evaluator": "ds_data02_f6_angular_release_comparison_v2.py",
        "quality_contract": {
            "macro_operator": "Relative RMSE <= 5% (0.05) evaluated against reference peak amplitude",
            "time_window_s": [0.0, EXPECTED_WINDOW_S],
            "window_frames": WINDOW_FRAMES,
            "degrees_of_freedom": "all_6dof_mandatory (surge, sway, heave, roll, pitch, yaw)",
            "heave_only_gate": "rejected",
            "truncated_3s_window": "rejected",
            "post_hoc_orientation_budget": "rejected",
            "zero_velocity_spin_inference": "rejected (translational node velocity != internal body spin)",
            "inherited_zero_spin_qualification": "rejected (distinct physical candidate)",
        },
        "mass_and_support_semantics": {
            "declared_physical_rigid_mass_kg": 128.0,
            "declared_inertia_diagonal_kg_m2": [8.53333333333, 8.53333333333, 13.6533333333],
            "fluid_density_support_mass_kg": 256.0,
            "fluid_density_mass_interpretation": "Observed sum of PartVTK CSV Mass column equals support lattice fluid volume weight (0.256 m^3 * 1000 kg/m^3 = 256.0 kg).",
            "solver_interaction_weight_masspart_kg": {
                "coarse_dp025": 0.015625,
                "medium_dp020": 0.008,
                "fine_dp0125": 0.00195313,
            },
            "separation_policy": "Physical mass (128 kg), lattice support mass (~256 kg), and interaction weight (masspart) are strictly distinct and preserved.",
        },
        "resolutions": resolution_summaries,
        "pairwise_comparisons": pairwise,
        "scientific_qualification": {
            "q_n_status": "not_assessed",
            "qualification_claim": "none; comparison evidence only",
            "medium_vs_fine_all_6dof_pass": pairwise["medium_vs_fine"]["evaluation_summary"]["all_6dof_pass"],
            "medium_vs_fine_max_macro_relative_rmse": pairwise["medium_vs_fine"]["evaluation_summary"]["max_macro_relative_rmse"],
        },
    }

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Path to config JSON")
    parser.add_argument("--output", type=Path, required=True, help="Path to output report JSON")
    args = parser.parse_args()

    report = evaluate_angular_release_comparison(args.config, args.output)
    print(f"Comparison report generated: {args.output} (all_6dof_pass={report['scientific_qualification']['medium_vs_fine_all_6dof_pass']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
