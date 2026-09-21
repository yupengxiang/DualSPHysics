#!/usr/bin/env python3
"""Re-audit moving-cup saved chords with full body-frame interpolation.

The first F2 moving-cup entry audit used a scalar normal displacement for all
coordinates when reconstructing a saved-frame chord.  This report retains
that historical result, recomputes each chord with the complete displacement
vector, and records the prescribed rotating-wall kinematics and boundary
shell dimensions.  It never edits a solver product or relaunches a case.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts.core_f2_qualification import (
    ANGLE_DEGREES,
    F2_WALL_TOLERANCE_M,
    MOTION_START_S,
    _closed_face_entry_events,
    _face_normal_body,
    _finite_box_spec,
    _legacy_scalar_closed_face_entry_events,
    _motion_angular_velocity_rad_s,
    _open_top_crossing,
    body_positions,
    cup_world_from_body,
    motion_angle,
)


SCHEMA = "core.f2.moving_cup_entry_forensics.v1"
FACES = ("bottom", "left", "right", "front", "back")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def _face_axis(face: str) -> tuple[int, int]:
    return {"bottom": (2, 0), "left": (0, 0), "right": (0, 1), "front": (1, 0), "back": (1, 1)}[face]


def _body_bounds(config: dict) -> tuple[np.ndarray, np.ndarray]:
    low = np.asarray(config["cup"]["low"], dtype=float)
    high = low + np.asarray(config["cup"]["size"], dtype=float)
    return low, high


def _event_detail(
    *,
    classifier: str,
    event: dict,
    frame_index: int,
    times: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    particle_ids: np.ndarray,
    local_index: int,
    previous_body: np.ndarray,
    current_body: np.ndarray,
    config: dict,
    low: np.ndarray,
    high: np.ndarray,
    first_top_exit: dict[int, int],
) -> dict:
    face = str(event["face"])
    axis, side = _face_axis(face)
    plane = float(low[axis] if side == 0 else high[axis])
    previous = previous_body[local_index]
    current = current_body[local_index]
    axis_delta = float(current[axis] - previous[axis])
    fraction = float((plane - previous[axis]) / axis_delta)
    full_crossing = previous + fraction * (current - previous)
    scalar_crossing = previous + fraction * np.full(3, axis_delta, dtype=float)
    time_s = float(times[frame_index])
    duration_s = float(config["parameter"]["value"])
    angle = motion_angle(time_s, duration_s)
    transform = cup_world_from_body(angle)
    angular_velocity = _motion_angular_velocity_rad_s(time_s, duration_s)
    omega_body = np.asarray([0.0, angular_velocity, 0.0])
    pivot = np.asarray([0.0, 0.0, 0.65])
    wall_velocity = transform[:3, :3] @ np.cross(omega_body, full_crossing - pivot)
    outward_normal = transform[:3, :3] @ _face_normal_body(face)
    # ``local_index`` indexes the common-mask arrays; the global particle
    # index is supplied by the caller through ``event['global_particle_index']``.
    global_index = int(event["global_particle_index"])
    particle_velocity = velocities[frame_index, global_index]
    tangential = [index for index in range(3) if index != axis]
    true_tangential_inside = bool(
        np.all(full_crossing[tangential] >= low[tangential] - F2_WALL_TOLERANCE_M)
        and np.all(full_crossing[tangential] <= high[tangential] + F2_WALL_TOLERANCE_M)
    )
    top_frame = first_top_exit.get(int(particle_ids[global_index]))
    prior_top_frame = top_frame if top_frame is not None and top_frame < frame_index else None
    return {
        "classifier": classifier,
        "frame_index": int(frame_index),
        "time_s": time_s,
        "particle_id": int(particle_ids[global_index]),
        "face": face,
        "fraction": float(event["fraction"]),
        "previous_world_m": positions[frame_index - 1, global_index].tolist(),
        "current_world_m": positions[frame_index, global_index].tolist(),
        "previous_body_m": previous.tolist(),
        "current_body_m": current.tolist(),
        "legacy_scalar_crossing_body_m": scalar_crossing.tolist(),
        "full_vector_crossing_body_m": full_crossing.tolist(),
        "previous_velocity_m_s": velocities[frame_index - 1, global_index].tolist(),
        "current_velocity_m_s": particle_velocity.tolist(),
        "previous_inside_open_box": bool(np.all((previous > low) & (previous < high))),
        "current_inside_open_box": bool(np.all((current > low) & (current < high))),
        "full_crossing_tangential_inside": true_tangential_inside,
        "first_prior_open_top_exit_frame": int(prior_top_frame) if prior_top_frame is not None else None,
        "first_prior_open_top_exit_time_s": float(times[prior_top_frame]) if prior_top_frame is not None else None,
        "prescribed_angle_degrees": float(angle),
        "prescribed_angular_velocity_y_rad_s": float(angular_velocity),
        "wall_velocity_at_full_crossing_m_s": wall_velocity.tolist(),
        "world_outward_normal": outward_normal.tolist(),
        "relative_outward_normal_velocity_m_s": float(np.dot(particle_velocity - wall_velocity, outward_normal)),
        "closed_face_signed_distance_previous_m": float(previous[axis] - plane),
        "closed_face_signed_distance_current_m": float(current[axis] - plane),
        "tangential_signed_distance_full_crossing_m": {
            "axis_0": float(full_crossing[0] - low[0]) if axis != 0 else None,
            "axis_1": float(full_crossing[1] - low[1]) if axis != 1 else None,
            "axis_2": float(full_crossing[2] - low[2]) if axis != 2 else None,
        },
    }


def _vtk_wall_summary(prepared: dict) -> dict:
    """Summarize generated shell and retained H2 normal-surface evidence."""
    result = {
        "dp_m": float(prepared["config"]["dp_m"]),
        "main_boundary_layers_vdp": [0, 1, 2],
        "main_boundary_particle_shell_span_m": float(3.0 * prepared["config"]["dp_m"]),
        "normal_construction_layer_vdp": -0.5,
        "normal_search_distance_h": 3.0,
        "svshapes": True,
        "nominal_cup_box_m": {
            "low": [float(v) for v in prepared["config"]["cup"]["low"]],
            "high": [float(a + b) for a, b in zip(prepared["config"]["cup"]["low"], prepared["config"]["cup"]["size"])],
        },
        "generated_boundary_vtk": None,
        "mdbc_reference": None,
    }
    try:
        from scripts.r4_f6_mdbc_runtime_zero_normal_audit import read_binary_vtk

        prefix = Path(prepared["generated_prefix"])
        bound_path = prefix.with_name(prefix.name + "_Bound.vtk")
        if bound_path.is_file():
            parsed = read_binary_vtk(bound_path)
            points = np.asarray(parsed["points"], dtype=float)
            mk = np.asarray(parsed.get("point_data", {}).get("Mk", []))
            target = np.asarray(prepared["config"]["cup"]["low"], dtype=float) + 0.5 * np.asarray(prepared["config"]["cup"]["size"], dtype=float)
            candidates = []
            for value in np.unique(mk):
                group = points[mk == value]
                if len(group):
                    candidates.append((float(np.linalg.norm(group.mean(axis=0) - target)), int(value), group))
            if candidates:
                _, mk_value, group = min(candidates, key=lambda item: item[0])
                result["generated_boundary_vtk"] = {
                    "path": str(bound_path.resolve()),
                    "sha256": core_cfd.digest(bound_path),
                    "generated_mk": mk_value,
                    "point_count": int(len(group)),
                    "cup_boundary_bbox_m": [group.min(axis=0).tolist(), group.max(axis=0).tolist()],
                }
        h2_dir = Path(__file__).resolve().parents[1] / "campaigns/core-v1/cfd/prepared/F2_H2_mdbc_boundary_repair_canary_v2"
        h2_prepared = h2_dir / "prepared.json"
        h2_hdp = next(h2_dir.glob("generated/*_hdp_Actual.vtk"), None)
        if h2_prepared.is_file() and h2_hdp is not None and h2_hdp.is_file():
            h2 = json.loads(h2_prepared.read_text())
            hdp = read_binary_vtk(h2_hdp)
            cell_mk = np.asarray(hdp.get("cell_data", {}).get("Mk", []))
            target = np.asarray(prepared["config"]["cup"]["low"], dtype=float) + 0.5 * np.asarray(prepared["config"]["cup"]["size"], dtype=float)
            surface_candidates = []
            for value in np.unique(cell_mk):
                cells = [hdp["polygons"][index] for index in np.flatnonzero(cell_mk == value)]
                if cells:
                    ids = np.unique(np.concatenate(cells))
                    group = np.asarray(hdp["points"])[ids]
                    surface_candidates.append((float(np.linalg.norm(group.mean(axis=0) - target)), int(value), group))
            if surface_candidates:
                _, mk_value, group = min(surface_candidates, key=lambda item: item[0])
                result["mdbc_reference"] = {
                    "prepared": str(h2_prepared.resolve()),
                    "prepared_sha256": core_cfd.digest(h2_prepared),
                    "normal_surface_vtk": str(h2_hdp.resolve()),
                    "normal_surface_sha256": core_cfd.digest(h2_hdp),
                    "generated_mk": mk_value,
                    "surface_point_count": int(len(group)),
                    "surface_bbox_m": [group.min(axis=0).tolist(), group.max(axis=0).tolist()],
                    "normal_count": int(h2.get("native_initial", {}).get("normal_count", 0)),
                    "zero_boundary_normals": int(h2.get("native_initial", {}).get("zero_boundary_normals", -1)),
                    "normal_preflight_pass": bool(h2.get("static_diagnostic_preflight", {}).get("mdbc_normals_complete_nonzero", False)),
                    "solver_arguments": h2.get("solver_arguments", []),
                }
    except (OSError, ValueError, KeyError, TypeError):
        result["generated_boundary_vtk"] = {"status": "unavailable"}
    return result


def _settled_spill_diagnostic(observations_path: Path | None) -> dict | None:
    if observations_path is None or not Path(observations_path).is_file():
        return None
    observations = json.loads(Path(observations_path).read_text())
    times = np.asarray(observations["time_s"], dtype=float)
    motion_complete = float(observations["event_times_s"]["motion_complete"])
    post_motion = times >= motion_complete
    initial_potential = float(observations["initial_potential_energy_relative_to_cup_floor_J"])
    settle_ke_limit = 0.05
    settle_speed_limit = 0.10
    outside = np.asarray(observations["outside_observation_mass_fraction"], dtype=float)
    speed = np.asarray(observations["speed_p95_m_s"], dtype=float)
    kinetic = np.asarray(observations["kinetic_energy_over_initial_potential"], dtype=float)
    final = {
        "time_s": float(times[-1]),
        "outside_observation_mass_fraction": float(outside[-1]),
        "speed_p95_m_s": float(speed[-1]),
        "kinetic_energy_over_initial_potential": float(kinetic[-1]),
        "kinetic_energy_J": float(kinetic[-1] * initial_potential),
    }
    post_motion_min = {
        "outside_observation_mass_fraction": float(np.min(outside[post_motion])),
        "speed_p95_m_s": float(np.min(speed[post_motion])),
        "kinetic_energy_over_initial_potential": float(np.min(kinetic[post_motion])),
    }
    return {
        "observations": str(Path(observations_path).resolve()),
        "observations_sha256": core_cfd.digest(observations_path),
        "registered_settle_gate": {
            "speed_p95_max_m_s": settle_speed_limit,
            "kinetic_energy_fraction_max": settle_ke_limit,
            "hold_s": 0.20,
            "global_initial_native_mass_denominator": True,
            "survivor_renormalization": False,
        },
        "event_times_s": observations["event_times_s"],
        "final": final,
        "post_motion_minima": post_motion_min,
        "settled_observed": observations["event_times_s"].get("settled") is not None,
        "spill_observed": observations["event_times_s"].get("spill_or_escape") is not None,
        "assessment": "right_censored_or_unreachable_under_current_observation_geometry; escaped native mass remains in the global denominator and is not deleted",
        "independent_task_candidates": [
            {
                "id": "F2_closed_catchment_geometry_v1",
                "kind": "new_physical_geometry_scope",
                "proposal": "declare and model a finite catchment that can physically receive post-cup spill before a settled event",
                "qualification_status": "separate scope; do not retrofit current F2 geometry",
            },
            {
                "id": "F2_destination_aware_settled_observer_v1",
                "kind": "new_observer_scope",
                "proposal": "pre-register compartment-wise settling while retaining global native mass and spill integrity as separate gates",
                "qualification_status": "separate observer task; no threshold change in current scope",
            },
        ],
    }


def analyze(
    prepared_path: Path,
    trajectory_path: Path,
    output: Path | None = None,
    observations_path: Path | None = None,
) -> dict:
    prepared_path = Path(prepared_path).resolve()
    trajectory_path = Path(trajectory_path).resolve()
    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    spec = _finite_box_spec(config["cup"], FACES, ("top",))
    low, high = _body_bounds(config)
    legacy_events: list[dict] = []
    corrected_events: list[dict] = []
    top_exit_count = 0
    top_entry_count = 0
    first_top_exit: dict[int, int] = {}
    with h5py.File(trajectory_path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        particle_ids = np.asarray(handle["particle_id"][:])
        for frame_index in range(1, len(times)):
            common = valid[frame_index - 1] & valid[frame_index]
            if not common.any():
                continue
            common_indices = np.flatnonzero(common)
            previous_body = body_positions(
                positions[frame_index - 1, common],
                cup_world_from_body(motion_angle(float(times[frame_index - 1]), float(config["parameter"]["value"]))),
            )
            current_body = body_positions(
                positions[frame_index, common],
                cup_world_from_body(motion_angle(float(times[frame_index]), float(config["parameter"]["value"]))),
            )
            top_exits = _open_top_crossing(previous_body, current_body, spec, F2_WALL_TOLERANCE_M)
            top_exit_count += int(top_exits.sum())
            for local_index in np.flatnonzero(top_exits):
                particle_id = int(particle_ids[common_indices[local_index]])
                first_top_exit.setdefault(particle_id, frame_index)
            top_entries = np.zeros(len(previous_body), dtype=bool)
            # The historical product audit already records open-top entries;
            # recompute only their count here without treating them as faults.
            dz = current_body[:, 2] - previous_body[:, 2]
            top_entries |= (dz < 0.0) & (previous_body[:, 2] >= high[2] - F2_WALL_TOLERANCE_M) & (current_body[:, 2] < high[2] - F2_WALL_TOLERANCE_M)
            if top_entries.any():
                fraction = (high[2] - previous_body[:, 2]) / np.where(np.abs(dz) > 1e-15, dz, 1.0)
                crossing = previous_body + fraction[:, None] * (current_body - previous_body)
                tangential = [0, 1]
                top_entries &= np.all((crossing[:, tangential] >= low[tangential] - F2_WALL_TOLERANCE_M) & (crossing[:, tangential] <= high[tangential] + F2_WALL_TOLERANCE_M), axis=1)
            top_entry_count += int(top_entries.sum())
            historical = _legacy_scalar_closed_face_entry_events(previous_body, current_body, spec, F2_WALL_TOLERANCE_M)
            corrected = _closed_face_entry_events(previous_body, current_body, spec, F2_WALL_TOLERANCE_M)
            for event in historical:
                event = dict(event)
                event["global_particle_index"] = int(common_indices[event["point_index"]])
                legacy_events.append(_event_detail(
                    classifier="legacy_scalar_chord",
                    event=event,
                    frame_index=frame_index,
                    times=times,
                    positions=positions,
                    velocities=velocities,
                    particle_ids=particle_ids,
                    local_index=int(event["point_index"]),
                    previous_body=previous_body,
                    current_body=current_body,
                    config=config,
                    low=low,
                    high=high,
                    first_top_exit=first_top_exit,
                ))
            for event in corrected:
                event = dict(event)
                event["global_particle_index"] = int(common_indices[event["point_index"]])
                corrected_events.append(_event_detail(
                    classifier="full_vector_chord",
                    event=event,
                    frame_index=frame_index,
                    times=times,
                    positions=positions,
                    velocities=velocities,
                    particle_ids=particle_ids,
                    local_index=int(event["point_index"]),
                    previous_body=previous_body,
                    current_body=current_body,
                    config=config,
                    low=low,
                    high=high,
                    first_top_exit=first_top_exit,
                ))
    all_legacy_pseudo = bool(legacy_events) and all(not item["full_crossing_tangential_inside"] for item in legacy_events)
    if legacy_events and not corrected_events and all_legacy_pseudo:
        classification = "legacy_scalar_interpolation_false_positive"
    elif corrected_events:
        classification = "full_vector_saved_chord_closed_face_entry"
    else:
        classification = "no_closed_face_entry_after_full_vector_reaudit"
    report = {
        "schema": SCHEMA,
        "created_at": _stamp(),
        "read_only": True,
        "solver_relaunched": False,
        "prepared": str(prepared_path),
        "trajectory": str(trajectory_path),
        "prepared_sha256": core_cfd.digest(prepared_path),
        "trajectory_sha256": core_cfd.digest(trajectory_path),
        "family": "F2",
        "case_id": config.get("case_id"),
        "qualification_claim": "none; moving-cup contact forensics only",
        "wall_model": _vtk_wall_summary(prepared),
        "prescribed_wall_motion": {
            "axis_body_and_native_file": [0.0, 1.0, 0.0],
            "pivot_m": [0.0, 0.0, 0.65],
            "motion_start_s": MOTION_START_S,
            "duration_s": float(config["parameter"]["value"]),
            "final_angle_degrees": ANGLE_DEGREES,
            "body_transform": "world_from_body=Ry(-motion_angle) about pivot; saved chords audited after this transform",
            "boundary_method_in_product": int(config.get("boundary_method", 1)),
        },
        "open_top_retracking": {
            "exit_count": int(top_exit_count),
            "entry_count": int(top_entry_count),
            "semantics": "top is open; exit/reentry is tracked separately and cannot authorize closed-wall entry",
        },
        "historical_scalar_classifier": {
            "entry_count": len(legacy_events),
            "events": legacy_events,
            "meaning": "retained historical result; scalar normal displacement was incorrectly applied to tangential coordinates",
        },
        "full_vector_reaudit": {
            "entry_count": len(corrected_events),
            "events": corrected_events,
            "interpolation": "crossing = previous_body + fraction * (current_body - previous_body)",
        },
        "classification": classification,
        "settled_spill_diagnostic": _settled_spill_diagnostic(observations_path),
        "conclusion": (
            "All historical cup entries are saved-chord classifier false positives: the full-vector crossing remains outside the tangential front/back interval; no dynamic mDBC repair is supported by these events."
            if all_legacy_pseudo and not corrected_events
            else "A full-vector closed-face entry remains and requires separate boundary-contact investigation."
            if corrected_events
            else "No closed-face entry remains after the full-vector re-audit."
        ),
    }
    if output is not None:
        _write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analyze(args.prepared, args.trajectory, args.output, args.observations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
