#!/usr/bin/env python3
"""Audit the consumed F2 fine/coarse native geometry and moving-cup state.

This audit is deliberately read-only.  It binds the completed native solver
outputs, the generated XML, the cell-centre source definition, and the
full-state HDF5 conversion without changing any of them.  It answers the
scientific question that must precede a new numerical-domain recipe:

* Is the initial fluid actually inside the finite moving cup?
* Do the generated boundary particles cover every declared finite face at
  each ``dp``?
* Does the saved moving-node pose agree with direct native BI4 frames?
* Are all 123/111 fine native exclusions at a computational face, and what
  velocity was recorded by the native ``PartVTKOut`` export?

The report does not classify Motive 1 as physical spill and never grants Q-I,
Q-N, or production.  It writes only a new report under the data root.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import h5py
import numpy as np


SCHEMA = "ds-data-02.f2.geometry-pose-audit.v1"
DEFAULT_DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DEFAULT_LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
DECODER_RELATIVE = Path("campaigns/l1-resume/artifacts/bi4_dump")
DOMAIN_LOW = np.array([-1.40, -1.20, -0.50], dtype=float)
DOMAIN_HIGH = np.array([3.00, 1.20, 2.20], dtype=float)
FLUID_LOW = np.array([0.0525, -0.12, 0.70], dtype=float)
FLUID_SIZE = np.array([0.32, 0.24, 0.32], dtype=float)
RHO0 = 1000.0
BODY_BOXES = {
    "cup": (np.array([0.0, -0.15, 0.65]), np.array([0.425, 0.30, 0.45]), 17, 1,
            ("bottom", "left", "right", "front", "back")),
    "receiver": (np.array([0.45, -0.30, 0.0]), np.array([1.10, 0.60, 0.45]), 18, 0,
                  ("bottom", "left", "right", "front", "back")),
    "tray": (np.array([-1.20, -1.0, -0.20]), np.array([4.0, 2.0, 0.15]), 19, 0,
             ("bottom", "left", "right", "front", "back")),
}
FACE_AXIS = {
    "bottom": (2, "low"), "top": (2, "high"),
    "left": (0, "low"), "right": (0, "high"),
    "front": (1, "low"), "back": (1, "high"),
}


def body_boxes(background: str) -> dict:
    """Return the declared finite boxes for one physical background.

    OFFSET moves only the receiver's transverse placement.  The distinction
    is part of the physical mother and must never be inferred from a grid
    origin or from a post-solver label.
    """
    boxes = {
        name: (low.copy(), size.copy(), mk, typ, tuple(faces))
        for name, (low, size, mk, typ, faces) in BODY_BOXES.items()
    }
    if background == "OFFSET":
        low, size, mk, typ, faces = boxes["receiver"]
        boxes["receiver"] = (np.array([0.45, -0.16, 0.0]), size, mk, typ, faces)
    return boxes
CASE_RESOLUTION = {"COARSE": 0.04, "MEDIUM": 0.02, "FINE": 0.01}


@dataclass(frozen=True)
class Case:
    background: str
    resolution: str

    @property
    def case_id(self) -> str:
        return f"F2H10V2_{self.background}_V1_{self.resolution}"

    @property
    def h5_case(self) -> str:
        return self.case_id


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    return path


def _find_one(root: Path, pattern: str, label: str) -> Path:
    found = sorted(root.glob(pattern))
    if len(found) != 1:
        raise ValueError(f"expected one {label} below {root}, found {found}")
    return require(found[0], label)


def _find_latest(root: Path, pattern: str, label: str) -> Path:
    found = sorted(root.glob(pattern))
    if not found:
        raise ValueError(f"expected at least one {label} below {root}, found none")
    return require(found[-1], label)


def _find_dir(root: Path, pattern: str, label: str) -> Path:
    found = sorted(root.glob(pattern))
    if len(found) != 1 or not found[0].is_dir():
        raise ValueError(f"expected one {label} directory below {root}, found {found}")
    return found[0].resolve()


def case_paths(data_root: Path, case: Case) -> dict[str, Path]:
    base = data_root / "families" / "F2" / case.case_id
    solver = _find_dir(base, "qualification-*/solver_output", "solver output")
    # The completed conversion is deliberately located by its own output;
    # this prevents accidentally reading an old or partial H5.
    h5 = _find_one(base, "conversion-*/trajectory.h5", "full-state trajectory")
    xml = _find_one(base, "gencase-*/" + case.case_id + ".xml", "generated XML")
    bi4 = _find_one(base, "gencase-*/" + case.case_id + ".bi4", "generated BI4")
    motion = _find_one(base, "gencase-*/" + case.case_id + "_motion.dat", "copied motion")
    run_out = require(solver / "Run.out", "Run.out")
    partout = require(solver / "data" / "PartOut_000.obi4", "PartOut_000.obi4")
    # Native ledger's CSV is the PartVTKOut export from PartOut_000.obi4.
    # A coarse CENTER ledger has an immutable v1 and a corrected v2.  The
    # lexical latest version is selected while both remain hash-bound in the
    # old evidence tree.
    csv_path = _find_latest(base, "native-ledger-*/partvtkout/excluded_particles.csv", "PartVTKOut exclusion CSV")
    labels_h5 = _find_latest(base, "labels-*/f2-native-labels.h5", "native labels HDF5")
    source = (
        Path(__file__).resolve().parent / "handoff_20261002" / "gridphase_v2"
        / "definitions" / case.case_id / f"{case.case_id}_Def.xml"
    )
    source = require(source, "cell-centre source definition")
    return {
        "base": base,
        "solver": solver,
        "h5": h5,
        "xml": xml,
        "bi4": bi4,
        "motion": motion,
        "run_out": run_out,
        "partout": partout,
        "excluded_csv": csv_path,
        "labels_h5": labels_h5,
        "source": source,
    }


def _vec(node: ET.Element, name: str) -> np.ndarray:
    child = node.find(name)
    if child is None:
        raise ValueError(f"missing {name}")
    return np.array([float(child.get(axis)) for axis in "xyz"], dtype=float)


def parse_domain(xml: Path, run_out: Path) -> dict:
    root = ET.parse(xml).getroot()
    domain = root.find(".//simulationdomain")
    if domain is None:
        raise ValueError(f"{xml}: simulationdomain is missing")
    low = _vec(domain, "posmin")
    high = _vec(domain, "posmax")
    text = run_out.read_text(errors="replace")
    match = re.search(
        r"MapRealPos\(final\)=\(([^)]*)\)-\(([^)]*)\)", text, flags=re.IGNORECASE
    )
    if match is None:
        raise ValueError(f"{run_out}: MapRealPos(final) is missing")
    log_low = np.array([float(x.strip()) for x in match.group(1).split(",")], dtype=float)
    log_high = np.array([float(x.strip()) for x in match.group(2).split(",")], dtype=float)
    if len(log_low) != 3 or len(log_high) != 3:
        raise ValueError(f"{run_out}: MapRealPos(final) is not 3D")
    return {
        "xml_low_m": low.tolist(), "xml_high_m": high.tolist(),
        "run_out_low_m": log_low.tolist(), "run_out_high_m": log_high.tolist(),
        "xml_and_run_out_match": bool(np.array_equal(low, log_low) and np.array_equal(high, log_high)),
        "old_domain_expected": bool(np.array_equal(low, DOMAIN_LOW) and np.array_equal(high, DOMAIN_HIGH)),
        "run_out_sha256": sha256(run_out),
    }


def parse_source(source: Path) -> dict:
    root = ET.parse(source).getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError(f"{source}: geometry definition is missing")
    dp = float(definition.get("dp"))
    main = root.find(".//geometry/commands/mainlist")
    if main is None:
        raise ValueError(f"{source}: geometry mainlist is missing")
    active_bound = None
    active_fluid = None
    bound = {}
    fluid = []
    for node in main:
        if node.tag == "setmkbound":
            active_bound = int(node.get("mk"))
            active_fluid = None
        elif node.tag == "setmkfluid":
            active_fluid = int(node.get("mk"))
            active_bound = None
        elif node.tag == "drawbox":
            point, size = node.find("point"), node.find("size")
            fill = node.findtext("boxfill", "").strip()
            if point is None or size is None:
                raise ValueError(f"{source}: drawbox lacks point/size")
            box = {
                "point_m": [float(point.get(axis)) for axis in "xyz"],
                "size_m": [float(size.get(axis)) for axis in "xyz"],
                "fill": fill,
            }
            if active_bound is not None:
                bound[active_bound] = box
            elif active_fluid is not None:
                box["mkfluid"] = active_fluid
                fluid.append(box)
    if set(bound) != {0, 1, 2} or len(fluid) != 3:
        raise ValueError(f"{source}: unexpected source populations bound={bound.keys()} fluid={len(fluid)}")
    return {"path": str(source), "sha256": sha256(source), "dp_m": dp,
            "bound_boxes": bound, "fluid_boxes": fluid}


def _body_face_plane(low: np.ndarray, size: np.ndarray, face: str) -> float:
    axis, side = FACE_AXIS[face]
    return float(low[axis] if side == "low" else low[axis] + size[axis])


def wall_coverage(position: np.ndarray, initial_type: np.ndarray, initial_mk: np.ndarray,
                  dp: float, boxes: dict) -> dict:
    result = {}
    for name, (low, size, mk, typ, faces) in boxes.items():
        mask = (initial_mk == mk) & (initial_type == typ)
        body = position[mask]
        if len(body) == 0:
            raise ValueError(f"{name}: no typed native boundary particles for mk={mk}, type={typ}")
        face_rows = {}
        for face in faces:
            axis, _ = FACE_AXIS[face]
            plane = _body_face_plane(low, size, face)
            distance = np.abs(body[:, axis] - plane)
            # Cell-centre geometry places a layer within half a dp of every
            # declared face; this check accepts float serialization only.
            covered = distance <= max(1e-7, 0.51 * dp)
            face_rows[face] = {
                "plane_m": plane, "nearest_distance_m": float(distance.min()),
                "particles_within_half_dp": int(covered.sum()),
                "covered": bool(covered.any()),
            }
        result[name] = {
            "mk": mk, "type": typ, "particle_count": int(len(body)),
            "bbox_low_m": body.min(axis=0).tolist(), "bbox_high_m": body.max(axis=0).tolist(),
            "faces": face_rows, "all_declared_faces_covered": bool(all(row["covered"] for row in face_rows.values())),
        }
    return result


def occupancy(position: np.ndarray, initial_type: np.ndarray, initial_mk: np.ndarray, dp: float, boxes: dict) -> dict:
    fluid = position[initial_type == 3]
    cup_low, cup_size, _, _, _ = boxes["cup"]
    receiver_low, receiver_size, _, _, _ = boxes["receiver"]
    tray_low, tray_size, _, _, _ = boxes["tray"]
    cup_high = cup_low + cup_size
    receiver_high = receiver_low + receiver_size
    tray_high = tray_low + tray_size
    inside = lambda q, low, high: np.all((q > low) & (q < high), axis=1)
    fluid_inside_cup = inside(fluid, cup_low, cup_high)
    fluid_in_receiver = inside(fluid, receiver_low, receiver_high)
    fluid_in_tray = inside(fluid, tray_low, tray_high)
    expected_low = FLUID_LOW + 0.5 * dp
    expected_high = FLUID_LOW + FLUID_SIZE - 0.5 * dp
    return {
        "fluid_count": int(len(fluid)),
        "fluid_bbox_low_m": fluid.min(axis=0).tolist(),
        "fluid_bbox_high_m": fluid.max(axis=0).tolist(),
        "expected_cell_center_low_m": expected_low.tolist(),
        "expected_cell_center_high_m": expected_high.tolist(),
        "cell_center_bbox_exact_within_float_tolerance": bool(
            np.allclose(fluid.min(axis=0), expected_low, rtol=0, atol=2e-6)
            and np.allclose(fluid.max(axis=0), expected_high, rtol=0, atol=2e-6)
        ),
        "inside_cup_count": int(fluid_inside_cup.sum()),
        "inside_receiver_count": int(fluid_in_receiver.sum()),
        "inside_tray_count": int(fluid_in_tray.sum()),
        "all_fluid_inside_initial_cup": bool(fluid_inside_cup.all()),
        "no_initial_fluid_receiver_overlap": bool(~fluid_in_receiver.any()),
        "no_initial_fluid_tray_overlap": bool(~fluid_in_tray.any()),
        "cup_inner_clearance_min_m": float(np.min(np.concatenate([fluid - cup_low, cup_high - fluid]))),
        "initial_discrete_mass_kg": float(len(fluid) * RHO0 * dp**3),
        "declared_continuous_mass_kg": float(np.prod(FLUID_SIZE) * RHO0),
    }


def _native_frame(decoder: Path, bi4: Path, temporary: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    subprocess.run([str(decoder), str(bi4), str(temporary)], check=True, stdout=subprocess.DEVNULL)
    root = ET.parse(str(temporary) + ".xml").getroot()
    parent = root.find("item")
    node = parent.find("item")
    folder = temporary / node.get("name")
    ids = np.fromfile(folder / "Idp.bin", np.uint32)
    order = np.argsort(ids)
    pos_file = folder / "Posd.bin" if (folder / "Posd.bin").exists() else folder / "Pos.bin"
    pos = np.fromfile(pos_file, np.float64 if pos_file.name == "Posd.bin" else np.float32).reshape(-1, 3)[order]
    vel = np.fromfile(folder / "Vel.bin", np.float32).reshape(-1, 3)[order]
    return ids[order], pos, vel, {e.get("name"): e.get("v") for e in node if e.tag != "item"}


def native_pose_audit(paths: dict[str, Path], h5: h5py.File, decoder: Path, initial_type: np.ndarray,
                      particle_id: np.ndarray) -> dict:
    moving = initial_type == 1
    # Directly decode a sparse set of native BI4 frames.  This is an adapter
    # check over already-consumed bytes, not a new conversion product.
    indices = (0, 1, 66, 100, 200, 400)
    rows = []
    with tempfile.TemporaryDirectory(prefix="f2-geometry-pose-") as td:
        for frame in indices:
            bi4 = paths["solver"] / "data" / f"Part_{frame:04d}.bi4"
            if not bi4.exists():
                continue
            ids, pos, vel, info = _native_frame(decoder, bi4, Path(td) / f"frame_{frame:04d}")
            common = np.searchsorted(particle_id, ids)
            if np.any(common >= len(particle_id)) or not np.array_equal(particle_id[common], ids):
                raise ValueError(f"{paths['base']}: native frame {frame} identity axis differs")
            selected = moving[common]
            native_pos = pos[selected]
            native_vel = vel[selected]
            h5_pos = h5["position"][frame, common[selected]]
            h5_vel = h5["velocity"][frame, common[selected]]
            rows.append({
                "frame": frame, "time_s": float(info.get("TimeStep", "nan")),
                "moving_node_count_native": int(selected.sum()),
                "max_abs_position_error_m": float(np.max(np.abs(native_pos - h5_pos))),
                "max_abs_velocity_error_m_s": float(np.max(np.abs(native_vel - h5_vel))),
                "native_case_particles": int(len(ids)),
                "native_identity_unique": bool(len(np.unique(ids)) == len(ids)),
            })
    return {"frames": rows, "all_pose_frames_match_h5_at_2e-5": bool(
        rows and all(r["max_abs_position_error_m"] <= 2e-5 and r["max_abs_velocity_error_m_s"] <= 2e-5 for r in rows)
    )}


def opening_surface_audit(h5: h5py.File, initial_type: np.ndarray, boxes: dict) -> dict:
    """Compare the frozen x-mouth predicate with the actual open cup top.

    The consumed event labels use a local x plane at ``cup_width-0.05``.
    The source geometry declares the cup top open, so an independent crossing
    count is needed before treating a zero x-mouth count as zero departure.
    """
    fluid_indices = np.flatnonzero(initial_type == 3)
    times = np.asarray(h5["time"][:], dtype=np.float64)
    rigid = np.asarray(h5["rigid_body_state"][:])
    positions = h5["position"]
    valid = h5["valid"]
    cup_low, cup_size, _, _, _ = boxes["cup"]
    cup_high = cup_low + cup_size
    origin = np.asarray([0.0, -1.0, 0.65], dtype=np.float64)
    axis = np.asarray([0.0, 1.0, 0.0], dtype=np.float64)
    tolerance = 0.0125
    mouth_x = float(cup_low[0] + cup_size[0] - 0.05)
    first_top = np.full(len(fluid_indices), np.nan, dtype=np.float64)
    first_mouth = np.full(len(fluid_indices), np.nan, dtype=np.float64)
    previous_body = None
    previous_valid = None
    for frame, time_s in enumerate(times):
        points = np.asarray(positions[frame, fluid_indices, :], dtype=np.float64)
        frame_valid = np.asarray(valid[frame, fluid_indices], dtype=bool)
        angle = float(rigid[frame]["actual_angle_rad"])
        shifted = points - origin
        cosine, sine = float(np.cos(-angle)), float(np.sin(-angle))
        body = origin + cosine * shifted + sine * np.cross(axis, shifted) + (1.0 - cosine) * (shifted @ axis)[:, None] * axis
        if previous_body is not None and time_s >= 0.5:
            top_cross = (
                np.isnan(first_top) & previous_valid & frame_valid
                & (previous_body[:, 2] <= cup_high[2]) & (body[:, 2] > cup_high[2])
            )
            aperture = (
                (body[:, 1] >= cup_low[1] - tolerance) & (body[:, 1] <= cup_high[1] + tolerance)
                & (body[:, 2] >= cup_low[2] - tolerance) & (body[:, 2] <= cup_high[2] + tolerance)
            )
            mouth_cross = (
                np.isnan(first_mouth) & previous_valid & frame_valid & aperture
                & (previous_body[:, 0] <= mouth_x) & (body[:, 0] > mouth_x)
            )
            first_top[top_cross] = time_s
            first_mouth[mouth_cross] = time_s
        previous_body = body
        previous_valid = frame_valid
    return {
        "legacy_mouth_plane_m": mouth_x,
        "open_face": "cup_top (local body z high face)",
        "cup_top_first_crossing_count": int(np.isfinite(first_top).sum()),
        "cup_top_first_crossing_time_min_s": float(np.nanmin(first_top)) if np.isfinite(first_top).any() else None,
        "legacy_mouth_first_crossing_count": int(np.isfinite(first_mouth).sum()),
        "legacy_mouth_first_crossing_time_min_s": float(np.nanmin(first_mouth)) if np.isfinite(first_mouth).any() else None,
        "predicate_interpretation": "a zero legacy x-mouth crossing count does not establish zero cup departure when the declared cup_top is open",
    }


def legacy_label_event_count(labels_h5: Path) -> dict:
    with h5py.File(labels_h5, "r") as labels:
        events = np.asarray(labels["events"])
    counts = {str(code): int(np.sum(events["event_code"] == code)) for code in range(1, 7)}
    return {
        "labels_h5": str(labels_h5), "labels_h5_sha256": sha256(labels_h5),
        "event_count_by_code": counts,
        "legacy_cup_departure_count": counts["1"],
    }


def exclusion_velocity_audit(csv_path: Path) -> dict:
    records = []
    with csv_path.open(newline="") as stream:
        for raw in csv.DictReader(stream, skipinitialspace=True):
            row = {key.strip(): value.strip() for key, value in raw.items()}
            records.append({
                "x": float(row["Pos.x [m]"]), "y": float(row["Pos.y [m]"]), "z": float(row["Pos.z [m]"]),
                "part_out": int(row["PartOut"]), "motive": int(row["Motive"]), "idp": int(row["Idp"]),
                "vx": float(row["Vel.x [m/s]"]), "vy": float(row["Vel.y [m/s]"]), "vz": float(row["Vel.z [m/s]"]),
                "rho": float(row["Rhop [kg/m^3]"]),
            })
    counts = {"xmin": 0, "xmax": 0, "ymin": 0, "ymax": 0, "zmin": 0, "zmax": 0}
    per_face = {key: [] for key in counts}
    for row in records:
        for axis, low, high in (("x", -1.4, 3.0), ("y", -1.2, 1.2), ("z", -0.5, 2.2)):
            if abs(row[axis] - low) <= 5e-4:
                counts[axis + "min"] += 1; per_face[axis + "min"].append(row)
            if abs(row[axis] - high) <= 5e-4:
                counts[axis + "max"] += 1; per_face[axis + "max"].append(row)
    face_summary = {}
    for face, rows in per_face.items():
        if not rows:
            face_summary[face] = {"count": 0}
            continue
        vel = np.array([[row["vx"], row["vy"], row["vz"]] for row in rows])
        pos = np.array([[row["x"], row["y"], row["z"]] for row in rows])
        face_summary[face] = {
            "count": len(rows), "position_low_m": pos.min(0).tolist(), "position_high_m": pos.max(0).tolist(),
            "velocity_low_m_s": vel.min(0).tolist(), "velocity_high_m_s": vel.max(0).tolist(),
            "speed_max_m_s": float(np.linalg.norm(vel, axis=1).max()),
        }
    return {
        "source_partvtkout_csv": str(csv_path), "source_partvtkout_csv_sha256": sha256(csv_path),
        "rows": len(records), "motive_counts": {str(k): int(v) for k, v in sorted(__import__('collections').Counter(x["motive"] for x in records).items())},
        "all_positions_velocities_density_finite": bool(all(np.isfinite([x["x"], x["y"], x["z"], x["vx"], x["vy"], x["vz"], x["rho"]]).all() for x in records)),
        "face_tolerance_m": 5e-4, "face_counts": counts, "faces": face_summary,
        "classification": "all rows are native Motive 1 numerical_unknown; face proximity is evidence of domain interaction only; physical spill not inferred",
    }


def one_case(data_root: Path, lab_root: Path, case: Case) -> dict:
    paths = case_paths(data_root, case)
    source_info = parse_source(paths["source"])
    boxes = body_boxes(case.background)
    domain_info = parse_domain(paths["xml"], paths["run_out"])
    decoder = require(lab_root / DECODER_RELATIVE, "native BI4 decoder")
    with h5py.File(paths["h5"], "r") as h5:
        initial_type = h5["initial_type"][:]
        initial_mk = h5["initial_mk"][:]
        initial_pos = h5["position"][0]
        particle_id = h5["particle_id"][:]
        if not np.all(np.diff(particle_id) >= 0):
            raise ValueError(f"{case.case_id}: H5 particle identity axis is not sorted")
        occupancy_info = occupancy(initial_pos, initial_type, initial_mk, CASE_RESOLUTION[case.resolution], boxes)
        coverage_info = wall_coverage(initial_pos, initial_type, initial_mk, CASE_RESOLUTION[case.resolution], boxes)
        pose_info = native_pose_audit(paths, h5, decoder, initial_type, particle_id)
        opening_info = opening_surface_audit(h5, initial_type, boxes)
        opening_info["consumed_label_events"] = legacy_label_event_count(paths["labels_h5"])
        rigid = h5["rigid_body_state"][:]
        rigid_rows = []
        for i in (0, 1, 66, 100, 200, 400):
            row = rigid[i]
            rigid_rows.append({name: (int(row[name]) if np.issubdtype(rigid.dtype[name], np.integer) else float(row[name])) for name in rigid.dtype.names})
        rigid_residual = {
            "max_position_rms_m": float(np.max(rigid["position_rms_m"])),
            "max_position_max_m": float(np.max(rigid["position_max_m"])),
            "max_velocity_rms_m_s": float(np.max(rigid["velocity_rms_m_s"])),
            "max_velocity_max_m_s": float(np.max(rigid["velocity_max_m_s"])),
            "max_angle_residual_rad": float(np.max(np.abs(rigid["angle_residual_rad"]))),
            "max_omega_residual_rad_s": float(np.max(np.abs(rigid["omega_residual_rad_s"]))),
            "moving_node_count_constant": bool(np.all(rigid["moving_node_count"] == rigid["moving_node_count"][0])),
            "pose_valid_all_frames": bool(np.all(rigid["valid"])),
        }
        h5_attrs = {
            key: (value.tolist() if isinstance(value, np.ndarray)
                  else value.item() if isinstance(value, np.generic)
                  else value)
            for key, value in h5.attrs.items()
            if key in {"MassFluid", "control_sha256", "geometry_sha256", "physical_condition_sha256", "rigid_body_state_control_sha256", "solver_dimension"}
        }
        report = {
            "case_id": case.case_id, "background": case.background, "resolution": case.resolution,
            "dp_m": CASE_RESOLUTION[case.resolution], "source_bindings": {
                key: {"path": str(value), "sha256": sha256(value)} for key, value in paths.items() if key not in {"base", "solver"}
            },
            "source_definition": source_info, "simulation_domain": domain_info,
            "occupancy": occupancy_info, "wall_face_coverage": coverage_info,
            "rigid_body_pose": {"h5_attribute_bindings": h5_attrs, "sampled_rows": rigid_rows, "residuals": rigid_residual},
            "native_pose_crosscheck": pose_info,
            "cup_opening_semantic_audit": opening_info,
            "native_exclusion_velocity_audit": exclusion_velocity_audit(paths["excluded_csv"]),
            "qualification_claim": "none; geometry/pose/domain evidence only; Motive 1 remains numerical_unknown",
        }
    return report


def build_report(data_root: Path, lab_root: Path) -> dict:
    cases = [Case(background, resolution) for background in ("CENTER", "OFFSET") for resolution in ("COARSE", "MEDIUM", "FINE")]
    reports = [one_case(data_root, lab_root, case) for case in cases]
    return {
        "schema": SCHEMA, "generated_at_utc": stamp(), "data_root": str(data_root), "lab_root": str(lab_root),
        "cases": reports,
        "frozen_physical_binding": {
            "continuous_fluid_low_m": FLUID_LOW.tolist(), "continuous_fluid_size_m": FLUID_SIZE.tolist(),
            "continuous_fluid_volume_m3": float(np.prod(FLUID_SIZE)), "continuous_initial_mass_kg": float(np.prod(FLUID_SIZE) * RHO0),
            "motion_and_finite_geometry_unchanged": True,
        },
        "interpretation": {
            "initial_occupancy": "all DP views must retain all fluid in the moving cup at t=0 and have no receiver/tray overlap",
            "domain_repair_basis": "old fine Motive 1 rows are all within 0.0005 m of an outer computational face; this supports a candidate numerical-domain test but does not classify physical spill",
            "native_velocity_source": "PartVTKOut CSV exported from each consumed PartOut_000.obi4; decoder cross-checks sampled Part_*.bi4 moving-node pose against H5",
            "qualification_claim": "none",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--lab-root", type=Path, default=DEFAULT_LAB_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.data_root.resolve(), args.lab_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"report": str(args.output.resolve()), "schema": SCHEMA, "cases": len(report["cases"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
