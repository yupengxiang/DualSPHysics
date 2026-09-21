#!/usr/bin/env python3
"""Materialize the v2 distributed-slot normal-layer repair Definition."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET

# Direct script execution needs the lab root on sys.path.
LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.f2_distributed_slot_definition_v1 import frame_boxes
from scripts.f2_distributed_slot_normal_root_review_v2 import PROPOSAL, DEFAULT_OUTPUT as ROOT_REVIEW, verify_proposal


BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/normal-repair-v2"
DEFINITION = BASE / "definition/F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor_v2_Def.xml"
CONTRACT = BASE / "definition/definition-contract-v2.json"
DP_M = 0.0075
CASE_ID = "F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor_v2"
SCHEMA = "core.f2.distributed_slot_transfer.normal_definition_contract.v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _sub(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs or {})
    if text is not None:
        node.text = text
    return node


def _drawbox(parent: ET.Element, fill: str, low: tuple[float, float, float], size: tuple[float, float, float], layers: str) -> ET.Element:
    node = _sub(parent, "drawbox")
    _sub(node, "boxfill", text=fill)
    _sub(node, "point", {axis: f"{value:.17g}" for axis, value in zip("xyz", low)})
    _sub(node, "size", {axis: f"{value:.17g}" for axis, value in zip("xyz", size)})
    _sub(node, "layers", {"vdp": layers})
    return node


def _parameter(parent: ET.Element, key: str, value: str) -> None:
    _sub(parent, "parameter", {"key": key, "value": value})


def write_definition(path: Path = DEFINITION) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(path)
    verify_proposal()
    path.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("case")
    casedef = _sub(root, "casedef")
    constants = _sub(casedef, "constantsdef")
    for tag, attrs in (("gravity", {"x": "0", "y": "0", "z": "-9.81"}), ("rhop0", {"value": "1000"}), ("rhopgradient", {"value": "2"}), ("hswl", {"value": "0", "auto": "true"}), ("gamma", {"value": "7"}), ("speedsystem", {"value": "0", "auto": "true"}), ("coefsound", {"value": "20"}), ("speedsound", {"value": "0", "auto": "true"}), ("coefh", {"value": "1.0"}), ("cflnumber", {"value": "0.2"})):
        _sub(constants, tag, attrs)
    _sub(casedef, "mkconfig", {"boundcount": "220", "fluidcount": "16"})
    geometry = _sub(casedef, "geometry")
    definition = _sub(geometry, "definition", {"dp": f"{DP_M:.17g}"})
    _sub(definition, "pointmin", {"x": "-0.30", "y": "-0.20", "z": "-0.20"})
    _sub(definition, "pointmax", {"x": "2.00", "y": "0.80", "z": "1.30"})
    _sub(definition, "pointref", {axis: f"{DP_M / 2.0:.17g}" for axis in "xyz"})
    commands = _sub(geometry, "commands")
    outer_fill = "bottom | left | right | front | back"
    frame_fill = "bottom | top | left | right | front | back"
    outer_low = (0.0, 0.0, 0.0)
    outer_size = (1.8, 0.6, 0.9)
    frames = frame_boxes()

    normals = _sub(commands, "list", {"name": "GeometryForNormals"})
    _sub(normals, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    _sub(normals, "setshapemode", text="actual | bound")
    _sub(normals, "setnormalinvert", {"invert": "true"})
    _sub(normals, "setmkbound", {"mk": "0"})
    _drawbox(normals, outer_fill, outer_low, outer_size, "0,-1,-2")
    _sub(normals, "setmkbound", {"mk": "1"})
    _sub(normals, "setnormalinvert", {"invert": "false"})
    for _name, low, size in frames:
        _drawbox(normals, frame_fill, low, size, "0,-1,-2")
    _sub(normals, "shapeout", {"file": "hdp"})
    _sub(normals, "resetdraw")

    main = _sub(commands, "mainlist")
    _sub(main, "runlist", {"name": "GeometryForNormals"})
    _sub(main, "setshapemode", text="actual | bound")
    _sub(main, "setdrawmode", {"mode": "full"})
    _sub(main, "setmkbound", {"mk": "0"})
    _drawbox(main, outer_fill, outer_low, outer_size, "0,-1,-2")
    _sub(main, "setmkbound", {"mk": "1"})
    for _name, low, size in frames:
        _drawbox(main, frame_fill, low, size, "0,-1,-2")
    _sub(main, "setmkfluid", {"mk": "0"})
    _drawbox(main, "solid", (0.05375, 0.05375, 0.05375), (0.74625, 0.49625, 0.35625), "")

    normal_block = _sub(casedef, "normals", {"active": "true"})
    norgeometry = _sub(normal_block, "norgeometry")
    _sub(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    _sub(norgeometry, "distanceh", {"v": "3.0"})
    _sub(norgeometry, "svshapes", {"v": "true"})

    execution = _sub(root, "execution")
    parameters = _sub(execution, "parameters")
    for key, value in (("SavePosDouble", "2"), ("Boundary", "2"), ("SlipMode", "1"), ("StepAlgorithm", "2"), ("Kernel", "2"), ("ViscoTreatment", "1"), ("Visco", "0.03"), ("ViscoBoundFactor", "1"), ("DensityDT", "3"), ("DensityDTvalue", "0.1"), ("Shifting", "0"), ("RigidAlgorithm", "1"), ("FtPause", "0"), ("CoefDtMin", "0.05"), ("DtIni", "0"), ("DtMin", "0"), ("DtFixed", "0"), ("DtAllParticles", "0"), ("TimeMax", "1.5"), ("TimeOut", "0.01"), ("PartsOutMax", "1"), ("RhopOutMin", "700"), ("RhopOutMax", "1300"), ("MinFluidStop", "0"), ("NoPenetration", "1")):
        _parameter(parameters, key, value)
    domain = _sub(parameters, "simulationdomain")
    _sub(domain, "posmin", {"x": "-0.30", "y": "-0.20", "z": "-0.20"})
    _sub(domain, "posmax", {"x": "2.00", "y": "0.80", "z": "1.30"})
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "case_id": CASE_ID}


def write_contract(base: Path = BASE) -> dict[str, Any]:
    base = Path(base).resolve()
    review = load(ROOT_REVIEW)
    if review.get("status") != "authorized_one_fresh_definition_and_cpu_native_preflight_only":
        raise ValueError("v2 root review is not active")
    if not DEFINITION.is_file():
        raise FileNotFoundError(DEFINITION)
    value = {"schema": SCHEMA, "status": "definition_written_cpu_native_preflight_pending", "qualification_claim": "none", "family": "F2", "scope_id": "F2_distributed_submerged_slot_transfer_x_v1", "revision_id": "F2_distributed_slot_gate_normal_layers_v2", "case_id": CASE_ID, "root_review": ref(ROOT_REVIEW, "v2 root review"), "proposal": ref(PROPOSAL, "v2 proposal"), "definition": ref(DEFINITION, "fresh v2 literal Definition"), "normal_layers_vdp": "0,-1,-2", "fresh_input": {"generated_xml_present": False, "native_bi4_present": False, "old_v1_assets_reused": False}, "hard_preflight_gates": {"zero_boundnor": 0, "zero_normal_size": 0, "source_mass_relative_error_max": 0.025, "total_mass_relative_error_max": 0.03}, "execution_controls": {"definition_written": True, "gencase_invoked": False, "native_decoder_invoked": False, "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False, "qualification_credit": 0}}
    output = base / "definition/definition-contract-v2.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "verify"))
    args = parser.parse_args(argv)
    if args.command == "write":
        record = write_definition()
        contract = write_contract()
        print(json.dumps({"definition": record, "contract": str(CONTRACT), "qualification_credit": 0}, ensure_ascii=False))
    else:
        root = ET.parse(DEFINITION).getroot()
        layers = [x.find("layers").get("vdp") for x in root.findall("./casedef/geometry/commands/list[@name='GeometryForNormals']/drawbox")]
        print(json.dumps({"status": "definition_static_contract_pass", "normal_layers": layers, "qualification_credit": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
