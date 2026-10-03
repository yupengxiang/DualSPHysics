#!/usr/bin/env python3
"""
F3 CELL3 Four-Way Same-UID Transport Comparison (Version 2).

Compares same-UID Lagrangian transport across the complete time/save-refinement ladder:
  - NOMINAL: baseline CFL=0.05, tout=0.01s (377,423 steps, 836 frames)
  - TIME: half-CFL CFL=0.025, tout=0.01s (754,843 steps, 836 frames)
  - OUTPUT: fine save CFL=0.05, tout=0.002s (377,423 steps, 4,176 frames)
  - QUARTER: quarter-CFL CFL=0.0125, tout=0.01s (1,509,684 steps, 836 frames, minimum floor-limited)

Audit Governance Requirements (v2):
1. QUARTER is mandatory; fails immediately if missing (no silent 3-way fallback).
2. Strict common time window: [0.0, min(actual_end_all_4, 8.35)]. No extrapolation or fractional millisecond extension.
3. Derives full nominal observed count directly from actual arrays (no hardcoded 11,956 default or assertion).
4. Strict cohort verification: verifies positive native mass and exact 34,560 fluid identities across all 4 datasets.
5. Explicit depth alignment: aligns nominal trajectory (zone, uid) mapping to frame 0 z0 coordinates for all fluid particles.
6. Top-open event (event 1) CDF computed strictly from actual event 1 arrays with explicit censor accounting.
7. Unconditional CDF normalized by each dataset's own actual native initial mass.
8. Empty/undefined jointly observed subsets represented as null with denominator 0 (never 0.0 error).
9. Pure measurement claim boundary (q_i: transport_audit_measurement_only, q_n: not_assessed, no autogate).
"""

import argparse
import json
from pathlib import Path
import h5py
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(description="F3 CELL3 Four-Way Transport Comparison v2")
    parser.add_argument("--nominal-traj", required=True, help="Path to nominal trajectory.h5")
    parser.add_argument("--nominal-labels", required=True, help="Path to nominal labels H5")
    parser.add_argument("--time-labels", required=True, help="Path to half-CFL time labels H5")
    parser.add_argument("--output-labels", required=True, help="Path to fine-output labels H5")
    parser.add_argument("--quarter-labels", required=True, help="Path to quarter-CFL labels H5 (mandatory)")
    parser.add_argument("--output", required=True, help="Path to output JSON report")
    return parser.parse_args()


