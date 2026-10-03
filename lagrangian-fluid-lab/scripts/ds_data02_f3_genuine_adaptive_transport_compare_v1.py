#!/usr/bin/env python3
"""F3 CELL3 Genuine Adaptive Paired Transport Comparison (Version 1).

Compares same-UID Lagrangian transport between the genuine adaptive CFL pair:
  - BASELINE (Repair 1): CFL=0.05, CoefDtMin=0.005, 383,189 steps, 836 frames, 0 clamps
  - GENUINE HALF (Repair 2): CFL=0.025, CoefDtMin=0.0025, 766,348 steps, 836 frames, 0 clamps
  - Exact step ratio: 766,348 / 383,189 = 1.99992x (~2.000x exact CFL halving).

Audit & Governance Rules:
1. Reuses frozen operator config f3_legacy_plain_full_transport_config.v1.json (69c3a478...).
2. Binds actual same-UID weighted native events, censors, first passage, residence, and reentry.
3. Computes exact empirical CDF supremum over union jump knots as a DESCRIPTIVE measurement (NOT a 5% gate).
4. Strictly evaluates on the common time window [0.0, min(8.35, actual_ends)] without extrapolation.
5. Strict fluid cohort verification: positive native fluid mass and exact 34,560 identities.
6. Frozen transport budgets source preregistration (prereg 004) and historical anchors bound.
7. Pure descriptive measurement claim boundary: q_i: transport_audit_measurement_only, q_n: not_assessed.
8. No quarter CFL substitution: quarter CFL was floor-clamped and is preserved as secondary historical evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
from typing import Any

import h5py
import numpy as np


SCHEMA = "ds02.f3.genuine-adaptive-transport-comparison.v1"
FAMILY_ID = "F3"
NOMINAL_WINDOW_END_S = 8.35


def digest(path: Path | str) -> str:
    """Compute sha256 checksum of a file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def usage_stats() -> dict[str, float]:
    """Capture process resource usage."""
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        v = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(v.ru_utime)
        result[f"{label}_system_seconds"] = float(v.ru_stime)
        result[f"{label}_max_rss_kib"] = float(v.ru_maxrss)
    return result


def compute_timing_stats(deltas: np.ndarray, weights: np.ndarray | None = None) -> dict[str, Any]:
    """Compute timing statistics for paired deltas, handling empty subsets safely."""
    count = int(len(deltas))
    if count == 0:
        return {
            "count": 0,
            "denominator": 0,
            "mean_signed_delta_s": None,
            "mass_weighted_mean_signed_delta_s": None,
            "mean_absolute_delta_s": None,
            "mass_weighted_mean_absolute_delta_s": None,
            "median_absolute_delta_s": None,
            "p75_absolute_delta_s": None,
            "p90_absolute_delta_s": None,
            "p95_absolute_delta_s": None,
            "p99_absolute_delta_s": None,
            "max_absolute_delta_s": None,
            "min_absolute_delta_s": None,
        }

    abs_deltas = np.abs(deltas)
    mean_signed = float(np.mean(deltas))
    mean_abs = float(np.mean(abs_deltas))
    median_abs = float(np.median(abs_deltas))
    p75_abs = float(np.percentile(abs_deltas, 75))
    p90_abs = float(np.percentile(abs_deltas, 90))
    p95_abs = float(np.percentile(abs_deltas, 95))
    p99_abs = float(np.percentile(abs_deltas, 99))
    max_abs = float(np.max(abs_deltas))
    min_abs = float(np.min(abs_deltas))

    if weights is not None and len(weights) == count and np.sum(weights) > 0:
        w_sum = float(np.sum(weights))
        w_mean_signed = float(np.sum(deltas * weights) / w_sum)
        w_mean_abs = float(np.sum(abs_deltas * weights) / w_sum)
    else:
        w_mean_signed = mean_signed
        w_mean_abs = mean_abs

    return {
        "count": count,
        "denominator": count,
        "mean_signed_delta_s": mean_signed,
        "mass_weighted_mean_signed_delta_s": w_mean_signed,
        "mean_absolute_delta_s": mean_abs,
        "mass_weighted_mean_absolute_delta_s": w_mean_abs,
        "median_absolute_delta_s": median_abs,
        "p75_absolute_delta_s": p75_abs,
        "p90_absolute_delta_s": p90_abs,
        "p95_absolute_delta_s": p95_abs,
        "p99_absolute_delta_s": p99_abs,
        "max_absolute_delta_s": max_abs,
        "min_absolute_delta_s": min_abs,
    }


