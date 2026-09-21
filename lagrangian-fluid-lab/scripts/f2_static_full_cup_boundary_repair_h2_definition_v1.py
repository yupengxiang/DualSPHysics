#!/usr/bin/env python3
"""Materialize the one root-approved F2 static full-cup H2 input.

This writer has one purpose: create a fresh Definition, a fresh zero-angle
motion file, and a small hash receipt for the q=0, dp=0.010 m H2 canary.  It
does not invoke GenCase, the native decoder, a solver, a queue, or any central
state mutation.  The Definition is built from the reviewed literal geometry;
the v4 cell-0 Definition is read only to verify the hash binding in the root
review and is never used as an XML template.

The source-box lower faces are one support clearance above the cup's closed
faces.  In particular, ``c = 3 * hdp * dp`` is applied to x, y, and z.  The
first requested fluid center is therefore ``low + c + dp/2`` on every closed
axis.  The draw extents are tuned to the declared native lattice counts while
remaining inside the continuous H2 source box.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Mapping


LAB = Path(__file__).resolve().parents[1]

PROPOSAL = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-proposal-v1.json"
ROOT_REVIEW = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-root-review-v1.json"
H1_NEGATIVE = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-negative-evidence-v1.json"
SOURCE_DEFINITION = LAB / (
    "campaigns/core-v1/cfd/f2-static-full-cup-matrix-prepared-v4/cells/"
    "00-CORE_F2_static_full_cup_volume_q0p00000000_dp0p010000000000_spatial/"
    "CORE_F2_static_full_cup_volume_q0p00000000_dp0p010000000000_spatial_Def.xml"
)

OUTPUT_DIR = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/input"
CASE_ID = "CORE_F2_static_full_cup_volume_supportclearance_h2_q0p00000000_dp0p010000000000_canary"
REVISION_ID = "F2_static_full_cup_support_clearance_h2_v1"
DEFINITION_NAME = f"{CASE_ID}_Def.xml"
MOTION_NAME = f"{CASE_ID}_motion.dat"
RECEIPT_NAME = "writer-receipt.json"
DEFAULT_INPUT = OUTPUT_DIR
DEFAULT_DEFINITION = OUTPUT_DIR / DEFINITION_NAME
DEFAULT_MOTION = OUTPUT_DIR / MOTION_NAME
DEFAULT_RECEIPT = OUTPUT_DIR / RECEIPT_NAME

Q = 0.0
DP_M = 0.010
HDP = 1.3
CLEARANCE_M = 3.0 * HDP * DP_M
INITIAL_VOLUME_M3 = 0.022950
RHO0 = 1000.0
TIME_MAX_S = 0.6
OUTPUT_INTERVAL_S = 0.02

CUP_LOW = (0.0, -0.15, 0.65)
CUP_SIZE = (0.425, 0.30, 0.45)
RECEIVER_LOW = (0.45, -0.30, 0.0)
RECEIVER_SIZE = (1.10, 0.60, 0.45)
TRAY_LOW = (-0.60, -0.55, -0.20)
TRAY_SIZE = (2.60, 1.10, 0.10)
DOMAIN_LOW = (-0.70, -0.65, -0.40)
DOMAIN_HIGH = (2.20, 0.80, 1.80)

# The continuous box is V / (width * depth).  Its bottom is deliberately
# raised by c, which is the H2 repair.  These values are derived again by
# ``sampling_geometry`` rather than treated as independent inputs.
FLUID_LOW = (
    CUP_LOW[0] + CLEARANCE_M,
    CUP_LOW[1] + CLEARANCE_M,
    CUP_LOW[2] + CLEARANCE_M,
)
FLUID_SIZE = (
    CUP_SIZE[0] - 2.0 * CLEARANCE_M,
    CUP_SIZE[1] - 2.0 * CLEARANCE_M,
    INITIAL_VOLUME_M3 / ((CUP_SIZE[0] - 2.0 * CLEARANCE_M) * (CUP_SIZE[1] - 2.0 * CLEARANCE_M)),
)
FLUID_FIRST_CENTER = tuple(value + DP_M / 2.0 for value in FLUID_LOW)

# The source extents are kept inside the continuous box and chosen to realize
# a mass error below the reviewed 3% preparation gate.  GenCase's solid-box
# endpoint convention gives one point at the first center and one point for
# every dp step in this draw extent.
NATIVE_COUNTS = (35, 22, 30)
FLUID_DRAW_SIZE = tuple((count - 1) * DP_M for count in NATIVE_COUNTS)
NATIVE_PARTICLE_COUNT = NATIVE_COUNTS[0] * NATIVE_COUNTS[1] * NATIVE_COUNTS[2]
NATIVE_MASS_KG = NATIVE_PARTICLE_COUNT * DP_M**3 * RHO0
MASS_ERROR_RELATIVE = NATIVE_MASS_KG / (INITIAL_VOLUME_M3 * RHO0) - 1.0

SCHEMA = "core.f2.static_full_cup.boundary_repair_h2.input_writer_receipt.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(LAB.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": _rel(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _assert_binding(item: Mapping[str, Any], path: Path, label: str) -> None:
    actual = Path(str(item.get("path", "")))
    if not actual.is_absolute():
        actual = LAB / actual
    if actual.resolve() != Path(path).resolve():
        raise ValueError(f"{label} path does not match reviewed input")
    if item.get("sha256") != sha256(path):
        raise ValueError(f"{label} SHA-256 does not match reviewed input")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label} byte count does not match reviewed input")


def _float_text(value: float) -> str:
    return f"{float(value):.17g}"


def _sub(parent: ET.Element, tag: str, attrs: Mapping[str, str] | None = None,
         text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, tag, dict(attrs or {}))
    if text is not None:
        node.text = text
    return node


def _drawbox(parent: ET.Element, fill: str, low: tuple[float, float, float],
             size: tuple[float, float, float], layers: str | None = None) -> ET.Element:
    node = _sub(parent, "drawbox")
    _sub(node, "boxfill", text=fill)
    _sub(node, "point", {axis: _float_text(value) for axis, value in zip("xyz", low)})
    _sub(node, "size", {axis: _float_text(value) for axis, value in zip("xyz", size)})
    if layers is not None:
        _sub(node, "layers", {"vdp": layers})
    return node


def _parameter(parent: ET.Element, key: str, value: str | int | float) -> None:
    _sub(parent, "parameter", {"key": key, "value": str(value)})


def sampling_geometry() -> dict[str, Any]:
    """Return the deterministic continuous and native source-box contract."""
    fluid_high = tuple(low + size for low, size in zip(FLUID_LOW, FLUID_SIZE))
    draw_high = tuple(low + size for low, size in zip(FLUID_FIRST_CENTER, FLUID_DRAW_SIZE))
    if any(value > high + 1.0e-12 for value, high in zip(draw_high, fluid_high)):
        raise ValueError("fresh native draw extent escapes the continuous H2 source box")
    if any(value <= low + CLEARANCE_M - 1.0e-12 for value, low in zip(FLUID_FIRST_CENTER, CUP_LOW)):
        raise ValueError("fresh first fluid center violates support clearance")
    return {
        "continuous_fluid": {
            "low_m": list(FLUID_LOW),
            "size_m": list(FLUID_SIZE),
            "volume_m3": INITIAL_VOLUME_M3,
            "clearance_m": CLEARANCE_M,
            "hdp": HDP,
            "dp_m": DP_M,
            "q": Q,
        },
        "sampling": {
            "first_center_m": list(FLUID_FIRST_CENTER),
            "draw_size_m": list(FLUID_DRAW_SIZE),
            "counts": list(NATIVE_COUNTS),
            "particle_count": NATIVE_PARTICLE_COUNT,
            "native_mass_kg": NATIVE_MASS_KG,
            "mass_error_relative": MASS_ERROR_RELATIVE,
            "inside_continuous_box": True,
            "native_cell_centre_sampling": True,
            "mass_rescaling": False,
        },
    }


def _parse_reviewed_bottom(proposal: Mapping[str, Any]) -> float:
    """Read the reviewed bottom expression and require its c-offset semantics.

    The proposal was initially written with a literal ``0.65`` bottom.  The
    H2 support-clearance contract requires the reviewed proposal to carry the
    corrected ``cup_low_z + c`` value (or an equivalent expression).  Keeping
    this check here prevents a stale proposal from authorizing a zero-clearance
    input.
    """
    rule = proposal.get("hypothesis", {}).get("source_box_rule", {})
    value = rule.get("fluid_bottom_m")
    if value is None:
        value = rule.get("fluid_bottom_rule")
    if isinstance(value, (int, float)):
        bottom = float(value)
    elif isinstance(value, str):
        text = value.strip().lower().replace(" ", "")
        if text.startswith(("cup_low_z+c(dp)", "cup_low_z+c", "0.65+c(dp)", "0.65+c")):
            bottom = CUP_LOW[2] + CLEARANCE_M
        else:
            try:
                bottom = float(value)
            except ValueError as exc:
                raise ValueError("H2 proposal has an unparseable fluid_bottom_m") from exc
    else:
        raise ValueError("H2 proposal has no reviewed fluid_bottom_m")
    if abs(bottom - (CUP_LOW[2] + CLEARANCE_M)) > 1.0e-12:
        raise ValueError("H2 proposal bottom must be cup floor plus c(dp)")
    return bottom


def verify_authorization(
    proposal_path: Path = PROPOSAL,
    root_review_path: Path = ROOT_REVIEW,
    source_definition_path: Path = SOURCE_DEFINITION,
    prior_negative_path: Path = H1_NEGATIVE,
) -> dict[str, Any]:
    """Rehash and validate the exact root-approved one-canary authorization."""
    proposal_path = Path(proposal_path).resolve()
    root_review_path = Path(root_review_path).resolve()
    source_definition_path = Path(source_definition_path).resolve()
    prior_negative_path = Path(prior_negative_path).resolve()
    proposal = _load(proposal_path)
    review = _load(root_review_path)
    if proposal.get("schema") != "core.f2.static_full_cup.boundary_repair_h2_proposal.v1":
        raise ValueError("unexpected H2 proposal schema")
    if proposal.get("status") != "proposal_only_root_review_required":
        raise ValueError("H2 proposal is not the reviewed proposal-only state")
    if proposal.get("scope_id") != "F2_static_full_cup_volume_hold_x_v1":
        raise ValueError("H2 proposal scope changed")
    if proposal.get("repair_id") != "F2_static_full_cup_initial_support_clearance_h2_v1":
        raise ValueError("H2 repair identity changed")
    hypothesis = proposal.get("hypothesis", {})
    if hypothesis.get("class") != "H2_initial_fluid_support_clearance":
        raise ValueError("H2 hypothesis class changed")
    if hypothesis.get("continuous_cup_geometry_unchanged") is not True:
        raise ValueError("H2 must retain continuous cup geometry")
    if hypothesis.get("hdp") != HDP or hypothesis.get("clearance_rule") != "c(dp)=3*hdp*dp":
        raise ValueError("H2 support-clearance rule changed")
    boundary = str(hypothesis.get("boundary_formulation", ""))
    if "Boundary=2" not in boundary or "explicit" not in boundary.lower():
        raise ValueError("H2 boundary contract must retain Boundary=2 explicit normals")
    identity = hypothesis.get("fresh_identity", {})
    if identity.get("revision_id") != REVISION_ID:
        raise ValueError("H2 revision identity changed")
    if identity.get("old_definition_reused") is not False or identity.get("old_trajectory_reused") is not False:
        raise ValueError("H2 proposal permits reuse of old inputs")
    if not proposal.get("qualification_claim", "").startswith("none;"):
        raise ValueError("H2 proposal carries a qualification claim")
    if proposal.get("qualified") is not False or proposal.get("T1_numerical") is not False:
        raise ValueError("H2 proposal qualification boundary changed")
    if proposal.get("matrix_credit") != 0 or proposal.get("authorization", {}).get("qualification_credit") != 0:
        raise ValueError("H2 proposal carries qualification credit")
    denominator = proposal.get("fixed_failure_denominator", {})
    if denominator.get("planned") != 15 or denominator.get("survivor_renormalization") is not False:
        raise ValueError("H2 proposal changed the fixed 15-row denominator")
    _parse_reviewed_bottom(proposal)

    if review.get("schema") != "core.f2.static_full_cup.boundary_repair_h2.root_review.v1":
        raise ValueError("unexpected H2 root-review schema")
    if review.get("status") != "approved_for_one_fresh_cpu_native_preflight":
        raise ValueError("H2 root review does not authorize the fresh preflight")
    if not str(review.get("qualification_claim", "")).startswith("none;"):
        raise ValueError("H2 root review carries a qualification claim")
    if review.get("scope_id") != proposal.get("scope_id") or review.get("repair_id") != proposal.get("repair_id"):
        raise ValueError("H2 root review identity does not match proposal")
    _assert_binding(review.get("proposal", {}), proposal_path, "root-review proposal")
    _assert_binding(review.get("source_definition", {}), source_definition_path, "root-review source Definition")
    _assert_binding(review.get("prior_negative", {}), prior_negative_path, "root-review prior negative")
    decision = review.get("decision", {})
    # The current root-review field is ``continuous_fit_screen_passed``.  Keep
    # this explicit to reject a review with a renamed/loosened gate.
    if decision.get("proposal_hash_reviewed") is not True or decision.get("continuous_fit_screen_passed") is not True:
        raise ValueError("H2 root review has not passed the static fit review")
    if decision.get("fresh_definition_write_allowed") is not True:
        raise ValueError("H2 root review does not allow Definition writing")
    if decision.get("cpu_gencase_allowed") is not True or decision.get("native_decode_allowed") is not True:
        raise ValueError("H2 root review CPU/native scope changed")
    for key in ("solver_allowed", "gpu_allowed", "job_spec_creation_allowed"):
        if decision.get(key) is not False:
            raise ValueError(f"H2 root review opened forbidden action: {key}")
    if decision.get("matrix_submission") is not False:
        raise ValueError("H2 root review opened matrix submission")
    for key in ("queue_mutation_allowed", "ledger_mutation_allowed", "registry_mutation_allowed", "qualification_credit"):
        if decision.get(key) != 0:
            raise ValueError(f"H2 root review opened protected state: {key}")
    if "q=0.0" not in str(decision.get("scope", "")) or "dp=0.010" not in str(decision.get("scope", "")):
        raise ValueError("H2 root review scope is not the q=0, dp=.010 canary")
    input_identity = review.get("input_identity", {})
    if input_identity.get("case_id") != CASE_ID or input_identity.get("revision_id") != REVISION_ID:
        raise ValueError("H2 root-review fresh case/revision identity changed")
    if input_identity.get("old_definition_reused") is not False or input_identity.get("old_trajectory_reused") is not False:
        raise ValueError("H2 root review permits old Definition/trajectory reuse")
    execution = review.get("execution_controls", {})
    if execution.get("read_only_review") is not True:
        raise ValueError("H2 root review must remain read-only")
    for key in ("definition_writer_now", "gencase_now", "native_decode_now", "solver_now", "gpu_launch_now"):
        if execution.get(key) is not False:
            raise ValueError(f"H2 root review records an immediate action: {key}")
    for key in ("queue_mutation_now", "ledger_mutation_now", "registry_mutation_now"):
        if execution.get(key) != 0:
            raise ValueError(f"H2 root review records protected-state mutation: {key}")
    gates = review.get("hard_gates", {})
    if gates.get("fresh_xml_and_bi4_required") is not True or not gates.get("fluid_support_clearance"):
        raise ValueError("H2 root review omitted fresh-input/support gates")
    if float(gates.get("mass_relative_error_max", float("nan"))) < abs(MASS_ERROR_RELATIVE):
        raise ValueError("H2 deterministic lattice exceeds reviewed mass gate")
    return {
        "proposal": proposal,
        "root_review": review,
        "refs": {
            "proposal": _ref(proposal_path, "H2 proposal contract"),
            "root_review": _ref(root_review_path, "H2 root review authorization"),
            "source_definition": _ref(source_definition_path, "reviewed v4 cell-0 Definition template (read-only provenance)"),
            "prior_negative": _ref(prior_negative_path, "immutable H1 negative evidence"),
        },
    }


def write_motion(target: Path) -> dict[str, Any]:
    """Write deterministic zero-angle motion for the new case identity."""
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = ["#Time;Degrees"]
    count = int(round(TIME_MAX_S / OUTPUT_INTERVAL_S))
    for index in range(count + 1):
        rows.append(f"{index * OUTPUT_INTERVAL_S:.6f};0.000000000")
    payload = "\n".join(rows) + "\n"
    target.write_text(payload, encoding="utf-8")
    return {"path": _rel(target), "sha256": sha256(target), "bytes": target.stat().st_size, "role": "fresh H2 zero-angle motion"}


def write_definition(target: Path = OUTPUT_DIR / DEFINITION_NAME,
                     motion_name: str = MOTION_NAME) -> dict[str, Any]:
    """Write a fresh literal H2 Definition without copying the old XML."""
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("case")
    casedef = _sub(root, "casedef")
    constants = _sub(casedef, "constantsdef")
    _sub(constants, "gravity", {"x": "0", "y": "0", "z": "-9.81"})
    _sub(constants, "rhop0", {"value": "1000"})
    _sub(constants, "rhopgradient", {"value": "2"})
    _sub(constants, "hswl", {"value": "0", "auto": "true"})
    _sub(constants, "gamma", {"value": "7"})
    _sub(constants, "speedsystem", {"value": "0", "auto": "true"})
    _sub(constants, "coefsound", {"value": "25"})
    _sub(constants, "speedsound", {"value": "0", "auto": "true"})
    _sub(constants, "hdp", {"value": _float_text(HDP)})
    _sub(constants, "cflnumber", {"value": "0.2"})
    _sub(casedef, "mkconfig", {"boundcount": "220", "fluidcount": "16"})

    geometry = _sub(casedef, "geometry")
    definition = _sub(geometry, "definition", {"dp": _float_text(DP_M)})
    _sub(definition, "pointmin", {axis: _float_text(value) for axis, value in zip("xyz", (-0.80, -0.70, -0.45))})
    _sub(definition, "pointmax", {axis: _float_text(value) for axis, value in zip("xyz", (2.30, 0.90, 1.80))})
    commands = _sub(geometry, "commands")

    normal_list = _sub(commands, "list", {"name": "GeometryForNormals"})
    _sub(normal_list, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    _sub(normal_list, "setshapemode", text="actual | bound")
    _sub(normal_list, "setnormalinvert", {"invert": "true"})
    _sub(normal_list, "setmkbound", {"mk": "0"})
    _drawbox(normal_list, "bottom | left | right | front | back", CUP_LOW, CUP_SIZE, "-0.5")
    _sub(normal_list, "setmkbound", {"mk": "1"})
    _drawbox(normal_list, "bottom | left | right | front | back", RECEIVER_LOW, RECEIVER_SIZE, "-0.5")
    _sub(normal_list, "setmkbound", {"mk": "2"})
    _drawbox(normal_list, "bottom", TRAY_LOW, TRAY_SIZE, "-0.5")
    _sub(normal_list, "shapeout", {"file": "hdp"})
    _sub(normal_list, "resetdraw")

    main = _sub(commands, "mainlist")
    _sub(main, "runlist", {"name": "GeometryForNormals"})
    _sub(main, "setshapemode", text="dp | bound")
    _sub(main, "setdrawmode", {"mode": "full"})
    _sub(main, "setmkbound", {"mk": "0"})
    _drawbox(main, "bottom | left | right | front | back", CUP_LOW, CUP_SIZE, "0,1,2")
    _sub(main, "setmkbound", {"mk": "1"})
    _drawbox(main, "bottom | left | right | front | back", RECEIVER_LOW, RECEIVER_SIZE, "0,1,2")
    _sub(main, "setmkbound", {"mk": "2"})
    _drawbox(main, "bottom", TRAY_LOW, TRAY_SIZE, "0,1,2")
    _sub(main, "setmkfluid", {"mk": "0"})
    _drawbox(main, "solid", FLUID_FIRST_CENTER, FLUID_DRAW_SIZE)

    normals = _sub(casedef, "normals", {"active": "true"})
    norgeometry = _sub(normals, "norgeometry")
    _sub(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    _sub(norgeometry, "distanceh", {"v": "3.0"})
    _sub(norgeometry, "svshapes", {"v": "true"})

    motion = _sub(casedef, "motion")
    objreal = _sub(motion, "objreal", {"ref": "0"})
    _sub(objreal, "begin", {"mov": "1", "start": "0", "finish": _float_text(TIME_MAX_S)})
    mvrotfile = _sub(objreal, "mvrotfile", {"id": "1", "duration": _float_text(TIME_MAX_S), "anglesunits": "degrees"})
    _sub(mvrotfile, "file", {"name": motion_name})
    _sub(mvrotfile, "axisp1", {"x": "0", "y": "-1", "z": "0.65"})
    _sub(mvrotfile, "axisp2", {"x": "0", "y": "1", "z": "0.65"})

    execution = _sub(root, "execution")
    parameters = _sub(execution, "parameters")
    for key, value in (
        ("SavePosDouble", 2), ("Boundary", 2), ("SlipMode", 1), ("StepAlgorithm", 2),
        ("Kernel", 2), ("ViscoTreatment", 1), ("Visco", "0.03"), ("ViscoBoundFactor", 1),
        ("DensityDT", 3), ("DensityDTvalue", "0.1"), ("Shifting", 0), ("RigidAlgorithm", 1),
        ("FtPause", 0), ("CoefDtMin", "0.05"), ("DtIni", 0), ("DtMin", 0),
        ("DtFixed", 0), ("DtAllParticles", 0), ("TimeMax", _float_text(TIME_MAX_S)),
        ("TimeOut", _float_text(OUTPUT_INTERVAL_S)), ("PartsOutMax", 1), ("RhopOutMin", 700),
        ("RhopOutMax", 1300), ("MinFluidStop", 0),
    ):
        _parameter(parameters, key, value)
    domain = _sub(parameters, "simulationdomain")
    _sub(domain, "posmin", {axis: _float_text(value) for axis, value in zip("xyz", DOMAIN_LOW)})
    _sub(domain, "posmax", {axis: _float_text(value) for axis, value in zip("xyz", DOMAIN_HIGH)})

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return {"path": _rel(target), "sha256": sha256(target), "bytes": target.stat().st_size, "role": "fresh H2 Definition"}


def inspect_definition(path: Path) -> dict[str, Any]:
    """Audit the exact fresh XML geometry/boundary contract."""
    path = Path(path).resolve()
    root = ET.parse(path).getroot()
    if root.tag != "case":
        raise ValueError("fresh H2 Definition root must be <case>")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or float(definition.get("dp", "nan")) != DP_M:
        raise ValueError("fresh H2 Definition dp mismatch")
    commands = root.find("./casedef/geometry/commands")
    normal_list = commands.find("list[@name='GeometryForNormals']") if commands is not None else None
    main = commands.find("mainlist") if commands is not None else None
    if normal_list is None or main is None:
        raise ValueError("fresh H2 Definition is missing explicit normal/main lists")
    normals = root.find("./casedef/normals")
    norgeometry = normals.find("norgeometry") if normals is not None else None
    if normals is None or normals.get("active") != "true" or norgeometry is None:
        raise ValueError("fresh H2 explicit normals are inactive")
    if norgeometry.find("geometryfile").get("file") != "[CaseName]_hdp_Actual.vtk":
        raise ValueError("fresh H2 geometry-normal file contract changed")
    if norgeometry.find("distanceh").get("v") != "3.0":
        raise ValueError("fresh H2 geometry-normal distance changed")
    source = main.findall("drawbox")[-1]
    point = source.find("point")
    size = source.find("size")
    expected = sampling_geometry()
    actual_first = [float(point.get(axis)) for axis in "xyz"]
    actual_size = [float(size.get(axis)) for axis in "xyz"]
    if any(abs(a - b) > 1.0e-12 for a, b in zip(actual_first, expected["sampling"]["first_center_m"])):
        raise ValueError("fresh H2 source first center changed")
    if any(abs(a - b) > 1.0e-12 for a, b in zip(actual_size, expected["sampling"]["draw_size_m"])):
        raise ValueError("fresh H2 source draw extent changed")
    params = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    if params.get("Boundary") != "2":
        raise ValueError("fresh H2 Definition must use Boundary=2")
    return {
        "definition": _ref(path, "fresh H2 Definition"),
        "boundary": {"Boundary": 2, "explicit_normals": True, "geometry_normals_distanceh": 3.0},
        "source_first_center_m": actual_first,
        "source_draw_size_m": actual_size,
        "runtime_invoked": False,
    }


def write_inputs(
    output_dir: Path = OUTPUT_DIR,
    *,
    proposal_path: Path = PROPOSAL,
    root_review_path: Path = ROOT_REVIEW,
    source_definition_path: Path = SOURCE_DEFINITION,
    prior_negative_path: Path = H1_NEGATIVE,
) -> dict[str, Any]:
    """Write the fresh input pair and compact receipt for preflight callers."""
    output_dir = Path(output_dir).resolve()
    auth = verify_authorization(proposal_path, root_review_path, source_definition_path, prior_negative_path)
    expected = sampling_geometry()
    output_dir.mkdir(parents=True, exist_ok=True)
    definition_path = output_dir / DEFINITION_NAME
    motion_path = output_dir / MOTION_NAME
    definition = write_definition(definition_path, MOTION_NAME)
    motion = write_motion(motion_path)
    inspection = inspect_definition(definition_path)
    if Path(definition_path).resolve() == Path(source_definition_path).resolve():
        raise ValueError("fresh H2 Definition path aliases the v4 source Definition")
    if definition["sha256"] == sha256(source_definition_path):
        raise ValueError("fresh H2 Definition is byte-identical to the v4 source Definition")
    receipt = {
        "schema": SCHEMA,
        "status": "fresh_inputs_written_preflight_pending",
        "family": "F2",
        "scope_id": "F2_static_full_cup_volume_hold_x_v1",
        "repair_id": "F2_static_full_cup_initial_support_clearance_h2_v1",
        "case_id": CASE_ID,
        "revision_id": REVISION_ID,
        "q": Q,
        "dp_m": DP_M,
        "definition": definition,
        "motion": motion,
        "source_template_sha256": sha256(source_definition_path),
        **expected,
        "boundary": {
            "Boundary": 2,
            "explicit_normals": True,
            "geometry_normals_distanceh": 3.0,
            "solver_mdbc_noslip_argument": "-mdbc_noslip:1",
        },
        "fresh_identity": {
            "case_id": CASE_ID,
            "revision_id": REVISION_ID,
            "old_definition_reused": False,
            "old_trajectory_reused": False,
            "old_generated_bi4_reused": False,
            "output_directory": _rel(output_dir),
        },
        "authorization": {
            "root_review": auth["refs"]["root_review"],
            "proposal": auth["refs"]["proposal"],
            "prior_negative": auth["refs"]["prior_negative"],
            "source_definition_provenance": auth["refs"]["source_definition"],
            "definition_writer_invoked": True,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_credit": 0,
        },
        "checks": {
            "support_clearance_applied_to_x_y_z": True,
            "continuous_top_below_cup_top": FLUID_LOW[2] + FLUID_SIZE[2] < CUP_LOW[2] + CUP_SIZE[2],
            "native_mass_relative_error_within_0p03": abs(MASS_ERROR_RELATIVE) <= 0.03,
            "fresh_xml_not_source_template": True,
            "fresh_motion_not_old_trajectory": True,
        },
        "implementation": _ref(Path(__file__), "H2 Definition writer"),
    }
    receipt_path = output_dir / RECEIPT_NAME
    partial = receipt_path.with_suffix(receipt_path.suffix + ".partial")
    partial.write_text(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(receipt_path)
    receipt["receipt"] = {"path": _rel(receipt_path), "sha256": sha256(receipt_path), "bytes": receipt_path.stat().st_size, "role": "compact H2 input hash receipt"}
    # The receipt self-reference is deliberately omitted from the file to keep
    # its digest stable; callers receive it in the returned value.
    receipt.pop("receipt")
    receipt["inspection"] = inspection
    return receipt


# ``build`` is the small preflight-friendly entry point used by other input
# materializers in this repository.  Keep ``write_inputs`` as the descriptive
# API while exposing the conventional alias for callers that only need one
# deterministic build operation.
def build(output_dir: Path = OUTPUT_DIR, **kwargs: Any) -> dict[str, Any]:
    return write_inputs(output_dir, **kwargs)


def verify_receipt(path: Path) -> dict[str, Any]:
    """Verify a materialized receipt and its two fresh input hashes."""
    path = Path(path).resolve()
    value = _load(path)
    if value.get("schema") != SCHEMA or value.get("status") != "fresh_inputs_written_preflight_pending":
        raise ValueError("unexpected H2 writer receipt")
    if value.get("case_id") != CASE_ID or value.get("revision_id") != REVISION_ID:
        raise ValueError("H2 receipt identity changed")
    for key in ("definition", "motion"):
        item = value.get(key, {})
        input_path = Path(str(item.get("path", "")))
        if not input_path.is_absolute():
            input_path = LAB / input_path
        _assert_binding(item, input_path, f"receipt {key}")
    if value.get("source_template_sha256") == value.get("definition", {}).get("sha256"):
        raise ValueError("H2 receipt reuses source Definition bytes")
    if value.get("boundary") != {
        "Boundary": 2,
        "explicit_normals": True,
        "geometry_normals_distanceh": 3.0,
        "solver_mdbc_noslip_argument": "-mdbc_noslip:1",
    }:
        raise ValueError("H2 receipt boundary contract changed")
    if value.get("fresh_identity", {}).get("old_definition_reused") is not False or value.get("fresh_identity", {}).get("old_trajectory_reused") is not False:
        raise ValueError("H2 receipt permits old identity reuse")
    authorization = value.get("authorization", {})
    for key in ("gencase_invoked", "native_decode_invoked", "solver_invoked", "gpu_started"):
        if authorization.get(key) is not False:
            raise ValueError(f"H2 receipt records forbidden execution: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "qualification_credit"):
        if authorization.get(key) != 0:
            raise ValueError(f"H2 receipt records protected-state mutation: {key}")
    inspect_definition(Path(str(value["definition"]["path"])))
    return {"ok": True, "receipt": _rel(path), "definition_sha256": value["definition"]["sha256"], "motion_sha256": value["motion"]["sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "verify"), nargs="?", default="write")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--receipt", type=Path, default=OUTPUT_DIR / RECEIPT_NAME)
    args = parser.parse_args()
    if args.command == "write":
        value = write_inputs(args.output_dir)
        print(json.dumps({"status": value["status"], "output_dir": _rel(args.output_dir), "case_id": CASE_ID}, ensure_ascii=False))
        return 0
    result = verify_receipt(args.receipt)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
