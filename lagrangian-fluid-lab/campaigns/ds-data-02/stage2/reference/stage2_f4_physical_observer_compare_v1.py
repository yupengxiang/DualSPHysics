#!/usr/bin/env python3
"""Compare selected F4 native observer sidecars at common query times.

This is an aggregate comparison only.  It never pairs particle IDs between
grids and never interpolates a bracketed query.  A bracket is retained in the
result, while position/velocity/kinetic-energy/region comparisons are marked
UNKNOWN until a consumer supplies an explicit interpolation/phase policy.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f4-physical-observer-compare.v1"
THRESHOLDS = {
    "position_scale_fraction_L": 0.02,
    "event_position_fraction_L": 0.05,
    "velocity_relative_fraction_nonzero_scale": 0.05,
    "kinetic_energy_relative_fraction_nonzero_scale": 0.05,
    "regional_mass_fraction_of_whole_initial": 0.03,
    "event_time_fraction": 0.01,
    "time_budget_fraction": 0.25,
    "output_budget_fraction": 0.25,
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"observer sidecar must be an object: {path}")
    return value


def atomic_json(path: Path, value: object) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def require_observer(value: dict[str, Any], label: str) -> None:
    if value.get("schema") != "ds02.stage2.f4-physical-observer.v1":
        raise ValueError(f"{label}: unsupported observer schema {value.get('schema')!r}")
    if not value.get("observations"):
        raise ValueError(f"{label}: no observations")
    if value.get("source_deleted") is True:
        raise ValueError(f"{label}: source_deleted=true")


def query_map(value: dict[str, Any]) -> dict[float, dict[str, Any]]:
    queries = value.get("time_window", {}).get("queries", [])
    result: dict[float, dict[str, Any]] = {}
    for query in queries:
        if not isinstance(query, dict) or not isinstance(query.get("query_time_s"), (int, float)):
            continue
        result[float(query["query_time_s"])] = query
    return result


def compact_bracket(query: dict[str, Any] | None) -> dict[str, Any]:
    if not query:
        return {"status": "MISSING_QUERY"}
    keep = ("query_time_s", "status", "lower_frame", "upper_frame", "lower_time_s", "upper_time_s", "bracket_width_s", "interpolation_fraction", "actual_window_s")
    return {key: query[key] for key in keep if key in query}


def observation_by_frame(value: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for observation in value.get("observations", []):
        if isinstance(observation, dict) and isinstance(observation.get("frame"), int):
            result[observation["frame"]] = observation
    return result


def exact_observation(value: dict[str, Any], query: dict[str, Any], frames: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    status = query.get("status")
    if status not in {"EXACT", "EXACT_OR_LEFT"}:
        return None
    frame = query.get("lower_frame")
    if not isinstance(frame, int):
        return None
    return frames.get(frame)


def scalar_diff(a: Any, b: Any) -> dict[str, Any]:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not math.isfinite(float(a)) or not math.isfinite(float(b)):
        return {"status": "UNKNOWN_NONFINITE_OR_MISSING", "a": a, "b": b}
    delta = float(b) - float(a)
    denom = abs(float(a))
    return {
        "status": "COMPUTED",
        "a": a,
        "b": b,
        "delta_b_minus_a": delta,
        "absolute_delta": abs(delta),
        "relative_error_fraction_vs_a": (abs(delta) / denom if denom else (0.0 if delta == 0 else "UNDEFINED_ZERO_REFERENCE")),
        "relative_error_pct_vs_a": (100.0 * abs(delta) / denom if denom else (0.0 if delta == 0 else "UNDEFINED_ZERO_REFERENCE")),
    }


def vector_diff(a: Any, b: Any) -> dict[str, Any]:
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b) or any(not isinstance(x, (int, float)) for x in a + b):
        return {"status": "UNKNOWN_NONFINITE_OR_MISSING", "a": a, "b": b}
    delta = [float(y) - float(x) for x, y in zip(a, b)]
    if any(not math.isfinite(x) for x in delta):
        return {"status": "UNKNOWN_NONFINITE_OR_MISSING", "a": a, "b": b}
    return {"status": "COMPUTED", "a": a, "b": b, "delta_b_minus_a": delta, "l2_absolute_delta": math.sqrt(sum(x * x for x in delta)), "max_absolute_delta": max((abs(x) for x in delta), default=0.0)}


def compare_group(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "count": scalar_diff(a.get("count"), b.get("count")),
        "particle_mass_kg": scalar_diff(a.get("particle_mass_kg"), b.get("particle_mass_kg")),
        "sample_mass_kg": scalar_diff(a.get("sample_mass_kg"), b.get("sample_mass_kg")),
        "centroid_m": vector_diff(a.get("centroid_m"), b.get("centroid_m")),
        "mean_velocity_m_per_s": vector_diff(a.get("mean_velocity_m_per_s"), b.get("mean_velocity_m_per_s")),
        "kinetic_energy_j": scalar_diff(a.get("kinetic_energy_j"), b.get("kinetic_energy_j")),
        "density_mean_kg_m3": scalar_diff((a.get("density") or {}).get("mean"), (b.get("density") or {}).get("mean")),
    }
    result["status"] = "COMPUTED_AGGREGATE_ONLY"
    return result


def fluid_groups(observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = observation.get("groups", {})
    fluid = groups.get("fluid", {}) if isinstance(groups, dict) else {}
    result: dict[str, dict[str, Any]] = {}
    if isinstance(fluid, dict):
        result["whole_fluid"] = fluid
        by_mk = fluid.get("by_mk", {})
        if isinstance(by_mk, dict):
            for mk, group in by_mk.items():
                if isinstance(group, dict):
                    result[f"fluid_mk_{mk}"] = group
    return result


def compare_exact(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    identity_a = a.get("identity", {})
    identity_b = b.get("identity", {})
    groups_a = fluid_groups(a)
    groups_b = fluid_groups(b)
    region_names = sorted(set(groups_a) | set(groups_b))
    regions: dict[str, Any] = {}
    for name in region_names:
        if name not in groups_a or name not in groups_b:
            regions[name] = {"status": "UNKNOWN_REGION_MISSING", "a_present": name in groups_a, "b_present": name in groups_b}
        else:
            regions[name] = compare_group(groups_a[name], groups_b[name])
    whole_a = a.get("fluid_observables", {})
    whole_b = b.get("fluid_observables", {})
    aggregate = {
        "sample_mass_kg": scalar_diff(whole_a.get("sample_mass_kg"), whole_b.get("sample_mass_kg")),
        "centroid_m": vector_diff(whole_a.get("centroid_m"), whole_b.get("centroid_m")),
        "mean_velocity_m_per_s": vector_diff(whole_a.get("mean_velocity_m_per_s"), whole_b.get("mean_velocity_m_per_s")),
        "kinetic_energy_j": scalar_diff(whole_a.get("kinetic_energy_j"), whole_b.get("kinetic_energy_j")),
    }
    return {
        "status": "EXACT_COMPARISON_RECORDED",
        "particle_identity": {
            "paired_by_particle_id": False,
            "reference_particle_count": identity_a.get("particle_count"),
            "variant_particle_count": identity_b.get("particle_count"),
            "reference_id_range": [identity_a.get("id_min"), identity_a.get("id_max")],
            "variant_id_range": [identity_b.get("id_min"), identity_b.get("id_max")],
        },
        "aggregate_fluid": aggregate,
        "regions_and_material_allocation": regions,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def compare(reference: dict[str, Any], variant: dict[str, Any], *, physical_case_id: str) -> dict[str, Any]:
    require_observer(reference, "reference")
    require_observer(variant, "variant")
    q_ref, q_var = query_map(reference), query_map(variant)
    frames_ref, frames_var = observation_by_frame(reference), observation_by_frame(variant)
    times = sorted(set(q_ref) | set(q_var))
    rows = []
    for time_s in times:
        ar, av = q_ref.get(time_s), q_var.get(time_s)
        row: dict[str, Any] = {"query_time_s": time_s, "reference_bracket": compact_bracket(ar), "variant_bracket": compact_bracket(av)}
        orow = exact_observation(reference, ar or {}, frames_ref) if ar else None
        vrow = exact_observation(variant, av or {}, frames_var) if av else None
        if orow is None or vrow is None:
            row.update({"status": "UNKNOWN_BRACKETED_OR_OUTSIDE_QUERY", "comparison": "UNKNOWN_NO_INTERPOLATION"})
        else:
            row["status"] = "EXACT_QUERY_COMPARISON"
            row["comparison"] = compare_exact(orow, vrow)
        rows.append(row)
    return {
        "schema": SCHEMA,
        "status": "PASS_SIDEcar_COMPARISON_WITH_BRACKETED_UNKNOWN",
        "physical_case_id": physical_case_id,
        "reference": {"schema": reference.get("schema"), "status": reference.get("status"), "source": reference.get("source", {}), "time_window": reference.get("time_window", {}) if False else {"first_saved_time_s": reference.get("time_window", {}).get("first_saved_time_s"), "last_saved_time_s": reference.get("time_window", {}).get("last_saved_time_s")}},
        "variant": {"schema": variant.get("schema"), "status": variant.get("status"), "source": variant.get("source", {}), "time_window": variant.get("time_window", {}) if False else {"first_saved_time_s": variant.get("time_window", {}).get("first_saved_time_s"), "last_saved_time_s": variant.get("time_window", {}).get("last_saved_time_s")}},
        "frozen_tolerances": THRESHOLDS,
        "sampling_policy": {"query_times_are_common_physical_times": True, "bracketed_queries": "retain bracket metadata and mark field comparisons UNKNOWN", "out_of_window": "UNKNOWN; no extrapolation", "particle_interpolation": "NOT_PERFORMED", "particle_id_pairing": "NOT_PERFORMED"},
        "query_comparisons": rows,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--variant", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--physical-case-id", default="F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000")
    args = parser.parse_args()
    result = compare(load(args.reference), load(args.variant), physical_case_id=args.physical_case_id)
    atomic_json(args.output, result)
    print(json.dumps({"output": str(args.output), "queries": len(result["query_comparisons"])}, indent=2))


if __name__ == "__main__":
    main()
