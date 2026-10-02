#!/usr/bin/env python3
"""Typed trajectory conversion and rigid-body dynamic state materialization for F6 DP025 postprocessing.

Reads DualSPHysics BI4 solver outputs and rigid body motion logs (FloatingInfo)
and materializes DS-DATA-02 typed trajectory.h5 with complete 6-DOF rigid body state.

This additive F6 converter preserves the fixed first-frame identity axis while
representing native particle exclusions with valid=false and NaN state values.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

FAMILY_ID = "F6"
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F6"
PROD_DIR = FAMILY_DIR / "production"
OWNER_METADATA_DIR = PROD_DIR / "owner_metadata"
REQUESTS_DIR = FAMILY_DIR / "requests"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")

BIN_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = BIN_ROOT / "PartVTK_linux64"
FLOATINGINFO = BIN_ROOT / "FloatingInfo_linux64"
COMPUTEFORCES = BIN_ROOT / "ComputeForces_linux64"

STAGE8_CASES = [
    ("F6_000_simple_free_response", "simple_free_response", 240, 2),
    ("F6_001_wave_no_contact", "wave_no_contact", 240, 2),
    ("F6_002_simple_free_response", "simple_free_response", 240, 5),
    ("F6_003_wave_no_contact", "wave_no_contact", 240, 5),
    ("F6_004_simple_free_response", "simple_free_response", 240, 6),
    ("F6_005_wave_no_contact", "wave_no_contact", 240, 6),
    ("F6_006_simple_free_response", "simple_free_response", 240, 7),
    ("F6_007_wave_no_contact", "wave_no_contact", 240, 7),
]

TYPE_BY_TAG = {"fixed": 0, "moving": 1, "floating": 2, "fluid": 3}
FRAME_RE = re.compile(r"^Part_(\d{4,})\.bi4$")


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def ensure_owner_metadata(case_id: str) -> Path:
    """Generate or retrieve owner metadata for an F6 Stage 8 case."""
    OWNER_METADATA_DIR.mkdir(parents=True, exist_ok=True)
    owner_file = OWNER_METADATA_DIR / f"{case_id}.owner.json"
    if owner_file.is_file():
        return owner_file

    roster_path = PROD_DIR / "stage8_roster.json"
    if not roster_path.is_file():
        raise FileNotFoundError(f"stage8_roster.json not found: {roster_path}")

    roster_data = json.loads(roster_path.read_text(encoding="utf-8"))
    case_info = next((c for c in roster_data["cases"] if c["case_id"] == case_id), None)
    if not case_info:
        raise KeyError(f"Case {case_id} not found in stage8_roster.json")

    summary_path = PROD_DIR / "stage8_production_summary.json"
    audit_counts = {}
    if summary_path.is_file():
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        case_audit = next((a for a in summary_data.get("audits", []) if a["case_id"] == case_id), None)
        if case_audit:
            audit_counts = case_audit.get("actual_counts", {})

    gencase_receipt_path = DATA_ROOT / case_id / f"{case_id}_GENCASE_01" / "execution-receipt.json"
    if not gencase_receipt_path.is_file():
        r_path = case_info.get("request", {}).get("receipt_path")
        if r_path:
            gencase_receipt_path = Path(r_path)
    gencase_sha256 = sha256_file(gencase_receipt_path) if gencase_receipt_path.is_file() else None

    is_simple = case_info["mechanism_id"] == "simple_free_response"
    owner_data = {
        "case_id": case_id,
        "family_id": "F6",
        "mechanism_id": case_info["mechanism_id"],
        "physical_case_id": case_info["physical_case_id"],
        "paired_background_id": case_info["paired_background_id"],
        "split": case_info["split"],
        "target_role": case_info["target_role"],
        "dp_m": case_info["dp_m"],
        "assigned_gpu": case_info["assigned_gpu"],
        "permitted_gpus": [2, 5, 6, 7],
        "gencase_receipt": str(gencase_receipt_path),
        "gencase_receipt_sha256": gencase_sha256,
        "total_particles": audit_counts.get("total", case_info["estimated_counts"]["total"]),
        "fluid_particles": audit_counts.get("fluid", case_info["estimated_counts"]["fluid"]),
        "floating_particles": audit_counts.get("floating", case_info["estimated_counts"]["floating"]),
        "fixed_particles": audit_counts.get("fixed", case_info["estimated_counts"]["fixed"]),
        "moving_particles": audit_counts.get("moving", case_info["estimated_counts"]["moving"]),
        "solver_dimension": 3,
        "contact_policy": case_info["contact_policy"],
        "physical_binding": {
            "control_family_id": "F6_CTRL_INITIAL_RELEASE" if is_simple else "F6_CTRL_REGULAR_PISTON_WAVE",
            "geometry_family_id": "F6_BOX_TANK_FREE_BODY" if is_simple else "F6_BOX_TANK_WAVE_PADDLE",
            "density_kg_m3": 1000.0,
            "event_window": {
                "time_start_s": 0.0,
                "time_end_s": 12.0,
                "output_interval_s": 0.05,
            },
        },
        "body": case_info["body"],
        "parameters": case_info["parameters"],
        "written_at_utc": now_str(),
    }
    owner_file.write_text(json.dumps(owner_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return owner_file


def parse_gencase_xml(xml_path: Path) -> dict[str, Any]:
    """Parse particle groups and physical constants from GenCase XML."""
    import xml.etree.ElementTree as ET

    root = ET.parse(xml_path).getroot()
    particles = root.find(".//execution/particles") or root.find(".//particles")
    constants = root.find(".//execution/constants") or root.find(".//constants")
    if particles is None or constants is None:
        raise ValueError(f"XML missing particles or constants: {xml_path}")

    groups = []
    for node in particles:
        if node.tag in TYPE_BY_TAG and node.get("begin") is not None:
            groups.append({
                "role": node.tag,
                "type": TYPE_BY_TAG[node.tag],
                "begin": int(node.get("begin")),
                "count": int(node.get("count", "0")),
                "mk": int(node.get("mk", "0")),
                "mkbound": int(node.get("mkbound", "0")) if node.get("mkbound") is not None else None,
            })
    groups.sort(key=lambda g: g["begin"])

    floating_node = particles.find("floating")
    massbody = float(floating_node.find("massbody").get("value", "nan")) if floating_node is not None and floating_node.find("massbody") is not None else None
    masspart = float(floating_node.find("masspart").get("value", "nan")) if floating_node is not None and floating_node.find("masspart") is not None else None

    # Inertia tensor
    inertia = None
    if floating_node is not None and floating_node.find("inertia") is not None:
        inode = floating_node.find("inertia")
        try:
            # Current GenCase floating XML uses diagonal x/y/z attributes;
            # accept legacy Ixx/Iyy/Izz only as an explicit fallback.
            def _diag(primary: str, legacy: str) -> float:
                value = inode.get(primary)
                if value is None:
                    value = inode.get(legacy, "0")
                return float(value)

            def _offdiag(primary: str, legacy: str) -> float:
                return float(inode.get(primary, inode.get(legacy, "0")))

            inertia = [
                [_diag("x", "Ixx"), _offdiag("xy", "Ixy"), _offdiag("xz", "Ixz")],
                [_offdiag("xy", "Ixy"), _diag("y", "Iyy"), _offdiag("yz", "Iyz")],
                [_offdiag("xz", "Ixz"), _offdiag("yz", "Iyz"), _diag("z", "Izz")],
            ]
        except Exception:
            pass

    return {
        "groups": groups,
        "np": int(particles.get("np", sum(g["count"] for g in groups))),
        "dp": float(constants.find("dp").get("value")),
        "rhop0": float(constants.find("rhop0").get("value")),
        "gamma": float(constants.find("gamma").get("value")),
        "b": float(constants.find("b").get("value")),
        "massfluid": float(constants.find("massfluid").get("value")),
        "massbound": float(constants.find("massbound").get("value", constants.find("massfluid").get("value"))),
        "massbody_kg": massbody,
        "masspart_kg": masspart,
        "floating_inertia_kg_m2": inertia,
    }


def quaternion_from_euler_deg(roll: float, pitch: float, yaw: float) -> list[float]:
    """Convert FloatingInfo roll, pitch, yaw (deg) to intrinsic XYZ unit quaternion [x, y, z, w]."""
    r, p, y = (math.radians(v) for v in (roll, pitch, yaw))
    cr, sr = math.cos(r / 2.0), math.sin(r / 2.0)
    cp, sp = math.cos(p / 2.0), math.sin(p / 2.0)
    cy, sy = math.cos(y / 2.0), math.sin(y / 2.0)
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    qw = cr * cp * cy + sr * sp * sy
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm > 0:
        qx /= norm
        qy /= norm
        qz /= norm
        qw /= norm
    return [qx, qy, qz, qw]


def ensure_floating_motion_csv(data_dir: Path, output_csv: Path | None = None) -> Path:
    """Ensure FloatingMotion CSV or Floating_Actual CSV exists by running FloatingInfo if necessary."""
    data_dir = Path(data_dir).resolve()
    parent = data_dir.parent
    candidates = (
        sorted(parent.glob("Floating_Actual*.csv"))
        + sorted(parent.glob("post/Floating_Actual*.csv"))
        + sorted(data_dir.glob("Floating_Actual*.csv"))
        + sorted(parent.glob("post/FloatingMotion*.csv"))
        + sorted(data_dir.glob("FloatingMotion*.csv"))
        + sorted(parent.glob("FloatingMotion*.csv"))
    )
    if candidates:
        return candidates[0]

    dest_csv = output_csv or data_dir.parent / "post/FloatingMotion_mk60.csv"
    dest_csv.parent.mkdir(parents=True, exist_ok=True)
    stem = dest_csv.with_suffix("")

    cmd = [
        str(FLOATINGINFO),
        "-dirdata", str(data_dir),
        "-onlymk:60",
        "-savedata", str(stem),
        "-savemotion:1",
        "-csvsep:0",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=dest_csv.parent)
    if res.returncode != 0:
        raise RuntimeError(f"FloatingInfo failed (code {res.returncode}): {res.stderr}")

    out_file = dest_csv.parent / f"{stem.name}_mk60.csv"
    if out_file.is_file():
        return out_file
    if dest_csv.is_file():
        return dest_csv
    found = sorted(dest_csv.parent.glob(f"{stem.name}*.csv"))
    if found:
        return found[0]
    raise FileNotFoundError(f"FloatingInfo did not produce motion CSV under {dest_csv.parent}")


def parse_floating_motion_csv(csv_path: Path) -> dict[str, np.ndarray]:
    """Parse FloatingInfo or Floating_Actual motion CSV into typed arrays."""
    text = csv_path.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        raise ValueError(f"Empty motion CSV: {csv_path}")

    delimiter = ";" if lines[0].count(";") >= lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    headers = [h.strip() for h in (reader.fieldnames or [])]

    def find_col_opt(candidates: Sequence[str]) -> str | None:
        for c in candidates:
            for h in headers:
                hl = h.lower()
                cl = c.lower()
                if hl == cl or hl.startswith(cl):
                    return h
        return None

    def find_col(candidates: Sequence[str], desc: str) -> str:
        col = find_col_opt(candidates)
        if col is not None:
            return col
        raise KeyError(f"Column for {desc!r} (candidates={candidates}) not found in {headers}")

    time_col = find_col(["time", "t"], "time")
    center_x = find_col(["center.x", "pos.x", "pos_x", "center_x", "x"], "center.x")
    center_y = find_col(["center.y", "pos.y", "pos_y", "center_y", "y"], "center.y")
    center_z = find_col(["center.z", "pos.z", "pos_z", "center_z", "z"], "center.z")

    fvel_x = find_col_opt(["fvel.x", "vel.x", "vel_x", "fvel_x", "vx", "u"])
    fvel_y = find_col_opt(["fvel.y", "vel.y", "vel_y", "fvel_y", "vy", "v"])
    fvel_z = find_col_opt(["fvel.z", "vel.z", "vel_z", "fvel_z", "vz", "w"])

    fomega_x = find_col_opt(["fomega.x", "omega.x", "omega_x", "fomega_x", "wx", "rotvel_x"])
    fomega_y = find_col_opt(["fomega.y", "omega.y", "omega_y", "fomega_y", "wy", "rotvel_y"])
    fomega_z = find_col_opt(["fomega.z", "omega.z", "omega_z", "fomega_z", "wz", "rotvel_z"])

    surge_col = find_col_opt(["surge", "disp.x", "disp_x", "dx"])
    sway_col = find_col_opt(["sway", "disp.y", "disp_y", "dy"])
    heave_col = find_col_opt(["heave", "disp.z", "disp_z", "dz"])

    roll_col = find_col_opt(["roll", "euler.x", "euler_x", "rot.x"])
    pitch_col = find_col_opt(["pitch", "euler.y", "euler_y", "rot.y"])
    yaw_col = find_col_opt(["yaw", "euler.z", "euler_z", "rot.z"])

    # Optional quaternion columns in Floating_Actual.csv
    qx_col = find_col_opt(["q_x", "qx", "quat_x", "quaternion.x", "q1"])
    qy_col = find_col_opt(["q_y", "qy", "quat_y", "quaternion.y", "q2"])
    qz_col = find_col_opt(["q_z", "qz", "quat_z", "quaternion.z", "q3"])
    qw_col = find_col_opt(["q_w", "qw", "quat_w", "quaternion.w", "q0"])
    has_quat_cols = all(c is not None for c in (qx_col, qy_col, qz_col, qw_col))

    face_x = find_col_opt(["face.x", "acc.x", "acc_x", "face_x", "ax"])
    face_y = find_col_opt(["face.y", "acc.y", "acc_y", "face_y", "ay"])
    face_z = find_col_opt(["face.z", "acc.z", "acc_z", "face_z", "az"])
    faceom_x = find_col_opt(["faceomega.x", "angacc.x", "angacc_x", "rotacc_x", "faceom_x"])
    faceom_y = find_col_opt(["faceomega.y", "angacc.y", "angacc_y", "rotacc_y", "faceom_y"])
    faceom_z = find_col_opt(["faceomega.z", "angacc.z", "angacc_z", "rotacc_z", "faceom_z"])

    fluidf_x = find_col_opt(["fluidforcelin.x", "fluidforce.x", "fluidf.x", "force.x", "fx"])
    fluidf_y = find_col_opt(["fluidforcelin.y", "fluidforce.y", "fluidf.y", "force.y", "fy"])
    fluidf_z = find_col_opt(["fluidforcelin.z", "fluidforce.z", "fluidf.z", "force.z", "fz"])
    fluidt_x = find_col_opt(["fluidforceang.x", "fluidtorque.x", "fluidt.x", "torque.x", "tx", "mx"])
    fluidt_y = find_col_opt(["fluidforceang.y", "fluidtorque.y", "fluidt.y", "torque.y", "ty", "my"])
    fluidt_z = find_col_opt(["fluidforceang.z", "fluidtorque.z", "fluidt.z", "torque.z", "tz", "mz"])

    times = []
    positions = []
    lin_vels = []
    ang_vels = []
    euler_deg = []
    quaternions_xyzw = []
    displacements = []
    lin_accs = []
    ang_accs = []
    fluid_forces = []
    fluid_torques = []

    for row in reader:
        t = float(row[time_col])
        times.append(t)
        px, py, pz = float(row[center_x]), float(row[center_y]), float(row[center_z])
        positions.append([px, py, pz])

        vx = float(row[fvel_x]) if fvel_x else 0.0
        vy = float(row[fvel_y]) if fvel_y else 0.0
        vz = float(row[fvel_z]) if fvel_z else 0.0
        lin_vels.append([vx, vy, vz])

        wx = float(row[fomega_x]) if fomega_x else 0.0
        wy = float(row[fomega_y]) if fomega_y else 0.0
        wz = float(row[fomega_z]) if fomega_z else 0.0
        ang_vels.append([wx, wy, wz])

        r = float(row[roll_col]) if roll_col else 0.0
        p = float(row[pitch_col]) if pitch_col else 0.0
        y = float(row[yaw_col]) if yaw_col else 0.0
        euler_deg.append([r, p, y])

        if has_quat_cols:
            qx = float(row[qx_col])  # type: ignore[arg-type]
            qy = float(row[qy_col])  # type: ignore[arg-type]
            qz = float(row[qz_col])  # type: ignore[arg-type]
            qw = float(row[qw_col])  # type: ignore[arg-type]
            q_norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
            if q_norm > 0:
                qx, qy, qz, qw = qx / q_norm, qy / q_norm, qz / q_norm, qw / q_norm
            quaternions_xyzw.append([qx, qy, qz, qw])
        else:
            quaternions_xyzw.append(quaternion_from_euler_deg(r, p, y))

        dx = float(row[surge_col]) if surge_col else (px - positions[0][0])
        dy = float(row[sway_col]) if sway_col else (py - positions[0][1])
        dz = float(row[heave_col]) if heave_col else (pz - positions[0][2])
        displacements.append([dx, dy, dz])

        ax = float(row[face_x]) if face_x else 0.0
        ay = float(row[face_y]) if face_y else 0.0
        az = float(row[face_z]) if face_z else 0.0
        lin_accs.append([ax, ay, az])

        a_wx = float(row[faceom_x]) if faceom_x else 0.0
        a_wy = float(row[faceom_y]) if faceom_y else 0.0
        a_wz = float(row[faceom_z]) if faceom_z else 0.0
        ang_accs.append([a_wx, a_wy, a_wz])

        ffx = float(row[fluidf_x]) if fluidf_x else 0.0
        ffy = float(row[fluidf_y]) if fluidf_y else 0.0
        ffz = float(row[fluidf_z]) if fluidf_z else 0.0
        fluid_forces.append([ffx, ffy, ffz])

        ftx = float(row[fluidt_x]) if fluidt_x else 0.0
        fty = float(row[fluidt_y]) if fluidt_y else 0.0
        ftz = float(row[fluidt_z]) if fluidt_z else 0.0
        fluid_torques.append([ftx, fty, ftz])

    euler_rad = np.radians(np.asarray(euler_deg, dtype=np.float64))

    return {
        "time": np.asarray(times, dtype=np.float64),
        "position": np.asarray(positions, dtype=np.float64),
        "linear_velocity": np.asarray(lin_vels, dtype=np.float64),
        "angular_velocity": np.asarray(ang_vels, dtype=np.float64),
        "orientation_euler_deg": np.asarray(euler_deg, dtype=np.float64),
        "orientation_euler_rad": euler_rad,
        "orientation_quaternion": np.asarray(quaternions_xyzw, dtype=np.float64),
        "body_quaternion_xyzw": np.asarray(quaternions_xyzw, dtype=np.float64),
        "surge_sway_heave_m": np.asarray(displacements, dtype=np.float64),
        "linear_acceleration": np.asarray(lin_accs, dtype=np.float64),
        "angular_acceleration": np.asarray(ang_accs, dtype=np.float64),
        "fluid_force": np.asarray(fluid_forces, dtype=np.float64),
        "fluid_torque": np.asarray(fluid_torques, dtype=np.float64),
    }


def _decode_bi4_frame(frame_path: Path, temp_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Decode a single BI4 frame using bi4_dump."""
    import xml.etree.ElementTree as ET

    out_prefix = temp_dir / "dump"
    if out_prefix.exists():
        shutil.rmtree(out_prefix)

    res = subprocess.run([str(DECODER), str(frame_path), str(out_prefix)], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"bi4_dump failed on {frame_path}: {res.stderr}")

    meta_xml = out_prefix.with_suffix(".xml")
    root = ET.parse(meta_xml).getroot()
    parent = root.find("item")
    node = parent.find("item")
    info = {item.get("name"): item.get("v") for item in node if item.tag != "item"}
    time_s = float(info.get("TimeStep", "nan"))

    folder = out_prefix / node.get("name")
    ids = np.fromfile(folder / "Idp.bin", np.uint32)
    pos_file = folder / "Posd.bin" if (folder / "Posd.bin").is_file() else folder / "Pos.bin"
    positions = np.fromfile(pos_file, np.float64 if pos_file.name == "Posd.bin" else np.float32).reshape(-1, 3)
    velocities = np.fromfile(folder / "Vel.bin", np.float32).reshape(-1, 3)
    densities = np.fromfile(folder / "Rhop.bin", np.float32)

    order = np.argsort(ids)
    return ids[order], positions[order], velocities[order], densities[order], time_s


