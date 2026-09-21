#!/usr/bin/env python3
"""Write and statically verify the fresh v2 submerged-orifice Definition.

The writer constructs XML from literal v2 geometry constants.  It never reads
the failed anchor Definition or BI4, never invokes GenCase/native decoding,
and never launches or mutates any runtime/job state.  Its output is a static
definition proposal only; CPU/native authorization remains closed elsewhere.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.f2_submerged_orifice_scope_v1 import (  # noqa: E402
    DEFAULT_BASE,
    EXPECTED_ROWS,
    load_json,
    verify_bundle,
)
from scripts.f2_submerged_orifice_normal_remediation_v2 import (  # noqa: E402
    CASE_ID,
    DEFAULT_AUDIT,
    DEFAULT_CANDIDATE,
    DEFAULT_CONTRACT as PARENT_REMEDIATION_CONTRACT,
    DEFAULT_PROPOSAL as PARENT_CPU_PROPOSAL,
    REVISION_ID,
)


SCHEMA_PROPOSAL = "core.f2.submerged_orifice_transfer.fresh_definition_proposal.v2"
SCHEMA_CONTRACT = "core.f2.submerged_orifice_transfer.fresh_definition_contract.v2"
CREATED_AT = "2026-09-21T00:00:00+00:00"
DP_M = 0.0075
Q = 0.5
ORIFICE_HEIGHT_M = 0.18
ZERO_NORMAL_TOLERANCE_M = 1.0e-12

REMEDIATION_DIR = DEFAULT_BASE / "normal-remediation-v2"
FRESH_DIR = REMEDIATION_DIR / "fresh-definition-v2"
DEFAULT_DEFINITION = FRESH_DIR / f"{CASE_ID}_Def.xml"
DEFAULT_PROPOSAL = REMEDIATION_DIR / "fresh-definition-proposal-v2.json"
DEFAULT_CONTRACT = REMEDIATION_DIR / "fresh-definition-contract-v2.json"
FAILED_ANCHOR_DIR = DEFAULT_BASE / "anchor-q0p5-dp0p0075"

OUTER_LOW = [0.0, 0.0, 0.0]
OUTER_SIZE = [1.6, 0.5, 0.8]
GATE_LOW = [0.72, 0.04, 0.18]
GATE_SIZE = [0.06, 0.42, 0.62]
GATE_VOID_LOW = [0.71625, 0.03625, 0.17625]
GATE_VOID_SIZE = [0.0675, 0.4275, 0.6275]
GATE_BOUND_LOW = [0.72375, 0.04375, 0.18375]
GATE_BOUND_SIZE = [0.0525, 0.4125, 0.6125]
SOURCE_LOW = [0.04, 0.04, 0.04]
SOURCE_SIZE = [0.64, 0.42, 0.36]
SOURCE_FIRST_CENTER = [value + DP_M / 2.0 for value in SOURCE_LOW]
SOURCE_DRAW_SIZE = [value - DP_M / 2.0 for value in SOURCE_SIZE]


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _verify_ref(item: dict[str, Any], label: str, expected_path: Path | None = None) -> Path:
    path = Path(item.get("path", "")).resolve()
    if expected_path is not None and path != Path(expected_path).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path):
        raise ValueError(f"{label}: SHA mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: byte count mismatch")
    return path


def _sub(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None,
         text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs or {})
    if text is not None:
        node.text = text
    return node


def _drawbox(parent: ET.Element, fill: str, low: list[float], size: list[float],
             layers: str | None = None) -> ET.Element:
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
    """Write a fresh literal v2 Definition without reading any prior XML."""
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f"fresh definition path already exists: {target}")
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
    _drawbox(normals_list, "all^top", OUTER_LOW, OUTER_SIZE, "0")
    _sub(normals_list, "setmkbound", {"mk": "1"})
    _sub(normals_list, "setnormalinvert", {"invert": "false"})
    _drawbox(normals_list, "bottom | top | left | right | front | back", GATE_LOW, GATE_SIZE, "0")
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


def _attrs(node: ET.Element, *keys: str) -> tuple[str | None, ...]:
    return tuple(node.get(key) for key in keys)


def inspect_definition(path: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    """Static XML audit of the new Definition's exact normal/geometry recipe."""
    path = Path(path).resolve()
    root = ET.parse(path).getroot()
    if root.tag != "case":
        raise ValueError("fresh Definition root must be <case>")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or float(definition.get("dp", "nan")) != DP_M:
        raise ValueError("fresh Definition dp mismatch")
    commands = root.find("./casedef/geometry/commands")
    normal_list = commands.find("list[@name='GeometryForNormals']") if commands is not None else None
    main = commands.find("mainlist") if commands is not None else None
    if normal_list is None or main is None:
        raise ValueError("fresh Definition missing normal list/mainlist")
    normal_drawboxes = normal_list.findall("drawbox")
    if len(normal_drawboxes) != 2:
        raise ValueError("fresh normal list must contain outer and gate drawboxes")
    normal_fills = [(node.findtext("boxfill") or "").strip() for node in normal_drawboxes]
    normal_layers = [node.find("layers") for node in normal_drawboxes]
    if normal_fills != ["all^top", "bottom | top | left | right | front | back"]:
        raise ValueError("fresh normal list face contract mismatch")
    if any(node is None or node.get("vdp") != "0" for node in normal_layers):
        raise ValueError("fresh normal list must use vdp=0 for both roles")
    runlist = main.find("runlist")
    if runlist is None or runlist.get("name") != "GeometryForNormals" or list(main).index(runlist) != 0:
        raise ValueError("normal runlist is not first in mainlist")
    drawboxes = main.findall("drawbox")
    if len(drawboxes) != 4:
        raise ValueError("fresh mainlist must contain outer, void, gate, and source drawboxes")
    sequence = [node.tag for node in list(main)]
    expected_sequence = ["runlist", "setshapemode", "setdrawmode", "setmkbound", "drawbox", "setmkvoid", "drawbox", "setmkbound", "drawbox", "setmkfluid", "drawbox"]
    if sequence != expected_sequence:
        raise ValueError(f"fresh mainlist sequence mismatch: {sequence}")
    outer_layers = drawboxes[0].find("layers")
    gate_layers = drawboxes[2].find("layers")
    if outer_layers is None or outer_layers.get("vdp") != "0,1,2":
        raise ValueError("fresh outer shell layer contract mismatch")
    if gate_layers is None or gate_layers.get("vdp") != "0,-1,-2":
        raise ValueError("fresh gate shell layer contract mismatch")
    if drawboxes[1].find("layers") is not None or drawboxes[3].find("layers") is not None:
        raise ValueError("void/source drawboxes must not carry boundary layers")
    normals = root.find("./casedef/normals")
    norgeometry = normals.find("norgeometry") if normals is not None else None
    if (normals is None or normals.get("active") != "true" or norgeometry is None
            or norgeometry.find("geometryfile").get("file") != "[CaseName]_hdp_Actual.vtk"
            or norgeometry.find("distanceh").get("v") != "3.0"
            or norgeometry.find("svshapes").get("v") != "true"):
        raise ValueError("fresh mDBC normal block mismatch")
    parameters = root.findall("./execution/parameters/parameter")
    parameter_map = {node.get("key"): node.get("value") for node in parameters}
    for key, value in (("Boundary", "2"), ("SlipMode", "1"), ("NoPenetration", "1")):
        if parameter_map.get(key) != value:
            raise ValueError(f"fresh parameter {key} mismatch")
    return {
        "definition_sha256": sha256(path),
        "definition_bytes": path.stat().st_size,
        "case_id": CASE_ID,
        "dp_m": DP_M,
        "normal_list": {
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
        "normal_block": {"active": True, "distanceh": 3.0, "svshapes": True},
        "runtime_invoked": False,
    }


def _parent_refs(base: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    paths = {
        "candidate": base / "candidate-card-v1.json",
        "matrix": base / "fixed-matrix-v1.json",
        "failure": base / "failure-denominator-v1.json",
        "lineage": base / "lineage-clarification-v1.json",
        "root_contract": base / "root-review-contract-v1.json",
        "failed_preflight": base / "anchor-q0p5-dp0p0075/preflight.json",
    }
    bundle = verify_bundle(base)
    if bundle.get("fixed_matrix", {}).get("rows") != EXPECTED_ROWS or bundle.get("fixed_matrix", {}).get("all_not_started") is not True:
        raise ValueError("parent 15-row matrix is not closed")
    return {
        "parent_candidate": _ref(paths["candidate"], "parent candidate"),
        "parent_matrix": _ref(paths["matrix"], "parent 15-row matrix"),
        "parent_failure_denominator": _ref(paths["failure"], "parent full denominator"),
        "parent_lineage": _ref(paths["lineage"], "parent lineage"),
        "parent_root_contract": _ref(paths["root_contract"], "parent root contract"),
        "failed_anchor_preflight": _ref(paths["failed_preflight"], "failed anchor noncredit evidence"),
        "v2_candidate": _ref(DEFAULT_CANDIDATE, "v2 normal remediation candidate"),
        "v2_cpu_proposal": _ref(PARENT_CPU_PROPOSAL, "v2 CPU-only proposal"),
        "v2_remediation_contract": _ref(PARENT_REMEDIATION_CONTRACT, "v2 remediation contract"),
        "v2_boundnor_audit": _ref(DEFAULT_AUDIT, "v2 BoundNor partition audit"),
        "definition_writer": _ref(Path(__file__).resolve(), "fresh Definition writer"),
    }


def build_proposal(base: Path = DEFAULT_BASE, definition: Path = DEFAULT_DEFINITION,
                   output: Path = DEFAULT_PROPOSAL) -> dict[str, Any]:
    definition = Path(definition).resolve()
    inspection = inspect_definition(definition)
    refs = _parent_refs(Path(base))
    proposal = {
        "schema": SCHEMA_PROPOSAL,
        "created_at_utc": CREATED_AT,
        "scope_id": "F2_submerged_orifice_transfer_v1",
        "revision_id": REVISION_ID,
        "status": "fresh_definition_written_static_only_not_runtime_preflighted",
        "authorized_now": False,
        "case_id": CASE_ID,
        "q": Q,
        "dp_m": DP_M,
        "orifice_height_m": ORIFICE_HEIGHT_M,
        "fresh_input_identity": {
            "definition": _ref(definition, "fresh literal v2 Definition"),
            "writer": _ref(Path(__file__).resolve(), "fresh Definition writer"),
            "old_anchor_definition_reused": False,
            "old_anchor_bi4_reused": False,
            "old_anchor_trajectory_reused": False,
            "old_anchor_path": str(FAILED_ANCHOR_DIR.resolve()),
            "new_generated_prefix": str((FRESH_DIR / "generated" / CASE_ID).resolve()),
            "new_native_bi4_present": False,
        },
        "definition_contract": inspection,
        "normal_remediation_contract": {
            "geometry_for_normals_outer_vdp": "0",
            "geometry_for_normals_gate_vdp": "0",
            "outer_main_layers": "0,1,2",
            "gate_void_precursor": True,
            "gate_main_layers": "0,-1,-2",
            "zero_normal_hard_threshold_m": ZERO_NORMAL_TOLERANCE_M,
        },
        "execution_controls": {
            "definition_writer_invoked": True,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
        "qualification": {
            "claim": "none",
            "matrix_credit": 0,
            "T1_credit": 0,
            "preflight_status": "not_run",
        },
        "denominator": {
            "planned": EXPECTED_ROWS,
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "unattempted": EXPECTED_ROWS,
            "credit": 0,
            "same_input_retry": False,
            "threshold_relaxation": False,
        },
        "hash_bindings": refs,
        "prohibited_until_new_root_review": [
            "GenCase", "native decoder", "solver", "GPU", "job creation", "queue", "ledger", "registry", "matrix submission",
        ],
    }
    write_json(output, proposal)
    return proposal


def build_contract(base: Path = DEFAULT_BASE, definition: Path = DEFAULT_DEFINITION,
                   proposal: Path = DEFAULT_PROPOSAL,
                   output: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    definition = Path(definition).resolve()
    proposal = Path(proposal).resolve()
    proposal_data = load_json(proposal)
    if proposal_data.get("schema") != SCHEMA_PROPOSAL or proposal_data.get("authorized_now") is not False:
        raise ValueError("fresh definition proposal is not static-only")
    inspection = inspect_definition(definition)
    contract = {
        "schema": SCHEMA_CONTRACT,
        "created_at_utc": CREATED_AT,
        "scope_id": "F2_submerged_orifice_transfer_v1",
        "revision_id": REVISION_ID,
        "status": "fresh_definition_static_contract_not_runtime_authorized",
        "decision": "fresh_definition_writer_reviewable_cpu_native_still_closed",
        "case_id": CASE_ID,
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
        "fresh_definition": {
            "definition": _ref(definition, "fresh literal v2 Definition"),
            "proposal": _ref(proposal, "fresh Definition proposal"),
            "writer": _ref(Path(__file__).resolve(), "fresh Definition writer"),
            "xml_contract": inspection,
            "old_anchor_definition_reused": False,
            "old_anchor_bi4_reused": False,
        },
        "hash_bindings": _parent_refs(Path(base)),
        "preflight": {
            "status": "not_run",
            "fresh_generated_xml_present": False,
            "fresh_native_bi4_present": False,
            "solver_product_present": False,
            "cpu_native_credit": 0,
        },
        "failure_denominator": {
            "planned_rows": EXPECTED_ROWS,
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "unattempted_rows": EXPECTED_ROWS,
            "qualification_numerator": 0,
            "same_input_retry": False,
            "threshold_relaxation": False,
            "survivor_renormalization": False,
        },
        "execution_controls": {
            "definition_writer_invoked": True,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
        "blockers": [
            "No GenCase/native preflight has been run for the new definition.",
            "Zero-normal hard gate remains exact at norm <= 1e-12 m.",
            "No solver, GPU, queue, ledger, registry, or qualification authority is granted.",
        ],
    }
    write_json(output, contract)
    return contract


def verify_contract(contract_path: Path = DEFAULT_CONTRACT,
                    proposal_path: Path = DEFAULT_PROPOSAL,
                    definition_path: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    contract = load_json(Path(contract_path).resolve())
    if contract.get("schema") != SCHEMA_CONTRACT or contract.get("authorization", {}).get("cpu_gencase") is not False:
        raise ValueError("fresh Definition contract schema/authorization mismatch")
    for key in ("native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if contract["authorization"].get(key) is not False:
            raise ValueError(f"fresh Definition contract opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if contract["authorization"].get(key) != 0:
            raise ValueError(f"fresh Definition contract opened {key}")
    _verify_ref(contract["fresh_definition"]["definition"], "contract Definition", Path(definition_path))
    _verify_ref(contract["fresh_definition"]["proposal"], "contract proposal", Path(proposal_path))
    _verify_ref(contract["fresh_definition"]["writer"], "contract writer", Path(__file__))
    inspect_definition(Path(definition_path))
    if contract.get("fresh_definition", {}).get("old_anchor_definition_reused") is not False:
        raise ValueError("contract reuses old Definition")
    if contract.get("fresh_definition", {}).get("old_anchor_bi4_reused") is not False:
        raise ValueError("contract reuses old BI4")
    if contract.get("failure_denominator", {}).get("planned_rows") != EXPECTED_ROWS:
        raise ValueError("contract denominator changed")
    text = json.dumps(contract, sort_keys=True)
    if ".bi4" in text:
        raise ValueError("fresh Definition contract must not bind a BI4 path")
    return contract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-definition", "write-proposal", "write-contract", "verify-contract"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args(argv)
    if args.command == "write-definition":
        result = write_definition(args.definition)
    elif args.command == "write-proposal":
        result = build_proposal(args.base, args.definition, args.proposal)
    elif args.command == "write-contract":
        result = build_contract(args.base, args.definition, args.proposal, args.contract)
    else:
        result = verify_contract(args.contract, args.proposal, args.definition)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
