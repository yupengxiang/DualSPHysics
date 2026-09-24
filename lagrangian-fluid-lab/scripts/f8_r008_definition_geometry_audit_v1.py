"""Read-only structural audit of frozen F8 R008 Definition geometry.

This validates only the materialized static XML inputs and their frozen hashes.
It does not invoke GenCase/native tools and cannot verify generated particles,
surface meshes, or runtime boundary-normal vectors.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle
from scripts import f8_r008_definition_control_pack_v1 as pack
from scripts import f8_t1_scope_design_v1 as scope


LAB = Path(__file__).resolve().parents[1]
PACK_RECEIPT = pack.LAB / pack.RECEIPT_TARGET
BOUNDARY_SEMANTICS_SOURCE = Path("scripts/f8_input_materialization_v1.py")
MAX_DEFINITION_BYTES = 64 * 1024
GEOMETRY_TOLERANCE_M = 2e-14
EXPECTED_BOUNDARY_CONTRACT = "periodic x/y; fixed no-slip mDBC z walls; no moving/floating boundaries"
PERIODIC_PRESENCE_SEMANTICS = (
    '<parameter key="XYPeriodic" value="0" comment="Periodic BC in X and Y; '
    'value is ignored by native presence semantics." />'
)
MDBC_PARAMETER_SEMANTICS = (
    '<parameter key="Boundary" value="2" comment="mDBC fixed boundary method." />'
)


class DefinitionGeometryAuditError(ValueError):
    """Frozen R008 Definition geometry differs from its static contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DefinitionGeometryAuditError(message)


def _node(parent: ET.Element, path: str, context: str) -> ET.Element:
    result = parent.find(path)
    _require(result is not None, f"{context}: missing XML node {path}")
    return result


def _attrs(node: ET.Element, expected: Mapping[str, str], context: str) -> None:
    _require(node.attrib == dict(expected),
             f"{context}: <{node.tag}> attributes differ from frozen geometry contract")


def _scalar(node: ET.Element, key: str, expected: float, context: str) -> float:
    raw = node.get(key)
    _require(raw is not None, f"{context}: missing numeric attribute {key}")
    try:
        value = float(raw)
    except ValueError as exc:
        raise DefinitionGeometryAuditError(f"{context}: invalid numeric attribute {key}") from exc
    _require(math.isfinite(value), f"{context}: non-finite numeric attribute {key}")
    _require(math.isclose(value, expected, rel_tol=0.0, abs_tol=GEOMETRY_TOLERANCE_M),
             f"{context}: {key}={value!r}, expected {expected!r}")
    return value


def _vector(node: ET.Element, expected: Mapping[str, float], context: str) -> dict[str, float]:
    vector_context = f"{context} <{node.tag}>"
    _require(set(node.attrib) == set(expected), f"{vector_context}: coordinate set changed")
    return {axis: _scalar(node, axis, value, vector_context) for axis, value in expected.items()}


def _stable_read_workspace_file(relative: str, maximum: int) -> bytes:
    root_fd, _absolute = bundle._open_absolute_directory(LAB)
    try:
        return bundle._stable_read_beneath(root_fd, relative, maximum)
    except (bundle.BundleVerificationError, OSError, ValueError) as exc:
        raise DefinitionGeometryAuditError(f"workspace evidence could not be read safely: {relative}") from exc
    finally:
        os.close(root_fd)


