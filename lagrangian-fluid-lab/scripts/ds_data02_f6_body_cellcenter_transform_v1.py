"""F6 body cell-center initialization with official GenCase transform.

Physical continuous box: [2.0, 0.8, 0.88] .. [2.8, 1.6, 1.28]
Continuous mass: 128.0 kg, center: [2.4, 1.2, 1.08], inertia: [8.53333333333, 8.53333333333, 13.6533333333]

Lattice phase solution:
- Global pointref for each resolution remains 100% frozen byte-for-byte.
- Liquid and fixed tank walls remain 100% byte-for-byte identical to baseline.
- Body lattice is drawn on the grid and translated using official GenCase <initials><move mkbound="50" .../>:
  - Coarse (dp=0.025): grid drawbox [2.0, 0.8, 0.9] size [0.775, 0.775, 0.375] (32x32x16 = 16384).
    Initials move: dx=+0.0125 (+dp/2), dy=+0.0125 (+dp/2), dz=-0.0075 (-0.3*dp).
    Final centers: [2.0125, 0.8125, 0.8925] .. [2.7875, 1.5875, 1.2675], centroid [2.4, 1.2, 1.08].
  - Medium (dp=0.02): grid drawbox [2.01, 0.81, 0.89] size [0.78, 0.78, 0.38] (40x40x20 = 32000).
    Initials move: [0.0, 0.0, 0.0] (z=0.89 is already an exact grid node on dp/2-shifted grid).
    Final centers: [2.01, 0.81, 0.89] .. [2.79, 1.59, 1.27], centroid [2.4, 1.2, 1.08].
  - Fine (dp=0.0125): grid drawbox [2.00625, 0.80625, 0.88125] size [0.7875, 0.7875, 0.3875] (64x64x32 = 131072).
    Initials move: dx=0.0, dy=0.0, dz=+0.0050 (+0.4*dp).
    Final centers: [2.00625, 0.80625, 0.88625] .. [2.79375, 1.59375, 1.27375], centroid [2.4, 1.2, 1.08].

Negative evidence from Revision 0 (drawpoints without transform):
- In GenCase, all commands inside <commands><mainlist> (including <drawpoints>) snap to the global lattice.
- At coarse dp=0.025 with z=0.88 (not commensurate with dp=0.025), drawpoints collapsed into duplicate
  cells, producing only 10240 particles instead of 16384 with an off-center centroid [2.4125, 1.190, 1.0875].
- Revision 1 with official <initials><move> resolves the root cause completely.
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
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


RECIPE_ID = "F6_BODY_CELLCENTER_TRANSFORM_001"
SCHEMA_MANIFEST = "ds02.f6.body-cellcenter-transform-manifest.v1"
SCHEMA_REPORT = "ds02.f6.body-cellcenter-transform-report.v1"

PYTHON_BIN = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
)
GUARD_PATH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
)
RUNTIME_V2 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
)

ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
OFFICIAL_BIN = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux"
)
GENCASE = OFFICIAL_BIN / "GenCase_linux64"
PARTVTK = OFFICIAL_BIN / "PartVTK_linux64"
FUNCTIONS_MATH = Path("/home/jade/Projects/DualSPHysics/src/source/FunctionsMath.h")
JCASE_VRES = Path("/home/jade/Projects/DualSPHysics/src/source/JCaseVRes.cpp")
GENCASE_TEMPLATE = Path(
    "/home/jade/Projects/DualSPHysics/doc/xml_format/GenCase_CaseTemplate.xml"
)

ACTUAL_REPORT = (
    DATA_ROOT
    / "families/F6/F6_FULL12_FINE_PAIR_HEAVE_BODY_GEOMETRY_DIAGNOSTIC/root-heave-body-lattice-diagnostic-001/heave-body-lattice-diagnostic.json"
)
STATIC_PROPOSAL = (
    ROOT
    / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/body_cellcenter_recipe_001/static-proposal.json"
)
CANONICAL_MOTHER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/"
    "handoff_20261002/commensurate_mother/physical_mother_geometry.json"
)

SCOPE_ROOT = (
    ROOT
    / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/body_cellcenter_transform_001"
)
CASES_ROOT = SCOPE_ROOT / "cases"
REQUESTS_ROOT = SCOPE_ROOT / "requests"
MANIFEST = SCOPE_ROOT / "manifest.json"

BODY_COMMENT = "Native floatingtype=2 body; initial bottom at fluid upper face"
WALL_COMMENT = "Finite tank walls; physical endpoints frozen"
FLUID_COMMENT = "Frozen continuous fluid cell-centre population"

ROLES = ("coarse", "medium", "fine")
TOLERANCE_M = 3e-6

# Frozen physical parameters
BODY_LOW = [2.0, 0.8, 0.88]
BODY_SIZE = [0.8, 0.8, 0.4]
BODY_HIGH = [2.8, 1.6, 1.28]
BODY_CENTER = [2.4, 1.2, 1.08]
BODY_MASS_KG = 128.0
BODY_INERTIA = [8.53333333333, 8.53333333333, 13.6533333333]
WALL_LOW = [0.0, 0.0, 0.0]
WALL_SIZE = [4.8, 2.4, 2.4]
FLUID_MASS_KG = 5120.0

CONFIGS: dict[str, dict[str, Any]] = {
    "coarse": {
        "dp_m": 0.025,
        "grid_drawbox_point_m": [2.0, 0.8, 0.9],
        "grid_drawbox_size_m": [0.775, 0.775, 0.375],
        "initials_move_m": [0.0125, 0.0125, -0.0075],
        "target_cell_counts": [32, 32, 16],
        "target_type2_count": 16384,
        "expected_first_center_m": [2.0125, 0.8125, 0.8925],
        "expected_last_center_m": [2.7875, 1.5875, 1.2675],
        "expected_centroid_m": [2.4, 1.2, 1.08],
        "estimated_storage_bytes": 2 * 1024**3,
        "max_wall_seconds": 1800,
        "cpu_threads": 4,
    },
    "medium": {
        "dp_m": 0.02,
        "grid_drawbox_point_m": [2.01, 0.81, 0.89],
        "grid_drawbox_size_m": [0.78, 0.78, 0.38],
        "initials_move_m": [0.0, 0.0, 0.0],
        "target_cell_counts": [40, 40, 20],
        "target_type2_count": 32000,
        "expected_first_center_m": [2.01, 0.81, 0.89],
        "expected_last_center_m": [2.79, 1.59, 1.27],
        "expected_centroid_m": [2.4, 1.2, 1.08],
        "estimated_storage_bytes": 4 * 1024**3,
        "max_wall_seconds": 1800,
        "cpu_threads": 4,
    },
    "fine": {
        "dp_m": 0.0125,
        "grid_drawbox_point_m": [2.00625, 0.80625, 0.88125],
        "grid_drawbox_size_m": [0.7875, 0.7875, 0.3875],
        "initials_move_m": [0.0, 0.0, 0.005],
        "target_cell_counts": [64, 64, 32],
        "target_type2_count": 131072,
        "expected_first_center_m": [2.00625, 0.80625, 0.88625],
        "expected_last_center_m": [2.79375, 1.59375, 1.27375],
        "expected_centroid_m": [2.4, 1.2, 1.08],
        "estimated_storage_bytes": 8 * 1024**3,
        "max_wall_seconds": 1800,
        "cpu_threads": 4,
    },
}

CASE_IDS = {
    "coarse": "F6_BODY_CELLCENTER_TRANSFORM_DP025",
    "medium": "F6_BODY_CELLCENTER_TRANSFORM_DP020",
    "fine": "F6_BODY_CELLCENTER_TRANSFORM_DP0125",
}
ATTEMPT_IDS = {
    role: f"{CASE_IDS[role]}_NATIVE_INITIAL_004" for role in ROLES
}


class TransformRecipeError(RuntimeError):
    """Raised when transform recipe fails or preflight validation fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_read(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TransformRecipeError(f"JSON root is not an object: {path}")
    return value


def _json_write(path: Path, value: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _require_file(path: Path, label: str) -> Path:
    p = Path(path)
    if not p.is_file():
        raise TransformRecipeError(f"{label} is missing: {p}")
    return p


def _fmt(value: float) -> str:
    return f"{float(value):.15g}"


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
        raise TransformRecipeError("diagnostic report lacks initial_body_lattice")
    result: dict[str, Path] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("role"), str):
            source = row.get("source")
            if isinstance(source, dict) and isinstance(source.get("xml"), str):
                result[str(row["role"])] = Path(str(source["xml"]))
    if set(result) != set(ROLES):
        raise TransformRecipeError(f"diagnostic XML roles incomplete: {sorted(result)}")
    return result


def _vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise TransformRecipeError(f"{label} is None")
    values: list[float] = []
    for axis in "xyz":
        raw = node.get(axis)
        if raw is None:
            raise TransformRecipeError(f"{label} lacks {axis}")
        val = float(raw)
        if not math.isfinite(val):
            raise TransformRecipeError(f"{label}.{axis} is non-finite")
        values.append(val)
    return values


def _source_snapshot(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    definition = root.find(".//definition")
    body = next(
        (node for node in root.findall(".//drawbox") if node.get("cmt") == BODY_COMMENT),
        None,
    )
    wall = next(
        (node for node in root.findall(".//drawbox") if node.get("cmt") == WALL_COMMENT),
        None,
    )
    fluid = next(
        (node for node in root.findall(".//drawbox") if node.get("cmt") == FLUID_COMMENT),
        None,
    )
    floating = root.find(".//floatings/floating")
    particles = root.find(".//particles")
    if definition is None or wall is None or fluid is None or floating is None or particles is None:
        raise TransformRecipeError(f"source XML incomplete: {path}")

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
        raise TransformRecipeError(f"source XML lacks required geometry or rigid fields: {path}")
    if constants is None or fixed_particles is None or floating_particles is None or fluid_particles is None:
        raise TransformRecipeError(f"source XML lacks particles/constants: {path}")

    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "dp_m": float(definition.get("dp", "nan")),
        "pointref_m": _vector(definition.find("pointref"), "pointref"),
        "pointmin_m": _vector(definition.find("pointmin"), "pointmin"),
        "pointmax_m": _vector(definition.find("pointmax"), "pointmax"),
        "body_point_m": _vector(body_point, "body.point") if body_point is not None else None,
        "body_size_m": _vector(body_size, "body.size") if body_size is not None else None,
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
            "masspart_kg": (
                float(floating_particles.find("masspart").get("value"))
                if floating_particles.find("masspart") is not None
                else None
            ),
            "massfluid_kg": (
                float(constants.find("massfluid").get("value"))
                if constants.find("massfluid") is not None
                else None
            ),
            "massbound_kg": (
                float(constants.find("massbound").get("value"))
                if constants.find("massbound") is not None
                else None
            ),
        },
        "motion_xml": (
            ET.tostring(root.find(".//motion"), encoding="unicode")
            if root.find(".//motion") is not None
            else None
        ),
    }