def load_dataset(name, path_str):
    path = Path(path_str)
    if not path.is_file():
        raise FileNotFoundError(f"Mandatory dataset {name} not found at {path_str}")

    with h5py.File(path, "r") as f:
        uids = f["particle_id"][:]
        zones = f["particle_zone"][:]
        mass = f["initial_fluid_mass_kg"][:]
        censor = f["first_passage_censor"][:]  # (N, 2)
        chord = f["first_passage_chord_time"][:]  # (N, 2)
        interval = f["first_passage_interval"][:]  # (N, 2, 2)
        time_arr = f["time"][:]

        num_loss_mass = float(f["numerical_loss_mass_kg"][-1])
        unk_mass = float(f["unknown_mass_kg"][-1])
        inv_mass = float(f["invalid_state_mass_kg"][-1])

    if not np.isfinite(mass).all() or (mass < 0).any():
        raise ValueError("Nonfinite or negative native cohort weights")
    if not np.isfinite(time_arr).all() or len(time_arr) < 2 or not (np.diff(time_arr) > 0).all() or time_arr[0] != 0:
        raise ValueError("Native time axis invalid")
    # Fluid cohort verification: positive native fluid mass
    fluid_mask = mass > 0.0
    fluid_count = int(fluid_mask.sum())
    if fluid_count != 34560:
        raise ValueError(f"{name} has {fluid_count} fluid particles with initial mass > 0, expected exactly 34560")

    uids_fl = uids[fluid_mask]
    zones_fl = zones[fluid_mask]
    if not (zones_fl == 0).all():
        raise ValueError(f"{name} fluid cohort contains non-zero particle zones: {np.unique(zones_fl)}")

    # Sort deterministically by UID
    sort_idx = np.argsort(uids_fl)
    uids_sorted = uids_fl[sort_idx]
    zones_sorted = zones_fl[sort_idx]
    mass_sorted = mass[fluid_mask][sort_idx]
    censor_sorted = censor[fluid_mask][sort_idx]
    chord_sorted = chord[fluid_mask][sort_idx]
    interval_sorted = interval[fluid_mask][sort_idx]

    if len(np.unique(uids_sorted)) != fluid_count or not np.array_equal(uids_sorted, np.arange(73440, 108000)):
        raise ValueError("Exact declared native fluid UID cohort required")
    if not np.isin(censor_sorted, [0, 1]).all():
        raise ValueError("Unsupported canonical censor code")
    observed = censor_sorted == 0
    if not np.isfinite(chord_sorted[observed]).all() or not np.isfinite(interval_sorted[observed]).all():
        raise ValueError("Observed event timing is nonfinite")
    if not (interval_sorted[..., 1][observed] > interval_sorted[..., 0][observed]).all():
        raise ValueError("Observed brackets must have positive width")
    total_initial_mass = float(np.sum(mass_sorted, dtype=np.float64))

    return {
        "name": name,
        "path": str(path.resolve()),
        "uids": uids_sorted,
        "zones": zones_sorted,
        "mass": mass_sorted,
        "censor": censor_sorted,
        "chord": chord_sorted,
        "interval": interval_sorted,
        "time": time_arr,
        "fluid_count": fluid_count,
        "total_initial_mass_kg": total_initial_mass,
        "native_end_time_s": float(time_arr[-1]),
        "frame_count": int(len(time_arr)),
        "unknown_loss_stats": {
            "final_numerical_loss_mass_kg": num_loss_mass,
            "final_unknown_mass_kg": unk_mass,
            "final_invalid_state_mass_kg": inv_mass,
            "event0_censor_counts": {
                "observed_passages": int((censor_sorted[:, 0] == 0).sum()),
                "right_censored": int((censor_sorted[:, 0] == 1).sum()),
                "unknown_loss": int((censor_sorted[:, 0] == 2).sum()),
            },
            "event1_censor_counts": {
                "observed_passages": int((censor_sorted[:, 1] == 0).sum()),
                "right_censored": int((censor_sorted[:, 1] == 1).sum()),
                "unknown_loss": int((censor_sorted[:, 1] == 2).sum()),
            },
        },
    }


def align_depth_positions(nominal_traj_path, fluid_uids, fluid_zones):
    traj_path = Path(nominal_traj_path)
    if not traj_path.is_file():
        raise FileNotFoundError(f"Nominal trajectory not found at {nominal_traj_path}")

    with h5py.File(traj_path, "r") as f:
        traj_ids = f["particle_id"][:]
        traj_zones = f["particle_zone"][:]
        pos0 = f["position"][0]  # (N_total, 3)

    if len(set(zip(traj_zones.tolist(), traj_ids.tolist()))) != len(traj_ids):
        raise ValueError("Nominal trajectory identities are not unique")
    lookup = {(int(z), int(u)): float(pos[2]) for z, u, pos in zip(traj_zones, traj_ids, pos0)}

    z0_fluid = np.array([lookup[(int(z), int(u))] for z, u in zip(fluid_zones, fluid_uids)], dtype=np.float64)

    z_min, z_max = float(z0_fluid.min()), float(z0_fluid.max())
    z_cut1, z_cut2 = z_min + (z_max-z_min)/3, z_min + 2*(z_max-z_min)/3
    masks = {
        "bottom": z0_fluid < z_cut1,
        "middle": (z0_fluid >= z_cut1) & (z0_fluid < z_cut2),
        "top": z0_fluid >= z_cut2,
        "all": np.ones(len(fluid_uids), dtype=bool),
    }

    counts = {k: int(m.sum()) for k, m in masks.items()}
    return z0_fluid, masks, counts


