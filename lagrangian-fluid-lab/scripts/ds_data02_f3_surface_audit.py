#!/usr/bin/env python3
"""Audit the frozen F3 weak trajectory against its in-domain surfaces.

The first weak dual-axis audit used the physical top opening as its only
surface.  That is a legal open-exit diagnostic, but it is not the dual-axis
exchange operator frozen for F3.  This read-only module replays the saved
HDF5 intervals on the frozen finite surfaces ``x=0`` and ``y=0`` and reports
the top opening separately.  It does not move a plane, alter an HDF5 file, or
turn an observed crossing into a qualification claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import resource
import time
from typing import Any, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds02.f3.finite-surface-audit.v1"
REQUIRED_DATASETS = (
    "time", "particle_id", "particle_zone", "initial_type", "initial_mk",
    "initial_mass", "valid", "position", "mass",
)
SURFACES = ("left_right_exchange", "front_back_exchange", "top_open_exit")


class SurfaceAuditError(RuntimeError):
    """Raised when the saved source does not satisfy the audit contract."""


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _ref(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "bytes": int(path.stat().st_size) if path.is_file() else None,
    }


def _sha256_file(path: Path, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SurfaceAuditError(f"cannot read JSON source: {path}") from exc


def _usage() -> dict[str, float]:
    values: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        current = resource.getrusage(who)
        values[f"{label}_user_seconds"] = float(current.ru_utime)
        values[f"{label}_system_seconds"] = float(current.ru_stime)
        values[f"{label}_max_rss_kib"] = float(current.ru_maxrss)
    return values


def _usage_delta(before: Mapping[str, float], after: Mapping[str, float]) -> dict[str, float]:
    return {key: float(after[key] - before.get(key, 0.0)) for key in after}


def _as_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SurfaceAuditError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise SurfaceAuditError(f"{label} is not finite: {value!r}")
    return result


def _validate_sources(
    *,
    h5_path: Path,
    operators_path: Path,
    event_definitions_path: Path,
    owner_metadata_path: Path,
    expected_h5_sha256: str | None,
) -> dict[str, Any]:
    operators = _load_json(operators_path)
    if operators.get("schema") != "ds02.f3.weak-dual-operators.v1":
        raise SurfaceAuditError("unexpected weak operator schema")
    event_definitions = _load_json(event_definitions_path)
    if event_definitions.get("schema") != "ds-data-02.f3.event_definitions.v1":
        raise SurfaceAuditError("unexpected F3 event-definition schema")
    owner = _load_json(owner_metadata_path)
    if owner.get("physical_case_id") != "F3_DUAL_AXIS_WEAK_006G_004G":
        raise SurfaceAuditError("surface audit is bound to the weak dual-axis physical case")
    binding = owner.get("physical_binding", {})
    if binding.get("schema") != "ds-data-02.physical-binding.v1":
        raise SurfaceAuditError("owner metadata lacks physical-binding.v1")
    if not h5_path.is_file():
        raise SurfaceAuditError(f"HDF5 source does not exist: {h5_path}")

    finite_surfaces = {
        item.get("event_id"): item
        for item in event_definitions.get("finite_surfaces", [])
        if isinstance(item, dict)
    }
    required = {"left_right_exchange", "front_back_exchange", "top_open_exit"}
    if not required.issubset(finite_surfaces):
        raise SurfaceAuditError(f"event definitions lack frozen surfaces: {sorted(required - set(finite_surfaces))}")
    for event_id in required:
        if "surface" not in finite_surfaces[event_id] or "normal_in_tank_frame" not in finite_surfaces[event_id]:
            raise SurfaceAuditError(f"event definition is incomplete: {event_id}")

    tank = binding.get("geometry", {}).get("tank", {})
    low = tank.get("low_m")
    size = tank.get("size_m")
    if not isinstance(low, list) or not isinstance(size, list) or len(low) != 3 or len(size) != 3:
        raise SurfaceAuditError("owner metadata lacks a 3-D continuous tank geometry")
    low = [_as_float(value, "tank.low_m") for value in low]
    size = [_as_float(value, "tank.size_m") for value in size]
    high = [low[i] + size[i] for i in range(3)]
    top_open = bool(binding.get("geometry", {}).get("top_open"))
    top_open = top_open or "top" in binding.get("open_inlet", {}).get("faces", [])
    if not top_open:
        raise SurfaceAuditError("weak owner metadata does not declare a physically open top")
    if not math.isclose(low[0], -0.45) or not math.isclose(high[0], 0.45):
        raise SurfaceAuditError("weak tank x bounds do not match the frozen event scope")
    if not math.isclose(low[1], -0.09) or not math.isclose(high[1], 0.09):
        raise SurfaceAuditError("weak tank y bounds do not match the frozen event scope")
    if not math.isclose(low[2], 0.0) or not math.isclose(high[2], 0.51):
        raise SurfaceAuditError("weak tank z bounds do not match the frozen event scope")

    return {
        "operators": _ref(operators_path),
        "event_definitions": _ref(event_definitions_path),
        "owner_metadata": _ref(owner_metadata_path),
        "operator_schema_sha256": _canonical_hash(operators),
        "event_definitions_sha256": _canonical_hash(event_definitions),
        "owner_metadata_sha256": _canonical_hash(owner),
        "physical_binding_sha256": _canonical_hash(binding),
        "physical_case_id": owner["physical_case_id"],
        "geometry": {"low_m": low, "high_m": high, "size_m": size},
        "expected_h5_sha256": expected_h5_sha256,
        "h5_sha256_status": "declared_only_not_rehashed" if expected_h5_sha256 else "not_provided",
        "surfaces": {
            event_id: {
                "event_id": event_id,
                "surface": finite_surfaces[event_id]["surface"],
                "normal_in_tank_frame": finite_surfaces[event_id]["normal_in_tank_frame"],
                "signed_direction": finite_surfaces[event_id].get("signed_direction"),
            }
            for event_id in ("left_right_exchange", "front_back_exchange", "top_open_exit")
        },
    }


def _new_surface_state(nfluid: int) -> dict[str, Any]:
    return {
        "candidate_crossings": 0,
        "accepted_crossings": 0,
        "aperture_rejected_crossings": 0,
        "positive_crossings": 0,
        "negative_crossings": 0,
        "positive_mass_kg": 0.0,
        "negative_mass_kg": 0.0,
        "first_passage_s": np.full(nfluid, np.nan, dtype=np.float64),
        "first_direction": np.full(nfluid, -1, dtype=np.int8),
        "crossing_count": np.zeros(nfluid, dtype=np.int64),
        "positive_count": np.zeros(nfluid, dtype=np.int64),
        "negative_count": np.zeros(nfluid, dtype=np.int64),
        "sample_events": [],
        "crossing_frames": [],
    }


def _event_for_pair(
    *,
    surface_id: str,
    previous: np.ndarray,
    current: np.ndarray,
    time_previous: float,
    time_current: float,
    previous_valid: np.ndarray,
    current_valid: np.ndarray,
    previous_mass: np.ndarray,
    current_mass: np.ndarray,
    low: Sequence[float],
    high: Sequence[float],
    state: dict[str, Any],
    fluid_indices: np.ndarray,
    particle_zone: np.ndarray,
    particle_id: np.ndarray,
    initial_mass: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    sample_limit: int,
    frame: int,
) -> None:
    if surface_id == "left_right_exchange":
        axis = 0
        plane = 0.0
        aperture_axes = (1, 2)
    elif surface_id == "front_back_exchange":
        axis = 1
        plane = 0.0
        aperture_axes = (0, 2)
    elif surface_id == "top_open_exit":
        axis = 2
        plane = high[2]
        aperture_axes = (0, 1)
    else:  # pragma: no cover - guarded by constants
        raise SurfaceAuditError(f"unknown surface: {surface_id}")

    both = previous_valid & current_valid
    both &= np.isfinite(previous).all(axis=1) & np.isfinite(current).all(axis=1)
    both &= np.isfinite(previous_mass) & np.isfinite(current_mass)
    both &= (previous_mass > 0) & (current_mass > 0)
    previous_axis = previous[:, axis]
    current_axis = current[:, axis]
    positive = both & (previous_axis < plane) & (current_axis >= plane)
    negative = both & (previous_axis > plane) & (current_axis <= plane)
    selected = positive | negative
    indices = np.flatnonzero(selected)
    if indices.size == 0:
        return

    delta = current_axis[indices] - previous_axis[indices]
    tau = np.divide(
        plane - previous_axis[indices],
        delta,
        out=np.full(indices.size, np.nan, dtype=np.float64),
        where=delta != 0,
    )
    valid_tau = np.isfinite(tau) & (tau >= 0.0) & (tau <= 1.0)
    crossing_point = previous[indices] + tau[:, None] * (current[indices] - previous[indices])
    within = valid_tau.copy()
    for aperture_axis in aperture_axes:
        within &= crossing_point[:, aperture_axis] >= low[aperture_axis]
        within &= crossing_point[:, aperture_axis] <= high[aperture_axis]

    state["candidate_crossings"] += int(indices.size)
    state["aperture_rejected_crossings"] += int(np.sum(~within))
    accepted_indices = indices[within]
    state["accepted_crossings"] += int(accepted_indices.size)
    if accepted_indices.size == 0:
        return

    accepted_tau = tau[within]
    accepted_positive = positive[accepted_indices]
    accepted_mass = 0.5 * (previous_mass[accepted_indices] + current_mass[accepted_indices])
    accepted_time = time_previous + accepted_tau * (time_current - time_previous)
    state["positive_crossings"] += int(np.sum(accepted_positive))
    state["negative_crossings"] += int(np.sum(~accepted_positive))
    state["positive_mass_kg"] += float(np.sum(accepted_mass[accepted_positive]))
    state["negative_mass_kg"] += float(np.sum(accepted_mass[~accepted_positive]))
    state["crossing_frames"].append({
        "frame_after": int(frame),
        "time_after_s": float(time_current),
        "accepted_count": int(accepted_indices.size),
        "accepted_mass_kg": float(np.sum(accepted_mass)),
        "positive_count": int(np.sum(accepted_positive)),
        "negative_count": int(np.sum(~accepted_positive)),
    })

    for offset, particle_idx in enumerate(accepted_indices):
        event_time = float(accepted_time[offset])
        direction = 1 if bool(accepted_positive[offset]) else -1
        state["crossing_count"][particle_idx] += 1
        if direction > 0:
            state["positive_count"][particle_idx] += 1
        else:
            state["negative_count"][particle_idx] += 1
        if not math.isfinite(float(state["first_passage_s"][particle_idx])):
            state["first_passage_s"][particle_idx] = event_time
            state["first_direction"][particle_idx] = direction
        if len(state["sample_events"]) < sample_limit:
            point = crossing_point[within][offset]
            state["sample_events"].append({
                "frame_before": int(frame - 1),
                "frame_after": int(frame),
                "time_before_s": float(time_previous),
                "time_after_s": float(time_current),
                "crossing_time_s": event_time,
                "tau": float(accepted_tau[offset]),
                "direction": "positive" if direction > 0 else "negative",
                "zone": int(particle_zone[fluid_indices[particle_idx]]),
                "idp": int(particle_id[fluid_indices[particle_idx]]),
                "initial_mass_kg": float(initial_mass[particle_idx]),
                "crossing_mass_kg": float(accepted_mass[offset]),
                "source_x": str(source_x[particle_idx]),
                "source_y": str(source_y[particle_idx]),
                "previous_position_m": [float(value) for value in previous[particle_idx]],
                "current_position_m": [float(value) for value in current[particle_idx]],
                "crossing_position_m": [float(value) for value in point],
            })


def _source_labels(initial_position: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    source_x = np.where(initial_position[:, 0] < 0.0, "left", "right")
    source_y = np.where(initial_position[:, 1] < 0.0, "front", "back")
    return source_x, source_y


def audit_surfaces(
    *,
    h5_path: Path,
    output_path: Path,
    operators_path: Path,
    event_definitions_path: Path,
    owner_metadata_path: Path,
    expected_h5_sha256: str | None = None,
    sample_limit: int = 64,
) -> dict[str, Any]:
    started = time.monotonic()
    before_usage = _usage()
    source_binding = _validate_sources(
        h5_path=h5_path,
        operators_path=operators_path,
        event_definitions_path=event_definitions_path,
        owner_metadata_path=owner_metadata_path,
        expected_h5_sha256=expected_h5_sha256,
    )
    if sample_limit < 0:
        raise SurfaceAuditError("sample_limit must be non-negative")

    with h5py.File(h5_path, "r") as h5:
        missing = [name for name in REQUIRED_DATASETS if name not in h5]
        if missing:
            raise SurfaceAuditError(f"HDF5 lacks required datasets: {missing}")
        times = np.asarray(h5["time"][:], dtype=np.float64)
        particle_id = np.asarray(h5["particle_id"][:])
        particle_zone = np.asarray(h5["particle_zone"][:])
        initial_type = np.asarray(h5["initial_type"][:])
        initial_mk = np.asarray(h5["initial_mk"][:])
        initial_mass_all = np.asarray(h5["initial_mass"][:], dtype=np.float64)
        frames = int(times.shape[0])
        particles = int(particle_id.shape[0])
        if frames < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
            raise SurfaceAuditError("time must be finite and strictly increasing")
        if h5["position"].shape != (frames, particles, 3):
            raise SurfaceAuditError("position shape does not match (time, particle, 3)")
        if h5["valid"].shape != (frames, particles) or h5["mass"].shape != (frames, particles):
            raise SurfaceAuditError("valid/mass shape does not match (time, particle)")
        fluid_indices = np.flatnonzero(initial_type == 3)
        if fluid_indices.size == 0:
            raise SurfaceAuditError("no type=3 fluid identities in source HDF5")
        initial_position = np.asarray(h5["position"][0, fluid_indices, :], dtype=np.float64)
        if not np.isfinite(initial_position).all():
            raise SurfaceAuditError("initial fluid positions are not finite")
        source_x, source_y = _source_labels(initial_position)
        nfluid = int(fluid_indices.size)
        states = {surface_id: _new_surface_state(nfluid) for surface_id in SURFACES}
        low = source_binding["geometry"]["low_m"]
        high = source_binding["geometry"]["high_m"]
        previous_position = None
        previous_valid = None
        previous_mass = None
        unknown_intervals = 0
        invalid_frame_rows = 0
        fluid_extrema = np.full((2, 3), np.nan, dtype=np.float64)
        valid_position_count = 0
        for frame, current_time in enumerate(times):
            current_position = np.asarray(h5["position"][frame, fluid_indices, :], dtype=np.float64)
            current_valid = np.asarray(h5["valid"][frame, fluid_indices], dtype=bool)
            current_mass = np.asarray(h5["mass"][frame, fluid_indices], dtype=np.float64)
            finite_position = np.isfinite(current_position).all(axis=1)
            good = current_valid & finite_position & np.isfinite(current_mass) & (current_mass > 0)
            if not bool(np.all(good)):
                invalid_frame_rows += 1
            if np.any(good):
                values = current_position[good]
                fluid_extrema[0] = np.nanmin(values, axis=0) if not np.isfinite(fluid_extrema[0]).all() else np.minimum(fluid_extrema[0], np.min(values, axis=0))
                fluid_extrema[1] = np.nanmax(values, axis=0) if not np.isfinite(fluid_extrema[1]).all() else np.maximum(fluid_extrema[1], np.max(values, axis=0))
                valid_position_count += int(np.sum(good))
            if previous_position is not None:
                unknown_intervals += int(np.sum(~(
                    previous_valid & current_valid
                    & np.isfinite(previous_position).all(axis=1)
                    & np.isfinite(current_position).all(axis=1)
                    & np.isfinite(previous_mass) & np.isfinite(current_mass)
                    & (previous_mass > 0) & (current_mass > 0)
                )))
                for surface_id in SURFACES:
                    _event_for_pair(
                        surface_id=surface_id,
                        previous=previous_position,
                        current=current_position,
                        time_previous=float(times[frame - 1]),
                        time_current=float(current_time),
                        previous_valid=previous_valid,
                        current_valid=current_valid,
                        previous_mass=previous_mass,
                        current_mass=current_mass,
                        low=low,
                        high=high,
                        state=states[surface_id],
                        fluid_indices=fluid_indices,
                        particle_zone=particle_zone,
                        particle_id=particle_id,
                        initial_mass=initial_mass_all[fluid_indices],
                        source_x=source_x,
                        source_y=source_y,
                        sample_limit=sample_limit,
                        frame=frame,
                    )
            previous_position = current_position
            previous_valid = current_valid
            previous_mass = current_mass

        final_position = previous_position
        final_valid = previous_valid
        final_category_counts = {"inside_domain": 0, "above_open_top": 0, "outside_finite_aperture": 0, "unknown": 0}
        for idx in range(nfluid):
            if not bool(final_valid[idx]) or not np.isfinite(final_position[idx]).all():
                category = "unknown"
            elif low[0] <= final_position[idx, 0] <= high[0] and low[1] <= final_position[idx, 1] <= high[1] and low[2] <= final_position[idx, 2] <= high[2]:
                category = "inside_domain"
            elif low[0] <= final_position[idx, 0] <= high[0] and low[1] <= final_position[idx, 1] <= high[1] and final_position[idx, 2] > high[2]:
                category = "above_open_top"
            else:
                category = "outside_finite_aperture"
            final_category_counts[category] += 1

        per_particle = []
        for idx, particle in enumerate(fluid_indices):
            row = {
                "zone": int(particle_zone[particle]),
                "idp": int(particle_id[particle]),
                "initial_mk": int(initial_mk[particle]),
                "initial_type": 3,
                "initial_mass_kg": float(initial_mass_all[particle]),
                "source_x": str(source_x[idx]),
                "source_y": str(source_y[idx]),
            }
            for surface_id, state in states.items():
                first = float(state["first_passage_s"][idx])
                row[surface_id] = {
                    "first_passage_s": None if not math.isfinite(first) else first,
                    "first_direction": None if state["first_direction"][idx] == -1 else ("positive" if state["first_direction"][idx] > 0 else "negative"),
                    "crossing_count": int(state["crossing_count"][idx]),
                    "positive_crossings": int(state["positive_count"][idx]),
                    "negative_crossings": int(state["negative_count"][idx]),
                    "repeat_crossings": max(0, int(state["crossing_count"][idx]) - 1),
                }
            per_particle.append(row)

    def serialise_state(surface_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "surface_id": surface_id,
            "classification": "in_domain_transport_interface" if surface_id != "top_open_exit" else "legal_open_exit_diagnostic",
            "candidate_crossings": int(state["candidate_crossings"]),
            "accepted_crossings": int(state["accepted_crossings"]),
            "aperture_rejected_crossings": int(state["aperture_rejected_crossings"]),
            "positive_crossings": int(state["positive_crossings"]),
            "negative_crossings": int(state["negative_crossings"]),
            "positive_crossing_mass_kg": float(state["positive_mass_kg"]),
            "negative_crossing_mass_kg": float(state["negative_mass_kg"]),
            "net_crossing_mass_kg": float(state["positive_mass_kg"] - state["negative_mass_kg"]),
            "repeat_crossings": int(np.sum(np.maximum(state["crossing_count"] - 1, 0))),
            "particle_count_with_crossing": int(np.sum(state["crossing_count"] > 0)),
            "sample_events_with_neighboring_states": state["sample_events"],
            "crossing_frame_rows": state["crossing_frames"],
        }

    report = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_status": "completed_actual_read_only_surface_replay",
        "audit_claim": "F3 weak dual-axis surface evidence only; no Q-N or production claim",
        "source": {
            "hdf5": _ref(h5_path),
            "binding": source_binding,
            "read_only": True,
            "hdf5_modified": False,
        },
        "trajectory": {
            "frames": frames,
            "particles": particles,
            "fluid_identities": nfluid,
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "time_finite_strictly_increasing": True,
            "initial_fluid_mass_kg": float(np.sum(initial_mass_all[fluid_indices])),
            "fluid_position_extrema_m": {"min": fluid_extrema[0].tolist(), "max": fluid_extrema[1].tolist()},
            "valid_finite_positive_samples": valid_position_count,
            "frames_with_invalid_or_nonfinite_fluid_state": invalid_frame_rows,
            "unknown_interval_particle_events": unknown_intervals,
            "final_category_counts": final_category_counts,
        },
        "surfaces": {surface_id: serialise_state(surface_id, states[surface_id]) for surface_id in SURFACES},
        "per_particle": per_particle,
        "resource": {
            "wall_seconds": float(time.monotonic() - started),
            "usage": _usage_delta(before_usage, _usage()),
        },
        "q_i_status": "surface replay and source binding complete; scientific qualification remains pending",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operators", type=Path, required=True)
    parser.add_argument("--event-definitions", type=Path, required=True)
    parser.add_argument("--owner-metadata", type=Path, required=True)
    parser.add_argument("--expected-h5-sha256")
    parser.add_argument("--sample-limit", type=int, default=64)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = audit_surfaces(
            h5_path=args.h5,
            output_path=args.output,
            operators_path=args.operators,
            event_definitions_path=args.event_definitions,
            owner_metadata_path=args.owner_metadata,
            expected_h5_sha256=args.expected_h5_sha256,
            sample_limit=args.sample_limit,
        )
    except (OSError, ValueError, SurfaceAuditError) as exc:
        print(f"F3 finite-surface audit failed: {exc}")
        return 2
    print(json.dumps({
        "output": str(args.output),
        "frames": report["trajectory"]["frames"],
        "fluid_identities": report["trajectory"]["fluid_identities"],
        "left_right": report["surfaces"]["left_right_exchange"]["accepted_crossings"],
        "front_back": report["surfaces"]["front_back_exchange"]["accepted_crossings"],
        "top_open_exit": report["surfaces"]["top_open_exit"]["accepted_crossings"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
