#!/usr/bin/env python3
"""CPU-only F2 moving mDBC contact forensics and one CFL repair canary.

The v2 full-cup/closed-catchment run already has a complete nonzero normal
field and a verified prescribed motion.  This module records that evidence,
then prepares one versioned copy whose only solver change is CFLnumber 0.20 to
0.10.  It never launches a solver or writes the campaign ledger.
"""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd


JOB_SCHEMA = "core.cfd.job.v1"
FORENSIC_SCHEMA = "core.f2.mdbc_contact_resolution_preflight.v1"
PREPARED_SCHEMA = "core.f2.full_cup_closed_catchment_mdbc_cfl_repair.v1"
CFL_BASE = 0.20
CFL_REPAIR = 0.10
BASE_REVISION = "F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_v2"
REPAIR_REVISION = "F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_cfl010_v1"
REPAIR_ID = "moving_mdbc_contact_time_resolution_cfl_half"
REPAIR_CASE_SUFFIX = "_cfl010_v1"
REPAIR_JOB_ID = "f2-resting-fill-side-wet-full-cup-closed-catchment-mdbc-cfl010-canary-v1-001"

BASE_PREPARED = (
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_v2/prepared.json"
)
BASE_ENTRY_FORENSICS = (
    "campaigns/core-v1/cfd/"
    "f2-full-cup-closed-catchment-mdbc-v2-moving-cup-entry-forensics.json"
)
BASE_EXCLUSION_FORENSICS = (
    "campaigns/core-v1/cfd/"
    "f2-full-cup-closed-catchment-mdbc-v2-native-exclusion-forensics.json"
)
BASE_RUNPARTS = (
    "campaigns/core-v1/cfd/"
    "f2-full-cup-closed-catchment-mdbc-v2-native-exclusion-forensics-RunPARTs.csv"
)
BASE_RUNOUT = (
    "campaigns/core-v1/cfd/"
    "f2-full-cup-closed-catchment-mdbc-v2-native-exclusion-forensics-Run.out"
)
ADAPTER_PROBE = (
    "campaigns/core-v1/evidence/f2-closed-catchment-v2-h200/"
    "core-cfd-adapter-real-probe-v1.json"
)
DECODER_RELATIVE = "campaigns/l1-resume/artifacts/bi4_dump"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _replace_name_in_text(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    path.write_text(text.replace(old, new))


def _set_cfl(xml_path: Path, value: float) -> None:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    nodes = root.findall(".//cflnumber")
    if not nodes:
        raise ValueError(f"missing cflnumber in {xml_path}")
    for node in nodes:
        node.set("value", f"{float(value):.17g}")
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _set_parameter(xml_path: Path, key: str, value: float) -> None:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        raise ValueError(f"missing execution parameter {key} in {xml_path}")
    node.set("value", f"{float(value):.17g}")
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _copy_versioned_tree(source_dir: Path, output_dir: Path, old_base: str, new_base: str) -> None:
    if output_dir.exists():
        # Permit recovery of a creator interruption before prepared.json was
        # written; never reuse a frozen prepared directory.
        if (output_dir / "prepared.json").exists():
            try:
                existing = json.loads((output_dir / "prepared.json").read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"output contains an unreadable prepared case: {output_dir}") from exc
            if existing.get("config", {}).get("revision_id") != REPAIR_REVISION:
                raise ValueError(f"output contains a different frozen prepared case: {output_dir}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_dir.rglob("*")):
        if source.is_dir() or source.name == "prepared.json":
            continue
        # The GenCase .out is a report for the old case and is not an input to
        # the worker.  Omitting it avoids binding stale CFL text as an input.
        if source.suffix == ".out":
            continue
        rel = source.relative_to(source_dir)
        rel_name = rel.name.replace(old_base, new_base)
        target = output_dir / rel.parent / rel_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if target.suffix in {".xml", ".dat"}:
            _replace_name_in_text(target, old_base, new_base)


def _native_candidate_preflight(prepared: dict) -> dict:
    prefix = Path(prepared["generated_prefix"])
    decoder = Path(prepared["decoder"])
    expected = prepared["native_initial"]
    with tempfile.TemporaryDirectory(prefix="f2-mdbc-cfl-native-") as td:
        ids, positions, velocities, density, meta, _info, arrays = core_cfd.native_frame(
            prefix.with_suffix(".bi4"), Path(td) / "native", decoder
        )
        normals = np.fromfile(Path(arrays) / "BoundNor.bin", dtype=np.float32).reshape(-1, 3)
    counts = {
        "total_particles": int(len(ids)),
        "fixed_particles": int(meta["CaseNfixed"]),
        "moving_particles": int(meta["CaseNmoving"]),
        "boundary_particles": int(meta["CaseNfixed"]) + int(meta["CaseNmoving"]),
        "fluid_particles": int(meta["CaseNfluid"]),
        "normal_count": int(len(normals)),
        "zero_boundary_normals": int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10)),
        "unique_ids": bool(len(np.unique(ids)) == len(ids)),
        "finite_initial_arrays": bool(
            np.isfinite(positions).all()
            and np.isfinite(velocities).all()
            and np.isfinite(density).all()
            and np.isfinite(normals).all()
        ),
    }
    expected_counts = {key: int(expected[key]) for key in ("total_particles", "fixed_particles", "moving_particles", "boundary_particles", "fluid_particles")}
    counts["counts_match_source"] = all(counts[key] == value for key, value in expected_counts.items())
    counts["normal_preflight_pass"] = bool(
        counts["normal_count"] == counts["boundary_particles"]
        and counts["zero_boundary_normals"] == 0
        and counts["unique_ids"]
        and counts["finite_initial_arrays"]
    )
    counts["pass"] = bool(counts["counts_match_source"] and counts["normal_preflight_pass"])
    if not counts["pass"]:
        raise ValueError(f"candidate native CPU preflight failed: {counts}")
    return counts


