#!/usr/bin/env python3
"""F7 native 3-D pump and moving-obstacle input generator.

The generator stops at bounded native GenCase evidence.  It never grants Q-I,
Q-N, or production status from XML, metadata, or a registry entry.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping


LAB = Path(__file__).resolve().parents[1]
REPO = LAB.parent
FAMILY_DIR = LAB / "campaigns/ds-data-02/families/F7"
OFFICIAL_PUMP_DIR = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump"
GENCASE = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
PUMP_XML = OFFICIAL_PUMP_DIR / "CasePump_Def.xml"
PUMP_FIXED = OFFICIAL_PUMP_DIR / "pump_fixed.vtk"
PUMP_MOVING = OFFICIAL_PUMP_DIR / "pump_moving.vtk"
TIME_MAX_S = 12.0


@dataclass(frozen=True)
class Resolution:
    name: str
    dp_m: float


@dataclass(frozen=True)
class Variant:
    index: int
    speed_scale: float
    fill_fraction: float
    offset_m: float
    gap_fraction: float
    phase_deg: float


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    mechanism: str
    resolution: str
    dp_m: float
    variant: int
    speed_scale: float
    fill_fraction: float
    offset_m: float
    gap_fraction: float
    phase_deg: float
    time_max_s: float = TIME_MAX_S
    time_out_s: float = 0.02


RESOLUTIONS = (
    Resolution("coarse", 0.025),
    Resolution("medium", 0.020),
    Resolution("fine", 0.016),
)
VARIANTS = (
    # The official pump's internal void has no coarse lattice fluid below
    # roughly 90% of its source fill height. Keep every native variant above
    # that measured lower bound so all 2x3 parents have positive fluid.
    Variant(0, 0.80, 0.90, -0.020, 0.10, 0.0),
    Variant(1, 1.00, 0.95, 0.000, 0.15, 0.0),
    Variant(2, 1.20, 1.00, 0.020, 0.20, 0.0),
    Variant(3, 1.00, 0.90, 0.040, 0.10, 90.0),
    Variant(4, 0.80, 1.00, -0.040, 0.20, 180.0),
    Variant(5, 1.20, 0.95, 0.020, 0.15, 180.0),
    Variant(6, 1.00, 1.00, -0.020, 0.20, 270.0),
    Variant(7, 0.90, 0.95, 0.000, 0.10, 270.0),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fmt(value: float) -> str:
    return format(float(value), ".12g")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def copy_if_needed(source: Path, destination: Path) -> None:
    source_hash = sha256_file(source)
    if destination.is_file() and sha256_file(destination) == source_hash:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


def case_specs() -> list[CaseSpec]:
    specs: list[CaseSpec] = []
    for mechanism in ("pump_recirculation", "moving_obstacle_exchange"):
        prefix = "PUMP" if mechanism == "pump_recirculation" else "OBSTACLE"
        for resolution in RESOLUTIONS:
            for variant in VARIANTS:
                case_id = (
                    f"F7_{prefix}_{resolution.name.upper()}_"
                    f"V{int(round(variant.speed_scale * 100)):03d}_"
                    f"F{int(round(variant.fill_fraction * 100)):03d}_O{variant.index:02d}"
                )
                specs.append(CaseSpec(
                    case_id, mechanism, resolution.name, resolution.dp_m,
                    variant.index, variant.speed_scale, variant.fill_fraction,
                    variant.offset_m, variant.gap_fraction, variant.phase_deg,
                ))
    return specs


def stage_for_case(spec: CaseSpec) -> str:
    if spec.resolution == "coarse" and spec.variant < 4:
        return "stage8"
    if (spec.resolution == "coarse" and spec.variant >= 4) or (spec.resolution == "medium" and spec.variant < 4):
        return "stage24"
    return "stage48"


def split_for_case(spec: CaseSpec) -> str:
    return ("train", "validation", "test")[spec.variant % 3]


def _set_parameter(root: ET.Element, key: str, value: float | str) -> None:
    node = root.find(f"./execution/parameters/parameter[@key='{key}']")
    if node is None:
        parameters = root.find("./execution/parameters")
        if parameters is None:
            raise ValueError(f"execution parameters missing while setting {key}")
        node = ET.SubElement(parameters, "parameter", key=key)
    node.set("value", fmt(value) if isinstance(value, (float, int)) else str(value))


def _point(node: ET.Element, x: float, y: float, z: float) -> None:
    node.set("x", fmt(x))
    node.set("y", fmt(y))
    node.set("z", fmt(z))


def _append_axis(parent: ET.Element, p1: tuple[float, float, float], p2: tuple[float, float, float]) -> None:
    one = ET.SubElement(parent, "axisp1")
    _point(one, *p1)
    two = ET.SubElement(parent, "axisp2")
    _point(two, *p2)


def _append_rotace(parent: ET.Element, ident: int, duration: float, next_id: int | None,
                   acceleration: float, axis: tuple[tuple[float, float, float], tuple[float, float, float]],
                   initial_velocity: float | None = None) -> None:
    attrs = {"id": str(ident), "duration": fmt(duration)}
    if next_id is not None:
        attrs["next"] = str(next_id)
    node = ET.SubElement(parent, "mvrotace", attrs)
    ET.SubElement(node, "ace", ang=fmt(acceleration), units_comment="degrees/s^2")
    if initial_velocity is not None:
        ET.SubElement(node, "velini", ang=fmt(initial_velocity), units_comment="degrees/s")
    _append_axis(node, *axis)


def _append_wait(parent: ET.Element, ident: int, duration: float, next_id: int | None) -> None:
    attrs = {"id": str(ident), "duration": fmt(duration)}
    if next_id is not None:
        attrs["next"] = str(next_id)
    ET.SubElement(parent, "wait", attrs)


def _pump_motion(parent: ET.Element, spec: CaseSpec) -> dict[str, Any]:
    parent.clear()
    parent.set("ref", "2")
    ET.SubElement(parent, "begin", mov="1", start="0", finish=fmt(spec.time_max_s))
    axis = ((-0.0176, -0.29, -0.7275), (-0.0176, -0.49, -0.7275))
    acceleration = 360.0 * spec.speed_scale
    velocity = 180.0 * spec.speed_scale
    _append_rotace(parent, 1, 0.5, 2, acceleration, axis, 0.0)
    _append_rotace(parent, 2, 1.0, 3, 0.0, axis)
    _append_rotace(parent, 3, 0.5, 4, -acceleration, axis)
    _append_wait(parent, 4, 0.5, 5)
    _append_rotace(parent, 5, 0.5, 6, -acceleration, axis, 0.0)
    _append_rotace(parent, 6, 1.0, 7, 0.0, axis)
    _append_rotace(parent, 7, 0.5, 8, acceleration, axis)
    _append_wait(parent, 8, 0.5, 1)
    return {
        "kind": "piecewise_acceleration_reverse",
        "axis_units": "degrees",
        "axis_p1_m": list(axis[0]), "axis_p2_m": list(axis[1]),
        "forward_acceleration_deg_s2": acceleration,
        "forward_velocity_deg_s": velocity, "cycle_period_s": 5.0,
        "time_window_s": [0.0, spec.time_max_s],
        "segments": ["accelerate", "forward", "decelerate", "stop",
                     "reverse_accelerate", "reverse", "reverse_decelerate", "stop"],
    }


def _pump_xml(spec: CaseSpec, assets: Path) -> tuple[str, dict[str, Any]]:
    root = ET.parse(assets / "CasePump_Def.xml").getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError("official Pump definition has no geometry definition")
    definition.set("dp", fmt(spec.dp_m))
    for draw in root.findall("./casedef/geometry/commands/mainlist/drawfilevtk"):
        name = Path(draw.get("file", "")).name
        if name not in {"pump_fixed.vtk", "pump_moving.vtk"}:
            raise ValueError(f"unexpected Pump draw source: {name}")
        # GenCase reads and copies drawfilevtk controls from its working
        # directory.  materialize() places immutable copies beside every
        # generated definition, so the native XML remains portable inside the
        # bounded runner and the copied controls have explicit hashes.
        draw.set("file", name)
    fill = root.find("./casedef/geometry/commands/mainlist/fillbox")
    if fill is None:
        raise ValueError("official Pump has no fluid fillbox")
    fill.set("x", fmt(0.14 + spec.offset_m))
    fill.set("y", "-0.1")
    fill.set("z", "-0.39")
    point, size = fill.find("./point"), fill.find("./size")
    if point is None or size is None:
        raise ValueError("official Pump fillbox is incomplete")
    # The official fillbox begins at x=-0.6, exactly on the inherited domain
    # lattice.  Moving that lower corner outside the GenCase domain makes the
    # coarse void fill disappear.  Keep the finite fluid lattice fixed and use
    # the declared offset as a control/recipe axis instead.
    point.set("x", "-0.6")
    size.set("z", fmt(0.82 * spec.fill_fraction))
    _set_parameter(root, "TimeMax", spec.time_max_s)
    _set_parameter(root, "TimeOut", spec.time_out_s)
    motion = root.find("./casedef/motion/objreal[@ref='2']")
    if motion is None:
        raise ValueError("official Pump has no moving object ref=2")
    motion_contract = _pump_motion(motion, spec)
    metadata = {
        "coordinate_frame": "official DualSPHysics Pump world coordinates",
        "fixed_mk": 0, "moving_mk": 2, "fluid_mk": 1, "moving_object_ref": 2,
        "native_source": "official DualSPHysics v5.4 main/13_Pump POLYDATA",
        "lifecycle_intent": "finite_initial_fluid; closed_candidate; verify_native_open_faces_with_solver",
        "motion": motion_contract,
    }
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True), metadata


def _obstacle_xml(spec: CaseSpec) -> tuple[str, dict[str, Any]]:
    tank_x, tank_y, tank_z = 1.2, 0.8, 0.6
    blade_length = tank_y * (1.0 - 2.0 * spec.gap_fraction)
    blade_thickness, blade_height, axis_z = 0.06, 0.48, 0.05
    fluid_height = 0.48 * spec.fill_fraction
    x0, y0 = -tank_x / 2.0, -tank_y / 2.0
    obstacle_x = spec.offset_m - blade_thickness / 2.0
    frequency = 0.5 * spec.speed_scale
    amplitude = 35.0 + 10.0 * (spec.gap_fraction - 0.1) / 0.1
    motion = f"""
      <motion>
        <objreal ref="2">
          <begin mov="1" start="0" finish="{fmt(spec.time_max_s)}" />
          <mvrotsinu id="1" duration="2" next="2" anglesunits="degrees">
            <freq v="{fmt(frequency)}" units_comment="1/s" />
            <ampl v="{fmt(amplitude)}" units_comment="degrees" />
            <phase v="{fmt(spec.phase_deg)}" units_comment="degrees" />
            <axisp1 x="{fmt(spec.offset_m)}" y="0" z="{fmt(axis_z)}" />
            <axisp2 x="{fmt(spec.offset_m)}" y="0" z="{fmt(axis_z + 1.0)}" />
          </mvrotsinu>
          <wait id="2" duration="0.25" next="3" />
          <mvrotsinu id="3" duration="2" next="4" anglesunits="degrees">
            <freq v="{fmt(frequency)}" units_comment="1/s" />
            <ampl v="{fmt(amplitude)}" units_comment="degrees" />
            <phase v="{fmt(spec.phase_deg + 180.0)}" units_comment="degrees" />
            <axisp1 x="{fmt(spec.offset_m)}" y="0" z="{fmt(axis_z)}" />
            <axisp2 x="{fmt(spec.offset_m)}" y="0" z="{fmt(axis_z + 1.0)}" />
          </mvrotsinu>
          <wait id="4" duration="0.25" next="1" />
        </objreal>
      </motion>
    """
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" units_comment="m/s^2" />
      <rhop0 value="1000" units_comment="kg/m^3" />
      <rhopgradient value="2" />
      <hswl value="0" auto="true" units_comment="m" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="30" />
      <speedsound value="0" auto="true" />
      <coefh value="0.91924" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="240" fluidcount="9" />
    <geometry>
      <definition dp="{fmt(spec.dp_m)}" units_comment="metres (m)">
        <pointref x="{fmt(spec.dp_m / 2)}" y="{fmt(spec.dp_m / 2)}" z="{fmt(spec.dp_m / 2)}" />
        <pointmin x="{fmt(x0)}" y="{fmt(y0)}" z="0" />
        <pointmax x="{fmt(-x0)}" y="{fmt(-y0)}" z="{fmt(tank_z)}" />
      </definition>
      <commands>
        <mainlist>
          <setshapemode>real | bound | dp</setshapemode>
          <setdrawmode mode="full" />
          <setmkbound mk="0" />
          <drawbox>
            <boxfill>bottom | left | right | front | back</boxfill>
            <point x="{fmt(x0)}" y="{fmt(y0)}" z="0" />
            <size x="{fmt(tank_x)}" y="{fmt(tank_y)}" z="{fmt(tank_z)}" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkbound mk="2" />
          <drawbox>
            <boxfill>all</boxfill>
            <point x="{fmt(obstacle_x)}" y="{fmt(-blade_length / 2)}" z="{fmt(axis_z)}" />
            <size x="{fmt(blade_thickness)}" y="{fmt(blade_length)}" z="{fmt(blade_height)}" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkfluid mk="1" />
          <fillbox x="{fmt(spec.offset_m)}" y="0" z="{fmt(axis_z + fluid_height / 2.0)}">
            <modefill>void</modefill>
            <point x="{fmt(x0 + 0.05)}" y="{fmt(y0 + 0.05)}" z="{fmt(axis_z)}" />
            <size x="{fmt(tank_x - 0.1)}" y="{fmt(tank_y - 0.1)}" z="{fmt(fluid_height)}" />
          </fillbox>
          <shapeout file="" />
        </mainlist>
      </commands>
    </geometry>
    {motion}
  </casedef>
  <execution>
    <parameters>
      <parameter key="SavePosDouble" value="2" />
      <parameter key="Boundary" value="2" />
      <parameter key="SlipMode" value="2" />
      <parameter key="NoPenetration" value="1" />
      <parameter key="StepAlgorithm" value="2" />
      <parameter key="Kernel" value="2" />
      <parameter key="ViscoTreatment" value="1" />
      <parameter key="Visco" value="0.05" />
      <parameter key="DensityDT" value="3" />
      <parameter key="DensityDTvalue" value="0.1" />
      <parameter key="Shifting" value="0" />
      <parameter key="RigidAlgorithm" value="1" />
      <parameter key="CoefDtMin" value="0.05" />
      <parameter key="DtIni" value="0" />
      <parameter key="DtMin" value="0" />
      <parameter key="DtFixed" value="0" />
      <parameter key="DtAllParticles" value="0" />
      <parameter key="TimeMax" value="{fmt(spec.time_max_s)}" units_comment="seconds" />
      <parameter key="TimeOut" value="{fmt(spec.time_out_s)}" units_comment="seconds" />
      <parameter key="PartsOutMax" value="1" />
      <parameter key="RhopOutMin" value="700" />
      <parameter key="RhopOutMax" value="1300" />
      <parameter key="MinFluidStop" value="0" />
      <simulationdomain>
        <posmin x="default-150%" y="default-150%" z="default-150%" />
        <posmax x="default+150%" y="default+150%" z="default+150%" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
"""
    metadata = {
        "coordinate_frame": "F7 tank world coordinates (SI metres; x,y horizontal, z vertical)",
        "fixed_mk": 0, "moving_mk": 2, "fluid_mk": 1, "moving_object_ref": 2,
        "geometry": {
            "tank_size_m": [tank_x, tank_y, tank_z],
            "blade_length_m": blade_length, "blade_thickness_m": blade_thickness,
            "blade_height_m": blade_height,
            "wall_clearance_m": (tank_y - blade_length) / 2.0,
            "gap_fraction": spec.gap_fraction,
        },
        "lifecycle_intent": "finite_initial_fluid; closed_candidate; verify_native_open_faces_with_solver",
        "motion": {
            "kind": "sinusoidal_rotation_with_explicit_neutral_wait_and_phase_reversal",
            "frequency_hz": frequency, "amplitude_deg": amplitude,
            "phase_deg": spec.phase_deg, "time_window_s": [0.0, spec.time_max_s],
            "period_s": 4.5 / spec.speed_scale,
            "axis_p1_m": [spec.offset_m, 0.0, axis_z],
            "axis_p2_m": [spec.offset_m, 0.0, axis_z + 1.0],
        },
    }
    return xml, metadata


