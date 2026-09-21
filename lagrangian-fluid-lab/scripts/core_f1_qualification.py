#!/usr/bin/env python3
"""F1-specific manufactured observer and frozen 13+2 comparator.

This module owns the F1 qualification observer.  It does not import the F4
``physical_observations`` implementation: the registered observables include
the finite obstacle approach, front/back bypass split, downstream rejoin, and
return.  Preparation and comparison are CPU-only.  A report from this module
is an unqualified evidence receipt until the canary, all matrix cells, and the
external campaign review have passed.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from scripts.core_cfd import digest, write_json
from scripts.core_f1 import (
    F1_EVENT_WINDOW_S,
    F1_GRAVITY_M_S2,
    F1_MAX_EVENT_WINDOW_S,
    F1_NATIVE_OUTPUT_INTERVAL_S,
    F1_OUTPUT_INTERVAL_S,
    F1_RESOLUTIONS,
    _f1_mass_quality,
    _f1_native_box,
    _f1_sampling,
    _f1_wall_spec,
    f1_config,
    prepare_reference,
    qualification_design,
    reference_definition,
    resolve_runtime_domain,
    validate_reference_prepared,
)
from scripts.core_cfd import environment, native_frame
from scripts.finite_wall_audit import outside_closed_face_masks, segment_crossing_events


SCHEMA = "core.f1.qualification.v1"
CALIBRATION_SCHEMA = "core.f1.observer.calibration.v1"
OBSERVATION_SCHEMA = "core.f1.observations.v1"
REVISION_ID = "F1_H1_geometry_observer_qualification_v1"
CANARY_JOB_ID = "f1-h1-reference-fullwindow-canary-001"
MDBC_REPAIR_REVISION_ID = "F1_H2_mdbc_obstacle_normals_repair_v1"
MDBC_CANARY_JOB_ID = "f1-h2-mdbc-repair-canary-001"

# These values are frozen in the design receipt and are written to every
# qualification definition.  The half-step cell changes the actual solver
# time controls as well as CFL; the evaluator later checks Run.csv evidence.
BASE_TIME_CONTROL = {"DtIni": 0.000345882, "DtMin": 0.0000172941, "DtFixed": 0.0}
HALF_TIME_CONTROL = {key: value / 2.0 for key, value in BASE_TIME_CONTROL.items()}

SPATIAL_ERROR_MAX = 0.05
TEMPORAL_ERROR_FRACTION = 0.20
TEMPORAL_ERROR_MAX = SPATIAL_ERROR_MAX * TEMPORAL_ERROR_FRACTION
EVENT_TIME_RELATIVE_MAX = 0.05
ACTUAL_DT_RATIO_MAX = 0.80
ACTUAL_STEP_RATIO_MIN = 1.25
NATIVE_OUTPUT_INTERVAL_RATIO_MAX = 0.30
NATIVE_OUTPUT_FRAME_RATIO_MIN = 3.0

OBSERVABLE_NAMES = (
    "center_of_mass_x_over_tank_length",
    "center_of_mass_y_over_tank_width",
    "center_of_mass_z_over_tank_height",
    "kinetic_energy_over_initial_potential_energy",
    "active_mass_over_initial_native_mass",
    "obstacle_approach_mass_fraction",
    "downstream_mass_fraction",
    "front_bypass_mass_fraction",
    "back_bypass_mass_fraction",
    "rejoin_mass_fraction",
    "downstream_lateral_centroid_over_tank_width",
    "minimum_obstacle_clearance_over_tank_length",
    "returning_mass_fraction",
)

EVENT_NAMES = ("approach", "downstream", "split", "rejoin", "return")


def _geometry(config: dict) -> tuple[dict, dict, float]:
    tank = config["continuum_geometry"]["tank"]
    obstacle = config["continuum_geometry"]["obstacle"]
    return tank, obstacle, float(config["dp_m"])


def observer_registration() -> dict:
    """Return the immutable F1 geometry-aware observer contract."""
    return {
        "schema": OBSERVATION_SCHEMA,
        "revision_id": REVISION_ID,
        "observable_names": list(OBSERVABLE_NAMES),
        "normalization": {
            "mass_denominator": "initial_native_fluid_mass_kg_from_frame_zero; never survivor-renormalized",
            "center_of_mass": "active native mass weighted, divided by fixed tank dimensions",
            "kinetic_energy": "active kinetic energy divided by frame-zero native initial gravitational potential energy",
            "obstacle_clearance": "signed nearest distance to finite obstacle, divided by tank length",
            "channel_fractions": "fixed initial-native-mass denominator; front/back/rejoin regions use obstacle geometry",
            "time": "linear interpolation on the common registered output grid; no point-index comparison",
        },
        "geometry": {
            "obstacle_source": "config.continuum_geometry.obstacle",
            "container_source": "config.continuum_geometry.tank",
            "clearance": "finite center_obstacle box, 2dp approach margin",
            "front_channel": "downstream x and y < obstacle ymin - 2dp",
            "back_channel": "downstream x and y > obstacle ymax + 2dp",
            "rejoin": "downstream x >= obstacle xmax + 4dp and lateral centroid within 0.125 tank widths of centerline",
        },
        "event_thresholds": {
            "approach_mass_fraction": 0.01,
            "downstream_mass_fraction": 0.05,
            "split_each_channel_mass_fraction": 0.01,
            "rejoin_mass_fraction": 0.05,
            "return_com_x_drop_m": "max(0.02, 2*dp)",
            "return_separation_s": 0.10,
            "post_return_tail_s": "sqrt(1.2/9.81)",
        },
        "event_order": list(EVENT_NAMES),
        "qualification_use": "geometry-aware diagnostic and numerical consistency comparison; no external physical truth claim",
    }


def _mass_fraction(mass: np.ndarray, mask: np.ndarray, denominator: float) -> float:
    return float(np.asarray(mass, dtype=np.float64)[mask].sum(dtype=np.float64) / max(denominator, 1e-30))


def _signed_obstacle_distance(points: np.ndarray, obstacle: dict) -> np.ndarray:
    """Signed distance to a finite box: negative values are obstacle penetration."""
    lower = np.asarray(obstacle["low"], dtype=np.float64)
    upper = lower + np.asarray(obstacle["size"], dtype=np.float64)
    outside = np.maximum(np.maximum(lower - points, 0.0), points - upper)
    distance = np.linalg.norm(outside, axis=1)
    inside = np.all((points > lower) & (points < upper), axis=1)
    if inside.any():
        selected = points[inside]
        depth = np.min(np.stack((selected - lower, upper - selected), axis=1), axis=(1, 2))
        distance[inside] = -depth
    return distance


def _frame_observation(config: dict, position: np.ndarray, velocity: np.ndarray,
                       mass: np.ndarray, valid: np.ndarray, initial_mass: float,
                       initial_potential_energy: float) -> tuple[list[float], dict]:
    tank, obstacle, dp = _geometry(config)
    tank_low = np.asarray(tank["low"], dtype=np.float64)
    tank_size = np.asarray(tank["size"], dtype=np.float64)
    obstacle_low = np.asarray(obstacle["low"], dtype=np.float64)
    obstacle_high = obstacle_low + np.asarray(obstacle["size"], dtype=np.float64)
    position = np.asarray(position, dtype=np.float64)
    velocity = np.asarray(velocity, dtype=np.float64)
    mass = np.asarray(mass, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    active = valid & np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1) & np.isfinite(mass)
    if not active.any():
        raise ValueError("F1 observer found no finite active particles")
    p, v, m = position[active], velocity[active], mass[active]
    active_mass = float(m.sum(dtype=np.float64))
    center = (m[:, None] * p).sum(axis=0) / max(active_mass, 1e-30)
    xmargin = 2.0 * dp
    approach = (
        (p[:, 0] >= obstacle_low[0] - xmargin)
        & (p[:, 0] <= obstacle_high[0] + xmargin)
        & (p[:, 1] >= obstacle_low[1] - xmargin)
        & (p[:, 1] <= obstacle_high[1] + xmargin)
        & (p[:, 2] >= obstacle_high[2] - xmargin)
    )
    downstream = p[:, 0] >= obstacle_high[0] + xmargin
    front = downstream & (p[:, 1] < obstacle_low[1] - xmargin)
    back = downstream & (p[:, 1] > obstacle_high[1] + xmargin)
    rejoin_zone = p[:, 0] >= obstacle_high[0] + 4.0 * dp
    downstream_mass = float(m[downstream].sum(dtype=np.float64))
    downstream_lateral = float(
        (m[downstream] * p[downstream, 1]).sum(dtype=np.float64) / max(downstream_mass, 1e-30)
    ) if downstream.any() else float((tank_low[1] + .5 * tank_size[1]))
    lateral_norm = (downstream_lateral - (tank_low[1] + .5 * tank_size[1])) / tank_size[1]
    rejoin = rejoin_zone & (np.abs(p[:, 1] - downstream_lateral) <= .5 * tank_size[1])
    clearance = _signed_obstacle_distance(p, obstacle)
    kinetic = float(.5 * np.sum(m * np.sum(v * v, axis=1), dtype=np.float64))
    values = [
        float((center[0] - tank_low[0]) / tank_size[0]),
        float((center[1] - tank_low[1]) / tank_size[1]),
        float((center[2] - tank_low[2]) / tank_size[2]),
        float(kinetic / max(initial_potential_energy, 1e-30)),
        float(active_mass / max(initial_mass, 1e-30)),
        _mass_fraction(m, approach, initial_mass),
        _mass_fraction(m, downstream, initial_mass),
        _mass_fraction(m, front, initial_mass),
        _mass_fraction(m, back, initial_mass),
        _mass_fraction(m, rejoin, initial_mass) if downstream.any() and abs(lateral_norm) <= .125 else 0.0,
        float(lateral_norm),
        float(clearance.min() / tank_size[0]),
        _mass_fraction(m, v[:, 0] < -0.05, initial_mass),
    ]
    if not np.isfinite(values).all():
        raise ValueError("F1 observer produced nonfinite geometry-aware values")
    row = {
        "active_mass_kg": active_mass,
        "active_mass_fraction": float(active_mass / max(initial_mass, 1e-30)),
        "center_of_mass_m": center.tolist(),
        "approach_mass_fraction": values[5],
        "downstream_mass_fraction": values[6],
        "front_bypass_mass_fraction": values[7],
        "back_bypass_mass_fraction": values[8],
        "rejoin_mass_fraction": values[9],
        "downstream_lateral_centroid_over_tank_width": values[10],
        "minimum_obstacle_clearance_m": float(clearance.min()),
        "returning_mass_fraction": values[12],
    }
    return values, row


def _event_times(config: dict, times: np.ndarray, rows: list[dict]) -> dict:
    if len(times) == 0:
        return {name: None for name in EVENT_NAMES} | {
            "event_window_complete": False,
            "event_window_status": "no_frames",
            "requested_horizon_reached": False,
        }
    approach = np.asarray([row["approach_mass_fraction"] >= .01 for row in rows], dtype=bool)
    downstream = np.asarray([row["downstream_mass_fraction"] >= .05 for row in rows], dtype=bool)
    split = np.asarray([
        row["front_bypass_mass_fraction"] >= .01 and row["back_bypass_mass_fraction"] >= .01
        for row in rows
    ], dtype=bool)
    rejoin = np.asarray([
        row["rejoin_mass_fraction"] >= .05
        and abs(row["downstream_lateral_centroid_over_tank_width"]) <= .125
        for row in rows
    ], dtype=bool)
    def first_after(mask: np.ndarray, previous: int | None, *, inclusive: bool = False) -> int | None:
        start = 0 if previous is None else previous + (0 if inclusive else 1)
        candidates = np.flatnonzero(mask & (np.arange(len(mask)) >= start))
        return None if len(candidates) == 0 else int(candidates[0])
    i_approach = first_after(approach, None)
    i_downstream = first_after(downstream, i_approach)
    # A finite obstacle can be crossed into both bypass channels in the same
    # saved frame in which the downstream threshold is first reached.
    i_split = first_after(split, i_downstream, inclusive=True)
    i_rejoin = first_after(rejoin, i_split)
    i_return = None
    if i_rejoin is not None:
        start = i_rejoin + 1
        peak = max(row["center_of_mass_m"][0] for row in rows[i_rejoin:])
        drop = max(.02, 2.0 * float(config["dp_m"]))
        for index in range(start, len(rows)):
            if times[index] > times[i_rejoin] + .10 and rows[index]["center_of_mass_m"][0] <= peak - drop:
                i_return = index
                break
    indices = {"approach": i_approach, "downstream": i_downstream, "split": i_split,
               "rejoin": i_rejoin, "return": i_return}
    event_times = {name: None if index is None else float(times[index]) for name, index in indices.items()}
    gravity_time = math.sqrt(1.2 / F1_GRAVITY_M_S2)
    horizon = bool(times[-1] >= float(config["time_max_s"]) - 1e-6)
    tail = bool(i_return is not None and times[-1] - times[i_return] >= gravity_time)
    complete = bool(horizon and all(index is not None for index in indices.values()) and tail)
    if complete:
        status = "complete"
    elif horizon:
        status = "right_censored_requires_single_doubling"
    else:
        status = "horizon_not_reached"
    return {
        **event_times,
        "event_window_complete": complete,
        "event_window_status": status,
        "requested_horizon_reached": horizon,
        "post_return_tail_s": None if i_return is None else float(times[-1] - times[i_return]),
        "required_post_return_tail_s": gravity_time,
    }


def observe_arrays(config: dict, times: np.ndarray, positions: np.ndarray,
                   velocities: np.ndarray, masses: np.ndarray, valid: np.ndarray) -> dict:
    """Observe a complete in-memory trajectory; used by CPU manufactured calibration."""
    times = np.asarray(times, dtype=np.float64)
    positions = np.asarray(positions, dtype=np.float64)
    velocities = np.asarray(velocities, dtype=np.float64)
    masses = np.asarray(masses, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    if times.ndim != 1 or positions.ndim != 3 or velocities.shape != positions.shape:
        raise ValueError("F1 manufactured trajectory shapes are invalid")
    if masses.shape != positions.shape[:2] or valid.shape != masses.shape or len(times) != len(masses):
        raise ValueError("F1 manufactured trajectory dimensions are inconsistent")
    if len(times) < 2 or np.any(np.diff(times) <= 0) or not np.isfinite(times).all():
        raise ValueError("F1 observation times must be finite and increasing")
    initial_valid = valid[0] & np.isfinite(masses[0])
    initial_mass = float(masses[0, initial_valid].sum(dtype=np.float64))
    if initial_mass <= 0:
        raise ValueError("F1 initial native mass must be positive")
    tank, _, _ = _geometry(config)
    z0 = positions[0, initial_valid, 2]
    initial_potential = float(np.sum(masses[0, initial_valid] * F1_GRAVITY_M_S2 * z0, dtype=np.float64))
    rows, values = [], []
    for index, time_s in enumerate(times):
        vector, row = _frame_observation(config, positions[index], velocities[index], masses[index], valid[index],
                                         initial_mass, initial_potential)
        row["time_s"] = float(time_s)
        rows.append(row)
        values.append(vector)
    event = _event_times(config, times, rows)
    continuum_mass = float(math.prod(config["fluid_box"]["size"]) * 1000.0)
    return {
        "schema": OBSERVATION_SCHEMA,
        "revision_id": REVISION_ID,
        "case_id": config["case_id"],
        "observable_names": list(OBSERVABLE_NAMES),
        "time_s": times.tolist(),
        "normalized_values": values,
        "geometry_rows": rows,
        "event_times_s": {name: event[name] for name in EVENT_NAMES},
        "event_window_complete": event["event_window_complete"],
        "event_window_status": event["event_window_status"],
        "requested_horizon_reached": event["requested_horizon_reached"],
        "post_return_tail_s": event["post_return_tail_s"],
        "required_post_return_tail_s": event["required_post_return_tail_s"],
        "initial_native_mass_kg": initial_mass,
        "continuous_initial_mass_kg": continuum_mass,
        "source_initial_mass_relative_error": float(initial_mass / max(continuum_mass, 1e-30) - 1.0),
        "normalization_denominator": "frame-zero native fluid mass; no survivor renormalization",
        "geometry_aware": True,
        "qualification_claim": "none; F1 geometry-aware observer evidence",
    }


def observe_hdf5(prepared_path: Path, hdf5_path: Path) -> dict:
    prepared = json.loads(Path(prepared_path).read_text())
    config = prepared["config"]
    with h5py.File(hdf5_path, "r") as h:
        times = np.asarray(h["time"][:], dtype=np.float64)
        if len(times) < 2:
            raise ValueError("F1 HDF5 has fewer than two frames")
        initial_valid = h["valid"][0].astype(bool)
        initial_mass = np.asarray(h["mass"][0], dtype=np.float64)
        initial_valid &= np.isfinite(initial_mass)
        initial_mass_value = float(initial_mass[initial_valid].sum(dtype=np.float64))
        initial_position = np.asarray(h["position"][0], dtype=np.float64)
        initial_potential = float(np.sum(initial_mass[initial_valid] * F1_GRAVITY_M_S2 * initial_position[initial_valid, 2], dtype=np.float64))
        rows, values = [], []
        for index, time_s in enumerate(times):
            vector, row = _frame_observation(
                config,
                np.asarray(h["position"][index]),
                np.asarray(h["velocity"][index]),
                np.asarray(h["mass"][index]),
                np.asarray(h["valid"][index]).astype(bool),
                initial_mass_value,
                initial_potential,
            )
            row["time_s"] = float(time_s)
            rows.append(row)
            values.append(vector)
    event = _event_times(config, times, rows)
    continuous_mass = float(math.prod(config["fluid_box"]["size"]) * 1000.0)
    return {
        "schema": OBSERVATION_SCHEMA,
        "revision_id": REVISION_ID,
        "case_id": config["case_id"],
        "observable_names": list(OBSERVABLE_NAMES),
        "time_s": times.tolist(),
        "normalized_values": values,
        "geometry_rows": rows,
        "event_times_s": {name: event[name] for name in EVENT_NAMES},
        "event_window_complete": event["event_window_complete"],
        "event_window_status": event["event_window_status"],
        "requested_horizon_reached": event["requested_horizon_reached"],
        "post_return_tail_s": event["post_return_tail_s"],
        "required_post_return_tail_s": event["required_post_return_tail_s"],
        "initial_native_mass_kg": initial_mass_value,
        "continuous_initial_mass_kg": continuous_mass,
        "source_initial_mass_relative_error": float(initial_mass_value / max(continuous_mass, 1e-30) - 1.0),
        "source_mass_gate_pass": abs(initial_mass_value / max(continuous_mass, 1e-30) - 1.0) <= .025,
        "normalization_denominator": "frame-zero native fluid mass; no survivor renormalization",
        "geometry_aware": True,
        "qualification_claim": "none; F1 geometry-aware observer evidence",
    }


def manufactured_calibration(output: Path) -> dict:
    """Run an analytic F1 obstacle-path fixture without solver or CFD fitting."""
    config = f1_config(.0075, .5, stage="qualification")
    times = np.asarray([0.0, .1, .2, .3, .5, 1.0, 2.2], dtype=np.float64)
    positions = np.full((len(times), 4, 3), [.3, .2, .2], dtype=np.float64)
    positions[2, 0] = [.72, .2, .35]  # approach over the finite obstacle
    positions[3, 0] = [.86, .12, .2]  # front bypass
    positions[3, 1] = [.86, .28, .2]  # back bypass
    positions[4, 0] = [.95, .12, .2]
    positions[4, 1] = [.95, .28, .2]
    positions[4, 2:] = [.4, .2, .2]
    positions[5, 0] = [.90, .12, .2]
    positions[5, 1] = [.90, .28, .2]
    positions[5, 2:] = [.35, .2, .2]
    positions[6] = positions[5]
    velocities = np.zeros_like(positions)
    velocities[5, 0:2, 0] = -.1
    masses = np.ones((len(times), 4), dtype=np.float64)
    valid = np.ones_like(masses, dtype=bool)
    observed = observe_arrays(config, times, positions, velocities, masses, valid)
    expected_events = {"approach": .2, "downstream": .3, "split": .3, "rejoin": .5, "return": 1.0}
    event_error = max(abs(observed["event_times_s"][name] - expected) for name, expected in expected_events.items())
    values = np.asarray(observed["normalized_values"], dtype=np.float64)
    checks = {
        "finite_values": bool(np.isfinite(values).all()),
        "fixed_observable_layout": tuple(observed["observable_names"]) == OBSERVABLE_NAMES,
        "geometry_aware_observables_present": all(
            name in observed["observable_names"] for name in (
                "obstacle_approach_mass_fraction", "front_bypass_mass_fraction",
                "back_bypass_mass_fraction", "rejoin_mass_fraction",
            )
        ),
        "event_order_and_times": event_error < 1e-12,
        "event_window_complete": observed["event_window_complete"] is True,
        "fixed_initial_mass_denominator": observed["initial_native_mass_kg"] == 4.0,
        "no_survivor_renormalization": observed["normalization_denominator"].find("no survivor") >= 0,
        "initial_com_analytic": np.allclose(values[0, :3], [.25, .5, 1.0 / 3.0]),
    }
    report = {
        "schema": CALIBRATION_SCHEMA,
        "revision_id": REVISION_ID,
        "family": "F1",
        "passed": bool(all(checks.values())),
        "checks": checks,
        "max_event_time_error_s": float(event_error),
        "event_times_s": observed["event_times_s"],
        "observable_names": list(OBSERVABLE_NAMES),
        "method": "analytic four-particle finite-obstacle bypass fixture; no CFD output, fitting, or threshold selection",
        "scope": "F1 geometry-aware observer implementation and event ordering only",
        "observer_code_sha256": digest(Path(__file__)),
        "qualification_claim": "none; manufactured observer calibration",
    }
    write_json(Path(output), report)
    return report


def aligned_difference(first: dict, second: dict, cadence: float = F1_OUTPUT_INTERVAL_S) -> dict:
    if tuple(first.get("observable_names", ())) != tuple(second.get("observable_names", ())):
        raise ValueError("F1 observable layout mismatch")
    a, b = np.asarray(first["time_s"], dtype=np.float64), np.asarray(second["time_s"], dtype=np.float64)
    av, bv = np.asarray(first["normalized_values"], dtype=np.float64), np.asarray(second["normalized_values"], dtype=np.float64)
    if av.ndim != 2 or bv.ndim != 2 or av.shape[1] != len(OBSERVABLE_NAMES) or bv.shape[1] != av.shape[1]:
        raise ValueError("F1 observation shape mismatch")
    if any(not np.isfinite(x).all() for x in (a, b, av, bv)) or len(a) < 2 or len(b) < 2:
        raise ValueError("F1 observations contain nonfinite/insufficient values")
    if np.any(np.diff(a) <= 0) or np.any(np.diff(b) <= 0):
        raise ValueError("F1 observations are not strictly time ordered")
    low, high = max(a[0], b[0]), min(a[-1], b[-1])
    if high <= low:
        raise ValueError("F1 observations have no common time support")
    first_tick = int(math.ceil(low / cadence - 1e-10))
    last_tick = int(math.floor(high / cadence + 1e-10))
    if last_tick - first_tick < 1:
        raise ValueError("F1 observations have fewer than two common cadence points")
    grid = np.arange(first_tick, last_tick + 1, dtype=np.float64) * cadence
    aa = np.column_stack([np.interp(grid, a, av[:, index]) for index in range(av.shape[1])])
    bb = np.column_stack([np.interp(grid, b, bv[:, index]) for index in range(bv.shape[1])])
    errors = np.max(np.abs(aa - bb), axis=0)
    return {
        "maximum": float(errors.max()),
        "per_observable_maximum": errors.tolist(),
        "observable_names": list(OBSERVABLE_NAMES),
        "common_start_s": float(grid[0]),
        "common_end_s": float(grid[-1]),
        "score_frames": int(len(grid)),
    }


def event_difference(first: dict, second: dict) -> dict:
    a, b = first.get("event_times_s", {}), second.get("event_times_s", {})
    missing = [name for name in EVENT_NAMES if a.get(name) is None or b.get(name) is None]
    relative = {}
    for name in EVENT_NAMES:
        if name in missing:
            continue
        denominator = max(abs(float(a[name])), abs(float(b[name])), F1_OUTPUT_INTERVAL_S)
        relative[name] = abs(float(a[name]) - float(b[name])) / denominator
    maximum = max(relative.values(), default=float("inf"))
    return {
        "topology_pass": not missing,
        "missing_events": missing,
        "relative_time_errors": relative,
        "maximum_relative_time_error": float(maximum),
        "passed": bool(not missing and maximum <= EVENT_TIME_RELATIVE_MAX),
    }


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip().replace(",", ""))
    except (AttributeError, ValueError):
        return None


def read_run_metrics(product: Path) -> dict:
    """Read actual solver steps/output cadence from native Run.csv/trajectory."""
    product = Path(product)
    run_csv = product / "solver" / "Run.csv"
    run_out = product / "solver" / "Run.out"
    result = {"run_csv": str(run_csv), "run_out": str(run_out), "available": False}
    if run_csv.is_file():
        lines = run_csv.read_text(errors="replace").splitlines()
        header_index = next((index for index, line in enumerate(lines) if line.startswith("#RunName;")), None)
        if header_index is not None and header_index + 1 < len(lines):
            header = lines[header_index].lstrip("#").split(";")
            row = next(csv.reader([lines[header_index + 1]], delimiter=";"), [])
            fields = dict(zip(header, row))
            steps = _parse_number(fields.get("Steps"))
            physical_time = _parse_number(fields.get("PhysicalTime"))
            part_files = _parse_number(fields.get("PartFiles"))
            if steps is not None and physical_time is not None and steps > 0:
                result.update({
                    "available": True,
                    "steps": int(steps),
                    "physical_time_s": float(physical_time),
                    "mean_solver_dt_s": float(physical_time / steps),
                    "part_files": None if part_files is None else int(part_files),
                    "dp_m": _parse_number(fields.get("Dp")),
                })
    if run_out.is_file():
        text = run_out.read_text(errors="replace")
        result["dt_min_adjustment_warning_count"] = len(re.findall(r"DTs adjusted to DtMin", text))
        result["solver_finished"] = "Finished execution (code=0)" in text
    else:
        result["dt_min_adjustment_warning_count"] = 0
        result["solver_finished"] = False
    return result


def _mdbc_box(parent: ET.Element, fill: str, low: list[float], size: list[float]) -> ET.Element:
    node = ET.SubElement(parent, "drawbox")
    ET.SubElement(node, "boxfill").text = fill
    ET.SubElement(node, "point", {axis: f"{float(low[index]):.17g}" for index, axis in enumerate("xyz")})
    ET.SubElement(node, "size", {axis: f"{float(size[index]):.17g}" for index, axis in enumerate("xyz")})
    ET.SubElement(node, "layers", {"vdp": "0"})
    return node


def mdbc_repair_definition(config: dict, template: Path, target: Path) -> dict:
    """Materialize the one conditional boundary repair hypothesis.

    H2 changes the boundary recipe with complete normal geometry, ghost
    normals and no-penetration.  It keeps the tank, obstacle, cell-centre
    fluid sampling, runtime domain, CFL, event window and native masses fixed.
    """
    base_audit = reference_definition(config, template, target)
    tree = ET.parse(target)
    root = tree.getroot()
    geometry = root.find(".//casedef/geometry")
    commands = geometry.find("commands") if geometry is not None else None
    mainlist = commands.find("mainlist") if commands is not None else None
    if commands is None or mainlist is None:
        raise ValueError("F1 mDBC repair definition has no geometry command lists")
    definition = geometry.find("definition")
    if definition is None:
        raise ValueError("F1 mDBC repair definition has no geometry definition")
    pointref = definition.find("pointref")
    if pointref is None:
        pointref = ET.SubElement(definition, "pointref")
    half_dp = .5 * float(config["dp_m"])
    for axis in "xyz":
        pointref.set(axis, f"{half_dp:.17g}")
    # Keep the declared fluid box and native particle count fixed while
    # expressing its centres on the new dp/2 reference lattice.  The H1
    # template had no pointref, so its .045 m centres are not representable
    # on this lattice; the nearest in-box centres are .04125 m at dp=.0075.
    fluid_seen = False
    fluid_drawbox = None
    for node in list(mainlist):
        if node.tag == "setmkfluid" and node.get("mk") == "0":
            fluid_seen = True
        elif fluid_seen and node.tag == "drawbox":
            fluid_drawbox = node
            break
    if fluid_drawbox is None or fluid_drawbox.find("point") is None:
        raise ValueError("F1 mDBC repair fluid drawbox is incomplete")
    fluid_point = fluid_drawbox.find("point")
    for axis in "xyz":
        fluid_point.set(axis, f"{float(fluid_point.get(axis)) - half_dp:.17g}")
    # The retained F1 template emits one boundary layer without an explicit
    # layer declaration.  The failure receipt shows the first leak on that
    # finite front face, while the vendored mDBC cases that serialize a
    # complete BoundNor array use three fixed boundary layers.  Materialize
    # the same support recipe for both the tank and finite obstacle walls;
    # this changes boundary support only and leaves all fluid particles and
    # continuum dimensions untouched.
    active_bound_mk = None
    for node in list(mainlist):
        if node.tag == "setmkbound":
            active_bound_mk = node.get("mk")
        elif node.tag == "drawbox" and active_bound_mk is not None:
            layers = node.find("layers")
            if layers is None:
                layers = ET.SubElement(node, "layers")
            layers.set("vdp", "0,1,2")
            point = node.find("point")
            size = node.find("size")
            if point is None or size is None:
                raise ValueError("F1 mDBC boundary drawbox is incomplete")
            low = [float(point.get(axis)) for axis in "xyz"]
            extent = [float(size.get(axis)) for axis in "xyz"]
            # Match the official finite-box mDBC support placement: the
            # serialized boundary layers straddle the physical face, so
            # every boundary particle receives a finite geometry normal.
            for index, axis in enumerate("xyz"):
                point.set(axis, f"{low[index] - .5 * float(config['dp_m']):.17g}")
                size.set(axis, f"{extent[index] + float(config['dp_m']):.17g}")
    normal_list = ET.Element("list", {"name": "GeometryForNormals"})
    ET.SubElement(normal_list, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    ET.SubElement(normal_list, "setshapemode").text = "actual | bound"
    ET.SubElement(normal_list, "setnormalinvert", {"invert": "true"})
    ET.SubElement(normal_list, "setmkbound", {"mk": "0"})
    _mdbc_box(normal_list, "all^top", [0.0, 0.0, 0.0], [1.2, 0.4, 0.6])
    ET.SubElement(normal_list, "setmkbound", {"mk": "1"})
    _mdbc_box(normal_list, "top | left | right | front | back", [0.68, 0.15, 0.0], [0.12, 0.10, 0.34])
    ET.SubElement(normal_list, "shapeout", {"file": "hdp"})
    ET.SubElement(normal_list, "resetdraw")
    commands.insert(0, normal_list)
    mainlist.insert(0, ET.Element("runlist", {"name": "GeometryForNormals"}))
    casedef = root.find("casedef")
    if casedef is None:
        raise ValueError("F1 mDBC repair definition has no casedef")
    old_normals = casedef.find("normals")
    if old_normals is not None:
        casedef.remove(old_normals)
    normals = ET.SubElement(casedef, "normals", {"active": "true"})
    norgeometry = ET.SubElement(normals, "norgeometry")
    ET.SubElement(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    ET.SubElement(norgeometry, "distanceh", {"v": "3.0"})
    ET.SubElement(norgeometry, "svshapes", {"v": "true"})
    parameters = root.find(".//execution/parameters")
    if parameters is None:
        raise ValueError("F1 mDBC repair definition has no execution parameters")
    for key, value in (("NoPenetration", "1"), ("Boundary", "2"), ("SlipMode", "2")):
        node = parameters.find(f"parameter[@key='{key}']")
        if node is None:
            node = ET.SubElement(parameters, "parameter", {"key": key})
        node.set("value", value)
    ET.indent(tree, space="    ")
    tree.write(target, encoding="utf-8", xml_declaration=True)
    generated_audit = {
        **base_audit,
        "revision_id": MDBC_REPAIR_REVISION_ID,
        "definition_sha256": digest(target),
        "continuum_geometry_unchanged": True,
        "physical_geometry_unchanged": True,
        "boundary_semantics_unchanged": False,
        "mass_rescaling": False,
        "boundary_recipe_changed": True,
        "boundary_recipe": "mDBC no-slip with explicit tank+obstacle normals, ghost normals, NoPenetration=1",
        "normal_geometry": {
            "tank_faces": "all^top",
            "obstacle_faces": "top|left|right|front|back",
            "distanceh": 3.0,
            "svshapes": True,
            "normal_invert": True,
            "shapeout": "hdp",
        },
        "initial_fluid_lattice": {
            "pointref": "dp/2",
            "declared_box_unchanged": True,
            "native_centres_shifted_from_H1_by_m": [-half_dp, -half_dp, -half_dp],
            "native_mass_and_particle_count_unchanged": True,
        },
        "changed_fields": [
            "casedef.geometry.commands.GeometryForNormals",
            "casedef.geometry.commands.mainlist.boundary.layers=0,1,2",
            "casedef.geometry.commands.mainlist.boundary.support_box=physical_face+/-dp/2",
            "casedef.geometry.definition.pointref=dp/2 for boundary lattice alignment",
            "fluid initial drawbox point shifted to same dp/2 lattice",
            "casedef.normals",
            "execution.parameters.Boundary=2",
            "execution.parameters.SlipMode=2",
            "execution.parameters.NoPenetration=1",
            "solver_arguments=-mdbc_noslip:1",
        ],
        "unchanged_fields": [
            "CFL", "TimeMax", "TimeOut", "DtIni", "DtMin",
            "fluid density and native mass policy", "declared continuum fluid box",
            "tank", "obstacle", "runtime domain",
        ],
    }
    return generated_audit


def prepare_mdbc_repair_canary(lab: Path, output: Path) -> dict:
    """CPU-prepare H2's one evidence-based mDBC repair canary."""
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("mDBC repair preparation output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    config = f1_config(.0075, .5, stage="canary")
    config.update({
        "scope_id": "F1_single_obstacle_mdbc_repair_canary",
        "revision_id": MDBC_REPAIR_REVISION_ID,
        "case_id": "CORE_F1_H2_mdbc_obstacle_q0p50000000_h0p46000000_dp0p007500000000_canary",
        "recipe_id": MDBC_REPAIR_REVISION_ID,
        "recipe": "mdbc_native_repair",
        "boundary_semantics": "mDBC no-slip, complete finite tank+obstacle normals, ghost normals, NoPenetration=1",
        "qualification_claim": "none",
        "hypothesis": (
            "H1 failure starts at the finite front wall near y=-0.099 m and high z; "
            "mDBC normals/ghost/no-penetration may prevent boundary leakage and subsequent density exclusions"
        ),
        "solver_arguments": ["-mdbc_noslip:1"],
    })
    template = lab / config["source_definition"]
    target = output / (config["case_id"] + "_Def.xml")
    audit = mdbc_repair_definition(config, template, target)
    sampling = _f1_sampling(config)
    half_dp = .5 * float(config["dp_m"])
    sampling["fluid_boxes"][0]["first_center_m"] = [
        float(value) - half_dp for value in sampling["fluid_boxes"][0]["first_center_m"]
    ]
    sampling["initialization_rule"] = (
        "H2 cell-centre drawbox sampling on explicit pointref=dp/2 lattice; "
        "declared continuum box and native rho*dp^3 mass unchanged"
    )
    mass = _f1_mass_quality(sampling)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / config["case_id"]
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(target.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError("mDBC GenCase failed; inspect " + str(output / "gencase.log"))
    generated_xml = prefix.with_suffix(".xml")
    generated = ET.parse(generated_xml).getroot()
    blocks = generated.findall(".//particles/fluid")
    if len(blocks) != 1 or int(blocks[0].get("count")) != sampling["expected_fluid_particles"]:
        raise ValueError("mDBC repair GenCase fluid count differs from static cell-centre declaration")
    checks = {
        "generated_normals_active": generated.find(".//casedef/normals[@active='true']") is not None,
        "generated_normal_geometry": generated.find(".//casedef/normals/norgeometry") is not None,
        "generated_normal_list": generated.find(".//geometry/commands/list[@name='GeometryForNormals']") is not None,
        "generated_no_penetration": generated.find(".//execution/parameters/parameter[@key='NoPenetration']").get("value") == "1",
        "generated_boundary_mdbc": generated.find(".//execution/parameters/parameter[@key='Boundary']").get("value") == "2",
        "generated_slip_mode": generated.find(".//execution/parameters/parameter[@key='SlipMode']").get("value") == "2",
    }
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    with tempfile.TemporaryDirectory(prefix="core-f1-mdbc-initial-") as folder:
        ids, pos, vel, rho, meta, info, arrays = native_frame(prefix.with_suffix(".bi4"), Path(folder) / "native", decoder)
        normal_file = arrays / "BoundNor.bin"
        normals = np.fromfile(normal_file, np.float32).reshape(-1, 3) if normal_file.is_file() else np.empty((0, 3))
        boundary_count = int(meta.get("CaseNfixed", 0))
        native = {
            "total_particles": int(len(ids)),
            "boundary_particles": boundary_count,
            "fluid_particles": int(meta.get("CaseNfluid", 0)),
            "normal_count": int(len(normals)),
            "zero_boundary_normals": int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10)) if len(normals) else None,
            "normal_file_present": bool(normal_file.is_file()),
            "unique_ids": bool(len(np.unique(ids)) == len(ids)),
            "finite_initial_arrays": bool(all(np.isfinite(array).all() for array in (pos, vel, rho))),
            "native_initial_mass_kg": float(meta.get("MassFluid", 0.0)) * int(meta.get("CaseNfluid", 0)),
        }
    checks.update({
        "native_normals_complete": native["normal_file_present"] and native["normal_count"] == native["boundary_particles"],
        "native_normals_finite_nonzero": native["normal_file_present"] and native["zero_boundary_normals"] == 0,
        "native_state_finite_unique": native["unique_ids"] and native["finite_initial_arrays"],
        "native_fluid_count": native["fluid_particles"] == sampling["expected_fluid_particles"],
        "mass_gate": bool(mass["mass_gate_pass"]),
    })
    inputs = {str(path.resolve()): digest(path) for path in output.rglob("*") if path.is_file()}
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": "2026-09-19T00:00:00+00:00",
        "config": config,
        "sampling": sampling,
        "mass_preflight": mass,
        "native_initial": native,
        "mdbc_preflight": checks,
        "preflight_pass": bool(all(checks.values())),
        "generated_prefix": str(prefix.resolve()),
        "source_template": str(template.resolve()),
        "source_template_sha256": digest(template),
        "definition_audit": audit,
        "resolved_runtime_domain": resolve_runtime_domain(generated_xml),
        "inputs": inputs,
        "solver_binary": str(binaries / "DualSPHysics5.4_linux64"),
        "solver_sha256": digest(binaries / "DualSPHysics5.4_linux64"),
        "decoder": str(decoder),
        "decoder_sha256": digest(decoder),
        "solver_arguments": ["-mdbc_noslip:1"],
        "qualification_claim": "none; conditional mDBC repair canary only",
    }
    write_json(output / "prepared.json", prepared)
    return prepared


