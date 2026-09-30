#!/usr/bin/env python3
"""Streaming F4 macro/transport observations from a direct-conversion HDF5.

The operator contract is registered separately from every resolution.  This
module therefore reports raw native mass, COM, momentum, and kinetic energy,
and computes source/destination and plane events from fixed physical regions.
It also emits the historical ``max(3*dp, 0.02 m)`` contact diagnostic with an
explicit resolution-dependent label.  It never turns observations into Q-N.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import resource
import time
from pathlib import Path
from typing import Any, Mapping

import h5py
import numpy as np

from scripts.ds_data02_direct_convert import (
    _validate_physical_binding,
    canonical_hash,
    sha256_file,
)


SCHEMA = "ds02.f4.reference-observations.v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _resource_snapshot() -> dict[str, float]:
    result: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        usage = resource.getrusage(who)
        result[f"{label}_user_seconds"] = float(usage.ru_utime)
        result[f"{label}_system_seconds"] = float(usage.ru_stime)
        result[f"{label}_max_rss_kib"] = float(usage.ru_maxrss)
    return result


def _usage_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def _bounds(region: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    low = np.asarray(region["low_m"], dtype=np.float64)
    high = low + np.asarray(region["size_m"], dtype=np.float64)
    if low.shape != (3,) or high.shape != (3,) or np.any(~np.isfinite(low)) or np.any(high <= low):
        raise ValueError(f"invalid physical region: {region}")
    return low, high


def _inside(position: np.ndarray, low: np.ndarray, high: np.ndarray, tolerance: float = 0.0) -> np.ndarray:
    return np.all((position >= low - tolerance) & (position <= high + tolerance), axis=1)


def _first_true(times: np.ndarray, flags: list[bool]) -> dict[str, Any]:
    indices = np.flatnonzero(np.asarray(flags, dtype=bool))
    if indices.size == 0:
        return {"status": "right_censored", "time_s": None}
    return {"status": "observed", "time_s": float(times[int(indices[0])]), "frame": int(indices[0])}


def _recontact(times: np.ndarray, flags: list[bool], first_index: int | None) -> dict[str, Any]:
    if first_index is None:
        return {"status": "right_censored", "time_s": None}
    left = False
    for index in range(first_index + 1, len(flags)):
        if left and flags[index]:
            return {"status": "observed", "time_s": float(times[index]), "frame": index}
        if not flags[index]:
            left = True
    return {"status": "right_censored", "time_s": None}


def _event_summary(times: np.ndarray, contact_flags: list[bool], spread: list[float]) -> dict[str, Any]:
    first = _first_true(times, contact_flags)
    first_index = first.get("frame")
    finite = np.asarray(spread, dtype=np.float64)
    if np.isfinite(finite).any():
        max_index = int(np.nanargmax(finite))
        maximum = {"status": "observed", "time_s": float(times[max_index]), "frame": max_index, "extent_m": float(finite[max_index])}
    else:
        maximum = {"status": "right_censored", "time_s": None, "extent_m": None}
    return {
        "first_contact": first,
        "maximum_spread_or_deflection": maximum,
        "recontact": _recontact(times, contact_flags, first_index),
        "contact_right_censored": first["status"] != "observed",
    }


def _region_operators(binding: Mapping[str, Any], tolerance: float) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    geometry = binding["geometry"]
    source_regions = {
        name: region for name, region in geometry.items() if "mkfluid" in region
    }
    if not source_regions:
        raise ValueError("physical binding contains no fluid source regions")
    destinations = {name: region for name, region in source_regions.items()}
    mechanism = binding["mechanism_id"]
    if mechanism == "finite_drop_pool":
        plane_x = float(_bounds(geometry["pool"])[1][0])
        contact_pairs = {"falling_drop": "pool"}
    elif mechanism == "oblique_finite_columns":
        left_high = _bounds(geometry["left_column"])[1]
        right_low = _bounds(geometry["right_column"])[0]
        plane_x = float((left_high[0] + right_low[0]) / 2.0)
        gap_low = np.array([left_high[0], max(_bounds(geometry["left_column"])[0][1], _bounds(geometry["right_column"])[0][1]), max(_bounds(geometry["left_column"])[0][2], _bounds(geometry["right_column"])[0][2])])
        gap_high = np.array([right_low[0], min(_bounds(geometry["left_column"])[1][1], _bounds(geometry["right_column"])[1][1]), min(_bounds(geometry["left_column"])[1][2], _bounds(geometry["right_column"])[1][2])])
        if np.all(gap_high > gap_low):
            destinations["inter_column_gap"] = {"low_m": gap_low.tolist(), "size_m": (gap_high - gap_low).tolist()}
        contact_pairs = {"left_column": "right_column", "right_column": "left_column"}
    else:
        raise ValueError(f"unsupported F4 mechanism for fixed operators: {mechanism}")
    return destinations, {"plane_x_m": plane_x, "contact_pairs": contact_pairs, "membership_tolerance_m": tolerance}


def _mk_to_source(binding: Mapping[str, Any], metadata: Mapping[str, Any]) -> tuple[dict[int, str], dict[str, int]]:
    mapping = metadata.get("typed_identity_binding", {}).get("fluid_mkfluid_to_native_mk", {})
    source_labels = binding["initial_state"]["source_labels"]
    mk_to_source: dict[int, str] = {}
    source_to_mk: dict[str, int] = {}
    for mkfluid, native_mk in mapping.items():
        label = source_labels.get(f"mkfluid:{int(mkfluid)}")
        if label is None:
            raise ValueError(f"no physical source label for mkfluid:{mkfluid}")
        mk_to_source[int(native_mk)] = str(label)
        source_to_mk[str(label)] = int(native_mk)
    if len(mk_to_source) < 2:
        raise ValueError("F4 observation requires all multiple fluid mk mappings")
    return mk_to_source, source_to_mk


def audit_observations(*, h5_path: Path, metadata_path: Path, operators_path: Path, output: Path, labels_output: Path | None = None, preview_output: Path | None = None, timeseries_output: Path | None = None, conversion_report_path: Path | None = None, particle_chunk: int = 65536) -> dict[str, Any]:
    started = time.monotonic()
    resource_before = _resource_snapshot()
    metadata = _load(metadata_path)
    binding = metadata.get("physical_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("F4 direct metadata lacks explicit physical_binding")
    _validate_physical_binding(binding)
    operators = _load(operators_path)
    if operators.get("schema") != "ds02.f4.observation-operators.v1":
        raise ValueError("unrecognized F4 operator registration")
    fixed_tolerance = float(operators["fixed_physical_tolerance_m"])
    resolution_diagnostic = max(3.0 * float(metadata["dp_m"]), fixed_tolerance)
    destinations, derived = _region_operators(binding, fixed_tolerance)
    mk_to_source, source_to_mk = _mk_to_source(binding, metadata)
    source_labels = sorted(source_to_mk)
    output = output.resolve()
    labels_output = (labels_output or output.with_name("source-regions.json")).resolve()
    preview_output = (preview_output or output.with_name("preview.json")).resolve()
    timeseries_output = (timeseries_output or output.with_name("macro-timeseries.csv")).resolve()
    for path in (output, labels_output, preview_output, timeseries_output):
        if path.exists():
            raise ValueError(f"refusing to overwrite observation artifact: {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    timeseries_output.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(h5_path, "r") as h5:
        frames = int(h5["time"].shape[0])
        particles = int(h5["particle_id"].shape[0])
        times = np.asarray(h5["time"][...], dtype=np.float64)
        if frames < 2 or np.any(~np.isfinite(times)) or np.any(np.diff(times) <= 0):
            raise ValueError("observation HDF5 lacks finite strictly increasing time")
        initial_type = np.asarray(h5["initial_type"][...], dtype=np.int8)
        initial_mk = np.asarray(h5["initial_mk"][...], dtype=np.int16)
        initial_mass = np.asarray(h5["initial_mass"][...], dtype=np.float64)
        fluid_axis = initial_type == 3
        observed_fluid_mks = sorted(set(initial_mk[fluid_axis].tolist()))
        if set(observed_fluid_mks) != set(mk_to_source):
            raise ValueError(f"metadata/XML fluid mks {sorted(mk_to_source)} disagree with HDF5 {observed_fluid_mks}")
        source_initial_native_mass = {
            label: float(initial_mass[fluid_axis & (initial_mk == native_mk)].sum())
            for label, native_mk in source_to_mk.items()
        }
        continuum_mass = {str(k): float(v) for k, v in binding["initial_state"]["continuum_mass_by_source_kg"].items()}
        native_mass_total = float(sum(source_initial_native_mass.values()))
        continuum_mass_total = float(sum(continuum_mass.values()))
        previous_x = np.full(particles, np.nan, dtype=np.float64)
        previous_plane_mass = {label: 0.0 for label in source_labels}
        residence_s = {label: 0.0 for label in source_labels}
        first_passage: dict[str, float | None] = {label: None for label in source_labels}
        crossing_positive = {label: 0 for label in source_labels}
        crossing_negative = {label: 0 for label in source_labels}
        contact_fixed = {label: [] for label in source_labels}
        contact_diag = {label: [] for label in source_labels}
        spread_series = {label: [] for label in source_labels}
        missing_by_frame: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        first_mid_final: dict[int, dict[str, Any]] = {}
        timeseries_output.parent.mkdir(parents=True, exist_ok=True)
        with timeseries_output.open("w", newline="", encoding="utf-8") as csv_handle:
            fieldnames = ["frame", "time_s", "active_mass_kg", "momentum_x_kg_m_s", "momentum_y_kg_m_s", "momentum_z_kg_m_s", "kinetic_energy_j"]
            for label in source_labels:
                fieldnames.extend([f"{label}_mass_kg", f"{label}_com_x_m", f"{label}_com_y_m", f"{label}_com_z_m", f"{label}_momentum_x_kg_m_s", f"{label}_momentum_y_kg_m_s", f"{label}_momentum_z_kg_m_s", f"{label}_kinetic_energy_j", f"{label}_spread_extent_m"])
                for destination in destinations:
                    fieldnames.append(f"{label}_to_{destination}_mass_kg")
            writer = csv.DictWriter(csv_handle, fieldnames=fieldnames)
            writer.writeheader()
            for frame in range(frames):
                stats = {
                    label: {"mass": 0.0, "pos_mass": np.zeros(3), "momentum": np.zeros(3), "energy": 0.0, "min": np.full(3, np.inf), "max": np.full(3, -np.inf), "dest": {name: 0.0 for name in destinations}}
                    for label in source_labels
                }
                active_mass_total = 0.0
                momentum_total = np.zeros(3)
                energy_total = 0.0
                current_plane_mass = {label: 0.0 for label in source_labels}
                frame_contact_fixed = {label: False for label in source_labels}
                frame_contact_diag = {label: False for label in source_labels}
                current_x = np.full(particles, np.nan, dtype=np.float64)
                valid_dataset = np.asarray(h5["valid"][frame], dtype=bool)
                missing_fluid = fluid_axis & ~valid_dataset
                if np.any(missing_fluid):
                    by_source = {
                        label: int(np.sum(missing_fluid & (initial_mk == native_mk)))
                        for label, native_mk in source_to_mk.items()
                        if np.any(missing_fluid & (initial_mk == native_mk))
                    }
                    missing_by_frame.append({
                        "frame": frame,
                        "time_s": float(times[frame]),
                        "fluid_particle_count": int(np.sum(missing_fluid)),
                        "by_source": by_source,
                        "unknown_native_mass_kg": float(initial_mass[missing_fluid].sum()),
                    })
                for start in range(0, particles, particle_chunk):
                    stop = min(start + particle_chunk, particles)
                    valid = np.asarray(valid_dataset[start:stop], dtype=bool)
                    types = np.asarray(h5["type"][frame, start:stop], dtype=np.int8)
                    positions = np.asarray(h5["position"][frame, start:stop], dtype=np.float64)
                    velocities = np.asarray(h5["velocity"][frame, start:stop], dtype=np.float64)
                    masses = np.asarray(h5["mass"][frame, start:stop], dtype=np.float64)
                    mks = initial_mk[start:stop]
                    active = valid & (types == 3) & fluid_axis[start:stop]
                    if np.any(active):
                        if any(np.any(~np.isfinite(arr[active])) for arr in (positions, velocities, masses)) or np.any(masses[active] <= 0):
                            raise ValueError(f"nonfinite/nonpositive active fluid at frame {frame}")
                    current_local_x = np.full(stop - start, np.nan, dtype=np.float64)
                    current_local_x[active] = positions[active, 0]
                    current_x[start:stop] = current_local_x
                    previous = previous_x[start:stop]
                    for native_mk, label in mk_to_source.items():
                        selected = active & (mks == native_mk)
                        if not np.any(selected):
                            continue
                        p = positions[selected]
                        v = velocities[selected]
                        m = masses[selected]
                        stats[label]["mass"] += float(m.sum())
                        stats[label]["pos_mass"] += (p * m[:, None]).sum(axis=0)
                        stats[label]["momentum"] += (v * m[:, None]).sum(axis=0)
                        stats[label]["energy"] += float(0.5 * np.sum(m * np.sum(v * v, axis=1)))
                        stats[label]["min"] = np.minimum(stats[label]["min"], p.min(axis=0))
                        stats[label]["max"] = np.maximum(stats[label]["max"], p.max(axis=0))
                        current_plane_mass[label] += float(m[positions[selected, 0] >= derived["plane_x_m"]].sum())
                        for destination, region in destinations.items():
                            low, high = _bounds(region)
                            stats[label]["dest"][destination] += float(m[_inside(p, low, high)].sum())
                        previous_selected = previous[selected]
                        current_selected = positions[selected, 0]
                        crossed = np.isfinite(previous_selected) & np.isfinite(current_selected) & ((previous_selected < derived["plane_x_m"]) != (current_selected < derived["plane_x_m"]))
                        if np.any(crossed):
                            positive = crossed & (previous_selected < derived["plane_x_m"]) & (current_selected >= derived["plane_x_m"])
                            negative = crossed & ~positive
                            crossing_positive[label] += int(np.sum(positive))
                            crossing_negative[label] += int(np.sum(negative))
                            if first_passage[label] is None:
                                first_passage[label] = float(times[frame])
                        fixed_pair = derived["contact_pairs"].get(label)
                        if fixed_pair is not None:
                            target_low, target_high = _bounds(binding["geometry"][fixed_pair])
                            frame_contact_fixed[label] = frame_contact_fixed[label] or bool(np.any(_inside(p, target_low, target_high, fixed_tolerance)))
                            frame_contact_diag[label] = frame_contact_diag[label] or bool(np.any(_inside(p, target_low, target_high, resolution_diagnostic)))
                    previous_x[start:stop] = current_x[start:stop]
                    active_mass_total += float(masses[active].sum())
                    momentum_total += (velocities[active] * masses[active, None]).sum(axis=0)
                    energy_total += float(0.5 * np.sum(masses[active] * np.sum(velocities[active] * velocities[active], axis=1)))
                if frame > 0:
                    dt = float(times[frame] - times[frame - 1])
                    for label in source_labels:
                        residence_s[label] += 0.5 * dt * (previous_plane_mass[label] + current_plane_mass[label])
                previous_plane_mass = current_plane_mass
                for label in source_labels:
                    contact_fixed[label].append(frame_contact_fixed[label])
                    contact_diag[label].append(frame_contact_diag[label])
                row: dict[str, Any] = {"frame": frame, "time_s": float(times[frame]), "active_mass_kg": active_mass_total, "momentum_x_kg_m_s": float(momentum_total[0]), "momentum_y_kg_m_s": float(momentum_total[1]), "momentum_z_kg_m_s": float(momentum_total[2]), "kinetic_energy_j": energy_total}
                for label in source_labels:
                    item = stats[label]
                    spread = float(np.max(item["max"] - item["min"])) if item["mass"] > 0 else math.nan
                    spread_series[label].append(spread)
                    com = item["pos_mass"] / item["mass"] if item["mass"] > 0 else np.full(3, math.nan)
                    row.update({f"{label}_mass_kg": item["mass"], f"{label}_com_x_m": float(com[0]), f"{label}_com_y_m": float(com[1]), f"{label}_com_z_m": float(com[2]), f"{label}_momentum_x_kg_m_s": float(item["momentum"][0]), f"{label}_momentum_y_kg_m_s": float(item["momentum"][1]), f"{label}_momentum_z_kg_m_s": float(item["momentum"][2]), f"{label}_kinetic_energy_j": item["energy"], f"{label}_spread_extent_m": spread})
                    for destination in destinations:
                        row[f"{label}_to_{destination}_mass_kg"] = item["dest"][destination]
                writer.writerow(row)
                rows.append(row)
                if frame in {0, frames // 2, frames - 1}:
                    first_mid_final[frame] = row.copy()
    times_array = times
    labels_evidence = {
        "schema": "ds02.f4.source-regions.v1",
        "h5": {"path": str(h5_path), "sha256": sha256_file(h5_path)},
        "metadata": {"path": str(metadata_path), "sha256": sha256_file(metadata_path)},
        "identity_key": "(Zone,Idp)",
        "fluid_initial_type": 3,
        "fluid_mk_to_source": {str(mk): label for mk, label in mk_to_source.items()},
        "source_to_native_mk": source_to_mk,
        "observed_fluid_mks": sorted(mk_to_source),
        "continuum_source_regions": binding["initial_state"]["source_regions"],
        "physical_binding_sha256": canonical_hash(binding),
        "status": "actual typed source/mk region mapping; no qualification claim",
    }
    labels_output.write_text(json.dumps(labels_evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    event_summary = {}
    for label in source_labels:
        event_summary[label] = {
            "fixed_physical_operator": _event_summary(times_array, contact_fixed[label], spread_series[label]),
            "resolution_dependent_diagnostic_operator": {
                "threshold_m": resolution_diagnostic,
                **_event_summary(times_array, contact_diag[label], spread_series[label]),
            },
            "plane_transport": {
                "plane_x_m": derived["plane_x_m"],
                "first_passage": {"status": "observed", "time_s": first_passage[label]} if first_passage[label] is not None else {"status": "right_censored", "time_s": None},
                "positive_crossings": crossing_positive[label],
                "negative_crossings": crossing_negative[label],
                "signed_net_crossings": crossing_positive[label] - crossing_negative[label],
                "residence_s": residence_s[label],
            },
        }
    native_mass_by_source = source_initial_native_mass
    init_error = {label: native_mass_by_source[label] - continuum_mass.get(label, math.nan) for label in source_labels}
    conversion_provenance = None
    if conversion_report_path is not None:
        conversion_provenance = {"path": str(conversion_report_path), "sha256": sha256_file(conversion_report_path)}
    report = {
        "schema": SCHEMA,
        "observation_status": "completed_actual_hdf5_stream",
        "claim_boundary": "reference macro/transport evidence only; Q-I/Q-N/production not granted",
        "input": {"h5": {"path": str(h5_path), "sha256": sha256_file(h5_path)}, "metadata": {"path": str(metadata_path), "sha256": sha256_file(metadata_path)}, "operators": {"path": str(operators_path), "sha256": sha256_file(operators_path)}, "direct_conversion_report": conversion_provenance},
        "shape": {"frames": frames, "particles": particles, "first_time_s": float(times[0]), "last_time_s": float(times[-1]), "strictly_increasing": True},
        "physical_binding_sha256": canonical_hash(binding),
        "operators": {"fixed_physical_tolerance_m": fixed_tolerance, "resolution_dependent_threshold_m": resolution_diagnostic, "derived": derived, "macro_error_budget_fraction": operators["macro_error_budget_fraction"], "feature_time_error_budget_fraction": operators["feature_time_error_budget_fraction"]},
        "typed_identity": {"fluid_mk_to_source": {str(mk): label for mk, label in mk_to_source.items()}, "observed_fluid_mks": sorted(mk_to_source), "all_source_mks_preserved": True},
        "mass_ledger": {"continuum_mass_by_source_kg": continuum_mass, "continuum_total_kg": continuum_mass_total, "native_initial_mass_by_source_kg": native_mass_by_source, "native_initial_total_kg": native_mass_total, "initialization_error_by_source_kg": init_error, "initialization_error_total_kg": native_mass_total - continuum_mass_total, "mass_normalization": "none", "first_frame_active_mass_kg": rows[0]["active_mass_kg"], "last_frame_active_mass_kg": rows[-1]["active_mass_kg"]},
        "lifecycle_missing": {
            "frames_with_missing_fluid": len(missing_by_frame),
            "first_missing_by_source": {
                label: next((item for item in missing_by_frame if label in item["by_source"]), None)
                for label in source_labels
            },
            "max_unknown_native_mass_kg": max((item["unknown_native_mass_kg"] for item in missing_by_frame), default=0.0),
            "missing_semantics": "native solver output omission; source identity is retained but position, velocity, density, and destination are unknown; no spill/redistribution is inferred",
            "frame_records": missing_by_frame,
        },
        "com_momentum_energy": {"quantity_units": {"com": "m", "momentum": "kg*m/s", "kinetic_energy": "J", "mass": "kg"}, "preview_rows": list(first_mid_final.values())},
        "events_and_transport": event_summary,
        "source_regions_output": str(labels_output),
        "timeseries_csv": {"path": str(timeseries_output), "sha256": sha256_file(timeseries_output), "rows": len(rows)},
        "preview": {"path": str(preview_output), "frames": sorted(first_mid_final)},
        "resource": {"wall_seconds": time.monotonic() - started, "usage": _usage_delta(resource_before, _resource_snapshot())},
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    preview_output.write_text(json.dumps({"schema": "ds02.f4.preview.v1", "source_report": str(output), "actual_frames": first_mid_final}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--h5", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--operators", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--timeseries", type=Path)
    parser.add_argument("--conversion-report", type=Path)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_observations(h5_path=args.h5, metadata_path=args.metadata, operators_path=args.operators, output=args.output, labels_output=args.labels, preview_output=args.preview, timeseries_output=args.timeseries, conversion_report_path=args.conversion_report, particle_chunk=args.particle_chunk)
    print(json.dumps({"output": str(args.output), "frames": report["shape"]["frames"], "particles": report["shape"]["particles"], "physical_binding_sha256": report["physical_binding_sha256"], "q_n_status": report["q_n_status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