def compute_unconditional_cdf(d, event_idx, common_window_end):
    m_total = d["total_initial_mass_kg"]
    obs_mask = (d["censor"][:, event_idx] == 0) & (d["chord"][:, event_idx] <= common_window_end)
    t_obs = d["chord"][:, event_idx][obs_mask]
    w_obs = d["mass"][obs_mask]

    if len(t_obs) == 0:
        grid_t = np.array([0.0, common_window_end], dtype=np.float64)
        grid_cdf = np.array([0.0, 0.0], dtype=np.float64)
        return grid_t, grid_cdf, 0.0, 0, 0.0

    sort_idx = np.argsort(t_obs)
    t_sorted = t_obs[sort_idx]
    w_cum = np.cumsum(w_obs[sort_idx], dtype=np.float64) / m_total

    grid_t = np.concatenate([[0.0], t_sorted, [common_window_end]])
    grid_cdf = np.concatenate([[0.0], w_cum, [w_cum[-1]]])
    return grid_t, grid_cdf, float(w_cum[-1]), int(len(t_obs)), float(np.sum(w_obs, dtype=np.float64))


def compute_ks_and_cdf_diff(grid_t_a, grid_cdf_a, grid_t_b, grid_cdf_b, common_window_end):
    # Combine union of jump points within common window
    eval_t = np.unique(np.concatenate([grid_t_a, grid_t_b]))
    eval_t = eval_t[(eval_t >= 0.0) & (eval_t <= common_window_end)]

    if len(eval_t) == 0:
        return 0.0, 0.0

    # Step function lookup (searchsorted with right side)
    idx_a = np.searchsorted(grid_t_a, eval_t, side="right") - 1
    idx_b = np.searchsorted(grid_t_b, eval_t, side="right") - 1
    idx_a = np.clip(idx_a, 0, len(grid_cdf_a) - 1)
    idx_b = np.clip(idx_b, 0, len(grid_cdf_b) - 1)

    cdf_a = grid_cdf_a[idx_a]
    cdf_b = grid_cdf_b[idx_b]

    diffs = np.abs(cdf_a - cdf_b)
    max_idx = int(np.argmax(diffs))
    return float(diffs[max_idx]), float(eval_t[max_idx])


def compute_timing_stats(deltas):
    if len(deltas) == 0:
        return {
            "count": 0,
            "denominator": 0,
            "mean_signed_delta_s": None,
            "mean_absolute_delta_s": None,
            "median_absolute_delta_s": None,
            "p75_absolute_delta_s": None,
            "p90_absolute_delta_s": None,
            "p95_absolute_delta_s": None,
            "max_absolute_delta_s": None,
        }

    abs_d = np.abs(deltas)
    return {
        "count": int(len(deltas)),
        "denominator": int(len(deltas)),
        "mean_signed_delta_s": float(np.mean(deltas)),
        "mean_absolute_delta_s": float(np.mean(abs_d)),
        "median_absolute_delta_s": float(np.median(abs_d)),
        "p75_absolute_delta_s": float(np.percentile(abs_d, 75)),
        "p90_absolute_delta_s": float(np.percentile(abs_d, 90)),
        "p95_absolute_delta_s": float(np.percentile(abs_d, 95)),
        "max_absolute_delta_s": float(np.max(abs_d)),
    }


