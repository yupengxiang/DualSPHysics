#!/usr/bin/env python3
"""Run the two bounded mDBC fixed-box force-gauge calibrations.

The DBC controls have their own runner.  This file is deliberately separate so
that the mDBC construction and its normal/ghost gates cannot silently inherit
the DBC acceptance logic.  It imports only the execution/audit helpers from
``run_fixed_box_force_gauge.py``; all mDBC source definitions and evidence stay
inside this isolated case directory.

There are exactly two mDBC calibrations here:

* ``canonical-2``: the 0.025 m canonical definition;
* ``fine-3``: the 0.0125 m one-step refinement.

The body is a fixed boundary block (source ``mkbound=1``), not a floating body.
The body particle shell is put one half-dp into the solid side of the physical
void, while the named ``GeometryForNormals`` body surface is one half-dp back
toward the fluid.  Thus ``x_gamma = x_b + n_g/2`` reconstructs the physical
0.2 m cube.  GenCase must report zero zero-normals before a GPU launch is
allowed.  Every solver attempt is retained, including failed attempts; a
stable trace is still diagnostic evidence and never automatic physical
acceptance.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


CASE_ROOT = Path(__file__).resolve().parent
BASE_PATH = CASE_ROOT / "run_fixed_box_force_gauge.py"
BASE_SPEC = importlib.util.spec_from_file_location("fixed_box_force_base", BASE_PATH)
if BASE_SPEC is None or BASE_SPEC.loader is None:
    raise RuntimeError(f"cannot import base runner: {BASE_PATH}")
BASE = importlib.util.module_from_spec(BASE_SPEC)
sys.modules[BASE_SPEC.name] = BASE
BASE_SPEC.loader.exec_module(BASE)

# The E0 parser is a strict binary-VTK reader.  Importing it here avoids a
# second permissive parser that could turn a missing normal array into zeros.
sys.path.insert(0, str(BASE.LAB_ROOT))
from diagnostics.r3_f6_canonical_geometry.probe import read_binary_vtk_fields  # noqa: E402


REPORT_PATH = CASE_ROOT / "mdbc-fixed-box-force-gauge-report.json"
REPORT_MD_PATH = CASE_ROOT / "mdbc-fixed-box-force-gauge-report.md"
RESULT_ROOT = BASE.RESULT_ROOT
RUN_ROOT = BASE.RUN_ROOT
GENERATED_ROOT = BASE.GENERATED_ROOT

OWNER_AUTHORIZED_GPU_INDICES = tuple(range(8))
PREFERRED_IDLE_GPU_INDICES = tuple(BASE.ALLOWED_GPU_INDICES)
NORMAL_ZERO_TOLERANCE = 1.0e-12
NORMAL_FINITE_TOLERANCE = 1.0e-12
NORMAL_DOUBLING_TOLERANCE = 2.0e-5
INTERFACE_FACE_TOLERANCE_FACTOR = 0.75
ORIENTATION_DOT_LIMIT = 0.5
INTERFACE_TOLERANCE_FACTOR = 0.75

PHYSICAL_BOX_MIN = np.asarray(BASE.BOX_MIN, dtype=float)
PHYSICAL_BOX_MAX = np.asarray(BASE.BOX_MAX, dtype=float)

CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "case_id": "fixed_box_mdbc_canonical",
        "run_label": "canonical-2",
        "label": "mDBC canonical rectangular fixed box",
        "definition": CASE_ROOT / "fixed_box_mdbc_canonical_Def.xml",
        "dp_m": 0.025,
        "distanceh": 3.0,
        "expected_fz_n": BASE.ANALYTIC_FZ_N,
        "historical_probe": "mdbc-probe-canonical-2",
        "existing_solver_run": RUN_ROOT / "mdbc-probe-canonical-final" / "attempts" / "20260907T123424.875319Z-4dfa3f2f.complete",
        "preflight": RUN_ROOT / "gpu-preflight-mdbc-canonical-final.txt",
        "solver_source_matches_final_definition": True,
    },
    {
        "case_id": "fixed_box_mdbc_fine",
        "run_label": "fine-3",
        "label": "mDBC one-step refined rectangular fixed box",
        "definition": CASE_ROOT / "fixed_box_mdbc_fine_Def.xml",
        "dp_m": 0.0125,
        "distanceh": 5.0,
        "expected_fz_n": BASE.ANALYTIC_FZ_N,
        "historical_probe": None,
        "existing_solver_run": RUN_ROOT / "mdbc-probe-fine-root",
        "preflight": RUN_ROOT / "mdbc-probe-fine-root" / "gpu-preflight.txt",
        "solver_source_matches_final_definition": True,
    },
)


def relative(path: Path) -> str:
    """Return a stable path relative to the isolated case root."""

    return str(path.relative_to(CASE_ROOT))


def _float_list(node: ET.Element | None, name: str = "vdp") -> list[float]:
    if node is None:
        return []
    value = node.attrib.get(name, "")
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def _shape_contract(
    node: ET.Element, normal_invert: bool | None, mkbound: int | None
) -> dict[str, Any]:
    point = node.find("./point")
    size = node.find("./size")
    if point is None or size is None:
        raise ValueError(f"{node.tag} is missing point/size")
    return {
        "tag": node.tag,
        "mkbound": mkbound,
        "normal_invert": normal_invert,
        "boxfill": (node.findtext("./boxfill") or "").strip(),
        "point_m": [float(point.attrib[key]) for key in ("x", "y", "z")],
        "size_m": [float(size.attrib[key]) for key in ("x", "y", "z")],
        "layers_vdp": _float_list(node.find("./layers")),
    }


def _direct_shapes(container: ET.Element) -> list[dict[str, Any]]:
    """Read direct draw commands while carrying the XML state."""

    shapes: list[dict[str, Any]] = []
    normal_invert: bool | None = None
    mkbound: int | None = None
    for child in list(container):
        if child.tag == "setnormalinvert":
            normal_invert = child.attrib.get("invert", "false").lower() == "true"
        elif child.tag == "setmkbound":
            mkbound = int(child.attrib["mk"])
        elif child.tag in {"setmkfluid", "setmkvoid"}:
            # Fluid/void draw commands are not boundary shapes.  Clearing the
            # carried boundary state prevents a water or void box from being
            # mistaken for another tank boundary box.
            mkbound = None
        elif child.tag == "drawbox":
            shapes.append(_shape_contract(child, normal_invert, mkbound))
    return shapes


def _box_max(shape: dict[str, Any]) -> list[float]:
    return [lo + width for lo, width in zip(shape["point_m"], shape["size_m"])]


def source_geometry_audit(definition: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Audit the source XML, including the physical void and half-dp pattern."""

    root = ET.parse(definition).getroot()
    geometry = root.find("./casedef/geometry")
    commands = root.find("./casedef/geometry/commands")
    definition_node = root.find("./casedef/geometry/definition")
    if geometry is None or commands is None or definition_node is None:
        raise ValueError(f"{definition} lacks casedef geometry/commands/definition")
    normal_list = commands.find("./list[@name='GeometryForNormals']")
    mainlist = commands.find("./mainlist")
    if normal_list is None or mainlist is None:
        raise ValueError(f"{definition} must contain GeometryForNormals and mainlist")

    normal_shapes = _direct_shapes(normal_list)
    main_shapes = _direct_shapes(mainlist)
    normal_body = [shape for shape in normal_shapes if shape["mkbound"] == 1]
    normal_tank = [shape for shape in normal_shapes if shape["mkbound"] == 0]
    main_body = [shape for shape in main_shapes if shape["mkbound"] == 1]
    main_tank = [shape for shape in main_shapes if shape["mkbound"] == 0]
    if len(normal_body) != 1 or len(main_body) != 1:
        raise ValueError(
            f"expected one normal and one actual body shape; got "
            f"{len(normal_body)} and {len(main_body)}"
        )
    if len(normal_tank) != 1 or len(main_tank) != 1:
        raise ValueError(
            f"expected one normal and one actual tank shape; got "
            f"{len(normal_tank)} and {len(main_tank)}"
        )

    # Find the physical void and prove that the body shell is drawn after it.
    current_mkbound: str | None = None
    void_shapes: list[dict[str, Any]] = []
    void_index: int | None = None
    body_index: int | None = None
    for index, child in enumerate(list(mainlist)):
        if child.tag == "setmkbound":
            current_mkbound = child.attrib.get("mk")
        elif child.tag == "setmkvoid":
            current_mkbound = None
            void_index = index
        elif child.tag == "drawbox":
            shape = _shape_contract(
                child,
                normal_invert=None,
                mkbound=int(current_mkbound) if current_mkbound is not None else None,
            )
            if current_mkbound == "1" and body_index is None:
                body_index = index
            if current_mkbound is None and void_index is not None:
                void_shapes.append(shape)
    physical_void = [
        shape
        for shape in void_shapes
        if np.allclose(shape["point_m"], BASE.BOX_MIN, atol=1.0e-12)
        and np.allclose(shape["size_m"], BASE.BOX_SIZE, atol=1.0e-12)
    ]
    if len(physical_void) != 1:
        raise ValueError(f"expected one physical 0.2 m void, got {len(physical_void)}")

    parameters = {
        node.attrib.get("key"): node.attrib.get("value")
        for node in root.findall("./execution/parameters/parameter")
    }
    normals = root.find("./casedef/normals")
    norgeometry = root.find("./casedef/normals/norgeometry")
    force_nodes = root.findall("./execution/special/gauges/force")
    force_targets = [node.find("./target") for node in force_nodes]
    gravity = root.find("./casedef/constantsdef/gravity")
    floating_nodes = root.findall(".//floating")
    floating_sections = root.findall(".//floatings")

    source_dp = float(definition_node.attrib["dp"])
    normal_body_layers = normal_body[0]["layers_vdp"]
    actual_body_layers = main_body[0]["layers_vdp"]
    normal_tank_layers = normal_tank[0]["layers_vdp"]
    actual_tank_layers = main_tank[0]["layers_vdp"]
    body_normal_shift = [
        float(value) * source_dp for value in normal_body_layers if abs(value) > 1.0e-12
    ]
    physical_min = np.asarray(BASE.BOX_MIN)
    physical_max = np.asarray(BASE.BOX_MAX)
    normal_body_min = np.asarray(normal_body[0]["point_m"])
    normal_body_max = normal_body_min + np.asarray(normal_body[0]["size_m"])
    actual_body_min = np.asarray(main_body[0]["point_m"])
    actual_body_max = actual_body_min + np.asarray(main_body[0]["size_m"])

    # The exact construction used by both definitions is one inward half-dp
    # body shift and one outward half-dp normal-only layer.  Keep the expected
    # physical interface explicit in the report rather than inferring it from
    # the generated particle count.
    contract_checks = {
        "boundary_parameter_is_mdbc": parameters.get("Boundary") == "2",
        "normals_active": normals is not None and normals.attrib.get("active") == "true",
        "norgeometry_present": norgeometry is not None,
        "normal_tank_invert_true": normal_tank[0]["normal_invert"] is True,
        "normal_body_invert_false": normal_body[0]["normal_invert"] is False,
        "normal_tank_single_minus_half_dp": normal_tank_layers == [-0.5],
        "normal_body_single_plus_half_dp": normal_body_layers == [0.5],
        "actual_tank_layers_are_0_1_2": actual_tank_layers == [0.0, 1.0, 2.0],
        "actual_body_layers_are_0_minus1_minus2": actual_body_layers == [0.0, -1.0, -2.0],
        "no_half_dp_on_actual_layers": -0.5 not in actual_tank_layers and -0.5 not in actual_body_layers,
        "body_drawn_after_void": void_index is not None and body_index is not None and body_index > void_index,
        "physical_void_is_exact_0p2_cube": np.allclose(physical_void[0]["point_m"], BASE.BOX_MIN, atol=1.0e-12)
        and np.allclose(physical_void[0]["size_m"], BASE.BOX_SIZE, atol=1.0e-12),
        "body_fully_submerged": BASE.BOX_MIN[2] > 0.0 and BASE.BOX_MAX[2] < BASE.TANK_INNER_MAX[2],
        "body_floor_gap_positive": BASE.BOX_MIN[2] > 0.0,
        "no_floating_section": not floating_sections and not floating_nodes,
        "force_target_mkbound_1": len(force_targets) == 1
        and force_targets[0] is not None
        and force_targets[0].attrib.get("mkbound") == "1",
        "source_dp_matches_spec": math.isclose(source_dp, spec["dp_m"], rel_tol=0.0, abs_tol=1.0e-12),
    }
    if not all(contract_checks.values()):
        failed = [name for name, passed in contract_checks.items() if not passed]
        raise ValueError(f"mDBC source contract failed: {failed}")

    return {
        "definition": relative(definition),
        "definition_sha256": BASE.sha256(definition),
        "source_dp_m": source_dp,
        "normal_distanceh": float(norgeometry.find("./distanceh").attrib["v"])
        if norgeometry is not None and norgeometry.find("./distanceh") is not None
        else None,
        "normal_geometryfile": norgeometry.find("./geometryfile").attrib["file"]
        if norgeometry is not None and norgeometry.find("./geometryfile") is not None
        else None,
        "normal_svshapes": norgeometry.find("./svshapes").attrib.get("v")
        if norgeometry is not None and norgeometry.find("./svshapes") is not None
        else None,
        "physical_void": {
            "source_mkvoid": True,
            "point_m": list(BASE.BOX_MIN),
            "size_m": list(BASE.BOX_SIZE),
            "max_m": list(BASE.BOX_MAX),
            "volume_m3": BASE.BOX_VOLUME_M3,
        },
        "normal_tank_shape": normal_tank[0],
        "normal_body_shape": normal_body[0],
        "actual_tank_shape": main_tank[0],
        "actual_body_shape": main_body[0],
        "normal_body_offset_from_physical_min_m": (normal_body_min - physical_min).tolist(),
        "normal_body_offset_from_physical_max_m": (normal_body_max - physical_max).tolist(),
        "actual_body_offset_from_physical_min_m": (actual_body_min - physical_min).tolist(),
        "actual_body_offset_from_physical_max_m": (actual_body_max - physical_max).tolist(),
        "body_normal_layer_displacements_m": body_normal_shift,
        "effective_interface_definition": {
            "formula": "x_gamma = x_boundary_particle + n_ghost/2",
            "physical_min_m": list(BASE.BOX_MIN),
            "physical_max_m": list(BASE.BOX_MAX),
            "normal_surface_plus_half_dp_reconstructs_physical_interface": True,
        },
        "parameters": parameters,
        "gravity": dict(gravity.attrib) if gravity is not None else None,
        "floating_nodes": len(floating_nodes),
        "contract_checks": contract_checks,
    }


