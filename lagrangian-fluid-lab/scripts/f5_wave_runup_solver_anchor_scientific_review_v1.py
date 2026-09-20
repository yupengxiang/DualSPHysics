#!/usr/bin/env python3
"""Read-only scientific post-review for the F5 solver anchor.

The solver worker deliberately stops before the scientific F5 gates.  This
sidecar review consumes the raw ``Part_*.bi4`` files, ``Run.out``, the eleven
``GaugesSWL_*.csv`` files, and the hash-bound F5 definition/contract.  It
never starts DualSPHysics, invokes CUDA, submits a queue job, or changes a
root review, job specification, registry, ledger, or matrix.

The default trajectory coverage is deliberately small: the first and last
available frames plus a fixed uniform sample.  ``--all-frames`` requests a
sequential decode of every frame that actually exists.  No missing frame is
created or inferred.  A geometry result is therefore labelled
``pending_sampled_only`` unless every available frame and every fluid
particle was checked.  Saved-frame segment crossings are diagnostics of the
linear chord between two saved states; they are not claims about sub-step
solver paths.

The current F5 contract names event gates but does not bind numerical event
thresholds or an acceptance envelope for the CIEMito table.  This reviewer
reports finite time-series diagnostics while keeping incident, run-up,
return, and external-reference gates ``pending_preregistered_threshold``.
Every report carries zero qualification and matrix credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import numpy as np


LAB = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    LAB
    / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
    / "fresh-definition-contract-v2.json"
)
DEFAULT_PREFLIGHT = (
    LAB
    / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
    / "preflight-v2/preflight.json"
)
# Keep the short spelling as an import compatibility alias for local tooling.
DEFAULT_PRELIGHT = DEFAULT_PREFLIGHT
DEFAULT_DEFINITION = (
    LAB
    / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
    / "F5_wave_runup_q0p50_dp0p0075_Def.xml"
)
DEFAULT_MOTION = (
    LAB
    / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
    / "Mov_piston_q0p50_scaled.dat"
)
DEFAULT_GEOMETRY = (
    LAB
    / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
    / "preflight-v2/generated/F5_wave_runup_q0p50_dp0p0075_v2_MkCells.vtk"
)
DEFAULT_REFERENCE = (
    LAB
    / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
    / "EXP_CaseWaveRunup_CIEMito.txt"
)
DEFAULT_DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"

EXPECTED_CASE_ID = "F5_wave_runup_q0p50_dp0p0075_v2"
EXPECTED_FRAMES = 801
EXPECTED_TMAX_S = 16.0
EXPECTED_TOUT_S = 0.02
EXPECTED_GAUGES = tuple([f"WG{i}" for i in range(1, 5)] + [f"Run-up{i}" for i in range(1, 8)])
FLUID_FIRST_ID = 94622
MASS_CHANGE_DIAGNOSTIC_LIMIT = 1.0e-8
ENDPOINT_TOLERANCE_M = 1.0e-8
SAMPLE_FRAME_COUNT = 9
DEFAULT_SURFACE_PARTICLE_STRIDE = 32


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(LAB))
    except ValueError:
        return str(Path(path).resolve())


def artifact(path: Path, role: str, *, required: bool = True) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        if required:
            raise FileNotFoundError(path)
        return {"path": relative(path), "present": False, "role": role}
    return {
        "path": relative(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _bound_path(item: dict[str, Any], *, label: str) -> Path:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise ValueError(f"malformed {label} binding")
    path = (LAB / item["path"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if "bytes" in item and int(item["bytes"]) != path.stat().st_size:
        raise ValueError(f"stale {label} byte binding: {path}")
    if "sha256" in item and item["sha256"] != sha256(path):
        raise ValueError(f"stale {label} hash binding: {path}")
    return path


def validate_contract(path: Path) -> dict[str, Any]:
    """Validate only immutable, zero-credit F5 contract facts."""

    contract = load_json(path)
    if contract.get("schema") != "core.f5.third_t1.definition_materialization.v2":
        raise ValueError("unexpected F5 definition contract schema")
    if contract.get("qualification_claim") != "none":
        raise ValueError("definition contract carries a qualification claim")
    candidate = contract.get("candidate", {})
    if (
        candidate.get("family") != "F5"
        or candidate.get("scope_id") != "F5_prescribed_wave_runup_x_v1"
        or candidate.get("case_id") != EXPECTED_CASE_ID
    ):
        raise ValueError("contract candidate identity differs from the protected F5 anchor")
    fixed = contract.get("fixed_contract", {})
    if (
        fixed.get("denominator_rows") != 15
        or float(fixed.get("time_max_s", math.nan)) != EXPECTED_TMAX_S
        or float(fixed.get("output_interval_s", math.nan)) != EXPECTED_TOUT_S
        or fixed.get("event_window_required") is not True
        or fixed.get("zero_credit_until_cpu_native_and_solver_reviews") is not True
    ):
        raise ValueError("F5 fixed denominator/window contract is not closed")
    execution = contract.get("execution_controls", {})
    for key in ("matrix_materialized", "matrix_submitted", "qualification_credit"):
        if execution.get(key) not in (False, 0):
            raise ValueError(f"contract opened protected state: {key}")
    identity = contract.get("fresh_identity", {})
    for key, default in (("definition", DEFAULT_DEFINITION), ("motion", DEFAULT_MOTION)):
        binding = identity.get(key, {}).get("output")
        if binding:
            _bound_path(binding, label=f"fresh_identity.{key}.output")
        elif default.is_file():
            # Older receipts have the path/hash nested differently.  The
            # caller still binds the concrete file below.
            continue
    return contract


def validate_preflight(
    path: Path | None, *, definition: Path | None = None, motion: Path | None = None
) -> dict[str, Any] | None:
    if path is None:
        return None
    preflight = load_json(path)
    if preflight.get("qualification_claim") != "none" or preflight.get("matrix_credit") != 0:
        raise ValueError("preflight is not zero-credit")
    if preflight.get("case_id") not in (None, EXPECTED_CASE_ID):
        raise ValueError("preflight case identity differs from the protected F5 anchor")
    for name, selected in (("input", definition), ("motion", motion)):
        binding = preflight.get(name)
        if binding and selected is not None:
            bound = _bound_path(binding, label=f"preflight.{name}")
            if bound != Path(selected).resolve():
                raise ValueError(f"preflight {name} binding differs from selected F5 source")
    return preflight


def validate_contract_sources(
    contract: dict[str, Any], *, definition: Path, motion: Path, slope: Path, blocks: Path, reference: Path
) -> None:
    """Keep caller-selected source files inside the frozen contract closure."""

    identity = contract.get("fresh_identity", {})
    for name, path in (("definition", definition), ("motion", motion)):
        binding = identity.get(name, {}).get("output")
        if not binding:
            continue
        bound = _bound_path(binding, label=f"fresh_identity.{name}.output")
        if bound != Path(path).resolve():
            raise ValueError(f"{name} path is outside the frozen F5 contract: {path}")
    adjacent = {
        (LAB / item["path"]).resolve(): item
        for item in identity.get("definition_adjacent_assets", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    for name, path in (("slope", slope), ("blocks", blocks), ("reference", reference)):
        bound = adjacent.get(Path(path).resolve())
        if bound is None:
            raise ValueError(f"{name} path is outside the frozen F5 adjacent-asset closure: {path}")
        _bound_path(bound, label=f"definition_adjacent_assets.{name}")


def parse_run_out(path: Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

    def number(pattern: str) -> float | None:
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            return None
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            return None
        return value if math.isfinite(value) else None

    excluded = re.search(r"Excluded particles\.+:\s*([\d,]+)", text)
    outputs = re.findall(r"^\s*Output\.{5,}:\s*[^\n]*?dt:([0-9.eE+-]+)", text, re.MULTILINE)
    return {
        "present": path.is_file(),
        "finished_code_zero": "Finished execution (code=0)" in text,
        "timemax_s": number(r"^TimeMax=([0-9.eE+-]+)$"),
        "output_dt_values_s": sorted({float(value) for value in outputs}),
        "excluded_particles": int(excluded.group(1).replace(",", "")) if excluded else None,
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256(path) if path.is_file() else None,
    }


def frame_inventory(solver: Path) -> dict[str, Any]:
    paths: dict[int, Path] = {}
    malformed: list[str] = []
    for path in sorted((Path(solver) / "data").glob("Part_*.bi4")):
        match = re.fullmatch(r"Part_(\d+)\.bi4", path.name)
        if not match:
            malformed.append(path.name)
            continue
        index = int(match.group(1))
        if index in paths:
            malformed.append(path.name)
        paths[index] = path
    indices = sorted(paths)
    contiguous = indices == list(range(len(indices)))
    complete = indices == list(range(EXPECTED_FRAMES))
    return {
        "paths": paths,
        "indices": indices,
        "count": len(indices),
        "first_last": [indices[:3], indices[-3:]],
        "malformed_names": malformed,
        "contiguous_from_zero": contiguous,
        "expected_count": EXPECTED_FRAMES,
        "complete_expected_indices": complete,
    }


def select_frame_indices(
    available: Iterable[int], *, all_frames: bool = False, sample_count: int = SAMPLE_FRAME_COUNT
) -> list[int]:
    """Select only indices that exist; never fill a missing future frame."""

    indices = sorted({int(value) for value in available})
    if not indices:
        return []
    if all_frames:
        return indices
    count = max(2, int(sample_count))
    if len(indices) <= count:
        return indices
    positions = np.linspace(0, len(indices) - 1, count, dtype=int)
    return sorted({indices[int(position)] for position in positions})


def _xml_item_values(parent: ET.Element) -> dict[str, str]:
    return {
        str(node.get("name")): str(node.get("v"))
        for node in parent
        if node.get("name") is not None and node.get("v") is not None
    }


def decode_bi4(path: Path, decoder: Path, temporary_root: Path) -> dict[str, Any]:
    """Decode one native frame through the pinned read-only decoder."""

    temporary_root = Path(temporary_root)
    stem = temporary_root / Path(path).stem
    if stem.exists():
        shutil.rmtree(stem)
    subprocess.run([str(decoder), str(path), str(stem)], check=True, stdout=subprocess.DEVNULL)
    root = ET.parse(str(stem) + ".xml").getroot()
    parent = root.find("item")
    if parent is None:
        raise ValueError(f"decoder XML has no top-level item: {path}")
    node = parent.find("item")
    if node is None:
        raise ValueError(f"decoder XML has no frame item: {path}")
    metadata = _xml_item_values(parent)
    info = _xml_item_values(node)
    folder_name = node.get("name")
    if not folder_name:
        raise ValueError(f"decoder XML has no frame folder: {path}")
    folder = stem / folder_name
    ids = np.fromfile(folder / "Idp.bin", dtype=np.uint32)
    position_file = folder / "Posd.bin" if (folder / "Posd.bin").is_file() else folder / "Pos.bin"
    positions = np.fromfile(
        position_file, dtype=np.float64 if position_file.name == "Posd.bin" else np.float32
    ).reshape(-1, 3)
    velocity = np.fromfile(folder / "Vel.bin", dtype=np.float32).reshape(-1, 3)
    density = np.fromfile(folder / "Rhop.bin", dtype=np.float32)
    if not (len(ids) == len(positions) == len(velocity) == len(density)):
        raise ValueError(f"native array lengths differ in {path}")
    order = np.argsort(ids)
    ids = ids[order]
    if len(np.unique(ids)) != len(ids):
        raise ValueError(f"duplicate native identities in {path}")
    return {
        "path": Path(path),
        "ids": ids,
        "position": positions[order].astype(np.float64, copy=False),
        "velocity": velocity[order].astype(np.float64, copy=False),
        "density": density[order].astype(np.float64, copy=False),
        "metadata": metadata,
        "info": info,
        "time_s": _metadata_time(info),
    }


def _metadata_time(info: dict[str, str]) -> float | None:
    # DualSPHysics stores physical simulation time in TimeStep.  RunTime is
    # wall-clock timing in some native products and is zero in this solver
    # output, so it must never be used to drive the prescribed piston motion.
    for key in ("TimeStep", "timesim", "RunTime"):
        value = info.get(key)
        if value is None:
            continue
        try:
            parsed = float(value)
        except ValueError:
            continue
        if math.isfinite(parsed):
            return parsed
    return None


def _float_metadata(metadata: dict[str, str], key: str) -> float | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def parse_gauge(path: Path) -> dict[str, Any]:
    rows: list[list[float]] = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.replace(";", " ").split()
        try:
            values = [float(value) for value in fields]
        except ValueError:
            continue
        if len(values) >= 4 and np.isfinite(values[:4]).all():
            rows.append(values[:4])
    array = np.asarray(rows, dtype=np.float64)
    issues: list[str] = []
    if array.ndim != 2 or array.shape[1] != 4 or len(array) < 2:
        issues.append("fewer_than_two_finite_rows")
    times = array[:, 0] if len(array) else np.empty(0)
    values = array[:, 3] if len(array) else np.empty(0)
    if len(times) > 1:
        differences = np.diff(times)
        if not np.all(differences > 0):
            issues.append("time_not_strictly_increasing")
        if not np.isclose(float(np.median(differences)), EXPECTED_TOUT_S, atol=0.003, rtol=0):
            issues.append("time_cadence_invalid")
    if len(times) and float(times[-1]) < EXPECTED_TMAX_S - 0.05:
        issues.append("short_window")
    return {
        "path": relative(path),
        "rows": int(len(array)),
        "time_start_s": float(times[0]) if len(times) else None,
        "time_end_s": float(times[-1]) if len(times) else None,
        "dt_median_s": float(np.median(np.diff(times))) if len(times) > 1 else None,
        "swl_initial_m": float(values[0]) if len(values) else None,
        "swl_min_m": float(values.min()) if len(values) else None,
        "swl_max_m": float(values.max()) if len(values) else None,
        "swl_peak_time_s": float(times[int(np.argmax(values))]) if len(values) else None,
        "dynamic_range_m": float(np.ptp(values)) if len(values) else None,
        "issues": issues,
        "sha256": sha256(path),
        "data": array,
    }


def gauge_audit(solver: Path) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(solver).glob("GaugesSWL_*.csv")):
        name = path.stem.removeprefix("GaugesSWL_")
        records[name] = parse_gauge(path)
    expected = set(EXPECTED_GAUGES)
    return {
        "names": sorted(records),
        "expected_names": sorted(expected),
        "missing_names": sorted(expected - set(records)),
        "unexpected_names": sorted(set(records) - expected),
        "all_expected": set(records) == expected,
        "all_structural_gates": bool(records) and all(not item["issues"] for item in records.values()),
        "records": records,
    }


def _parse_motion(path: Path) -> dict[str, np.ndarray]:
    values: list[tuple[float, float]] = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        try:
            time_s, displacement = float(fields[0]), float(fields[1])
        except ValueError:
            continue
        if math.isfinite(time_s) and math.isfinite(displacement):
            values.append((time_s, displacement))
    if len(values) < 2:
        raise ValueError(f"motion file has fewer than two finite rows: {path}")
    array = np.asarray(values, dtype=np.float64)
    if np.any(np.diff(array[:, 0]) < 0):
        raise ValueError("motion times are not non-decreasing")
    return {"time_s": array[:, 0], "displacement_m": array[:, 1]}


def motion_displacement(motion: dict[str, np.ndarray], time_s: float) -> float | None:
    if not math.isfinite(time_s):
        return None
    times = motion["time_s"]
    values = motion["displacement_m"]
    if time_s < float(times[0]) - 1e-9 or time_s > float(times[-1]) + 1e-9:
        return None
    return float(np.interp(time_s, times, values))


def _read_binary_vtk_mkcells(path: Path) -> dict[str, Any]:
    """Read the binary POLYDATA form emitted by GenCase without h5py."""

    data = Path(path).read_bytes()
    offset = 0

    def line() -> str:
        nonlocal offset
        while offset < len(data) and data[offset : offset + 1] in (b"\n", b"\r"):
            offset += 1
        end = data.find(b"\n", offset)
        if end < 0:
            raise ValueError(f"truncated VTK header: {path}")
        value = data[offset:end].decode("ascii").strip()
        offset = end + 1
        return value

    def array(count: int, dtype: str) -> np.ndarray:
        nonlocal offset
        dtypes = {
            "float": ">f4",
            "double": ">f8",
            "int": ">i4",
            "unsigned_int": ">u4",
            "short": ">i2",
            "unsigned_short": ">u2",
            "char": ">i1",
            "unsigned_char": ">u1",
        }
        if dtype.lower() not in dtypes:
            raise ValueError(f"unsupported VTK type {dtype}")
        np_dtype = np.dtype(dtypes[dtype.lower()])
        size = int(count) * np_dtype.itemsize
        end = offset + size
        if end > len(data):
            raise ValueError(f"truncated VTK binary data: {path}")
        result = np.frombuffer(data[offset:end], dtype=np_dtype).copy()
        offset = end
        return result

    if not line().startswith("# vtk DataFile"):
        raise ValueError(f"not a VTK file: {path}")
    line()
    encoding, dataset = line().upper(), line().upper()
    if encoding != "BINARY" or dataset != "DATASET POLYDATA":
        raise ValueError(f"expected binary POLYDATA VTK: {path}")
    point_tokens = line().split()
    if len(point_tokens) != 3 or point_tokens[0].upper() != "POINTS":
        raise ValueError(f"invalid VTK POINTS header: {path}")
    point_count = int(point_tokens[1])
    points = array(point_count * 3, point_tokens[2]).reshape(-1, 3).astype(np.float64)
    polygon_tokens = line().split()
    if len(polygon_tokens) != 3 or polygon_tokens[0].upper() != "POLYGONS":
        raise ValueError(f"invalid VTK POLYGONS header: {path}")
    polygon_count, integer_count = int(polygon_tokens[1]), int(polygon_tokens[2])
    connectivity = array(integer_count, "int")
    cursor = 0
    cells: list[np.ndarray] = []
    for _ in range(polygon_count):
        if cursor >= len(connectivity):
            raise ValueError("truncated VTK polygon connectivity")
        vertex_count = int(connectivity[cursor])
        cursor += 1
        if vertex_count < 3 or cursor + vertex_count > len(connectivity):
            raise ValueError("invalid VTK polygon vertex count")
        cell = connectivity[cursor : cursor + vertex_count].astype(np.int64)
        cursor += vertex_count
        if np.any(cell < 0) or np.any(cell >= point_count):
            raise ValueError("VTK polygon references an invalid point")
        cells.append(cell)
    if cursor != integer_count:
        raise ValueError("VTK polygon count mismatch")
    cell_data = line().split()
    if len(cell_data) != 2 or cell_data[0].upper() != "CELL_DATA" or int(cell_data[1]) != polygon_count:
        raise ValueError("invalid VTK CELL_DATA header")
    scalars = line().split()
    if len(scalars) < 3 or scalars[0].upper() != "SCALARS" or scalars[1] != "Mk":
        raise ValueError("Mk scalar is missing from VTK")
    if line().upper() != "LOOKUP_TABLE DEFAULT":
        raise ValueError("VTK lookup table is missing")
    mk = array(polygon_count, scalars[2])
    field = line().split()
    if len(field) != 3 or field[0].upper() != "FIELD" or int(field[-1]) != 1:
        raise ValueError("VTK Type field is missing")
    type_header = line().split()
    if len(type_header) != 4 or type_header[0] != "Type" or int(type_header[2]) != polygon_count:
        raise ValueError("invalid VTK Type header")
    kind = array(polygon_count, type_header[3])
    return {"points": points, "cells": cells, "mk": np.asarray(mk), "type": np.asarray(kind)}


def boundary_triangles(path: Path) -> dict[str, np.ndarray]:
    parsed = _read_binary_vtk_mkcells(path)
    values: list[np.ndarray] = []
    mks: list[int] = []
    kinds: list[int] = []
    for cell, mk, kind in zip(parsed["cells"], parsed["mk"], parsed["type"]):
        if int(kind) not in (0, 1):
            continue
        for index in range(1, len(cell) - 1):
            values.append(parsed["points"][[cell[0], cell[index], cell[index + 1]]])
            mks.append(int(mk))
            kinds.append(int(kind))
    if not values:
        raise ValueError(f"VTK contains no boundary triangles: {path}")
    return {
        "triangles": np.asarray(values, dtype=np.float64),
        "mk": np.asarray(mks, dtype=np.int64),
        "type": np.asarray(kinds, dtype=np.int8),
    }


def read_binary_stl(path: Path) -> np.ndarray:
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise ValueError(f"invalid binary STL: {path}")
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + count * 50:
        raise ValueError(f"unexpected binary STL length: {path}")
    triangles = np.empty((count, 3, 3), dtype=np.float64)
    for index in range(count):
        values = struct.unpack_from("<12fH", data, 84 + index * 50)
        triangles[index] = np.asarray(values[3:12], dtype=np.float64).reshape(3, 3)
    return triangles


def transform_wave_stl(triangles: np.ndarray) -> np.ndarray:
    """Apply the fixed F5 XML rotation/translation to one source STL."""

    value = np.asarray(triangles, dtype=np.float64)
    rotation = np.asarray([[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    return value @ rotation.T + np.asarray([5.95, 0.37, 0.0])


def mesh_is_watertight(triangles: np.ndarray) -> bool:
    edges: dict[tuple[tuple[float, float, float], tuple[float, float, float]], int] = {}
    for triangle in np.asarray(triangles):
        for left, right in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            edge = tuple(sorted((tuple(map(float, left)), tuple(map(float, right)))))
            edges[edge] = edges.get(edge, 0) + 1
    return bool(edges) and all(count == 2 for count in edges.values())


def _ray_triangle_hits(points: np.ndarray, triangle: np.ndarray) -> np.ndarray:
    """Return +x ray intersections for a chunk of points and one triangle."""

    origin = np.asarray(points, dtype=np.float64)
    edge1 = triangle[1] - triangle[0]
    edge2 = triangle[2] - triangle[0]
    direction = np.asarray([1.0, 0.0, 0.0])
    h = np.cross(direction, edge2)
    determinant = float(np.dot(edge1, h))
    scale = max(1.0, float(np.linalg.norm(edge1) * np.linalg.norm(edge2)))
    if abs(determinant) <= 32.0 * np.finfo(np.float64).eps * scale:
        return np.zeros(len(origin), dtype=bool)
    inverse = 1.0 / determinant
    offset = origin - triangle[0]
    u = inverse * np.einsum("ij,j->i", offset, h)
    qvec = np.cross(offset, edge1)
    v = inverse * qvec[:, 0]
    t = inverse * np.einsum("j,ij->i", edge2, qvec)
    epsilon = 64.0 * np.finfo(np.float64).eps
    return (u >= -epsilon) & (v >= -epsilon) & (u + v <= 1.0 + epsilon) & (t > epsilon)


def points_inside_mesh(points: np.ndarray, triangles: np.ndarray, *, chunk_size: int = 4096) -> np.ndarray:
    """Classify points strictly inside a closed triangle mesh by ray parity."""

    points = np.asarray(points, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or triangles.ndim != 3 or triangles.shape[1:] != (3, 3):
        raise ValueError("points/triangles have invalid shapes")
    if not len(points) or not len(triangles):
        return np.zeros(len(points), dtype=bool)
    lower = triangles.reshape(-1, 3).min(axis=0)
    upper = triangles.reshape(-1, 3).max(axis=0)
    candidates = np.all((points >= lower - ENDPOINT_TOLERANCE_M) & (points <= upper + ENDPOINT_TOLERANCE_M), axis=1)
    result = np.zeros(len(points), dtype=bool)
    candidate_indices = np.flatnonzero(candidates)
    for start in range(0, len(candidate_indices), int(chunk_size)):
        index = candidate_indices[start : start + int(chunk_size)]
        chunk = points[index]
        parity = np.zeros(len(chunk), dtype=bool)
        for triangle in triangles:
            parity ^= _ray_triangle_hits(chunk, triangle)
        result[index] = parity
    return result


def _segment_box_hits(p0: np.ndarray, p1: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    p0, p1 = np.asarray(p0, dtype=np.float64), np.asarray(p1, dtype=np.float64)
    delta = p1 - p0
    enter = np.full(len(p0), -np.inf, dtype=np.float64)
    exit_ = np.full(len(p0), np.inf, dtype=np.float64)
    for axis in range(3):
        direction = delta[:, axis]
        parallel = np.isclose(direction, 0.0, atol=1e-15, rtol=0.0)
        outside = parallel & ((p0[:, axis] < lower[axis]) | (p0[:, axis] > upper[axis]))
        enter[outside] = np.inf
        exit_[outside] = -np.inf
        moving = ~parallel
        first = np.full(len(p0), np.nan)
        second = np.full(len(p0), np.nan)
        first[moving] = (lower[axis] - p0[moving, axis]) / direction[moving]
        second[moving] = (upper[axis] - p0[moving, axis]) / direction[moving]
        enter = np.maximum(enter, np.where(moving, np.minimum(first, second), -np.inf))
        exit_ = np.minimum(exit_, np.where(moving, np.maximum(first, second), np.inf))
    return (enter <= exit_) & (exit_ >= 0.0) & (enter <= 1.0)


def _segment_triangle_hits(p0: np.ndarray, p1: np.ndarray, triangle: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Möller–Trumbore segment test for one triangle and many segments."""

    p0 = np.asarray(p0, dtype=np.float64)
    p1 = np.asarray(p1, dtype=np.float64)
    direction = p1 - p0
    edge1 = triangle[1] - triangle[0]
    edge2 = triangle[2] - triangle[0]
    pvec = np.cross(direction, edge2)
    determinant = np.einsum("j,ij->i", edge1, pvec)
    scale = max(1.0, float(np.linalg.norm(edge1) * np.linalg.norm(edge2)))
    epsilon = 32.0 * np.finfo(np.float64).eps * scale
    valid_det = np.abs(determinant) > epsilon
    inverse = np.zeros_like(determinant)
    inverse[valid_det] = 1.0 / determinant[valid_det]
    offset = p0 - triangle[0]
    u = inverse * np.einsum("ij,ij->i", offset, pvec)
    qvec = np.cross(offset, edge1)
    v = inverse * np.einsum("ij,ij->i", direction, qvec)
    t = inverse * np.einsum("j,ij->i", edge2, qvec)
    endpoint_epsilon = 64.0 * np.finfo(np.float64).eps
    hit = (
        valid_det
        & (u >= -endpoint_epsilon)
        & (v >= -endpoint_epsilon)
        & (u + v <= 1.0 + endpoint_epsilon)
        & (t > endpoint_epsilon)
        & (t < 1.0 - endpoint_epsilon)
    )
    return hit, t