def compare_pair(d_a, d_b, depth_masks, common_window_end, nominal_observed_full_ev0, nominal_observed_full_ev1):
    assert np.array_equal(d_a["uids"], d_b["uids"]), f"UID mismatch between {d_a['name']} and {d_b['name']}"
    assert np.array_equal(d_a["zones"], d_b["zones"]), f"Zone mismatch between {d_a['name']} and {d_b['name']}"

    pair_name = f"{d_a['name']}_vs_{d_b['name']}"
    events_report = {}

    for event_idx, event_name, nominal_full_obs in [
        (0, "event0_sloshing_cross", nominal_observed_full_ev0),
        (1, "event1_top_open_spill", nominal_observed_full_ev1),
    ]:
        obs_a = (d_a["censor"][:, event_idx] == 0) & (d_a["chord"][:, event_idx] <= common_window_end)
        obs_b = (d_b["censor"][:, event_idx] == 0) & (d_b["chord"][:, event_idx] <= common_window_end)

        count_a = int(obs_a.sum())
        count_b = int(obs_b.sum())
        joint_mask = obs_a & obs_b
        joint_count = int(joint_mask.sum())

        a_only_mask = obs_a & ~obs_b
        b_only_mask = ~obs_a & obs_b
        a_only_count = int(a_only_mask.sum())
        b_only_count = int(b_only_mask.sum())
        switching_count = a_only_count + b_only_count
        net_change = count_b - count_a

        # Paired interval non-overlap
        if joint_count > 0:
            int_a = d_a["interval"][:, event_idx, :][joint_mask]
            int_b = d_b["interval"][:, event_idx, :][joint_mask]
            overlap = (int_a[:, 0] <= int_b[:, 1]) & (int_b[:, 0] <= int_a[:, 1])
            nonoverlap_count = int((~overlap).sum())
            fraction_nonoverlap = float(nonoverlap_count / joint_count)
            t_a = d_a["chord"][:, event_idx][joint_mask]
            t_b = d_b["chord"][:, event_idx][joint_mask]
            deltas = t_b - t_a
            timing_stats = compute_timing_stats(deltas)
        else:
            nonoverlap_count = 0
            fraction_nonoverlap = None
            timing_stats = compute_timing_stats(np.array([], dtype=np.float64))

        # Unconditional CDF comparison
        grid_t_a, grid_cdf_a, max_cdf_a, obs_cnt_a, obs_mass_a = compute_unconditional_cdf(d_a, event_idx, common_window_end)
        grid_t_b, grid_cdf_b, max_cdf_b, obs_cnt_b, obs_mass_b = compute_unconditional_cdf(d_b, event_idx, common_window_end)
        max_cdf_diff, t_at_max = compute_ks_and_cdf_diff(grid_t_a, grid_cdf_a, grid_t_b, grid_cdf_b, common_window_end)

        # Temporal subwindows progression
        temporal_subwindows = []
        for t_cut in [1.5, 2.5, 5.0]:
            sub_obs_a = obs_a & (d_a["chord"][:, event_idx] <= t_cut)
            sub_obs_b = obs_b & (d_b["chord"][:, event_idx] <= t_cut)
            sub_joint = sub_obs_a & sub_obs_b
            sub_joint_count = int(sub_joint.sum())
            sub_a_only = int((sub_obs_a & ~sub_obs_b).sum())
            sub_b_only = int((~sub_obs_a & sub_obs_b).sum())
            sub_switching = sub_a_only + sub_b_only

            frac_joint = float(sub_switching / sub_joint_count) if sub_joint_count > 0 else None
            frac_nominal_full = float(sub_switching / nominal_full_obs) if nominal_full_obs > 0 else None

            if sub_joint_count > 0:
                sub_deltas = d_b["chord"][:, event_idx][sub_joint] - d_a["chord"][:, event_idx][sub_joint]
                sub_stats = compute_timing_stats(sub_deltas)
            else:
                sub_stats = compute_timing_stats(np.array([], dtype=np.float64))

            temporal_subwindows.append({
                "window_cutoff_s": t_cut,
                "a_observed_count": int(sub_obs_a.sum()),
                "b_observed_count": int(sub_obs_b.sum()),
                "jointly_observed_count": sub_joint_count,
                "switching_uids_count": sub_switching,
                "a_only_count": sub_a_only,
                "b_only_count": sub_b_only,
                "switching_fraction_vs_window_joint": frac_joint,
                "switching_fraction_vs_nominal_full": frac_nominal_full,
                "timing_statistics_joint": sub_stats,
            })

        # Depth layers stratification
        depth_layers = {}
        for layer_name in ["bottom", "middle", "top"]:
            layer_m = depth_masks[layer_name]
            layer_joint = joint_mask & layer_m
            layer_joint_count = int(layer_joint.sum())
            layer_a_obs = int((obs_a & layer_m).sum())
            layer_b_obs = int((obs_b & layer_m).sum())
            layer_switch = int(((a_only_mask | b_only_mask) & layer_m).sum())

            if layer_joint_count > 0:
                l_int_a = d_a["interval"][:, event_idx, :][layer_joint]
                l_int_b = d_b["interval"][:, event_idx, :][layer_joint]
                l_overlap = (l_int_a[:, 0] <= l_int_b[:, 1]) & (l_int_b[:, 0] <= l_int_a[:, 1])
                l_nonoverlap = int((~l_overlap).sum())
                l_frac_nonoverlap = float(l_nonoverlap / layer_joint_count)
                l_deltas = d_b["chord"][:, event_idx][layer_joint] - d_a["chord"][:, event_idx][layer_joint]
                l_stats = compute_timing_stats(l_deltas)
            else:
                l_nonoverlap = 0
                l_frac_nonoverlap = None
                l_stats = compute_timing_stats(np.array([], dtype=np.float64))

            depth_layers[layer_name] = {
                "total_particles_in_layer": int(layer_m.sum()),
                "a_observed_count": layer_a_obs,
                "b_observed_count": layer_b_obs,
                "jointly_observed_count": layer_joint_count,
                "switching_uids_count": layer_switch,
                "paired_brackets_nonoverlapping_count": l_nonoverlap,
                "fraction_of_joint_nonoverlapping": l_frac_nonoverlap,
                "timing_statistics_joint": l_stats,
            }

        events_report[event_name] = {
            "a_observed_count": count_a,
            "b_observed_count": count_b,
            "jointly_observed_count": joint_count,
            "switching_uids_count": switching_count,
            "a_only_observed_count": a_only_count,
            "b_only_observed_count": b_only_count,
            "net_count_change": net_change,
            "paired_brackets_nonoverlapping_count": nonoverlap_count,
            "fraction_of_joint_nonoverlapping": fraction_nonoverlap,
            "unconditional_first_passage_cdf": {
                "a_max_cdf": max_cdf_a,
                "b_max_cdf": max_cdf_b,
                "max_absolute_cdf_diff": max_cdf_diff,
                "time_at_max_diff_s": t_at_max,
                "normalization": "own_actual_native_initial_fluid_mass",
            },
            "timing_statistics_full_window_joint": timing_stats,
            "temporal_subwindows": temporal_subwindows,
            "depth_layer_stratification": depth_layers,
        }

    return events_report