def _normal_audit(lab: Path, prepared: dict, event: dict) -> dict:
    prefix = Path(prepared["generated_prefix"])
    decoder = Path(prepared["decoder"])
    if not prefix.with_suffix(".bi4").is_file():
        raise FileNotFoundError(prefix.with_suffix(".bi4"))
    with tempfile.TemporaryDirectory(prefix="f2-mdbc-normals-") as td:
        ids, positions, _vel, _rho, meta, _info, arrays = core_cfd.native_frame(
            prefix.with_suffix(".bi4"), Path(td) / "native", decoder
        )
        normal_file = arrays / "BoundNor.bin"
        normals = np.fromfile(normal_file, dtype=np.float32).reshape(-1, 3)
    boundary_count = int(meta["CaseNfixed"]) + int(meta["CaseNmoving"])
    moving_start = int(meta["CaseNfixed"])
    moving_count = int(meta["CaseNmoving"])
    moving_pos = positions[moving_start : moving_start + moving_count]
    moving_normals = normals[moving_start : moving_start + moving_count]
    low = np.asarray([0.0, -0.15, 0.65], dtype=float)
    high = np.asarray([0.425, 0.15, 1.10], dtype=float)
    dp = float(prepared["config"]["dp_m"])
    face_specs = {
        "left": (0, "lo", np.asarray([1.0, 0.0, 0.0])),
        "right": (0, "hi", np.asarray([-1.0, 0.0, 0.0])),
        "front": (1, "lo", np.asarray([0.0, 1.0, 0.0])),
        "back": (1, "hi", np.asarray([0.0, -1.0, 0.0])),
        "bottom": (2, "lo", np.asarray([0.0, 0.0, 1.0])),
    }
    face_results = {}
    for name, (axis, side, expected) in face_specs.items():
        face = low[axis] if side == "lo" else high[axis]
        mask = moving_pos[:, axis] <= face + dp if side == "lo" else moving_pos[:, axis] >= face - dp
        for tangent in range(3):
            if tangent != axis:
                mask &= (moving_pos[:, tangent] >= low[tangent] + 2 * dp)
                mask &= (moving_pos[:, tangent] <= high[tangent] - 2 * dp)
        dots = moving_normals[mask] @ expected
        face_results[name] = {
            "interior_particle_count": int(mask.sum()),
            "expected_inward_dot_positive": int(np.sum(dots > 1e-10)),
            "wrong_sign_count": int(np.sum(dots < -1e-10)),
            "near_zero_count": int(np.sum(np.abs(dots) <= 1e-10)),
            "dot_min": float(dots.min()) if len(dots) else None,
            "dot_max": float(dots.max()) if len(dots) else None,
        }
    event_body = np.asarray(
        event.get("full_crossing_body_m", event["full_vector_crossing_body_m"]),
        dtype=float,
    )
    distances = np.linalg.norm(moving_pos - event_body, axis=1)
    nearest = int(np.argmin(distances))
    local_normal = moving_normals[nearest]
    local_expected = np.asarray([1.0, 0.0, 0.0])
    return {
        "decoded_native_case": meta.get("CaseName"),
        "total_particles": int(len(ids)),
        "fixed_particles": int(meta["CaseNfixed"]),
        "moving_particles": int(meta["CaseNmoving"]),
        "fluid_particles": int(meta["CaseNfluid"]),
        "normal_count": int(len(normals)),
        "finite": bool(np.isfinite(normals).all()),
        "zero_normals": int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10)),
        "normal_norm_min": float(np.linalg.norm(normals, axis=1).min()),
        "normal_norm_max": float(np.linalg.norm(normals, axis=1).max()),
        "moving_cup_face_orientation": face_results,
        "first_dynamic_cup_event_local": {
            "event_body_m": event_body.tolist(),
            "nearest_boundary_id": int(ids[moving_start + nearest]),
            "nearest_boundary_position_m": moving_pos[nearest].tolist(),
            "nearest_normal": local_normal.tolist(),
            "expected_left_face_inward_normal": local_expected.tolist(),
            "expected_dot": float(local_normal @ local_expected),
            "distance_m": float(distances[nearest]),
        },
        "normal_preflight_pass": bool(
            len(normals) == boundary_count
            and np.isfinite(normals).all()
            and np.all(np.linalg.norm(normals, axis=1) > 1e-10)
        ),
    }


