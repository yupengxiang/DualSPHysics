#!/usr/bin/env python3
"""Compare F7 native transport labels across time/save refinements on the 12s window (v2).

This v2 replaces the legacy 601-frame hardcoded comparator (ds_data02_f7_native_transport_compare_v1)
with a full-window paired-identity transport audit for 6001-frame dense datasets.

Features:
- Handles 6001-frame dense save datasets (and arbitrary matching frame counts >= 2).
- Verifies exact unique UID, particle_zone, and native weight matching across all identities.
- Performs full paired cohort decomposition: joint-observed, baseline-only, variant-only, joint-censored.
- Computes per-identity chord delta statistics (mean signed, mean absolute, median, p95, max).
- Computes true interval non-overlap (empty intersection of passage brackets).
- Computes unconditional initial mass CDF over [0, 12] s and supremum deviation.
- Preserves native exclusion mass (unknown-loss semantics; no legal-exit claim).
- Retains frozen kinetic energy provenance (scale 89.584705923 J, ~43% negative spatial KE).
- Zero learned weights or surrogate models; strictly descriptive measurement.
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


SCHEMA = "ds02.f7.full-native-transport-comparison.v3"
WINDOW_START_S = 0.0
WINDOW_END_S = 12.0


def digest(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def usage_stats() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        v = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(v.ru_utime)
        result[f"{label}_system_seconds"] = float(v.ru_stime)
        result[f"{label}_max_rss_kib"] = float(v.ru_maxrss)
    return result


def compute_unconditional_cdf(
    times: np.ndarray,
    censored_mask: np.ndarray,
    weights: np.ndarray,
    grid: np.ndarray,
) -> tuple[np.ndarray, dict[str, float | None]]:
    """Compute unconditional initial mass CDF at supplied evaluation times; retain initial-mass denominator."""
    total_mass = float(np.sum(weights))
    if total_mass <= 0:
        raise ValueError("Total mass must be positive for CDF evaluation")

    # Observed particles have event time t; censored particles have event time > WINDOW_END_S
    effective_times = np.where(censored_mask, WINDOW_END_S + 1.0, times)
    order = np.argsort(effective_times)
    sorted_times = effective_times[order]
    sorted_weights = weights[order]
    cumsum_weights = np.cumsum(sorted_weights)

    idx = np.searchsorted(sorted_times, grid, side="right") - 1
    cdf_values = np.where(idx >= 0, cumsum_weights[np.maximum(0, idx)] / total_mass, 0.0)

    # Compute passage time deciles (10%, 20%, ..., 90%)
    deciles: dict[str, float | None] = {}
    for q in range(10, 100, 10):
        target = (q / 100.0) * total_mass
        d_idx = np.searchsorted(cumsum_weights, target, side="left")
        if d_idx < len(sorted_times) and sorted_times[d_idx] <= WINDOW_END_S:
            deciles[f"p{q}_time_s"] = float(sorted_times[d_idx])
        else:
            deciles[f"p{q}_time_s"] = None

    return cdf_values, deciles


def compare(
    baseline_path: Path,
    variant_path: Path,
    budget_path: Path,
    event_config_path: Path,
    baseline_report_path: Path,
    variant_report_path: Path,
    output_path: Path,
    *,
    cdf_grid_points: int = 1201,
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"Output path already exists: {output_path}")

    # Load and verify reports
    baseline_report = json.loads(baseline_report_path.read_text())
    variant_report = json.loads(variant_report_path.read_text())
    budget = json.loads(budget_path.read_text())
    event_config = json.loads(event_config_path.read_text())

    # Input file digests
    input_files = [
        baseline_path, variant_path, budget_path, event_config_path,
        baseline_report_path, variant_report_path,
    ]
    digests = {str(p): digest(p) for p in input_files}

    if baseline_report.get("sha256") != digests[str(baseline_path)]:
        raise ValueError("Baseline report sha256 disagrees with actual file digest")
    if variant_report.get("sha256") != digests[str(variant_path)]:
        raise ValueError("Variant report sha256 disagrees with actual file digest")

    n_frames_base = baseline_report["frames"]
    n_frames_var = variant_report["frames"]
    if n_frames_base != n_frames_var:
        raise ValueError(f"Frame count mismatch: baseline={n_frames_base} vs variant={n_frames_var}")

    n_identities_base = baseline_report["identities"]
    n_identities_var = variant_report["identities"]
    if n_identities_base != n_identities_var:
        raise ValueError(f"Identity count mismatch: baseline={n_identities_base} vs variant={n_identities_var}")

    event_ids = [e["id"] for e in event_config["events"]]
    if baseline_report["event_ids"] != event_ids or variant_report["event_ids"] != event_ids:
        raise ValueError("Event ID mismatch between reports and event config")

    allowance_s = budget["physical_scale"]["save_or_integration_event_budget_s"]
    total_budget_s = budget["physical_scale"]["event_absolute_budget_s"]

    # Open both label HDF5 artifacts
    with h5py.File(baseline_path, "r") as h_base, h5py.File(variant_path, "r") as h_var:
        # Check completeness
        if not bool(h_base.attrs.get("complete", False)) or not bool(h_var.attrs.get("complete", False)):
            raise ValueError("Both label artifacts must have complete=True attribute")

        # Verify identity alignment; exact native weights and frozen event configuration
        uids_base = h_base["particle_id"][:]
        uids_var = h_var["particle_id"][:]
        if not np.array_equal(uids_base, uids_var):
            raise ValueError("Particle IDs do not match identically between baseline and variant")

        zones_base = h_base["particle_zone"][:]
        zones_var = h_var["particle_zone"][:]
        if not np.array_equal(zones_base, zones_var):
            raise ValueError("Particle zones do not match identically between baseline and variant")

        sources_base = h_base["source_label"][:]
        sources_var = h_var["source_label"][:]
        if not np.array_equal(sources_base, sources_var):
            raise ValueError("Source labels do not match identically between baseline and variant")

        # Initial fluid mass
        masses_base = h_base["initial_fluid_mass_kg"][:]
        masses_var = h_var["initial_fluid_mass_kg"][:]
        if masses_base.dtype != masses_var.dtype or not np.array_equal(masses_base, masses_var):
            raise ValueError("Per-particle initial masses differ between baseline and variant")
        assert np.isfinite(masses_base).all() and (masses_base >= 0).all()
        keys = np.column_stack((zones_base, uids_base))
        assert len(np.unique(keys, axis=0)) == len(keys), 'UID/zone keys must be unique'
        weights = masses_base.astype(np.float64)
        total_initial_mass_kg = float(np.sum(weights))

        times_base = h_base["time"][:]
        times_var = h_var["time"][:]
        if len(times_base) != n_frames_base or len(times_var) != n_frames_var:
            raise ValueError("Time array length disagrees with frame count")

        for h in [h_base, h_var]:
            assert json.loads(h.attrs['config_json']) == event_config
        for t in [times_base, times_var]:
            assert np.isfinite(t).all() and (np.diff(t)>0).all() and t[0]==0 and t[-1]>=12
        # Time grid only for compact CDF display; exact diagnostics use all jump knots
        cdf_grid = np.linspace(WINDOW_START_S, WINDOW_END_S, cdf_grid_points)

        events_output: list[dict[str, Any]] = []
        crossing_counts_base = h_base['total_crossing_count'][:].astype(np.int64)
        crossing_counts_var = h_var['total_crossing_count'][:].astype(np.int64)
        for h, counts, report in [(h_base,crossing_counts_base,baseline_report),(h_var,crossing_counts_var,variant_report)]:
            assert counts.shape == (len(weights),len(event_ids))
            assert np.array_equal(counts.sum(axis=0), report['event_crossing_counts'])
            assert len(h['all_observed_crossings']) == report['all_observed_crossing_rows']
            assert np.array_equal(h['cyclic_recrossing_count'][:], np.maximum(counts-1,0))

        for ei, event_id in enumerate(event_ids):
            censor_base = h_base["first_passage_censor"][:, ei]
            censor_var = h_var["first_passage_censor"][:, ei]
            chord_base = h_base["first_passage_chord_time"][:, ei]
            chord_var = h_var["first_passage_chord_time"][:, ei]
            interval_base = h_base["first_passage_interval"][:, ei, :]
            interval_var = h_var["first_passage_interval"][:, ei, :]

            assert np.isin(censor_base,[0,1]).all() and np.isin(censor_var,[0,1]).all()
            obs_base = (censor_base == 0)
            obs_var = (censor_var == 0)

            for observed, chord, interval in [(obs_base,chord_base,interval_base),(obs_var,chord_var,interval_var)]:
                assert np.isfinite(chord[observed]).all() and np.isfinite(interval[observed]).all()
                assert ((interval[observed,0] <= chord[observed]) & (chord[observed] <= interval[observed,1])).all()
            # Cohort breakdown
            joint_mask = obs_base & obs_var
            base_only_mask = obs_base & (~obs_var)
            var_only_mask = (~obs_base) & obs_var
            joint_cens_mask = (~obs_base) & (~obs_var)

            joint_count = int(np.sum(joint_mask))
            base_only_count = int(np.sum(base_only_mask))
            var_only_count = int(np.sum(var_only_mask))
            joint_cens_count = int(np.sum(joint_cens_mask))

            joint_mass = float(np.sum(weights[joint_mask]))
            base_only_mass = float(np.sum(weights[base_only_mask]))
            var_only_mass = float(np.sum(weights[var_only_mask]))
            joint_cens_mass = float(np.sum(weights[joint_cens_mask]))

            switching_count = base_only_count + var_only_count
            switching_mass = base_only_mass + var_only_mass
            net_change_count = var_only_count - base_only_count
            net_change_mass = var_only_mass - base_only_mass

            # Paired chord delta statistics on joint cohort
            if joint_count > 0:
                t_b = chord_base[joint_mask]
                t_v = chord_var[joint_mask]
                w_j = weights[joint_mask]

                deltas = t_v - t_b
                abs_deltas = np.abs(deltas)

                mean_signed_s = float(np.mean(deltas))
                mean_abs_s = float(np.mean(abs_deltas))
                median_abs_s = float(np.median(abs_deltas))
                p95_abs_s = float(np.percentile(abs_deltas, 95))
                p99_abs_s = float(np.percentile(abs_deltas, 99))
                max_abs_s = float(np.max(abs_deltas))
                min_abs_s = float(np.min(abs_deltas))

                mass_weighted_mean_signed_s = float(np.sum(deltas * w_j) / np.sum(w_j))
                mass_weighted_mean_abs_s = float(np.sum(abs_deltas * w_j) / np.sum(w_j))

                # Interval non-overlap
                # Interval shape: (n_particles, 2) where col 0 is t_lo, col 1 is t_hi
                iv_b = interval_base[joint_mask]
                iv_v = interval_var[joint_mask]
                # Overlap iff max(lo_b, lo_v) <= min(hi_b, hi_v)
                overlap = np.maximum(iv_b[:, 0], iv_v[:, 0]) <= np.minimum(iv_b[:, 1], iv_v[:, 1])
                non_overlap = ~overlap
                non_overlap_count = int(np.sum(non_overlap))
                non_overlap_mass = float(np.sum(w_j[non_overlap]))
                non_overlap_fraction = float(non_overlap_count / joint_count)
            else:
                mean_signed_s = None
                mean_abs_s = None
                median_abs_s = None
                p95_abs_s = None
                p99_abs_s = None
                max_abs_s = None
                min_abs_s = None
                mass_weighted_mean_signed_s = None
                mass_weighted_mean_abs_s = None
                non_overlap_count = 0
                non_overlap_mass = 0.0
                non_overlap_fraction = 0.0

            # Macro passage mean calculation
            m_base_tot = float(np.sum(weights[obs_base]))
            m_var_tot = float(np.sum(weights[obs_var]))
            macro_mean_base_s = float(np.sum(chord_base[obs_base] * weights[obs_base]) / m_base_tot) if m_base_tot > 0 else None
            macro_mean_var_s = float(np.sum(chord_var[obs_var] * weights[obs_var]) / m_var_tot) if m_var_tot > 0 else None
            macro_delta_s = (macro_mean_var_s - macro_mean_base_s) if (macro_mean_base_s is not None and macro_mean_var_s is not None) else None

            # Unconditional initial mass CDF
            cdf_base, deciles_base = compute_unconditional_cdf(chord_base, ~obs_base, weights, cdf_grid)
            cdf_var, deciles_var = compute_unconditional_cdf(chord_var, ~obs_var, weights, cdf_grid)
            cdf_abs_diff = np.abs(cdf_var - cdf_base)
            sampled_grid_max_cdf_deviation = float(np.max(cdf_abs_diff))
            knots = np.unique(np.concatenate(([0.,12.], chord_base[obs_base & (chord_base>=0) & (chord_base<=12)], chord_var[obs_var & (chord_var>=0) & (chord_var<=12)])))
            exact_base, _ = compute_unconditional_cdf(chord_base, ~obs_base, weights, knots)
            exact_var, _ = compute_unconditional_cdf(chord_var, ~obs_var, weights, knots)
            exact_abs = np.abs(exact_var-exact_base)
            max_cdf_deviation = float(exact_abs.max())
            l1_cdf_deviation_s = float(np.sum(exact_abs[:-1]*np.diff(knots)))

            # Sample CDF at 1-second intervals for compact JSON report
            sample_times = [float(t) for t in range(0, int(WINDOW_END_S) + 1)]
            sample_indices = [int(np.round(t / (WINDOW_END_S / (cdf_grid_points - 1)))) for t in sample_times]
            sampled_cdf_base = {f"t_{t:.0f}s": float(cdf_base[idx]) for t, idx in zip(sample_times, sample_indices)}
            sampled_cdf_var = {f"t_{t:.0f}s": float(cdf_var[idx]) for t, idx in zip(sample_times, sample_indices)}

            count_delta = crossing_counts_var[:,ei]-crossing_counts_base[:,ei]
            events_output.append({
                "all_observed_crossing_and_reentry_cohorts": {
                    "baseline_total_rows":int(crossing_counts_base[:,ei].sum()),
                    "variant_total_rows":int(crossing_counts_var[:,ei].sum()),
                    "baseline_rows_after_first_per_identity":int(np.maximum(crossing_counts_base[:,ei]-1,0).sum()),
                    "variant_rows_after_first_per_identity":int(np.maximum(crossing_counts_var[:,ei]-1,0).sum()),
                    "identities_with_changed_observed_count":int((count_delta!=0).sum()),
                    "mass_kg_with_changed_observed_count":float(weights[count_delta!=0].sum()),
                    "count_increased_identities":int((count_delta>0).sum()),
                    "count_decreased_identities":int((count_delta<0).sum()),
                    "maximum_absolute_count_change":int(np.abs(count_delta).max()),
                    "boundary":"All saved crossing rows retained; counts after first include repeated crossings in either direction; hidden between-save crossings unresolved"
                },
                "event_id": event_id,
                "cohort_breakdown": {
                    "joint_observed": {"count": joint_count, "mass_kg": joint_mass},
                    "baseline_only": {"count": base_only_count, "mass_kg": base_only_mass},
                    "variant_only": {"count": var_only_count, "mass_kg": var_only_mass},
                    "joint_censored": {"count": joint_cens_count, "mass_kg": joint_cens_mass},
                    "switching_identities": {"count": switching_count, "mass_kg": switching_mass},
                    "net_change_observed": {"count": net_change_count, "mass_kg": net_change_mass},
                },
                "per_identity_chord_deltas": {
                    "joint_count": joint_count,
                    "joint_mass_kg": joint_mass,
                    "mean_signed_delta_s": mean_signed_s,
                    "mean_absolute_delta_s": mean_abs_s,
                    "median_absolute_delta_s": median_abs_s,
                    "p95_absolute_delta_s": p95_abs_s,
                    "p99_absolute_delta_s": p99_abs_s,
                    "max_absolute_delta_s": max_abs_s,
                    "min_absolute_delta_s": min_abs_s,
                    "mass_weighted_mean_signed_delta_s": mass_weighted_mean_signed_s,
                    "mass_weighted_mean_absolute_delta_s": mass_weighted_mean_abs_s,
                },
                "interval_non_overlap": {
                    "non_overlapping_brackets_count": non_overlap_count,
                    "non_overlapping_brackets_mass_kg": non_overlap_mass,
                    "non_overlapping_brackets_fraction": non_overlap_fraction,
                },
                "macro_passage": {
                    "baseline_observed_count": int(np.sum(obs_base)),
                    "baseline_observed_mass_kg": m_base_tot,
                    "baseline_mass_weighted_chord_s": macro_mean_base_s,
                    "variant_observed_count": int(np.sum(obs_var)),
                    "variant_observed_mass_kg": m_var_tot,
                    "variant_mass_weighted_chord_s": macro_mean_var_s,
                    "macro_weighted_chord_delta_s": macro_delta_s,
                    "integration_budget_allowance_s": allowance_s,
                    "event_absolute_budget_s": total_budget_s,
                    "macro_weighted_chord_within_budget": (abs(macro_delta_s) <= allowance_s) if macro_delta_s is not None else None,
                },
                "unconditional_initial_mass_cdf": {
                    "max_absolute_cdf_deviation": max_cdf_deviation,
                    "sampled_grid_max_absolute_deviation": sampled_grid_max_cdf_deviation,
                    "exact_knots_count": len(knots),
                    "method": "Exact right-continuous empirical mass CDF at union of all observed jump times on [0,12]; rectangle integral between jumps",
                    "l1_integrated_cdf_deviation_s": l1_cdf_deviation_s,
                    "baseline_deciles": deciles_base,
                    "variant_deciles": deciles_var,
                    "sampled_cdf_baseline": sampled_cdf_base,
                    "sampled_cdf_variant": sampled_cdf_var,
                    "policy": "Strictly descriptive measurement; no invented 5% CDF pass gate or containment claim.",
                },
            })

    # Summary of observed crossing rows and recrossings from reports
    all_observed_rows_baseline = baseline_report["all_observed_crossing_rows"]
    all_observed_rows_variant = variant_report["all_observed_crossing_rows"]
    crossing_rows_delta = all_observed_rows_variant - all_observed_rows_baseline

    event_crossing_counts_baseline = dict(zip(event_ids, baseline_report["event_crossing_counts"]))
    event_crossing_counts_variant = dict(zip(event_ids, variant_report["event_crossing_counts"]))
    event_crossing_counts_delta = {
        eid: event_crossing_counts_variant[eid] - event_crossing_counts_baseline[eid]
        for eid in event_ids
    }

    # Native exclusion mass (unknown-loss semantics)
    exclusion_mass_baseline = baseline_report["final_native_exclusion_mass_kg"]
    exclusion_mass_variant = variant_report["final_native_exclusion_mass_kg"]
    exclusion_mass_delta = exclusion_mass_variant - exclusion_mass_baseline

    unknown_region_mass_baseline = baseline_report["final_unknown_region_mass_kg"]
    unknown_region_mass_variant = variant_report["final_unknown_region_mass_kg"]

    # Maximum half brackets across events
    max_half_brackets = [
        max(baseline_report["maximum_all_event_half_bracket_s"]),
        max(variant_report["maximum_all_event_half_bracket_s"]),
    ]

    report = {
        "schema": SCHEMA,
        "physical_window_s": [WINDOW_START_S, WINDOW_END_S],
        "frames": n_frames_base,
        "total_identities": n_identities_base,
        "total_initial_fluid_mass_kg": total_initial_mass_kg,
        "input_sha256": digests,
        "events": events_output,
        "all_observed_crossing_rows": {
            "baseline": all_observed_rows_baseline,
            "variant": all_observed_rows_variant,
            "delta": crossing_rows_delta,
            "per_event_baseline": event_crossing_counts_baseline,
            "per_event_variant": event_crossing_counts_variant,
            "per_event_delta": event_crossing_counts_delta,
        },
        "native_exclusion_mass": {
            "baseline_kg": exclusion_mass_baseline,
            "variant_kg": exclusion_mass_variant,
            "delta_kg": exclusion_mass_delta,
            "baseline_unknown_region_kg": unknown_region_mass_baseline,
            "variant_unknown_region_kg": unknown_region_mass_variant,
            "interpretation": (
                "Excluded particles represent native numerical boundary deletions by DualSPHysics; "
                "physical fate remains unassessed and must not be declared legal exit or containment."
            ),
        },
        "save_bracket_allocation": {
            "maximum_observed_half_bracket_s": max_half_brackets,
            "save_bracket_allocation_s": allowance_s,
            "save_bracket_allocation_pass": all(x <= allowance_s for x in max_half_brackets),
        },
        "kinetic_energy_provenance": {
            "frozen_reference_kinetic_energy_scale_j": 89.584705923,
            "preserved_spatial_ke_failed_relative_error_approx_percent": 43.0,
            "note": "Historical spatial KE comparison failed with about43% discrepancy; this is not a statement that kinetic energy is negative.",
        },
        "claim_boundary": {
            "model_invoked": False,
            "production": "not_evaluated",
            "production_granted": False,
            "q_i": "transport_comparison_measurement_only",
            "q_n": "not_assessed",
            "q_n_granted": False,
            "training": "not_authorized",
            "statement": (
                "Source-bound full-window (0-12s, 6001 frames) paired-identity transport diagnostics only; "
                "weighted means are descriptive only; per-identity deltas, interval non-overlap, cohort switching, "
                "and unconditional CDF reported without retrospective gate tuning or unphysical containment claims."
            ),
        },
        "resource_usage": usage_stats(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("baseline", "variant", "budget", "event-config", "baseline-report", "variant-report", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--cdf-grid-points", type=int, default=1201)
    args = parser.parse_args()

    result = compare(
        args.baseline,
        args.variant,
        args.budget,
        getattr(args, "event_config"),
        getattr(args, "baseline_report"),
        getattr(args, "variant_report"),
        args.output,
        cdf_grid_points=args.cdf_grid_points,
    )
    print(json.dumps({
        "schema": result["schema"],
        "all_observed_crossing_rows": result["all_observed_crossing_rows"],
        "native_exclusion_mass_delta_kg": result["native_exclusion_mass"]["delta_kg"],
        "q_n_status": "not_assessed",
    }))


if __name__ == "__main__":
    main()
