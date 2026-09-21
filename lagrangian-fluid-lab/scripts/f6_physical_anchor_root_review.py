#!/usr/bin/env python3
"""Build a fresh, CPU-only F6 gravity physical-anchor root review.

The Definition is generated from new constants and is never copied from a
legacy XML.  The preflight is analytic: it checks geometry, mass, inertia,
gravity, predicted free-fall/contact timing and the required body-state
sidecar contract.  It never invokes GenCase, a solver, GPU code or a queue.
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
DEFAULT_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-root-review-v1-20260921"
SCRIPT_PATH = Path(__file__).resolve()

CONTRACT_SCHEMA = "core.f6.physical_anchor.definition_contract.v1"
SIDECAR_SCHEMA = "core.f6.physical_anchor.body_state_force_sidecar.v1"
EVENT_SCHEMA = "core.f6.physical_anchor.event_window_contract.v1"
PROPOSAL_SCHEMA = "core.f6.physical_anchor.root_review_proposal.v1"
PREFLIGHT_SCHEMA = "core.f6.physical_anchor.cpu_preflight_receipt.v1"

IDENTITY = "CORE_F6_physical_anchor_single_body_gravity_20260921"
BODY_ID = "F6_physical_anchor_body_beta_20260921"
MKBOUND = 8
DP_M = 0.02
RHO_FLUID = 1000.0
RHO_BODY = 780.0
GRAVITY = (0.0, 0.0, -9.81)
OUTPUT_INTERVAL_S = 0.005
TIME_START_S = 0.0
TIME_END_S = 1.5
SETTLE_HOLD_START_S = 1.0
SETTLE_HOLD_END_S = 1.5
CONTACT_TIME_TOLERANCE_S = 0.02

# Fresh geometry for this physical route.  These values are not read from W0,
# the historical F6 cases, or any generated/native artifact.
TANK_LOW = (0.0, 0.0, 0.0)
TANK_SIZE = (1.50, 0.60, 0.90)
TANK_CLOSED_FACES = ("bottom", "left", "right", "front", "back")
TANK_OPEN_FACES = ("top",)
FLUID_LOW = (0.18, 0.08, 0.05)
FLUID_SIZE = (1.14, 0.44, 0.23)
BODY_SIZE = (0.20, 0.16, 0.12)
BODY_COM = (0.75, 0.30, 0.55)
BODY_LINEAR_VELOCITY = (0.0, 0.0, 0.0)
BODY_ANGULAR_VELOCITY = (0.0, 0.0, 0.0)

LEGACY_PATHS = (
    ("cases/F6/F6_floating_box/F6_floating_box_Def.xml", "historical XML hash only"),
    ("data/F6_floating_box.h5", "historical HDF5 hash only"),
    ("cases/F6/F6_heavy_box_entry/F6_heavy_box_entry_Def.xml", "historical XML hash only"),
    ("data/F6_heavy_box_entry.h5", "historical HDF5 hash only"),
    ("cases/F6/F6_twin_floaters/F6_twin_floaters_Def.xml", "historical XML hash only"),
    ("data/F6_twin_floaters.h5", "historical HDF5 hash only"),
    ("campaigns/core-v1/cfd/f6-fluid-rigid-body-w0-w1-static-anchor-v1/CORE_F6_W0_W1_single_body_no_contact_anchor_20260921_Def.xml", "zero-force anchor hash only"),
    ("campaigns/core-v1/cfd/f6-fluid-rigid-body-root-review-only-proposal-v1-20260921.json", "parent proposal hash only"),
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
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def bind(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def legacy_hashes() -> list[dict[str, Any]]:
    result = []
    for relative, role in LEGACY_PATHS:
        item = bind(LAB / relative, role)
        item.update({"hash_only": True, "reused_as_input": False})
        result.append(item)
    return result


def high(low: tuple[float, float, float], size: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(a + b for a, b in zip(low, size))


def body_model() -> dict[str, Any]:
    volume = math.prod(BODY_SIZE)
    mass = RHO_BODY * volume
    dx, dy, dz = BODY_SIZE
    inertia = [
        [mass * (dy * dy + dz * dz) / 12.0, 0.0, 0.0],
        [0.0, mass * (dx * dx + dz * dz) / 12.0, 0.0],
        [0.0, 0.0, mass * (dx * dx + dy * dy) / 12.0],
    ]
    low = tuple(c - size / 2.0 for c, size in zip(BODY_COM, BODY_SIZE))
    return {
        "body_id": BODY_ID,
        "mkbound": MKBOUND,
        "shape": "axis_aligned_box",
        "size_m": list(BODY_SIZE),
        "bbox_low_m": list(low),
        "bbox_high_m": list(high(low, BODY_SIZE)),
        "com_m": list(BODY_COM),
        "density_kg_m3": RHO_BODY,
        "volume_m3": volume,
        "mass_kg": mass,
        "inertia_about_com_kg_m2": inertia,
        "inertia_convention": "world-aligned body axes at initial COM; tensor about COM",
        "initial_linear_velocity_m_s": list(BODY_LINEAR_VELOCITY),
        "initial_angular_velocity_rad_s": list(BODY_ANGULAR_VELOCITY),
    }


def fluid_model() -> dict[str, Any]:
    return {
        "mkfluid": 0,
        "density_kg_m3": RHO_FLUID,
        "low_m": list(FLUID_LOW),
        "size_m": list(FLUID_SIZE),
        "high_m": list(high(FLUID_LOW, FLUID_SIZE)),
        "free_surface_z_m": FLUID_LOW[2] + FLUID_SIZE[2],
        "initial_velocity_m_s": [0.0, 0.0, 0.0],
    }


def expected_fluid_drawbox_size(fluid: dict[str, Any]) -> list[float]:
    """Return the Definition drawbox size for the declared fluid contract.

    Most Definitions use the continuous box size directly.  A GenCase
    endpoint-safe support-centre revision may explicitly register a smaller
    drawbox while retaining the continuous volume in ``fluid.size_m`` for the
    mass gate.  Keeping this lookup in the shared contract code prevents the
    native preflight from silently inferring a different convention.
    """
    sampling = fluid.get("sampling_contract", {})
    drawbox = sampling.get("drawbox_size_m") if isinstance(sampling, dict) else None
    if drawbox is None:
        drawbox = fluid["size_m"]
    return [float(value) for value in drawbox]


def tank_model() -> dict[str, Any]:
    return {
        "low_m": list(TANK_LOW),
        "size_m": list(TANK_SIZE),
        "high_m": list(high(TANK_LOW, TANK_SIZE)),
        "closed_faces": list(TANK_CLOSED_FACES),
        "open_faces": list(TANK_OPEN_FACES),
        "boundary_method": "standard_closed_faces_with_open_top_contract",
    }


def analytic_events(body: dict[str, Any], fluid: dict[str, Any], tank: dict[str, Any]) -> dict[str, Any]:
    body_bottom = body["bbox_low_m"][2]
    free_surface = fluid["free_surface_z_m"]
    gap = body_bottom - free_surface
    contact_com_z = free_surface + body["size_m"][2] / 2.0
    drop_to_contact = body["com_m"][2] - contact_com_z
    contact_time = math.sqrt(2.0 * drop_to_contact / abs(GRAVITY[2]))
    impact_speed = math.sqrt(2.0 * abs(GRAVITY[2]) * drop_to_contact)
    equilibrium_submerged_fraction = body["density_kg_m3"] / fluid["density_kg_m3"]
    equilibrium_submerged_depth = equilibrium_submerged_fraction * body["size_m"][2]
    equilibrium_bottom = free_surface - equilibrium_submerged_depth
    equilibrium_com = equilibrium_bottom + body["size_m"][2] / 2.0
    equilibrium_top = equilibrium_bottom + body["size_m"][2]
    free_fall_to_equilibrium_time = math.sqrt(2.0 * (body["com_m"][2] - equilibrium_com) / abs(GRAVITY[2]))
    bottom_clearance_at_equilibrium = equilibrium_bottom - tank["low_m"][2]
    top_clearance_at_equilibrium = tank["high_m"][2] - equilibrium_top
    return {
        "initial_fluid_surface_gap_m": gap,
        "predicted_contact_com_z_m": contact_com_z,
        "predicted_contact_time_s": contact_time,
        "predicted_impact_speed_m_s": impact_speed,
        "contact_prediction_window_s": [max(TIME_START_S, contact_time - CONTACT_TIME_TOLERANCE_S), contact_time + CONTACT_TIME_TOLERANCE_S],
        "equilibrium_submerged_fraction": equilibrium_submerged_fraction,
        "equilibrium_submerged_depth_m": equilibrium_submerged_depth,
        "equilibrium_bottom_z_m": equilibrium_bottom,
        "equilibrium_com_z_m": equilibrium_com,
        "equilibrium_top_z_m": equilibrium_top,
        "free_fall_equivalent_time_to_equilibrium_s": free_fall_to_equilibrium_time,
        "tank_bottom_clearance_at_equilibrium_m": bottom_clearance_at_equilibrium,
        "tank_top_clearance_at_equilibrium_m": top_clearance_at_equilibrium,
        "hydrodynamic_response_is_runtime_unknown": True,
    }


def sub(parent: ET.Element, tag: str, **attrs: Any) -> ET.Element:
    return ET.SubElement(parent, tag, {key: str(value) for key, value in attrs.items()})


def draw_box(commands: ET.Element, *, point: tuple[float, float, float], size: tuple[float, float, float], kind: str, mk: int, fill: str) -> None:
    sub(commands, f"setmk{kind}", mk=mk)
    node = sub(commands, "drawbox")
    sub(node, "boxfill").text = fill
    sub(node, "point", x=point[0], y=point[1], z=point[2])
    sub(node, "size", x=size[0], y=size[1], z=size[2])


def write_definition(path: Path) -> None:
    root = ET.Element("case")
    casedef = sub(root, "casedef")
    constants = sub(casedef, "constantsdef")
    sub(constants, "gravity", x=GRAVITY[0], y=GRAVITY[1], z=GRAVITY[2])
    sub(constants, "rhop0", value=RHO_FLUID)
    sub(constants, "rhopgradient", value=2)
    sub(constants, "hswl", value=0, auto="true")
    sub(constants, "gamma", value=7)
    sub(constants, "speedsystem", value=0, auto="true")
    sub(constants, "coefsound", value=20)
    sub(constants, "speedsound", value=0, auto="true")
    sub(constants, "coefh", value=1.0)
    sub(constants, "cflnumber", value=0.2)
    sub(casedef, "mkconfig", boundcount=200, fluidcount=16)
    geometry = sub(casedef, "geometry")
    definition = sub(geometry, "definition", dp=DP_M)
    sub(definition, "pointmin", x=-0.20, y=-0.20, z=-0.20)
    sub(definition, "pointmax", x=1.70, y=0.80, z=1.05)
    commands = sub(sub(geometry, "commands"), "mainlist")
    sub(commands, "setshapemode").text = "dp | bound"
    sub(commands, "setdrawmode", mode="full")
    draw_box(commands, point=FLUID_LOW, size=FLUID_SIZE, kind="fluid", mk=0, fill="solid")
    draw_box(commands, point=TANK_LOW, size=TANK_SIZE, kind="bound", mk=0, fill="bottom | left | right | front | back")
    sub(commands, "setmkvoid")
    body_low = tuple(c - size / 2.0 for c, size in zip(BODY_COM, BODY_SIZE))
    draw_box(commands, point=body_low, size=BODY_SIZE, kind="bound", mk=MKBOUND, fill="solid")
    floatings = sub(casedef, "floatings")
    floating = sub(floatings, "floating", mkbound=MKBOUND, rhopbody=RHO_BODY)
    sub(floating, "linearvelini", x=BODY_LINEAR_VELOCITY[0], y=BODY_LINEAR_VELOCITY[1], z=BODY_LINEAR_VELOCITY[2])
    execution = sub(root, "execution")
    parameters = sub(execution, "parameters")
    for key, value in (
        ("SavePosDouble", 0), ("StepAlgorithm", 1), ("VerletSteps", 40),
        ("Kernel", 2), ("ViscoTreatment", 1), ("Visco", 0.08),
        ("ViscoBoundFactor", 1), ("DensityDT", 2), ("DensityDTvalue", 0.1),
        ("Shifting", 0), ("RigidAlgorithm", 1), ("FtPause", 0),
        ("CoefDtMin", 0.05), ("DtIni", 0), ("DtMin", 0), ("DtFixed", 0),
        ("DtAllParticles", 0), ("TimeMax", TIME_END_S), ("TimeOut", OUTPUT_INTERVAL_S),
        ("MinFluidStop", 0), ("RhopOutMin", 650), ("RhopOutMax", 1350),
    ):
        sub(parameters, "parameter", key=key, value=value)
    domain = sub(parameters, "simulationdomain")
    sub(domain, "posmin", x="default - 25%", y="default - 25%", z="default - 25%")
    sub(domain, "posmax", x="default + 25%", y="default + 25%", z="default + 25%")
    ET.indent(root, space="    ")
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def build_sidecar(body: dict[str, Any], events_path: str) -> dict[str, Any]:
    fields = [
        {"name": "time_s", "dtype": "float64", "shape": "[n_frames]"},
        {"name": "body_position_m", "dtype": "float64", "shape": "[n_frames,3]"},
        {"name": "body_quaternion_xyzw", "dtype": "float64", "shape": "[n_frames,4]"},
        {"name": "linear_velocity_m_s", "dtype": "float64", "shape": "[n_frames,3]"},
        {"name": "angular_velocity_rad_s", "dtype": "float64", "shape": "[n_frames,3]"},
        {"name": "fluid_force_N", "dtype": "float64", "shape": "[n_frames,3]"},
        {"name": "fluid_torque_Nm", "dtype": "float64", "shape": "[n_frames,3]"},
        {"name": "contact_count", "dtype": "int32", "shape": "[n_frames]"},
        {"name": "penetration_depth_m", "dtype": "float64", "shape": "[n_frames]"},
        {"name": "boundary_contact_count", "dtype": "int32", "shape": "[n_frames]"},
        {"name": "open_face_mass_flux_kg_s", "dtype": "float64", "shape": "[n_frames]"},
        {"name": "event_status", "dtype": "string", "shape": "[n_frames]"},
        {"name": "valid", "dtype": "bool", "shape": "[n_frames]"},
    ]
    return {
        "schema": SIDECAR_SCHEMA,
        "status": "contract_only_no_runtime_sidecar",
        "body_id": BODY_ID,
        "mkbound": MKBOUND,
        "body_geometry_binding": body,
        "required_fields": fields,
        "identity_rule": "body_id is immutable; particle_id is not a substitute for body state",
        "force_semantics": "fluid_force_N and fluid_torque_Nm are fluid-body interaction totals with gravity and body weight reported separately",
        "boundary_semantics": "boundary_contact_count covers closed tank faces; open_face_mass_flux_kg_s covers the top opening",
        "event_window_contract": events_path,
        "qualification_claim": "none",
        "qualification_credit": 0,
    }


def build_event_contract(body: dict[str, Any], fluid: dict[str, Any], tank: dict[str, Any]) -> dict[str, Any]:
    events = analytic_events(body, fluid, tank)
    frame_count = int(round((TIME_END_S - TIME_START_S) / OUTPUT_INTERVAL_S)) + 1
    return {
        "schema": EVENT_SCHEMA,
        "event_id": "F6_physical_anchor_gravity_entry_buoyancy_v1",
        "body_id": BODY_ID,
        "forcing_mode": "gravity_minus_9p81_fluid_body_coupling_expected",
        "physical_f6_qualification": False,
        "window": {
            "start_s": TIME_START_S,
            "end_s": TIME_END_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "expected_frame_count": frame_count,
            "settle_hold_start_s": SETTLE_HOLD_START_S,
            "settle_hold_end_s": SETTLE_HOLD_END_S,
        },
        "predicted_events": events,
        "required_runtime_events": [
            "body_free_fall_started",
            "fluid_contact_observed_once_or_more",
            "buoyant_response_observed",
            "no_closed_tank_face_contact_or_penetration",
            "no_unaccounted_open_top_mass_flux",
            "settle_hold_present_and_uncensored",
        ],
        "completion_rule": [
            "all 301 frames exist at strictly increasing 0.005 s cadence",
            "body_id is present on every row and all body/force/torque values are finite",
            "fluid-contact time lies within the predicted contact window [t_contact-0.02,t_contact+0.02] s",
            "closed-face contact count and penetration depth are zero throughout",
            "the body remains inside the tank; later equilibrium has at least 3*dp bottom and top margins",
            "the final [1.0,1.5] s interval is present, uncensored, and carries status fields",
        ],
        "uncensored_required": True,
        "status_without_runtime": "auditable_prediction_pending_runtime_event_window",
        "qualification_claim": "none",
        "qualification_credit": 0,
    }


def build_contract(root: Path, definition: Path, sidecar: Path, event: Path) -> dict[str, Any]:
    body, fluid, tank = body_model(), fluid_model(), tank_model()
    return {
        "schema": CONTRACT_SCHEMA,
        "contract_id": "F6_physical_anchor_definition_contract_20260921",
        "status": "fresh_definition_written_cpu_preflight_pending",
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_physical_anchor_v1",
        "revision_id": "F6_gravity_single_body_entry_buoyancy_v1",
        "case_id": IDENTITY,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "physical_f6_qualification": False,
        "implementation": bind(SCRIPT_PATH, "F6 physical-anchor root-review implementation"),
        "fresh_input": {
            "definition": bind(definition, "fresh gravity=-9.81 Definition generated from new constants"),
            "old_assets_reused": False,
            "old_xml_copied": False,
            "old_bi4_reused": False,
            "old_hdf5_reused": False,
        },
        "gravity_m_s2": list(GRAVITY),
        "fluid": fluid,
        "tank": tank,
        "body": body,
        "predicted_events": analytic_events(body, fluid, tank),
        "sidecar_schema": bind(sidecar, "fresh body-state/force/torque sidecar schema"),
        "event_window": bind(event, "fresh predicted contact and complete event-window contract"),
        "legacy_provenance_hash_only": legacy_hashes(),
        "gate_policy": {
            "static_cpu_only": True,
            "gravity_m_s2_exact": -9.81,
            "minimum_clearance_over_dp": 3.0,
            "contact_prediction_tolerance_s": CONTACT_TIME_TOLERANCE_S,
            "event_window_complete_required": True,
            "solver_canary_authorization_in_this_receipt": False,
            "qualification_credit": 0,
        },
        "execution_controls": {
            "definition_written": True,
            "xml_parsed": False,
            "cpu_preflight_run": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
    }


def static_preflight(root: Path, contract: dict[str, Any], definition: Path, sidecar: Path, event: Path) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    xml_parsed = False

    def check(name: str, passed: bool, detail: Any) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    try:
        xml_root = ET.parse(definition).getroot()
        xml_parsed = True
        xml_text = definition.read_text(encoding="utf-8")
        forbidden = ["F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".bi4", ".h5"]
        check("fresh_xml_parse", xml_root.tag == "case", {"root_tag": xml_root.tag})
        check("fresh_xml_no_legacy_input", not any(token in xml_text for token in forbidden), {"forbidden_tokens": forbidden})
        gravity = xml_root.find("./casedef/constantsdef/gravity")
        gravity_values = [float(gravity.get(axis)) for axis in ("x", "y", "z")] if gravity is not None else None
        check("gravity_binding", gravity_values == list(GRAVITY), {"observed": gravity_values, "expected": list(GRAVITY)})
        dp = float(xml_root.find("./casedef/geometry/definition").get("dp"))
        check("fresh_resolution", abs(dp - DP_M) <= 1.0e-15, {"observed": dp, "expected": DP_M})
        floating = xml_root.find("./casedef/floatings/floating")
        massbody = floating.find("massbody") if floating is not None else None
        density_binding = floating is not None and floating.get("rhopbody") is not None and abs(float(floating.get("rhopbody")) - RHO_BODY) <= 1.0e-12
        mass_binding = massbody is not None and abs(float(massbody.get("value")) - body_model()["mass_kg"]) <= 1.0e-12
        check("body_density_binding", floating is not None and floating.get("mkbound") == str(MKBOUND) and (density_binding or mass_binding), {"mkbound": None if floating is None else floating.get("mkbound"), "rhopbody": None if floating is None else floating.get("rhopbody"), "massbody": None if massbody is None else massbody.get("value")})
        params = {node.get("key"): node.get("value") for node in xml_root.findall("./execution/parameters/parameter")}
        check("runtime_cadence_binding", params.get("TimeMax") == str(TIME_END_S) and params.get("TimeOut") == str(OUTPUT_INTERVAL_S), {"TimeMax": params.get("TimeMax"), "TimeOut": params.get("TimeOut")})
        fluid_node = xml_root.find("./casedef/geometry/commands/mainlist/drawbox")
        fluid_point = fluid_node.find("point") if fluid_node is not None else None
        fluid_size = fluid_node.find("size") if fluid_node is not None else None
        observed_fluid_low = [float(fluid_point.get(axis)) for axis in "xyz"] if fluid_point is not None else None
        observed_fluid_size = [float(fluid_size.get(axis)) for axis in "xyz"] if fluid_size is not None else None
        expected_fluid_size = expected_fluid_drawbox_size(contract["fluid"])
        low_matches = observed_fluid_low is not None and all(abs(actual - expected) <= 1.0e-12 for actual, expected in zip(observed_fluid_low, contract["fluid"]["low_m"]))
        size_matches = observed_fluid_size is not None and all(abs(actual - expected) <= 1.0e-12 for actual, expected in zip(observed_fluid_size, expected_fluid_size))
        check(
            "fluid_drawbox_binding",
            low_matches and size_matches,
            {"observed_low_m": observed_fluid_low, "expected_low_m": contract["fluid"]["low_m"], "observed_size_m": observed_fluid_size, "expected_size_m": expected_fluid_size},
        )
    except (ET.ParseError, AttributeError, TypeError, ValueError) as error:
        check("fresh_xml_parse", False, str(error))

    body, fluid, tank = contract["body"], contract["fluid"], contract["tank"]
    events = contract["predicted_events"]
    volume = math.prod(body["size_m"])
    expected_mass = body["density_kg_m3"] * volume
    check("mass_from_density_volume", abs(body["mass_kg"] - expected_mass) <= 1.0e-12, {"mass_kg": body["mass_kg"], "expected": expected_mass})
    dx, dy, dz = body["size_m"]
    mass = body["mass_kg"]
    inertia_expected = [[mass * (dy * dy + dz * dz) / 12.0, 0.0, 0.0], [0.0, mass * (dx * dx + dz * dz) / 12.0, 0.0], [0.0, 0.0, mass * (dx * dx + dy * dy) / 12.0]]
    inertia_ok = all(abs(body["inertia_about_com_kg_m2"][i][j] - inertia_expected[i][j]) <= 1.0e-12 for i in range(3) for j in range(3))
    positive = all(body["inertia_about_com_kg_m2"][i][i] > 0.0 for i in range(3))
    check("inertia_tensor", inertia_ok and positive, {"expected": inertia_expected, "observed": body["inertia_about_com_kg_m2"], "positive_diagonal": positive})
    low, high_body = body["bbox_low_m"], body["bbox_high_m"]
    tank_low, tank_high = tank["low_m"], tank["high_m"]
    inside = all(tank_low[i] < low[i] < high_body[i] < tank_high[i] for i in range(3))
    check("initial_body_inside_tank", inside, {"body_low": low, "body_high": high_body, "tank_low": tank_low, "tank_high": tank_high})
    initial_gap = fluid["free_surface_z_m"] * 0.0 + low[2] - fluid["free_surface_z_m"]
    clearance = {
        "bottom": low[2] - tank_low[2], "left": low[0] - tank_low[0], "right": tank_high[0] - high_body[0],
        "front": low[1] - tank_low[1], "back": tank_high[1] - high_body[1], "top": tank_high[2] - high_body[2],
        "fluid_surface_gap": initial_gap,
    }
    check("initial_no_contact", initial_gap > 3.0 * DP_M and min(clearance.values()) > 3.0 * DP_M, {"clearance_m": clearance, "required_m": 3.0 * DP_M})
    predicted_contact = events["predicted_contact_time_s"]
    predicted_window = events["contact_prediction_window_s"]
    equilibrium_ok = events["equilibrium_submerged_fraction"] > 0.0 and events["equilibrium_submerged_fraction"] < 1.0 and events["tank_bottom_clearance_at_equilibrium_m"] > 3.0 * DP_M and events["tank_top_clearance_at_equilibrium_m"] > 3.0 * DP_M
    check("analytic_contact_and_equilibrium", math.isfinite(predicted_contact) and 0.0 < predicted_window[0] < predicted_window[1] < TIME_END_S and equilibrium_ok, {"predicted_events": events})
    check("event_window_auditable", events["hydrodynamic_response_is_runtime_unknown"] is True and predicted_window[1] < SETTLE_HOLD_START_S and TIME_END_S >= SETTLE_HOLD_END_S, {"predicted_contact_window_s": predicted_window, "settle_hold_s": [SETTLE_HOLD_START_S, SETTLE_HOLD_END_S], "runtime_response_unknown": True})

    try:
        sidecar_value = json.loads(sidecar.read_text(encoding="utf-8"))
        names = {field["name"] for field in sidecar_value["required_fields"]}
        required = {"time_s", "body_position_m", "body_quaternion_xyzw", "linear_velocity_m_s", "angular_velocity_rad_s", "fluid_force_N", "fluid_torque_Nm", "contact_count", "penetration_depth_m", "boundary_contact_count", "open_face_mass_flux_kg_s", "event_status", "valid"}
        check("body_state_force_torque_sidecar", sidecar_value.get("schema") == SIDECAR_SCHEMA and sidecar_value.get("body_id") == BODY_ID and names == required, {"schema": sidecar_value.get("schema"), "body_id": sidecar_value.get("body_id"), "missing": sorted(required - names), "extra": sorted(names - required)})
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        check("body_state_force_torque_sidecar", False, str(error))
    try:
        event_value = json.loads(event.read_text(encoding="utf-8"))
        window = event_value["window"]
        expected_frames = int(round((TIME_END_S - TIME_START_S) / OUTPUT_INTERVAL_S)) + 1
        event_ok = event_value.get("schema") == EVENT_SCHEMA and event_value.get("body_id") == BODY_ID and event_value.get("physical_f6_qualification") is False and window.get("expected_frame_count") == expected_frames and window.get("output_interval_s") == OUTPUT_INTERVAL_S and event_value.get("uncensored_required") is True
        check("event_window_contract", event_ok, {"window": window, "predicted_contact_window_s": event_value.get("predicted_events", {}).get("contact_prediction_window_s"), "status_without_runtime": event_value.get("status_without_runtime")})
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        check("event_window_contract", False, str(error))

    passed = all(item["passed"] for item in checks.values())
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": "cpu_physical_anchor_preflight_pass" if passed else "cpu_physical_anchor_preflight_failed",
        "gate_passed": passed,
        "event_window_auditable": checks.get("event_window_auditable", {}).get("passed", False),
        "event_window_complete": False,
        "event_window_status": "auditable_prediction_pending_runtime_event_window",
        "checks": checks,
        "recommendation": "worth_one_protected_solver_canary_conditionally" if passed else "do_not_authorize_solver_canary",
        "solver_canary_authorized_in_this_receipt": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "execution_controls": {
            "xml_parsed": xml_parsed,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
        "failure_policy": "If any CPU preflight gate fails, retain this receipt and do not authorize or launch a solver canary.",
        "contract": bind(root / "definition-contract.json", "fresh physical-anchor contract"),
        "definition": bind(definition, "fresh gravity=-9.81 Definition"),
        "sidecar_schema": bind(sidecar, "fresh body-state/force/torque sidecar schema"),
        "event_window": bind(event, "fresh predicted event-window contract"),
        "legacy_provenance_hash_only": True,
    }


def build_proposal(root: Path, contract: dict[str, Any], definition: Path, sidecar: Path, event: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    gate_passed = bool(preflight["gate_passed"])
    event_window_auditable = bool(preflight["event_window_auditable"])
    return {
        "schema": PROPOSAL_SCHEMA,
        "proposal_id": "F6_physical_anchor_root_review_only_20260921",
        "status": "proposal_only_cpu_preflight_pass_pending_root_authorization" if gate_passed else "proposal_only_cpu_preflight_failed_no_authorization",
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_physical_anchor_v1",
        "revision_id": "F6_gravity_single_body_entry_buoyancy_v1",
        "case_id": IDENTITY,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "parent_static_anchor": bind(LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-w0-w1-static-anchor-v1/definition-contract.json", "zero-force anchor hash lineage only"),
        "fresh_contract": {
            "contract": bind(root / "definition-contract.json", "fresh physical-anchor contract"),
            "definition": bind(definition, "fresh gravity=-9.81 Definition"),
            "body_state_force_torque_sidecar": bind(sidecar, "fresh sidecar schema"),
            "event_window": bind(event, "fresh predicted event-window contract"),
            "implementation": bind(SCRIPT_PATH, "F6 physical-anchor root-review implementation"),
        },
        "physical_anchor": {
            "mechanism": "gravity-driven single rigid body entry followed by buoyant response",
            "body_id": BODY_ID,
            "gravity_m_s2": list(GRAVITY),
            "initial_velocity_m_s": list(BODY_LINEAR_VELOCITY),
            "predicted_contact_window_s": contract["predicted_events"]["contact_prediction_window_s"],
            "predicted_impact_speed_m_s": contract["predicted_events"]["predicted_impact_speed_m_s"],
            "equilibrium_submerged_fraction": contract["predicted_events"]["equilibrium_submerged_fraction"],
            "runtime_hydrodynamics": "unknown until sidecar is produced",
        },
        "root_review_decision": {
            "cpu_preflight_pass": gate_passed,
            "event_window_is_analytically_auditable": event_window_auditable,
            "worth_one_protected_solver_canary_conditionally": gate_passed and event_window_auditable,
            "solver_canary_authorized_now": False,
            "authorization_requires": [
                "root approval of this exact hash-bound Definition and event contract",
                "one solver canary only with no same-input retry",
                "body-state/force/torque sidecar retained even on failure",
                "event window and boundary gates remain hard failures",
            ],
        },
        "execution_controls": {
            "read_only_review": True,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
        },
        "provenance_policy": {
            "old_xml_bi4_hdf5_as_inputs": False,
            "old_assets_as_qualification": False,
            "legacy_role": "hash_only",
            "legacy_hashes": contract["legacy_provenance_hash_only"],
        },
        "failure_policy": "A missing or censored contact/event/body-state record blocks the canary result and leaves credit at zero; no retry or matrix expansion is implied.",
    }


def create(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    definition = root / f"{IDENTITY}_Def.xml"
    sidecar = root / "body-state-force-torque-sidecar-schema.json"
    event = root / "event-window-contract.json"
    contract_path = root / "definition-contract.json"
    proposal_path = root / "proposal.json"
    preflight_path = root / "preflight.json"
    write_definition(definition)
    body, fluid, tank = body_model(), fluid_model(), tank_model()
    write_json(sidecar, build_sidecar(body, rel(event)))
    write_json(event, build_event_contract(body, fluid, tank))
    contract = build_contract(root, definition, sidecar, event)
    write_json(contract_path, contract)
    receipt = static_preflight(root, contract, definition, sidecar, event)
    write_json(proposal_path, build_proposal(root, contract, definition, sidecar, event, receipt))
    receipt["proposal"] = bind(proposal_path, "fresh physical-anchor root-review proposal")
    receipt["implementation"] = bind(SCRIPT_PATH, "F6 physical-anchor root-review implementation")
    receipt["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(preflight_path, receipt)
    return receipt


def verify(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    receipt = json.loads((root / "preflight.json").read_text(encoding="utf-8"))
    if receipt["schema"] != PREFLIGHT_SCHEMA:
        raise ValueError("unexpected F6 physical-anchor preflight schema")
    if receipt["qualification_claim"] != "none" or receipt["qualification_credit"] != 0:
        raise ValueError("physical-anchor preflight carries qualification credit")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    receipt = create(args.root)
    verify(args.root)
    print(json.dumps({"status": receipt["status"], "event_window_auditable": receipt["event_window_auditable"], "recommendation": receipt["recommendation"], "preflight": rel(args.root / "preflight.json")}, indent=2))
    return 0 if receipt["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
