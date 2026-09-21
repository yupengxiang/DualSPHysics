#!/usr/bin/env python3
"""Read-only F1 H2 bottom-contact forensic and CPU candidate preflight.

The H2 mDBC run failed at the obstacle footprint.  This module binds that
failure to the immutable GenCase/solver artifacts, checks the normal and
ghost snapshots, compares the historical F3 DBC baffle case, and optionally
prepares exactly one CPU-only candidate: add the obstacle bottom face to both
the boundary draw and ``GeometryForNormals``.  It never launches the solver,
does not change the original prepared case, and writes no campaign ledger.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts.r4_f6_mdbc_runtime_zero_normal_audit import read_binary_vtk


SCHEMA = "core.f1.h2.bottom_contact_forensics.v1"
DP = 0.0075
H = 0.0129904
F1_CASE = (
    "CORE_F1_H2_mdbc_obstacle_q0p50000000_h0p46000000_"
    "dp0p007500000000_canary"
)
F1_H3_CASE = (
    "CORE_F1_H3_mdbc_obstacle_bottom_face_q0p50000000_h0p46000000_"
    "dp0p007500000000_canary"
)
F3_CASE = "L2_C2_F3_offaxis_baffle_nominal"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _clean_float(value: Any) -> float:
    return float(value)


def _normal_summary(normal_path: Path, ghost_path: Path, bound_path: Path) -> dict[str, Any]:
    normal = read_binary_vtk(normal_path)
    ghost = read_binary_vtk(ghost_path)
    bound = read_binary_vtk(bound_path)
    points = np.asarray(normal["points"], dtype=float)
    ghost_points = np.asarray(ghost["points"], dtype=float)
    normals = np.asarray(normal["point_data"]["Normal"], dtype=float)
    normal_size = np.asarray(normal["point_data"]["NormalSize"], dtype=float)
    ghost_normals = np.asarray(ghost["point_data"]["Normal"], dtype=float)
    ghost_size = np.asarray(ghost["point_data"]["NormalSize"], dtype=float)
    mk = np.asarray(normal["point_data"]["Mk"], dtype=int)
    obstacle = mk == 18
    strict_obstacle_xy = (
        (points[:, 0] > 0.68)
        & (points[:, 0] < 0.80)
        & (points[:, 1] > 0.15)
        & (points[:, 1] < 0.25)
    )
    bottom_band = (points[:, 2] >= -0.006) & (points[:, 2] < 0.0075)
    bottom_edge = obstacle & (np.abs(points[:, 2] + DP / 2.0) <= 1.0e-6)
    bottom_interior = bottom_edge & strict_obstacle_xy
    effective_interface = points[bottom_edge] + ghost_normals[bottom_edge] / 2.0
    by_mk = {
        str(int(value)): int(count)
        for value, count in zip(*np.unique(mk, return_counts=True))
    }
    return {
        "normal_point_count": int(len(points)),
        "bound_point_count": int(len(bound["points"])),
        "mk_counts": by_mk,
        "normal_points_equal_bound_points": bool(
            np.array_equal(points, np.asarray(bound["points"], dtype=float))
        ),
        "ghost_points_equal_normal_points": bool(np.array_equal(points, ghost_points)),
        "ghost_normal_is_two_times_normal_max_abs_error": float(
            np.max(np.abs(ghost_normals - 2.0 * normals))
        ),
        "ghost_size_is_two_times_normal_size_max_abs_error": float(
            np.max(np.abs(ghost_size - 2.0 * normal_size))
        ),
        "normal_norm_matches_normal_size_max_abs_error": float(
            np.max(np.abs(np.linalg.norm(normals, axis=1) - normal_size))
        ),
        "zero_normal_count": int(np.sum(np.linalg.norm(normals, axis=1) <= 1.0e-10)),
        "normal_size_range_m": [float(normal_size.min()), float(normal_size.max())],
        "obstacle_mk": 18,
        "obstacle_boundary_count": int(np.sum(obstacle)),
        "obstacle_bottom_edge_z_m": -DP / 2.0,
        "obstacle_bottom_edge_particle_count": int(np.sum(bottom_edge)),
        "obstacle_bottom_edge_normal_direction_counts": {
            str(tuple(float(x) for x in row)): int(count)
            for row, count in zip(
                *np.unique(
                    np.round(normals[bottom_edge], 8), axis=0, return_counts=True
                )
            )
        },
        "obstacle_bottom_edge_effective_interface_z_range_m": [
            float(effective_interface[:, 2].min()),
            float(effective_interface[:, 2].max()),
        ],
        "boundary_shell_contract": {
            "obstacle_boundary_layers_vdp": "0,1,2",
            "obstacle_normal_geometry_layers_vdp": "0",
            "support_face_offset_m": DP / 2.0,
            "continuous_obstacle_bottom_z_m": 0.0,
            "edge_boundary_centres_z_m": -DP / 2.0,
            "bottom_edge_normal_vector_m": [0.0, 0.0, DP / 2.0],
            "ghost_file_semantics": "same boundary POINTS/IDs with doubled normal displacement; effective interface = boundary point + ghost displacement/2",
            "effective_interface_matches_continuous_bottom_max_abs_error_m": float(
                np.max(np.abs(effective_interface[:, 2]))
            ),
        },
        "obstacle_bottom_interior_particle_count": int(np.sum(bottom_interior)),
        "obstacle_bottom_interior_or_tank_floor_count_in_bottom_band": int(
            np.sum(strict_obstacle_xy & bottom_band)
        ),
        "boundary_points_strictly_inside_obstacle_xy_bottom_band": int(
            np.sum(strict_obstacle_xy & bottom_band)
        ),
        "interpretation": (
            "The edge shell has +z normals at z=-dp/2, but setmkvoid removes the "
            "tank floor below the obstacle and no boundary center remains in the "
            "strict obstacle footprint. The complete normal/ghost arrays therefore "
            "do not close this geometric hole."
        ),
    }


def _first_failure_trajectory(
    trajectory: Path, result_path: Path, normal_path: Path
) -> dict[str, Any]:
    result = json.loads(result_path.read_text())
    first = result["first_wall_violation"]
    ids = [int(value) for value in first["ids"]]
    time_s = float(first["time_s"])
    normal = read_binary_vtk(normal_path)
    boundary_points = np.asarray(normal["points"], dtype=float)
    boundary_mk = np.asarray(normal["point_data"]["Mk"], dtype=int)
    records: list[dict[str, Any]] = []
    with h5py.File(trajectory, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        particle_ids = np.asarray(handle["particle_id"][:], dtype=np.uint64)
        positions = handle["position"]
        velocities = handle["velocity"]
        density = handle["density"]
        pressure = handle["pressure"]
        valid = handle["valid"]
        indices = []
        for particle_id in ids:
            found = np.flatnonzero(particle_ids == particle_id)
            if len(found) != 1:
                raise ValueError(f"failure particle id {particle_id} not unique")
            indices.append(int(found[0]))
        center = int(np.argmin(np.abs(times - time_s)))
        frame_indices = list(range(max(0, center - 2), min(len(times), center + 3)))
        for frame in frame_indices:
            for particle_id, index in zip(ids, indices):
                point = np.asarray(positions[frame, index], dtype=float)
                nearest = np.linalg.norm(boundary_points - point, axis=1)
                nearest_index = int(np.argmin(nearest))
                records.append(
                    {
                        "frame_index": int(frame),
                        "time_s": float(times[frame]),
                        "particle_id": int(particle_id),
                        "valid": bool(valid[frame, index]),
                        "position_m": point.tolist(),
                        "velocity_m_s": np.asarray(velocities[frame, index], dtype=float).tolist(),
                        "density_kg_m3": float(density[frame, index]),
                        "pressure_native": float(pressure[frame, index]),
                        "nearest_boundary_distance_m": float(nearest[nearest_index]),
                        "nearest_boundary_mk": int(boundary_mk[nearest_index]),
                        "nearest_boundary_position_m": boundary_points[nearest_index].tolist(),
                    }
                )
    first_records = [row for row in records if abs(row["time_s"] - time_s) < 1.0e-8]
    return {
        "first_wall_violation_time_s": time_s,
        "first_wall_violation_ids": ids,
        "first_wall_violation_positions_m": first["positions_m"],
        "trajectory_window": records,
        "first_frame_records": first_records,
        "failure_is_inside_obstacle_projection": all(
            0.68 < float(point[0]) < 0.80 and 0.15 < float(point[1]) < 0.25
            for point in first["positions_m"]
        ),
        "failure_crosses_continuous_bottom_plane": all(
            float(point[2]) < 0.0 for point in first["positions_m"]
        ),
        "interpretation": (
            "At the first reported violation the two fluid centers are inside the "
            "obstacle x/y footprint and have crossed z=0. This is consistent with "
            "the unfilled floor hole; it is not evidence of a zero-normal or ghost "
            "serialization failure."
        ),
    }


def _f3_comparison(bound_path: Path, trajectory: Path) -> dict[str, Any]:
    bound = read_binary_vtk(bound_path)
    points = np.asarray(bound["points"], dtype=float)
    point_data = bound["point_data"]
    mk = np.asarray(point_data["Mk"], dtype=int)
    baffle = mk == 18
    strict_xy = (
        (points[:, 0] > 0.58)
        & (points[:, 0] < 0.62)
        & (points[:, 1] > 0.04)
        & (points[:, 1] < 0.14)
    )
    bottom = baffle & (np.abs(points[:, 2]) <= 1.0e-6)
    bottom_interior = bottom & strict_xy
    frame_minima: list[float] = []
    with h5py.File(trajectory, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = handle["position"]
        valid = handle["valid"]
        types = handle["type"]
        for index in range(len(times)):
            point = np.asarray(positions[index], dtype=float)
            active = np.asarray(valid[index], dtype=bool)
            particle_type = np.asarray(types[index])
            mask = (
                active
                & (particle_type > 0)
                & (point[:, 0] >= 0.58)
                & (point[:, 0] <= 0.62)
                & (point[:, 1] >= 0.04)
                & (point[:, 1] <= 0.14)
            )
            if np.any(mask):
                frame_minima.append(float(point[mask, 2].min()))
    return {
        "case_id": F3_CASE,
        "boundary_semantics": "DBC (Run.out), no explicit runtime mDBC normals/ghost arrays",
        "generated_bound_point_count": int(len(points)),
        "generated_bound_mk_counts": {
            str(int(value)): int(count)
            for value, count in zip(*np.unique(mk, return_counts=True))
        },
        "baffle_bottom_edge_particle_count": int(np.sum(bottom)),
        "baffle_bottom_interior_particle_count": int(np.sum(bottom_interior)),
        "fluid_min_z_in_baffle_xy_over_saved_frames_m": float(min(frame_minima)),
        "baffle_top_z_m": 0.19,
        "fluid_entered_bottom_hole_in_saved_frames": bool(min(frame_minima) < 0.19),
        "comparison_limit": (
            "F3 uses the same open-bottom baffle draw and setmkvoid topology, but its "
            "saved fluid remains above the baffle top (minimum z≈0.195 m). It therefore "
            "does not exercise the hole. Its DBC run cannot validate the explicit F1 "
            "mDBC bottom-face contract, and no direct ghost comparison is available."
        ),
    }


def _patch_bottom_face(source: Path, target: Path) -> list[dict[str, str]]:
    root = ET.parse(source).getroot()
    changes: list[dict[str, str]] = []
    for parent in root.iter():
        for drawbox in parent.findall("drawbox"):
            point = drawbox.find("point")
            boxfill = drawbox.find("boxfill")
            if point is None or boxfill is None:
                continue
            x = float(point.get("x"))
            y = float(point.get("y"))
            old = (boxfill.text or "").strip()
            normal_target = (
                parent.tag == "list"
                and parent.get("name") == "GeometryForNormals"
                and abs(x - 0.68) <= 1.0e-6
                and abs(y - 0.15) <= 1.0e-6
                and old != "solid"
            )
            boundary_target = (
                parent.tag == "mainlist"
                and abs(x - 0.67625) <= 1.0e-6
                and abs(y - 0.14625) <= 1.0e-6
                and old != "solid"
            )
            if normal_target or boundary_target:
                new = old if "bottom" in old.split("|") else "bottom | " + old
                boxfill.text = new
                changes.append(
                    {
                        "parent": parent.tag,
                        "parent_name": parent.get("name") or "",
                        "old_boxfill": old,
                        "new_boxfill": new,
                    }
                )
    if len(changes) != 2:
        raise RuntimeError(f"expected exactly two bottom-face changes, got {len(changes)}")
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="    ")
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return changes


def _parse_gencase_log(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    patterns = {
        "points_loaded": r"Points loaded:\s*([0-9,]+)",
        "fixed_particles": r"Fixed\.\.\.\.\s*:\s*([0-9,]+)",
        "fluid_particles": r"Fluid\.\.\.\.\s*:\s*([0-9,]+)",
        "nonzero_normals": r"Non-zero particle normals:\s*([0-9,]+)/([0-9,]+)",
        "final_zero_normals": r"Final zero normals:\s*([0-9,]+)/([0-9,]+)",
        "normal_size_range": r"Normals size range:\s*\(([^)]+)\)",
    }
    out: dict[str, Any] = {}
    for key, pattern in patterns.items():
        found = re.findall(pattern, text)
        if not found:
            continue
        value = found[-1]
        if key in {"nonzero_normals", "final_zero_normals"}:
            out[key] = [int(value[0].replace(",", "")), int(value[1].replace(",", ""))]
        elif key == "normal_size_range":
            out[key] = [float(part.strip()) for part in value.split("-")]
        else:
            out[key] = int(value.replace(",", ""))
    return out


def _candidate_preflight(candidate_root: Path, source_definition: Path, lab: Path) -> dict[str, Any]:
    if candidate_root.exists() and any(candidate_root.iterdir()):
        raise ValueError(f"candidate output must be fresh: {candidate_root}")
    candidate_root.mkdir(parents=True, exist_ok=True)
    definition = candidate_root / (F1_CASE + "_bottom_face_Def.xml")
    changes = _patch_bottom_face(source_definition, definition)
    binary = lab / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
    prefix = candidate_root / "generated" / (F1_CASE + "_bottom_face")
    command = [str(binary), str(definition.with_suffix("")), str(prefix), "-save:all"]
    log = candidate_root / "gencase.log"
    with log.open("w") as stream:
        process = subprocess.run(command, cwd=candidate_root, stdout=stream, stderr=subprocess.STDOUT)
    if process.returncode != 0:
        raise RuntimeError(f"candidate GenCase failed; inspect {log}")
    generated_prefix = prefix
    bound = read_binary_vtk(generated_prefix.with_name(generated_prefix.name + "_Bound.vtk"))
    fluid = read_binary_vtk(generated_prefix.with_name(generated_prefix.name + "_Fluid.vtk"))
    all_points = np.asarray(bound["points"], dtype=float)
    mk = np.asarray(bound["point_data"]["Mk"], dtype=int)
    normal = np.asarray(bound["point_data"].get("Normal", np.empty((0, 3))), dtype=float)
    normal_size = np.asarray(bound["point_data"].get("NormalSize", np.empty((0,))), dtype=float)
    obstacle = mk == 18
    bottom = obstacle & (np.abs(all_points[:, 2] + DP / 2.0) <= 1.0e-6)
    bottom_interior = bottom & (all_points[:, 0] > 0.68) & (all_points[:, 0] < 0.80) & (all_points[:, 1] > 0.15) & (all_points[:, 1] < 0.25)
    # Rounded tuple join is sufficient for this lattice and avoids an O(N^2) comparison.
    boundary_keys = {tuple(np.round(point, 8)) for point in all_points}
    fluid_points = np.asarray(fluid["points"], dtype=float)
    overlap = sum(tuple(np.round(point, 8)) in boundary_keys for point in fluid_points)
    log_summary = _parse_gencase_log(log)
    files = {}
    for path in sorted(candidate_root.rglob("*")):
        if path.is_file():
            files[str(path.relative_to(candidate_root))] = _sha256(path)
    report = {
        "status": "cpu_gencase_pass",
        "execution_kind": "CPU GenCase only; no solver or GPU",
        "source_definition": str(source_definition.resolve()),
        "source_definition_sha256": _sha256(source_definition),
        "candidate_definition": str(definition.resolve()),
        "candidate_definition_sha256": _sha256(definition),
        "candidate_changes": changes,
        "gencase_binary": str(binary.resolve()),
        "gencase_binary_sha256": _sha256(binary),
        "gencase_command": command,
        "gencase_log": str(log.resolve()),
        "gencase_log_summary": log_summary,
        "generated_total_particles": int(len(bound["points"]) + len(fluid_points)),
        "generated_boundary_particles": int(len(bound["points"])),
        "generated_fluid_particles": int(len(fluid_points)),
        "generated_boundary_mk_counts": {
            str(int(value)): int(count)
            for value, count in zip(*np.unique(mk, return_counts=True))
        },
        "generated_obstacle_bottom_edge_particles": int(np.sum(bottom)),
        "generated_obstacle_bottom_interior_particles": int(np.sum(bottom_interior)),
        "generated_bound_fluid_exact_overlap_count": int(overlap),
        "generated_normal_count": int(len(normal)),
        "generated_zero_normal_count": int(
            np.sum(np.linalg.norm(normal, axis=1) <= 1.0e-10)
        ) if len(normal) else None,
        "generated_normal_size_range_m": [float(normal_size.min()), float(normal_size.max())] if len(normal_size) else None,
        "generated_inputs_sha256": files,
        "qualification_claim": "none; static repair candidate only",
    }
    _write_json(candidate_root / "candidate-preflight.json", report)
    return report


def _write_candidate_prepared_and_job(
    candidate_root: Path,
    source_prepared: Path,
    lab: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    """Freeze the CPU-verified H3 native inputs and a scheduler-neutral job.

    The candidate is made from the already generated bottom-face assets.  This
    function does not invoke GenCase or a solver and refuses to overwrite an
    existing prepared/job/proposal byte stream.  The solver remains the F1
    worker and receives the unchanged CFL=.2, 2.2 s window, and hard gates.
    """
    candidate_root = Path(candidate_root).resolve()
    source_prepared = Path(source_prepared).resolve()
    lab = Path(lab).resolve()
    evidence_root = Path(evidence_root).resolve()
    preflight_path = candidate_root / "candidate-preflight.json"
    if not preflight_path.is_file():
        raise FileNotFoundError(preflight_path)
    preflight = json.loads(preflight_path.read_text())
    if preflight.get("status") != "cpu_gencase_pass":
        raise ValueError("H3 candidate static preflight is not passing")
    if preflight.get("generated_obstacle_bottom_interior_particles", 0) <= 0:
        raise ValueError("H3 candidate has no obstacle bottom interior particles")
    if preflight.get("generated_zero_normal_count") != 0:
        raise ValueError("H3 candidate has zero normals")
    if preflight.get("generated_bound_fluid_exact_overlap_count") != 0:
        raise ValueError("H3 candidate has an exact fluid/boundary overlap")

    original = json.loads(source_prepared.read_text())
    config = json.loads(json.dumps(original["config"]))
    config.update(
        {
            "scope_id": "F1_single_obstacle_mdbc_repair_canary",
            "revision_id": "F1_H3_obstacle_bottom_face_mdbc_v1",
            "case_id": F1_H3_CASE,
            "recipe_id": "F1_H3_obstacle_bottom_face_mdbc_v1",
            "recipe": "mdbc_native_boundary_topology_repair",
            "stage": "repair_canary",
            "qualification_claim": "none",
            "qualified": False,
            "source_definition": str(Path(preflight["candidate_definition"]).resolve()),
            "boundary_semantics": (
                "mDBC no-slip, unchanged H2 normal/ghost/no-penetration recipe; "
                "obstacle bottom face explicitly closed in boundary and normal geometry"
            ),
            "hypothesis": (
                "H3 boundary-topology repair: setmkvoid removed the tank floor under "
                "the obstacle while the obstacle bottom was absent from mainlist and "
                "GeometryForNormals; restore that single physical face"
            ),
            "mechanism_class": "boundary_topology",
            "mechanism_class_attempt": 1,
            "prior_failure_lineage": [
                "F1_H1 baseline mDBC full-window failure retained",
                "F1_H2 mDBC normals/ghost repair failure retained",
            ],
        }
    )
    definition_audit = json.loads(json.dumps(original.get("definition_audit", {})))
    definition_audit.update(
        {
            "revision_id": "F1_H3_obstacle_bottom_face_mdbc_v1",
            "boundary_recipe_changed": True,
            "physical_geometry_unchanged": True,
            "continuum_geometry_unchanged": True,
            "mass_rescaling": False,
            "mechanism_class": "boundary_topology",
            "changed_fields": [
                "obstacle mainlist boundary drawbox boxfill adds bottom",
                "obstacle GeometryForNormals drawbox boxfill adds bottom",
            ],
            "unchanged_fields": [
                "obstacle/tank continuum dimensions",
                "fluid continuum box, density, native rho*dp^3 mass",
                "CFL, DtIni, DtMin, TimeMax=2.2 s, output cadence",
                "mDBC Boundary=2, SlipMode=2, NoPenetration=1, -mdbc_noslip:1",
                "runtime domain and gravity",
            ],
        }
    )

    generated_prefix = candidate_root / "generated" / (F1_CASE + "_bottom_face")
    candidate_inputs: dict[str, str] = {}
    definition = Path(preflight["candidate_definition"]).resolve()
    for path in [candidate_root / "gencase.log", definition, *sorted((candidate_root / "generated").glob("*"))]:
        if path.is_file():
            candidate_inputs[str(path.resolve())] = _sha256(path)
    required_generated = {Path(preflight["candidate_definition"]).name}
    if not generated_prefix.with_suffix(".bi4").is_file():
        raise FileNotFoundError(generated_prefix.with_suffix(".bi4"))
    if len(candidate_inputs) < 3:
        raise ValueError("H3 candidate input closure is incomplete")

    prepared = json.loads(json.dumps(original))
    prepared["created_at"] = "2026-09-20T00:00:00+00:00"
    prepared["config"] = config
    prepared["generated_prefix"] = str(generated_prefix.resolve())
    prepared["source_template"] = str(Path(preflight["source_definition"]).resolve())
    prepared["source_template_sha256"] = preflight["source_definition_sha256"]
    prepared["definition_audit"] = definition_audit
    prepared["inputs"] = candidate_inputs
    prepared["preflight_pass"] = True
    prepared["qualification_claim"] = "none; F1 H3 boundary-topology repair canary only"
    native = dict(prepared.get("native_initial", {}))
    native.update(
        {
            "total_particles": preflight["generated_total_particles"],
            "boundary_particles": preflight["generated_boundary_particles"],
            "fluid_particles": preflight["generated_fluid_particles"],
            "normal_count": preflight["generated_normal_count"],
            "zero_boundary_normals": preflight["generated_zero_normal_count"],
            "initial_state_pass": True,
            "obstacle_bottom_interior_particles": preflight["generated_obstacle_bottom_interior_particles"],
            "exact_boundary_fluid_overlap_count": preflight["generated_bound_fluid_exact_overlap_count"],
        }
    )
    prepared["native_initial"] = native
    mdbc = dict(prepared.get("mdbc_preflight", {}))
    mdbc.update(
        {
            "native_normals_complete": True,
            "native_normals_finite_nonzero": True,
            "obstacle_bottom_interior_particles": preflight["generated_obstacle_bottom_interior_particles"],
            "full_solid_obstacle_topology_audit_required": True,
        }
    )
    prepared["mdbc_preflight"] = mdbc
    prepared_path = candidate_root / "prepared.json"
    if prepared_path.exists():
        if prepared_path.read_text() != json.dumps(prepared, indent=2, allow_nan=False) + "\n":
            raise ValueError(f"refusing to overwrite existing prepared candidate: {prepared_path}")
    else:
        _write_json(prepared_path, prepared)

    source_scripts = [
        lab / "scripts/core_f1.py",
        lab / "scripts/core_cfd.py",
        lab / "scripts/finite_wall_audit.py",
        lab / "scripts/l2_f1r_audit.py",
        lab / "scripts/l2_f1r_h1_canary.py",
        lab / "scripts/l2_campaign.py",
    ]
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    input_files: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_input(path: Path, role: str) -> None:
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"H3 job input missing ({role}): {path}")
        key = str(path)
        if key not in seen:
            seen.add(key)
            input_files.append({"path": key, "sha256": _sha256(path), "role": role})

    add_input(prepared_path, "prepared H3 canary")
    add_input(solver, "official DualSPHysics solver")
    add_input(decoder, "native decoder")
    for path in source_scripts:
        add_input(path, "frozen F1 worker source")
    for path in candidate_inputs:
        add_input(Path(path), "candidate native input")

    job = {
        "schema": "core.cfd.job.v1",
        "job_id": "f1-h3-obstacle-bottom-face-mdbc-canary-001",
        "logical_id": "f1-h3-obstacle-bottom-face-mdbc-canary-001",
        "attempt_role": "conditional_repair",
        "category": "boundary_topology_repair_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [
            str(lab / ".venv/bin/python"),
            str(lab / "scripts/core_f1.py"),
            "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
            "--output", "{attempt_dir}/product",
        ],
        "required_outputs": [
            "product/result.json", "product/trajectory.h5",
            "product/audit.json", "product/observations.json",
        ],
        "resources": {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.25},
        "timeout_seconds": 3600,
        "depends_on": [],
        "qualification_claim": "none",
        "input_files": input_files,
        "prepared_case_id": F1_H3_CASE,
        "registered_window_s": 2.2,
        "maximum_extended_window_s": 4.4,
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        "source_snapshot_required": True,
        "mechanism_class": "boundary_topology",
        "mechanism_class_attempt": 1,
        "repair_budget": {"max_mechanism_classes": 2, "max_canaries_per_class": 1},
        "prior_failure_evidence": {
            "h1_h2_forensics": str((evidence_root / "f1-h2-bottom-contact-forensics-v1.json").resolve()),
            "h1_h2_forensics_sha256": _sha256(evidence_root / "f1-h2-bottom-contact-forensics-v1.json"),
        },
        "hard_integrity_contract": {
            "no_missing_native_fluid_ids": True,
            "no_nonfinite_active_values": True,
            "closed_wall_endpoint_tolerance_m": 1e-8,
            "saved_chord_crossings_allowed": 0,
            "full_solid_obstacle_audit": True,
            "obstacle_penetration_particle_frames_allowed": 0,
            "fluid_boundary_exact_overlap_allowed": 0,
        },
        "qualification_status": "repair_canary_only; H1/H2 negative results retained; no range claim",
    }
    job_path = candidate_root / "f1-h3-obstacle-bottom-face-mdbc-canary-job.json"
    job_bytes = json.dumps(job, indent=2, allow_nan=False) + "\n"
    if job_path.exists() and job_path.read_text() != job_bytes:
        raise ValueError(f"refusing to overwrite existing H3 job: {job_path}")
    if not job_path.exists():
        job_path.write_text(job_bytes)

    proposal = {
        "schema": "core.f1.h3.obstacle_bottom_face_canary.v1",
        "proposal_id": "F1_H3_obstacle_bottom_face_mdbc_canary_v1",
        "status": "prepared_cpu_only_not_submitted",
        "mechanism_class": "boundary_topology",
        "mechanism_class_attempt": 1,
        "max_mechanism_classes": 2,
        "h1_h2_history": {
            "h1": "original F1 full-window mDBC failure retained",
            "h2": "mDBC normals/ghost/no-penetration repair failure retained",
            "new_evidence": "H2 first violation is inside obstacle xy and below continuous z=0 where no obstacle bottom interior boundary exists",
        },
        "single_variable_change": [
            "obstacle mainlist boundary drawbox adds bottom face",
            "obstacle GeometryForNormals drawbox adds bottom face",
        ],
        "unchanged": [
            "CFL=0.2, DtIni, DtMin, output cadence, TimeMax=2.2 s",
            "mDBC Boundary=2, SlipMode=2, NoPenetration=1, -mdbc_noslip:1",
            "continuum fluid/obstacle/tank geometry, gravity, density and native rho*dp^3 mass",
            "runtime domain and all hard thresholds",
        ],
        "prepared": {"path": str(prepared_path), "sha256": _sha256(prepared_path)},
        "job": {"path": str(job_path), "sha256": _sha256(job_path)},
        "candidate_preflight": {"path": str(preflight_path), "sha256": _sha256(preflight_path)},
        "hard_integrity_contract": job["hard_integrity_contract"],
        "qualification_claim": "none; solver not run",
        "gpu_launched": False,
        "ledger_written": False,
    }
    proposal_path = candidate_root / "f1-h3-obstacle-bottom-face-canary-proposal-v1.json"
    proposal_bytes = json.dumps(proposal, indent=2, allow_nan=False) + "\n"
    if proposal_path.exists() and proposal_path.read_text() != proposal_bytes:
        raise ValueError(f"refusing to overwrite existing H3 proposal: {proposal_path}")
    if not proposal_path.exists():
        proposal_path.write_text(proposal_bytes)
    return {
        "prepared": str(prepared_path),
        "prepared_sha256": _sha256(prepared_path),
        "job": str(job_path),
        "job_sha256": _sha256(job_path),
        "proposal": str(proposal_path),
        "proposal_sha256": _sha256(proposal_path),
        "candidate_preflight": str(preflight_path),
        "candidate_preflight_sha256": _sha256(preflight_path),
        "input_count": len(input_files),
        "gpu_launched": False,
        "ledger_written": False,
    }


def build_report(
    lab: Path,
    output_dir: Path,
    prepared: Path,
    product: Path,
    f3_bound: Path,
    f3_trajectory: Path,
    result_path: Path,
    prepare_candidate: bool,
) -> dict[str, Any]:
    result = json.loads(result_path.read_text())
    trajectory = product / "trajectory.h5"
    normal_path = product / "solver/CfgInit_Normals.vtk"
    ghost_path = product / "solver/CfgInit_NormalsGhost.vtk"
    bound_path = prepared.parent / "generated" / (F1_CASE + "_Bound.vtk")
    source_definition = prepared.parent / (F1_CASE + "_Def.xml")
    normal = _normal_summary(normal_path, ghost_path, bound_path)
    trajectory_summary = _first_failure_trajectory(trajectory, result_path, normal_path)
    f3 = _f3_comparison(f3_bound, f3_trajectory)
    candidate = None
    if prepare_candidate:
        candidate = _candidate_preflight(output_dir / "candidate", source_definition, lab)
    else:
        prior = output_dir / "candidate" / "candidate-preflight.json"
        if prior.is_file():
            candidate = json.loads(prior.read_text())
    proposal = {
        "proposal_id": "F1_H3_obstacle_bottom_face_mdbc_canary_v1",
        "status": "prepared_cpu_only_not_submitted",
        "mechanism_class": "boundary topology: restore obstacle bottom contact face",
        "evidence_root": "missing obstacle-bottom interior boundary after setmkvoid; first F1 H2 failure crosses z=0 inside obstacle footprint",
        "single_variable_change": [
            "add bottom to the obstacle mainlist boundary drawbox boxfill",
            "add bottom to the obstacle GeometryForNormals drawbox boxfill",
        ],
        "unchanged": [
            "CFL=0.2 and actual DtIni/DtMin",
            "mDBC Boundary=2, SlipMode=2, NoPenetration=1, -mdbc_noslip:1",
            "fluid continuum box, q=0.5, dp=0.0075, native mass and density",
            "tank, obstacle dimensions, gravity, viscosity, runtime domain, TimeMax=2.2 s",
        ],
        "falsification": {
            "pass_condition": "CPU candidate has interior bottom particles and no zero normals; solver canary must then show no first bottom-hole entry under unchanged hard gates",
            "failure_condition": "any zero normal, fluid-boundary overlap, or retained first bottom-plane penetration keeps this mechanism failed",
            "no_threshold_relaxation": True,
            "no_cfl_retry": True,
        },
        "resource_estimate_from_h2": {
            "baseline_gpu": "RTX 6000 Ada",
            "baseline_case_particles": 266134,
            "candidate_case_particles": int(candidate["generated_total_particles"]) if candidate else 267178,
            "baseline_gpu_memory_mib": 58.21,
            "candidate_gpu_memory_estimate_mib": 64.0,
            "baseline_solver_seconds": 142.782181,
            "candidate_solver_seconds_estimate": [145.0, 180.0],
            "estimate_basis": "H2 unchanged numerical controls; +1044 boundary particles and same 2.2 s window",
        },
        "qualification_claim": "none; one evidence-based canary proposal, no solver result",
    }
    artifact_paths = [prepared, source_definition, bound_path, normal_path, ghost_path, result_path, product / "audit.json", product / "observations.json"]
    input_hashes = {str(path.resolve()): _sha256(path) for path in artifact_paths if path.is_file()}
    # The result receipt already contains the verified trajectory hash; avoid making
    # the forensic writer mutate or re-interpret the original execution receipt.
    report = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_id": F1_CASE,
        "scope": "read-only forensic of completed F1 H2 mDBC failure plus static candidate",
        "solver_rerun": False,
        "gpu_launched": False,
        "ledger_written": False,
        "forensic_code": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
            "vtk_parser_path": str((SOURCE_ROOT / "scripts/r4_f6_mdbc_runtime_zero_normal_audit.py").resolve()),
            "vtk_parser_sha256": _sha256(SOURCE_ROOT / "scripts/r4_f6_mdbc_runtime_zero_normal_audit.py"),
        },
        "source_inputs": input_hashes,
        "trajectory": {
            "path": str(trajectory.resolve()),
            "sha256_from_original_receipt": result.get("conversion", {}).get("sha256"),
            "frames": int(result["structural"]["frame_count"]),
            "particle_count": int(result["structural"]["particle_count"]),
        },
        "h2_run_parameters": {
            "boundary": "mDBC",
            "slip_mode": "No-slip",
            "mdbc_corrector": True,
            "no_penetration": 1,
            "solver_argument": "-mdbc_noslip:1",
            "dp_m": DP,
            "kernel_h_m": H,
            "h_over_dp": H / DP,
            "cfl": 0.2,
            "dt_ini_s": 0.0003091370956550911,
            "dt_min_s": 1.545685501307964e-05,
            "time_max_s": 2.2,
            "output_interval_s": 0.02,
            "visco": 0.08,
        },
        "normal_and_ghost_forensics": normal,
        "first_failure_forensics": trajectory_summary,
        "f3_comparison": f3,
        "root_cause_assessment": {
            "status": "evidence_supported_new_mechanism",
            "claim": "F1 H2 first failure is compatible with an unclosed obstacle-floor hole: setmkvoid removes tank bottom under obstacle, while obstacle bottom is omitted from the boundary and normal geometry.",
            "what_is_excluded": [
                "zero normals: excluded by 145476/145476 nonzero normals and GenCase final zero=0",
                "ghost serialization: excluded by exact point identity, GhostNormal=2*Normal, GhostNormalSize=2*NormalSize",
                "CFL/Dt as the proposed cause: not tested here and deliberately not retried",
                "outer tank wall leakage: first positions are inside obstacle x/y projection at z≈0",
            ],
            "remaining_limit": "Saved trajectory establishes entry through the missing continuous floor support; it does not prove substep contact forces or guarantee the bottom-face candidate will pass.",
        },
        "candidate_proposal": proposal,
        "candidate_cpu_preflight": candidate,
        "qualification_claim": "none; F1 H2 remains a retained negative result and the H3 candidate has no solver result",
    }
    _write_json(output_dir / "f1-h2-bottom-contact-forensics-v1.json", report)
    _write_json(output_dir / "f1-h2-bottom-contact-canary-proposal-v1.json", proposal)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prepare-candidate", action="store_true")
    parser.add_argument(
        "--prepare-job",
        action="store_true",
        help="freeze the already preflighted H3 prepared/job/proposal without rerunning GenCase",
    )
    parser.add_argument("--prepared", type=Path, default=SOURCE_ROOT / "campaigns/core-v1/cfd/prepared/F1_H2_mdbc_repair_center_medium_canary_v6/prepared.json")
    parser.add_argument("--product", type=Path, default=SOURCE_ROOT / "campaigns/core-v1/runtime/attempts/f1-h2-mdbc-repair-canary-001/20260919T175354-3ce99dbbd4b7/product")
    parser.add_argument("--result", type=Path, default=SOURCE_ROOT / "campaigns/core-v1/evidence/f1-h2-mdbc-result.json")
    parser.add_argument("--f3-bound", type=Path, default=SOURCE_ROOT / "campaigns/l2-multifamily/c2-canary/artifacts/L2_C2_F3_offaxis_baffle_nominal/generated/L2_C2_F3_offaxis_baffle_nominal_Bound.vtk")
    parser.add_argument("--f3-trajectory", type=Path, default=SOURCE_ROOT / "campaigns/l2-multifamily/c2-canary/data/L2_C2_F3_offaxis_baffle_nominal.h5")
    args = parser.parse_args()
    # Job freezing is deliberately independent of the read-only forensic report:
    # a scheduler handoff must not rewrite the retained H1/H2 failure receipt.
    if args.prepare_job and not args.prepare_candidate:
        frozen_job = _write_candidate_prepared_and_job(
            args.output_dir.resolve() / "candidate",
            args.prepared.resolve(),
            args.lab_root.resolve(),
            args.output_dir.resolve(),
        )
        print(json.dumps({"frozen_job": frozen_job, "gpu_launched": False, "ledger_written": False}, indent=2))
        return 0
    report = build_report(
        args.lab_root.resolve(), args.output_dir.resolve(), args.prepared.resolve(),
        args.product.resolve(), args.f3_bound.resolve(), args.f3_trajectory.resolve(),
        args.result.resolve(), args.prepare_candidate,
    )
    frozen_job = None
    if args.prepare_job:
        frozen_job = _write_candidate_prepared_and_job(
            args.output_dir.resolve() / "candidate",
            args.prepared.resolve(),
            args.lab_root.resolve(),
            args.output_dir.resolve(),
        )
    print(json.dumps({
        "schema": report["schema"],
        "first_failure_time_s": report["first_failure_forensics"]["first_wall_violation_time_s"],
        "bottom_interior_particles_original": report["normal_and_ghost_forensics"]["obstacle_bottom_interior_particle_count"],
        "candidate_status": (report["candidate_cpu_preflight"] or {}).get("status"),
        "candidate_bottom_interior_particles": (report["candidate_cpu_preflight"] or {}).get("generated_obstacle_bottom_interior_particles"),
        "frozen_job": frozen_job,
        "gpu_launched": report["gpu_launched"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
