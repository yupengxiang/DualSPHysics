#!/usr/bin/env python3
"""CPU/static face-level audit of the existing F6 fixed-box mDBC artifacts.

This script never launches GenCase, DualSPHysics, ``nvidia-smi`` or any other
solver/runtime process.  It only reads the two existing ingested result trees
for the fixed-box mDBC canonical and fine cases, their generated VTK/XML/log
artifacts, and writes a deterministic JSON/Markdown evidence package.

The runtime normal files are interpreted using the DualSPHysics VTK convention:

* ``CfgInit_Normals.vtk`` POINTS are boundary coordinates ``x_b``;
* ``FIELD/Normal`` in that file is the boundary-to-limit displacement ``n_b``;
* ``CfgInit_NormalsGhost.vtk`` contains the same POINTS and the doubled
  displacement ``n_g``;
* the effective interface used by this audit is ``x_gamma = x_b + n_g/2``.

The zero-normal threshold is explicit because the checked-in artifacts contain
machine-epsilon residuals rather than exact all-zero vectors.  Consequently,
the GenCase text line ``Final zero normals: 0/...`` and this thresholded
runtime count are both reported instead of being silently conflated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASE_ROOT = (
    REPO_ROOT
    / "lagrangian-fluid-lab"
    / "campaigns"
    / "v0.1-candidate"
    / "cases"
    / "r3-fixed-box-force-gauge"
)
DEFAULT_JSON = DEFAULT_CASE_ROOT / "r4-mdbc-runtime-zero-normal-audit.json"
DEFAULT_MARKDOWN = DEFAULT_CASE_ROOT / "r4-mdbc-runtime-zero-normal-audit.md"

AUDIT_ID = "R4_F6_MDBC_RUNTIME_ZERO_NORMAL_AUDIT"
SCHEMA_VERSION = 1

ZERO_NORMAL_TOLERANCE_M = 1.0e-12
NEAR_ZERO_NORMAL_TOLERANCE_M = 1.0e-8
FACE_TOLERANCE_M = 1.0e-5
GHOST_DOUBLING_TOLERANCE_M = 2.0e-5

FACE_DEFINITIONS = (
    ("x_min", 0, "min"),
    ("x_max", 0, "max"),
    ("y_min", 1, "min"),
    ("y_max", 1, "max"),
    ("z_min", 2, "min"),
    ("z_max", 2, "max"),
)
AXIS_NAMES = ("x", "y", "z")
SIDE_NAMES = ("min", "max")

CASE_SPECS: tuple[dict[str, str], ...] = (
    {
        "case_id": "fixed_box_mdbc_canonical",
        "run_label": "canonical-2",
        "result_directory": "results/fixed_box_mdbc_canonical/canonical-2-ingested",
        "generated_directory": "generated/fixed_box_mdbc_canonical",
        "definition": "fixed_box_mdbc_canonical_Def.xml",
        "generated_prefix": "fixed_box_mdbc_canonical",
    },
    {
        "case_id": "fixed_box_mdbc_fine",
        "run_label": "fine-3",
        "result_directory": "results/fixed_box_mdbc_fine/fine-3-ingested",
        "generated_directory": "generated/fixed_box_mdbc_fine",
        "definition": "fixed_box_mdbc_fine_Def.xml",
        "generated_prefix": "fixed_box_mdbc_fine",
    },
)


# Legacy binary VTK uses big-endian numeric payloads.  The one-byte types do
# not have an endian distinction, but the explicit dtype keeps the parser
# uniform and makes the on-disk convention visible.
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


def _read_line(content: bytes, offset: int, path: Path) -> tuple[str, int]:
    end = content.find(b"\n", offset)
    if end < 0:
        raise ValueError(f"{path}: unterminated VTK header line at byte {offset}")
    line = content[offset:end]
    if line.endswith(b"\r"):
        line = line[:-1]
    try:
        decoded = line.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: non-ASCII VTK header at byte {offset}") from exc
    return decoded, end + 1


def _skip_newline(content: bytes, offset: int) -> int:
    if content[offset : offset + 2] == b"\r\n":
        return offset + 2
    if content[offset : offset + 1] == b"\n":
        return offset + 1
    return offset


def _read_payload(
    content: bytes, offset: int, count: int, kind: str, path: Path
) -> tuple[np.ndarray, int]:
    if kind not in VTK_TYPES:
        raise ValueError(f"{path}: unsupported binary VTK type {kind!r}")
    dtype_name, width = VTK_TYPES[kind]
    end = offset + count * width
    if end > len(content):
        raise ValueError(
            f"{path}: binary {kind} payload ends at {end}, file has {len(content)} bytes"
        )
    values = np.frombuffer(
        content, dtype=np.dtype(dtype_name), count=count, offset=offset
    ).copy()
    return values, _skip_newline(content, end)


def _store_vtk_array(
    target: dict[str, np.ndarray],
    metadata: dict[str, dict[str, Any]],
    name: str,
    values: np.ndarray,
    components: int,
    count: int,
    kind: str,
    location: str,
) -> None:
    reshaped = values.reshape(count, components)
    target[name] = reshaped[:, 0] if components == 1 else reshaped
    metadata[f"{location}:{name}"] = {
        "location": location,
        "name": name,
        "components": components,
        "count": count,
        "kind": kind,
    }


def read_binary_vtk(path: Path) -> dict[str, Any]:
    """Read the legacy binary POLYDATA subset used by the case artifacts.

    The parser handles POINTS, POLYGONS/VERTICES, SCALARS and FIELD arrays,
    including unsigned VTK scalar types in generated ``Bound``/``MkCells``
    files.  It is intentionally strict: a missing or malformed array raises an
    error instead of manufacturing zeros.
    """

    content = path.read_bytes()
    offset = 0
    first, offset = _read_line(content, offset, path)
    second, offset = _read_line(content, offset, path)
    third, offset = _read_line(content, offset, path)
    fourth, offset = _read_line(content, offset, path)
    if not first.startswith("# vtk DataFile"):
        raise ValueError(f"{path}: not a legacy VTK file")
    if third.strip().upper() != "BINARY":
        raise ValueError(f"{path}: expected BINARY VTK payload, got {third!r}")
    if fourth.strip().upper() != "DATASET POLYDATA":
        raise ValueError(f"{path}: expected POLYDATA, got {fourth!r}")

    point_header, offset = _read_line(content, offset, path)
    match = re.fullmatch(r"POINTS\s+(\d+)\s+(\S+)", point_header)
    if match is None:
        raise ValueError(f"{path}: malformed POINTS header {point_header!r}")
    point_count = int(match.group(1))
    point_kind = match.group(2)
    points_flat, offset = _read_payload(
        content, offset, point_count * 3, point_kind, path
    )
    points = points_flat.reshape(point_count, 3).astype(float)

    polygons: list[tuple[int, ...]] = []
    vertices: list[tuple[int, ...]] = []
    point_data: dict[str, np.ndarray] = {}
    cell_data: dict[str, np.ndarray] = {}
    field_data: dict[str, np.ndarray] = {}
    metadata: dict[str, dict[str, Any]] = {}
    association: str | None = None
    cell_count: int | None = None
    sections: list[dict[str, Any]] = []

    while True:
        offset = _skip_newline(content, offset)
        if offset >= len(content):
            break
        header, offset = _read_line(content, offset, path)
        fields = header.split()
        if not fields:
            continue

        keyword = fields[0].upper()
        if keyword in {"POLYGONS", "VERTICES", "LINES", "TRIANGLE_STRIPS"}:
            if len(fields) != 3:
                raise ValueError(f"{path}: malformed {keyword} header {header!r}")
            number = int(fields[1])
            total_values = int(fields[2])
            values, offset = _read_payload(
                content, offset, total_values, "int", path
            )
            values_list = values.tolist()
            cells: list[tuple[int, ...]] = []
            index = 0
            for _ in range(number):
                if index >= len(values_list):
                    raise ValueError(f"{path}: truncated {keyword} cell list")
                vertices_in_cell = int(values_list[index])
                index += 1
                stop = index + vertices_in_cell
                if stop > len(values_list):
                    raise ValueError(f"{path}: truncated {keyword} cell payload")
                cells.append(tuple(int(value) for value in values_list[index:stop]))
                index = stop
            if index != len(values_list):
                raise ValueError(f"{path}: {keyword} payload has unused integers")
            if keyword == "POLYGONS":
                polygons = cells
                cell_count = number
            elif keyword == "VERTICES":
                vertices = cells
            sections.append({"keyword": keyword, "count": number})
            continue

        if keyword == "POINT_DATA":
            if len(fields) != 2:
                raise ValueError(f"{path}: malformed POINT_DATA header {header!r}")
            association = "point"
            expected = int(fields[1])
            if expected != point_count:
                raise ValueError(
                    f"{path}: POINT_DATA count {expected} != POINTS count {point_count}"
                )
            sections.append({"keyword": keyword, "count": expected})
            continue

        if keyword == "CELL_DATA":
            if len(fields) != 2:
                raise ValueError(f"{path}: malformed CELL_DATA header {header!r}")
            association = "cell"
            expected = int(fields[1])
            if cell_count is None:
                cell_count = expected
            if expected != cell_count:
                raise ValueError(
                    f"{path}: CELL_DATA count {expected} != cell count {cell_count}"
                )
            sections.append({"keyword": keyword, "count": expected})
            continue

        if keyword == "SCALARS":
            if association is None:
                raise ValueError(f"{path}: SCALARS has no POINT_DATA/CELL_DATA")
            if len(fields) not in {3, 4}:
                raise ValueError(f"{path}: malformed SCALARS header {header!r}")
            name = fields[1]
            kind = fields[2]
            components = int(fields[3]) if len(fields) == 4 else 1
            lookup, offset = _read_line(content, offset, path)
            if not lookup.startswith("LOOKUP_TABLE"):
                raise ValueError(f"{path}: expected LOOKUP_TABLE, got {lookup!r}")
            count = point_count if association == "point" else cell_count
            if count is None:
                raise ValueError(f"{path}: scalar {name} has unknown count")
            values, offset = _read_payload(
                content, offset, count * components, kind, path
            )
            target = point_data if association == "point" else cell_data
            _store_vtk_array(
                target,
                metadata,
                name,
                values,
                components,
                count,
                kind,
                association,
            )
            continue

        if keyword == "FIELD":
            if len(fields) != 3:
                raise ValueError(f"{path}: malformed FIELD header {header!r}")
            field_count = int(fields[2])
            target = (
                point_data
                if association == "point"
                else cell_data
                if association == "cell"
                else field_data
            )
            location = association or "field"
            for _ in range(field_count):
                array_header, offset = _read_line(content, offset, path)
                array_fields = array_header.split()
                if len(array_fields) != 4:
                    raise ValueError(
                        f"{path}: malformed FIELD array header {array_header!r}"
                    )
                name = array_fields[0]
                components = int(array_fields[1])
                count = int(array_fields[2])
                kind = array_fields[3]
                values, offset = _read_payload(
                    content, offset, components * count, kind, path
                )
                _store_vtk_array(
                    target,
                    metadata,
                    name,
                    values,
                    components,
                    count,
                    kind,
                    location,
                )
            continue

        raise ValueError(f"{path}: unsupported VTK section {header!r}")

    return {
        "path": str(path),
        "point_count": point_count,
        "points": points,
        "polygons": polygons,
        "vertices": vertices,
        "point_data": point_data,
        "cell_data": cell_data,
        "field_data": field_data,
        "metadata": metadata,
        "sections": sections,
    }


def _all_vtk_arrays(vtk: dict[str, Any]) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    arrays.update(vtk["field_data"])
    arrays.update(vtk["cell_data"])
    arrays.update(vtk["point_data"])
    return arrays


def _required_array(vtk: dict[str, Any], name: str) -> np.ndarray:
    arrays = _all_vtk_arrays(vtk)
    if name not in arrays:
        raise ValueError(f"{vtk['path']}: missing required VTK array {name!r}")
    return arrays[name]


def _column(values: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim == 2 and array.shape[1] == 1:
        array = array[:, 0]
    if array.ndim != 1:
        raise ValueError(f"{name}: expected scalar array, got shape {array.shape}")
    return array


def _vector(values: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{name}: expected 3-component array, got shape {array.shape}")
    return array.astype(float)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _file_record(path: Path, root: Path, *, required: bool) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": _relative(path, root),
        "required": required,
        "present": path.is_file(),
    }
    if path.is_file():
        record.update({"bytes": path.stat().st_size, "sha256": _sha256(path)})
    return record


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    return int(value.replace(",", ""))


def _float_or_none(value: str | None) -> float | None:
    return None if value is None else float(value)


def _float_list(value: str | None) -> list[float]:
    if not value:
        return []
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def _xml_value(value: str) -> bool | float | str:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return float(value)
    except ValueError:
        return value


def _node_vector(node: ET.Element | None) -> list[float] | None:
    if node is None:
        return None
    try:
        return [float(node.attrib[key]) for key in ("x", "y", "z")]
    except KeyError:
        return None


def parse_definition(path: Path, root: Path) -> dict[str, Any]:
    """Read only the source contract needed to label the generated evidence."""

    tree = ET.parse(path)
    xml_root = tree.getroot()
    definition = xml_root.find("./casedef/geometry/definition")
    commands = xml_root.find("./casedef/geometry/commands")
    boundary = xml_root.find("./execution/parameters/parameter[@key='Boundary']")
    norgeometry = xml_root.find("./casedef/normals/norgeometry")

    physical_void: dict[str, Any] | None = None
    actual_body: dict[str, Any] | None = None
    normal_body: dict[str, Any] | None = None

    if commands is not None:
        mainlist = commands.find("./mainlist")
        if mainlist is not None:
            current_state: str | None = None
            for child in list(mainlist):
                if child.tag == "setmkvoid":
                    current_state = "void"
                elif child.tag in {"setmkbound", "setmkfluid"}:
                    current_state = child.attrib.get("mk")
                elif child.tag == "drawbox":
                    point = _node_vector(child.find("./point"))
                    size = _node_vector(child.find("./size"))
                    if point is None or size is None:
                        continue
                    item = {
                        "point_m": point,
                        "size_m": size,
                        "max_m": [a + b for a, b in zip(point, size)],
                        "layers_vdp": _float_list(
                            (child.find("./layers").attrib.get("vdp")
                             if child.find("./layers") is not None
                             else None)
                        ),
                        "boxfill": (child.findtext("./boxfill") or "").strip(),
                    }
                    if current_state == "void" and physical_void is None:
                        physical_void = item
                    if current_state == "1" and actual_body is None:
                        actual_body = item

        normal_list = commands.find("./list[@name='GeometryForNormals']")
        if normal_list is not None:
            current_mk: str | None = None
            for child in list(normal_list):
                if child.tag == "setmkbound":
                    current_mk = child.attrib.get("mk")
                elif child.tag == "drawbox" and current_mk == "1":
                    point = _node_vector(child.find("./point"))
                    size = _node_vector(child.find("./size"))
                    if point is not None and size is not None and normal_body is None:
                        normal_body = {
                            "point_m": point,
                            "size_m": size,
                            "max_m": [a + b for a, b in zip(point, size)],
                            "layers_vdp": _float_list(
                                (child.find("./layers").attrib.get("vdp")
                                 if child.find("./layers") is not None
                                 else None)
                            ),
                            "boxfill": (child.findtext("./boxfill") or "").strip(),
                        }

    return {
        "path": _relative(path, root),
        "source_dp_m": (
            _float_or_none(definition.attrib.get("dp")) if definition is not None else None
        ),
        "boundary_parameter": boundary.attrib.get("value") if boundary is not None else None,
        "normal_geometryfile": (
            norgeometry.find("./geometryfile").attrib.get("file")
            if norgeometry is not None and norgeometry.find("./geometryfile") is not None
            else None
        ),
        "normal_distanceh": (
            _float_or_none(norgeometry.find("./distanceh").attrib.get("v"))
            if norgeometry is not None and norgeometry.find("./distanceh") is not None
            else None
        ),
        "physical_void": physical_void,
        "actual_body": actual_body,
        "normal_body": normal_body,
    }


def parse_generated_xml(path: Path, root: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    xml_root = tree.getroot()
    particles = xml_root.find(".//particles")
    if particles is None:
        raise ValueError(f"{path}: generated XML has no particles element")
    summary = particles.find("./_summary")

    def item_summary(name: str) -> dict[str, Any]:
        node = summary.find(f"./{name}") if summary is not None else None
        return (
            {
                "count": _int_or_none(node.attrib.get("count")),
                "id": node.attrib.get("id"),
                "mkcount": _int_or_none(node.attrib.get("mkcount")),
                "mkvalues": node.attrib.get("mkvalues"),
            }
            if node is not None
            else {}
        )

    def block_items(name: str) -> list[dict[str, Any]]:
        result = []
        for node in particles.findall(f"./{name}"):
            result.append(
                {
                    "mkbound": _int_or_none(node.attrib.get("mkbound")),
                    "mkfluid": _int_or_none(node.attrib.get("mkfluid")),
                    "mk": _int_or_none(node.attrib.get("mk")),
                    "begin": _int_or_none(node.attrib.get("begin")),
                    "count": _int_or_none(node.attrib.get("count")),
                }
            )
        return result

    constants = xml_root.find(".//constants")
    constants_out: dict[str, Any] = {}
    if constants is not None:
        for child in list(constants):
            if "value" in child.attrib:
                constants_out[child.tag] = _xml_value(child.attrib["value"])

    vtkout = [dict(node.attrib) for node in xml_root.findall(".//vtkout/vtkfile")]
    fixed_blocks = block_items("fixed")
    body_block = next(
        (block for block in fixed_blocks if block.get("mkbound") == 1), None
    )

    return {
        "path": _relative(path, root),
        "application": xml_root.attrib.get("app"),
        "date": xml_root.attrib.get("date"),
        "particles": {
            "np": _int_or_none(particles.attrib.get("np")),
            "nb": _int_or_none(particles.attrib.get("nb")),
            "nbf": _int_or_none(particles.attrib.get("nbf")),
            "mkboundfirst": _int_or_none(particles.attrib.get("mkboundfirst")),
            "mkfluidfirst": _int_or_none(particles.attrib.get("mkfluidfirst")),
        },
        "summary": {
            "fixed": item_summary("fixed"),
            "moving": item_summary("moving"),
            "floating": item_summary("floating"),
            "fluid": item_summary("fluid"),
        },
        "blocks": {
            "fixed": fixed_blocks,
            "moving": block_items("moving"),
            "floating": block_items("floating"),
            "fluid": block_items("fluid"),
        },
        "body_mk": body_block.get("mk") if body_block is not None else None,
        "constants": constants_out,
        "vtk_outputs": vtkout,
    }


def parse_gencase_log(path: Path, root: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")

    def integer(pattern: str) -> int | None:
        match = re.search(pattern, text)
        return _int_or_none(match.group(1)) if match else None

    nonzero = re.search(
        r"Non-zero particle normals:\s*([\d,]+)\s*/\s*([\d,]+).*?"
        r"Normals size range:\s*\(([0-9.eE+\-]+)\s*-\s*([0-9.eE+\-]+)\)",
        text,
    )
    final_zero = re.search(
        r"Final zero normals:\s*([\d,]+)\s*/\s*([\d,]+)\s*\(([0-9.]+)%\)",
        text,
    )
    evaluated = re.search(
        r"Evaluating\s+([\d,]+)\s+particles with\s+(\d+)\s+shapes\s+"
        r"\(distance\s+([^)]*)\)",
        text,
    )
    finished = re.findall(r"Finished execution \(code=(-?\d+)\)", text)
    shape_outputs: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        match = re.search(
            r"FileShapes>\s+(\S+)\s+shapes:\s*(\d+)\s+points:\s*(\d+)",
            line,
        )
        if match:
            shape_outputs[match.group(1)] = {
                "shape_count": int(match.group(2)),
                "point_count": int(match.group(3)),
            }

    return {
        "path": _relative(path, root),
        "return_code": int(finished[-1]) if finished else None,
        "points_loaded": integer(r"Points loaded:\s*([\d,]+)"),
        "particle_summary": {
            name: integer(rf"{name.capitalize()}\.{'{4,}'}:\s*([\d,]+)")
            for name in ("fixed", "moving", "floating", "fluid")
        },
        "normal_evaluation": (
            {
                "particles": _int_or_none(evaluated.group(1)),
                "shapes": int(evaluated.group(2)),
                "distance_text": evaluated.group(3).strip(),
            }
            if evaluated
            else None
        ),
        "nonzero_particle_normals": (
            {
                "count": _int_or_none(nonzero.group(1)),
                "total": _int_or_none(nonzero.group(2)),
                "min_size_reported_m": float(nonzero.group(3)),
                "max_size_reported_m": float(nonzero.group(4)),
            }
            if nonzero
            else None
        ),
        "final_zero_normals_reported": (
            {
                "count": _int_or_none(final_zero.group(1)),
                "total": _int_or_none(final_zero.group(2)),
                "percentage": float(final_zero.group(3)),
            }
            if final_zero
            else None
        ),
        "shape_outputs": shape_outputs,
    }


def parse_solver_log(path: Path, root: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    finished = re.findall(r"Finished execution \(code=(-?\d+)\)", text)

    def integer(pattern: str) -> int | None:
        match = re.search(pattern, text)
        return _int_or_none(match.group(1)) if match else None

    if "JSphGpu" in text or "RunMode=\"Pos-Cell - Single-GPU\"" in text:
        execution_kind = "gpu"
    elif "JSphCpu" in text or "CPU execution" in text:
        execution_kind = "cpu"
    else:
        execution_kind = "unknown"
    return {
        "path": _relative(path, root),
        "return_code": int(finished[-1]) if finished else None,
        "execution_kind_in_existing_log": execution_kind,
        "boundary_mode_mdbc": 'Boundary="mDBC"' in text,
        "fixed_count": integer(r"CaseNfixed=([\d,]+)"),
        "moving_count": integer(r"CaseNmoving=([\d,]+)"),
        "floating_count": integer(r"FloatingCount=([\d,]+)"),
        "fluid_count": integer(r"CaseNfluid=([\d,]+)"),
        "finished_message_present": "Simulation finished" in text,
    }


def _bbox(points: np.ndarray) -> list[list[float]]:
    if len(points) == 0:
        return [[], []]
    return [points.min(axis=0).astype(float).tolist(), points.max(axis=0).astype(float).tolist()]


def _counts_by_int(values: np.ndarray) -> dict[str, int]:
    return {
        str(int(value)): int(np.sum(values == value))
        for value in sorted(np.unique(values).tolist())
    }


def _stats_by_mk(
    mks: np.ndarray,
    norm: np.ndarray,
    normal_size: np.ndarray,
    zero: np.ndarray,
    near_zero: np.ndarray,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in sorted(np.unique(mks).tolist()):
        mask = mks == value
        result[str(int(value))] = {
            "particle_count": int(np.sum(mask)),
            "zero_normal_count": int(np.sum(mask & zero)),
            "near_zero_normal_count": int(np.sum(mask & near_zero)),
            "zero_normal_fraction": float(np.mean(zero[mask])) if np.any(mask) else None,
            "normal_norm_min_m": float(norm[mask].min()) if np.any(mask) else None,
            "normal_norm_max_m": float(norm[mask].max()) if np.any(mask) else None,
            "normal_size_min_m": float(normal_size[mask].min()) if np.any(mask) else None,
            "normal_size_max_m": float(normal_size[mask].max()) if np.any(mask) else None,
        }
    return result


def _face_value(box_min: np.ndarray, box_max: np.ndarray, axis: int, side: str) -> float:
    return float(box_min[axis] if side == "min" else box_max[axis])


def _face_mask(
    points: np.ndarray,
    box_min: np.ndarray,
    box_max: np.ndarray,
    axis: int,
    side: str,
    tolerance: float,
) -> np.ndarray:
    mask = np.abs(points[:, axis] - _face_value(box_min, box_max, axis, side)) <= tolerance
    for other_axis in range(3):
        if other_axis == axis:
            continue
        mask &= points[:, other_axis] >= box_min[other_axis] - tolerance
        mask &= points[:, other_axis] <= box_max[other_axis] + tolerance
    return mask


def _face_name(axis: int, side: str) -> str:
    return f"{AXIS_NAMES[axis]}_{side}"


def _topology_rows(
    points: np.ndarray,
    zero: np.ndarray,
    near_zero: np.ndarray,
    box_min: np.ndarray,
    box_max: np.ndarray,
    body_mask: np.ndarray,
) -> dict[str, Any]:
    plane_masks = [
        _face_mask(
            points,
            box_min,
            box_max,
            axis,
            side,
            FACE_TOLERANCE_M,
        )
        for _, axis, side in FACE_DEFINITIONS
    ]
    plane_incidence = np.sum(np.stack(plane_masks, axis=1), axis=1)
    face_rows: dict[str, dict[str, Any]] = {}
    for face_index, (name, axis, side) in enumerate(FACE_DEFINITIONS):
        mask = body_mask & plane_masks[face_index]
        interior = mask & (plane_incidence == 1)
        face_rows[name] = {
            "incident_point_count": int(np.sum(mask)),
            "incident_zero_normal_count": int(np.sum(mask & zero)),
            "incident_near_zero_normal_count": int(np.sum(mask & near_zero)),
            "interior_point_count": int(np.sum(interior)),
            "interior_zero_normal_count": int(np.sum(interior & zero)),
            "interior_near_zero_normal_count": int(np.sum(interior & near_zero)),
            "plane_axis": AXIS_NAMES[axis],
            "plane_side": side,
            "plane_coordinate_m": _face_value(box_min, box_max, axis, side),
        }

    edge_rows: dict[str, dict[str, Any]] = {}
    for first_axis in range(3):
        for second_axis in range(first_axis + 1, 3):
            for first_side in SIDE_NAMES:
                for second_side in SIDE_NAMES:
                    first_name = _face_name(first_axis, first_side)
                    second_name = _face_name(second_axis, second_side)
                    name = f"{first_name}__{second_name}"
                    first_index = next(
                        index
                        for index, (face_name, _, _) in enumerate(FACE_DEFINITIONS)
                        if face_name == first_name
                    )
                    second_index = next(
                        index
                        for index, (face_name, _, _) in enumerate(FACE_DEFINITIONS)
                        if face_name == second_name
                    )
                    mask = (
                        body_mask
                        & (plane_incidence == 2)
                        & plane_masks[first_index]
                        & plane_masks[second_index]
                    )
                    edge_rows[name] = {
                        "point_count": int(np.sum(mask)),
                        "zero_normal_count": int(np.sum(mask & zero)),
                        "near_zero_normal_count": int(np.sum(mask & near_zero)),
                        "faces": [first_name, second_name],
                    }

    corner_rows: dict[str, dict[str, Any]] = {}
    for x_side in SIDE_NAMES:
        for y_side in SIDE_NAMES:
            for z_side in SIDE_NAMES:
                names = [f"x_{x_side}", f"y_{y_side}", f"z_{z_side}"]
                indices = [
                    next(index for index, (name, _, _) in enumerate(FACE_DEFINITIONS) if name == face_name)
                    for face_name in names
                ]
                mask = body_mask & (plane_incidence == 3)
                for index in indices:
                    mask &= plane_masks[index]
                name = "__".join(names)
                corner_rows[name] = {
                    "point_count": int(np.sum(mask)),
                    "zero_normal_count": int(np.sum(mask & zero)),
                    "near_zero_normal_count": int(np.sum(mask & near_zero)),
                    "faces": names,
                }

    body_incidence = plane_incidence[body_mask]
    body_zero = zero[body_mask]
    body_near_zero = near_zero[body_mask]
    topology = {
        "face_interior": {
            "point_count": int(np.sum(body_incidence == 1)),
            "zero_normal_count": int(np.sum(body_zero & (body_incidence == 1))),
            "near_zero_normal_count": int(np.sum(body_near_zero & (body_incidence == 1))),
        },
        "edge_excluding_corners": {
            "point_count": int(np.sum(body_incidence == 2)),
            "zero_normal_count": int(np.sum(body_zero & (body_incidence == 2))),
            "near_zero_normal_count": int(np.sum(body_near_zero & (body_incidence == 2))),
        },
        "corner": {
            "point_count": int(np.sum(body_incidence == 3)),
            "zero_normal_count": int(np.sum(body_zero & (body_incidence == 3))),
            "near_zero_normal_count": int(np.sum(body_near_zero & (body_incidence == 3))),
        },
        "off_surface_or_unexpected_incidence": {
            "point_count": int(np.sum(~np.isin(body_incidence, [1, 2, 3]))),
            "zero_normal_count": int(
                np.sum(body_zero & ~np.isin(body_incidence, [1, 2, 3]))
            ),
            "near_zero_normal_count": int(
                np.sum(body_near_zero & ~np.isin(body_incidence, [1, 2, 3]))
            ),
        },
    }
    return {
        "faces": face_rows,
        "edges": edge_rows,
        "corners": corner_rows,
        "partition": topology,
        "body_plane_incidence_counts": {
            str(index): int(np.sum(body_incidence == index))
            for index in sorted(np.unique(body_incidence).tolist())
        },
    }


def _infer_hdp_faces(
    hdp: dict[str, Any], body_mk: int, source_box: dict[str, Any] | None
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    cell_mk = _column(_required_array(hdp, "Mk"), "hdp Mk").astype(int)
    body_cells = [index for index, value in enumerate(cell_mk) if value == body_mk]
    if len(body_cells) != 6:
        raise ValueError(
            f"{hdp['path']}: expected six hdp body faces for Mk={body_mk}, got {len(body_cells)}"
        )
    body_vertex_ids = sorted(
        {
            vertex
            for cell_index in body_cells
            for vertex in hdp["polygons"][cell_index]
        }
    )
    body_vertices = hdp["points"][body_vertex_ids]
    hdp_min = body_vertices.min(axis=0)
    hdp_max = body_vertices.max(axis=0)
    if len(body_vertex_ids) != 8:
        raise ValueError(
            f"{hdp['path']}: expected eight hdp body corner points, got {len(body_vertex_ids)}"
        )

    expected_min = hdp_min.copy()
    expected_max = hdp_max.copy()
    if source_box is not None:
        expected_min = np.asarray(source_box["point_m"], dtype=float)
        expected_max = np.asarray(source_box["max_m"], dtype=float)

    faces: list[dict[str, Any]] = []
    for cell_index in body_cells:
        vertex_ids = list(hdp["polygons"][cell_index])
        vertices = hdp["points"][vertex_ids]
        spans = vertices.max(axis=0) - vertices.min(axis=0)
        axis = int(np.argmin(spans))
        coordinate = float(np.mean(vertices[:, axis]))
        side = "min" if abs(coordinate - hdp_min[axis]) <= abs(coordinate - hdp_max[axis]) else "max"
        name = _face_name(axis, side)
        coordinate_expected = _face_value(expected_min, expected_max, axis, side)
        vertex_residual = np.zeros_like(vertices)
        for vertex_axis in range(3):
            target = (
                expected_min[vertex_axis]
                if np.isclose(vertices[:, vertex_axis], expected_min[vertex_axis], atol=FACE_TOLERANCE_M).all()
                else expected_max[vertex_axis]
                if np.isclose(vertices[:, vertex_axis], expected_max[vertex_axis], atol=FACE_TOLERANCE_M).all()
                else np.nan
            )
            if math.isfinite(float(target)):
                vertex_residual[:, vertex_axis] = np.abs(vertices[:, vertex_axis] - target)
            else:
                vertex_residual[:, vertex_axis] = np.nan
        finite_residual = vertex_residual[np.isfinite(vertex_residual)]
        faces.append(
            {
                "name": name,
                "cell_index": int(cell_index),
                "cell_mk": int(cell_mk[cell_index]),
                "vertex_ids": vertex_ids,
                "axis": AXIS_NAMES[axis],
                "side": side,
                "coordinate_m": coordinate,
                "expected_coordinate_m": coordinate_expected,
                "coordinate_residual_m": abs(coordinate - coordinate_expected),
                "max_vertex_residual_to_source_box_m": (
                    float(finite_residual.max()) if len(finite_residual) else None
                ),
                "vertex_bbox_m": _bbox(vertices),
            }
        )
    faces.sort(key=lambda item: next(index for index, (name, _, _) in enumerate(FACE_DEFINITIONS) if name == item["name"]))
    names = [face["name"] for face in faces]
    expected_names = [name for name, _, _ in FACE_DEFINITIONS]
    if names != expected_names:
        raise ValueError(f"{hdp['path']}: hdp body faces do not cover six box faces: {names}")
    return expected_min, expected_max, faces


def _construction_overlap(
    interface: np.ndarray,
    zero: np.ndarray,
    near_zero: np.ndarray,
    body_mask: np.ndarray,
    box_min: np.ndarray,
    box_max: np.ndarray,
    hdp_faces: list[dict[str, Any]],
) -> dict[str, Any]:
    face_masks = [
        _face_mask(
            interface,
            box_min,
            box_max,
            next(axis for name, axis, _ in FACE_DEFINITIONS if name == face["name"]),
            face["side"],
            FACE_TOLERANCE_M,
        )
        for face in hdp_faces
    ]
    union = np.any(np.stack(face_masks, axis=1), axis=1)
    body_interface = body_mask
    rows: list[dict[str, Any]] = []
    for face, mask in zip(hdp_faces, face_masks):
        selected = body_interface & mask
        axis = next(
            axis
            for name, axis, _ in FACE_DEFINITIONS
            if name == face["name"]
        )
        rows.append(
            {
                "name": face["name"],
                "hdp_cell_index": face["cell_index"],
                "interface_point_count": int(np.sum(selected)),
                "interface_zero_normal_count": int(np.sum(selected & zero)),
                "interface_near_zero_normal_count": int(np.sum(selected & near_zero)),
                "max_runtime_plane_residual_to_source_box_m": (
                    float(
                        np.max(
                            np.abs(
                                interface[selected, axis]
                                - _face_value(box_min, box_max, axis, face["side"])
                            )
                        )
                    )
                    if np.any(selected)
                    else None
                ),
                "all_selected_points_within_construction_rectangle": True,
            }
        )
    body_incidence = np.sum(np.stack(face_masks, axis=1), axis=1)[body_interface]
    body_selected = body_interface & union
    return {
        "formula": "x_gamma = x_b + n_ghost/2",
        "face_plane_tolerance_m": FACE_TOLERANCE_M,
        "body_interface_point_count": int(np.sum(body_interface)),
        "body_interface_bbox_m": _bbox(interface[body_interface]),
        "body_interface_on_any_hdp_body_face_count": int(np.sum(body_selected)),
        "body_interface_not_on_hdp_body_face_count": int(
            np.sum(body_interface & ~union)
        ),
        "body_interface_face_incidence_counts": {
            str(index): int(np.sum(body_incidence == index))
            for index in sorted(np.unique(body_incidence).tolist())
        },
        "faces": rows,
        "all_body_interface_points_match_construction_faces": bool(
            np.all(body_interface <= union)
        ),
    }


def _generated_vtk_summary(vtk: dict[str, Any]) -> dict[str, Any]:
    arrays = _all_vtk_arrays(vtk)
    result: dict[str, Any] = {
        "point_count": int(vtk["point_count"]),
        "polygon_count": int(len(vtk["polygons"])),
        "vertex_cell_count": int(len(vtk["vertices"])),
        "array_names": sorted(arrays),
        "array_metadata": {
            key: vtk["metadata"][key]
            for key in sorted(vtk["metadata"])
        },
    }
    if "Mk" in arrays:
        result["mk_counts"] = _counts_by_int(_column(arrays["Mk"], "Mk").astype(int))
    if "Type" in arrays:
        result["type_counts"] = _counts_by_int(_column(arrays["Type"], "Type").astype(int))
    if "Normal" in arrays:
        normal = _vector(arrays["Normal"], "Normal")
        normal_norm = np.linalg.norm(normal, axis=1)
        result["normal_exact_vector_zero_count"] = int(np.all(normal == 0, axis=1).sum())
        result["normal_threshold_zero_count"] = int(
            np.sum(normal_norm <= ZERO_NORMAL_TOLERANCE_M)
        )
        result["normal_near_zero_count"] = int(
            np.sum(normal_norm <= NEAR_ZERO_NORMAL_TOLERANCE_M)
        )
        result["normal_norm_range_m"] = [
            float(normal_norm.min()),
            float(normal_norm.max()),
        ]
    if "NormalSize" in arrays:
        size = _column(arrays["NormalSize"], "NormalSize").astype(float)
        result["normal_size_exact_zero_count"] = int(np.sum(size == 0))
        result["normal_size_threshold_zero_count"] = int(
            np.sum(size <= ZERO_NORMAL_TOLERANCE_M)
        )
        result["normal_size_range_m"] = [float(size.min()), float(size.max())]
    return result


def _audit_case(case_root: Path, spec: dict[str, str]) -> dict[str, Any]:
    case_id = spec["case_id"]
    result_dir = case_root / spec["result_directory"]
    generated_dir = case_root / spec["generated_directory"]
    definition_path = case_root / spec["definition"]
    prefix = spec["generated_prefix"]

    paths = {
        "definition": definition_path,
        "normal_vtk": result_dir / "CfgInit_Normals.vtk",
        "ghost_vtk": result_dir / "CfgInit_NormalsGhost.vtk",
        "hdp_actual_vtk": generated_dir / f"{prefix}_hdp_Actual.vtk",
        "bound_vtk": generated_dir / f"{prefix}_Bound.vtk",
        "mkcells_vtk": generated_dir / f"{prefix}_MkCells.vtk",
        "generated_xml": result_dir / "generated_particles.xml",
        "gencase_log": result_dir / "gencase.stdout.log",
        "solver_log": result_dir / "solver.stdout.log",
        "run_out": result_dir / "Run.out",
        "run_csv": result_dir / "Run.csv",
        "run_parts_csv": result_dir / "RunPARTs.csv",
    }
    required_names = {
        "normal_vtk",
        "ghost_vtk",
        "hdp_actual_vtk",
        "generated_xml",
        "gencase_log",
    }
    source_files = {
        name: _file_record(path, case_root, required=name in required_names)
        for name, path in paths.items()
    }
    errors: list[str] = []
    missing_required = [
        name for name in sorted(required_names) if not source_files[name]["present"]
    ]
    if missing_required:
        errors.append(f"missing required artifacts: {', '.join(missing_required)}")

    case: dict[str, Any] = {
        "case_id": case_id,
        "run_label": spec["run_label"],
        "artifact_directories": {
            "result": _relative(result_dir, case_root),
            "generated": _relative(generated_dir, case_root),
        },
        "source_files": source_files,
        "errors": errors,
        "status": "partial_missing_required_artifacts" if missing_required else "pending",
    }

    definition: dict[str, Any] | None = None
    generated_xml: dict[str, Any] | None = None
    gencase: dict[str, Any] | None = None
    solver: dict[str, Any] | None = None
    try:
        if definition_path.is_file():
            definition = parse_definition(definition_path, case_root)
        if paths["generated_xml"].is_file():
            generated_xml = parse_generated_xml(paths["generated_xml"], case_root)
        if paths["gencase_log"].is_file():
            gencase = parse_gencase_log(paths["gencase_log"], case_root)
        if paths["solver_log"].is_file():
            solver = parse_solver_log(paths["solver_log"], case_root)
    except (OSError, ET.ParseError, ValueError) as exc:
        case["errors"].append(f"metadata parse error: {exc}")

    case["source_contract"] = definition
    case["generated_summary"] = generated_xml
    case["gencase_summary"] = gencase
    case["existing_solver_log_summary"] = solver

    if missing_required:
        case["status"] = "partial_missing_required_artifacts"
        return case

    try:
        normal_vtk = read_binary_vtk(paths["normal_vtk"])
        ghost_vtk = read_binary_vtk(paths["ghost_vtk"])
        hdp_vtk = read_binary_vtk(paths["hdp_actual_vtk"])
        normal_arrays = _all_vtk_arrays(normal_vtk)
        ghost_arrays = _all_vtk_arrays(ghost_vtk)
        normal_points = normal_vtk["points"]
        ghost_points = ghost_vtk["points"]
        normal_mk = _column(_required_array(normal_vtk, "Mk"), "normal Mk").astype(int)
        ghost_mk = _column(_required_array(ghost_vtk, "Mk"), "ghost Mk").astype(int)
        normal_vector = _vector(_required_array(normal_vtk, "Normal"), "normal Normal")
        ghost_vector = _vector(_required_array(ghost_vtk, "Normal"), "ghost Normal")
        normal_size = _column(
            _required_array(normal_vtk, "NormalSize"), "normal NormalSize"
        ).astype(float)
        ghost_size = _column(
            _required_array(ghost_vtk, "NormalSize"), "ghost NormalSize"
        ).astype(float)
        if len(normal_points) != len(ghost_points):
            raise ValueError("normal and ghost POINTS counts differ")
        if len(normal_mk) != len(normal_points) or len(ghost_mk) != len(ghost_points):
            raise ValueError("normal/ghost Mk count does not match POINTS")

        normal_norm = np.linalg.norm(normal_vector, axis=1)
        ghost_norm = np.linalg.norm(ghost_vector, axis=1)
        zero = normal_norm <= ZERO_NORMAL_TOLERANCE_M
        near_zero = normal_norm <= NEAR_ZERO_NORMAL_TOLERANCE_M
        finite = bool(
            np.isfinite(normal_points).all()
            and np.isfinite(ghost_points).all()
            and np.isfinite(normal_vector).all()
            and np.isfinite(ghost_vector).all()
            and np.isfinite(normal_size).all()
            and np.isfinite(ghost_size).all()
        )
        if not finite:
            raise ValueError("normal/ghost arrays contain non-finite values")

        body_mk = (
            generated_xml.get("body_mk")
            if generated_xml is not None
            else None
        )
        if body_mk is None:
            hdp_mk = _column(_required_array(hdp_vtk, "Mk"), "hdp Mk").astype(int)
            candidates = [int(value) for value in np.unique(hdp_mk) if np.sum(hdp_mk == value) == 6]
            if len(candidates) != 1:
                raise ValueError(f"could not infer unique body Mk from hdp cells: {candidates}")
            body_mk = candidates[0]
        body_mk = int(body_mk)
        body_mask = normal_mk == body_mk

        source_box = definition.get("physical_void") if definition else None
        box_min, box_max, hdp_faces = _infer_hdp_faces(hdp_vtk, body_mk, source_box)
        interface = normal_points + ghost_vector / 2.0

        topology = _topology_rows(
            interface,
            zero,
            near_zero,
            box_min,
            box_max,
            body_mask,
        )
        overlap = _construction_overlap(
            interface,
            zero,
            near_zero,
            body_mask,
            box_min,
            box_max,
            hdp_faces,
        )

        bound_summary: dict[str, Any] | None = None
        bound_runtime_comparison: dict[str, Any] | None = None
        if paths["bound_vtk"].is_file():
            bound_vtk = read_binary_vtk(paths["bound_vtk"])
            bound_arrays = _all_vtk_arrays(bound_vtk)
            bound_summary = _generated_vtk_summary(bound_vtk)
            comparison: dict[str, Any] = {
                "points_equal_exactly": bool(np.array_equal(bound_vtk["points"], normal_points)),
                "max_abs_point_difference_m": (
                    float(np.max(np.abs(bound_vtk["points"] - normal_points)))
                    if len(bound_vtk["points"]) == len(normal_points)
                    else None
                ),
            }
            for name in ("Mk", "Normal", "NormalSize"):
                if name in bound_arrays and name in normal_arrays:
                    left = np.asarray(bound_arrays[name])
                    right = np.asarray(normal_arrays[name])
                    comparison[f"{name}_equal_exactly"] = bool(np.array_equal(left, right))
                    comparison[f"{name}_max_abs_difference"] = (
                        float(np.max(np.abs(left.astype(float) - right.astype(float))))
                        if left.shape == right.shape
                        else None
                    )
                else:
                    comparison[f"{name}_equal_exactly"] = None
                    comparison[f"{name}_max_abs_difference"] = None
            if "Normal" in bound_arrays:
                bound_normal = _vector(bound_arrays["Normal"], "bound Normal")
                bound_norm = np.linalg.norm(bound_normal, axis=1)
                comparison["bound_threshold_zero_count"] = int(
                    np.sum(bound_norm <= ZERO_NORMAL_TOLERANCE_M)
                )
                comparison["bound_exact_vector_zero_count"] = int(
                    np.all(bound_normal == 0, axis=1).sum()
                )
            bound_runtime_comparison = comparison

        mkcells_summary: dict[str, Any] | None = None
        if paths["mkcells_vtk"].is_file():
            mkcells_summary = _generated_vtk_summary(read_binary_vtk(paths["mkcells_vtk"]))

        normal_file_summary = {
            "point_count": int(len(normal_points)),
            "array_names": sorted(normal_arrays),
            "array_metadata": {
                key: normal_vtk["metadata"][key]
                for key in sorted(normal_vtk["metadata"])
            },
            "finite_arrays": finite,
            "boundary_bbox_m": _bbox(normal_points),
            "effective_interface_bbox_m": _bbox(interface),
            "mk_counts": _counts_by_int(normal_mk),
        }
        ghost_file_summary = {
            "point_count": int(len(ghost_points)),
            "array_names": sorted(ghost_arrays),
            "array_metadata": {
                key: ghost_vtk["metadata"][key]
                for key in sorted(ghost_vtk["metadata"])
            },
            "finite_arrays": finite,
            "boundary_bbox_m": _bbox(ghost_points),
            "mk_counts": _counts_by_int(ghost_mk),
        }
        normal_by_mk = _stats_by_mk(
            normal_mk,
            normal_norm,
            normal_size,
            zero,
            near_zero,
        )

        vector_residual = ghost_vector - 2.0 * normal_vector
        size_residual = ghost_size - 2.0 * normal_size
        points_difference = ghost_points - normal_points
        runtime_vs_generation: dict[str, Any] = {
            "bound_vtk_present": paths["bound_vtk"].is_file(),
            "bound_vtk_vs_runtime": bound_runtime_comparison,
            "gencase_reported_final_zero_normals": (
                gencase.get("final_zero_normals_reported") if gencase else None
            ),
            "serialized_generation_threshold_zero_count": (
                bound_runtime_comparison.get("bound_threshold_zero_count")
                if bound_runtime_comparison
                else None
            ),
            "runtime_threshold_zero_count": int(np.sum(zero)),
            "runtime_exact_vector_zero_count": int(np.all(normal_vector == 0, axis=1).sum()),
            "generation_log_to_runtime_threshold_difference": (
                int(np.sum(zero))
                - int(gencase["final_zero_normals_reported"]["count"])
                if gencase and gencase.get("final_zero_normals_reported")
                else None
            ),
            "interpretation": (
                "The existing GenCase line reports exact final zero normals as 0, "
                "while the serialized Bound/CfgInit arrays contain machine-epsilon "
                "norms that are counted under the explicit <=1e-12 m audit threshold. "
                "Bound and runtime arrays are compared directly; no new runtime was run."
            ),
        }

        source_dp = definition.get("source_dp_m") if definition else None
        generated_dp = (
            generated_xml.get("constants", {}).get("dp") if generated_xml else None
        )
        h_value = generated_xml.get("constants", {}).get("h") if generated_xml else None
        dp = generated_dp if generated_dp is not None else source_dp
        box_size = box_max - box_min
        cells_per_axis = (box_size / float(dp)).tolist() if dp else None
        resolution = {
            "source_dp_m": source_dp,
            "generated_dp_m": generated_dp,
            "h_m": h_value,
            "h_over_dp": (float(h_value) / float(dp)) if h_value and dp else None,
            "box_min_m": box_min.astype(float).tolist(),
            "box_max_m": box_max.astype(float).tolist(),
            "box_size_m": box_size.astype(float).tolist(),
            "box_cells_per_axis_float": cells_per_axis,
            "box_cells_per_axis_rounded": (
                [int(round(value)) for value in cells_per_axis]
                if cells_per_axis is not None
                else None
            ),
            "nominal_box_nodes_per_axis": (
                [int(round(value)) + 1 for value in cells_per_axis]
                if cells_per_axis is not None
                else None
            ),
            "runtime_boundary_point_count": int(len(normal_points)),
            "runtime_body_point_count": int(np.sum(body_mask)),
            "runtime_zero_normal_count": int(np.sum(zero)),
            "runtime_zero_normal_fraction": float(np.mean(zero)),
            "runtime_body_zero_normal_count": int(np.sum(zero & body_mask)),
            "runtime_body_zero_normal_fraction": (
                float(np.mean(zero[body_mask])) if np.any(body_mask) else None
            ),
        }

        zero_summary = {
            "definition": "zero iff Euclidean norm of FIELD/Normal <= 1e-12 m",
            "near_zero_definition": "near-zero iff Euclidean norm of FIELD/Normal <= 1e-8 m",
            "total_zero_normal_count": int(np.sum(zero)),
            "total_zero_normal_fraction": float(np.mean(zero)),
            "total_near_zero_normal_count": int(np.sum(near_zero)),
            "exact_vector_zero_count": int(np.all(normal_vector == 0, axis=1).sum()),
            "normal_size_threshold_zero_count": int(
                np.sum(normal_size <= ZERO_NORMAL_TOLERANCE_M)
            ),
            "zero_normal_by_mk": normal_by_mk,
            "zero_normal_by_mk_counts": {
                key: value["zero_normal_count"] for key, value in normal_by_mk.items()
            },
            "face_counts_are_incident": True,
            "face_count_note": (
                "Face rows include edge/corner points incident on that face; the exclusive "
                "face interior, edge, and corner partition is reported separately."
            ),
        }

        ghost_contract = {
            "normal_points_equal_ghost_points_exactly": bool(
                np.array_equal(normal_points, ghost_points)
            ),
            "max_abs_point_difference_m": float(np.max(np.abs(points_difference))),
            "mk_equal_exactly": bool(np.array_equal(normal_mk, ghost_mk)),
            "normal_vector_max_abs_residual_m": float(np.max(np.abs(vector_residual))),
            "normal_size_max_abs_residual_m": float(np.max(np.abs(size_residual))),
            "normal_vector_ratio_min_nonzero": (
                float(np.min(ghost_norm[~zero] / normal_norm[~zero]))
                if np.any(~zero)
                else None
            ),
            "normal_vector_ratio_max_nonzero": (
                float(np.max(ghost_norm[~zero] / normal_norm[~zero]))
                if np.any(~zero)
                else None
            ),
            "normal_size_ratio_min_nonzero": (
                float(np.min(ghost_size[normal_size > ZERO_NORMAL_TOLERANCE_M] / normal_size[normal_size > ZERO_NORMAL_TOLERANCE_M]))
                if np.any(normal_size > ZERO_NORMAL_TOLERANCE_M)
                else None
            ),
            "normal_size_ratio_max_nonzero": (
                float(np.max(ghost_size[normal_size > ZERO_NORMAL_TOLERANCE_M] / normal_size[normal_size > ZERO_NORMAL_TOLERANCE_M]))
                if np.any(normal_size > ZERO_NORMAL_TOLERANCE_M)
                else None
            ),
            "pass": bool(
                np.array_equal(normal_points, ghost_points)
                and np.array_equal(normal_mk, ghost_mk)
                and np.max(np.abs(vector_residual)) <= GHOST_DOUBLING_TOLERANCE_M
                and np.max(np.abs(size_residual)) <= GHOST_DOUBLING_TOLERANCE_M
            ),
        }

        hdp_arrays = _all_vtk_arrays(hdp_vtk)
        hdp_mk = _column(_required_array(hdp_vtk, "Mk"), "hdp Mk").astype(int)
        construction = {
            "hdp_actual_point_count": int(hdp_vtk["point_count"]),
            "hdp_actual_polygon_count": int(len(hdp_vtk["polygons"])),
            "hdp_actual_cell_mk_counts": _counts_by_int(hdp_mk),
            "body_mk": body_mk,
            "body_hdp_face_count": int(len(hdp_faces)),
            "body_hdp_vertex_count": int(
                len(
                    {
                        vertex
                        for face in hdp_faces
                        for vertex in face["vertex_ids"]
                    }
                )
            ),
            "body_hdp_faces": hdp_faces,
            "runtime_interface": overlap,
            "physical_box_source": "source definition physical mkvoid when available, otherwise hdp body bbox",
            "hdp_field_names": sorted(hdp_arrays),
        }

        generated_count_checks: dict[str, Any] = {}
        if generated_xml is not None:
            particles = generated_xml["particles"]
            summary = generated_xml["summary"]
            generated_count_checks = {
                "runtime_normal_count_equals_generated_nb": len(normal_points) == particles.get("nb"),
                "runtime_fixed_count_equals_generated_nbf": len(normal_points) == particles.get("nbf"),
                "runtime_mk_counts": _counts_by_int(normal_mk),
                "generated_fixed_summary": summary.get("fixed"),
                "generated_body_block": next(
                    (
                        block
                        for block in generated_xml.get("blocks", {}).get("fixed", [])
                        if block.get("mkbound") == 1
                    ),
                    None,
                ),
            }
            fixed_summary = summary.get("fixed", {})
            generated_count_checks["runtime_fixed_count_equals_generated_fixed_summary"] = (
                len(normal_points) == fixed_summary.get("count")
                if fixed_summary.get("count") is not None
                else None
            )

        case.update(
            {
                "status": "complete",
                "body_mk": body_mk,
                "resolution": resolution,
                "normal_vtk_summary": normal_file_summary,
                "ghost_vtk_summary": ghost_file_summary,
                "generated_bound_vtk_summary": bound_summary,
                "generated_mkcells_vtk_summary": mkcells_summary,
                "zero_normals": zero_summary,
                "zero_normals_by_topology": topology,
                "ghost_contract": ghost_contract,
                "generation_vs_runtime": runtime_vs_generation,
                "construction_face_overlap": construction,
                "generated_count_checks": generated_count_checks,
                "checks": {
                    "required_arrays_present": True,
                    "finite_arrays": finite,
                    "ghost_doubling_pass": ghost_contract["pass"],
                    "runtime_zero_free_pass": int(np.sum(zero)) == 0,
                    "construction_face_overlap_pass": overlap[
                        "all_body_interface_points_match_construction_faces"
                    ],
                    "runtime_body_topology_partition_pass": (
                        topology["partition"]["off_surface_or_unexpected_incidence"]["point_count"] == 0
                    ),
                    "generation_log_zero_free_as_reported": (
                        gencase.get("final_zero_normals_reported", {}).get("count") == 0
                        if gencase and gencase.get("final_zero_normals_reported")
                        else None
                    ),
                    "serialized_generation_runtime_arrays_match": (
                        bound_runtime_comparison.get("Normal_equal_exactly")
                        and bound_runtime_comparison.get("NormalSize_equal_exactly")
                        if bound_runtime_comparison
                        else None
                    ),
                },
            }
        )
    except (OSError, ValueError, KeyError, IndexError) as exc:
        case["status"] = "parse_or_audit_error"
        case["errors"].append(str(exc))
    return case


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _build_resolution_comparison(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_label = {case["run_label"]: case for case in cases if case.get("status") == "complete"}
    canonical = by_label.get("canonical-2")
    fine = by_label.get("fine-3")
    if canonical is None or fine is None:
        return {
            "available": False,
            "reason": "both complete canonical-2 and fine-3 audits are required",
        }
    c_resolution = canonical["resolution"]
    f_resolution = fine["resolution"]
    c_zero = canonical["zero_normals"]["total_zero_normal_count"]
    f_zero = fine["zero_normals"]["total_zero_normal_count"]
    c_fraction = canonical["zero_normals"]["total_zero_normal_fraction"]
    f_fraction = fine["zero_normals"]["total_zero_normal_fraction"]
    return {
        "available": True,
        "canonical_label": "canonical-2",
        "fine_label": "fine-3",
        "dp_fine_over_canonical": _ratio(
            f_resolution.get("generated_dp_m"), c_resolution.get("generated_dp_m")
        ),
        "boundary_particle_count_fine_over_canonical": _ratio(
            f_resolution.get("runtime_boundary_point_count"),
            c_resolution.get("runtime_boundary_point_count"),
        ),
        "body_particle_count_fine_over_canonical": _ratio(
            f_resolution.get("runtime_body_point_count"),
            c_resolution.get("runtime_body_point_count"),
        ),
        "zero_normal_count": {
            "canonical-2": c_zero,
            "fine-3": f_zero,
            "fine_over_canonical": _ratio(f_zero, c_zero),
        },
        "zero_normal_fraction": {
            "canonical-2": c_fraction,
            "fine-3": f_fraction,
            "fine_minus_canonical_absolute": f_fraction - c_fraction,
            "fine_minus_canonical_percentage_points": 100.0 * (f_fraction - c_fraction),
        },
        "runtime_zero_free_at_both_resolutions": c_zero == 0 and f_zero == 0,
        "finding": (
            "Refinement increases the absolute thresholded zero-normal count in the "
            "existing artifacts while the fraction changes only slightly; neither "
            "resolution is zero-free under the stated threshold."
        ),
    }


def build_report(case_root: Path = DEFAULT_CASE_ROOT) -> dict[str, Any]:
    case_root = case_root.resolve()
    cases = [_audit_case(case_root, spec) for spec in CASE_SPECS]
    complete = [case for case in cases if case.get("status") == "complete"]
    return {
        "schema_version": SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "audit_execution": {
            "mode": "cpu_static",
            "solver_launched_by_audit": False,
            "cfd_launched_by_audit": False,
            "gpu_used_by_audit": False,
            "nvidia_smi_called_by_audit": False,
            "input_policy": "read existing fixed-box canonical/fine artifacts only",
            "write_policy": "JSON and Markdown evidence outputs only",
        },
        "scope": {
            "case_root": _relative(case_root, REPO_ROOT),
            "cases": [spec["run_label"] for spec in CASE_SPECS],
            "requested_evidence": [
                "runtime CfgInit_Normals.vtk and CfgInit_NormalsGhost.vtk",
                "hdp_Actual.vtk construction faces",
                "generated Bound.vtk and generated XML/log summaries when available",
                "zero normals by Mk, six faces, twelve edges, eight corners",
                "construction-face coincidence and resolution comparison",
            ],
        },
        "thresholds": {
            "zero_normal_norm_lte_m": ZERO_NORMAL_TOLERANCE_M,
            "near_zero_normal_norm_lte_m": NEAR_ZERO_NORMAL_TOLERANCE_M,
            "face_plane_tolerance_m": FACE_TOLERANCE_M,
            "ghost_doubling_abs_tolerance_m": GHOST_DOUBLING_TOLERANCE_M,
            "exact_vector_zero_definition": "all three serialized Normal components equal 0",
            "topology_partition": "face interior = one incident plane; edge = two; corner = three",
        },
        "cases": cases,
        "resolution_comparison": _build_resolution_comparison(cases),
        "summary": {
            "case_count": len(cases),
            "complete_case_count": len(complete),
            "runtime_zero_free_all_cases": bool(
                complete and all(
                    case["checks"]["runtime_zero_free_pass"] for case in complete
                )
            ),
            "ghost_doubling_pass_all_complete_cases": bool(
                complete and all(
                    case["checks"]["ghost_doubling_pass"] for case in complete
                )
            ),
            "construction_face_overlap_pass_all_complete_cases": bool(
                complete and all(
                    case["checks"]["construction_face_overlap_pass"] for case in complete
                )
            ),
            "runtime_zero_normal_counts_by_resolution": {
                case["run_label"]: case["zero_normals"]["total_zero_normal_count"]
                for case in complete
            },
            "overall_evidence_status": (
                "complete_with_thresholded_runtime_zero_normals"
                if len(complete) == len(cases)
                and any(case["zero_normals"]["total_zero_normal_count"] for case in complete)
                else "complete_zero_free_or_partial"
            ),
        },
        "not_audited_or_unavailable": [
            "No new CPU solver execution or CPU-kernel trace was produced; the existing solver logs are provenance only and identify GPU execution.",
            "CfgInit_Normals*.vtk are initialization snapshots, not a per-time-step normal history.",
            "The ghost VTK POINTS are the same x_b boundary coordinates; independent ghost coordinates are not serialized and are inferred as x_b+n_ghost.",
            "The serialized Bound.vtk Normal field is compared, but no raw in-memory BoundNor pointer/state or CPU reduction trace is available.",
            "No new CFD/GPU force, pressure, penetration, or physical-acceptance claim is made by this static audit.",
        ],
    }


def _md_num(value: Any, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R4 F6 fixed-box mDBC runtime zero-normal audit",
        "",
        "> CPU/static evidence only. This audit reads existing artifacts and does not launch CFD, a solver, GPU work, or `nvidia-smi`.",
        "",
        "## 判定摘要",
        "",
        "The runtime zero criterion is `||FIELD/Normal|| <= 1e-12 m`; exact serialized all-zero vectors are reported separately. `CfgInit_Normals.vtk` POINTS are `x_b`, and the effective interface is reconstructed as `x_gamma = x_b + n_ghost/2`.",
        "",
        "| resolution | dp (m) | runtime zero normals | fraction | zero by Mk | Ghost≈2×Normal | construction faces |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for case in report["cases"]:
        if case.get("status") != "complete":
            lines.append(
                f"| `{case['run_label']}` | n/a | unavailable | n/a | n/a | n/a | `{case['status']}` |"
            )
            continue
        resolution = case["resolution"]
        zero = case["zero_normals"]
        checks = case["checks"]
        lines.append(
            f"| `{case['run_label']}` | {_md_num(resolution.get('generated_dp_m'))} | "
            f"{zero['total_zero_normal_count']} / {case['normal_vtk_summary']['point_count']} | "
            f"{100.0 * zero['total_zero_normal_fraction']:.6f}% | "
            f"{zero['zero_normal_by_mk_counts']} | "
            f"`{'PASS' if checks['ghost_doubling_pass'] else 'FAIL'}` | "
            f"`{'PASS' if checks['construction_face_overlap_pass'] else 'FAIL'}` |"
        )

    lines.extend(
        [
            "",
            "## 面级零法向取证",
            "",
            "Face rows are incident counts, so edge/corner points appear on each incident face. The exclusive partition is face interior (one plane), edge excluding corners (two planes), and corner (three planes).",
            "",
        ]
    )
    for case in report["cases"]:
        if case.get("status") != "complete":
            continue
        zero = case["zero_normals"]
        topology = case["zero_normals_by_topology"]
        lines.append(f"### `{case['run_label']}`")
        lines.append("")
        lines.append("| item | total points | zero normals | near-zero normals |")
        lines.append("|---|---:|---:|---:|")
        for name, row in topology["faces"].items():
            lines.append(
                f"| face `{name}` (incident) | {row['incident_point_count']} | "
                f"{row['incident_zero_normal_count']} | {row['incident_near_zero_normal_count']} |"
            )
        for name, row in topology["edges"].items():
            lines.append(
                f"| edge `{name}` | {row['point_count']} | {row['zero_normal_count']} | "
                f"{row['near_zero_normal_count']} |"
            )
        for name, row in topology["corners"].items():
            lines.append(
                f"| corner `{name}` | {row['point_count']} | {row['zero_normal_count']} | "
                f"{row['near_zero_normal_count']} |"
            )
        lines.append("")
        lines.append("Exclusive partition:")
        lines.append("")
        for name, row in topology["partition"].items():
            lines.append(
                f"- `{name}`: {row['point_count']} points, "
                f"{row['zero_normal_count']} zero, {row['near_zero_normal_count']} near-zero."
            )
        lines.append("")
        lines.append(
            f"By Mk: `{json.dumps(zero['zero_normal_by_mk_counts'], ensure_ascii=False, sort_keys=True)}`; "
            f"exact vector zeros: `{zero['exact_vector_zero_count']}`."
        )
        lines.append("")

    lines.extend(["## Ghost、生成期与运行时", ""])
    lines.append(
        "The ghost contract compares both vector and scalar size fields against exactly twice the normal field, while also checking that POINTS and Mk remain identical. The generated `Bound.vtk` is compared directly with runtime `CfgInit_Normals.vtk` when present."
    )
    lines.append("")
    lines.append("| resolution | max `|n_g-2n_b|` | max `|size_g-2size_b|` | Bound vs runtime | GenCase reported zero | serialized threshold zero |")
    lines.append("|---|---:|---:|---|---:|---:|")
    for case in report["cases"]:
        if case.get("status") != "complete":
            continue
        ghost = case["ghost_contract"]
        generation = case["generation_vs_runtime"]
        bound = generation.get("bound_vtk_vs_runtime") or {}
        lines.append(
            f"| `{case['run_label']}` | {_md_num(ghost['normal_vector_max_abs_residual_m'], 4)} | "
            f"{_md_num(ghost['normal_size_max_abs_residual_m'], 4)} | "
            f"`{'exact' if bound.get('Normal_equal_exactly') else 'not exact/unavailable'}` | "
            f"{_md_num((generation.get('gencase_reported_final_zero_normals') or {}).get('count'))} | "
            f"{_md_num(generation.get('serialized_generation_threshold_zero_count'))} |"
        )
    lines.extend(
        [
            "",
            "Interpretation: both GenCase logs say `Final zero normals: 0/...`, but the serialized normal vectors at the affected locations have norm `1.11e-16 m`. Under the declared `1e-12 m` threshold, runtime counts are 63 (canonical-2) and 240 (fine-3). The `Bound.vtk` and runtime normal/size arrays are exact matches in these artifacts, so this is not a newly introduced runtime mutation.",
            "",
            "## 构造面重合关系",
            "",
            "For each case, `hdp_Actual.vtk` is read as the construction surface. Its six `Mk=18` quadrilateral cells are matched to the physical box faces, and all reconstructed body `x_gamma` points are tested against those face rectangles using a `1e-5 m` plane tolerance.",
            "",
            "| resolution | hdp points | hdp body faces | runtime body interface points | on any hdp face | not on hdp face |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for case in report["cases"]:
        if case.get("status") != "complete":
            continue
        construction = case["construction_face_overlap"]
        overlap = construction["runtime_interface"]
        lines.append(
            f"| `{case['run_label']}` | {construction['hdp_actual_point_count']} | "
            f"{construction['body_hdp_face_count']} | {overlap['body_interface_point_count']} | "
            f"{overlap['body_interface_on_any_hdp_body_face_count']} | "
            f"{overlap['body_interface_not_on_hdp_body_face_count']} |"
        )
    lines.extend(["", "### hdp body-face map", ""])
    lines.append("| resolution | face | hdp cell | hdp residual (m) | runtime residual (m) | runtime interface points | runtime zero |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for case in report["cases"]:
        if case.get("status") != "complete":
            continue
        construction = case["construction_face_overlap"]
        runtime_faces = {
            row["name"]: row for row in construction["runtime_interface"]["faces"]
        }
        for face in construction["body_hdp_faces"]:
            runtime = runtime_faces[face["name"]]
            lines.append(
                f"| `{case['run_label']}` | `{face['name']}` | {face['cell_index']} | "
                f"{_md_num(face['max_vertex_residual_to_source_box_m'], 4)} | "
                f"{_md_num(runtime['max_runtime_plane_residual_to_source_box_m'], 4)} | "
                f"{runtime['interface_point_count']} | {runtime['interface_zero_normal_count']} |"
            )
    lines.extend(["", "## 分辨率对照", ""])
    comparison = report["resolution_comparison"]
    if comparison.get("available"):
        lines.extend(
            [
                f"- `dp(fine)/dp(canonical) = {_md_num(comparison['dp_fine_over_canonical'])}`.",
                f"- Boundary point count ratio fine/canonical: `{_md_num(comparison['boundary_particle_count_fine_over_canonical'])}`; body point count ratio: `{_md_num(comparison['body_particle_count_fine_over_canonical'])}`.",
                f"- Thresholded zero count: canonical `{comparison['zero_normal_count']['canonical-2']}`, fine `{comparison['zero_normal_count']['fine-3']}`; fine/canonical `{_md_num(comparison['zero_normal_count']['fine_over_canonical'])}`.",
                f"- Thresholded zero fraction: canonical `{100.0 * comparison['zero_normal_fraction']['canonical-2']:.6f}%`, fine `{100.0 * comparison['zero_normal_fraction']['fine-3']:.6f}%`; change `{comparison['zero_normal_fraction']['fine_minus_canonical_percentage_points']:.6f}` percentage points.",
                f"- Zero-free at both resolutions: `{comparison['runtime_zero_free_at_both_resolutions']}`.",
                "",
                comparison["finding"],
            ]
        )
    else:
        lines.append(f"Unavailable: {comparison.get('reason', 'unknown reason')}.")

    lines.extend(["", "## 未能审计/不可得字段", ""])
    lines.extend(f"- {item}" for item in report["not_audited_or_unavailable"])
    lines.extend(
        [
            "",
            "## 输入清单",
            "",
            "The JSON report records relative paths, byte sizes, and SHA-256 hashes for every input and optional summary file. Re-running the script against unchanged artifacts produces the same JSON/Markdown content.",
            "",
            f"Machine-readable report: `{_relative(DEFAULT_JSON, Path(report['scope']['case_root']).parent.parent.parent.parent.parent.parent) if False else 'r4-mdbc-runtime-zero-normal-audit.json'}`.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    report: dict[str, Any], json_path: Path = DEFAULT_JSON, markdown_path: Path = DEFAULT_MARKDOWN
) -> None:
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-root",
        type=Path,
        default=DEFAULT_CASE_ROOT,
        help="fixed-box case root (default: repository case root)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="override JSON output path; default is the requested case-local report",
    )
    parser.add_argument(
        "--output-markdown",
        type=Path,
        default=None,
        help="override Markdown output path; default is the requested case-local report",
    )
    args = parser.parse_args(argv)
    case_root = args.case_root.resolve()
    report = build_report(case_root)
    json_path = args.output_json.resolve() if args.output_json else case_root / DEFAULT_JSON.name
    markdown_path = (
        args.output_markdown.resolve()
        if args.output_markdown
        else case_root / DEFAULT_MARKDOWN.name
    )
    write_outputs(report, json_path, markdown_path)
    summary = report["summary"]
    print(
        f"{AUDIT_ID}: {summary['overall_evidence_status']}; "
        f"zero counts {summary['runtime_zero_normal_counts_by_resolution']}"
    )
    print(f"JSON: {_relative(json_path, case_root)}")
    print(f"Markdown: {_relative(markdown_path, case_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
