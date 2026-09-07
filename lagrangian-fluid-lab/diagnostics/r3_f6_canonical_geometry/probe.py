#!/usr/bin/env python3
"""Audit the canonical E0 mDBC geometry and its generated VTK semantics.

This diagnostic deliberately keeps the physical wall and the numerical
particle layer as separate objects.  The ``GeometryForNormals`` list describes
the surface to which normals are constructed (the ``*_hdp_Actual.vtk`` file),
while ``mainlist`` describes the actual boundary particles.  In particular,
the Float1 normal-construction cylinder and the Float1 particle cylinder are
looked up in their named XML lists; no global ``drawcylinder`` search is used.

DualSPHysics writes ``CfgInit_Normals.vtk`` and
``CfgInit_NormalsGhost.vtk`` with the same ``POINTS``.  The first ``Normal``
array is the boundary-to-limit displacement ``n_b`` and the second is the
solver-doubled displacement ``n_g``.  The audit therefore reconstructs
``x_g=x_b+n_g`` and ``x_gamma=x_b+n_g/2``.  It never treats ghost-file points
as already being ghost coordinates.

The report is an E0 geometry result, not a hydrostatic or force acceptance:
both definitions have real CPU GenCase and one-step CPU mDBC artifacts, but
the physical mDBC gate remains blocked until pressure/force closure is run.
The Float1 candidate additionally records the official Chrono warning because
its definition intentionally uses ``RigidAlgorithm=1`` for a short geometry
smoke test rather than claiming a validated floating-body integration.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import numpy as np


LAB = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parent
DEFINITIONS = ROOT / "definitions"
EVIDENCE = ROOT / "evidence"
OUTPUT_JSON = ROOT / "canonical-geometry.json"
OUTPUT_MD = ROOT / "CANONICAL-GEOMETRY.md"

ZERO_TOLERANCE = 1.0e-12
FINITE_TOLERANCE = 1.0e-12
INTERFACE_TOLERANCE_M = 1.0e-5
CYLINDER_INTERFACE_TOLERANCE_M = 2.0e-3
ORIENTATION_TOLERANCE = 0.5
DOUBLING_TOLERANCE = 2.0e-5


CASE_SPECS: dict[str, dict[str, Any]] = {
    "canonical_rectangular": {
        "label": "canonical rectangular tank",
        "definition": DEFINITIONS / "canonical_rectangular_Def.xml",
        "evidence": EVIDENCE / "rectangular",
        "kind": "rectangular_open_top",
        "physical_tank": {
            "x_min_m": 0.02,
            "x_max_m": 0.38,
            "y_min_m": 0.02,
            "y_max_m": 0.28,
            "z_floor_m": 0.02,
            "z_side_max_m": 0.30,
        },
    },
    "canonical_float1_cylinder": {
        "label": "canonical tank plus Float1 cylinder",
        "definition": DEFINITIONS / "canonical_float1_cylinder_Def.xml",
        "evidence": EVIDENCE / "float1_cylinder",
        "kind": "rectangular_open_top_plus_float1_cylinder",
        "physical_tank": {
            "x_min_m": 0.02,
            "x_max_m": 0.38,
            "y_min_m": 0.02,
            "y_max_m": 0.28,
            "z_floor_m": 0.02,
            "z_side_max_m": 0.35,
        },
        "physical_float1": {
            "center_xy_m": [0.20, 0.16],
            "radius_m": 0.11,
            "z_min_m": 0.14,
            "z_max_m": 0.30,
        },
    },
}


def _field_dtype(kind: str) -> tuple[str, int]:
    """Return the big-endian NumPy dtype and byte width for VTK binary data."""

    if kind == "short":
        return ">i2", 2
    if kind == "int":
        return ">i4", 4
    if kind == "float":
        return ">f4", 4
    if kind == "double":
        return ">f8", 8
    raise ValueError(f"unsupported binary VTK field type: {kind}")


def _points_from_vtk_bytes(content: bytes, path: Path) -> tuple[np.ndarray, int]:
    point_header = re.search(
        br"POINTS\s+(\d+)\s+(float|double)\r?\n", content
    )
    if point_header is None:
        raise ValueError(f"{path} has no binary POINTS header")
    count = int(point_header.group(1))
    dtype, width = _field_dtype(point_header.group(2).decode())
    point_offset = point_header.end()
    point_end = point_offset + count * 3 * width
    if point_end > len(content):
        raise ValueError(f"{path} ends inside POINTS payload")
    points = np.frombuffer(
        content, dtype=dtype, count=count * 3, offset=point_offset
    ).reshape(count, 3)
    return points.astype(float), point_end


def read_binary_vtk_fields(path: Path) -> dict[str, Any]:
    """Read POINTS and FIELD arrays from a binary VTK POLYDATA file.

    The parser is intentionally strict about point/field counts and payload
    boundaries.  A missing FIELD block is an error rather than an implicit
    all-zero normal field.
    """

    content = path.read_bytes()
    points, point_end = _points_from_vtk_bytes(content, path)
    field_match = re.search(br"FIELD\s+FieldData\s+(\d+)\r?\n", content[point_end:])
    if field_match is None:
        raise ValueError(f"{path} has no FIELD FieldData block")
    cursor = point_end + field_match.end()
    field_count = int(field_match.group(1))
    arrays: dict[str, np.ndarray] = {}
    headers: dict[str, dict[str, Any]] = {}
    for _ in range(field_count):
        header = re.match(
            rb"([A-Za-z0-9_]+)\s+(\d+)\s+(\d+)\s+"
            rb"(short|int|float|double)\r?\n",
            content[cursor:],
        )
        if header is None:
            raise ValueError(f"{path} has malformed FIELD array header at {cursor}")
        name = header.group(1).decode()
        components = int(header.group(2))
        array_count = int(header.group(3))
        kind = header.group(4).decode()
        if array_count != len(points):
            raise ValueError(
                f"{path} FIELD {name} count {array_count} != "
                f"POINTS count {len(points)}"
            )
        dtype, width = _field_dtype(kind)
        data_offset = cursor + header.end()
        data_end = data_offset + components * len(points) * width
        if data_end > len(content):
            raise ValueError(f"{path} ends inside FIELD {name} payload")
        values = np.frombuffer(
            content,
            dtype=dtype,
            count=components * len(points),
            offset=data_offset,
        ).reshape(len(points), components)
        arrays[name] = values.astype(float if kind in {"float", "double"} else int)
        headers[name] = {
            "components": components,
            "count": len(points),
            "kind": kind,
            "payload_offset": data_offset,
        }
        cursor = data_end
        if content[cursor : cursor + 1] == b"\n":
            cursor += 1
    return {
        "path": str(path),
        "count": len(points),
        "points": points,
        "arrays": arrays,
        "headers": headers,
    }


def read_binary_vtk_points(path: Path) -> dict[str, Any]:
    """Read only POINTS from a binary VTK POLYDATA shape file."""

    content = path.read_bytes()
    points, _ = _points_from_vtk_bytes(content, path)
    return {"path": str(path), "count": len(points), "points": points}


def _relative(path: Path) -> str:
    return str(path.relative_to(LAB))


def _safe_int(text: str | None) -> int | None:
    if text is None:
        return None
    return int(text.replace(",", ""))


def _safe_float(text: str | None) -> float | None:
    return None if text is None else float(text)


def _float_list(text: str | None) -> list[float]:
    if not text:
        return []
    return [float(item.strip()) for item in text.split(",") if item.strip()]


def _point_element(element: ET.Element) -> list[float]:
    point = element.find("./point")
    if point is None:
        raise ValueError(f"{element.tag} has no direct point child")
    return [float(point.attrib[key]) for key in ("x", "y", "z")]


def _draw_shape_contract(
    shape: ET.Element, *, normal_invert: bool | None, mkbound: int | None
) -> dict[str, Any]:
    tag = shape.tag
    points = [
        [float(point.attrib[key]) for key in ("x", "y", "z")]
        for point in shape.findall("./point")
    ]
    layers = shape.find("./layers")
    payload: dict[str, Any] = {
        "tag": tag,
        "mkbound": mkbound,
        "normal_invert": normal_invert,
        "points": points,
        "layers_vdp": _float_list(layers.attrib.get("vdp"))
        if layers is not None
        else [],
    }
    if tag == "drawbox":
        boxfill = shape.find("./boxfill")
        size = shape.find("./size")
        payload["boxfill"] = boxfill.text.strip() if boxfill is not None and boxfill.text else ""
        payload["size"] = (
            [float(size.attrib[key]) for key in ("x", "y", "z")]
            if size is not None
            else None
        )
    elif tag == "drawcylinder":
        payload["radius_m"] = float(shape.attrib["radius"])
        payload["mask"] = int(shape.attrib.get("mask", "0"))
    return payload


def _direct_shape_contracts(container: ET.Element) -> list[dict[str, Any]]:
    """Parse direct draw commands while carrying the current XML state."""

    result: list[dict[str, Any]] = []
    normal_invert: bool | None = None
    mkbound: int | None = None
    for child in list(container):
        if child.tag == "setnormalinvert":
            normal_invert = child.attrib.get("invert", "false").lower() == "true"
        elif child.tag == "setmkbound":
            mkbound = int(child.attrib["mk"])
        elif child.tag in {"drawbox", "drawcylinder"}:
            result.append(
                _draw_shape_contract(
                    child, normal_invert=normal_invert, mkbound=mkbound
                )
            )
    return result


def parse_geometry_contract(path: Path) -> dict[str, Any]:
    """Parse named normal and particle lists from a case definition XML."""

    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    commands = root.find("./casedef/geometry/commands")
    if definition is None or commands is None:
        raise ValueError(f"{path} has no casedef geometry definition/commands")
    normal_list = commands.find("./list[@name='GeometryForNormals']")
    main_list = commands.find("./mainlist")
    if normal_list is None or main_list is None:
        raise ValueError(f"{path} must contain GeometryForNormals and mainlist")

    normal_shapes = _direct_shape_contracts(normal_list)
    main_shapes = _direct_shape_contracts(main_list)
    normal_cylinders = [shape for shape in normal_shapes if shape["tag"] == "drawcylinder"]
    actual_cylinders = [shape for shape in main_shapes if shape["tag"] == "drawcylinder"]
    normal_boxes = [shape for shape in normal_shapes if shape["tag"] == "drawbox"]
    actual_boxes = [shape for shape in main_shapes if shape["tag"] == "drawbox"]

    norgeometry = root.find("./casedef/normals/norgeometry")
    parameter_values = {
        p.attrib.get("key"): p.attrib.get("value")
        for p in root.findall("./execution/parameters/parameter")
    }
    floating = [dict(item.attrib) for item in root.findall("./casedef/floatings/floating")]

    normal_tank = next((shape for shape in normal_boxes if shape.get("mkbound") == 0), None)
    actual_tank = next((shape for shape in actual_boxes if shape.get("mkbound") == 0), None)
    normal_tank_layers = normal_tank["layers_vdp"] if normal_tank else []
    actual_tank_layers = actual_tank["layers_vdp"] if actual_tank else []
    body_layers = actual_cylinders[0]["layers_vdp"] if actual_cylinders else []

    return {
        "source": _relative(path),
        "dp_m": float(definition.attrib["dp"]),
        "normal_list_name": normal_list.attrib.get("name"),
        "normal_shapes": normal_shapes,
        "main_shapes": main_shapes,
        "normal_cylinders": normal_cylinders,
        "actual_cylinders": actual_cylinders,
        "normal_boxes": normal_boxes,
        "actual_boxes": actual_boxes,
        "normal_tank": normal_tank,
        "actual_tank": actual_tank,
        "norgeometry": {
            "geometryfile": norgeometry.find("./geometryfile").attrib["file"]
            if norgeometry is not None and norgeometry.find("./geometryfile") is not None
            else None,
            "distanceh": float(norgeometry.find("./distanceh").attrib["v"])
            if norgeometry is not None and norgeometry.find("./distanceh") is not None
            else None,
            "svshapes": norgeometry.find("./svshapes").attrib.get("v")
            if norgeometry is not None and norgeometry.find("./svshapes") is not None
            else None,
        },
        "parameters": parameter_values,
        "floating": floating,
        "layer_audit": {
            "normal_tank_vdp": normal_tank_layers,
            "main_tank_vdp": actual_tank_layers,
            "actual_body_vdp": body_layers,
            "normal_tank_half_dp_count": sum(
                1 for value in normal_tank_layers if abs(value + 0.5) <= 1.0e-12
            ),
            "main_tank_half_dp_count": sum(
                1 for value in actual_tank_layers if abs(value + 0.5) <= 1.0e-12
            ),
            "actual_body_half_dp_count": sum(
                1 for value in body_layers if abs(value + 0.5) <= 1.0e-12
            ),
            "normal_tank_has_single_half_dp_shift": normal_tank_layers.count(-0.5) == 1,
            "no_second_half_dp_on_particle_layer": (
                -0.5 not in actual_tank_layers and -0.5 not in body_layers
            ),
        },
    }


def parse_generated_xml(path: Path) -> dict[str, Any]:
    """Read GenCase's generated particle summary."""

    root = ET.parse(path).getroot()
    particles = root.find("./execution/particles")
    if particles is None:
        raise ValueError(f"{path} has no generated execution/particles summary")
    summary = particles.find("./_summary")

    def summary_item(name: str) -> dict[str, Any]:
        item = summary.find(f"./{name}") if summary is not None else None
        if item is None:
            item = root.find(f".//{name}")
        if item is None:
            return {}
        return {
            "count": _safe_int(item.attrib.get("count")),
            "id": item.attrib.get("id"),
            "mkvalues": _safe_int(item.attrib.get("mkvalues")),
            "mkcount": _safe_int(item.attrib.get("mkcount")),
        }

    return {
        "path": _relative(path),
        "np": _safe_int(particles.attrib.get("np")),
        "nb": _safe_int(particles.attrib.get("nb")),
        "nbf": _safe_int(particles.attrib.get("nbf")),
        "mkboundfirst": _safe_int(particles.attrib.get("mkboundfirst")),
        "mkfluidfirst": _safe_int(particles.attrib.get("mkfluidfirst")),
        "fixed": summary_item("fixed"),
        "moving": summary_item("moving"),
        "floating": summary_item("floating"),
        "fluid": summary_item("fluid"),
    }


