#!/usr/bin/env python3
"""Read-only static-hold observer for the H2 v5 runtime products.

The runtime adapter intentionally writes only generic CFD hard-integrity
fields.  This observer applies the registered H2 static-hold contract to a
completed trajectory without starting a solver or changing the worker result.
Its output is a sidecar evidence record; it never grants T1 or registry
credit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.f2.h2_mdbc.static_range_v5.static_hold_observation.v1"
RUNTIME_SCHEMA = "core.f2.h2_mdbc.static_range_v5.runtime_prepared.v1"
SCOPE_ID = "F2_H2_mdbc_static_range_qualification_v5"
TIME_MAX_S = 0.6
OUTPUT_INTERVAL_S = 0.02
SETTLE_HOLD_S = 0.2
SPEED_P95_MAX_M_S = 0.1
KINETIC_OVER_POTENTIAL_MAX = 0.05
RETENTION_MIN = 0.95
WALL_TOLERANCE_M = 1e-8


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _p95(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(np.percentile(values, 95.0)) if values.size else 0.0


def _box(prepared: dict[str, Any], name: str) -> tuple[np.ndarray, np.ndarray]:
    value = prepared["config"][name]
    low = np.asarray(value["low_m"], dtype=float)
    high = low + np.asarray(value["size_m"], dtype=float)
    return low, high


def _segment_crosses_closed_box(a: np.ndarray, b: np.ndarray, low: np.ndarray, high: np.ndarray) -> int:
    """Count saved-frame segments that cross a closed cup face.

    The top is open.  A crossing is counted only when the endpoint is outside
    a closed face while the segment intersects that face's rectangle.
    """
    count = 0
    delta = b - a
    for axis in range(3):
        for face in (low[axis], high[axis]):
            # The upper z face is the open cup mouth.
            if axis == 2 and abs(face - high[2]) <= WALL_TOLERANCE_M:
                continue
            component = delta[:, axis]
            moving = np.abs(component) > 1e-15
            fraction = np.full(len(a), np.nan, dtype=float)
            fraction[moving] = (face - a[moving, axis]) / component[moving]
            valid = moving & np.isfinite(fraction) & (fraction >= 0.0) & (fraction <= 1.0)
            if not np.any(valid):
                continue
            points = a + fraction[:, None] * delta
            other = [i for i in range(3) if i != axis]
            valid &= np.all((points[:, other] >= low[other] - WALL_TOLERANCE_M) &
                            (points[:, other] <= high[other] + WALL_TOLERANCE_M), axis=1)
            count += int(np.sum(valid))
    return count


def observe(prepared_path: Path, trajectory_path: Path) -> dict[str, Any]:
    prepared_path = Path(prepared_path).resolve()
    trajectory_path = Path(trajectory_path).resolve()
    prepared = load(prepared_path)
    if prepared.get("schema") != RUNTIME_SCHEMA or prepared.get("scope_id") != SCOPE_ID:
        raise ValueError("runtime prepared schema/scope mismatch")
    if prepared.get("preflight_pass") is not True or prepared.get("qualification_claim", "").startswith("none") is False:
        raise ValueError("runtime prepared input is not a zero-credit qualification canary")
    low, high = _box(prepared, "cup")
    receiver_low, receiver_high = _box(prepared, "receiver")
    tray_low, tray_high = _box(prepared, "tray")
    gate = prepared["config"].get("hold_gate", {})
    retention_min_gate = float(gate.get("cup_retention_mass_fraction_min", RETENTION_MIN))
    expected_time_max = float(prepared["config"].get("time_max_s", TIME_MAX_S))
    expected_output = float(prepared["config"].get("registered_output_interval_s", OUTPUT_INTERVAL_S))

    with h5py.File(trajectory_path, "r") as handle:
        required = ("time", "position", "velocity", "mass", "valid", "particle_id")
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"trajectory missing datasets: {missing}")
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        masses = np.asarray(handle["mass"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        particle_ids = np.asarray(handle["particle_id"][:])
        if positions.ndim != 3 or velocities.shape != positions.shape or masses.shape != positions.shape[:2] or valid.shape != positions.shape[:2]:
            raise ValueError("trajectory dataset shapes are inconsistent")
        if times.ndim != 1 or len(times) != positions.shape[0] or len(times) < 2:
            raise ValueError("trajectory time axis is invalid")
        initial_valid = valid[0].copy()
        initial_ids = particle_ids[initial_valid]
        initial_mass_values = masses[0].astype(float)
        initial_mass = float(initial_mass_values[initial_valid].sum(dtype=np.float64))
        initial_position = positions[0]
        initial_potential = float((initial_mass_values[initial_valid] * 9.81 *
                                   np.maximum(initial_position[initial_valid, 2] - low[2], 0.0)).sum(dtype=np.float64))
        retention: list[float] = []
        outside: list[float] = []
        receiver_mass: list[float] = []
        tray_mass: list[float] = []
        speed_p95: list[float] = []
        kinetic_ratio: list[float] = []
        mass_delta: list[float] = []
        missing_count: list[int] = []
        nonfinite_count: list[int] = []
        closed_endpoint_frames = 0
        saved_chord_crossings = 0
        previous: tuple[np.ndarray, np.ndarray] | None = None
        for frame in range(len(times)):
            active = valid[frame].copy()
            finite = (np.isfinite(positions[frame]).all(axis=1) &
                      np.isfinite(velocities[frame]).all(axis=1) &
                      np.isfinite(masses[frame]))
            nonfinite_count.append(int(np.sum(active & ~finite)))
            active &= finite
            pos = positions[frame]
            mass = masses[frame].astype(float)
            inside = active & np.all((pos >= low) & (pos <= high), axis=1)
            active_mass = float(mass[active].sum(dtype=np.float64))
            cup_mass = float(mass[inside].sum(dtype=np.float64))
            retention.append(cup_mass / max(initial_mass, 1e-30))
            outside.append(float(mass[active & ~inside].sum(dtype=np.float64)) / max(initial_mass, 1e-30))
            receiver = active & np.all((pos >= receiver_low) & (pos <= receiver_high), axis=1)
            tray = active & np.all((pos >= tray_low) & (pos <= tray_high), axis=1)
            receiver_mass.append(float(mass[receiver].sum(dtype=np.float64)) / max(initial_mass, 1e-30))
            tray_mass.append(float(mass[tray].sum(dtype=np.float64)) / max(initial_mass, 1e-30))
            speeds = np.linalg.norm(velocities[frame, active], axis=1)
            speed_p95.append(_p95(speeds))
            kinetic = float((0.5 * mass[active] * np.sum(velocities[frame, active] ** 2, axis=1)).sum(dtype=np.float64))
            kinetic_ratio.append(kinetic / max(initial_potential, 1e-30))
            mass_delta.append(float(np.max(np.abs(mass[initial_valid] - initial_mass_values[initial_valid]), initial=0.0)))
            missing_count.append(int(np.sum(initial_valid & ~valid[frame])))
            # A closed face endpoint is any active particle on a cup side or
            # bottom.  The top face remains open by contract.
            closed = active & (
                np.isclose(pos[:, 2], low[2], atol=WALL_TOLERANCE_M) |
                np.isclose(pos[:, 0], low[0], atol=WALL_TOLERANCE_M) |
                np.isclose(pos[:, 0], high[0], atol=WALL_TOLERANCE_M) |
                np.isclose(pos[:, 1], low[1], atol=WALL_TOLERANCE_M) |
                np.isclose(pos[:, 1], high[1], atol=WALL_TOLERANCE_M)
            )
            closed_endpoint_frames += int(np.sum(closed))
            if previous is not None:
                common = previous[1] & valid[frame] & np.isfinite(previous[0]).all(axis=1) & finite
                if np.any(common):
                    saved_chord_crossings += _segment_crosses_closed_box(
                        previous[0][common], pos[common], low, high
                    )
            previous = (pos.copy(), valid[frame].copy())

    retention_a = np.asarray(retention, dtype=float)
    outside_a = np.asarray(outside, dtype=float)
    receiver_a = np.asarray(receiver_mass, dtype=float)
    tray_a = np.asarray(tray_mass, dtype=float)
    speed_a = np.asarray(speed_p95, dtype=float)
    kinetic_a = np.asarray(kinetic_ratio, dtype=float)
    horizon = bool(times[-1] >= expected_time_max - 1e-6)
    cadence = float(np.median(np.diff(times))) if len(times) > 1 else float("nan")
    cadence_ok = bool(np.isfinite(cadence) and abs(cadence - expected_output) <= 2e-5)
    # The static event is the final continuous hold.  This avoids treating a
    # short initial quiet interval as completion.
    stable = (speed_a <= SPEED_P95_MAX_M_S) & (kinetic_a <= KINETIC_OVER_POTENTIAL_MAX)
    stable_duration = 0.0
    if len(times) >= 2 and stable[-1]:
        start = len(times) - 1
        while start > 0 and stable[start - 1]:
            start -= 1
        stable_duration = float(times[-1] - times[start])
    static_settled = bool(stable_duration + 1e-9 >= SETTLE_HOLD_S)
    hard_checks = {
        "time_axis_valid": bool(np.isfinite(times).all() and np.all(np.diff(times) > 0.0)),
        "registered_horizon_reached": horizon,
        "registered_output_cadence": cadence_ok,
        "native_ids_unique": bool(particle_ids.ndim == 1 and len(np.unique(particle_ids)) == len(particle_ids)),
        "no_missing_native_ids": max(missing_count, default=0) == 0,
        "no_unexpected_nonfinite_active_values": sum(nonfinite_count) == 0,
        "native_mass_unchanged": bool(max(mass_delta, default=0.0) <= 1e-12 * max(initial_mass, 1.0)),
        "no_closed_cup_endpoint_penetrations": closed_endpoint_frames == 0,
        "no_closed_cup_saved_chord_crossings": saved_chord_crossings == 0,
        "cup_retention_gate": (float(np.min(retention_a)) if retention_a.size else 0.0) >= retention_min_gate,
        "no_open_cup_escape": float(np.max(outside_a, initial=0.0)) <= 1e-12,
        "no_unexpected_receiver_mass": float(np.max(receiver_a, initial=0.0)) <= 1e-12,
        "no_unexpected_tray_mass": float(np.max(tray_a, initial=0.0)) <= 1e-12,
        "static_speed_gate": float(np.max(speed_a, initial=0.0)) <= SPEED_P95_MAX_M_S,
        "static_kinetic_gate": float(np.max(kinetic_a, initial=0.0)) <= KINETIC_OVER_POTENTIAL_MAX,
    }
    hard_pass = bool(all(hard_checks.values()))
    return {
        "schema": SCHEMA,
        "created_at_utc": stamp(),
        "family": "F2",
        "scope_id": SCOPE_ID,
        "case_id": prepared["case_id"],
        "cell_index": int(prepared["cell_index"]),
        "prepared": ref(prepared_path, "runtime prepared input"),
        "trajectory": ref(trajectory_path, "solver trajectory"),
        "registered": {"time_max_s": expected_time_max, "output_interval_s": expected_output,
                        "settle_hold_s": SETTLE_HOLD_S, "retention_min": retention_min_gate},
        "observed": {"time_start_s": float(times[0]), "time_end_s": float(times[-1]),
                     "frame_count": int(len(times)), "cadence_median_s": cadence,
                     "stable_final_duration_s": stable_duration,
                     "minimum_cup_retention_mass_fraction": (float(np.min(retention_a)) if retention_a.size else 0.0),
                     "maximum_outside_cup_mass_fraction": float(np.max(outside_a, initial=0.0)),
                     "maximum_receiver_mass_fraction": float(np.max(receiver_a, initial=0.0)),
                     "maximum_tray_mass_fraction": float(np.max(tray_a, initial=0.0)),
                     "maximum_speed_p95_m_s": float(np.max(speed_a, initial=0.0)),
                     "maximum_kinetic_over_initial_potential": float(np.max(kinetic_a, initial=0.0)),
                     "closed_cup_endpoint_particle_frames": int(closed_endpoint_frames),
                     "closed_cup_saved_chord_crossings": int(saved_chord_crossings),
                     "native_missing_count_max": int(max(missing_count, default=0)),
                     "nonfinite_active_value_count": int(sum(nonfinite_count))},
        "hard_checks": hard_checks,
        "hard_integrity_pass": hard_pass,
        "static_settled": static_settled,
        "event_window_complete": bool(hard_pass and static_settled),
        "qualification_claim": "none; H2 v5 static-hold observation sidecar",
        "qualified": False,
        "matrix_credit": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    value = observe(args.prepared, args.trajectory)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"case_id": value["case_id"], "hard_integrity_pass": value["hard_integrity_pass"],
                      "static_settled": value["static_settled"],
                      "event_window_complete": value["event_window_complete"],
                      "matrix_credit": value["matrix_credit"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