def audit_definition_geometry(payload: bytes, case: Mapping[str, Any]) -> dict[str, Any]:
    """Check one static Definition's full declared domain, wall and fluid geometry."""
    case_id = case.get("case_id")
    _require(isinstance(case_id, str) and bool(case_id), "frozen geometry row lacks a case_id")
    context = f"{case_id} Definition"
    _require(isinstance(payload, bytes) and 0 < len(payload) <= MAX_DEFINITION_BYTES,
             f"{context}: input is absent or exceeds the static XML size bound")
    upper = payload.upper()
    _require(b"<!DOCTYPE" not in upper and b"<!ENTITY" not in upper,
             f"{context}: declarations/entities are forbidden in frozen Definition XML")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DefinitionGeometryAuditError(f"{context}: malformed XML") from exc
    _require(root.tag == "case", f"{context}: root element is not case")
    _require([child.tag for child in root] == ["casedef", "execution"],
             f"{context}: root element contains unregistered sections")
    casedef = _node(root, "./casedef", context)
    _require([child.tag for child in casedef] == ["constantsdef", "mkconfig", "geometry", "normals"],
             f"{context}: case definition sections changed")

    dp = float(case["dp_m"])
    half_height = scope.HALF_HEIGHT_M
    length_x, length_y = scope.LENGTH_X_M, scope.LENGTH_Y_M
    wall_extent = half_height + dp
    domain_extent = half_height + 6.0 * dp

    geometry = _node(root, "./casedef/geometry", context)
    _require([child.tag for child in geometry] == ["definition", "commands"],
             f"{context}: geometry element contains unregistered children")
    definition = _node(geometry, "./definition", context)
    _require(set(definition.attrib) == {"dp"}, f"{context}: geometry spacing attributes changed")
    _scalar(definition, "dp", dp, context)
    _vector(_node(definition, "./pointref", context), {"x": 0.0, "y": 0.0, "z": 0.0}, context)
    domain_min = _vector(
        _node(definition, "./pointmin", context),
        {"x": 0.0, "y": 0.0, "z": -domain_extent}, context,
    )
    domain_max = _vector(
        _node(definition, "./pointmax", context),
        {"x": length_x, "y": length_y, "z": domain_extent}, context,
    )
    _require([child.tag for child in definition] == ["pointref", "pointmin", "pointmax"],
             f"{context}: unexpected geometry definition children")

    commands = _node(geometry, "./commands", context)
    _require([child.tag for child in commands] == ["list", "mainlist"],
             f"{context}: geometry command container is not closed")
    normal_lists = commands.findall("./list[@name='GeometryForNormals']")
    _require(len(normal_lists) == 1, f"{context}: expected exactly one GeometryForNormals list")
    normal_list = normal_lists[0]
    _require([child.tag for child in normal_list] == [
        "setactive", "setshapemode", "setnormalinvert", "setmkbound", "drawbox", "shapeout", "resetdraw",
    ], f"{context}: normal-generation command order changed")
    _attrs(_node(normal_list, "./setactive", context), {"drawpoints": "0", "drawshapes": "1"}, context)
    _require(_node(normal_list, "./setshapemode", context).text.strip() == "actual | bound",
             f"{context}: normal geometry is not rendered in actual | bound mode")
    _attrs(_node(normal_list, "./setnormalinvert", context), {"invert": "true"}, context)
    _attrs(_node(normal_list, "./setmkbound", context), {"mk": "0", "name": "FiniteNoSlipZWalls"}, context)
    _attrs(_node(normal_list, "./shapeout", context), {"file": "hdp"}, context)
    normal_wall = _node(normal_list, "./drawbox", context)
    _require([child.tag for child in normal_wall] == ["boxfill", "layers", "point", "size"],
             f"{context}: normal wall box structure changed")
    _require(normal_wall.findtext("./boxfill", "").strip() == "top | bottom",
             f"{context}: normal-generation shape must select only top and bottom faces")
    _attrs(_node(normal_wall, "./layers", context), {"vdp": "-0.5"}, context)
    normal_point = _vector(
        _node(normal_wall, "./point", context),
        {"x": 0.0, "y": 0.0, "z": -wall_extent}, context,
    )
    normal_size = _vector(
        _node(normal_wall, "./size", context),
        {"x": length_x, "y": length_y, "z": 2.0 * wall_extent}, context,
    )

    mainlist = _node(commands, "./mainlist", context)
    _require([child.tag for child in mainlist] == [
        "runlist", "setshapemode", "setdrawmode", "setmkbound", "drawbox", "setmkfluid", "drawbox",
    ], f"{context}: main geometry command order or multiplicity changed")
    _attrs(_node(mainlist, "./runlist", context), {"name": "GeometryForNormals"}, context)
    _require(_node(mainlist, "./setshapemode", context).text.strip() == "dp | bound",
             f"{context}: particle geometry is not rendered in dp | bound mode")
    _attrs(_node(mainlist, "./setdrawmode", context), {"mode": "full"}, context)
    _attrs(_node(mainlist, "./setmkbound", context), {"mk": "0", "name": "FiniteNoSlipZWalls"}, context)
    wall = _node(mainlist, "./drawbox[1]", context)
    _require([child.tag for child in wall] == ["boxfill", "layers", "point", "size"],
             f"{context}: particle wall box structure changed")
    _require(wall.findtext("./boxfill", "").strip() == "top | bottom",
             f"{context}: particle wall shape must select only top and bottom faces")
    _attrs(_node(wall, "./layers", context), {"vdp": "0,1,2,3"}, context)
    wall_point = _vector(
        _node(wall, "./point", context),
        {"x": 0.0, "y": 0.0, "z": -wall_extent}, context,
    )
    wall_size = _vector(
        _node(wall, "./size", context),
        {"x": length_x, "y": length_y, "z": 2.0 * wall_extent}, context,
    )
    _attrs(_node(mainlist, "./setmkfluid", context), {"mk": "0", "name": "FullyFilledChannelFluid"}, context)
    fluid = _node(mainlist, "./drawbox[2]", context)
    _require([child.tag for child in fluid] == ["boxfill", "point", "size"],
             f"{context}: fluid box structure changed")
    _require(fluid.findtext("./boxfill", "").strip() == "solid",
             f"{context}: fluid fill must be a single solid volume")
    fluid_point = _vector(
        _node(fluid, "./point", context),
        {"x": 0.0, "y": 0.0, "z": -half_height}, context,
    )
    fluid_size = _vector(
        _node(fluid, "./size", context),
        {"x": length_x, "y": length_y, "z": 2.0 * half_height}, context,
    )

    normals = _node(root, "./casedef/normals", context)
    _attrs(normals, {"active": "true"}, context)
    _require([child.tag for child in normals] == ["norgeometry"],
             f"{context}: normal-generation configuration changed")
    normal_generation = _node(normals, "./norgeometry", context)
    _attrs(_node(normal_generation, "./geometryfile", context),
           {"file": "[CaseName]_hdp_Actual.vtk"}, context)
    _attrs(_node(normal_generation, "./distanceh", context), {"v": "3.0"}, context)
    _attrs(_node(normal_generation, "./svshapes", context), {"v": "true"}, context)

    boundary_parameters = root.findall("./execution/parameters/parameter[@key='Boundary']")
    periodic_parameters = root.findall("./execution/parameters/parameter[@key='XYPeriodic']")
    _require(len(boundary_parameters) == 1 and boundary_parameters[0].get("value") == "2"
             and len(periodic_parameters) == 1 and periodic_parameters[0].get("value") == "0",
             f"{context}: boundary or periodicity control changed")
    _vector(_node(root, "./casedef/constantsdef/gravity", context),
            {"x": 0.0, "y": 0.0, "z": 0.0}, context)
    accinput = _node(root, "./execution/special/accinputs/accinput", context)
    _require(accinput.get("mkfluid") == "0" and accinput.find("./globalgravity") is not None
             and accinput.find("./globalgravity").get("value") == "0",
             f"{context}: global gravity is not disabled")

    return {
        "case_id": case_id,
        "dp_m": dp,
        "domain_z_bounds_m": [domain_min["z"], domain_max["z"]],
        "wall_box_reference_z_bounds_m": [-wall_extent, wall_extent],
        "fluid_z_bounds_m": [-half_height, half_height],
        "boundary_shape": "top | bottom only, four particle layers per wall",
        "requested_wall_plane_offsets_dp": [1.0, 2.0, 3.0, 4.0],
        "outer_domain_clearance_dp": 2.0,
        "four_layer_support_rule_passes": 4.0 >= 2.0 * math.sqrt(3.0),
        "registered_boundary_contract": "periodic x/y; fixed no-slip mDBC z walls",
        "registered_boundary_parameters": {"Boundary": 2, "XYPeriodic": 0},
        "normal_geometry_layer_vdp": -0.5,
        "normal_length_and_direction_gate": "future native gate: magnitude >= 0.25*dp; lower +z, upper -z",
        "normal_shape_inversion_declared": True,
        "native_normal_vectors_verified": False,
        "geometry_vectors": {
            "normal_wall_origin": normal_point,
            "normal_wall_size": normal_size,
            "particle_wall_origin": wall_point,
            "particle_wall_size": wall_size,
            "fluid_origin": fluid_point,
            "fluid_size": fluid_size,
        },
    }


