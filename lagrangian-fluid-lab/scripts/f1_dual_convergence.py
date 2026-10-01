#!/usr/bin/env python3
"""Compute numerical convergence across F1 DUAL (Asymmetric Dual-Channel) reference resolutions.

Evaluates spatial refinement across Coarse (dp=0.020m), Medium (dp=0.012m), and Fine (dp=0.008m):
- Channel split fractions (lower channel width 0.34m vs upper channel 0.60m)
- Hydrodynamic front milestones (separator entry x=2.05m, exit/remerge x=1.25m, wall impact x=0.05m)
- Transverse center-of-mass deflection Y_com(t)
- Peak kinetic energy and splash height
- Mass conservation and exclusion accounting
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import h5py
import numpy as np


def analyze_dual_case(h5_path: Path) -> dict[str, Any]:
    h5_path = Path(h5_path).resolve()
    with h5py.File(h5_path, "r") as h:
        times = np.asarray(h["time"][:], dtype=np.float64)
        n_frames = len(times)

        # Initial frame accounting
        valid_0 = np.asarray(h["valid"][0], dtype=bool)
        fluid_0 = valid_0 & (np.asarray(h["type"][0], dtype=np.int64) == 3)
        initial_count = int(np.sum(fluid_0))
        initial_mass = float(np.sum(h["mass"][0][fluid_0]))
        initial_pos = np.asarray(h["position"][0][fluid_0], dtype=np.float64)

        # Time series storage
        com_list: list[list[float]] = []
        ke_list: list[float] = []
        mean_speed_list: list[float] = []
        max_speed_list: list[float] = []
        active_mass_list: list[float] = []
        active_count_list: list[int] = []
        lower_channel_mass_list: list[float] = []
        upper_channel_mass_list: list[float] = []
        max_z_splash_list: list[float] = []
        front_x_list: list[float] = []

        # Geometry bounds for channels:
        # Separator: x in [1.25, 2.05], y in [0.34, 0.40]
        # Lower channel: x in [1.25, 2.05], y < 0.34
        # Upper channel: x in [1.25, 2.05], y > 0.40
        for ti in range(n_frames):
            valid_frame = np.asarray(h["valid"][ti], dtype=bool)
            type_frame = np.asarray(h["type"][ti], dtype=np.int64)
            fluid = valid_frame & (type_frame == 3)
            if not np.any(fluid):
                com_list.append([0.0, 0.0, 0.0])
                ke_list.append(0.0)
                mean_speed_list.append(0.0)
                max_speed_list.append(0.0)
                active_mass_list.append(0.0)
                active_count_list.append(0)
                lower_channel_mass_list.append(0.0)
                upper_channel_mass_list.append(0.0)
                max_z_splash_list.append(0.0)
                front_x_list.append(3.22)
                continue

            pos = np.asarray(h["position"][ti], dtype=np.float64)[fluid]
            mass = np.asarray(h["mass"][ti], dtype=np.float64)[fluid]
            vel = np.asarray(h["velocity"][ti], dtype=np.float64)[fluid]
            total_m = float(np.sum(mass))

            com = np.sum(pos * mass[:, None], axis=0) / total_m
            speed_sq = np.sum(vel ** 2, axis=-1)
            ke = 0.5 * np.sum(mass * speed_sq)
            speed = np.sqrt(speed_sq)

            # Channel mass decomposition in channel zone x in [1.25, 2.05]
            in_x_channel = (pos[:, 0] >= 1.25) & (pos[:, 0] <= 2.05)
            lower_mask = in_x_channel & (pos[:, 1] < 0.34)
            upper_mask = in_x_channel & (pos[:, 1] > 0.40)

            # Downstream splash height in x < 0.5
            downstream_mask = pos[:, 0] < 0.5
            max_z = float(np.max(pos[downstream_mask, 2])) if np.any(downstream_mask) else float(np.max(pos[:, 2]))
            min_x = float(np.min(pos[:, 0]))

            com_list.append(com.tolist())
            ke_list.append(float(ke))
            mean_speed_list.append(float(np.mean(speed)))
            max_speed_list.append(float(np.max(speed)))
            active_mass_list.append(total_m)
            active_count_list.append(int(np.sum(fluid)))
            lower_channel_mass_list.append(float(np.sum(mass[lower_mask])))
            upper_channel_mass_list.append(float(np.sum(mass[upper_mask])))
            max_z_splash_list.append(max_z)
            front_x_list.append(min_x)

    front_x_arr = np.asarray(front_x_list)
    # Milestone times:
    # 1. Separator entry (x <= 2.05)
    t_entry = float(times[np.argmax(front_x_arr <= 2.05)]) if np.any(front_x_arr <= 2.05) else None
    # 2. Separator exit / remerge (x <= 1.25)
    t_remerge = float(times[np.argmax(front_x_arr <= 1.25)]) if np.any(front_x_arr <= 1.25) else None
    # 3. Downstream wall impact (x <= 0.05)
    t_impact = float(times[np.argmax(front_x_arr <= 0.05)]) if np.any(front_x_arr <= 0.05) else None

    # Channel split ratio during peak passage window (t in [0.4, 1.2] s)
    passage_mask = (times >= 0.4) & (times <= 1.2)
    tot_lower_passage = float(np.trapz(np.array(lower_channel_mass_list)[passage_mask], times[passage_mask]))
    tot_upper_passage = float(np.trapz(np.array(upper_channel_mass_list)[passage_mask], times[passage_mask]))
    split_ratio_lower = tot_lower_passage / (tot_lower_passage + tot_upper_passage) if (tot_lower_passage + tot_upper_passage) > 0 else 0.0

    return {
        "case_id": h5_path.parent.parent.name,
        "path": str(h5_path),
        "frame_count": n_frames,
        "time_start_s": float(times[0]),
        "time_end_s": float(times[-1]),
        "initial_count": initial_count,
        "initial_mass_kg": initial_mass,
        "final_active_count": active_count_list[-1],
        "final_active_mass_kg": active_mass_list[-1],
        "mass_loss_fraction": float((initial_mass - active_mass_list[-1]) / initial_mass),
        "milestones_s": {
            "separator_entry_x2p05": t_entry,
            "remerge_exit_x1p25": t_remerge,
            "downstream_wall_impact_x0p05": t_impact,
        },
        "channel_split": {
            "integrated_lower_mass_s": tot_lower_passage,
            "integrated_upper_mass_s": tot_upper_passage,
            "lower_channel_fraction": split_ratio_lower,
            "theoretical_width_fraction": 0.34 / (0.34 + 0.60),  # 0.3617
        },
        "peak_observables": {
            "peak_kinetic_energy_j": float(np.max(ke_list)),
            "peak_kinetic_energy_time_s": float(times[np.argmax(ke_list)]),
            "peak_splash_height_m": float(np.max(max_z_splash_list)),
            "peak_splash_time_s": float(times[np.argmax(max_z_splash_list)]),
            "max_fluid_speed_m_s": float(np.max(max_speed_list)),
        },
        "times_s": times.tolist(),
        "center_of_mass_m": com_list,
        "kinetic_energy_j": ke_list,
        "mean_speed_m_s": mean_speed_list,
        "active_mass_kg": active_mass_list,
    }


def compare_f1_dual_triplet(coarse_h5: Path, medium_h5: Path, fine_h5: Path, output_json: Path | None = None) -> dict[str, Any]:
    cases = {
        "COARSE": analyze_dual_case(coarse_h5),
        "MEDIUM": analyze_dual_case(medium_h5),
        "FINE": analyze_dual_case(fine_h5),
    }

    ref = cases["FINE"]
    comparison: dict[str, Any] = {
        "schema": "ds02.f1-dual-convergence.v1",
        "cases": {},
        "relative_errors_vs_fine": {},
        "monotonicity_checks": {},
    }

    for res in ("COARSE", "MEDIUM", "FINE"):
        c = cases[res]
        comparison["cases"][res] = {
            "initial_fluid_particles": c["initial_count"],
            "initial_fluid_mass_kg": c["initial_mass_kg"],
            "mass_loss_fraction": c["mass_loss_fraction"],
            "milestones_s": c["milestones_s"],
            "channel_split": c["channel_split"],
            "peak_observables": c["peak_observables"],
        }

    # Relative errors against Fine reference
    for res in ("COARSE", "MEDIUM"):
        c = cases[res]
        ke_err = abs(c["peak_observables"]["peak_kinetic_energy_j"] - ref["peak_observables"]["peak_kinetic_energy_j"]) / ref["peak_observables"]["peak_kinetic_energy_j"]
        splash_err = abs(c["peak_observables"]["peak_splash_height_m"] - ref["peak_observables"]["peak_splash_height_m"]) / ref["peak_observables"]["peak_splash_height_m"]
        split_err = abs(c["channel_split"]["lower_channel_fraction"] - ref["channel_split"]["lower_channel_fraction"]) / ref["channel_split"]["lower_channel_fraction"]
        mass_err = abs(c["initial_mass_kg"] - ref["initial_mass_kg"]) / ref["initial_mass_kg"]
        speed_err = abs(c["peak_observables"]["max_fluid_speed_m_s"] - ref["peak_observables"]["max_fluid_speed_m_s"]) / ref["peak_observables"]["max_fluid_speed_m_s"]

        comparison["relative_errors_vs_fine"][res] = {
            "initial_mass_rel_error": float(mass_err),
            "peak_kinetic_energy_rel_error": float(ke_err),
            "peak_splash_height_rel_error": float(splash_err),
            "channel_split_rel_error": float(split_err),
            "max_fluid_speed_rel_error": float(speed_err),
        }

    # Verify Monotonic Convergence
    err_c = comparison["relative_errors_vs_fine"]["COARSE"]
    err_m = comparison["relative_errors_vs_fine"]["MEDIUM"]
    comparison["monotonicity_checks"] = {
        "initial_mass_monotonic": bool(err_m["initial_mass_rel_error"] <= err_c["initial_mass_rel_error"]),
        "peak_ke_monotonic": bool(err_m["peak_kinetic_energy_rel_error"] <= err_c["peak_kinetic_energy_rel_error"]),
        "channel_split_monotonic": bool(err_m["channel_split_rel_error"] <= err_c["channel_split_rel_error"]),
        "max_speed_monotonic": bool(err_m["max_fluid_speed_rel_error"] <= err_c["max_fluid_speed_rel_error"]),
    }

    if output_json is not None:
        output_json = Path(output_json).resolve()
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(comparison, f, indent=2)

    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit F1 DUAL multi-resolution convergence.")
    parser.add_argument("--coarse", type=Path, required=True, help="Path to Coarse trajectory.h5")
    parser.add_argument("--medium", type=Path, required=True, help="Path to Medium trajectory.h5")
    parser.add_argument("--fine", type=Path, required=True, help="Path to Fine trajectory.h5")
    parser.add_argument("--output", type=Path, default=Path("f1_dual_convergence_report.json"), help="Output JSON path")
    args = parser.parse_args()

    result = compare_f1_dual_triplet(args.coarse, args.medium, args.fine, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