def segment_mesh_crossings(
    p0: np.ndarray,
    p1: np.ndarray,
    triangles: np.ndarray,
    particle_ids: np.ndarray | None = None,
    *,
    max_records: int = 10,
) -> dict[str, Any]:
    """Count finite segment/triangle crossings with an AABB broad phase."""

    p0, p1 = np.asarray(p0, dtype=np.float64), np.asarray(p1, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.float64)
    if p0.shape != p1.shape or p0.ndim != 2 or p0.shape[1] != 3:
        raise ValueError("segment endpoints have incompatible shapes")
    if triangles.ndim != 3 or triangles.shape[1:] != (3, 3):
        raise ValueError("triangles have an invalid shape")
    if particle_ids is None:
        particle_ids = np.arange(len(p0), dtype=np.int64)
    else:
        particle_ids = np.asarray(particle_ids)
    if len(particle_ids) != len(p0):
        raise ValueError("particle ID length differs from segment count")
    if not len(p0) or not len(triangles):
        return {"count": 0, "records": []}
    segment_lower = np.minimum(p0, p1)
    segment_upper = np.maximum(p0, p1)
    total = 0
    records: list[dict[str, Any]] = []
    for tri_index, triangle in enumerate(triangles):
        lower = triangle.min(axis=0) - ENDPOINT_TOLERANCE_M
        upper = triangle.max(axis=0) + ENDPOINT_TOLERANCE_M
        candidates = np.flatnonzero(np.all((segment_upper >= lower) & (segment_lower <= upper), axis=1))
        if not len(candidates):
            continue
        hit, fraction = _segment_triangle_hits(p0[candidates], p1[candidates], triangle)
        hit_indices = candidates[np.flatnonzero(hit)]
        total += int(len(hit_indices))
        if len(records) < max_records:
            for point_index in hit_indices[: max_records - len(records)]:
                records.append(
                    {
                        "particle_id": int(particle_ids[point_index]),
                        "point_index": int(point_index),
                        "triangle_index": int(tri_index),
                        "fraction": float(fraction[np.flatnonzero(candidates == point_index)[0]]),
                    }
                )
    return {"count": int(total), "records": records}