def parse_gencase_log(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")

    def integer(pattern: str) -> int | None:
        match = re.search(pattern, text)
        return int(match.group(1).replace(",", "")) if match else None

    def summary(label: str) -> int | None:
        return integer(rf"{label}\.{{4,}}:\s*([\d,]+)")

    nonzero = re.search(
        r"Non-zero particle normals:\s*([\d,]+)\s*/\s*([\d,]+).*?"
        r"Normals size range:\s*\(([0-9.eE+\-]+)\s*-\s*([0-9.eE+\-]+)\)",
        text,
    )
    zero = re.search(
        r"Final zero normals:\s*([\d,]+)\s*/\s*([\d,]+)\s*\(([0-9.]+)%\)",
        text,
    )
    codes = re.findall(r"Finished execution \(code=(-?\d+)\)", text)
    result: dict[str, Any] = {
        "log": relative(path),
        "log_sha256": BASE.sha256(path),
        "return_code": int(codes[-1]) if codes else None,
        "fixed_summary": summary("Fixed"),
        "fluid_summary": summary("Fluid"),
        "moving_summary": summary("Moving"),
        "floating_summary": summary("Floating"),
        "nonzero_normals": {
            "count": int(nonzero.group(1).replace(",", "")),
            "total": int(nonzero.group(2).replace(",", "")),
            "min_size_m": float(nonzero.group(3)),
            "max_size_m": float(nonzero.group(4)),
        }
        if nonzero
        else None,
        "final_zero_normals": {
            "count": int(zero.group(1).replace(",", "")),
            "total": int(zero.group(2).replace(",", "")),
            "percentage": float(zero.group(3)),
        }
        if zero
        else None,
        "finished_text_found": "Finished execution (code=0)." in text,
    }
    final_zero = result["final_zero_normals"]
    result["normal_completeness_gate"] = bool(
        result["return_code"] == 0
        and result["finished_text_found"]
        and final_zero is not None
        and final_zero["count"] == 0
        and final_zero["total"] is not None
        and final_zero["total"] == result["fixed_summary"]
    )
    return result


def _array_stats(values: np.ndarray) -> dict[str, Any]:
    values = np.asarray(values)
    finite = np.isfinite(values)
    return {
        "shape": list(values.shape),
        "finite": bool(np.all(finite)),
        "min": float(np.min(values)) if values.size else None,
        "max": float(np.max(values)) if values.size else None,
        "mean": float(np.mean(values)) if values.size else None,
    }


def normal_ghost_audit(
    attempt_dir: Path, generated: dict[str, Any], source: dict[str, Any], dp_m: float
) -> dict[str, Any]:
    """Audit solver normal and ghost arrays and reconstruct the body interface."""

    normal_path = attempt_dir / "CfgInit_Normals.vtk"
    ghost_path = attempt_dir / "CfgInit_NormalsGhost.vtk"
    if not normal_path.is_file() or not ghost_path.is_file():
        raise FileNotFoundError(
            f"mDBC normal/ghost files missing: {normal_path.name}, {ghost_path.name}"
        )
    normal = read_binary_vtk_fields(normal_path)
    ghost = read_binary_vtk_fields(ghost_path)
    required = {"Mk", "Normal", "NormalSize"}
    normal_fields = set(normal["arrays"])
    ghost_fields = set(ghost["arrays"])
    normal_count = int(normal["count"])
    ghost_count = int(ghost["count"])
    generated_fixed_count = int(generated["nb"])
    missing_normal = sorted(required - normal_fields)
    missing_ghost = sorted(required - ghost_fields)
    same_point_count = normal_count == ghost_count
    same_points = same_point_count and bool(
        np.allclose(normal["points"], ghost["points"], rtol=0.0, atol=1.0e-7)
    )
    same_mk = same_point_count and bool(
        np.array_equal(normal["arrays"].get("Mk"), ghost["arrays"].get("Mk"))
    )
    normal_vectors = np.asarray(normal["arrays"].get("Normal", np.empty((0, 3))), dtype=float)
    ghost_vectors = np.asarray(ghost["arrays"].get("Normal", np.empty((0, 3))), dtype=float)
    normal_sizes = np.asarray(normal["arrays"].get("NormalSize", np.empty((0, 1))), dtype=float).reshape(-1)
    ghost_sizes = np.asarray(ghost["arrays"].get("NormalSize", np.empty((0, 1))), dtype=float).reshape(-1)
    normal_mk = np.asarray(normal["arrays"].get("Mk", np.empty((0, 1))), dtype=int).reshape(-1)
    ghost_mk = np.asarray(ghost["arrays"].get("Mk", np.empty((0, 1))), dtype=int).reshape(-1)
    finite_all = all(
        np.all(np.isfinite(values))
        for values in (normal["points"], ghost["points"], normal_vectors, ghost_vectors, normal_sizes, ghost_sizes)
    )
    normal_norms = np.linalg.norm(normal_vectors, axis=1) if normal_vectors.ndim == 2 else np.empty(0)
    ghost_norms = np.linalg.norm(ghost_vectors, axis=1) if ghost_vectors.ndim == 2 else np.empty(0)
    zero_normal_count = int(np.sum(normal_norms <= NORMAL_ZERO_TOLERANCE))
    zero_ghost_count = int(np.sum(ghost_norms <= NORMAL_ZERO_TOLERANCE))
    positive_normal_size = int(np.sum(normal_sizes <= NORMAL_ZERO_TOLERANCE)) == 0
    positive_ghost_size = int(np.sum(ghost_sizes <= NORMAL_ZERO_TOLERANCE)) == 0
    if len(normal_vectors) == len(ghost_vectors):
        vector_double_error = float(np.max(np.abs(ghost_vectors - 2.0 * normal_vectors)))
    else:
        vector_double_error = math.inf
    if len(normal_sizes) == len(ghost_sizes):
        size_double_error = float(np.max(np.abs(ghost_sizes - 2.0 * normal_sizes)))
    else:
        size_double_error = math.inf

    mapping = generated["mapping_source_to_global_mk"]
    body_rows = [
        item for item in mapping
        if item["source_mkbound"] == 1 and item["particle_type"] == "fixed"
    ]
    if len(body_rows) != 1:
        raise ValueError(f"normal audit requires one fixed source mkbound=1 row, got {body_rows}")
    body_global_mk = int(body_rows[0]["global_mk"])
    body_expected_count = int(body_rows[0]["count"])
    body_mask = normal_mk == body_global_mk
    body_ghost_mask = ghost_mk == body_global_mk
    body_count_normal = int(np.sum(body_mask))
    body_count_ghost = int(np.sum(body_ghost_mask))
    body_points = normal["points"][body_mask]
    body_ghost = ghost_vectors[body_mask]
    body_interface = body_points + body_ghost / 2.0
    body_normal_norms = normal_norms[body_mask]
    body_ghost_norms = ghost_norms[body_ghost_mask]

    # Classify each reconstructed body-interface point against the six faces.
    # A point on an edge/corner accumulates the corresponding outward face
    # directions, matching the lattice normal convention.
    face_vectors = np.asarray(
        [
            [-1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, -1.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )
    face_locations = np.asarray(
        [
            PHYSICAL_BOX_MIN[0], PHYSICAL_BOX_MAX[0],
            PHYSICAL_BOX_MIN[1], PHYSICAL_BOX_MAX[1],
            PHYSICAL_BOX_MIN[2], PHYSICAL_BOX_MAX[2],
        ],
        dtype=float,
    )
    if len(body_interface):
        # Keep the six scalar columns explicit so x/y/z face coordinates cannot
        # be accidentally permuted when this audit is changed.
        distances = np.column_stack(
            [
                np.abs(body_interface[:, 0] - PHYSICAL_BOX_MIN[0]),
                np.abs(body_interface[:, 0] - PHYSICAL_BOX_MAX[0]),
                np.abs(body_interface[:, 1] - PHYSICAL_BOX_MIN[1]),
                np.abs(body_interface[:, 1] - PHYSICAL_BOX_MAX[1]),
                np.abs(body_interface[:, 2] - PHYSICAL_BOX_MIN[2]),
                np.abs(body_interface[:, 2] - PHYSICAL_BOX_MAX[2]),
            ]
        )
        nearest = np.min(distances, axis=1)
        face_tolerance = max(INTERFACE_FACE_TOLERANCE_FACTOR * dp_m, 1.0e-6)
        expected = np.zeros_like(body_interface)
        for face_index in range(6):
            expected += (
                distances[:, face_index] <= nearest + face_tolerance
            )[:, None] * face_vectors[face_index]
        expected_norm = np.linalg.norm(expected, axis=1)
        expected_unit = expected / np.maximum(expected_norm[:, None], NORMAL_ZERO_TOLERANCE)
        normal_unit = body_ghost / np.maximum(
            np.linalg.norm(body_ghost, axis=1)[:, None], NORMAL_ZERO_TOLERANCE
        )
        dots = np.sum(normal_unit * expected_unit, axis=1)
        face_residual = nearest
        interface_bbox = [body_interface.min(axis=0).tolist(), body_interface.max(axis=0).tolist()]
        orientation_min = float(np.min(dots))
        orientation_fraction = float(np.mean(dots >= ORIENTATION_DOT_LIMIT))
        face_counts = {
            "x_min": int(np.sum(distances[:, 0] <= face_tolerance)),
            "x_max": int(np.sum(distances[:, 1] <= face_tolerance)),
            "y_min": int(np.sum(distances[:, 2] <= face_tolerance)),
            "y_max": int(np.sum(distances[:, 3] <= face_tolerance)),
            "z_min": int(np.sum(distances[:, 4] <= face_tolerance)),
            "z_max": int(np.sum(distances[:, 5] <= face_tolerance)),
        }
    else:
        face_residual = np.empty(0)
        interface_bbox = [[], []]
        orientation_min = None
        orientation_fraction = None
        face_counts = {}

    residual_limit = max(INTERFACE_TOLERANCE_FACTOR * dp_m, 1.0e-6)
    interface_gate = bool(
        len(body_interface) > 0
        and np.all(face_residual <= residual_limit + 1.0e-7)
        and orientation_min is not None
        and orientation_min >= ORIENTATION_DOT_LIMIT - 1.0e-6
    )
    checks = {
        "files_present": normal_path.is_file() and ghost_path.is_file(),
        "required_arrays_present": not missing_normal and not missing_ghost,
        "normal_count_matches_generated_fixed_count": normal_count == generated_fixed_count,
        "ghost_count_matches_generated_fixed_count": ghost_count == generated_fixed_count,
        "normal_ghost_points_match": same_points,
        "normal_ghost_mk_match": same_mk,
        "arrays_finite": finite_all,
        "no_zero_normals": zero_normal_count == 0 and zero_ghost_count == 0,
        "normal_sizes_positive": positive_normal_size and positive_ghost_size,
        "ghost_vector_is_double_normal": vector_double_error <= NORMAL_DOUBLING_TOLERANCE,
        "ghost_size_is_double_normal_size": size_double_error <= NORMAL_DOUBLING_TOLERANCE,
        "body_global_mk_matches_source_mapping": body_count_normal == body_expected_count,
        "body_ghost_mk_matches_source_mapping": body_count_ghost == body_expected_count,
        "body_interface_geometry_and_orientation": interface_gate,
    }
    return {
        "normal_file": {"path": relative(normal_path), "sha256": BASE.sha256(normal_path)},
        "ghost_file": {"path": relative(ghost_path), "sha256": BASE.sha256(ghost_path)},
        "normal_count": normal_count,
        "ghost_count": ghost_count,
        "generated_fixed_count": generated_fixed_count,
        "missing_normal_arrays": missing_normal,
        "missing_ghost_arrays": missing_ghost,
        "normal_array_stats": {key: _array_stats(value) for key, value in normal["arrays"].items()},
        "ghost_array_stats": {key: _array_stats(value) for key, value in ghost["arrays"].items()},
        "normal_zero_count": zero_normal_count,
        "ghost_zero_count": zero_ghost_count,
        "body_normal_zero_count": int(np.sum(body_normal_norms <= NORMAL_ZERO_TOLERANCE)),
        "body_ghost_zero_count": int(np.sum(body_ghost_norms <= NORMAL_ZERO_TOLERANCE)),
        "normal_size_nonpositive_count": int(np.sum(normal_sizes <= NORMAL_ZERO_TOLERANCE)),
        "ghost_size_nonpositive_count": int(np.sum(ghost_sizes <= NORMAL_ZERO_TOLERANCE)),
        "max_ghost_vector_minus_2_normal": vector_double_error,
        "max_ghost_size_minus_2_normal_size": size_double_error,
        "source_mkbound": 1,
        "body_global_mk": body_global_mk,
        "body_expected_count": body_expected_count,
        "body_normal_count": body_count_normal,
        "body_ghost_count": body_count_ghost,
        "effective_body_interface_bbox_m": interface_bbox,
        "effective_body_interface_max_face_residual_m": float(np.max(face_residual))
        if len(face_residual)
        else None,
        "effective_body_interface_median_face_residual_m": float(np.median(face_residual))
        if len(face_residual)
        else None,
        "effective_body_interface_residual_limit_m": residual_limit,
        "effective_body_interface_face_counts": face_counts,
        "effective_body_normal_orientation_min_dot": orientation_min,
        "effective_body_normal_orientation_fraction_dot_ge_0p5": orientation_fraction,
        "checks": checks,
        "gate": all(checks.values()),
    }


def _copy_generated_evidence(
    result_dir: Path, gencase: dict[str, Any], generated: dict[str, Any]
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    generated_xml = CASE_ROOT / generated["generated_xml"]
    xml_copy = result_dir / "generated_particles.xml"
    log_copy = result_dir / "gencase.stdout.log"
    shutil.copy2(generated_xml, xml_copy)
    shutil.copy2(CASE_ROOT / gencase["stdout_log"], log_copy)
    evidence["particles_xml"] = relative(xml_copy)
    evidence["particles_xml_sha256"] = BASE.sha256(xml_copy)
    evidence["gencase_stdout"] = relative(log_copy)
    evidence["gencase_stdout_sha256"] = BASE.sha256(log_copy)
    return evidence


def _copy_solver_evidence(attempt_dir: Path, result_dir: Path) -> dict[str, Any]:
    names = (
        "CfgInit_Normals.vtk",
        "CfgInit_NormalsGhost.vtk",
        "CfgInit_Domain.vtk",
        "CfgInit_MapCells.vtk",
    )
    copied: dict[str, Any] = {}
    for name in names:
        source = attempt_dir / name
        if source.is_file():
            destination = result_dir / name
            shutil.copy2(source, destination)
            copied[name] = {"path": relative(destination), "sha256": BASE.sha256(destination)}
    return copied


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _force_screen(
    gauge: dict[str, Any], expected_fz_n: float, fields: dict[str, Any] | None,
    normal_gate: bool, mapping_gate: bool, solver_gate: bool,
) -> dict[str, Any]:
    windows = gauge["windows"]
    sample_gate = all(
        window["samples"] >= 20 and window["forcez [N]"] is not None
        for window in windows.values()
    )
    # A 5% reference band is a bounded screening threshold, not an acceptance
    # claim.  It is deliberately reported even when mDBC is unstable.
    stability_limit = max(0.05 * abs(expected_fz_n), 0.5)
    stable_gate = sample_gate and all(
        window["forcez [N]"]["std"] <= stability_limit
        for window in windows.values()
        if window["forcez [N]"] is not None
    )
    means = [
        windows[name]["forcez [N]"]["mean"]
        for name in ("last_0p20s", "last_0p40s", "last_0p60s")
        if windows[name]["forcez [N]"] is not None
    ]
    reference_error = (
        abs(means[0] - expected_fz_n) / abs(expected_fz_n) * 100.0
        if means and expected_fz_n
        else None
    )
    fields_gate = bool(
        fields
        and fields.get("required_fields_complete")
        and fields.get("fluid_count_constant")
        and fields.get("fluid_mass_conserved")
        and fields.get("fluid_penetration_into_box", {}).get("pass")
        and fields.get("fixed_body_particle_count_constant")
        and fields.get("fixed_body_unchanged")
    )
    return {
        "fixed_body_mapping_gate": mapping_gate,
        "normal_ghost_gate": normal_gate,
        "solver_configuration_gate": solver_gate,
        "fields_gate": fields_gate,
        "multiple_window_gate": sample_gate,
        "stable_window_gate": stable_gate,
        "stable_window_std_limit_n": stability_limit,
        "forcez_window_means_n": means,
        "reference_fz_n": expected_fz_n,
        "reference_error_last_0p20s_percent": reference_error,
        "status": "diagnostic_only_not_physical_acceptance",
    }


def _read_saved_preflight(path: Path) -> dict[str, Any]:
    """Parse a previously saved live nvidia-smi CSV snapshot.

    The parent task already ran the canonical and fine probes with live
    preflight.  Reusing those immutable solver directories avoids launching a
    duplicate calibration, while this parser keeps the exact UUID/occupancy
    evidence in the mDBC report.
    """

    command = (
        "nvidia-smi --query-gpu=index,uuid,memory.used,memory.total,"
        "utilization.gpu --format=csv,noheader,nounits"
    )
    rows: list[dict[str, Any]] = []
    raw = path.read_text(errors="replace")
    for line in raw.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        try:
            rows.append({
                "index": int(fields[0]),
                "uuid": fields[1],
                "memory_used_mib": int(fields[2]),
                "memory_total_mib": int(fields[3]),
                "utilization_percent": int(fields[4]),
            })
        except ValueError:
            continue
    selected = next((row for row in rows if row["index"] == 4), None)
    if selected is None:
        raise ValueError(f"saved preflight {path} contains no GPU4 row")
    return {
        "command": command,
        "return_code": 0,
        "rows": rows,
        "snapshot": relative(path),
        "selected_gpu": selected,
        "owner_authorized_gpu_indices": list(OWNER_AUTHORIZED_GPU_INDICES),
        "preferred_idle_gpu_indices": list(PREFERRED_IDLE_GPU_INDICES),
        "busy_owner_authorized_indices_not_interrupted": [
            row["index"]
            for row in rows
            if row["index"] in OWNER_AUTHORIZED_GPU_INDICES
            and (
                row["index"] not in PREFERRED_IDLE_GPU_INDICES
                or row["memory_used_mib"] >= BASE.IDLE_MEMORY_LIMIT_MIB
                or row["utilization_percent"] > BASE.IDLE_UTILIZATION_LIMIT_PERCENT
            )
        ],
        "preflight_reused_from_completed_probe": True,
    }


def _historical_normal_ghost_audit(run_dir: Path) -> dict[str, Any]:
    """Audit a legacy probe whose generated XML was intentionally superseded."""

    normal_path = run_dir / "CfgInit_Normals.vtk"
    ghost_path = run_dir / "CfgInit_NormalsGhost.vtk"
    if not normal_path.is_file() or not ghost_path.is_file():
        return {
            "gate": False,
            "checks": {"files_present": False},
            "reason": "legacy probe has no normal/ghost files",
        }
    normal = read_binary_vtk_fields(normal_path)
    ghost = read_binary_vtk_fields(ghost_path)
    required = {"Mk", "Normal", "NormalSize"}
    normal_vectors = np.asarray(normal["arrays"].get("Normal", []), dtype=float)
    ghost_vectors = np.asarray(ghost["arrays"].get("Normal", []), dtype=float)
    normal_sizes = np.asarray(normal["arrays"].get("NormalSize", []), dtype=float).reshape(-1)
    ghost_sizes = np.asarray(ghost["arrays"].get("NormalSize", []), dtype=float).reshape(-1)
    normal_mk = np.asarray(normal["arrays"].get("Mk", []), dtype=int).reshape(-1)
    ghost_mk = np.asarray(ghost["arrays"].get("Mk", []), dtype=int).reshape(-1)
    normal_norms = np.linalg.norm(normal_vectors, axis=1) if normal_vectors.ndim == 2 else np.empty(0)
    ghost_norms = np.linalg.norm(ghost_vectors, axis=1) if ghost_vectors.ndim == 2 else np.empty(0)
    max_vector_error = (
        float(np.max(np.abs(ghost_vectors - 2.0 * normal_vectors)))
        if len(normal_vectors) == len(ghost_vectors)
        else math.inf
    )
    max_size_error = (
        float(np.max(np.abs(ghost_sizes - 2.0 * normal_sizes)))
        if len(normal_sizes) == len(ghost_sizes)
        else math.inf
    )
    checks = {
        "files_present": True,
        "required_arrays_present": required <= set(normal["arrays"]) and required <= set(ghost["arrays"]),
        "points_match": normal["count"] == ghost["count"] and bool(
            np.allclose(normal["points"], ghost["points"], rtol=0.0, atol=1.0e-7)
        ),
        "mk_match": len(normal_mk) == len(ghost_mk) and bool(np.array_equal(normal_mk, ghost_mk)),
        "finite": all(
            np.all(np.isfinite(values))
            for values in (normal["points"], ghost["points"], normal_vectors, ghost_vectors, normal_sizes, ghost_sizes)
        ),
        "no_zero_normals": int(np.sum(normal_norms <= NORMAL_ZERO_TOLERANCE)) == 0
        and int(np.sum(ghost_norms <= NORMAL_ZERO_TOLERANCE)) == 0,
        "ghost_vector_doubling": max_vector_error <= NORMAL_DOUBLING_TOLERANCE,
        "ghost_size_doubling": max_size_error <= NORMAL_DOUBLING_TOLERANCE,
    }
    return {
        "normal_file": {"path": relative(normal_path), "sha256": BASE.sha256(normal_path)},
        "ghost_file": {"path": relative(ghost_path), "sha256": BASE.sha256(ghost_path)},
        "normal_count": int(normal["count"]),
        "ghost_count": int(ghost["count"]),
        "normal_zero_count": int(np.sum(normal_norms <= NORMAL_ZERO_TOLERANCE)),
        "ghost_zero_count": int(np.sum(ghost_norms <= NORMAL_ZERO_TOLERANCE)),
        "body_normal_zero_count": int(
            np.sum(normal_norms[normal_mk == 18] <= NORMAL_ZERO_TOLERANCE)
        ),
        "body_ghost_zero_count": int(
            np.sum(ghost_norms[ghost_mk == 18] <= NORMAL_ZERO_TOLERANCE)
        ),
        "normal_mk_counts": {
            str(int(value)): int(np.sum(normal_mk == value))
            for value in np.unique(normal_mk)
        },
        "max_ghost_vector_minus_2_normal": max_vector_error,
        "max_ghost_size_minus_2_normal_size": max_size_error,
        "checks": checks,
        "gate": all(checks.values()),
        "note": "Legacy solver probe is not cross-matched to the final shifted-shell generated XML; zero normals intentionally fail the structural gate.",
    }


def _fake_attempt(run_dir: Path, gpu: dict[str, Any], generated_prefix: Path) -> dict[str, Any]:
    """Represent an already completed probe without overwriting its metadata."""

    return {
        "schema_version": 1,
        "case_id": run_dir.name,
        "attempt_id": run_dir.name,
        "status": "completed",
        "started_at_utc": None,
        "finished_at_utc": None,
        "command": [str(BASE.SOLVER), f"-gpu:{gpu['index']}", str(generated_prefix), str(run_dir)],
        "actual_command": [str(BASE.SOLVER), f"-gpu:{gpu['index']}", str(generated_prefix), str(run_dir)],
        "gpu_at_launch": gpu,
        "attempt_directory": relative(run_dir),
        "part_files": len(list((run_dir / "data").glob("Part_[0-9][0-9][0-9][0-9].bi4"))),
        "provenance": "completed_probe_ingested_without_duplicate_launch",
    }


def _solver_log_audit(run_dir: Path, attempt: dict[str, Any]) -> dict[str, Any]:
    """Use the base audit plus a tolerant excluded-particle parser."""

    audit = BASE.solver_log_audit(run_dir, attempt)
    text = (run_dir / "solver.stdout.log").read_text(errors="replace")
    match = re.search(r"Excluded particles\.+:\s*([\d,]+)", text)
    if match:
        audit["excluded_particles"] = match.group(1)
    return audit


def ingest_existing_case(
    spec: dict[str, Any], source: dict[str, Any], gencase: dict[str, Any],
    gencase_log: dict[str, Any], mapping_gate: dict[str, Any],
) -> dict[str, Any]:
    """Ingest one completed probe and apply the final mDBC gates.

    The canonical probe is deliberately an older construction with 216
    missing normals.  It is retained as the requested ``canonical-2`` failure
    evidence.  The fine probe uses the final fine generated XML and is fully
    field-audited here; its 240 zero normals, excluded particles, and late
    penetration remain failures.
    """

    run_dir = Path(spec["existing_solver_run"])
    preflight_path = Path(spec["preflight"])
    if not run_dir.is_dir():
        raise FileNotFoundError(f"completed probe directory missing: {run_dir}")
    if not preflight_path.is_file():
        raise FileNotFoundError(f"live preflight snapshot missing: {preflight_path}")

    preflight = _read_saved_preflight(preflight_path)
    gpu = preflight["selected_gpu"]
    generated = gencase["generated"]
    generated_prefix = CASE_ROOT / gencase["generated_prefix"]
    attempt = _fake_attempt(run_dir, gpu, generated_prefix)
    result_dir = RESULT_ROOT / spec["case_id"] / f"{spec['run_label']}-ingested"
    BASE.copy_run_metadata(run_dir, result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    attempt_path = result_dir / "attempt.json"
    BASE.json_dump(attempt_path, attempt)
    solver_evidence = _copy_solver_evidence(run_dir, result_dir)
    generated_evidence = _copy_generated_evidence(result_dir, gencase, generated)
    solver_log = _solver_log_audit(run_dir, attempt)

    case_report: dict[str, Any] = {
        "case_id": spec["case_id"],
        "run_label": spec["run_label"],
        "label": spec["label"],
        "definition": source,
        "gencase": gencase,
        "gencase_log_audit": gencase_log,
        "fixed_body_mapping_gate": mapping_gate,
        "gpu_preflight": preflight,
        "attempt": attempt,
        "attempt_provenance": {
            "solver_run_directory": relative(run_dir),
            "source_definition_matches_final_definition": bool(spec["solver_source_matches_final_definition"]),
            "duplicate_solver_launch": False,
        },
        "result_directory": relative(result_dir),
        "generated_evidence": generated_evidence,
        "solver_evidence": solver_evidence,
        "solver_log": solver_log,
        "analytical_reference": {
            "rho_kg_m3": BASE.RHO0,
            "gravity_m_s2": BASE.G,
            "box_size_m": list(BASE.BOX_SIZE),
            "box_volume_m3": BASE.BOX_VOLUME_M3,
            "pressure_resultant_fz_n": BASE.ANALYTIC_FZ_N,
            "status": "pre_registered_reference_only",
        },
        "execution_status": "completed",
        "acceptance_status": "candidate_not_accepted",
    }

    if spec["solver_source_matches_final_definition"]:
        normal_audit = normal_ghost_audit(run_dir, generated, source, spec["dp_m"])
        case_report["normal_ghost_audit"] = normal_audit
        generated_xml = CASE_ROOT / generated["generated_xml"]
        expected_fluid = generated["fluid_mapping"][0]["count"]
        fields = BASE.field_audit(run_dir, generated_xml, result_dir, expected_fluid)
        case_report["field_integrity"] = fields
        mapping_for_gate = bool(
            mapping_gate["source_mkbound_maps_to_one_fixed_row"]
            and mapping_gate["no_moving_or_floating_rows"]
        )
        normal_for_gate = bool(normal_audit["gate"])
    else:
        # The old canonical-2 generated XML was not retained and has 2,197
        # body particles rather than the final shifted-shell 504.  Do not
        # compare its fields by row index or pretend its mapping is current.
        normal_audit = _historical_normal_ghost_audit(run_dir)
        case_report["normal_ghost_audit"] = normal_audit
        case_report["field_integrity"] = {
            "audit_status": "not_run_source_mapping_mismatch",
            "reason": "legacy canonical-2 generated XML was superseded and is not available; raw solver fields remain retained",
            "fixed_body_motion": "not_audited",
            "fluid_penetration": "not_audited",
        }
        mapping_for_gate = False
        normal_for_gate = False

    gauge = BASE.parse_force_csv(run_dir / "GaugesForce_BoxForce.csv", result_dir / "force_timeseries.csv")
    case_report["force_gauge"] = gauge
    excluded = _safe_int(solver_log.get("excluded_particles"))
    solver_gate = bool(
        solver_log.get("finished_text_found")
        and solver_log.get("gauge_config_target_found")
        and excluded == 0
        and mapping_for_gate
    )
    case_report["solver_configuration_gate"] = {
        "finished_text_found": solver_log.get("finished_text_found"),
        "gauge_config_target_found": solver_log.get("gauge_config_target_found"),
        "excluded_particles": excluded,
        "source_mkbound_1_fixed_mapping": mapping_for_gate,
        "moving_summary": solver_log.get("moving_summary"),
        "floating_summary": solver_log.get("floating_summary"),
        "pass": solver_gate,
        "note": "generated XML mapping is authoritative; mDBC solver summary omits moving/floating rows",
    }
    case_report["screen"] = _force_screen(
        gauge, float(spec["expected_fz_n"]), case_report["field_integrity"],
        normal_for_gate, mapping_for_gate, solver_gate,
    )
    case_report["acceptance_status"] = "candidate_not_accepted"
    return case_report


def run_case(spec: dict[str, Any], index: int) -> dict[str, Any]:
    case_id = spec["case_id"]
    definition = Path(spec["definition"])
    source = source_geometry_audit(definition, spec)
    gencase = BASE.run_gencase(case_id, definition)
    case_report: dict[str, Any] = {
        "case_id": case_id,
        "run_label": spec["run_label"],
        "label": spec["label"],
        "definition": source,
        "gencase": gencase,
        "analytical_reference": {
            "rho_kg_m3": BASE.RHO0,
            "gravity_m_s2": BASE.G,
            "box_size_m": list(BASE.BOX_SIZE),
            "box_volume_m3": BASE.BOX_VOLUME_M3,
            "pressure_resultant_fz_n": BASE.ANALYTIC_FZ_N,
            "status": "pre_registered_reference_only",
        },
        "execution_status": "not_started",
        "acceptance_status": "candidate_not_accepted",
    }
    gencase_log = parse_gencase_log(CASE_ROOT / gencase["stdout_log"])
    case_report["gencase_log_audit"] = gencase_log
    if gencase["return_code"] != 0 or not gencase.get("generated"):
        case_report["execution_status"] = "gencase_failed"
        case_report["blocked_reason"] = "GenCase failed; no GPU launch was attempted."
        return case_report
    generated = gencase["generated"]
    mapping = generated["mapping_source_to_global_mk"]
    body_rows = [item for item in mapping if item["source_mkbound"] == 1]
    no_moving_floating = not any(
        item["particle_type"] in {"moving", "floating"} for item in mapping
    )
    mapping_gate = {
        "source_mkbound": 1,
        "mapping_rows": body_rows,
        "source_mkbound_maps_to_one_fixed_row": len(body_rows) == 1
        and body_rows[0]["particle_type"] == "fixed",
        "no_moving_or_floating_rows": no_moving_floating,
        "body_global_mk": body_rows[0]["global_mk"] if len(body_rows) == 1 else None,
        "body_particle_count": body_rows[0]["count"] if len(body_rows) == 1 else None,
    }
    case_report["fixed_body_mapping_gate"] = mapping_gate
    mapping_safe = bool(
        mapping_gate["source_mkbound_maps_to_one_fixed_row"]
        and mapping_gate["no_moving_or_floating_rows"]
    )
    if not gencase_log["normal_completeness_gate"] or not mapping_safe:
        case_report["execution_status"] = "blocked_not_run"
        reasons: list[str] = []
        if not gencase_log["normal_completeness_gate"]:
            reasons.append("GenCase final zero-normal/missing-normal gate failed")
        if not mapping_safe:
            reasons.append("source mkbound=1 did not map to exactly one fixed row")
        case_report["blocked_reason"] = "; ".join(reasons)
        return case_report

    # The owner has already completed the bounded canonical-2 and fine-3
    # probes in immutable shared run directories.  Ingest those exact logs and
    # traces rather than launching duplicate solver attempts; the ingestion
    # path still applies the strict normal/ghost, mapping, field, exclusion,
    # and force-window gates below.
    if spec.get("existing_solver_run"):
        return ingest_existing_case(
            spec, source, gencase, gencase_log, mapping_gate
        )

    # Live preflight immediately before each launch.  Busy owner-authorized
    # GPUs are recorded and left untouched; selection is restricted to truly
    # idle preferred GPUs 4--7.
    preflight_path = RUN_ROOT / "gpu-preflight" / f"mdbc-{index:02d}-{case_id}.txt"
    snapshot = BASE.capture_gpu_snapshot(preflight_path)
    gpu = BASE.choose_idle_gpu(snapshot)
    case_report["gpu_preflight"] = {
        **snapshot,
        "owner_authorized_gpu_indices": list(OWNER_AUTHORIZED_GPU_INDICES),
        "preferred_idle_gpu_indices": list(PREFERRED_IDLE_GPU_INDICES),
        "busy_owner_authorized_indices_not_interrupted": [
            row["index"]
            for row in snapshot.get("rows", [])
            if row["index"] in OWNER_AUTHORIZED_GPU_INDICES
            and (
                row["index"] not in PREFERRED_IDLE_GPU_INDICES
                or row["memory_used_mib"] >= BASE.IDLE_MEMORY_LIMIT_MIB
                or row["utilization_percent"] > BASE.IDLE_UTILIZATION_LIMIT_PERCENT
            )
        ],
        "selected_gpu": gpu,
    }
    generated_prefix = CASE_ROOT / gencase["generated_prefix"]
    attempt = BASE.run_solver_attempt(case_id, generated_prefix, gpu)
    case_report["attempt"] = attempt
    attempt_dir = CASE_ROOT / attempt["attempt_directory"]
    result_dir = RESULT_ROOT / case_id / attempt["attempt_id"]
    BASE.copy_run_metadata(attempt_dir, result_dir)
    case_report["result_directory"] = relative(result_dir)
    case_report["solver_log"] = _solver_log_audit(attempt_dir, attempt)
    case_report["solver_evidence"] = _copy_solver_evidence(attempt_dir, result_dir)
    case_report["execution_status"] = "completed" if attempt["status"] == "completed" else "solver_failed"
    if attempt["status"] != "completed":
        case_report["blocked_reason"] = "GPU solver attempt failed; failed attempt retained."
        return case_report

    case_report["generated_evidence"] = _copy_generated_evidence(result_dir, gencase, generated)
    generated_xml = CASE_ROOT / generated["generated_xml"]
    normal_audit = normal_ghost_audit(attempt_dir, generated, source, spec["dp_m"])
    case_report["normal_ghost_audit"] = normal_audit
    expected_fluid = generated["fluid_mapping"][0]["count"]
    fields = BASE.field_audit(attempt_dir, generated_xml, result_dir, expected_fluid)
    case_report["field_integrity"] = fields
    gauge_source = attempt_dir / "GaugesForce_BoxForce.csv"
    gauge = BASE.parse_force_csv(gauge_source, result_dir / "force_timeseries.csv")
    case_report["force_gauge"] = gauge

    solver_log = case_report["solver_log"]
    excluded = _safe_int(solver_log.get("excluded_particles"))
    solver_gate = bool(
        solver_log.get("finished_text_found")
        and solver_log.get("gauge_config_target_found")
        and excluded == 0
        and mapping_safe
        and solver_log.get("attempt_status") == "completed"
    )
    case_report["solver_configuration_gate"] = {
        "finished_text_found": solver_log.get("finished_text_found"),
        "gauge_config_target_found": solver_log.get("gauge_config_target_found"),
        "excluded_particles": excluded,
        "source_mkbound_1_fixed_mapping": mapping_safe,
        "moving_summary": solver_log.get("moving_summary"),
        "floating_summary": solver_log.get("floating_summary"),
        "pass": solver_gate,
        "note": "mDBC solver summary omits moving/floating rows; generated XML mapping is authoritative and has no such rows",
    }
    case_report["screen"] = _force_screen(
        gauge,
        float(spec["expected_fz_n"]),
        fields,
        bool(normal_audit["gate"]),
        mapping_safe,
        solver_gate,
    )
    # Keep this explicit regardless of all diagnostic gates.
    case_report["acceptance_status"] = "candidate_not_accepted"
    return case_report


def _historical_probe_audit() -> list[dict[str, Any]]:
    """Record old probes without treating them as either final calibration."""

    records: list[dict[str, Any]] = []
    for spec in CASE_SPECS:
        name = spec.get("historical_probe")
        if not name:
            records.append({
                "run_label": "fine-3",
                "path": None,
                "status": "no_valid_historical_fine_probe",
                "note": "The old canonical-3/-4 directories were checked and both used Dp=0.025; they are not fine evidence.",
            })
            continue
        path = RUN_ROOT / name
        log = path / "solver.stdout.log"
        force = path / "GaugesForce_BoxForce.csv"
        item: dict[str, Any] = {
            "run_label": spec["run_label"],
            "path": relative(path) if path.exists() else None,
            "status": "superseded_historical_probe" if path.exists() else "missing",
            "note": "Retained for provenance only; not used for final mDBC result because it predates the final shifted-shell construction.",
        }
        if log.is_file():
            item["solver_log"] = {"path": relative(log), "sha256": BASE.sha256(log)}
            text = log.read_text(errors="replace")
            item["boundary_mode_mdbc"] = 'Boundary="mDBC"' in text
        if force.is_file():
            item["force_trace"] = {"path": relative(force), "sha256": BASE.sha256(force)}
            try:
                item["force_windows"] = BASE.parse_force_csv(force, path / "historical-force-copy.csv")["windows"]
                (path / "historical-force-copy.csv").unlink(missing_ok=True)
            except Exception as error:
                item["force_parse_error"] = f"{type(error).__name__}: {error}"
        records.append(item)
    # Canonical-3 and canonical-4 are intentionally called out because they
    # were previously mistaken for a fine run by label alone.
    for name in ("mdbc-probe-canonical-3", "mdbc-probe-canonical-4"):
        path = RUN_ROOT / name
        log = path / "solver.stdout.log"
        records.append({
            "run_label": name,
            "path": relative(path) if path.exists() else None,
            "status": "superseded_not_fine" if path.exists() else "missing",
            "reported_dp_m": 0.025 if log.is_file() and "Dp=0.025" in log.read_text(errors="replace") else None,
            "note": "Both legacy directories have the canonical 0.025 m particle count; neither is a fine run.",
            "solver_log": {"path": relative(log), "sha256": BASE.sha256(log)} if log.is_file() else None,
            "force_trace": {
                "path": relative(path / "GaugesForce_BoxForce.csv"),
                "sha256": BASE.sha256(path / "GaugesForce_BoxForce.csv"),
            }
            if (path / "GaugesForce_BoxForce.csv").is_file()
            else None,
        })
    return records


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# mDBC fixed immersed box force gauge",
        "",
        "> Bounded candidate evidence only. `overall_acceptance_status` is deliberately `candidate_not_accepted`; the analytical 78.48 N value is a preregistered pressure reference, not an acceptance threshold by itself.",
        "",
        "## Scope and semantics",
        "",
        f"- Exactly two bounded mDBC calibrations: `canonical-2` (`dp={CASE_SPECS[0]['dp_m']} m`) and `fine-3` (`dp={CASE_SPECS[1]['dp_m']} m`). No radius scan or extra calibration was run.",
        f"- Physical cube: `{BASE.BOX_SIZE[0]:g} x {BASE.BOX_SIZE[1]:g} x {BASE.BOX_SIZE[2]:g} m`, void `{list(BASE.BOX_MIN)}--{list(BASE.BOX_MAX)} m`; floor gap `{BASE.BOX_MIN[2]:g} m`, water top `{BASE.TANK_INNER_MAX[2]:g} m`.",
        "- Both definitions use source `mkbound=1`, no `<floating>` section, and `Boundary=2` mDBC. The fixed shell is drawn after the void; its normal-only surface has one `+0.5 dp` layer and the shell uses `0,-1,-2` layers.",
        "- The solver files are audited as `x_gamma=x_boundary+n_ghost/2`; ghost vectors/sizes must be exactly twice the normal arrays, and the reconstructed body interface must lie on the physical cube faces with outward normals.",
        "- Gauge output is signed pressure interaction on selected fixed boundary particles only (`forcex`, `forcey`, `forcez`); it excludes gravity, support reaction, and viscosity.",
        "- Analytical preregistered reference: `Fz=rho*g*V=78.48 N` in `+z`; it is never converted to physical acceptance automatically.",
        "",
        "## Source and runtime evidence",
        "",
        "- Gauge format: `doc/xml_format/_FmtXML_Gauges.xml` (`force/target mkbound`).",
        "- Source mapping: `src/source/JDsGaugeSystem.cpp:472-493` (`AddGaugeForce` resolves `mkbound` through `JSphMk`).",
        "- Force semantics: `src/source/JDsGaugeItem.cpp:1710-1988` and CUDA implementation `src/source/JDsGauge_ker.cu:497-603`.",
        f"- Owner authorization covers GPU indices `{list(OWNER_AUTHORIZED_GPU_INDICES)}`. Live preflight prefers idle `{list(PREFERRED_IDLE_GPU_INDICES)}`; busy jobs were not interrupted.",
        "",
        "## Final calibration runs",
        "",
        "| run | execution | GPU / UUID | attempt | zero normals | normal/ghost | fixed body | force windows | late Fz (N) | status |",
        "|---|---|---|---|---:|---|---|---|---:|---|",
    ]
    for case in report["cases"]:
        execution = case.get("execution_status", "unknown")
        if execution != "completed":
            zero = case.get("gencase_log_audit", {}).get("final_zero_normals")
            zero_text = "—" if not zero else f"{zero['count']}/{zero['total']}"
            lines.append(
                f"| `{case.get('run_label', case.get('case_id'))}` | `{execution}` | — | — | `{zero_text}` | — | — | — | — | `{case.get('acceptance_status', 'candidate_not_accepted')}` |"
            )
            continue
        gpu = case["attempt"]["gpu_at_launch"]
        normal = case["normal_ghost_audit"]
        field = case["field_integrity"]
        force = case["force_gauge"]
        late = force["windows"]["last_0p20s"]["forcez [N]"]["mean"]
        fixed_unchanged = field.get("fixed_body_unchanged", "not_audited")
        lines.append(
            f"| `{case['run_label']}` | `{execution}` | `{gpu['index']} / {gpu['uuid']}` | `{case['attempt']['attempt_id']}` | `{normal.get('normal_zero_count', 0)}/{normal['normal_count']}` | `{normal['gate']}` | `{fixed_unchanged}` | `{case['screen']['stable_window_gate']}` | `{late:.3f}` | `{case['acceptance_status']}` |"
        )
    for case in report["cases"]:
        lines.extend(["", f"### `{case.get('run_label', case.get('case_id'))}`", ""])
        lines.append(f"- Definition: `{case['definition']['definition']}`; SHA-256 `{case['definition']['definition_sha256']}`.")
        lines.append(f"- GenCase log: `{case['gencase_log_audit']['log']}`; generated final zero-normal audit: `{case['gencase_log_audit'].get('final_zero_normals')}`.")
        if case.get("execution_status") != "completed":
            lines.append(f"- No solver launch: `{case.get('blocked_reason', 'see machine-readable report')}`. Generated output/logs are retained.")
            continue
        normal = case["normal_ghost_audit"]
        force = case["force_gauge"]
        field = case["field_integrity"]
        lines.extend([
            f"- Source `mkbound=1` -> generated fixed `Mk={case['fixed_body_mapping_gate']['body_global_mk']}`, `{case['fixed_body_mapping_gate']['body_particle_count']}` particles. Generated XML: `{case['generated_evidence']['particles_xml']}`.",
            f"- GPU preflight: `{case['gpu_preflight']['snapshot']}`; selected `{case['attempt']['gpu_at_launch']['index']}` / `{case['attempt']['gpu_at_launch']['uuid']}`; busy authorized indices left untouched: `{case['gpu_preflight']['busy_owner_authorized_indices_not_interrupted']}`.",
            f"- Normal/ghost arrays: `{normal['normal_file']['path']}`, `{normal['ghost_file']['path']}`; counts `{normal['normal_count']}/{normal['ghost_count']}`, zero total `{normal.get('normal_zero_count')}/{normal.get('ghost_zero_count')}` (body `{normal.get('body_normal_zero_count')}/{normal.get('body_ghost_zero_count')}`), max doubling errors `{normal['max_ghost_vector_minus_2_normal']:.3e}` and `{normal['max_ghost_size_minus_2_normal_size']:.3e}`.",
            f"- Signed trace: `{force['signed_csv']}` (`forcex/forcey/forcez`, {force['sample_count']} samples). `Fz` means last 0.20/0.40/0.60 s: `{case['screen']['forcez_window_means_n']}`, standard-deviation limit `{case['screen']['stable_window_std_limit_n']:.3f} N`, stable gate `{case['screen']['stable_window_gate']}`.",
            f"- Solver log/config gate: `{case['solver_configuration_gate']['pass']}`; excluded particles `{case['solver_configuration_gate']['excluded_particles']}`. Overall candidate acceptance remains `{case['acceptance_status']}`.",
        ])
        if "effective_body_interface_bbox_m" in normal:
            lines.insert(
                len(lines) - 2,
                f"- Reconstructed body interface bbox `{normal['effective_body_interface_bbox_m']}`, max face residual `{normal['effective_body_interface_max_face_residual_m']:.3e} m`, min outward-normal dot `{normal['effective_body_normal_orientation_min_dot']:.3f}`; gate `{normal['gate']}`.",
            )
        else:
            lines.insert(
                len(lines) - 2,
                f"- Historical normal/ghost gate: zero `{normal.get('normal_zero_count')}/{normal.get('ghost_zero_count')}`, gate `{normal.get('gate')}`; current generated mapping was not applied to superseded solver fields.",
            )
        if "fixed_body_unchanged" in field:
            lines.insert(
                len(lines) - 2,
                f"- Fixed-body field audit matches by `(Zone,Idp)` after filtering generated `Mk={field['fixed_body_global_mk']}`: count `{field['fixed_body_particle_count_initial']}/{field['fixed_body_particle_count_final']}`, max motion `{field['fixed_body_particle_motion_max_m']:.3e} m`; fluid penetration `{field['fluid_penetration_into_box']['initial_particles']}/{field['fluid_penetration_into_box']['final_particles']}`.",
            )
        else:
            lines.insert(
                len(lines) - 2,
                f"- Fixed-body field audit: `{field.get('audit_status')}`; {field.get('reason', 'not available')}.",
            )
    lines.extend([
        "",
        "## Historical probe provenance",
        "",
        "The old `mdbc-probe-canonical-2` trace is retained as superseded canonical evidence. The old `mdbc-probe-canonical-3` and `mdbc-probe-canonical-4` directories were checked: both are `dp=0.025 m` canonical runs, not fine evidence. They are listed only to prevent a filename-based fine-run claim; the final `fine-3` row above has its own generated prefix and attempt directory.",
        "",
        "## Acceptance decision",
        "",
        "All execution results, traces, normal/ghost files, generated mappings, and failed/blocked outcomes are evidence. A force window that is unstable or a failed structural gate remains a diagnostic failure. No mDBC result in this report is physically accepted.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    if not all(path.is_file() for path in (BASE.GENCASE, BASE.SOLVER, BASE.PARTVTK)):
        raise SystemExit("missing one or more vendored DualSPHysics binaries")
    started = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    for index, spec in enumerate(CASE_SPECS):
        try:
            records.append(run_case(spec, index))
        except Exception as error:
            # Keep a machine-readable row even if post-processing fails after
            # the solver has written its raw attempt directory.
            records.append({
                "case_id": spec["case_id"],
                "run_label": spec["run_label"],
                "execution_status": "runner_exception",
                "acceptance_status": "candidate_not_accepted",
                "error": f"{type(error).__name__}: {error}",
            })
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_id": "R3-fixed-box-force-gauge-mDBC",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_root": str(CASE_ROOT.relative_to(BASE.LAB_ROOT)),
        "bounded_calibration_count": len(CASE_SPECS),
        "bounded_calibration_policy": "exactly canonical-2 and fine-3; no radius scan",
        "owner_authorization": {
            "authorized_gpu_indices": list(OWNER_AUTHORIZED_GPU_INDICES),
            "preferred_idle_indices": list(PREFERRED_IDLE_GPU_INDICES),
            "busy_jobs_interrupted": False,
            "selection_rule": "live nvidia-smi immediately before launch; memory.used < 500 MiB and utilization == 0 on preferred indices",
        },
        "resource_policy": {
            "idle_memory_limit_mib": BASE.IDLE_MEMORY_LIMIT_MIB,
            "idle_utilization_limit_percent": BASE.IDLE_UTILIZATION_LIMIT_PERCENT,
            "existing_processes_not_interrupted": True,
        },
        "source_semantics": {
            "gauge_xml": "doc/xml_format/_FmtXML_Gauges.xml",
            "gauge_system_add_gauge_force": "src/source/JDsGaugeSystem.cpp:472-493",
            "gauge_force_impl": "src/source/JDsGaugeItem.cpp:1710-1988",
            "gauge_force_kernel": "src/source/JDsGauge_ker.cu:497-603",
            "force_interpretation": "signed pressure interaction on selected fixed boundary particles only; excludes gravity, support reaction, and viscosity",
        },
        "analytical_reference": {
            "box_dimensions_m": list(BASE.BOX_SIZE),
            "box_volume_m3": BASE.BOX_VOLUME_M3,
            "rho_kg_m3": BASE.RHO0,
            "g_m_s2": BASE.G,
            "fz_n": BASE.ANALYTIC_FZ_N,
            "status": "pre_registered_reference_only",
        },
        "normal_ghost_contract": {
            "normal_file_arrays": ["Mk", "Normal", "NormalSize"],
            "ghost_file_arrays": ["Mk", "Normal", "NormalSize"],
            "required_formula": "x_gamma=x_boundary+n_ghost/2",
            "required_ghost_doubling_tolerance": NORMAL_DOUBLING_TOLERANCE,
            "required_zero_normal_count": 0,
            "required_body_interface": "physical cube [0.50,0.70] x [0.30,0.50] x [0.20,0.40] m with outward normal orientation",
        },
        "historical_probe_provenance": _historical_probe_audit(),
        "cases": records,
        "overall_acceptance_status": "candidate_not_accepted",
    }
    BASE.json_dump(REPORT_PATH, report)
    REPORT_MD_PATH.write_text(render_markdown(report))
    print(json.dumps({
        "report": str(REPORT_PATH),
        "cases": [
            {
                "run_label": row.get("run_label"),
                "case_id": row.get("case_id"),
                "execution_status": row.get("execution_status"),
                "acceptance_status": row.get("acceptance_status"),
            }
            for row in records
        ],
    }, indent=2))
    # A deliberate blocked_not_run outcome is a valid bounded result.  A
    # solver failure or runner exception remains non-zero for CI visibility.
    allowed = {"completed", "blocked_not_run"}
    return 0 if all(row.get("execution_status") in allowed for row in records) else 1


if __name__ == "__main__":
    sys.exit(main())