def compute_exact_cdf_supremum_and_l1(
    times_a: np.ndarray,
    weights_a: np.ndarray,
    times_b: np.ndarray,
    weights_b: np.ndarray,
    total_mass_a: float,
    total_mass_b: float,
    window_start: float,
    window_end: float,
) -> dict[str, Any]:
    """Compute the exact empirical CDF supremum over union jump knots and L1 integrated deviation.

    For two empirical step-function CDFs F_a and F_b, the supremum of |F_b(t) - F_a(t)|
    is guaranteed to be attained at one of the knot discontinuities (right limit or left limit).
    Integration is computed exactly over constant difference intervals.
    """
    if total_mass_a <= 0 or total_mass_b <= 0:
        raise ValueError("Total masses must be strictly positive for CDF evaluation")

    # Filter to window
    mask_a = (times_a >= window_start) & (times_a <= window_end)
    t_a = times_a[mask_a]
    w_a = weights_a[mask_a]

    mask_b = (times_b >= window_start) & (times_b <= window_end)
    t_b = times_b[mask_b]
    w_b = weights_b[mask_b]

    # Sort each
    order_a = np.argsort(t_a)
    t_a_sorted = t_a[order_a]
    cumsum_a = np.cumsum(w_a[order_a], dtype=np.float64) / total_mass_a

    order_b = np.argsort(t_b)
    t_b_sorted = t_b[order_b]
    cumsum_b = np.cumsum(w_b[order_b], dtype=np.float64) / total_mass_b

    # Form union of all jump knots plus window boundaries
    knots = np.unique(np.concatenate([[window_start], t_a_sorted, t_b_sorted, [window_end]]))
    knots = knots[(knots >= window_start) & (knots <= window_end)]

    if len(knots) <= 1:
        return {
            "knot_supremum_absolute_deviation": 0.0,
            "time_at_knot_supremum_s": float(window_start),
            "l1_integrated_cdf_deviation_mass_s": 0.0,
            "baseline_terminal_cdf": 0.0,
            "half_terminal_cdf": 0.0,
            "baseline_deciles": {},
            "half_deciles": {},
            "sampled_cdf_baseline": {},
            "sampled_cdf_half": {},
        }

    # Evaluate right limits at knots: F(t)
    idx_a_right = np.searchsorted(t_a_sorted, knots, side="right") - 1
    cdf_a_right = np.where(idx_a_right >= 0, cumsum_a[np.maximum(0, idx_a_right)], 0.0)

    idx_b_right = np.searchsorted(t_b_sorted, knots, side="right") - 1
    cdf_b_right = np.where(idx_b_right >= 0, cumsum_b[np.maximum(0, idx_b_right)], 0.0)

    # Evaluate left limits at knots: F(t-)
    idx_a_left = np.searchsorted(t_a_sorted, knots, side="left") - 1
    cdf_a_left = np.where(idx_a_left >= 0, cumsum_a[np.maximum(0, idx_a_left)], 0.0)

    idx_b_left = np.searchsorted(t_b_sorted, knots, side="left") - 1
    cdf_b_left = np.where(idx_b_left >= 0, cumsum_b[np.maximum(0, idx_b_left)], 0.0)

    diff_right = np.abs(cdf_b_right - cdf_a_right)
    diff_left = np.abs(cdf_b_left - cdf_a_left)

    max_right_idx = int(np.argmax(diff_right))
    max_left_idx = int(np.argmax(diff_left))

    max_right_val = float(diff_right[max_right_idx])
    max_left_val = float(diff_left[max_left_idx])

    if max_right_val >= max_left_val:
        sup_dev = max_right_val
        t_sup = float(knots[max_right_idx])
    else:
        sup_dev = max_left_val
        t_sup = float(knots[max_left_idx])

    # Exact L1 integration: on open interval (knots[k], knots[k+1]), CDF values are constant = right-value at knots[k]
    dt_intervals = np.diff(knots)
    diff_intervals = diff_right[:-1]
    l1_dev = float(np.sum(diff_intervals * dt_intervals))

    # Compute passage time deciles (10% to 90% of total initial mass)
    deciles_a: dict[str, float | None] = {}
    deciles_b: dict[str, float | None] = {}
    for q in range(10, 100, 10):
        frac = q / 100.0
        # A
        idx_q_a = np.searchsorted(cumsum_a, frac, side="left")
        deciles_a[f"p{q}_time_s"] = float(t_a_sorted[idx_q_a]) if idx_q_a < len(t_a_sorted) else None
        # B
        idx_q_b = np.searchsorted(cumsum_b, frac, side="left")
        deciles_b[f"p{q}_time_s"] = float(t_b_sorted[idx_q_b]) if idx_q_b < len(t_b_sorted) else None

    # Sample CDF at 1-second intervals for clean JSON report presentation
    sample_times = [float(t) for t in range(int(window_start), int(window_end) + 1)]
    idx_s_a = np.searchsorted(t_a_sorted, sample_times, side="right") - 1
    idx_s_b = np.searchsorted(t_b_sorted, sample_times, side="right") - 1
    sampled_a = {f"t_{t:.0f}s": float(cumsum_a[i]) if i >= 0 else 0.0 for t, i in zip(sample_times, idx_s_a)}
    sampled_b = {f"t_{t:.0f}s": float(cumsum_b[i]) if i >= 0 else 0.0 for t, i in zip(sample_times, idx_s_b)}

    return {
        "knot_supremum_absolute_deviation": sup_dev,
        "time_at_knot_supremum_s": t_sup,
        "l1_integrated_cdf_deviation_mass_s": l1_dev,
        "baseline_terminal_cdf": float(cumsum_a[-1]) if len(cumsum_a) > 0 else 0.0,
        "half_terminal_cdf": float(cumsum_b[-1]) if len(cumsum_b) > 0 else 0.0,
        "baseline_deciles": deciles_a,
        "half_deciles": deciles_b,
        "sampled_cdf_baseline": sampled_a,
        "sampled_cdf_half": sampled_b,
        "policy": "Strictly descriptive measurement; no invented 5% CDF pass gate or containment claim.",
    }