def _parse_runparts(path: Path, target_time: float) -> dict:
    rows = []
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        for row in reader:
            try:
                if not row.get("TimeStep [s]") or not row.get("DtMin [s]") or not row.get("DtMax [s]"):
                    continue
                time_value = float(row["TimeStep [s]"])
                dt_min = float(row["DtMin [s]"])
                dt_max = float(row["DtMax [s]"])
            except (KeyError, ValueError):
                continue
            rows.append((abs(time_value - target_time), time_value, dt_min, dt_max, int(row["Steps"])))
    rows.sort()
    near = rows[:3]
    return {
        "nearest_rows": [
            {"time_s": t, "dt_min_s": dmin, "dt_max_s": dmax, "steps": steps}
            for _distance, t, dmin, dmax, steps in near
        ],
        "nearest_dt_min_s": float(min(item[2] for item in near)) if near else None,
        "nearest_dt_max_s": float(max(item[3] for item in near)) if near else None,
    }


def _motion_and_solver_audit(lab: Path, prepared: dict, entry: dict, runout: Path, runparts: Path) -> dict:
    xml_path = Path(prepared["generated_prefix"]).with_suffix(".xml")
    root = ET.parse(xml_path).getroot()
    cfl = root.find(".//cflnumber")
    parameters = {
        node.get("key"): float(node.get("value"))
        for node in root.findall(".//execution/parameters/parameter")
        if node.get("key") in {"DtIni", "DtMin", "DtFixed", "TimeMax", "TimeOut", "Boundary", "SlipMode"}
    }
    motion = root.find(".//casedef/motion/objreal/mvrotfile")
    axis1 = motion.find("axisp1") if motion is not None else None
    axis2 = motion.find("axisp2") if motion is not None else None
    motion_file_node = motion.find("file") if motion is not None else None
    motion_file = xml_path.parent / motion_file_node.get("name") if motion_file_node is not None else None
    motion_rows = []
    if motion_file is not None and motion_file.is_file():
        with motion_file.open() as stream:
            for line in stream:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.strip().split(";")
                if len(parts) >= 2:
                    motion_rows.append((float(parts[0]), float(parts[1])))
    warning_times = []
    for line in runout.read_text().splitlines():
        if "DTs adjusted to DtMin" not in line:
            continue
        marker = "(t:"
        if marker in line:
            try:
                warning_times.append(float(line.split(marker, 1)[1].split(",", 1)[0]))
            except ValueError:
                pass
    event_time = float(entry["time_s"])
    nearest_motion_row = min(motion_rows, key=lambda row: abs(row[0] - event_time)) if motion_rows else None
    if motion_rows:
        nearest_index = min(range(len(motion_rows)), key=lambda i: abs(motion_rows[i][0] - event_time))
        if 0 < nearest_index < len(motion_rows) - 1:
            left, right = motion_rows[nearest_index - 1], motion_rows[nearest_index + 1]
            file_rate_deg_s = (right[1] - left[1]) / (right[0] - left[0])
        elif nearest_index + 1 < len(motion_rows):
            left, right = motion_rows[nearest_index], motion_rows[nearest_index + 1]
            file_rate_deg_s = (right[1] - left[1]) / (right[0] - left[0])
        else:
            left, right = motion_rows[nearest_index - 1], motion_rows[nearest_index]
            file_rate_deg_s = (right[1] - left[1]) / (right[0] - left[0])
    else:
        file_rate_deg_s = None
    file_rate_rad_s = None if file_rate_deg_s is None else math.radians(file_rate_deg_s)
    physical_rate_rad_s = None if file_rate_rad_s is None else -file_rate_rad_s
    body = np.asarray(entry["full_vector_crossing_body_m"], dtype=float)
    pivot = np.asarray([0.0, 0.0, 0.65])
    angle_file_deg = float(entry["prescribed_angle_degrees"])
    angle_physical_rad = -math.radians(angle_file_deg)
    cs, sn = math.cos(angle_physical_rad), math.sin(angle_physical_rad)
    ry_minus_file = np.asarray([[cs, 0.0, sn], [0.0, 1.0, 0.0], [-sn, 0.0, cs]])
    world_relative = ry_minus_file @ (body - pivot)
    expected_wall_velocity = np.cross(np.asarray([0.0, physical_rate_rad_s or 0.0, 0.0]), world_relative)
    reported_wall_velocity = np.asarray(entry["wall_velocity_at_full_crossing_m_s"], dtype=float)
    return {
        "generated_xml": str(xml_path),
        "generated_xml_sha256": digest(xml_path),
        "cflnumber": None if cfl is None else float(cfl.get("value")),
        "execution_parameters": parameters,
        "boundary_method": parameters.get("Boundary"),
        "slip_mode": parameters.get("SlipMode"),
        "motion": {
            "axis1": None if axis1 is None else dict(axis1.attrib),
            "axis2": None if axis2 is None else dict(axis2.attrib),
            "motion_file": None if motion_file is None else str(motion_file),
            "motion_file_sha256": None if motion_file is None else digest(motion_file),
            "row_count": len(motion_rows),
            "first_row": motion_rows[0] if motion_rows else None,
            "last_row": motion_rows[-1] if motion_rows else None,
            "duration_attribute_s": None if motion is None else float(motion.get("duration")),
            "motion_angle_at_nearest_saved_event_deg": nearest_motion_row[1] if nearest_motion_row else None,
            "file_angle_rate_rad_s": file_rate_rad_s,
            "physical_world_angular_rate_y_rad_s": physical_rate_rad_s,
            "native_axis_convention": "for XML axis p1=(0,-1,0.65) to p2=(0,1,0.65), official MatrixRot yields world_from_body=Ry(-file_angle); the file derivative and physical +y angular rate therefore have opposite signs",
            "source_rotation_code": {
                "JMatrix4_h": str((lab / "vendor/official/DualSPHysics_v5.4/src/source/JMatrix4.h").resolve()),
                "JMotionObj_cpp": str((lab / "vendor/official/DualSPHysics_v5.4/src/source/JMotionObj.cpp").resolve()),
                "JMatrix4_h_sha256": digest(lab / "vendor/official/DualSPHysics_v5.4/src/source/JMatrix4.h"),
                "JMotionObj_cpp_sha256": digest(lab / "vendor/official/DualSPHysics_v5.4/src/source/JMotionObj.cpp"),
            },
            "wall_velocity_check": {
                "reported_m_s": reported_wall_velocity.tolist(),
                "from_native_axis_and_file_m_s": expected_wall_velocity.tolist(),
                "max_abs_difference_m_s": float(np.max(np.abs(reported_wall_velocity - expected_wall_velocity))),
                "body_point_used_m": body.tolist(),
            },
        },
        "runparts": _parse_runparts(runparts, event_time),
        "dtmin_adjustment_warning_times_s": warning_times,
        "dtmin_adjustment_before_first_cup_event": bool(any(t <= event_time for t in warning_times)),
        "interpretation": {
            "motion_implementation": "generated axis/file and native prescribed wall motion are bound; event report wall velocity agrees with the same rigid-body transform",
            "time_step": "the first cup event precedes every DtMin clamp in Run.out; CFL is a numerical contact-resolution hypothesis, not a repaired input/configuration error",
        },
    }