def convert_f6_case(
    *,
    case_id: str,
    data_dir: Path,
    generated_xml: Path,
    output_h5: Path,
    report_path: Path,
    motion_csv: Path | None = None,
    owner_metadata: Path | None = None,
    solver_log: Path | None = None,
    solver_receipt: Path | None = None,
    gencase_receipt: Path | None = None,
) -> dict[str, Any]:
    """Convert BI4 files and rigid motion logs into DS-DATA-02 trajectory.h5."""
    start_time = time.monotonic()
    data_dir = Path(data_dir).resolve()
    generated_xml = Path(generated_xml).resolve()
    output_h5 = Path(output_h5).resolve()
    report_path = Path(report_path).resolve()

    output_h5.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Parse GenCase XML
    xml_data = parse_gencase_xml(generated_xml)
    total_particles = xml_data["np"]
    groups = xml_data["groups"]

    # 2. Find and check BI4 frame paths
    frame_files = sorted(data_dir.glob("Part_*.bi4"))
    if len(frame_files) < 2:
        raise ValueError(f"Fewer than 2 BI4 frames found in {data_dir}")
    nframes = len(frame_files)

    # 3. Read or generate Rigid Body Motion Log
    if motion_csv is None or not motion_csv.is_file():
        motion_csv = ensure_floating_motion_csv(data_dir)
    rigid_data = parse_floating_motion_csv(motion_csv)

    # 4. Identity axis setup
    particle_ids = np.arange(total_particles, dtype=np.uint32)
    particle_zone = np.zeros(total_particles, dtype=np.int16)
    particle_type = np.zeros((nframes, total_particles), dtype=np.int8)
    particle_mk = np.zeros((nframes, total_particles), dtype=np.int16)

    # Build per-particle mass lookup based on GenCase role
    mass_template = np.full(total_particles, xml_data["massfluid"], dtype=np.float32)
    for g in groups:
        begin, count = g["begin"], g["count"]
        particle_type[:, begin : begin + count] = g["type"]
        particle_mk[:, begin : begin + count] = g["mk"]
        if g["role"] != "fluid":
            mass_template[begin : begin + count] = xml_data["massbound"]

    # 5. Materialize HDF5
    partial_h5 = output_h5.with_suffix(output_h5.suffix + ".partial")
    if partial_h5.exists():
        partial_h5.unlink()

    chunk_size = min(total_particles, 65536)
    with tempfile.TemporaryDirectory(prefix="f6-convert-") as temp_dir:
        temp_path = Path(temp_dir)
        with h5py.File(partial_h5, "w") as h5:
            # Root attributes
            h5.attrs["schema"] = "ds-data-02.hdf5-schema.v1"
            h5.attrs["family_id"] = "F6"
            h5.attrs["case_id"] = case_id
            h5.attrs["time_units"] = "s"
            h5.attrs["position_units"] = "m"
            h5.attrs["velocity_units"] = "m/s"
            h5.attrs["density_units"] = "kg/m^3"
            h5.attrs["mass_units"] = "kg"
            h5.attrs["pressure_units"] = "Pa"
            coord_frame = "world_tank_and_tank_attached_observations" if "wave" in case_id.lower() else "tank_attached_inertial"
            h5.attrs["coordinate_frame"] = coord_frame
            h5.attrs["generated_xml_sha256"] = sha256_file(generated_xml)
            h5.attrs["generated_xml"] = str(generated_xml)
            if xml_data["massbody_kg"] is not None:
                h5.attrs["floating_massbody_kg"] = float(xml_data["massbody_kg"])
            if xml_data["masspart_kg"] is not None:
                h5.attrs["floating_masspart_kg"] = float(xml_data["masspart_kg"])
            if xml_data["floating_inertia_kg_m2"] is not None:
                h5.attrs["floating_inertia_kg_m2"] = json.dumps(xml_data["floating_inertia_kg_m2"], separators=(",", ":"))
            h5.attrs["orientation_semantics"] = "FloatingInfo roll/pitch/yaw Euler deg and intrinsic XYZ unit quaternion [x,y,z,w]"
            h5.attrs["particle_identity"] = "native Idp"
            h5.attrs["identity_key"] = "(Zone,Idp)"
            h5.attrs["geometry"] = "F6_BOX_TANK_FREE_BODY" if "simple" in case_id.lower() else "F6_BOX_TANK_WAVE_PADDLE"
            h5.attrs["control"] = "F6_CTRL_INITIAL_RELEASE" if "simple" in case_id.lower() else "F6_CTRL_REGULAR_PISTON_WAVE"
            h5.attrs["boundary_mode"] = "closed_system"
            h5.attrs["closed_system"] = True
            h5.attrs["lifecycle_mode"] = "fixed_cohort"
            h5.attrs["rigid_body_state"] = "/rigid_body"
            h5.attrs["solver_dimension"] = 3

            # 1D fixed particle datasets
            h5.create_dataset("particle_id", data=particle_ids, dtype="u4")
            h5.create_dataset("particle_zone", data=particle_zone, dtype="i2")
            h5.create_dataset("initial_type", data=particle_type[0], dtype="i1")
            h5.create_dataset("initial_mk", data=particle_mk[0], dtype="i2")
            h5.create_dataset("initial_mass", data=mass_template, dtype="f4")

            # Time series datasets
            h5.create_dataset("time", shape=(nframes,), dtype="f8")
            h5.create_dataset("valid", shape=(nframes, total_particles), dtype="bool", chunks=(1, chunk_size), compression="lzf", fillvalue=False)
            h5.create_dataset("type", data=particle_type, dtype="i1", chunks=(1, chunk_size), compression="lzf")
            h5.create_dataset("mk", data=particle_mk, dtype="i2", chunks=(1, chunk_size), compression="lzf")
            h5.create_dataset("position", shape=(nframes, total_particles, 3), dtype="f4", chunks=(1, chunk_size, 3), compression="lzf", fillvalue=np.nan)
            h5.create_dataset("velocity", shape=(nframes, total_particles, 3), dtype="f4", chunks=(1, chunk_size, 3), compression="lzf", fillvalue=np.nan)
            h5.create_dataset("density", shape=(nframes, total_particles), dtype="f4", chunks=(1, chunk_size), compression="lzf", fillvalue=np.nan)
            h5.create_dataset("mass", shape=(nframes, total_particles), dtype="f4", chunks=(1, chunk_size), compression="lzf", fillvalue=np.nan)
            h5.create_dataset("pressure", shape=(nframes, total_particles), dtype="f4", chunks=(1, chunk_size), compression="lzf", fillvalue=np.nan)

            gamma = xml_data["gamma"]
            rhop0 = xml_data["rhop0"]
            b_const = xml_data["b"]

            # Loop over BI4 frames
            for frame_idx, frame_path in enumerate(frame_files):
                ids, pos, vel, rho, time_s = _decode_bi4_frame(frame_path, temp_path)
                # Native solver boundary-out events can remove particles from later
                # frames.  Keep a fixed first-frame identity axis and mark those
                # particles invalid rather than silently changing the cohort.
                slots = np.searchsorted(particle_ids, ids)
                if np.any(slots >= total_particles) or not np.array_equal(particle_ids[slots], ids):
                    raise ValueError(f"Unexpected particle identity at frame {frame_path.name}")
                if len(np.unique(slots)) != len(slots):
                    raise ValueError(f"Duplicate particle identity at frame {frame_path.name}")

                h5["time"][frame_idx] = time_s
                h5["valid"][frame_idx, slots] = True
                h5["position"][frame_idx, slots, :] = pos.astype(np.float32)
                h5["velocity"][frame_idx, slots, :] = vel.astype(np.float32)
                h5["density"][frame_idx, slots] = rho.astype(np.float32)
                h5["mass"][frame_idx, slots] = mass_template[slots]

                # Tait EOS for pressure
                pressure = b_const * ((rho.astype(np.float64) / rhop0) ** gamma - 1.0)
                h5["pressure"][frame_idx, slots] = pressure.astype(np.float32)

            # 6. Complete Rigid Body State Group
            rb_group = h5.create_group("rigid_body")
            rb_group.attrs["schema"] = "ds-data-02.f6.rigid-body-state.v1"
            rb_group.attrs["body_name"] = "floating_box"
            rb_group.attrs["mass_kg"] = float(xml_data["massbody_kg"]) if xml_data["massbody_kg"] is not None else float("nan")
            rb_group.attrs["quaternion_convention"] = "xyzw"
            rb_group.attrs["orientation_convention"] = "FloatingInfo roll/pitch/yaw intrinsic XYZ, quaternion xyzw"
            if xml_data["floating_inertia_kg_m2"] is not None:
                rb_group.attrs["inertia_tensor_kg_m2"] = json.dumps(xml_data["floating_inertia_kg_m2"])

            # Subsample or align rigid motion log to BI4 frames
            motion_times = rigid_data["time"]
            h5_times = h5["time"][:]

            # Interpolate or exact-match rigid state
            for key in (
                "position",
                "linear_velocity",
                "angular_velocity",
                "orientation_quaternion",
                "body_quaternion_xyzw",
                "orientation_euler_deg",
                "orientation_euler_rad",
                "surge_sway_heave_m",
                "linear_acceleration",
                "angular_acceleration",
                "fluid_force",
                "fluid_torque",
            ):
                arr = rigid_data[key]
                if len(arr) == nframes and np.allclose(motion_times[:nframes], h5_times, atol=1e-3):
                    aligned = arr[:nframes]
                else:
                    # Interpolate to exact HDF5 time points
                    aligned = np.zeros((nframes, arr.shape[1]), dtype=np.float64)
                    for dim in range(arr.shape[1]):
                        aligned[:, dim] = np.interp(h5_times, motion_times, arr[:, dim])
                    if "quaternion" in key:
                        norms = np.linalg.norm(aligned, axis=1, keepdims=True)
                        norms[norms == 0] = 1.0
                        aligned = aligned / norms
                rb_group.create_dataset(key, data=aligned, dtype="f8")

            rb_group.create_dataset("contact_event_flag", data=np.zeros(nframes, dtype=bool))

            # Mirror into legacy rigid_state group for compatibility
            rs_group = h5.create_group("rigid_state")
            for key in rb_group.keys():
                rs_group[key] = h5py.SoftLink(f"/rigid_body/{key}")

            h5.attrs["conversion_complete"] = True
            h5.attrs["conversion_complete_frames"] = int(nframes)

    partial_h5.replace(output_h5)
    elapsed = time.monotonic() - start_time

    report = {
        "schema": "ds02.f6.conversion-report.v1",
        "case_id": case_id,
        "family_id": "F6",
        "status": "completed",
        "output_h5": str(output_h5),
        "output_sha256": sha256_file(output_h5),
        "file_bytes": output_h5.stat().st_size,
        "frames": nframes,
        "particles": total_particles,
        "elapsed_seconds": elapsed,
        "data_dir": str(data_dir),
        "generated_xml": str(generated_xml),
        "motion_csv": str(motion_csv),
        "created_at_utc": now_str(),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def emit_f6_stage8_conversion_request(
    case_id: str,
    mech: str,
    last_frame: int,
    gpu_idx: int,
    family_dir: Path = FAMILY_DIR,
) -> Path:
    """Emit campaign runner request for F6 Stage 8 conversion."""
    family_dir = Path(family_dir).resolve()
    owner_meta = ensure_owner_metadata(case_id)

    case_data_dir = DATA_ROOT / case_id
    qual_dirs = sorted(case_data_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_receipt = None
    solver_dir = None
    for qd in reversed(qual_dirs):
        rec = qd / "execution-receipt.json"
        if rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0:
                    solver_receipt = rec
                    solver_dir = qd / "solver"
                    break
            except Exception:
                pass

    gencase_dir = case_data_dir / f"{case_id}_GENCASE_01"
    gencase_receipt = gencase_dir / "execution-receipt.json"
    generated_xml = gencase_dir / f"{case_id}.xml"
    gencase_bi4 = gencase_dir / f"{case_id}.bi4"

    # Solver outputs can be pending if queued
    solver_log = (solver_dir / "Run.out") if solver_dir else gencase_dir / "Run.out"
    part_0000 = (solver_dir / "data/Part_0000.bi4") if solver_dir else gencase_dir / "Part_0000.bi4"
    part_last = (solver_dir / f"data/Part_{last_frame:04d}.bi4") if solver_dir else gencase_dir / f"Part_{last_frame:04d}.bi4"

    attempt_id = "full-typed-native-conversion-001"
    storage_est = 6 * 1024 * 1024 * 1024  # ~6 GiB
    wall_sec = 1800

    convert_py = REPO / "scripts/ds_data02_f6_stage8_convert.py"
    command = [
        str(REPO / ".venv/bin/python"),
        str(convert_py),
        "--direct-run",
        "--case-id", case_id,
        "--data-dir", str(solver_dir / "data") if solver_dir else "{attempt_root}/data",
        "--generated-xml", str(generated_xml),
        "--output", "{attempt_root}/trajectory.h5",
        "--report", "{attempt_root}/conversion-report.json",
        "--owner-metadata", str(owner_meta),
    ]

    input_files = [
        str(convert_py.resolve()),
        str(owner_meta.resolve()),
        str(gencase_receipt.resolve()) if gencase_receipt.is_file() else str(generated_xml.resolve()),
        str(generated_xml.resolve()),
        str(gencase_bi4.resolve()),
        str(DECODER.resolve()),
        str(FLOATINGINFO.resolve()),
    ]
    if solver_receipt and solver_receipt.is_file():
        input_files.append(str(solver_receipt.resolve()))
    if solver_log and solver_log.is_file():
        input_files.append(str(solver_log.resolve()))

    req = {
        "schema": "ds02.request.v1",
        "family_id": "F6",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 4,
        "max_wall_seconds": wall_sec,
        "estimated_storage_bytes": storage_est,
        "worktree_root": str(REPO.parent),
        "cwd": str(REPO),
        "command": command,
        "input_files": input_files,
        "purpose": "Stage 8 production typed trajectory conversion with 6-DOF rigid body state",
    }

    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    req_file = REQUESTS_DIR / f"{case_id}-conversion.json"
    req_file.write_text(json.dumps(req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    prod_conv_dir = PROD_DIR / "conversion_requests"
    prod_conv_dir.mkdir(parents=True, exist_ok=True)
    (prod_conv_dir / f"{case_id}-conversion.json").write_text(json.dumps(req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def convert_stage8_case(case_id: str, *, overwrite: bool = False) -> dict[str, Any]:
    """Locate completed solver data and convert F6 Stage 8 case directly."""
    case_data_dir = DATA_ROOT / case_id
    if not case_data_dir.is_dir():
        raise FileNotFoundError(f"Case directory not found: {case_data_dir}")

    qual_dirs = sorted(case_data_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_dir = None
    for qd in reversed(qual_dirs):
        rec = qd / "execution-receipt.json"
        if rec.is_file():
            try:
                data = json.loads(rec.read_text(encoding="utf-8"))
                if data.get("status") == "completed" and data.get("returncode") == 0:
                    solver_dir = qd / "solver"
                    break
            except Exception:
                pass
        if not solver_dir and (qd / "solver/Run.out").is_file():
            solver_dir = qd / "solver"
            break

    if not solver_dir:
        raise FileNotFoundError(f"Missing completed solver run for {case_id}")

    data_dir = solver_dir / "data"
    gencase_dir = case_data_dir / f"{case_id}_GENCASE_01"
    generated_xml = gencase_dir / f"{case_id}.xml"

    attempt_dir = case_data_dir / "full-typed-native-conversion-001"
    output_h5 = attempt_dir / "trajectory.h5"
    report_path = attempt_dir / "conversion-report.json"

    if output_h5.exists() and not overwrite:
        if report_path.is_file():
            try:
                return json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    attempt_dir.mkdir(parents=True, exist_ok=True)
    owner_meta = ensure_owner_metadata(case_id)

    return convert_f6_case(
        case_id=case_id,
        data_dir=data_dir,
        generated_xml=generated_xml,
        output_h5=output_h5,
        report_path=report_path,
        owner_metadata=owner_meta,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--convert-all", action="store_true", help="Convert all 8 Stage 8 production cases")
    parser.add_argument("--convert-cases", nargs="*", help="Specific case IDs to convert directly")
    parser.add_argument("--emit-requests", action="store_true", help="Emit conversion requests for all Stage 8 cases")
    parser.add_argument("--direct-run", action="store_true", help="Run conversion directly on specified inputs")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing trajectory.h5")
    parser.add_argument("--case-id", type=str, help="Case ID to convert")
    parser.add_argument("--data-dir", type=Path, help="Directory containing Part_*.bi4")
    parser.add_argument("--generated-xml", type=Path, help="GenCase XML file")
    parser.add_argument("--output", type=Path, help="Path for output trajectory.h5")
    parser.add_argument("--report", type=Path, help="Path for conversion report JSON")
    parser.add_argument("--motion-csv", type=Path, help="FloatingInfo motion CSV")
    parser.add_argument("--owner-metadata", type=Path, help="Owner metadata JSON")
    args = parser.parse_args()

    if args.direct_run:
        if not args.case_id or not args.data_dir or not args.generated_xml or not args.output:
            parser.error("--direct-run requires --case-id, --data-dir, --generated-xml, and --output")
        report_path = args.report or args.output.parent / "conversion-report.json"
        rep = convert_f6_case(
            case_id=args.case_id,
            data_dir=args.data_dir,
            generated_xml=args.generated_xml,
            output_h5=args.output,
            report_path=report_path,
            motion_csv=args.motion_csv,
            owner_metadata=args.owner_metadata,
        )
        print(f"[{now_str()}] Conversion complete: {rep['output_h5']} ({rep['frames']} frames, {rep['particles']} particles)")
        return 0

    if args.convert_all or args.convert_cases is not None:
        targets = args.convert_cases if (args.convert_cases and len(args.convert_cases) > 0) else [c[0] for c in STAGE8_CASES]
        print(f"[{now_str()}] Converting {len(targets)} Stage 8 cases directly...")
        reports = []
        for cid in targets:
            rep = convert_stage8_case(cid, overwrite=args.overwrite)
            reports.append(rep)
            print(f"[{now_str()}] {cid}: converted {rep['frames']} frames ({rep['particles']} particles) in {rep['elapsed_seconds']:.1f}s")
        summary_path = FAMILY_DIR / "stage8_conversion_summary.json"
        summary_path.write_text(json.dumps(reports, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[{now_str()}] All conversions complete. Summary written to {summary_path}")
        return 0

    if args.emit_requests or not any(vars(args).values()):
        emitted = []
        for cid, mech, last_frame, gpu in STAGE8_CASES:
            ensure_owner_metadata(cid)
            p = emit_f6_stage8_conversion_request(cid, mech, last_frame, gpu)
            emitted.append(p)
            print(f"[{now_str()}] Emitted conversion request: {p.name}")
        print(f"[{now_str()}] Successfully emitted {len(emitted)} Stage 8 conversion requests.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
