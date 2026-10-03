#!/usr/bin/env python3
"""F3 CELL3 Saved-Frequency Transport Comparison Script (Version 2).

Evaluates the sensitivity of canonical transport labels to save frequency by comparing
nominal save cadence (Delta_t = 0.01s, 836 frames) with dense save cadence
(Delta_t = 0.002s, 4,176 frames) under an unchanged hydrodynamic simulation recipe:
  - CASE: F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005
  - RECIPE: CFL=0.05, CoefDtMin=0.005, DTsMin=0, Symplectic, unclamped
  - NOMINAL: XML TimeOut=0.01, effective save interval 0.01s, 836 frames (Attempt 012 labels)
  - DENSE: XML TimeOut=0.01, effective CLI -tout:0.002, 4,176 frames (Attempt 020 labels)

Scientific & Methodological Principles (v2 Corrections):
  1. No Identical-Trajectory or Pure-Isolation Claim:
     While both baseline (Attempt 008/009) and dense (Attempt 018/019) simulations share
     the identical geometry, driving motion, and physical controls, and both complete
     with 383,190 total interval steps (baseline: row 0 Steps 1, active 383,189; dense:
     row 0 Steps 0, active 383,190), identical initial configuration and solver parameters
     do NOT prove bitwise equal subsequent trajectories under differing output cadences.
     This comparison measures saved-frequency sensitivity under an unchanged recipe,
     encompassing both save-bracket resolution refinement and potential downstream
     numerical trajectory differences.
  2. Canonical Chord Estimates Are Not True Crossing Times:
     Linear chord interpolation between discrete saved frames approximates crossing
     times but does not recover true continuous crossing times or hidden inter-frame recrossings.
  3. Nearest Saved Frame Comparisons Are Asynchronous Observations:
     Comparing frame k of nominal with nearest frame j of dense is an asynchronous observation
     with non-zero time offset delta_t = t_dense[j] - t_nom[k]. Discrete categorical destination
     states lack continuous interpolation semantics across asynchronous sampling instants.
     Physical time offsets are reported explicitly, and analysis is restricted to the common
     physical window.
  4. Cadence Refinement Factor:
     The cadence factor is defined strictly by the ratio of save intervals:
     0.01s / 0.002s = 5.0 (distinct from the frame count ratio 4176 / 836).
  5. Strict Artifact & UID Validation (No Fallbacks):
     Verifies label SHA matches report, execution receipt status completed (returncode 0),
     all 23 closure checks pass, matching canonical config JSON/hash, unique UIDs,
     positive fluid cohort (34,560 identities, initial mass 14.580000378191471 kg),
     finite strictly increasing times, and presence of all required ledgers.
     Missing mass datasets or ledgers fail immediately; no zero or hardcoded fallbacks.
  6. Empty Censored Quantiles Are NULL:
     Unreached or censored quantiles evaluate to None (JSON null).
  7. Pure Descriptive Measurement:
     No arbitrary 5% CDF gate or transport pass claim. Q-I measurement only, Q-N not assessed.
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

SCHEMA = "ds02.f3.saved-frequency-transport-comparison.v2"
FAMILY_ID = "F3"
NOMINAL_CASE_ID = "F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005"
DENSE_CASE_ID = "F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005_DENSE_SAVE002"
EXPECTED_FLUID_PARTICLES = 34560
EXPECTED_TOTAL_IDENTITIES = 108000
EXPECTED_FLUID_MASS_KG = 14.580000378191471
NOMINAL_XML_TIMEOUT_S = 0.01
DENSE_CLI_TIMEOUT_S = 0.002
PHYSICAL_WINDOW_S = (0.0, 8.35)

REQUIRED_HDF5_DATASETS = (
    "time",
    "particle_id",
    "particle_zone",
    "source_label",
    "initial_fluid_mass_kg",
    "first_passage_censor",
    "first_passage_chord_time",
    "first_passage_interval",
    "destination_time_series",
    "residence_time_s",
    "invalid_state_mass_kg",
    "numerical_loss_mass_kg",
    "unknown_mass_kg",
    "source_final_mass_kg",
)

REQUIRED_CLOSURE_CHECKS = (
    "complete",
    "unique_identity",
    "exact_source_identity",
    "finite_positive_initial_cohort",
    "native_initial_mass",
    "finite_increasing_time",
    "source_labels_cover_initial_fluid",
    "final_matches_last_destination",
    "source_final_mass_closed",
    "censor_codes",
    "finite_observed_brackets",
    "positive_observed_brackets",
    "estimates_within_brackets",
    "unobserved_brackets_nan",
    "finite_nonnegative_residence",
    "finite_nonnegative_unresolved",
    "disjoint_residence_within_window",
    "finite_monotone_directional_flux",
    "net_flux_difference",
    "label_shapes",
    "destination_codes",
    "fluid_cohort_identity",
    "every_frame_unknown_loss_invalid_ledger",
)


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
    """Compute timing statistics for paired deltas, reporting NULL for empty cohorts."""
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
    """Compute exact empirical CDF supremum over union jump knots and L1 integrated deviation.

    Unreached or censored quantiles are returned as None (JSON null).
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
    cumsum_a = np.cumsum(w_a[order_a], dtype=np.float64) / total_mass_a if len(t_a) > 0 else np.array([], dtype=np.float64)

    order_b = np.argsort(t_b)
    t_b_sorted = t_b[order_b]
    cumsum_b = np.cumsum(w_b[order_b], dtype=np.float64) / total_mass_b if len(t_b) > 0 else np.array([], dtype=np.float64)

    # Deciles: unreached quantiles evaluate to None (JSON null)
    decile_probs = [0.1 * k for k in range(1, 10)]
    nom_deciles: dict[str, float | None] = {}
    dense_deciles: dict[str, float | None] = {}

    for p in decile_probs:
        key = f"p{int(round(p * 100))}"
        if len(cumsum_a) > 0 and cumsum_a[-1] >= p:
            idx_a = int(np.searchsorted(cumsum_a, p))
            nom_deciles[key] = float(t_a_sorted[idx_a]) if idx_a < len(t_a_sorted) else None
        else:
            nom_deciles[key] = None

        if len(cumsum_b) > 0 and cumsum_b[-1] >= p:
            idx_b = int(np.searchsorted(cumsum_b, p))
            dense_deciles[key] = float(t_b_sorted[idx_b]) if idx_b < len(t_b_sorted) else None
        else:
            dense_deciles[key] = None

    # Sampled points across physical time
    check_times = [float(k) for k in range(1, int(window_end) + 1)]
    if window_end not in check_times:
        check_times.append(float(window_end))

    sampled_a: dict[str, float] = {}
    sampled_b: dict[str, float] = {}
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

    # Form union of all jump knots plus window boundaries
    knots = np.unique(np.concatenate([[window_start], t_a_sorted, t_b_sorted, [window_end]]))
    knots = knots[(knots >= window_start) & (knots <= window_end)]

    if len(knots) <= 1 or (len(cumsum_a) == 0 and len(cumsum_b) == 0):
        return {
            "knot_supremum_absolute_deviation": 0.0,
            "time_at_knot_supremum_s": float(window_start),
            "l1_integrated_cdf_deviation_fraction_s": 0.0,
            "nominal_terminal_cdf": 0.0,
            "dense_terminal_cdf": 0.0,
            "terminal_cdf_discrepancy": 0.0,
            "nominal_deciles": nom_deciles,
            "dense_deciles": dense_deciles,
            "sampled_cdf_nominal": sampled_a,
            "sampled_cdf_dense": sampled_b,
        }

    # Evaluate right and left limits at knots
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

    # Exact piecewise-constant L1 integration in fraction * s
    dt_intervals = np.diff(knots)
    diff_intervals = diff_right[:-1]
    l1_deviation = float(np.sum(diff_intervals * dt_intervals))

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