def _parse_xml_geometry(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError("F5 Definition has no geometry/definition")
    pointmin = definition.find("pointmin")
    pointmax = definition.find("pointmax")
    if pointmin is None or pointmax is None:
        raise ValueError("F5 Definition has no pointmin/pointmax")
    bounds = {
        "min": [float(pointmin.get(axis)) for axis in "xyz"],
        "max": [float(pointmax.get(axis)) for axis in "xyz"],
    }
    boxes: dict[str, dict[str, list[float]]] = {}
    for node in root.findall("./casedef/geometry/commands/mainlist/drawbox"):
        point = node.find("point")
        size = node.find("size")
        if point is None or size is None:
            continue
        low = [float(point.get(axis)) for axis in "xyz"]
        extent = [float(size.get(axis)) for axis in "xyz"]
        name = "piston" if node.get("cmt") == "piston" else "bottom"
        if name not in boxes:
            boxes[name] = {"low": low, "size": extent, "high": (np.asarray(low) + extent).tolist()}
    gauges: dict[str, dict[str, list[float]]] = {}
    for node in root.findall("./execution/special/gauges/swl"):
        name = node.get("name")
        point0, point2 = node.find("point0"), node.find("point2")
        if name and point0 is not None and point2 is not None:
            gauges[name] = {
                "point0": [float(point0.get(axis)) for axis in "xyz"],
                "point2": [float(point2.get(axis)) for axis in "xyz"],
            }
    parameters = {
        node.get("key"): node.get("value")
        for node in root.findall("./execution/parameters/parameter")
        if node.get("key") is not None
    }
    stl_transforms = []
    for node in root.findall("./casedef/geometry/commands/mainlist/drawfilestl"):
        move = node.find("drawmove")
        rotate = node.find("drawrotate")
        stl_transforms.append(
            {
                "file": node.get("file"),
                "move": [float(move.get(axis)) for axis in "xyz"] if move is not None else None,
                "rotate": [float(rotate.get(axis)) for axis in ("angx", "angy", "angz")] if rotate is not None else None,
            }
        )
    return {"bounds": bounds, "boxes": boxes, "gauges": gauges, "parameters": parameters, "stl_transforms": stl_transforms}


def _declared_bounds(preflight: dict[str, Any] | None, xml_geometry: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    declared = (preflight or {}).get("geometry", {}).get("declared_bounds_m")
    if isinstance(declared, dict) and "min" in declared and "max" in declared:
        lower, upper = declared["min"], declared["max"]
    else:
        lower, upper = xml_geometry["bounds"]["min"], xml_geometry["bounds"]["max"]
    return np.asarray(lower, dtype=np.float64), np.asarray(upper, dtype=np.float64)


def _mesh_summary(mesh: np.ndarray, path: Path, role: str) -> dict[str, Any]:
    value = np.asarray(mesh, dtype=np.float64)
    return {
        "role": role,
        "path": relative(path),
        "sha256": sha256(path),
        "triangles": int(len(value)),
        "watertight": mesh_is_watertight(value),
        "bounds_min_m": value.reshape(-1, 3).min(axis=0).tolist() if len(value) else None,
        "bounds_max_m": value.reshape(-1, 3).max(axis=0).tolist() if len(value) else None,
    }


def build_static_geometry(
    *,
    geometry_path: Path,
    slope_path: Path,
    blocks_path: Path,
    definition_path: Path,
    preflight: dict[str, Any] | None,
) -> dict[str, Any]:
    xml_geometry = _parse_xml_geometry(definition_path)
    boundary = boundary_triangles(geometry_path)
    slope = transform_wave_stl(read_binary_stl(slope_path))
    blocks = transform_wave_stl(read_binary_stl(blocks_path))
    lower, upper = _declared_bounds(preflight, xml_geometry)
    if np.any(upper <= lower) or not np.isfinite(np.r_[lower, upper]).all():
        raise ValueError("F5 declared geometry bounds are invalid")
    # The XML transform is part of the fixed F5 identity.  A modified source
    # transform is a contract mismatch, not an opportunity to reinterpret it.
    transforms = {item.get("file"): item for item in xml_geometry["stl_transforms"]}
    for name in ("Slope.stl", "Blocks_3D_scaled.stl"):
        item = transforms.get(name)
        if item is None or item.get("move") != [5.95, 0.37, 0.0] or item.get("rotate") != [0.0, 0.0, -90.0]:
            raise ValueError(f"unexpected fixed F5 STL transform for {name}")
    return {
        "boundary_triangles": boundary,
        "slope_triangles": slope,
        "blocks_triangles": blocks,
        "declared_bounds": (lower, upper),
        "xml_geometry": xml_geometry,
        "summary": {
            "source_vtk": artifact(geometry_path, "generated static boundary triangle source"),
            "slope": _mesh_summary(slope, slope_path, "F5 slope source STL transformed by Definition"),
            "blocks": _mesh_summary(blocks, blocks_path, "F5 blocks source STL transformed by Definition"),
            "declared_bounds_m": {"min": lower.tolist(), "max": upper.tolist()},
            "boundary_triangle_count": int(len(boundary["triangles"])),
            "boundary_mk_counts": {
                str(int(mk)): int(np.sum(boundary["mk"] == mk)) for mk in np.unique(boundary["mk"])
            },
        },
    }


def _endpoint_geometry(
    positions: np.ndarray,
    *,
    time_s: float,
    displacement: float | None,
    geometry: dict[str, Any],
) -> dict[str, Any]:
    xml = geometry["xml_geometry"]
    lower, upper = geometry["declared_bounds"]
    envelope = np.any((positions < lower - ENDPOINT_TOLERANCE_M) | (positions > upper + ENDPOINT_TOLERANCE_M), axis=1)
    slope_inside = points_inside_mesh(positions, geometry["slope_triangles"])
    blocks_inside = points_inside_mesh(positions, geometry["blocks_triangles"])
    piston_inside = np.zeros(len(positions), dtype=bool)
    bottom_below = np.zeros(len(positions), dtype=bool)
    if displacement is not None:
        piston = xml["boxes"].get("piston")
        if piston:
            piston_lower = np.asarray(piston["low"], dtype=np.float64) + np.asarray([displacement, 0.0, 0.0])
            piston_upper = piston_lower + np.asarray(piston["size"], dtype=np.float64)
            piston_inside = np.all((positions > piston_lower + ENDPOINT_TOLERANCE_M) & (positions < piston_upper - ENDPOINT_TOLERANCE_M), axis=1)
    bottom = xml["boxes"].get("bottom")
    if bottom:
        bottom_lower = np.asarray(bottom["low"], dtype=np.float64)
        bottom_upper = bottom_lower + np.asarray(bottom["size"], dtype=np.float64)
        bottom_below = (
            (positions[:, 2] < bottom_lower[2] - ENDPOINT_TOLERANCE_M)
            & (positions[:, 0] >= bottom_lower[0] - ENDPOINT_TOLERANCE_M)
            & (positions[:, 0] <= bottom_upper[0] + ENDPOINT_TOLERANCE_M)
            & (positions[:, 1] >= bottom_lower[1] - ENDPOINT_TOLERANCE_M)
            & (positions[:, 1] <= bottom_upper[1] + ENDPOINT_TOLERANCE_M)
        )
    entities = slope_inside | blocks_inside | piston_inside | bottom_below
    return {
        "generation_envelope_outside_count": int(envelope.sum()),
        "entity_penetration_count": int(entities.sum()),
        "entity_penetration_by_component": {
            "slope": int(slope_inside.sum()),
            "blocks": int(blocks_inside.sum()),
            "piston": int(piston_inside.sum()),
            "bottom": int(bottom_below.sum()),
        },
        "time_s": float(time_s) if math.isfinite(time_s) else None,
        "displacement_m": displacement,
    }


def _interval_geometry(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    d0: float | None,
    d1: float | None,
    geometry: dict[str, Any],
    particle_stride: int,
) -> dict[str, Any]:
    ids0, ids1 = previous["ids"], current["ids"]
    common, index0, index1 = np.intersect1d(ids0, ids1, assume_unique=True, return_indices=True)
    fluid0 = common >= FLUID_FIRST_ID
    index0, index1 = index0[fluid0], index1[fluid0]
    common = common[fluid0]
    if particle_stride > 1:
        selected = np.arange(0, len(common), particle_stride, dtype=np.int64)
        index0, index1, common = index0[selected], index1[selected], common[selected]
    p0, p1 = previous["position"][index0], current["position"][index1]
    if not len(p0):
        return {"chord_crossing_count": 0, "records": [], "particles_checked": 0, "common_fluid_particles": 0}
    total = 0
    records: list[dict[str, Any]] = []
    slope = segment_mesh_crossings(p0, p1, geometry["slope_triangles"], common)
    blocks = segment_mesh_crossings(p0, p1, geometry["blocks_triangles"], common)
    total += slope["count"] + blocks["count"]
    records.extend([{**record, "component": "slope"} for record in slope["records"]])
    records.extend([{**record, "component": "blocks"} for record in blocks["records"]])
    xml = geometry["xml_geometry"]
    bottom = xml["boxes"].get("bottom")
    if bottom:
        lower = np.asarray(bottom["low"], dtype=np.float64)
        upper = lower + np.asarray(bottom["size"], dtype=np.float64)
        direction = p1 - p0
        moving = np.abs(direction[:, 2]) > 1e-15
        fraction = np.full(len(p0), np.nan)
        fraction[moving] = (lower[2] - p0[moving, 2]) / direction[moving, 2]
        hit = moving & (fraction > 0.0) & (fraction < 1.0)
        crossing = p0 + fraction[:, None] * direction
        hit &= np.all((crossing[:, :2] >= lower[:2] - ENDPOINT_TOLERANCE_M) & (crossing[:, :2] <= upper[:2] + ENDPOINT_TOLERANCE_M), axis=1)
        count = int(hit.sum())
        total += count
        for index in np.flatnonzero(hit)[: max(0, 10 - len(records))]:
            records.append({"particle_id": int(common[index]), "point_index": int(index), "component": "bottom", "fraction": float(fraction[index])})
    if d0 is not None and d1 is not None:
        piston = xml["boxes"].get("piston")
        if piston:
            lower = np.asarray(piston["low"], dtype=np.float64)
            upper = lower + np.asarray(piston["size"], dtype=np.float64)
            rel0 = p0 - np.asarray([d0, 0.0, 0.0])
            rel1 = p1 - np.asarray([d1, 0.0, 0.0])
            hit = _segment_box_hits(rel0, rel1, lower, upper)
            count = int(hit.sum())
            total += count
            for index in np.flatnonzero(hit)[: max(0, 10 - len(records))]:
                records.append({"particle_id": int(common[index]), "point_index": int(index), "component": "piston"})
    return {
        "chord_crossing_count": int(total),
        "records": records[:10],
        "particles_checked": int(len(p0)),
        "common_fluid_particles": int(len(common)),
    }


def _reference_diagnostic(gauges: dict[str, dict[str, Any]], reference_path: Path) -> dict[str, Any]:
    if not Path(reference_path).is_file():
        return {"status": "pending_reference_missing", "path": relative(reference_path)}
    rows: list[list[float]] = []
    for line in Path(reference_path).read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        try:
            values = [float(value) for value in line.split()]
        except ValueError:
            continue
        if len(values) == 6 and np.isfinite(values).all():
            rows.append(values)
    reference = np.asarray(rows, dtype=np.float64)
    if reference.ndim != 2 or reference.shape[1] != 6 or len(reference) < 2 or np.any(np.diff(reference[:, 0]) < 0):
        return {"status": "pending_reference_invalid", "path": relative(reference_path)}
    times, inverse = np.unique(reference[:, 0], return_inverse=True)
    aggregate = np.zeros((len(times), 6), dtype=np.float64)
    aggregate[:, 0] = times
    for index in range(len(times)):
        aggregate[index, 1:] = reference[inverse == index, 1:].mean(axis=0)
    results: dict[str, Any] = {}
    for index, name in enumerate(("WG1", "WG2", "WG3", "WG4"), start=1):
        record = gauges.get(name)
        if record is None or record.get("data") is None or len(record["data"]) < 2:
            results[name] = {"status": "insufficient_model_rows"}
            continue
        model = record["data"]
        lo = max(float(model[0, 0]), float(times[0]))
        hi = min(float(model[-1, 0]), float(times[-1]))
        mask = (model[:, 0] >= lo) & (model[:, 0] <= hi)
        if hi <= lo or int(mask.sum()) < 2:
            results[name] = {"status": "insufficient_overlap"}
            continue
        model_eta = model[mask, 3] - model[0, 3]
        external = np.interp(model[mask, 0], times, aggregate[:, index])
        residual = model_eta - external
        results[name] = {
            "status": "computed_diagnostic_only",
            "overlap_start_s": float(model[mask, 0][0]),
            "overlap_end_s": float(model[mask, 0][-1]),
            "samples": int(mask.sum()),
            "rmse_m": float(np.sqrt(np.mean(residual**2))),
            "max_abs_m": float(np.max(np.abs(residual))),
        }
    computed = [row for row in results.values() if row.get("status") == "computed_diagnostic_only"]
    return {
        "status": "computed_diagnostic_only" if len(computed) == 4 else "partial_diagnostic_only",
        "path": relative(reference_path),
        "sha256": sha256(reference_path),
        "original_rows": int(len(reference)),
        "unique_time_rows": int(len(times)),
        "duplicate_transition_count": int(np.count_nonzero(np.diff(reference[:, 0]) == 0.0)),
        "fixed_time_origin": True,
        "gauges": results,
        "acceptance_status": "pending_preregistered_reference_envelope",
    }


def event_audit(gauges: dict[str, dict[str, Any]], reference_path: Path) -> dict[str, Any]:
    stats = {}
    for name in EXPECTED_GAUGES:
        row = gauges.get(name)
        if row is None:
            stats[name] = {"status": "missing"}
        else:
            stats[name] = {
                key: row.get(key)
                for key in ("rows", "time_start_s", "time_end_s", "swl_initial_m", "swl_min_m", "swl_max_m", "swl_peak_time_s", "dynamic_range_m", "issues")
            }
    runup = [stats[f"Run-up{i}"] for i in range(1, 8)]
    incident_available = all(stats[f"WG{i}"].get("status") != "missing" for i in range(1, 5))
    runup_available = all(item.get("status") != "missing" for item in runup)
    return {
        "incident_order": {
            "status": "pending_preregistered_threshold" if incident_available else "pending_missing_gauges",
            "condition": "WG1 then WG2 then WG3 under a root-bound incident threshold",
            "threshold_bound": False,
        },
        "runup_threshold": {
            "status": "pending_preregistered_threshold" if runup_available else "pending_missing_gauges",
            "condition": "run-up line exceeds the root-bound q-independent threshold",
            "threshold_bound": False,
            "diagnostic_peak_times_s": [item.get("swl_peak_time_s") for item in runup],
        },
        "return_threshold": {
            "status": "pending_preregistered_threshold" if runup_available else "pending_missing_gauges",
            "condition": "run-up returns below the root-bound threshold before 16 s",
            "threshold_bound": False,
        },
        "external_gauges": _reference_diagnostic(gauges, reference_path),
        "gauge_statistics": stats,
        "completion": "pending_event_thresholds_or_input_coverage",
    }


def _frame_result(frame: dict[str, Any]) -> dict[str, Any]:
    metadata = frame["metadata"]
    ids = frame["ids"]
    fluid = ids >= FLUID_FIRST_ID
    return {
        "index": int(re.search(r"(\d+)$", frame["path"].stem).group(1)),
        "path": relative(frame["path"]),
        "time_s": frame["time_s"],
        "particles": int(len(ids)),
        "fluid_particles": int(fluid.sum()),
        "ids_unique": bool(len(np.unique(ids)) == len(ids)),
        "finite_active_arrays": bool(
            np.isfinite(frame["position"]).all()
            and np.isfinite(frame["velocity"]).all()
            and np.isfinite(frame["density"]).all()
        ),
        "massfluid_kg": _float_metadata(metadata, "MassFluid"),
        "sha256": sha256(frame["path"]),
    }


def review(
    attempt: Path,
    *,
    contract: Path = DEFAULT_CONTRACT,
    preflight: Path | None = DEFAULT_PREFLIGHT,
    definition: Path = DEFAULT_DEFINITION,
    motion: Path = DEFAULT_MOTION,
    geometry_path: Path = DEFAULT_GEOMETRY,
    slope_path: Path | None = None,
    blocks_path: Path | None = None,
    reference: Path = DEFAULT_REFERENCE,
    decoder: Path = DEFAULT_DECODER,
    all_frames: bool = False,
    sample_count: int = SAMPLE_FRAME_COUNT,
    surface_particle_stride: int = DEFAULT_SURFACE_PARTICLE_STRIDE,
) -> dict[str, Any]:
    """Run a read-only F5 review and return a zero-credit report."""

    attempt = Path(attempt).resolve()
    solver = attempt / "product/solver"
    contract = Path(contract).resolve()
    preflight = Path(preflight).resolve() if preflight is not None else None
    definition = Path(definition).resolve()
    motion = Path(motion).resolve()
    geometry_path = Path(geometry_path).resolve()
    slope_path = (slope_path or definition.parent / "Slope.stl").resolve()
    blocks_path = (blocks_path or definition.parent / "Blocks_3D_scaled.stl").resolve()
    reference = Path(reference).resolve()
    decoder = Path(decoder).resolve()

    contract_data = validate_contract(contract)
    validate_contract_sources(
        contract_data,
        definition=definition,
        motion=motion,
        slope=slope_path,
        blocks=blocks_path,
        reference=reference,
    )
    preflight_data = (
        validate_preflight(preflight, definition=definition, motion=motion)
        if preflight is not None and preflight.is_file()
        else None
    )
    run = parse_run_out(solver / "Run.out")
    frames = frame_inventory(solver)
    gauges = gauge_audit(solver)
    run_window_gates = {
        "finished_code_zero": bool(run["finished_code_zero"]),
        "timemax_exact": bool(
            run["timemax_s"] is not None and math.isclose(run["timemax_s"], EXPECTED_TMAX_S, abs_tol=1.0e-9, rel_tol=0.0)
        ),
        "output_interval_exact": bool(
            len(run["output_dt_values_s"]) == 1
            and math.isclose(run["output_dt_values_s"][0], EXPECTED_TOUT_S, abs_tol=1.0e-9, rel_tol=0.0)
        ),
        "excluded_particles_zero": run["excluded_particles"] == 0,
    }
    runtime_complete = bool(
        all(run_window_gates.values())
        and frames["complete_expected_indices"]
        and gauges["all_expected"]
        and gauges["all_structural_gates"]
    )

    base: dict[str, Any] = {
        "schema": "core.f5.third_t1.solver_anchor_scientific_review.v1",
        "status": "scientific_review_pending_runtime_completion",
        "attempt": str(attempt),
        "case_id": EXPECTED_CASE_ID,
        "family": "F5",
        "coverage_policy": {
            "requested": "all_frames" if all_frames else "first_last_plus_uniform_sample",
            "sample_count": int(sample_count),
            "surface_particle_stride": int(surface_particle_stride),
            "missing_future_frames_are_not_inferred": True,
            "saved_chord_semantics": "linear chord between decoded saved endpoints; not an exact substep path",
        },
        "runtime": {
            "run_out": run,
            "run_window_gates": run_window_gates,
            "frames": {key: value for key, value in frames.items() if key != "paths"},
            "gauges": {key: value for key, value in gauges.items() if key != "records"},
            "complete_for_scientific_review": runtime_complete,
        },
        "inputs": {
            "contract": artifact(contract, "F5 fixed zero-credit definition contract"),
            "definition": artifact(definition, "F5 Definition"),
            "motion": artifact(motion, "F5 piston motion"),
            "static_boundary_vtk": artifact(geometry_path, "generated static MkCells geometry", required=False),
            "slope_stl": artifact(slope_path, "F5 slope geometry", required=False),
            "blocks_stl": artifact(blocks_path, "F5 blocks geometry", required=False),
            "reference": artifact(reference, "CIEMito external gauge reference", required=False),
        },
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "t1_credit": 0,
        "execution_controls": {
            "review_read_only": True,
            "solver_invoked_by_review": False,
            "gpu_started_by_review": False,
            "queue_mutation": 0,
            "root_review_mutation": 0,
            "job_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
        },
    }

    if not runtime_complete:
        base.update(
            {
                "coverage": {
                    "frames_available": frames["count"],
                    "frames_decoded": 0,
                    "decoded_indices": [],
                    "full_frame_coverage": False,
                    "full_particle_coverage": False,
                },
                "geometry": {
                    "status": "pending_runtime_completion",
                    "generation_envelope": "pending_runtime_completion",
                    "entity_penetration": "pending_runtime_completion",
                    "saved_chord_crossings": "pending_runtime_completion",
                    "domain_containment": "pending_runtime_completion",
                },
                "mass": {"status": "pending_runtime_completion"},
                "events": event_audit(gauges["records"], reference),
                "scientific_review_pending": [
                    "Run.out completion/window/exclusion gates and exact 801-frame/11-gauge coverage",
                    "sampled or full native geometry audit",
                    "full-window source-mass closure",
                    "incident/run-up/return thresholds not bound in current contract",
                ],
            }
        )
        return base

    if not decoder.is_file():
        raise FileNotFoundError(f"native decoder is required after runtime completion: {decoder}")
    if surface_particle_stride < 1:
        raise ValueError("surface_particle_stride must be positive")
    static = build_static_geometry(
        geometry_path=geometry_path,
        slope_path=slope_path,
        blocks_path=blocks_path,
        definition_path=definition,
        preflight=preflight_data,
    )
    motion_data = _parse_motion(motion)
    selected = select_frame_indices(frames["indices"], all_frames=all_frames, sample_count=sample_count)
    decode_all_for_gate = bool(all_frames and selected == frames["indices"] and frames["complete_expected_indices"])
    decoded_results: list[dict[str, Any]] = []
    endpoint_rows: list[dict[str, Any]] = []
    interval_rows: list[dict[str, Any]] = []
    mass_values: list[float] = []
    identity_reference: np.ndarray | None = None
    identity_mismatch_frames: list[int] = []
    time_mismatch_frames: list[int] = []
    nonfinite_frames: list[int] = []
    previous: dict[str, Any] | None = None
    previous_displacement: float | None = None
    with tempfile.TemporaryDirectory(prefix="f5-scientific-review-") as temporary:
        for frame_index in selected:
            current = decode_bi4(frames["paths"][frame_index], decoder, Path(temporary))
            decoded_results.append(_frame_result(current))
            if not decoded_results[-1]["finite_active_arrays"]:
                nonfinite_frames.append(int(frame_index))
            if identity_reference is None:
                identity_reference = current["ids"].copy()
            elif not np.array_equal(identity_reference, current["ids"]):
                identity_mismatch_frames.append(int(frame_index))
            fluid_mask = current["ids"] >= FLUID_FIRST_ID
            massfluid = _float_metadata(current["metadata"], "MassFluid")
            fluid_count = int(fluid_mask.sum())
            if massfluid is not None:
                mass_values.append(float(fluid_count * massfluid))
            time_s = current["time_s"]
            expected_time_s = float(frame_index * EXPECTED_TOUT_S)
            if time_s is None or not math.isclose(time_s, expected_time_s, abs_tol=5.0e-4, rel_tol=0.0):
                time_mismatch_frames.append(int(frame_index))
            displacement = motion_displacement(motion_data, time_s) if time_s is not None else None
            endpoint_rows.append(
                _endpoint_geometry(
                    current["position"][fluid_mask],
                    time_s=time_s if time_s is not None else math.nan,
                    displacement=displacement,
                    geometry=static,
                )
            )
            if previous is not None:
                interval_rows.append(
                    _interval_geometry(
                        previous,
                        current,
                        d0=previous_displacement,
                        d1=displacement,
                        geometry=static,
                        particle_stride=surface_particle_stride,
                    )
                )
            previous, previous_displacement = current, displacement

    endpoint_count = int(sum(row["entity_penetration_count"] for row in endpoint_rows))
    envelope_count = int(sum(row["generation_envelope_outside_count"] for row in endpoint_rows))
    crossing_count = int(sum(row["chord_crossing_count"] for row in interval_rows))
    by_component = {
        component: int(sum(row["entity_penetration_by_component"][component] for row in endpoint_rows))
        for component in ("slope", "blocks", "piston", "bottom")
    }
    full_frame_coverage = bool(decode_all_for_gate)
    full_particle_coverage = bool(surface_particle_stride == 1)
    complete_geometry_coverage = bool(full_frame_coverage and full_particle_coverage)
    identity_pass = not identity_mismatch_frames
    native_time_pass = not time_mismatch_frames
    finite_pass = not nonfinite_frames
    native_pass = identity_pass and native_time_pass and finite_pass
    geometry_status = "observed_pass" if complete_geometry_coverage and native_pass and endpoint_count == 0 and crossing_count == 0 else (
        "observed_fail" if complete_geometry_coverage else "pending_sampled_only"
    )
    initial_mass = mass_values[0] if mass_values else None
    mass_change = [((value - initial_mass) / initial_mass) for value in mass_values] if initial_mass else []
    max_mass_change = max((abs(value) for value in mass_change), default=None)
    mass_status = (
        "observed_pass_diagnostic_limit"
        if complete_geometry_coverage and native_pass and max_mass_change is not None and max_mass_change <= MASS_CHANGE_DIAGNOSTIC_LIMIT
        else "observed_fail_diagnostic_limit"
        if complete_geometry_coverage and (not native_pass or max_mass_change is not None)
        else "pending_sampled_only"
    )
    scientific_pending = [
        "incident order, run-up threshold, return threshold: no preregistered numerical threshold in current F5 contract",
        "external CIEMito acceptance envelope: diagnostic RMSE only; no release threshold is bound",
        "runtime-domain containment: Definition uses default simulationdomain bounds; only the static generation envelope was checked",
    ]
    if time_mismatch_frames:
        scientific_pending.append("native frame metadata time did not match its saved-frame index")
    if identity_mismatch_frames:
        scientific_pending.append("native particle identity changed between decoded frames")
    if nonfinite_frames:
        scientific_pending.append("native active arrays contained non-finite values")
    base.update(
        {
            "status": "scientific_review_complete_zero_credit" if complete_geometry_coverage else "scientific_review_sampled_pending_zero_credit",
            "coverage": {
                "frames_available": frames["count"],
                "frames_decoded": len(selected),
                "decoded_indices": selected,
                "full_frame_coverage": full_frame_coverage,
                "full_particle_coverage": full_particle_coverage,
                "complete_geometry_coverage": complete_geometry_coverage,
                "frame_selection": "all_available_frames" if all_frames else "first_last_plus_uniform_sample",
            },
            "static_geometry": static["summary"],
            "frames_decoded": decoded_results,
            "geometry": {
                "status": geometry_status,
                "endpoint_tolerance_m": ENDPOINT_TOLERANCE_M,
                "generation_envelope_outside_particle_frames": envelope_count,
                "entity_penetration_particle_frames": endpoint_count,
                "entity_penetration_by_component_particle_frames": by_component,
                "endpoint_geometry_by_frame": endpoint_rows,
                "saved_chord_crossing_count": crossing_count,
                "saved_chord_crossing_records": [record for row in interval_rows for record in row["records"]][:20],
                "saved_chord_interval_summary": [
                    {key: value for key, value in row.items() if key != "records"} for row in interval_rows
                ],
                "native_identity": {
                    "status": "observed_pass" if identity_pass else "observed_fail",
                    "reference_frame_index": int(selected[0]) if selected else None,
                    "mismatch_frame_indices": identity_mismatch_frames,
                },
                "native_time": {
                    "status": "observed_pass" if native_time_pass else "observed_fail",
                    "expected_interval_s": EXPECTED_TOUT_S,
                    "mismatch_frame_indices": time_mismatch_frames,
                },
                "native_finite": {
                    "status": "observed_pass" if finite_pass else "observed_fail",
                    "nonfinite_frame_indices": nonfinite_frames,
                },
                "intervals_checked": len(interval_rows),
                "surface_particles_checked": int(sum(row["particles_checked"] for row in interval_rows)),
                "surface_particle_stride": int(surface_particle_stride),
                "domain_containment": {
                    "status": "generation_envelope_observed" if complete_geometry_coverage else "generation_envelope_sampled",
                    "runtime_domain_contract": "not_explicitly_numeric_in_F5_Definition",
                    "generation_envelope_outside_count": envelope_count,
                },
            },
            "mass": {
                "status": mass_status,
                "massfluid_kg": mass_values[0] / max(decoded_results[0]["fluid_particles"], 1) if mass_values and decoded_results else None,
                "initial_fluid_mass_kg": initial_mass,
                "sampled_fluid_mass_kg": mass_values,
                "sampled_relative_change": mass_change,
                "maximum_abs_relative_change": max_mass_change,
                "diagnostic_limit_relative": MASS_CHANGE_DIAGNOSTIC_LIMIT,
                "contract_threshold_bound": False,
                "threshold_note": "F5 contract names full-window mass but does not bind a numeric tolerance; limit is diagnostic only.",
            },
            "events": event_audit(gauges["records"], reference),
            "scientific_review_pending": scientific_pending,
        }
    )
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument("--motion", type=Path, default=DEFAULT_MOTION)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY)
    parser.add_argument("--slope", type=Path)
    parser.add_argument("--blocks", type=Path)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--decoder", type=Path, default=DEFAULT_DECODER)
    parser.add_argument(
        "--all-frames",
        action="store_true",
        help="decode every frame that exists; combine with --surface-particle-stride 1 for the full geometry gate",
    )
    parser.add_argument("--sample-count", type=int, default=SAMPLE_FRAME_COUNT)
    parser.add_argument("--surface-particle-stride", type=int, default=DEFAULT_SURFACE_PARTICLE_STRIDE)
    args = parser.parse_args()
    report = review(
        args.attempt,
        contract=args.contract,
        preflight=args.preflight,
        definition=args.definition,
        motion=args.motion,
        geometry_path=args.geometry,
        slope_path=args.slope,
        blocks_path=args.blocks,
        reference=args.reference,
        decoder=args.decoder,
        all_frames=args.all_frames,
        sample_count=args.sample_count,
        surface_particle_stride=args.surface_particle_stride,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "qualification_claim": "none",
                "matrix_credit": 0,
                "t1_credit": 0,
                "frames_decoded": report.get("coverage", {}).get("frames_decoded", 0),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
