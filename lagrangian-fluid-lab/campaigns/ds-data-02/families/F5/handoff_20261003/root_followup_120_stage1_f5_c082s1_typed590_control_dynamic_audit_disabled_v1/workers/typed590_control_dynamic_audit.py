#!/usr/bin/env python3
"""Read-only typed590 control/state diagnostic for F5 C082S1.

The registered Root142 CPU job opens the producer-attested typed590 H5 and the
producer-attested transformed motion table.  It reports every saved state and
focus states around the forcing schedule: moving-particle center/displacement/
velocity, control interpolation residual, fluid velocity, UID/type/finite
integrity, and a source-Mk50 footprint free-surface extent proxy.

This worker does not modify arrays, resample trajectories, certify runup, grant
precision or Q-N, or create case credit.  The source preparation never opens
H5/DAT; the worker reads them only when Root explicitly enables the disabled
request after independent review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

import h5py
import numpy as np

SCHEMA = "ds02.f5.c082s1.typed590-control-dynamic-audit.fresh120.v1"
BINDING_SCHEMA = "ds02.f5.c082s1.typed590-control-dynamic-binding.fresh120.v1"
CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
FLUID_TYPE = 3
MOVING_TYPE = 1
EXPECTED_FRAMES = 801
EXPECTED_PARTICLES = 194427
EXPECTED_FLUID = 31658
EXPECTED_MOVING = 4210
EXPECTED_FIXED = 158559
EXPECTED_FLOATING = 0
BED_X_BOUNDS = (-0.2, 4.8)
BED_Y_BOUNDS = (-0.22, 0.22)
BED_NODES_XZ = np.asarray(((-0.2, 0.0), (2.0, 0.0), (3.0, 0.28),
                           (3.6, 0.448), (3.9, 0.448), (4.4, 0.05),
                           (4.8, 0.05)), dtype=np.float64)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def bound(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("<")


def finite_vec(value: np.ndarray) -> bool:
    return bool(np.isfinite(value).all())


def uid_diff(expected: np.ndarray, observed: np.ndarray) -> tuple[int, int]:
    exp = np.asarray(expected, dtype=np.uint64).reshape(-1)
    obs = np.asarray(observed, dtype=np.uint64).reshape(-1)
    missing = np.setdiff1d(exp, obs, assume_unique=True)
    extra = np.setdiff1d(obs, exp, assume_unique=True)
    return int(missing.size), int(extra.size)


def profile_z(x: np.ndarray) -> np.ndarray:
    result = np.full(x.shape, np.nan, dtype=np.float64)
    inside = (x >= BED_X_BOUNDS[0]) & (x <= BED_X_BOUNDS[1])
    result[inside] = np.interp(x[inside], BED_NODES_XZ[:, 0], BED_NODES_XZ[:, 1])
    return result


def metadata_records(binding: Mapping[str, Any]) -> list[dict[str, str]]:
    checked: list[dict[str, str]] = []
    for item in binding.get("metadata_records", []):
        require(isinstance(item, Mapping), "metadata_records entry must be an object")
        path = Path(str(item["path"])).resolve()
        expected = str(item["sha256"])
        require(path.is_file(), f"metadata file missing: {path}")
        require(sha256_file(path) == expected, f"metadata SHA mismatch: {path}")
        checked.append({"role": str(item["role"]), "path": str(path), "sha256": expected})
    require(checked, "metadata_records empty")
    return checked


def verify_binding(binding: Mapping[str, Any], tag: str) -> dict[str, Any]:
    require(binding.get("schema") == BINDING_SCHEMA, "binding schema mismatch")
    require(binding.get("tag") == tag and binding.get("case_id") == CASE_ID, "case identity mismatch")
    require(binding.get("expected_frames") == EXPECTED_FRAMES, "frame count contract mismatch")
    require(binding.get("expected_particle_axis") == EXPECTED_PARTICLES, "particle axis contract mismatch")
    counts = binding.get("expected_counts")
    require(counts == {"total": EXPECTED_PARTICLES, "fixed": EXPECTED_FIXED,
                        "moving": EXPECTED_MOVING, "fluid": EXPECTED_FLUID,
                        "floating": EXPECTED_FLOATING}, "count contract mismatch")
    h5 = Path(str(binding["trajectory_h5"])).resolve()
    motion = Path(str(binding["motion_file"])).resolve()
    require(h5.is_file() and motion.is_file(), "producer H5/motion path missing")
    require(bound(binding.get("trajectory_h5_sha256")) and bound(binding.get("motion_file_sha256")), "producer payload SHA missing")
    conversion = load_json(Path(str(binding["conversion_report"])))
    require(conversion.get("conversion_status") == "completed", "typed conversion is not completed")
    require(conversion.get("output_hdf5") == str(h5), "typed H5 path mismatch")
    require(conversion.get("output_sha256") == binding["trajectory_h5_sha256"], "typed H5 producer SHA mismatch")
    require(conversion.get("frames") == EXPECTED_FRAMES and conversion.get("particles") == EXPECTED_PARTICLES, "typed counts mismatch")
    solver_dim = conversion.get("solver_dimension", {})
    require(isinstance(solver_dim, Mapping) and solver_dim.get("solver_dimension") == 3 and solver_dim.get("xml_data2d") == "false", "typed dimension mismatch")
    identity = conversion.get("typed_identity", {})
    require(50 in identity.get("observed_mks", []) and {0, 1, 3}.issubset(set(identity.get("observed_types", []))), "typed Mk/type identity mismatch")
    motion_report = load_json(Path(str(binding["motion_transform_report"])))
    require(motion_report.get("status") == "completed" and motion_report.get("rows") == 641, "motion transform producer report mismatch")
    require(motion_report.get("output_motion") == str(motion), "motion path mismatch")
    require(motion_report.get("output_motion_sha256") == binding["motion_file_sha256"], "motion producer SHA mismatch")
    require(float(motion_report.get("time_start_s")) == 0.0 and float(motion_report.get("time_end_s")) == 16.0, "motion time window mismatch")
    require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_mkbound") == 40, "Mk mapping mismatch")
    require(bound(binding.get("source_h5_condition_sha256")) and binding.get("source_h5_scope_schema") == "legacy-owner-scope.v0", "legacy H5 scope binding missing")
    require(binding.get("full_visual_gate") == "WAIT", "visual gate was loosened")
    return {"conversion": conversion, "motion_report": motion_report, "metadata_records": metadata_records(binding), "trajectory_h5": str(h5), "motion_file": str(motion)}


def control_table(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    table = np.loadtxt(path, ndmin=2)
    require(table.ndim == 2 and table.shape[1] == 2 and table.shape[0] == 641, "motion table must be 641x2")
    require(np.isfinite(table).all(), "motion table contains nonfinite values")
    times = np.asarray(table[:, 0], dtype=np.float64)
    displacement = np.asarray(table[:, 1], dtype=np.float64) - float(table[0, 1])
    require(np.all(np.diff(times) > 0), "motion times are not strictly increasing")
    require(abs(float(times[0])) <= 1e-9 and abs(float(times[-1]) - 16.0) <= 1e-6, "motion time range mismatch")
    velocity = np.gradient(displacement, times)
    return times, displacement, velocity


def surface_summary(position: np.ndarray, fluid_mask: np.ndarray) -> dict[str, Any]:
    finite = fluid_mask & np.isfinite(position).all(axis=1)
    in_xy = finite & (position[:, 0] >= BED_X_BOUNDS[0]) & (position[:, 0] <= BED_X_BOUNDS[1]) & (position[:, 1] >= BED_Y_BOUNDS[0]) & (position[:, 1] <= BED_Y_BOUNDS[1])
    pz = profile_z(position[:, 0])
    above = in_xy & (position[:, 2] >= pz)
    if not above.any():
        return {"count": 0, "extent_m": None, "shoreward_reach_x_m": None, "surface_z95_m": None, "surface_zmax_m": None}
    points = position[above]
    return {
        "count": int(above.sum()),
        "extent_m": {"min": [float(x) for x in points.min(axis=0)], "max": [float(x) for x in points.max(axis=0)]},
        "shoreward_reach_x_m": float(points[:, 0].max()),
        "surface_z95_m": float(np.percentile(points[:, 2], 95.0)),
        "surface_zmax_m": float(points[:, 2].max()),
    }


def frame_summary(index: int, time_s: float, position: np.ndarray, velocity: np.ndarray, valid: np.ndarray, particle_type: np.ndarray, particle_ids: np.ndarray, initial_fluid_mask: np.ndarray, initial_moving_mask: np.ndarray, initial_fluid_ids: np.ndarray, initial_moving_center: np.ndarray, initial_fluid_position: np.ndarray, initial_moving_position: np.ndarray, control_dx: float, control_vx: float) -> dict[str, Any]:
    valid = np.asarray(valid).reshape(-1).astype(bool, copy=False)
    particle_type = np.asarray(particle_type).reshape(-1)
    position = np.asarray(position, dtype=np.float64)
    velocity = np.asarray(velocity, dtype=np.float64)
    particle_ids = np.asarray(particle_ids, dtype=np.uint64).reshape(-1)
    fluid = valid & (particle_type == FLUID_TYPE)
    moving = valid & (particle_type == MOVING_TYPE)
    finite_position = np.isfinite(position).all(axis=1)
    finite_velocity = np.isfinite(velocity).all(axis=1)
    fluid_finite = fluid & finite_position & finite_velocity
    moving_finite = moving & finite_position & finite_velocity
    fluid_ids = particle_ids[fluid]
    missing_fluid, extra_fluid = uid_diff(initial_fluid_ids, fluid_ids)
    if moving_finite.any():
        moving_center = position[moving_finite].mean(axis=0)
        moving_velocity_center = velocity[moving_finite].mean(axis=0)
        moving_displacement = moving_center - initial_moving_center
        moving_speed = np.linalg.norm(velocity[moving_finite], axis=1)
        moving_dx_error = float(moving_displacement[0] - control_dx)
        moving_vx_error = float(moving_velocity_center[0] - control_vx)
        moving_disp_norm = float(np.linalg.norm(moving_displacement))
        moving_position_spread = float(np.ptp(position[moving_finite, 0]))
    else:
        moving_center = np.full(3, np.nan)
        moving_velocity_center = np.full(3, np.nan)
        moving_displacement = np.full(3, np.nan)
        moving_speed = np.asarray([], dtype=np.float64)
        moving_dx_error = math.nan
        moving_vx_error = math.nan
        moving_disp_norm = math.nan
        moving_position_spread = math.nan
    if fluid_finite.any():
        fluid_velocity = velocity[fluid_finite]
        fluid_speed = np.linalg.norm(fluid_velocity, axis=1)
        same_initial_fluid = initial_fluid_mask & fluid & finite_position
        fluid_displacement = position[same_initial_fluid] - initial_fluid_position[same_initial_fluid]
        fluid_disp_norm = float(np.linalg.norm(fluid_displacement, axis=1).max()) if fluid_displacement.size else 0.0
        fluid_mean_velocity = fluid_velocity.mean(axis=0)
        fluid_speed_summary = {"mean_mps": float(fluid_speed.mean()), "p95_mps": float(np.percentile(fluid_speed, 95.0)), "max_mps": float(fluid_speed.max())}
        fluid_max_abs_velocity_component_mps = float(np.abs(fluid_velocity).max())
    else:
        fluid_disp_norm = math.nan
        fluid_mean_velocity = np.full(3, np.nan)
        fluid_speed_summary = {"mean_mps": math.nan, "p95_mps": math.nan, "max_mps": math.nan}
        fluid_max_abs_velocity_component_mps = math.nan
    current_finite_active = valid & finite_position & finite_velocity
    return {
        "frame": int(index),
        "time_s": float(time_s),
        "control": {"prescribed_dx_m": float(control_dx), "prescribed_vx_mps": float(control_vx)},
        "identity": {"valid_fluid_count": int(fluid.sum()), "valid_moving_count": int(moving.sum()), "finite_fluid_count": int(fluid_finite.sum()), "finite_moving_count": int(moving_finite.sum()), "missing_initial_fluid_uid_count": missing_fluid, "unexpected_fluid_uid_count": extra_fluid, "nonfinite_active_position_or_velocity_count": int((valid & ~finite_position).sum() + (valid & ~finite_velocity).sum())},
        "moving": {"center_m": [float(x) for x in moving_center], "center_displacement_m": [float(x) for x in moving_displacement], "center_velocity_mps": [float(x) for x in moving_velocity_center], "center_displacement_norm_m": moving_disp_norm, "center_control_error_m": moving_dx_error, "center_velocity_control_error_mps": moving_vx_error, "position_x_spread_m": moving_position_spread, "particle_speed_max_mps": float(moving_speed.max()) if moving_speed.size else math.nan},
        "fluid": {"mean_velocity_mps": [float(x) for x in fluid_mean_velocity], "speed": fluid_speed_summary, "max_abs_velocity_component_mps": fluid_max_abs_velocity_component_mps, "max_displacement_from_frame0_m": fluid_disp_norm},
        "free_surface_extent": surface_summary(position, fluid),
        "active_finite_count": int(current_finite_active.sum()),
    }


def run(binding: Mapping[str, Any]) -> dict[str, Any]:
    tag = str(binding["tag"])
    verified = verify_binding(binding, tag)
    h5_path = Path(verified["trajectory_h5"])
    motion_path = Path(verified["motion_file"])
    control_t, control_dx_values, control_vx_values = control_table(motion_path)
    focus = {int(item["frame"]): str(item["reason"]) for item in binding["focus_frames"]}
    require(len(focus) == 7 and all(0 <= frame < EXPECTED_FRAMES for frame in focus), "focus frame contract mismatch")
    rows: list[dict[str, Any]] = []
    with h5py.File(h5_path, "r") as h5:
        required = ("time", "particle_id", "valid", "position", "velocity", "type", "mk")
        for name in required:
            require(name in h5, f"typed H5 dataset missing: {name}")
        times_ds = h5["time"]
        ids = np.asarray(h5["particle_id"][...], dtype=np.uint64).reshape(-1)
        require(times_ds.shape == (EXPECTED_FRAMES,), "typed H5 time shape mismatch")
        require(ids.size == EXPECTED_PARTICLES and np.unique(ids).size == EXPECTED_PARTICLES, "typed particle IDs are not a unique full axis")
        position_ds = h5["position"]
        velocity_ds = h5["velocity"]
        valid_ds = h5["valid"]
        type_ds = h5["type"]
        mk_ds = h5["mk"]
        require(position_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES, 3), "position shape mismatch")
        require(velocity_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES, 3), "velocity shape mismatch")
        require(valid_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES), "valid shape mismatch")
        require(type_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES), "type shape mismatch")
        require(mk_ds.shape == (EXPECTED_FRAMES, EXPECTED_PARTICLES), "mk shape mismatch")
        times = np.asarray(times_ds[...], dtype=np.float64)
        require(np.isfinite(times).all() and np.all(np.diff(times) > 0), "typed time axis is not finite/increasing")
        initial_valid = np.asarray(valid_ds[0, ...]).reshape(-1).astype(bool, copy=False)
        initial_type = np.asarray(type_ds[0, ...]).reshape(-1)
        initial_mk = np.asarray(mk_ds[0, ...]).reshape(-1)
        initial_position = np.asarray(position_ds[0, ...], dtype=np.float64)
        initial_velocity = np.asarray(velocity_ds[0, ...], dtype=np.float64)
        initial_fluid_mask = initial_valid & (initial_type == FLUID_TYPE)
        initial_moving_mask = initial_valid & (initial_type == MOVING_TYPE)
        initial_fluid_ids = ids[initial_fluid_mask]
        require(int(initial_fluid_mask.sum()) == EXPECTED_FLUID and int(initial_moving_mask.sum()) == EXPECTED_MOVING, "initial typed populations mismatch")
        require(int((initial_valid & (initial_type == 0)).sum()) == EXPECTED_FIXED and int((initial_valid & (initial_type == 2)).sum()) == EXPECTED_FLOATING, "initial fixed/floating populations mismatch")
        require(int((initial_mk == 50).sum()) > 0, "native Mk50 bed marker absent at frame zero")
        initial_moving_center = initial_position[initial_moving_mask].mean(axis=0)
        require(finite_vec(initial_position[initial_valid]) and finite_vec(initial_velocity[initial_valid]), "initial active state is nonfinite")
        for index, time_s in enumerate(times):
            control_dx = float(np.interp(time_s, control_t, control_dx_values))
            control_vx = float(np.interp(time_s, control_t, control_vx_values))
            position = np.asarray(position_ds[index, ...], dtype=np.float64)
            velocity = np.asarray(velocity_ds[index, ...], dtype=np.float64)
            valid = np.asarray(valid_ds[index, ...]).reshape(-1).astype(bool, copy=False)
            particle_type = np.asarray(type_ds[index, ...]).reshape(-1)
            row = frame_summary(index, float(time_s), position, velocity, valid, particle_type, ids, initial_fluid_mask, initial_moving_mask, initial_fluid_ids, initial_moving_center, initial_position, initial_position, control_dx, control_vx)
            if index in focus:
                row["focus_reason"] = focus[index]
            rows.append(row)
    focus_rows = [row for row in rows if row["frame"] in focus]
    max_alignment = max(abs(float(row["moving"]["center_control_error_m"])) for row in rows if math.isfinite(float(row["moving"]["center_control_error_m"])))
    max_velocity_alignment = max(abs(float(row["moving"]["center_velocity_control_error_mps"])) for row in rows if math.isfinite(float(row["moving"]["center_velocity_control_error_mps"])))
    max_fluid_displacement = max(float(row["fluid"]["max_displacement_from_frame0_m"]) for row in rows if math.isfinite(float(row["fluid"]["max_displacement_from_frame0_m"])))
    max_fluid_speed = max(float(row["fluid"]["speed"]["max_mps"]) for row in rows if math.isfinite(float(row["fluid"]["speed"]["max_mps"])))
    surface_x = [float(row["free_surface_extent"]["shoreward_reach_x_m"]) for row in rows if row["free_surface_extent"]["shoreward_reach_x_m"] is not None]
    surface_z = [float(row["free_surface_extent"]["surface_z95_m"]) for row in rows if row["free_surface_extent"]["surface_z95_m"] is not None]
    return {
        "schema": SCHEMA,
        "status": "completed",
        "diagnostic_only": True,
        "tag": tag,
        "case_id": CASE_ID,
        "candidate_id": binding["candidate_id"],
        "condition_id": binding["condition_id"],
        "inputs": {"trajectory_h5": str(h5_path), "trajectory_h5_sha256": binding["trajectory_h5_sha256"], "motion_file": str(motion_path), "motion_file_sha256": binding["motion_file_sha256"], "typed_conversion_report": binding["conversion_report"], "typed_conversion_report_sha256": binding["conversion_report_sha256"], "motion_transform_report": binding["motion_transform_report"], "motion_transform_report_sha256": binding["motion_transform_report_sha256"]},
        "typed590_contract": {"frames": EXPECTED_FRAMES, "particle_axis": EXPECTED_PARTICLES, "fluid": EXPECTED_FLUID, "moving": EXPECTED_MOVING, "fixed": EXPECTED_FIXED, "floating": EXPECTED_FLOATING, "solver_dimension": 3, "native_bed_mk": 50, "source_mkbound": 40, "time_first_s": rows[0]["time_s"], "time_last_s": rows[-1]["time_s"]},
        "control_application_diagnostic": {"motion_rows": 641, "motion_time_range_s": [float(control_t[0]), float(control_t[-1])], "motion_dx_range_m": [float(control_dx_values.min()), float(control_dx_values.max())], "motion_dx_peak_to_peak_m": float(np.ptp(control_dx_values)), "max_abs_moving_center_control_error_m": max_alignment, "max_abs_moving_center_velocity_control_error_mps": max_velocity_alignment, "measured_control_and_particle_state_are_reported_not_accepted": True},
        "dynamic_state_diagnostic": {"max_fluid_displacement_m": max_fluid_displacement, "max_fluid_speed_mps": max_fluid_speed, "surface_shoreward_reach_range_m": [min(surface_x), max(surface_x)] if surface_x else None, "surface_z95_range_m": [min(surface_z), max(surface_z)] if surface_z else None, "full_saved_state_rows": len(rows), "uid_loss_or_nonfinite_is_reported_per_frame": True},
        "focus_frame_reports": focus_rows,
        "all_frame_summaries": rows,
        "interpretation": {"control_path": "measured from producer motion table and typed590 moving/fluid state", "visual_runup_event": "not evaluated by this worker", "full801_visual_gate": "WAIT", "precision_granted": False, "q_n_granted": False, "case_increment": 0, "thresholds": "no penetration or precision threshold is changed by this diagnostic"},
        "source_arrays_modified": False,
        "source_arrays_dropped_or_masked": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binding = load_json(args.binding)
    report = run(binding)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"schema": report["schema"], "status": report["status"], "tag": report["tag"], "frames": len(report["all_frame_summaries"]), "diagnostic_only": True}))

if __name__ == "__main__":
    main()
