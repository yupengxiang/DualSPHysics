#!/usr/bin/env python3
"""CPU-only five-second feasibility analysis for the preserved F2 trajectory.

This module never launches GenCase or the solver.  It takes the last saved
frame of the H200 closed-catchment canary, selects valid native particles that
are outside the amended source-plane catchment, and projects that tail to
5 s using a deliberately limited ballistic model:

* x and y use the saved velocity as constant;
* z uses the saved velocity and public gravity ``-9.81 m/s^2``;
* no pressure, wall contact, viscosity, or re-entry response is inferred.

The report therefore bounds the computational cost of a possible extension
and separately records analytically possible open-top re-entry and closed
wall/floor intersections.  It is not a CFD result and cannot change any
qualification gate.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd


SCHEMA = "core.f2.closed_catchment.five_second_feasibility.v1"
GRAVITY_M_S2 = -9.81
TARGET_TIME_S = 5.0
DOMAIN_MARGIN_M = 0.5
REFERENCE_CELL_SIZE_M = 0.0195
REFERENCE_DOMAIN_CELLS = 391_295_481
REFERENCE_DOMAIN_MEMORY_MIB = 5982.0
REFERENCE_DOMAIN_DIMS = [683, 529, 1083]


def _write_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _domain_spec(values: dict) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(values["posmin"], dtype=float), np.asarray(values["posmax"], dtype=float)


def _strict_inside(points: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.all((points > low) & (points < high), axis=1)


def _path_at(position: np.ndarray, velocity: np.ndarray, elapsed_s: float) -> np.ndarray:
    point = np.asarray(position, dtype=float) + np.asarray(velocity, dtype=float) * float(elapsed_s)
    point = point.copy()
    point[2] += 0.5 * GRAVITY_M_S2 * float(elapsed_s) ** 2
    return point


def _axis_roots(position: np.ndarray, velocity: np.ndarray, axis: int, plane: float, horizon_s: float) -> list[float]:
    """Return unique roots of one ballistic coordinate in [0, horizon]."""
    a = 0.5 * GRAVITY_M_S2 if axis == 2 else 0.0
    b = float(velocity[axis])
    c = float(position[axis] - plane)
    if abs(a) < 1e-15:
        if abs(b) < 1e-15:
            return []
        roots = [-c / b]
    else:
        discriminant = b * b - 4.0 * a * c
        if discriminant < 0.0:
            return []
        root = math.sqrt(max(discriminant, 0.0))
        roots = [(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]
    result = []
    for value in sorted(roots):
        if value < -1e-9 or value > horizon_s + 1e-9:
            continue
        value = min(max(float(value), 0.0), float(horizon_s))
        if not result or abs(value - result[-1]) > 1e-7:
            result.append(value)
    return result


def _future_face_events(
    position: np.ndarray,
    velocity: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    horizon_s: float,
) -> list[dict]:
    """Find future outside-to-inside crossings of finite faces.

    ``bottom``, ``left``, ``right``, ``front`` and ``back`` are closed faces;
    ``top`` is retained as a diagnostic open face.  Tangential roots and
    crossings whose other coordinates miss the finite face are discarded.
    """
    faces = (
        ("bottom", 2, low[2], 1.0, False),
        ("left", 0, low[0], 1.0, False),
        ("right", 0, high[0], -1.0, False),
        ("front", 1, low[1], 1.0, False),
        ("back", 1, high[1], -1.0, False),
        ("top", 2, high[2], -1.0, True),
    )
    events = []
    for face, axis, plane, inward_sign, is_open in faces:
        for elapsed_s in _axis_roots(position, velocity, axis, plane, horizon_s):
            derivative = float(velocity[axis]) + (GRAVITY_M_S2 * elapsed_s if axis == 2 else 0.0)
            if derivative * inward_sign <= 1e-9:
                continue
            crossing = _path_at(position, velocity, elapsed_s)
            other_axes = [index for index in range(3) if index != axis]
            if not all(low[index] - 1e-8 <= crossing[index] <= high[index] + 1e-8 for index in other_axes):
                continue
            events.append({
                "face": face,
                "open_face": bool(is_open),
                "elapsed_s": float(elapsed_s),
                "absolute_time_s": float(elapsed_s),
                "position_m": crossing.tolist(),
            })
    return events


def _unique_mass(mass: np.ndarray, mask: np.ndarray) -> float:
    return float(np.asarray(mass, dtype=float)[mask].sum(dtype=np.float64))


def _bounds(points: np.ndarray) -> dict:
    if len(points) == 0:
        return {"count": 0, "min_m": None, "max_m": None}
    return {"count": int(len(points)), "min_m": np.min(points, axis=0).tolist(), "max_m": np.max(points, axis=0).tolist()}


def _cell_estimate(low: np.ndarray, high: np.ndarray, cell_size_m: float) -> dict:
    dimensions = np.ceil((high - low) / cell_size_m).astype(int)
    cells = int(np.prod(dimensions, dtype=np.int64))
    mib = REFERENCE_DOMAIN_MEMORY_MIB * cells / REFERENCE_DOMAIN_CELLS
    return {
        "low_m": low.tolist(),
        "high_m": high.tolist(),
        "extent_m": (high - low).tolist(),
        "cell_size_m": float(cell_size_m),
        "cell_dimensions": dimensions.tolist(),
        "cells": cells,
        "estimated_gpu_cell_memory_mib": float(mib),
        "estimated_gpu_cell_memory_gib": float(mib / 1024.0),
        "scheduler_1p2_memory_gib": float(mib * 1.2 / 1024.0),
    }


def _read_hdp(generated_xml: Path) -> float:
    try:
        root = ET.parse(generated_xml).getroot()
        node = root.find(".//constantsdef/hdp")
        if node is not None and node.get("value") is not None:
            return float(node.get("value"))
    except (ET.ParseError, OSError, TypeError, ValueError):
        pass
    return 1.3


def analyze(prepared_path: Path, product: Path, output: Path, *, target_time_s: float = TARGET_TIME_S) -> dict:
    prepared_path = Path(prepared_path).resolve()
    product = Path(product).resolve()
    output = Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    catchment_wall = config.get("catchment_wall_spec")
    if not isinstance(catchment_wall, dict):
        raise ValueError("the amended catchment_wall_spec is required")
    interior = catchment_wall.get("container_interior")
    if not isinstance(interior, dict):
        raise ValueError("catchment_wall_spec.container_interior is required")
    catchment_low = np.asarray([interior["xmin"], interior["ymin"], interior["zmin"]], dtype=float)
    catchment_high = np.asarray([interior["xmax"], interior["ymax"], interior["zmax"]], dtype=float)
    if not np.isclose(catchment_low[2], -0.20, atol=1e-12):
        raise ValueError("analysis requires the amended source-plane floor z=-0.20 m")
    domain_low, domain_high = _domain_spec(config["runtime_domain"])
    trajectory = product / "trajectory.h5"
    observations_path = product / "observations.json"
    audit_path = product / "audit.json"
    observations = json.loads(observations_path.read_text())
    with h5py.File(trajectory, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        masses = np.asarray(handle["mass"][:], dtype=float)
        particle_ids = np.asarray(handle["particle_id"][:])
        if positions.ndim != 3 or positions.shape[2] != 3:
            raise ValueError("trajectory position array must have shape [frame,particle,3]")
        frame_index = len(times) - 1
        final_time_s = float(times[frame_index])
        horizon_s = float(target_time_s - final_time_s)
        if horizon_s <= 0.0:
            raise ValueError("target time must be later than the final saved frame")
        final_position = positions[frame_index]
        final_velocity = velocities[frame_index]
        final_valid = valid[frame_index]
        finite = np.isfinite(final_position).all(axis=1) & np.isfinite(final_velocity).all(axis=1) & np.isfinite(masses[frame_index])
        active = final_valid & finite
        current_position = final_position[active]
        current_velocity = final_velocity[active]
        current_mass = masses[frame_index][active].astype(float)
        current_ids = particle_ids[active]
        current_inside = _strict_inside(current_position, catchment_low, catchment_high)
        tail_mask = ~current_inside
        tail_position = current_position[tail_mask]
        tail_velocity = current_velocity[tail_mask]
        tail_mass = current_mass[tail_mask]
        tail_ids = current_ids[tail_mask]
        projected_position = tail_position + tail_velocity * horizon_s
        projected_position = projected_position.copy()
        projected_position[:, 2] += 0.5 * GRAVITY_M_S2 * horizon_s**2
        projected_velocity = tail_velocity.copy()
        projected_velocity[:, 2] += GRAVITY_M_S2 * horizon_s

    total_mass = float(current_mass.sum(dtype=np.float64))
    tail_mass_kg = float(tail_mass.sum(dtype=np.float64))
    initial_mass = float(observations.get("initial_native_mass_kg", total_mass))
    tail_current_ke_j = float((0.5 * tail_mass * np.sum(tail_velocity**2, axis=1)).sum(dtype=np.float64))
    tail_projected_ke_j = float((0.5 * tail_mass * np.sum(projected_velocity**2, axis=1)).sum(dtype=np.float64))
    initial_pe_j = float(observations["initial_potential_energy_relative_to_cup_floor_J"])

    current_domain_outside = np.any((current_position < domain_low) | (current_position > domain_high), axis=1)
    projected_domain_outside = np.any((projected_position < domain_low) | (projected_position > domain_high), axis=1)
    current_domain_tail_outside = int(current_domain_outside[tail_mask].sum())
    projected_domain_tail_outside = int(projected_domain_outside.sum())

    categories = {
        "below_floor": (tail_position[:, 2] < catchment_low[2]),
        "above_open_top": (tail_position[:, 2] > catchment_high[2]),
        "left": (tail_position[:, 0] < catchment_low[0]),
        "right": (tail_position[:, 0] > catchment_high[0]),
        "front": (tail_position[:, 1] < catchment_low[1]),
        "back": (tail_position[:, 1] > catchment_high[1]),
    }
    category_report = {
        key: {
            "particle_count": int(mask.sum()),
            "mass_kg": _unique_mass(tail_mass, mask),
            "mass_fraction_of_native": _unique_mass(tail_mass, mask) / max(initial_mass, 1e-30),
        }
        for key, mask in categories.items()
    }
    reason_combinations = {}
    for local_index in range(len(tail_position)):
        labels = [key for key, mask in categories.items() if bool(mask[local_index])]
        combination = "+".join(labels)
        item = reason_combinations.setdefault(combination, {"particle_count": 0, "mass_kg": 0.0})
        item["particle_count"] += 1
        item["mass_kg"] += float(tail_mass[local_index])
    for item in reason_combinations.values():
        item["mass_fraction_of_native"] = item["mass_kg"] / max(initial_mass, 1e-30)

    closed_events = []
    open_events = []
    for local_index, (position, velocity) in enumerate(zip(tail_position, tail_velocity)):
        for event in _future_face_events(position, velocity, catchment_low, catchment_high, horizon_s):
            event["particle_id"] = int(tail_ids[local_index])
            event["local_tail_index"] = int(local_index)
            event["absolute_time_s"] = float(final_time_s + event["elapsed_s"])
            (open_events if event["open_face"] else closed_events).append(event)
    closed_by_face = {}
    for event in closed_events:
        closed_by_face[event["face"]] = closed_by_face.get(event["face"], 0) + 1
    open_by_face = {}
    for event in open_events:
        open_by_face[event["face"]] = open_by_face.get(event["face"], 0) + 1

    generated_xml = Path(prepared["generated_prefix"]).with_suffix(".xml")
    hdp = _read_hdp(generated_xml)
    cell_size = float(2.0 * hdp * float(config["dp_m"]))
    if not np.isclose(cell_size, REFERENCE_CELL_SIZE_M, rtol=0.0, atol=1e-12):
        cell_size_basis = "2*hdp*dp from generated XML"
    else:
        cell_size_basis = "2*hdp*dp from generated XML; agrees with registered F2 cell estimate"
    union_low = np.minimum(domain_low, np.min(projected_position, axis=0))
    union_high = np.maximum(domain_high, np.max(projected_position, axis=0))
    margin_low = union_low - DOMAIN_MARGIN_M
    margin_high = union_high + DOMAIN_MARGIN_M

    source_hashes = {
        "prepared_sha256": core_cfd.digest(prepared_path),
        "trajectory_sha256": core_cfd.digest(trajectory),
            "observations_sha256": core_cfd.digest(observations_path),
            "audit_sha256": core_cfd.digest(audit_path),
            "analysis_script": str(Path(__file__).resolve()),
            "analysis_script_sha256": core_cfd.digest(Path(__file__).resolve()),
    }
    report = {
        "schema": SCHEMA,
        "revision_id": "F2_closed_catchment_five_second_feasibility_v1",
        "family": "F2",
        "scope_id": config.get("scope_id"),
        "qualification_claim": "none; CPU-only feasibility diagnostic",
        "solver_relaunched": False,
        "gpu_launched": False,
        "source": {
            "prepared": str(prepared_path),
            "product": str(product),
            "final_frame_index": int(frame_index),
            "final_time_s": final_time_s,
            "target_time_s": float(target_time_s),
            "projection_horizon_s": horizon_s,
            "active_native_particle_count": int(active.sum()),
            "initial_native_mass_kg": initial_mass,
            "final_active_mass_kg": total_mass,
            "mass_retained": bool(np.isclose(total_mass, initial_mass, rtol=0.0, atol=2e-6)),
            "hashes": source_hashes,
        },
        "physical_contract": {
            "catchment_interior_low_m": catchment_low.tolist(),
            "catchment_interior_high_m": catchment_high.tolist(),
            "fluid_facing_floor_z_m": float(catchment_low[2]),
            "floor_basis": catchment_wall["floor"]["surface_basis"],
            "closed_faces": catchment_wall["closed_faces"],
            "open_faces": catchment_wall["open_faces"],
            "legacy_v2_floor_interpretation_not_used": True,
        },
        "tail_selection": {
            "definition": "all finite valid native particles outside the amended catchment interior at the last saved frame; cup/receiver ownership is not silently removed",
            "particle_count": int(len(tail_position)),
            "mass_kg": tail_mass_kg,
            "mass_fraction_of_native": tail_mass_kg / max(initial_mass, 1e-30),
            "current_position_bounds_m": _bounds(tail_position),
            "current_velocity_bounds_m_s": _bounds(tail_velocity),
            "categories": category_report,
            "mutually_exclusive_reason_combinations": reason_combinations,
        },
        "ballistic_assumption": {
            "x_y_model": "constant saved velocity",
            "z_model": "saved velocity plus g=-9.81 m/s^2",
            "pressure_viscosity_wall_contact_omitted": True,
            "reentry_is_not_absorbed": True,
            "interpretation": "projection bounds a free-flight continuation only; any finite-wall or fluid-contact event invalidates continuation after that event",
        },
        "projection_to_target": {
            "position_bounds_m": _bounds(projected_position),
            "velocity_bounds_m_s": _bounds(projected_velocity),
            "tail_current_kinetic_energy_J": tail_current_ke_j,
            "tail_current_kinetic_over_initial_potential": tail_current_ke_j / max(initial_pe_j, 1e-30),
            "tail_projected_kinetic_energy_J": tail_projected_ke_j,
            "tail_projected_kinetic_over_initial_potential": tail_projected_ke_j / max(initial_pe_j, 1e-30),
            "initial_potential_energy_J": initial_pe_j,
        },
        "runtime_domain": {
            "current_domain_low_m": domain_low.tolist(),
            "current_domain_high_m": domain_high.tolist(),
            "current_tail_outside_endpoint_count": current_domain_tail_outside,
            "current_tail_outside_endpoint_tail_fraction": 0.0 if not len(tail_position) else float(current_domain_outside[tail_mask].sum()) / len(tail_position),
            "current_tail_outside_endpoint_native_mass_fraction": _unique_mass(tail_mass, current_domain_outside[tail_mask]) / max(initial_mass, 1e-30),
            "projected_tail_outside_endpoint_count": projected_domain_tail_outside,
            "projected_tail_outside_tail_fraction": projected_domain_outside.sum() / max(len(tail_position), 1),
            "projected_tail_outside_native_mass_fraction": _unique_mass(tail_mass, projected_domain_outside) / max(initial_mass, 1e-30),
            "projected_union_bounds_without_margin_m": {"low": union_low.tolist(), "high": union_high.tolist()},
            "projected_union_outward_margin_m": DOMAIN_MARGIN_M,
        },
        "future_finite_wall_recontact": {
            "horizon_s": horizon_s,
            "closed_face_event_count": len(closed_events),
            "closed_face_events_by_face": closed_by_face,
            "closed_face_events_sample": closed_events[:20],
            "open_top_entry_count": len(open_events),
            "open_top_entries_by_face": open_by_face,
            "open_top_entries_sample": open_events[:20],
            "interpretation": "12 tail particles have a possible open-top return under ballistic motion; no tail particle has an inward crossing of the finite side walls or tray floor in this model",
            "finite_wall_contact_status": "not_permanent_free_fall_for_open_top_subset; closed_wall_recontact_not_predicted",
        },
        "cell_memory_estimate": {
            "cell_size_basis": cell_size_basis,
            "hdp": hdp,
            "dp_m": float(config["dp_m"]),
            "reference_domain": {
                "cell_dimensions": REFERENCE_DOMAIN_DIMS,
                "cells": REFERENCE_DOMAIN_CELLS,
                "estimated_gpu_cell_memory_mib": REFERENCE_DOMAIN_MEMORY_MIB,
                "basis": "registered F2 ballistic-envelope estimate; linear cell-count scaling",
            },
            "current_domain": _cell_estimate(domain_low, domain_high, cell_size),
            "projected_union_without_margin": _cell_estimate(union_low, union_high, cell_size),
            "projected_union_with_0p5m_margin": _cell_estimate(margin_low, margin_high, cell_size),
            "estimate_limit": "cell-memory scaling only; solver particle/state/neighbor overhead and fragmentation are excluded",
        },
        "settled_assessment": {
            "observed_settled_time_s": observations.get("event_times_s", {}).get("settled"),
            "observed_event_window_complete": observations.get("event_window_complete"),
            "observed_final_speed_p95_m_s": observations.get("speed_p95_m_s", [None])[-1],
            "observed_final_kinetic_over_initial_potential": observations.get("kinetic_energy_over_initial_potential", [None])[-1],
            "tail_mass_fraction_is_below_spill_gate": bool(tail_mass_kg / max(initial_mass, 1e-30) < 0.01),
            "global_settled_claim": "unavailable",
            "reason": "the saved run has no settled event; the escaped tail alone carries >5% of initial potential as current kinetic energy and its free-flight projection grows to >68%, while only the open-top subset has a possible return; no physical 5s settled result can be inferred",
        },
        "extension_recommendation": {
            "status": "do_not_extend_current_scope_from_this_projection",
            "reason": "the tail-only 5s envelope needs approximately 4.85 billion cells and about 72.5 GiB of cell memory with a 0.5 m margin under the registered scaling, and the model predicts open-top re-entry plus omitted wall/contact physics",
            "next_independent_candidate": "F2_resting_fill_static_hold_x_v1",
        },
    }
    _write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-time-s", type=float, default=TARGET_TIME_S)
    args = parser.parse_args()
    report = analyze(args.prepared, args.product, args.output, target_time_s=args.target_time_s)
    print(json.dumps({
        "schema": report["schema"],
        "qualification_claim": report["qualification_claim"],
        "tail_particle_count": report["tail_selection"]["particle_count"],
        "tail_mass_fraction": report["tail_selection"]["mass_fraction_of_native"],
        "projected_tail_bounds_m": report["projection_to_target"]["position_bounds_m"],
        "closed_face_event_count": report["future_finite_wall_recontact"]["closed_face_event_count"],
        "open_top_entry_count": report["future_finite_wall_recontact"]["open_top_entry_count"],
        "projected_memory_gib_with_margin": report["cell_memory_estimate"]["projected_union_with_0p5m_margin"]["estimated_gpu_cell_memory_gib"],
        "status": report["extension_recommendation"]["status"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