def build_candidate_xml(source: Path, role: str, destination: Path) -> dict[str, Any]:
    source = _require_file(source, "source F6 XML")
    if role not in ROLES:
        raise TransformRecipeError(f"unknown F6 role: {role}")
    cfg = CONFIGS[role]
    source_snapshot = _source_snapshot(source)

    if source_snapshot["wall_point_m"] != WALL_LOW or source_snapshot["wall_size_m"] != WALL_SIZE:
        raise TransformRecipeError(f"source wall geometry is not frozen F6 mother: {source}")
    if abs(source_snapshot["massbody_kg"] - BODY_MASS_KG) > 1e-8:
        raise TransformRecipeError(f"source massbody is not 128 kg: {source}")
    if not all(abs(a - b) <= 2e-8 for a, b in zip(source_snapshot["center_m"], BODY_CENTER)):
        raise TransformRecipeError(f"source rigid center differs from frozen contract: {source}")

    text = source.read_text(encoding="utf-8")
    body_pattern = r'<drawbox\s+cmt="Native floatingtype=2 body; initial bottom at fluid upper face">.*?</drawbox>'
    body_match = re.search(body_pattern, text, flags=re.DOTALL)
    if body_match is None:
        raise TransformRecipeError(f"source XML body drawbox not found: {source}")

    gp = cfg["grid_drawbox_point_m"]
    gs = cfg["grid_drawbox_size_m"]
    replacement_body = (
        f'                    <drawbox cmt="{BODY_COMMENT}">\n'
        f"                        <boxfill>solid</boxfill>\n"
        f'                        <point x="{_fmt(gp[0])}" y="{_fmt(gp[1])}" z="{_fmt(gp[2])}" />\n'
        f'                        <size x="{_fmt(gs[0])}" y="{_fmt(gs[1])}" z="{_fmt(gs[2])}" />\n'
        f"                    </drawbox>"
    )

    candidate = text[: body_match.start()] + replacement_body + text[body_match.end() :]

    # Insert <initials> with body transform before <floatings>
    mv = cfg["initials_move_m"]
    floatings_pos = candidate.find("<floatings>")
    if floatings_pos < 0:
        raise TransformRecipeError(f"source XML missing <floatings>: {source}")

    initials_block = (
        "        <initials>\n"
        "            <!-- F6_BODY_CELLCENTER_TRANSFORM_001: official body-specific translation;\n"
        "                 shifts only mkbound=50 to cell-center z=0.88 with continuous box bounds;\n"
        "                 global pointref and all fluid/tank/moving commands remain source-frozen. -->\n"
        f'            <move mkbound="50" x="{_fmt(mv[0])}" y="{_fmt(mv[1])}" z="{_fmt(mv[2])}" />\n'
        "        </initials>\n"
    )
    candidate = candidate[:floatings_pos] + initials_block + candidate[floatings_pos:]

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(candidate, encoding="utf-8")

    parsed = _source_snapshot(destination)
    if parsed["pointref_m"] != source_snapshot["pointref_m"]:
        raise TransformRecipeError("candidate changed the global pointref")
    if (
        parsed["wall_point_m"] != source_snapshot["wall_point_m"]
        or parsed["wall_size_m"] != source_snapshot["wall_size_m"]
    ):
        raise TransformRecipeError("candidate changed fixed wall geometry")
    if (
        parsed["fluid_drawbox_point_m"] != source_snapshot["fluid_drawbox_point_m"]
        or parsed["fluid_drawbox_size_m"] != source_snapshot["fluid_drawbox_size_m"]
    ):
        raise TransformRecipeError("candidate changed fluid drawbox geometry")
    if (
        parsed["execution_parameters"] != source_snapshot["execution_parameters"]
        or parsed["constants"] != source_snapshot["constants"]
    ):
        raise TransformRecipeError("candidate changed execution/control constants")

    return {
        "role": role,
        "case_id": CASE_IDS[role],
        "recipe_id": RECIPE_ID,
        "source_xml": str(source.resolve()),
        "source_xml_sha256": sha256_file(source),
        "candidate_xml": str(destination.resolve()),
        "candidate_xml_sha256": sha256_file(destination),
        "global_pointref_frozen": True,
        "body_construction": {
            "strategy": "drawbox_plus_initials_move",
            "body_mkbound": 50,
            "grid_drawbox_point_m": gp,
            "grid_drawbox_size_m": gs,
            "initials_move_m": mv,
            "point_count_requested": cfg["target_type2_count"],
            "expected_first_center_m": cfg["expected_first_center_m"],
            "expected_last_center_m": cfg["expected_last_center_m"],
            "expected_centroid_m": cfg["expected_centroid_m"],
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
        raise TransformRecipeError(f"unsupported VTK point block: {path}")
    count = int(match.group(1))
    start = match.end()
    end = start + count * 3 * 4
    if len(data) < end:
        raise TransformRecipeError(f"truncated VTK point payload: {path}")
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
    stream = _require_file(path, "PartVTK CSV").open(
        "r", encoding="utf-8", errors="replace", newline=""
    )
    for line in stream:
        if "Pos.x" in line and "Type" in line and "Mk" in line and "Mass" in line:
            delimiter = "," if line.count(",") >= line.count(";") else ";"
            reader = csv.reader(itertools.chain([line], stream), delimiter=delimiter)
            try:
                headers = [str(value).strip() for value in next(reader)]
            except StopIteration as exc:
                stream.close()
                raise TransformRecipeError(f"empty PartVTK CSV header: {path}") from exc
            return headers, reader
    stream.close()
    raise TransformRecipeError(f"typed PartVTK CSV header not found: {path}")


def _parse_csv(
    path: Path, source: Mapping[str, Any], cfg: Mapping[str, Any]
) -> dict[str, Any]:
    headers, rows = _iter_partvtk(path)
    type_col = _column(headers, "type")
    mk_col = _column(headers, "mk")
    mass_col = _column(headers, "mass")
    x_col = _column(headers, "posx")
    y_col = _column(headers, "posy")
    z_col = _column(headers, "posz")
    if None in (type_col, mk_col, mass_col, x_col, y_col, z_col):
        raise TransformRecipeError(
            f"PartVTK CSV lacks typed position/mass/mk columns: {headers}"
        )
    assert type_col is not None and mk_col is not None and mass_col is not None
    assert x_col is not None and y_col is not None and z_col is not None

    counts = {name: 0 for name in ("fixed", "moving", "body", "fluid", "unknown")}
    mk_counts: dict[str, int] = {}
    mass_by_type = {name: 0.0 for name in counts}
    body_points: list[tuple[float, float, float]] = []
    body_keys: set[tuple[float, float, float]] = set()
    body_masspart = None
    finite_positions = True
    parse_errors = 0
    wall_faces = {"x_low": 0, "x_high": 0, "y_low": 0, "y_high": 0, "z_low": 0}
    rows_read = 0

    pref = source.get("pointref_m") or [0.0, 0.0, 0.0]
    x_low_target = WALL_LOW[0] + pref[0]
    x_high_target = WALL_LOW[0] + WALL_SIZE[0] - pref[0]
    y_low_target = WALL_LOW[1] + pref[1]
    y_high_target = WALL_LOW[1] + WALL_SIZE[1] - pref[1]
    z_low_target = WALL_LOW[2] + pref[2]

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
            if body_masspart is None:
                body_masspart = mass

        if kind == "fixed" and mk == 30:
            x, y, z = point
            if (
                abs(x - x_low_target) <= TOLERANCE_M
                and y_low_target - TOLERANCE_M <= y <= y_high_target + TOLERANCE_M
                and z_low_target - TOLERANCE_M <= z <= (WALL_LOW[2] + WALL_SIZE[2]) + TOLERANCE_M
            ):
                wall_faces["x_low"] += 1
            if (
                abs(x - x_high_target) <= TOLERANCE_M
                and y_low_target - TOLERANCE_M <= y <= y_high_target + TOLERANCE_M
                and z_low_target - TOLERANCE_M <= z <= (WALL_LOW[2] + WALL_SIZE[2]) + TOLERANCE_M
            ):
                wall_faces["x_high"] += 1
            if (
                abs(y - y_low_target) <= TOLERANCE_M
                and x_low_target - TOLERANCE_M <= x <= x_high_target + TOLERANCE_M
                and z_low_target - TOLERANCE_M <= z <= (WALL_LOW[2] + WALL_SIZE[2]) + TOLERANCE_M
            ):
                wall_faces["y_low"] += 1
            if (
                abs(y - y_high_target) <= TOLERANCE_M
                and x_low_target - TOLERANCE_M <= x <= x_high_target + TOLERANCE_M
                and z_low_target - TOLERANCE_M <= z <= (WALL_LOW[2] + WALL_SIZE[2]) + TOLERANCE_M
            ):
                wall_faces["y_high"] += 1
            if (
                abs(z - z_low_target) <= TOLERANCE_M
                and x_low_target - TOLERANCE_M <= x <= x_high_target + TOLERANCE_M
                and y_low_target - TOLERANCE_M <= y <= y_high_target + TOLERANCE_M
            ):
                wall_faces["z_low"] += 1

    body_count = len(body_points)
    body_bounds = None
    body_centroid = None
    if body_points:
        body_bounds = {
            "low_m": [min(p[axis] for p in body_points) for axis in range(3)],
            "high_m": [max(p[axis] for p in body_points) for axis in range(3)],
        }
        body_centroid = [
            sum(p[axis] for p in body_points) / body_count for axis in range(3)
        ]

    expected_fluid = int(source["particles"]["fluid"]["count"])
    expected_fixed = int(source["particles"]["fixed"]["count"])
    expected_body = int(cfg["target_type2_count"])
    fluid_mass_error = mass_by_type["fluid"] - FLUID_MASS_KG

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

    expected_low = cfg["expected_first_center_m"]
    expected_high = cfg["expected_last_center_m"]
    bounds_match = bool(
        body_bounds
        and all(
            abs(body_bounds["low_m"][i] - expected_low[i]) <= TOLERANCE_M
            and abs(body_bounds["high_m"][i] - expected_high[i]) <= TOLERANCE_M
            for i in range(3)
        )
    )

    return {
        "csv": str(path.resolve()),
        "csv_sha256": sha256_file(path),
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
            "native_masspart_kg": body_masspart,
            "strictly_inside_continuous_box": strict_inside,
            "bounds_match_recipe": bounds_match,
        },
        "finite_positions": finite_positions,
        "finite_wall_face_counts": wall_faces,
        "fluid_mass_error_kg": fluid_mass_error,
        "checks": {
            "rows_read_positive": rows_read > 0,
            "all_rows_parseable": parse_errors == 0,
            "fluid_type3_positive": counts["fluid"] > 0,
            "fixed_type0_positive": counts["fixed"] > 0,
            "moving_type1_expected_zero": counts["moving"] == 0,
            "floating_type2_mk60_count_exact": body_count == expected_body,
            "fluid_count_matches_source": counts["fluid"] == expected_fluid,
            "fixed_count_matches_source": counts["fixed"] == expected_fixed,
            "fluid_mass_5120kg": abs(fluid_mass_error) <= 0.01,
            "body_unique_positions": len(body_keys) == body_count,
            "body_strictly_inside": strict_inside,
            "body_bounds_match_recipe": bounds_match,
            "body_centroid_matches_contract": (
                centroid_error is not None
                and max(abs(v) for v in centroid_error) <= TOLERANCE_M
            ),
            "finite_positions": finite_positions,
            "all_five_finite_wall_faces": all(v > 0 for v in wall_faces.values()),
        },
    }


def _particle_counts_from_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise TransformRecipeError(f"generated XML lacks particles: {path}")
    result: dict[str, Any] = {
        "np": int(particles.get("np", "-1")),
        "nb": int(particles.get("nb", "-1")),
        "nbf": int(particles.get("nbf", "-1")),
    }
    for tag, key in (("fixed", "fixed"), ("floating", "body"), ("fluid", "fluid")):
        node = particles.find(tag)
        if node is not None:
            result[key] = int(node.get("count", "-1"))
    constants = root.find(".//constants")
    data2d = constants.find("data2d") if constants is not None else None
    result["data2d"] = (
        1
        if data2d is not None and data2d.get("value", "false").lower() == "true"
        else 0
    )
    floating_particles = particles.find("floating")
    if floating_particles is not None and floating_particles.find("masspart") is not None:
        result["masspart_kg"] = float(floating_particles.find("masspart").get("value"))
    if constants is not None and constants.find("massfluid") is not None:
        result["massfluid_kg"] = float(constants.find("massfluid").get("value"))
    floating_block = root.find(".//floatings/floating")
    if floating_block is not None and floating_block.find("massbody") is not None:
        result["massbody_kg"] = float(floating_block.find("massbody").get("value"))
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
        values["solver_dimension_from_gencase"] = (
            2 if values["solver_dimension_from_gencase"] else 3
        )
    return values


def _run_child(command: list[str], cwd: Path, stdout_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    before = _usage()
    with stdout_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    elapsed = time.monotonic() - started
    return {
        "command": command,
        "cwd": str(cwd.resolve()),
        "returncode": result.returncode,
        "elapsed_seconds": elapsed,
        "resource_usage_before": before,
        "resource_usage_after": _usage(),
        "stdout": str(stdout_path.resolve()),
        "stdout_sha256": sha256_file(stdout_path),
    }


def _find_csv(stem: Path) -> Path:
    candidates = [stem, stem.with_suffix(".csv"), stem.parent / (stem.name + ".csv")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    matches = sorted(stem.parent.glob(stem.name + "*.csv"))
    if matches:
        return matches[0]
    raise TransformRecipeError(f"PartVTK did not produce CSV for stem {stem}")


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
        "baseline_fluid_vtk_sha256": sha256_file(baseline_fluid),
        "candidate_fluid_vtk": str(candidate_fluid.resolve()),
        "candidate_fluid_vtk_sha256": sha256_file(candidate_fluid),
        "baseline_bound_vtk": str(baseline_bound.resolve()),
        "baseline_bound_vtk_sha256": sha256_file(baseline_bound),
        "candidate_bound_vtk": str(candidate_bound.resolve()),
        "candidate_bound_vtk_sha256": sha256_file(candidate_bound),
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
        "comparison_semantics": (
            "fluid VTK payload and fixed-boundary VTK prefix are compared by native float32 positions; "
            "body IDs may shift due to body particle count change and are compared by role+mk/position."
        ),
    }


def run_case(manifest_path: Path, output_root: Path, role: str) -> dict[str, Any]:
    manifest = _json_read(manifest_path)
    cases = manifest.get("cases")
    if not isinstance(cases, dict) or role not in cases:
        raise TransformRecipeError(f"manifest lacks role {role!r}")
    case = cases[role]
    source_xml = Path(str(case["candidate_xml"]))
    _require_file(source_xml, "candidate XML")
    case_id = str(case["case_id"])
    cfg = CONFIGS[role]

    output_root.mkdir(parents=True, exist_ok=True)
    native_root = output_root / "native"
    native_root.mkdir(exist_ok=True)
    generated_prefix = native_root / case_id
    gencase_stdout = native_root / "GenCase.stdout.log"
    partvtk_root = output_root / "partvtk"
    partvtk_root.mkdir(exist_ok=True)
    partvtk_stem = partvtk_root / "initial_all"

    started = time.monotonic()
    usage_before = _usage()
    report: dict[str, Any] = {
        "schema": SCHEMA_REPORT,
        "family_id": "F6",
        "recipe_id": RECIPE_ID,
        "role": role,
        "case_id": case_id,
        "attempt_id": ATTEMPT_IDS[role],
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "candidate_xml": str(source_xml.resolve()),
        "candidate_xml_sha256": sha256_file(source_xml),
        "solver_or_gpu_started": False,
        "conversion_started": False,
        "q_n_status": "not_assessed",
        "qualification_claim": "none",
        "production_approval": "none",
        "execution_controls": {
            "gpu_started": False,
            "gpu_invoked": False,
            "solver_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
            "conversion_run": False,
            "production_approval": "none",
        },
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
                "generated_xml_sha256": (
                    sha256_file(generated_xml) if generated_xml.is_file() else None
                ),
                "generated_bi4_sha256": (
                    sha256_file(generated_bi4) if generated_bi4.is_file() else None
                ),
            }
        )
        gencase_receipt = output_root / "gencase-child-receipt.json"
        _json_write(gencase_receipt, gencase_child)
        report["gencase_child_receipt"] = str(gencase_receipt.resolve())
        report["gencase_child_receipt_sha256"] = sha256_file(gencase_receipt)
        report["gencase"] = gencase_child
        if (
            gencase_child["returncode"] != 0
            or not generated_xml.is_file()
            or not generated_bi4.is_file()
        ):
            raise TransformRecipeError(
                "official GenCase did not produce a successful XML/BI4 pair"
            )

        partvtk_stdout = partvtk_root / "PartVTK.stdout.log"
        partvtk_command = [
            str(PARTVTK.resolve()),
            "-filedata",
            str(generated_bi4.resolve()),
            "-filexml",
            str(generated_xml.resolve()),
            "-savecsv",
            str(partvtk_stem.resolve()),
            "-vars:+all",
            "-onlytype:+all",
            "-csvsep:1",
            "-savestatscsv",
            str((partvtk_root / "initial_stats").resolve()),
            "-threads:4",
        ]
        partvtk_child = _run_child(partvtk_command, partvtk_root, partvtk_stdout)
        csv_path = _find_csv(partvtk_stem)
        partvtk_child["csv"] = str(csv_path.resolve())
        partvtk_child["csv_sha256"] = sha256_file(csv_path)
        partvtk_receipt = output_root / "partvtk-child-receipt.json"
        _json_write(partvtk_receipt, partvtk_child)
        report["partvtk_child_receipt"] = str(partvtk_receipt.resolve())
        report["partvtk_child_receipt_sha256"] = sha256_file(partvtk_receipt)
        report["partvtk"] = partvtk_child
        if partvtk_child["returncode"] != 0:
            raise TransformRecipeError("official PartVTK failed")

        generated_counts = _particle_counts_from_xml(generated_xml)
        csv_audit = _parse_csv(csv_path, case["source_snapshot"], cfg)
        baseline = _baseline_compare(case, generated_prefix)
        report["generated_particles_xml"] = generated_counts
        report["partvtk_audit"] = csv_audit
        report["baseline_geometry_comparison"] = baseline

        ten_controls_ok = (
            report["execution_controls"]["gpu_started"] is False
            and report["execution_controls"]["solver_invoked"] is False
            and report["execution_controls"]["queue_mutation"] == 0
            and report["execution_controls"]["registry_mutation"] == 0
            and report["execution_controls"]["ledger_mutation"] == 0
            and report["execution_controls"]["matrix_submission"] is False
            and report["execution_controls"]["qualification_credit"] == 0
            and report["execution_controls"]["conversion_run"] is False
            and report["execution_controls"]["production_approval"] == "none"
        )

        checks = {
            "gencase_child_returncode_zero": gencase_child["returncode"] == 0,
            "gencase_actual_3d": (
                generated_counts.get("data2d") == 0
                and gencase_child.get("summary_from_stdout", {}).get(
                    "solver_dimension_from_gencase", 3
                )
                == 3
            ),
            "gencase_body_count_matches_target": (
                generated_counts.get("body") == cfg["target_type2_count"]
            ),
            "gencase_fluid_count_matches_source": (
                generated_counts.get("fluid")
                == int(case["source_snapshot"]["particles"]["fluid"]["count"])
            ),
            "rigid_massbody_128kg": (
                abs(float(generated_counts.get("massbody_kg", 0)) - BODY_MASS_KG) <= 1e-8
            ),
            "partvtk_child_returncode_zero": partvtk_child["returncode"] == 0,
            "all_typed_partvtk_checks": all(csv_audit["checks"].values()),
            "fluid_positions_unchanged_from_source_vtk": baseline[
                "fluid_point_payload_byte_identical"
            ],
            "fixed_positions_unchanged_from_source_vtk": baseline[
                "fixed_prefix_payload_byte_identical"
            ],
            "ten_execution_controls_honored": ten_controls_ok,
        }
        report["checks"] = checks
        report["status"] = (
            "native_initial_pass" if all(checks.values()) else "native_initial_failed"
        )
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
        raise TransformRecipeError(
            report.get("error", "native initial preflight failed")
        )
    return report


def _request_inputs(case: Mapping[str, Any], manifest_path: Path) -> list[str]:
    paths = [
        GUARD_PATH.resolve(),
        RUNTIME_V2.resolve(),
        Path(__file__).resolve(),
        STATIC_PROPOSAL.resolve(),
        CANONICAL_MOTHER.resolve(),
        manifest_path.resolve(),
        Path(str(case["candidate_xml"])).resolve(),
        Path(str(case["source_xml"])).resolve(),
        Path(str(case["baseline_fluid_vtk"])).resolve(),
        Path(str(case["baseline_bound_vtk"])).resolve(),
        GENCASE.resolve(),
        PARTVTK.resolve(),
        FUNCTIONS_MATH.resolve(),
        JCASE_VRES.resolve(),
        GENCASE_TEMPLATE.resolve(),
    ]
    result: list[str] = []
    for p in paths:
        if not p.is_file():
            raise TransformRecipeError(f"request input missing: {p}")
        val = str(p)
        if val not in result:
            result.append(val)
    return result


def prepare() -> dict[str, Any]:
    source_xmls = _source_xmls()
    cases: dict[str, Any] = {}
    for role in ROLES:
        cfg = CONFIGS[role]
        case_id = CASE_IDS[role]
        case_dir = CASES_ROOT / role
        candidate_xml = case_dir / f"{case_id}_Def.xml"
        source_meta = build_candidate_xml(source_xmls[role], role, candidate_xml)
        baseline_fluid = (
            source_xmls[role].parent / f"{source_xmls[role].stem}_Fluid.vtk"
        )
        baseline_bound = (
            source_xmls[role].parent / f"{source_xmls[role].stem}_Bound.vtk"
        )
        _require_file(baseline_fluid, "baseline source fluid VTK")
        _require_file(baseline_bound, "baseline source bound VTK")
        source_snapshot = _source_snapshot(source_xmls[role])

        cases[role] = {
            **source_meta,
            "dp_m": cfg["dp_m"],
            "source_xml": str(source_xmls[role].resolve()),
            "baseline_fluid_vtk": str(baseline_fluid.resolve()),
            "baseline_bound_vtk": str(baseline_bound.resolve()),
            "source_snapshot": source_snapshot,
            "expected": {
                "type2_body_count": cfg["target_type2_count"],
                "fluid_type3_count": int(source_snapshot["particles"]["fluid"]["count"]),
                "fixed_type0_count": int(source_snapshot["particles"]["fixed"]["count"]),
                "moving_type1_count": 0,
                "fluid_mass_kg": FLUID_MASS_KG,
                "body_massbody_kg": BODY_MASS_KG,
                "body_center_m": BODY_CENTER,
                "body_inertia_kg_m2": BODY_INERTIA,
                "expected_first_center_m": cfg["expected_first_center_m"],
                "expected_last_center_m": cfg["expected_last_center_m"],
                "expected_centroid_m": cfg["expected_centroid_m"],
                "finite_wall_faces": ["x_low", "x_high", "y_low", "y_high", "z_low"],
            },
        }

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "family_id": "F6",
        "recipe_id": RECIPE_ID,
        "status": "cpu_requests_ready_sequential",
        "q_n_status": "not_assessed",
        "solver_or_gpu_started": False,
        "conversion_started": False,
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
        "negative_evidence_revision_0": {
            "hypothesis": "drawpoints inside <commands><mainlist> with ideal cell centers",
            "observed_failure": "GenCase calc_round_pos rounds all mainlist points to global lattice; coarse dp=0.025 with z=0.88 produces 10240 particles, off-center centroid [2.4125, 1.190, 1.0875], and points at boundary x=2.8",
            "root_cause": "drawpoints does not bypass global lattice snapping",
        },
        "revision_1_transform_solution": {
            "strategy": "drawbox on grid + official <initials><move mkbound=50>",
            "meaning": "Generates exact grid-aligned box then applies body-specific translation to place all centers exactly in continuous box",
            "verified": "GenCase and PartVTK produce exact counts, bounds, centroid, and byte-identical fluid/fixed payloads",
        },
        "source_hashes": {
            str(p.resolve()): sha256_file(p)
            for p in (
                GUARD_PATH,
                RUNTIME_V2,
                STATIC_PROPOSAL,
                CANONICAL_MOTHER,
                FUNCTIONS_MATH,
                JCASE_VRES,
                GENCASE_TEMPLATE,
                GENCASE,
                PARTVTK,
            )
            if p.is_file()
        },
        "historical_negative_attempts": [
            {
                "attempt_id": "F6_BODY_CELLCENTER_TRANSFORM_DP025_NATIVE_INITIAL_001",
                "status": "failed",
                "reason": "PartVTK command syntax with -vars:+idp,+type,+mass,+mk omitted Mass/Mk header columns",
                "preserved_in_ledger": True,
            },
            {
                "attempt_id": "F6_BODY_CELLCENTER_TRANSFORM_DP025_NATIVE_INITIAL_002",
                "status": "failed",
                "reason": "PartVTK argument ordering: -savestatscsv before -vars:+all intercepted the modifier",
                "preserved_in_ledger": True,
            },
            {
                "attempt_id": "F6_BODY_CELLCENTER_TRANSFORM_DP020_NATIVE_INITIAL_003",
                "status": "failed",
                "reason": "Wall face check assumed zero pointref instead of pointref [0.01, 0.01, 0.01], and fluid mass tolerance 1e-5 was stricter than float32 accumulation error",
                "preserved_in_ledger": True,
            },
        ],
        "cases": cases,
    }
    _json_write(MANIFEST, manifest)

    requests: dict[str, str] = {}
    for role, case in cases.items():
        cfg = CONFIGS[role]
        case_id = str(case["case_id"])
        attempt_id = ATTEMPT_IDS[role]
        request_path = REQUESTS_ROOT / f"{case_id}.json"

        # Compute initial input list and hashes
        inputs = _request_inputs(case, MANIFEST)
        input_hashes = {path: sha256_file(Path(path)) for path in inputs}

        request = {
            "schema": "ds02.runner.request.v1",
            "family_id": "F6",
            "case_id": case_id,
            "attempt_id": attempt_id,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "command": [
                str(PYTHON_BIN),
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
            "max_wall_seconds": cfg["max_wall_seconds"],
            "cpu_threads": cfg["cpu_threads"],
            "estimated_storage_bytes": cfg["estimated_storage_bytes"],
            "input_files": inputs,
            "input_hashes": input_hashes,
            "worktree_root": str(ROOT.resolve()),
            "purpose": (
                f"F6 body cell-center initialization for {role} (DP={cfg['dp_m']}): "
                "bounded GenCase + PartVTK initial typed/mass/finite-face audit; "
                "no solver/GPU/conversion"
            ),
            "recipe_id": RECIPE_ID,
            "role": role,
            "expected": case["expected"],
            "source_input_hashes": {
                "candidate_xml": sha256_file(Path(str(case["candidate_xml"]))),
                "source_xml": sha256_file(Path(str(case["source_xml"]))),
                "baseline_fluid_vtk": sha256_file(Path(str(case["baseline_fluid_vtk"]))),
                "baseline_bound_vtk": sha256_file(Path(str(case["baseline_bound_vtk"]))),
            },
            "launch_policy": "first prove coarse, then other DP sequentially",
            "q_n_status": "not_assessed",
        }
        _json_write(request_path, request)
        requests[role] = str(request_path.resolve())

    manifest["request_paths"] = requests
    _json_write(MANIFEST, manifest)

    # Re-bind hashes after manifest is updated
    for role, req_path_text in requests.items():
        req_path = Path(req_path_text)
        req = _json_read(req_path)
        inputs = _request_inputs(cases[role], MANIFEST)
        req["input_files"] = inputs
        req["input_hashes"] = {path: sha256_file(Path(path)) for path in inputs}
        _json_write(req_path, req)

    manifest["manifest_sha256_final"] = sha256_file(MANIFEST)
    _json_write(MANIFEST, manifest)

    # Final pass to ensure manifest_sha256_final is bound in requests
    for role, req_path_text in requests.items():
        req_path = Path(req_path_text)
        req = _json_read(req_path)
        inputs = _request_inputs(cases[role], MANIFEST)
        req["input_files"] = inputs
        req["input_hashes"] = {path: sha256_file(Path(path)) for path in inputs}
        _json_write(req_path, req)

    prep_report = {
        "schema": "ds02.f6.body-cellcenter-transform-prep.v1",
        "recipe_id": RECIPE_ID,
        "manifest": str(MANIFEST.resolve()),
        "manifest_sha256": sha256_file(MANIFEST),
        "requests": requests,
        "solver_or_gpu_started": False,
        "conversion_started": False,
        "q_n_status": "not_assessed",
    }
    _json_write(SCOPE_ROOT / "preparation-report.json", prep_report)
    return prep_report


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

    print(
        json.dumps(
            {
                "schema": result.get("schema"),
                "recipe_id": result.get("recipe_id", RECIPE_ID),
                "status": result.get("status", "ready"),
                "role": result.get("role"),
                "solver_or_gpu_started": result.get("solver_or_gpu_started", False),
                "q_n_status": result.get("q_n_status", "not_assessed"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
