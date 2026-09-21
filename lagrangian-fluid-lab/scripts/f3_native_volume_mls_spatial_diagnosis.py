"""Diagnose F3 native-volume MLS spatial-scope differences.

This is a read-only, diagnostic postprocess for already completed 512-seed
traces.  It identifies the time windows in which the prospective F3 material
first-passage CDF bound exceeds 0.02, attributes the discrepancy to paired
geometric seeds, and reads the corresponding native CFD fields to report
macro-field and support proxies.  The native field metrics are evidence about
the reference trajectory and the reconstruction input; they do not establish
continuous material reliability or T2 qualification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "core.material.f3.native_volume_mls.spatial_diagnosis.v1"
CDF_GATE = 0.02
F3_WALL_LOW = np.asarray([-0.45, -0.09, 0.0], dtype=np.float64)
F3_WALL_HIGH = np.asarray([0.45, 0.09, 0.51], dtype=np.float64)
F3_COEFH = 0.91924
WINDOW_MERGE_GAP_S = 0.0


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _attr_json(handle, name: str, default=None):
    value = handle.attrs.get(name, default)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _trace(path: str | Path) -> dict:
    path = Path(path).resolve()
    with h5py.File(path, "r") as handle:
        schema = str(handle.attrs.get("schema", ""))
        if not schema.startswith("core.material.f3.native_volume_mls.trace."):
            raise ValueError(f"not an F3 native MLS trace: {path}")
        committed = int(handle.attrs.get("committed", -1))
        if committed < 1:
            raise ValueError(f"trace has no complete interval: {path}")
        result = {
            "path": str(path),
            "sha256": sha256_file(path),
            "schema": schema,
            "binding": _attr_json(handle, "binding", {}) or {},
            "time": np.asarray(handle["time"][:committed + 1], dtype=np.float64),
            "initial_position": np.asarray(handle["initial_position"][:], dtype=np.float64),
            "source_label": np.asarray(handle["source_label"][:], dtype=np.int8),
            "position": np.asarray(handle["position"][:committed + 1], dtype=np.float64),
            "reliable": np.asarray(handle["reliable"][:committed + 1], dtype=bool),
            "permanent_unknown": np.asarray(handle["permanent_unknown"][:committed + 1], dtype=bool),
            "first_passage": np.asarray(handle["first_passage"][committed], dtype=np.float64),
            "failure_reason": np.asarray(handle["failure_reason"][committed]).astype(str),
            "support_count": np.asarray(handle["support_count"][:committed + 1], dtype=np.int64),
            "effective_sample_size": np.asarray(handle["effective_sample_size"][:committed + 1], dtype=np.float64),
            "geometry_rank": np.asarray(handle["geometry_rank"][:committed + 1], dtype=np.int8),
            "condition_number": np.asarray(handle["condition_number"][:committed + 1], dtype=np.float64),
            "anisotropy": np.asarray(handle["anisotropy"][:committed + 1], dtype=np.float64),
            "reconstruction_error_mps": np.asarray(handle["reconstruction_error_mps"][:committed + 1], dtype=np.float64),
            "old_gate_pass": np.asarray(handle["old_gate_pass"][:committed + 1], dtype=bool),
            "candidate_support_pass": np.asarray(handle["candidate_support_pass"][:committed + 1], dtype=bool),
            "candidate_count": np.asarray(handle["candidate_count"][:committed + 1], dtype=np.int64),
            "wall_rejected_count": np.asarray(handle["wall_rejected_count"][:committed + 1], dtype=np.int64),
        }
    if len(result["source_label"]) != 512:
        raise ValueError("spatial diagnosis requires the registered 512-seed axis")
    if result["initial_position"].shape != (512, 3):
        raise ValueError("invalid initial seed positions")
    if not np.isfinite(result["time"]).all() or np.any(np.diff(result["time"]) <= 0.0):
        raise ValueError("invalid trace time axis")
    return result


def _first_failure(trace: dict) -> np.ndarray:
    unknown = trace["permanent_unknown"]
    result = np.full(unknown.shape[1], -1, dtype=np.int64)
    for seed in range(unknown.shape[1]):
        indices = np.flatnonzero(unknown[:, seed])
        if len(indices):
            result[seed] = int(indices[0])
    return result


def _possible_unknown_time(trace: dict) -> np.ndarray:
    first = _first_failure(trace)
    result = np.full(len(first), np.nan, dtype=np.float64)
    for seed, frame in enumerate(first):
        if frame >= 0:
            result[seed] = trace["time"][max(0, int(frame) - 1)]
    return result


def _event_bounds(trace: dict, source: int, value: float) -> tuple[float, float]:
    select = trace["source_label"] == source
    event = trace["first_passage"]
    denominator = float(np.count_nonzero(select))
    lower = float(np.count_nonzero(select & np.isfinite(event) & (event <= value)) / denominator)
    possible = _possible_unknown_time(trace)
    unresolved = select & trace["permanent_unknown"][-1] & ~np.isfinite(event)
    upper = lower + float(np.count_nonzero(unresolved & (possible <= value)) / denominator)
    return lower, upper


def _difference_windows(left: dict, right: dict, source: int) -> list[dict]:
    values: set[float] = {0.0, float(left["time"][-1]), float(right["time"][-1])}
    for trace in (left, right):
        select = trace["source_label"] == source
        event = trace["first_passage"][select]
        values.update(float(value) for value in event[np.isfinite(event)])
        possible = _possible_unknown_time(trace)[select]
        values.update(float(value) for value in possible[np.isfinite(possible)])
    grid = np.asarray(sorted(values), dtype=np.float64)
    rows = []
    for index, value in enumerate(grid):
        left_lower, left_upper = _event_bounds(left, source, float(value))
        right_lower, right_upper = _event_bounds(right, source, float(value))
        lower = right_lower - left_upper
        upper = right_upper - left_lower
        rows.append({
            "time_s": float(value),
            "lower_difference_right_minus_left": float(lower),
            "upper_difference_right_minus_left": float(upper),
            "sup_abs_difference_bound": float(max(abs(lower), abs(upper))),
            "next_time_s": float(grid[index + 1]) if index + 1 < len(grid) else float(value),
            "left_lower": float(left_lower), "left_upper": float(left_upper),
            "right_lower": float(right_lower), "right_upper": float(right_upper),
        })
    windows = []
    start = None
    end = None
    rows_in = []
    for row in rows:
        if row["sup_abs_difference_bound"] > CDF_GATE:
            if start is None:
                start = row["time_s"]
                rows_in = []
            end = row["next_time_s"]
            rows_in.append(row)
        elif start is not None:
            windows.append(_finish_window(start, end, rows_in))
            start = end = None
            rows_in = []
    if start is not None:
        windows.append(_finish_window(start, end, rows_in))
    return windows


def _finish_window(start: float, end: float, rows: list[dict]) -> dict:
    peak = max(rows, key=lambda row: row["sup_abs_difference_bound"])
    return {
        "start_s": float(start),
        "end_s": float(end),
        "duration_s": float(max(0.0, end - start)),
        "peak_time_s": peak["time_s"],
        "peak": peak,
    }


def _seed_contributions(left: dict, right: dict, source: int, value: float) -> dict:
    select = left["source_label"] == source
    event_left, event_right = left["first_passage"], right["first_passage"]
    observed_left = select & np.isfinite(event_left) & (event_left <= value)
    observed_right = select & np.isfinite(event_right) & (event_right <= value)
    right_earlier = np.flatnonzero(observed_right & ~observed_left)
    left_earlier = np.flatnonzero(observed_left & ~observed_right)
    unknown_left = np.flatnonzero(select & left["permanent_unknown"][-1] & ~np.isfinite(event_left))
    unknown_right = np.flatnonzero(select & right["permanent_unknown"][-1] & ~np.isfinite(event_right))
    possible_left = _possible_unknown_time(left)
    possible_right = _possible_unknown_time(right)
    unknown_left_eligible = unknown_left[possible_left[unknown_left] <= value]
    unknown_right_eligible = unknown_right[possible_right[unknown_right] <= value]
    return {
        "right_earlier_seed_ids": right_earlier.astype(int).tolist(),
        "left_earlier_seed_ids": left_earlier.astype(int).tolist(),
        "right_unresolved_seed_ids": unknown_right.astype(int).tolist(),
        "left_unresolved_seed_ids": unknown_left.astype(int).tolist(),
        "right_earlier_count": int(len(right_earlier)),
        "left_earlier_count": int(len(left_earlier)),
        "right_unresolved_count": int(len(unknown_right)),
        "left_unresolved_count": int(len(unknown_left)),
        "right_unresolved_eligible_at_peak_seed_ids": unknown_right_eligible.astype(int).tolist(),
        "left_unresolved_eligible_at_peak_seed_ids": unknown_left_eligible.astype(int).tolist(),
        "right_unresolved_eligible_at_peak_count": int(len(unknown_right_eligible)),
        "left_unresolved_eligible_at_peak_count": int(len(unknown_left_eligible)),
    }


def _bbox(points: np.ndarray) -> dict | None:
    if len(points) == 0:
        return None
    return {"min_m": np.min(points, axis=0).tolist(), "max_m": np.max(points, axis=0).tolist()}


def _wall_distance(points: np.ndarray) -> np.ndarray:
    distances = np.column_stack((points - F3_WALL_LOW[None, :], F3_WALL_HIGH[None, :] - points))
    return np.min(distances, axis=1)


def _summary_stats(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if not len(finite):
        return {"count": 0, "min": None, "p05": None, "median": None, "p95": None, "max": None, "mean": None}
    q = np.quantile(finite, [0.05, 0.5, 0.95])
    return {
        "count": int(len(finite)), "min": float(np.min(finite)), "p05": float(q[0]),
        "median": float(q[1]), "p95": float(q[2]), "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
    }


def _trace_support_summary(trace: dict, source: int, frame_indices: np.ndarray,
                           seed_ids: np.ndarray | None = None) -> dict:
    if seed_ids is None:
        seed_ids = np.flatnonzero(trace["source_label"] == source)
    frame_indices = np.unique(np.asarray(frame_indices, dtype=np.int64))
    frame_indices = frame_indices[(frame_indices >= 0) & (frame_indices < len(trace["time"]))]
    if len(frame_indices) == 0 or len(seed_ids) == 0:
        return {"frame_count": int(len(frame_indices)), "seed_count": int(len(seed_ids))}
    sl = np.ix_(frame_indices, seed_ids)
    support = trace["support_count"][sl]
    candidate = trace["candidate_count"][sl]
    rejected = trace["wall_rejected_count"][sl]
    ess = trace["effective_sample_size"][sl]
    rank = trace["geometry_rank"][sl]
    condition = trace["condition_number"][sl]
    anisotropy = trace["anisotropy"][sl]
    residual = trace["reconstruction_error_mps"][sl]
    old_pass = trace["old_gate_pass"][sl]
    candidate_pass = trace["candidate_support_pass"][sl]
    query_position = trace["position"][sl]
    wall_distance = _wall_distance(query_position.reshape(-1, 3))
    h = float(trace["binding"].get("static_backend", {}).get("h_m", np.nan))
    support_radius = 2.0 * h if np.isfinite(h) else np.nan
    # Candidate count is a local particle-volume proxy for free-surface support;
    # it is deliberately labeled a proxy rather than a free-surface truth field.
    result = {
        "frame_count": int(len(frame_indices)),
        "seed_count": int(len(seed_ids)),
        "time_start_s": float(trace["time"][frame_indices[0]]),
        "time_end_s": float(trace["time"][frame_indices[-1]]),
        "support_count": _summary_stats(support),
        "candidate_count_free_surface_proxy": _summary_stats(candidate),
        "effective_sample_size": _summary_stats(ess),
        "geometry_rank": _summary_stats(rank),
        "condition_number": _summary_stats(condition),
        "anisotropy": _summary_stats(anisotropy),
        "reconstruction_error_mps": _summary_stats(residual),
        "wall_rejected_count": _summary_stats(rejected),
        "query_wall_distance_m": _summary_stats(wall_distance),
        "near_wall_fraction_query_distance_le_2h": (
            float(np.mean(wall_distance <= support_radius)) if np.isfinite(support_radius) else None
        ),
        "wall_visibility_rejection_fraction": float(np.mean(rejected > 0)),
        "low_ess_fraction": float(np.mean(ess < 4.0)),
        "rank_deficient_fraction": float(np.mean(rank < 4)),
        "old_gate_fail_fraction": float(np.mean(~old_pass)),
        "candidate_support_fail_fraction": float(np.mean(~candidate_pass)),
        "support_radius_m": support_radius if np.isfinite(support_radius) else None,
    }
    return result


def _nearest_frame(times: np.ndarray, value: float) -> int:
    return int(np.argmin(np.abs(times - float(value))))


def _native_macro(handle, frame: int, *, support_radius_m: float | None = None) -> dict:
    position = np.asarray(handle["position"][frame], dtype=np.float64)
    velocity = np.asarray(handle["velocity"][frame], dtype=np.float64)
    mass = np.asarray(handle["mass"][frame], dtype=np.float64)
    density = np.asarray(handle["density"][frame], dtype=np.float64)
    pressure = np.asarray(handle["pressure"][frame], dtype=np.float64)
    valid = np.asarray(handle["valid"][frame], dtype=bool)
    particle_type = np.asarray(handle["type"][frame])
    selected = valid & (particle_type == 3)
    selected &= np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
    selected &= np.isfinite(mass) & (mass > 0.0) & np.isfinite(density) & (density > 0.0)
    selected &= np.isfinite(pressure)
    if not np.any(selected):
        raise ValueError("reference frame has no finite fluid rows")
    p, v, m, rho, pres = (array[selected] for array in (position, velocity, mass, density, pressure))
    total_mass = float(np.sum(m))
    weights = m / total_mass
    speed2 = np.einsum("ij,ij->i", v, v)
    wall_distance = _wall_distance(p)
    density_q = np.quantile(rho, [0.05, 0.5, 0.95])
    velocity_mean = np.sum(v * weights[:, None], axis=0)
    density_median = float(density_q[1])
    return {
        "frame": int(frame), "particle_count": int(len(p)), "total_mass_kg": total_mass,
        "center_of_mass_m": np.sum(p * weights[:, None], axis=0).tolist(),
        "mean_velocity_mps": velocity_mean.tolist(),
        "velocity_rms_mps": float(np.sqrt(np.sum(weights * speed2))),
        "kinetic_energy_j": float(0.5 * np.sum(m * speed2)),
        "density_kgpm3": {"mass_weighted_mean": float(np.sum(weights * rho)),
                           "p05": float(density_q[0]), "median": density_median,
                           "p95": float(density_q[2]),
                           "coefficient_of_variation": float(np.std(rho) / max(np.mean(rho), 1.0e-12))},
        "pressure_pa": {"mass_weighted_mean": float(np.sum(weights * pres)),
                        "p05": float(np.quantile(pres, 0.05)),
                        "median": float(np.quantile(pres, 0.5)),
                        "p95": float(np.quantile(pres, 0.95))},
        "wall_distance_m": _summary_stats(wall_distance),
        "particle_fraction_within_2h": (
            float(np.mean(wall_distance <= support_radius_m))
            if support_radius_m is not None and np.isfinite(support_radius_m) else None
        ),
        "particle_fraction_low_density_proxy_below_0p95_median": float(np.mean(rho < 0.95 * density_median)),
        "particle_fraction_low_density_proxy_below_0p99_median": float(np.mean(rho < 0.99 * density_median)),
    }


def _macro_delta(left: dict, right: dict) -> dict:
    def delta(a, b):
        a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
        scale = np.maximum(np.maximum(np.abs(a), np.abs(b)), 1.0e-12)
        return {"left": a.tolist(), "right": b.tolist(), "right_minus_left": (b - a).tolist(),
                "relative_abs_max": float(np.max(np.abs(b - a) / scale))}
    return {
        "total_mass_kg": delta(left["total_mass_kg"], right["total_mass_kg"]),
        "center_of_mass_m": delta(left["center_of_mass_m"], right["center_of_mass_m"]),
        "mean_velocity_mps": delta(left["mean_velocity_mps"], right["mean_velocity_mps"]),
        "velocity_rms_mps": delta(left["velocity_rms_mps"], right["velocity_rms_mps"]),
        "kinetic_energy_j": delta(left["kinetic_energy_j"], right["kinetic_energy_j"]),
        "density_mass_weighted_mean": delta(left["density_kgpm3"]["mass_weighted_mean"], right["density_kgpm3"]["mass_weighted_mean"]),
        "density_coefficient_of_variation": delta(left["density_kgpm3"]["coefficient_of_variation"], right["density_kgpm3"]["coefficient_of_variation"]),
        "pressure_mass_weighted_mean": delta(left["pressure_pa"]["mass_weighted_mean"], right["pressure_pa"]["mass_weighted_mean"]),
        "wall_distance_median": delta(left["wall_distance_m"]["median"], right["wall_distance_m"]["median"]),
        "low_density_proxy_fraction": delta(left["particle_fraction_low_density_proxy_below_0p95_median"], right["particle_fraction_low_density_proxy_below_0p95_median"]),
        "low_density_proxy_fraction_0p99": delta(left["particle_fraction_low_density_proxy_below_0p99_median"], right["particle_fraction_low_density_proxy_below_0p99_median"]),
    }


def _reference_window(left: dict, right: dict, window: dict, source: int) -> dict:
    left_ref = left["reference"]
    right_ref = right["reference"]
    peak = float(window["peak_time_s"])
    left_frame = _nearest_frame(left_ref["times"], peak)
    right_frame = _nearest_frame(right_ref["times"], peak)
    left_h = float(left["binding"].get("static_backend", {}).get("h_m", np.nan))
    right_h = float(right["binding"].get("static_backend", {}).get("h_m", np.nan))
    left_macro = _native_macro(left_ref["handle"], left_frame,
                               support_radius_m=2.0 * left_h if np.isfinite(left_h) else None)
    right_macro = _native_macro(right_ref["handle"], right_frame,
                                support_radius_m=2.0 * right_h if np.isfinite(right_h) else None)
    # The source rows are global fluid fields; this frame-local support summary
    # is the source-specific tracer query footprint at the same physical time.
    left_trace_frame = _nearest_frame(left["time"], peak)
    right_trace_frame = _nearest_frame(right["time"], peak)
    source_seed_ids_left = np.flatnonzero(left["source_label"] == source)
    source_seed_ids_right = np.flatnonzero(right["source_label"] == source)
    return {
        "peak_time_s": peak,
        "left_reference_frame": int(left_frame),
        "right_reference_frame": int(right_frame),
        "left_reference_time_s": float(left_ref["times"][left_frame]),
        "right_reference_time_s": float(right_ref["times"][right_frame]),
        "reference_macro_left": left_macro,
        "reference_macro_right": right_macro,
        "reference_macro_delta_right_minus_left": _macro_delta(left_macro, right_macro),
        "left_trace_support_at_peak": _trace_support_summary(left, source, np.asarray([left_trace_frame]), source_seed_ids_left),
        "right_trace_support_at_peak": _trace_support_summary(right, source, np.asarray([right_trace_frame]), source_seed_ids_right),
    }


def _reference_open(trace: dict) -> dict:
    path = Path(trace["binding"].get("source_h5", "")).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"reference source missing: {path}")
    handle = h5py.File(path, "r")
    times = np.asarray(handle["time"][:], dtype=np.float64)
    declared = trace["binding"].get("source_sha256")
    return {"path": str(path), "sha256": declared, "handle": handle, "times": times}


def _close_reference(trace: dict) -> None:
    trace.get("reference", {}).get("handle").close()


def _augment_windows(left: dict, right: dict, source: int, windows: list[dict]) -> list[dict]:
    result = []
    for window in windows:
        contribution = _seed_contributions(left, right, source, window["peak_time_s"])
        right_ids = np.asarray(contribution["right_earlier_seed_ids"], dtype=np.int64)
        left_ids = np.asarray(contribution["left_earlier_seed_ids"], dtype=np.int64)
        contribution["right_earlier_initial_position_bbox_m"] = _bbox(right["initial_position"][right_ids])
        contribution["left_earlier_initial_position_bbox_m"] = _bbox(left["initial_position"][left_ids])
        window = dict(window)
        window["seed_contribution_at_peak"] = contribution
        window["reference_and_support_at_peak"] = _reference_window(left, right, window, source)
        contributing = np.unique(np.asarray(
            contribution["right_earlier_seed_ids"] + contribution["left_earlier_seed_ids"],
            dtype=np.int64,
        ))
        peak_left = _nearest_frame(left["time"], window["peak_time_s"])
        peak_right = _nearest_frame(right["time"], window["peak_time_s"])
        window["reference_and_support_at_peak"]["left_trace_support_contributing_seeds"] = _trace_support_summary(
            left, source, np.asarray([peak_left]), contributing,
        )
        window["reference_and_support_at_peak"]["right_trace_support_contributing_seeds"] = _trace_support_summary(
            right, source, np.asarray([peak_right]), contributing,
        )
        result.append(window)
    return result


def _first_failure_rows(trace: dict) -> dict:
    first = _first_failure(trace)
    rows = []
    for source in (0, 1):
        select = (trace["source_label"] == source) & (first >= 0)
        ids = np.flatnonzero(select)
        reasons = {}
        for seed in ids:
            frame = int(first[seed])
            reason = str(trace["failure_reason"][seed])
            reasons.setdefault(reason, []).append(int(seed))
        by_reason = {}
        for reason, seed_ids in reasons.items():
            frames = first[np.asarray(seed_ids, dtype=np.int64)]
            by_reason[reason] = {
                "seed_ids": seed_ids,
                "count": int(len(seed_ids)),
                "first_time_s": float(np.min(trace["time"][frames])),
                "last_time_s": float(np.max(trace["time"][frames])),
                "support_at_first_failure": _trace_support_summary(trace, source, np.unique(frames), np.asarray(seed_ids, dtype=np.int64)),
            }
        rows.append({"source": source, "unknown_count": int(len(ids)), "by_reason": by_reason})
    return {"by_source": rows}


def diagnose_pair(left_path: str | Path, right_path: str | Path,
                  left_name: str, right_name: str) -> dict:
    left, right = _trace(left_path), _trace(right_path)
    if left["binding"].get("source_definition") != right["binding"].get("source_definition"):
        raise ValueError("source definitions differ")
    if left["binding"].get("event_definition") != right["binding"].get("event_definition"):
        raise ValueError("event definitions differ")
    if not np.array_equal(left["initial_position"], right["initial_position"]):
        raise ValueError("spatial diagnosis requires exact paired initial positions")
    if not np.array_equal(left["source_label"], right["source_label"]):
        raise ValueError("spatial diagnosis requires exact paired source labels")
    left["reference"] = _reference_open(left)
    right["reference"] = _reference_open(right)
    try:
        by_source = {}
        for source in (0, 1):
            windows = _difference_windows(left, right, source)
            by_source[str(source)] = {
                "cdf_gate": CDF_GATE,
                "exceedance_window_count": int(len(windows)),
                "exceedance_windows": _augment_windows(left, right, source, windows),
            }
        return {
            "left": {"name": left_name, "path": left["path"], "sha256": left["sha256"],
                     "source_h5": left["reference"]["path"], "source_sha256": left["reference"]["sha256"],
                     "time_end_s": float(left["time"][-1])},
            "right": {"name": right_name, "path": right["path"], "sha256": right["sha256"],
                      "source_h5": right["reference"]["path"], "source_sha256": right["reference"]["sha256"],
                      "time_end_s": float(right["time"][-1])},
            "comparison_policy": {
                "seed_axis": "same deterministic 512-seed initial positions, paired by seed index",
                "cdf_threshold": CDF_GATE,
                "cdf_bound": "right_lower-left_upper and right_upper-left_lower, including unresolved unknown mass",
                "reference_field": "native current-frame CFD position/velocity/mass/density/pressure; no future frame or interpolation claim",
                "free_surface": "candidate_count and low-density fractions are support proxies, not a free-surface label",
                "qualification_claim": "none",
            },
            "first_failure": {
                "left": _first_failure_rows(left),
                "right": _first_failure_rows(right),
            },
            "by_source": by_source,
            "interpretation": {
                "reference_vs_reconstruction": "native macro-field deltas indicate SPH reference-scope differences; paired tracer support/reconstruction deltas at the same windows indicate the MLS/frozen-frame contribution. This evidence cannot isolate the two components when both change with resolution.",
                "reference_numerical_dissipation_candidate": "The separately audited F3 generated XML semantics report records ViscoTreatment=1 and Visco=.05 across the registered assets, with h changing by resolution. Resolution-dependent artificial dissipation is therefore a registered candidate for long-time reference transport divergence; this diagnosis does not attribute the observed CDF differences to it, and it remains separate from native cadence/time-hold, MLS support, and quadrature effects.",
                "near_wall": "wall_rejected_count and query wall distance diagnose finite-wall visibility; wall_occluded is a reconstruction support failure, not proof of a physical wall event.",
                "free_surface": "candidate_count, ESS, rank, anisotropy and density proxies diagnose sparse/interface support; they do not establish material reliability.",
            },
        }
    finally:
        _close_reference(left)
        _close_reference(right)


def _parse_pair(value: str) -> tuple[str, str, str]:
    parts = value.split("=", 2)
    if len(parts) != 3 or not all(parts):
        raise ValueError("--pair must be NAME=LEFT_TRACE=RIGHT_TRACE")
    return parts[0], parts[1], parts[2]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", required=True,
                        help="NAME=LEFT_TRACE=RIGHT_TRACE; repeat for each spatial pair")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    pairs = []
    for value in args.pair:
        name, left, right = _parse_pair(value)
        pairs.append({"comparison_id": name, "diagnosis": diagnose_pair(left, right, name + ":left", name + ":right")})
    result = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "implementation": {"script": str(Path(__file__).resolve()), "script_sha256": sha256_file(__file__)},
        "status": "diagnostic_only",
        "pairs": pairs,
        "thresholds": {"first_passage_cdf_bound_difference": CDF_GATE,
                       "unknown_gate_context": "1% per source remains a separate fixed gate"},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_value(result), indent=2, sort_keys=True) + "\n")
    compact = {
        "schema": SCHEMA,
        "pairs": [{"comparison_id": pair["comparison_id"],
                   "source_windows": {source: pair["diagnosis"]["by_source"][source]["exceedance_window_count"] for source in ("0", "1")}}
                  for pair in pairs],
        "output": str(args.output.resolve()),
    }
    print(json.dumps(compact, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
