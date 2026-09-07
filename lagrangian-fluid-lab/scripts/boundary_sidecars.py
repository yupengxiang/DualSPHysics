#!/usr/bin/env python3
"""Read DualSPHysics MkCells geometry and build finite triangle sidecars.

DualSPHysics writes ``MkCells.vtk`` as binary VTK POLYDATA.  The file contains
both fluid and boundary polygon cells; this module deliberately keeps only
boundary cells (Type 0 fixed, Type 1 moving) and triangulates polygon fans.
The resulting sidecar stores every boundary triangle in world coordinates at
every exported HDF5 frame, so a tracer consumer never has to infer geometry
from boundary particles or silently treat a finite wall as an infinite plane.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import h5py
import numpy as np

try:
    from scripts.passive_tracers import transform_triangles
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from passive_tracers import transform_triangles


_DTYPES = {
    "float": ">f4",
    "double": ">f8",
    "unsigned_char": ">u1",
    "char": ">i1",
    "unsigned_short": ">u2",
    "short": ">i2",
    "unsigned_int": ">u4",
    "int": ">i4",
}


def _next_ascii_line(data: bytes, offset: int) -> tuple[str, int]:
    """Read an ASCII VTK line after a binary array, tolerating its newline."""
    while offset < len(data) and data[offset:offset + 1] in (b"\n", b"\r"):
        offset += 1
    end = data.find(b"\n", offset)
    if end < 0:
        raise ValueError("truncated VTK ASCII header")
    try:
        line = data[offset:end].decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise ValueError("binary VTK array was parsed at the wrong offset") from error
    return line, end + 1


def _array(data: bytes, offset: int, count: int, dtype: str) -> tuple[np.ndarray, int]:
    if dtype not in _DTYPES:
        raise ValueError(f"unsupported VTK scalar type: {dtype}")
    np_dtype = np.dtype(_DTYPES[dtype])
    size = int(count) * np_dtype.itemsize
    end = offset + size
    if end > len(data):
        raise ValueError("truncated binary VTK array")
    return np.frombuffer(data[offset:end], dtype=np_dtype).copy(), end


def read_binary_vtk_polydata(path: Path) -> dict[str, Any]:
    """Read points, polygon cells, and Mk/Type cell labels from MkCells.vtk."""
    data = Path(path).read_bytes()
    offset = 0
    header, offset = _next_ascii_line(data, offset)
    if not header.startswith("# vtk DataFile"):
        raise ValueError(f"not a VTK file: {path}")
    _, offset = _next_ascii_line(data, offset)
    encoding, offset = _next_ascii_line(data, offset)
    if encoding.upper() != "BINARY":
        raise ValueError("only binary VTK is supported for MkCells geometry")
    dataset, offset = _next_ascii_line(data, offset)
    if dataset.upper() != "DATASET POLYDATA":
        raise ValueError(f"expected POLYDATA, got {dataset!r}")

    line, offset = _next_ascii_line(data, offset)
    parts = line.split()
    if len(parts) != 3 or parts[0].upper() != "POINTS":
        raise ValueError(f"expected POINTS header, got {line!r}")
    point_count, point_type = int(parts[1]), parts[2].lower()
    point_values, offset = _array(data, offset, point_count * 3, point_type)
    points = point_values.reshape(point_count, 3).astype(np.float64)

    line, offset = _next_ascii_line(data, offset)
    parts = line.split()
    if len(parts) != 3 or parts[0].upper() != "POLYGONS":
        raise ValueError(f"expected POLYGONS header, got {line!r}")
    polygon_count, integer_count = int(parts[1]), int(parts[2])
    polygon_values, offset = _array(data, offset, integer_count, "int")
    cells: list[np.ndarray] = []
    cursor = 0
    for _ in range(polygon_count):
        if cursor >= len(polygon_values):
            raise ValueError("truncated polygon connectivity")
        vertex_count = int(polygon_values[cursor])
        cursor += 1
        if vertex_count < 3 or cursor + vertex_count > len(polygon_values):
            raise ValueError("invalid polygon vertex count")
        cell = polygon_values[cursor:cursor + vertex_count].astype(np.int64)
        cursor += vertex_count
        if np.any(cell < 0) or np.any(cell >= point_count):
            raise ValueError("polygon references an out-of-range point")
        cells.append(cell)
    if cursor != integer_count:
        raise ValueError("POLYGONS connectivity count does not match cells")

    line, offset = _next_ascii_line(data, offset)
    if not line.upper().startswith("CELL_DATA "):
        raise ValueError(f"expected CELL_DATA header, got {line!r}")
    if int(line.split()[1]) != polygon_count:
        raise ValueError("CELL_DATA count differs from polygon count")
    line, offset = _next_ascii_line(data, offset)
    parts = line.split()
    if len(parts) < 3 or parts[0].upper() != "SCALARS" or parts[1] != "Mk":
        raise ValueError(f"expected Mk scalar array, got {line!r}")
    mk_type = parts[2].lower()
    line, offset = _next_ascii_line(data, offset)
    if line.upper() != "LOOKUP_TABLE DEFAULT":
        raise ValueError(f"expected VTK lookup table, got {line!r}")
    mk, offset = _array(data, offset, polygon_count, mk_type)
    line, offset = _next_ascii_line(data, offset)
    if not line.upper().startswith("FIELD FIELDDATA "):
        raise ValueError(f"expected Type field data, got {line!r}")
    field_count = int(line.split()[-1])
    if field_count != 1:
        raise ValueError("expected exactly one VTK field-data array")
    line, offset = _next_ascii_line(data, offset)
    parts = line.split()
    if len(parts) != 4 or parts[0] != "Type" or int(parts[1]) != 1 or int(parts[2]) != polygon_count:
        raise ValueError(f"invalid Type field header: {line!r}")
    cell_type, offset = _array(data, offset, polygon_count, parts[3].lower())
    return {
        "points": points,
        "cells": cells,
        "mk": np.asarray(mk),
        "type": np.asarray(cell_type),
        "source": str(Path(path)),
    }


def boundary_triangles(parsed: dict[str, Any]) -> dict[str, np.ndarray]:
    """Triangulate Type 0/1 boundary polygons, excluding Type 3 fluid cells."""
    points = np.asarray(parsed["points"], dtype=np.float64)
    cells = parsed["cells"]
    mk = np.asarray(parsed["mk"])
    cell_type = np.asarray(parsed["type"])
    triangle_values: list[np.ndarray] = []
    triangle_mk: list[int] = []
    triangle_type: list[int] = []
    for cell, cell_mk, kind in zip(cells, mk, cell_type):
        if int(kind) not in (0, 1):
            continue
        for index in range(1, len(cell) - 1):
            triangle_values.append(points[[cell[0], cell[index], cell[index + 1]]])
            triangle_mk.append(int(cell_mk))
            triangle_type.append(int(kind))
    if not triangle_values:
        raise ValueError("MkCells file contains no Type 0/1 boundary polygons")
    return {
        "triangles": np.asarray(triangle_values, dtype=np.float64),
        "mk": np.asarray(triangle_mk, dtype=np.int64),
        "type": np.asarray(triangle_type, dtype=np.int8),
    }


def _transform_series(triangles: np.ndarray, transforms: np.ndarray) -> np.ndarray:
    transforms = np.asarray(transforms, dtype=np.float64)
    if transforms.ndim != 3 or transforms.shape[1:] != (4, 4):
        raise ValueError("moving-boundary transforms must have shape [T,4,4]")
    return np.asarray([transform_triangles(triangles, transform) for transform in transforms])


def build_world_series(h5_path: Path, parsed: dict[str, Any]) -> dict[str, Any]:
    """Build world-space triangle series and provenance from a parsed VTK file."""
    triangles = boundary_triangles(parsed)
    static = triangles["triangles"][triangles["type"] == 0]
    moving = triangles["triangles"][triangles["type"] == 1]
    with h5py.File(Path(h5_path), "r") as h5:
        times = np.asarray(h5["time"][:], dtype=np.float64)
        transforms = None
        if len(moving):
            if "control/cup_world_from_body" not in h5:
                raise ValueError("moving Type 1 boundary requires cup_world_from_body control")
            transforms = np.asarray(h5["control/cup_world_from_body"][:], dtype=np.float64)
            if len(transforms) != len(times):
                raise ValueError("moving-boundary transform count differs from HDF5 frame count")
            moving_world = _transform_series(moving, transforms)
        else:
            moving_world = np.empty((len(times), 0, 3, 3), dtype=np.float64)
    static_world = np.repeat(static[None, ...], len(times), axis=0)
    world = np.concatenate((static_world, moving_world), axis=1)
    triangle_mk = np.concatenate((triangles["mk"][triangles["type"] == 0],
                                  triangles["mk"][triangles["type"] == 1]))
    triangle_type = np.concatenate((np.zeros(len(static), dtype=np.int8),
                                    np.ones(len(moving), dtype=np.int8)))
    geometry_hash = sha256()
    geometry_hash.update(np.ascontiguousarray(triangles["triangles"]).tobytes())
    geometry_hash.update(np.ascontiguousarray(triangles["mk"]).tobytes())
    geometry_hash.update(np.ascontiguousarray(triangles["type"]).tobytes())
    return {
        "time": times,
        "triangles_world": world,
        "triangle_mk": triangle_mk,
        "triangle_type": triangle_type,
        "source_geometry_sha256": geometry_hash.hexdigest(),
        "static_triangle_count": int(len(static)),
        "moving_triangle_count": int(len(moving)),
    }


def write_sidecar(path: Path, case_id: str, h5_path: Path, parsed: dict[str, Any], *,
                  source_vtk_label: str | None = None,
                  source_hdf5_label: str | None = None) -> dict[str, Any]:
    """Write a compressed sidecar and return an auditable summary."""
    series = build_world_series(h5_path, parsed)
    triangles = series["triangles_world"]
    edge1 = triangles[:, :, 1] - triangles[:, :, 0]
    edge2 = triangles[:, :, 2] - triangles[:, :, 0]
    area2 = np.linalg.norm(np.cross(edge1, edge2), axis=-1)
    nondegenerate = np.isfinite(area2) & (area2 > 1e-12)
    if not np.all(np.isfinite(triangles)) or not np.all(nondegenerate):
        raise ValueError(f"{case_id}: sidecar contains non-finite or degenerate triangles")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=series["time"])
        h5.create_dataset("triangles_world", data=triangles, compression="gzip", compression_opts=4,
                          chunks=(1, min(128, triangles.shape[1]), 3, 3))
        h5.create_dataset("triangle_mk", data=series["triangle_mk"])
        h5.create_dataset("triangle_type", data=series["triangle_type"])
        h5.attrs["schema_version"] = "boundary-sidecar-v1"
        h5.attrs["case_id"] = case_id
        h5.attrs["coordinate_frame"] = "world"
        h5.attrs["semantics"] = "finite boundary triangles; Type 0 fixed and Type 1 prescribed moving surfaces; Type 3 fluid surfaces excluded"
        # Keep provenance clone-portable.  Callers that know the lab root pass
        # repository-relative labels; tests and ad-hoc use fall back to names.
        h5.attrs["source_vtk"] = source_vtk_label or Path(parsed["source"]).name
        h5.attrs["source_hdf5"] = source_hdf5_label or Path(h5_path).name
        h5.attrs["source_geometry_sha256"] = series["source_geometry_sha256"]
    return audit_sidecar(path)


def audit_sidecar(path: Path) -> dict[str, Any]:
    """Validate sidecar schema, frame axis, finite triangles, and provenance."""
    with h5py.File(Path(path), "r") as h5:
        required = ("time", "triangles_world", "triangle_mk", "triangle_type")
        missing = [name for name in required if name not in h5]
        if missing:
            raise ValueError(f"sidecar missing datasets: {missing}")
        time = np.asarray(h5["time"][:], dtype=np.float64)
        triangles = np.asarray(h5["triangles_world"][:], dtype=np.float64)
        mk = np.asarray(h5["triangle_mk"][:])
        kind = np.asarray(h5["triangle_type"][:])
        if time.ndim != 1 or len(time) < 2 or not np.all(np.diff(time) > 0):
            raise ValueError("sidecar time must be strictly increasing")
        if triangles.ndim != 4 or triangles.shape[0] != len(time) or triangles.shape[2:] != (3, 3):
            raise ValueError("triangles_world must have shape [T,N,3,3]")
        if len(mk) != triangles.shape[1] or len(kind) != triangles.shape[1]:
            raise ValueError("triangle labels do not match triangle axis")
        if not np.all(np.isin(kind, (0, 1))):
            raise ValueError("sidecar triangle_type must contain only 0/1")
        edge1 = triangles[:, :, 1] - triangles[:, :, 0]
        edge2 = triangles[:, :, 2] - triangles[:, :, 0]
        area2 = np.linalg.norm(np.cross(edge1, edge2), axis=-1)
        finite = np.all(np.isfinite(triangles), axis=(1, 2, 3))
        nondegenerate = np.all(area2 > 1e-12, axis=1)
        return {
            "path": str(Path(path)),
            "case_id": h5.attrs.get("case_id", "unknown"),
            "schema_version": h5.attrs.get("schema_version", "unknown"),
            "coordinate_frame": h5.attrs.get("coordinate_frame", "unknown"),
            "frame_count": int(len(time)),
            "triangle_count": int(triangles.shape[1]),
            "static_triangle_count": int(np.sum(kind == 0)),
            "moving_triangle_count": int(np.sum(kind == 1)),
            "all_frames_finite": bool(np.all(finite)),
            "all_frames_nondegenerate": bool(np.all(nondegenerate)),
            "time_start_s": float(time[0]),
            "time_end_s": float(time[-1]),
            "source_vtk": h5.attrs.get("source_vtk", "unknown"),
            "source_hdf5": h5.attrs.get("source_hdf5", "unknown"),
            "source_geometry_sha256": h5.attrs.get("source_geometry_sha256", "unknown"),
        }


def sidecar_provider(path: Path):
    """Return an ``advect_hdf5`` barrier callback backed by a sidecar.

    The sidecar is loaded once, and each callback linearly interpolates the
    already-world-space triangles between the two solver frames.  It is kept
    separate from the solver HDF5 so the same tracer code can compare a legacy
    no-wall run with a wall-aware run without rewriting the source export.
    """
    with h5py.File(Path(path), "r") as h5:
        times = np.asarray(h5["time"][:], dtype=np.float64)
        triangles = np.asarray(h5["triangles_world"][:], dtype=np.float64)
    if triangles.shape[0] != len(times):
        raise ValueError("sidecar frame axis does not match its time axis")

    def provider(_solver_h5, frame0: int, frame1: int, alpha: float):
        if not (0 <= int(frame0) < len(times) and 0 <= int(frame1) < len(times)):
            raise IndexError("solver frame is outside sidecar frame axis")
        return ((1.0 - float(alpha)) * triangles[int(frame0)]
                + float(alpha) * triangles[int(frame1)])

    return provider
