#!/usr/bin/env python3
"""Audit native F1 GenCase normal support and physical face orientation.

This is a bounded, read-only CPU audit of a fresh GenCase output prefix.  It
checks actual typed boundary counts, fluid count and mass parameters, finite
normal arrays, positive ``NormalSize``/usable vectors on every fixed row, and
maps residual rows to the ten finite faces declared by the F1 definition.  It
also checks vector orientation against the physical face directions.  No
normal is inferred, renormalized, or copied from a neighboring layer.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import resource
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


SCHEMA = "ds02.f1.finite-center.initial-normal-support-audit.v1"
NORMAL_SIZE_TOLERANCE_M = 1.0e-8
USABLE_NORMAL_TOLERANCE_M = 1.0e-8
FACE_TOLERANCE_M = 1.0e-8
ORIENTATION_EPSILON_M = 1.0e-8

VTK_TYPES: dict[str, tuple[str, int]] = {
    "char": (">i1", 1),
    "signed_char": (">i1", 1),
    "unsigned_char": (">u1", 1),
    "short": (">i2", 2),
    "unsigned_short": (">u2", 2),
    "int": (">i4", 4),
    "unsigned_int": (">u4", 4),
    "long": (">i8", 8),
    "unsigned_long": (">u8", 8),
    "float": (">f4", 4),
    "double": (">f8", 8),
}

# Coordinates are the physical planes from GeometryForNormals, not extrema
# of the generated point cloud.  The directions are the expected displacement
# toward the declared fluid side: into the tank for outer walls, below/above
# the separator for its y/z faces, and toward increasing x for the separator
# channel direction.  A direction is checked only on usable interior rows;
# shared edges may have a zero dot product because their vector is composite.
FACE_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "outer_x_low", "population": "outer_wall", "mk": 10, "axis": 0, "target": 0.0, "tangent": (1, 2), "low": (-0.005, -0.005), "high": (1.005, 1.0), "direction": (1.0, 0.0, 0.0), "basis": "into_tank"},
    {"name": "outer_x_high", "population": "outer_wall", "mk": 10, "axis": 0, "target": 3.23, "tangent": (1, 2), "low": (-0.005, -0.005), "high": (1.005, 1.0), "direction": (-1.0, 0.0, 0.0), "basis": "into_tank"},
    {"name": "outer_y_low", "population": "outer_wall", "mk": 10, "axis": 1, "target": -0.005, "tangent": (0, 2), "low": (0.0, -0.005), "high": (3.23, 1.0), "direction": (0.0, 1.0, 0.0), "basis": "into_tank"},
    {"name": "outer_y_high", "population": "outer_wall", "mk": 10, "axis": 1, "target": 1.005, "tangent": (0, 2), "low": (0.0, -0.005), "high": (3.23, 1.0), "direction": (0.0, -1.0, 0.0), "basis": "into_tank"},
    {"name": "outer_z_low", "population": "outer_wall", "mk": 10, "axis": 2, "target": -0.005, "tangent": (0, 1), "low": (0.0, -0.005), "high": (3.23, 1.005), "direction": (0.0, 0.0, 1.0), "basis": "into_tank"},
    {"name": "separator_x_low", "population": "separator", "mk": 11, "axis": 0, "target": 1.25, "tangent": (1, 2), "low": (0.34, 0.0), "high": (0.4, 0.7), "direction": (1.0, 0.0, 0.0), "basis": "declared_channel_direction; no directly adjacent initial fluid cell on this face"},
    {"name": "separator_x_high", "population": "separator", "mk": 11, "axis": 0, "target": 2.05, "tangent": (1, 2), "low": (0.34, 0.0), "high": (0.4, 0.7), "direction": (1.0, 0.0, 0.0), "basis": "toward_initial_fluid_side_x_positive"},
    {"name": "separator_y_low", "population": "separator", "mk": 11, "axis": 1, "target": 0.34, "tangent": (0, 2), "low": (1.25, 0.0), "high": (2.05, 0.7), "direction": (0.0, -1.0, 0.0), "basis": "toward_initial_fluid_side_y_negative"},
    {"name": "separator_y_high", "population": "separator", "mk": 11, "axis": 1, "target": 0.4, "tangent": (0, 2), "low": (1.25, 0.0), "high": (2.05, 0.7), "direction": (0.0, 1.0, 0.0), "basis": "toward_initial_fluid_side_y_positive"},
    {"name": "separator_z_high", "population": "separator", "mk": 11, "axis": 2, "target": 0.7, "tangent": (0, 1), "low": (1.25, 0.34), "high": (2.05, 0.4), "direction": (0.0, 0.0, -1.0), "basis": "toward_initial_fluid_side_z_negative"},
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rusage() -> dict[str, float]:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "self_user_seconds": float(self_usage.ru_utime),
        "self_system_seconds": float(self_usage.ru_stime),
        "children_user_seconds": float(child_usage.ru_utime),
        "children_system_seconds": float(child_usage.ru_stime),
        "combined_user_seconds": float(self_usage.ru_utime + child_usage.ru_utime),
        "combined_system_seconds": float(self_usage.ru_stime + child_usage.ru_stime),
        "max_rss_kib_self": float(self_usage.ru_maxrss),
        "max_rss_kib_children": float(child_usage.ru_maxrss),
    }


def _skip_newline(raw: bytes, offset: int) -> int:
    if raw[offset : offset + 2] == b"\r\n":
        return offset + 2
    if raw[offset : offset + 1] == b"\n":
        return offset + 1
    return offset


def _line(raw: bytes, offset: int, path: Path) -> tuple[str, int]:
    end = raw.find(b"\n", offset)
    if end < 0:
        raise ValueError(f"{path}: unterminated VTK header")
    line = raw[offset:end].rstrip(b"\r")
    try:
        return line.decode("ascii"), end + 1
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: non-ASCII VTK header") from exc


def _payload(raw: bytes, offset: int, count: int, kind: str, path: Path) -> tuple[np.ndarray, int]:
    if kind not in VTK_TYPES:
        raise ValueError(f"{path}: unsupported VTK type {kind!r}")
    dtype_name, width = VTK_TYPES[kind]
    stop = offset + count * width
    if stop > len(raw):
        raise ValueError(f"{path}: truncated {kind} payload")
    return np.frombuffer(raw, dtype=np.dtype(dtype_name), count=count, offset=offset).copy(), _skip_newline(raw, stop)


def read_binary_vtk(path: Path) -> dict[str, Any]:
    """Read the strict legacy binary VTK subset used by GenCase Bound.vtk."""

    raw = path.read_bytes()
    offset = 0
    first, offset = _line(raw, offset, path)
    _description, offset = _line(raw, offset, path)
    encoding, offset = _line(raw, offset, path)
    dataset, offset = _line(raw, offset, path)
    if not first.startswith("# vtk DataFile") or encoding.strip().upper() != "BINARY" or dataset.strip().upper() != "DATASET POLYDATA":
        raise ValueError(f"{path}: unsupported VTK preamble")
    point_header, offset = _line(raw, offset, path)
    match = re.fullmatch(r"POINTS\s+(\d+)\s+(\S+)", point_header)
    if match is None:
        raise ValueError(f"{path}: malformed POINTS header")
    point_count = int(match.group(1))
    point_kind = match.group(2)
    point_values, offset = _payload(raw, offset, point_count * 3, point_kind, path)
    points = point_values.reshape(point_count, 3).astype(np.float64)
    point_data: dict[str, np.ndarray] = {}
    field_data: dict[str, np.ndarray] = {}
    data_count: int | None = None
    while True:
        offset = _skip_newline(raw, offset)
        if offset >= len(raw):
            break
        header, offset = _line(raw, offset, path)
        fields = header.split()
        if not fields:
            continue
        keyword = fields[0].upper()
        if keyword == "POINT_DATA":
            if len(fields) != 2:
                raise ValueError(f"{path}: malformed POINT_DATA")
            data_count = int(fields[1])
            if data_count != point_count:
                raise ValueError(f"{path}: POINT_DATA count differs from POINTS")
            continue
        if keyword in {"VERTICES", "POLYGONS", "LINES", "TRIANGLE_STRIPS"}:
            if len(fields) != 3:
                raise ValueError(f"{path}: malformed {keyword} section")
            # GenCase Bound.vtk emits one vertex cell per boundary point before
            # POINT_DATA.  The audit needs no cell topology, but it must consume
            # the binary payload exactly so subsequent typed arrays remain aligned.
            _cell_count = int(fields[1])
            total_values = int(fields[2])
            _ignored_cells, offset = _payload(raw, offset, total_values, "int", path)
            continue
        if keyword == "FIELD":
            if len(fields) != 3:
                raise ValueError(f"{path}: malformed FIELD section")
            field_count = int(fields[2])
            for _ in range(field_count):
                field_header, offset = _line(raw, offset, path)
                field_fields = field_header.split()
                if len(field_fields) != 4:
                    raise ValueError(f"{path}: malformed FIELD array header {field_header!r}")
                field_name, field_components, field_values, field_kind = field_fields
                field_components_i = int(field_components)
                field_values_i = int(field_values)
                field_payload, offset = _payload(
                    raw,
                    offset,
                    field_components_i * field_values_i,
                    field_kind,
                    path,
                )
                # GenCase writes its typed boundary arrays in a VTK
                # ``FIELD FieldData`` block immediately after POINT_DATA.
                # Although the block is named FieldData, these arrays are
                # point-aligned when their count equals POINT_DATA.  Preserve
                # that native association instead of discarding it or
                # manufacturing values; unrelated arrays remain field data.
                shaped = field_payload.reshape(field_values_i, field_components_i)
                target = point_data if data_count is not None and field_values_i == data_count else field_data
                target[field_name] = shaped[:, 0] if field_components_i == 1 else shaped
            continue
        if keyword == "SCALARS":
            if data_count is None or len(fields) < 3:
                raise ValueError(f"{path}: malformed SCALARS section")
            name, kind = fields[1], fields[2]
            components = int(fields[3]) if len(fields) >= 4 else 1
            lookup, offset = _line(raw, offset, path)
            if not lookup.upper().startswith("LOOKUP_TABLE"):
                raise ValueError(f"{path}: missing LOOKUP_TABLE for {name}")
            values, offset = _payload(raw, offset, data_count * components, kind, path)
            shaped = values.reshape(data_count, components)
            point_data[name] = shaped[:, 0] if components == 1 else shaped
            continue
        # GenCase writes several point arrays in its compact four-token form
        # without the VTK SCALARS keyword (for example ``Normal 3 N float``).
        # Consume that native form explicitly instead of searching binary data
        # for textual headers or manufacturing missing arrays.
        if len(fields) == 4 and fields[1].isdigit() and fields[2].isdigit() and fields[3] in VTK_TYPES:
            if data_count is None:
                raise ValueError(f"{path}: compact array appears before POINT_DATA")
            name = fields[0]
            components = int(fields[1])
            count = int(fields[2])
            if count != data_count:
                raise ValueError(f"{path}: compact array {name} count differs from POINT_DATA")
            values, offset = _payload(raw, offset, count * components, fields[3], path)
            shaped = values.reshape(count, components)
            point_data[name] = shaped[:, 0] if components == 1 else shaped
            continue
        if keyword == "VECTORS":
            if data_count is None or len(fields) != 3:
                raise ValueError(f"{path}: malformed VECTORS section")
            name, kind = fields[1], fields[2]
            values, offset = _payload(raw, offset, data_count * 3, kind, path)
            point_data[name] = values.reshape(data_count, 3)
            continue
        # Bound.vtk has no cells or additional sections.  Refuse an unknown
        # section rather than guessing its payload offset.
        raise ValueError(f"{path}: unsupported VTK section {header!r}")
    return {"points": points, "point_data": point_data, "field_data": field_data, "sha256": sha256(path), "file_size_bytes": len(raw)}


def _point_count(path: Path) -> int:
    raw = path.read_bytes()[:512]
    match = re.search(rb"POINTS\s+(\d+)\s+\S+", raw)
    if match is None:
        raise ValueError(f"{path}: POINTS header not found")
    return int(match.group(1))


def _fixed_population_xml(generated_xml: Path) -> dict[int, int]:
    root = ET.parse(generated_xml).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles")
    rows = {}
    for element in particles.findall("fixed"):
        rows[int(element.attrib["mk"])] = int(element.attrib["count"])
    if not rows:
        raise ValueError("generated XML has no fixed records")
    return rows


def _xml_summary(generated_xml: Path) -> dict[str, Any]:
    root = ET.parse(generated_xml).getroot()
    particles = root.find(".//particles")
    constants = root.find(".//constants")
    data2d = root.find(".//constants/data2d")
    if particles is None or constants is None or data2d is None:
        raise ValueError("generated XML lacks particles/constants/data2d")
    fluid = particles.find("fluid")
    if fluid is None:
        raise ValueError("generated XML has no fluid record")
    mass = constants.find("massfluid")
    dp = constants.find("dp")
    h = constants.find("h")
    normal = root.find(".//normals/norgeometry")
    distanceh = normal.find("distanceh") if normal is not None else None
    svshapes = normal.find("svshapes") if normal is not None else None
    return {
        "dimension": 2 if data2d.attrib.get("value", "false").lower() == "true" else 3,
        "total_particles": int(particles.attrib["np"]),
        "fixed_particles": int(particles.attrib["nb"]),
        "fluid_particles": int(fluid.attrib["count"]),
        "fixed_counts": _fixed_population_xml(generated_xml),
        "massfluid_kg": float(mass.attrib["value"]) if mass is not None else None,
        "expected_fluid_mass_kg": float(mass.attrib["value"]) * int(fluid.attrib["count"]) if mass is not None else None,
        "dp_m": float(dp.attrib["value"]) if dp is not None else None,
        "h_m": float(h.attrib["value"]) if h is not None else None,
        "distanceh": distanceh.attrib.get("v") if distanceh is not None else None,
        "svshapes": svshapes.attrib.get("v") if svshapes is not None else None,
    }


def _face_mask(points: np.ndarray, mk: np.ndarray, spec: dict[str, Any], tolerance: float) -> np.ndarray:
    axis = int(spec["axis"])
    mask = (mk == int(spec["mk"])) & np.isfinite(points).all(axis=1)
    mask &= np.abs(points[:, axis] - float(spec["target"])) <= tolerance
    for index, tangent in enumerate(spec["tangent"]):
        mask &= points[:, tangent] >= float(spec["low"][index]) - tolerance
        mask &= points[:, tangent] <= float(spec["high"][index]) + tolerance
    return mask


def _face_interior_mask(points: np.ndarray, spec: dict[str, Any], tolerance: float) -> np.ndarray:
    mask = np.isfinite(points).all(axis=1)
    mask &= np.abs(points[:, int(spec["axis"])] - float(spec["target"])) <= tolerance
    # Exclude only the physical half-dp edge strip for orientation.  Composite
    # corner vectors are still reported by the full face mask.
    interior_margin = 0.005 + FACE_TOLERANCE_M
    for index, tangent in enumerate(spec["tangent"]):
        mask &= points[:, tangent] >= float(spec["low"][index]) + interior_margin
        mask &= points[:, tangent] <= float(spec["high"][index]) - interior_margin
    return mask


def _layers(values: np.ndarray) -> list[dict[str, Any]]:
    if not len(values):
        return []
    unique, counts = np.unique(np.round(values.astype(np.float64), 8), return_counts=True)
    return [{"coordinate_m": float(value), "count": int(count)} for value, count in zip(unique, counts)]


def _orientation_summary(normals: np.ndarray, mask: np.ndarray, interior: np.ndarray, direction: tuple[float, float, float]) -> dict[str, Any]:
    usable = mask & interior
    selected = normals[usable]
    if not len(selected):
        return {
            "interior_usable_count": 0,
            "positive_dot_count": 0,
            "zero_dot_count": 0,
            "negative_dot_count": 0,
            "aligned_fraction": None,
            "dot_min_m": None,
            "dot_max_m": None,
            "orientation_pass": False,
            "reason": "no usable interior normals on this physical face",
        }
    dots = selected.astype(np.float64) @ np.asarray(direction, dtype=np.float64)
    positive = dots > ORIENTATION_EPSILON_M
    negative = dots < -ORIENTATION_EPSILON_M
    zero = ~(positive | negative)
    aligned_fraction = float(positive.sum() / len(dots))
    return {
        "interior_usable_count": int(len(dots)),
        "positive_dot_count": int(positive.sum()),
        "zero_dot_count": int(zero.sum()),
        "negative_dot_count": int(negative.sum()),
        "aligned_fraction": aligned_fraction,
        "dot_min_m": float(dots.min()),
        "dot_max_m": float(dots.max()),
        "orientation_pass": bool(not negative.any() and aligned_fraction >= 0.95),
        "reason": "direction checked against physical face basis; edge/composite vectors may have zero dot",
    }


def _run_out_summary(run_out: Path) -> dict[str, Any]:
    content = run_out.read_text(errors="replace")
    zero_lines = [line.strip() for line in content.splitlines() if "Final zero normals:" in line]
    warning_lines = [line.strip() for line in content.splitlines() if "without normal data" in line.lower()]
    nonzero_lines = [line.strip() for line in content.splitlines() if "Non-zero particle normals:" in line]
    return {
        "path": str(run_out),
        "sha256": sha256(run_out),
        "zero_normal_lines": zero_lines,
        "warning_lines": warning_lines,
        "nonzero_normal_lines": nonzero_lines,
        "zero_normal_warning_count": len(warning_lines),
        "hash_bound": True,
    }


def audit(
    *,
    generated_root: Path,
    generated_xml: Path,
    generated_bi4: Path,
    bound_vtk: Path,
    fluid_vtk: Path,
    all_vtk: Path,
    hdp_vtk: Path,
    gencase_out: Path,
    output: Path,
    expected_fluid_mass_kg: float = 616.0,
) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    before = _rusage()
    source_paths = [generated_xml, generated_bi4, bound_vtk, fluid_vtk, all_vtk, hdp_vtk, gencase_out]
    source_before = {str(path): sha256(path) for path in source_paths}
    xml = _xml_summary(generated_xml)
    bound = read_binary_vtk(bound_vtk)
    point_data = bound["point_data"]
    required = {"Mk", "Type", "Normal", "NormalSize"}
    missing = required - set(point_data)
    if missing:
        raise ValueError(f"Bound.vtk missing required arrays: {sorted(missing)}")
    points = bound["points"]
    mk = np.asarray(point_data["Mk"])
    types = np.asarray(point_data["Type"])
    normals = np.asarray(point_data["Normal"], dtype=np.float64)
    normal_size = np.asarray(point_data["NormalSize"], dtype=np.float64)
    if normals.shape != (len(points), 3) or normal_size.shape != (len(points),):
        raise ValueError("Bound normal arrays have unexpected shapes")
    if len(mk) != len(points) or len(types) != len(points):
        raise ValueError("Bound typed arrays do not match points")
    fixed = np.isin(mk, [10, 11])
    if not bool(fixed.any()):
        raise ValueError("Bound.vtk has no expected F1 fixed Mk values")
    norms = np.linalg.norm(normals, axis=1)
    normal_size_good = np.isfinite(normal_size) & (normal_size > NORMAL_SIZE_TOLERANCE_M)
    normal_good = np.isfinite(normals).all(axis=1) & (norms > USABLE_NORMAL_TOLERANCE_M)
    usable = normal_size_good & normal_good
    fixed_missing_size = fixed & ~normal_size_good
    fixed_missing_usable = fixed & ~normal_good
    xml_counts = {int(key): int(value) for key, value in xml["fixed_counts"].items()}
    vtk_counts = {int(value): int((mk == value).sum()) for value in np.unique(mk)}
    face_rows: list[dict[str, Any]] = []
    membership: Counter[tuple[str, ...]] = Counter()
    face_masks: dict[str, np.ndarray] = {}
    face_tolerance = float((xml["dp_m"] or 0.01) / 2.0 + FACE_TOLERANCE_M)
    for spec in FACE_SPECS:
        mask = _face_mask(points, mk, spec, face_tolerance)
        face_masks[str(spec["name"])] = mask
    for index in np.flatnonzero(fixed_missing_size | fixed_missing_usable):
        names = tuple(name for name, mask in face_masks.items() if bool(mask[index]))
        membership[names] += 1
    for spec in FACE_SPECS:
        name = str(spec["name"])
        mask = face_masks[name]
        interior = _face_interior_mask(points, spec, face_tolerance)
        residual = mask & (fixed_missing_size | fixed_missing_usable)
        size_zero = mask & ~normal_size_good
        usable_zero = mask & ~normal_good
        orientation = _orientation_summary(normals, mask & fixed, interior, tuple(spec["direction"]))
        face_rows.append({
            "name": name,
            "population": spec["population"],
            "mk": int(spec["mk"]),
            "physical_plane_m": float(spec["target"]),
            "expected_direction": list(spec["direction"]),
            "orientation_basis": spec["basis"],
            "candidate_tolerance_m": face_tolerance,
            "candidate_point_count": int(mask.sum()),
            "candidate_normal_size_zero_count": int(size_zero.sum()),
            "candidate_usable_normal_zero_count": int(usable_zero.sum()),
            "residual_position_bounds_m": (
                [residual_points.min(axis=0).astype(float).tolist(), residual_points.max(axis=0).astype(float).tolist()]
                if len(residual_points := points[residual]) else None
            ),
            "residual_coordinate_layers_m": _layers(points[residual, int(spec["axis"])]),
            "orientation": orientation,
            "face_hard_gate": bool(mask.any() and not residual.any() and orientation["orientation_pass"]),
        })
    source_after = {str(path): sha256(path) for path in source_paths}
    if source_before != source_after:
        raise AssertionError("a hashed GenCase input changed during read-only audit")
    all_fixed = int(fixed.sum())
    type_counts = {str(int(value)): int((types == value).sum()) for value in np.unique(types)}
    report = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": generated_xml.stem,
        "physical_case_id": "F1_DUAL_FINITE_CENTER_QUADRATURE",
        "claim_boundary": "Native GenCase normal hard-gate evidence only; no solver acceptance, Q-N, or production qualification.",
        "source_paths": {"generated_root": str(generated_root), "generated_xml": str(generated_xml), "generated_bi4": str(generated_bi4), "bound_vtk": str(bound_vtk), "fluid_vtk": str(fluid_vtk), "all_vtk": str(all_vtk), "hdp_vtk": str(hdp_vtk), "gencase_out": str(gencase_out)},
        "source_hashes_before": source_before,
        "source_hashes_after": source_after,
        "input_bytes_unchanged": source_before == source_after,
        "generated_xml": xml,
        "vtk_headers": {"bound_point_count": int(len(points)), "fluid_point_count": _point_count(fluid_vtk), "all_point_count": _point_count(all_vtk), "hdp_point_count": _point_count(hdp_vtk)},
        "typed_native_counts": {
            "fixed_rows": all_fixed,
            "mk_counts": {str(key): value for key, value in sorted(vtk_counts.items())},
            "type_counts": type_counts,
            "xml_fixed_counts": {str(key): value for key, value in sorted(xml_counts.items())},
            "xml_vtk_fixed_counts_match": all(vtk_counts.get(key) == value for key, value in xml_counts.items()),
        },
        "native_arrays": {
            "points_finite": bool(np.isfinite(points).all()),
            "normal_finite": bool(np.isfinite(normals).all()),
            "normal_size_finite": bool(np.isfinite(normal_size).all()),
            "normal_size_threshold_m": NORMAL_SIZE_TOLERANCE_M,
            "usable_normal_threshold_m": USABLE_NORMAL_TOLERANCE_M,
            "fixed_normal_size_zero_count": int(fixed_missing_size.sum()),
            "fixed_usable_normal_zero_count": int(fixed_missing_usable.sum()),
            "fixed_normal_size_positive_count": int((fixed & normal_size_good).sum()),
            "fixed_usable_normal_count": int((fixed & normal_good).sum()),
            "all_fixed_rows_pass_size": bool(not fixed_missing_size.any()),
            "all_fixed_rows_pass_usable_vector": bool(not fixed_missing_usable.any()),
            "normal_magnitude_min_fixed_m": float(norms[fixed].min()) if fixed.any() else None,
            "normal_magnitude_max_fixed_m": float(norms[fixed].max()) if fixed.any() else None,
        },
        "finite_face_attribution": {
            "faces": face_rows,
            "residual_membership_histogram": [{"faces": list(names), "count": int(count)} for names, count in sorted(membership.items(), key=lambda item: (-item[1], item[0]))],
            "all_ten_faces_nonempty": bool(all(row["candidate_point_count"] > 0 for row in face_rows)),
            "all_ten_faces_hard_pass": bool(all(row["face_hard_gate"] for row in face_rows)),
        },
        "gencase_log": _run_out_summary(gencase_out),
        "checks": {
            "dimension_is_3d": xml["dimension"] == 3,
            "expected_total_particles": xml["total_particles"] == 1011911,
            "expected_fluid_particles": xml["fluid_particles"] == 616000 and _point_count(fluid_vtk) == 616000,
            "expected_fixed_particles": xml["fixed_particles"] == 395911 and len(points) == 395911,
            "expected_typed_fixed_counts": xml_counts == {10: 361104, 11: 34807} and all(vtk_counts.get(k) == v for k, v in {10: 361104, 11: 34807}.items()),
            "expected_fluid_mass_kg": xml["expected_fluid_mass_kg"] == float(expected_fluid_mass_kg),
            "arrays_finite": bool(np.isfinite(points).all() and np.isfinite(normals).all() and np.isfinite(normal_size).all()),
            "all_fixed_normal_size_positive": bool(not fixed_missing_size.any()),
            "all_fixed_usable_normals_nonzero": bool(not fixed_missing_usable.any()),
            "all_finite_faces_oriented": bool(all(row["orientation"]["orientation_pass"] for row in face_rows)),
            "all_finite_faces_hard_pass": bool(all(row["face_hard_gate"] for row in face_rows)),
            "gencase_warning_absent": len(_run_out_summary(gencase_out)["warning_lines"]) == 0,
            "source_inputs_unchanged": source_before == source_after,
        },
        "hard_gate_pass": bool(
            xml["dimension"] == 3
            and xml["total_particles"] == 1011911
            and xml["fluid_particles"] == 616000
            and xml["fixed_particles"] == 395911
            and xml_counts == {10: 361104, 11: 34807}
            and all(vtk_counts.get(k) == v for k, v in {10: 361104, 11: 34807}.items())
            and xml["expected_fluid_mass_kg"] == float(expected_fluid_mass_kg)
            and not fixed_missing_size.any()
            and not fixed_missing_usable.any()
            and all(row["face_hard_gate"] for row in face_rows)
            and not _run_out_summary(gencase_out)["warning_lines"]
        ),
        "resource_usage": {"before": before, "after": _rusage()},
        "limitations": [
            "GenCase normal support is an initial native representation gate; it does not establish solver-time lifecycle, observables, numerical convergence, Q-N, or production eligibility.",
            "Face rows are attributed from declared physical planes with a half-dp tolerance; vectors at shared edges are reported separately and are not inferred from adjacent faces.",
            "The expected direction for separator x_low is a declared channel-direction check even though the initial fluid reservoir has no directly adjacent x_low cell; this limitation remains visible in the basis field.",
        ],
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-root", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--generated-bi4", type=Path, required=True)
    parser.add_argument("--bound-vtk", type=Path, required=True)
    parser.add_argument("--fluid-vtk", type=Path, required=True)
    parser.add_argument("--all-vtk", type=Path, required=True)
    parser.add_argument("--hdp-vtk", type=Path, required=True)
    parser.add_argument("--gencase-out", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(
        generated_root=args.generated_root,
        generated_xml=args.generated_xml,
        generated_bi4=args.generated_bi4,
        bound_vtk=args.bound_vtk,
        fluid_vtk=args.fluid_vtk,
        all_vtk=args.all_vtk,
        hdp_vtk=args.hdp_vtk,
        gencase_out=args.gencase_out,
        output=args.output,
    )
    print(json.dumps({"hard_gate_pass": report["hard_gate_pass"], "fixed_normal_size_zero_count": report["native_arrays"]["fixed_normal_size_zero_count"], "fixed_usable_normal_zero_count": report["native_arrays"]["fixed_usable_normal_zero_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
