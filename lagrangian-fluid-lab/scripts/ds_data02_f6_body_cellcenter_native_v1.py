"""Prepare and audit the F6 explicit body cell-centre initialization.

The F6 body z-origin (0.88 m) is not commensurate with the global ``dp/2``
phase at ``dp=0.025``.  A global pointref change would therefore move the
fluid and wall lattices.  This additive recipe freezes each source XML's
global pointref and replaces only the floating-body drawbox with the official
GenCase ``drawpoints`` command.  It is the smallest body-specific construction
that can express the requested centres without silently moving the liquid or
fixed/moving geometry.

``prepare`` only writes new candidate XMLs, manifests, and CPU requests.
``run-case`` is intended to be called by the shared DS-DATA-02 CPU runner.  It
executes official GenCase and PartVTK in the child process, writes structured
child receipts, and performs the initial typed/mass/finite-wall checks.  It
does not start DualSPHysics, GPU work, conversion, or any solver experiment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import re
import resource
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from ds_data02_f6_body_cellcenter_recipe_v1 import (
    ACTUAL_REPORT,
    CANONICAL_MOTHER,
    OUTPUT as STATIC_PROPOSAL,
    centered_box_recipe,
    sha256_file,
)


ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
RUNTIME_V2 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
)
OFFICIAL_BIN = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux"
)
GENCASE = OFFICIAL_BIN / "GenCase_linux64"
PARTVTK = OFFICIAL_BIN / "PartVTK_linux64"
FUNCTIONS_MATH = Path("/home/jade/Projects/DualSPHysics/src/source/FunctionsMath.h")
JCASE_VRES = Path("/home/jade/Projects/DualSPHysics/src/source/JCaseVRes.cpp")
GENCASE_TEMPLATE = Path(
    "/home/jade/Projects/DualSPHysics/doc/xml_format/GenCase_CaseTemplate.xml"
)

RECIPE_ID = "F6_BODY_CELLCENTER_EXPLICIT_POINTS_001"
SCOPE_ROOT = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/body_cellcenter_native_001"
CASES_ROOT = SCOPE_ROOT / "cases"
REQUESTS_ROOT = SCOPE_ROOT / "requests"
MANIFEST = SCOPE_ROOT / "manifest.json"
BODY_COMMENT = "Native floatingtype=2 body; initial bottom at fluid upper face"
ROLES = ("coarse", "medium", "fine")
STORAGE_BYTES = {"coarse": 2 * 1024**3, "medium": 4 * 1024**3, "fine": 8 * 1024**3}
DP = {"coarse": 0.025, "medium": 0.02, "fine": 0.0125}
CASE_IDS = {
    role: f"F6_BODY_CELLCENTER_EXPLICIT_DP{role.upper()}"
    for role in ROLES
}
TOLERANCE_M = 3e-6
FLUID_MASS_KG = 5120.0
BODY_LOW = [2.0, 0.8, 0.88]
BODY_SIZE = [0.8, 0.8, 0.4]
BODY_HIGH = [2.8, 1.6, 1.28]
BODY_CENTER = [2.4, 1.2, 1.08]
BODY_MASS_KG = 128.0
BODY_INERTIA = [8.53333333333, 8.53333333333, 13.6533333333]
WALL_LOW = [0.0, 0.0, 0.0]
WALL_SIZE = [4.8, 2.4, 2.4]


class NativeRecipeError(RuntimeError):
    """Raised for an unsafe candidate or a failed native preflight."""


def _json_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _json_read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise NativeRecipeError(f"JSON root is not an object: {path}")
    return value


def _fmt(value: float) -> str:
    return f"{float(value):.15g}"


def _sha(path: Path) -> str:
    return sha256_file(path)


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise NativeRecipeError(f"{label} is missing: {path}")
    return path


def _usage() -> dict[str, Any]:
    def pack(row: resource.struct_rusage) -> dict[str, Any]:
        return {
            "user_seconds": row.ru_utime,
            "system_seconds": row.ru_stime,
            "max_rss_kib": row.ru_maxrss,
            "minor_faults": row.ru_minflt,
            "major_faults": row.ru_majflt,
            "in_block": row.ru_inblock,
            "out_block": row.ru_oublock,
            "voluntary_context_switches": row.ru_nvcsw,
            "involuntary_context_switches": row.ru_nivcsw,
        }

    return {
        "self": pack(resource.getrusage(resource.RUSAGE_SELF)),
        "children": pack(resource.getrusage(resource.RUSAGE_CHILDREN)),
    }


def _source_xmls() -> dict[str, Path]:
    report = _json_read(ACTUAL_REPORT)
    rows = report.get("initial_body_lattice")
    if not isinstance(rows, list):
        raise NativeRecipeError("diagnostic report lacks initial_body_lattice")
    result: dict[str, Path] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("role"), str):
            source = row.get("source")
            if isinstance(source, dict) and isinstance(source.get("xml"), str):
                result[str(row["role"])] = Path(str(source["xml"]))
    if set(result) != set(ROLES):
        raise NativeRecipeError(f"diagnostic XML roles are incomplete: {sorted(result)}")
    return result


def _drawbox(root: ET.Element, comment: str) -> ET.Element:
    for node in root.findall(".//drawbox"):
        if node.get("cmt") == comment:
            return node
    raise NativeRecipeError(f"source XML lacks body drawbox {comment!r}")


def _vector(node: ET.Element, label: str) -> list[float]:
    values: list[float] = []
    for axis in "xyz":
        raw = node.get(axis)
        if raw is None:
            raise NativeRecipeError(f"{label} lacks {axis}")
        value = float(raw)
        if not math.isfinite(value):
            raise NativeRecipeError(f"{label}.{axis} is nonfinite")
        values.append(value)
    return values


def _source_snapshot(path: Path, *, allow_explicit_body: bool = False) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find(".//definition")
    body = next(
        (node for node in root.findall(".//drawbox") if node.get("cmt") == BODY_COMMENT),
        None,
    )
    explicit_body = root.find(".//drawpoints")
    if body is None and (not allow_explicit_body or explicit_body is None):
        raise NativeRecipeError(f"source XML lacks body drawbox or explicit drawpoints: {path}")
    wall = next(
        (node for node in root.findall(".//drawbox") if node.get("cmt") == "Finite tank walls; physical endpoints frozen"),
        None,
    )
    fluid = next(
        (node for node in root.findall(".//drawbox") if node.get("cmt") == "Frozen continuous fluid cell-centre population"),
        None,
    )
    floating = root.find(".//floatings/floating")
    particles = root.find(".//particles")
    if definition is None or wall is None or fluid is None or floating is None or particles is None:
        raise NativeRecipeError(f"source XML is incomplete: {path}")
    body_point = body.find("point") if body is not None else None
    body_size = body.find("size") if body is not None else None
    wall_point = wall.find("point")
    wall_size = wall.find("size")
    fluid_point = fluid.find("point")
    fluid_size = fluid.find("size")
    massbody = floating.find("massbody")
    center = floating.find("center")
    inertia = floating.find("inertia")
    constants = root.find(".//constants")
    floating_particles = particles.find("floating")
    fluid_particles = particles.find("fluid")
    fixed_particles = particles.find("fixed")
    required = (wall_point, wall_size, fluid_point, fluid_size, massbody, center, inertia)
    if any(item is None for item in required):
        raise NativeRecipeError(f"source XML lacks required geometry or rigid fields: {path}")
    assert wall_point is not None and wall_size is not None
    assert fluid_point is not None and fluid_size is not None
    assert massbody is not None and center is not None and inertia is not None
    if (
        constants is None
        or fixed_particles is None
        or floating_particles is None
        or fluid_particles is None
    ):
        raise NativeRecipeError(f"source XML lacks particles/constants: {path}")
    return {
        "path": str(path.resolve()),
        "sha256": _sha(path),
        "dp_m": float(definition.get("dp", "nan")),
        "pointref_m": _vector(definition.find("pointref"), "pointref"),
        "pointmin_m": _vector(definition.find("pointmin"), "pointmin"),
        "pointmax_m": _vector(definition.find("pointmax"), "pointmax"),
        "body_point_m": _vector(body_point, "body.point") if body_point is not None else None,
        "body_size_m": _vector(body_size, "body.size") if body_size is not None else None,
        "explicit_body_point_count": (
            len(root.findall(".//drawpoints/point")) if explicit_body is not None else 0
        ),
        "wall_point_m": _vector(wall_point, "wall.point"),
        "wall_size_m": _vector(wall_size, "wall.size"),
        "fluid_drawbox_point_m": _vector(fluid_point, "fluid.point"),
        "fluid_drawbox_size_m": _vector(fluid_size, "fluid.size"),
        "massbody_kg": float(massbody.get("value", "nan")),
        "center_m": _vector(center, "center"),
        "inertia_kg_m2": _vector(inertia, "inertia"),
        "execution_parameters": {
            str(node.get("key")): str(node.get("value"))
            for node in root.findall(".//execution//parameter")
            if node.get("key") is not None
        },
        "constants": {
            str(node.tag): dict(node.attrib) for node in list(constants) if node.tag is not None
        },
        "particles": {
            "attributes": dict(particles.attrib),
            "fixed": dict(fixed_particles.attrib),
            "floating": dict(floating_particles.attrib),
            "fluid": dict(fluid_particles.attrib),
            "masspart_kg": float(floating_particles.find("masspart").get("value"))
            if floating_particles.find("masspart") is not None
            else None,
            "massfluid_kg": float(constants.find("massfluid").get("value"))
            if constants.find("massfluid") is not None
            else None,
            "massbound_kg": float(constants.find("massbound").get("value"))
            if constants.find("massbound") is not None
            else None,
        },
        "motion_xml": ET.tostring(root.find(".//motion"), encoding="unicode") if root.find(".//motion") is not None else None,
    }


def _points(low: Sequence[float], size: Sequence[float], dp: float) -> Iterator[tuple[float, float, float]]:
    nx, ny, nz = (round(float(value) / dp) for value in size)
    for iz in range(int(nz)):
        z = float(low[2]) + (iz + 0.5) * dp
        for iy in range(int(ny)):
            y = float(low[1]) + (iy + 0.5) * dp
            for ix in range(int(nx)):
                yield (
                    float(low[0]) + (ix + 0.5) * dp,
                    y,
                    z,
                )


def _point_lines(recipe: Mapping[str, Any]) -> str:
    lines = []
    for point in _points(BODY_LOW, BODY_SIZE, float(recipe["dp_m"])):
        lines.append(
            f'                        <point x="{_fmt(point[0])}" y="{_fmt(point[1])}" z="{_fmt(point[2])}" />'
        )
    return "\n".join(lines)


def build_candidate_xml(source: Path, role: str, destination: Path) -> dict[str, Any]:
    """Write a new explicit-points XML while freezing all non-body source bytes semantically."""

    source = _require_file(source, "source F6 XML")
    if role not in ROLES:
        raise NativeRecipeError(f"unknown F6 role: {role}")
    recipe = centered_box_recipe(BODY_LOW, BODY_SIZE, DP[role])
    source_snapshot = _source_snapshot(source)
    if source_snapshot["wall_point_m"] != WALL_LOW or source_snapshot["wall_size_m"] != WALL_SIZE:
        raise NativeRecipeError(f"source wall geometry is not the frozen F6 mother: {source}")
    if source_snapshot["body_point_m"] != BODY_LOW or source_snapshot["body_size_m"] != BODY_SIZE:
        raise NativeRecipeError(f"source body geometry is not the frozen F6 mother: {source}")
    if abs(source_snapshot["massbody_kg"] - BODY_MASS_KG) > 1e-8:
        raise NativeRecipeError(f"source massbody is not 128 kg: {source}")
    if not all(abs(a - b) <= 2e-8 for a, b in zip(source_snapshot["center_m"], BODY_CENTER)):
        raise NativeRecipeError(f"source rigid center differs from frozen contract: {source}")

    text = source.read_text(encoding="utf-8")
    pointref_match = re.search(r"<pointref\b[^>]*/>", text)
    body_match = re.search(
        r'<drawbox\s+cmt="Native floatingtype=2 body; initial bottom at fluid upper face">.*?</drawbox>',
        text,
        flags=re.DOTALL,
    )
    if pointref_match is None or body_match is None:
        raise NativeRecipeError(f"source XML candidate anchors are missing: {source}")
    points = _point_lines(recipe)
    replacement = (
        "                    <!-- F6_BODY_CELLCENTER_EXPLICIT_POINTS_001: official drawpoints; "
        "global pointref and all liquid/wall/moving commands remain source-frozen. -->\n"
        "                    <drawpoints>\n"
        f"{points}\n"
        "                    </drawpoints>"
    )
    # Replace body first, then retain the source global pointref byte-for-byte.
    candidate = text[: body_match.start()] + replacement + text[body_match.end() :]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(candidate, encoding="utf-8")
    parsed = _source_snapshot(destination, allow_explicit_body=True)
    if parsed["pointref_m"] != source_snapshot["pointref_m"]:
        raise NativeRecipeError("candidate changed the global pointref")
    if parsed["wall_point_m"] != source_snapshot["wall_point_m"] or parsed["wall_size_m"] != source_snapshot["wall_size_m"]:
        raise NativeRecipeError("candidate changed fixed wall geometry")
    if parsed["fluid_drawbox_point_m"] != source_snapshot["fluid_drawbox_point_m"] or parsed["fluid_drawbox_size_m"] != source_snapshot["fluid_drawbox_size_m"]:
        raise NativeRecipeError("candidate changed fluid drawbox geometry")
    if parsed["execution_parameters"] != source_snapshot["execution_parameters"] or parsed["constants"] != source_snapshot["constants"]:
        raise NativeRecipeError("candidate changed execution/control constants")
    if parsed["explicit_body_point_count"] != int(recipe["ideal_type2_count"]):
        raise NativeRecipeError(
            "candidate explicit body point count differs from the registered target"
        )
    return {
        "role": role,
        "case_id": CASE_IDS[role],
        "recipe_id": RECIPE_ID,
        "source_xml": str(source.resolve()),
        "source_xml_sha256": _sha(source),
        "candidate_xml": str(destination.resolve()),
        "candidate_xml_sha256": _sha(destination),
        "global_pointref_frozen": True,
        "body_construction": {
            "official_command": "drawpoints",
            "body_mkbound": 50,
            "point_count_requested": int(recipe["ideal_type2_count"]),
            "point_first_m": recipe["ideal_first_center_m"],
            "point_last_m": recipe["ideal_last_center_m"],
            "point_centroid_m": recipe["ideal_centroid_m"],
            "continuous_low_m": BODY_LOW,
            "continuous_high_m": BODY_HIGH,
            "continuous_body_mass_kg": BODY_MASS_KG,
            "continuous_center_m": BODY_CENTER,
            "continuous_inertia_kg_m2": BODY_INERTIA,
        },
        "frozen_source_semantics": {
            "pointref_m": source_snapshot["pointref_m"],
            "fluid_drawbox_point_m": source_snapshot["fluid_drawbox_point_m"],
            "fluid_drawbox_size_m": source_snapshot["fluid_drawbox_size_m"],
            "wall_point_m": source_snapshot["wall_point_m"],
            "wall_size_m": source_snapshot["wall_size_m"],
            "execution_parameters": source_snapshot["execution_parameters"],
            "constants": source_snapshot["constants"],
            "motion_xml": source_snapshot["motion_xml"],
        },
        "source_mutated": False,
        "q_n_status": "not_assessed",
    }


def _vtk_points_payload(path: Path) -> tuple[int, bytes]:
    data = _require_file(path, "VTK artifact").read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\s*\n", data)
    if match is None:
        raise NativeRecipeError(f"unsupported VTK point block: {path}")
    count = int(match.group(1))
    start = match.end()
    end = start + count * 3 * 4
    if len(data) < end:
        raise NativeRecipeError(f"truncated VTK point payload: {path}")
    return count, data[start:end]


def _column(headers: Sequence[str], *needles: str) -> int | None:
    normalized = [re.sub(r"[^a-z0-9]+", "", value.lower()) for value in headers]
    for index, value in enumerate(normalized):
        if any(needle in value for needle in needles):
            return index
    return None


def _type_name(value: str) -> str:
    value = value.strip().lower()
    return {
        "0": "fixed",
        "1": "moving",
        "2": "body",
        "3": "fluid",
        "fixed": "fixed",
        "moving": "moving",
        "floating": "body",
        "fluid": "fluid",
    }.get(value, "unknown")


def _iter_partvtk(path: Path) -> tuple[list[str], Iterator[list[str]]]:
    stream = _require_file(path, "PartVTK CSV").open("r", encoding="utf-8", errors="replace", newline="")
    for line in stream:
        if "Pos.x" in line and "Type" in line and "Mk" in line and "Mass" in line:
            delimiter = "," if line.count(",") >= line.count(";") else ";"
            reader = csv.reader(itertools.chain([line], stream), delimiter=delimiter)
            try:
                headers = [str(value).strip() for value in next(reader)]
            except StopIteration as exc:
                stream.close()
                raise NativeRecipeError(f"empty PartVTK CSV header: {path}") from exc
            return headers, reader
    stream.close()
    raise NativeRecipeError(f"typed PartVTK CSV header not found: {path}")


def _parse_csv(path: Path, source: Mapping[str, Any], recipe: Mapping[str, Any]) -> dict[str, Any]:
    headers, rows = _iter_partvtk(path)
    type_col = _column(headers, "type")
    mk_col = _column(headers, "mk")
    mass_col = _column(headers, "mass")
    x_col = _column(headers, "posx")
    y_col = _column(headers, "posy")
    z_col = _column(headers, "posz")
    if None in (type_col, mk_col, mass_col, x_col, y_col, z_col):
        raise NativeRecipeError(f"PartVTK CSV lacks typed position/mass/mk columns: {headers}")
    assert type_col is not None and mk_col is not None and mass_col is not None
    assert x_col is not None and y_col is not None and z_col is not None
    counts = {name: 0 for name in ("fixed", "moving", "body", "fluid", "unknown")}
    mk_counts: dict[str, int] = {}
    mass_by_type = {name: 0.0 for name in counts}
    body_points: list[tuple[float, float, float]] = []
    body_keys: set[tuple[float, float, float]] = set()
    finite_positions = True
    parse_errors = 0
    wall_faces = {"x_low": 0, "x_high": 0, "y_low": 0, "y_high": 0, "z_low": 0}
    rows_read = 0
    for row in rows:
        if not row or len(row) <= max(type_col, mk_col, mass_col, x_col, y_col, z_col):
            continue
        try:
            kind = _type_name(row[type_col])
            mk = int(float(row[mk_col]))
            mass = float(row[mass_col])
            point = (float(row[x_col]), float(row[y_col]), float(row[z_col]))
        except (TypeError, ValueError):
            parse_errors += 1
            continue
        rows_read += 1
        if not all(math.isfinite(value) for value in (*point, mass)):
            finite_positions = False
        counts[kind] += 1
        mk_counts[f"{kind}:mk{mk}"] = mk_counts.get(f"{kind}:mk{mk}", 0) + 1
        mass_by_type[kind] += mass
        if kind == "body" and mk == 60:
            body_points.append(point)
            body_keys.add(point)
        if kind == "fixed" and mk == 30:
            x, y, z = point
            if abs(x - WALL_LOW[0]) <= TOLERANCE_M and WALL_LOW[1] - TOLERANCE_M <= y <= WALL_SIZE[1] + TOLERANCE_M and WALL_LOW[2] - TOLERANCE_M <= z <= WALL_SIZE[2] + TOLERANCE_M:
                wall_faces["x_low"] += 1
            if abs(x - (WALL_LOW[0] + WALL_SIZE[0])) <= TOLERANCE_M and WALL_LOW[1] - TOLERANCE_M <= y <= WALL_SIZE[1] + TOLERANCE_M and WALL_LOW[2] - TOLERANCE_M <= z <= WALL_SIZE[2] + TOLERANCE_M:
                wall_faces["x_high"] += 1
            if abs(y - WALL_LOW[1]) <= TOLERANCE_M and WALL_LOW[0] - TOLERANCE_M <= x <= WALL_SIZE[0] + TOLERANCE_M and WALL_LOW[2] - TOLERANCE_M <= z <= WALL_SIZE[2] + TOLERANCE_M:
                wall_faces["y_low"] += 1
            if abs(y - (WALL_LOW[1] + WALL_SIZE[1])) <= TOLERANCE_M and WALL_LOW[0] - TOLERANCE_M <= x <= WALL_SIZE[0] + TOLERANCE_M and WALL_LOW[2] - TOLERANCE_M <= z <= WALL_SIZE[2] + TOLERANCE_M:
                wall_faces["y_high"] += 1
            if abs(z - WALL_LOW[2]) <= TOLERANCE_M and WALL_LOW[0] - TOLERANCE_M <= x <= WALL_SIZE[0] + TOLERANCE_M and WALL_LOW[1] - TOLERANCE_M <= y <= WALL_SIZE[1] + TOLERANCE_M:
                wall_faces["z_low"] += 1
    # The iterator owns the file handle.  Exhaustion closes it; this is also
    # safe when PartVTK has no data because the loop still exhausts the file.
    body_count = len(body_points)
    body_bounds = None
    body_centroid = None
    if body_points:
        body_bounds = {
            "low_m": [min(point[axis] for point in body_points) for axis in range(3)],
            "high_m": [max(point[axis] for point in body_points) for axis in range(3)],
        }
        body_centroid = [
            sum(point[axis] for point in body_points) / body_count for axis in range(3)
        ]
    expected_fluid = int(source["particles"]["fluid"]["count"])
    expected_fixed = int(source["particles"]["fixed"]["count"])
    expected_body = int(recipe["ideal_type2_count"])
    fluid_mass_error = mass_by_type["fluid"] - FLUID_MASS_KG
    body_mass_error = mass_by_type["body"] - BODY_MASS_KG
    strict_inside = bool(
        body_points
        and all(
            BODY_LOW[axis] + TOLERANCE_M < point[axis] < BODY_HIGH[axis] - TOLERANCE_M
            for point in body_points
            for axis in range(3)
        )
    )
    centroid_error = (
        [body_centroid[axis] - BODY_CENTER[axis] for axis in range(3)]
        if body_centroid is not None
        else None
    )
    return {
        "csv": str(path.resolve()),
        "csv_sha256": _sha(path),
        "headers": headers,
        "rows_read": rows_read,
        "parse_errors": parse_errors,
        "typed_counts": counts,
        "typed_mk_counts": mk_counts,
        "mass_by_type_kg": mass_by_type,
        "body": {
            "type": 2,
            "mk": 60,
            "count": body_count,
            "unique_position_count": len(body_keys),
            "bounds_m": body_bounds,
            "centroid_m": body_centroid,
            "centroid_error_m": centroid_error,
            "strictly_inside_continuous_box": strict_inside,
        },
        "finite_positions": finite_positions,
        "finite_wall_face_counts": wall_faces,
        "fluid_mass_error_kg": fluid_mass_error,
        "body_mass_error_kg": body_mass_error,
        "checks": {
            "rows_read_positive": rows_read > 0,
            "all_rows_parseable": parse_errors == 0,
            "fluid_type3_positive": counts["fluid"] > 0,
            "fixed_type0_positive": counts["fixed"] > 0,
            "moving_type1_expected_zero": counts["moving"] == 0,
            "floating_type2_mk60_count_exact": body_count == expected_body,
            "fluid_count_matches_source": counts["fluid"] == expected_fluid,
            "fixed_count_matches_source": counts["fixed"] == expected_fixed,
            "fluid_mass_5120kg": abs(fluid_mass_error) <= 1e-5,
            "body_mass_128kg": abs(body_mass_error) <= 1e-5,
            "body_unique_positions": len(body_keys) == body_count,
            "body_strictly_inside": strict_inside,
            "body_centroid_matches_contract": centroid_error is not None and max(abs(value) for value in centroid_error) <= TOLERANCE_M,
            "finite_positions": finite_positions,
            "all_five_finite_wall_faces": all(value > 0 for value in wall_faces.values()),
        },
    }


def _particle_counts_from_xml(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise NativeRecipeError(f"generated XML lacks particles: {path}")
    result = {"np": int(particles.get("np", "-1")), "nb": int(particles.get("nb", "-1")), "nbf": int(particles.get("nbf", "-1"))}
    for tag, key in (("fixed", "fixed"), ("floating", "body"), ("fluid", "fluid")):
        node = particles.find(tag)
        if node is not None:
            result[key] = int(node.get("count", "-1"))
    constants = root.find(".//constants")
    data2d = constants.find("data2d") if constants is not None else None
    result["data2d"] = 1 if data2d is not None and data2d.get("value", "false").lower() == "true" else 0
    floating = root.find(".//particles/floating")
    if floating is not None and floating.find("masspart") is not None:
        result["masspart_kg"] = float(floating.find("masspart").get("value"))
    if constants is not None and constants.find("massfluid") is not None:
        result["massfluid_kg"] = float(constants.find("massfluid").get("value"))
    return result


def _gencase_summary(text: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, pattern in (
        ("total_particles", r"Total particles:\s*([\d,]+)"),
        ("fluid_particles", r"Fluid\.\.\.*:\s*([\d,]+)"),
        ("solver_dimension_from_gencase", r"Data2D=\[([01])\]"),
    ):
        match = re.search(pattern, text)
        if match:
            values[key] = int(match.group(1).replace(",", ""))
    if "solver_dimension_from_gencase" in values:
        values["solver_dimension_from_gencase"] = 2 if values["solver_dimension_from_gencase"] else 3
    return values


def _run_child(command: list[str], cwd: Path, stdout_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    before = _usage()
    with stdout_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=False)
    elapsed = time.monotonic() - started
    return {
        "command": command,
        "cwd": str(cwd.resolve()),
        "returncode": result.returncode,
        "elapsed_seconds": elapsed,
        "resource_usage_before": before,
        "resource_usage_after": _usage(),
        "stdout": str(stdout_path.resolve()),
        "stdout_sha256": _sha(stdout_path),
    }


def _find_csv(stem: Path) -> Path:
    candidates = [stem, stem.with_suffix(".csv"), stem.parent / (stem.name + ".csv")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted(stem.parent.glob(stem.name + "*.csv"))
    if matches:
        return matches[0]
    raise NativeRecipeError(f"PartVTK did not produce CSV for stem {stem}")


def _baseline_compare(case: Mapping[str, Any], generated_prefix: Path) -> dict[str, Any]:
    baseline_fluid = Path(str(case["baseline_fluid_vtk"]))
    baseline_bound = Path(str(case["baseline_bound_vtk"]))
    candidate_fluid = generated_prefix.with_name(generated_prefix.name + "_Fluid.vtk")
    candidate_bound = generated_prefix.with_name(generated_prefix.name + "_Bound.vtk")
    old_fluid_count, old_fluid_payload = _vtk_points_payload(baseline_fluid)
    new_fluid_count, new_fluid_payload = _vtk_points_payload(candidate_fluid)
    old_bound_count, old_bound_payload = _vtk_points_payload(baseline_bound)
    new_bound_count, new_bound_payload = _vtk_points_payload(candidate_bound)
    source = case["source_snapshot"]
    fixed_count = int(source["particles"]["fixed"]["count"])
    fixed_bytes = fixed_count * 3 * 4
    return {
        "baseline_fluid_vtk": str(baseline_fluid.resolve()),
        "baseline_fluid_vtk_sha256": _sha(baseline_fluid),
        "candidate_fluid_vtk": str(candidate_fluid.resolve()),
        "candidate_fluid_vtk_sha256": _sha(candidate_fluid),
        "baseline_bound_vtk": str(baseline_bound.resolve()),
        "baseline_bound_vtk_sha256": _sha(baseline_bound),
        "candidate_bound_vtk": str(candidate_bound.resolve()),
        "candidate_bound_vtk_sha256": _sha(candidate_bound),
        "baseline_fluid_point_count": old_fluid_count,
        "candidate_fluid_point_count": new_fluid_count,
        "baseline_bound_point_count": old_bound_count,
        "candidate_bound_point_count": new_bound_count,
        "fluid_point_payload_byte_identical": old_fluid_payload == new_fluid_payload,
        "fixed_prefix_payload_byte_identical": (
            old_bound_payload[:fixed_bytes] == new_bound_payload[:fixed_bytes]
            and old_bound_count >= fixed_count
            and new_bound_count >= fixed_count
        ),
        "fixed_prefix_count_compared": fixed_count,
        "comparison_semantics": "fluid VTK payload and fixed-boundary VTK prefix are compared by native float32 positions; body IDs may shift and are not compared by raw Idp",
    }


def run_case(manifest_path: Path, output_root: Path, role: str) -> dict[str, Any]:
    manifest = _json_read(manifest_path)
    cases = manifest.get("cases")
    if not isinstance(cases, dict) or role not in cases:
        raise NativeRecipeError(f"manifest has no role {role!r}")
    case = cases[role]
    source_xml = Path(str(case["candidate_xml"]))
    _require_file(source_xml, "candidate XML")
    case_id = str(case["case_id"])
    # The shared runner creates the attempt root before invoking this module.
    # Keep that directory immutable at the boundary while creating only our
    # own child directories here.
    output_root.mkdir(parents=True, exist_ok=True)
    native_root = output_root / "native"
    native_root.mkdir()
    generated_prefix = native_root / case_id
    gencase_stdout = native_root / "GenCase.stdout.log"
    partvtk_root = output_root / "partvtk"
    partvtk_root.mkdir()
    partvtk_stem = partvtk_root / "initial_all"
    started = time.monotonic()
    usage_before = _usage()
    report: dict[str, Any] = {
        "schema": "ds02.f6.body-cellcenter-native-preflight.v1",
        "family_id": "F6",
        "recipe_id": RECIPE_ID,
        "role": role,
        "case_id": case_id,
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": _sha(manifest_path),
        "candidate_xml": str(source_xml.resolve()),
        "candidate_xml_sha256": _sha(source_xml),
        "solver_or_gpu_started": False,
        "conversion_started": False,
        "q_n_status": "not_assessed",
        "qualification_claim": "none",
        "production_approval": "none",
    }
    try:
        gencase_command = [
            str(GENCASE.resolve()),
            str(source_xml.with_suffix("")),
            str(generated_prefix),
            "-save:all",
            "-threads:4",
        ]
        gencase_child = _run_child(gencase_command, source_xml.parent, gencase_stdout)
        gencase_text = gencase_stdout.read_text(encoding="utf-8", errors="replace")
        generated_xml = generated_prefix.with_suffix(".xml")
        generated_bi4 = generated_prefix.with_suffix(".bi4")
        gencase_child.update(
            {
                "summary_from_stdout": _gencase_summary(gencase_text),
                "generated_xml": str(generated_xml.resolve()),
                "generated_bi4": str(generated_bi4.resolve()),
                "generated_xml_sha256": _sha(generated_xml) if generated_xml.is_file() else None,
                "generated_bi4_sha256": _sha(generated_bi4) if generated_bi4.is_file() else None,
            }
        )
        gencase_receipt = output_root / "gencase-child-receipt.json"
        _json_write(gencase_receipt, gencase_child)
        report["gencase_child_receipt"] = str(gencase_receipt.resolve())
        report["gencase_child_receipt_sha256"] = _sha(gencase_receipt)
        report["gencase"] = gencase_child
        if gencase_child["returncode"] != 0 or not generated_xml.is_file() or not generated_bi4.is_file():
            raise NativeRecipeError("official GenCase did not produce a successful XML/BI4 pair")

        partvtk_stdout = partvtk_root / "PartVTK.stdout.log"
        partvtk_command = [
            str(PARTVTK.resolve()),
            "-filedata",
            str(generated_bi4.resolve()),
            "-filexml",
            str(generated_xml.resolve()),
            "-savecsv",
            str(partvtk_stem.resolve()),
            "-savestatscsv",
            str((partvtk_root / "initial_stats").resolve()),
            "-csvsep:1",
            "-onlytype:+all",
            "-vars:+idp,+type,+mass,+mk",
            "-threads:4",
        ]
        partvtk_child = _run_child(partvtk_command, partvtk_root, partvtk_stdout)
        csv_path = _find_csv(partvtk_stem)
        partvtk_child["csv"] = str(csv_path.resolve())
        partvtk_child["csv_sha256"] = _sha(csv_path)
        partvtk_receipt = output_root / "partvtk-child-receipt.json"
        _json_write(partvtk_receipt, partvtk_child)
        report["partvtk_child_receipt"] = str(partvtk_receipt.resolve())
        report["partvtk_child_receipt_sha256"] = _sha(partvtk_receipt)
        report["partvtk"] = partvtk_child
        if partvtk_child["returncode"] != 0:
            raise NativeRecipeError("official PartVTK failed")

        generated_counts = _particle_counts_from_xml(generated_xml)
        recipe = centered_box_recipe(BODY_LOW, BODY_SIZE, float(case["dp_m"]))
        csv_audit = _parse_csv(csv_path, case["source_snapshot"], recipe)
        baseline = _baseline_compare(case, generated_prefix)
        report["generated_particles_xml"] = generated_counts
        report["partvtk_audit"] = csv_audit
        report["baseline_geometry_comparison"] = baseline
        report["checks"] = {
            "gencase_child_returncode_zero": gencase_child["returncode"] == 0,
            "gencase_actual_3d": generated_counts.get("data2d") == 0 and gencase_child.get("summary_from_stdout", {}).get("solver_dimension_from_gencase", 3) == 3,
            "gencase_body_count_matches_target": generated_counts.get("body") == int(recipe["ideal_type2_count"]),
            "gencase_fluid_count_matches_source": generated_counts.get("fluid") == int(case["source_snapshot"]["particles"]["fluid"]["count"]),
            "partvtk_child_returncode_zero": partvtk_child["returncode"] == 0,
            "all_typed_partvtk_checks": all(csv_audit["checks"].values()),
            "fluid_positions_unchanged_from_source_vtk": baseline["fluid_point_payload_byte_identical"],
            "fixed_positions_unchanged_from_source_vtk": baseline["fixed_prefix_payload_byte_identical"],
            "same_frozen_fluid_mass_5120kg": csv_audit["checks"]["fluid_mass_5120kg"],
        }
        report["status"] = "native_initial_pass" if all(report["checks"].values()) else "native_initial_failed"
    except Exception as exc:
        report["status"] = "native_initial_failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        report["resource_usage"] = {"before": usage_before, "after": _usage()}
        report["source_mutated"] = False
        report["finished_without_solver_or_gpu"] = True
        _json_write(output_root / "native-initial-report.json", report)
    if report["status"] != "native_initial_pass":
        raise NativeRecipeError(report.get("error", "native initial preflight failed"))
    return report


def _request_inputs(case: Mapping[str, Any], manifest_path: Path) -> list[str]:
    paths = [
        Path(__file__).resolve(),
        STATIC_PROPOSAL.resolve(),
        manifest_path.resolve(),
        Path(str(case["candidate_xml"])).resolve(),
        Path(str(case["source_xml"])).resolve(),
        Path(str(case["baseline_fluid_vtk"])).resolve(),
        Path(str(case["baseline_bound_vtk"])).resolve(),
        RUNTIME_V2.resolve(),
        GENCASE.resolve(),
        PARTVTK.resolve(),
        FUNCTIONS_MATH.resolve(),
        JCASE_VRES.resolve(),
        GENCASE_TEMPLATE.resolve(),
        CANONICAL_MOTHER.resolve(),
    ]
    result: list[str] = []
    for path in paths:
        if not path.is_file():
            raise NativeRecipeError(f"request input is missing: {path}")
        value = str(path)
        if value not in result:
            result.append(value)
    return result


def prepare() -> dict[str, Any]:
    static = _json_read(STATIC_PROPOSAL)
    candidates = static.get("candidates")
    if not isinstance(candidates, list):
        raise NativeRecipeError("static proposal lacks candidates")
    source_xml = _source_xmls()
    cases: dict[str, Any] = {}
    for role in ROLES:
        static_row = next((row for row in candidates if isinstance(row, dict) and row.get("role") == role), None)
        if static_row is None:
            raise NativeRecipeError(f"static proposal lacks {role}")
        case_id = CASE_IDS[role]
        case_dir = CASES_ROOT / role
        candidate_xml = case_dir / f"{case_id}_Def.xml"
        source_meta = build_candidate_xml(source_xml[role], role, candidate_xml)
        baseline_fluid = source_xml[role].parent / f"{source_xml[role].stem}_Fluid.vtk"
        baseline_bound = source_xml[role].parent / f"{source_xml[role].stem}_Bound.vtk"
        _require_file(baseline_fluid, "baseline source fluid VTK")
        _require_file(baseline_bound, "baseline source bound VTK")
        source_snapshot = _source_snapshot(source_xml[role])
        recipe = centered_box_recipe(BODY_LOW, BODY_SIZE, DP[role])
        cases[role] = {
            **source_meta,
            "dp_m": DP[role],
            "source_xml": str(source_xml[role].resolve()),
            "baseline_fluid_vtk": str(baseline_fluid.resolve()),
            "baseline_bound_vtk": str(baseline_bound.resolve()),
            "source_snapshot": source_snapshot,
            "expected": {
                "type2_body_count": recipe["ideal_type2_count"],
                "fluid_type3_count": int(source_snapshot["particles"]["fluid"]["count"]),
                "fixed_type0_count": int(source_snapshot["particles"]["fixed"]["count"]),
                "moving_type1_count": 0,
                "fluid_mass_kg": FLUID_MASS_KG,
                "body_massbody_kg": BODY_MASS_KG,
                "body_center_m": BODY_CENTER,
                "body_inertia_kg_m2": BODY_INERTIA,
                "finite_wall_faces": ["x_low", "x_high", "y_low", "y_high", "z_low"],
            },
        }
    manifest = {
        "schema": "ds02.f6.body-cellcenter-native-manifest.v1",
        "family_id": "F6",
        "recipe_id": RECIPE_ID,
        "status": "cpu_requests_ready_root_dispatch_sequential",
        "q_n_status": "not_assessed",
        "solver_or_gpu_started": False,
        "conversion_started": False,
        "official_grid_evidence": {
            "functions_math": str(FUNCTIONS_MATH.resolve()),
            "jcase_vres": str(JCASE_VRES.resolve()),
            "calc_round_pos_formula": "posmin + dp*round((pos-posmin)/dp)",
            "recipe_decision": "freeze each source global pointref; use official drawpoints for body-only exact target because body z=0.88 is not commensurate with dp=0.025 half-phase",
        },
        "continuous_contract": {
            "body_low_m": BODY_LOW,
            "body_high_m": BODY_HIGH,
            "body_mass_kg": BODY_MASS_KG,
            "body_center_m": BODY_CENTER,
            "body_inertia_kg_m2": BODY_INERTIA,
            "fluid_mass_kg": FLUID_MASS_KG,
            "wall_low_m": WALL_LOW,
            "wall_size_m": WALL_SIZE,
            "boundary_strategy_unchanged": True,
            "control_time_unchanged": True,
            "mass_normalization": "forbidden",
        },
        "source_hashes": {
            str(path.resolve()): _sha(path)
            for path in (STATIC_PROPOSAL, CANONICAL_MOTHER, FUNCTIONS_MATH, JCASE_VRES, GENCASE_TEMPLATE, RUNTIME_V2, GENCASE, PARTVTK)
            if path.is_file()
        },
        "cases": cases,
    }
    _json_write(MANIFEST, manifest)
    requests: dict[str, str] = {}
    for role, case in cases.items():
        case_id = str(case["case_id"])
        request_path = REQUESTS_ROOT / f"{case_id}.json"
        attempt_id = f"{case_id}_NATIVE_INITIAL_001"
        request = {
            "schema": "ds02.runner.request.v1",
            "family_id": "F6",
            "case_id": case_id,
            "attempt_id": attempt_id,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "command": [
                "/usr/bin/python3",
                str(Path(__file__).resolve()),
                "run-case",
                "--manifest",
                str(MANIFEST.resolve()),
                "--role",
                role,
                "--output-root",
                "{attempt_root}",
            ],
            "cwd": str(ROOT.resolve()),
            "max_wall_seconds": 1800,
            "cpu_threads": 4,
            "estimated_storage_bytes": STORAGE_BYTES[role],
            "input_files": _request_inputs(case, MANIFEST),
            "worktree_root": str(ROOT.resolve()),
            "purpose": "F6 explicit body cell-centre GenCase plus official PartVTK initial typed/mass/wall audit; no solver/GPU/conversion",
            "recipe_id": RECIPE_ID,
            "role": role,
            "expected": case["expected"],
            "source_input_hashes": {
                "candidate_xml": _sha(Path(str(case["candidate_xml"]))),
                "source_xml": _sha(Path(str(case["source_xml"]))),
                "baseline_fluid_vtk": _sha(Path(str(case["baseline_fluid_vtk"]))),
                "baseline_bound_vtk": _sha(Path(str(case["baseline_bound_vtk"]))),
            },
            "launch_policy": "root may run coarse first; medium/fine must wait for the previous native initial report and remain separate immutable attempts",
            "q_n_status": "not_assessed",
        }
        _json_write(request_path, request)
        requests[role] = str(request_path.resolve())
    manifest["request_paths"] = requests
    manifest["manifest_sha256_after_requests"] = None
    _json_write(MANIFEST, manifest)
    # Request input hashes intentionally bind the final manifest bytes.  Rewrite
    # request files once more after the manifest's final fields are present.
    for role, request_path_text in requests.items():
        request_path = Path(request_path_text)
        request = _json_read(request_path)
        request["input_files"] = _request_inputs(cases[role], MANIFEST)
        _json_write(request_path, request)
    manifest["manifest_sha256_after_requests"] = _sha(MANIFEST)
    _json_write(MANIFEST, manifest)
    result = {
        "schema": "ds02.f6.body-cellcenter-native-preparation.v1",
        "recipe_id": RECIPE_ID,
        "manifest": str(MANIFEST.resolve()),
        "manifest_sha256": _sha(MANIFEST),
        "requests": requests,
        "solver_or_gpu_started": False,
        "conversion_started": False,
        "q_n_status": "not_assessed",
    }
    _json_write(SCOPE_ROOT / "preparation-report.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("prepare")
    run = sub.add_parser("run-case")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--role", choices=ROLES, required=True)
    run.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "prepare":
        result = prepare()
    else:
        result = run_case(args.manifest, args.output_root, args.role)
    print(json.dumps({
        "schema": result["schema"],
        "recipe_id": result.get("recipe_id", RECIPE_ID),
        "status": result.get("status", "ready"),
        "role": result.get("role"),
        "solver_or_gpu_started": result.get("solver_or_gpu_started", False),
        "q_n_status": result.get("q_n_status", "not_assessed"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