def _read_frozen_definition(binding: Mapping[str, Any]) -> bytes:
    relative = binding.get("path")
    expected_bytes = binding.get("bytes")
    expected_sha256 = binding.get("sha256")
    _require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
             and ".." not in Path(relative).parts,
             "frozen Definition path is not a safe relative path")
    _require(isinstance(expected_bytes, int) and not isinstance(expected_bytes, bool)
             and 0 < expected_bytes <= MAX_DEFINITION_BYTES,
             "frozen Definition byte count is invalid")
    _require(isinstance(expected_sha256, str) and len(expected_sha256) == 64,
             "frozen Definition SHA-256 is malformed")
    payload = _stable_read_workspace_file(relative, MAX_DEFINITION_BYTES)
    _require(len(payload) == expected_bytes and hashlib.sha256(payload).hexdigest() == expected_sha256,
                 f"frozen Definition bytes differ from hash-closed pack: {relative}")
    return payload


def audit_frozen_geometry_pack() -> dict[str, Any]:
    """Revalidate the immutable 47-Definition pack and audit every geometry."""
    scope_receipt = pack._json(pack.DESIGN_RECEIPT)
    frozen_physics = scope_receipt.get("frozen_physics_and_control", {})
    expected_geometry = {
        "x": [0.0, scope.LENGTH_X_M],
        "y": [0.0, scope.LENGTH_Y_M],
        "z": [-scope.HALF_HEIGHT_M, scope.HALF_HEIGHT_M],
    }
    _require(frozen_physics.get("geometry_m") == expected_geometry
             and frozen_physics.get("boundary") == EXPECTED_BOUNDARY_CONTRACT,
             "frozen R008 scope geometry or boundary contract changed")
    boundary_source_bytes = _stable_read_workspace_file(BOUNDARY_SEMANTICS_SOURCE.as_posix(), 1024 * 1024)
    try:
        boundary_source = boundary_source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DefinitionGeometryAuditError("boundary semantics source is not UTF-8") from exc
    _require(boundary_source.count(PERIODIC_PRESENCE_SEMANTICS) == 1
             and boundary_source.count(MDBC_PARAMETER_SEMANTICS) == 1,
             "XYPeriodic presence or Boundary=mDBC semantic source changed")
    boundary_source_sha256 = hashlib.sha256(boundary_source.encode("utf-8")).hexdigest()
    expected_receipt = pack._close_materialized_pack(pack.build_pack(), LAB)
    payload = _stable_read_workspace_file(pack.RECEIPT_TARGET.as_posix(), 16 * 1024 * 1024)
    canonical_payload = (json.dumps(expected_receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _require(payload == canonical_payload,
             "materialized Definition/control receipt differs from the canonical static pack")
    receipt = json.loads(payload)
    _require(receipt.get("status") == "static_definition_control_pack_materialized_no_execution_authority"
             and receipt.get("case_counts") == {
                 "qualification": 15, "production": 32, "total": 47,
                 "definition_files": 47, "control_files": 47,
             }, "frozen R008 Definition/control pack is not the exact 15+32 static pack")
    cases = receipt.get("cases")
    _require(isinstance(cases, list) and len(cases) == 47,
             "frozen R008 pack does not contain 47 case rows")
    seen: set[str] = set()
    summaries: list[dict[str, Any]] = []
    for case in cases:
        case_id = case.get("case_id") if isinstance(case, dict) else None
        _require(isinstance(case_id, str) and case_id not in seen,
                 "frozen Definition pack has a missing or duplicate case identity")
        seen.add(case_id)
        binding = case.get("definition")
        _require(isinstance(binding, dict), f"{case_id}: frozen Definition binding is absent")
        summaries.append(audit_definition_geometry(_read_frozen_definition(binding), case))
    _require(seen == {str(row["case_id"]) for row in scope.qualification_matrix() + scope.production_manifest()},
             "audited Definition case IDs differ from the frozen 15+32 scope matrices")
    return {
        "schema": "core.cfd.f8.r008_definition_geometry_static_audit.v1",
        "status": "static_frozen_definition_geometry_passed_runtime_geometry_unverified",
        "source_receipt_sha256": hashlib.sha256(payload).hexdigest(),
        "definition_count": len(summaries),
        "case_summaries": summaries,
        "frozen_scope_geometry_m": expected_geometry,
        "frozen_scope_boundary_contract": EXPECTED_BOUNDARY_CONTRACT,
        "boundary_semantics_source": {
            "path": BOUNDARY_SEMANTICS_SOURCE.as_posix(),
            "sha256": boundary_source_sha256,
            "Boundary_2_means_mDBC": True,
            "XYPeriodic_zero_value_uses_presence_semantics": True,
        },
        "native_geometry_generated": False,
        "native_normal_vectors_verified": False,
        "boundary_semantics_note": "XYPeriodic=0 is checked as the registered XML value, not interpreted as absence of x/y periodic boundary conditions; the frozen scope declares periodic x/y.",
        "gencase_invoked": False,
        "solver_invoked": False,
        "qualification_credit": 0,
        "execution_authority": {"gencase": False, "native_decoder": False, "solver": False, "T1_numerical": False},
    }


__all__ = ["DefinitionGeometryAuditError", "audit_definition_geometry", "audit_frozen_geometry_pack"]