def analyze_reentry(
    dest_series: np.ndarray,
    source_labels: np.ndarray,
    fluid_mask: np.ndarray,
) -> dict[str, Any]:
    """Analyze same-UID particle reentry / recrossings between destination regions.

    Source labels: 1 = left (x < 0), 2 = right (x >= 0).
    Destination codes: 1 = left, 2 = right.
    A particle undergoes reentry if it crosses from its initial source region to the opposite
    region and subsequently returns to its initial region.
    """
    nt, n_total = dest_series.shape
    fl_indices = np.where(fluid_mask)[0]
    sources = source_labels[fl_indices]

    reentered_flags = np.zeros(len(fl_indices), dtype=bool)
    first_exit_frames = np.full(len(fl_indices), -1, dtype=int)
    total_transition_events = 0

    for idx, (p_idx, src) in enumerate(zip(fl_indices, sources)):
        if src not in (1, 2):
            continue
        opp = 2 if src == 1 else 1
        traj = dest_series[:, p_idx]

        # Find transitions
        # Mask where particle was in source, then in opp, then back in source
        in_opp = (traj == opp)
        if not np.any(in_opp):
            continue

        first_opp_frame = int(np.argmax(in_opp))
        first_exit_frames[idx] = first_opp_frame

        # Check if particle re-entered source region at any subsequent frame
        subsequent_src = (traj[first_opp_frame + 1:] == src)
        if np.any(subsequent_src):
            reentered_flags[idx] = True

        # Count state transitions
        valid_dest = (traj == 1) | (traj == 2)
        valid_traj = traj[valid_dest]
        if len(valid_traj) > 1:
            diffs = (valid_traj[1:] != valid_traj[:-1])
            total_transition_events += int(np.sum(diffs))

    return {
        "reentered_particles_count": int(np.sum(reentered_flags)),
        "reentered_mask": reentered_flags,
        "total_transition_events_count": total_transition_events,
    }