def _pump_control_rows(spec: CaseSpec, dt: float = 0.02) -> list[dict[str, Any]]:
    acceleration = 360.0 * spec.speed_scale
    velocity = 180.0 * spec.speed_scale
    rows: list[dict[str, Any]] = []
    for index in range(int(round(spec.time_max_s / dt)) + 1):
        t = min(index * dt, spec.time_max_s)
        phase = t % 5.0
        if phase < 0.5:
            omega, angle, state = acceleration * phase, 0.5 * acceleration * phase**2, "forward_accelerate"
        elif phase < 1.5:
            omega, angle, state = velocity, 0.125 * acceleration + velocity * (phase - 0.5), "forward_constant"
        elif phase < 2.0:
            elapsed = phase - 1.5
            omega = velocity - acceleration * elapsed
            angle = 0.125 * acceleration + velocity + velocity * elapsed - 0.5 * acceleration * elapsed**2
            state = "forward_decelerate"
        elif phase < 2.5:
            omega, angle, state = 0.0, 0.75 * acceleration, "neutral_wait"
        elif phase < 3.0:
            elapsed = phase - 2.5
            omega, angle, state = -acceleration * elapsed, 0.75 * acceleration - 0.5 * acceleration * elapsed**2, "reverse_accelerate"
        elif phase < 4.0:
            omega, angle, state = -velocity, 0.625 * acceleration - velocity * (phase - 3.0), "reverse_constant"
        elif phase < 4.5:
            elapsed = phase - 4.0
            omega = -velocity + acceleration * elapsed
            angle = 0.125 * acceleration - velocity * elapsed + 0.5 * acceleration * elapsed**2
            state = "reverse_decelerate"
        else:
            omega, angle, state = 0.0, 0.0, "neutral_wait"
        rows.append({"time_s": t, "angle_deg": angle, "angular_velocity_deg_s": omega, "state": state})
    return rows