def make_forensics(lab: Path, prepared_path: Path, output: Path) -> dict:
    prepared = json.loads(prepared_path.read_text())
    entry_path = lab / BASE_ENTRY_FORENSICS
    exclusion_path = lab / BASE_EXCLUSION_FORENSICS
    runparts_path = lab / BASE_RUNPARTS
    runout_path = lab / BASE_RUNOUT
    entry_report = json.loads(entry_path.read_text())
    first_event = entry_report["full_vector_reaudit"]["events"][0]
    normal = _normal_audit(lab, prepared, first_event)
    motion = _motion_and_solver_audit(lab, prepared, first_event, runout_path, runparts_path)
    exclusion = json.loads(exclusion_path.read_text())
    adapter_path = lab / ADAPTER_PROBE
    adapter = json.loads(adapter_path.read_text()) if adapter_path.is_file() else None
    report = {
        "schema": FORENSIC_SCHEMA,
        "created_at": stamp(),
        "read_only": True,
        "solver_relaunched": False,
        "qualification_claim": None,
        "forensic_code": {
            "path": str(Path(__file__).resolve()),
            "sha256": digest(Path(__file__).resolve()),
            "version": "contact-preflight-v1; read-only native normal/motion/CFL evidence",
        },
        "prepared": str(prepared_path.resolve()),
        "prepared_sha256": digest(prepared_path),
        "entry_forensics": {"path": str(entry_path.resolve()), "sha256": digest(entry_path)},
        "native_exclusion_forensics": {"path": str(exclusion_path.resolve()), "sha256": digest(exclusion_path)},
        "native_solver_artifacts": {
            "runparts": str(runparts_path.resolve()),
            "runparts_sha256": digest(runparts_path),
            "run_out": str(runout_path.resolve()),
            "run_out_sha256": digest(runout_path),
            "classification": exclusion["native_solver_artifacts"]["classification"],
        },
        "first_dynamic_cup_event": {
            "frame_index": int(first_event["frame_index"]),
            "time_s": float(first_event["time_s"]),
            "particle_id": int(first_event["particle_id"]),
            "face": first_event["face"],
            "previous_body_m": first_event["previous_body_m"],
            "current_body_m": first_event["current_body_m"],
            "full_crossing_body_m": first_event.get(
                "full_crossing_body_m", first_event["full_vector_crossing_body_m"]
            ),
            "relative_outward_normal_velocity_m_s": first_event["relative_outward_normal_velocity_m_s"],
            "saved_chord_limitation": "a saved-frame chord is not a proof of a continuous substep path",
        },
        "normal_audit": normal,
        "motion_and_time_audit": motion,
        "public_adapter_motion_crosscheck": {
            "adapter_probe": None if adapter is None else str(adapter_path.resolve()),
            "adapter_probe_sha256": None if adapter is None else digest(adapter_path),
            "adapter_geometry_code": str((lab / "scripts/core_cfd_dataset.py").resolve()),
            "adapter_geometry_code_sha256": digest(lab / "scripts/core_cfd_dataset.py"),
            "adapter_contract_code": str((lab / "scripts/core_contract.py").resolve()),
            "adapter_contract_code_sha256": digest(lab / "scripts/core_contract.py"),
            "adapter_pose_at_probe": None if adapter is None else adapter.get("known_inputs", {}).get("pose_world_from_body"),
            "adapter_angular_velocity_at_probe": None if adapter is None else adapter.get("known_inputs", {}).get("rigid_angular_velocity_rad_s"),
            "sign_reconciliation": "The public PrescribedGeometry Rodrigues implementation currently applies +axis_direction*file_angle, while the official JMotionObj/JMatrix4 arbitrary-axis XML path with p1=(0,-1,0.65), p2=(0,1,0.65) yields world_from_body=Ry(-file_angle). The original solver audit therefore keeps Ry(-file_angle), which reproduces the recorded wall velocity; the public adapter sign difference is a separate adapter-contract issue and is not used to reinterpret this solver run.",
            "solver_side_evidence": "official JMatrix4.h/JMotionObj.cpp hashes and first-event wall-velocity residual are bound above",
        },
        "mechanism_classification": {
            "static_zero_normal_input_defect": False,
            "rigid_motion_axis_or_file_mismatch": False,
            "pre_event_dtmin_clamp": False,
            "supported_single_variable_candidate": REPAIR_ID,
            "candidate_change": {"path": "generated XML and Def.xml constantsdef/cflnumber", "from": CFL_BASE, "to": CFL_REPAIR},
            "unchanged": [
                "full-cup v3 native initial lattice and mass policy",
                "cup, receiver, retained tray floor and four catchment walls",
                "mDBC Boundary=2, no-slip flag, normal geometry, motion file and axis",
                "time horizon, output cadence, gravity, EOS and viscosity",
            ],
        },
        "limitations": [
            "normal preflight and local orientation do not prove the saved-frame entry is a continuous physical penetration",
            "native NpOutRho exclusions do not identify a unique density-correction cause",
            "the CFL canary tests contact time resolution only and remains qualification_only",
        ],
    }
    write_json(output, report)
    return report


