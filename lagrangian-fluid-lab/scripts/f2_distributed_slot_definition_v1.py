#!/usr/bin/env python3
"""Materialize the fresh distributed-slot F2 Definition after root review.

This writer creates a literal XML recipe for the new two-slot gate.  It does
not read or copy a failed orifice Definition and it never calls GenCase, a
native decoder, a solver, CUDA, or the queue.  The subsequent CPU/native step
is a separate command and a separate immutable output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


LAB_ROOT = Path(__file__).resolve().parents[1]
ROOT_REVIEW = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-root-review-v1.json"
PROPOSAL = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-proposal-v1.json"
DEFAULT_BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1"
DP_M = 0.0075
Q = 0.5
SLOT_WIDTH_M = 0.09
CASE_ID = "F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor"
SCHEMA = "core.f2.distributed_slot_transfer.definition_contract.v1"


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


def frame_boxes(slot_width: float = SLOT_WIDTH_M) -> list[tuple[str, tuple[float, float, float], tuple[float, float, float]]]:
    if not 0.06 <= slot_width <= 0.12:
        raise ValueError("slot width outside the registered range")
    y0, y1 = 0.05, 0.55
    c0, c1 = 0.20, 0.40
    left_end = c0 - slot_width / 2.0
    right_start = c1 + slot_width / 2.0
    return [
        ("left_frame", (0.80, y0, 0.04), (0.06, left_end - y0, 0.16)),
        ("central_web", (0.80, c0 + slot_width / 2.0, 0.04), (0.06, c1 - c0 - slot_width, 0.16)),
        ("right_frame", (0.80, right_start, 0.04), (0.06, y1 - right_start, 0.16)),
        ("top_frame", (0.80, y0, 0.20), (0.06, y1 - y0, 0.66)),
    ]


def _root_review() -> dict[str, Any]:
    review = load(ROOT_REVIEW)
    if review.get("schema") != "core.f2.distributed_slot_transfer.root_review_receipt.v1":
        raise ValueError("distributed-slot root review schema mismatch")
    decision = review.get("review_decision", {})
    if decision.get("authorized_action") != "write_one_fresh_literal_definition_then_run_exactly_one_cpu_gencase_native_decode":
        raise ValueError("root review does not authorize the fresh Definition")
    for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_ledger", "authorized_registry", "authorized_matrix"):
        if decision.get(key) is not False:
            raise ValueError(f"root review unexpectedly authorizes {key}")
    return review


def write_definition(output: Path, *, q: float = Q, dp: float = DP_M) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"fresh Definition already exists: {output}")
    if q != Q or dp != DP_M:
        raise ValueError("this first anchor is fixed at q=.5, dp=.0075")
    output.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("case")
    casedef = _sub(root, "casedef")
    constants = _sub(casedef, "constantsdef")
    _sub(constants, "gravity", {"x": "0", "y": "0", "z": "-9.81"})
    for tag, attrs in (("rhop0", {"value": "1000"}), ("rhopgradient", {"value": "2"}),
                       ("hswl", {"value": "0", "auto": "true"}), ("gamma", {"value": "7"}),
                       ("speedsystem", {"value": "0", "auto": "true"}), ("coefsound", {"value": "20"}),
                       ("speedsound", {"value": "0", "auto": "true"}), ("coefh", {"value": "1.0"}),
                       ("cflnumber", {"value": "0.2"})):
        _sub(constants, tag, attrs)
    _sub(casedef, "mkconfig", {"boundcount": "220", "fluidcount": "16"})

    geometry = _sub(casedef, "geometry")
    definition = _sub(geometry, "definition", {"dp": f"{dp:.17g}"})
    _sub(definition, "pointmin", {"x": "-0.30", "y": "-0.20", "z": "-0.20"})
    _sub(definition, "pointmax", {"x": "2.00", "y": "0.80", "z": "1.30"})
    _sub(definition, "pointref", {axis: f"{dp / 2.0:.17g}" for axis in "xyz"})
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
    _drawbox(normals, outer_fill, outer_low, outer_size, "0,1,2")
    _sub(normals, "setmkbound", {"mk": "1"})
    _sub(normals, "setnormalinvert", {"invert": "false"})
    for _name, low, size in frames:
        _drawbox(normals, frame_fill, low, size, "0,1,2")
    _sub(normals, "shapeout", {"file": "hdp"})
    _sub(normals, "resetdraw")

    main = _sub(commands, "mainlist")
    _sub(main, "runlist", {"name": "GeometryForNormals"})
    _sub(main, "setshapemode", text="actual | bound")
    _sub(main, "setdrawmode", {"mode": "full"})
    _sub(main, "setmkbound", {"mk": "0"})
    _drawbox(main, outer_fill, outer_low, outer_size, "0,1,2")
    _sub(main, "setmkbound", {"mk": "1"})
    for _name, low, size in frames:
        _drawbox(main, frame_fill, low, size, "0,-1,-2")
    _sub(main, "setmkfluid", {"mk": "0"})
    # Cell-centre closure for the declared [0.05,.80] × [.05,.55] × [.05,.41] source.
    _drawbox(main, "solid", (0.05375, 0.05375, 0.05375), (0.74625, 0.49625, 0.35625), "")

    normal_block = _sub(casedef, "normals", {"active": "true"})
    norgeometry = _sub(normal_block, "norgeometry")
    _sub(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    _sub(norgeometry, "distanceh", {"v": "3.0"})
    _sub(norgeometry, "svshapes", {"v": "true"})

    execution = _sub(root, "execution")
    parameters = _sub(execution, "parameters")
    values = (
        ("SavePosDouble", "2"), ("Boundary", "2"), ("SlipMode", "1"), ("StepAlgorithm", "2"),
        ("Kernel", "2"), ("ViscoTreatment", "1"), ("Visco", "0.03"), ("ViscoBoundFactor", "1"),
        ("DensityDT", "3"), ("DensityDTvalue", "0.1"), ("Shifting", "0"), ("RigidAlgorithm", "1"),
        ("FtPause", "0"), ("CoefDtMin", "0.05"), ("DtIni", "0"), ("DtMin", "0"),
        ("DtFixed", "0"), ("DtAllParticles", "0"), ("TimeMax", "1.5"), ("TimeOut", "0.01"),
        ("PartsOutMax", "1"), ("RhopOutMin", "700"), ("RhopOutMax", "1300"), ("MinFluidStop", "0"),
        ("NoPenetration", "1"),
    )
    for key, value in values:
        _parameter(parameters, key, value)
    domain = _sub(parameters, "simulationdomain")
    _sub(domain, "posmin", {"x": "-0.30", "y": "-0.20", "z": "-0.20"})
    _sub(domain, "posmax", {"x": "2.00", "y": "0.80", "z": "1.30"})

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return {"path": str(output), "sha256": sha256(output), "bytes": output.stat().st_size, "case_id": CASE_ID}


def write_contract(base: Path = DEFAULT_BASE) -> dict[str, Any]:
    base = Path(base).resolve()
    review = _root_review()
    definition_path = base / "definition" / f"{CASE_ID}_Def.xml"
    if not definition_path.is_file():
        raise FileNotFoundError("write the fresh Definition before writing its contract")
    contract = {
        "schema": SCHEMA,
        "status": "definition_written_cpu_native_preflight_pending",
        "qualification_claim": "none",
        "family": "F2",
        "scope_id": "F2_distributed_submerged_slot_transfer_x_v1",
        "revision_id": "F2_distributed_slot_gate_v1",
        "case_id": CASE_ID,
        "anchor": {"q": Q, "slot_width_m": SLOT_WIDTH_M, "dp_m": DP_M, "time_max_s": 1.5, "output_interval_s": 0.01},
        "root_review": ref(ROOT_REVIEW, "root review authorization"),
        "proposal": ref(PROPOSAL, "distributed-slot proposal"),
        "definition": ref(definition_path, "fresh literal distributed-slot Definition"),
        "fresh_input": {"generated_xml_present": False, "native_bi4_present": False, "old_scope_assets_reused": False},
        "hard_preflight_gates": {"zero_boundnor": 0, "zero_normal_size": 0, "overlap": 0, "endpoints": 0, "chords": 0, "source_mass_relative_error_max": 0.025, "total_mass_relative_error_max": 0.03},
        "execution_controls": {"definition_written": True, "gencase_invoked": False, "native_decoder_invoked": False, "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False, "qualification_credit": 0},
    }
    output = base / "definition" / "definition-contract-v1.json"
    output.write_text(json.dumps(contract, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return contract


def verify_definition(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    root = ET.parse(path).getroot()
    if root.tag != "case":
        raise ValueError("Definition root must be <case>")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or float(definition.get("dp", "nan")) != DP_M:
        raise ValueError("Definition dp mismatch")
    params = {n.get("key"): n.get("value") for n in root.findall("./execution/parameters/parameter")}
    if params.get("Boundary") != "2" or params.get("TimeMax") != "1.5" or params.get("TimeOut") != "0.01":
        raise ValueError("Definition numerical contract mismatch")
    commands = root.find("./casedef/geometry/commands")
    normals = commands.find("list[@name='GeometryForNormals']") if commands is not None else None
    main = commands.find("mainlist") if commands is not None else None
    if normals is None or main is None or len(normals.findall("drawbox")) != 5 or len(main.findall("drawbox")) != 6:
        raise ValueError("Definition does not contain outer shell plus four frame boxes and source")
    slots = frame_boxes()
    if slots[1][1][1] >= slots[1][1][1] + slots[1][2][1]:
        raise ValueError("central web has invalid width")
    if root.find("./casedef/normals/norgeometry") is None:
        raise ValueError("normal geometry block missing")
    return {"status": "definition_static_contract_pass", "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "case_id": CASE_ID, "frame_count": 4}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "verify"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--definition", type=Path)
    args = parser.parse_args(argv)
    definition = (Path(args.definition).resolve() if args.definition else Path(args.base).resolve() / "definition" / f"{CASE_ID}_Def.xml")
    if args.command == "write":
        record = write_definition(definition)
        contract = write_contract(args.base)
        print(json.dumps({"definition": record, "contract": str(Path(args.base).resolve() / "definition/definition-contract-v1.json"), "qualification_credit": 0}, ensure_ascii=False))
    else:
        print(json.dumps(verify_definition(definition), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
