#!/usr/bin/env python3
"""Write and statically inspect the fresh F2 receiver/catch Definition.

The writer is intentionally literal.  It does not read or transform an old
F2 Definition, generated XML, BI4 file, trajectory, or runtime record.  It
only materializes the new input after the separate root-review receipt has
authorized the path; GenCase/native decoding are handled by the preflight
runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1"
INPUT = BASE / "input"
CASE_ID = "CORE_F2_STATIC_RECEIVER_BALLISTIC_CATCH_q0p50000000_dp0p007500000000_anchor"
DEFAULT_DEFINITION = INPUT / f"{CASE_ID}_Def.xml"
DEFAULT_CONTRACT = INPUT / "definition-contract-v1.json"
DP_M = 0.0075
Q = 0.5
TIME_MAX_S = 1.5
OUTPUT_INTERVAL_S = 0.005
INITIAL_VELOCITY = (0.0, 0.0, -0.2)

OUTER_LOW = (0.0, -0.45, 0.0)
OUTER_SIZE = (1.25, 0.90, 0.80)
RECEIVER_LOW = (0.35, -0.18, 0.08)
RECEIVER_SIZE = (0.50, 0.36, 0.50)
SOURCE_LOW = (0.48, -0.09, 0.65)
SOURCE_SIZE = (0.24, 0.18, 0.18)
RUNTIME_LOW = (-0.15, -0.55, -0.15)
RUNTIME_HIGH = (1.40, 0.55, 1.05)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _sub(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None,
         text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs or {})
    if text is not None:
        node.text = text
    return node


def _drawbox(parent: ET.Element, fill: str, low: tuple[float, float, float],
             size: tuple[float, float, float]) -> ET.Element:
    node = _sub(parent, "drawbox")
    _sub(node, "boxfill", text=fill)
    _sub(node, "point", {axis: f"{value:.17g}" for axis, value in zip("xyz", low)})
    _sub(node, "size", {axis: f"{value:.17g}" for axis, value in zip("xyz", size)})
    return node


def _parameter(parent: ET.Element, key: str, value: str | float | int) -> None:
    _sub(parent, "parameter", {"key": key, "value": str(value)})


def _cell_centred_box(low: tuple[float, float, float], size: tuple[float, float, float]) -> tuple[tuple[float, ...], tuple[float, ...], tuple[int, ...]]:
    """Return the explicit native centre lattice and its draw extent."""
    import math
    first = tuple(math.ceil(value / DP_M - 0.5 - 1.0e-10) for value in low)
    counts = tuple(max(1, int(round(value / DP_M))) for value in size)
    centre = tuple((index + 0.5) * DP_M for index in first)
    extent = tuple((count - 1) * DP_M for count in counts)
    return centre, extent, counts


def write_definition(target: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f"fresh Definition already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    source_centre, source_draw_size, counts = _cell_centred_box(SOURCE_LOW, SOURCE_SIZE)
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
    _sub(definition, "pointmin", {axis: f"{value:.17g}" for axis, value in zip("xyz", RUNTIME_LOW)})
    _sub(definition, "pointmax", {axis: f"{value:.17g}" for axis, value in zip("xyz", RUNTIME_HIGH)})
    commands = _sub(geometry, "commands")
    main = _sub(commands, "mainlist")
    _sub(main, "setshapemode", text="dp | bound")
    _sub(main, "setdrawmode", {"mode": "full"})
    _sub(main, "setmkbound", {"mk": "0"})
    _drawbox(main, "bottom | left | right | front | back", OUTER_LOW, OUTER_SIZE)
    _sub(main, "setmkbound", {"mk": "1"})
    _drawbox(main, "bottom | left | right | front | back", RECEIVER_LOW, RECEIVER_SIZE)
    _sub(main, "setmkfluid", {"mk": "0"})
    _drawbox(main, "solid", source_centre, source_draw_size)

    initials = _sub(casedef, "initials")
    _sub(initials, "velocity", {"mkfluid": "0", "x": f"{INITIAL_VELOCITY[0]:.17g}",
                                  "y": f"{INITIAL_VELOCITY[1]:.17g}",
                                  "z": f"{INITIAL_VELOCITY[2]:.17g}"})

    execution = _sub(root, "execution")
    parameters = _sub(execution, "parameters")
    for key, value in (
        ("SavePosDouble", "2"), ("Boundary", "1"), ("SlipMode", "1"),
        ("StepAlgorithm", "2"), ("Kernel", "2"), ("ViscoTreatment", "1"),
        ("Visco", "0.03"), ("ViscoBoundFactor", "1"), ("DensityDT", "2"),
        ("DensityDTvalue", "0.1"), ("Shifting", "0"), ("RigidAlgorithm", "1"),
        ("FtPause", "0"), ("CoefDtMin", "0.05"), ("DtIni", "0"),
        ("DtMin", "0"), ("DtFixed", "0"), ("DtAllParticles", "0"),
        ("TimeMax", f"{TIME_MAX_S:.17g}"), ("TimeOut", f"{OUTPUT_INTERVAL_S:.17g}"),
        ("PartsOutMax", "1"), ("MinFluidStop", "0"), ("RhopOutMin", "700"),
        ("RhopOutMax", "1300"),
    ):
        _parameter(parameters, key, value)
    domain = _sub(parameters, "simulationdomain")
    _sub(domain, "posmin", {axis: f"{value:.17g}" for axis, value in zip("xyz", RUNTIME_LOW)})
    _sub(domain, "posmax", {axis: f"{value:.17g}" for axis, value in zip("xyz", RUNTIME_HIGH)})

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return inspect_definition(target)


def inspect_definition(path: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    path = Path(path).resolve()
    root = ET.parse(path).getroot()
    if root.tag != "case":
        raise ValueError("Definition root must be case")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or abs(float(definition.get("dp", "nan")) - DP_M) > 1e-12:
        raise ValueError("Definition dp mismatch")
    pointmin = definition.find("pointmin")
    pointmax = definition.find("pointmax")
    if pointmin is None or pointmax is None:
        raise ValueError("Definition domain is incomplete")
    if tuple(float(pointmin.get(a, "nan")) for a in "xyz") != RUNTIME_LOW:
        raise ValueError("runtime lower domain mismatch")
    if tuple(float(pointmax.get(a, "nan")) for a in "xyz") != RUNTIME_HIGH:
        raise ValueError("runtime upper domain mismatch")
    main = root.find("./casedef/geometry/commands/mainlist")
    if main is None:
        raise ValueError("mainlist missing")
    sequence = [node.tag for node in list(main)]
    expected = ["setshapemode", "setdrawmode", "setmkbound", "drawbox",
                "setmkbound", "drawbox", "setmkfluid", "drawbox"]
    if sequence != expected:
        raise ValueError(f"geometry command sequence mismatch: {sequence}")
    boxes = main.findall("drawbox")
    fills = [(box.findtext("boxfill") or "").strip() for box in boxes]
    if fills != ["bottom | left | right | front | back",
                 "bottom | left | right | front | back", "solid"]:
        raise ValueError("geometry face contract mismatch")
    def box_values(box: ET.Element) -> tuple[tuple[float, ...], tuple[float, ...]]:
        point, size = box.find("point"), box.find("size")
        if point is None or size is None:
            raise ValueError("drawbox missing point or size")
        return (tuple(float(point.get(a, "nan")) for a in "xyz"),
                tuple(float(size.get(a, "nan")) for a in "xyz"))
    observed = [box_values(box) for box in boxes]
    if observed[:2] != [(OUTER_LOW, OUTER_SIZE), (RECEIVER_LOW, RECEIVER_SIZE)]:
        raise ValueError("outer/receiver geometry mismatch")
    source_centre, source_draw_size, counts = _cell_centred_box(SOURCE_LOW, SOURCE_SIZE)
    if observed[2] != (source_centre, source_draw_size):
        raise ValueError("source lattice geometry mismatch")
    velocity = root.find("./casedef/initials/velocity")
    if velocity is None or tuple(float(velocity.get(a, "nan")) for a in "xyz") != INITIAL_VELOCITY:
        raise ValueError("initial velocity mismatch")
    params = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    if abs(float(params.get("TimeMax", "nan")) - TIME_MAX_S) > 1e-12:
        raise ValueError("TimeMax mismatch")
    if abs(float(params.get("TimeOut", "nan")) - OUTPUT_INTERVAL_S) > 1e-12:
        raise ValueError("TimeOut mismatch")
    if params.get("Boundary") != "1":
        raise ValueError("native DBC Boundary=1 is required")
    return {
        "schema": "core.f2.static_receiver_ballistic_catch.definition.v1",
        "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size,
        "case_id": CASE_ID, "family": "F2", "scope_id": "F2_static_receiver_ballistic_catch_x_v1",
        "q": Q, "dp_m": DP_M, "time_max_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "outer_low_m": list(OUTER_LOW), "outer_size_m": list(OUTER_SIZE),
        "receiver_low_m": list(RECEIVER_LOW), "receiver_size_m": list(RECEIVER_SIZE),
        "source_low_m": list(SOURCE_LOW), "source_size_m": list(SOURCE_SIZE),
        "source_first_center_m": list(source_centre), "source_draw_size_m": list(source_draw_size),
        "source_counts": list(counts), "source_particle_count": int(counts[0] * counts[1] * counts[2]),
        "initial_velocity_mps": list(INITIAL_VELOCITY), "mass_policy": "native rho*dp^3; no mass rescaling",
        "runtime_domain_low_m": list(RUNTIME_LOW), "runtime_domain_high_m": list(RUNTIME_HIGH),
        "qualification_claim": "none; fresh input only",
    }


def write_contract(definition: Path = DEFAULT_DEFINITION, output: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    definition = Path(definition).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"contract already exists: {output}")
    contract = inspect_definition(definition)
    contract.update({
        "schema": "core.f2.static_receiver_ballistic_catch.definition_contract.v1",
        "definition_sha256": contract["sha256"],
        "created_by": str(Path(__file__).resolve()),
        "writer_sha256": sha256(Path(__file__).resolve()),
        "fresh_input": True, "source_reuse": False, "qualification_inheritance": False,
        "same_input_retry": False, "solver_launch": False, "gpu_launch": False,
        "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0,
        "matrix_credit": 0,
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {"path": str(output), "sha256": sha256(output), "bytes": output.stat().st_size,
            "definition_sha256": contract["sha256"], "qualification_claim": "none"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("write-definition"); p.add_argument("--output", type=Path, default=DEFAULT_DEFINITION)
    p = sub.add_parser("inspect"); p.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    p = sub.add_parser("write-contract"); p.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION); p.add_argument("--output", type=Path, default=DEFAULT_CONTRACT)
    p = sub.add_parser("verify"); p.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    args = parser.parse_args()
    if args.command == "write-definition": result = write_definition(args.output)
    elif args.command == "inspect" or args.command == "verify": result = inspect_definition(args.definition)
    else: result = write_contract(args.definition, args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