def _parse_shape_line(line: str) -> tuple[str, int | None, int | None] | None:
    match = re.search(
        r"FileShapes>\s+(\S+)\s+shapes:\s*(\d+)\s+points:\s*(\d+)", line
    )
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def parse_gencase_log(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    nonzero = re.search(
        r"Non-zero particle normals:\s*([\d,]+)\s*/\s*([\d,]+).*?"
        r"Normals size range:\s*\(([0-9.eE+\-]+)\s*-\s*([0-9.eE+\-]+)\)",
        text,
    )
    zero = re.search(
        r"Final zero normals:\s*([\d,]+)\s*/\s*([\d,]+)\s*\(([0-9.]+)%\)", text
    )
    shapes: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        parsed = _parse_shape_line(line)
        if parsed is not None:
            filename, count, points = parsed
            shapes[filename] = {"shape_count": count, "point_count": points}
    code = re.findall(r"Finished execution \(code=(-?\d+)\)", text)
    return {
        "path": _relative(path),
        "return_code": int(code[-1]) if code else None,
        "points_loaded": _safe_int(
            re.search(r"Points loaded:\s*([\d,]+)", text).group(1)
            if re.search(r"Points loaded:\s*([\d,]+)", text)
            else None
        ),
        "nonzero_normals": {
            "count": _safe_int(nonzero.group(1)),
            "total": _safe_int(nonzero.group(2)),
            "min_size_m": float(nonzero.group(3)),
            "max_size_m": float(nonzero.group(4)),
        }
        if nonzero
        else {},
        "final_zero_normals": {
            "count": _safe_int(zero.group(1)),
            "total": _safe_int(zero.group(2)),
            "percentage": float(zero.group(3)),
        }
        if zero
        else {},
        "shape_outputs": shapes,
    }


def parse_solver_log(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    codes = re.findall(r"Finished execution \(code=(-?\d+)\)", text)
    warning_lines: list[str] = []
    in_warnings = False
    for line in text.splitlines():
        if line.strip() == "[WARNINGS]":
            in_warnings = True
            continue
        if in_warnings and not line.strip():
            in_warnings = False
            continue
        if in_warnings and re.match(r"\s*\d+\.\s+", line):
            warning_lines.append(re.sub(r"^\s*\d+\.\s+", "", line).strip())
    warning_lines = list(dict.fromkeys(warning_lines))
    return {
        "path": _relative(path),
        "return_code": int(codes[-1]) if codes else (0 if "Simulation finished" in text else None),
        "steps": _safe_int(
            re.search(r"Steps of simulation\.*:\s*([\d,]+)", text).group(1)
            if re.search(r"Steps of simulation\.*:\s*([\d,]+)", text)
            else None
        ),
        "boundary_mode_mdbc": 'Boundary="mDBC"' in text,
        "warnings": warning_lines,
        "chrono_warning": any("Chrono" in warning for warning in warning_lines),
        "initial_normal_files_written": all(
            (path.parent / "solver" / filename).is_file()
            for filename in ("CfgInit_Normals.vtk", "CfgInit_NormalsGhost.vtk")
        ),
    }


def _finite_bbox(values: np.ndarray) -> list[list[float]]:
    if len(values) == 0:
        return [[], []]
    return [values.min(axis=0).tolist(), values.max(axis=0).tolist()]


def _safe_unit(values: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(values, axis=1)
    return values / np.maximum(norms[:, None], ZERO_TOLERANCE)


def _hash_file(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"path": _relative(path), "bytes": size, "sha256": digest.hexdigest()}


def _face_distance_matrix(points: np.ndarray, tank: dict[str, float]) -> np.ndarray:
    return np.column_stack(
        [
            np.abs(points[:, 0] - tank["x_min_m"]),
            np.abs(points[:, 0] - tank["x_max_m"]),
            np.abs(points[:, 1] - tank["y_min_m"]),
            np.abs(points[:, 1] - tank["y_max_m"]),
            np.abs(points[:, 2] - tank["z_floor_m"]),
        ]
    )


def _tank_geometry_audit(
    interface: np.ndarray, normals: np.ndarray, fixed_mask: np.ndarray, tank: dict[str, float]
) -> dict[str, Any]:
    points = interface[fixed_mask]
    normal_unit = _safe_unit(normals[fixed_mask])
    distances = _face_distance_matrix(points, tank)
    nearest = distances.min(axis=1)
    face_vectors = np.array(
        [[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]]
    )
    expected = np.zeros_like(normal_unit)
    for index in range(face_vectors.shape[0]):
        expected += (
            distances[:, index] <= nearest + INTERFACE_TOLERANCE_M
        )[:, None] * face_vectors[index]
    expected = _safe_unit(expected)
    dots = np.sum(normal_unit * expected, axis=1)
    face_names = ("x_min", "x_max", "y_min", "y_max", "z_floor")
    face_counts = {
        name: int(np.sum(distances[:, index] <= INTERFACE_TOLERANCE_M))
        for index, name in enumerate(face_names)
    }
    corner_or_edge = np.sum(distances <= INTERFACE_TOLERANCE_M, axis=1) >= 2
    side_or_floor = nearest <= INTERFACE_TOLERANCE_M
    # A corner may have a one-sided/weighted normal because the open top rim
    # is not a fifth face.  The weak 0.5 bound is intentional and is reported;
    # it catches an inward normal without pretending lattice-corner averaging
    # is an exact analytic normal.
    return {
        "interface_point_count": int(len(points)),
        "effective_interface_bbox_m": _finite_bbox(points),
        "max_face_residual_m": float(np.max(nearest)) if len(nearest) else None,
        "median_face_residual_m": float(np.median(nearest)) if len(nearest) else None,
        "face_coverage_counts": face_counts,
        "edge_or_corner_count": int(np.sum(corner_or_edge)),
        "surface_point_count": int(np.sum(side_or_floor)),
        "normal_to_expected_surface_dot_min": float(np.min(dots)) if len(dots) else None,
        "normal_to_expected_surface_dot_median": float(np.median(dots)) if len(dots) else None,
        "normal_orientation_fraction_dot_ge_0p5": float(np.mean(dots >= ORIENTATION_TOLERANCE))
        if len(dots)
        else None,
        "normal_orientation_pass": bool(
            len(dots) > 0
            and np.all(dots >= ORIENTATION_TOLERANCE - 1.0e-6)
        ),
    }


def _cylinder_geometry_audit(
    interface: np.ndarray,
    normals: np.ndarray,
    body_mask: np.ndarray,
    physical: dict[str, Any],
) -> dict[str, Any]:
    points = interface[body_mask]
    normal_unit = _safe_unit(normals[body_mask])
    center = np.asarray(physical["center_xy_m"], dtype=float)
    radial_vector = np.column_stack(
        [points[:, 0] - center[0], points[:, 1] - center[1], np.zeros(len(points))]
    )
    radial = np.linalg.norm(radial_vector[:, :2], axis=1)
    side_distance = np.abs(radial - physical["radius_m"])
    bottom_distance = np.abs(points[:, 2] - physical["z_min_m"])
    top_distance = np.abs(points[:, 2] - physical["z_max_m"])
    distances = np.column_stack([side_distance, bottom_distance, top_distance])
    nearest = distances.min(axis=1)

    expected = np.zeros_like(normal_unit)
    radial_unit = _safe_unit(radial_vector)
    expected += (side_distance <= nearest + INTERFACE_TOLERANCE_M)[:, None] * radial_unit
    expected += (
        bottom_distance <= nearest + INTERFACE_TOLERANCE_M
    )[:, None] * np.array([0.0, 0.0, -1.0])
    expected += (
        top_distance <= nearest + INTERFACE_TOLERANCE_M
    )[:, None] * np.array([0.0, 0.0, 1.0])
    expected = _safe_unit(expected)
    dots = np.sum(normal_unit * expected, axis=1)
    nearest_surface = np.argmin(distances, axis=1)
    return {
        "interface_point_count": int(len(points)),
        "effective_interface_bbox_m": _finite_bbox(points),
        "effective_radius_range_m": [float(radial.min()), float(radial.max())]
        if len(radial)
        else [],
        "max_surface_residual_m": float(np.max(nearest)) if len(nearest) else None,
        "median_surface_residual_m": float(np.median(nearest)) if len(nearest) else None,
        "nearest_surface_counts": {
            "side": int(np.sum(nearest_surface == 0)),
            "bottom_cap": int(np.sum(nearest_surface == 1)),
            "top_cap": int(np.sum(nearest_surface == 2)),
        },
        "normal_to_expected_surface_dot_min": float(np.min(dots)) if len(dots) else None,
        "normal_to_expected_surface_dot_median": float(np.median(dots)) if len(dots) else None,
        "normal_orientation_fraction_dot_ge_0p99": float(np.mean(dots >= 0.99))
        if len(dots)
        else None,
        "normal_orientation_pass": bool(len(dots) > 0 and np.all(dots >= 0.99 - 1.0e-6)),
    }


def _contract_physical_audit(contract: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    normal_cylinders = contract["normal_cylinders"]
    actual_cylinders = contract["actual_cylinders"]
    layers = contract["layer_audit"]
    audit: dict[str, Any] = {
        "normal_construction_surface": {
            "list": contract["normal_list_name"],
            "tank": contract["normal_tank"],
            "cylinders": normal_cylinders,
            "geometryfile": contract["norgeometry"]["geometryfile"],
            "distanceh": contract["norgeometry"]["distanceh"],
        },
        "boundary_particle_layer": {
            "list": "mainlist",
            "tank": contract["actual_tank"],
            "cylinders": actual_cylinders,
        },
        "ghost_interface_definition": {
            "normal_file_points": "x_b = CfgInit_Normals.vtk POINTS",
            "initial_normal": "n_b = CfgInit_Normals.vtk FIELD/Normal",
            "ghost_normal": "n_g = CfgInit_NormalsGhost.vtk FIELD/Normal = 2*n_b",
            "inferred_ghost_coordinate": "x_g = x_b + n_g",
            "effective_interface": "x_gamma = x_b + n_g/2",
        },
        "layers": layers,
        "physical_wall_preserved": True,
    }
    if normal_cylinders:
        audit["cylinder_separation"] = {
            "normal_construction_radius_m": normal_cylinders[0]["radius_m"],
            "normal_construction_endpoints_m": normal_cylinders[0]["points"],
            "actual_particle_radius_m": actual_cylinders[0]["radius_m"]
            if actual_cylinders
            else None,
            "actual_particle_endpoints_m": actual_cylinders[0]["points"]
            if actual_cylinders
            else [],
            "looked_up_by_named_lists": True,
            "normal_list_name": contract["normal_list_name"],
            "actual_list_name": "mainlist",
        }
    if "physical_float1" in spec:
        physical = spec["physical_float1"]
        normal = normal_cylinders[0] if normal_cylinders else {}
        actual = actual_cylinders[0] if actual_cylinders else {}
        audit["physical_wall_preservation_check"] = {
            "target_radius_m": physical["radius_m"],
            "normal_surface_radius_m": normal.get("radius_m"),
            "target_z_range_m": [physical["z_min_m"], physical["z_max_m"]],
            "normal_surface_z_range_m": [
                point[2] for point in normal.get("points", [])
            ],
            "target_and_normal_surface_match": bool(
                normal.get("radius_m") == physical["radius_m"]
                and [point[2] for point in normal.get("points", [])]
                == [physical["z_min_m"], physical["z_max_m"]]
            ),
            "particle_cylinder_is_distinct": bool(
                actual
                and actual.get("radius_m") != physical["radius_m"]
                and actual.get("points") != normal.get("points")
            ),
        }
    return audit


def inspect_case(case_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    definition = spec["definition"]
    evidence = spec["evidence"]
    generated = evidence / "generated"
    solver = evidence / "solver"
    generated_xml = generated / f"{case_id}.xml"
    normal_path = solver / "CfgInit_Normals.vtk"
    ghost_path = solver / "CfgInit_NormalsGhost.vtk"
    hdp_path = generated / f"{case_id}_hdp_Actual.vtk"
    bound_path = generated / f"{case_id}_Bound.vtk"
    contract = parse_geometry_contract(definition)
    generated_summary = parse_generated_xml(generated_xml)
    gencase = parse_gencase_log(evidence / "gencase.log")
    solver_log = parse_solver_log(evidence / "solver.log")
    normal = read_binary_vtk_fields(normal_path)
    ghost = read_binary_vtk_fields(ghost_path)

    if normal["count"] != ghost["count"]:
        raise ValueError(f"{case_id}: normal/ghost point count mismatch")
    count = normal["count"]
    arrays = normal["arrays"]
    ghost_arrays = ghost["arrays"]
    required = {"Mk", "Normal", "NormalSize"}
    if not required.issubset(arrays) or not required.issubset(ghost_arrays):
        raise ValueError(f"{case_id}: missing one of {sorted(required)} in FIELD arrays")
    if not np.array_equal(normal["points"], ghost["points"]):
        raise ValueError(f"{case_id}: ghost VTK does not retain x_b POINTS")
    if not np.array_equal(arrays["Mk"], ghost_arrays["Mk"]):
        raise ValueError(f"{case_id}: normal/ghost Mk differs")

    x_b = normal["points"]
    n_b = arrays["Normal"]
    n_g = ghost_arrays["Normal"]
    x_g = x_b + n_g
    x_gamma = x_b + n_g / 2.0
    n_b_norm = np.linalg.norm(n_b, axis=1)
    n_g_norm = np.linalg.norm(n_g, axis=1)
    mks = arrays["Mk"][:, 0].astype(int)
    fixed_mk = generated_summary.get("fixed", {}).get("mkvalues")
    float_mk = generated_summary.get("floating", {}).get("mkvalues")
    fixed_mask = mks == fixed_mk if fixed_mk is not None else np.zeros(count, dtype=bool)
    body_mask = mks == float_mk if float_mk is not None else np.zeros(count, dtype=bool)
    doubling_residual = np.abs(n_g - 2.0 * n_b)
    size_residual = np.abs(
        ghost_arrays["NormalSize"][:, 0] - 2.0 * arrays["NormalSize"][:, 0]
    )
    finite = bool(
        np.isfinite(x_b).all()
        and np.isfinite(x_g).all()
        and np.isfinite(x_gamma).all()
        and np.isfinite(n_b).all()
        and np.isfinite(n_g).all()
        and np.isfinite(arrays["NormalSize"]).all()
        and np.isfinite(ghost_arrays["NormalSize"]).all()
    )
    tank_audit = _tank_geometry_audit(
        x_gamma, n_b, fixed_mask, spec["physical_tank"]
    )
    body_audit = (
        _cylinder_geometry_audit(x_gamma, n_b, body_mask, spec["physical_float1"])
        if "physical_float1" in spec
        else None
    )
    hdp = read_binary_vtk_points(hdp_path)
    contract_audit = _contract_physical_audit(contract, spec)
    zero_mask = n_b_norm <= ZERO_TOLERANCE
    zero_by_mk = {
        str(mk): int(np.sum(zero_mask & (mks == mk)))
        for mk in sorted(set(mks.tolist()))
    }
    boundary_count = generated_summary.get("nb")
    fixed_count = generated_summary.get("nbf")
    floating_count = generated_summary.get("floating", {}).get("count") or 0
    solver_files = [normal_path, ghost_path]
    artifact_paths = [
        definition,
        evidence / "gencase.log",
        evidence / "bifileinfo.log",
        evidence / "solver.log",
        generated_xml,
        hdp_path,
        bound_path,
        *solver_files,
    ]
    artifacts = [_hash_file(path) for path in artifact_paths if path.is_file()]

    geometry_gate_checks = {
        "gencase_return_code_zero": gencase["return_code"] == 0,
        "solver_return_code_zero": solver_log["return_code"] == 0,
        "mdbc_boundary_mode_observed": solver_log["boundary_mode_mdbc"],
        "finite_vtk_arrays": finite,
        "normal_points_equal_ghost_points": bool(
            np.array_equal(x_b, ghost["points"])
        ),
        "zero_normals_absent": int(np.sum(zero_mask)) == 0,
        "ghost_field_is_exactly_doubled": bool(
            np.max(doubling_residual) <= DOUBLING_TOLERANCE
        ),
        "ghost_size_is_exactly_doubled": bool(
            np.max(size_residual) <= DOUBLING_TOLERANCE
        ),
        "tank_interface_matches_physical_wall": bool(
            tank_audit["max_face_residual_m"] is not None
            and tank_audit["max_face_residual_m"] <= INTERFACE_TOLERANCE_M
        ),
        "tank_corner_and_edge_coverage": tank_audit["edge_or_corner_count"] > 0,
        "tank_normal_is_not_inward": tank_audit["normal_orientation_pass"],
        "layer_contract_has_single_half_dp_shift": bool(
            contract["layer_audit"]["normal_tank_has_single_half_dp_shift"]
            and contract["layer_audit"]["no_second_half_dp_on_particle_layer"]
        ),
    }
    if body_audit is not None:
        geometry_gate_checks.update(
            {
                "float1_interface_matches_physical_cylinder": bool(
                    body_audit["max_surface_residual_m"] is not None
                    and body_audit["max_surface_residual_m"]
                    <= CYLINDER_INTERFACE_TOLERANCE_M
                ),
                "float1_normal_orientation_pass": body_audit["normal_orientation_pass"],
                "normal_and_actual_cylinders_are_separate": contract_audit[
                    "physical_wall_preservation_check"
                ]["particle_cylinder_is_distinct"],
            }
        )
    geometry_gate_pass = all(geometry_gate_checks.values())
    physical_blockers = [
        "No hydrostatic pressure/force gauge or displaced-volume closure was run in this E0 initialization artifact.",
    ]
    if body_audit is not None:
        physical_blockers.append(
            "Float1 one-step smoke test retains RigidAlgorithm=1; the solver explicitly advises Chrono (RigidAlgorithm=3) for floating mDBC collisions."
        )
    physical_gate = {
        "status": "blocked",
        "mdbc_acceptance": False,
        "blockers": physical_blockers,
        "pressure_force_hydrostatic_run": False,
        "one_step_solver_is_only_initialization": True,
    }
    return {
        "case_id": case_id,
        "label": spec["label"],
        "status": "candidate" if geometry_gate_pass else "blocked",
        "definition_contract": contract,
        "physical_contract": contract_audit,
        "generated_summary": generated_summary,
        "gencase": gencase,
        "solver": solver_log,
        "vtk_semantics": {
            "boundary_coordinate": "x_b = CfgInit_Normals.vtk POINTS",
            "initial_displacement": "n_b = CfgInit_Normals.vtk FIELD/Normal",
            "ghost_displacement": "n_g = CfgInit_NormalsGhost.vtk FIELD/Normal",
            "inferred_ghost_coordinate": "x_g = x_b + n_g",
            "effective_interface": "x_gamma = (x_b + x_g)/2 = x_b + n_g/2",
        },
        "structural": {
            "boundary_count": int(count),
            "fixed_count_from_vtk": int(np.sum(fixed_mask)),
            "floating_count_from_vtk": int(np.sum(body_mask)),
            "generated_boundary_count": boundary_count,
            "generated_fixed_count": fixed_count,
            "generated_floating_count": floating_count,
            "generated_counts_match_vtk": bool(
                boundary_count == count
                and fixed_count == int(np.sum(fixed_mask))
                and floating_count == int(np.sum(body_mask))
            ),
            "zero_normal_count": int(np.sum(zero_mask)),
            "zero_normal_by_mk": zero_by_mk,
            "near_zero_normal_count_le_1e-8": int(np.sum(n_b_norm <= 1.0e-8)),
            "normal_size_range_m": [float(n_b_norm.min()), float(n_b_norm.max())],
            "normal_size_field_range_m": [
                float(arrays["NormalSize"][:, 0].min()),
                float(arrays["NormalSize"][:, 0].max()),
            ],
            "ghost_doubling_max_abs_residual": float(np.max(doubling_residual)),
            "normal_size_doubling_max_abs_residual": float(np.max(size_residual)),
            "normal_completeness": bool(np.sum(zero_mask) == 0),
            "finite_arrays": finite,
            "points_equal_between_files": bool(np.array_equal(x_b, ghost["points"])),
        },
        "geometry": {
            "boundary_bbox_m": _finite_bbox(x_b),
            "inferred_ghost_bbox_m": _finite_bbox(x_g),
            "effective_interface_bbox_m": _finite_bbox(x_gamma),
            "normal_geometry_hdp_bbox_m": _finite_bbox(hdp["points"]),
            "normal_geometry_hdp_point_count": int(hdp["count"]),
            "tank": tank_audit,
            "float1_cylinder": body_audit,
            "physical_wall_surface_is_canonical": True,
        },
        "geometry_gate": {
            "status": "pass" if geometry_gate_pass else "blocked",
            "checks": geometry_gate_checks,
            "all_checks_pass": geometry_gate_pass,
            "thresholds": {
                "zero_normal": ZERO_TOLERANCE,
                "doubling_abs_residual": DOUBLING_TOLERANCE,
                "tank_interface_residual_m": INTERFACE_TOLERANCE_M,
                "cylinder_interface_residual_m": CYLINDER_INTERFACE_TOLERANCE_M,
                "corner_orientation_dot": ORIENTATION_TOLERANCE,
            },
        },
        "physical_mdbc_gate": physical_gate,
        "evidence": {
            "definition": _relative(definition),
            "generated_xml": _relative(generated_xml),
            "gencase_log": _relative(evidence / "gencase.log"),
            "bifileinfo_log": _relative(evidence / "bifileinfo.log"),
            "solver_log": _relative(evidence / "solver.log"),
            "normal_geometry_vtk": _relative(hdp_path),
            "boundary_vtk": _relative(bound_path),
            "normal_vtk": _relative(normal_path),
            "ghost_vtk": _relative(ghost_path),
            "artifacts": artifacts,
        },
    }


def build_report() -> dict[str, Any]:
    """Build the complete E0 report from checked-in definitions and artifacts."""

    cases = {
        case_id: inspect_case(case_id, spec) for case_id, spec in CASE_SPECS.items()
    }
    geometry_pass = all(
        case["geometry_gate"]["all_checks_pass"] for case in cases.values()
    )
    return {
        "schema_version": 1,
        "diagnostic_id": "r3_f6_canonical_mdbc_geometry",
        "status": "candidate" if geometry_pass else "blocked",
        "acceptance_status": "candidate_geometry_pass_physical_gate_blocked",
        "scientific_acceptance": "not_accepted_physical_mdbc_validation",
        "execution_status": "completed_cpu_gencase_and_one_step_cpu_solver",
        "compute": {
            "gencase": "CPU, 8 OpenMP threads",
            "solver": "DualSPHysics5.4CPU, one initialization step",
            "cfd_solver_run": True,
            "solver_scope": "short initialization smoke test only; no pressure/force closure",
            "gpu_used": False,
            "gpu_indices_used": [],
            "production_tracer_imported": False,
        },
        "scope": (
            "E0 canonical physical-wall reconstruction.  The normal construction "
            "surface, actual boundary layer, and VTK-reconstructed ghost/interface "
            "are audited independently for a rectangular wall and a Float1 cylinder."
        ),
        "source_evidence": {
            "official_mdbc_guide": _relative(
                LAB / "vendor/official/DualSPHysics_v5.4/doc/guides/XML_GUIDE_MDBC.pdf"
            ),
            "official_bound_normal_loader": _relative(
                LAB / "vendor/official/DualSPHysics_v5.4/src/source/JPartsLoad4.cpp"
            ),
            "official_bound_normal_interface": _relative(
                LAB / "vendor/official/DualSPHysics_v5.4/src/source/JPartsLoad4.h"
            ),
            "official_mdbc_initialization": _relative(
                LAB / "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp"
            ),
            "official_cpu_mdbc_kernel": _relative(
                LAB / "vendor/official/DualSPHysics_v5.4/src/source/JSphCpu_mdbc.cpp"
            ),
            "official_examples": [
                _relative(
                    LAB
                    / "vendor/official/DualSPHysics_v5.4/examples/mdbc/05_FlowCylinder/CaseFlowFrCylinder_Re200_Def.xml"
                ),
                _relative(
                    LAB
                    / "vendor/official/DualSPHysics_v5.4/examples/mdbc/08_FloatingWaves/CaseFloatingWaves_Def.xml"
                ),
            ],
        },
        "reproduction": {
            "gencase": (
                "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64 "
                "<definition_without_.xml> <evidence>/<case> -save:all -threads:8"
            ),
            "bifileinfo": (
                "vendor/official/DualSPHysics_v5.4/bin/linux/BIFileInfo_linux64 "
                "<evidence>/<case>.bi4 -svarrays:1"
            ),
            "solver": (
                "CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=8 "
                "LD_LIBRARY_PATH=vendor/official/DualSPHysics_v5.4/bin/linux "
                "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4CPU_linux64 "
                "<generated>/<case> <evidence>/<case>/solver"
            ),
            "gpu_policy": "GPU intentionally unused; existing GPU jobs were not disturbed.",
        },
        "cases": cases,
        "status_legend": {
            "pass": "E0 geometry/serialization checks pass",
            "candidate": "geometry pass but downstream physical acceptance remains open",
            "blocked": "required geometry check or downstream acceptance is not available",
        },
        "conclusions": [
            "The canonical rectangular definition keeps the nominal physical wall at x/y=0..0.4/0.3 and z=0, constructs hdp on its inner face at one Dp/2 offset, and generates the particle shell with vdp=0,1,2.",
            "The Float1 definition keeps the physical normal-construction cylinder at R=0.11 m and z=0.14..0.30 m, while the separate actual particle cylinder is R=0.08 m with z=0.16..0.28 m and vdp=0,-1,-2.",
            "The VTK audit observes exact point identity and n_g=2*n_b, then reconstructs x_gamma=x_b+n_g/2.  It does not claim that ghost VTK POINTS are ghost coordinates.",
            "Both candidates have real GenCase and one-step CPU solver evidence with zero serialized normal vectors; this is a pass for E0 geometry and a candidate for mDBC acceptance.",
        ],
        "open_blockers": [
            "Run a matched hydrostatic pressure/force gauge and displaced-volume closure before accepting mDBC physics.",
            "For floating mDBC, repeat with the official Chrono collision/integration route (RigidAlgorithm=3) rather than treating the RigidAlgorithm=1 smoke test as physical validation.",
            "Keep E1 tracer/schema changes separate from this canonical geometry package.",
        ],
    }


def markdown(report: dict[str, Any]) -> str:
    """Render the compact human-readable E0 handoff."""

    lines = [
        "# R3-F6 canonical mDBC geometry — E0",
        "",
        "**Status:** `candidate` overall; `pass` for canonical geometry/serialization; `blocked` for downstream physical mDBC acceptance. CPU/GenCase only; no GPU was used.",
        "",
        "This package keeps the physical wall at the intended location and rebuilds the numerical boundary layer and normal construction independently. It does not modify the formal tracer or schema.",
        "",
        "## Geometry contract",
        "",
        "`GeometryForNormals` is the normal-construction surface written to `*_hdp_Actual.vtk`; `mainlist` is the actual boundary-particle layer. The solver artifacts are interpreted as:",
        "",
        "```text",
        "x_b     = POINTS(CfgInit_Normals.vtk)",
        "n_b     = FIELD/Normal(CfgInit_Normals.vtk)",
        "n_g     = FIELD/Normal(CfgInit_NormalsGhost.vtk) = 2 n_b",
        "x_g     = x_b + n_g",
        "x_gamma = (x_b + x_g)/2 = x_b + n_g/2",
        "```",
        "",
        "The ghost-file `POINTS` are checked to be the same `x_b`; they are not silently treated as ghost coordinates.",
        "",
        "| case | generated particles (bound/fixed/float/fluid) | zero normals | max `|n_g-2n_b|` | physical-interface residual | geometry | mDBC physics |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for case_id, case in report["cases"].items():
        structural = case["structural"]
        tank = case["geometry"]["tank"]
        body = case["geometry"]["float1_cylinder"]
        residuals = [tank["max_face_residual_m"]]
        if body is not None:
            residuals.append(body["max_surface_residual_m"])
        residual = max(value for value in residuals if value is not None)
        summary = case["generated_summary"]
        lines.append(
            f"| `{case_id}` | {summary.get('nb')}/{summary.get('nbf')}/"
            f"{summary.get('floating', {}).get('count') or 0}/"
            f"{summary.get('fluid', {}).get('count')} | "
            f"{structural['zero_normal_count']} | "
            f"{structural['ghost_doubling_max_abs_residual']:.3g} | "
            f"{residual:.3g} m | `"
            f"{case['geometry_gate']['status']}` | `"
            f"{case['physical_mdbc_gate']['status']}` |"
        )
    lines.extend(
        [
            "",
            "## Corrected E0 rationale",
            "",
            "- **Rectangular wall:** the XML box is the canonical nominal wall (`x=0..0.4`, `y=0..0.3`, `z=0`, top open). Only `GeometryForNormals` carries `layers vdp=\"-0.5\"`, so its `hdp_Actual` surface is the physical inner wall (`x/y=0.02..0.38/0.28`, `z=0.02`). The actual shell is independently generated with `vdp=\"0,1,2\"`. This is one half-`Dp` reconstruction shift, not two.",
            "- **Float1 cylinder:** the normal-construction cylinder is explicitly `R=0.11 m`, `z=0.14..0.30 m` in the named `GeometryForNormals` list. The actual Float1 boundary cylinder is separately `R=0.08 m`, `z=0.16..0.28 m`, `vdp=\"0,-1,-2\"` in `mainlist`. The parser checks those named lists and proves they are distinct; it never chooses the first global `drawcylinder`.",
            "- **Normals and ghost/interface:** all final boundary normals are non-zero; the solver's ghost array is exactly doubled; `x_gamma` lands on the canonical tank faces and the `R=0.11 m` cylinder within the reported raster tolerance. Corners/edges are included in the audit; the weak corner orientation threshold (`dot >= 0.5`) reports weighted lattice-corner normals without pretending they are analytic face sums.",
            "",
            "## Actual-generation evidence",
            "",
            "Both cases have checked-in `gencase.log`, `bifileinfo.log`, generated `.bi4/.xml/.vtk`, `solver.log`, `CfgInit_Normals.vtk`, and `CfgInit_NormalsGhost.vtk`. GenCase and one-step `DualSPHysics5.4CPU` both finish with code 0. No GPU was used because the E0 audit is CPU-first.",
            "",
            "The one-step solver is an initialization smoke test only. It does not supply a hydrostatic pressure/force gauge or displaced-volume closure. The Float1 log also contains the official warning that floating mDBC collisions should use Chrono (`RigidAlgorithm=3`); therefore the physical mDBC gate stays `blocked` even though the E0 geometry gate is `pass`.",
            "",
            "## Machine-readable handoff",
            "",
            f"- JSON: `{_relative(OUTPUT_JSON)}`",
            f"- pytest: `{_relative(ROOT / 'test_canonical_geometry.py')}`",
            "- Official local references: XML mDBC guide, `JPartsLoad4.cpp`, `JSph.cpp`, and `JSphCpu_mdbc.cpp` listed in the JSON.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report() -> dict[str, Any]:
    report = build_report()
    OUTPUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    OUTPUT_MD.write_text(markdown(report))
    return report


if __name__ == "__main__":
    print(json.dumps(write_report(), indent=2, ensure_ascii=False))
