#!/usr/bin/env python3
"""Create and preflight one fresh F6 v10 observation-axis input.

This worker writes a new Definition and its contracts from local constants,
then delegates exactly one CPU GenCase/native decode to the reviewed native
preflight implementation.  It never reads a v9 Definition, XML, BI4, HDF5,
trajectory, solver output, queue, registry, ledger, or matrix.  The existing
v10 proposal is context and identity only; all generated inputs below are
fresh.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_cpu_native_preflight_v1 as runner  # noqa: E402


SOURCE_DIR = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-root-review-20260921"
OUTPUT_DIR = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-cpu-native-preflight-20260921"
PROPOSAL = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cadence-revision-v10-20260921/proposal.json"
SOURCE_PROPOSAL = SOURCE_DIR / "proposal.json"
SCRIPT = Path(__file__).resolve()

DEFINITION_ID = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v10_observation_axis_20260921"
BODY_ID = "F6_physical_anchor_body_lambda_v10_20260921"
CASE_ID = "F6_physical_anchor_observation_axis_v10_cpu_native_preflight_20260921"
AUTHORIZATION_ID = "F6_physical_anchor_observation_axis_v10_cpu_native_preflight_authorization_20260921"
REVISION_ID = "F6_gravity_single_body_observation_axis_actual_time_v10"
SCOPE_ID = "F6_fluid_rigid_body_physical_anchor_v2"

CONTRACT_SCHEMA = "core.f6.physical_anchor.definition_contract.v1"
SIDECAR_SCHEMA = "core.f6.physical_anchor.body_state_force_sidecar.v1"
EVENT_SCHEMA = "core.f6.physical_anchor.event_window_contract.v1"
PREFLIGHT_SCHEMA = "core.f6.physical_anchor.cpu_preflight_receipt.v1"

MKBOUND = 8
DP_M = 0.02
RHO_FLUID = 1000.0
RHO_BODY = 780.0
GRAVITY = (0.0, 0.0, -9.81)
OUTPUT_INTERVAL_S = 0.005
TIME_START_S = 0.0
TIME_END_S = 1.5
OBSERVATION_START_S = 1.0
OBSERVATION_END_S = 1.5
CONTACT_TIME_TOLERANCE_S = 0.02

TANK_LOW = (0.0, 0.0, 0.0)
TANK_SIZE = (1.50, 0.60, 0.90)
TANK_CLOSED_FACES = ("bottom", "left", "right", "front", "back")
TANK_OPEN_FACES = ("top",)
FLUID_LOW = (0.18, 0.08, 0.04)
FLUID_SIZE = (1.14, 0.44, 0.24)
BODY_SIZE = (0.20, 0.16, 0.12)
BODY_COM = (0.75, 0.30, 0.55)
BODY_LINEAR_VELOCITY = (0.0, 0.0, 0.0)
BODY_ANGULAR_VELOCITY = (0.0, 0.0, 0.0)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def bind(path: Path, role: str, *, hash_only: bool = False) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        display = path.relative_to(LAB.resolve()).as_posix()
    except ValueError:
        display = str(path)
    return {
        "path": display,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
        "hash_only": bool(hash_only),
    }


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
    drawbox = tuple(value - DP_M for value in FLUID_SIZE)
    return {
        "mkfluid": 0,
        "density_kg_m3": RHO_FLUID,
        "low_m": list(FLUID_LOW),
        "size_m": list(FLUID_SIZE),
        "high_m": list(high(FLUID_LOW, FLUID_SIZE)),
        "free_surface_z_m": FLUID_LOW[2] + FLUID_SIZE[2],
        "initial_velocity_m_s": [0.0, 0.0, 0.0],
        "sampling_contract": {
            "mode": "endpoint_safe_support_centres",
            "dp_m": DP_M,
            "continuous_box_size_m": list(FLUID_SIZE),
            "drawbox_size_m": list(drawbox),
            "drawbox_high_m": list(high(FLUID_LOW, drawbox)),
            "endpoint_rule": "GenCase includes both endpoint support centres; drawbox size is continuous_size_minus_dp",
            "continuous_volume_mass_gate": True,
            "particle_centres_inside_continuous_box": True,
            "mass_gate_definition": "MassFluid * native fluid particle count versus density * continuous_box_volume",
        },
    }


def tank_model() -> dict[str, Any]:
    return {
        "low_m": list(TANK_LOW),
        "size_m": list(TANK_SIZE),
        "high_m": list(high(TANK_LOW, TANK_SIZE)),
        "closed_faces": list(TANK_CLOSED_FACES),
        "open_faces": list(TANK_OPEN_FACES),
        "boundary_method": "standard_closed_faces_with_open_top_contract",
        "entity_boundary_contract": {
            "closed_face_entity": "bottom | left | right | front | back",
            "open_face_entity": "top",
            "open_face_mass_flux_required_kg_s": 0.0,
            "closed_face_contact_required": 0,
            "penetration_required_m": 0.0,
        },
    }


def analytic_events(body: dict[str, Any], fluid: dict[str, Any], tank: dict[str, Any]) -> dict[str, Any]:
    body_bottom = body["bbox_low_m"][2]
    free_surface = fluid["free_surface_z_m"]
    gap = body_bottom - free_surface
    contact_com_z = free_surface + body["size_m"][2] / 2.0
    drop_to_contact = body["com_m"][2] - contact_com_z
    contact_time = math.sqrt(2.0 * drop_to_contact / abs(GRAVITY[2]))
    impact_speed = math.sqrt(2.0 * abs(GRAVITY[2]) * drop_to_contact)
    submerged_fraction = body["density_kg_m3"] / fluid["density_kg_m3"]
    submerged_depth = submerged_fraction * body["size_m"][2]
    equilibrium_bottom = free_surface - submerged_depth
    equilibrium_com = equilibrium_bottom + body["size_m"][2] / 2.0
    equilibrium_top = equilibrium_bottom + body["size_m"][2]
    return {
        "initial_fluid_surface_gap_m": gap,
        "predicted_contact_com_z_m": contact_com_z,
        "predicted_contact_time_s": contact_time,
        "predicted_impact_speed_m_s": impact_speed,
        "contact_prediction_window_s": [max(TIME_START_S, contact_time - CONTACT_TIME_TOLERANCE_S), contact_time + CONTACT_TIME_TOLERANCE_S],
        "equilibrium_submerged_fraction": submerged_fraction,
        "equilibrium_submerged_depth_m": submerged_depth,
        "equilibrium_bottom_z_m": equilibrium_bottom,
        "equilibrium_com_z_m": equilibrium_com,
        "equilibrium_top_z_m": equilibrium_top,
        "tank_bottom_clearance_at_equilibrium_m": equilibrium_bottom - tank["low_m"][2],
        "tank_top_clearance_at_equilibrium_m": tank["high_m"][2] - equilibrium_top,
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
    # XML comments are ignored by GenCase but make the fresh Definition
    # identity explicit even when the physical constants remain unchanged.
    root.append(ET.Comment("F6 v10 observation-axis fresh Definition; no v9 XML/BI4 input"))
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
    fluid_drawbox = tuple(value - DP_M for value in FLUID_SIZE)
    draw_box(commands, point=FLUID_LOW, size=fluid_drawbox, kind="fluid", mk=0, fill="solid")
    draw_box(commands, point=TANK_LOW, size=TANK_SIZE, kind="bound", mk=0, fill="bottom | left | right | front | back")
    sub(commands, "setmkvoid")
    body_low = tuple(c - size / 2.0 for c, size in zip(BODY_COM, BODY_SIZE))
    draw_box(commands, point=body_low, size=BODY_SIZE, kind="bound", mk=MKBOUND, fill="solid")
    floating = sub(sub(casedef, "floatings"), "floating", mkbound=MKBOUND)
    sub(floating, "linearvelini", x=BODY_LINEAR_VELOCITY[0], y=BODY_LINEAR_VELOCITY[1], z=BODY_LINEAR_VELOCITY[2])
    body = body_model()
    sub(floating, "massbody", value=body["mass_kg"])
    sub(floating, "center", x=BODY_COM[0], y=BODY_COM[1], z=BODY_COM[2])
    inertia = body["inertia_about_com_kg_m2"]
    sub(floating, "inertia", x=inertia[0][0], y=inertia[1][1], z=inertia[2][2])
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


def sidecar_contract(event_path: str) -> dict[str, Any]:
    names = [
        ("time_s", "float64", "[n_frames]"),
        ("body_position_m", "float64", "[n_frames,3]"),
        ("body_quaternion_xyzw", "float64", "[n_frames,4]"),
        ("linear_velocity_m_s", "float64", "[n_frames,3]"),
        ("angular_velocity_rad_s", "float64", "[n_frames,3]"),
        ("fluid_force_N", "float64", "[n_frames,3]"),
        ("fluid_torque_Nm", "float64", "[n_frames,3]"),
        ("contact_count", "int32", "[n_frames]"),
        ("penetration_depth_m", "float64", "[n_frames]"),
        ("boundary_contact_count", "int32", "[n_frames]"),
        ("open_face_mass_flux_kg_s", "float64", "[n_frames]"),
        ("event_status", "string", "[n_frames]"),
        ("valid", "bool", "[n_frames]"),
    ]
    return {
        "schema": SIDECAR_SCHEMA,
        "status": "contract_only_no_runtime_sidecar",
        "body_id": BODY_ID,
        "mkbound": MKBOUND,
        "body_geometry_binding": body_model(),
        "required_fields": [{"name": n, "dtype": d, "shape": s} for n, d, s in names],
        "identity_rule": "body_id is immutable; particle_id is not a substitute for body state",
        "force_semantics": "fluid_force_N and fluid_torque_Nm are fluid-body interaction totals with gravity and body weight reported separately",
        "boundary_semantics": "boundary_contact_count covers closed tank faces; open_face_mass_flux_kg_s covers the top opening",
        "event_window_contract": event_path,
        "time_axis_contract": {
            "requested_output_interval_s": OUTPUT_INTERVAL_S,
            "native_time_axis": "solver_reported_actual_TimeStep",
            "max_gap_s": 0.0055,
            "terminal_target_s": TIME_END_S,
            "terminal_overshoot_max_s": 0.0005,
            "coverage_mode": "native_time_bracket_with_max_gap_s",
        },
        "observation_window": {
            "name": "observation_hold",
            "start_s": OBSERVATION_START_S,
            "end_s": OBSERVATION_END_S,
            "requires_equilibrium_claim": False,
            "equilibrium_status": "not_claimed",
        },
        "qualification_claim": "none",
        "qualification_credit": 0,
    }


def event_contract() -> dict[str, Any]:
    body, fluid, tank = body_model(), fluid_model(), tank_model()
    events = analytic_events(body, fluid, tank)
    frames = int(round((TIME_END_S - TIME_START_S) / OUTPUT_INTERVAL_S)) + 1
    return {
        "schema": EVENT_SCHEMA,
        "event_id": "F6_physical_anchor_observation_axis_v10_event_window",
        "body_id": BODY_ID,
        "forcing_mode": "gravity_minus_9p81_fluid_body_coupling_expected",
        "physical_f6_qualification": False,
        "window": {
            "start_s": TIME_START_S,
            "end_s": TIME_END_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "expected_frame_count": frames,
            "settle_hold_start_s": OBSERVATION_START_S,
            "settle_hold_end_s": OBSERVATION_END_S,
        },
        "time_axis_contract": {
            "requested_output_interval_s": OUTPUT_INTERVAL_S,
            "native_time_axis": "solver_reported_actual_TimeStep",
            "frame_count": frames,
            "start_time_s": TIME_START_S,
            "end_time_target_s": TIME_END_S,
            "strictly_increasing": True,
            "max_gap_s": 0.0055,
            "max_gap_basis": "pre_registered_10_percent_envelope_over_requested_interval",
            "terminal_coverage": {
                "mode": "bracket_target",
                "target_end_s": TIME_END_S,
                "last_native_time_must_be_at_least_target": True,
                "terminal_overshoot_max_s": 0.0005,
            },
            "interpolation_for_common_grid": "linear_in_solver_reported_actual_time_only; no future CFD values",
        },
        "observation_window": {
            "name": "observation_hold",
            "start_s": OBSERVATION_START_S,
            "end_s": OBSERVATION_END_S,
            "coverage": "native_time_bracket_with_max_gap_s",
            "requires_equilibrium_claim": False,
            "equilibrium_status": "not_claimed",
            "equilibrium_thresholds": None,
        },
        "predicted_events": events,
        "required_runtime_events": [
            "body_free_fall_started",
            "fluid_contact_observed_once_or_more",
            "buoyant_response_observed",
            "no_closed_tank_face_contact_or_penetration",
            "no_unaccounted_open_top_mass_flux",
            "observation_hold_present_and_uncensored",
        ],
        "completion_rule": [
            "all 301 frames exist on the solver-reported actual TimeStep axis",
            "body_id is present on every row and all body/force/torque values are finite",
            "all native gaps are <= 0.0055 s and terminal time is in [1.5,1.5005] s",
            "fluid-contact time lies within the independently recomputed prediction window",
            "closed-face contact count and penetration depth are zero throughout",
            "open-top mass flux is zero",
            "the final [1.0,1.5] s observation interval is bracketed without an equilibrium claim",
        ],
        "uncensored_required": True,
        "status_without_runtime": "auditable_prediction_pending_runtime_event_window",
        "qualification_claim": "none",
        "qualification_credit": 0,
    }


def definition_contract(definition: Path, sidecar: Path, event: Path) -> dict[str, Any]:
    body, fluid, tank = body_model(), fluid_model(), tank_model()
    return {
        "schema": CONTRACT_SCHEMA,
        "contract_id": "F6_physical_anchor_observation_axis_definition_contract_20260921",
        "status": "fresh_definition_written_cpu_native_preflight_pending",
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_physical_anchor_v2",
        "revision_id": REVISION_ID,
        "case_id": DEFINITION_ID,
        "body_id": BODY_ID,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "physical_f6_qualification": False,
        "execution_profile": {"model": "gpt-5.6-luna", "reasoning": "max"},
        "implementation": bind(SCRIPT, "fresh v10 observation-axis worker"),
        "fresh_input": {
            "definition": bind(definition, "fresh v10 gravity=-9.81 Definition"),
            "old_assets_reused": False,
            "old_xml_copied": False,
            "old_bi4_reused": False,
            "old_hdf5_reused": False,
            "old_trajectory_reused": False,
        },
        "gravity_m_s2": list(GRAVITY),
        "fluid": fluid,
        "tank": tank,
        "body": body,
        "predicted_events": analytic_events(body, fluid, tank),
        "sidecar_schema": bind(sidecar, "fresh v10 body-state/force/torque sidecar schema"),
        "event_window": bind(event, "fresh v10 analytical event-window contract"),
        "time_axis_contract": {
            "requested_output_interval_s": OUTPUT_INTERVAL_S,
            "native_time_axis": "solver_reported_actual_TimeStep",
            "max_gap_s": 0.0055,
            "terminal_overshoot_max_s": 0.0005,
            "coverage_mode": "native_time_bracket_with_max_gap_s",
        },
        "observation_window_contract": {
            "name": "observation_hold",
            "start_s": OBSERVATION_START_S,
            "end_s": OBSERVATION_END_S,
            "requires_equilibrium_claim": False,
            "equilibrium_status": "not_claimed",
        },
        "input_binding": {
            "proposal": bind(SOURCE_PROPOSAL, "hash-bound derived v10 proposal"),
            "proposal_context": bind(PROPOSAL, "existing v10 proposal identity context"),
            "definition_id": DEFINITION_ID,
            "case_id": CASE_ID,
            "revision_id": REVISION_ID,
            "body_id": BODY_ID,
            "fresh_generated_xml_required": True,
            "fresh_generated_bi4_required": True,
        },
        "geometry_contract": {
            "closed_face_entity": "bottom | left | right | front | back",
            "open_face_entity": "top",
            "open_face_present_in_definition": False,
            "open_face_mass_flux_required_kg_s": 0.0,
            "closed_face_contact_required": 0,
            "penetration_required_m": 0.0,
        },
        "gate_policy": {
            "static_cpu_only": True,
            "exactly_one_gencase": True,
            "exactly_one_native_decode": True,
            "event_window_complete_required": False,
            "solver_canary_authorization_in_this_receipt": False,
            "qualification_credit": 0,
        },
        "provenance_policy": {
            "old_xml_bi4_hdf5_as_inputs": False,
            "old_trajectory_as_input": False,
            "prior_v9_context_hash_only": True,
            "prior_v9_context_not_read_as_input": True,
        },
        "execution_controls": {
            "definition_written": True,
            "xml_parsed": False,
            "cpu_preflight_run": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
    }


def static_preflight(definition: Path, contract: dict[str, Any], sidecar: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, passed: bool, detail: Any) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    root = ET.parse(definition).getroot()
    xml_text = definition.read_text(encoding="utf-8")
    forbidden = ["F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".bi4", ".h5"]
    check("fresh_xml_parse", root.tag == "case", {"root_tag": root.tag})
    check("fresh_xml_no_legacy_input", not any(token in xml_text for token in forbidden), {"forbidden_tokens": forbidden})
    gravity = root.find("./casedef/constantsdef/gravity")
    observed_gravity = [float(gravity.get(axis)) for axis in "xyz"] if gravity is not None else []
    check("gravity_binding", observed_gravity == list(GRAVITY), {"observed": observed_gravity, "expected": list(GRAVITY)})
    geometry_definition = root.find("./casedef/geometry/definition")
    observed_dp = float(geometry_definition.get("dp")) if geometry_definition is not None else float("nan")
    check("fresh_resolution", math.isclose(observed_dp, DP_M, rel_tol=0.0, abs_tol=1e-12), {"observed": observed_dp, "expected": DP_M})

    drawboxes = root.findall("./casedef/geometry/commands/mainlist/drawbox")
    body, fluid, tank = contract["body"], contract["fluid"], contract["tank"]
    drawbox_size = fluid["sampling_contract"]["drawbox_size_m"]
    drawbox_details = []
    for node in drawboxes:
        point = node.find("point")
        size = node.find("size")
        drawbox_details.append({
            "fill": node.findtext("boxfill"),
            "point": [float(point.get(axis)) for axis in "xyz"] if point is not None else None,
            "size": [float(size.get(axis)) for axis in "xyz"] if size is not None else None,
        })
    check("fluid_drawbox_binding", len(drawboxes) >= 1 and drawbox_details[0]["point"] == fluid["low_m"] and drawbox_details[0]["size"] == drawbox_size, {"observed": drawbox_details[0] if drawbox_details else None, "expected_low_m": fluid["low_m"], "expected_drawbox_size_m": drawbox_size})
    tank_fill = drawbox_details[1]["fill"] if len(drawbox_details) > 1 else ""
    body_fill = drawbox_details[2]["fill"] if len(drawbox_details) > 2 else ""
    check("geometry_opening_entity_boundary", len(drawboxes) == 3 and all(face in tank_fill for face in TANK_CLOSED_FACES) and "top" not in tank_fill and body_fill == "solid", {"drawboxes": drawbox_details, "closed_faces": list(TANK_CLOSED_FACES), "open_faces": list(TANK_OPEN_FACES)})
    floating = root.find("./casedef/floatings/floating")
    body_expected = body_model()
    massbody = floating.find("massbody") if floating is not None else None
    center = floating.find("center") if floating is not None else None
    inertia = floating.find("inertia") if floating is not None else None
    observed_mass = float(massbody.get("value")) if massbody is not None else float("nan")
    observed_center = [float(center.get(axis)) for axis in "xyz"] if center is not None else []
    observed_inertia = [float(inertia.get(axis)) for axis in "xyz"] if inertia is not None else []
    expected_inertia = [body_expected["inertia_about_com_kg_m2"][i][i] for i in range(3)]
    check("body_mass_com_inertia_binding", floating is not None and floating.get("mkbound") == str(MKBOUND) and math.isclose(observed_mass, body_expected["mass_kg"], rel_tol=0.0, abs_tol=1e-12) and observed_center == body_expected["com_m"] and observed_inertia == expected_inertia, {"mkbound": floating.get("mkbound") if floating is not None else None, "massbody_kg": observed_mass, "center_m": observed_center, "inertia_diag_kg_m2": observed_inertia, "expected_mass_kg": body_expected["mass_kg"], "expected_center_m": body_expected["com_m"], "expected_inertia_diag_kg_m2": expected_inertia})

    expected_events = analytic_events(body, fluid, tank)
    window = event["window"]
    observation = event["observation_window"]
    check("event_window_recomputed", event["body_id"] == BODY_ID and event["predicted_events"] == expected_events and window["expected_frame_count"] == 301 and window["start_s"] == TIME_START_S and window["end_s"] == TIME_END_S, {"predicted_events": expected_events, "window": window})
    check("observation_window_no_equilibrium_claim", observation["start_s"] == OBSERVATION_START_S and observation["end_s"] == OBSERVATION_END_S and observation["requires_equilibrium_claim"] is False and observation["equilibrium_status"] == "not_claimed", observation)
    axis = event.get("time_axis_contract", {})
    check("actual_timestep_bracket_contract", axis.get("native_time_axis") == "solver_reported_actual_TimeStep" and axis.get("max_gap_s") == 0.0055 and axis.get("terminal_coverage", {}).get("terminal_overshoot_max_s") == 0.0005 and axis.get("terminal_coverage", {}).get("mode") == "bracket_target", axis)
    volume_mass = math.prod(FLUID_SIZE) * RHO_FLUID
    check("fluid_continuum_mass_contract", math.isclose(volume_mass, 120.384, rel_tol=0.0, abs_tol=1e-12), {"continuum_fluid_mass_kg": volume_mass, "density_kg_m3": RHO_FLUID, "continuous_volume_m3": math.prod(FLUID_SIZE)})
    check("sidecar_identity_binding", sidecar.get("schema") == SIDECAR_SCHEMA and sidecar.get("body_id") == BODY_ID and len(sidecar.get("required_fields", [])) == 13, {"schema": sidecar.get("schema"), "body_id": sidecar.get("body_id"), "required_field_count": len(sidecar.get("required_fields", []))})
    check("event_identity_binding", event.get("schema") == EVENT_SCHEMA and event.get("body_id") == BODY_ID and event.get("physical_f6_qualification") is False and event.get("uncensored_required") is True, {"schema": event.get("schema"), "body_id": event.get("body_id"), "physical_f6_qualification": event.get("physical_f6_qualification")})
    passed = all(item["passed"] for item in checks.values())
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": "cpu_physical_anchor_preflight_pass" if passed else "cpu_physical_anchor_preflight_failed",
        "gate_passed": passed,
        "event_window_auditable": checks["event_window_recomputed"]["passed"],
        "event_window_complete": False,
        "event_window_status": "auditable_prediction_pending_runtime_event_window",
        "checks": checks,
        "recommendation": "run_exactly_one_cpu_native_preflight" if passed else "retain_negative_evidence_do_not_run_native_preflight",
        "solver_canary_authorized_in_this_receipt": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "execution_controls": {
            "definition_written": True,
            "xml_parsed": True,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
        "failure_policy": "Every failed gate is retained as negative evidence; qualification_claim remains none and qualification_credit remains zero.",
        "contract": bind(SOURCE_DIR / "definition-contract.json", "fresh v10 Definition contract"),
        "definition": bind(definition, "fresh v10 gravity=-9.81 Definition"),
        "sidecar_schema": bind(SOURCE_DIR / "body-state-force-torque-sidecar-schema.json", "fresh v10 sidecar schema"),
        "event_window": bind(SOURCE_DIR / "event-window-contract.json", "fresh v10 event-window contract"),
        "proposal": bind(SOURCE_PROPOSAL, "hash-bound derived v10 proposal"),
        "proposal_context": bind(PROPOSAL, "existing v10 proposal identity context"),
    }


def prepare_source() -> tuple[Path, dict[str, Any]]:
    if SOURCE_DIR.exists() and any(SOURCE_DIR.iterdir()):
        raise RuntimeError(f"fresh source directory is not empty: {SOURCE_DIR}")
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise RuntimeError(f"one-shot output directory is not empty: {OUTPUT_DIR}")
    if not PROPOSAL.is_file():
        raise FileNotFoundError(PROPOSAL)
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    if proposal.get("proposal_id") != "F6_physical_anchor_observation_axis_v10_20260921":
        raise ValueError("unexpected v10 proposal identity")
    definition = SOURCE_DIR / f"{DEFINITION_ID}_Def.xml"
    sidecar_path = SOURCE_DIR / "body-state-force-torque-sidecar-schema.json"
    event_path = SOURCE_DIR / "event-window-contract.json"
    contract_path = SOURCE_DIR / "definition-contract.json"
    static_path = SOURCE_DIR / "preflight-static.json"
    derived_proposal = dict(proposal)
    derived_proposal["status"] = "root_review_only_fresh_definition_cpu_native_preflight_pending"
    derived_proposal["fresh_identity"] = dict(derived_proposal.get("fresh_identity", {}))
    derived_proposal["fresh_identity"]["body_id"] = BODY_ID
    derived_proposal["fresh_identity"]["fresh_generated_xml_required"] = True
    derived_proposal["fresh_identity"]["fresh_generated_bi4_required"] = True
    derived_proposal["root_review_decision"] = {
        "cpu_native_preflight_authorized": True,
        "solver_canary_authorized_now": False,
        "solver_canary_authorized_in_this_receipt": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
    }
    derived_proposal["derived_artifact"] = {
        "role": "fresh v10 preflight binding only",
        "source_proposal": bind(PROPOSAL, "existing v10 proposal identity context"),
        "old_xml_bi4_hdf5_reused_as_input": False,
        "old_trajectory_reused_as_input": False,
    }
    derived_proposal["fresh_identity"]["body_id"] = BODY_ID
    derived_proposal["time_axis_contract"] = json.loads(json.dumps(event_contract()["time_axis_contract"]))
    derived_proposal["observation_window_contract"] = json.loads(json.dumps(event_contract()["observation_window"]))
    write_json(SOURCE_PROPOSAL, derived_proposal)
    write_definition(definition)
    write_json(sidecar_path, sidecar_contract(event_path.relative_to(LAB).as_posix()))
    write_json(event_path, event_contract())
    contract = definition_contract(definition, sidecar_path, event_path)
    write_json(contract_path, contract)
    static = static_preflight(definition, contract, json.loads(sidecar_path.read_text(encoding="utf-8")), json.loads(event_path.read_text(encoding="utf-8")))
    write_json(static_path, static)
    return definition, static


def configure_runner(definition: Path) -> None:
    # The runner is reused as an execution implementation only.  All v10
    # identity, constants and contracts are bound here; no v9 file is read.
    physical = runner.physical
    physical.IDENTITY = DEFINITION_ID
    physical.BODY_ID = BODY_ID
    physical.MKBOUND = MKBOUND
    physical.DP_M = DP_M
    physical.GRAVITY = GRAVITY
    physical.OUTPUT_INTERVAL_S = OUTPUT_INTERVAL_S
    physical.TIME_START_S = TIME_START_S
    physical.TIME_END_S = TIME_END_S
    physical.SIDECAR_SCHEMA = SIDECAR_SCHEMA
    physical.EVENT_SCHEMA = EVENT_SCHEMA
    runner.DEFINITION_ID = DEFINITION_ID
    runner.BODY_ID = BODY_ID
    runner.CASE_ID = CASE_ID
    runner.AUTHORIZATION_ID = AUTHORIZATION_ID
    # The generic v1 runner emits its historical scope label.  Bind every
    # v10 receipt to the fresh v2 scope without modifying the old runner or
    # invalidating immutable v1/v9 receipts.
    runner.SCOPE_ID = SCOPE_ID
    runner.OUTPUT_DIR = OUTPUT_DIR
    runner.SOURCE_DIR = SOURCE_DIR
    runner.DEFINITION = definition
    runner.CONTRACT = SOURCE_DIR / "definition-contract.json"
    runner.SIDECAR = SOURCE_DIR / "body-state-force-torque-sidecar-schema.json"
    runner.EVENT = SOURCE_DIR / "event-window-contract.json"
    runner.STATIC_PREFLIGHT = SOURCE_DIR / "preflight-static.json"
    runner.PROPOSAL = SOURCE_PROPOSAL


def enrich_receipt(receipt: dict[str, Any], definition: Path, static: dict[str, Any]) -> dict[str, Any]:
    generated_xml = receipt.get("gencase_generated_xml") or receipt.get("gencase", {}).get("generated_xml")
    native_bi4 = receipt.get("native_bi4") or receipt.get("gencase", {}).get("native_bi4")
    identity_checks = {
        "definition_id_exact": receipt.get("definition_id") == DEFINITION_ID,
        "body_id_exact": receipt.get("body_id") == BODY_ID,
        "case_id_exact": receipt.get("case_id") == CASE_ID,
        "revision_id_exact": REVISION_ID == json.loads((SOURCE_DIR / "definition-contract.json").read_text(encoding="utf-8"))["revision_id"],
        "fresh_definition_filename": definition.name.startswith(DEFINITION_ID),
        "fresh_generated_xml_filename": bool(generated_xml and Path(generated_xml["path"]).name.startswith(CASE_ID)),
        "fresh_generated_bi4_filename": bool(native_bi4 and Path(native_bi4["path"]).name.startswith(CASE_ID)),
    }
    hash_refs = {
        "definition": bind(definition, "fresh v10 Definition input"),
        "definition_contract": bind(SOURCE_DIR / "definition-contract.json", "fresh v10 Definition contract"),
        "sidecar_schema": bind(SOURCE_DIR / "body-state-force-torque-sidecar-schema.json", "fresh v10 sidecar schema"),
        "event_window_contract": bind(SOURCE_DIR / "event-window-contract.json", "fresh v10 event-window contract"),
        "proposal": bind(SOURCE_PROPOSAL, "hash-bound derived v10 proposal"),
        "proposal_context": bind(PROPOSAL, "existing v10 proposal identity context"),
        "worker": bind(SCRIPT, "fresh v10 worker"),
    }
    if generated_xml:
        hash_refs["generated_xml"] = generated_xml
    if native_bi4:
        hash_refs["generated_bi4"] = native_bi4
    generated_xml_text = ""
    if generated_xml and Path(generated_xml["path"]).is_file():
        generated_xml_text = Path(generated_xml["path"]).read_text(encoding="utf-8")
    identity_checks["generated_xml_no_legacy_input"] = not any(token in generated_xml_text for token in ("F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".h5")) if generated_xml_text else False
    identity_checks["all_hash_bindings_present"] = all(item.get("sha256") and item.get("bytes", 0) > 0 for item in hash_refs.values())
    receipt["fresh_identity"] = {
        "definition_id": DEFINITION_ID,
        "case_id": CASE_ID,
        "revision_id": REVISION_ID,
        "body_id": BODY_ID,
        "proposal_id": "F6_physical_anchor_observation_axis_v10_20260921",
        "checks": identity_checks,
    }
    receipt["scope_id"] = SCOPE_ID
    receipt["input_hashes"] = hash_refs
    receipt["event_window"] = {
        "status": "auditable_prediction_pending_runtime_event_window",
        "complete": False,
        "predicted_contact_window_s": json.loads((SOURCE_DIR / "event-window-contract.json").read_text(encoding="utf-8"))["predicted_events"]["contact_prediction_window_s"],
        "observation_window_s": [OBSERVATION_START_S, OBSERVATION_END_S],
        "requires_equilibrium_claim": False,
        "equilibrium_status": "not_claimed",
        "native_time_axis_contract": "solver_reported_actual_TimeStep",
        "requested_output_interval_s": OUTPUT_INTERVAL_S,
        "expected_frame_count": 301,
    }
    receipt["geometry_opening_entity_boundary"] = static["checks"]["geometry_opening_entity_boundary"]
    receipt["mass_com_inertia"] = {
        "fluid": receipt.get("native", {}),
        "body": receipt.get("generated_body", {}),
    }
    receipt["execution_profile"] = {"model": "gpt-5.6-luna", "reasoning": "max"}
    receipt["negative_evidence"] = {
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_submission": False,
    }
    if receipt.get("status") == "cpu_native_preflight_pass_exact_one" and not all(identity_checks.values()):
        receipt["status"] = "cpu_native_preflight_failed_hard"
        receipt["preflight_pass"] = False
        receipt["failure"] = {"kind": "fresh_identity_or_hash_binding_failed", "checks": identity_checks}
    return receipt


def run_once() -> dict[str, Any]:
    definition, static = prepare_source()
    if not static.get("gate_passed"):
        # Static failure is retained and deliberately blocks native execution.
        static["negative_evidence"] = {"qualification_claim": "none", "qualification_credit": 0, "T1": False}
        write_json(SOURCE_DIR / "preflight-static.json", static)
        return static
    configure_runner(definition)
    receipt = runner.run(OUTPUT_DIR)
    # Rebind the generic runner's authorization and one-shot lock metadata to
    # the new v2 scope.  This is metadata-only; GenCase/native outputs remain
    # unchanged and no second invocation is permitted.
    authorization_path = OUTPUT_DIR / "authorization.json"
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["scope_id"] = SCOPE_ID
    write_json(authorization_path, authorization)
    lock_path = OUTPUT_DIR / "one-shot-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["authorization_sha256"] = sha256(authorization_path)
    write_json(lock_path, lock)
    receipt["scope_id"] = SCOPE_ID
    receipt["authorization"] = bind(authorization_path, "root authorization for exactly one CPU/native preflight")
    receipt["one_shot_lock"] = bind(lock_path, "pre-execution same-input retry lock")
    receipt = enrich_receipt(receipt, definition, static)
    write_json(OUTPUT_DIR / "preflight.json", receipt)
    runner.verify_receipt(OUTPUT_DIR / "preflight.json")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    if Path(args.output).resolve() != OUTPUT_DIR.resolve():
        raise ValueError("custom output is disabled to preserve exactly-one preflight identity")
    receipt = run_once()
    print(json.dumps({"status": receipt.get("status"), "preflight_pass": receipt.get("preflight_pass", receipt.get("gate_passed", False)), "output": str(OUTPUT_DIR / "preflight.json")}, ensure_ascii=False))
    return 0 if receipt.get("status") == "cpu_native_preflight_pass_exact_one" else 1


if __name__ == "__main__":
    raise SystemExit(main())
