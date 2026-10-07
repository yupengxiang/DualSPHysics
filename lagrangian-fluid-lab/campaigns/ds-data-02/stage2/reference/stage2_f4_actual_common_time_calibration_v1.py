#!/usr/bin/env python3
"""Audit actual F4 selected observers at common physical times.

The four inputs are already completed selected-observer JSON sidecars.  This
worker reads only those small sidecars and never opens a native Part file or
an HDF5 payload.  It reports the actual timestamp brackets and computes
provisional weighted-observable deltas, but keeps every bracketed comparison
UNKNOWN until an independently calibrated interpolation/output-error bound
exists.  Frame numbers are retained as provenance only and are never used to
pair observations.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REPORT_PATH = REFERENCE / "stage2_f4_actual_common_time_calibration_v1.json"
PLAN_PATH = REFERENCE / "stage2_f4_physical_observer_calibration_plan_v1.json"
SELFTEST_PATH = REFERENCE / "stage2_f4_physical_observer_compare_selftest_v1.json"

OBSERVERS = {
    "dp0_same_cfl": DATA_ROOT / "families/F4/F4_S1_DP0_SAME_CFL_SELECTED_PHYSICAL_OBSERVER_V2/f4-s1-dp0-same-cfl-selected-observer-primary-001/observer/f4_s1_dp0_selected_physical_observer.json",
    "dp0_half_cfl": DATA_ROOT / "families/F4/F4_S1_DP0_HALF_CFL_SELECTED_PHYSICAL_OBSERVER_FORWARD_V1/f4-s1-half-cfl-selected-observer-primary-001/observer/f4_s1_selected_physical_observer.json",
    "coarse_same_cfl": DATA_ROOT / "families/F4/F4_S1_COARSE_SELECTED_PHYSICAL_OBSERVER_FORWARD_V1/f4-s1-coarse-selected-observer-primary-001/observer/f4_s1_selected_physical_observer.json",
    "fine_same_cfl": DATA_ROOT / "families/F4/F4_S1_FINE_DP008_SELECTED_PHYSICAL_OBSERVER_V3/f4-s1-fine-dp008-selected-observer-v3-primary-001/observer/f4_s1_fine_dp0008_selected_physical_observer_v3.json",
}
QUERY_TIMES = (0.0, 0.3, 0.6, 0.9, 1.2)
LATE_QUERY_TIMES = (0.9, 1.2)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(path)}


def atomic_json(path: Path, value: Any) -> None:
    encoded = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise FileExistsError(f"refusing to overwrite existing report: {path}")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def finite_float(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is non-finite")
    return result


def load_observer(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "PASS_DECODED_SELECTED_NATIVE_FIELDS":
        raise ValueError(f"observer is not a completed selected decode: {path}")
    scope = value.get("scope", {})
    if scope.get("selected_frames_only") is not True or scope.get("hdf5_read") is not False:
        raise ValueError(f"observer scope is not selected native only: {path}")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError(f"observer has no observations: {path}")
    times = [finite_float(row["time"]["decoded_s"], f"{path}:time") for row in observations]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError(f"observer times are not strictly increasing: {path}")
    for row in observations:
        actual = finite_float(row["time"]["runparts_s"], "RunPARTs time")
        decoded = finite_float(row["time"]["decoded_s"], "decoded time")
        if abs(actual - decoded) > 1.0e-12:
            raise ValueError(f"RunPARTs/decoded time mismatch exceeds audit bound: {path}")
        fluid = row.get("groups", {}).get("fluid")
        if not isinstance(fluid, dict) or "weighted_centroid_m" not in fluid or "weighted_velocity_m_per_s" not in fluid:
            raise ValueError(f"weighted fluid observables missing: {path}")
    return value


def bracket(times: list[float], query: float) -> dict[str, Any]:
    if not math.isfinite(query):
        return {"query_time_s": query, "status": "REJECT_NONFINITE_QUERY"}
    if query < times[0] or query > times[-1]:
        return {"query_time_s": query, "status": "OUTSIDE_SAVED_WINDOW", "window_s": [times[0], times[-1]]}
    for index, actual in enumerate(times):
        if actual == query:
            return {"query_time_s": query, "status": "EXACT", "lower_frame": index, "upper_frame": index, "lower_time_s": actual, "upper_time_s": actual, "bracket_width_s": 0.0}
        if actual > query:
            lower = index - 1
            width = actual - times[lower]
            return {
                "query_time_s": query,
                "status": "BRACKETED",
                "lower_frame": lower,
                "upper_frame": index,
                "lower_time_s": times[lower],
                "upper_time_s": actual,
                "bracket_width_s": width,
                "interpolation_fraction": (query - times[lower]) / width,
            }
    raise AssertionError("bracket search fell through an in-window query")


def vector(value: Any, label: str) -> list[float]:
    values = [finite_float(item, label) for item in value]
    if len(values) != 3:
        raise ValueError(f"{label} is not a 3-vector")
    return values


def field_summary(observation: dict[str, Any]) -> dict[str, Any]:
    fluid = observation["groups"]["fluid"]
    by_mk: dict[str, Any] = {}
    for mk, group in sorted((fluid.get("by_mk") or {}).items(), key=lambda item: str(item[0])):
        by_mk[str(mk)] = {
            "sample_mass_kg": finite_float(group["sample_mass_kg"], f"mk{mk} mass"),
            "weighted_centroid_m": vector(group["weighted_centroid_m"], f"mk{mk} centroid"),
            "weighted_velocity_m_per_s": vector(group["weighted_velocity_m_per_s"], f"mk{mk} velocity"),
            "kinetic_energy_j": finite_float(group["kinetic_energy_j"], f"mk{mk} KE"),
            "count": int(group["count"]),
        }
    return {
        "sample_mass_kg": finite_float(fluid["sample_mass_kg"], "fluid mass"),
        "weighted_centroid_m": vector(fluid["weighted_centroid_m"], "fluid centroid"),
        "weighted_velocity_m_per_s": vector(fluid["weighted_velocity_m_per_s"], "fluid velocity"),
        "kinetic_energy_j": finite_float(fluid["kinetic_energy_j"], "fluid KE"),
        "count": int(fluid["count"]),
        "by_mk": by_mk,
        "source_float32_centroid": vector(fluid["centroid_m"], "float32 centroid"),
        "source_float32_velocity": vector(fluid["mean_velocity_m_per_s"], "float32 velocity"),
    }


def mix(a: float, b: float, fraction: float) -> float:
    return a + fraction * (b - a)


def mix_vector(a: list[float], b: list[float], fraction: float) -> list[float]:
    return [mix(x, y, fraction) for x, y in zip(a, b)]


def interpolate_summary(lower: dict[str, Any], upper: dict[str, Any], fraction: float) -> dict[str, Any]:
    by_mk: dict[str, Any] = {}
    common_mk = sorted(set(lower["by_mk"]) & set(upper["by_mk"]))
    for mk in common_mk:
        left, right = lower["by_mk"][mk], upper["by_mk"][mk]
        by_mk[mk] = {
            "sample_mass_kg": mix(left["sample_mass_kg"], right["sample_mass_kg"], fraction),
            "weighted_centroid_m": mix_vector(left["weighted_centroid_m"], right["weighted_centroid_m"], fraction),
            "weighted_velocity_m_per_s": mix_vector(left["weighted_velocity_m_per_s"], right["weighted_velocity_m_per_s"], fraction),
            "kinetic_energy_j": mix(left["kinetic_energy_j"], right["kinetic_energy_j"], fraction),
            "count": left["count"],
        }
    return {
        "sample_mass_kg": mix(lower["sample_mass_kg"], upper["sample_mass_kg"], fraction),
        "weighted_centroid_m": mix_vector(lower["weighted_centroid_m"], upper["weighted_centroid_m"], fraction),
        "weighted_velocity_m_per_s": mix_vector(lower["weighted_velocity_m_per_s"], upper["weighted_velocity_m_per_s"], fraction),
        "kinetic_energy_j": mix(lower["kinetic_energy_j"], upper["kinetic_energy_j"], fraction),
        "count": lower["count"],
        "by_mk": by_mk,
        "interpolation": "linear_provisional_only",
    }


def query_summary(value: dict[str, Any], query: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    status = query["status"]
    observations = value["observations"]
    if status == "OUTSIDE_SAVED_WINDOW":
        return None, "UNKNOWN_OUTSIDE_SAVED_WINDOW"
    if status == "EXACT":
        return field_summary(observations[query["lower_frame"]]), "EXACT_VALUE"
    if status == "BRACKETED":
        lower = field_summary(observations[query["lower_frame"]])
        upper = field_summary(observations[query["upper_frame"]])
        return interpolate_summary(lower, upper, float(query["interpolation_fraction"])), "BRACKETED_VALUE_UNCALIBRATED"
    return None, "UNKNOWN_QUERY_STATUS"


def delta(reference: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    centroid_delta = [b - a for a, b in zip(reference["weighted_centroid_m"], variant["weighted_centroid_m"])]
    velocity_delta = [b - a for a, b in zip(reference["weighted_velocity_m_per_s"], variant["weighted_velocity_m_per_s"])]
    ref_ke = reference["kinetic_energy_j"]
    var_ke = variant["kinetic_energy_j"]
    ke_relative: float | str
    if ref_ke == 0.0:
        ke_relative = "UNDEFINED_ZERO_REFERENCE"
    else:
        ke_relative = (var_ke - ref_ke) / abs(ref_ke)
    regions: dict[str, Any] = {}
    for mk in sorted(set(reference["by_mk"]) & set(variant["by_mk"])):
        a = reference["by_mk"][mk]
        b = variant["by_mk"][mk]
        regions[mk] = {
            "sample_mass_delta_kg": b["sample_mass_kg"] - a["sample_mass_kg"],
            "sample_mass_relative_fraction": "UNDEFINED_ZERO_REFERENCE" if a["sample_mass_kg"] == 0.0 else (b["sample_mass_kg"] - a["sample_mass_kg"]) / abs(a["sample_mass_kg"]),
            "weighted_centroid_delta_m": [y - x for x, y in zip(a["weighted_centroid_m"], b["weighted_centroid_m"])],
            "weighted_velocity_delta_m_per_s": [y - x for x, y in zip(a["weighted_velocity_m_per_s"], b["weighted_velocity_m_per_s"])],
            "kinetic_energy_delta_j": b["kinetic_energy_j"] - a["kinetic_energy_j"],
        }
    return {
        "fluid": {
            "sample_mass_delta_kg": variant["sample_mass_kg"] - reference["sample_mass_kg"],
            "sample_mass_relative_fraction": "UNDEFINED_ZERO_REFERENCE" if reference["sample_mass_kg"] == 0.0 else (variant["sample_mass_kg"] - reference["sample_mass_kg"]) / abs(reference["sample_mass_kg"]),
            "weighted_centroid_delta_m": centroid_delta,
            "weighted_centroid_l2_m": math.sqrt(sum(item * item for item in centroid_delta)),
            "weighted_velocity_delta_m_per_s": velocity_delta,
            "weighted_velocity_l2_m_per_s": math.sqrt(sum(item * item for item in velocity_delta)),
            "kinetic_energy_delta_j": var_ke - ref_ke,
            "kinetic_energy_relative_fraction": ke_relative,
        },
        "by_mk": regions,
    }


def run() -> dict[str, Any]:
    loaded = {label: load_observer(path) for label, path in OBSERVERS.items()}
    metadata: dict[str, Any] = {}
    query_records: dict[str, list[dict[str, Any]]] = {}
    summaries: dict[str, dict[float, tuple[dict[str, Any] | None, str]]] = {}
    for label, value in loaded.items():
        source = value["source"]
        times = [finite_float(row["time"]["decoded_s"], f"{label} time") for row in value["observations"]]
        metadata[label] = {
            "observer": record(OBSERVERS[label]),
            "source_scope": value["scope"],
            "source_runparts": source.get("runparts"),
            "source_generated_xml": source.get("generated_xml"),
            "decoder": source.get("decoder"),
            "selected_frames": source.get("selected_frames"),
            "selected_count": len(value["observations"]),
            "full_runparts_frame_count": value["scope"].get("runparts_frame_count"),
            "actual_selected_window_s": [times[0], times[-1]],
            "actual_output_parameters": source.get("particle_range_semantics", {}).get("parameters", {}),
            "position_dtype": value["observations"][0].get("position_dtype"),
            "mass_semantics": value.get("mass_semantics"),
        }
        rows = [bracket(times, query) for query in QUERY_TIMES]
        query_records[label] = rows
        summaries[label] = {query: query_summary(value, row) for query, row in zip(QUERY_TIMES, rows)}

    comparisons: dict[str, Any] = {}
    for variant in ("dp0_half_cfl", "coarse_same_cfl", "fine_same_cfl"):
        entries: list[dict[str, Any]] = []
        for query in QUERY_TIMES:
            ref_query, ref_status = summaries["dp0_same_cfl"][query]
            var_query, var_status = summaries[variant][query]
            comparison: dict[str, Any] = {
                "status": "COMPUTED_STRUCTURAL_ONLY" if ref_status == "EXACT_VALUE" and var_status == "EXACT_VALUE" else "UNKNOWN_UNCALIBRATED_BRACKET",
                "reference_value_status": ref_status,
                "variant_value_status": var_status,
            }
            if ref_query is not None and var_query is not None:
                comparison["provisional_weighted_observable_delta"] = delta(ref_query, var_query)
            else:
                comparison["provisional_weighted_observable_delta"] = "UNAVAILABLE"
            entries.append({"query_time_s": query, "reference_bracket": next(row for row in query_records["dp0_same_cfl"] if row["query_time_s"] == query), "variant_bracket": next(row for row in query_records[variant] if row["query_time_s"] == query), "comparison": comparison})
        comparisons[variant] = {"against": "dp0_same_cfl", "queries": entries}

    return {
        "schema": "ds02.stage2.f4-actual-common-time-calibration.v1",
        "status": "ACTUAL_SELECTED_OBSERVER_COMMON_TIME_AUDIT",
        "preparation_source_commit": git_head(),
        "sentinel_id": "F4-S1",
        "family_id": "F4",
        "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "scope": {
            "native_or_h5_read_by_this_worker": False,
            "input_scope": "four completed selected-observer JSON sidecars only",
            "full_native_tree_scanned": False,
            "output_qualification": "UNKNOWN_SELECTED_OBSERVER_ONLY",
            "field_interpolation_by_worker": False,
            "weighted_operator": "groups.fluid.weighted_centroid_m / weighted_velocity_m_per_s and kinetic_energy_j; float32 mean fields retained only as diagnostic",
        },
        "common_query_registration": {
            "query_times_s": list(QUERY_TIMES),
            "late_query_times_s": list(LATE_QUERY_TIMES),
            "time_policy": "actual selected timestamps; exact/bracketed status recorded per run; no frame-index pairing or extrapolation",
            "bracketed_values": "provisional linear values are emitted for audit visibility but comparison remains UNKNOWN until independent interpolation/output calibration",
            "endpoint_rule": "query 1.2 requires a saved time at or beyond 1.2; each actual endpoint and shortfall is retained",
        },
        "frozen_error_budget": {
            "position_relative_to_L": 0.02,
            "event_position_relative_to_L": 0.05,
            "velocity_and_ke_nonzero_reference": 0.05,
            "regional_mass_fraction_of_whole_initial_fluid_mass": 0.03,
            "event_time_fraction_of_characteristic_time": 0.01,
            "time_error_fraction_of_total_window": 0.25,
            "output_error_fraction_of_total_window": 0.25,
        },
        "manufactured_calibration": {
            "selftest": record(SELFTEST_PATH),
            "selftest_status": json.loads(SELFTEST_PATH.read_text(encoding="utf-8")).get("status"),
            "calibration_interpretation": "manufactured boundary behavior is PASS; it does not calibrate real field interpolation error",
        },
        "runs": metadata,
        "actual_query_brackets": query_records,
        "comparisons": comparisons,
        "late_common_time_summary": {
            "queries": list(LATE_QUERY_TIMES),
            "all_variants_have_saved_time_at_or_beyond_1p2": all(query_records[label][-1]["status"] != "OUTSIDE_SAVED_WINDOW" for label in OBSERVERS),
            "comparison_status": "UNKNOWN_UNCALIBRATED_BRACKETS",
            "output_resolution_status": "UNKNOWN_SELECTED_9_FRAMES_FROM_2401_FRAME_RUNS",
            "note": "The late values are useful source-bound diagnostics; they do not grant QI/QN/QE or prove dense-output convergence.",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


if __name__ == "__main__":
    report = run()
    atomic_json(REPORT_PATH, report)
    print(json.dumps({"status": report["status"], "report": str(REPORT_PATH), "queries": list(QUERY_TIMES)}, ensure_ascii=False))