def make_mdbc_repair_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass") or prepared.get("config", {}).get("recipe") != "mdbc_native_repair":
        raise ValueError("mDBC repair prepared case did not pass CPU preflight")
    solver = Path(prepared["solver_binary"]).resolve()
    spec = {
        "schema": "core.cfd.job.v1",
        "job_id": MDBC_CANARY_JOB_ID,
        "logical_id": MDBC_CANARY_JOB_ID,
        "attempt_role": "conditional_repair",
        "category": "repair_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f1.py"), "--lab-root", str(lab),
                 "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": .25},
        "timeout_seconds": 3600,
        "depends_on": [],
        "qualification_claim": "none",
        "input_files": [{"path": str(prepared_path), "sha256": digest(prepared_path)},
                        {"path": str(solver), "sha256": digest(solver)}],
        "prepared_case_id": prepared["config"]["case_id"],
        "registered_window_s": prepared["config"]["time_max_s"],
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        "root_cause_evidence": "f1-canary-forensics.json",
        "qualification_status": "conditional repair evidence; original H1 failure retained",
    }
    write_json(output, spec)
    return spec


def failed_canary_forensics(lab: Path, product: Path, output: Path) -> dict:
    """Preserve the native exclusion and finite-wall causal evidence."""
    lab, product, output = Path(lab).resolve(), Path(product).resolve(), Path(output).resolve()
    runparts = product / "solver" / "RunPARTs.csv"
    aggregate = {"excluded": 0, "position": 0, "density": 0, "movement": 0, "first_exclusion_part": None,
                 "last_exclusion_part": None}
    rows = []
    if runparts.is_file():
        with runparts.open(newline="", errors="replace") as stream:
            for row in csv.DictReader(stream, delimiter=";"):
                def integer(key):
                    value = (row.get(key) or "").replace(",", "").strip()
                    try:
                        return int(float(value))
                    except ValueError:
                        return 0
                excluded = integer("NpOut")
                if excluded:
                    part = integer("Part")
                    aggregate["excluded"] += excluded
                    aggregate["position"] += integer("NpOutPos")
                    aggregate["density"] += integer("NpOutRho")
                    aggregate["movement"] += integer("NpOutMov")
                    aggregate["first_exclusion_part"] = part if aggregate["first_exclusion_part"] is None else min(aggregate["first_exclusion_part"], part)
                    aggregate["last_exclusion_part"] = part if aggregate["last_exclusion_part"] is None else max(aggregate["last_exclusion_part"], part)
                    rows.append({"part": part, "time_s": row.get("TimeStep [s]"), "excluded": excluded,
                                 "position": integer("NpOutPos"), "density": integer("NpOutRho"),
                                 "movement": integer("NpOutMov")})
    partout = {"status": "unavailable", "total": 0, "motive_counts": {}}
    prepared = product / "prepared.json"
    if prepared.is_file():
        decoder = Path(json.loads(prepared.read_text()).get("decoder", ""))
    else:
        decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    partvtk = lab / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
    data_dir = product / "solver" / "data"
    if decoder and partvtk.is_file() and data_dir.is_dir() and any(data_dir.glob("PartOut_*.obi4")):
        with tempfile.TemporaryDirectory(prefix="core-f1-forensics-") as folder:
            csv_path, resume_path = Path(folder) / "excluded.csv", Path(folder) / "resume.csv"
            proc = subprocess.run([str(partvtk), "-dirdata", str(data_dir), "-savecsv", str(csv_path),
                                   "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"],
                                  cwd=product, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if proc.returncode == 0 and csv_path.is_file():
                motive = {}
                first_rows = []
                with csv_path.open(newline="", errors="replace") as stream:
                    for row in csv.DictReader(stream):
                        value = (row.get("Motive") or "").strip()
                        motive[value] = motive.get(value, 0) + 1
                        if len(first_rows) < 5:
                            first_rows.append({key: row.get(key) for key in ("PartOut", "Motive", "Idp", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]")})
                partout = {"status": "available", "total": sum(motive.values()), "motive_counts": motive,
                           "first_rows": first_rows, "decoder": str(partvtk)}
    wall_rows, chord_crossings = [], 0
    hdf5 = product / "trajectory.h5"
    if hdf5.is_file():
        spec = {"container_interior": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": .4, "zmin": 0.0, "zmax": .6},
                "closed_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"], "obstacles": []}
        with h5py.File(hdf5, "r") as handle:
            previous = None
            ids = handle["particle_id"][:]
            for index, time_s in enumerate(handle["time"][:]):
                position = handle["position"][index]
                valid = handle["valid"][index].astype(bool)
                masks = outside_closed_face_masks(position, spec, 1e-8)
                for face, mask in masks.items():
                    bad = mask & valid
                    if bad.any():
                        wall_rows.append({"frame": index, "time_s": float(time_s), "face": face,
                                          "count": int(bad.sum()), "ids": ids[bad].astype(int).tolist(),
                                          "bounds_m": {axis: [float(position[bad, axis_index].min()), float(position[bad, axis_index].max())]
                                                       for axis, axis_index in zip("xyz", range(3))}})
                if previous is not None:
                    common = previous[1] & valid
                    chord_crossings += len(segment_crossing_events(previous[0][common], position[common], spec, 1e-8))
                previous = position, valid
    first_wall = wall_rows[0] if wall_rows else None
    report = {
        "schema": "core.f1.failure.forensics.v1",
        "revision_id": MDBC_REPAIR_REVISION_ID,
        "family": "F1",
        "source_product": str(product),
        "native_runparts": aggregate,
        "native_exclusion_classification": {
            "position": "invalid position / finite runtime or physical-wall escape",
            "density": "density below native RhopOutMin after the same boundary-leak episode",
            "movement": "invalid movement counter",
            "observed_pattern": "position exclusions precede and density exclusions dominate later Parts; movement exclusions are zero",
        },
        "partout": partout,
        "finite_wall": {
            "endpoint_violation_frames": len(wall_rows),
            "rows": wall_rows,
            "saved_chord_crossings": chord_crossings,
            "first_violation": first_wall,
            "closed_face": None if first_wall is None else first_wall["face"],
        },
        "root_cause_assessment": {
            "supported": bool(first_wall and first_wall["face"] == "front" and aggregate["position"] > 0 and aggregate["movement"] == 0),
            "finding": "front physical face leakage near y=-0.099 m at z near the open-tank rim precedes native density exclusions",
            "repair_hypothesis": "complete mDBC normals/ghost/no-penetration boundary recipe; preserve all fluid/tank/obstacle/time/mass inputs",
            "cfl_only_repair_allowed": False,
            "qualification_claim": "none",
        },
    }
    write_json(output, report)
    return report


def _time_control_for_cell(config: dict) -> dict:
    return copy.deepcopy(HALF_TIME_CONTROL if config["design_cell"] == "internal_time" else BASE_TIME_CONTROL)


def formal_design() -> dict:
    """Build the F1-specific 13+2 design with actual time controls frozen."""
    base = qualification_design()
    cells = copy.deepcopy(base["cells"])
    for config in cells:
        config["time_control"] = _time_control_for_cell(config)
        config["observer_revision"] = REVISION_ID
        config["observer_observable_names"] = list(OBSERVABLE_NAMES)
        config["event_registration"] = observer_registration()["event_thresholds"]
    design = {
        "schema": SCHEMA,
        "revision_id": REVISION_ID,
        "scope_id": base["scope_id"],
        "family": "F1",
        "qualification_claim": "none",
        "candidate_status": "pre_registered_unqualified",
        "cell_count": len(cells),
        "cells": cells,
        "spatial_cells": 13,
        "temporal_cells": 2,
        "spatial_resolutions_m": list(F1_RESOLUTIONS),
        "one_dimensional_parameter": base["one_dimensional_parameter"],
        "fixed_geometry": base["fixed_geometry"],
        "registered_window": {
            "initial_time_max_s": F1_EVENT_WINDOW_S,
            "output_interval_s": F1_OUTPUT_INTERVAL_S,
            "maximum_extended_time_max_s": F1_MAX_EVENT_WINDOW_S,
            "extension_policy": "one whole-scope doubling after a frozen event right-censor",
            "event_completion_required": True,
        },
        "observer": observer_registration(),
        "preregistered_gates": {
            "spatial_max_absolute_normalized_difference": SPATIAL_ERROR_MAX,
            "temporal_fraction_of_spatial_budget": TEMPORAL_ERROR_FRACTION,
            "temporal_max_absolute_normalized_difference": TEMPORAL_ERROR_MAX,
            "event_time_relative_error_max": EVENT_TIME_RELATIVE_MAX,
            "actual_dt_ratio_max_for_internal_time": ACTUAL_DT_RATIO_MAX,
            "actual_step_ratio_min_for_internal_time": ACTUAL_STEP_RATIO_MIN,
            "native_output_interval_ratio_max": NATIVE_OUTPUT_INTERVAL_RATIO_MAX,
            "native_output_frame_ratio_min": NATIVE_OUTPUT_FRAME_RATIO_MIN,
            "closed_wall_endpoint_tolerance_m": 1e-8,
            "saved_chord_crossings_allowed": 0,
            "source_initial_mass_relative_error_max": .025,
            "initial_mass_spread_over_continuous_mass_max": .03,
            "no_survivor_renormalization": True,
            "canary_hard_integrity_required": True,
            "all_15_cells_required": True,
        },
        "temporal_time_control": {
            "base": BASE_TIME_CONTROL,
            "internal_time": HALF_TIME_CONTROL,
            "actual_evidence": "solver/Run.csv Steps and PhysicalTime, not config CFL alone",
        },
        "canary_dependency": {
            "job_id": CANARY_JOB_ID,
            "required_before_qualification": True,
            "required_status": "succeeded with hard_integrity_pass, mass gate, and complete event window",
        },
        "calibration_dependency": {
            "schema": CALIBRATION_SCHEMA,
            "required_pass": True,
            "external_physical_validation": False,
        },
    }
    return design


def validate_formal_prepared(prepared_path: Path) -> dict:
    prepared_path = Path(prepared_path).resolve()
    base = validate_reference_prepared(prepared_path)
    prepared = json.loads(prepared_path.read_text())
    config = prepared.get("config", {})
    issues = list(base.get("issues", []))
    if config.get("stage") != "qualification":
        issues.append("formal matrix cell is not a qualification-stage case")
    if config.get("observer_revision") != REVISION_ID:
        issues.append("observer revision is not frozen F1 qualification revision")
    control = config.get("time_control", {})
    expected = _time_control_for_cell(config) if config else {}
    for key, value in expected.items():
        if not math.isclose(float(control.get(key, float("nan"))), value, rel_tol=0.0, abs_tol=1e-12):
            issues.append(f"time control {key} is not frozen at {value}")
    generated = Path(prepared.get("generated_prefix", "")).with_suffix(".xml")
    if not generated.is_file():
        issues.append("generated XML is missing")
    else:
        root = ET.parse(generated).getroot()
        for key, value in expected.items():
            node = root.find(f".//execution/parameters/parameter[@key='{key}']")
            actual = None if node is None else _parse_number(node.get("value"))
            if actual is None or not math.isclose(actual, value, rel_tol=0.0, abs_tol=1e-12):
                issues.append(f"generated XML {key} does not materialize frozen time control")
    passed = not issues
    return {
        "schema": "core.f1.static.v1",
        "revision_id": REVISION_ID,
        "prepared": str(prepared_path),
        "case_id": config.get("case_id"),
        "design_cell": config.get("design_cell"),
        "static_quality_pass": passed,
        "preflight_pass": passed,
        "mass_rescaling": False,
        "continuum_geometry_unchanged": True,
        "time_control": control,
        "qualification_claim": "none",
        "issues": issues,
    }


def write_design(output: Path) -> dict:
    design = formal_design()
    write_json(Path(output), design)
    return design


def prepare_matrix(lab: Path, output: Path) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("F1 qualification matrix output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    design = formal_design()
    design_path = output / "design.json"
    write_json(design_path, design)
    rows = []
    for index, config in enumerate(design["cells"]):
        cell_root = output / f"cell-{index:02d}"
        prepared = prepare_reference(config, lab, cell_root)
        validation = validate_formal_prepared(cell_root / "prepared.json")
        rows.append({
            "index": index,
            "case_id": config["case_id"],
            "q": config["parameter"]["q"],
            "dp_m": config["dp_m"],
            "design_cell": config["design_cell"],
            "prepared": str((cell_root / "prepared.json").resolve()),
            "preflight_pass": bool(prepared["preflight_pass"]),
            "static_quality_pass": bool(validation["static_quality_pass"]),
            "mass_gate_pass": bool(prepared["mass_preflight"]["mass_gate_pass"]),
            "time_control": config["time_control"],
        })
        write_json(output / "prepared-matrix.json", {
            "schema": SCHEMA,
            "revision_id": REVISION_ID,
            "design_sha256": digest(design_path),
            "cells": rows,
            "complete": len(rows) == len(design["cells"]),
            "qualification_claim": "none",
        })
    passed = len(rows) == 15 and all(row["preflight_pass"] and row["static_quality_pass"] and row["mass_gate_pass"] for row in rows)
    return {
        "schema": SCHEMA,
        "revision_id": REVISION_ID,
        "matrix_root": str(output),
        "cell_count": len(rows),
        "preflight_pass": passed,
        "static_quality_pass": passed,
        "qualification_claim": "none; CPU preparation only",
    }


def _resource_estimate(config: dict) -> dict:
    dp = float(config["dp_m"])
    if config["design_cell"] == "native_output":
        return {"cpu_cores": 2, "ram_mib": 24576 if dp <= .0075 else 16384,
                "gpu_peak_mib": 6144 if dp <= .0075 else 4096, "io_weight": 1}
    if dp <= .005 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib": 6144, "io_weight": 1}
    if dp <= .0075 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 1}
    return {"cpu_cores": 2, "ram_mib": 12288, "gpu_peak_mib": 3072, "io_weight": 1}


def make_jobs(matrix_root: Path, lab: Path, output: Path) -> dict:
    matrix_root, lab, output = Path(matrix_root).resolve(), Path(lab).resolve(), Path(output).resolve()
    design = json.loads((matrix_root / "design.json").read_text())
    matrix = json.loads((matrix_root / "prepared-matrix.json").read_text())
    if len(matrix.get("cells", [])) != 15 or not matrix.get("complete"):
        raise ValueError("F1 qualification matrix is incomplete")
    jobs_dir = output.with_suffix("")
    jobs_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for index, row in enumerate(matrix["cells"]):
        prepared_path = Path(row["prepared"]).resolve()
        validation = validate_formal_prepared(prepared_path)
        if not validation["static_quality_pass"]:
            raise ValueError(f"F1 cell {index:02d} static validation failed: {validation['issues']}")
        prepared = json.loads(prepared_path.read_text())
        solver = Path(prepared["solver_binary"]).resolve()
        decoder = Path(prepared["decoder"]).resolve()
        config = prepared["config"]
        job_id = f"f1-h1-qualification-cell-{index:02d}"
        timeout = 10800 if config["dp_m"] <= .005 else 7200
        spec = {
            "schema": "core.cfd.job.v1",
            "job_id": job_id,
            "logical_id": job_id,
            "attempt_role": "initial",
            "category": "qualification",
            "host": "ada",
            "source_lab": str(lab),
            "cwd": str(lab),
            "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f1.py"),
                     "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
                     "--output", "{attempt_dir}/product"],
            "required_outputs": ["product/result.json", "product/trajectory.h5",
                                 "product/audit.json", "product/observations.json"],
            "resources": _resource_estimate(config),
            "timeout_seconds": timeout,
            "depends_on": [],
            "qualification_claim": "none",
            "input_files": [
                {"path": str(prepared_path), "sha256": digest(prepared_path)},
                {"path": str(solver), "sha256": digest(solver)},
                {"path": str(decoder), "sha256": digest(decoder)},
            ],
            "prepared_case_id": config["case_id"],
            "registered_window_s": config["time_max_s"],
            "maximum_extended_window_s": config["event_window"]["maximum_extended_time_max_s"],
            "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
            "canary_gate_required": CANARY_JOB_ID,
            "observer_revision": REVISION_ID,
            "time_control_gate": "actual Run.csv Steps/PhysicalTime required for internal_time cell",
            "static_validation": validation,
        }
        path = jobs_dir / f"{job_id}.json"
        write_json(path, spec)
        jobs.append({"index": index, "job_id": job_id, "path": str(path),
                     "prepared": str(prepared_path), "resources": spec["resources"],
                     "required_outputs": spec["required_outputs"]})
    manifest = {
        "schema": "core.cfd.jobs.v1",
        "revision_id": REVISION_ID,
        "matrix_root": str(matrix_root),
        "matrix_sha256": digest(matrix_root / "prepared-matrix.json"),
        "design_sha256": digest(matrix_root / "design.json"),
        "jobs": jobs,
        "job_count": len(jobs),
        "execution_status": "prepared_only; canary gate required before qualification",
        "qualification_claim": "none",
        "canary_dependency": CANARY_JOB_ID,
    }
    write_json(output, manifest)
    return manifest


