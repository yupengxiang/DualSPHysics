#!/usr/bin/env python3
"""Materialize and inspect the fresh F2 release-speed v2 Definition.

The v2 Definition is authored as a new literal XML document.  It does not
read, copy, transform, or hash-bind the v1 Definition, generated XML/BI4,
trajectory, or solver output.  The only scientific change from the selected
proposal is the prescribed source velocity ``-0.10 m/s``; the new case and
output namespace are independent of the failed v1 anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-release010-v2"
INPUT = BASE / "input"
CASE_ID = "CORE_F2_RECEIVER_BALLISTIC_CATCH_RELEASE010_q0p50000000_dp0p007500000000_anchor"
DEFAULT_DEFINITION = INPUT / f"{CASE_ID}_Def.xml"
DEFAULT_CONTRACT = INPUT / "definition-contract-v2.json"
OBSERVER_CONTRACT = BASE / "observer-contract-v2.json"

FAMILY = "F2"
SCOPE_ID = "F2_receiver_ballistic_catch_release_speed_v2_x_v1"
REVISION_ID = "F2_receiver_ballistic_catch_release_speed_v2"
Q = 0.5
DP_M = 0.0075
TIME_MAX_S = 1.5
OUTPUT_INTERVAL_S = 0.005
INITIAL_VELOCITY = (0.0, 0.0, -0.10)

OUTER_LOW = (0.0, -0.45, 0.0)
OUTER_SIZE = (1.25, 0.90, 0.80)
RECEIVER_LOW = (0.35, -0.18, 0.08)
RECEIVER_SIZE = (0.50, 0.36, 0.50)
SOURCE_LOW = (0.48, -0.09, 0.65)
SOURCE_SIZE = (0.24, 0.18, 0.18)
RUNTIME_LOW = (-0.15, -0.55, -0.15)
RUNTIME_HIGH = (1.40, 0.55, 1.05)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sub(parent: ET.Element, tag: str, attrs: dict[str, str] | None = None,
         text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs or {})
    if text is not None:
        node.text = text
    return node


def _drawbox(parent: ET.Element, fill: str, low: tuple[float, float, float],
             size: tuple[float, float, float]) -> None:
    node = _sub(parent, "drawbox")
    _sub(node, "boxfill", text=fill)
    _sub(node, "point", {axis: f"{value:.17g}" for axis, value in zip("xyz", low)})
    _sub(node, "size", {axis: f"{value:.17g}" for axis, value in zip("xyz", size)})


def _cell_centred_box(low: tuple[float, float, float], size: tuple[float, float, float]):
    first = tuple(math.ceil(value / DP_M - 0.5 - 1.0e-10) for value in low)
    counts = tuple(max(1, int(round(value / DP_M))) for value in size)
    centre = tuple((index + 0.5) * DP_M for index in first)
    extent = tuple((count - 1) * DP_M for count in counts)
    return centre, extent, counts


def _parameter(parent: ET.Element, key: str, value: str | float | int) -> None:
    _sub(parent, "parameter", {"key": key, "value": str(value)})


def write_definition(target: Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f"fresh v2 Definition already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    source_centre, source_draw_size, _counts = _cell_centred_box(SOURCE_LOW, SOURCE_SIZE)
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
    _sub(initials, "velocity", {
        "mkfluid": "0",
        "x": f"{INITIAL_VELOCITY[0]:.17g}",
        "y": f"{INITIAL_VELOCITY[1]:.17g}",
        "z": f"{INITIAL_VELOCITY[2]:.17g}",
    })

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
        raise ValueError("Definition runtime domain is incomplete")
    if tuple(float(pointmin.get(axis, "nan")) for axis in "xyz") != RUNTIME_LOW:
        raise ValueError("runtime lower domain mismatch")
    if tuple(float(pointmax.get(axis, "nan")) for axis in "xyz") != RUNTIME_HIGH:
        raise ValueError("runtime upper domain mismatch")
    main = root.find("./casedef/geometry/commands/mainlist")
    if main is None:
        raise ValueError("geometry mainlist missing")
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

    def box_values(box: ET.Element):
        point, size = box.find("point"), box.find("size")
        if point is None or size is None:
            raise ValueError("drawbox missing point or size")
        return (tuple(float(point.get(axis, "nan")) for axis in "xyz"),
                tuple(float(size.get(axis, "nan")) for axis in "xyz"))

    observed = [box_values(box) for box in boxes]
    if observed[:2] != [(OUTER_LOW, OUTER_SIZE), (RECEIVER_LOW, RECEIVER_SIZE)]:
        raise ValueError("outer/receiver geometry mismatch")
    source_centre, source_draw_size, counts = _cell_centred_box(SOURCE_LOW, SOURCE_SIZE)
    if observed[2] != (source_centre, source_draw_size):
        raise ValueError("source lattice geometry mismatch")
    velocity = root.find("./casedef/initials/velocity")
    if velocity is None or tuple(float(velocity.get(axis, "nan")) for axis in "xyz") != INITIAL_VELOCITY:
        raise ValueError("fresh v2 initial velocity mismatch")
    params = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    if abs(float(params.get("TimeMax", "nan")) - TIME_MAX_S) > 1e-12:
        raise ValueError("TimeMax mismatch")
    if abs(float(params.get("TimeOut", "nan")) - OUTPUT_INTERVAL_S) > 1e-12:
        raise ValueError("TimeOut mismatch")
    if params.get("Boundary") != "1":
        raise ValueError("native DBC Boundary=1 is required")
    return {
        "schema": "core.f2.receiver_ballistic_catch.definition.v2",
        "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size,
        "case_id": CASE_ID, "family": FAMILY, "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID, "q": Q, "dp_m": DP_M,
        "time_max_s": TIME_MAX_S, "output_interval_s": OUTPUT_INTERVAL_S,
        "outer_low_m": list(OUTER_LOW), "outer_size_m": list(OUTER_SIZE),
        "receiver_low_m": list(RECEIVER_LOW), "receiver_size_m": list(RECEIVER_SIZE),
        "source_low_m": list(SOURCE_LOW), "source_size_m": list(SOURCE_SIZE),
        "source_first_center_m": list(source_centre),
        "source_draw_size_m": list(source_draw_size),
        "source_counts": list(counts),
        "source_particle_count": int(counts[0] * counts[1] * counts[2]),
        "initial_velocity_m_s": list(INITIAL_VELOCITY),
        "changed_control": {"name": "initial_source_velocity_z_m_s", "v1": -0.20, "v2": -0.10},
        "mass_policy": "native rho*dp^3; no mass rescaling",
        "runtime_domain_low_m": list(RUNTIME_LOW),
        "runtime_domain_high_m": list(RUNTIME_HIGH),
        "qualification_claim": "none; fresh CPU/native input closure only",
    }


def write_contract(definition: Path = DEFAULT_DEFINITION,
                   output: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    definition = Path(definition).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"v2 Definition contract already exists: {output}")
    contract = inspect_definition(definition)
    contract.update({
        "schema": "core.f2.receiver_ballistic_catch.definition_contract.v2",
        "status": "definition_written_cpu_native_preflight_pending",
        "definition_sha256": contract["sha256"],
        "writer_path": str(Path(__file__).resolve()),
        "writer_sha256": sha256(Path(__file__).resolve()),
        "fresh_input": {
            "source_identity_changed": True,
            "source_reuse": False,
            "qualification_inheritance": False,
            "old_v1_definition_reused": False,
            "old_v1_generated_xml_reused": False,
            "old_v1_native_bi4_reused": False,
            "old_v1_trajectory_reused": False,
            "old_v1_output_stem_reused": False,
            "same_input_retry": False,
            "new_literal_definition": True,
            "new_native_output": True,
        },
        "hard_preflight_gates": {
            "ids_unique_and_xml_aligned": True,
            "fluid_ids_match_generated_xml": True,
            "all_decoded_arrays_finite": True,
            "closed_outer_wall_endpoint_count_max": 0,
            "closed_receiver_endpoint_count_max": 0,
            "source_mass_relative_error_max": 0.025,
            "threshold_relaxation": False,
            "survivor_renormalization": False,
        },
        "execution_controls": {
            "definition_written": True,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
        },
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {"path": str(output), "sha256": sha256(output), "bytes": output.stat().st_size,
            "definition_sha256": contract["definition_sha256"], "qualification_claim": "none"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("write-definition")
    p.add_argument("--output", type=Path, default=DEFAULT_DEFINITION)
    p = sub.add_parser("inspect")
    p.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    p = sub.add_parser("write-contract")
    p.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    p.add_argument("--output", type=Path, default=DEFAULT_CONTRACT)
    p = sub.add_parser("verify")
    p.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    args = parser.parse_args()
    if args.command == "write-definition":
        result = write_definition(args.output)
    elif args.command in ("inspect", "verify"):
        result = inspect_definition(args.definition)
    else:
        result = write_contract(args.definition, args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
