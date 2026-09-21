#!/usr/bin/env python3
"""Write and verify one static v4 F2 normal/mass repair hypothesis.

This adapter is deliberately proposal-only.  It reads the already materialized
v3 preflight sidecars to make a bounded failure audit, writes a new literal
Definition, and binds a candidate and root-review-only contract.  It has no
GenCase, native decoder, solver, GPU, job, queue, ledger, registry, or matrix
submission path.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping
import xml.etree.ElementTree as ET

import numpy as np

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
from scripts.r4_f6_mdbc_runtime_zero_normal_audit import (  # noqa: E402
    _all_vtk_arrays,
    read_binary_vtk,
)


REVISION_ID = "F2_submerged_orifice_normal_remediation_v4"
CANDIDATE_ID = "F2_submerged_orifice_normalremediation_q0p5_signednormal_countclosed_v4"
CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4"
PARENT_V3_CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3"
CREATED_AT = "2026-09-21T00:00:00+00:00"
Q = 0.5
DP_M = 0.0075
ORIFICE_HEIGHT_M = 0.18
ZERO_NORMAL_TOLERANCE_M = 1.0e-12
MASS_RELATIVE_ERROR_MAX = 0.025
CONTINUOUS_SOURCE_VOLUME_M3 = 0.64 * 0.42 * 0.36
SOURCE_DENSITY_KG_M3 = 1000.0
PARTICLE_MASS_KG = SOURCE_DENSITY_KG_M3 * DP_M**3
SOURCE_FIRST_CENTER = (0.04125, 0.04125, 0.04125)
SOURCE_COUNTS = (86, 56, 48)
SOURCE_PARTICLES = math.prod(SOURCE_COUNTS)
SOURCE_DRAW_SIZE = (0.6375, 0.4125, 0.3525)
SOURCE_DISCRETE_MASS_KG = SOURCE_PARTICLES * PARTICLE_MASS_KG
SOURCE_RELATIVE_ERROR = SOURCE_DISCRETE_MASS_KG / (
    CONTINUOUS_SOURCE_VOLUME_M3 * SOURCE_DENSITY_KG_M3
) - 1.0

OUTER_LOW = (0.0, 0.0, 0.0)
OUTER_SIZE = (1.6, 0.5, 0.8)
GATE_LOW = (0.72, 0.04, 0.18)
GATE_SIZE = (0.06, 0.42, 0.62)
GATE_VOID_LOW = (0.71625, 0.03625, 0.17625)
GATE_VOID_SIZE = (0.0675, 0.4275, 0.6275)
GATE_BOUND_LOW = (0.72375, 0.04375, 0.18375)
GATE_BOUND_SIZE = (0.0525, 0.4125, 0.6125)

REMEDIATION = DEFAULT_BASE / "normal-remediation-v4"
DEFAULT_DEFINITION = REMEDIATION / "fresh-definition-v4" / f"{CASE_ID}_Def.xml"
DEFAULT_EVIDENCE = REMEDIATION / "v3-failure-evidence-v4.json"
DEFAULT_CANDIDATE = REMEDIATION / "normal-remediation-candidate-v4.json"
DEFAULT_CONTRACT = REMEDIATION / "root-review-only-contract-v4.json"
DEFAULT_OUTPUT_PREFIX = REMEDIATION / "preflight-v4" / CASE_ID
DEFAULT_REPORT = LAB_ROOT / "reports/F2-SUBMERGED-ORIFICE-NORMAL-REMEDIATION-V4-ROOT-REVIEW-2026-09-21.zh-CN.md"

V3_DIR = DEFAULT_BASE / "normal-remediation-v3"
V3_PREFLIGHT = V3_DIR / "preflight-v3" / "preflight.json"
V3_BOUND = V3_DIR / "preflight-v3" / f"{PARENT_V3_CASE_ID}_Bound.vtk"
V3_ACTUAL = V3_DIR / "preflight-v3" / f"{PARENT_V3_CASE_ID}_hdp_Actual.vtk"
V3_LOG = V3_DIR / "preflight-v3" / "gencase.log"
V3_DEFINITION = V3_DIR / "fresh-definition-v3" / f"{PARENT_V3_CASE_ID}_Def.xml"

SCHEMA_EVIDENCE = "core.f2.submerged_orifice_transfer.v3_failure_evidence.v1"
SCHEMA_CANDIDATE = "core.f2.submerged_orifice_transfer.normal_remediation_candidate.v4"
SCHEMA_CONTRACT = "core.f2.submerged_orifice_transfer.normal_remediation.root_review_only.v4"


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
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def verify_ref(item: Mapping[str, Any], label: str, expected: Path | None = None) -> Path:
    value = item.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: path missing")
    path = Path(value).resolve()
    if expected is not None and path != Path(expected).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: stale SHA/byte binding")
    return path


def _sub(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs or {})
    if text is not None:
        node.text = text
    return node


def _drawbox(parent: ET.Element, fill: str, low: tuple[float, ...], size: tuple[float, ...], layers: str | None = None) -> ET.Element:
    node = _sub(parent, "drawbox")
    _sub(node, "boxfill", text=fill)
    _sub(node, "point", {axis: f"{value:.17g}" for axis, value in zip("xyz", low)})
    _sub(node, "size", {axis: f"{value:.17g}" for axis, value in zip("xyz", size)})
    if layers is not None:
        _sub(node, "layers", {"vdp": layers})
    return node


def _parameter(parent: ET.Element, key: str, value: str) -> None:
    _sub(parent, "parameter", {"key": key, "value": value})


def write_definition(target: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    """Write the independent v4 literal Definition; never reads v3 XML."""
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f"v4 Definition already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("case")
    casedef = _sub(root, "casedef")
    constants = _sub(casedef, "constantsdef")
    _sub(constants, "gravity", {"x": "0", "y": "0", "z": "-9.81"})
    for tag, attrs in (
        ("rhop0", {"value": "1000"}), ("rhopgradient", {"value": "2"}),
        ("hswl", {"value": "0", "auto": "true"}), ("gamma", {"value": "7"}),
        ("speedsystem", {"value": "0", "auto": "true"}), ("coefsound", {"value": "20"}),
        ("speedsound", {"value": "0", "auto": "true"}), ("coefh", {"value": "1.0"}),
        ("cflnumber", {"value": "0.2"}),
    ):
        _sub(constants, tag, attrs)
    _sub(casedef, "mkconfig", {"boundcount": "220", "fluidcount": "16"})
    geometry = _sub(casedef, "geometry")
    definition = _sub(geometry, "definition", {"dp": f"{DP_M:.17g}"})
    _sub(definition, "pointmin", {"x": "-0.30", "y": "-0.15", "z": "-0.15"})
    _sub(definition, "pointmax", {"x": "1.90", "y": "0.65", "z": "1.20"})
    _sub(definition, "pointref", {"x": "0.00375", "y": "0.00375", "z": "0.00375"})
    commands = _sub(geometry, "commands")
    normal_list = _sub(commands, "list", {"name": "GeometryForNormals"})
    _sub(normal_list, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    _sub(normal_list, "setshapemode", text="actual | bound")
    _sub(normal_list, "setnormalinvert", {"invert": "true"})
    _sub(normal_list, "setmkbound", {"mk": "0"})
    # v3 emitted the outer normal layers on the exterior.  The v4 hypothesis
    # mirrors them to the fluid-facing side of the active boundary shells.
    _drawbox(normal_list, "bottom | left | right | front | back", OUTER_LOW, OUTER_SIZE, "0,-1,-2")
    _sub(normal_list, "setmkbound", {"mk": "1"})
    _sub(normal_list, "setnormalinvert", {"invert": "false"})
    _drawbox(normal_list, "bottom | top | left | right | front | back", GATE_LOW, GATE_SIZE, "0,1,2")
    _sub(normal_list, "shapeout", {"file": "hdp"})
    _sub(normal_list, "resetdraw")
    main = _sub(commands, "mainlist")
    _sub(main, "runlist", {"name": "GeometryForNormals"})
    _sub(main, "setshapemode", text="actual | bound")
    _sub(main, "setdrawmode", {"mode": "full"})
    _sub(main, "setmkbound", {"mk": "0"})
    _drawbox(main, "bottom | left | right | front | back", OUTER_LOW, OUTER_SIZE, "0,1,2")
    _sub(main, "setmkvoid")
    _drawbox(main, "solid", GATE_VOID_LOW, GATE_VOID_SIZE)
    _sub(main, "setmkbound", {"mk": "1"})
    _drawbox(main, "bottom | top | left | right | front | back", GATE_BOUND_LOW, GATE_BOUND_SIZE, "0,-1,-2")
    _sub(main, "setmkfluid", {"mk": "0"})
    _drawbox(main, "solid", SOURCE_FIRST_CENTER, SOURCE_DRAW_SIZE)
    normals = _sub(casedef, "normals", {"active": "true"})
    norgeometry = _sub(normals, "norgeometry")
    _sub(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    _sub(norgeometry, "distanceh", {"v": "3.0"})
    _sub(norgeometry, "svshapes", {"v": "true"})
    execution = _sub(root, "execution")
    parameters = _sub(execution, "parameters")
    for key, value in (
        ("SavePosDouble", "2"), ("Boundary", "2"), ("SlipMode", "1"), ("StepAlgorithm", "2"),
        ("Kernel", "2"), ("ViscoTreatment", "1"), ("Visco", "0.03"), ("ViscoBoundFactor", "1"),
        ("DensityDT", "3"), ("DensityDTvalue", "0.1"), ("Shifting", "0"), ("RigidAlgorithm", "1"),
        ("FtPause", "0"), ("CoefDtMin", "0.05"), ("DtIni", "0"), ("DtMin", "0"),
        ("DtFixed", "0"), ("DtAllParticles", "0"), ("TimeMax", "1.5"), ("TimeOut", "0.01"),
        ("PartsOutMax", "1"), ("RhopOutMin", "700"), ("RhopOutMax", "1300"), ("MinFluidStop", "0"),
        ("NoPenetration", "1"),
    ):
        _parameter(parameters, key, value)
    domain = _sub(parameters, "simulationdomain")
    _sub(domain, "posmin", {"x": "-0.30", "y": "-0.15", "z": "-0.15"})
    _sub(domain, "posmax", {"x": "1.90", "y": "0.65", "z": "1.20"})
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return inspect_definition(target)


def _attrs(node: ET.Element | None, keys: tuple[str, ...]) -> tuple[float, ...]:
    if node is None:
        raise ValueError("Definition geometry attribute missing")
    return tuple(float(node.get(key, "nan")) for key in keys)


def inspect_definition(path: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    path = Path(path).resolve()
    root = ET.parse(path).getroot()
    if root.tag != "case":
        raise ValueError("v4 Definition root mismatch")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or not math.isclose(float(definition.get("dp", "nan")), DP_M, abs_tol=1e-15, rel_tol=0):
        raise ValueError("v4 Definition dp mismatch")
    commands = root.find("./casedef/geometry/commands")
    normal = commands.find("list[@name='GeometryForNormals']") if commands is not None else None
    main = commands.find("mainlist") if commands is not None else None
    if normal is None or main is None:
        raise ValueError("v4 normal/main lists missing")
    nboxes = normal.findall("drawbox")
    if len(nboxes) != 2:
        raise ValueError("v4 GeometryForNormals must have two boxes")
    fills = [(n.findtext("boxfill") or "").strip() for n in nboxes]
    layers = [n.find("layers").get("vdp") if n.find("layers") is not None else None for n in nboxes]
    if fills != ["bottom | left | right | front | back", "bottom | top | left | right | front | back"]:
        raise ValueError("v4 normal faces changed")
    if layers != ["0,-1,-2", "0,1,2"]:
        raise ValueError("v4 signed normal-layer hypothesis changed")
    mb = main.findall("drawbox")
    if len(mb) != 4 or main.find("runlist") is None or list(main).index(main.find("runlist")) != 0:
        raise ValueError("v4 mainlist shape/ordering changed")
    outer_layers = mb[0].find("layers")
    gate_layers = mb[2].find("layers")
    source = mb[3]
    if outer_layers is None or outer_layers.get("vdp") != "0,1,2" or gate_layers is None or gate_layers.get("vdp") != "0,-1,-2":
        raise ValueError("v4 active boundary layers changed")
    source_low = _attrs(source.find("point"), ("x", "y", "z"))
    source_size = _attrs(source.find("size"), ("x", "y", "z"))
    if source_low != SOURCE_FIRST_CENTER or source_size != SOURCE_DRAW_SIZE:
        raise ValueError("v4 count-closed source extent changed")
    normals = root.find("./casedef/normals")
    if normals is None or normals.get("active") != "true" or normals.find("norgeometry") is None:
        raise ValueError("v4 normal block inactive")
    return {
        "definition_sha256": sha256(path), "definition_bytes": path.stat().st_size,
        "case_id": CASE_ID, "dp_m": DP_M,
        "normal_geometry": {"outer_layers_vdp": layers[0], "gate_layers_vdp": layers[1], "outer_faces": fills[0], "gate_faces": fills[1]},
        "active_boundary_layers": {"outer_layers_vdp": outer_layers.get("vdp"), "gate_layers_vdp": gate_layers.get("vdp")},
        "source_lattice": {"first_center_m": list(source_low), "draw_size_m": list(source_size), "expected_counts_xyz": list(SOURCE_COUNTS), "expected_particles": SOURCE_PARTICLES, "predicted_discrete_mass_kg": SOURCE_DISCRETE_MASS_KG, "predicted_relative_error": SOURCE_RELATIVE_ERROR},
        "normal_block": {"active": True, "distanceh": 3.0, "svshapes": True},
        "runtime_invoked": False,
    }


def _parent_bindings(base: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    bundle = verify_bundle(base)
    if bundle.get("fixed_matrix", {}).get("rows") != EXPECTED_ROWS or bundle.get("fixed_matrix", {}).get("all_not_started") is not True:
        raise ValueError("parent matrix is not closed")
    if bundle.get("failure_denominator", {}).get("planned") != EXPECTED_ROWS or bundle.get("failure_denominator", {}).get("credit") != 0:
        raise ValueError("parent denominator is not closed")
    return {key: ref(base / filename, role) for key, filename, role in (
        ("parent_root_contract", "root-review-contract-v1.json", "parent scope root contract"),
        ("parent_fixed_matrix", "fixed-matrix-v1.json", "parent 15-row matrix"),
        ("parent_failure_denominator", "failure-denominator-v1.json", "parent full denominator"),
        ("parent_lineage", "lineage-clarification-v1.json", "parent lineage closure"),
    )}


def _read_v3_definition(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    normal = root.find("./casedef/geometry/commands/list[@name='GeometryForNormals']")
    boxes = normal.findall("drawbox") if normal is not None else []
    layers = [b.find("layers").get("vdp") for b in boxes if b.find("layers") is not None]
    source = root.find("./casedef/geometry/commands/mainlist/drawbox[4]")
    return {"normal_layers_vdp": layers, "source_low_m": list(_attrs(source.find("point"), ("x", "y", "z"))), "source_size_m": list(_attrs(source.find("size"), ("x", "y", "z")))}


def build_evidence(output: Path = DEFAULT_EVIDENCE) -> dict[str, Any]:
    """Audit existing v3 sidecars only; no native or runtime invocation."""
    preflight = load_json(V3_PREFLIGHT)
    if preflight.get("case_id") != PARENT_V3_CASE_ID or preflight.get("preflight_pass") is not False:
        raise ValueError("v3 evidence is not the closed failed preflight")
    counts = preflight.get("generated_counts", {})
    native = preflight.get("native_initial", {})
    mass = native.get("hard_gates", {}).get("mass", {})
    if counts.get("fluid_particles") != 219725 or counts.get("boundary_particles") != 255906:
        raise ValueError("v3 generated counts changed")
    if native.get("zero_boundnor_count") != 83443 or native.get("zero_normal_size_count") != 83443:
        raise ValueError("v3 zero-normal evidence changed")
    if mass.get("relative_error") != -0.04207502092633919:
        raise ValueError("v3 mass evidence changed")
    vtk = read_binary_vtk(V3_BOUND)
    arrays = _all_vtk_arrays(vtk)
    points = np.asarray(vtk["points"], dtype=float)
    normals = np.asarray(arrays["Normal"], dtype=float)
    sizes = np.asarray(arrays["NormalSize"], dtype=float)
    mk = np.asarray(arrays["Mk"])
    if normals.shape != (len(points), 3) or sizes.shape != (len(points),) or len(points) != 255906:
        raise ValueError("v3 Bound.vtk shape/count mismatch")
    zero = np.linalg.norm(normals, axis=1) <= ZERO_NORMAL_TOLERANCE_M
    parts = {int(value): int(np.sum(zero & (mk == value))) for value in np.unique(mk)}
    if parts != {17: 64899, 18: 18544}:
        raise ValueError(f"v3 Bound.vtk Mk partition changed: {parts}")
    actual = read_binary_vtk(V3_ACTUAL)
    actual_mk = np.asarray(actual["cell_data"]["Mk"])
    actual_shapes = Counter(int(value) for value in actual_mk)
    log = V3_LOG.read_text(encoding="utf-8")
    if "Non-zero particle normals: 172,463/255,906" not in log or "Final zero normals: 83,443/255,906" not in log:
        raise ValueError("v3 GenCase log normal summary changed")
    v3_def = _read_v3_definition(V3_DEFINITION)
    evidence = {
        "schema": SCHEMA_EVIDENCE, "created_at_utc": CREATED_AT, "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID, "status": "read_only_v3_failure_evidence_closed",
        "case_id": PARENT_V3_CASE_ID, "qualification_claim": "none", "matrix_credit": 0,
        "input_scope": {"preflight_json_read": True, "bound_vtk_read": True, "hdp_actual_vtk_read": True, "gencase_log_read": True, "definition_read": True, "bi4_read": False, "native_decoder_invoked": False, "gencase_invoked": False, "solver_invoked": False, "gpu_invoked": False, "job_created": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False},
        "observed_failure": {"zero_boundnor_count": 83443, "zero_normal_size_count": 83443, "mk17_outer_zero_count": 64899, "mk18_gate_zero_count": 18544, "boundary_particles": 255906, "fluid_particles": 219725, "mass_relative_error": -0.04207502092633919, "mass_gate_max": MASS_RELATIVE_ERROR_MAX, "outer_endpoint_count": 0, "gate_endpoint_penetration_count": 0, "ids_finite_gates_passed": True},
        "geometry_observation": {"v3_normal_layers_vdp": v3_def["normal_layers_vdp"], "hdp_actual_shape_count": int(len(actual_mk)), "hdp_actual_points": int(len(actual["points"])), "hdp_actual_shapes_by_mk": {str(k): v for k, v in sorted(actual_shapes.items())}, "zero_normals_are_exact_vectors": int(np.all(normals[zero] == 0.0, axis=1).sum()) == 83443, "zero_normals_mk_partition": parts},
        "source_count_observation": {"v3_source_low_m": v3_def["source_low_m"], "v3_source_size_m": v3_def["source_size_m"], "observed_fluid_count_factorization": [85, 55, 47], "observed_fluid_count": 219725, "v4_proposed_source_size_m": list(SOURCE_DRAW_SIZE), "v4_predicted_count_xyz": list(SOURCE_COUNTS), "v4_predicted_particles": SOURCE_PARTICLES, "v4_predicted_mass_relative_error": SOURCE_RELATIVE_ERROR},
        "single_falsifiable_hypothesis": {"statement": "The v3 normal geometry is layer-directionally misregistered: outer layers 0,1,2 are emitted on the opposite side of the active shell and gate layers 0,-1,-2 are emitted on the solid-side rows that still carry zero vectors. A sign-mirrored GeometryForNormals recipe, coupled with the one-dp endpoint correction required by the observed 85x55x47 source lattice, should remove the zero-normal rows and bring native source mass inside the unchanged 2.5% gate.", "v4_outer_normal_layers_vdp": "0,-1,-2", "v4_gate_normal_layers_vdp": "0,1,2", "falsifier": "Any future exact-one fresh CPU/native audit with a nonzero zero-normal count, nonfinite/ID failure, endpoint violation, or absolute source mass error above 0.025 falsifies this candidate and pauses this F2 remediation route."},
        "source": {"v3_preflight": ref(V3_PREFLIGHT, "closed v3 failed preflight"), "v3_bound_vtk": ref(V3_BOUND, "closed v3 Bound.vtk normal sidecar"), "v3_hdp_actual_vtk": ref(V3_ACTUAL, "closed v3 GeometryForNormals sidecar"), "v3_gencase_log": ref(V3_LOG, "closed v3 GenCase log"), "v3_definition": ref(V3_DEFINITION, "historical v3 Definition evidence"), "v4_evidence_adapter": ref(Path(__file__).resolve(), "v4 read-only evidence adapter")},
        "execution_controls": {"definition_writer_invoked": False, "gencase_invoked": False, "native_decoder_invoked": False, "solver_invoked": False, "gpu_invoked": False, "job_created": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False, "qualification_numerator_credit": 0},
    }
    write_json(output, evidence)
    return evidence


def _parent_bindings_for_candidate(base: Path) -> dict[str, Any]:
    return _parent_bindings(base)


def _assert_evidence(evidence_path: Path) -> dict[str, Any]:
    evidence = load_json(evidence_path)
    if evidence.get("schema") != SCHEMA_EVIDENCE or evidence.get("status") != "read_only_v3_failure_evidence_closed":
        raise ValueError("v4 evidence schema/status mismatch")
    obs = evidence.get("observed_failure", {})
    if (obs.get("zero_boundnor_count"), obs.get("zero_normal_size_count"), obs.get("mk17_outer_zero_count"), obs.get("mk18_gate_zero_count")) != (83443, 83443, 64899, 18544):
        raise ValueError("v3 hard failure evidence changed")
    if obs.get("mass_relative_error") != -0.04207502092633919 or obs.get("mass_gate_max") != MASS_RELATIVE_ERROR_MAX:
        raise ValueError("v3 mass failure evidence changed")
    controls = evidence.get("input_scope", {})
    for key in ("bi4_read", "native_decoder_invoked", "gencase_invoked", "solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if controls.get(key) is not False:
            raise ValueError(f"evidence opened prohibited action: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"evidence mutated protected state: {key}")
    return evidence


def build_candidate(base: Path = DEFAULT_BASE, evidence_path: Path = DEFAULT_EVIDENCE, definition_path: Path = DEFAULT_DEFINITION, output: Path = DEFAULT_CANDIDATE) -> dict[str, Any]:
    evidence_path = Path(evidence_path).resolve(); definition_path = Path(definition_path).resolve()
    evidence = _assert_evidence(evidence_path)
    definition = inspect_definition(definition_path)
    if DEFAULT_OUTPUT_PREFIX.parent.exists() and any(DEFAULT_OUTPUT_PREFIX.parent.iterdir()):
        raise ValueError("v4 output prefix parent is not fresh")
    candidate = {
        "schema": SCHEMA_CANDIDATE, "created_at_utc": CREATED_AT, "family": "F2", "scope_id": SCOPE_ID, "revision_id": REVISION_ID, "candidate_id": CANDIDATE_ID, "candidate_status": "root_review_only_static_candidate_not_run", "qualification_claim": "none", "qualified": False, "matrix_credit": 0, "case_id": CASE_ID, "parent_failed_case_id": PARENT_V3_CASE_ID,
        "one_hypothesis": evidence["single_falsifiable_hypothesis"],
        "new_input_identity": {"fresh_definition_required": True, "fresh_definition": str(definition_path), "fresh_generated_prefix": str(DEFAULT_OUTPUT_PREFIX.resolve()), "new_case_id": CASE_ID, "old_anchor_definition_reused": False, "old_anchor_native_input_reused": False, "v3_failed_definition_reused": False, "v3_failed_native_input_reused": False, "old_trajectory_reused": False},
        "geometry_and_normal_contract": {"physical_geometry_changed": False, "outer_normal_faces": "bottom | left | right | front | back", "gate_normal_faces": "bottom | top | left | right | front | back", "outer_normal_layers_vdp": "0,-1,-2", "gate_normal_layers_vdp": "0,1,2", "outer_main_layers_vdp": "0,1,2", "gate_main_layers_vdp": "0,-1,-2", "gate_void_precursor": True, "normal_distance_h": 3.0, "svshapes": True},
        "source_lattice_closure": {"first_center_m": list(SOURCE_FIRST_CENTER), "draw_size_m": list(SOURCE_DRAW_SIZE), "expected_counts_xyz": list(SOURCE_COUNTS), "expected_particle_count": SOURCE_PARTICLES, "continuous_source_mass_kg": CONTINUOUS_SOURCE_VOLUME_M3 * SOURCE_DENSITY_KG_M3, "particle_mass_kg": PARTICLE_MASS_KG, "expected_discrete_mass_kg": SOURCE_DISCRETE_MASS_KG, "expected_relative_error": SOURCE_RELATIVE_ERROR, "runtime_count_observed": False},
        "hard_preflight_gates": {"zero_boundnor_count_max": 0, "zero_normal_size_count_max": 0, "zero_normal_norm_threshold_m": ZERO_NORMAL_TOLERANCE_M, "arrays_finite": True, "ids_unique_and_xml_aligned": True, "outer_endpoint_count_max": 0, "gate_endpoint_penetration_count_max": 0, "native_mass_relative_error_max": MASS_RELATIVE_ERROR_MAX, "threshold_relaxation": False, "survivor_renormalization": False},
        "observed_parent_failure": evidence["observed_failure"],
        "denominator_preservation": {"planned_rows": EXPECTED_ROWS, "executed_rows": 0, "passed_rows": 0, "failed_rows": 0, "unattempted_rows": EXPECTED_ROWS, "qualification_numerator": 0, "all_rows_retained": True, "same_input_retry": False, "threshold_relaxation": False},
        "hash_bindings": {"v3_failure_evidence": ref(evidence_path, "closed v3 failure evidence"), "v3_failed_preflight": ref(V3_PREFLIGHT, "closed v3 failed preflight"), "v3_bound_vtk": ref(V3_BOUND, "closed v3 Bound.vtk evidence"), "v3_hdp_actual_vtk": ref(V3_ACTUAL, "closed v3 normal geometry evidence"), "v3_gencase_log": ref(V3_LOG, "closed v3 GenCase log"), "v3_definition_evidence": ref(V3_DEFINITION, "historical v3 Definition evidence"), "v4_fresh_definition": ref(definition_path, "new v4 literal Definition"), "v4_adapter": ref(Path(__file__).resolve(), "v4 candidate/contract adapter"), **_parent_bindings_for_candidate(Path(base))},
        "execution_controls": {"definition_writer_invoked": True, "gencase_invoked": False, "native_decoder_invoked": False, "solver_invoked": False, "gpu_invoked": False, "job_created": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False, "qualification_numerator_credit": 0},
        "prohibited_until_root_review": ["GenCase", "native decoder", "solver", "GPU", "job creation", "queue", "ledger", "registry", "matrix submission", "threshold relaxation", "same-input retry"],
    }
    write_json(output, candidate)
    return candidate


def _assert_candidate(candidate: Mapping[str, Any], definition_path: Path) -> None:
    if candidate.get("schema") != SCHEMA_CANDIDATE or candidate.get("candidate_id") != CANDIDATE_ID or candidate.get("case_id") != CASE_ID:
        raise ValueError("v4 candidate identity mismatch")
    if candidate.get("candidate_status") != "root_review_only_static_candidate_not_run" or candidate.get("matrix_credit") != 0:
        raise ValueError("v4 candidate is not static/no-credit")
    identity = candidate.get("new_input_identity", {})
    for key in ("old_anchor_definition_reused", "old_anchor_native_input_reused", "v3_failed_definition_reused", "v3_failed_native_input_reused", "old_trajectory_reused"):
        if identity.get(key) is not False:
            raise ValueError(f"v4 candidate permits reuse: {key}")
    gates = candidate.get("hard_preflight_gates", {})
    if gates.get("zero_boundnor_count_max") != 0 or gates.get("zero_normal_size_count_max") != 0 or gates.get("native_mass_relative_error_max") != MASS_RELATIVE_ERROR_MAX:
        raise ValueError("v4 hard gates changed")
    if candidate.get("denominator_preservation", {}).get("qualification_numerator") != 0:
        raise ValueError("v4 candidate contains credit")
    controls = candidate.get("execution_controls", {})
    for key in ("gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if controls.get(key) is not False:
            raise ValueError(f"v4 candidate records runtime: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if controls.get(key) != 0:
            raise ValueError(f"v4 candidate mutated protected state: {key}")
    inspect_definition(definition_path)


def build_contract(base: Path = DEFAULT_BASE, candidate_path: Path = DEFAULT_CANDIDATE, evidence_path: Path = DEFAULT_EVIDENCE, definition_path: Path = DEFAULT_DEFINITION, output: Path = DEFAULT_CONTRACT, test_path: Path | None = None) -> dict[str, Any]:
    candidate_path = Path(candidate_path).resolve(); evidence_path = Path(evidence_path).resolve(); definition_path = Path(definition_path).resolve()
    candidate = load_json(candidate_path); _assert_candidate(candidate, definition_path); _assert_evidence(evidence_path)
    bindings = {"v4_candidate": ref(candidate_path, "v4 root-review candidate"), "v3_failure_evidence": ref(evidence_path, "closed v3 failure evidence"), "v4_fresh_definition": ref(definition_path, "new v4 literal Definition"), "v4_adapter": ref(Path(__file__).resolve(), "v4 candidate/contract adapter"), **_parent_bindings(Path(base))}
    if test_path is not None:
        bindings["v4_contract_test"] = ref(Path(test_path).resolve(), "v4 static contract test")
    contract = {"schema": SCHEMA_CONTRACT, "created_at_utc": CREATED_AT, "scope_id": SCOPE_ID, "revision_id": REVISION_ID, "candidate_id": CANDIDATE_ID, "case_id": CASE_ID, "parent_failed_case_id": PARENT_V3_CASE_ID, "status": "root_review_only_static_contract_runtime_closed", "decision": "candidate_requires_independent_root_review_before_any_runtime", "authorized_now": False, "proposal_only": True, "qualification_claim": "none", "matrix_credit": 0,
        "authorization": {"cpu_gencase": False, "native_decode": False, "solver_launch": False, "gpu_launch": False, "job_spec_creation": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False},
        "fresh_input": {"definition": ref(definition_path, "new v4 literal Definition"), "generated_prefix": str(DEFAULT_OUTPUT_PREFIX.resolve()), "generated_products_present": False, "native_input_present": False, "old_anchor_definition_reused": False, "old_anchor_native_input_reused": False, "v3_failed_definition_reused": False, "v3_failed_native_input_reused": False},
        "one_hypothesis_review": candidate["one_hypothesis"], "geometry_and_normal_contract": candidate["geometry_and_normal_contract"], "source_lattice_closure": candidate["source_lattice_closure"], "hard_preflight_gates": candidate["hard_preflight_gates"], "preflight": {"status": "not_authorized", "generated_xml_present": False, "native_arrays_present": False, "solver_product_present": False, "qualification_credit": 0}, "failure_denominator": candidate["denominator_preservation"], "hash_bindings": bindings,
        "execution_controls": {"definition_writer_invoked": True, "gencase_invoked": False, "native_decoder_invoked": False, "solver_invoked": False, "gpu_invoked": False, "job_created": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False, "qualification_numerator_credit": 0},
        "blockers": ["v3 closed with 83,443 zero BoundNor and NormalSize entries", "v3 closed at -4.207502092633919% source mass error", "the signed-layer and endpoint correction are predictions only", "any future hard-gate failure falsifies v4 and pauses this F2 route"], "prohibited_until_new_root_review": ["GenCase", "native decoder", "solver", "GPU", "job creation", "queue", "ledger", "registry", "matrix submission", "threshold relaxation", "same-input retry"]}
    if ".bi4" in json.dumps(contract, sort_keys=True).lower():
        raise ValueError("v4 contract must not contain a native input path")
    write_json(output, contract)
    return contract


def verify_contract(contract_path: Path = DEFAULT_CONTRACT, base: Path = DEFAULT_BASE, candidate_path: Path = DEFAULT_CANDIDATE, evidence_path: Path = DEFAULT_EVIDENCE, definition_path: Path = DEFAULT_DEFINITION, test_path: Path | None = None) -> dict[str, Any]:
    contract_path = Path(contract_path).resolve(); contract = load_json(contract_path)
    if contract.get("schema") != SCHEMA_CONTRACT or contract.get("authorized_now") is not False or contract.get("proposal_only") is not True or contract.get("matrix_credit") != 0:
        raise ValueError("v4 contract opened authority/credit")
    auth = contract.get("authorization", {})
    for key in ("cpu_gencase", "native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"v4 contract opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"v4 contract opened {key}")
    candidate_path = Path(candidate_path).resolve(); evidence_path = Path(evidence_path).resolve(); definition_path = Path(definition_path).resolve()
    _assert_candidate(load_json(candidate_path), definition_path); _assert_evidence(evidence_path)
    expected = {"v4_candidate": candidate_path, "v3_failure_evidence": evidence_path, "v4_fresh_definition": definition_path, "v4_adapter": Path(__file__).resolve()}
    if test_path is not None:
        expected["v4_contract_test"] = Path(test_path).resolve()
    bindings = contract.get("hash_bindings", {})
    for key, path in expected.items():
        verify_ref(bindings.get(key, {}), f"v4 contract {key}", path)
    for key, item in _parent_bindings(Path(base)).items():
        verify_ref(bindings.get(key, {}), f"v4 contract {key}", Path(item["path"]))
    fresh = contract.get("fresh_input", {})
    if fresh.get("generated_products_present") is not False or fresh.get("native_input_present") is not False:
        raise ValueError("v4 contract records generated input")
    if contract.get("failure_denominator", {}).get("planned_rows") != EXPECTED_ROWS or contract.get("failure_denominator", {}).get("qualification_numerator") != 0:
        raise ValueError("v4 denominator is not closed")
    if ".bi4" in json.dumps(contract, sort_keys=True).lower():
        raise ValueError("v4 contract contains native input path")
    return contract


def build_report(contract_path: Path = DEFAULT_CONTRACT, candidate_path: Path = DEFAULT_CANDIDATE, evidence_path: Path = DEFAULT_EVIDENCE, definition_path: Path = DEFAULT_DEFINITION, test_path: Path | None = None, output: Path = DEFAULT_REPORT) -> Path:
    contract = verify_contract(contract_path, candidate_path=candidate_path, evidence_path=evidence_path, definition_path=definition_path, test_path=test_path)
    files = [Path(contract_path), Path(candidate_path), Path(evidence_path), Path(definition_path), Path(__file__), V3_PREFLIGHT, V3_BOUND, V3_ACTUAL, V3_LOG, V3_DEFINITION]
    if test_path is not None:
        files.append(Path(test_path))
    lines = ["# F2 submerged-orifice normal remediation v4 root-review-only audit", "", "状态：**全新静态候选；运行权限关闭；无 qualification/matrix credit**。", "", "v3 的固定 CPU/native preflight 已闭合失败：83,443 个 BoundNor 与 NormalSize 零值，outer Mk=17 为 64,899、gate Mk=18 为 18,544；ID/finite/端点门通过，但源质量误差为 -4.207502092633919%。", "", "唯一 v4 假设是一个完整 literal recipe：将 GeometryForNormals 的 outer/gate vdp 分别从 v3 的 `0,1,2`/`0,-1,-2` 镜像为 `0,-1,-2`/`0,1,2`，并将源框端点修正为预测 86×56×48 格点。预测离散质量误差为 +0.78125%；这只是待证伪预测。", "", "若未来经独立 root review 后执行的 exact-one CPU/native preflight 任一 zero-normal、finite/ID、端点或质量门失败，则 v4 被证伪，F2 normal-remediation 路线暂停；不得放宽门槛、重试同输入或授予 credit。", "", "所有 GenCase、native decoder、solver、GPU、job、queue、ledger、registry、matrix 权限均关闭。", "", f"Contract status: `{contract['status']}`。", "", "## Hash closure", ""]
    lines.extend(f"- `{path.resolve()}` SHA-256 `{sha256(path)}` ({path.stat().st_size} bytes)" for path in files)
    lines.append("")
    Path(output).resolve().parent.mkdir(parents=True, exist_ok=True)
    Path(output).resolve().write_text("\n".join(lines), encoding="utf-8")
    return Path(output).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-definition", "write-evidence", "write-candidate", "write-contract", "verify-contract", "write-report"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--test", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write-definition":
        result: Any = write_definition(args.output or args.definition)
    elif args.command == "write-evidence":
        result = build_evidence(args.output or args.evidence)
    elif args.command == "write-candidate":
        result = build_candidate(args.base, args.evidence, args.definition, args.output or args.candidate)
    elif args.command == "write-contract":
        result = build_contract(args.base, args.candidate, args.evidence, args.definition, args.output or args.contract, args.test)
    elif args.command == "verify-contract":
        result = verify_contract(args.output or args.contract, args.base, args.candidate, args.evidence, args.definition, args.test)
    else:
        result = str(build_report(args.contract, args.candidate, args.evidence, args.definition, args.test, args.output or DEFAULT_REPORT))
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) if isinstance(result, dict) else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
