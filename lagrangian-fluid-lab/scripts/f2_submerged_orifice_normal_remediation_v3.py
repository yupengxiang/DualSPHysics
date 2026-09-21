#!/usr/bin/env python3
"""Prepare a new, root-review-only submerged-orifice remediation candidate.

The v3 candidate is based on a read-only audit of the materialized v4
``Bound.vtk`` failure.  It writes a new literal Definition and static
hash-bound candidate/contract, but it has no GenCase, native decoder, solver,
GPU, job, queue, ledger, registry, or matrix submission path.  The new
Definition is never read from an earlier Definition and no native input is
created here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping
import xml.etree.ElementTree as ET

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.f2_submerged_orifice_scope_v1 import (  # noqa: E402
    DEFAULT_BASE,
    EXPECTED_ROWS,
    SCOPE_ID,
    load_json,
    verify_bundle,
)


SCHEMA_CANDIDATE = (
    "core.f2.submerged_orifice_transfer.normal_remediation_candidate.v3"
)
SCHEMA_CONTRACT = (
    "core.f2.submerged_orifice_transfer.normal_remediation.root_review_only.v3"
)
REVISION_ID = "F2_submerged_orifice_normal_remediation_v3"
CANDIDATE_ID = "F2_submerged_orifice_normalremediation_q0p5_closed_lattice_v3"
CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3"
PARENT_V4_CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2"
CREATED_AT = "2026-09-21T00:00:00+00:00"
Q = 0.5
DP_M = 0.0075
ORIFICE_HEIGHT_M = 0.18
ZERO_NORMAL_TOLERANCE_M = 1.0e-12
MASS_RELATIVE_ERROR_MAX = 0.025
CONTINUOUS_SOURCE_VOLUME_M3 = 0.64 * 0.42 * 0.36
SOURCE_DENSITY_KG_M3 = 1000.0
PARTICLE_MASS_KG = SOURCE_DENSITY_KG_M3 * DP_M**3
SOURCE_LATTICE_COUNTS = (86, 56, 48)
SOURCE_LATTICE_PARTICLES = math.prod(SOURCE_LATTICE_COUNTS)
SOURCE_TARGET_MASS_KG = SOURCE_LATTICE_PARTICLES * PARTICLE_MASS_KG
SOURCE_TARGET_RELATIVE_ERROR = (
    SOURCE_TARGET_MASS_KG / (CONTINUOUS_SOURCE_VOLUME_M3 * SOURCE_DENSITY_KG_M3)
    - 1.0
)

OUTER_LOW = [0.0, 0.0, 0.0]
OUTER_SIZE = [1.6, 0.5, 0.8]
GATE_LOW = [0.72, 0.04, 0.18]
GATE_SIZE = [0.06, 0.42, 0.62]
GATE_VOID_LOW = [0.71625, 0.03625, 0.17625]
GATE_VOID_SIZE = [0.0675, 0.4275, 0.6275]
GATE_BOUND_LOW = [0.72375, 0.04375, 0.18375]
GATE_BOUND_SIZE = [0.0525, 0.4125, 0.6125]
SOURCE_FIRST_CENTER = [0.04125, 0.04125, 0.04125]
# GenCase drawbox extents are made count-closed for the static recipe.  The
# expected lattice is an assertion for the future preflight, not an observed
# generated result.
SOURCE_DRAW_SIZE = [0.63, 0.405, 0.345]

DEFAULT_REMEDIATION = DEFAULT_BASE / "normal-remediation-v3"
DEFAULT_DEFINITION = (
    DEFAULT_REMEDIATION
    / "fresh-definition-v3"
    / f"{CASE_ID}_Def.xml"
)
DEFAULT_AUDIT = DEFAULT_REMEDIATION / "v4-boundnor-failure-audit-v1.json"
DEFAULT_PREFLIGHT = (
    DEFAULT_BASE / "normal-remediation-v2/preflight-v4/preflight.json"
)
DEFAULT_CANDIDATE = DEFAULT_REMEDIATION / "normal-remediation-candidate-v3.json"
DEFAULT_CONTRACT = DEFAULT_REMEDIATION / "root-review-only-contract-v3.json"
DEFAULT_OUTPUT_PREFIX = DEFAULT_REMEDIATION / "preflight-v3" / CASE_ID
DEFAULT_REPORT = (
    LAB_ROOT / "reports/F2-SUBMERGED-ORIFICE-NORMAL-REMEDIATION-V3-ROOT-REVIEW-2026-09-21.zh-CN.md"
)
AUDIT_ADAPTER = LAB_ROOT / "scripts/f2_submerged_orifice_v4_failure_audit_v1.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def verify_ref(
    item: Mapping[str, Any],
    label: str,
    expected_path: Path | None = None,
) -> Path:
    value = item.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: path missing")
    path = Path(value).resolve()
    if expected_path is not None and path != Path(expected_path).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path):
        raise ValueError(f"{label}: SHA-256 mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: byte count mismatch")
    return path


def _sub(
    parent: ET.Element,
    tag: str,
    attrs: dict[str, str] | None = None,
    text: str | None = None,
) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs or {})
    if text is not None:
        node.text = text
    return node


def _drawbox(
    parent: ET.Element,
    fill: str,
    low: list[float],
    size: list[float],
    layers: str | None = None,
) -> ET.Element:
    node = _sub(parent, "drawbox")
    _sub(node, "boxfill", text=fill)
    _sub(
        node,
        "point",
        {axis: f"{value:.17g}" for axis, value in zip("xyz", low)},
    )
    _sub(
        node,
        "size",
        {axis: f"{value:.17g}" for axis, value in zip("xyz", size)},
    )
    if layers is not None:
        _sub(node, "layers", {"vdp": layers})
    return node


def _parameter(parent: ET.Element, key: str, value: str) -> None:
    _sub(parent, "parameter", {"key": key, "value": value})


def write_definition(target: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    """Write a fresh v3 literal Definition without reading earlier XML."""
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f"fresh v3 Definition path already exists: {target}")
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
    _sub(constants, "coefsound", {"value": "20"})
    _sub(constants, "speedsound", {"value": "0", "auto": "true"})
    _sub(constants, "coefh", {"value": "1.0"})
    _sub(constants, "cflnumber", {"value": "0.2"})
    _sub(casedef, "mkconfig", {"boundcount": "220", "fluidcount": "16"})

    geometry = _sub(casedef, "geometry")
    definition = _sub(geometry, "definition", {"dp": f"{DP_M:.17g}"})
    _sub(definition, "pointmin", {"x": "-0.30", "y": "-0.15", "z": "-0.15"})
    _sub(definition, "pointmax", {"x": "1.90", "y": "0.65", "z": "1.20"})
    _sub(definition, "pointref", {axis: f"{DP_M / 2.0:.17g}" for axis in "xyz"})
    commands = _sub(geometry, "commands")

    normals_list = _sub(commands, "list", {"name": "GeometryForNormals"})
    _sub(normals_list, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    _sub(normals_list, "setshapemode", text="actual | bound")
    _sub(normals_list, "setnormalinvert", {"invert": "true"})
    _sub(normals_list, "setmkbound", {"mk": "0"})
    # Explicitly mirror the five closed outer faces and all active boundary
    # shell layers.  This is the one v3 geometry/normal closure hypothesis.
    _drawbox(
        normals_list,
        "bottom | left | right | front | back",
        OUTER_LOW,
        OUTER_SIZE,
        "0,1,2",
    )
    _sub(normals_list, "setmkbound", {"mk": "1"})
    _sub(normals_list, "setnormalinvert", {"invert": "false"})
    _drawbox(
        normals_list,
        "bottom | top | left | right | front | back",
        GATE_LOW,
        GATE_SIZE,
        "0,-1,-2",
    )
    _sub(normals_list, "shapeout", {"file": "hdp"})
    _sub(normals_list, "resetdraw")

    main = _sub(commands, "mainlist")
    _sub(main, "runlist", {"name": "GeometryForNormals"})
    _sub(main, "setshapemode", text="actual | bound")
    _sub(main, "setdrawmode", {"mode": "full"})
    _sub(main, "setmkbound", {"mk": "0"})
    _drawbox(main, "bottom | left | right | front | back", OUTER_LOW, OUTER_SIZE, "0,1,2")
    _sub(main, "setmkvoid")
    _drawbox(main, "solid", GATE_VOID_LOW, GATE_VOID_SIZE)
    _sub(main, "setmkbound", {"mk": "1"})
    _drawbox(
        main,
        "bottom | top | left | right | front | back",
        GATE_BOUND_LOW,
        GATE_BOUND_SIZE,
        "0,-1,-2",
    )
    _sub(main, "setmkfluid", {"mk": "0"})
    _drawbox(main, "solid", SOURCE_FIRST_CENTER, SOURCE_DRAW_SIZE)

    normals = _sub(casedef, "normals", {"active": "true"})
    norgeometry = _sub(normals, "norgeometry")
    _sub(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    _sub(norgeometry, "distanceh", {"v": "3.0"})
    _sub(norgeometry, "svshapes", {"v": "true"})

    execution = _sub(root, "execution")
    parameters = _sub(execution, "parameters")
    values = (
        ("SavePosDouble", "2"), ("Boundary", "2"), ("SlipMode", "1"),
        ("StepAlgorithm", "2"), ("Kernel", "2"), ("ViscoTreatment", "1"),
        ("Visco", "0.03"), ("ViscoBoundFactor", "1"), ("DensityDT", "3"),
        ("DensityDTvalue", "0.1"), ("Shifting", "0"), ("RigidAlgorithm", "1"),
        ("FtPause", "0"), ("CoefDtMin", "0.05"), ("DtIni", "0"),
        ("DtMin", "0"), ("DtFixed", "0"), ("DtAllParticles", "0"),
        ("TimeMax", "1.5"), ("TimeOut", "0.01"), ("PartsOutMax", "1"),
        ("RhopOutMin", "700"), ("RhopOutMax", "1300"), ("MinFluidStop", "0"),
        ("NoPenetration", "1"),
    )
    for key, value in values:
        _parameter(parameters, key, value)
    domain = _sub(parameters, "simulationdomain")
    _sub(domain, "posmin", {"x": "-0.30", "y": "-0.15", "z": "-0.15"})
    _sub(domain, "posmax", {"x": "1.90", "y": "0.65", "z": "1.20"})

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "bytes": target.stat().st_size,
        "case_id": CASE_ID,
        "writer_runtime_invoked": False,
    }


def _attrs(node: ET.Element, *keys: str) -> tuple[float, ...]:
    try:
        return tuple(float(node.get(key, "nan")) for key in keys)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid Definition attributes on {node.tag}") from exc


def _source_lattice_contract(low: tuple[float, ...], size: tuple[float, ...]) -> dict[str, Any]:
    if any(not math.isfinite(value) for value in (*low, *size)):
        raise ValueError("source lattice attributes are not finite")
    counts = tuple(int(value) for value in SOURCE_LATTICE_COUNTS)
    expected_last = tuple(
        low[axis] + (counts[axis] - 1) * DP_M for axis in range(3)
    )
    return {
        "first_center_m": list(low),
        "draw_size_m": list(size),
        "expected_counts_xyz": list(counts),
        "expected_particle_count": SOURCE_LATTICE_PARTICLES,
        "expected_last_center_m": list(expected_last),
        "particle_mass_kg": PARTICLE_MASS_KG,
        "target_discrete_mass_kg": SOURCE_TARGET_MASS_KG,
        "target_relative_error": SOURCE_TARGET_RELATIVE_ERROR,
        "count_prediction_is_unexecuted": True,
    }


def inspect_definition(path: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    """Statically audit the new literal XML recipe."""
    path = Path(path).resolve()
    root = ET.parse(path).getroot()
    if root.tag != "case":
        raise ValueError("v3 Definition root must be <case>")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or not math.isclose(
        float(definition.get("dp", "nan")), DP_M, rel_tol=0.0, abs_tol=1.0e-15
    ):
        raise ValueError("v3 Definition dp mismatch")
    commands = root.find("./casedef/geometry/commands")
    normal_list = commands.find("list[@name='GeometryForNormals']") if commands is not None else None
    main = commands.find("mainlist") if commands is not None else None
    if normal_list is None or main is None:
        raise ValueError("v3 Definition normal/main lists missing")
    normal_boxes = normal_list.findall("drawbox")
    normal_fills = [(box.findtext("boxfill") or "").strip() for box in normal_boxes]
    normal_layers = [box.find("layers") for box in normal_boxes]
    if normal_fills != [
        "bottom | left | right | front | back",
        "bottom | top | left | right | front | back",
    ]:
        raise ValueError("v3 normal face recipe mismatch")
    if [layer.get("vdp") if layer is not None else None for layer in normal_layers] != [
        "0,1,2", "0,-1,-2"
    ]:
        raise ValueError("v3 normal layers do not mirror active shells")
    sequence = [node.tag for node in list(main)]
    expected_sequence = [
        "runlist", "setshapemode", "setdrawmode", "setmkbound", "drawbox",
        "setmkvoid", "drawbox", "setmkbound", "drawbox", "setmkfluid", "drawbox",
    ]
    if sequence != expected_sequence:
        raise ValueError(f"v3 mainlist sequence mismatch: {sequence}")
    main_boxes = main.findall("drawbox")
    if len(main_boxes) != 4:
        raise ValueError("v3 mainlist must contain four drawboxes")
    outer_layers = main_boxes[0].find("layers")
    gate_layers = main_boxes[2].find("layers")
    if outer_layers is None or outer_layers.get("vdp") != "0,1,2":
        raise ValueError("v3 outer active layers mismatch")
    if gate_layers is None or gate_layers.get("vdp") != "0,-1,-2":
        raise ValueError("v3 gate active layers mismatch")
    source = main_boxes[3]
    source_low = _attrs(source.find("point"), "x", "y", "z")
    source_size = _attrs(source.find("size"), "x", "y", "z")
    if source_low != tuple(SOURCE_FIRST_CENTER) or source_size != tuple(SOURCE_DRAW_SIZE):
        raise ValueError("v3 source lattice box changed")
    normals = root.find("./casedef/normals")
    norgeometry = normals.find("norgeometry") if normals is not None else None
    if (
        normals is None
        or normals.get("active") != "true"
        or norgeometry is None
        or norgeometry.find("geometryfile").get("file") != "[CaseName]_hdp_Actual.vtk"
        or norgeometry.find("distanceh").get("v") != "3.0"
        or norgeometry.find("svshapes").get("v") != "true"
    ):
        raise ValueError("v3 normal block mismatch")
    params = {
        node.get("key"): node.get("value")
        for node in root.findall("./execution/parameters/parameter")
    }
    for key, value in (("Boundary", "2"), ("SlipMode", "1"), ("NoPenetration", "1")):
        if params.get(key) != value:
            raise ValueError(f"v3 parameter {key} mismatch")
    return {
        "definition_sha256": sha256(path),
        "definition_bytes": path.stat().st_size,
        "case_id": CASE_ID,
        "dp_m": DP_M,
        "normal_geometry": {
            "outer_boxfill": normal_fills[0],
            "gate_boxfill": normal_fills[1],
            "outer_layers_vdp": normal_layers[0].get("vdp"),
            "gate_layers_vdp": normal_layers[1].get("vdp"),
        },
        "mainlist": {
            "runlist_first": True,
            "outer_layers_vdp": outer_layers.get("vdp"),
            "setmkvoid_gate_precursor": True,
            "gate_layers_vdp": gate_layers.get("vdp"),
            "source_is_unlayered": True,
        },
        "source_lattice": _source_lattice_contract(source_low, source_size),
        "normal_block": {"active": True, "distanceh": 3.0, "svshapes": True},
        "runtime_invoked": False,
    }


def _parent_bindings(base: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    bundle = verify_bundle(base)
    if bundle.get("fixed_matrix", {}).get("rows") != EXPECTED_ROWS:
        raise ValueError("parent matrix does not retain all rows")
    if bundle.get("fixed_matrix", {}).get("all_not_started") is not True:
        raise ValueError("parent matrix is not closed")
    if bundle.get("failure_denominator", {}).get("planned") != EXPECTED_ROWS:
        raise ValueError("parent denominator changed")
    if bundle.get("failure_denominator", {}).get("credit") != 0:
        raise ValueError("parent denominator has credit")
    return {
        "parent_root_contract": ref(base / "root-review-contract-v1.json", "parent scope root contract"),
        "parent_fixed_matrix": ref(base / "fixed-matrix-v1.json", "parent 15-row matrix"),
        "parent_failure_denominator": ref(base / "failure-denominator-v1.json", "parent full denominator"),
        "parent_lineage": ref(base / "lineage-clarification-v1.json", "parent lineage closure"),
    }


def _assert_failure_evidence(audit_path: Path, preflight_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    audit = load_json(audit_path)
    preflight = load_json(preflight_path)
    if audit.get("schema") != "core.f2.submerged_orifice_transfer.v4_failure_boundnor_audit.v1":
        raise ValueError("v4 failure audit schema mismatch")
    if audit.get("case_id") != PARENT_V4_CASE_ID or audit.get("status") != "read_only_v4_boundnor_failure_audited":
        raise ValueError("v4 failure audit identity/status mismatch")
    scope = audit.get("input_scope", {})
    for key in ("definition_read", "bi4_read", "native_decoder_invoked", "gencase_invoked", "solver_invoked", "gpu_invoked"):
        if scope.get(key) is not False:
            raise ValueError(f"v4 audit opened prohibited input/runtime: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if scope.get(key) != 0:
            raise ValueError(f"v4 audit mutated protected state: {key}")
    summary = audit.get("generated_field_summary", {})
    if summary.get("global_zero_boundnor_count") != 64899 or summary.get("global_zero_normal_size_count") != 64899:
        raise ValueError("v4 audit no longer binds 64,899 zero normals")
    partitions = {int(row["mk"]): row for row in audit.get("mk_partitions", [])}
    if partitions.get(17, {}).get("zero_boundnor_count") != 64899:
        raise ValueError("v4 outer partition changed")
    if partitions.get(18, {}).get("zero_boundnor_count") != 0:
        raise ValueError("v4 gate partition changed")
    if preflight.get("schema") != "core.f2.submerged_orifice_transfer.cpu_native_preflight.v4":
        raise ValueError("v4 preflight evidence schema mismatch")
    if preflight.get("case_id") != PARENT_V4_CASE_ID or preflight.get("preflight_pass") is not False:
        raise ValueError("v4 preflight is not the failed evidence")
    counts = preflight.get("generated_counts", {})
    if counts.get("fluid_particles") != 240198 or counts.get("boundary_particles") != 255906:
        raise ValueError("v4 generated count evidence changed")
    native = preflight.get("native_initial", {})
    if native.get("zero_boundnor_count") != 64899 or native.get("zero_normal_size_count") != 64899:
        raise ValueError("v4 native zero-normal evidence changed")
    mass = native.get("hard_gates", {}).get("mass", {})
    if mass.get("relative_error") != 0.04718017578125 or mass.get("max_relative_error") != MASS_RELATIVE_ERROR_MAX:
        raise ValueError("v4 mass evidence changed")
    return audit, preflight


def build_candidate(
    base: Path = DEFAULT_BASE,
    audit_path: Path = DEFAULT_AUDIT,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    definition_path: Path = DEFAULT_DEFINITION,
    output: Path = DEFAULT_CANDIDATE,
) -> dict[str, Any]:
    base = Path(base).resolve()
    audit_path = Path(audit_path).resolve()
    preflight_path = Path(preflight_path).resolve()
    definition_path = Path(definition_path).resolve()
    audit, preflight = _assert_failure_evidence(audit_path, preflight_path)
    definition = inspect_definition(definition_path)
    candidate = {
        "schema": SCHEMA_CANDIDATE,
        "created_at_utc": CREATED_AT,
        "family": "F2",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "candidate_id": CANDIDATE_ID,
        "candidate_status": "root_review_only_static_candidate_not_run",
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "case_id": CASE_ID,
        "parent_failed_case_id": PARENT_V4_CASE_ID,
        "one_hypothesis": {
            "statement": (
                "The v4 hard failure is a single geometry/normal closure defect: "
                "the outer normal source does not explicitly mirror all active outer "
                "shell layers, while the inclusive source extent emits one extra y "
                "and z lattice row. Mirror the active shell in GeometryForNormals "
                "and use a count-closed 86x56x48 source lattice."
            ),
            "evidence": [
                "v4 Bound.vtk: 64,899/64,899 zero entries are Mk=17; Mk=18 has 0.",
                "v4 preflight: generated source count is 86x57x49=240,198 and mass error is +4.718017578125%.",
                "A count-closed 86x56x48 lattice predicts 231,168 particles and +0.78125% mass error.",
            ],
            "scope_limit": "one geometry/normal hypothesis; no alternate candidate is authorized",
        },
        "new_input_identity": {
            "fresh_definition_required": True,
            "fresh_definition": definition_path.as_posix(),
            "fresh_generated_prefix": DEFAULT_OUTPUT_PREFIX.resolve().as_posix(),
            "new_case_id": CASE_ID,
            "old_anchor_definition_reused": False,
            "old_anchor_native_input_reused": False,
            "v4_failed_definition_reused": False,
            "v4_failed_native_input_reused": False,
            "old_trajectory_reused": False,
        },
        "geometry_and_normal_contract": {
            "physical_geometry_changed": False,
            "outer_normal_faces": "bottom | left | right | front | back",
            "outer_normal_layers_vdp": "0,1,2",
            "gate_normal_faces": "bottom | top | left | right | front | back",
            "gate_normal_layers_vdp": "0,-1,-2",
            "outer_main_layers_vdp": "0,1,2",
            "gate_void_precursor": True,
            "gate_main_layers_vdp": "0,-1,-2",
            "normal_distance_h": 3.0,
            "svshapes": True,
        },
        "source_lattice_closure": {
            "first_center_m": SOURCE_FIRST_CENTER,
            "draw_size_m": SOURCE_DRAW_SIZE,
            "expected_counts_xyz": list(SOURCE_LATTICE_COUNTS),
            "expected_particle_count": SOURCE_LATTICE_PARTICLES,
            "continuous_source_mass_kg": CONTINUOUS_SOURCE_VOLUME_M3 * SOURCE_DENSITY_KG_M3,
            "particle_mass_kg": PARTICLE_MASS_KG,
            "expected_discrete_mass_kg": SOURCE_TARGET_MASS_KG,
            "expected_relative_error": SOURCE_TARGET_RELATIVE_ERROR,
            "mass_gate_max": MASS_RELATIVE_ERROR_MAX,
            "runtime_count_observed": False,
        },
        "hard_preflight_gates": {
            "zero_boundnor_count_max": 0,
            "zero_normal_size_count_max": 0,
            "zero_normal_norm_threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "arrays_finite": True,
            "ids_unique_and_xml_aligned": True,
            "outer_endpoint_count_max": 0,
            "gate_endpoint_penetration_count_max": 0,
            "native_mass_relative_error_max": MASS_RELATIVE_ERROR_MAX,
            "threshold_relaxation": False,
            "survivor_renormalization": False,
        },
        "denominator_preservation": {
            "planned_rows": EXPECTED_ROWS,
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "unattempted_rows": EXPECTED_ROWS,
            "qualification_numerator": 0,
            "all_rows_retained": True,
            "same_input_retry": False,
        },
        "observed_parent_failure": {
            "boundnor_zero_count": audit["generated_field_summary"]["global_zero_boundnor_count"],
            "normal_size_zero_count": audit["generated_field_summary"]["global_zero_normal_size_count"],
            "fluid_particles": preflight["generated_counts"]["fluid_particles"],
            "mass_relative_error": preflight["native_initial"]["hard_gates"]["mass"]["relative_error"],
            "credit": 0,
        },
        "hash_bindings": {
            "v4_preflight_evidence": ref(preflight_path, "read-only failed v4 preflight JSON"),
            "v4_boundnor_failure_audit": ref(audit_path, "read-only v4 Bound.vtk audit"),
            "v4_failure_audit_adapter": ref(AUDIT_ADAPTER, "v4 read-only audit adapter"),
            "fresh_definition": ref(definition_path, "fresh v3 literal Definition"),
            "normal_remediation_v3_adapter": ref(Path(__file__).resolve(), "v3 static candidate/writer adapter"),
            **_parent_bindings(base),
        },
        "execution_controls": {
            "definition_writer_invoked": True,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_numerator_credit": 0,
        },
        "prohibited_until_root_review": [
            "GenCase", "native decoder", "solver", "GPU", "job creation",
            "queue", "ledger", "registry", "matrix submission",
        ],
    }
    write_json(output, candidate)
    return candidate


def _assert_static_candidate(candidate: Mapping[str, Any], definition_path: Path) -> None:
    if candidate.get("schema") != SCHEMA_CANDIDATE or candidate.get("case_id") != CASE_ID:
        raise ValueError("v3 candidate identity/schema mismatch")
    if candidate.get("candidate_status") != "root_review_only_static_candidate_not_run":
        raise ValueError("v3 candidate is not static-only")
    if candidate.get("matrix_credit") != 0 or candidate.get("qualification_claim") != "none":
        raise ValueError("v3 candidate contains credit")
    identity = candidate.get("new_input_identity", {})
    if identity.get("fresh_definition") != str(Path(definition_path).resolve()):
        raise ValueError("v3 candidate Definition path changed")
    for key in (
        "old_anchor_definition_reused", "old_anchor_native_input_reused",
        "v4_failed_definition_reused", "v4_failed_native_input_reused",
        "old_trajectory_reused",
    ):
        if identity.get(key) is not False:
            raise ValueError(f"v3 candidate permits reuse: {key}")
    if candidate.get("hard_preflight_gates", {}).get("zero_boundnor_count_max") != 0:
        raise ValueError("v3 candidate relaxed zero BoundNor gate")
    if candidate.get("hard_preflight_gates", {}).get("native_mass_relative_error_max") != MASS_RELATIVE_ERROR_MAX:
        raise ValueError("v3 candidate changed mass gate")
    denominator = candidate.get("denominator_preservation", {})
    if denominator.get("planned_rows") != EXPECTED_ROWS or denominator.get("qualification_numerator") != 0:
        raise ValueError("v3 denominator is not closed")
    controls = candidate.get("execution_controls", {})
    for key in ("gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if controls.get(key) is not False:
            raise ValueError(f"v3 candidate records runtime execution: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"v3 candidate mutated protected state: {key}")
    inspect_definition(definition_path)


def build_contract(
    base: Path = DEFAULT_BASE,
    candidate_path: Path = DEFAULT_CANDIDATE,
    audit_path: Path = DEFAULT_AUDIT,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    definition_path: Path = DEFAULT_DEFINITION,
    output: Path = DEFAULT_CONTRACT,
    test_path: Path | None = None,
) -> dict[str, Any]:
    base = Path(base).resolve()
    candidate_path = Path(candidate_path).resolve()
    audit_path = Path(audit_path).resolve()
    preflight_path = Path(preflight_path).resolve()
    definition_path = Path(definition_path).resolve()
    candidate = load_json(candidate_path)
    _assert_static_candidate(candidate, definition_path)
    _assert_failure_evidence(audit_path, preflight_path)
    bindings: dict[str, Any] = {
        "v3_candidate": ref(candidate_path, "v3 root-review candidate"),
        "v3_fresh_definition": ref(definition_path, "v3 fresh literal Definition"),
        "v4_preflight_evidence": ref(preflight_path, "v4 failed preflight evidence"),
        "v4_boundnor_failure_audit": ref(audit_path, "v4 read-only Bound.vtk audit"),
        "v4_failure_audit_adapter": ref(AUDIT_ADAPTER, "v4 read-only audit adapter"),
        "normal_remediation_v3_adapter": ref(Path(__file__).resolve(), "v3 static contract adapter"),
        **_parent_bindings(base),
    }
    if test_path is not None:
        bindings["v3_contract_test"] = ref(Path(test_path).resolve(), "v3 static contract test")
    contract = {
        "schema": SCHEMA_CONTRACT,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "candidate_id": CANDIDATE_ID,
        "case_id": CASE_ID,
        "parent_failed_case_id": PARENT_V4_CASE_ID,
        "status": "root_review_only_static_contract_runtime_closed",
        "decision": "candidate_requires_independent_root_review_before_any_runtime",
        "authorized_now": False,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "authorization": {
            "cpu_gencase": False,
            "native_decode": False,
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "fresh_input": {
            "definition": ref(definition_path, "fresh v3 literal Definition"),
            "generated_prefix": str(DEFAULT_OUTPUT_PREFIX.resolve()),
            "generated_products_present": False,
            "native_input_present": False,
            "old_anchor_definition_reused": False,
            "old_anchor_native_input_reused": False,
            "v4_failed_definition_reused": False,
            "v4_failed_native_input_reused": False,
        },
        "one_hypothesis_review": candidate["one_hypothesis"],
        "hard_preflight_gates": candidate["hard_preflight_gates"],
        "preflight": {
            "status": "not_run",
            "generated_xml_present": False,
            "native_arrays_present": False,
            "solver_product_present": False,
            "qualification_credit": 0,
        },
        "failure_denominator": candidate["denominator_preservation"],
        "hash_bindings": bindings,
        "execution_controls": {
            "definition_writer_invoked": True,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_numerator_credit": 0,
        },
        "blockers": [
            "v4 failed with 64,899 zero outer-wall BoundNor/NormalSize entries",
            "v4 failed mass gate at +4.718017578125%; the new source lattice is only a static prediction",
            "no v3 GenCase/native preflight has been run",
            "zero-normal and mass gates remain exact; no threshold relaxation is allowed",
        ],
        "required_root_review": "review the one hash-bound geometry/normal closure hypothesis; keep runtime closed until separately authorized",
    }
    write_json(output, contract)
    return contract


def verify_contract(
    contract_path: Path = DEFAULT_CONTRACT,
    base: Path = DEFAULT_BASE,
    candidate_path: Path = DEFAULT_CANDIDATE,
    audit_path: Path = DEFAULT_AUDIT,
    preflight_path: Path = DEFAULT_PREFLIGHT,
    definition_path: Path = DEFAULT_DEFINITION,
    test_path: Path | None = None,
) -> dict[str, Any]:
    contract_path = Path(contract_path).resolve()
    contract = load_json(contract_path)
    if contract.get("schema") != SCHEMA_CONTRACT or contract.get("case_id") != CASE_ID:
        raise ValueError("v3 contract schema/identity mismatch")
    if contract.get("authorized_now") is not False or contract.get("matrix_credit") != 0:
        raise ValueError("v3 contract opened authority or credit")
    auth = contract.get("authorization", {})
    for key in ("cpu_gencase", "native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"v3 contract opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"v3 contract opened {key}")
    _assert_static_candidate(load_json(Path(candidate_path).resolve()), Path(definition_path).resolve())
    _assert_failure_evidence(Path(audit_path).resolve(), Path(preflight_path).resolve())
    expected = {
        "v3_candidate": Path(candidate_path),
        "v3_fresh_definition": Path(definition_path),
        "v4_preflight_evidence": Path(preflight_path),
        "v4_boundnor_failure_audit": Path(audit_path),
        "v4_failure_audit_adapter": AUDIT_ADAPTER,
        "normal_remediation_v3_adapter": Path(__file__),
    }
    if test_path is not None:
        expected["v3_contract_test"] = Path(test_path)
    bindings = contract.get("hash_bindings", {})
    for key, path in expected.items():
        verify_ref(bindings.get(key, {}), f"v3 contract {key}", path)
    for key, item in _parent_bindings(Path(base)).items():
        verify_ref(bindings.get(key, {}), f"v3 contract {key}", Path(item["path"]))
        if bindings[key].get("sha256") != item["sha256"]:
            raise ValueError(f"v3 contract parent binding stale: {key}")
    fresh = contract.get("fresh_input", {})
    if fresh.get("generated_products_present") is not False or fresh.get("native_input_present") is not False:
        raise ValueError("v3 contract records generated input")
    for key in ("old_anchor_definition_reused", "old_anchor_native_input_reused", "v4_failed_definition_reused", "v4_failed_native_input_reused"):
        if fresh.get(key) is not False:
            raise ValueError(f"v3 contract permits reuse: {key}")
    if contract.get("failure_denominator", {}).get("planned_rows") != EXPECTED_ROWS:
        raise ValueError("v3 denominator is not full")
    if contract.get("failure_denominator", {}).get("qualification_numerator") != 0:
        raise ValueError("v3 contract contains qualification credit")
    if ".bi4" in json.dumps(contract, sort_keys=True).lower():
        raise ValueError("v3 contract must not bind native input path")
    return contract


def build_report(
    contract_path: Path = DEFAULT_CONTRACT,
    candidate_path: Path = DEFAULT_CANDIDATE,
    audit_path: Path = DEFAULT_AUDIT,
    definition_path: Path = DEFAULT_DEFINITION,
    test_path: Path | None = None,
    output: Path = DEFAULT_REPORT,
) -> Path:
    contract = verify_contract(
        contract_path,
        candidate_path=candidate_path,
        audit_path=audit_path,
        definition_path=definition_path,
        test_path=test_path,
    )
    files = [
        Path(contract_path), Path(candidate_path), Path(audit_path),
        Path(definition_path), Path(__file__), AUDIT_ADAPTER,
    ]
    if test_path is not None:
        files.append(Path(test_path))
    lines = [
        "# F2 submerged-orifice normal remediation v3 root-review-only report",
        "",
        "Status: **static candidate only; runtime closed; no qualification credit**.",
        "",
        "The v4 read-only audit found 64,899 zero `BoundNor`/`NormalSize` values, all in outer `Mk=17`; gate `Mk=18` had zero. The same v4 evidence generated 86×57×49 fluid particles and +4.718017578125% mass error. The single v3 hypothesis mirrors all active outer/gate shell layers in `GeometryForNormals` and uses a count-closed 86×56×48 source lattice, predicting +0.78125% mass error. These predictions remain unexecuted.",
        "",
        "The hard gates remain zero zero-normal entries, finite arrays, ID alignment, zero endpoint violations, and native mass relative error ≤2.5%. No threshold is relaxed and no survivor rescaling is permitted.",
        "",
        "Authorization is closed for CPU GenCase, native decode, solver, GPU, job creation, queue, ledger, registry, and matrix submission. The new output prefix is reserved only and contains no generated products.",
        "",
        f"Contract status: `{contract['status']}`.",
        "",
        "## Hash closure",
        "",
    ]
    for path in files:
        path = path.resolve()
        lines.append(f"- `{path}` SHA-256 `{sha256(path)}` ({path.stat().st_size} bytes)")
    lines.extend(["", "No GenCase/native decode/solver/GPU execution was performed for v3.", ""])
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("write-definition", "write-candidate", "write-contract", "verify-contract", "write-report"),
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--test", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write-definition":
        result: Any = write_definition(args.output or args.definition)
    elif args.command == "write-candidate":
        result = build_candidate(args.base, args.audit, args.preflight, args.definition, args.output or args.candidate)
    elif args.command == "write-contract":
        result = build_contract(args.base, args.candidate, args.audit, args.preflight, args.definition, args.output or args.contract, args.test)
    elif args.command == "verify-contract":
        result = verify_contract(args.output or args.contract, args.base, args.candidate, args.audit, args.preflight, args.definition, args.test)
    else:
        result = str(build_report(args.contract, args.candidate, args.audit, args.definition, args.test, args.output or DEFAULT_REPORT))
    if isinstance(result, dict):
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