def main():
    args = parse_args()

    # Load all four mandatory datasets
    nominal = load_dataset("nominal", args.nominal_labels)
    time = load_dataset("time", args.time_labels)
    output = load_dataset("output", args.output_labels)
    quarter = load_dataset("quarter", args.quarter_labels)

    # Cohort cross-check
    for d in [time, output, quarter]:
        if not np.array_equal(nominal["uids"], d["uids"]):
            raise ValueError(f"Cohort UID mismatch between nominal and {d['name']}")
        if not np.array_equal(nominal["zones"], d["zones"]):
            raise ValueError(f"Cohort Zone mismatch between nominal and {d['name']}")

    for d in [time, output, quarter]:
        if not np.allclose(nominal["mass"], d["mass"], rtol=1e-10, atol=1e-12):
            raise ValueError("Native same-UID initial mass differs")
    # Derive common window end: [0, min(actual_end_all_4, 8.35)]
    common_window_end = min(8.35, nominal["native_end_time_s"], time["native_end_time_s"],
                            output["native_end_time_s"], quarter["native_end_time_s"])

    # Align depth coordinates from nominal trajectory
    z0_fluid, depth_masks, depth_counts = align_depth_positions(args.nominal_traj, nominal["uids"], nominal["zones"])

    # Derive full nominal observed counts from actual arrays
    nominal_obs_ev0 = int(((nominal["censor"][:, 0] == 0) & (nominal["chord"][:, 0] <= common_window_end)).sum())
    nominal_obs_ev1 = int(((nominal["censor"][:, 1] == 0) & (nominal["chord"][:, 1] <= common_window_end)).sum())

    datasets = [nominal, time, output, quarter]
    pairwise = {}

    for i in range(len(datasets)):
        for j in range(i + 1, len(datasets)):
            d_a = datasets[i]
            d_b = datasets[j]
            key = f"{d_a['name']}_vs_{d_b['name']}"
            pairwise[key] = compare_pair(d_a, d_b, depth_masks, common_window_end, nominal_obs_ev0, nominal_obs_ev1)

    # Four-way comparison summary matrix
    summary_matrix = []
    for pair_key, pair_val in pairwise.items():
        ev0 = pair_val["event0_sloshing_cross"]
        ev1 = pair_val["event1_top_open_spill"]
        summary_matrix.append({
            "pair": pair_key,
            "event0_mean_abs_delta_s": ev0["timing_statistics_full_window_joint"]["mean_absolute_delta_s"],
            "event0_p95_abs_delta_s": ev0["timing_statistics_full_window_joint"]["p95_absolute_delta_s"],
            "event0_max_abs_delta_s": ev0["timing_statistics_full_window_joint"]["max_absolute_delta_s"],
            "event0_switching_uids_count": ev0["switching_uids_count"],
            "event0_nonoverlapping_brackets_count": ev0["paired_brackets_nonoverlapping_count"],
            "event0_fraction_nonoverlapping": ev0["fraction_of_joint_nonoverlapping"],
            "event0_max_cdf_diff": ev0["unconditional_first_passage_cdf"]["max_absolute_cdf_diff"],
            "event1_switching_uids_count": ev1["switching_uids_count"],
            "event1_max_cdf_diff": ev1["unconditional_first_passage_cdf"]["max_absolute_cdf_diff"],
        })

    report = {
        "schema": "ds02.f3.quarter-cfl-four-way-comparison.v3",
        "family_id": "F3",
        "case_id": "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen",
        "audit_version": "v3",
        "claim_boundary": {
            "model_invoked": False,
            "production": "not_evaluated",
            "production_granted": False,
            "q_i": "transport_audit_measurement_only",
            "q_n": "not_assessed",
            "q_n_granted": False,
            "training": "not_authorized",
            "evaluation_type": "empirical_measurement_only",
            "governance_note": "Descriptive transport ladder audit; no Q-N gate claim, no autogate pass/fail",
        },
        "common_window": {
            "start_s": 0.0,
            "end_s": common_window_end,
            "window_rule": "min(actual_end_all_4, 8.35)",
        },
        "fluid_cohort": {
            "count": 34560,
            "positive_mass_verified": True,
            "unique_uids": True,
            "zones": [0],
            "initial_native_fluid_mass_kg": {d["name"]: d["total_initial_mass_kg"] for d in datasets},
            "depth_distribution": depth_counts,
        },
        "derived_nominal_observed": {
            "event0_observed_count": nominal_obs_ev0,
            "event1_observed_count": nominal_obs_ev1,
            "derivation": "computed_directly_from_nominal_arrays",
        },
        "unknown_loss_audit": {d["name"]: d["unknown_loss_stats"] for d in datasets},
        "summary_matrix": summary_matrix,
        "pairwise_comparisons": pairwise,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as writer:
        writer.write(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"Report v2 successfully written to {out_path}", flush=True)


if __name__ == "__main__":
    main()