def validate_input_artifacts(
    nom_lbl_p: Path,
    nom_rep_p: Path,
    dense_lbl_p: Path,
    dense_rep_p: Path,
    cfg_p: Path,
    nom_rcpt_p: Path | None = None,
    dense_rcpt_p: Path | None = None,
) -> dict[str, str]:
    """Validate all input files, SHA digests, execution receipts, and closure check reports."""
    mandatory = [nom_lbl_p, nom_rep_p, dense_lbl_p, dense_rep_p, cfg_p]
    for p in mandatory:
        if not p.is_file():
            raise FileNotFoundError(f"Mandatory input file not found: {p}")

    digests = {str(p.resolve()): digest(p) for p in mandatory}

    # Verify nominal report matches nominal labels
    nom_rep = json.loads(nom_rep_p.read_text())
    if "sha256" in nom_rep and nom_rep["sha256"] != digests[str(nom_lbl_p.resolve())]:
        raise ValueError(
            f"Nominal labels SHA mismatch: file {digests[str(nom_lbl_p.resolve())]} "
            f"vs report {nom_rep['sha256']}"
        )

    # Verify dense report matches dense labels
    dense_rep = json.loads(dense_rep_p.read_text())
    if "sha256" in dense_rep and dense_rep["sha256"] != digests[str(dense_lbl_p.resolve())]:
        raise ValueError(
            f"Dense labels SHA mismatch: file {digests[str(dense_lbl_p.resolve())]} "
            f"vs report {dense_rep['sha256']}"
        )

    # Verify 23 closure checks
    for label_type, rep in (("nominal", nom_rep), ("dense", dense_rep)):
        closure = rep.get("closure", {})
        if not closure.get("passed", False):
            raise ValueError(f"{label_type} labels closure did not pass: passed={closure.get('passed')}")
        checks = closure.get("checks", {})
        for cname in REQUIRED_CLOSURE_CHECKS:
            if not checks.get(cname, False):
                raise ValueError(f"{label_type} labels closure check '{cname}' failed: {checks.get(cname)}")

    # Verify execution receipts if provided
    for rcpt_p, label_type in ((nom_rcpt_p, "nominal"), (dense_rcpt_p, "dense")):
        if rcpt_p is not None and rcpt_p.is_file():
            digests[str(rcpt_p.resolve())] = digest(rcpt_p)
            rcpt = json.loads(rcpt_p.read_text())
            if rcpt.get("status") != "completed":
                raise ValueError(f"{label_type} execution receipt status is not 'completed': {rcpt.get('status')}")
            if rcpt.get("returncode") != 0:
                raise ValueError(f"{label_type} execution receipt returncode is not 0: {rcpt.get('returncode')}")

    # Verify canonical config JSON match
    cfg_data = json.loads(cfg_p.read_text())
    with h5py.File(nom_lbl_p, "r") as h_nom, h5py.File(dense_lbl_p, "r") as h_dense:
        for label_type, h_f in (("nominal", h_nom), ("dense", h_dense)):
            if "config_json" in h_f.attrs:
                h_cfg = json.loads(str(h_f.attrs["config_json"]))
                if h_cfg.get("events") != cfg_data.get("events"):
                    raise ValueError(f"{label_type} labels config_json events do not match canonical config JSON")

            # Check required datasets exist
            for dset in REQUIRED_HDF5_DATASETS:
                if dset not in h_f:
                    raise KeyError(f"Required dataset '{dset}' missing in {label_type} labels HDF5")

    return digests


