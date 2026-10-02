"""Materialize and audit a finite cell-centre F1 ECC initialization.

The original ECC reference definitions use a lattice phase that removes the
upper fluid row when it coincides with the fixed wall.  This module registers
an additive numeric-only mother: the continuous tank, obstacle, gravity and
solver controls come from an immutable copy of the original definition;
``pointmin`` selects a half-cell lattice phase, fixed faces use explicit
``vdp=0,1,2`` layers, and the fluid is populated by a commensurate
cell-centre ``fillbox``.  It never changes the continuous geometry or rescales
native mass.

The ``run-gencase`` command is intended to be called by the shared CPU runner.
It invokes only official GenCase and PartVTK, writes under the supplied
attempt root, and emits a bounded initial-state audit.  It does not invoke a
solver or a GPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import resource
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.spatial import cKDTree


FAMILY_ID = "F1"
MECHANISM_ID = "eccentric_obstacle"
PHYSICAL_CASE_ID = "F1_ECCENTRIC_CELL_CENTER_HALFDP"
SCHEMA = "ds02.f1.eccentric-cellcenter.v1"
RHO0 = 1000.0
FLUID_LOW = (0.0, 0.0, 0.0)
FLUID_SIZE = (0.4, 0.67, 0.3)
TANK_LOW = (0.0, 0.0, 0.0)
TANK_SIZE = (1.6, 0.67, 0.4)
OBSTACLE_LOW = (0.9, 0.24, 0.0)
OBSTACLE_SIZE = (0.12, 0.12, 0.45)
OUTER_FACE_BOXFILL = "bottom | left | right | front | back"
OBSTACLE_FACE_BOXFILL = "top | left | right | front | back"
BOUNDARY_LAYERS = (0, 1, 2)

_SCRIPT = Path(__file__).resolve()
_LAB = _SCRIPT.parents[1]
_SCOPE = _LAB / "campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_cellcenter_initialization_001"
DEFAULT_TEMPLATE = _SCOPE / "source/F1_REF_ECC_NOMINAL_BASE_Def.xml"

RESOLUTIONS: tuple[dict[str, Any], ...] = (
    {"resolution": "dp010", "dp_m": 0.01, "counts_xyz": (40, 67, 30)},
    {"resolution": "dp005", "dp_m": 0.005, "counts_xyz": (80, 134, 60)},
    {"resolution": "dp003333", "dp_m": 0.01 / 3.0, "counts_xyz": (120, 201, 90)},
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    raise TypeError(type(value).__name__)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=_json_default)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _q(value: float) -> str:
    return format(float(value), ".16g")


def _attrs(element: ET.Element | None) -> dict[str, Any]:
    if element is None:
        return {}
    result: dict[str, Any] = {}
    for key, value in element.attrib.items():
        try:
            result[key] = float(value)
            if result[key].is_integer():
                result[key] = int(result[key])
        except ValueError:
            result[key] = value
    return result


def _vec(element: ET.Element, key: str = "point") -> tuple[float, float, float]:
    node = element.find(key)
    if node is None:
        raise ValueError(f"missing {key} in {element.tag}")
    return tuple(float(node.attrib[axis]) for axis in ("x", "y", "z"))


def _size(element: ET.Element) -> tuple[float, float, float]:
    node = element.find("size")
    if node is None:
        raise ValueError(f"missing size in {element.tag}")
    return tuple(float(node.attrib[axis]) for axis in ("x", "y", "z"))


def _find_drawboxes(mainlist: ET.Element) -> list[ET.Element]:
    return [node for node in mainlist if node.tag == "drawbox"]


def inspect_source(template: Path) -> dict[str, Any]:
    """Extract the physical contract and controls from the immutable source."""
    source_hash = sha256(template)
    root = ET.parse(template).getroot()
    definition = root.find("./casedef/geometry/definition")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if definition is None or mainlist is None:
        raise ValueError("ECC source lacks definition/mainlist")
    boxes = _find_drawboxes(mainlist)
    if len(boxes) != 4:
        raise ValueError(f"expected 4 source drawboxes, got {len(boxes)}")
    fluid, outer, obstacle_void, obstacle_bound = boxes
    if fluid.findtext("boxfill") != "solid" or tuple(round(v, 12) for v in _vec(fluid)) != FLUID_LOW:
        raise ValueError("source fluid geometry differs from frozen ECC fill")
    if tuple(round(v, 12) for v in _size(fluid)) != FLUID_SIZE:
        raise ValueError("source fluid extent differs from frozen ECC fill")
    if outer.findtext("boxfill") != OUTER_FACE_BOXFILL:
        raise ValueError("source outer face selection differs")
    if tuple(round(v, 12) for v in _vec(outer)) != TANK_LOW or tuple(round(v, 12) for v in _size(outer)) != TANK_SIZE:
        raise ValueError("source tank geometry differs")
    if obstacle_void.findtext("boxfill") != "solid" or tuple(round(v, 12) for v in _vec(obstacle_void)) != OBSTACLE_LOW or tuple(round(v, 12) for v in _size(obstacle_void)) != OBSTACLE_SIZE:
        raise ValueError("source obstacle void differs")
    if obstacle_bound.findtext("boxfill") != OBSTACLE_FACE_BOXFILL or tuple(round(v, 12) for v in _vec(obstacle_bound)) != OBSTACLE_LOW or tuple(round(v, 12) for v in _size(obstacle_bound)) != OBSTACLE_SIZE:
        raise ValueError("source obstacle face selection differs")

    constants_node = root.find("./casedef/constantsdef")
    if constants_node is None:
        raise ValueError("source constantsdef missing")
    constants = {node.tag: _attrs(node) for node in constants_node}
    parameters_node = root.find("./execution/parameters")
    if parameters_node is None:
        raise ValueError("source execution parameters missing")
    all_parameters = {
        node.attrib["key"]: node.attrib.get("value")
        for node in parameters_node.findall("parameter")
        if "key" in node.attrib
    }
    # These are numerical/discretization or output controls. They stay in the
    # numeric binding and are deliberately absent from the physical hash.
    numeric_keys = {
        "SavePosDouble", "StepAlgorithm", "VerletSteps", "Kernel", "CoefDtMin",
        "DtIni", "DtMin", "DtFixed", "DtAllParticles", "TimeMax", "TimeOut",
        "RhopOutMin", "RhopOutMax",
    }
    physical_parameters = {key: value for key, value in all_parameters.items() if key not in numeric_keys}
    physical_payload = {
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "continuous_geometry": {
            "tank_low_m": list(TANK_LOW),
            "tank_size_m": list(TANK_SIZE),
            "tank_high_m": [TANK_LOW[i] + TANK_SIZE[i] for i in range(3)],
            "closed_outer_faces": ["x=0", "x=1.6", "y=0", "y=0.67", "z=0"],
            "open_top": True,
            "fluid_low_m": list(FLUID_LOW),
            "fluid_size_m": list(FLUID_SIZE),
            "fluid_volume_m3": math.prod(FLUID_SIZE),
            "fluid_continuous_mass_kg": RHO0 * math.prod(FLUID_SIZE),
            "obstacle_low_m": list(OBSTACLE_LOW),
            "obstacle_size_m": list(OBSTACLE_SIZE),
            "obstacle_high_m": [OBSTACLE_LOW[i] + OBSTACLE_SIZE[i] for i in range(3)],
        },
        "physical_controls": {
            "boundary_method": "DBC",
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "density_kg_m3": RHO0,
            "constantsdef": constants,
            "parameters": physical_parameters,
            "motion": "empty static motion element",
            "no_normals_section": True,
        },
        "source_contract": {
            "mechanism_id": MECHANISM_ID,
            "source_template_sha256": source_hash,
            "physical_fields_verified_from_source": True,
        },
    }
    return {
        "source_path": str(template.resolve()),
        "source_sha256": source_hash,
        "physical_payload": physical_payload,
        "physical_hash": hashlib.sha256(_canonical(physical_payload).encode()).hexdigest(),
        "physical_parameters": physical_parameters,
        "numeric_parameters": {key: value for key, value in all_parameters.items() if key in numeric_keys},
    }


def _mainlist(dp: float) -> str:
    half = dp / 2.0
    fluid_size = tuple(size - dp for size in FLUID_SIZE)
    return f"""<mainlist>
          <setshapemode>dp | bound</setshapemode>
          <setdrawmode mode="full" />
          <setmkbound mk="0" />
          <drawbox cmt="Frozen ECC outer physical faces; vdp layers are numeric half-cell support only">
            <boxfill>{OUTER_FACE_BOXFILL}</boxfill>
            <point x="{_q(TANK_LOW[0])}" y="{_q(TANK_LOW[1])}" z="{_q(TANK_LOW[2])}" />
            <size x="{_q(TANK_SIZE[0])}" y="{_q(TANK_SIZE[1])}" z="{_q(TANK_SIZE[2])}" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkvoid />
          <drawbox cmt="Frozen ECC obstacle solid volume; physical bounds unchanged">
            <boxfill>solid</boxfill>
            <point x="{_q(OBSTACLE_LOW[0])}" y="{_q(OBSTACLE_LOW[1])}" z="{_q(OBSTACLE_LOW[2])}" />
            <size x="{_q(OBSTACLE_SIZE[0])}" y="{_q(OBSTACLE_SIZE[1])}" z="{_q(OBSTACLE_SIZE[2])}" />
          </drawbox>
          <setmkbound mk="1" />
          <drawbox cmt="Frozen ECC obstacle physical faces; vdp layers are numeric support only">
            <boxfill>{OBSTACLE_FACE_BOXFILL}</boxfill>
            <point x="{_q(OBSTACLE_LOW[0])}" y="{_q(OBSTACLE_LOW[1])}" z="{_q(OBSTACLE_LOW[2])}" />
            <size x="{_q(OBSTACLE_SIZE[0])}" y="{_q(OBSTACLE_SIZE[1])}" z="{_q(OBSTACLE_SIZE[2])}" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkfluid mk="0" />
          <fillbox x="{_q(dp)}" y="{_q(dp)}" z="{_q(dp)}" cmt="Numeric-only cell-centre seeding: low+dp/2 through high-dp/2">
            <modefill>fluid</modefill>
            <point x="{_q(FLUID_LOW[0] + half)}" y="{_q(FLUID_LOW[1] + half)}" z="{_q(FLUID_LOW[2] + half)}" />
            <size x="{_q(fluid_size[0])}" y="{_q(fluid_size[1])}" z="{_q(fluid_size[2])}" />
          </fillbox>
        </mainlist>"""


def _replace_once(text: str, pattern: str, replacement: str, *, flags: int = 0) -> str:
    result, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise ValueError(f"expected one match for {pattern!r}, got {count}")
    return result


def materialize_case(template: Path, output_root: Path, spec: dict[str, Any], source_info: dict[str, Any]) -> dict[str, Any]:
    dp = float(spec["dp_m"])
    resolution = str(spec["resolution"])
    case_id = f"F1_ECC_CELL_CENTER_HALFDP_{resolution.upper()}"
    text = template.read_text(encoding="utf-8")
    text = _replace_once(text, r"<!-- mechanism=.*? -->", f"<!-- mechanism={MECHANISM_ID}; physical_case_id={PHYSICAL_CASE_ID}; resolution={resolution}; numeric-only-cellcenter-mother -->")
    text = _replace_once(text, r'<definition dp="[^"]+"', f'<definition dp="{_q(dp)}"')
    text = _replace_once(text, r'<pointmin x="[^"]+" y="[^"]+" z="[^"]+"\s*/>', f'<pointmin x="{_q(-dp / 2)}" y="{_q(-dp / 2)}" z="{_q(-dp / 2)}" />')
    text = _replace_once(text, r"<mainlist>.*?</mainlist>", _mainlist(dp), flags=re.DOTALL)
    definition_dir = output_root / "definitions" / case_id
    definition_dir.mkdir(parents=True, exist_ok=True)
    definition = definition_dir / f"{case_id}_Def.xml"
    definition.write_text(text, encoding="utf-8")
    expected_count = math.prod(spec["counts_xyz"])
    expected_mass = RHO0 * math.prod(FLUID_SIZE)
    metadata = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "mechanism_id": MECHANISM_ID,
        "case_id": case_id,
        "physical_case_id": PHYSICAL_CASE_ID,
        "status": "definition_only_pending_shared_cpu_gencase",
        "qualification_claim": "none",
        "production_claim": "none",
        "q_n_status": "not_assessed",
        "repair_lineage": {
            "kind": "new_numeric_only_cellcenter_mother",
            "parent_failed_reference_cases": [
                "F1_REF_ECC_NOMINAL_COARSE",
                "F1_REF_ECC_NOMINAL_MEDIUM",
                "F1_REF_ECC_NOMINAL_FINE",
            ],
            "failure_addressed": "lattice phase and wall/fluid coincident rows removed one fluid y-layer in the old definitions",
            "old_inputs_immutable": True,
        },
        "source_binding": {
            "template_path": source_info["source_path"],
            "template_sha256": source_info["source_sha256"],
            "physical_fields_reused_byte_semantically": True,
            "controls_reused_byte_semantically": True,
        },
        "physical_binding": {
            "physical_case_id": PHYSICAL_CASE_ID,
            "physical_hash": source_info["physical_hash"],
            "payload": source_info["physical_payload"],
            "continuous_fluid_volume_m3": math.prod(FLUID_SIZE),
            "continuous_fluid_mass_kg": expected_mass,
            "mass_normalization": "forbidden",
            "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
            "boundary_method": "DBC",
            "normals": "not declared; DBC source has no normals section",
        },
        "numeric_binding": {
            "dp_m": dp,
            "pointmin_m": [-dp / 2.0] * 3,
            "fluid_population": "fillbox modefill=fluid; point=continuous_low+dp/2; size=continuous_extent-dp",
            "fixed_support_layers_vdp": list(BOUNDARY_LAYERS),
            "wall_layer_role": "numeric half-cell support around the unchanged physical faces",
            "physical_hash_excludes": ["dp_m", "pointmin_m", "fillbox point/size", "vdp support layers"],
            "time_max_s": 1.6,
            "time_out_s": 0.001,
        },
        "expected_initial": {
            "counts_xyz": list(spec["counts_xyz"]),
            "fluid_particles_type3": expected_count,
            "fluid_mass_kg": expected_mass,
            "fluid_center_low_m": [FLUID_LOW[i] + dp / 2.0 for i in range(3)],
            "fluid_center_high_m": [FLUID_LOW[i] + FLUID_SIZE[i] - dp / 2.0 for i in range(3)],
            "no_initial_void_overlap": True,
            "no_initial_particle_deletion": True,
        },
        "finite_faces": {
            "outer": ["x=0", "x=1.6", "y=0", "y=0.67", "z=0"],
            "obstacle": ["x=0.9", "x=1.02", "y=0.24", "y=0.36", "z=0.45"],
            "coverage_method": "finite interior sampling at spacing <= dp against native Bound.vtk points",
        },
        "definition_path": str(definition.resolve()),
        "definition_sha256": sha256(definition),
    }
    metadata_path = definition_dir / f"{case_id}.metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"case_id": case_id, "resolution": resolution, "dp_m": dp, "counts_xyz": list(spec["counts_xyz"]), "definition": str(definition.resolve()), "metadata": str(metadata_path.resolve()), "definition_sha256": metadata["definition_sha256"], "metadata_sha256": sha256(metadata_path), "expected_fluid_particles": expected_count, "expected_fluid_mass_kg": expected_mass}


def design(output_root: Path, template: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    source_info = inspect_source(template.resolve())
    cases = [materialize_case(template.resolve(), output_root, spec, source_info) for spec in RESOLUTIONS]
    manifest = {
        "schema": "ds02.f1.eccentric-cellcenter-manifest.v1",
        "family_id": FAMILY_ID,
        "mechanism_id": MECHANISM_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "claim_boundary": "CPU GenCase/PartVTK initial evidence only; no solver, Q-N, or production claim",
        "source": source_info,
        "continuous_geometry": {
            "tank_low_m": list(TANK_LOW), "tank_size_m": list(TANK_SIZE),
            "fluid_low_m": list(FLUID_LOW), "fluid_size_m": list(FLUID_SIZE),
            "obstacle_low_m": list(OBSTACLE_LOW), "obstacle_size_m": list(OBSTACLE_SIZE),
            "continuous_fluid_mass_kg": RHO0 * math.prod(FLUID_SIZE),
        },
        "resolutions": cases,
        "frozen_qualification_window": {"time_max_s": 1.6, "time_out_s": 0.001, "macro_budget_fraction": 0.05, "event_budget_fraction_of_characteristic_time": 0.02},
    }
    manifest_path = output_root / "eccentric-cellcenter-manifest.json"
    manifest["manifest_path"] = str(manifest_path.resolve())
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest["manifest_sha256"] = sha256(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def _read_binary_vtk_points(path: Path) -> np.ndarray:
    raw = path.read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\r?\n", raw)
    if match is None:
        raise ValueError(f"binary VTK POINTS header missing: {path}")
    count = int(match.group(1))
    expected = count * 3 * 4
    if len(raw) < match.end() + expected:
        raise ValueError(f"truncated VTK points: {path}")
    return np.frombuffer(raw, dtype=">f4", count=count * 3, offset=match.end()).reshape(count, 3).astype(np.float64)


def _samples(low: Iterable[float], high: Iterable[float], dp: float) -> np.ndarray:
    rows = []
    for lo, hi in zip(low, high):
        rows.append(np.linspace(float(lo), float(hi), int(math.ceil((float(hi) - float(lo)) / dp)) + 1))
    a, b = np.meshgrid(rows[0], rows[1], indexing="ij")
    return np.column_stack((a.ravel(), b.ravel()))


def _face(points: np.ndarray, *, axis: int, plane: float, low: Iterable[float], high: Iterable[float], dp: float) -> dict[str, Any]:
    tangents = [index for index in range(3) if index != axis]
    near = points[np.abs(points[:, axis] - plane) <= dp / 2.0 + 2e-6]
    query = np.full((_samples(low, high, dp).shape[0], 3), float(plane))
    sampled = _samples(low, high, dp)
    query[:, tangents[0]], query[:, tangents[1]] = sampled[:, 0], sampled[:, 1]
    if len(near):
        distances = cKDTree(near).query(query, workers=1)[0]
    else:
        distances = np.full(len(query), np.inf)
    worst = int(np.argmax(distances)) if len(distances) else 0
    radius = math.sqrt(3.0) * dp / 2.0 + 2e-6
    return {
        "axis": axis, "plane_m": plane, "tangential_low_m": list(low), "tangential_high_m": list(high),
        "native_near_plane_points": int(len(near)), "surface_samples": int(len(query)),
        "maximum_distance_m": float(distances[worst]) if len(distances) else None,
        "acceptance_distance_m": radius, "uncovered_samples": int(np.count_nonzero(distances > radius)),
        "worst_sample_m": query[worst].tolist() if len(query) else None,
        "covered": bool(len(query) and np.all(distances <= radius)),
    }


def finite_face_report(points: np.ndarray, dp: float) -> dict[str, Any]:
    outer_specs = (
        ("x_low", 0, 0.0, (0.0, 0.0), (0.67, 0.4)),
        ("x_high", 0, 1.6, (0.0, 0.0), (0.67, 0.4)),
        ("y_low", 1, 0.0, (0.0, 0.0), (1.6, 0.4)),
        ("y_high", 1, 0.67, (0.0, 0.0), (1.6, 0.4)),
        ("z_low", 2, 0.0, (0.0, 0.0), (1.6, 0.67)),
    )
    obstacle_specs = (
        ("x_low", 0, 0.9, (0.24, 0.0), (0.36, 0.45)),
        ("x_high", 0, 1.02, (0.24, 0.0), (0.36, 0.45)),
        ("y_low", 1, 0.24, (0.9, 0.0), (1.02, 0.45)),
        ("y_high", 1, 0.36, (0.9, 0.0), (1.02, 0.45)),
        ("z_high", 2, 0.45, (0.9, 0.24), (1.02, 0.36)),
    )
    outer = {name: _face(points, axis=axis, plane=plane, low=low, high=high, dp=dp) for name, axis, plane, low, high in outer_specs}
    obstacle = {name: _face(points, axis=axis, plane=plane, low=low, high=high, dp=dp) for name, axis, plane, low, high in obstacle_specs}
    return {"outer_faces": outer, "obstacle_faces": obstacle, "all_outer_five_covered": all(row["covered"] for row in outer.values()), "all_obstacle_five_covered": all(row["covered"] for row in obstacle.values())}


def _summary_number(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return int(match.group(1).replace(",", "")) if match else None


def audit_case(case: dict[str, Any], case_root: Path) -> dict[str, Any]:
    definition = Path(case["definition"])
    metadata = json.loads(Path(case["metadata"]).read_text(encoding="utf-8"))
    prefix = case_root / case["case_id"]
    out_path = prefix.with_suffix(".out")
    fluid_vtk = prefix.parent / f"{prefix.name}_Fluid.vtk"
    bound_vtk = prefix.parent / f"{prefix.name}_Bound.vtk"
    partvtk_vtk = case_root / "PartVTK_initial.vtk"
    out_text = out_path.read_text(encoding="utf-8", errors="replace")
    fluid = _read_binary_vtk_points(fluid_vtk)
    bound = _read_binary_vtk_points(bound_vtk)
    partvtk = _read_binary_vtk_points(partvtk_vtk)
    dp = float(case["dp_m"])
    expected = int(case["expected_fluid_particles"])
    expected_low = np.asarray(metadata["expected_initial"]["fluid_center_low_m"], dtype=float)
    expected_high = np.asarray(metadata["expected_initial"]["fluid_center_high_m"], dtype=float)
    tol = max(3e-6, dp * 2e-5)
    unique_count = int(np.unique(fluid, axis=0).shape[0])
    inside = bool(np.all(fluid >= expected_low - tol) and np.all(fluid <= expected_high + tol))
    void_low = np.asarray(OBSTACLE_LOW) - tol
    void_high = np.asarray(OBSTACLE_LOW) + np.asarray(OBSTACLE_SIZE) + tol
    overlap = np.all((fluid >= void_low) & (fluid <= void_high), axis=1)
    actual_mass = len(fluid) * RHO0 * dp ** 3
    coverage = finite_face_report(bound, dp)
    generated_xml = prefix.with_suffix(".xml")
    xml_root = ET.parse(generated_xml).getroot()
    normals_declared = xml_root.find("./casedef/normals") is not None
    report = {
        "schema": "ds02.f1.eccentric-cellcenter-native-audit.v1",
        "case_id": case["case_id"], "resolution": case["resolution"], "dp_m": dp,
        "definition_sha256": sha256(definition),
        "generated_outputs": {"prefix": str(prefix), "out": str(out_path), "fluid_vtk": str(fluid_vtk), "bound_vtk": str(bound_vtk), "official_partvtk_initial_vtk": str(partvtk_vtk)},
        "actual": {
            "dimension": 3,
            "fluid_vtk_points": int(len(fluid)),
            "bound_vtk_points": int(len(bound)),
            "official_partvtk_initial_points": int(len(partvtk)),
            "gencase_fluid_summary": _summary_number(out_text, r"Fluid\.\.\.\.:\s*([0-9,]+)"),
            "gencase_total_summary": _summary_number(out_text, r"Total particles:\s*([0-9,]+)"),
            "fluid_bounds_m": {"low": fluid.min(axis=0).tolist(), "high": fluid.max(axis=0).tolist()},
            "unique_fluid_points": unique_count,
            "native_mass_kg": actual_mass,
            "native_mass_error_kg": actual_mass - float(metadata["physical_binding"]["continuous_fluid_mass_kg"]),
            "initial_void_overlap_particles": int(np.count_nonzero(overlap)),
            "centres_inside_declared_fluid_envelope": inside,
            "normals_declared": normals_declared,
        },
        "coverage": coverage,
        "expected": {
            "fluid_particles": expected,
            "mass_kg": float(metadata["physical_binding"]["continuous_fluid_mass_kg"]),
            "center_count_xyz": metadata["expected_initial"]["counts_xyz"],
            "center_low_m": expected_low.tolist(), "center_high_m": expected_high.tolist(),
        },
        "physical_hash": metadata["physical_binding"]["physical_hash"],
        "physical_geometry_control_unchanged_claim": "source-semantic hash only; actual GenCase evidence is this report",
        "gate": {
            "exact_fluid_count": len(fluid) == expected,
            "exact_native_mass": math.isclose(actual_mass, float(metadata["physical_binding"]["continuous_fluid_mass_kg"]), rel_tol=0.0, abs_tol=2e-9),
            "unique_initial_fluid_positions": unique_count == len(fluid),
            "no_initial_void_overlap": int(np.count_nonzero(overlap)) == 0,
            "all_centres_inside_envelope": inside,
            "all_outer_five_faces_covered": coverage["all_outer_five_covered"],
            "all_obstacle_five_faces_covered": coverage["all_obstacle_five_covered"],
            "three_dimensional": len(fluid) > 0 and len(np.unique(fluid[:, 2])) >= 3,
            "dbc_without_normals": not normals_declared,
        },
        "q_n_status": "not_assessed",
    }
    report["gate"]["all_preflight_gates"] = all(report["gate"].values())
    return report


def _usage() -> dict[str, Any]:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    def pack(row: resource.struct_rusage) -> dict[str, Any]:
        return {"user_seconds": row.ru_utime, "system_seconds": row.ru_stime, "max_rss_kib": row.ru_maxrss, "minor_faults": row.ru_minflt, "major_faults": row.ru_majflt, "in_block": row.ru_inblock, "out_block": row.ru_oublock, "voluntary_context_switches": row.ru_nvcsw, "involuntary_context_switches": row.ru_nivcsw}
    return {"self": pack(self_usage), "children": pack(child_usage)}


def run_gencase(manifest_path: Path, attempt_root: Path, output_path: Path, gencase: Path, partvtk: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    attempt_root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    usage_before = _usage()
    cases: list[dict[str, Any]] = []
    for case in manifest["resolutions"]:
        case_root = attempt_root / case["case_id"]
        case_root.mkdir(parents=True, exist_ok=True)
        prefix = case_root / case["case_id"]
        gencase_command = [str(gencase), str(Path(case["definition"]).with_suffix("")), str(prefix), "-save:all", "-threads:4"]
        gencase_log = case_root / "GenCase.stdout.log"
        with gencase_log.open("wb") as log:
            result = subprocess.run(gencase_command, cwd=gencase.parent, stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"GenCase failed for {case['case_id']} with {result.returncode}; see {gencase_log}")
        partvtk_path = case_root / "PartVTK_initial.vtk"
        partvtk_command = [str(partvtk), "-filedata", f"{prefix}.bi4", "-filexml", f"{prefix}.xml", "-savevtk", str(partvtk_path), "-threads:4"]
        partvtk_log = case_root / "PartVTK.stdout.log"
        with partvtk_log.open("wb") as log:
            result = subprocess.run(partvtk_command, cwd=partvtk.parent, stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"PartVTK failed for {case['case_id']} with {result.returncode}; see {partvtk_log}")
        cases.append(audit_case(case, case_root))
    report = {
        "schema": "ds02.f1.eccentric-cellcenter-preflight.v1",
        "family_id": FAMILY_ID, "mechanism_id": MECHANISM_ID, "physical_case_id": PHYSICAL_CASE_ID,
        "manifest": str(manifest_path.resolve()), "manifest_sha256": sha256(manifest_path),
        "attempt_root": str(attempt_root.resolve()), "gencase": str(gencase.resolve()), "partvtk": str(partvtk.resolve()),
        "cases": cases,
        "physical_hashes": sorted({case["physical_hash"] for case in cases}),
        "all_physical_hashes_equal": len({case["physical_hash"] for case in cases}) == 1,
        "all_case_preflight_gates": all(case["gate"]["all_preflight_gates"] for case in cases),
        "q_n_status": "not_assessed",
        "qualification_claim": "none",
        "production_claim": "none",
        "resource_usage": {"before": usage_before, "after": _usage()},
        "elapsed_seconds": time.time() - started,
        "child_processes_include_official_gencase_and_partvtk": True,
        "source_bytes_mutated": False,
        "frozen_qualification_registration": {"time_max_s": 1.6, "time_out_s": 0.001, "macro_budget_fraction": 0.05, "event_budget_fraction_of_characteristic_time": 0.02},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_design = sub.add_parser("design")
    p_design.add_argument("--output-root", type=Path, default=_SCOPE)
    p_design.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    p_run = sub.add_parser("run-gencase")
    p_run.add_argument("--manifest", type=Path, required=True)
    p_run.add_argument("--attempt-root", type=Path, required=True)
    p_run.add_argument("--output", type=Path, required=True)
    p_run.add_argument("--gencase", type=Path, required=True)
    p_run.add_argument("--partvtk", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "design":
        result = design(args.output_root, args.template)
    else:
        result = run_gencase(args.manifest, args.attempt_root, args.output, args.gencase, args.partvtk)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
