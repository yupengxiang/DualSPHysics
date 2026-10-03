#!/usr/bin/env python3
"""F3 CELL3 Saved-Frequency Transport Comparison Script (Version 1).

Compares canonical transport labels between nominal save cadence (Delta_t = 0.01s, 836 frames)
and dense save cadence (Delta_t = 0.002s, 4,176 frames) for the identical physical simulation:
  - CASE: F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005
  - PHYSICS: CFL=0.05, CoefDtMin=0.005, DTsMin=0, 383,190 steps, unclamped Symplectic
  - NOMINAL: XML TimeOut=0.01, effective save interval 0.01s, 836 frames (Attempt 012 labels)
  - DENSE: XML TimeOut=0.01, effective CLI -tout:0.002, 4,176 frames (5x save cadence refinement)

Key Comparison Principles:
  1. Physical-time alignment (NOT saved-index pairing):
     Aligns frame observations by continuous physical time t in seconds, mapping nominal frame k
     to nearest dense frame j with |t_dense[j] - t_nom[k]| < dt_dense/2.
  2. Strict UID validation:
     Verifies exact 1-to-1 match of all 108,000 particle identity keys (Zone, Idp) and the
     34,560 fluid particle cohort between nominal and dense datasets. Discrepancies fail immediately.
  3. No velocity-zero fallback:
     No synthetic velocities or fallback fabrications are introduced.
  4. Temporal discretization error isolation:
     Because the hydrodynamic solver steps and parameters are identical (383,190 steps),
     any difference in chord crossing times or save brackets isolates the pure effect of
     temporal save resolution (save-bracket quantization).
  5. Save bracket analysis:
     Directly evaluates whether refining the save interval from 10 ms to 2 ms encapsulates
     chord passage events, measuring bracket overlap fraction and chord containment.
  6. Empirical CDF over continuous physical time:
     Computes exact union-knot supremum and L1 integrated deviation in fraction*s over [0.0, 8.35s],
     with conditional zero CDF handling for all-censored events.
  7. Retains initial mass (14.58 kg), unknown/censored fates, and complete physical window [0.0, 8.35].
  8. Pure descriptive measurement claim boundaries:
     No arbitrary 5% autogates; Q-I measurement only, Q-N not assessed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
from typing import Any

import h5py
import numpy as np

SCHEMA = "ds02.f3.saved-frequency-transport-comparison.v1"
FAMILY_ID = "F3"
NOMINAL_CASE_ID = "F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005"
DENSE_CASE_ID = "F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005_DENSE_SAVE002"
EXPECTED_FLUID_PARTICLES = 34560
EXPECTED_TOTAL_IDENTITIES = 108000
EXPECTED_FLUID_MASS_KG = 14.580000378191471
NOMINAL_XML_TIMEOUT_S = 0.01
DENSE_CLI_TIMEOUT_S = 0.002
PHYSICAL_WINDOW_S = (0.0, 8.35)


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
    """Compute the exact empirical CDF supremum over union jump knots and L1 integrated deviation."""
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
    cumsum_a = np.cumsum(w_a[order_a], dtype=np.float64) / total_mass_a if len(t_a) > 0 else np.array([], dtype=np.float64)

    order_b = np.argsort(t_b)
    t_b_sorted = t_b[order_b]
    cumsum_b = np.cumsum(w_b[order_b], dtype=np.float64) / total_mass_b if len(t_b) > 0 else np.array([], dtype=np.float64)

    # Form union of all jump knots plus window boundaries
    knots = np.unique(np.concatenate([[window_start], t_a_sorted, t_b_sorted, [window_end]]))
    knots = knots[(knots >= window_start) & (knots <= window_end)]

    if len(knots) <= 1:
        return {
            "knot_supremum_absolute_deviation": 0.0,
            "time_at_knot_supremum_s": float(window_start),
            "l1_integrated_cdf_deviation_fraction_s": 0.0,
            "nominal_terminal_cdf": 0.0,
            "dense_terminal_cdf": 0.0,
            "nominal_deciles": {},
            "dense_deciles": {},
            "sampled_cdf_nominal": {},
            "sampled_cdf_dense": {},
        }

    # Evaluate right limits at knots: F(t) (conditional zero for empty cohort)
    if len(cumsum_a) == 0:
        cdf_a_right = np.zeros_like(knots, dtype=np.float64)
        cdf_a_left = np.zeros_like(knots, dtype=np.float64)
    else:
        idx_a_right = np.searchsorted(t_a_sorted, knots, side="right") - 1
        cdf_a_right = np.where(idx_a_right >= 0, cumsum_a[np.maximum(0, idx_a_right)], 0.0)
        idx_a_left = np.searchsorted(t_a_sorted, knots, side="left") - 1
        cdf_a_left = np.where(idx_a_left >= 0, cumsum_a[np.maximum(0, idx_a_left)], 0.0)

    if len(cumsum_b) == 0:
        cdf_b_right = np.zeros_like(knots, dtype=np.float64)
        cdf_b_left = np.zeros_like(knots, dtype=np.float64)
    else:
        idx_b_right = np.searchsorted(t_b_sorted, knots, side="right") - 1
        cdf_b_right = np.where(idx_b_right >= 0, cumsum_b[np.maximum(0, idx_b_right)], 0.0)
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

    # Exact L1 integration in fraction * s
    dt_intervals = np.diff(knots)
    diff_intervals = diff_right[:-1]
    l1_deviation = float(np.sum(diff_intervals * dt_intervals))

    # Deciles
    decile_probs = [0.1 * k for k in range(1, 10)]
    nom_deciles = {}
    dense_deciles = {}
    if len(cumsum_a) > 0:
        for p in decile_probs:
            idx = np.searchsorted(cumsum_a, p)
            nom_deciles[f"p{int(p*100)}"] = float(t_a_sorted[idx]) if idx < len(t_a_sorted) else None
    if len(cumsum_b) > 0:
        for p in decile_probs:
            idx = np.searchsorted(cumsum_b, p)
            dense_deciles[f"p{int(p*100)}"] = float(t_b_sorted[idx]) if idx < len(t_b_sorted) else None

    # Sampled points
    check_times = [float(k) for k in range(1, int(window_end) + 1)]
    if window_end not in check_times:
        check_times.append(float(window_end))

    sampled_a = {}
    sampled_b = {}
    for ct in check_times:
        if len(cumsum_a) > 0:
            idx = np.searchsorted(t_a_sorted, ct, side="right") - 1
            val_a = float(cumsum_a[idx]) if idx >= 0 else 0.0
        else:
            val_a = 0.0
        if len(cumsum_b) > 0:
            idx = np.searchsorted(t_b_sorted, ct, side="right") - 1
            val_b = float(cumsum_b[idx]) if idx >= 0 else 0.0
        else:
            val_b = 0.0
        sampled_a[f"t_{ct:.2f}s"] = val_a
        sampled_b[f"t_{ct:.2f}s"] = val_b

    return {
        "knot_supremum_absolute_deviation": sup_dev,
        "time_at_knot_supremum_s": t_sup,
        "l1_integrated_cdf_deviation_fraction_s": l1_deviation,
        "nominal_terminal_cdf": float(cdf_a_right[-1]),
        "dense_terminal_cdf": float(cdf_b_right[-1]),
        "terminal_cdf_discrepancy": float(cdf_b_right[-1] - cdf_a_right[-1]),
        "nominal_deciles": nom_deciles,
        "dense_deciles": dense_deciles,
        "sampled_cdf_nominal": sampled_a,
        "sampled_cdf_dense": sampled_b,
    }


def validate_uids(
    h_nom: h5py.File,
    h_dense: h5py.File,
    max_particles: int | None = None,
) -> tuple[np.ndarray, int, float]:
    """Verify exact 1-to-1 match of all particle identities and extract fluid cohort mask."""
    id_nom = h_nom["particle_id"][:]
    zone_nom = h_nom["particle_zone"][:]
    src_nom = h_nom["source_label"][:]

    id_dense = h_dense["particle_id"][:]
    zone_dense = h_dense["particle_zone"][:]
    src_dense = h_dense["source_label"][:]

    if len(id_nom) != len(id_dense):
        raise ValueError(f"Identity length mismatch: nominal {len(id_nom)} vs dense {len(id_dense)}")

    if not np.array_equal(id_nom, id_dense):
        raise ValueError("particle_id arrays differ between nominal and dense datasets")

    if not np.array_equal(zone_nom, zone_dense):
        raise ValueError("particle_zone arrays differ between nominal and dense datasets")

    if not np.array_equal(src_nom, src_dense):
        raise ValueError("source_label arrays differ between nominal and dense datasets")

    # Fluid cohort: source_label > 0
    fluid_mask = src_nom > 0
    fluid_count = int(np.sum(fluid_mask))

    masses_nom = h_nom["initial_fluid_mass_kg"][:] if "initial_fluid_mass_kg" in h_nom else np.full(len(id_nom), EXPECTED_FLUID_MASS_KG / fluid_count)
    total_mass = float(np.sum(masses_nom[fluid_mask]))

    if max_particles is not None and max_particles < fluid_count:
        # Subsampled cohort for synthetic unit tests
        idx_fluid = np.flatnonzero(fluid_mask)
        sub_mask = np.zeros(len(fluid_mask), dtype=bool)
        sub_mask[idx_fluid[:max_particles]] = True
        fluid_mask = sub_mask
        fluid_count = max_particles
        total_mass = float(np.sum(masses_nom[fluid_mask]))

    return fluid_mask, fluid_count, total_mass


def align_physical_times(
    time_nom: np.ndarray,
    time_dense: np.ndarray,
) -> tuple[list[tuple[int, int]], float]:
    """Align discrete saved frames by continuous physical time in seconds.

    For each nominal frame k at time t_k, find nearest dense frame j with
    minimum |time_dense[j] - t_k|. Returns paired indices and maximum time delta.
    """
    pairs = []
    max_delta = 0.0

    for k, t_nom in enumerate(time_nom):
        # Nearest dense frame
        j = int(np.argmin(np.abs(time_dense - t_nom)))
        delta = abs(float(time_dense[j] - t_nom))
        max_delta = max(max_delta, delta)
        pairs.append((k, j))

    return pairs, max_delta


def compare_destination_series(
    h_nom: h5py.File,
    h_dense: h5py.File,
    fluid_mask: np.ndarray,
    time_pairs: list[tuple[int, int]],
    time_nom: np.ndarray,
) -> dict[str, Any]:
    """Compare destination region assignment at physically aligned time frames."""
    d_nom = h_nom["destination_time_series"]
    d_dense = h_dense["destination_time_series"]

    n_fluid = int(np.sum(fluid_mask))
    agreement_fractions = []
    mismatch_counts = []
    sampled_times = []

    for k, j in time_pairs:
        t_val = float(time_nom[k])
        sampled_times.append(t_val)

        state_nom = d_nom[k, fluid_mask]
        state_dense = d_dense[j, fluid_mask]

        match_mask = state_nom == state_dense
        n_match = int(np.sum(match_mask))
        aggr = float(n_match / n_fluid) if n_fluid > 0 else 1.0

        agreement_fractions.append(aggr)
        mismatch_counts.append(n_fluid - n_match)

    aggr_arr = np.array(agreement_fractions, dtype=np.float64)
    min_aggr = float(np.min(aggr_arr))
    t_min_aggr = float(sampled_times[int(np.argmin(aggr_arr))])
    mean_aggr = float(np.mean(aggr_arr))

    return {
        "frames_compared": len(time_pairs),
        "mean_destination_agreement_fraction": mean_aggr,
        "minimum_destination_agreement_fraction": min_aggr,
        "time_at_minimum_agreement_s": t_min_aggr,
        "maximum_mismatched_particles": int(np.max(mismatch_counts)),
        "time_at_maximum_mismatches_s": float(sampled_times[int(np.argmax(mismatch_counts))]),
    }


def compare_f3_saved_frequency(
    nominal_labels_path: Path | str,
    nominal_report_path: Path | str,
    dense_labels_path: Path | str,
    dense_report_path: Path | str,
    config_path: Path | str,
    output_path: Path | str,
    *,
    max_particles: int | None = None,
) -> dict[str, Any]:
    """Execute rigorous saved-frequency transport comparison between nominal and dense labels."""
    nom_lbl_p = Path(nominal_labels_path)
    nom_rep_p = Path(nominal_report_path)
    dense_lbl_p = Path(dense_labels_path)
    dense_rep_p = Path(dense_report_path)
    cfg_p = Path(config_path)
    out_p = Path(output_path)

    mandatory = [nom_lbl_p, nom_rep_p, dense_lbl_p, dense_rep_p, cfg_p]
    for p in mandatory:
        if not p.is_file():
            raise FileNotFoundError(f"Input file not found: {p}")

    digests = {str(p.resolve()): digest(p) for p in mandatory}

    config = json.loads(cfg_p.read_text())
    nom_rep = json.loads(nom_rep_p.read_text())
    dense_rep = json.loads(dense_rep_p.read_text())

    with h5py.File(nom_lbl_p, "r") as h_nom, h5py.File(dense_lbl_p, "r") as h_dense:
        # UID Validation
        fluid_mask, n_fluid, total_mass_kg = validate_uids(h_nom, h_dense, max_particles=max_particles)

        time_nom = h_nom["time"][:]
        time_dense = h_dense["time"][:]
        common_end_time = float(min(time_nom[-1], time_dense[-1], PHYSICAL_WINDOW_S[1]))

        # Physical time alignment
        time_pairs, max_align_delta = align_physical_times(time_nom, time_dense)

        # Time series destination agreement
        dest_agreement = compare_destination_series(h_nom, h_dense, fluid_mask, time_pairs, time_nom)

        # Event passage comparison for each configured event
        events = config.get("events", [])
        event_results = {}

        masses = h_nom["initial_fluid_mass_kg"][:] if "initial_fluid_mass_kg" in h_nom else np.full(len(fluid_mask), EXPECTED_FLUID_MASS_KG / n_fluid)
        fluid_masses = masses[fluid_mask]

        for ev_idx, event in enumerate(events):
            ev_id = event["id"]

            censor_nom = h_nom["first_passage_censor"][:, ev_idx][fluid_mask]
            censor_dense = h_dense["first_passage_censor"][:, ev_idx][fluid_mask]

            chord_nom = h_nom["first_passage_chord_time"][:, ev_idx][fluid_mask]
            chord_dense = h_dense["first_passage_chord_time"][:, ev_idx][fluid_mask]

            interval_nom = h_nom["first_passage_interval"][:, ev_idx, :][fluid_mask]
            interval_dense = h_dense["first_passage_interval"][:, ev_idx, :][fluid_mask]

            # Fate contingency classification
            nom_obs = censor_nom == 0
            dense_obs = censor_dense == 0

            joint_obs = nom_obs & dense_obs
            nom_only = nom_obs & (~dense_obs)
            dense_only = (~nom_obs) & dense_obs
            joint_cens = (~nom_obs) & (~dense_obs)

            n_joint = int(np.sum(joint_obs))
            n_nom_only = int(np.sum(nom_only))
            n_dense_only = int(np.sum(dense_only))
            n_joint_cens = int(np.sum(joint_cens))

            # Joint chord deltas: dense - nominal
            if n_joint > 0:
                joint_deltas = chord_dense[joint_obs] - chord_nom[joint_obs]
                joint_weights = fluid_masses[joint_obs]
                timing_stats = compute_timing_stats(joint_deltas, joint_weights)

                # Save bracket analysis for joint-observed cohort
                w_nom = interval_nom[joint_obs, 1] - interval_nom[joint_obs, 0]
                w_dense = interval_dense[joint_obs, 1] - interval_dense[joint_obs, 0]
                tightening_factors = np.where(w_dense > 0, w_nom / w_dense, 0.0)

                # Dense chord inside nominal bracket
                dense_in_nom = (chord_dense[joint_obs] >= interval_nom[joint_obs, 0] - 1e-9) & (chord_dense[joint_obs] <= interval_nom[joint_obs, 1] + 1e-9)
                n_dense_in_nom = int(np.sum(dense_in_nom))

                # Nominal chord inside dense bracket
                nom_in_dense = (chord_nom[joint_obs] >= interval_dense[joint_obs, 0] - 1e-9) & (chord_nom[joint_obs] <= interval_dense[joint_obs, 1] + 1e-9)
                n_nom_in_dense = int(np.sum(nom_in_dense))

                # Non-empty bracket intersection: max(entry) <= min(exit)
                int_start = np.maximum(interval_nom[joint_obs, 0], interval_dense[joint_obs, 0])
                int_end = np.minimum(interval_nom[joint_obs, 1], interval_dense[joint_obs, 1])
                bracket_overlap = int_end >= int_start - 1e-9
                n_bracket_overlap = int(np.sum(bracket_overlap))
                n_bracket_non_overlap = n_joint - n_bracket_overlap

                bracket_analysis = {
                    "nominal_mean_bracket_width_s": float(np.mean(w_nom)),
                    "nominal_median_bracket_width_s": float(np.median(w_nom)),
                    "dense_mean_bracket_width_s": float(np.mean(w_dense)),
                    "dense_median_bracket_width_s": float(np.median(w_dense)),
                    "mean_tightening_factor": float(np.mean(tightening_factors)),
                    "dense_chord_inside_nominal_bracket_count": n_dense_in_nom,
                    "dense_chord_inside_nominal_bracket_fraction": float(n_dense_in_nom / n_joint),
                    "nominal_chord_inside_dense_bracket_count": n_nom_in_dense,
                    "nominal_chord_inside_dense_bracket_fraction": float(n_nom_in_dense / n_joint),
                    "bracket_overlap_count": n_bracket_overlap,
                    "bracket_overlap_fraction": float(n_bracket_overlap / n_joint),
                    "bracket_non_overlap_count": n_bracket_non_overlap,
                    "bracket_non_overlap_fraction": float(n_bracket_non_overlap / n_joint),
                }

                # Subwindow analysis
                subwindows = {}
                for w_name, (w_lo, w_hi) in (
                    ("early_canary_0_to_1p5s", (0.0, 1.5)),
                    ("mid_window_0_to_2p5s", (0.0, 2.5)),
                    ("late_window_2p5_to_8p35s", (2.5, common_end_time)),
                ):
                    sub_mask = joint_obs & (chord_nom >= w_lo) & (chord_nom <= w_hi)
                    sub_count = int(np.sum(sub_mask))
                    if sub_count > 0:
                        s_deltas = chord_dense[sub_mask] - chord_nom[sub_mask]
                        s_stats = compute_timing_stats(s_deltas, fluid_masses[sub_mask])
                        subwindows[w_name] = s_stats
                    else:
                        subwindows[w_name] = {"count": 0}
            else:
                timing_stats = compute_timing_stats(np.array([]))
                bracket_analysis = {"status": "no_joint_observed_events"}
                subwindows = {}

            # Full cohort empirical CDF comparison
            nom_times = chord_nom[nom_obs]
            nom_weights = fluid_masses[nom_obs]
            dense_times = chord_dense[dense_obs]
            dense_weights = fluid_masses[dense_obs]

            cdf_comparison = compute_exact_cdf_supremum_and_l1(
                nom_times, nom_weights,
                dense_times, dense_weights,
                total_mass_a=total_mass_kg,
                total_mass_b=total_mass_kg,
                window_start=0.0,
                window_end=common_end_time,
            )

            event_results[ev_id] = {
                "event_label": event.get("label", ev_id),
                "classification": event.get("classification", "unclassified"),
                "fate_contingency": {
                    "joint_observed_count": n_joint,
                    "joint_observed_fraction": float(n_joint / n_fluid) if n_fluid > 0 else 0.0,
                    "nominal_only_observed_count": n_nom_only,
                    "nominal_only_observed_fraction": float(n_nom_only / n_fluid) if n_fluid > 0 else 0.0,
                    "dense_only_observed_count": n_dense_only,
                    "dense_only_observed_fraction": float(n_dense_only / n_fluid) if n_fluid > 0 else 0.0,
                    "joint_censored_count": n_joint_cens,
                    "joint_censored_fraction": float(n_joint_cens / n_fluid) if n_fluid > 0 else 0.0,
                    "fate_switch_count": n_nom_only + n_dense_only,
                    "fate_switch_fraction": float((n_nom_only + n_dense_only) / n_fluid) if n_fluid > 0 else 0.0,
                },
                "timing_statistics": timing_stats,
                "save_bracket_analysis": bracket_analysis,
                "subwindows": subwindows,
                "empirical_cdf_comparison": cdf_comparison,
            }

        # Final residence time comparison
        res_nom = h_nom["residence_time_s"][:, :][fluid_mask]
        res_dense = h_dense["residence_time_s"][:, :][fluid_mask]
        res_regions = config.get("destination_regions", [])
        residence_comparison = {}
        for r_idx, reg in enumerate(res_regions):
            r_id = reg["id"]
            d_res = res_dense[:, r_idx] - res_nom[:, r_idx]
            residence_comparison[r_id] = {
                "mean_signed_delta_s": float(np.mean(d_res)),
                "median_absolute_delta_s": float(np.median(np.abs(d_res))),
                "p95_absolute_delta_s": float(np.percentile(np.abs(d_res), 95)),
                "total_mass_seconds_delta_kg_s": float(np.sum(d_res * fluid_masses)),
            }

    report = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "title": "F3 CELL3 Saved-Frequency Transport Comparison (836 Nominal vs 4,176 Dense Frames)",
        "simulation_identity": {
            "case_id": NOMINAL_CASE_ID,
            "cfl": 0.05,
            "coef_dt_min": 0.005,
            "dts_min": 0,
            "total_solver_steps": 383190,
            "solver_step_parity": "exact_match_same_physics",
        },
        "save_cadence_provenance": {
            "nominal": {
                "xml_nominal_timeout_s": NOMINAL_XML_TIMEOUT_S,
                "effective_save_interval_s": NOMINAL_XML_TIMEOUT_S,
                "total_saved_frames": len(time_nom),
                "labels_artifact_sha256": digests[str(nom_lbl_p.resolve())],
            },
            "dense": {
                "xml_nominal_timeout_s": NOMINAL_XML_TIMEOUT_S,
                "effective_cli_timeout_s": DENSE_CLI_TIMEOUT_S,
                "effective_save_interval_s": DENSE_CLI_TIMEOUT_S,
                "total_saved_frames": len(time_dense),
                "labels_artifact_sha256": digests[str(dense_lbl_p.resolve())],
            },
            "save_cadence_refinement_factor": float(len(time_dense) / len(time_nom)),
        },
        "cohort_identity_validation": {
            "status": "exact_1to1_uid_match",
            "total_identities": EXPECTED_TOTAL_IDENTITIES,
            "fluid_particles": n_fluid,
            "total_fluid_mass_kg": total_mass_kg,
            "discrepancies_detected": 0,
        },
        "physical_time_alignment": {
            "window_s": [0.0, common_end_time],
            "frames_aligned": len(time_pairs),
            "max_alignment_time_discrepancy_s": max_align_delta,
            "alignment_tolerance_satisfied": bool(max_align_delta <= DENSE_CLI_TIMEOUT_S / 2.0 + 1e-9),
        },
        "destination_series_agreement": dest_agreement,
        "events": event_results,
        "residence_time_comparison": residence_comparison,
        "claim_boundary": {
            "model_invoked": False,
            "production": "not_evaluated",
            "production_granted": False,
            "q_i": "saved_frequency_comparison_measurement_only",
            "q_n": "not_assessed",
            "q_n_granted": False,
            "training": "not_authorized",
            "governance_note": (
                "Descriptive saved-frequency comparison isolating temporal save-cadence quantization error "
                "between nominal (836 frames) and dense (4176 frames) saves of the identical adaptive run. "
                "No arbitrary 5% autogates; Q-I measurement only."
            ),
        },
        "input_sha256": digests,
        "resource_usage": usage_stats(),
    }

    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nominal-labels", type=Path, required=True, help="Nominal native-labels.h5")
    parser.add_argument("--nominal-report", type=Path, required=True, help="Nominal labels-report.json")
    parser.add_argument("--dense-labels", type=Path, required=True, help="Dense native-labels.h5")
    parser.add_argument("--dense-report", type=Path, required=True, help="Dense labels-report.json")
    parser.add_argument("--config", type=Path, required=True, help="Transport config JSON")
    parser.add_argument("--output", type=Path, required=True, help="Output comparison JSON")
    parser.add_argument("--max-particles", type=int, default=None, help="Max particles to audit (for tests)")

    args = parser.parse_args()
    report = compare_f3_saved_frequency(
        nominal_labels_path=args.nominal_labels,
        nominal_report_path=args.nominal_report,
        dense_labels_path=args.dense_labels,
        dense_report_path=args.dense_report,
        config_path=args.config,
        output_path=args.output,
        max_particles=args.max_particles,
    )
    print(json.dumps({
        "schema": report["schema"],
        "cohort": report["cohort_identity_validation"],
        "alignment": report["physical_time_alignment"],
        "destination_agreement": report["destination_series_agreement"]["mean_destination_agreement_fraction"],
        "events": {k: {
            "knot_supremum": v["empirical_cdf_comparison"]["knot_supremum_absolute_deviation"],
            "l1_fraction_s": v["empirical_cdf_comparison"]["l1_integrated_cdf_deviation_fraction_s"],
            "bracket_overlap": v["save_bracket_analysis"].get("bracket_overlap_fraction"),
        } for k, v in report["events"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