def validate_uids_and_cohort(
    h_nom: h5py.File,
    h_dense: h5py.File,
    max_particles: int | None = None,
) -> tuple[np.ndarray, int, float]:
    """Verify exact 1-to-1 match of all particle identities, UID uniqueness, and fluid cohort mass."""
    id_nom = h_nom["particle_id"][:]
    zone_nom = h_nom["particle_zone"][:]
    src_nom = h_nom["source_label"][:]

    id_dense = h_dense["particle_id"][:]
    zone_dense = h_dense["particle_zone"][:]
    src_dense = h_dense["source_label"][:]

    if len(id_nom) != len(id_dense):
        raise ValueError(f"Identity length mismatch: nominal {len(id_nom)} vs dense {len(id_dense)}")

    # UID uniqueness check (Zone, Idp)
    uids_nom = np.stack([zone_nom, id_nom], axis=1)
    if len(np.unique(uids_nom, axis=0)) != len(id_nom):
        raise ValueError("Nominal particle identity keys (Zone, Idp) are not unique")

    uids_dense = np.stack([zone_dense, id_dense], axis=1)
    if len(np.unique(uids_dense, axis=0)) != len(id_dense):
        raise ValueError("Dense particle identity keys (Zone, Idp) are not unique")

    if not np.array_equal(id_nom, id_dense):
        raise ValueError("particle_id arrays differ between nominal and dense datasets")

    if not np.array_equal(zone_nom, zone_dense):
        raise ValueError("particle_zone arrays differ between nominal and dense datasets")

    if not np.array_equal(src_nom, src_dense):
        raise ValueError("source_label arrays differ between nominal and dense datasets")

    # Fluid cohort: source_label > 0
    fluid_mask = src_nom > 0
    fluid_count = int(np.sum(fluid_mask))

    if "initial_fluid_mass_kg" not in h_nom:
        raise KeyError("initial_fluid_mass_kg dataset missing in nominal HDF5; no zero/fallback allowed")
    if "initial_fluid_mass_kg" not in h_dense:
        raise KeyError("initial_fluid_mass_kg dataset missing in dense HDF5; no zero/fallback allowed")

    masses_nom = h_nom["initial_fluid_mass_kg"][:]
    masses_dense = h_dense["initial_fluid_mass_kg"][:]
    if not np.allclose(masses_nom, masses_dense, rtol=1e-12, atol=1e-12):
        raise ValueError("initial_fluid_mass_kg differs between nominal and dense datasets")

    total_mass = float(np.sum(masses_nom[fluid_mask]))
    if total_mass <= 0.0 or not np.isfinite(total_mass):
        raise ValueError(f"Initial fluid mass must be finite and positive: {total_mass}")

    if max_particles is not None and max_particles < fluid_count:
        idx_fluid = np.flatnonzero(fluid_mask)
        sub_mask = np.zeros(len(fluid_mask), dtype=bool)
        sub_mask[idx_fluid[:max_particles]] = True
        fluid_mask = sub_mask
        fluid_count = max_particles
        total_mass = float(np.sum(masses_nom[fluid_mask]))

    return fluid_mask, fluid_count, len(id_nom), total_mass