def compare_f3_genuine_adaptive_transport(
    baseline_labels_path: Path | str,
    baseline_report_path: Path | str,
    baseline_receipt_path: Path | str,
    half_labels_path: Path | str,
    half_report_path: Path | str,
    half_receipt_path: Path | str,
    config_path: Path | str,
    preregistration_path: Path | str,
    protocol_path: Path | str,
    gate_path: Path | str,
    output_path: Path | str,
    trajectory_path: Path | str | None = None,
) -> dict[str, Any]:
    """Execute primary paired transport comparison between baseline and half adaptive runs."""
    baseline_labels_p = Path(baseline_labels_path)
    baseline_report_p = Path(baseline_report_path)
    baseline_receipt_p = Path(baseline_receipt_path)
    half_labels_p = Path(half_labels_path)
    half_report_p = Path(half_report_path)
    half_receipt_p = Path(half_receipt_path)
    config_p = Path(config_path)
    prereg_p = Path(preregistration_path)
    protocol_p = Path(protocol_path)
    gate_p = Path(gate_path)
    output_p = Path(output_path)

    # Verify input files exist
    mandatory_files = [
        baseline_labels_p, baseline_report_p, baseline_receipt_p,
        half_labels_p, half_report_p, half_receipt_p,
        config_p, prereg_p, protocol_p, gate_p,
    ]
    for p in mandatory_files:
        if not p.is_file():
            raise FileNotFoundError(f"Mandatory input file not found: {p}")

    # Compute sha256 digests
    digests = {str(p.resolve()): digest(p) for p in mandatory_files}
    if trajectory_path is not None and Path(trajectory_path).is_file():
        traj_p = Path(trajectory_path)
        digests[str(traj_p.resolve())] = digest(traj_p)

    # Load and verify receipts
    base_receipt = json.loads(baseline_receipt_p.read_text())
    half_receipt = json.loads(half_receipt_p.read_text())
    if base_receipt.get("status") != "completed" or base_receipt.get("returncode") != 0:
        raise ValueError(f"Baseline receipt status invalid: {base_receipt.get('status')}, code {base_receipt.get('returncode')}")
    if half_receipt.get("status") != "completed" or half_receipt.get("returncode") != 0:
        raise ValueError(f"Half receipt status invalid: {half_receipt.get('status')}, code {half_receipt.get('returncode')}")

    # Load and verify reports
    base_report = json.loads(baseline_report_p.read_text())
    half_report = json.loads(half_report_p.read_text())
    if base_report.get("sha256") != digests[str(baseline_labels_p.resolve())]:
        raise ValueError("Baseline report sha256 disagrees with actual baseline labels H5 digest")
    if half_report.get("sha256") != digests[str(half_labels_p.resolve())]:
        raise ValueError("Half report sha256 disagrees with actual half labels H5 digest")

    # Load frozen config, prereg, protocol, gate
    config = json.loads(config_p.read_text())
    prereg = json.loads(prereg_p.read_text())
    protocol = json.loads(protocol_p.read_text())
    gate = json.loads(gate_p.read_text())

    event_ids = [e["id"] for e in config.get("events", [])]
    region_ids = [r["id"] for r in config.get("destination_regions", [])]

    # Open both HDF5 label artifacts
    with h5py.File(baseline_labels_p, "r") as h_base, h5py.File(half_labels_p, "r") as h_half:
        # Check completeness
        if not bool(h_base.attrs.get("complete", False)) or not bool(h_half.attrs.get("complete", False)):
            raise ValueError("Both label artifacts must have complete=True attribute")

        # Identity alignment
        uids_base = h_base["particle_id"][:]
        uids_half = h_half["particle_id"][:]
        zones_base = h_base["particle_zone"][:]
        zones_half = h_half["particle_zone"][:]

        if not np.array_equal(uids_base, uids_half):
            raise ValueError("Particle IDs do not match identically between baseline and half")
        if not np.array_equal(zones_base, zones_half):
            raise ValueError("Particle zones do not match identically between baseline and half")

        # Initial fluid mass
        mass_base = h_base["initial_fluid_mass_kg"][:]
        mass_half = h_half["initial_fluid_mass_kg"][:]
        if not np.allclose(mass_base, mass_half, rtol=1e-12, atol=1e-12):
            raise ValueError("Per-particle initial fluid masses differ between baseline and half")

        # Fluid cohort selection
        fluid_mask_base = mass_base > 0.0
        fluid_mask_half = mass_half > 0.0
        if not np.array_equal(fluid_mask_base, fluid_mask_half):
            raise ValueError("Fluid masks differ between baseline and half")

        fluid_mask = fluid_mask_base
        n_fluid = int(fluid_mask.sum())
        if n_fluid != 34560:
            raise ValueError(f"Fluid count is {n_fluid}, expected exactly 34560")

        fl_uids = uids_base[fluid_mask]
        fl_zones = zones_base[fluid_mask]
        fl_mass = mass_base[fluid_mask].astype(np.float64)
        total_initial_mass_kg = float(np.sum(fl_mass))

        # Check deterministic UID ordering
        sort_order = np.argsort(fl_uids)
        if not np.array_equal(sort_order, np.arange(len(fl_uids))):
            fl_uids = fl_uids[sort_order]
            fl_zones = fl_zones[sort_order]
            fl_mass = fl_mass[sort_order]
            fluid_sort_needed = True
        else:
            fluid_sort_needed = False

        # Source labels (1 = left, 2 = right)
        sources_base = h_base["source_label"][:]
        sources_half = h_half["source_label"][:]
        if not np.array_equal(sources_base, sources_half):
            raise ValueError("Source labels differ between baseline and half")
        fl_sources = sources_base[fluid_mask]
        if fluid_sort_needed:
            fl_sources = fl_sources[sort_order]

        time_base = h_base["time"][:]
        time_half = h_half["time"][:]
        n_frames_base = len(time_base)
        n_frames_half = len(time_half)
        if n_frames_base != 836 or n_frames_half != 836:
            raise ValueError(f"Expected 836 frames, got baseline={n_frames_base}, half={n_frames_half}")

        t_end_base = float(time_base[-1])
        t_end_half = float(time_half[-1])
        common_window_end = min(NOMINAL_WINDOW_END_S, t_end_base, t_end_half)
        common_window_start = 0.0

        # Depth stratification if trajectory is available
        depth_masks: dict[str, np.ndarray] = {}
        depth_counts: dict[str, int] = {}
        depth_stratification_available = False
        if trajectory_path is not None and Path(trajectory_path).is_file():
            with h5py.File(trajectory_path, "r") as h_tr:
                tr_ids = h_tr["particle_id"][:]
                tr_zones = h_tr["particle_zone"][:]
                pos0 = h_tr["position"][0]
                lookup = {(int(z), int(u)): float(pos[2]) for z, u, pos in zip(tr_zones, tr_ids, pos0)}
                z0 = np.array([lookup[(int(z), int(u))] for z, u in zip(fl_zones, fl_uids)], dtype=np.float64)
                depth_masks = {
                    "bottom": z0 < 0.05,
                    "middle": (z0 >= 0.05) & (z0 <= 0.15),
                    "top": z0 > 0.15,
                }
                depth_counts = {k: int(m.sum()) for k, m in depth_masks.items()}
                depth_stratification_available = True

        # Process Events
        events_output: list[dict[str, Any]] = []

        for ei, event_id in enumerate(event_ids):
            censor_b_raw = h_base["first_passage_censor"][:, ei][fluid_mask]
            censor_h_raw = h_half["first_passage_censor"][:, ei][fluid_mask]
            chord_b_raw = h_base["first_passage_chord_time"][:, ei][fluid_mask]
            chord_h_raw = h_half["first_passage_chord_time"][:, ei][fluid_mask]
            int_b_raw = h_base["first_passage_interval"][:, ei, :][fluid_mask]
            int_h_raw = h_half["first_passage_interval"][:, ei, :][fluid_mask]

            if fluid_sort_needed:
                censor_b = censor_b_raw[sort_order]
                censor_h = censor_h_raw[sort_order]
                chord_b = chord_b_raw[sort_order]
                chord_h = chord_h_raw[sort_order]
                int_b = int_b_raw[sort_order]
                int_h = int_h_raw[sort_order]
            else:
                censor_b = censor_b_raw
                censor_h = censor_h_raw
                chord_b = chord_b_raw
                chord_h = chord_h_raw
                int_b = int_b_raw
                int_h = int_h_raw

            # Common window observation
            obs_b = (censor_b == 0) & (chord_b <= common_window_end)
            obs_h = (censor_h == 0) & (chord_h <= common_window_end)

            joint_mask = obs_b & obs_h
            b_only_mask = obs_b & (~obs_h)
            h_only_mask = (~obs_b) & obs_h
            joint_cens_mask = (~obs_b) & (~obs_h)

            joint_count = int(np.sum(joint_mask))
            b_only_count = int(np.sum(b_only_mask))
            h_only_count = int(np.sum(h_only_mask))
            joint_cens_count = int(np.sum(joint_cens_mask))

            joint_mass = float(np.sum(fl_mass[joint_mask]))
            b_only_mass = float(np.sum(fl_mass[b_only_mask]))
            h_only_mass = float(np.sum(fl_mass[h_only_mask]))
            joint_cens_mass = float(np.sum(fl_mass[joint_cens_mask]))

            switching_count = b_only_count + h_only_count
            switching_mass = b_only_mass + h_only_mass
            net_change_count = h_only_count - b_only_count
            net_change_mass = h_only_mass - b_only_mass

            # Paired chord deltas on joint cohort
            if joint_count > 0:
                t_b_joint = chord_b[joint_mask]
                t_h_joint = chord_h[joint_mask]
                w_joint = fl_mass[joint_mask]
                deltas = t_h_joint - t_b_joint
                timing_stats = compute_timing_stats(deltas, w_joint)

                # Paired bracket non-overlap
                iv_b = int_b[joint_mask]
                iv_h = int_h[joint_mask]
                overlap = np.maximum(iv_b[:, 0], iv_h[:, 0]) <= np.minimum(iv_b[:, 1], iv_h[:, 1])
                non_overlap = ~overlap
                non_overlap_count = int(np.sum(non_overlap))
                non_overlap_mass = float(np.sum(w_joint[non_overlap]))
                non_overlap_fraction = float(non_overlap_count / joint_count)
            else:
                timing_stats = compute_timing_stats(np.array([], dtype=np.float64))
                non_overlap_count = 0
                non_overlap_mass = 0.0
                non_overlap_fraction = None

            # Macro passage mean calculation
            m_base_tot = float(np.sum(fl_mass[obs_b]))
            m_half_tot = float(np.sum(fl_mass[obs_h]))
            macro_mean_b = float(np.sum(chord_b[obs_b] * fl_mass[obs_b]) / m_base_tot) if m_base_tot > 0 else None
            macro_mean_h = float(np.sum(chord_h[obs_h] * fl_mass[obs_h]) / m_half_tot) if m_half_tot > 0 else None
            macro_delta = (macro_mean_h - macro_mean_b) if (macro_mean_b is not None and macro_mean_h is not None) else None

            # Exact empirical CDF supremum and L1 integrated deviation
            cdf_eval = compute_exact_cdf_supremum_and_l1(
                chord_b[obs_b], fl_mass[obs_b],
                chord_h[obs_h], fl_mass[obs_h],
                total_initial_mass_kg, total_initial_mass_kg,
                common_window_start, common_window_end,
            )

            # Temporal subwindows progression
            subwindows: list[dict[str, Any]] = []
            for t_cut in [1.5, 2.5, 5.0, common_window_end]:
                sub_obs_b = obs_b & (chord_b <= t_cut)
                sub_obs_h = obs_h & (chord_h <= t_cut)
                sub_joint = sub_obs_b & sub_obs_h
                sub_joint_count = int(np.sum(sub_joint))
                sub_b_only = int(np.sum(sub_obs_b & ~sub_obs_h))
                sub_h_only = int(np.sum(~sub_obs_b & sub_obs_h))
                sub_switch = sub_b_only + sub_h_only

                if sub_joint_count > 0:
                    sub_deltas = chord_h[sub_joint] - chord_b[sub_joint]
                    sub_timing = compute_timing_stats(sub_deltas, fl_mass[sub_joint])
                else:
                    sub_timing = compute_timing_stats(np.array([], dtype=np.float64))

                subwindows.append({
                    "cutoff_s": float(t_cut),
                    "baseline_observed_count": int(np.sum(sub_obs_b)),
                    "half_observed_count": int(np.sum(sub_obs_h)),
                    "joint_observed_count": sub_joint_count,
                    "switching_identities_count": sub_switch,
                    "baseline_only_count": sub_b_only,
                    "half_only_count": sub_h_only,
                    "switching_fraction_joint": float(sub_switch / sub_joint_count) if sub_joint_count > 0 else None,
                    "timing_statistics_joint": sub_timing,
                })

            # Depth stratification if available
            depth_output: dict[str, Any] = {}
            if depth_stratification_available:
                for layer_name, layer_m in depth_masks.items():
                    layer_joint = joint_mask & layer_m
                    layer_joint_cnt = int(np.sum(layer_joint))
                    layer_b_obs = int(np.sum(obs_b & layer_m))
                    layer_h_obs = int(np.sum(obs_h & layer_m))
                    layer_switch = int(np.sum((b_only_mask | h_only_mask) & layer_m))

                    if layer_joint_cnt > 0:
                        l_iv_b = int_b[layer_joint]
                        l_iv_h = int_h[layer_joint]
                        l_overlap = np.maximum(l_iv_b[:, 0], l_iv_h[:, 0]) <= np.minimum(l_iv_b[:, 1], l_iv_h[:, 1])
                        l_nonoverlap = int(np.sum(~l_overlap))
                        l_frac_nonoverlap = float(l_nonoverlap / layer_joint_cnt)
                        l_deltas = chord_h[layer_joint] - chord_b[layer_joint]
                        l_stats = compute_timing_stats(l_deltas, fl_mass[layer_joint])
                    else:
                        l_nonoverlap = 0
                        l_frac_nonoverlap = None
                        l_stats = compute_timing_stats(np.array([], dtype=np.float64))

                    depth_output[layer_name] = {
                        "total_particles": int(np.sum(layer_m)),
                        "baseline_observed_count": layer_b_obs,
                        "half_observed_count": layer_h_obs,
                        "joint_observed_count": layer_joint_cnt,
                        "switching_identities_count": layer_switch,
                        "non_overlapping_brackets_count": l_nonoverlap,
                        "fraction_non_overlapping": l_frac_nonoverlap,
                        "timing_statistics_joint": l_stats,
                    }

            events_output.append({
                "event_id": event_id,
                "cohort_breakdown": {
                    "joint_observed": {"count": joint_count, "mass_kg": joint_mass},
                    "baseline_only": {"count": b_only_count, "mass_kg": b_only_mass},
                    "half_only": {"count": h_only_count, "mass_kg": h_only_mass},
                    "joint_censored": {"count": joint_cens_count, "mass_kg": joint_cens_mass},
                    "switching_identities": {"count": switching_count, "mass_kg": switching_mass},
                    "net_change_observed": {"count": net_change_count, "mass_kg": net_change_mass},
                },
                "per_identity_chord_deltas_joint": timing_stats,
                "bracket_non_overlap": {
                    "non_overlapping_brackets_count": non_overlap_count,
                    "non_overlapping_brackets_mass_kg": non_overlap_mass,
                    "fraction_non_overlapping": non_overlap_fraction,
                },
                "macro_passage": {
                    "baseline_observed_count": int(np.sum(obs_b)),
                    "baseline_observed_mass_kg": m_base_tot,
                    "baseline_mass_weighted_chord_s": macro_mean_b,
                    "half_observed_count": int(np.sum(obs_h)),
                    "half_observed_mass_kg": m_half_tot,
                    "half_mass_weighted_chord_s": macro_mean_h,
                    "macro_weighted_chord_delta_s": macro_delta,
                },
                "exact_unconditional_initial_mass_cdf": cdf_eval,
                "temporal_subwindows": subwindows,
                "depth_stratification": depth_output if depth_stratification_available else "omitted_trajectory_unbound",
            })

        # Residence Time Comparison
        res_b = h_base["residence_time_s"][:][fluid_mask]
        res_h = h_half["residence_time_s"][:][fluid_mask]
        unres_b = h_base["unresolved_interval_time_s"][:][fluid_mask]
        unres_h = h_half["unresolved_interval_time_s"][:][fluid_mask]
        if fluid_sort_needed:
            res_b = res_b[sort_order]
            res_h = res_h[sort_order]
            unres_b = unres_b[sort_order]
            unres_h = unres_h[sort_order]

        residence_comparison: dict[str, Any] = {}
        for ri, region_id in enumerate(region_ids):
            rb = res_b[:, ri]
            rh = res_h[:, ri]
            r_delta = rh - rb
            tot_b_mass_s = float(np.sum(rb * fl_mass))
            tot_h_mass_s = float(np.sum(rh * fl_mass))
            res_stats = compute_timing_stats(r_delta, fl_mass)
            residence_comparison[region_id] = {
                "baseline_total_mass_seconds": tot_b_mass_s,
                "half_total_mass_seconds": tot_h_mass_s,
                "delta_total_mass_seconds": tot_h_mass_s - tot_b_mass_s,
                "per_particle_delta_statistics": res_stats,
            }

        unres_delta = unres_h - unres_b
        residence_comparison["unresolved_interval_time"] = {
            "baseline_total_mass_seconds": float(np.sum(unres_b * fl_mass)),
            "half_total_mass_seconds": float(np.sum(unres_h * fl_mass)),
            "per_particle_delta_statistics": compute_timing_stats(unres_delta, fl_mass),
        }

        # Cumulative Net Flux Comparison
        flux_b = h_base["cumulative_net_flux_kg"][:]  # (nt, ne)
        flux_h = h_half["cumulative_net_flux_kg"][:]
        fwd_bwd_b = h_base["forward_backward_mass_kg"][:]  # (nt, ne, 2)
        fwd_bwd_h = h_half["forward_backward_mass_kg"][:]

        flux_comparison: dict[str, Any] = {}
        for ei, event_id in enumerate(event_ids):
            fb = flux_b[:, ei]
            fh = flux_h[:, ei]
            f_diff = np.abs(fh - fb)
            trapz_fn = getattr(np, "trapezoid", getattr(np, "trapz", None))
            l1_flux_diff = float(trapz_fn(f_diff, time_base))

            flux_comparison[event_id] = {
                "baseline_terminal_net_flux_kg": float(fb[-1]),
                "half_terminal_net_flux_kg": float(fh[-1]),
                "delta_terminal_net_flux_kg": float(fh[-1] - fb[-1]),
                "max_absolute_trajectory_flux_discrepancy_kg": float(np.max(f_diff)),
                "time_at_max_flux_discrepancy_s": float(time_base[int(np.argmax(f_diff))]),
                "l1_integrated_flux_deviation_kg_s": l1_flux_diff,
                "baseline_terminal_forward_mass_kg": float(fwd_bwd_b[-1, ei, 0]),
                "baseline_terminal_backward_mass_kg": float(fwd_bwd_b[-1, ei, 1]),
                "half_terminal_forward_mass_kg": float(fwd_bwd_h[-1, ei, 0]),
                "half_terminal_backward_mass_kg": float(fwd_bwd_h[-1, ei, 1]),
            }

        # Reentry Analysis from destination time series
        dest_b = h_base["destination_time_series"][:]
        dest_h = h_half["destination_time_series"][:]

        reentry_b = analyze_reentry(dest_b, sources_base, fluid_mask)
        reentry_h = analyze_reentry(dest_h, sources_half, fluid_mask)

        reentry_mask_b = reentry_b["reentered_mask"]
        reentry_mask_h = reentry_h["reentered_mask"]

        reentry_comparison = {
            "baseline_reentered_particles_count": reentry_b["reentered_particles_count"],
            "baseline_reentered_mass_kg": float(np.sum(fl_mass[reentry_mask_b])),
            "baseline_total_transition_events": reentry_b["total_transition_events_count"],
            "half_reentered_particles_count": reentry_h["reentered_particles_count"],
            "half_reentered_mass_kg": float(np.sum(fl_mass[reentry_mask_h])),
            "half_total_transition_events": reentry_h["total_transition_events_count"],
            "delta_reentered_particles_count": reentry_h["reentered_particles_count"] - reentry_b["reentered_particles_count"],
            "delta_reentered_mass_kg": float(np.sum(fl_mass[reentry_mask_h])) - float(np.sum(fl_mass[reentry_mask_b])),
            "joint_reentered_particles_count": int(np.sum(reentry_mask_b & reentry_mask_h)),
            "switching_reentered_particles_count": int(np.sum(reentry_mask_b ^ reentry_mask_h)),
        }

        # Unknown Loss & Boundary Audit
        unknown_loss_audit = {
            "baseline": {
                "final_numerical_loss_mass_kg": float(h_base["numerical_loss_mass_kg"][-1]) if "numerical_loss_mass_kg" in h_base else 0.0,
                "final_unknown_mass_kg": float(h_base["unknown_mass_kg"][-1]) if "unknown_mass_kg" in h_base else 0.0,
                "final_invalid_state_mass_kg": float(h_base["invalid_state_mass_kg"][-1]) if "invalid_state_mass_kg" in h_base else 0.0,
            },
            "half": {
                "final_numerical_loss_mass_kg": float(h_half["numerical_loss_mass_kg"][-1]) if "numerical_loss_mass_kg" in h_half else 0.0,
                "final_unknown_mass_kg": float(h_half["unknown_mass_kg"][-1]) if "unknown_mass_kg" in h_half else 0.0,
                "final_invalid_state_mass_kg": float(h_half["invalid_state_mass_kg"][-1]) if "invalid_state_mass_kg" in h_half else 0.0,
            },
        }

    # Solver timestepping & CFL verification
    timestepping_provenance = {
        "baseline": {
            "case_id": "F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005",
            "attempt_id": "root-cell3-adaptive-baseline-native-transport-labels-012",
            "cfl": 0.05,
            "coef_dt_min": 0.005,
            "steps": 383189,
            "all_native_steps": 383190,
            "dt_min_clamps": 0,
            "frames": 836,
            "end_time_s": t_end_base,
        },
        "half": {
            "case_id": "F3_CELL3_LONG_DP0075_REPAIR2_ADAPTIVE_CFL025_COEF0025",
            "attempt_id": "root-cell3-adaptive-half-native-transport-labels-014",
            "cfl": 0.025,
            "coef_dt_min": 0.0025,
            "steps": 766348,
            "all_native_steps": 766349,
            "dt_min_clamps": 0,
            "frames": 836,
            "end_time_s": t_end_half,
        },
        "step_ratio": 766348 / 383189,
        "step_ratio_target": 2.0,
        "timestepping_classification": "genuine_adaptive_cfl_halving_zero_clamps",
        "quarter_status": "quarter_cfl_dtmin_clamped_retained_as_secondary_historical_evidence_not_substituted",
    }

    # Historical Anchors
    historical_anchors = {
        "preregistration": {
            "path": str(prereg_p.resolve()),
            "sha256": digests[str(prereg_p.resolve())],
            "schema": prereg.get("schema"),
            "status": prereg.get("status"),
        },
        "historical_protocol": {
            "path": str(protocol_p.resolve()),
            "sha256": digests[str(protocol_p.resolve())],
            "schema": protocol.get("protocol_schema"),
            "cfl": protocol.get("cfl"),
            "note": "Original CELL3 protocol defines macro relative budgets (0.01 time/output, 0.05 reference); event share cap not part of protocol.",
        },
        "historical_gate": {
            "path": str(gate_p.resolve()),
            "sha256": digests[str(gate_p.resolve())],
            "status": gate.get("status"),
            "panels_passed_count": gate.get("panels_passed_count"),
            "separation_note": "T1 macro gate passed 13/13 panels across fixed-tank sloshing. New transport T2 is a separate scientific layer and is not yet qualified.",
        },
    }

    # Construct final report
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "comparison_title": "F3 CELL3 Genuine Adaptive CFL Halving Paired Transport Comparison",
        "common_window_s": [common_window_start, common_window_end],
        "fluid_cohort": {
            "count": n_fluid,
            "total_initial_mass_kg": total_initial_mass_kg,
            "identities_verified_identical": True,
            "zones_verified_identical": True,
            "masses_verified_identical": True,
        },
        "timestepping_provenance": timestepping_provenance,
        "events": events_output,
        "residence_time_comparison": residence_comparison,
        "cumulative_net_flux_comparison": flux_comparison,
        "reentry_comparison": reentry_comparison,
        "unknown_loss_audit": unknown_loss_audit,
        "historical_anchors": historical_anchors,
        "input_sha256": digests,
        "claim_boundary": {
            "model_invoked": False,
            "production": "not_evaluated",
            "production_granted": False,
            "q_i": "transport_comparison_measurement_only",
            "q_n": "not_assessed",
            "q_n_granted": False,
            "training": "not_authorized",
            "governance_note": (
                "Purely descriptive transport comparison between genuine adaptive Repair 1 (CFL=0.05) and "
                "Repair 2 (CFL=0.025); step ratio 1.99992x; zero clamps. No retrospective gate invented, "
                "no 5% autogate claim, preserves baseline and historical negative evidence."
            ),
        },
        "resource_usage": usage_stats(),
    }

    output_p.parent.mkdir(parents=True, exist_ok=True)
    output_p.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-labels", type=Path, required=True, help="Baseline native-labels.h5")
    parser.add_argument("--baseline-report", type=Path, required=True, help="Baseline labels-report.json")
    parser.add_argument("--baseline-receipt", type=Path, required=True, help="Baseline execution-receipt.json")
    parser.add_argument("--half-labels", type=Path, required=True, help="Half native-labels.h5")
    parser.add_argument("--half-report", type=Path, required=True, help="Half labels-report.json")
    parser.add_argument("--half-receipt", type=Path, required=True, help="Half execution-receipt.json")
    parser.add_argument("--config", type=Path, required=True, help="Operator config JSON")
    parser.add_argument("--preregistration", type=Path, required=True, help="Preregistration JSON")
    parser.add_argument("--protocol", type=Path, required=True, help="Historical protocol JSON")
    parser.add_argument("--gate", type=Path, required=True, help="Historical gate JSON")
    parser.add_argument("--trajectory", type=Path, default=None, help="Optional nominal trajectory H5 for depth stratification")
    parser.add_argument("--output", type=Path, required=True, help="Output comparison JSON report")

    args = parser.parse_args()
    report = compare_f3_genuine_adaptive_transport(
        args.baseline_labels,
        args.baseline_report,
        args.baseline_receipt,
        args.half_labels,
        args.half_report,
        args.half_receipt,
        args.config,
        args.preregistration,
        args.protocol,
        args.gate,
        args.output,
        trajectory_path=args.trajectory,
    )
    print(json.dumps({
        "schema": report["schema"],
        "common_window_s": report["common_window_s"],
        "fluid_cohort_count": report["fluid_cohort"]["count"],
        "step_ratio": report["timestepping_provenance"]["step_ratio"],
        "claim_boundary": report["claim_boundary"],
    }, indent=2))


if __name__ == "__main__":
    main()