def _obstacle_control_rows(spec: CaseSpec, dt: float = 0.02) -> list[dict[str, Any]]:
    frequency = 0.5 * spec.speed_scale
    amplitude = 35.0 + 10.0 * (spec.gap_fraction - 0.1) / 0.1
    rows: list[dict[str, Any]] = []
    for index in range(int(round(spec.time_max_s / dt)) + 1):
        t = min(index * dt, spec.time_max_s)
        phase = t % 4.5
        if phase < 2.0:
            local, phase_rad, state = phase, math.radians(spec.phase_deg), "forward_sinusoid"
        elif phase < 2.25:
            rows.append({"time_s": t, "angle_deg": 0.0, "angular_velocity_deg_s": 0.0, "state": "neutral_wait"})
            continue
        elif phase < 4.25:
            local, phase_rad, state = phase - 2.25, math.radians(spec.phase_deg + 180.0), "reverse_sinusoid"
        else:
            rows.append({"time_s": t, "angle_deg": 0.0, "angular_velocity_deg_s": 0.0, "state": "neutral_wait"})
            continue
        omega_rad = 2.0 * math.pi * frequency
        angle = amplitude * math.sin(omega_rad * local + phase_rad)
        omega = math.degrees(amplitude * omega_rad * math.cos(omega_rad * local + phase_rad))
        rows.append({"time_s": t, "angle_deg": angle, "angular_velocity_deg_s": omega, "state": state})
    return rows