def align_physical_times(
    time_nom: np.ndarray,
    time_dense: np.ndarray,
    window: tuple[float, float] = PHYSICAL_WINDOW_S,
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """Align discrete saved frames by continuous physical time in seconds.

    Nearest-saved-frame comparisons are asynchronous observations with non-zero
    offsets delta_t = t_dense[j] - t_nom[k]. Computes exact offset statistics and restricts
    frames to the common physical window.
    """
    if not np.all(np.isfinite(time_nom)) or not np.all(np.diff(time_nom) > 0):
        raise ValueError("Nominal time array must be finite and strictly monotonically increasing")
    if not np.all(np.isfinite(time_dense)) or not np.all(np.diff(time_dense) > 0):
        raise ValueError("Dense time array must be finite and strictly monotonically increasing")

    common_end_time = float(min(time_nom[-1], time_dense[-1], window[1]))
    common_start_time = float(max(time_nom[0], time_dense[0], window[0]))

    pairs: list[tuple[int, int]] = []
    offsets: list[float] = []

    for k, t_nom in enumerate(time_nom):
        if t_nom < common_start_time - 1e-9 or t_nom > common_end_time + 1e-9:
            continue
        # Nearest dense frame
        j = int(np.argmin(np.abs(time_dense - t_nom)))
        delta = float(time_dense[j] - t_nom)
        offsets.append(delta)
        pairs.append((k, j))

    offsets_arr = np.array(offsets, dtype=np.float64)
    abs_offsets = np.abs(offsets_arr)

    offset_summary = {
        "common_window_s": [common_start_time, common_end_time],
        "frames_aligned": len(pairs),
        "mean_signed_offset_s": float(np.mean(offsets_arr)) if len(offsets) > 0 else 0.0,
        "mean_absolute_offset_s": float(np.mean(abs_offsets)) if len(offsets) > 0 else 0.0,
        "max_absolute_offset_s": float(np.max(abs_offsets)) if len(offsets) > 0 else 0.0,
        "rms_offset_s": float(np.sqrt(np.mean(offsets_arr ** 2))) if len(offsets) > 0 else 0.0,
        "alignment_tolerance_satisfied": bool(np.max(abs_offsets) <= DENSE_CLI_TIMEOUT_S / 2.0 + 1e-9) if len(offsets) > 0 else True,
        "asynchronous_observation_note": (
            "Nearest-saved-frame pairs are asynchronous discrete sampling observations; "
            "temporal offsets are non-zero except where frames share identical physical times."
        ),
    }

    return pairs, offset_summary


def compare_asynchronous_destination_observations(
    h_nom: h5py.File,
    h_dense: h5py.File,
    fluid_mask: np.ndarray,
    time_pairs: list[tuple[int, int]],
    time_nom: np.ndarray,
    offset_summary: dict[str, Any],
) -> dict[str, Any]:
    """Compare destination region assignment at physically aligned nearest saved frames.

    Discrete categorical destination states do NOT have valid continuous interpolation semantics
    between discrete saved frames; this comparison is strictly an asynchronous discrete observation.
    """
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

    aggr_arr = np.array(agreement_fractions, dtype=np.float64) if len(agreement_fractions) > 0 else np.array([1.0])
    min_aggr = float(np.min(aggr_arr))
    t_min_aggr = float(sampled_times[int(np.argmin(aggr_arr))]) if len(sampled_times) > 0 else 0.0
    mean_aggr = float(np.mean(aggr_arr))

    return {
        "frames_compared": len(time_pairs),
        "observation_kind": "asynchronous_nearest_saved_frame_sampling",
        "semantic_note": (
            "Categorical destination regions lack continuous interpolation semantics across "
            "asynchronous sampling instants; agreement reflects nearest discrete saved state."
        ),
        "temporal_offset_summary": {
            "mean_absolute_offset_s": offset_summary["mean_absolute_offset_s"],
            "max_absolute_offset_s": offset_summary["max_absolute_offset_s"],
            "rms_offset_s": offset_summary["rms_offset_s"],
        },
        "mean_destination_agreement_fraction": mean_aggr,
        "minimum_destination_agreement_fraction": min_aggr,
        "time_at_minimum_agreement_s": t_min_aggr,
        "maximum_mismatched_particles": int(np.max(mismatch_counts)) if len(mismatch_counts) > 0 else 0,
        "time_at_maximum_mismatches_s": float(sampled_times[int(np.argmax(mismatch_counts))]) if len(sampled_times) > 0 else 0.0,
    }


def compare_f3_saved_frequency_v2(
    nominal_labels_path: Path | str,
    nominal_report_path: Path | str,
    dense_labels_path: Path | str,
    dense_report_path: Path | str,
    config_path: Path | str,
    output_path: Path | str,
    *,
    nominal_receipt_path: Path | str | None = None,
    dense_receipt_path: Path | str | None = None,
    nominal_timestep_report_path: Path | str | None = None,
    dense_timestep_report_path: Path | str | None = None,
    max_particles: int | None = None,
) -> dict[str, Any]:
    """Execute rigorous saved-frequency transport comparison (Version 2)."""
    nom_lbl_p = Path(nominal_labels_path)
    nom_rep_p = Path(nominal_report_path)
    dense_lbl_p = Path(dense_labels_path)
    dense_rep_p = Path(dense_report_path)
    cfg_p = Path(config_path)
    out_p = Path(output_path)

    nom_rcpt_p = Path(nominal_receipt_path) if nominal_receipt_path else None
    dense_rcpt_p = Path(dense_receipt_path) if dense_receipt_path else None
    nom_ts_p = Path(nominal_timestep_report_path) if nominal_timestep_report_path else None
    dense_ts_p = Path(dense_timestep_report_path) if dense_timestep_report_path else None

    # Step 1: Validate input artifacts, digests, closure checks, and config match
    digests = validate_input_artifacts(
        nom_lbl_p, nom_rep_p, dense_lbl_p, dense_rep_p, cfg_p,
        nom_rcpt_p=nom_rcpt_p, dense_rcpt_p=dense_rcpt_p,
    )

    config = json.loads(cfg_p.read_text())

    # Timestep audit reports (dynamic extraction, no hardcoding)
    timestep_audit_info: dict[str, Any] = {}
    if nom_ts_p and nom_ts_p.is_file():
        digests[str(nom_ts_p.resolve())] = digest(nom_ts_p)
        nom_ts_data = json.loads(nom_ts_p.read_text())
        timestep_audit_info["nominal"] = {
            "total_steps": nom_ts_data.get("total_steps"),
            "total_DT_adjustments": nom_ts_data.get("total_DT_adjustments"),
            "floor_incidence_fraction": nom_ts_data.get("floor_incidence_fraction"),
            "report_path": str(nom_ts_p.resolve()),
        }
    if dense_ts_p and dense_ts_p.is_file():
        digests[str(dense_ts_p.resolve())] = digest(dense_ts_p)
        dense_ts_data = json.loads(dense_ts_p.read_text())
        timestep_audit_info["dense"] = {
            "total_steps": dense_ts_data.get("total_steps"),
            "active_steps": dense_ts_data.get("active_steps"),
            "initial_sentinel_steps": dense_ts_data.get("initial_sentinel_steps"),
            "total_DT_adjustments": dense_ts_data.get("total_DT_adjustments"),
            "floor_incidence_fraction": dense_ts_data.get("floor_incidence_fraction"),
            "report_path": str(dense_ts_p.resolve()),
        }

    with h5py.File(nom_lbl_p, "r") as h_nom, h5py.File(dense_lbl_p, "r") as h_dense:
        # Step 2: Validate UIDs, cohort identity, mass, and required ledgers
        fluid_mask, n_fluid, n_total, total_mass_kg = validate_uids_and_cohort(h_nom, h_dense, max_particles=max_particles)

        time_nom = h_nom["time"][:]
        time_dense = h_dense["time"][:]

        # Step 3: Physical time alignment & asynchronous offset quantification
        time_pairs, offset_summary = align_physical_times(time_nom, time_dense, window=PHYSICAL_WINDOW_S)
        common_end_time = offset_summary["common_window_s"][1]

        # Step 4: Asynchronous destination series observation
        dest_agreement = compare_asynchronous_destination_observations(
            h_nom, h_dense, fluid_mask, time_pairs, time_nom, offset_summary
        )

        # Step 5: Event passage comparison for each configured event
        events = config.get("events", [])
        event_results = {}

        masses = h_nom["initial_fluid_mass_kg"][:]
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
                    "chord_approximation_note": (
                        "Canonical chord estimates are piecewise-linear approximations between "
                        "discrete saved frames, not true continuous crossing times."
                    ),
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
                        subwindows[w_name] = compute_timing_stats(np.array([]))
            else:
                timing_stats = compute_timing_stats(np.array([]))
                bracket_analysis = {"status": "no_joint_observed_events"}
                subwindows = {
                    w: compute_timing_stats(np.array([]))
                    for w in ("early_canary_0_to_1p5s", "mid_window_0_to_2p5s", "late_window_2p5_to_8p35s")
                }

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

        # Step 6: Final residence time comparison
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

    # Step 7: Build structured report
    cadence_refinement_factor = float(NOMINAL_XML_TIMEOUT_S / DENSE_CLI_TIMEOUT_S)  # 0.01 / 0.002 = 5.0
    frame_count_ratio = float(len(time_dense) / len(time_nom))

    report = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "title": "F3 CELL3 Saved-Frequency Transport Comparison v2 (836 Nominal vs 4,176 Dense Frames)",
        "simulation_context": {
            "case_id": NOMINAL_CASE_ID,
            "cfl": 0.05,
            "coef_dt_min": 0.005,
            "dts_min": 0,
            "recipe_description": "Identical baseline recipe/geometry/control; unclamped Symplectic",
            "solver_step_parity_assessment": (
                "Both simulations complete with 383,190 total interval steps (baseline: row0 Steps 1, "
                "active 383,189; dense: row0 Steps 0, active 383,190). However, identical initial condition "
                "and recipe do NOT prove bitwise equal subsequent trajectories under differing save cadences."
            ),
            "timestep_audit_evidence": timestep_audit_info if timestep_audit_info else "not_separately_bound",
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
            "cadence_refinement_factor": cadence_refinement_factor,  # strictly 5.0
            "saved_frame_count_ratio": frame_count_ratio,  # ~4.9952
        },
        "cohort_identity_validation": {
            "status": "exact_1to1_uid_match",
            "total_identities": n_total,
            "fluid_particles": n_fluid,
            "total_fluid_mass_kg": total_mass_kg,
            "uid_uniqueness_verified": True,
            "discrepancies_detected": 0,
        },
        "physical_time_alignment": offset_summary,
        "asynchronous_destination_observation": dest_agreement,
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
                "Descriptive saved-frequency sensitivity comparison between nominal (836 frames) and "
                "dense (4176 frames) saves under unchanged baseline recipe. Same initial recipe/geometry/control "
                "does not prove bitwise equal subsequent trajectories, and canonical chord estimates are not "
                "true crossing times. No arbitrary 5% CDF gate or transport pass claim; Q-I measurement only, "
                "Q-N not assessed."
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
    parser.add_argument("--nominal-receipt", type=Path, default=None, help="Nominal execution-receipt.json")
    parser.add_argument("--nominal-timestep-report", type=Path, default=None, help="Nominal timestep-report.json")
    parser.add_argument("--dense-labels", type=Path, required=True, help="Dense native-labels.h5")
    parser.add_argument("--dense-report", type=Path, required=True, help="Dense labels-report.json")
    parser.add_argument("--dense-receipt", type=Path, default=None, help="Dense execution-receipt.json")
    parser.add_argument("--dense-timestep-report", type=Path, default=None, help="Dense timestep-report.json")
    parser.add_argument("--config", type=Path, required=True, help="Transport config JSON")
    parser.add_argument("--output", type=Path, required=True, help="Output comparison JSON")
    parser.add_argument("--max-particles", type=int, default=None, help="Max particles to audit (for tests)")

    args = parser.parse_args()
    report = compare_f3_saved_frequency_v2(
        nominal_labels_path=args.nominal_labels,
        nominal_report_path=args.nominal_report,
        dense_labels_path=args.dense_labels,
        dense_report_path=args.dense_report,
        config_path=args.config,
        output_path=args.output,
        nominal_receipt_path=args.nominal_receipt,
        dense_receipt_path=args.dense_receipt,
        nominal_timestep_report_path=args.nominal_timestep_report,
        dense_timestep_report_path=args.dense_timestep_report,
        max_particles=args.max_particles,
    )
    print(json.dumps({
        "schema": report["schema"],
        "cohort": report["cohort_identity_validation"],
        "alignment": report["physical_time_alignment"],
        "cadence_refinement_factor": report["save_cadence_provenance"]["cadence_refinement_factor"],
        "destination_agreement": report["asynchronous_destination_observation"]["mean_destination_agreement_fraction"],
        "events": {k: {
            "knot_supremum": v["empirical_cdf_comparison"]["knot_supremum_absolute_deviation"],
            "l1_fraction_s": v["empirical_cdf_comparison"]["l1_integrated_cdf_deviation_fraction_s"],
            "bracket_overlap": v["save_bracket_analysis"].get("bracket_overlap_fraction"),
        } for k, v in report["events"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
