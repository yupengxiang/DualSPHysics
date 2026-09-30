#!/usr/bin/env python3
"""Read-only native medium/fine F2 geometry and exclusion diagnostics.

The script is intended to run as a bounded CPU audit through
``ds_data02_runtime.py``.  It never starts DualSPHysics.  For each supplied
completed solver view it decodes the initial frame and the first three posed
frames with the official PartVTK binary, exports the native exclusion cohort
with PartVTKOut, and writes a provenance-bound report.  The report keeps
numerical exclusions separate from physical receiver/tray destinations.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping

import numpy as np


CSV_COLUMNS = (
    "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp",
    "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]",
    "Mass [kg]", "Press [Pa]", "Type", "Mk",
)
MOTION_RE = re.compile(r"^\s*([^;,#]+)\s*[;,]\s*([^;,#]+)")


class DiagnosticError(RuntimeError):
    """Raised when an immutable native source cannot be audited."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def require_file(path: Any, label: str) -> Path:
    candidate = Path(str(path)).expanduser().resolve()
    if not candidate.is_file():
        raise DiagnosticError(f"{label} is missing: {candidate}")
    return candidate


def finite_float(value: Any) -> float:
    result = float(str(value).strip().replace(" ", ""))
    if not math.isfinite(result):
        raise ValueError(value)
    return result


def parse_csv_rows(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Pos.x [m]")), None)
    if header_index is None:
        raise DiagnosticError(f"PartVTK CSV has no particle header: {path}")
    header = [item.strip() for item in lines[header_index].split(",") if item.strip()]
    if any(column not in header for column in CSV_COLUMNS):
        missing = [column for column in CSV_COLUMNS if column not in header]
        raise DiagnosticError(f"PartVTK CSV lacks required fields {missing}: {path}")
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 1:]:
        if not line.strip():
            continue
        values = [item.strip() for item in line.split(",")]
        if len(values) >= len(header):
            rows.append(dict(zip(header, values)))
    summary: dict[str, str] = {}
    if header_index >= 2:
        summary_header = [item.strip() for item in lines[0].split(",")]
        summary_values = [item.strip() for item in lines[1].split(",")]
        summary = dict(zip(summary_header, summary_values))
    return summary, rows