def _write_control(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    lines = ["# time_s,angle_deg,angular_velocity_deg_s,state; SI time and degree control for audit only\n",
             "time_s,angle_deg,angular_velocity_deg_s,state\n"]
    for row in rows:
        lines.append(f"{fmt(float(row['time_s']))},{fmt(float(row['angle_deg']))},"
                     f"{fmt(float(row['angular_velocity_deg_s']))},{row['state']}\n")
    write_text(path, "".join(lines))


def _relative(path: Path, family_dir: Path) -> str:
    return str(path.relative_to(family_dir))


def _asset_manifest(assets: Path) -> dict[str, Any]:
    sources = {"CasePump_Def.xml": PUMP_XML, "pump_fixed.vtk": PUMP_FIXED,
               "pump_moving.vtk": PUMP_MOVING}
    result: dict[str, Any] = {}
    for name, source in sources.items():
        destination = assets / name
        copy_if_needed(source, destination)
        result[name] = {
            "source_path": str(source), "source_sha256": sha256_file(source),
            "copied_path": str(destination), "copied_sha256": sha256_file(destination),
            "copy_verified": sha256_file(source) == sha256_file(destination),
        }
    return result


def _case_manifest(spec: CaseSpec, definition: Path, control: Path,
                   metadata: Mapping[str, Any], assets: Mapping[str, Any],
                   family_dir: Path) -> dict[str, Any]:
    return {
        "schema": "ds02.f7.case-manifest.v1", "case_id": spec.case_id,
        "family_id": "F7", "mechanism": spec.mechanism,
        "registry_stage": stage_for_case(spec), "split": split_for_case(spec),
        "status": "generator_ready; gencase_pending", "physical_parameters": asdict(spec),
        "recipe": {
            "definition_xml": _relative(definition, family_dir),
            "control_csv": _relative(control, family_dir),
            "coordinate_frame": metadata["coordinate_frame"],
            "units": {"length": "m", "time": "s", "density": "kg/m^3", "mass": "kg", "angle": "degree"},
            "native_mk": {"fixed": metadata["fixed_mk"], "moving": metadata["moving_mk"], "fluid": metadata["fluid_mk"]},
            "geometry": metadata.get("geometry"),
            "motion": metadata["motion"],
            "lifecycle_intent": metadata["lifecycle_intent"],
        },
        "source_assets": assets,
        "qualification": {
            "q_i": "pending actual shared-runner GenCase and native solver evidence",
            "q_n": "pending; no claim from generated inputs or metadata",
            "production": "closed",
            "required_checks": [
                "actual positive fluid count and Data2D=0",
                "actual 3-D layers, finite initial mass, gap and motion coverage",
                "source-zone, first-passage, residence and repeated-cycle native labels",
                "closed mass ledger or open boundary flux/lifecycle ledger",
                "startup, several cycles, stop/reverse/backflow observables",
            ],
        },
        "lineage": {
            "parent": "official_pump_13_Pump" if spec.mechanism == "pump_recirculation" else "f7_native_3d_paddle_template",
            "historical_pump_issue": "old D05 reported 12 missing identities and 0.324 kg; no closedness inference is made",
        },
    }


def materialize(family_dir: Path = FAMILY_DIR) -> dict[str, Any]:
    family_dir = Path(family_dir).resolve()
    assets_dir = family_dir / "assets/official_pump"
    definitions = family_dir / "definitions"
    controls = family_dir / "controls"
    manifests = family_dir / "case_manifests"
    for path in (assets_dir, definitions, controls, manifests,
                 family_dir / "requests", family_dir / "labels", family_dir / "preview"):
        path.mkdir(parents=True, exist_ok=True)
    assets = _asset_manifest(assets_dir)
    # GenCase resolves drawfilevtk names against the request cwd rather than
    # the XML's directory. Keep one verified copy beside the definitions.
    for name in ("pump_fixed.vtk", "pump_moving.vtk"):
        copy_if_needed(assets_dir / name, family_dir / "definitions" / name)
    specs = case_specs()
    registry: list[dict[str, Any]] = []
    for spec in specs:
        definition = definitions / f"{spec.case_id}_Def.xml"
        control = controls / f"{spec.case_id}_motion.csv"
        if spec.mechanism == "pump_recirculation":
            xml, metadata = _pump_xml(spec, assets_dir)
            rows = _pump_control_rows(spec)
        else:
            xml, metadata = _obstacle_xml(spec)
            rows = _obstacle_control_rows(spec)
        write_text(definition, xml)
        _write_control(control, rows)
        write_json(manifests / f"{spec.case_id}.json",
                   _case_manifest(spec, definition, control, metadata, assets, family_dir))
        registry.append({
            **asdict(spec), "stage": stage_for_case(spec), "split": split_for_case(spec),
            "definition_xml": _relative(definition, family_dir), "control_csv": _relative(control, family_dir),
            "definition_sha256": sha256_file(definition), "control_sha256": sha256_file(control),
            "native_3d_intent": True, "q_i": "pending", "q_n": "pending",
        })
    write_text(family_dir / "case_registry.jsonl",
               "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in registry))
    write_json(family_dir / "reference_evidence.json", {
        "schema": "ds02.f7.reference-evidence.v1", "created_at_utc": utc_now(),
        "evidence_boundary": "source and historical diagnosis only; no numerical qualification claim",
        "official_pump_source": assets,
        "historical_d05_issue": {
            "source_h5": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-01/d05/normalized/B05_F7_pump3d_dp030.h5",
            "solver_log": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-01/d05/B05_F7_pump3d_dp030/solver.stdout.log",
            "observed_missing_initial_identities": 12, "observed_missing_mass_kg": 0.324,
            "hash_policy": "historical asset was not rehashed by this generator",
            "interpretation": "diagnostic only; cannot establish closed/open lifecycle or solver qualification",
        },
        "new_recipe_contract": {
            "two_true_3d_mechanisms": ["official Pump POLYDATA", "finite 3-D tank and moving paddle"],
            "resolution_matrix": [asdict(item) for item in RESOLUTIONS], "case_count": len(specs),
            "lifecycle": "finite initial fluid; native solver must select closed mass ledger or explicit open flux ledger",
            "time_window_s": [0.0, TIME_MAX_S],
        },
    })
    write_json(family_dir / "split_plan.json", {
        "schema": "ds02.f7.split-plan.v1", "case_count": len(specs),
        "stages": {
            "stage8": {"case_count": 8, "selection": "coarse resolution, variants 0..3, four per mechanism"},
            "stage24": {"case_count": 16, "selection": "incremental coarse variants 4..7 plus medium variants 0..3; cumulative stage8+stage24=24"},
            "stage48": {"case_count": 24, "selection": "incremental medium variants 4..7 plus all fine variants; cumulative stage8+stage24+stage48=48"},
        },
        "split_counts": {key: sum(row["split"] == key for row in registry) for key in ("train", "validation", "test")},
        "split_rule": "variant modulo 3 within each mechanism/resolution block",
        "geometry_holdout": "moving-obstacle mechanism and phase/gap variants are held out from pump source geometry",
        "qualification_boundary": "registry membership is not Q-I or Q-N evidence",
    })
    write_json(family_dir / "qualified_recipes.json", {
        "schema": "ds02.f7.qualified-recipes.v1", "status": "none_qualified",
        "q_i": "pending actual GenCase, native solver trajectory, lifecycle ledger and labels",
        "q_n": "pending actual recipe/time/observables evidence",
        "recipes": [{"case_id": row["case_id"], "mechanism": row["mechanism"], "resolution": row["resolution"],
                     "status": "generator_ready_gencase_pending", "definition_sha256": row["definition_sha256"],
                     "control_sha256": row["control_sha256"]} for row in registry],
    })
    write_json(family_dir / "labels/event_schema.json", {
        "schema": "ds02.f7.native-event-labels.v1", "status": "schema_only_until_native_trajectory",
        "identity": ["particle_zone", "particle_id"],
        "events": ["source_zone_assignment_at_initial_frame", "first_crossing_of_impeller_or_obstacle_subdomain",
                    "residence_between_finite_internal_faces", "repeated_closed_cycle_crossing_without_new_mass",
                    "backflow_or_open_flux_if_native_boundary_is_open"],
        "required_fields": ["time_s", "typed_identity", "source_zone", "event_type", "finite_region_id", "ledger_status"],
        "mass_rule": "count typed identities once in a closed ledger; use signed flux for an open boundary",
    })
    write_text(family_dir / "preview/README.md",
               "# F7 preview boundary\n\nNo preview is emitted by this CPU generator. Native previews must cite a solver receipt, full time window and event labels. A geometry sketch or canary is not Q-N evidence.\n")
    write_json(family_dir / "family_card.json", {
        "schema": "ds02.f7.family-card.v1", "family_id": "F7",
        "title": "3-D pump recirculation and moving-obstacle exchange",
        "generator": str(Path(__file__).resolve()), "generator_sha256": sha256_file(Path(__file__).resolve()),
        "created_at_utc": utc_now(), "case_count": len(specs),
        "mechanisms": {"pump_recirculation": "official 13_Pump fixed/moving POLYDATA with native reverse/stop motion",
                       "moving_obstacle_exchange": "finite 3-D tank with a 3-D rotating paddle and phase-reversed motion"},
        "resolution_matrix": [asdict(item) for item in RESOLUTIONS], "time_window_s": [0.0, TIME_MAX_S],
        "status": "inputs_materialized; actual GenCase/solver/Q-I/Q-N pending",
        "next_executable": "emit bounded CPU GenCase requests through shared ds_data02_runtime.py, inspect actual counts/layers/gap/mass/control, then root may submit solver requests",
    })
    write_text(family_dir / "FAMILY_HANDOFF.md", f"""# F7 handoff

Materialized {len(specs)} independent XML/control pairs: two true 3-D mechanisms, three resolutions and eight variants per mechanism/resolution. Official Pump files are copied under assets/official_pump/ and hashes are recorded in reference_evidence.json.

Historical Pump evidence is diagnostic only: old D05 reported 12 missing identities and 0.324 kg. This generator requires a native closed mass ledger or explicit open boundary flux/lifecycle ledger; it does not infer either from metadata.

Status: generator ready; CPU GenCase and native solver evidence pending. No Q-I, Q-N or production claim is made. Requests are emitted under requests/ only by the CLI.

Generated at {utc_now()}.
""")
    return {"family_dir": str(family_dir), "case_count": len(specs),
            "mechanism_counts": {key: sum(spec.mechanism == key for spec in specs)
                                 for key in ("pump_recirculation", "moving_obstacle_exchange")},
            "resolution_counts": {key: sum(spec.resolution == key for spec in specs)
                                  for key in ("coarse", "medium", "fine")}, "asset_manifest": assets}


def _request_cases(mode: str) -> list[CaseSpec]:
    specs = case_specs()
    if mode == "all":
        return specs
    if mode == "stage8":
        return [spec for spec in specs if stage_for_case(spec) == "stage8"]
    if mode == "matrix":
        return [spec for spec in specs if spec.variant == 0]
    raise ValueError(f"unknown request mode: {mode}")


def emit_requests(family_dir: Path = FAMILY_DIR, mode: str = "matrix", attempt_number: int = 1) -> list[Path]:
    family_dir = Path(family_dir).resolve()
    materialize(family_dir)
    request_dir = family_dir / "requests"
    definitions, controls = family_dir / "definitions", family_dir / "controls"
    assets = family_dir / "assets/official_pump"
    emitted: list[Path] = []
    for spec in _request_cases(mode):
        definition = definitions / f"{spec.case_id}_Def.xml"
        control = controls / f"{spec.case_id}_motion.csv"
        inputs = [GENCASE, definition, control, Path(__file__).resolve()]
        if spec.mechanism == "pump_recirculation":
            inputs += [assets / "CasePump_Def.xml", definitions / "pump_fixed.vtk", definitions / "pump_moving.vtk"]
        request = {
            "schema": "ds02.cpu-request.v1", "family_id": "F7", "case_id": spec.case_id,
            "attempt_id": f"{spec.case_id}_GENCASE_{attempt_number:02d}", "kind": "cpu", "cpu_task_kind": "gencase",
            "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/" + spec.case_id, "-save:all"],
            "cwd": str(definitions), "max_wall_seconds": 300, "cpu_threads": 4,
            "estimated_storage_bytes": 240 * 1024 * 1024, "input_files": [str(path) for path in inputs],
            "worktree_root": str(REPO),
            "purpose": "bounded native GenCase preflight only; no solver/GPU/model",
            "expected_checks": {"mechanism": spec.mechanism, "resolution": spec.resolution,
                                "expected_dimension": 3, "positive_fluid_required": True,
                                "motion_window_s": [0.0, spec.time_max_s], "gap_axis": spec.gap_fraction,
                                "initial_mass": "parse native MassFluid and actual fluid count; no rescaling"},
            "provenance_note": "Later solver requests must cite this request, actual external GenCase prefix/BI4/XML/control hashes.",
        }
        path = request_dir / f"{spec.case_id}-gencase.json"
        write_json(path, request)
        emitted.append(path)
    write_json(family_dir / "request_manifest.json", {
        "schema": "ds02.f7.request-manifest.v1", "mode": mode, "request_count": len(emitted),
        "requests": [str(path.relative_to(family_dir)) for path in emitted],
        "resource_boundary": {"max_wall_seconds": 300, "cpu_threads": 4, "estimated_storage_bytes": 240 * 1024 * 1024},
        "status": "ready_for_shared_runner; not executed by this command",
    })
    return emitted


def _parse_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return None if match is None else int(match.group(1).replace(",", ""))


def _parse_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return None if match is None else float(match.group(1))


def parse_gencase_stdout(path: Path) -> dict[str, Any]:
    text = Path(path).read_text(errors="replace")
    total = _parse_int(r"Total particles:\s*([\d,]+)", text)
    fluid = _parse_int(r"Fluid\.*:\s*([\d,]+)", text)
    mass_fluid = _parse_float(r"MassFluid=\[([0-9eE+_.-]+)\]", text)
    data2d = re.search(r"Data2D=\[([01])\]", text)
    domain = re.search(r"Domain points:\s*(\d+)\s*x\s*(\d+)\s*x\s*(\d+)", text)
    return {
        "total_particles": total, "fluid_particles": fluid,
        "mass_fluid_kg_per_particle": mass_fluid,
        "solver_dimension_from_gencase": (2 if data2d and data2d.group(1) == "1" else 3 if data2d else None),
        "domain_points": None if domain is None else [int(value) for value in domain.groups()],
        "domain_z_layers": None if domain is None else int(domain.group(3)),
    }


def audit_receipts(receipt_paths: Iterable[Path], family_dir: Path = FAMILY_DIR) -> dict[str, Any]:
    family_dir = Path(family_dir).resolve()
    specs = {spec.case_id: spec for spec in case_specs()}
    rows: list[dict[str, Any]] = []
    for receipt_path in receipt_paths:
        receipt_path = Path(receipt_path).resolve()
        receipt = json.loads(receipt_path.read_text())
        request = receipt.get("request", {})
        case_id = request.get("case_id")
        if case_id not in specs:
            raise ValueError(f"receipt case_id is not an F7 generated case: {case_id}")
        spec = specs[case_id]
        output = Path(receipt.get("output_root", ""))
        parsed = parse_gencase_stdout(output / "stdout.log") if (output / "stdout.log").is_file() else {}
        definition = family_dir / "definitions" / f"{case_id}_Def.xml"
        control = family_dir / "controls" / f"{case_id}_motion.csv"
        control_rows = max(0, sum(1 for _ in control.open(encoding="utf-8", errors="replace")) - 2) if control.is_file() else 0
        checks = {
            "positive_fluid": bool(parsed.get("fluid_particles", 0) > 0),
            "actual_3d": parsed.get("solver_dimension_from_gencase") == 3,
            "multiple_z_layers": bool(parsed.get("domain_z_layers", 0) > 1),
            "motion_control_rows_cover_window": control_rows >= int(spec.time_max_s / 0.02),
        }
        row = {
            "receipt": str(receipt_path), "receipt_sha256": sha256_file(receipt_path),
            "output_root": str(output), "status": receipt.get("status"), "returncode": receipt.get("returncode"),
            "elapsed_seconds": receipt.get("elapsed_seconds"), "bytes": receipt.get("bytes"), **parsed,
            "definition_sha256": sha256_file(definition) if definition.is_file() else None,
            "control_sha256": sha256_file(control) if control.is_file() else None,
            "control_rows": control_rows, "motion_window_requested_s": [0.0, spec.time_max_s],
            "gap_fraction_requested": spec.gap_fraction, "initial_mass_kg": (
                None if parsed.get("fluid_particles") is None or parsed.get("mass_fluid_kg_per_particle") is None
                else parsed["fluid_particles"] * parsed["mass_fluid_kg_per_particle"]),
            "native_checks": checks, "preflight_structural_pass": all(checks.values()) and receipt.get("status") == "completed",
            "qualification_boundary": "GenCase/preflight evidence only; Q-I/Q-N/production remain pending native solver trajectory, lifecycle and observables",
        }
        rows.append(row)
    result = {"schema": "ds02.f7.gencase-evidence.v1", "created_at_utc": utc_now(),
              "evidence_boundary": "actual bounded CPU GenCase only; no Q-I/Q-N claim", "receipts": rows}
    write_json(family_dir / "gencase_evidence.json", result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    materialize_cmd = sub.add_parser("materialize")
    materialize_cmd.add_argument("--family-dir", type=Path, default=FAMILY_DIR)
    materialize_cmd.add_argument("--emit-requests", choices=("none", "matrix", "stage8", "all"), default="none")
    requests_cmd = sub.add_parser("requests")
    requests_cmd.add_argument("--family-dir", type=Path, default=FAMILY_DIR)
    requests_cmd.add_argument("--mode", choices=("matrix", "stage8", "all"), default="matrix")
    requests_cmd.add_argument("--attempt-number", type=int, default=1)
    audit_cmd = sub.add_parser("audit")
    audit_cmd.add_argument("receipts", nargs="+", type=Path)
    audit_cmd.add_argument("--family-dir", type=Path, default=FAMILY_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "materialize":
        result = materialize(args.family_dir)
        if args.emit_requests != "none":
            result["requests"] = [str(path) for path in emit_requests(args.family_dir, args.emit_requests)]
    elif args.command == "requests":
        result = {"requests": [str(path) for path in emit_requests(args.family_dir, args.mode, args.attempt_number)]}
    else:
        result = audit_receipts(args.receipts, args.family_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
