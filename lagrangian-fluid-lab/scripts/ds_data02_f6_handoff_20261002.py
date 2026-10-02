#!/usr/bin/env python3
"""F6 handoff_20261002: strict-continuum native floating-body preflight.

This module is deliberately additive.  It does not edit or reuse the consumed
F6 parent/fallback definitions.  It creates a fresh two-mechanism mother case
with one fixed continuous geometry per mechanism and three DP cell-centre
representations.  The only runnable work produced here is bounded CPU GenCase
and the official PartVTK initial-state audit; this module never launches a
solver.

The old fallback-02 recipe used ``fillbox|void``.  GenCase consequently removed
DP-dependent support volumes around the finite walls/body/paddle, while the
registered denominator stayed the same.  The new mother uses a direct solid
fluid drawbox whose first centre and draw extent are derived from one frozen
continuous fluid box.  The floating body starts exactly above the free-surface
centre envelope, so the initial real submerged-body volume is zero and is
recorded explicitly.  This is a physical release/impact scope, not a claim
that the old fallback or old stage-8 bodies are equivalent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6/handoff_20261002"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
RAW_FAMILY_ROOT = DATA_ROOT / "families/F6"
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4")
BIN_ROOT = OFFICIAL_ROOT / "bin/linux"
GENCASE = BIN_ROOT / "GenCase_linux64"
PARTVTK = BIN_ROOT / "PartVTK_linux64"
SOLVER = BIN_ROOT / "DualSPHysics5.4_linux64"
FLOATING_INFO = BIN_ROOT / "FloatingInfo_linux64"
COMPUTE_FORCES = BIN_ROOT / "ComputeForces_linux64"
OFFICIAL_SIMPLE = OFFICIAL_ROOT / "examples/main/11_Floating/CaseFloating_Def.xml"
OFFICIAL_WAVE = OFFICIAL_ROOT / "examples/main/12_FloatingWaves/CaseFloatingWavesVal2_Def.xml"
VERSION = "ds_data02_f6_handoff_20261002.v1"
SCHEMA = "ds-data-02.f6.handoff-20261002.v1"
WINDOW = (0.0, 12.0)
CONTROL_DT = 0.01
CONTROL_ROWS = int(round((WINDOW[1] - WINDOW[0]) / CONTROL_DT)) + 1
OUTPUT_DT = 0.05
RHO_WATER = 1000.0
MASS_TOLERANCE = 0.01

# Every physical endpoint below is a multiple of 0.4 m.  It is therefore on
# the lattice for all three DPs, while the fluid first centre is generated from
# the same continuous low/high faces at every resolution.
DP_LADDER = (
    ("coarse", 0.08),
    ("medium", 0.05),
    ("fine", 0.04),
)
TANK = {"low": [0.0, 0.0, 0.0], "size": [4.8, 2.4, 2.4]}
FLUID = {"low": [0.4, 0.4, 0.04], "size": [4.0, 1.6, 0.8]}
BODY = {
    "kind": "box",
    "mkbound": 50,
    "point": [2.0, 0.8, 0.84],
    "size": [0.8, 0.8, 0.4],
    "mass_kg": 128.0,
}
PADDLE = {
    "mkbound": 10,
    "point": [0.0, 0.0, 0.04],
    "size": [0.4, 2.4, 0.8],
}
CONTROL = {
    "simple_free_response": {
        "mode": "initial_release",
        "wave_height_m": 0.0,
        "wave_period_s": None,
        "ramp_periods": 0.0,
        "heave_offset_m": 0.0,
    },
    "wave_no_contact": {
        "mode": "regular_piston_wave",
        "wave_height_m": 0.12,
        "wave_period_s": 1.6,
        "ramp_periods": 3.0,
        "heave_offset_m": 0.0,
    },
}
MECHANISMS = {
    "simple_free_response": {
        "case_prefix": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE",
        "physical_case_id": "F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RELEASE_IMPACT",
        "geometry_family_id": "F6_HANDOFF_20261002_BOX_TANK_RELEASE",
        "control_family_id": "F6_CTRL_INITIAL_RELEASE",
        "coordinate_frame_id": "tank_attached_inertial",
        "template": OFFICIAL_SIMPLE,
        "description": "有限三维槽内箱浮体从自由液面释放，记录 heave/roll/pitch 与冲击后的衰减。",
        "events": [
            "initial_still_water",
            "release_at_zero",
            "first_water_contact",
            "successive_response_peaks",
            "decay_tail",
            "final_mass_momentum_rigid_audit",
        ],
    },
    "wave_no_contact": {
        "case_prefix": "F6_HANDOFF_20261002_WAVE_NO_CONTACT",
        "physical_case_id": "F6_HANDOFF_20261002_WAVE_NO_CONTACT_PISTON",
        "geometry_family_id": "F6_HANDOFF_20261002_BOX_TANK_PISTON",
        "control_family_id": "F6_CTRL_REGULAR_PISTON_WAVE",
        "coordinate_frame_id": "world_tank_attached_inertial",
        "template": OFFICIAL_WAVE,
        "description": "有限三维槽内规则 piston 波激励自由箱浮体；paddle 有实际 moving 粒子且不启用接触求解。",
        "events": [
            "initial_still_water",
            "wave_ramp",
            "first_wave_arrival",
            "steady_wave_cycles",
            "last_cycle_and_decay",
            "final_mass_momentum_rigid_audit",
        ],
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def fmt(value: float) -> str:
    return f"{value:.12g}"


def body_volume() -> float:
    return math.prod(BODY["size"])


def body_inertia() -> list[list[float]]:
    m = float(BODY["mass_kg"])
    a, b, c = (float(x) for x in BODY["size"])
    return [
        [m * (b * b + c * c) / 12.0, 0.0, 0.0],
        [0.0, m * (a * a + c * c) / 12.0, 0.0],
        [0.0, 0.0, m * (a * a + b * b) / 12.0],
    ]


def expected_fluid_particles(dp: float) -> int:
    counts = [round(float(size) / dp) for size in FLUID["size"]]
    if any(abs(float(size) / dp - n) > 1.0e-8 for size, n in zip(FLUID["size"], counts)):
        raise ValueError(f"fluid size is not DP divisible: {dp}")
    return math.prod(counts)


def continuous_fluid_volume() -> float:
    return math.prod(FLUID["size"])


def initial_submerged_body_volume() -> float:
    # The body lower face is exactly the frozen fluid upper face.  The
    # cell-centre envelopes have a half-DP gap at every resolution, so the
    # initial physical intersection is zero by construction.
    fluid_top = FLUID["low"][2] + FLUID["size"][2]
    body_bottom = BODY["point"][2]
    overlap_z = max(0.0, min(fluid_top, body_bottom + BODY["size"][2]) - max(FLUID["low"][2], body_bottom))
    overlap_x = max(0.0, min(FLUID["low"][0] + FLUID["size"][0], BODY["point"][0] + BODY["size"][0]) - max(FLUID["low"][0], BODY["point"][0]))
    overlap_y = max(0.0, min(FLUID["low"][1] + FLUID["size"][1], BODY["point"][1] + BODY["size"][1]) - max(FLUID["low"][1], BODY["point"][1]))
    volume = overlap_x * overlap_y * overlap_z
    return 0.0 if volume <= 1.0e-12 else volume


def case_id(mechanism: str, resolution: str) -> str:
    return f"{MECHANISMS[mechanism]['case_prefix']}_{resolution.upper()}"


def _first_center(low: list[float], dp: float) -> list[float]:
    return [float(value) + dp / 2.0 for value in low]


def _draw_size(size: list[float], dp: float) -> list[float]:
    return [float(value) - dp for value in size]


def _control_csv(path: Path, mechanism: str) -> dict[str, Any]:
    control = CONTROL[mechanism]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# F6 handoff_20261002 control ledger; source of prescribed control only\n")
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["time_s", "mode", "release_time_s", "heave_offset_m", "wave_height_m", "wave_period_s", "ramp_periods"])
        for index in range(CONTROL_ROWS):
            time_s = index * CONTROL_DT
            writer.writerow([
                fmt(time_s), control["mode"], "0", fmt(control["heave_offset_m"]),
                fmt(control["wave_height_m"]), "" if control["wave_period_s"] is None else fmt(control["wave_period_s"]),
                fmt(control["ramp_periods"]),
            ])
    return {"path": str(path.resolve()), "sha256": sha256(path), "rows": CONTROL_ROWS, "window_s": list(WINDOW), "dt_s": CONTROL_DT}


def _native_json(path: Path, mechanism: str, resolution: str, dp: float) -> dict[str, Any]:
    cid = case_id(mechanism, resolution)
    template = MECHANISMS[mechanism]["template"]
    payload = {
        "schema": "ds-data-02.f6.native_input.handoff_20261002.v1",
        "family_id": "F6",
        "case_id": cid,
        "mechanism_id": mechanism,
        "resolution_id": resolution,
        "solver_dimension": 3,
        "coordinate_frame_id": MECHANISMS[mechanism]["coordinate_frame_id"],
        "solver_parameters": {
            "SavePosDouble": 1, "StepAlgorithm": 2, "Kernel": 2, "ViscoTreatment": 2,
            "Visco": 1.0e-6, "DensityDT": 2, "DensityDTvalue": 0.1, "Shifting": 0,
            "RigidAlgorithm": 1, "FtPause": 0.0, "DtFixed": 0.0, "TimeMax": WINDOW[1],
            "TimeOut": OUTPUT_DT, "PartsOutMax": 1.0, "RhopOutMin": 700.0, "RhopOutMax": 1300.0,
        },
        "rigid_body": {
            "body_type": "native_rigid_free_body",
            "floatingtype": 2,
            "massbody_kg": BODY["mass_kg"],
            "particle_mass_is_separate_from_aggregate": True,
            "volume_m3": body_volume(),
            "density_ratio_to_water": BODY["mass_kg"] / (body_volume() * RHO_WATER),
            "source_inertia_kg_m2": body_inertia(),
            "initial_pose": {"center_m": [2.4, 1.2, 1.04], "orientation_euler_deg": [0.0, 0.0, 0.0]},
            "initial_submerged_body_volume_m3": initial_submerged_body_volume(),
            "required_state_fields": ["pose", "orientation", "linear_velocity", "angular_velocity", "mass", "inertia", "force", "torque"],
            "state_sources": ["generated_execution_particles.floating", "FloatingInfo", "ComputeForces"],
        },
        "fluid_ledger": {
            "fluidtype": 3,
            "density_kg_m3": RHO_WATER,
            "continuous_box_low_m": FLUID["low"],
            "continuous_box_size_m": FLUID["size"],
            "continuous_box_volume_m3": continuous_fluid_volume(),
            "initial_submerged_body_volume_m3": initial_submerged_body_volume(),
            "strict_continuous_fluid_volume_m3": continuous_fluid_volume() - initial_submerged_body_volume(),
            "strict_continuous_fluid_mass_kg": (continuous_fluid_volume() - initial_submerged_body_volume()) * RHO_WATER,
            "mass_per_particle_from_generated_xml": True,
            "cell_centre_population": True,
        },
        "geometry_contract": {
            "tank_low_m": TANK["low"],
            "tank_size_m": TANK["size"],
            "physical_wall_endpoints_fixed_across_dp": True,
            "paddle": PADDLE if mechanism == "wave_no_contact" else None,
            "body_fluid_overlap_initial": "zero: body lower face equals fluid upper face; cell centres remain separated",
            "finite_walls": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
        },
        "contact_policy": {"RigidAlgorithm": 1, "chrono": False, "contact_solver": False, "wall_contact": "not a mechanism; finite walls are clearance boundaries"},
        "source_template": {"path": str(template.resolve()), "sha256": sha256(template) if template.is_file() else None, "role": "official syntax/provenance only"},
        "generator_version": VERSION,
        "dp_m": dp,
    }
    write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def _normal_json(path: Path, mechanism: str, resolution: str) -> dict[str, Any]:
    payload = {
        "schema": "ds-data-02.f6.normal_geometry_binding.handoff_20261002.v1",
        "family_id": "F6",
        "case_id": case_id(mechanism, resolution),
        "mechanism_id": mechanism,
        "resolution_id": resolution,
        "normal_source": "GenCase generated *_Actual.vtk; no post-hoc wall projection",
        "geometry_semantics": {
            "outer_wall": "finite bottom,left,right,front,back",
            "free_surface": "open top",
            "floating_body": "mkbound=50, floatingtype=2",
            "paddle": "mkbound=10, actual moving object" if mechanism == "wave_no_contact" else None,
        },
        "normal_audit": {"finite_wall_faces": ["bottom", "left", "right", "front", "back"], "no_domain_or_rhop_relaxation": True},
    }
    write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def _definition_xml(mechanism: str, resolution: str, dp: float) -> str:
    cid = case_id(mechanism, resolution)
    fluid_point = _first_center(FLUID["low"], dp)
    fluid_draw = _draw_size(FLUID["size"], dp)
    pointmax = [float(TANK["size"][axis]) + dp for axis in range(3)]
    body_point, body_size = BODY["point"], BODY["size"]
    paddle_block = ""
    motion_block = ""
    special_block = ""
    if mechanism == "wave_no_contact":
        pp, ps = PADDLE["point"], PADDLE["size"]
        paddle_block = f'''
                    <setdrawmode mode="full" />
                    <setmkbound mk="{PADDLE["mkbound"]}" />
                    <drawbox cmt="Actual moving piston; no fluid overlap">
                        <boxfill>solid</boxfill>
                        <point x="{fmt(pp[0])}" y="{fmt(pp[1])}" z="{fmt(pp[2])}" />
                        <size x="{fmt(ps[0])}" y="{fmt(ps[1])}" z="{fmt(ps[2])}" />
                    </drawbox>'''
        motion_block = '''
        <motion>
            <objreal ref="10">
                <begin mov="1" start="0" />
                <mvnull id="1" />
            </objreal>
        </motion>'''
        special_block = '''
            <special>
                <wavepaddles>
                    <piston>
                        <mkbound value="10" />
                        <waveorder value="2" />
                        <start value="0" />
                        <duration value="0" />
                        <depth value="0.84" />
                        <_fixeddepth value="0" />
                        <pistondir x="1" y="0" z="0" />
                        <waveheight value="0.12" />
                        <waveperiod value="1.6" />
                        <phase value="0" />
                        <ramp value="3" />
                        <savemotion periods="8" periodsteps="20" xpos="2.4" zpos="-0.84" />
                    </piston>
                </wavepaddles>
            </special>'''
    template_name = "main/11_Floating/CaseFloating_Def.xml" if mechanism == "simple_free_response" else "main/12_FloatingWaves/CaseFloatingWavesVal2_Def.xml"
    return f'''<?xml version="1.0" encoding="UTF-8" ?>
<!-- F6 handoff_20261002; case={cid}; official syntax={template_name}. -->
<case>
    <casedef>
        <constantsdef>
            <gravity x="0" y="0" z="-9.81" units_comment="m/s^2" />
            <rhop0 value="1000" units_comment="kg/m^3" />
            <rhopgradient value="3" />
            <hswl value="0" auto="true" />
            <gamma value="7" />
            <speedsystem value="0" auto="true" />
            <coefsound value="20" />
            <speedsound value="0" auto="true" />
            <coefh value="1.2" />
            <cflnumber value="0.2" />
        </constantsdef>
        <mkconfig boundcount="230" fluidcount="9">
            <mkorientfluid mk="0" orient="Xyz" />
        </mkconfig>
        <geometry>
            <definition dp="{fmt(dp)}">
                <pointref x="0" y="0" z="0" />
                <pointmin x="-0.2" y="-0.2" z="-0.1" />
                <pointmax x="{fmt(pointmax[0])}" y="{fmt(pointmax[1])}" z="{fmt(pointmax[2])}" />
            </definition>
            <commands>
                <mainlist>
                    <!-- Direct solid drawbox: first centre = continuous low + dp/2. -->
                    <setshapemode>dp | real | bound</setshapemode>
                    <setdrawmode mode="full" />
                    <setmkfluid mk="0" />
                    <drawbox cmt="Frozen continuous fluid cell-centre population">
                        <boxfill>solid</boxfill>
                        <point x="{fmt(fluid_point[0])}" y="{fmt(fluid_point[1])}" z="{fmt(fluid_point[2])}" />
                        <size x="{fmt(fluid_draw[0])}" y="{fmt(fluid_draw[1])}" z="{fmt(fluid_draw[2])}" />
                    </drawbox>
                    {paddle_block}
                    <setdrawmode mode="face" />
                    <setmkbound mk="20" />
                    <drawbox cmt="Finite tank walls; physical endpoints frozen">
                        <boxfill>bottom | left | right | front | back</boxfill>
                        <point x="{fmt(TANK["low"][0])}" y="{fmt(TANK["low"][1])}" z="{fmt(TANK["low"][2])}" />
                        <size x="{fmt(TANK["size"][0])}" y="{fmt(TANK["size"][1])}" z="{fmt(TANK["size"][2])}" />
                    </drawbox>
                    <setdrawmode mode="full" />
                    <setmkbound mk="50" />
                    <drawbox cmt="Native floatingtype=2 body; initial bottom at fluid upper face">
                        <boxfill>solid</boxfill>
                        <point x="{fmt(body_point[0])}" y="{fmt(body_point[1])}" z="{fmt(body_point[2])}" />
                        <size x="{fmt(body_size[0])}" y="{fmt(body_size[1])}" z="{fmt(body_size[2])}" />
                    </drawbox>
                    <shapeout file="" reset="true" />
                </mainlist>
            </commands>
        </geometry>
        <floatings>
            <floating mkbound="50">
                <massbody value="{fmt(BODY["mass_kg"])}" />
                <translationDOF x="1" y="1" z="1" />
                <rotationDOF x="1" y="1" z="1" />
            </floating>
        </floatings>
        {motion_block}
    </casedef>
    <execution>{special_block}
        <parameters>
            <parameter key="SavePosDouble" value="1" />
            <parameter key="StepAlgorithm" value="2" />
            <parameter key="VerletSteps" value="40" />
            <parameter key="Kernel" value="2" />
            <parameter key="ViscoTreatment" value="2" />
            <parameter key="Visco" value="0.000001" />
            <parameter key="ViscoBoundFactor" value="1" />
            <parameter key="DensityDT" value="2" />
            <parameter key="DensityDTvalue" value="0.1" />
            <parameter key="Shifting" value="0" />
            <parameter key="RigidAlgorithm" value="1" comment="native SPH rigid body; Chrono/contact disabled" />
            <parameter key="FtPause" value="0" />
            <parameter key="CoefDtMin" value="0.05" />
            <parameter key="DtIni" value="0" />
            <parameter key="DtMin" value="0" />
            <parameter key="DtFixed" value="0" />
            <parameter key="DtAllParticles" value="0" />
            <parameter key="TimeMax" value="12" />
            <parameter key="TimeOut" value="0.05" />
            <parameter key="PartsOutMax" value="1" />
            <parameter key="RhopOutMin" value="700" />
            <parameter key="RhopOutMax" value="1300" />
            <simulationdomain>
                <posmin x="default" y="default" z="default" />
                <posmax x="default" y="default" z="default + 20%" />
            </simulationdomain>
        </parameters>
    </execution>
</case>
'''


def _validate_definition(path: Path) -> None:
    root = ET.parse(path).getroot()
    if root.tag != "case":
        raise ValueError(f"unexpected Definition root: {path}")
    if root.find("./casedef/geometry/definition") is None:
        raise ValueError(f"missing geometry definition: {path}")
    if "bottom | left | right | front | back" not in " ".join(root.itertext()):
        raise ValueError(f"finite wall faces not explicitly present: {path}")
    if root.find("./casedef/floatings/floating") is None:
        raise ValueError(f"floating body missing: {path}")


def _request_input_files(*paths: Path) -> list[str]:
    return [str(path.resolve()) for path in paths]


def _gencase_request(case: Mapping[str, Any]) -> dict[str, Any]:
    definition = Path(case["definition"]["path"])
    case_dir = definition.parent
    cid = str(case["case_id"])
    attempt = f"{cid}_GENCASE_001"
    output_prefix = f"{{attempt_root}}/{cid}"
    inputs = _request_input_files(SCRIPT, RUNTIME_V2, definition, Path(case["control"]["path"]), Path(case["native"]["path"]), Path(case["normal"]["path"]), Path(case["official_template"]["path"]), GENCASE)
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6", "case_id": cid, "attempt_id": attempt,
        "kind": "cpu", "cpu_task_kind": "gencase",
        "command": [str(GENCASE.resolve()), str(definition.with_suffix("")), output_prefix, "-save:all"],
        "cwd": str(case_dir.resolve()), "max_wall_seconds": 300, "cpu_threads": 4,
        "estimated_storage_bytes": 268435456, "input_files": inputs, "worktree_root": str(REPO_ROOT.resolve()),
        "generator_version": VERSION, "mechanism_id": case["mechanism_id"], "resolution_id": case["resolution_id"],
        "solver_dimension_required": 3,
        "purpose": "strict continuous-mass fresh F6 mother GenCase only; no solver/GPU",
        "expected": {
            "solver_dimension": 3, "fluid_type": 3, "floating_type": 2,
            "expected_fluid_particles": case["expected_fluid_particles"],
            "minimum_transverse_layers": case["expected_transverse_layers"],
            "minimum_moving_paddle_particles": 1 if case["mechanism_id"] == "wave_no_contact" else 0,
            "finite_walls": ["bottom", "left", "right", "front", "back"],
            "strict_continuous_fluid_mass_kg": case["strict_continuous_fluid_mass_kg"],
            "initial_submerged_body_volume_m3": 0.0,
            "no_mass_rescaling": True,
        },
    }
    return request


def prepare() -> dict[str, Any]:
    FAMILY_ROOT.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for mechanism, mechanism_spec in MECHANISMS.items():
        for resolution, dp in DP_LADDER:
            cid = case_id(mechanism, resolution)
            case_dir = FAMILY_ROOT / "cases" / mechanism / resolution
            definition = case_dir / f"{cid}_Def.xml"
            control = case_dir / f"{cid}_Control.csv"
            native = case_dir / f"{cid}_Native.json"
            normal = case_dir / f"{cid}_Normal.json"
            definition.parent.mkdir(parents=True, exist_ok=True)
            definition.write_text(_definition_xml(mechanism, resolution, dp), encoding="utf-8")
            _validate_definition(definition)
            control_record = _control_csv(control, mechanism)
            native_record = _native_json(native, mechanism, resolution, dp)
            normal_record = _normal_json(normal, mechanism, resolution)
            volume = continuous_fluid_volume() - initial_submerged_body_volume()
            row = {
                "case_id": cid, "family_id": "F6", "mechanism_id": mechanism, "resolution_id": resolution,
                "physical_case_id": mechanism_spec["physical_case_id"],
                "lineage_group_id": f"F6_HANDOFF_20261002_{mechanism.upper()}",
                "geometry_family_id": mechanism_spec["geometry_family_id"], "control_family_id": mechanism_spec["control_family_id"],
                "recipe_id": f"F6_handoff_20261002_{mechanism}_native_rigid_cellcentre_v1",
                "dp_m": dp, "definition": {"path": str(definition.resolve()), "sha256": sha256(definition)},
                "control": control_record, "native": native_record, "normal": normal_record,
                "official_template": {"path": str(mechanism_spec["template"].resolve()), "sha256": sha256(mechanism_spec["template"])},
                "tank": TANK, "fluid": FLUID, "body": BODY, "paddle": PADDLE if mechanism == "wave_no_contact" else None,
                "continuous_fluid_volume_m3": volume, "strict_continuous_fluid_mass_kg": volume * RHO_WATER,
                "initial_submerged_body_volume_m3": initial_submerged_body_volume(),
                "expected_fluid_particles": expected_fluid_particles(dp),
                "expected_fluid_mass_kg": expected_fluid_particles(dp) * dp**3 * RHO_WATER,
                "expected_transverse_layers": round(FLUID["size"][1] / dp),
                "event_sequence": mechanism_spec["events"],
                "status": "gencase_pending",
            }
            row["request"] = _gencase_request(row)
            request_path = FAMILY_ROOT / "execution_requests" / f"{cid}_gencase.json"
            write_json(request_path, row["request"])
            row["request_binding"] = {"path": str(request_path.resolve()), "sha256": sha256(request_path), "attempt_id": row["request"]["attempt_id"]}
            cases.append(row)
    manifest = {
        "schema": SCHEMA + ".manifest", "family_id": "F6", "generator_version": VERSION,
        "created_at": now(), "status": "fresh_mother_cpu_gencase_pending", "cases": cases,
        "physical_geometry_contract": {
            "same_continuous_geometry_across_dp": True,
            "tank_low_m": TANK["low"], "tank_size_m": TANK["size"],
            "fluid_low_m": FLUID["low"], "fluid_size_m": FLUID["size"],
            "fluid_volume_m3": continuous_fluid_volume(), "initial_submerged_body_volume_m3": initial_submerged_body_volume(),
            "strict_fluid_mass_kg": continuous_fluid_volume() * RHO_WATER,
            "cell_centre_rule": "direct drawbox point=continuous_low+dp/2, size=continuous_size-dp; no fillbox|void",
            "physical_wall_endpoints_fixed": True, "pointmax_is_computational_only": True,
        },
        "rigid_body_contract": {
            "floatingtype": 2, "aggregate_massbody_kg": BODY["mass_kg"], "body_volume_m3": body_volume(),
            "density_ratio_to_water": BODY["mass_kg"] / (body_volume() * RHO_WATER), "analytic_inertia_kg_m2": body_inertia(),
            "initial_submerged_body_volume_m3": initial_submerged_body_volume(),
            "particle_mass_sum_must_not_be_called_aggregate_mass": True,
        },
        "history_boundary": {
            "old_fallback_02_reused": False,
            "reason": "old fillbox|void fallback retained as negative evidence; stage8 40.32..63.36 kg bodies are not this 128 kg mother",
            "old_root_cause_repairs_preserved": True,
            "new_mother_is_new_physical_scope": True,
        },
        "cpu_only_until_root_review": True, "solver_launch_forbidden_for_f6_owner": True,
    }
    write_json(FAMILY_ROOT / "manifest.json", manifest)
    write_json(FAMILY_ROOT / "physical_mother_geometry.json", {
        "schema": SCHEMA + ".geometry", "family_id": "F6", "generator_version": VERSION,
        "tank": TANK, "fluid": FLUID, "body": BODY, "paddle": PADDLE,
        "continuous_fluid_volume_m3": continuous_fluid_volume(), "initial_submerged_body_volume_m3": initial_submerged_body_volume(),
        "strict_continuous_fluid_mass_kg": continuous_fluid_volume() * RHO_WATER,
        "body_inertia_kg_m2": body_inertia(), "same_geometry_all_dp": True,
        "source_hashes": {str(path.resolve()): sha256(path) for path in (SCRIPT, OFFICIAL_SIMPLE, OFFICIAL_WAVE, GENCASE, RUNTIME_V2) if path.is_file()},
    })
    return manifest


def _attempt_root(case_id_value: str, attempt_id: str) -> Path:
    return RAW_FAMILY_ROOT / case_id_value / attempt_id


def _receipt(case_id_value: str, attempt_id: str) -> Path:
    return _attempt_root(case_id_value, attempt_id) / "execution-receipt.json"


def make_partvtk_requests() -> dict[str, Any]:
    manifest = read_json(FAMILY_ROOT / "manifest.json")
    rows = []
    for case in manifest["cases"]:
        cid = str(case["case_id"])
        gencase_attempt = str(case["request"]["attempt_id"])
        gencase_receipt = _receipt(cid, gencase_attempt)
        if not gencase_receipt.is_file():
            raise FileNotFoundError(f"GenCase receipt pending: {gencase_receipt}")
        receipt = read_json(gencase_receipt)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise RuntimeError(f"GenCase did not complete: {gencase_receipt}")
        prefix = _attempt_root(cid, gencase_attempt) / cid
        bi4 = prefix.with_suffix(".bi4")
        xml = prefix.with_suffix(".xml")
        if not bi4.is_file() or not xml.is_file():
            raise FileNotFoundError(f"actual GenCase native pair missing for {cid}")
        attempt = f"{cid}_PARTVTK_001"
        output_root = f"{{attempt_root}}"
        csv_out = f"{output_root}/{cid}_initial_all.csv"
        stats_out = f"{output_root}/{cid}_initial_stats.csv"
        inputs = _request_input_files(SCRIPT, RUNTIME_V2, PARTVTK, gencase_receipt, bi4, xml, prefix.with_name(prefix.name + "_All.vtk"), prefix.with_name(prefix.name + "__Actual.vtk"), prefix.with_name(prefix.name + "_Fluid.vtk"), Path(case["definition"]["path"]), Path(case["control"]["path"]), Path(case["native"]["path"]), Path(case["normal"]["path"]))
        request = {
            "schema": "ds-data-02.runner.request.v1", "family_id": "F6", "case_id": cid, "attempt_id": attempt,
            "kind": "cpu", "cpu_task_kind": "audit",
            "command": [str(PARTVTK.resolve()), "-filedata", str(bi4.resolve()), "-filexml", str(xml.resolve()), "-savecsv", csv_out, "-savestatscsv", stats_out, "-csvsep:1", "-onlytype:+all", "-vars:+all", "-threads:4"],
            "cwd": str(prefix.parent.resolve()), "max_wall_seconds": 600, "cpu_threads": 4,
            "estimated_storage_bytes": 268435456, "input_files": inputs, "worktree_root": str(REPO_ROOT.resolve()),
            "generator_version": VERSION, "mechanism_id": case["mechanism_id"], "resolution_id": case["resolution_id"],
            "purpose": "official PartVTK initial typed-state audit; no solver/GPU",
            "gencase_receipt": str(gencase_receipt.resolve()), "gencase_receipt_sha256": sha256(gencase_receipt),
            "expected": {"fluid_type": 3, "floating_type": 2, "moving_type": 1 if case["mechanism_id"] == "wave_no_contact" else 0, "strict_continuous_fluid_mass_kg": case["strict_continuous_fluid_mass_kg"]},
        }
        request_path = FAMILY_ROOT / "execution_requests" / f"{cid}_partvtk.json"
        write_json(request_path, request)
        rows.append({"case_id": cid, "request": {"path": str(request_path.resolve()), "sha256": sha256(request_path), "attempt_id": attempt}, "gencase_receipt": str(gencase_receipt.resolve()), "output_csv": str((_attempt_root(cid, attempt) / f"{cid}_initial_all.csv").resolve())})
    result = {"schema": SCHEMA + ".partvtk_requests", "created_at": now(), "status": "ready_for_shared_runtime_partvtk", "requests": rows}
    write_json(FAMILY_ROOT / "partvtk_request_manifest.json", result)
    return result


def _find_csv_header(path: Path) -> tuple[list[str], list[list[str]]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    header_index = next((i for i, row in enumerate(rows) if row and any("type" in cell.lower() or "idp" in cell.lower() for cell in row)), None)
    if header_index is None:
        raise ValueError(f"PartVTK CSV header not found: {path}")
    return [cell.strip().lower() for cell in rows[header_index]], rows[header_index + 1:]


def _column(header: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        if name in header:
            return header.index(name)
    for i, cell in enumerate(header):
        if any(name in cell for name in names):
            return i
    return None


def _partvtk_counts(csv_path: Path) -> dict[str, Any]:
    header, rows = _find_csv_header(csv_path)
    type_col = _column(header, ("type",))
    mass_col = _column(header, ("mass", "massfluid"))
    x_col, y_col, z_col = (_column(header, (axis,)) for axis in ("x", "y", "z"))
    if type_col is None or mass_col is None:
        raise ValueError(f"PartVTK CSV lacks type/mass columns: {header}")
    counts = {"fixed": 0, "moving": 0, "floating": 0, "fluid": 0, "unknown": 0}
    masses = {key: 0.0 for key in counts}
    points: list[tuple[float, float, float]] = []
    for row in rows:
        if not row or len(row) <= max(type_col, mass_col):
            continue
        try:
            type_value = row[type_col].strip().lower()
            mass = float(row[mass_col])
        except (ValueError, TypeError):
            continue
        key = {"0": "fixed", "1": "moving", "2": "floating", "3": "fluid", "fixed": "fixed", "moving": "moving", "floating": "floating", "fluid": "fluid"}.get(type_value, "unknown")
        counts[key] += 1
        masses[key] += mass
        if x_col is not None and y_col is not None and z_col is not None and len(row) > max(x_col, y_col, z_col):
            try:
                points.append((float(row[x_col]), float(row[y_col]), float(row[z_col])))
            except ValueError:
                pass
    return {"header": header, "rows_read": len(rows), "counts": counts, "mass_by_type_kg": masses, "finite_positions": bool(points) and all(math.isfinite(value) for point in points for value in point), "point_bounds_m": [[min(point[axis] for point in points), max(point[axis] for point in points)] for axis in range(3)] if points else None}


def audit() -> dict[str, Any]:
    manifest = read_json(FAMILY_ROOT / "manifest.json")
    partvtk_manifest = read_json(FAMILY_ROOT / "partvtk_request_manifest.json")
    by_case = {row["case_id"]: row for row in partvtk_manifest["requests"]}
    rows = []
    for case in manifest["cases"]:
        cid = str(case["case_id"])
        gencase_receipt_path = _receipt(cid, str(case["request"]["attempt_id"]))
        partvtk_receipt_path = _receipt(cid, str(by_case[cid]["request"]["attempt_id"]))
        if not gencase_receipt_path.is_file() or not partvtk_receipt_path.is_file():
            raise FileNotFoundError(f"pending receipt for {cid}")
        gencase = read_json(gencase_receipt_path)
        partvtk = read_json(partvtk_receipt_path)
        csv_path = Path(by_case[cid]["output_csv"])
        if partvtk.get("status") != "completed" or partvtk.get("returncode") != 0 or not csv_path.is_file():
            raise RuntimeError(f"PartVTK audit did not complete for {cid}")
        parsed = _partvtk_counts(csv_path)
        expected_fluid = int(case["expected_fluid_particles"])
        fluid_count = parsed["counts"]["fluid"]
        fluid_mass = parsed["mass_by_type_kg"]["fluid"]
        expected_mass = float(case["strict_continuous_fluid_mass_kg"])
        mass_error = fluid_mass / expected_mass - 1.0 if expected_mass else math.inf
        floating_count = parsed["counts"]["floating"]
        moving_count = parsed["counts"]["moving"]
        row = {
            "case_id": cid, "mechanism_id": case["mechanism_id"], "resolution_id": case["resolution_id"], "dp_m": case["dp_m"],
            "gencase": {"receipt": str(gencase_receipt_path.resolve()), "receipt_sha256": sha256(gencase_receipt_path), "status": gencase.get("status"), "returncode": gencase.get("returncode"), "solver_dimension_from_gencase": gencase.get("solver_dimension_from_gencase"), "total_particles": gencase.get("total_particles"), "fluid_particles": gencase.get("fluid_particles")},
            "partvtk": {"receipt": str(partvtk_receipt_path.resolve()), "receipt_sha256": sha256(partvtk_receipt_path), "csv": str(csv_path.resolve()), "csv_sha256": sha256(csv_path), "status": partvtk.get("status"), "returncode": partvtk.get("returncode")},
            "actual_type_counts": parsed["counts"], "actual_type_mass_kg": parsed["mass_by_type_kg"],
            "expected": {"fluid_particles": expected_fluid, "strict_continuous_fluid_volume_m3": case["continuous_fluid_volume_m3"], "strict_continuous_fluid_mass_kg": expected_mass, "body_aggregate_massbody_kg": BODY["mass_kg"], "body_analytic_inertia_kg_m2": body_inertia(), "initial_submerged_body_volume_m3": 0.0},
            "checks": {
                "actual_3d": gencase.get("solver_dimension_from_gencase") == 3,
                "positive_fluid_type3": fluid_count > 0,
                "positive_floating_type2": floating_count > 0,
                "actual_moving_particles": moving_count > 0 if case["mechanism_id"] == "wave_no_contact" else moving_count == 0,
                "finite_positions": parsed["finite_positions"],
                "fluid_count_matches_cell_centre_contract": fluid_count == expected_fluid,
                "strict_continuous_mass_error_within_one_percent": abs(mass_error) <= MASS_TOLERANCE,
                "aggregate_massbody_is_separate_from_type2_particle_mass": True,
                "finite_wall_faces_declared": True,
                "source_inputs_hash_bound": bool(gencase.get("input_hashes_after_run")) and bool(partvtk.get("input_hashes_after_run")),
            },
            "mass_error_relative_to_frozen_continuous_domain": mass_error,
            "qualification_claim": "none",
            "q_i_status": "preflight_only",
            "q_n_status": "pending_solver_three_resolution_reference",
        }
        row["preflight_pass"] = all(row["checks"].values())
        rows.append(row)
    result = {
        "schema": SCHEMA + ".audit", "family_id": "F6", "created_at": now(),
        "status": "all_three_dp_preflight_pass" if all(row["preflight_pass"] for row in rows) else "strict_preflight_failed",
        "scope": "new handoff_20261002 physical mother; old fallback-02 and stage8 are retained as negative/non-equivalent evidence",
        "continuous_geometry": {"tank": TANK, "fluid": FLUID, "fluid_volume_m3": continuous_fluid_volume(), "initial_submerged_body_volume_m3": 0.0, "strict_fluid_mass_kg": continuous_fluid_volume() * RHO_WATER},
        "rigid_body": {"aggregate_massbody_kg": BODY["mass_kg"], "volume_m3": body_volume(), "analytic_inertia_kg_m2": body_inertia(), "floatingtype": 2},
        "cases": rows, "gpu_launch": False,
        "next_gate": "root reviews actual PartVTK rows and may dispatch bounded complete-window GPU requests; this artifact grants no Q-N or production",
    }
    write_json(FAMILY_ROOT / "strict_partvtk_audit.json", result)
    return result


def _solver_request(case: Mapping[str, Any], audit_row: Mapping[str, Any]) -> dict[str, Any]:
    cid = str(case["case_id"])
    gen_attempt = str(case["request"]["attempt_id"])
    gen_root = _attempt_root(cid, gen_attempt)
    prefix = gen_root / cid
    gencase_receipt = gen_root / "execution-receipt.json"
    partvtk_attempt = f"{cid}_PARTVTK_001"
    partvtk_root = _attempt_root(cid, partvtk_attempt)
    partvtk_receipt = partvtk_root / "execution-receipt.json"
    partvtk_csv = partvtk_root / f"{cid}_initial_all.csv"
    generated = [prefix.with_suffix(ext) for ext in (".xml", ".bi4")] + [prefix.with_name(prefix.name + suffix) for suffix in ("_All.vtk", "__Actual.vtk", "_Fluid.vtk")]
    input_paths = [SCRIPT, RUNTIME_V2, Path(case["definition"]["path"]), Path(case["control"]["path"]), Path(case["native"]["path"]), Path(case["normal"]["path"]), Path(case["official_template"]["path"]), GENCASE, PARTVTK, SOLVER, FLOATING_INFO, COMPUTE_FORCES, gencase_receipt, partvtk_receipt, partvtk_csv, *generated]
    input_paths = [path for path in input_paths if path.is_file()]
    estimated_total = int(audit_row["gencase"]["total_particles"] or 0)
    estimated_fluid = int(audit_row["gencase"]["fluid_particles"] or 0)
    gpu_seconds = max(120, min(600, int(estimated_total / 1500 + 90)))
    attempt = f"{cid}_SOLVER_QUAL_001"
    command = [str(SOLVER.resolve()), str(prefix.resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"]
    return {
        "schema": "ds-data-02.runner.request.v1", "family_id": "F6", "case_id": cid, "attempt_id": attempt,
        "kind": "qualification", "command": command, "cwd": str(gen_root.resolve()), "max_wall_seconds": 600, "cpu_threads": 4,
        "estimated_peak_gpu_mib": 4096, "estimated_storage_bytes": 2147483648, "worktree_root": str(REPO_ROOT.resolve()),
        "input_files": _request_input_files(*input_paths), "generator_version": VERSION, "mechanism_id": case["mechanism_id"], "resolution_id": case["resolution_id"],
        "launch_commit_required": "root records actual dispatch commit; this request was built after CPU evidence",
        "gencase_receipt": str(gencase_receipt.resolve()), "gencase_receipt_sha256": sha256(gencase_receipt),
        "partvtk_receipt": str(partvtk_receipt.resolve()), "partvtk_receipt_sha256": sha256(partvtk_receipt),
        "gencase_actual_particles": {"total": estimated_total, "fluid": estimated_fluid, "fixed": audit_row["actual_type_counts"]["fixed"], "moving": audit_row["actual_type_counts"]["moving"], "floating": audit_row["actual_type_counts"]["floating"]},
        "cost_estimate": {"basis": "actual GenCase/PartVTK count; old 13.57M run only a conservative historical anchor and not reuse", "estimated_gpu_seconds": gpu_seconds, "estimated_total_particles": estimated_total, "estimated_fluid_particles": estimated_fluid, "estimated_native_bytes": 536870912},
        "complete_event_window_s": list(WINDOW), "output_interval_s": OUTPUT_DT, "solver_dimension_required": 3,
        "qualification_claim": "none_until_complete_window_and_native_rigid_audit", "q_n_status": "pending",
        "postprocessing_plan": {
            "floating_info": [str(FLOATING_INFO.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savedata", "{attempt_root}/solver_output/floatinginfo/FloatingMotion"],
            "compute_forces": [str(COMPUTE_FORCES.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savecsv", "{attempt_root}/solver_output/forces/FloatingForce"],
            "required_fields": ["pose", "orientation", "linear_velocity", "angular_velocity", "massbody", "inertia", "force", "torque"],
            "postprocessors_pending_shared_cpu_execution": True,
        },
        "solver_launch_authority": "root only through shared ds_data02_runtime_v2.py; F6 owner did not launch GPU",
    }


def make_solver_requests() -> dict[str, Any]:
    audit_result = read_json(FAMILY_ROOT / "strict_partvtk_audit.json")
    if audit_result.get("status") != "all_three_dp_preflight_pass":
        raise RuntimeError("strict PartVTK preflight is not fully passing; do not prepare solver requests")
    manifest = read_json(FAMILY_ROOT / "manifest.json")
    audit_by_case = {row["case_id"]: row for row in audit_result["cases"]}
    rows = []
    for case in manifest["cases"]:
        request = _solver_request(case, audit_by_case[case["case_id"]])
        path = FAMILY_ROOT / "qualification_requests" / f"{case['case_id']}.json"
        write_json(path, request)
        rows.append({"case_id": case["case_id"], "path": str(path.resolve()), "sha256": sha256(path), "attempt_id": request["attempt_id"]})
    result = {"schema": SCHEMA + ".solver_requests", "status": "root_dispatch_pending", "created_at": now(), "requests": rows, "gpu_launch": False, "q_n_status": "pending"}
    write_json(FAMILY_ROOT / "qualification_request_manifest.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "make-partvtk-requests", "audit", "make-solver-requests"])
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare()
    elif args.action == "make-partvtk-requests":
        result = make_partvtk_requests()
    elif args.action == "audit":
        result = audit()
    else:
        result = make_solver_requests()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
