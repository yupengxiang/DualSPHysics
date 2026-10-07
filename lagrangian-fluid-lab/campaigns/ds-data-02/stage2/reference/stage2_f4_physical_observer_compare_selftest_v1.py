#!/usr/bin/env python3
"""Manufactured boundary tests for the F4 observer comparison contract."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from stage2_f4_physical_observer_compare_v1 import compare


def group(mk: int, *, mass: float = 1.0, sample: float = 2.0, centroid: list[float] | None = None, ke: float = 0.0) -> dict:
    return {
        "kind": "fluid", "mk": mk, "count": 2, "particle_mass_kg": mass, "sample_mass_kg": sample,
        "centroid_m": centroid or [0.0, 0.0, 0.0], "mean_velocity_m_per_s": [0.0, 0.0, 0.0],
        "kinetic_energy_j": ke, "density": {"mean": 1000.0, "status": "PASS_FINITE"},
    }


def observer(status: str = "EXACT", *, include_mk1: bool = True, nan_centroid: bool = False, q: float = 0.0, bracket: tuple[float, float] | None = None) -> dict:
    if bracket is None and status in {"EXACT", "EXACT_OR_LEFT"}:
        query = {"query_time_s": q, "status": status, "lower_frame": 0, "upper_frame": 0, "lower_time_s": q, "upper_time_s": q}
        observations = [{
            "frame": 0,
            "identity": {"particle_count": 4, "id_min": 0, "id_max": 3},
            "groups": {"fluid": {"by_mk": {"0": group(0), **({"1": group(1)} if include_mk1 else {})}}},
            "fluid_observables": {"sample_mass_kg": 2.0, "centroid_m": [float("nan"), 0.0, 0.0] if nan_centroid else [0.0, 0.0, 0.0], "mean_velocity_m_per_s": [0.0, 0.0, 0.0], "kinetic_energy_j": 0.0},
        }]
    elif bracket is not None:
        query = {"query_time_s": q, "status": "BRACKETED", "lower_frame": 0, "upper_frame": 1, "lower_time_s": bracket[0], "upper_time_s": bracket[1], "bracket_width_s": bracket[1] - bracket[0]}
        observations = []
    else:
        query = {"query_time_s": q, "status": status, "actual_window_s": [0.0, 0.25]}
        observations = []
    return {"schema": "ds02.stage2.f4-physical-observer.v1", "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS", "time_window": {"first_saved_time_s": 0.0, "last_saved_time_s": 0.25, "queries": [query]}, "observations": observations, "source_deleted": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = {}

    outside = compare(observer("OUTSIDE_SAVED_WINDOW", q=1.0), observer("OUTSIDE_SAVED_WINDOW", q=1.0), physical_case_id="manufactured")
    cases["outside_window_rejected_without_extrapolation"] = {
        "pass": outside["query_comparisons"][0]["comparison"] == "UNKNOWN_NO_INTERPOLATION",
        "status": outside["query_comparisons"][0]["status"],
    }

    unequal = compare(observer(bracket=(0.4, 0.6), q=0.5), observer(bracket=(0.45, 0.55), q=0.5), physical_case_id="manufactured")
    q_unequal = unequal["query_comparisons"][0]
    cases["unequal_timestamp_brackets_remain_unknown"] = {
        "pass": q_unequal["comparison"] == "UNKNOWN_NO_INTERPOLATION" and q_unequal["reference_bracket"]["lower_time_s"] != q_unequal["variant_bracket"]["lower_time_s"],
        "status": q_unequal["status"],
        "reference_bracket": q_unequal["reference_bracket"],
        "variant_bracket": q_unequal["variant_bracket"],
    }

    nonunit_a, nonunit_b = observer(), observer()
    nonunit_b["observations"][0]["groups"]["fluid"]["by_mk"]["0"]["particle_mass_kg"] = 0.5
    nonunit_b["observations"][0]["groups"]["fluid"]["by_mk"]["0"]["sample_mass_kg"] = 1.0
    nonunit_b["observations"][0]["fluid_observables"]["kinetic_energy_j"] = 1.0
    nonunit = compare(nonunit_a, nonunit_b, physical_case_id="manufactured")
    exact = nonunit["query_comparisons"][0]["comparison"]
    mk0 = exact["regions_and_material_allocation"]["fluid_mk_0"]
    cases["nonunit_mass_and_zero_reference_are_not_silently_passed"] = {
        "pass": mk0["particle_mass_kg"]["status"] == "COMPUTED" and exact["aggregate_fluid"]["kinetic_energy_j"]["relative_error_fraction_vs_a"] == "UNDEFINED_ZERO_REFERENCE",
        "particle_mass_delta": mk0["particle_mass_kg"],
        "zero_ke_delta": exact["aggregate_fluid"]["kinetic_energy_j"],
    }

    missing = compare(observer(include_mk1=True), observer(include_mk1=False), physical_case_id="manufactured")
    missing_region = missing["query_comparisons"][0]["comparison"]["regions_and_material_allocation"]["fluid_mk_1"]
    cases["missing_material_region_is_unknown"] = {"pass": missing_region["status"] == "UNKNOWN_REGION_MISSING", "status": missing_region["status"]}

    nan_case = compare(observer(nan_centroid=True), observer(), physical_case_id="manufactured")
    nan_centroid = nan_case["query_comparisons"][0]["comparison"]["aggregate_fluid"]["centroid_m"]
    cases["nan_observable_is_unknown"] = {"pass": nan_centroid["status"] == "UNKNOWN_NONFINITE_OR_MISSING", "status": nan_centroid["status"]}

    passed = all(bool(value["pass"]) for value in cases.values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps({"schema": "ds02.stage2.f4-physical-observer-compare-selftest.v1", "status": "PASS_ALL_MANUFACTURED_BOUNDARIES" if passed else "FAIL_MANUFACTURED_BOUNDARY", "cases": cases, "uses_native_or_h5": False}, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    if not passed:
        raise SystemExit(1)
    print(json.dumps({"status": "PASS_ALL_MANUFACTURED_BOUNDARIES", "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