def prepare_cfl_candidate(lab: Path, source_prepared: Path, output_dir: Path) -> dict:
    source_prepared = Path(source_prepared).resolve()
    output_dir = Path(output_dir).resolve()
    source = json.loads(source_prepared.read_text())
    source_config = source.get("config", {})
    if source_config.get("revision_id") != BASE_REVISION:
        raise ValueError("source is not the frozen full-cup closed-catchment mDBC v2 prepared case")
    if not source.get("preflight_pass") or source_config.get("qualification_only") is not True:
        raise ValueError("source must be a passed qualification_only CPU prepared case")
    if not math.isclose(float(source_config.get("cfl")), CFL_BASE, abs_tol=1e-12):
        raise ValueError("source CFL is not the baseline 0.20")
    source_dir = source_prepared.parent
    old_base = Path(source["generated_prefix"]).name
    new_base = old_base + REPAIR_CASE_SUFFIX
    _copy_versioned_tree(source_dir, output_dir, old_base, new_base)
    new_def = output_dir / f"{new_base}_Def.xml"
    new_generated_prefix = output_dir / "generated" / new_base
    new_xml = new_generated_prefix.with_suffix(".xml")
    _set_cfl(new_def, CFL_REPAIR)
    _set_cfl(new_xml, CFL_REPAIR)
    for key in ("DtIni", "DtMin", "DtFixed"):
        _set_parameter(new_def, key, float(source_config["time_control"][key]))
        _set_parameter(new_xml, key, float(source_config["time_control"][key]))
    # The source files are copied byte-for-byte except for the case-name text
    # in XML and the one CFL value.  All native particle and normal assets are
    # therefore the exact v2 inputs.
    prepared = copy.deepcopy(source)
    config = prepared["config"]
    config["schema"] = PREPARED_SCHEMA
    config["revision_id"] = REPAIR_REVISION
    config["case_id"] = source_config["case_id"] + REPAIR_CASE_SUFFIX
    config["recipe_id"] = source_config["recipe_id"] + "_cfl010"
    config["repair_candidate_id"] = REPAIR_ID
    config["cfl"] = CFL_REPAIR
    config["time_control"] = dict(source_config["time_control"], cflnumber=CFL_REPAIR)
    config["motion_solver_convention"] = {
        "xml_axis_p1": [0.0, -1.0, 0.65],
        "xml_axis_p2": [0.0, 1.0, 0.65],
        "file_angle_units": "degrees",
        "official_solver_world_from_body": "Ry(-file_angle) for this XML axis path",
        "public_adapter_reconciliation_required": True,
        "evidence": "f2-full-cup-closed-catchment-mdbc-v2-motion-contact-preflight-v1",
    }
    config["qualification_only"] = True
    config["qualification_claim"] = "none; independent CFL contact-resolution canary only"
    config["qualified"] = False
    config["definition_audit"] = copy.deepcopy(source_config["definition_audit"])
    config["definition_audit"]["definition"] = str(new_def)
    config["definition_audit"]["definition_sha256"] = digest(new_def)
    config["definition_audit"]["changed_fields"] = list(config["definition_audit"]["changed_fields"]) + [
        "single numerical contact-resolution change: CFLnumber 0.20 -> 0.10",
    ]
    config["definition_audit"]["qualification_claim"] = "none"
    config["definition_audit"]["unchanged_fields"] = list(config["definition_audit"]["unchanged_fields"]) + [
        "mDBC normal construction, rigid motion and all physical geometry",
        "DtIni, DtMin, DtFixed, TimeMax and TimeOut",
    ]
    config["dynamic_canary_preflight"] = copy.deepcopy(prepared.get("dynamic_canary_preflight", {}))
    config["dynamic_canary_preflight"]["single_variable_change"] = {
        "field": "time_control.cflnumber",
        "baseline": CFL_BASE,
        "candidate": CFL_REPAIR,
    }
    config["dynamic_canary_preflight"]["qualification_only"] = True
    prepared["revision_basis"] = {
        "source_prepared": str(source_prepared),
        "source_prepared_sha256": digest(source_prepared),
        "change": "only cflnumber in Def.xml/generated solver XML and matching config metadata",
        "source_geometry_bytes_reused": True,
        "native_particle_assets_reused": True,
    }
    prepared["generated_prefix"] = str(new_generated_prefix)
    prepared["source_template"] = str(new_def)
    prepared["source_template_sha256"] = digest(new_def)
    prepared["definition_audit"] = config["definition_audit"]
    prepared["qualification_only"] = True
    prepared["qualification_claim"] = "none; independent CFL contact-resolution canary only"
    prepared["native_candidate_preflight"] = _native_candidate_preflight(prepared)
    prepared["preflight_pass"] = bool(prepared["native_candidate_preflight"]["pass"])
    # Rebind copied motion and definition paths while preserving their bytes.
    prepared["definition_audit"]["motion_file"] = str(output_dir / (new_base + "_motion.dat"))
    prepared["definition_audit"]["motion_sha256"] = digest(Path(prepared["definition_audit"]["motion_file"]))
    inputs = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "prepared.json":
            inputs[str(path.resolve())] = digest(path)
    prepared["inputs"] = inputs
    write_json(output_dir / "prepared.json", prepared)
    return prepared


