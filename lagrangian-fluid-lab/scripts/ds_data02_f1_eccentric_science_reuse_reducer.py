#!/usr/bin/env python3
"""Reduce existing F1 ECC science evidence without rereading trajectory HDF5.

All inputs are JSON sidecars or receipts.  The reducer reports natural native
mass, frozen error allocations, existing macro and finite-aperture event
comparisons, and their explicit limitations.  It is an evidence reducer, not
a scientific acceptance gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
from typing import Any


def usage() -> dict[str, dict[str, float]]:
    def one(which: str) -> dict[str, float]:
        row = resource.getrusage(which)
        return {
            "user_seconds": row.ru_utime,
            "system_seconds": row.ru_stime,
            "max_rss_kib": float(row.ru_maxrss),
            "minor_faults": float(row.ru_minflt),
            "major_faults": float(row.ru_majflt),
            "in_block": float(row.ru_inblock),
            "out_block": float(row.ru_oublock),
            "voluntary_context_switches": float(row.ru_nvcsw),
            "involuntary_context_switches": float(row.ru_nivcsw),
        }
    return {"self": one(resource.RUSAGE_SELF), "children": one(resource.RUSAGE_CHILDREN)}


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def load_json(path_text: str) -> tuple[Path, Any]:
    path = Path(path_text)
    if path.suffix.lower() == ".h5":
        raise ValueError(f"HDF5 is deliberately excluded from this reducer: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    return path, json.loads(path.read_text())


def summarize_integrity(case: dict[str, Any], report: dict[str, Any], observation: dict[str, Any], continuous_mass: float) -> dict[str, Any]:
    ledger = report["fluid_mass_ledger"]
    mass = float(ledger["initial_mass_kg"])
    observed_rows = observation.get("rows", [])
    return {
        "case_id": case["case_id"],
        "resolution": case["resolution"],
        "dp_m": case["dp_m"],
        "solver_dimension": report["dimension_evidence"]["solver_dimension"],
        "frames": len(observed_rows),
        "initial_fluid_mass_kg": mass,
        "continuous_initial_mass_kg": continuous_mass,
        "mass_difference_kg": mass - continuous_mass,
        "mass_relative_error": mass / continuous_mass - 1.0,
        "mass_is_native_not_normalized": observation["normalization"] == "mass and energy retain physical scale; missing initial mass is explicit",
        "type3_fluid_ledger": {
            "initial_count": ledger["initial_count"],
            "retained_final_count": ledger["final_initial_cohort_retained_count"],
            "solver_excluded_particles": ledger["solver_excluded_particles"],
            "separate_from_type2": ledger["separate_from_type2"],
        },
        "q_i_status": report["q_i_status"],
        "q_n_status": report["q_n_status"],
    }


def summarize_series(observation: dict[str, Any]) -> dict[str, Any]:
    rows = observation["rows"]
    return {
        "frames": len(rows),
        "time_start_s": rows[0]["time_s"],
        "time_end_s": rows[-1]["time_s"],
        "initial_fluid_mass_kg": rows[0]["fluid_mass_kg"],
        "final_fluid_mass_kg": rows[-1]["fluid_mass_kg"],
        "mass_drift_kg": rows[-1]["fluid_mass_kg"] - rows[0]["fluid_mass_kg"],
        "active_fluid_count_initial": rows[0]["active_fluid_count"],
        "active_fluid_count_final": rows[-1]["active_fluid_count"],
        "q_n_status": observation["q_n_status"],
    }


def summarize_steps(steps: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for name, row in steps.items():
        if "measurement" not in row:
            # The sidecar also carries a non-case factor summary.  Preserve it
            # under its own key instead of treating it like a measurement row.
            result[name] = row
            continue
        measurement = row["measurement"]
        result[name] = {
            "status": row["status"],
            "native_minimum_dt_s": measurement["native_minimum_dt_s"],
            "native_maximum_dt_s": measurement["native_maximum_dt_s"],
            "internal_step_count": measurement["internal_step_count"],
            "final_time_s": measurement["final_time_s"],
            "saved_frame_count": measurement["saved_frame_count"],
            "source": measurement["source"],
            "source_sha256": measurement["source_sha256"],
        }
    return result


def summarize_dense_events(comparison: dict[str, Any], event_config: dict[str, Any], event_budget_s: float) -> dict[str, Any]:
    events = comparison["events"]
    residence = comparison["residence"]
    max_chord = max(float(row["chord_time_max_absolute_difference_s"]) for row in events)
    max_worst_bracket = max(float(row["saved_interval_worst_possible_max_difference_s"]) for row in events)
    max_weighted_chord = max(float(row["chord_time_mass_weighted_mean_absolute_difference_s"]) for row in events)
    max_residence = max(float(row["max_absolute_difference_s"]) for row in residence)
    return {
        "baseline_saved_frames": comparison["baseline_saved_frames"],
        "reference_saved_frames": comparison["reference_saved_frames"],
        "max_actual_timestamp_alignment_difference_s": comparison["max_actual_timestamp_alignment_difference_s"],
        "finite_aperture_event_ids": [row["id"] for row in event_config["events"]],
        "first_passage_semantics": event_config["limitations"][1],
        "events": [
            {
                "event_id": row["event_id"],
                "chord_time_max_absolute_difference_s": row["chord_time_max_absolute_difference_s"],
                "chord_time_mass_weighted_mean_absolute_difference_s": row["chord_time_mass_weighted_mean_absolute_difference_s"],
                "saved_interval_worst_possible_max_difference_s": row["saved_interval_worst_possible_max_difference_s"],
                "cumulative_forward_backward_max_difference_kg": row["cumulative_forward_backward_max_difference_kg"],
                "timestamp_bracket_forward_backward_max_difference_bound_kg": row["timestamp_bracket_forward_backward_max_difference_bound_kg"],
                "jointly_censored_mass_kg": row["jointly_censored_mass_kg"],
            }
            for row in events
        ],
        "residence": residence,
        "final_destination_disagreement_mass_kg": comparison["final_destination_disagreement_mass_kg"],
        "final_destination_disagreement_mass_fraction": comparison["final_destination_disagreement_mass_fraction"],
        "temporal_diagnostics": comparison["temporal_diagnostics"],
        "max_observed_chord_time_error_s": max_chord,
        "max_mass_weighted_chord_time_error_s": max_weighted_chord,
        "max_saved_bracket_worst_case_error_s": max_worst_bracket,
        "max_residence_error_s": max_residence,
        "event_budget_s": event_budget_s,
        "observed_chord_within_event_budget": max_chord <= event_budget_s,
        "worst_saved_bracket_within_event_budget": max_worst_bracket <= event_budget_s,
        "residence_within_event_budget": max_residence <= event_budget_s,
        "q_n_status": comparison["q_n_status"],
        "limitations": comparison["limitations"],
    }


def summarize_macro(comparison: dict[str, Any], macro_budget: float) -> dict[str, Any]:
    values = {
        "center_of_mass_difference_plus_time_offset_bound_over_H0": comparison["center_of_mass_difference_plus_time_offset_bound_over_H0"],
        "quantile_max_difference_over_H0": comparison["quantile_max_difference_over_H0"],
        "kinetic_energy_max_difference_over_continuous_MgH0": comparison["kinetic_energy_max_difference_over_continuous_MgH0"],
    }
    return {
        "same_native_initial_state": comparison["same_native_initial_state"],
        "saved_nominal_bin_count": comparison["saved_nominal_bin_count"],
        "maximum_actual_timestamp_difference_s": comparison["maximum_actual_timestamp_difference_s"],
        "metrics": values,
        "macro_budget": macro_budget,
        "metric_max": max(values.values()),
        "all_registered_metrics_within_macro_budget": max(values.values()) <= macro_budget,
        "fluid_mass_max_absolute_difference_kg": comparison["fluid_mass_max_absolute_difference_kg"],
        "q_n_status": comparison["q_n_status"],
        "inference": comparison["inference"],
        "limitations": comparison["limitations"],
    }


def summarize_half_labels(comparison: dict[str, Any]) -> dict[str, Any]:
    event_max = max(float(row["chord_time_max_absolute_difference_s"]) for row in comparison["events"])
    residence_max = max(float(row["max_absolute_difference_s"]) for row in comparison["residence"])
    return {
        "baseline_saved_frames": comparison["baseline_saved_frames"],
        "reference_saved_frames": comparison["reference_saved_frames"],
        "max_actual_timestamp_alignment_difference_s": comparison["max_actual_timestamp_alignment_difference_s"],
        "max_event_chord_error_s": event_max,
        "max_residence_error_s": residence_max,
        "final_destination_disagreement_mass_kg": comparison["final_destination_disagreement_mass_kg"],
        "final_destination_disagreement_mass_fraction": comparison["final_destination_disagreement_mass_fraction"],
        "temporal_diagnostics": comparison["temporal_diagnostics"],
        "q_n_status": comparison["q_n_status"],
        "limitations": comparison["limitations"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    before_usage = usage()
    manifest = json.loads(args.manifest.read_text())
    continuous_mass = float(manifest["continuous_initial_mass_kg"])
    loaded: dict[str, Any] = {}
    input_hashes: dict[str, str] = {str(args.manifest): sha256(args.manifest)}

    def get(name: str) -> Any:
        if name not in loaded:
            path, value = load_json(manifest["inputs"][name])
            loaded[name] = value
            input_hashes[str(path)] = sha256(path)
        return loaded[name]

    mass_rows = []
    for case in manifest["reference_cases"]:
        report = get(case["integrity_key"])
        observation = get(case["observation_key"])
        mass_rows.append(summarize_integrity(case, report, observation, continuous_mass))
    dense_observation = get("dense_observation")
    half_observation = get("half_dt_observation")
    metadata = get("budget_metadata")
    budget = metadata["error_budget"]
    event_scale = budget["event_time_scale"]
    event_budget_s = float(budget["event_time_error_absolute_seconds_at_nominal_H0"])
    macro_budget = float(budget["macro_observable_relative_error"])
    dense_labels = get("dense_label_comparison")
    half_labels = get("half_dt_label_comparison")
    dense_events = summarize_dense_events(dense_labels, get("event_config"), event_budget_s)
    half_macro = summarize_macro(get("half_dt_macro_comparison"), macro_budget)
    finite_faces = get("finite_face_audit")
    time_steps = summarize_steps(get("actual_native_steps"))
    result = {
        "schema": "ds02.f1.eccentric-science-reuse-reducer.v1",
        "family_id": "F1",
        "mechanism_id": "eccentric_obstacle",
        "source_hdf5_read": False,
        "source_hdf5_hash_policy": "no trajectory HDF5 opened; reducer consumes immutable JSON reports and receipts only",
        "continuous_initial_mass_kg": continuous_mass,
        "native_initial_mass_accounting": mass_rows,
        "frozen_error_budget": {
            "macro_relative_error": macro_budget,
            "event_time_fraction_of_characteristic_time": budget["event_time_error_fraction_of_characteristic_time"],
            "characteristic_time_s": event_scale["characteristic_time_s"],
            "event_time_absolute_budget_s": event_budget_s,
            "save_fraction_of_total_error_budget_max": budget["save_fraction_of_total_error_budget_max"],
            "integration_fraction_of_total_error_budget_max": budget["integration_fraction_of_total_error_budget_max"],
            "save_quantization_budget_s": event_scale["save_quantization_budget_s"],
            "event_control_time_out_s": event_scale["event_control_time_out_s"],
            "reference_matrix_time_out_s": event_scale["reference_matrix_time_out_s"],
            "reference_matrix_timing_status": event_scale["reference_matrix_timing_status"],
        },
        "time_study": time_steps,
        "dense_macro_series": summarize_series(dense_observation),
        "half_dt_macro_series": summarize_series(half_observation),
        "dense_finite_aperture_comparison": dense_events,
        "half_dt_finite_aperture_comparison": summarize_half_labels(half_labels),
        "half_dt_macro_comparison": half_macro,
        "finite_face_support": {
            "all_cases_outer_five_covered": finite_faces["all_cases_outer_five_covered"],
            "all_cases_obstacle_five_covered": finite_faces["all_cases_obstacle_five_covered"],
            "all_cases_source_unchanged": finite_faces["all_cases_source_unchanged"],
            "q_n_status": finite_faces["q_n_status"],
            "floor_intersection_treatment": finite_faces["floor_intersection_treatment"],
        },
        "assessment": {
            "native_mass_normalization": "not used; natural quadrature mass retained",
            "macro_evidence": "existing half-dt macro comparison has all reported metrics within 5% physical-scale macro budget",
            "dense_event_evidence": "existing .001 s finite-aperture comparison is complete-window evidence; observed chord/residence and saved-bracket bounds are reported against the frozen event budget",
            "qn_status": "not_granted",
            "production_approval": "none",
            "blocking_or_pending": [
                "event timing must account for observed event error and saved-bracket uncertainty against the frozen 2% allocation",
                "normal-vector and full scientific qualification remain separate from static Bound.vtk support",
                "HALF_DT existing comparison is diagnostic only; new floor-safe fixed-step request is prepared separately and not launched by this agent",
            ],
        },
        "input_sha256": input_hashes,
        "resource_usage": {"before": before_usage, "after": usage()},
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "native_mass_rows": len(mass_rows),
        "dense_event_budget_pass": dense_events["observed_chord_within_event_budget"],
        "dense_saved_bracket_budget_pass": dense_events["worst_saved_bracket_within_event_budget"],
        "macro_budget_pass": half_macro["all_registered_metrics_within_macro_budget"],
        "q_n_status": result["assessment"]["qn_status"],
    }))


if __name__ == "__main__":
    main()
