"""Prepare and audit an F1 ECC thick-boundary DBC initialisation.

This is an additive, CPU-only GenCase/PartVTK preflight module.  The earlier
ECC candidates put a boundary face on the same lattice rows as the fluid and
then tried two ``vdp`` directions; those attempts are preserved as negative
evidence and are not modified by this module.

The candidate keeps the ECC continuous tank, obstacle, density, gravity and
one-particle-per-cell fluid quadrature.  It borrows the explicit lattice
anchor from the successful F1 finite-centre DBC definition and the
``boxfill=solid`` cell-centre primitive from the successful F5 references.
Each closed tank face is a separate three-grid-layer solid slab wholly
outside its physical plane.  The nearest fixed row is therefore at
``0.5*dp`` outside the plane and cannot overwrite the first fluid row at
``0.5*dp`` inside the fluid envelope.  The obstacle uses the same outside
slab construction for its four vertical faces and top; its physical solid
volume and location remain unchanged.

``run-gencase`` invokes only the official GenCase and PartVTK binaries.  It
writes a child GenCase receipt containing the parsed official total/fluid
counts and Data2D dimension before the larger native audit.  The native audit
also decodes the generated BI4 through the read-only upstream ``bi4_dump``
adapter, requires ``Posd.bin`` (double positions), checks the real Idp axis
against generated fixed/fluid ranges, and performs finite-face coverage on
the typed fixed positions.  No solver, GPU, learning model, or Q-N decision
is made here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import resource
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.spatial import cKDTree


FAMILY_ID = "F1"
MECHANISM_ID = "eccentric_obstacle"
PHYSICAL_CASE_ID = "F1_ECCENTRIC_THICK_BOUNDARY_DBC"
SCHEMA = "ds02.f1.eccentric-thick-boundary.v1"
RHO0 = 1000.0
DP_M = 0.01
FLUID_LOW = (0.0, 0.0, 0.0)
FLUID_SIZE = (0.4, 0.67, 0.3)
TANK_LOW = (0.0, 0.0, 0.0)
TANK_SIZE = (1.6, 0.67, 0.4)
OBSTACLE_LOW = (0.9, 0.24, 0.0)
OBSTACLE_SIZE = (0.12, 0.12, 0.45)
OUTER_FACES = ("x_low", "x_high", "y_low", "y_high", "z_low")
OBSTACLE_FACES = ("x_low", "x_high", "y_low", "y_high", "z_high")
EXPECTED_COUNTS = (40, 67, 30)
EXPECTED_FLUID = math.prod(EXPECTED_COUNTS)
EXPECTED_MASS = RHO0 * math.prod(FLUID_SIZE)
SUPPORT_LAYERS = 3

_SCRIPT = Path(__file__).resolve()
_LAB = _SCRIPT.parents[1]
_SCOPE = _LAB / "campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_001"
DEFAULT_TEMPLATE = _LAB / "campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_solid_cellcenter_fallback_003/source/F1_REF_ECC_NOMINAL_BASE_Def.xml"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    raise TypeError(type(value).__name__)


def _q(value: float) -> str:
    return format(float(value), ".16g")


def _xyz(node: ET.Element, tag: str = "point") -> tuple[float, float, float]:
    child = node.find(tag)
    if child is None:
        raise ValueError(f"{tag} missing from {node.tag}")
    return tuple(float(child.attrib[axis]) for axis in ("x", "y", "z"))


def _size(node: ET.Element) -> tuple[float, float, float]:
    child = node.find("size")
    if child is None:
        raise ValueError(f"size missing from {node.tag}")
    return tuple(float(child.attrib[axis]) for axis in ("x", "y", "z"))


def _parameters(root: ET.Element) -> dict[str, str]:
    return {
        node.attrib["key"]: node.attrib.get("value", "")
        for node in root.findall("./execution/parameters/parameter")
        if "key" in node.attrib
    }


def _set_parameter(root: ET.Element, key: str, value: str) -> None:
    node = root.find(f"./execution/parameters/parameter[@key='{key}']")
    if node is None:
        params = root.find("./execution/parameters")
        if params is None:
            raise ValueError("execution/parameters missing")
        node = ET.Element("parameter", {"key": key, "value": value})
        params.insert(0, node)
    else:
        node.set("value", value)


def inspect_source(template: Path) -> dict[str, Any]:
    """Read the immutable ECC source and derive a physical-only binding."""

    template = template.resolve()
    root = ET.parse(template).getroot()
    definition = root.find("./casedef/geometry/definition")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    constants = root.find("./casedef/constantsdef")
    if definition is None or mainlist is None or constants is None:
        raise ValueError("ECC source lacks definition, constants, or mainlist")
    boxes = [node for node in mainlist if node.tag == "drawbox"]
    if len(boxes) != 4:
        raise ValueError(f"expected four immutable ECC drawboxes, got {len(boxes)}")
    fluid, outer, obstacle_void, obstacle_bound = boxes
    if fluid.findtext("boxfill") != "solid" or _xyz(fluid) != FLUID_LOW or _size(fluid) != FLUID_SIZE:
        raise ValueError("source fluid primitive is not the frozen ECC reservoir")
    if outer.findtext("boxfill") != "bottom | left | right | front | back" or _xyz(outer) != TANK_LOW or _size(outer) != TANK_SIZE:
        raise ValueError("source tank primitive is not the frozen ECC tank")
    if obstacle_void.findtext("boxfill") != "solid" or _xyz(obstacle_void) != OBSTACLE_LOW or _size(obstacle_void) != OBSTACLE_SIZE:
        raise ValueError("source obstacle void differs from the frozen ECC obstacle")
    if obstacle_bound.findtext("boxfill") != "top | left | right | front | back" or _xyz(obstacle_bound) != OBSTACLE_LOW or _size(obstacle_bound) != OBSTACLE_SIZE:
        raise ValueError("source obstacle boundary differs from the frozen ECC obstacle")
    if root.find("./casedef/normals") is not None:
        raise ValueError("ECC DBC source unexpectedly declares mDBC normals")

    constant_payload = {node.tag: dict(node.attrib) for node in constants}
    gravity = constants.find("gravity")
    rhop0 = constants.find("rhop0")
    if gravity is None or tuple(float(gravity.attrib[axis]) for axis in ("x", "y", "z")) != (0.0, 0.0, -9.81):
        raise ValueError("source gravity differs from frozen ECC control")
    if rhop0 is None or float(rhop0.attrib.get("value", "nan")) != RHO0:
        raise ValueError("source density differs from frozen ECC control")
    params = _parameters(root)
    # The source has no Boundary parameter because DBC is the official
    # default.  The candidate writes Boundary=1 explicitly so a later solver
    # request cannot depend on a command-line default.
    if params.get("Boundary") not in (None, "1"):
        raise ValueError(f"source boundary is not DBC: {params.get('Boundary')}")
    physical_payload = {
        "schema": "ds02.f1.eccentric-thick-boundary.physical.v1",
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "mechanism_id": MECHANISM_ID,
        "continuous_geometry": {
            "tank_low_m": list(TANK_LOW),
            "tank_high_m": [TANK_LOW[i] + TANK_SIZE[i] for i in range(3)],
            "tank_size_m": list(TANK_SIZE),
            "closed_faces": list(OUTER_FACES),
            "open_top": True,
            "fluid_low_m": list(FLUID_LOW),
            "fluid_high_m": [FLUID_LOW[i] + FLUID_SIZE[i] for i in range(3)],
            "fluid_size_m": list(FLUID_SIZE),
            "obstacle_low_m": list(OBSTACLE_LOW),
            "obstacle_high_m": [OBSTACLE_LOW[i] + OBSTACLE_SIZE[i] for i in range(3)],
            "obstacle_size_m": list(OBSTACLE_SIZE),
        },
        "initial_state": {
            "density_kg_m3": RHO0,
            "continuum_fluid_volume_m3": math.prod(FLUID_SIZE),
            "continuum_fluid_mass_kg": EXPECTED_MASS,
            "initial_velocity_m_per_s": [0.0, 0.0, 0.0],
            "quadrature": "one fluid particle per dp^3 cell; native mass retained",
            "mass_rescaling": False,
        },
        "physical_controls": {
            "boundary_method": "DBC",
            "gravity_m_per_s2": [0.0, 0.0, -9.81],
            "constantsdef": constant_payload,
            "source_execution_parameters_except_numeric": {
                key: value
                for key, value in params.items()
                if key not in {"SavePosDouble", "StepAlgorithm", "VerletSteps", "Kernel", "CoefDtMin", "DtIni", "DtMin", "DtFixed", "DtAllParticles", "TimeMax", "TimeOut", "RhopOutMin", "RhopOutMax"}
            },
            "motion": "empty static motion element",
            "normals": False,
        },
        "source_definition_sha256": sha256(template),
    }
    return {
        "source_path": str(template),
        "source_sha256": sha256(template),
        "physical_payload": physical_payload,
        "physical_hash": hashlib.sha256(_canonical(physical_payload).encode()).hexdigest(),
        "source_parameters": params,
    }


def _element(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    child = ET.SubElement(parent, tag, attrs or {})
    if text is not None:
        child.text = text
    return child


def _drawbox(parent: ET.Element, comment: str, fill: str, point: Iterable[float], size: Iterable[float]) -> None:
    draw = _element(parent, "drawbox", {"cmt": comment})
    _element(draw, "boxfill", text=fill)
    _element(draw, "point", {axis: _q(value) for axis, value in zip(("x", "y", "z"), point)})
    _element(draw, "size", {axis: _q(value) for axis, value in zip(("x", "y", "z"), size)})


def _slab_geometry(dp: float) -> dict[str, dict[str, list[float]]]:
    """Return three-grid-layer solid slabs external to every frozen face."""

    # The grid is anchored at +dp/2.  A low-face slab has nodes
    # plane-2.5dp, plane-1.5dp, plane-.5dp; a high-face slab has
    # plane+.5dp, plane+1.5dp, plane+2.5dp.  Its endpoint is therefore
    # strictly outside the fluid cell-centre envelope.
    lo = np.asarray(TANK_LOW, dtype=float)
    hi = lo + np.asarray(TANK_SIZE, dtype=float)
    a = 2.5 * dp
    thickness = 2.0 * dp
    tangent_low = lo - a
    tangent_high = hi + a
    return {
        "x_low": {"point": [lo[0] - a, tangent_low[1], tangent_low[2]], "size": [thickness, tangent_high[1] - tangent_low[1], tangent_high[2] - tangent_low[2]]},
        "x_high": {"point": [hi[0] + .5 * dp, tangent_low[1], tangent_low[2]], "size": [thickness, tangent_high[1] - tangent_low[1], tangent_high[2] - tangent_low[2]]},
        "y_low": {"point": [tangent_low[0], lo[1] - a, tangent_low[2]], "size": [tangent_high[0] - tangent_low[0], thickness, tangent_high[2] - tangent_low[2]]},
        "y_high": {"point": [tangent_low[0], hi[1] + .5 * dp, tangent_low[2]], "size": [tangent_high[0] - tangent_low[0], thickness, tangent_high[2] - tangent_low[2]]},
        "z_low": {"point": [tangent_low[0], tangent_low[1], lo[2] - a], "size": [tangent_high[0] - tangent_low[0], tangent_high[1] - tangent_low[1], thickness]},
    }


def _obstacle_slabs(dp: float) -> dict[str, dict[str, list[float]]]:
    lo = np.asarray(OBSTACLE_LOW, dtype=float)
    hi = lo + np.asarray(OBSTACLE_SIZE, dtype=float)
    a = 2.5 * dp
    thickness = 2.0 * dp
    tangent_low = lo - a
    tangent_high = hi + a
    return {
        "x_low": {"point": [lo[0] - a, tangent_low[1], tangent_low[2]], "size": [thickness, tangent_high[1] - tangent_low[1], tangent_high[2] - tangent_low[2]]},
        "x_high": {"point": [hi[0] + .5 * dp, tangent_low[1], tangent_low[2]], "size": [thickness, tangent_high[1] - tangent_low[1], tangent_high[2] - tangent_low[2]]},
        "y_low": {"point": [tangent_low[0], lo[1] - a, tangent_low[2]], "size": [tangent_high[0] - tangent_low[0], thickness, tangent_high[2] - tangent_low[2]]},
        "y_high": {"point": [tangent_low[0], hi[1] + .5 * dp, tangent_low[2]], "size": [tangent_high[0] - tangent_low[0], thickness, tangent_high[2] - tangent_low[2]]},
        "z_high": {"point": [tangent_low[0], tangent_low[1], hi[2] + .5 * dp], "size": [tangent_high[0] - tangent_low[0], tangent_high[1] - tangent_low[1], thickness]},
    }


def _replace_geometry(root: ET.Element, dp: float) -> None:
    definition = root.find("./casedef/geometry/definition")
    commands = root.find("./casedef/geometry/commands")
    if definition is None or commands is None:
        raise ValueError("candidate geometry nodes missing")
    definition.set("dp", _q(dp))
    definition.set("units_comment", "metres (m)")
    pointref = definition.find("pointref")
    if pointref is None:
        pointref = ET.Element("pointref")
        definition.insert(0, pointref)
    pointref.attrib.update({"x": _q(dp / 2), "y": _q(dp / 2), "z": _q(dp / 2)})
    pointmin = definition.find("pointmin")
    pointmax = definition.find("pointmax")
    if pointmin is None or pointmax is None:
        raise ValueError("ECC source point bounds missing")
    pointmin.attrib.update({"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    # The original numerical domain is ample for the three outside support
    # layers and for the obstacle top; retaining it avoids a hidden domain
    # change in this fallback.
    pointmax.attrib.update({"x": "2", "y": "1", "z": "1"})
    mainlist = commands.find("mainlist")
    if mainlist is None:
        raise ValueError("ECC source mainlist missing")
    for child in list(mainlist):
        mainlist.remove(child)
    _element(mainlist, "setshapemode", text="dp | actual | bound")
    _element(mainlist, "setdrawmode", {"mode": "full"})
    _element(mainlist, "setmkbound", {"mk": "0"})
    for name, slab in _slab_geometry(dp).items():
        _drawbox(mainlist, f"thick outer support {name}; external solid layers only", "solid", slab["point"], slab["size"])
    _element(mainlist, "setmkvoid")
    _drawbox(mainlist, "frozen ECC obstacle physical solid; continuous geometry unchanged", "solid", OBSTACLE_LOW, OBSTACLE_SIZE)
    _element(mainlist, "setmkbound", {"mk": "1"})
    for name, slab in _obstacle_slabs(dp).items():
        _drawbox(mainlist, f"thick obstacle support {name}; external solid layers only", "solid", slab["point"], slab["size"])
    _element(mainlist, "setmkfluid", {"mk": "0"})
    _drawbox(mainlist, "exact ECC fluid cell centres; one native particle per dp^3 cell", "solid", [dp / 2] * 3, [FLUID_SIZE[i] - dp for i in range(3)])


def materialize_case(template: Path, output_root: Path) -> dict[str, Any]:
    source = inspect_source(template)
    root = ET.parse(template).getroot()
    _replace_geometry(root, DP_M)
    _set_parameter(root, "SavePosDouble", "1")
    _set_parameter(root, "Boundary", "1")
    if root.find("./casedef/normals") is not None:
        raise ValueError("candidate must remain DBC without normals")
    output_root.mkdir(parents=True, exist_ok=True)
    case_dir = output_root / "definitions" / "F1_ECC_THICK_BOUNDARY_DBC_DP010"
    case_dir.mkdir(parents=True, exist_ok=True)
    definition = case_dir / "F1_ECC_THICK_BOUNDARY_DBC_DP010_Def.xml"
    ET.ElementTree(root).write(definition, encoding="utf-8", xml_declaration=True)
    metadata = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "mechanism_id": MECHANISM_ID,
        "case_id": "F1_ECC_THICK_BOUNDARY_DBC_DP010",
        "physical_case_id": PHYSICAL_CASE_ID,
        "status": "static_recipe_pending_root_review_and_bounded_cpu_gencase",
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "claim_boundary": "Static recipe only until an independently scheduled GenCase/PartVTK/BI4 audit completes; no solver or GPU has run.",
        "source_binding": source,
        "physical_binding": {
            "physical_hash": source["physical_hash"],
            "payload": source["physical_payload"],
            "continuous_fluid_mass_kg": EXPECTED_MASS,
            "mass_normalization": "forbidden",
            "boundary_method": "DBC",
            "normals": False,
        },
        "numeric_binding": {
            "dp_m": DP_M,
            "pointref_m": [DP_M / 2] * 3,
            "pointmin_m": [-2.5 * DP_M] * 3,
            "fluid_primitive": "solid drawbox, point=low+0.5dp, size=extent-dp",
            "outer_support": "five separate solid slabs, three lattice rows external to each closed physical face",
            "obstacle_support": "five separate solid slabs external to four vertical faces and top; obstacle body unchanged",
            "nearest_fixed_offset_m": DP_M / 2,
            "support_layers": SUPPORT_LAYERS,
            "no_vdp": True,
            "save_pos_double": True,
            "boundary_parameter": 1,
            "explicit_default_expansion": "source omitted Boundary and uses official DBC default; candidate writes Boundary=1 explicitly",
        },
        "expected_initial": {
            "counts_xyz": list(EXPECTED_COUNTS),
            "fluid_particles": EXPECTED_FLUID,
            "fluid_mass_kg": EXPECTED_MASS,
            "fluid_center_low_m": [DP_M / 2] * 3,
            "fluid_center_high_m": [FLUID_SIZE[i] - DP_M / 2 for i in range(3)],
            "fluid_id_role": "type=3 downstream; GenCase XML fluid range is authoritative before conversion",
            "fixed_id_role": "GenCase XML fixed ranges plus Idp.bin are authoritative for initial coverage",
        },
        "hard_gates": [
            "official GenCase receipt returncode=0, total/fluid counts and Data2D=0",
            "generated BI4 contains Posd.bin and unique contiguous Idp.bin",
            "generated XML fixed/fluid ranges cover every BI4 Idp exactly once",
            "BI4 fluid count and native mass equal 80400 and 80.4 kg without rescale",
            "fluid centres do not coincide with any fixed position and remain in envelope",
            "typed fixed BI4 positions cover all five finite outer and five obstacle faces",
        ],
        "precedent_evidence": {
            "f1_dual_finite_center": {
                "definition": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261002/finite_center_initialization_001/F1_DUAL_FINITE_CENTER_DP001_003_Def.xml",
                "native_audit": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_DUAL_FINITE_CENTER_DP001_003/finite-center-native-audit-003/finite-center-native-audit.json",
                "observed": {"dimension": 3, "total_particles": 1011911, "fluid_particles": 616000, "fluid_mass_kg": 616.0},
                "role": "pointref/grid-anchor and actual DBC-compatible GenCase/BI4 receipt precedent; ECC geometry is not inherited",
            },
            "f5_solid_cell_center": {
                "definition": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007/runup_return/F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007.xml",
                "actual_gencase_audit": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_010/gencase-audit-010.json",
                "observed": {"dimension": 3, "dp00125_fluid_particles": 1204224, "dp005_fluid_particles": 18816, "solid_cell_center_mass_contract": True},
                "role": "explicit solid fluid drawbox, pointref phase, and finite solid-wall precedent",
            },
        },
        "preserved_negative_evidence": {
            "summary": "/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_solid_cellcenter_fallback_003/evidence/solid-fallback-coarse-stop-summary.json",
            "interpretation": "base solid wall had low-face coverage loss; vdp=0 covered faces but deleted 5754 fluid rows; vdp=-1 still failed. Those bytes remain immutable and this recipe uses no vdp redraw.",
        },
        "definition_path": str(definition.resolve()),
        "definition_sha256": sha256(definition),
    }
    metadata_path = case_dir / "F1_ECC_THICK_BOUNDARY_DBC_DP010.metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    return {
        "case_id": metadata["case_id"],
        "definition": str(definition.resolve()),
        "metadata": str(metadata_path.resolve()),
        "definition_sha256": sha256(definition),
        "metadata_sha256": sha256(metadata_path),
        "physical_hash": source["physical_hash"],
        "expected_fluid_particles": EXPECTED_FLUID,
        "expected_fluid_mass_kg": EXPECTED_MASS,
    }


def _read_binary_vtk_points(path: Path) -> np.ndarray:
    raw = path.read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\r?\n", raw)
    if match is None:
        raise ValueError(f"binary VTK POINTS header missing: {path}")
    count = int(match.group(1))
    end = match.end() + count * 3 * 4
    if end > len(raw):
        raise ValueError(f"truncated VTK points: {path}")
    return np.frombuffer(raw, dtype=">f4", count=count * 3, offset=match.end()).astype(np.float64).reshape(count, 3)


def _summary_number(text: str, pattern: str) -> int | float | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).replace(",", "")
    try:
        return int(value)
    except ValueError:
        return float(value)


def _parse_particle_ranges(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    particles = root.find("./execution/particles")
    if particles is None:
        raise ValueError("generated XML has no execution/particles range")
    total = int(particles.attrib["np"])
    fixed: list[dict[str, Any]] = []
    fluid: list[dict[str, Any]] = []
    for node in particles:
        if node.tag not in {"fixed", "fluid", "moving", "floating"}:
            continue
        row = {
            "role": node.tag,
            "begin": int(node.attrib["begin"]),
            "count": int(node.attrib["count"]),
            "end": int(node.attrib["begin"]) + int(node.attrib["count"]),
            "mk": int(node.attrib.get("mk", "-1")),
        }
        (fluid if node.tag == "fluid" else fixed).append(row)
    constants = root.find("./execution/constants")
    massfluid = None
    if constants is not None:
        node = constants.find("massfluid")
        if node is not None:
            massfluid = float(node.attrib["value"])
    data2d = root.find("./execution/constants/data2d")
    return {
        "total": total,
        "fixed_ranges": fixed,
        "fluid_ranges": fluid,
        "fixed_count": sum(row["count"] for row in fixed),
        "fluid_count": sum(row["count"] for row in fluid),
        "massfluid_kg": massfluid,
        "data2d": None if data2d is None else data2d.attrib.get("value"),
    }


def _decode_double_bi4(bi4: Path, bi4_dump: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="f1-ecc-thick-bi4-") as temp_name:
        temp = Path(temp_name) / "decoded"
        result = subprocess.run([str(bi4_dump), str(bi4), str(temp)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"bi4_dump failed ({result.returncode}): {result.stdout[-1000:]}")
        xml_path = temp.with_suffix(".xml")
        root = ET.parse(xml_path).getroot()
        node = root.find(".//item/item")
        if node is None or "name" not in node.attrib:
            raise ValueError("BI4 decoder XML lacks particle item")
        directory = temp / node.attrib["name"]
        ids_path = directory / "Idp.bin"
        posd_path = directory / "Posd.bin"
        if not ids_path.exists() or not posd_path.exists():
            raise ValueError("double BI4 audit requires Idp.bin and Posd.bin")
        ids = np.fromfile(ids_path, dtype=np.uint32)
        positions = np.fromfile(posd_path, dtype=np.float64)
        if len(positions) != len(ids) * 3:
            raise ValueError("Posd.bin length does not match Idp.bin")
        positions = positions.reshape(len(ids), 3)
        order = np.argsort(ids, kind="stable")
        return ids[order], positions[order], {"decoder_stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(), "array_directory": str(directory), "posd": True}


def _axis_samples(low: float, high: float, dp: float) -> np.ndarray:
    count = int(round((high - low) / dp))
    return np.linspace(low, high, count + 1, dtype=float)


def _face_report(points: np.ndarray, *, name: str, axis: int, plane: float, tangent_low: tuple[float, float], tangent_high: tuple[float, float], dp: float) -> dict[str, Any]:
    tangents = [idx for idx in range(3) if idx != axis]
    values = [_axis_samples(tangent_low[i], tangent_high[i], dp) for i in range(2)]
    aa, bb = np.meshgrid(values[0], values[1], indexing="ij")
    query = np.zeros((aa.size, 3), dtype=float)
    query[:, axis] = plane
    query[:, tangents[0]] = aa.ravel()
    query[:, tangents[1]] = bb.ravel()
    near_all = points[np.abs(points[:, axis] - plane) <= dp / 2 + 2e-6]
    # At corners, an adjacent face slab can also lie within dp/2 of this
    # plane.  Keep a tangential interior band for the orientation check and
    # coverage nearest-neighbour set; the query still includes the physical
    # face edges, which are covered by the slab owning this face.
    tangent_mask = np.ones(len(near_all), dtype=bool)
    for tangent, low, high in zip(tangents, tangent_low, tangent_high):
        tangent_mask &= near_all[:, tangent] >= low + 0.75 * dp - 2e-6
        tangent_mask &= near_all[:, tangent] <= high - 0.75 * dp + 2e-6
    near_interior = near_all[tangent_mask]
    if len(near_all):
        distances = cKDTree(near_all).query(query, workers=1)[0]
    else:
        distances = np.full(len(query), np.inf)
    radius = math.sqrt(3.0) * dp / 2 + 2e-6
    low_face = name.endswith("_low")
    external = (
        near_interior[:, axis] < plane - 1e-7
        if low_face
        else near_interior[:, axis] > plane + 1e-7
    ) if len(near_interior) else np.zeros(0, dtype=bool)
    external_fraction = float(np.mean(external)) if len(external) else 0.0
    # Adjacent slabs can contribute a small number of points at an edge of a
    # physical face.  The owning thick slab must still dominate the interior
    # face band; the 90% threshold makes that attribution explicit.
    oriented = bool(len(external) and external_fraction >= 0.90)
    worst = int(np.argmax(distances)) if len(distances) else 0
    return {
        "name": name,
        "plane_m": plane,
        "near_plane_fixed_points": int(len(near_all)),
        "interior_orientation_points": int(len(near_interior)),
        "external_orientation_fraction": external_fraction,
        "surface_samples": int(len(query)),
        "maximum_distance_m": float(distances[worst]) if len(distances) else None,
        "acceptance_distance_m": radius,
        "uncovered_samples": int(np.count_nonzero(distances > radius)),
        "external_orientation": oriented,
        "worst_sample_m": query[worst].tolist() if len(query) else None,
        "covered": bool(len(query) and np.all(distances <= radius) and oriented),
    }


def finite_face_report(fixed: np.ndarray, dp: float = DP_M) -> dict[str, Any]:
    tank_hi = np.asarray(TANK_LOW) + np.asarray(TANK_SIZE)
    obstacle_hi = np.asarray(OBSTACLE_LOW) + np.asarray(OBSTACLE_SIZE)
    faces = {
        "outer": [
            ("x_low", 0, TANK_LOW[0], (TANK_LOW[1], TANK_LOW[2]), (tank_hi[1], tank_hi[2])),
            ("x_high", 0, tank_hi[0], (TANK_LOW[1], TANK_LOW[2]), (tank_hi[1], tank_hi[2])),
            ("y_low", 1, TANK_LOW[1], (TANK_LOW[0], TANK_LOW[2]), (tank_hi[0], tank_hi[2])),
            ("y_high", 1, tank_hi[1], (TANK_LOW[0], TANK_LOW[2]), (tank_hi[0], tank_hi[2])),
            ("z_low", 2, TANK_LOW[2], (TANK_LOW[0], TANK_LOW[1]), (tank_hi[0], tank_hi[1])),
        ],
        "obstacle": [
            ("x_low", 0, OBSTACLE_LOW[0], (OBSTACLE_LOW[1], OBSTACLE_LOW[2]), (obstacle_hi[1], obstacle_hi[2])),
            ("x_high", 0, obstacle_hi[0], (OBSTACLE_LOW[1], OBSTACLE_LOW[2]), (obstacle_hi[1], obstacle_hi[2])),
            ("y_low", 1, OBSTACLE_LOW[1], (OBSTACLE_LOW[0], OBSTACLE_LOW[2]), (obstacle_hi[0], obstacle_hi[2])),
            ("y_high", 1, obstacle_hi[1], (OBSTACLE_LOW[0], OBSTACLE_LOW[2]), (obstacle_hi[0], obstacle_hi[2])),
            ("z_high", 2, obstacle_hi[2], (OBSTACLE_LOW[0], OBSTACLE_LOW[1]), (obstacle_hi[0], obstacle_hi[1])),
        ],
    }
    result: dict[str, Any] = {}
    for group, specs in faces.items():
        result[group] = {
            name: _face_report(fixed, name=name, axis=axis, plane=float(plane), tangent_low=tuple(tangent_low), tangent_high=tuple(tangent_high), dp=dp)
            for name, axis, plane, tangent_low, tangent_high in specs
        }
    result["all_outer_five_covered"] = all(row["covered"] for row in result["outer"].values())
    result["all_obstacle_five_covered"] = all(row["covered"] for row in result["obstacle"].values())
    return result


def _typed_positions(ids: np.ndarray, positions: np.ndarray, ranges: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if len(ids) == 0 or not np.array_equal(ids, np.arange(len(ids), dtype=np.uint32)):
        raise ValueError("BI4 Idp axis is not unique contiguous zero-based identity")
    fixed_mask = np.zeros(len(ids), dtype=bool)
    fluid_mask = np.zeros(len(ids), dtype=bool)
    for row in ranges["fixed_ranges"]:
        fixed_mask[row["begin"]:row["end"]] = True
    for row in ranges["fluid_ranges"]:
        fluid_mask[row["begin"]:row["end"]] = True
    if np.any(fixed_mask & fluid_mask) or not np.all(fixed_mask | fluid_mask):
        raise ValueError("generated fixed/fluid ranges do not partition Idp")
    typed = {"fixed_id_ranges": ranges["fixed_ranges"], "fluid_id_ranges": ranges["fluid_ranges"], "fixed_count": int(fixed_mask.sum()), "fluid_count": int(fluid_mask.sum())}
    return positions[fixed_mask], positions[fluid_mask], typed


def audit_native(case: dict[str, Any], case_root: Path, bi4_dump: Path) -> dict[str, Any]:
    metadata = json.loads(Path(case["metadata"]).read_text(encoding="utf-8"))
    prefix = case_root / "F1_ECC_THICK_BOUNDARY_DBC_DP010"
    out_path = prefix.with_suffix(".out")
    xml_path = prefix.with_suffix(".xml")
    bi4_path = prefix.with_suffix(".bi4")
    fluid_vtk = prefix.parent / f"{prefix.name}_Fluid.vtk"
    bound_vtk = prefix.parent / f"{prefix.name}_Bound.vtk"
    partvtk_vtk = case_root / "PartVTK_initial.vtk"
    out_text = out_path.read_text(encoding="utf-8", errors="replace")
    ranges = _parse_particle_ranges(xml_path)
    ids, positions, decoder = _decode_double_bi4(bi4_path, bi4_dump)
    fixed, fluid, typed = _typed_positions(ids, positions, ranges)
    fluid_vtk_points = _read_binary_vtk_points(fluid_vtk)
    bound_vtk_points = _read_binary_vtk_points(bound_vtk)
    partvtk_points = _read_binary_vtk_points(partvtk_vtk)
    fluid_low = np.asarray([DP_M / 2] * 3)
    fluid_high = np.asarray([FLUID_SIZE[i] - DP_M / 2 for i in range(3)])
    fluid_finite = bool(np.isfinite(fluid).all())
    fluid_unique = len(np.unique(fluid, axis=0)) == len(fluid)
    fluid_inside = bool(np.all(fluid >= fluid_low - 2e-6) and np.all(fluid <= fluid_high + 2e-6))
    # Position identity equality is checked against the independent official
    # fluid VTK.  Sorting avoids relying on output ordering while retaining
    # every actual BI4 identity for the typed checks above.
    bi4_fluid_sorted = fluid[np.lexsort((fluid[:, 2], fluid[:, 1], fluid[:, 0]))]
    vtk_fluid_sorted = fluid_vtk_points[np.lexsort((fluid_vtk_points[:, 2], fluid_vtk_points[:, 1], fluid_vtk_points[:, 0]))]
    # PartVTK's VTK point block is float32 while the BI4 audit is Posd.bin;
    # keep the comparison below a small fraction of dp but above float32
    # roundoff at the 1.6 m tank scale.
    vtk_equal = len(bi4_fluid_sorted) == len(vtk_fluid_sorted) and bool(np.max(np.abs(bi4_fluid_sorted - vtk_fluid_sorted)) <= max(2e-7, DP_M * 2e-5))
    exact_no_overlap = not bool(cKDTree(fluid).query(fixed, workers=1)[0].min() <= 1e-10) if len(fixed) and len(fluid) else True
    coverage = finite_face_report(fixed)
    data2d = _summary_number(out_text, r"Data2D=\[([01])\]")
    gencase_fluid = _summary_number(out_text, r"Fluid\.+:\s*([0-9,]+)")
    gencase_total = _summary_number(out_text, r"Total particles:\s*([0-9,]+)")
    massfluid = ranges["massfluid_kg"]
    initial_mass = len(fluid) * float(massfluid) if massfluid is not None else None
    checks = {
        "official_3d": data2d == 0 and ranges["data2d"] == "false",
        "official_summary_counts": gencase_fluid == EXPECTED_FLUID and gencase_total == len(ids),
        "double_bi4_positions": bool(decoder["posd"]),
        "idp_unique_contiguous": np.array_equal(ids, np.arange(len(ids), dtype=np.uint32)),
        "generated_ranges_partition_ids": typed["fixed_count"] + typed["fluid_count"] == len(ids),
        "exact_fluid_count": len(fluid) == EXPECTED_FLUID and len(fluid_vtk_points) == EXPECTED_FLUID,
        "native_mass_kg": massfluid is not None and math.isclose(float(initial_mass), EXPECTED_MASS, rel_tol=0, abs_tol=2e-9),
        "fluid_finite_unique": fluid_finite and fluid_unique,
        "fluid_inside_cell_center_envelope": fluid_inside,
        "bi4_fluid_matches_official_fluid_vtk": vtk_equal,
        "fluid_fixed_positions_disjoint": exact_no_overlap,
        "outer_five_face_coverage_from_typed_fixed": coverage["all_outer_five_covered"],
        "obstacle_five_face_coverage_from_typed_fixed": coverage["all_obstacle_five_covered"],
        "official_partvtk_total_points": len(partvtk_points) == len(ids),
        "dbc_without_normals": ET.parse(xml_path).getroot().find("./casedef/normals") is None,
    }
    child_receipt = {
        "schema": "ds02.f1.eccentric-thick-boundary.gencase-child-receipt.v1",
        "case_id": case["case_id"],
        "status": "completed" if checks["official_3d"] and checks["official_summary_counts"] else "completed_with_parse_failure",
        "returncode": 0,
        "solver_dimension_from_gencase": 3 if checks["official_3d"] else None,
        "dimension": 3 if checks["official_3d"] else None,
        "total_particles": gencase_total,
        "fluid_particles": gencase_fluid,
        "fixed_particles": typed["fixed_count"],
        "native_bi4": str(bi4_path.resolve()),
        "native_bi4_sha256": sha256(bi4_path),
        "gencase_out": str(out_path.resolve()),
        "gencase_out_sha256": sha256(out_path),
        "generated_xml_sha256": sha256(xml_path),
        "double_position_array": decoder["posd"],
        "resource_note": "This is the child official GenCase receipt; the parent runner must not infer scientific status from JSON stdout regex.",
    }
    child_path = case_root / "gencase-child-receipt.json"
    child_path.write_text(json.dumps(child_receipt, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    report = {
        "schema": "ds02.f1.eccentric-thick-boundary.native-audit.v1",
        "case_id": case["case_id"],
        "physical_case_id": PHYSICAL_CASE_ID,
        "status": "pass_initial_native_contract" if all(checks.values()) else "failed_initial_native_contract",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "actual": {
            "dimension": 3 if checks["official_3d"] else None,
            "total_particles": len(ids),
            "fluid_particles": len(fluid),
            "fixed_particles": len(fixed),
            "gencase_fluid_summary": gencase_fluid,
            "gencase_total_summary": gencase_total,
            "massfluid_kg": massfluid,
            "initial_fluid_mass_kg": initial_mass,
            "fluid_bounds_m": [fluid.min(axis=0).tolist(), fluid.max(axis=0).tolist()] if len(fluid) else None,
            "fixed_bounds_m": [fixed.min(axis=0).tolist(), fixed.max(axis=0).tolist()] if len(fixed) else None,
            "partvtk_initial_points": len(partvtk_points),
        },
        "typed_identity": typed,
        "coverage_from_actual_double_bi4_fixed_positions": coverage,
        "checks": checks,
        "child_gencase_receipt": str(child_path.resolve()),
        "source_hashes": {name: sha256(path) for name, path in {"out": out_path, "generated_xml": xml_path, "bi4": bi4_path, "fluid_vtk": fluid_vtk, "bound_vtk": bound_vtk, "partvtk_vtk": partvtk_vtk, "metadata": Path(case["metadata"]) }.items()},
        "limitations": [
            "Initial GenCase/PartVTK/BI4 geometry only; no solver, temporal lifecycle, transport, Q-N, or production decision.",
            "Open ECC top remains a free surface; no birth or exit ledger is inferred.",
        ],
    }
    return report


def _usage() -> dict[str, Any]:
    def pack(row: resource.struct_rusage) -> dict[str, Any]:
        return {"user_seconds": row.ru_utime, "system_seconds": row.ru_stime, "max_rss_kib": row.ru_maxrss, "in_block": row.ru_inblock, "out_block": row.ru_oublock, "voluntary_context_switches": row.ru_nvcsw, "involuntary_context_switches": row.ru_nivcsw}
    return {"self": pack(resource.getrusage(resource.RUSAGE_SELF)), "children": pack(resource.getrusage(resource.RUSAGE_CHILDREN))}


def design(output_root: Path = _SCOPE, template: Path = DEFAULT_TEMPLATE) -> dict[str, Any]:
    output_root = output_root.resolve()
    case = materialize_case(template.resolve(), output_root)
    manifest = {
        "schema": "ds02.f1.eccentric-thick-boundary-manifest.v1",
        "family_id": FAMILY_ID,
        "mechanism_id": MECHANISM_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "claim_boundary": "static candidate only; root review required before bounded CPU GenCase",
        "case": case,
        "recipe": {
            "resolution": "dp010",
            "counts_xyz": list(EXPECTED_COUNTS),
            "fluid_particles": EXPECTED_FLUID,
            "fluid_mass_kg": EXPECTED_MASS,
            "closed_outer_faces": list(OUTER_FACES),
            "obstacle_faces": list(OBSTACLE_FACES),
            "support_layers": SUPPORT_LAYERS,
            "support_is_external": True,
            "uses_vdp": False,
        },
        "no_execution_performed": True,
        "q_n_status": "not_assessed",
    }
    path = output_root / "eccentric-thick-boundary-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    manifest["manifest_path"] = str(path.resolve())
    manifest["manifest_sha256"] = sha256(path)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    return manifest


def run_gencase(manifest_path: Path, attempt_root: Path, output_path: Path, gencase: Path, partvtk: Path, bi4_dump: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = manifest["case"]
    attempt_root.mkdir(parents=True, exist_ok=True)
    case_root = attempt_root / case["case_id"]
    case_root.mkdir(parents=True, exist_ok=True)
    prefix = case_root / case["case_id"]
    before = _usage()
    started = time.monotonic()
    gencase_log = case_root / "GenCase.stdout.log"
    command = [str(gencase), str(Path(case["definition"]).with_suffix("")), str(prefix), "-save:all", "-threads:4"]
    with gencase_log.open("wb") as stream:
        gencase_result = subprocess.run(command, cwd=gencase.parent, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if gencase_result.returncode != 0:
        raise RuntimeError(f"official GenCase failed with {gencase_result.returncode}; see {gencase_log}")
    # The child receipt is based on the official .out/XML/BI4, never on the
    # parent runner's stdout parser.  It exists before PartVTK so an outer
    # parser failure cannot erase the actual GenCase facts.
    out_path = prefix.with_suffix(".out")
    xml_path = prefix.with_suffix(".xml")
    ranges = _parse_particle_ranges(xml_path)
    out_text = out_path.read_text(encoding="utf-8", errors="replace")
    child_receipt = {
        "schema": "ds02.f1.eccentric-thick-boundary.gencase-child-receipt.v1",
        "case_id": case["case_id"],
        "status": "completed",
        "returncode": int(gencase_result.returncode),
        "solver_dimension_from_gencase": 3 if _summary_number(out_text, r"Data2D=\[([01])\]") == 0 else 2,
        "dimension": 3 if _summary_number(out_text, r"Data2D=\[([01])\]") == 0 else 2,
        "total_particles": _summary_number(out_text, r"Total particles:\s*([0-9,]+)"),
        "fluid_particles": _summary_number(out_text, r"Fluid\.+:\s*([0-9,]+)"),
        "fixed_particles": ranges["fixed_count"],
        "gencase_out": str(out_path.resolve()),
        "gencase_out_sha256": sha256(out_path),
        "generated_xml_sha256": sha256(xml_path),
        "native_bi4": str(prefix.with_suffix(".bi4").resolve()),
        "native_bi4_sha256": sha256(prefix.with_suffix(".bi4")),
        "resource_note": "Official child receipt; no scientific status is inferred from parent stdout regex.",
    }
    child_path = case_root / "gencase-child-receipt.json"
    child_path.write_text(json.dumps(child_receipt, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    partvtk_path = case_root / "PartVTK_initial.vtk"
    partvtk_log = case_root / "PartVTK.stdout.log"
    partvtk_command = [str(partvtk), "-filedata", str(prefix.with_suffix(".bi4")), "-filexml", str(prefix.with_suffix(".xml")), "-savevtk", str(partvtk_path), "-threads:4"]
    with partvtk_log.open("wb") as stream:
        partvtk_result = subprocess.run(partvtk_command, cwd=partvtk.parent, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if partvtk_result.returncode != 0:
        raise RuntimeError(f"official PartVTK failed with {partvtk_result.returncode}; see {partvtk_log}")
    report = audit_native(case, case_root, bi4_dump)
    report.update({
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256(manifest_path),
        "attempt_root": str(attempt_root.resolve()),
        "official_gencase": str(gencase.resolve()),
        "official_partvtk": str(partvtk.resolve()),
        "elapsed_seconds": time.monotonic() - started,
        "resource_usage": {"before": before, "after": _usage()},
        "child_processes_include_official_gencase_and_partvtk": True,
        "source_bytes_mutated": False,
    })
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
    p_run.add_argument("--bi4-dump", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "design":
        result = design(args.output_root, args.template)
    else:
        result = run_gencase(args.manifest, args.attempt_root, args.output, args.gencase, args.partvtk, args.bi4_dump)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