def _hashes_valid(job: dict, product: Path, paths: list[Path]) -> bool:
    indexed = {item["path"]: item["sha256"] for item in job.get("result", {}).get("artifact_index", job.get("result", {}).get("outputs", []))}
    return all(indexed.get("product/" + path.name) == digest(path) for path in paths)


def _job_for_prepared(jobs: list[dict], prepared_path: Path) -> dict | None:
    expected = digest(prepared_path)
    matches = [job for job in jobs if any(item.get("path") == str(prepared_path) and item.get("sha256") == expected
                                         for item in job.get("spec", {}).get("input_files", []))]
    completed = [job for job in matches if job.get("status") == "succeeded"]
    return completed[0] if completed else (matches[0] if matches else None)


def _canary_gate(jobs: list[dict], canary_job_id: str = CANARY_JOB_ID) -> dict:
    matching = [job for job in jobs if job.get("job_id") == canary_job_id]
    if not matching:
        return {"available": False, "passed": False, "reason": "canary_job_missing", "job_id": canary_job_id}
    job = matching[0]
    if job.get("status") != "succeeded":
        return {"available": True, "passed": False, "reason": "canary_not_succeeded",
                "job_id": canary_job_id, "status": job.get("status")}
    product = Path(job.get("attempt_dir", "")) / "product"
    audit_path = product / "audit.json"
    if not audit_path.is_file():
        return {"available": True, "passed": False, "reason": "canary_audit_missing", "job_id": canary_job_id}
    audit = json.loads(audit_path.read_text())
    product_prepared = product / "prepared.json"
    mass_pass = False
    if product_prepared.is_file():
        mass_pass = bool(json.loads(product_prepared.read_text()).get("mass_preflight", {}).get("mass_gate_pass"))
    passed = bool(audit.get("hard_integrity_pass") and audit.get("requested_horizon_reached")
                  and audit.get("event_window_complete") and mass_pass
                  and audit.get("qualification_claim", "").find("none") >= 0)
    return {"available": True, "passed": passed, "job_id": canary_job_id,
            "status": job.get("status"), "hard_integrity_pass": audit.get("hard_integrity_pass"),
            "requested_horizon_reached": audit.get("requested_horizon_reached"),
            "event_window_complete": audit.get("event_window_complete"),
            "mass_gate_pass": mass_pass,
            "event_window_status": audit.get("event_window_status")}