def make_job(lab: Path, prepared_path: Path, output: Path) -> dict:
    prepared_path = Path(prepared_path).resolve()
    prepared = json.loads(prepared_path.read_text())
    config = prepared.get("config", {})
    if config.get("revision_id") != REPAIR_REVISION or config.get("repair_candidate_id") != REPAIR_ID:
        raise ValueError("prepared case is not the CFL repair candidate")
    if config.get("qualification_only") is not True or config.get("split") != "qualification_only":
        raise ValueError("repair candidate must remain qualification_only")
    if not math.isclose(float(config.get("cfl")), CFL_REPAIR, abs_tol=1e-12):
        raise ValueError("candidate CFL is not 0.10")
    if not prepared.get("preflight_pass"):
        raise ValueError("candidate preflight failed")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    runner = lab / "scripts/core_f2_qualification.py"
    creator = lab / "scripts/f2_full_cup_closed_catchment_mdbc_contact.py"
    baseline_usage = lab / "campaigns/core-v1/cfd/f2-full-cup-closed-catchment-mdbc-v2-root-integration.json"
    baseline = json.loads(baseline_usage.read_text())["usage"]
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": REPAIR_JOB_ID,
        "logical_id": REPAIR_JOB_ID,
        "attempt_role": "f2_full_cup_closed_catchment_mdbc_cfl_contact_repair_canary",
        "category": "f2_dynamic_full_cup_closed_catchment_mdbc_repair_canary",
        "host": "h200",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(runner), "--lab-root", str(lab), "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "split": "qualification_only",
        "qualification_status": "candidate-only; no range or T1 qualification",
        "launch_recommendation": "root review/queue only; do not launch automatically from this script",
        "input_files": [
            {"path": str(prepared_path), "sha256": digest(prepared_path)},
            {"path": str(solver), "sha256": digest(solver)},
            {"path": str(decoder), "sha256": digest(decoder)},
            {"path": str(runner), "sha256": digest(runner)},
            {"path": str(creator), "sha256": digest(creator)},
        ],
        "prepared_case_id": config["case_id"],
        "scope_id": config["scope_id"],
        "revision_id": config["revision_id"],
        "family": "F2",
        "repair_candidate_id": REPAIR_ID,
        "registered_window_s": float(config["time_max_s"]),
        "maximum_extended_window_s": float(config["maximum_extended_time_s"]),
        "motion_start_s": float(config["motion_start_s"]),
        "rotation_duration_s": 0.85,
        "angle_degrees": float(config["angle_degrees"]),
        "single_variable_change": {
            "field": "time_control.cflnumber",
            "baseline": CFL_BASE,
            "candidate": CFL_REPAIR,
            "all_other_prepared_fields_equal_to_v2": True,
        },
        "motion_sign_reconciliation": {
            "solver_world_from_body": "Ry(-file_angle) for the official XML axis p1=(0,-1,0.65) to p2=(0,1,0.65)",
            "public_adapter_status": "separate sign reconciliation required; this candidate uses the native solver audit convention",
        },
        "geometry_contract": {
            "full_cup_initial_state_reused": True,
            "catchment_geometry_reused": True,
            "normal_construction_reused": True,
            "motion_axis_and_file_reused": True,
            "mass_rescaling": False,
        },
        "resource_estimate": {
            "baseline_wall_seconds": baseline["wall_seconds"],
            "baseline_cpu_seconds_children": baseline["cpu_seconds_children"],
            "expected_wall_seconds_range": [420.0, 720.0],
            "expected_cpu_seconds_children_range": [450.0, 800.0],
            "observed_baseline_peak_gpu_mib": baseline["peak_gpu_mib_sampled"],
            "expected_peak_gpu_mib": 2048,
            "scheduler_gpu_reservation_mib": 12288,
            "estimate_basis": "same 692,158 particles and cells; halving CFL may approximately double substeps, while memory is unchanged",
        },
        "observer_contract": config["wall_audit_contract"],
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0; output is attempt_dir/product",
    }
    write_json(output, spec)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("forensics")
    p.add_argument("--prepared", type=Path, default=None)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source-prepared", type=Path, default=None)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = args.lab_root.resolve()
    if args.command == "forensics":
        prepared = args.prepared or (lab / BASE_PREPARED)
        result = make_forensics(lab, prepared.resolve(), args.output.resolve())
    elif args.command == "prepare":
        source = args.source_prepared or (lab / BASE_PREPARED)
        result = prepare_cfl_candidate(lab, source.resolve(), args.output.resolve())
    else:
        result = make_job(lab, args.prepared.resolve(), args.output.resolve())
    print(json.dumps({
        "command": args.command,
        "preflight_pass": result.get("preflight_pass"),
        "qualification_only": result.get("qualification_only", result.get("config", {}).get("qualification_only")),
        "revision_id": result.get("revision_id", result.get("config", {}).get("revision_id")),
        "prepared_case_id": result.get("prepared_case_id", result.get("config", {}).get("case_id")),
        "job_id": result.get("job_id"),
        "zero_normals": result.get("normal_audit", {}).get("zero_normals"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
