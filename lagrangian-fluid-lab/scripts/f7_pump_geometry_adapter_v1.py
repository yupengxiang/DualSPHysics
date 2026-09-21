#!/usr/bin/env python3
"""Read the official DualSPHysics Pump geometry into the Core geometry contract.

This adapter is intentionally a pure, in-memory boundary.  It parses the
official Pump XML plus its fixed binary and moving ASCII POLYDATA files and
returns a :class:`scripts.core_contract.PrescribedGeometry`.  It does not
write generated inputs, invoke GenCase/native tools, or start any runtime.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from scripts.core_contract import (
    DUALSPHYSICS_MVROTFILE_ROTATION_VERSION,
    PrescribedGeometry,
)


LAB = Path(__file__).resolve().parents[1]
PUMP_RELATIVE_DIR = "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump"
DEFAULT_DEFINITION = LAB / PUMP_RELATIVE_DIR / "CasePump_Def.xml"
DEFAULT_FIXED = LAB / PUMP_RELATIVE_DIR / "pump_fixed.vtk"
DEFAULT_MOVING = LAB / PUMP_RELATIVE_DIR / "pump_moving.vtk"
COORDINATE_FRAME = "official DualSPHysics Pump world coordinates"
OFFICIAL_SOURCE_SHA256 = {
    "CasePump_Def.xml": "746ae80f4c21bca62a01d59ee04d0eaaf3d1af830c36dafef4b684ca8f3c9453",
    "pump_fixed.vtk": "6148ea8f05a2cf497eb14dd6d7ae03693cafa1c8bd271f74ff1316ba2fbaf616",
    "pump_moving.vtk": "376a6d84164ec1e154486196b4d6e7f647f857ad6cd2cf12fdd268f435753c72",
}

_VTK_DTYPES = {
    "float": ">f4",
    "double": ">f8",
    "int": ">i4",
    "unsigned_int": ">u4",
    "short": ">i2",
    "unsigned_short": ">u2",
    "char": ">i1",
    "unsigned_char": ">u1",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _line(data: bytes, offset: int) -> tuple[str, int]:
    while offset < len(data) and data[offset:offset + 1] in (b"\n", b"\r"):
        offset += 1
    end = data.find(b"\n", offset)
    if end < 0:
        raise ValueError("truncated VTK ASCII header")
    try:
        value = data[offset:end].decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise ValueError("binary VTK array was parsed at the wrong offset") from error
    return value, end + 1


def _binary_array(data: bytes, offset: int, count: int, scalar_type: str) -> tuple[np.ndarray, int]:
    dtype = _VTK_DTYPES.get(scalar_type.lower())
    if dtype is None:
        raise ValueError(f"unsupported VTK scalar type: {scalar_type}")
    np_dtype = np.dtype(dtype)
    end = offset + int(count) * np_dtype.itemsize
    if end > len(data):
        raise ValueError("truncated binary VTK array")
    return np.frombuffer(data[offset:end], dtype=np_dtype).copy(), end


def _ascii_array(data: bytes, offset: int, count: int, *, integer: bool = False) -> tuple[np.ndarray, int]:
    try:
        text = data[offset:].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("ASCII VTK section contains non-ASCII bytes") from error
    values: list[str] = []
    cursor = 0
    for _ in range(int(count)):
        match = re.match(r"\s*(\S+)", text[cursor:])
        if match is None:
            raise ValueError("truncated ASCII VTK array")
        values.append(match.group(1))
        cursor += match.end()
    try:
        parsed = np.asarray([int(value) if integer else float(value) for value in values])
    except ValueError as error:
        raise ValueError("invalid ASCII VTK scalar") from error
    return parsed, offset + cursor


def read_polydata(path: Path) -> dict[str, Any]:
    """Read official VTK POLYDATA points and polygon connectivity.

    The Pump example deliberately has no ``CELL_DATA`` section, unlike the
    generated ``MkCells.vtk`` files consumed by ``boundary_sidecars``.  This
    parser therefore stops after ``POLYGONS`` and assigns labels from the XML
    source that selected each file.
    """
    data = Path(path).read_bytes()
    offset = 0
    header, offset = _line(data, offset)
    if not header.startswith("# vtk DataFile"):
        raise ValueError(f"not a VTK file: {path}")
    _, offset = _line(data, offset)
    encoding, offset = _line(data, offset)
    if encoding.upper() not in {"ASCII", "BINARY"}:
        raise ValueError(f"unsupported VTK encoding: {encoding}")
    dataset, offset = _line(data, offset)
    if dataset.upper() != "DATASET POLYDATA":
        raise ValueError(f"expected POLYDATA, got {dataset!r}")

    line, offset = _line(data, offset)
    parts = line.split()
    if len(parts) != 3 or parts[0].upper() != "POINTS":
        raise ValueError(f"expected POINTS header, got {line!r}")
    point_count, point_type = int(parts[1]), parts[2]
    if point_count <= 0:
        raise ValueError("POLYDATA must contain points")
    if encoding.upper() == "BINARY":
        point_values, offset = _binary_array(data, offset, point_count * 3, point_type)
    else:
        point_values, offset = _ascii_array(data, offset, point_count * 3)
    points = np.asarray(point_values, dtype=np.float64).reshape(point_count, 3)
    if not np.isfinite(points).all():
        raise ValueError("POLYDATA points are not finite")

    line, offset = _line(data, offset)
    parts = line.split()
    if len(parts) != 3 or parts[0].upper() != "POLYGONS":
        raise ValueError(f"expected POLYGONS header, got {line!r}")
    polygon_count, integer_count = int(parts[1]), int(parts[2])
    if polygon_count <= 0 or integer_count < polygon_count * 4:
        raise ValueError("invalid POLYGONS counts")
    if encoding.upper() == "BINARY":
        polygon_values, offset = _binary_array(data, offset, integer_count, "int")
    else:
        polygon_values, offset = _ascii_array(data, offset, integer_count, integer=True)

    cells: list[np.ndarray] = []
    cursor = 0
    for _ in range(polygon_count):
        if cursor >= integer_count:
            raise ValueError("truncated polygon connectivity")
        vertex_count = int(polygon_values[cursor])
        cursor += 1
        if vertex_count < 3 or cursor + vertex_count > integer_count:
            raise ValueError("invalid polygon vertex count")
        cell = np.asarray(polygon_values[cursor:cursor + vertex_count], dtype=np.int64)
        cursor += vertex_count
        if np.any(cell < 0) or np.any(cell >= point_count):
            raise ValueError("polygon references an out-of-range point")
        cells.append(cell)
    if cursor != integer_count:
        raise ValueError("POLYGONS connectivity count does not match cells")

    triangles: list[np.ndarray] = []
    for cell in cells:
        for index in range(1, len(cell) - 1):
            triangles.append(points[[cell[0], cell[index], cell[index + 1]]])
    raw_result = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    cross = np.cross(raw_result[:, 1] - raw_result[:, 0], raw_result[:, 2] - raw_result[:, 0])
    norms = np.linalg.norm(cross, axis=1)
    if not np.isfinite(raw_result).all():
        raise ValueError("POLYDATA contains nonfinite triangles")
    valid = norms > 1e-15
    if not np.any(valid):
        raise ValueError("POLYDATA contains no nondegenerate triangles")
    result = raw_result[valid]
    return {
        "path": str(Path(path)),
        "encoding": encoding.upper(),
        "point_count": point_count,
        "polygon_count": polygon_count,
        "integer_count": integer_count,
        "points": points,
        "cells": cells,
        "triangles": result,
        "raw_triangle_count": len(raw_result),
        "degenerate_triangle_count": int(np.count_nonzero(~valid)),
        "triangle_count": len(result),
    }


def _float_attr(node: ET.Element, key: str) -> float:
    value = node.get(key)
    if value is None:
        raise ValueError(f"missing XML attribute {key}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"nonfinite XML attribute {key}")
    return result


def parse_pump_definition(path: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    """Parse and validate the immutable official Pump XML contract."""
    path = Path(path)
    observed_definition_hash = sha256_file(path)
    if observed_definition_hash != OFFICIAL_SOURCE_SHA256["CasePump_Def.xml"]:
        raise ValueError("Pump XML is not the allowlisted official source")
    root = ET.parse(path).getroot()
    draw_files = root.findall("./casedef/geometry/commands/mainlist/drawfilevtk")
    draw_names = [item.get("file") for item in draw_files]
    if draw_names != ["pump_fixed.vtk", "pump_moving.vtk"]:
        raise ValueError(f"unexpected Pump VTK source order: {draw_names}")
    mainlist = root.findall("./casedef/geometry/commands/mainlist/*")
    bound_labels = [item.get("mk") for item in mainlist if item.tag == "setmkbound"]
    fluid_labels = [item.get("mk") for item in mainlist if item.tag == "setmkfluid"]
    if bound_labels != ["0", "2"] or fluid_labels != ["1"]:
        raise ValueError("official Pump mk sequence is not fixed=0, moving=2, fluid=1")

    object_node = root.find("./casedef/motion/objreal[@ref='2']")
    if object_node is None:
        raise ValueError("official Pump has no objreal ref=2")
    begin = object_node.find("./begin")
    rotations = object_node.findall("./mvrotace")
    if begin is None or len(rotations) != 2:
        raise ValueError("official Pump motion schedule is incomplete")
    if begin.get("mov") != "1":
        raise ValueError("official Pump motion begin must select mov=1")
    start = _float_attr(begin, "start")
    finish = _float_attr(begin, "finish")
    if finish <= start:
        raise ValueError("Pump motion finish must be after its start")
    segments: list[dict[str, Any]] = []
    axis_point: np.ndarray | None = None
    axis_p2: np.ndarray | None = None
    segment_ids: list[int] = []
    for rotation in rotations:
        p1_node, p2_node = rotation.find("./axisp1"), rotation.find("./axisp2")
        if p1_node is None or p2_node is None:
            raise ValueError("Pump rotation axis is incomplete")
        p1 = np.asarray([_float_attr(p1_node, key) for key in ("x", "y", "z")])
        p2 = np.asarray([_float_attr(p2_node, key) for key in ("x", "y", "z")])
        if axis_point is None:
            axis_point, axis_p2 = p1, p2
        elif not np.allclose(axis_point, p1) or not np.allclose(axis_p2, p2):
            raise ValueError("Pump motion segments do not share one fixed axis")
        acceleration = rotation.find("./ace")
        initial_velocity = rotation.find("./velini")
        segment_id = rotation.get("id")
        if segment_id is None:
            raise ValueError("Pump rotation segment is missing id")
        segment_id_int = int(segment_id)
        if segment_id_int in segment_ids:
            raise ValueError("Pump rotation segment ids must be unique")
        segment_ids.append(segment_id_int)
        angle_units = rotation.get("anglesunits", "degrees")
        if angle_units != "degrees":
            raise ValueError("F7 Pump adapter requires explicit degree-valued rotation segments")
        next_id = rotation.get("next")
        segments.append({
            "id": segment_id_int,
            "next_id": None if next_id is None else int(next_id),
            "angle_units": angle_units,
            "duration_s": _float_attr(rotation, "duration"),
            "acceleration_deg_s2": 0.0 if acceleration is None else _float_attr(acceleration, "ang"),
            "initial_velocity_deg_s": None if initial_velocity is None else _float_attr(initial_velocity, "ang"),
        })
    if segments[0]["id"] != 1 or segments[0]["next_id"] != segments[1]["id"]:
        raise ValueError("Pump rotation segments do not form the expected 1 -> 2 chain")
    if segments[1]["next_id"] is not None:
        raise ValueError("Pump rotation schedule has an unexpected trailing segment")
    if abs(float(segments[1]["acceleration_deg_s2"])) > 1e-12:
        raise ValueError("Pump second rotation segment must have zero acceleration")
    if segments[1]["initial_velocity_deg_s"] is not None:
        raise ValueError("Pump second rotation segment must inherit velocity")
    if any(float(segment["duration_s"]) <= 0 for segment in segments):
        raise ValueError("Pump rotation segment durations must be positive")
    assert axis_point is not None and axis_p2 is not None
    axis_direction = axis_p2 - axis_point
    if np.linalg.norm(axis_direction) <= 1e-15:
        raise ValueError("Pump rotation axis is degenerate")
    parameters = {
        item.get("key"): item.get("value")
        for item in root.findall("./execution/parameters/parameter")
    }
    contract = {
        "schema": "core.f7.pump.recirculation.motion_source.v1",
        "definition_path": str(path),
        "definition_sha256": sha256_file(path),
        "draw_files": draw_names,
        "fixed_mk": 0,
        "moving_mk": 2,
        "fluid_mk": 1,
        "moving_object_ref": 2,
        "begin_mov_id": 1,
        "finish_s": finish,
        "angle_units": "degrees",
        "begin_start_s": start,
        "axis_point_m": axis_point.tolist(),
        "axis_p2_m": axis_p2.tolist(),
        "axis_direction_m": axis_direction.tolist(),
        "segments": segments,
        "time_max_s": float(parameters["TimeMax"]),
        "time_out_s": float(parameters["TimeOut"]),
        "motion_version": DUALSPHYSICS_MVROTFILE_ROTATION_VERSION,
    }
    if (not math.isfinite(contract["time_max_s"]) or contract["time_max_s"] <= 0
            or not math.isfinite(contract["time_out_s"]) or contract["time_out_s"] <= 0
            or contract["time_out_s"] > contract["time_max_s"]):
        raise ValueError("Pump TimeMax/TimeOut must be finite, positive, and ordered")
    contract["definition_sha256"] = observed_definition_hash
    contract["motion_sha256"] = _canonical_hash(contract)
    return contract


def pump_angle_degrees(time_s: float, contract: dict[str, Any]) -> float:
    """Evaluate the official two-stage prescribed angular displacement."""
    time_s = float(time_s)
    if not math.isfinite(time_s) or time_s < 0:
        raise ValueError("Pump time must be finite and nonnegative")
    start = float(contract["begin_start_s"])
    finish = float(contract["finish_s"])
    time_s = min(time_s, finish)
    first = contract["segments"][0]
    duration = float(first["duration_s"])
    acceleration = float(first["acceleration_deg_s2"])
    initial_velocity = float(first["initial_velocity_deg_s"] or 0.0)
    if time_s <= start:
        return 0.0
    elapsed = min(time_s - start, duration)
    first_angle = initial_velocity * elapsed + 0.5 * acceleration * elapsed * elapsed
    if time_s <= start + duration:
        return first_angle
    final_velocity = initial_velocity + acceleration * duration
    return first_angle + final_velocity * (time_s - start - duration)


def pump_angular_velocity_degrees_per_second(time_s: float, contract: dict[str, Any]) -> float:
    """Evaluate the exact XML piecewise angular velocity, including event bounds."""
    time_s = float(time_s)
    if not math.isfinite(time_s) or time_s < 0:
        raise ValueError("Pump time must be finite and nonnegative")
    start = float(contract["begin_start_s"])
    finish = float(contract["finish_s"])
    if time_s <= start or time_s >= finish:
        return 0.0
    first = contract["segments"][0]
    duration = float(first["duration_s"])
    acceleration = float(first["acceleration_deg_s2"])
    initial_velocity = float(first["initial_velocity_deg_s"] or 0.0)
    if time_s <= start + duration:
        return initial_velocity + acceleration * (time_s - start)
    return initial_velocity + acceleration * duration


def _motion_samples(contract: dict[str, Any], end_time_s: float, sample_interval_s: float) -> tuple[np.ndarray, np.ndarray]:
    end_time_s = float(end_time_s)
    sample_interval_s = float(sample_interval_s)
    if not math.isfinite(end_time_s) or end_time_s <= 0:
        raise ValueError("Pump end time must be positive and finite")
    if not math.isfinite(sample_interval_s) or sample_interval_s <= 0:
        raise ValueError("Pump sample interval must be positive and finite")
    first_end = float(contract["begin_start_s"]) + float(contract["segments"][0]["duration_s"])
    knots = np.arange(0.0, end_time_s, sample_interval_s, dtype=np.float64)
    knots = np.concatenate((knots, np.asarray([
        0.0,
        contract["begin_start_s"],
        first_end,
        contract["finish_s"],
        end_time_s,
    ])))
    times = np.unique(np.round(knots[(knots >= 0.0) & (knots <= end_time_s)], 12))
    if len(times) < 2 or times[-1] != end_time_s:
        times = np.concatenate((times, np.asarray([end_time_s])))
    angles = np.asarray([pump_angle_degrees(value, contract) for value in times], dtype=np.float64)
    return times, angles


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(path)


def load_pump_geometry(
    definition: Path = DEFAULT_DEFINITION,
    fixed_geometry: Path = DEFAULT_FIXED,
    moving_geometry: Path = DEFAULT_MOVING,
    *,
    end_time_s: float | None = None,
    sample_interval_s: float = 0.01,
) -> tuple[PrescribedGeometry, dict[str, Any]]:
    """Return a Core prescribed geometry and immutable source metadata."""
    definition = Path(definition)
    fixed_geometry, moving_geometry = Path(fixed_geometry), Path(moving_geometry)
    contract = parse_pump_definition(definition)
    expected_fixed, expected_moving = contract["draw_files"]
    expected_fixed_path = (definition.parent / expected_fixed).resolve()
    expected_moving_path = (definition.parent / expected_moving).resolve()
    if (fixed_geometry.resolve() != expected_fixed_path
            or moving_geometry.resolve() != expected_moving_path):
        raise ValueError("Pump geometry paths do not match the XML drawfilevtk source directory")
    if sha256_file(fixed_geometry) != OFFICIAL_SOURCE_SHA256[expected_fixed]:
        raise ValueError("Pump fixed geometry is not the allowlisted official source")
    if sha256_file(moving_geometry) != OFFICIAL_SOURCE_SHA256[expected_moving]:
        raise ValueError("Pump moving geometry is not the allowlisted official source")
    fixed = read_polydata(fixed_geometry)
    moving = read_polydata(moving_geometry)
    triangles = np.concatenate((fixed["triangles"], moving["triangles"]), axis=0)
    component_id = np.concatenate((
        np.zeros(fixed["triangle_count"], dtype=np.int64),
        np.ones(moving["triangle_count"], dtype=np.int64),
    ))
    body_id = np.concatenate((
        np.zeros(fixed["triangle_count"], dtype=np.int64),
        np.full(moving["triangle_count"], 2, dtype=np.int64),
    ))
    wall_velocity = np.zeros((len(triangles), 3), dtype=np.float64)
    end_time = float(contract["time_max_s"] if end_time_s is None else end_time_s)
    times, angles = _motion_samples(contract, end_time, sample_interval_s)
    max_acceleration = max(
        abs(float(segment["acceleration_deg_s2"])) for segment in contract["segments"]
    )
    interpolation_error_bound = max_acceleration * float(sample_interval_s) ** 2 / 8.0
    geometry = PrescribedGeometry(
        triangles,
        component_id,
        body_id,
        wall_velocity,
        COORDINATE_FRAME,
        times,
        angles,
        np.asarray(contract["axis_point_m"], dtype=np.float64),
        np.asarray(contract["axis_direction_m"], dtype=np.float64),
        moving_body_id=2,
        motion_version=DUALSPHYSICS_MVROTFILE_ROTATION_VERSION,
        motion_sha256=contract["motion_sha256"],
    )
    metadata = {
        "schema": "core.f7.pump.geometry_adapter.v1",
        "coordinate_frame": COORDINATE_FRAME,
        "source_bindings": [
            {"path": _relative(definition), "sha256": sha256_file(definition), "role": "Pump XML"},
            {"path": _relative(fixed_geometry), "sha256": sha256_file(fixed_geometry), "role": "fixed VTK"},
            {"path": _relative(moving_geometry), "sha256": sha256_file(moving_geometry), "role": "moving VTK"},
        ],
        "official_source_allowlist": dict(OFFICIAL_SOURCE_SHA256),
        "xml_contract": contract,
        "fixed": {key: value for key, value in fixed.items() if key not in {"points", "cells", "triangles"}},
        "moving": {key: value for key, value in moving.items() if key not in {"points", "cells", "triangles"}},
        "combined_triangle_count": int(len(triangles)),
        "moving_body_id": 2,
        "sample_times_s": times.tolist(),
        "sample_angles_degrees": angles.tolist(),
        "motion_sampling": {
            "sample_interval_s": float(sample_interval_s),
            "analytic_angle_evaluator": "pump_angle_degrees",
            "analytic_angular_velocity_evaluator": "pump_angular_velocity_degrees_per_second",
            "linear_angle_interpolation_error_bound_deg": interpolation_error_bound,
            "core_prescribed_geometry_uses_sampled_pose_and_gradient_velocity": True,
            "exact_motion_contract_is_not_runtime_evidence": True,
        },
        "runtime_execution": {
            "read_only": True,
            "definition_written": False,
            "gencase_invoked": False,
            "native_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
        },
    }
    return geometry, metadata


if __name__ == "__main__":
    geometry, metadata = load_pump_geometry()
    print(json.dumps({
        "schema": metadata["schema"],
        "combined_triangle_count": metadata["combined_triangle_count"],
        "moving_body_id": metadata["moving_body_id"],
        "motion_sha256": geometry.motion_sha256,
        "runtime_execution": metadata["runtime_execution"],
    }, ensure_ascii=False, indent=2))