def _compare_pair(first: dict, second: dict, limit: float) -> dict:
    vector = aligned_difference(first, second)
    events = event_difference(first, second)
    return {"vector": vector, "events": events,
            "passed": bool(vector["maximum"] <= limit and events["passed"])}


def evaluate(matrix_root: Path, runtime_root: Path, *, calibration: Path | None = None,
             canary_job_id: str = CANARY_JOB_ID) -> dict:
    matrix_root, runtime_root = Path(matrix_root).resolve(), Path(runtime_root).resolve()
    design = json.loads((matrix_root / "design.json").read_text())
    matrix = json.loads((matrix_root / "prepared-matrix.json").read_text())
    from scripts.core_runtime import Store
    jobs = Store(runtime_root).jobs()
    cells, observations, run_metrics, missing, failures = [], {}, {}, [], []
    for row in matrix["cells"]:
        prepared_path = Path(row["prepared"]).resolve()
        job = _job_for_prepared(jobs, prepared_path)
        if job is None or job.get("status") != "succeeded":
            missing.append({"index": row["index"], "case_id": row["case_id"],
                            "attempt_status": None if job is None else job.get("status")})
            continue
        product = Path(job["attempt_dir"]) / "product"
        audit_path = product / "audit.json"
        trajectory_path = product / "trajectory.h5"
        worker_obs_path = product / "observations.json"
        if not all(path.is_file() for path in (audit_path, trajectory_path, worker_obs_path)):
            failures.append({"index": row["index"], "case_id": row["case_id"], "reason": "required_product_missing"})
            continue
        prepared = json.loads(prepared_path.read_text())
        static = validate_formal_prepared(prepared_path)
        audit = json.loads(audit_path.read_text())
        obs = observe_hdf5(prepared_path, trajectory_path)
        metrics = read_run_metrics(product)
        observations[(prepared["config"]["parameter"]["q"], prepared["config"]["dp_m"], prepared["config"]["design_cell"])] = obs
        run_metrics[(prepared["config"]["parameter"]["q"], prepared["config"]["dp_m"], prepared["config"]["design_cell"])] = metrics
        hashes = _hashes_valid(job, product, [audit_path, trajectory_path, worker_obs_path])
        good = bool(static["static_quality_pass"] and hashes and audit.get("hard_integrity_pass")
                    and obs.get("source_mass_gate_pass", abs(obs["source_initial_mass_relative_error"]) <= .025)
                    and obs.get("event_window_complete"))
        if not good:
            failures.append({"index": row["index"], "case_id": row["case_id"],
                             "reason": "static_hash_hard_mass_event_gate",
                             "static_quality_pass": static["static_quality_pass"],
                             "hashes_valid": hashes, "hard_integrity_pass": audit.get("hard_integrity_pass"),
                             "source_mass_gate_pass": obs.get("source_mass_gate_pass"),
                             "event_window_complete": obs.get("event_window_complete"),
                             "event_window_status": obs.get("event_window_status")})
        cells.append({"index": row["index"], "case_id": row["case_id"], "job_id": job["job_id"],
                      "passed": good, "hashes_valid": hashes, "audit": audit,
                      "observer": {"event_times_s": obs["event_times_s"],
                                   "event_window_status": obs["event_window_status"],
                                   "maximum_observable_count": len(obs["observable_names"])},
                      "run_metrics": metrics})
    gates = design["preregistered_gates"]
    comparisons = []
    spatial_pass = independent_pass = True
    for q in (0.0, .5, 1.0, .25, .75):
        middle = observations.get((q, .0075, "spatial"))
        fine = observations.get((q, .005, "spatial"))
        if middle is None or fine is None:
            spatial_pass = False
            if q in (.25, .75):
                independent_pass = False
            continue
        mf = _compare_pair(middle, fine, float(gates["spatial_max_absolute_normalized_difference"]))
        record = {"q": q, "kind": "medium_vs_fine", **mf}
        passed = mf["passed"]
        if q in (0.0, .5, 1.0):
            coarse = observations.get((q, .01, "spatial"))
            if coarse is None:
                passed = False
                record["coarse_available"] = False
            else:
                cm = _compare_pair(coarse, middle, float(gates["spatial_max_absolute_normalized_difference"]))
                cf = _compare_pair(coarse, fine, float(gates["spatial_max_absolute_normalized_difference"]))
                monotone = mf["vector"]["maximum"] <= cm["vector"]["maximum"] + 1e-12
                passed = passed and cm["passed"] and cf["passed"] and monotone
                record.update({"coarse_vs_medium": cm, "coarse_vs_fine": cf,
                               "monotone_refinement": monotone})
        record["passed"] = bool(passed)
        comparisons.append(record)
        spatial_pass &= bool(passed)
        if q in (.25, .75):
            independent_pass &= bool(passed)
    temporal_pass = actual_dt_pass = native_output_pass = True
    baseline = observations.get((.5, .0075, "spatial"))
    baseline_metrics = run_metrics.get((.5, .0075, "spatial"))
    for kind in ("internal_time", "native_output"):
        other = observations.get((.5, .0075, kind))
        other_metrics = run_metrics.get((.5, .0075, kind))
        if baseline is None or other is None or baseline_metrics is None or other_metrics is None:
            temporal_pass = actual_dt_pass = native_output_pass = False
            continue
        pair = _compare_pair(baseline, other, float(gates["temporal_max_absolute_normalized_difference"]))
        if kind == "internal_time":
            if not baseline_metrics.get("available") or not other_metrics.get("available"):
                time_evidence = False
                ratios = {"dt_ratio": None, "steps_ratio": None}
            else:
                dt_ratio = other_metrics["mean_solver_dt_s"] / max(baseline_metrics["mean_solver_dt_s"], 1e-30)
                steps_ratio = other_metrics["steps"] / max(baseline_metrics["steps"], 1)
                ratios = {"dt_ratio": dt_ratio, "steps_ratio": steps_ratio}
                time_evidence = bool(dt_ratio <= float(gates["actual_dt_ratio_max_for_internal_time"])
                                     and steps_ratio >= float(gates["actual_step_ratio_min_for_internal_time"]))
            passed = bool(pair["passed"] and time_evidence)
            actual_dt_pass &= time_evidence
            temporal_pass &= passed
            comparisons.append({"q": .5, "kind": kind, **pair, "actual_time_step_evidence": time_evidence,
                                "actual_time_step_ratios": ratios, "passed": passed})
        else:
            base_times = np.asarray(baseline["time_s"])
            other_times = np.asarray(other["time_s"])
            base_interval = float(np.median(np.diff(base_times)))
            other_interval = float(np.median(np.diff(other_times)))
            interval_ratio = other_interval / max(base_interval, 1e-30)
            frame_ratio = len(other_times) / max(len(base_times), 1)
            cadence_evidence = bool(interval_ratio <= float(gates["native_output_interval_ratio_max"])
                                    and frame_ratio >= float(gates["native_output_frame_ratio_min"]))
            passed = bool(pair["passed"] and cadence_evidence)
            native_output_pass &= passed
            temporal_pass &= passed
            comparisons.append({"q": .5, "kind": kind, **pair, "output_cadence_evidence": cadence_evidence,
                                "output_interval_ratio": interval_ratio, "output_frame_ratio": frame_ratio,
                                "passed": passed})
    calibration_report = None
    calibrated = False
    if calibration is not None and Path(calibration).is_file():
        calibration = Path(calibration).resolve()
        payload = json.loads(calibration.read_text())
        calibrated = bool(payload.get("schema") == CALIBRATION_SCHEMA and payload.get("passed") is True
                          and payload.get("observer_code_sha256") == digest(Path(__file__)))
        calibration_report = {"path": str(calibration), "sha256": digest(calibration), "passed": calibrated}
    canary = _canary_gate(jobs, canary_job_id)
    all_cells = len(cells) == 15 and not missing and not failures
    checks = {
        "static_matrix": bool(matrix.get("complete") and len(matrix.get("cells", [])) == 15),
        "canary_gate": bool(canary["passed"]),
        "observer_calibrated": calibrated,
        "matrix_complete": all_cells,
        "all_case_hard_mass_event_gates": all_cells,
        "spatial": bool(spatial_pass),
        "independent_checks": bool(independent_pass),
        "time_and_output": bool(temporal_pass),
        "actual_time_step_gate": bool(actual_dt_pass),
        "native_output_cadence_gate": bool(native_output_pass),
    }
    return {
        "schema": SCHEMA,
        "revision_id": REVISION_ID,
        "scope_id": design["scope_id"],
        "family": "F1",
        "extent": "one-dimensional initial-height range with registered spatial/temporal cells",
        "T1_numerical": bool(all(checks.values())),
        "T2_macro": False,
        "T2_path": False,
        "external_physical_validation": False,
        "qualified": False,
        "qualification_claim": "none; canary and 13+2 comparator evidence only",
        "promotion_status": "blocked_until_canary_matrix_and_external_campaign_review",
        "checks": checks,
        "canary": canary,
        "calibration": calibration_report,
        "design_sha256": digest(matrix_root / "design.json"),
        "matrix_sha256": digest(matrix_root / "prepared-matrix.json"),
        "cells": cells,
        "missing": missing,
        "failures": failures,
        "comparisons": comparisons,
        "observer_revision": REVISION_ID,
        "claim_limit": "registered finite tank, obstacle, height range, resolutions, time controls, and observer scales only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("calibrate")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("write-design")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("prepare-matrix")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("validate-prepared")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-jobs")
    p.add_argument("--matrix", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("forensics")
    p.add_argument("--product", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("prepare-mdbc-repair")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-mdbc-repair-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("evaluate")
    p.add_argument("--matrix", type=Path, required=True)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--calibration", type=Path)
    p.add_argument("--canary-job-id", default=CANARY_JOB_ID)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "calibrate":
        result = manufactured_calibration(args.output)
    elif args.command == "write-design":
        result = write_design(args.output)
    elif args.command == "prepare-matrix":
        result = prepare_matrix(args.lab_root, args.output)
    elif args.command == "validate-prepared":
        result = validate_formal_prepared(args.prepared)
        write_json(args.output, result)
    elif args.command == "make-jobs":
        result = make_jobs(args.matrix, args.lab_root, args.output)
    elif args.command == "forensics":
        result = failed_canary_forensics(args.lab_root, args.product, args.output)
    elif args.command == "prepare-mdbc-repair":
        result = prepare_mdbc_repair_canary(args.lab_root, args.output)
    elif args.command == "make-mdbc-repair-job":
        result = make_mdbc_repair_job(args.prepared, args.lab_root, args.output)
    else:
        result = evaluate(args.matrix, args.runtime, calibration=args.calibration,
                          canary_job_id=args.canary_job_id)
        write_json(args.output, result)
    print(json.dumps({key: result[key] for key in (
        "passed", "preflight_pass", "static_quality_pass", "cell_count", "job_count",
        "T1_numerical", "qualification_claim", "checks", "mdbc_preflight") if key in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
