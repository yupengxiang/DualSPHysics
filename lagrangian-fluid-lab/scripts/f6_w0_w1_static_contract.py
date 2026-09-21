#!/usr/bin/env python3
"""Create and audit a fresh CPU-only F6 W0/W1 static contract.

This module writes a new Definition, body-state sidecar schema, event-window
contract, proposal and preflight receipt.  It never invokes GenCase, a solver,
GPU code or a queue.  Historical F6 XML/BI4/HDF5 files are hashed as provenance
only; they are never parsed or used to construct the fresh contract.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-w0-w1-static-anchor-v1"
SCRIPT_PATH = Path(__file__).resolve()

CONTRACT_SCHEMA = "core.f6.w0_w1.static_definition_contract.v1"
SIDECAR_SCHEMA = "core.f6.body_state_sidecar.v1"
EVENT_SCHEMA = "core.f6.event_window_contract.v1"
PROPOSAL_SCHEMA = "core.f6.w0_w1.static_anchor_proposal.v1"
PREFLIGHT_SCHEMA = "core.f6.w0_w1.static_preflight_receipt.v1"

IDENTITY = "CORE_F6_W0_W1_single_body_no_contact_anchor_20260921"
BODY_ID = "F6_W0_W1_body_alpha_20260921"
MKBOUND = 7
DP_M = 0.02
RHO_FLUID = 1000.0
RHO_BODY = 780.0
# W0/W1 is deliberately a zero-force units/inertia anchor.  It is not a
# physical F6 buoyancy or free-fall run; gravity is introduced only by a later
# separately reviewed runtime contract.
GRAVITY = (0.0, 0.0, 0.0)
OUTPUT_INTERVAL_S = 0.01
TIME_START_S = 0.0
TIME_END_S = 1.5
SETTLE_HOLD_START_S = 1.0
SETTLE_HOLD_END_S = 1.5

TANK_LOW = (0.0, 0.0, 0.0)
TANK_SIZE = (1.40, 0.50, 0.80)
TANK_CLOSED_FACES = ("bottom", "left", "right", "front", "back")
TANK_OPEN_FACES = ("top",)
FLUID_LOW = (0.15, 0.05, 0.05)
FLUID_SIZE = (1.10, 0.40, 0.23)
BODY_SIZE = (0.18, 0.14, 0.12)
BODY_COM = (0.70, 0.25, 0.65)
BODY_LINEAR_VELOCITY = (0.0, 0.0, 0.0)
BODY_ANGULAR_VELOCITY = (0.0, 0.0, 0.0)

LEGACY_PATHS = (
    ("cases/F6/F6_floating_box/F6_floating_box_Def.xml", "historical XML hash only"),
    ("data/F6_floating_box.h5", "historical HDF5 hash only"),
    ("cases/F6/F6_heavy_box_entry/F6_heavy_box_entry_Def.xml", "historical XML hash only"),
    ("data/F6_heavy_box_entry.h5", "historical HDF5 hash only"),
    ("cases/F6/F6_twin_floaters/F6_twin_floaters_Def.xml", "historical XML hash only"),
    ("data/F6_twin_floaters.h5", "historical HDF5 hash only"),
    ("campaigns/core-v1/cfd/f6-fluid-rigid-body-root-review-only-proposal-v1-20260921.json", "parent proposal lineage hash only"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    path = path.resolve()
    try:
        return str(path.relative_to(LAB))
    except ValueError:
        return str(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def bind(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": rel(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def hash_only_provenance() -> list[dict[str, Any]]:
    result = []
    for relative, role in LEGACY_PATHS:
        path = LAB / relative
        item = bind(path, role)
        item.update({"hash_only": True, "reused_as_input": False})
        result.append(item)
    return result


def box_high(low: tuple[float, float, float], size: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(a + b for a, b in zip(low, size))


def body_geometry() -> dict[str, Any]:
    volume = math.prod(BODY_SIZE)
    mass = RHO_BODY * volume
    dx, dy, dz = BODY_SIZE
    ixx = mass * (dy * dy + dz * dz) / 12.0
    iyy = mass * (dx * dx + dz * dz) / 12.0
    izz = mass * (dx * dx + dy * dy) / 12.0
    low = tuple(c - length / 2.0 for c, length in zip(BODY_COM, BODY_SIZE))
    high = box_high(low, BODY_SIZE)
    return {
        "body_id": BODY_ID,
        "mkbound": MKBOUND,
        "shape": "axis_aligned_box",
        "size_m": list(BODY_SIZE),
        "bbox_low_m": list(low),
        "bbox_high_m": list(high),
        "com_m": list(BODY_COM),
        "density_kg_m3": RHO_BODY,
        "volume_m3": volume,
        "mass_kg": mass,
        "inertia_about_com_kg_m2": [
            [ixx, 0.0, 0.0],
            [0.0, iyy, 0.0],
            [0.0, 0.0, izz],
        ],
        "inertia_convention": "world-aligned body axes at initial COM; tensor about COM",
        "initial_linear_velocity_m_s": list(BODY_LINEAR_VELOCITY),
        "initial_angular_velocity_rad_s": list(BODY_ANGULAR_VELOCITY),
    }


def fluid_geometry() -> dict[str, Any]:
    return {
        "mkfluid": 0,
        "density_kg_m3": RHO_FLUID,
        "low_m": list(FLUID_LOW),
        "size_m": list(FLUID_SIZE),
        "high_m": list(box_high(FLUID_LOW, FLUID_SIZE)),
        "free_surface_z_m": FLUID_LOW[2] + FLUID_SIZE[2],
        "initial_velocity_m_s": [0.0, 0.0, 0.0],
    }


def tank_geometry() -> dict[str, Any]:
    return {
        "low_m": list(TANK_LOW),
        "size_m": list(TANK_SIZE),
        "high_m": list(box_high(TANK_LOW, TANK_SIZE)),
        "closed_faces": list(TANK_CLOSED_FACES),
        "open_faces": list(TANK_OPEN_FACES),
        "boundary_method": "standard_closed_faces_with_open_top_contract",
    }


def clearance_contract(body: dict[str, Any], fluid: dict[str, Any], tank: dict[str, Any]) -> dict[str, Any]:
    body_low = body["bbox_low_m"]
    body_high = body["bbox_high_m"]
    tank_low = tank["low_m"]
    tank_high = tank["high_m"]
    fluid_high = fluid["high_m"]
    clearances = {
        "bottom": body_low[2] - tank_low[2],
        "left": body_low[0] - tank_low[0],
        "right": tank_high[0] - body_high[0],
        "front": body_low[1] - tank_low[1],
        "back": tank_high[1] - body_high[1],
        "open_top": tank_high[2] - body_high[2],
        "fluid_free_surface": body_low[2] - fluid["free_surface_z_m"],
    }
    return {
        "clearance_m": clearances,
        "minimum_closed_face_clearance_m": min(clearances[name] for name in TANK_CLOSED_FACES),
        "minimum_all_declared_clearance_m": min(clearances.values()),
        "required_clearance_m": 3.0 * DP_M,
        "body_fully_above_fluid": body_low[2] > fluid["free_surface_z_m"],
        "initial_contact_expected": False,
    }


def _sub(parent: ET.Element, tag: str, **attrs: Any) -> ET.Element:
    return ET.SubElement(parent, tag, {key: str(value) for key, value in attrs.items()})


def _draw_box(commands: ET.Element, *, point: tuple[float, float, float], size: tuple[float, float, float], kind: str, mk: int, fill: str) -> None:
    _sub(commands, f"setmk{kind}", mk=mk)
    node = _sub(commands, "drawbox")
    _sub(node, "boxfill").text = fill
    _sub(node, "point", x=point[0], y=point[1], z=point[2])
    _sub(node, "size", x=size[0], y=size[1], z=size[2])


def write_definition(path: Path) -> None:
    """Write a fresh XML definition from the contract constants only."""
    root = ET.Element("case")
    casedef = _sub(root, "casedef")
    constants = _sub(casedef, "constantsdef")
    _sub(constants, "gravity", x=GRAVITY[0], y=GRAVITY[1], z=GRAVITY[2])
    _sub(constants, "rhop0", value=RHO_FLUID)
    _sub(constants, "rhopgradient", value=2)
    _sub(constants, "hswl", value=0, auto="true")
    _sub(constants, "gamma", value=7)
    _sub(constants, "speedsystem", value=0, auto="true")
    _sub(constants, "coefsound", value=20)
    _sub(constants, "speedsound", value=0, auto="true")
    _sub(constants, "coefh", value=1.0)
    _sub(constants, "cflnumber", value=0.2)
    _sub(casedef, "mkconfig", boundcount=200, fluidcount=16)
    geometry = _sub(casedef, "geometry")
    definition = _sub(geometry, "definition", dp=DP_M)
    _sub(definition, "pointmin", x=-0.20, y=-0.20, z=-0.20)
    _sub(definition, "pointmax", x=1.60, y=0.70, z=0.95)
    commands_root = _sub(geometry, "commands")
    commands = _sub(commands_root, "mainlist")
    _sub(commands, "setshapemode").text = "dp | bound"
    _sub(commands, "setdrawmode", mode="full")
    _draw_box(commands, point=FLUID_LOW, size=FLUID_SIZE, kind="fluid", mk=0, fill="solid")
    _draw_box(commands, point=TANK_LOW, size=TANK_SIZE, kind="bound", mk=0,
              fill="bottom | left | right | front | back")
    _sub(commands, "setmkvoid")
    _draw_box(commands, point=tuple(c - length / 2.0 for c, length in zip(BODY_COM, BODY_SIZE)),
              size=BODY_SIZE, kind="bound", mk=MKBOUND, fill="solid")
    floatings = _sub(casedef, "floatings")
    floating = _sub(floatings, "floating", mkbound=MKBOUND, rhopbody=RHO_BODY)
    _sub(floating, "linearvelini", x=BODY_LINEAR_VELOCITY[0], y=BODY_LINEAR_VELOCITY[1], z=BODY_LINEAR_VELOCITY[2])
    execution = _sub(root, "execution")
    parameters = _sub(execution, "parameters")
    for key, value in (
        ("SavePosDouble", 0), ("StepAlgorithm", 1), ("VerletSteps", 40),
        ("Kernel", 2), ("ViscoTreatment", 1), ("Visco", 0.08),
        ("ViscoBoundFactor", 1), ("DensityDT", 2), ("DensityDTvalue", 0.1),
        ("Shifting", 0), ("RigidAlgorithm", 1), ("FtPause", 0),
        ("CoefDtMin", 0.05), ("DtIni", 0), ("DtMin", 0), ("DtFixed", 0),
        ("DtAllParticles", 0), ("TimeMax", TIME_END_S), ("TimeOut", OUTPUT_INTERVAL_S),
        ("MinFluidStop", 0), ("RhopOutMin", 650), ("RhopOutMax", 1350),
    ):
        _sub(parameters, "parameter", key=key, value=value)
    domain = _sub(parameters, "simulationdomain")
    _sub(domain, "posmin", x="default - 25%", y="default - 25%", z="default - 25%")
    _sub(domain, "posmax", x="default + 25%", y="default + 25%", z="default + 25%")
    ET.indent(root, space="    ")
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def build_sidecar_schema(body: dict[str, Any], event_path: str) -> dict[str, Any]:
    return {
        "schema": SIDECAR_SCHEMA,
        "status": "contract_only_no_runtime_sidecar",
        "forcing_mode": "zero_gravity_zero_force_units_inertia_anchor",
        "physical_f6_qualification": False,
        "body_id": BODY_ID,
        "mkbound": MKBOUND,
        "identity_rule": "body_id is immutable and is never inferred from a particle_id",
        "required_fields": [
            {"name": "time_s", "dtype": "float64", "shape": "[n_frames]"},
            {"name": "body_position_m", "dtype": "float64", "shape": "[n_frames,3]"},
            {"name": "body_quaternion_xyzw", "dtype": "float64", "shape": "[n_frames,4]"},
            {"name": "linear_velocity_m_s", "dtype": "float64", "shape": "[n_frames,3]"},
            {"name": "angular_velocity_rad_s", "dtype": "float64", "shape": "[n_frames,3]"},
            {"name": "fluid_force_N", "dtype": "float64", "shape": "[n_frames,3]"},
            {"name": "fluid_torque_Nm", "dtype": "float64", "shape": "[n_frames,3]"},
            {"name": "contact_count", "dtype": "int32", "shape": "[n_frames]"},
            {"name": "penetration_depth_m", "dtype": "float64", "shape": "[n_frames]"},
            {"name": "valid", "dtype": "bool", "shape": "[n_frames]"},
        ],
        "body_geometry_binding": body,
        "event_window_contract": event_path,
        "mass_policy": "body mass and inertia are authoritative from this sidecar binding; particle mass is not a substitute",
        "qualification_claim": "none",
        "qualification_credit": 0,
    }


def build_event_contract(body: dict[str, Any]) -> dict[str, Any]:
    frame_count = int(round((TIME_END_S - TIME_START_S) / OUTPUT_INTERVAL_S)) + 1
    return {
        "schema": EVENT_SCHEMA,
        "event_id": "F6_W0_W1_static_no_contact_balance_v1",
        "forcing_mode": "zero_gravity_zero_force_units_inertia_anchor",
        "physical_f6_qualification": False,
        "body_id": BODY_ID,
        "window": {
            "start_s": TIME_START_S,
            "end_s": TIME_END_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "expected_frame_count": frame_count,
            "settle_hold_start_s": SETTLE_HOLD_START_S,
            "settle_hold_end_s": SETTLE_HOLD_END_S,
        },
        "initial_state": {
            "com_m": body["com_m"],
            "linear_velocity_m_s": body["initial_linear_velocity_m_s"],
            "angular_velocity_rad_s": body["initial_angular_velocity_rad_s"],
            "contact_expected": False,
        },
        "completion_required": True,
        "completion_rule": [
            "all expected frames exist and time_s is strictly increasing at the declared cadence",
            "body_id is present on every body-state row",
            "all state, force and torque values are finite",
            "contact_count equals zero and penetration_depth_m is no greater than 1e-12 throughout",
            "the body remains inside the declared tank and above the fluid free surface under the zero-force contract",
            "the final settle-hold interval [1.0,1.5] s is present and uncensored",
        ],
        "uncensored_required": True,
        "status_without_runtime": "pending_runtime_event_window",
        "qualification_claim": "none",
        "qualification_credit": 0,
    }


def build_contract(root: Path, definition: Path, sidecar: Path, event: Path) -> dict[str, Any]:
    body = body_geometry()
    fluid = fluid_geometry()
    tank = tank_geometry()
    return {
        "schema": CONTRACT_SCHEMA,
        "contract_id": "F6_W0_W1_static_definition_contract_20260921",
        "status": "definition_written_cpu_static_gate_pending",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_w0_w1_static_anchor_v1",
        "revision_id": "F6_W0_W1_single_body_no_contact_anchor_v1",
        "case_id": IDENTITY,
        "forcing_mode": "zero_gravity_zero_force_units_inertia_anchor",
        "physical_f6_qualification": False,
        "implementation": bind(SCRIPT_PATH, "F6 W0/W1 static contract implementation"),
        "hypothesis": "A fresh zero-force, no-contact single rigid body contract can close units, geometry, mass, inertia, identity and event-window semantics before any solver execution is considered; it makes no buoyancy or free-fall claim.",
        "fresh_input": {
            "definition": bind(definition, "fresh F6 W0/W1 Definition; generated here, never copied from legacy XML"),
            "old_assets_reused": False,
            "gen_case_invoked": False,
            "native_bi4_present": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
        "fluid": fluid,
        "tank": tank,
        "body": body,
        "initial_clearance": clearance_contract(body, fluid, tank),
        "sidecar_schema": bind(sidecar, "new body-state sidecar schema"),
        "event_window": bind(event, "new complete static/no-contact event-window contract"),
        "legacy_provenance_hash_only": hash_only_provenance(),
        "gate_policy": {
            "static_only": True,
            "min_clearance_over_dp": 3.0,
            "body_mass_relative_tolerance": 1.0e-12,
            "inertia_relative_tolerance": 1.0e-12,
            "event_window_complete_required": True,
            "qualification_credit": 0,
        },
        "execution_controls": {
            "definition_written": True,
            "xml_parsed": False,
            "static_gate_run": False,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
    }


def _float(value: str | None, name: str) -> float:
    if value is None:
        raise ValueError(f"missing XML attribute: {name}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite XML value: {name}")
    return result


def static_gate(root: Path, contract: dict[str, Any], definition: Path, sidecar: Path, event: Path) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, passed: bool, detail: Any) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    try:
        xml_root = ET.parse(definition).getroot()
        check("xml_parse", xml_root.tag == "case", {"root_tag": xml_root.tag})
        xml_text = definition.read_text(encoding="utf-8")
        forbidden = ["F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".bi4", ".h5"]
        check("fresh_xml_has_no_legacy_reference", not any(token in xml_text for token in forbidden), {"forbidden_tokens": forbidden})
        dp = _float(xml_root.find("./casedef/geometry/definition").get("dp"), "dp")
        check("definition_dp", abs(dp - DP_M) <= 1.0e-15, {"observed": dp, "expected": DP_M})
        floating = xml_root.find("./casedef/floatings/floating")
        check("floating_binding", floating is not None and floating.get("mkbound") == str(MKBOUND) and abs(_float(floating.get("rhopbody"), "rhopbody") - RHO_BODY) <= 1.0e-12, {"mkbound": None if floating is None else floating.get("mkbound"), "rhopbody": None if floating is None else floating.get("rhopbody")})
        velocity = None if floating is None else floating.find("./linearvelini")
        check("initial_velocity_binding", velocity is not None and all(abs(_float(velocity.get(axis), axis)) <= 1.0e-15 for axis in ("x", "y", "z")), {"expected": list(BODY_LINEAR_VELOCITY)})
        params = {node.get("key"): node.get("value") for node in xml_root.findall("./execution/parameters/parameter")}
        check("runtime_window_binding", params.get("TimeMax") == str(TIME_END_S) and params.get("TimeOut") == str(OUTPUT_INTERVAL_S), {"TimeMax": params.get("TimeMax"), "TimeOut": params.get("TimeOut")})
    except (ET.ParseError, AttributeError, TypeError, ValueError) as error:
        check("xml_parse", False, str(error))

    body = contract["body"]
    fluid = contract["fluid"]
    tank = contract["tank"]
    clearance = contract["initial_clearance"]
    check("body_mass_from_density_volume", abs(body["mass_kg"] - body["density_kg_m3"] * body["volume_m3"]) <= 1.0e-12, {"mass_kg": body["mass_kg"], "rho_times_volume": body["density_kg_m3"] * body["volume_m3"]})
    dx, dy, dz = body["size_m"]
    mass = body["mass_kg"]
    expected_inertia = [
        [mass * (dy * dy + dz * dz) / 12.0, 0.0, 0.0],
        [0.0, mass * (dx * dx + dz * dz) / 12.0, 0.0],
        [0.0, 0.0, mass * (dx * dx + dy * dy) / 12.0],
    ]
    inertia_ok = all(abs(body["inertia_about_com_kg_m2"][i][j] - expected_inertia[i][j]) <= 1.0e-12 for i in range(3) for j in range(3))
    positive_definite = all(body["inertia_about_com_kg_m2"][i][i] > 0.0 for i in range(3))
    check("inertia_tensor", inertia_ok and positive_definite, {"expected": expected_inertia, "observed": body["inertia_about_com_kg_m2"], "positive_diagonal": positive_definite})
    body_low = body["bbox_low_m"]
    body_high = body["bbox_high_m"]
    tank_low = tank["low_m"]
    tank_high = tank["high_m"]
    inside = all(tank_low[i] < body_low[i] < body_high[i] < tank_high[i] for i in range(3))
    check("body_inside_tank", inside, {"body_low": body_low, "body_high": body_high, "tank_low": tank_low, "tank_high": tank_high})
    check("no_initial_fluid_contact", clearance["body_fully_above_fluid"] and not clearance["initial_contact_expected"], clearance)
    check("clearance_margin", clearance["minimum_all_declared_clearance_m"] > clearance["required_clearance_m"], clearance)
    zero_gravity = all(abs(value) <= 1.0e-15 for value in GRAVITY)
    check("density_and_zero_force_mode", fluid["density_kg_m3"] > 0.0 and body["density_kg_m3"] > 0.0 and zero_gravity, {"fluid_density": fluid["density_kg_m3"], "body_density": body["density_kg_m3"], "gravity": GRAVITY, "physical_f6_claim": False})

    try:
        sidecar_value = json.loads(sidecar.read_text(encoding="utf-8"))
        required_names = {field["name"] for field in sidecar_value["required_fields"]}
        expected_names = {"time_s", "body_position_m", "body_quaternion_xyzw", "linear_velocity_m_s", "angular_velocity_rad_s", "fluid_force_N", "fluid_torque_Nm", "contact_count", "penetration_depth_m", "valid"}
        check("sidecar_schema", sidecar_value.get("schema") == SIDECAR_SCHEMA and sidecar_value.get("body_id") == BODY_ID and required_names == expected_names, {"schema": sidecar_value.get("schema"), "body_id": sidecar_value.get("body_id"), "missing": sorted(expected_names - required_names), "extra": sorted(required_names - expected_names)})
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        check("sidecar_schema", False, str(error))
    try:
        event_value = json.loads(event.read_text(encoding="utf-8"))
        window = event_value["window"]
        expected_frames = int(round((TIME_END_S - TIME_START_S) / OUTPUT_INTERVAL_S)) + 1
        event_ok = (event_value.get("schema") == EVENT_SCHEMA and event_value.get("body_id") == BODY_ID and window["expected_frame_count"] == expected_frames and window["output_interval_s"] == OUTPUT_INTERVAL_S and event_value.get("completion_required") is True and event_value.get("uncensored_required") is True)
        event_ok = event_ok and event_value.get("forcing_mode") == "zero_gravity_zero_force_units_inertia_anchor" and event_value.get("physical_f6_qualification") is False
        check("event_window_contract", event_ok, {"window": window, "expected_frame_count": expected_frames, "forcing_mode": event_value.get("forcing_mode"), "status_without_runtime": event_value.get("status_without_runtime")})
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        check("event_window_contract", False, str(error))

    all_passed = all(item["passed"] for item in checks.values())
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": "cpu_static_gate_pass" if all_passed else "cpu_static_gate_failed",
        "gate_passed": all_passed,
        "checks": checks,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "event_window_complete": False,
        "event_window_status": "pending_runtime_event_window",
        "execution_controls": {
            "xml_parsed": True,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
        "failure_policy": "If any static check fails, retain this receipt as failure evidence and do not continue to GenCase, solver or matrix preparation.",
        "contract": bind(root / "definition-contract.json", "fresh F6 definition contract"),
        "definition": bind(definition, "fresh F6 Definition"),
        "sidecar_schema": bind(sidecar, "fresh body-state sidecar schema"),
        "event_window": bind(event, "fresh event-window contract"),
        "implementation": bind(SCRIPT_PATH, "F6 W0/W1 static contract implementation"),
        "legacy_provenance_hash_only": True,
    }


def build_proposal(root: Path, contract: dict[str, Any], definition: Path, sidecar: Path, event: Path) -> dict[str, Any]:
    return {
        "schema": PROPOSAL_SCHEMA,
        "proposal_id": "F6_W0_W1_static_anchor_root_review_only_20260921",
        "parent_proposal": bind(LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-root-review-only-proposal-v1-20260921.json", "parent F6 root-review-only proposal lineage"),
        "status": "proposal_only_cpu_static_gate",
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_w0_w1_static_anchor_v1",
        "revision_id": "F6_W0_W1_single_body_no_contact_anchor_v1",
        "case_id": IDENTITY,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "candidate": {
            "mechanism": "single free rigid body zero-force no-contact units/inertia anchor",
            "body_id": BODY_ID,
            "purpose": "close fresh Definition, body mass/inertia, identity and complete event-window semantics before any fluid-body runtime; gravity is zero by design",
            "physical_f6_qualification": False,
            "new_identity": True,
            "old_assets_as_inputs": False,
        },
        "fresh_contract": {
            "contract": bind(root / "definition-contract.json", "fresh contract"),
            "definition": bind(definition, "fresh XML Definition"),
            "body_state_sidecar_schema": bind(sidecar, "fresh sidecar schema"),
            "event_window_contract": bind(event, "fresh event-window contract"),
            "implementation": bind(SCRIPT_PATH, "F6 W0/W1 static contract implementation"),
        },
        "static_gate": {
            "authorized_action": "write and parse the fresh Definition and validate geometry, mass, inertia, body identity, sidecar schema and event-window contract on CPU",
            "gen_case": False,
            "solver": False,
            "gpu": False,
            "queue": False,
            "required_clearance_over_dp": 3.0,
            "event_window_complete_required_before_runtime": True,
        },
        "provenance_policy": {
            "legacy_assets": "hash_only",
            "legacy_assets_as_inputs": False,
            "legacy_assets_as_qualification": False,
            "old_definition_reused": False,
            "old_bi4_reused": False,
            "old_hdf5_reused": False,
            "legacy_hashes": contract["legacy_provenance_hash_only"],
        },
        "execution_controls": {
            "read_only_review": True,
            "definition_writer_only": True,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
        },
        "failure_policy": "Static failure is terminal evidence for this review; do not run GenCase, solver, GPU or queue and do not repair by reusing a legacy input.",
    }


def create(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    definition = root / f"{IDENTITY}_Def.xml"
    sidecar = root / "body-state-sidecar-schema.json"
    event = root / "event-window-contract.json"
    contract_path = root / "definition-contract.json"
    proposal_path = root / "proposal.json"
    preflight_path = root / "preflight.json"
    write_definition(definition)
    body = body_geometry()
    sidecar_value = build_sidecar_schema(body, rel(event))
    event_value = build_event_contract(body)
    write_json(sidecar, sidecar_value)
    write_json(event, event_value)
    contract = build_contract(root, definition, sidecar, event)
    write_json(contract_path, contract)
    proposal = build_proposal(root, contract, definition, sidecar, event)
    write_json(proposal_path, proposal)
    receipt = static_gate(root, contract, definition, sidecar, event)
    receipt["proposal"] = bind(proposal_path, "fresh root-review-only proposal")
    receipt["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(preflight_path, receipt)
    return receipt


def verify(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    receipt = json.loads((root / "preflight.json").read_text(encoding="utf-8"))
    if receipt["schema"] != PREFLIGHT_SCHEMA:
        raise ValueError("unexpected F6 W0/W1 preflight schema")
    for name in ("definition-contract.json", "proposal.json", "body-state-sidecar-schema.json", "event-window-contract.json"):
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing F6 W0/W1 contract artifact: {path}")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    receipt = create(args.root)
    verify(args.root)
    print(json.dumps({"status": receipt["status"], "gate_passed": receipt["gate_passed"], "preflight": rel(args.root / "preflight.json")}, indent=2))
    return 0 if receipt["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
