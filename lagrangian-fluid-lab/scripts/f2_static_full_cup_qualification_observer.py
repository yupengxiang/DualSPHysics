#!/usr/bin/env python3
"""Read-only observer/evaluator for the F2 static-volume candidate scope.

The evaluator consumes the v4 CPU preparation report and optional, explicitly
hash-bound HDF5 trajectory products.  It reuses the finite-wall and static
hold geometry rules from ``core_f2_resting_fill`` while adapting them to the
v4 per-cell manifest (which intentionally has no legacy ``config`` object).
It never starts a solver, creates a job, touches a queue, or mutates a ledger
or registry.  Missing and failed products remain in the registered 15-cell
denominator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_f2_resting_fill as legacy_static_observer
from scripts.core_qualification import aligned_difference
from scripts.finite_wall_audit import outside_closed_face_masks, segment_crossing_events


SCHEMA = "core.f2.static_full_cup.qualification_receipt.v1"
RUNTIME_SCHEMA = "core.f2.static_full_cup.matrix_runtime_products.v1"
ADMISSION_SCHEMA = "core.f2.static_full_cup.qualification_admission.v1"
PREPARATION_SCHEMA = "core.f2.static_full_cup.matrix_preparation.v1"
PREPARATION_AUDIT_SCHEMA = "core.f2.static_full_cup.matrix_preparation_audit.v1"
EXPECTED_CELLS = 15
WALL_TOLERANCE_M = 1e-8
GRAVITY_M_S2 = 9.81
OBSERVATION_VERSION = "F2_static_full_cup_volume_observer_v1"
OBSERVABLE_LAYOUT = (
    "cup_retention_mass_fraction",
    "outside_cup_mass_fraction",
    "speed_p95_over_registered_limit",
    "kinetic_over_initial_potential_over_registered_limit",
    "center_of_mass_x_over_cup_width",
    "center_of_mass_y_over_cup_depth",
    "center_of_mass_z_over_cup_height",
    "active_mass_fraction",
)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def verify_ref(binding: dict[str, Any], label: str, *, require_role: str | None = None) -> Path:
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise ValueError(f"{label} has no path")
    path = Path(binding["path"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if binding.get("sha256") != digest(path):
        raise ValueError(f"{label} hash mismatch: {path}")
    if binding.get("bytes") is not None and int(binding["bytes"]) != path.stat().st_size:
        raise ValueError(f"{label} byte count mismatch: {path}")
    if require_role and require_role not in str(binding.get("role", "")):
        raise ValueError(f"{label} role does not contain {require_role!r}")
    return path


def _candidate_contract(candidate_path: Path, binding: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate_path = verify_ref(binding, "candidate card")
    card = load(candidate_path)
    if card.get("schema") != "core.f2.static_full_cup_volume_candidate.v1":
        raise ValueError("candidate card schema mismatch")
    if card.get("scope_id") != "F2_static_full_cup_volume_hold_x_v1":
        raise ValueError("candidate scope mismatch")
    if card.get("qualification_only") is not True or card.get("qualified") is not False:
        raise ValueError("candidate is not qualification-only/unqualified")
    design = card.get("qualification_design", {})
    cells = list(design.get("cells", []))
    if design.get("cell_count") != EXPECTED_CELLS or len(cells) != EXPECTED_CELLS:
        raise ValueError("candidate denominator is not 15")
    if design.get("matrix_inputs_materialized") is not False or design.get("matrix_jobs_materialized") is not False:
        raise ValueError("candidate card claims matrix or jobs already materialized")
    for index, cell in enumerate(cells):
        if cell.get("index") != index or cell.get("status") != "design_only_unprepared":
            raise ValueError(f"candidate cell {index} is not the registered design-only row")
    return card, cells


def _verify_preparation(report_path: Path, audit_path: Path | None) -> dict[str, Any]:
    report_path = Path(report_path).resolve()
    report = load(report_path)
    if report.get("schema") != PREPARATION_SCHEMA:
        raise ValueError("unexpected v4 preparation report schema")
    if report.get("status") != "prepared":
        raise ValueError("v4 preparation report is incomplete; failed rows remain denominator")
    if report.get("registered_cell_count") != EXPECTED_CELLS:
        raise ValueError("v4 preparation denominator is not 15")
    if report.get("prepared_cell_count") != EXPECTED_CELLS or report.get("failed_cell_count") != 0:
        raise ValueError("v4 preparation does not contain 15 passed CPU cells")
    if report.get("unattempted_cell_count") != 0 or report.get("candidate_matrix_jobs_materialized") is not False:
        raise ValueError("v4 preparation has unattempted cells or claims jobs")
    controls = report.get("execution_controls", {})
    for key, expected in {
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "matrix_jobs_materialized": False,
        "qualification_claim_allowed": False,
    }.items():
        if controls.get(key) != expected:
            raise ValueError(f"v4 preparation execution control changed: {key}")
    card, design_cells = _candidate_contract(report_path, report["candidate_card"])

    audit = None
    if audit_path is not None:
        audit_path = Path(audit_path).resolve()
        audit = load(audit_path)
        if audit.get("schema") != PREPARATION_AUDIT_SCHEMA:
            raise ValueError("unexpected v4 preparation audit schema")
        source = audit.get("source_report", {})
        if Path(source.get("path", "")).resolve() != report_path or source.get("sha256") != digest(report_path):
            raise ValueError("preparation audit is not bound to this v4 report")
        if audit.get("fixed_failure_denominator") is not True or audit.get("prepared_cell_count") != EXPECTED_CELLS:
            raise ValueError("preparation audit does not close the 15-cell denominator")
        if audit.get("execution_controls", {}).get("registry_mutation") != 0:
            raise ValueError("preparation audit claims registry mutation")

    rows = report.get("cells", [])
    denominator = report.get("failure_denominator", {}).get("rows", [])
    if len(rows) != EXPECTED_CELLS or len(denominator) != EXPECTED_CELLS:
        raise ValueError("v4 preparation rows do not close the denominator")
    if [int(row.get("index", -1)) for row in rows] != list(range(EXPECTED_CELLS)):
        raise ValueError("v4 preparation cells are missing or reordered")
    if [int(row.get("index", -1)) for row in denominator] != list(range(EXPECTED_CELLS)):
        raise ValueError("v4 failure denominator is missing or reordered")

    prepared_by_index: dict[int, dict[str, Any]] = {}
    for row, design_cell in zip(rows, design_cells):
        index = int(row["index"])
        if row.get("case_id") != design_cell.get("case_id") or row.get("status") != "prepared":
            raise ValueError(f"v4 row {index} differs from candidate card")
        prepared_path = verify_ref({
            "path": row.get("prepared"),
            "sha256": row.get("prepared_sha256"),
            "bytes": Path(row["prepared"]).stat().st_size,
        }, f"cell {index} prepared")
        prepared = load(prepared_path)
        if prepared.get("schema") != "core.f2.static_full_cup.matrix_cell_prepared.v1":
            raise ValueError(f"cell {index} prepared schema mismatch")
        if prepared.get("preflight_pass") is not True or prepared.get("hash_closure_pass") is not True:
            raise ValueError(f"cell {index} prepared contract is not passed")
        for key, expected in {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutated": False,
            "ledger_mutated": False,
            "registry_mutated": False,
            "mass_rescaling": False,
        }.items():
            if prepared.get(key) != expected:
                raise ValueError(f"cell {index} prepared contract changed: {key}")
        if prepared.get("case_id") != design_cell.get("case_id") or int(prepared.get("index", -1)) != index:
            raise ValueError(f"cell {index} prepared identity differs from candidate")
        if abs(float(prepared.get("q", -1.0)) - float(design_cell["q"])) > 1e-12 or abs(float(prepared.get("dp_m", -1.0)) - float(design_cell["dp_m"])) > 1e-12:
            raise ValueError(f"cell {index} prepared q/dp differs from candidate")
        closure = prepared.get("hash_closure", [])
        if not isinstance(closure, list) or not closure:
            raise ValueError(f"cell {index} has no hash closure")
        closure_roles = set()
        for item in closure:
            verify_ref(item, f"cell {index} closure")
            closure_roles.add(str(item.get("role", "")))
        if not any("Def.xml" in role or "Definition" in role for role in closure_roles):
            raise ValueError(f"cell {index} closure has no Definition")
        if not any("motion" in role.lower() for role in closure_roles):
            raise ValueError(f"cell {index} closure has no motion input")
        if not any("preflight" in role.lower() for role in closure_roles):
            raise ValueError(f"cell {index} closure has no preflight")
        preflight_path = Path(prepared["preflight"]).resolve()
        preflight = load(preflight_path)
        if preflight.get("schema") != "core.f2.static_full_cup.matrix_cell_preflight.v1" or preflight.get("preflight_pass") is not True:
            raise ValueError(f"cell {index} preflight contract is not passed")
        if preflight.get("trajectory_or_solver_checked") is not False or preflight.get("mass_rescaling") is not False:
            raise ValueError(f"cell {index} preflight is not CPU-only")
        if preflight.get("case_id") != design_cell.get("case_id"):
            raise ValueError(f"cell {index} preflight case mismatch")
        prepared_by_index[index] = {
            "row": row,
            "design": design_cell,
            "prepared_path": prepared_path,
            "prepared": prepared,
            "preflight_path": preflight_path,
            "preflight": preflight,
        }
    if len(prepared_by_index) != EXPECTED_CELLS:
        raise ValueError("v4 prepared cell map is incomplete")
    return {
        "report_path": report_path,
        "report": report,
        "report_ref": ref(report_path, "v4 CPU preparation report"),
        "audit_path": audit_path,
        "audit": audit,
        "candidate_path": Path(report["candidate_card"]["path"]).resolve(),
        "candidate": card,
        "design_cells": design_cells,
        "prepared_by_index": prepared_by_index,
    }


def admission_contract(context: dict[str, Any]) -> dict[str, Any]:
    """Return the future product contract; this function performs no admission."""
    return {
        "schema": ADMISSION_SCHEMA,
        "created_at": stamp(),
        "family": "F2",
        "candidate_id": context["candidate"].get("candidate_id"),
        "scope_id": context["candidate"].get("scope_id"),
        "candidate_card": ref(context["candidate_path"], "15-cell candidate card"),
        "source_preparation": context["report_ref"],
        "source_preparation_audit": ref(context["audit_path"], "v4 preparation audit") if context.get("audit_path") else None,
        "observer_code": ref(Path(__file__), "read-only F2 static-volume observer/evaluator"),
        "legacy_static_observer_code": ref(
            Path(legacy_static_observer.__file__), "reused static hold/open-top helper source"
        ),
        "qualification_claim": "none; candidate static-volume scope only",
        "admission_controls": {
            "solver_launch_allowed": False,
            "gpu_launch_allowed": False,
            "job_spec_creation_allowed": False,
            "queue_mutation_allowed": False,
            "ledger_mutation_allowed": False,
            "registry_mutation_allowed": False,
            "anchor_trajectory_reuse_allowed": False,
            "survivor_renormalization_allowed": False,
            "threshold_relaxation_allowed": False,
        },
        "required_runtime_product_per_cell": {
            "fixed_denominator": EXPECTED_CELLS,
            "trajectory_hdf5": True,
            "trajectory_sha256_and_bytes": True,
            "prepared_sha256_exact_match": True,
            "case_id_exact_match": True,
            "native_identity_axis_exact_match": True,
            "solver_product_is_read_only_input": True,
            "anchor_trajectory_reuse": False,
            "missing_or_failed_rows_retained": True,
        },
        "required_temporal_evidence": {
            "internal_time": "trajectory comparison plus explicit actual-step control evidence supplied by root runtime receipt",
            "native_output": "trajectory comparison at the independently declared finer saved cadence",
        },
        "future_job_review": {
            "this_module_does_not_create_jobs": True,
            "root_review_required_before_any_solver_or_gpu_submission": True,
            "registry_scope_registration_deferred": True,
        },
    }


def _cup_spec(card: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    cup = card["physical_contract"]["cup"]
    low = np.asarray(cup["low_m"], dtype=float)
    high = low + np.asarray(cup["size_m"], dtype=float)
    spec = {
        "container_interior": {
            "xmin": float(low[0]), "xmax": float(high[0]),
            "ymin": float(low[1]), "ymax": float(high[1]),
            "zmin": float(low[2]), "zmax": float(high[2]),
        },
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "obstacles": [],
    }
    return low, high, spec


def _expected_axis(preflight: dict[str, Any]) -> np.ndarray:
    groups = preflight.get("generated_particle_groups", {}).get("fluid", [])
    parts = [
        np.arange(int(group["begin"]), int(group["begin"]) + int(group["count"]), dtype=np.uint64)
        for group in groups
    ]
    return np.concatenate(parts) if parts else np.empty(0, dtype=np.uint64)


def _settled_time(times: np.ndarray, speed: np.ndarray, ke: np.ndarray,
                  speed_limit: float, ke_limit: float, hold: float) -> float | None:
    good = (speed <= speed_limit) & (ke <= ke_limit)
    for start in np.flatnonzero(good):
        end = int(start)
        while end + 1 < len(good) and good[end + 1]:
            end += 1
        if end == len(good) - 1 and times[end] - times[start] >= hold - 1e-9:
            return float(times[start])
    return None


def observe_cell(prepared_entry: dict[str, Any], trajectory_path: Path, card: dict[str, Any]) -> dict[str, Any]:
    """Observe one v4 prepared cell from a trajectory HDF5, without running CFD."""
    trajectory_path = Path(trajectory_path).resolve()
    low, high, cup_spec = _cup_spec(card)
    gates = card["gates"]
    preflight = prepared_entry["preflight"]
    expected_axis = _expected_axis(preflight)
    prepared = prepared_entry["prepared"]
    with h5py.File(trajectory_path, "r") as handle:
        required = ("time", "particle_id", "position", "velocity", "density", "pressure", "mass", "valid")
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"trajectory missing datasets: {missing}")
        times = np.asarray(handle["time"][:], dtype=float)
        ids = np.asarray(handle["particle_id"][:])
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        density = np.asarray(handle["density"][:], dtype=float)
        pressure = np.asarray(handle["pressure"][:], dtype=float)
        masses = np.asarray(handle["mass"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
    if times.ndim != 1 or len(times) < 2:
        raise ValueError("trajectory needs at least two saved frames")
    nframes, nparticles = len(times), len(ids)
    if positions.shape != (nframes, nparticles, 3) or velocities.shape != positions.shape:
        raise ValueError("trajectory position/velocity axes are inconsistent")
    if any(array.shape != (nframes, nparticles) for array in (density, pressure, masses, valid)):
        raise ValueError("trajectory scalar axes are inconsistent")
    time_valid = bool(np.isfinite(times).all() and np.all(np.diff(times) > 0.0))
    expected_exact = bool(ids.ndim == 1 and np.array_equal(ids.astype(np.uint64, copy=False), expected_axis))
    initial_valid = valid[0].copy()
    initial_ids = ids[initial_valid]
    initial_mass_values = masses[0]
    initial_mass = float(initial_mass_values[initial_valid].sum(dtype=np.float64))
    if initial_mass <= 0 or not np.isfinite(initial_mass):
        raise ValueError("trajectory initial mass is not positive finite")
    initial_position = positions[0]
    initial_potential = float(
        (initial_mass_values[initial_valid] * GRAVITY_M_S2 * np.maximum(initial_position[initial_valid, 2] - low[2], 0.0)).sum(dtype=np.float64)
    )
    retention, outside, speed_p95, ke_fraction, com = [], [], [], [], []
    missing_counts, nonfinite_counts, mass_deltas, mass_sum_deltas = [], [], [], []
    endpoint_frames = 0
    endpoint_by_face = {face: 0 for face in ("bottom", "left", "right", "front", "back")}
    chord_events = 0
    first_chord = None
    open_endpoint_frames = 0
    open_chord_events = 0
    first_open_chord = None
    previous = None
    for frame_index, time_s in enumerate(times):
        active = valid[frame_index].copy()
        finite = (
            np.isfinite(positions[frame_index]).all(axis=1)
            & np.isfinite(velocities[frame_index]).all(axis=1)
            & np.isfinite(masses[frame_index])
            & np.isfinite(density[frame_index])
            & np.isfinite(pressure[frame_index])
        )
        nonfinite_counts.append(int(np.sum(active & ~finite)))
        active &= finite
        missing_counts.append(int(np.sum(initial_valid & ~valid[frame_index])))
        tracked = initial_valid & valid[frame_index] & finite
        mass_deltas.append(float(np.max(np.abs(masses[frame_index, tracked] - initial_mass_values[tracked]), initial=0.0)))
        selected = positions[frame_index, active]
        selected_mass = masses[frame_index, active]
        inside = np.all((selected >= low) & (selected <= high), axis=1)
        active_mass = float(selected_mass.sum(dtype=np.float64))
        retention.append(float(selected_mass[inside].sum(dtype=np.float64) / initial_mass))
        outside.append(float(selected_mass[~inside].sum(dtype=np.float64) / initial_mass))
        mass_sum_deltas.append(abs(active_mass - initial_mass))
        speeds = np.linalg.norm(velocities[frame_index, active], axis=1)
        speed_p95.append(float(np.percentile(speeds, 95)) if len(speeds) else 0.0)
        kinetic = float((0.5 * selected_mass * np.sum(velocities[frame_index, active] ** 2, axis=1)).sum(dtype=np.float64))
        ke_fraction.append(kinetic / max(initial_potential, 1e-30))
        com.append(((selected_mass[:, None] * selected).sum(axis=0) / max(active_mass, 1e-30)).tolist() if len(selected) else [np.nan] * 3)
        endpoint = outside_closed_face_masks(positions[frame_index], cup_spec, WALL_TOLERANCE_M)
        for face, mask in endpoint.items():
            mask &= valid[frame_index]
            count = int(mask.sum())
            endpoint_by_face[face] += count
            endpoint_frames += count
        if previous is not None:
            common = previous["valid"] & valid[frame_index] & previous["finite"] & finite
            if common.any():
                events = segment_crossing_events(previous["positions"][common], positions[frame_index, common], cup_spec, WALL_TOLERANCE_M)
                chord_events += len(events)
                if events and first_chord is None:
                    first_chord = {"frame_index": frame_index, "time_s": float(time_s), "events": events[:10]}
                open_events = legacy_static_observer._top_opening_crossing_events(
                    previous["positions"][common], positions[frame_index, common], low, high, WALL_TOLERANCE_M
                )
                open_chord_events += len(open_events)
                if open_events and first_open_chord is None:
                    first_open_chord = {"frame_index": frame_index, "time_s": float(time_s), "events": open_events[:10]}
        open_endpoint = legacy_static_observer._top_opening_endpoint_mask(positions[frame_index], low, high, WALL_TOLERANCE_M) & valid[frame_index]
        open_endpoint_frames += int(open_endpoint.sum())
        previous = {"valid": valid[frame_index].copy(), "finite": finite, "positions": positions[frame_index].copy()}
    retention = np.asarray(retention, dtype=float)
    outside = np.asarray(outside, dtype=float)
    speed_p95 = np.asarray(speed_p95, dtype=float)
    ke_fraction = np.asarray(ke_fraction, dtype=float)
    com = np.asarray(com, dtype=float)
    horizon = bool(times[-1] >= float(card["qualification_design"]["registered_window_s"]) - 1e-6)
    no_missing = int(max(missing_counts, default=0)) == 0
    nonfinite_total = int(sum(nonfinite_counts))
    no_mass_change = bool(
        max(mass_deltas, default=0.0) <= float(gates["mass_change_relative_max"]) * initial_mass
        and max(mass_sum_deltas, default=0.0) <= float(gates["mass_change_relative_max"]) * initial_mass
    )
    settled = _settled_time(
        times, speed_p95, ke_fraction,
        float(gates["static_speed_p95_m_s_max"]),
        float(gates["static_kinetic_over_initial_potential_max"]),
        float(gates["static_settle_hold_s"]),
    )
    declared_interval = float(prepared.get("output_interval_s", card["qualification_design"]["output_interval_s"]))
    saved_interval = float(np.median(np.diff(times))) if len(times) > 1 else math.nan
    cadence_matches = bool(
        np.isfinite(saved_interval)
        and abs(saved_interval - declared_interval) <= max(1e-6, declared_interval * 0.05)
    )
    hard_checks = {
        "time_axis_valid": time_valid,
        "initial_native_ids_present": bool(expected_exact and len(initial_ids) == len(expected_axis)),
        "no_unexpected_native_ids": bool(expected_exact and not np.any(valid & ~initial_valid[None, :])),
        "no_missing_native_ids": no_missing,
        "no_nonfinite_active_values": nonfinite_total == 0,
        "native_mass_unchanged": no_mass_change,
        "no_cup_closed_wall_endpoint_penetrations": endpoint_frames == 0,
        "no_cup_saved_chord_crossings": chord_events == 0,
        "no_open_cup_escape": bool(np.max(outside, initial=0.0) <= 1e-12),
        "no_open_top_saved_chord_crossings": open_chord_events == 0,
        "requested_static_hold_horizon_reached": horizon,
        "saved_output_cadence_matches_declared": cadence_matches,
    }
    static_settled = settled is not None
    event_complete = bool(all(hard_checks.values()) and static_settled)
    spans = high - low
    normalized = np.column_stack((
        retention,
        outside,
        speed_p95 / float(gates["static_speed_p95_m_s_max"]),
        ke_fraction / float(gates["static_kinetic_over_initial_potential_max"]),
        com[:, 0] / spans[0],
        com[:, 1] / spans[1],
        com[:, 2] / spans[2],
        np.asarray([float(np.sum(masses[i][valid[i]], dtype=np.float64) / initial_mass) for i in range(nframes)]),
    ))
    observation = {
        "schema": "core.f2.static_full_cup.matrix_cell_observation.v1",
        "observation_version": OBSERVATION_VERSION,
        "observation_geometry": "full finite cup interior with bottom/left/right/front/back closed and top open",
        "observable_layout": list(OBSERVABLE_LAYOUT),
        "index": int(prepared["index"]),
        "case_id": prepared["case_id"],
        "q": float(prepared["q"]),
        "dp_m": float(prepared["dp_m"]),
        "design_cell": prepared["design_cell"],
        "trajectory": str(trajectory_path),
        "time_s": times.tolist(),
        "normalized_values": normalized.tolist(),
        "cup_retention_mass_fraction": retention.tolist(),
        "outside_cup_mass_fraction": outside.tolist(),
        "speed_p95_m_s": speed_p95.tolist(),
        "kinetic_energy_over_initial_potential": ke_fraction.tolist(),
        "center_of_mass_m": com.tolist(),
        "initial_native_mass_kg": initial_mass,
        "maximum_outside_cup_mass_fraction": float(np.max(outside, initial=0.0)),
        "maximum_speed_p95_m_s": float(np.max(speed_p95, initial=0.0)),
        "maximum_kinetic_over_initial_potential": float(np.max(ke_fraction, initial=0.0)),
        "native_missing_count_max": int(max(missing_counts, default=0)),
        "nonfinite_active_value_count": nonfinite_total,
        "mass_delta_max_kg": float(max(mass_deltas, default=0.0)),
        "mass_sum_delta_max_kg": float(max(mass_sum_deltas, default=0.0)),
        "cup_closed_wall_endpoint_particle_frames": int(endpoint_frames),
        "cup_closed_wall_endpoint_by_face": endpoint_by_face,
        "cup_saved_chord_crossings": int(chord_events),
        "first_cup_saved_chord_crossing": first_chord,
        "cup_open_top_endpoint_particle_frames": int(open_endpoint_frames),
        "cup_open_top_saved_chord_crossings": int(open_chord_events),
        "first_cup_open_top_saved_chord_crossing": first_open_chord,
        "settled_time_s": settled,
        "static_settled": static_settled,
        "requested_horizon_reached": horizon,
        "declared_output_interval_s": declared_interval,
        "saved_output_interval_median_s": saved_interval,
        "hard_checks": hard_checks,
        "hard_integrity_pass": bool(all(hard_checks.values())),
        "static_hold_gate_pass": bool(event_complete),
        "event_window_complete": event_complete,
        "qualification_claim": "none; candidate-scope static observation only",
        "qualified": False,
    }
    return observation


def _runtime_products(path: Path | None, context: dict[str, Any]) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    payload = load(Path(path).resolve())
    if payload.get("schema") != RUNTIME_SCHEMA:
        raise ValueError("unexpected runtime product manifest schema")
    if payload.get("scope_id") != context["candidate"].get("scope_id"):
        raise ValueError("runtime product scope mismatch")
    if payload.get("job_spec_creation") is True or payload.get("queue_mutation") not in (None, 0, False):
        raise ValueError("runtime product manifest claims job/queue mutation")
    rows = payload.get("cells", [])
    result: dict[int, dict[str, Any]] = {}
    for item in rows:
        index = int(item.get("index", -1))
        if index in result or index < 0 or index >= EXPECTED_CELLS:
            raise ValueError("runtime product manifest has duplicate/out-of-range cell")
        prepared = context["prepared_by_index"][index]
        if item.get("anchor_trajectory_reused") is True:
            result[index] = {"manifest": item, "trajectory": None,
                             "error_category": "anchor_trajectory_reuse"}
            continue
        if item.get("case_id") != prepared["prepared"]["case_id"]:
            result[index] = {"manifest": item, "trajectory": None,
                             "error_category": "runtime_case_id_mismatch"}
            continue
        if item.get("prepared_sha256") != digest(prepared["prepared_path"]):
            result[index] = {"manifest": item, "trajectory": None,
                             "error_category": "runtime_prepared_hash_mismatch"}
            continue
        trajectory_binding = item.get("trajectory")
        try:
            trajectory = verify_ref(trajectory_binding, f"runtime cell {index} trajectory")
            if trajectory.suffix.lower() not in {".h5", ".hdf5"}:
                raise ValueError("trajectory is not HDF5")
        except (FileNotFoundError, ValueError, TypeError, KeyError) as error:
            result[index] = {"manifest": item, "trajectory": None,
                             "error_category": "runtime_product_hash_mismatch",
                             "error": str(error)}
            continue
        result[index] = {"manifest": item, "trajectory": trajectory}
    return result


def _failure_categories(observation: dict[str, Any]) -> list[str]:
    categories = []
    checks = observation.get("hard_checks", {})
    mapping = {
        "time_axis_valid": "time_axis_invalid",
        "initial_native_ids_present": "native_identity_axis_mismatch",
        "no_unexpected_native_ids": "unexpected_native_id",
        "no_missing_native_ids": "missing_native_id",
        "no_nonfinite_active_values": "nonfinite_active_value",
        "native_mass_unchanged": "mass_change",
        "no_cup_closed_wall_endpoint_penetrations": "cup_closed_face_endpoint",
        "no_cup_saved_chord_crossings": "cup_saved_chord_crossing",
        "no_open_cup_escape": "open_cup_escape",
        "no_open_top_saved_chord_crossings": "open_top_chord_crossing",
        "requested_static_hold_horizon_reached": "event_window_incomplete",
        "saved_output_cadence_matches_declared": "output_cadence_mismatch",
    }
    categories.extend(category for key, category in mapping.items() if checks.get(key) is False)
    if observation.get("static_settled") is not True:
        categories.append("static_settle_failed")
    return sorted(set(categories))


def _compare(first: dict[str, Any] | None, second: dict[str, Any] | None,
             threshold: float, kind: str, q: float, held_out: bool = False) -> dict[str, Any]:
    if first is None or second is None:
        return {"q": q, "kind": kind, "held_out": held_out, "passed": False,
                "failure_categories": ["comparison_input_missing"]}
    try:
        error = aligned_difference(first, second, cadence=0.01 if kind == "temporal" else 0.02)
    except Exception as error:
        return {"q": q, "kind": kind, "held_out": held_out, "passed": False,
                "failure_categories": ["comparison_contract_error"], "error": str(error)}
    return {"q": q, "kind": kind, "held_out": held_out,
            "threshold": float(threshold), "passed": bool(error["maximum"] <= threshold),
            "failure_categories": [] if error["maximum"] <= threshold else ["normalized_difference_exceeded"], **error}


def _spatial_observation(observations: dict[tuple[float, float, str], dict[str, Any]],
                         q: float, dp: float) -> dict[str, Any] | None:
    """Resolve registered spatial and spatial-held-out design-cell labels."""
    return observations.get((q, dp, "spatial")) or observations.get((q, dp, "spatial_held_out"))


def evaluate_matrix(preparation_report: Path, *, preparation_audit: Path | None = None,
                    runtime_products: Path | None = None, output: Path | None = None) -> dict[str, Any]:
    context = _verify_preparation(Path(preparation_report), preparation_audit)
    runtime = _runtime_products(runtime_products, context)
    card = context["candidate"]
    design = context["design_cells"]
    rows = []
    observations: dict[tuple[float, float, str], dict[str, Any]] = {}
    failures = []
    derived_dir = None
    if output is not None:
        derived_dir = Path(output).resolve().parent / (Path(output).stem + ".observations")
        if derived_dir.exists():
            raise FileExistsError(derived_dir)
        derived_dir.mkdir(parents=True, exist_ok=True)
    for index in range(EXPECTED_CELLS):
        prepared_entry = context["prepared_by_index"][index]
        base = prepared_entry["row"]
        row = {
            "index": index,
            "case_id": base["case_id"],
            "q": float(base["q"]),
            "dp_m": float(base["dp_m"]),
            "design_cell": base["design_cell"],
            "held_out": bool(design[index].get("held_out", False)),
            "status": "missing_runtime_product",
            "passed": False,
            "failure_categories": ["missing_runtime_product"],
            "prepared": str(prepared_entry["prepared_path"]),
            "prepared_sha256": digest(prepared_entry["prepared_path"]),
        }
        product = runtime.get(index)
        if product is not None:
            if product.get("trajectory") is None:
                category = product.get("error_category", "runtime_product_binding_invalid")
                row.update({"status": "runtime_product_invalid", "failure_categories": [category],
                            "error": {"message": product.get("error", category)}})
            else:
                try:
                    obs = observe_cell(prepared_entry, product["trajectory"], card)
                    observation_path = None
                    if derived_dir is not None:
                        observation_path = derived_dir / f"cell-{index:02d}.observation.json"
                        # Derived observations are written only under the explicitly requested
                        # evaluator output location; runtime products remain read-only.
                        write_json(observation_path, obs)
                    row.update({
                        "status": "observed" if obs["event_window_complete"] else "failed_static_gate",
                        "passed": bool(obs["event_window_complete"]),
                        "failure_categories": _failure_categories(obs),
                        "trajectory": ref(product["trajectory"], "runtime trajectory"),
                        "observation_pass": bool(obs["event_window_complete"]),
                    })
                    if observation_path is not None:
                        row["observation"] = ref(observation_path, "read-only derived observation")
                    key = (float(base["q"]), float(base["dp_m"]), base["design_cell"])
                    observations[key] = obs
                except Exception as error:
                    row.update({"status": "runtime_product_invalid", "failure_categories": ["trajectory_schema_invalid"],
                                "error": {"type": type(error).__name__, "message": str(error)},
                                "trajectory": ref(product["trajectory"], "runtime trajectory")})
        if row["failure_categories"]:
            failures.append({"index": index, "case_id": row["case_id"], "categories": row["failure_categories"],
                             "status": row["status"], "error": row.get("error")})
        rows.append(row)

    gates = card["gates"]
    comparisons = []
    spatial_pass = True
    independent_pass = True
    for q in (0.0, 0.5, 1.0, 0.25, 0.75):
        middle = _spatial_observation(observations, q, 0.0075)
        fine = _spatial_observation(observations, q, 0.005)
        held_out = q in (0.25, 0.75)
        record = _compare(middle, fine, float(gates["spatial_max_absolute_normalized_difference"]), "spatial", q, held_out)
        record["resolution_pair"] = [0.0075, 0.005]
        comparisons.append(record)
        spatial_pass &= bool(record["passed"])
        independent_pass &= bool(record["passed"])
        if not held_out:
            coarse = _spatial_observation(observations, q, 0.01)
            coarse_middle = _compare(coarse, middle, float(gates["spatial_max_absolute_normalized_difference"]), "spatial_coarse_middle", q)
            coarse_fine = _compare(coarse, fine, float(gates["spatial_max_absolute_normalized_difference"]), "spatial_coarse_fine", q)
            monotone = bool(record.get("maximum", math.inf) <= coarse_middle.get("maximum", math.inf) + 1e-12)
            coarse_record = {"q": q, "kind": "spatial_refinement", "coarse_middle": coarse_middle,
                             "coarse_fine": coarse_fine, "monotone_refinement": monotone,
                             "passed": bool(coarse_middle["passed"] and coarse_fine["passed"] and monotone)}
            comparisons.append(coarse_record)
            spatial_pass &= coarse_record["passed"]
            if not coarse_record["passed"]:
                for row in rows:
                    if abs(float(row["q"]) - q) < 1e-12 and row["design_cell"] == "spatial":
                        row["failure_categories"] = sorted(set(row["failure_categories"] + ["spatial_comparison_failed"]))
        if not record["passed"]:
            for row in rows:
                if abs(float(row["q"]) - q) < 1e-12 and row["design_cell"].startswith("spatial"):
                    row["failure_categories"] = sorted(set(row["failure_categories"] + ["spatial_comparison_failed"]))
    temporal_pass = True
    temporal_control_pass = True
    baseline = observations.get((0.5, 0.0075, "spatial"))
    for kind in ("internal_time", "native_output"):
        other = observations.get((0.5, 0.0075, kind))
        record = _compare(baseline, other, float(gates["temporal_max_absolute_normalized_difference"]), "temporal", 0.5)
        record["temporal_variant"] = kind
        comparisons.append(record)
        temporal_pass &= bool(record["passed"])
        if not record["passed"]:
            for row in rows:
                if row["design_cell"] in {"spatial", kind} and abs(float(row["q"]) - 0.5) < 1e-12 and abs(float(row["dp_m"]) - 0.0075) < 1e-12:
                    row["failure_categories"] = sorted(set(row["failure_categories"] + ["temporal_comparison_failed"]))
        if kind == "internal_time":
            item = runtime.get(13, {}).get("manifest", {}) if 13 in runtime else {}
            evidence = item.get("control_evidence", {})
            present = bool(evidence.get("actual_step_count") and float(evidence["actual_step_count"]) > 0)
            temporal_control_pass &= present
            if not present:
                for row in rows:
                    if row["index"] in (13,):
                        row["failure_categories"] = sorted(set(row["failure_categories"] + ["temporal_control_evidence_missing"]))
    for row in rows:
        if row["failure_categories"]:
            row["passed"] = False
    failures = [{"index": row["index"], "case_id": row["case_id"], "status": row["status"],
                 "categories": row["failure_categories"]} for row in rows if row["failure_categories"]]
    matrix_complete = all(row["status"] in {"observed"} and row["observation_pass"] is True for row in rows)
    all_hard = matrix_complete and all(not _failure_categories(observations[(float(row["q"]), float(row["dp_m"]), row["design_cell"])]) for row in rows)
    checks = {
        "preparation_contract": True,
        "fixed_15_cell_denominator": len(rows) == EXPECTED_CELLS,
        "matrix_complete": matrix_complete,
        "all_case_hard_static_event_gates": all_hard,
        "spatial": bool(spatial_pass),
        "held_out_independent_checks": bool(independent_pass),
        "temporal": bool(temporal_pass),
        "temporal_control_evidence": bool(temporal_control_pass),
        "anchor_trajectory_reuse_detected": False,
        "survivor_renormalization_detected": False,
    }
    candidate_scope_pass = bool(all(checks[key] for key in (
        "preparation_contract", "fixed_15_cell_denominator", "matrix_complete",
        "all_case_hard_static_event_gates", "spatial", "held_out_independent_checks",
        "temporal", "temporal_control_evidence",
    )) and not checks["anchor_trajectory_reuse_detected"] and not checks["survivor_renormalization_detected"])
    # False is intentional: this receipt never registers T1 or promotes a central scope.
    result = {
        "schema": SCHEMA,
        "created_at": stamp(),
        "family": "F2",
        "candidate_id": card["candidate_id"],
        "scope_id": card["scope_id"],
        "source_preparation": context["report_ref"],
        "source_preparation_audit": ref(context["audit_path"], "v4 preparation audit") if context.get("audit_path") else None,
        "candidate_card": ref(context["candidate_path"], "15-cell candidate card"),
        "observer_code": ref(Path(__file__), "read-only F2 static-volume observer/evaluator"),
        "legacy_static_observer_reused": {
            "path": str(Path(legacy_static_observer.__file__).resolve()),
            "sha256": digest(Path(legacy_static_observer.__file__)),
            "helpers": ["top-opening endpoint/chord classification", "static hold semantics"],
        },
        "registered_cell_count": EXPECTED_CELLS,
        "fixed_failure_denominator": True,
        "cells": rows,
        "failure_denominator": {"fixed": EXPECTED_CELLS, "rows": rows, "survivor_renormalization": False},
        "failures": failures,
        "comparisons": comparisons,
        "checks": checks,
        "candidate_scope_pass": candidate_scope_pass,
        "T1_numerical": False,
        "qualification_claim": "none; candidate-scope-only static-volume receipt; no central registration",
        "promotion_status": "candidate_scope_pass_pending_root_review" if candidate_scope_pass else "blocked_until_all_15_rows_and_gates",
        "execution_controls": {
            "trajectory_read_only": True,
            "solver_invoked_by_evaluator": False,
            "gpu_invoked_by_evaluator": False,
            "job_spec_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "anchor_trajectory_reused": False,
        },
        "admission_contract": admission_contract(context),
    }
    if output is not None:
        output = Path(output).resolve()
        if output.exists():
            raise FileExistsError(output)
        write_json(output, result)
        result["receipt_artifact"] = ref(output, "candidate-scope-only evaluator receipt")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation-report", type=Path, required=True)
    parser.add_argument("--preparation-audit", type=Path)
    parser.add_argument("--runtime-products", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate_matrix(args.preparation_report, preparation_audit=args.preparation_audit,
                             runtime_products=args.runtime_products, output=args.output)
    print(json.dumps({"candidate_scope_pass": result["candidate_scope_pass"],
                      "T1_numerical": result["T1_numerical"],
                      "failure_count": len(result["failures"]),
                      "qualification_claim": result["qualification_claim"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