def row_position(row: Mapping[str, str]) -> np.ndarray:
    return np.asarray([finite_float(row[key]) for key in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")], dtype=np.float64)


def row_velocity(row: Mapping[str, str]) -> np.ndarray:
    return np.asarray([finite_float(row[key]) for key in ("Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]")], dtype=np.float64)


def decode_frame(*, binary: Path, data_dir: Path, frame_first: int, frame_last: int, output_dir: Path, prefix: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_prefix = output_dir / prefix
    command = [
        str(binary), "-dirdata", str(data_dir), f"-first:{frame_first}", f"-last:{frame_last}",
        "-threads:4", "-savecsv", str(csv_prefix), "-onlytype:+all",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = f"{binary.parent}:{environment.get('LD_LIBRARY_PATH', '')}"
    completed = subprocess.run(command, cwd=output_dir, env=environment, capture_output=True, text=True, check=False)
    log_path = output_dir / f"{prefix}.stdout.log"
    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise DiagnosticError(f"PartVTK failed ({completed.returncode}): {completed.stdout[-1200:]}{completed.stderr[-1200:]}")
    frame_paths = []
    for frame in range(frame_first, frame_last + 1):
        path = output_dir / f"{prefix}_{frame:04d}.csv"
        require_file(path, f"PartVTK frame {frame}")
        frame_paths.append(path)
    return {
        "command": command,
        "binary": {"path": str(binary), "sha256": sha256(binary)},
        "returncode": completed.returncode,
        "frames": [{"index": frame, "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size} for frame, path in zip(range(frame_first, frame_last + 1), frame_paths)],
        "log": {"path": str(log_path), "sha256": sha256(log_path)},
    }


def decode_selected_frames(*, binary: Path, data_dir: Path, frame_indices: Iterable[int], output_dir: Path, prefix: str) -> dict[str, Any]:
    """Decode selected native frames without treating a save index as a time step."""
    indices = sorted({int(index) for index in frame_indices})
    if not indices:
        raise DiagnosticError("at least one selected native frame is required")
    frames: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    for index in indices:
        result = decode_frame(
            binary=binary,
            data_dir=data_dir,
            frame_first=index,
            frame_last=index,
            output_dir=output_dir,
            prefix=f"{prefix}_{index:04d}",
        )
        frames.extend(result["frames"])
        logs.append(result["log"])
    return {
        "command_kind": "official_partvtk_selected_frames",
        "binary": {"path": str(binary), "sha256": sha256(binary)},
        "returncode": 0,
        "frames": frames,
        "logs": logs,
    }


def decode_exclusions(*, binary: Path, data_dir: Path, output_dir: Path, prefix: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{prefix}.csv"
    vtk_path = output_dir / f"{prefix}.vtk"
    stats_path = output_dir / f"{prefix}_stats.csv"
    command = [
        str(binary), "-dirdata", str(data_dir), "-first:0", "-last:0",
        "-savecsv", str(csv_path), "-savevtk", str(vtk_path),
        "-saveresume", str(stats_path), "-createdirs:1", "-csvsep:1",
    ]
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = f"{binary.parent}:{environment.get('LD_LIBRARY_PATH', '')}"
    completed = subprocess.run(command, cwd=output_dir, env=environment, capture_output=True, text=True, check=False)
    log_path = output_dir / f"{prefix}.stdout.log"
    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise DiagnosticError(f"PartVTKOut failed ({completed.returncode}): {completed.stdout[-1200:]}{completed.stderr[-1200:]}")
    require_file(csv_path, "PartVTKOut CSV")
    lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Pos.x [m]")), None)
    rows: list[dict[str, Any]] = []
    if header_index is not None:
        header = [item.strip() for item in lines[header_index].split(",") if item.strip()]
        for line in lines[header_index + 1:]:
            if not line.strip():
                continue
            values = [item.strip() for item in line.split(",")]
            if len(values) < len(header):
                continue
            raw = dict(zip(header, values))
            try:
                rows.append({
                    "idp": int(raw["Idp"]),
                    "part_out": int(raw["PartOut"]),
                    "motive": int(raw["Motive"]),
                    "position_m": [finite_float(raw[name]) for name in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")],
                    "velocity_m_s": [finite_float(raw[name]) for name in ("Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]")],
                    "density_kg_m3": finite_float(raw["Rhop [kg/m^3]"]),
                })
            except (KeyError, ValueError):
                continue
    outputs = []
    for path in (csv_path, vtk_path, stats_path, log_path):
        if path.is_file():
            outputs.append({"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size})
    return {"command": command, "binary": {"path": str(binary), "sha256": sha256(binary)}, "returncode": completed.returncode, "rows": rows, "outputs": outputs}


def read_runparts(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for raw in csv.DictReader(handle, delimiter=";"):
            try:
                row = {str(key): value for key, value in raw.items()}
                row["part"] = int(str(row["Part"]).replace(",", ""))
                row["time_s"] = finite_float(row["TimeStep [s]"])
                for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov"):
                    row[key] = int(round(finite_float(row[key])))
                rows.append(row)
            except (KeyError, ValueError):
                continue
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise DiagnosticError(f"RunPARTs.csv parts are not contiguous: {path}")
    return rows


def read_motion(path: Path) -> tuple[np.ndarray, np.ndarray]:
    times: list[float] = []
    angles: list[float] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = MOTION_RE.match(raw.strip())
        if not match:
            continue
        try:
            times.append(finite_float(match.group(1)))
            angles.append(math.radians(finite_float(match.group(2))))
        except ValueError:
            continue
    if len(times) < 2 or not np.all(np.diff(times) > 0):
        raise DiagnosticError(f"motion time axis is not strictly increasing: {path}")
    return np.asarray(times, dtype=np.float64), np.asarray(angles, dtype=np.float64)


def rotation_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    return np.asarray([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


def fit_rotation(points0: np.ndarray, points: np.ndarray, origin: np.ndarray, axis: np.ndarray) -> float:
    q = points0 - origin
    r = points - origin
    q_perp = q - (q @ axis)[:, None] * axis
    r_perp = r - (r @ axis)[:, None] * axis
    denominator = np.sum(q_perp * q_perp, axis=1)
    usable = denominator > 1e-16
    if not np.any(usable):
        raise DiagnosticError("moving cup has no points usable for pose fit")
    q_perp, r_perp, denominator = q_perp[usable], r_perp[usable], denominator[usable]
    cosine = np.sum(q_perp * r_perp, axis=1) / denominator
    sine = np.sum(axis * np.cross(q_perp, r_perp), axis=1) / denominator
    return float(math.atan2(float(np.sum(sine)), float(np.sum(cosine))))


def parse_boxes(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    mainlist = root.find(".//geometry/commands/mainlist")
    if mainlist is None:
        raise DiagnosticError(f"generated XML lacks geometry mainlist: {xml_path}")
    bound_mk: int | None = None
    fluid_mk: int | None = None
    bounds: dict[int, dict[str, Any]] = {}
    fluids: dict[int, list[dict[str, Any]]] = {}
    for node in mainlist:
        if node.tag == "setmkbound":
            bound_mk = int(node.attrib["mk"])
            fluid_mk = None
        elif node.tag == "setmkfluid":
            fluid_mk = int(node.attrib["mk"])
            bound_mk = None
        elif node.tag != "drawbox":
            continue
        point = node.find("./point")
        size = node.find("./size")
        if point is None or size is None:
            continue
        low = np.asarray([float(point.attrib[key]) for key in ("x", "y", "z")], dtype=np.float64)
        extent = np.asarray([float(size.attrib[key]) for key in ("x", "y", "z")], dtype=np.float64)
        fill = (node.findtext("./boxfill") or "").strip()
        record = {"low_m": low, "size_m": extent, "high_m": low + extent, "boxfill": fill}
        if bound_mk is not None:
            bounds[bound_mk] = {**record, "mk": bound_mk}
        if fluid_mk is not None:
            fluids.setdefault(fluid_mk, []).append({**record, "mk": fluid_mk})
    if not bounds or not fluids:
        raise DiagnosticError(f"generated XML has no bound/fluid boxes: {xml_path}")
    return {"bounds": bounds, "fluids": fluids}


def points_from_rows(rows: Iterable[Mapping[str, str]]) -> np.ndarray:
    return np.asarray([row_position(row) for row in rows], dtype=np.float64)


def group_points(rows: Iterable[Mapping[str, str]], *, types: set[int] | None = None) -> dict[tuple[int, int], np.ndarray]:
    groups: dict[tuple[int, int], list[np.ndarray]] = {}
    for row in rows:
        key = (int(row["Type"]), int(row["Mk"]))
        if types is not None and key[0] not in types:
            continue
        groups.setdefault(key, []).append(row_position(row))
    return {key: np.asarray(values, dtype=np.float64) for key, values in groups.items()}


def nearest_group(groups: Mapping[tuple[int, int], np.ndarray], expected_low: np.ndarray, expected_high: np.ndarray) -> tuple[int, int] | None:
    if not groups:
        return None
    expected_center = (expected_low + expected_high) / 2.0
    return min(groups, key=lambda key: float(np.linalg.norm(groups[key].mean(axis=0) - expected_center)))


def face_coverage(points: np.ndarray, low: np.ndarray, size: np.ndarray, dp: float, faces: tuple[str, ...]) -> dict[str, Any]:
    if len(points) == 0:
        return {face: {"count": 0, "span_fraction": 0.0, "normal": None} for face in faces}
    high = low + size
    tolerance = max(2.25 * float(dp), 1e-6)
    output: dict[str, Any] = {}
    axes = {"x": 0, "y": 1, "z": 2}
    for face in faces:
        side = face[-1]
        axis = axes[face[0]]
        target = low[axis] if side == "-" else high[axis]
        near = np.abs(points[:, axis] - target) <= tolerance
        selected = points[near]
        tangential = [index for index in range(3) if index != axis]
        spans = []
        for tangent in tangential:
            if len(selected):
                spans.append(max(0.0, min(1.0, (float(selected[:, tangent].max()) - float(selected[:, tangent].min())) / max(float(size[tangent]), 1e-12))))
            else:
                spans.append(0.0)
        output[face] = {
            "count": int(len(selected)),
            "span_fraction": float(min(spans) if spans else 0.0),
            "normal": [float(-1 if side == "-" else 1) if index == axis else 0.0 for index in range(3)],
            "coordinate_target_m": float(target),
            "tolerance_m": float(tolerance),
        }
    return output


def fixed_wall_evidence(rows: list[dict[str, str]], boxes: Mapping[int, Mapping[str, Any]], dp: float) -> dict[str, Any]:
    fixed_groups = group_points(rows, types={0})
    moving_groups = group_points(rows, types={1})
    evidence: dict[str, Any] = {}
    for mk, name, faces, groups in ((0, "moving_cup_frame0", ("x-", "x+", "y-", "y+", "z-", "z+"), moving_groups),
                                    (1, "receiver", ("x-", "x+", "y-", "y+", "z-"), fixed_groups),
                                    (2, "tray", ("z-",), fixed_groups)):
        box = boxes.get(mk)
        if not isinstance(box, Mapping):
            evidence[name] = {"status": "missing_declared_box", "mk": mk}
            continue
        key = nearest_group(groups, np.asarray(box["low_m"], dtype=np.float64), np.asarray(box["high_m"], dtype=np.float64))
        if key is None:
            evidence[name] = {"status": "missing_native_group", "declared_mk": mk}
            continue
        points = groups[key]
        coverage = face_coverage(points, np.asarray(box["low_m"]), np.asarray(box["size_m"]), dp, faces)
        evidence[name] = {
            "status": "measured",
            "declared_mk": mk,
            "native_type_mk": [int(key[0]), int(key[1])],
            "point_count": int(len(points)),
            "bounds_low_m": points.min(axis=0).tolist(),
            "bounds_high_m": points.max(axis=0).tolist(),
            "declared_low_m": np.asarray(box["low_m"]).tolist(),
            "declared_high_m": np.asarray(box["high_m"]).tolist(),
            "face_coverage": coverage,
            "finite_wall_faces": list(faces),
            "closure_is_face_coverage_not_particle_count": True,
        }
    return evidence


def cup_pose_evidence(frame_rows: list[dict[str, str]], initial_rows: list[dict[str, str]], *, time_s: float, control_angle_rad: float, control_sign: float, origin: np.ndarray, axis: np.ndarray, box: Mapping[str, Any], dp: float) -> dict[str, Any]:
    initial = [row for row in initial_rows if int(row["Type"]) == 1]
    current = [row for row in frame_rows if int(row["Type"]) == 1]
    initial_by_key = {(int(row["Zone"]), int(row["Idp"])): row_position(row) for row in initial}
    current_by_key = {(int(row["Zone"]), int(row["Idp"])): row_position(row) for row in current}
    shared = sorted(set(initial_by_key) & set(current_by_key))
    p0 = np.asarray([initial_by_key[key] for key in shared], dtype=np.float64)
    p = np.asarray([current_by_key[key] for key in shared], dtype=np.float64)
    if not len(shared):
        raise DiagnosticError("moving cup has no shared typed identities for pose fit")
    centroid0 = p0.mean(axis=0)
    centroid = p.mean(axis=0)
    # Fit the rotation after removing rigid translation.  The old implementation
    # passed the fixed axis origin directly, which silently biases the angle when
    # a body translates in x/y/z.
    fitted = fit_rotation(p0 - centroid0, p - centroid, np.zeros(3), axis)
    forward = rotation_matrix(axis, fitted)
    rotated_centroid = (centroid0 - origin) @ forward.T + origin
    translation = centroid - rotated_centroid
    inverse = rotation_matrix(axis, -fitted)
    local = (p - translation - origin) @ inverse.T + origin
    low = np.asarray(box["low_m"], dtype=np.float64)
    size = np.asarray(box["size_m"], dtype=np.float64)
    high = low + size
    coverage = face_coverage(local, low, size, dp, ("z-", "z+"))
    expected_angle = float(control_sign) * control_angle_rad
    angle_residual = math.atan2(math.sin(fitted - expected_angle), math.cos(fitted - expected_angle))
    predicted = (p0 - origin) @ forward.T + origin + translation
    residual = np.linalg.norm(p - predicted, axis=1)
    current_velocity = np.asarray([row_velocity(row) for row in current], dtype=np.float64)
    displacement = np.linalg.norm(p - p0, axis=1)
    return {
        "time_s": float(time_s),
        "moving_node_count_initial": len(initial),
        "moving_node_count_current": len(current),
        "typed_identity_intersection": len(shared),
        "fit_angle_rad": float(fitted),
        "prescribed_angle_rad": float(control_angle_rad),
        "native_control_sign": float(control_sign),
        "expected_native_angle_rad": float(expected_angle),
        "angle_residual_rad": float(angle_residual),
        "initial_centroid_m": centroid0.tolist(),
        "current_centroid_m": centroid.tolist(),
        "translation_m": translation.tolist(),
        "mean_velocity_m_s": current_velocity.mean(axis=0).tolist() if len(current_velocity) else None,
        "max_velocity_m_s": float(np.linalg.norm(current_velocity, axis=1).max()) if len(current_velocity) else None,
        "position_rms_residual_m": float(np.sqrt(np.mean(residual ** 2))) if len(residual) else None,
        "position_max_residual_m": float(residual.max()) if len(residual) else None,
        "max_node_displacement_m": float(displacement.max()) if len(displacement) else None,
        "local_bounds_low_m": local.min(axis=0).tolist() if len(local) else None,
        "local_bounds_high_m": local.max(axis=0).tolist() if len(local) else None,
        "declared_initial_bounds_low_m": low.tolist(),
        "declared_initial_bounds_high_m": high.tolist(),
        "high_low_face_coverage": coverage,
        "normal_evidence": {name: value.get("normal") for name, value in coverage.items()},
        "motion_and_face_closure_are_separate": True,
    }


def audit_case(case: Mapping[str, Any], *, partvtk: Path, partvtkout: Path, root: Path, posed_frame_indices: Iterable[int], motion_control_sign: float) -> dict[str, Any]:
    case_id = str(case["case_id"])
    dp = float(case["dp_m"])
    solver_output = require_file(Path(str(case["solver_output"])) / "RunPARTs.csv", f"{case_id} RunPARTs.csv").parent
    runparts_path = solver_output / "RunPARTs.csv"
    runparts = read_runparts(runparts_path)
    data_dir = require_file(solver_output / "data/PartOut_000.obi4", f"{case_id} PartOut_000.obi4").parent
    generated_xml = require_file(case["generated_xml"], f"{case_id} generated XML")
    gencase_receipt = require_file(case["gencase_receipt"], f"{case_id} GenCase receipt")
    solver_receipt = require_file(case["solver_receipt"], f"{case_id} solver receipt")
    motion = require_file(case["motion"], f"{case_id} motion control")
    boxes = parse_boxes(generated_xml)
    frame_dir = root / "partvtk" / case_id
    first = decode_frame(binary=partvtk, data_dir=data_dir, frame_first=0, frame_last=3, output_dir=frame_dir, prefix="Particles")
    max_frame = len(runparts) - 1
    posed_indices = sorted({int(index) for index in posed_frame_indices})
    if any(index <= 0 or index > max_frame for index in posed_indices):
        raise DiagnosticError(f"{case_id} posed frame indices exceed RunPARTs range: {posed_indices}")
    posed = decode_selected_frames(
        binary=partvtk,
        data_dir=data_dir,
        frame_indices=posed_indices,
        output_dir=frame_dir,
        prefix="Posed",
    )
    exclusion = decode_exclusions(binary=partvtkout, data_dir=data_dir, output_dir=root / "partvtkout" / case_id, prefix="excluded_particles")
    frame_records: list[tuple[int, dict[str, str], list[dict[str, str]]]] = []
    for item in first["frames"]:
        summary, rows = parse_csv_rows(Path(item["path"]))
        frame_records.append((int(item["index"]), summary, rows))
    initial_index, initial_summary, initial_rows = frame_records[0]
    fluid_rows = [row for row in initial_rows if int(row["Type"]) == 3]
    fluid_mass = float(sum(finite_float(row["Mass [kg]"]) for row in fluid_rows))
    declared_volume = float(sum(np.prod(np.asarray(box["size_m"], dtype=np.float64)) for values in boxes["fluids"].values() for box in values))
    volume_from_particles = float(len(fluid_rows) * dp ** 3)
    declared_mass = declared_volume * 1000.0
    mass_error_fraction = (volume_from_particles / declared_volume - 1.0) if declared_volume else None
    id_to_identity: dict[int, set[tuple[int, int, int]]] = {}
    for row in initial_rows:
        id_to_identity.setdefault(int(row["Idp"]), set()).add(
            (int(row["Zone"]), int(row["Type"]), int(row["Mk"]))
        )
    exclusion_rows: list[dict[str, Any]] = []
    motive_totals: Counter[str] = Counter()
    unresolved_parts: list[int] = []
    typed_totals: Counter[str] = Counter()
    for row in exclusion["rows"]:
        part = int(row["part_out"])
        time_value = runparts[part]["time_s"] if 0 <= part < len(runparts) else None
        if time_value is None:
            unresolved_parts.append(part)
        identities = sorted(id_to_identity.get(int(row["idp"]), set()))
        zones = sorted({identity[0] for identity in identities})
        types = sorted({identity[1] for identity in identities})
        mks = sorted({identity[2] for identity in identities})
        for identity in identities:
            typed_totals["%d/%d/%d" % identity] += 1
        motive_totals[str(row["motive"])] += 1
        exclusion_rows.append({
            **row,
            "zone_candidates": zones,
            "typed_identity": {
                "zone": zones[0] if len(zones) == 1 else None,
                "idp": int(row["idp"]),
                "type": types[0] if len(types) == 1 else None,
                "mk": mks[0] if len(mks) == 1 else None,
                "initial_zone_type_mk": [list(identity) for identity in identities],
            },
            "first_missing_frame": part,
            "first_missing_time_s": time_value,
            "motive_class": "native_solver_excluded_numerical_unknown",
        })
    motion_times, motion_angles = read_motion(motion)
    origin = np.asarray([0.0, 0.0, 0.65], dtype=np.float64)
    axis = np.asarray([0.0, 1.0, 0.0], dtype=np.float64)
    cup_box = boxes["bounds"].get(0)
    if cup_box is None:
        raise DiagnosticError(f"{case_id} has no moving cup bound box")
    pose_rows: list[dict[str, Any]] = []
    posed_frame_records: list[tuple[int, dict[str, str], list[dict[str, str]]]] = []
    for item in posed["frames"]:
        summary, rows = parse_csv_rows(Path(item["path"]))
        posed_frame_records.append((int(item["index"]), summary, rows))
    for index, _, rows in posed_frame_records:
        time_value = runparts[index]["time_s"] if index < len(runparts) else float(index)
        control_angle = float(np.interp(time_value, motion_times, motion_angles))
        pose_rows.append(cup_pose_evidence(rows, initial_rows, time_s=time_value, control_angle_rad=control_angle, control_sign=motion_control_sign, origin=origin, axis=axis, box=cup_box, dp=dp))
    fixed = fixed_wall_evidence(initial_rows, boxes["bounds"], dp)
    receipt_data = {"solver": json.loads(solver_receipt.read_text()), "gencase": json.loads(gencase_receipt.read_text())}
    return {
        "case_id": case_id,
        "resolution": case.get("resolution"),
        "dp_m": dp,
        "source_bindings": {
            "solver_receipt": {"path": str(solver_receipt), "sha256": sha256(solver_receipt)},
            "gencase_receipt": {"path": str(gencase_receipt), "sha256": sha256(gencase_receipt)},
            "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
            "motion": {"path": str(motion), "sha256": sha256(motion)},
            "runparts": {"path": str(runparts_path), "sha256": sha256(runparts_path)},
            "partout_000": {"path": str(data_dir / "PartOut_000.obi4"), "sha256": sha256(data_dir / "PartOut_000.obi4")},
        },
        "initial_frame": {
            "summary": initial_summary,
            "particle_count": len(initial_rows),
            "fluid_count_type3": len(fluid_rows),
            "fluid_mass_sum_kg": fluid_mass,
            "continuous_volume_m3": declared_volume,
            "continuous_mass_kg": declared_mass,
            "particle_lattice_volume_m3": volume_from_particles,
            "particle_lattice_mass_kg": volume_from_particles * 1000.0,
            "particle_lattice_relative_volume_error": mass_error_fraction,
            "source_layer_counts_by_native_mk": dict(sorted(Counter(int(row["Mk"]) for row in fluid_rows).items())),
            "fluid_bounds_low_m": points_from_rows(fluid_rows).min(axis=0).tolist() if fluid_rows else None,
            "fluid_bounds_high_m": points_from_rows(fluid_rows).max(axis=0).tolist() if fluid_rows else None,
            "mass_is_reported_without_normalization": True,
        },
        "partvtk_initial_decode": first,
        "partvtk_posed_decode": posed,
        "partvtkout_exclusion_decode": {
            "execution": {key: value for key, value in exclusion.items() if key != "rows"},
            "row_count": len(exclusion["rows"]),
            "motive_totals": dict(sorted(motive_totals.items())),
            "typed_identity_totals": dict(sorted(typed_totals.items())),
            "unresolved_first_missing_parts": sorted(set(unresolved_parts)),
            "records": exclusion_rows,
            "positions_velocity_density_are_native_partvtkout": True,
            "excluded_mass_is_numerical_unknown_until_event_audit": True,
        },
        "moving_cup_local_frame": {
            "axis_origin_m": origin.tolist(),
            "axis_unit": axis.tolist(),
            "pose_frames_after_initial": pose_rows,
            "high_low_face_evidence_not_particle_count": True,
        },
        "finite_wall_evidence_frame0": fixed,
        "geometry_boxes_from_generated_xml": jsonable(boxes),
        "runparts_exclusion_totals": {
            "NpOut": int(sum(row["NpOut"] for row in runparts)),
            "NpOutPos": int(sum(row["NpOutPos"] for row in runparts)),
            "NpOutRho": int(sum(row["NpOutRho"] for row in runparts)),
            "NpOutMov": int(sum(row["NpOutMov"] for row in runparts)),
            "final_time_s": float(runparts[-1]["time_s"]),
        },
        "interpretation": {
            "native_exclusion_motive_is_not_physical_spill": True,
            "receiver_and_tray_require_finite_face_coverage": True,
            "continuous_volume_comparison_precedes_any_mass_normalization": True,
            "qualification_status": "pending_root_scientific_review",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--partvtk", type=Path, required=True)
    parser.add_argument("--partvtkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    partvtk = require_file(args.partvtk, "PartVTK binary")
    partvtkout = require_file(args.partvtkout, "PartVTKOut binary")
    manifest_path = require_file(args.manifest, "diagnostic manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") not in {
        "ds-data-02.f2.native-resolution-diagnostic-input.v1",
        "ds-data-02.f2.native-resolution-diagnostic-input.v2",
    }:
        raise DiagnosticError("diagnostic manifest schema is invalid")
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 4:
        raise DiagnosticError("diagnostic manifest must contain exactly four medium/fine cases")
    posed_frame_indices = manifest.get("posed_frame_indices", [1, 2, 3])
    if not isinstance(posed_frame_indices, list) or not posed_frame_indices:
        raise DiagnosticError("diagnostic manifest must contain posed_frame_indices")
    motion_control_sign = float(manifest.get("motion_control_sign", -1.0))
    if not math.isfinite(motion_control_sign) or motion_control_sign not in {-1.0, 1.0}:
        raise DiagnosticError("motion_control_sign must be +1 or -1")
    report = {
        "schema": "ds-data-02.f2.native-resolution-diagnostic.v2" if manifest.get("schema", "").endswith(".v2") else "ds-data-02.f2.native-resolution-diagnostic.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "binary_bindings": {
            "partvtk": {"path": str(partvtk), "sha256": sha256(partvtk)},
            "partvtkout": {"path": str(partvtkout), "sha256": sha256(partvtkout)},
        },
        "posed_frame_indices": [int(index) for index in posed_frame_indices],
        "motion_control_sign": motion_control_sign,
        "cases": [audit_case(case, partvtk=partvtk, partvtkout=partvtkout, root=output.parent / "artifacts", posed_frame_indices=posed_frame_indices, motion_control_sign=motion_control_sign) for case in cases],
        "status": "diagnostic_complete_pending_scientific_review",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    output.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "path": str(output), "sha256": sha256(output), "case_count": len(report["cases"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
