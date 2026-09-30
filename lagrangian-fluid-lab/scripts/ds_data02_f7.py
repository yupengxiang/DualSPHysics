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
BIN_ROOT = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
SOLVER = BIN_ROOT / "DualSPHysics5.4_linux64"
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
    physical_parent_id: str
    registry_kind: str
    split: str
    stage: str
    time_max_s: float = TIME_MAX_S
    time_out_s: float = 0.02


@dataclass(frozen=True)
class PhysicalVariant:
    """One physical condition; resolution is a derived view of this row."""

    index: int
    speed_scale: float
    fill_fraction: float
    offset_m: float
    gap_fraction: float
    phase_deg: float
    split: str
    holdout_axis: str


RESOLUTIONS = (
    Resolution("coarse", 0.025),
    Resolution("medium", 0.020),
    Resolution("fine", 0.016),
)
PRODUCTION_RESOLUTION = "fine"
NEW_SPLITS = (
    "train", "validation", "test", "train", "validation", "test",
    "train", "validation", "test", "train", "validation", "test",
    "train", "validation", "test", "train", "validation", "test",
    "train", "validation", "test", "train", "validation", "test",
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


def _legacy_view_specs() -> list[CaseSpec]:
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
                    physical_parent_id=f"LEGACY_{prefix}_V{variant.index:02d}",
                    registry_kind="legacy_view", split=("train", "validation", "test")[variant.index % 3],
                    stage=("stage8" if resolution.name == "coarse" and variant.index < 4
                           else "stage24" if (resolution.name == "coarse" or
                                               (resolution.name == "medium" and variant.index < 4))
                           else "stage48"),
                ))
    return specs


def physical_variants() -> list[PhysicalVariant]:
    """Return 24 independent conditions per mechanism.

    The old generator varied only resolution around eight conditions.  This
    table makes speed, fill, offset, gap and control phase explicit physical
    axes.  The final twelve conditions exercise the held-out geometry/control
    combinations; their split is fixed here and is independent of the legacy
    registry.
    """
    variants: list[PhysicalVariant] = []
    speeds = (0.80, 1.00, 1.20)
    fills = (0.90, 0.95, 1.00)
    offsets = (-0.040, 0.000, 0.040)
    # Clearance is measured from the paddle ends to the tank walls.  Values
    # below 0.20 leave fewer than four coarse lattice spacings after native
    # boundary layers and are retained only in the archived legacy views.
    gaps = (0.20, 0.25, 0.30)
    phases = (0.0, 90.0, 180.0, 270.0)
    for index in range(24):
        # This mixed-radix map gives 24 unique tuples.  It keeps the first
        # four per mechanism as the stage-8 seed, adds eight at stage 24, and
        # leaves the final twelve for stage 48/geometry-control holdout.
        speed = speeds[index % len(speeds)]
        fill = fills[(index // 3) % len(fills)]
        offset = offsets[(index // 9) % len(offsets)]
        gap = gaps[(index // 3) % len(gaps)]
        phase = phases[index % len(phases)]
        variants.append(PhysicalVariant(
            index=index, speed_scale=speed, fill_fraction=fill, offset_m=offset,
            gap_fraction=gap, phase_deg=phase, split=NEW_SPLITS[index],
            holdout_axis=("baseline" if index < 4 else
                          "speed_fill_control" if index < 12 else
                          "geometry_control_holdout"),
        ))
    return variants


def _stage_for_parent(index: int) -> str:
    if index < 4:
        return "stage8"
    if index < 12:
        return "stage24"
    return "stage48"


def _make_spec(case_id: str, mechanism: str, resolution: Resolution,
               variant: PhysicalVariant, *, physical_parent_id: str,
               registry_kind: str, split: str | None = None,
               stage: str | None = None) -> CaseSpec:
    return CaseSpec(
        case_id=case_id, mechanism=mechanism, resolution=resolution.name,
        dp_m=resolution.dp_m, variant=variant.index,
        speed_scale=variant.speed_scale, fill_fraction=variant.fill_fraction,
        offset_m=variant.offset_m, gap_fraction=variant.gap_fraction,
        phase_deg=variant.phase_deg, physical_parent_id=physical_parent_id,
        registry_kind=registry_kind, split=split or variant.split,
        stage=stage or _stage_for_parent(variant.index),
    )


def production_specs() -> list[CaseSpec]:
    specs: list[CaseSpec] = []
    resolution = next(item for item in RESOLUTIONS if item.name == PRODUCTION_RESOLUTION)
    for mechanism in ("pump_recirculation", "moving_obstacle_exchange"):
        prefix = "PUMP" if mechanism == "pump_recirculation" else "OBSTACLE"
        for variant in physical_variants():
            parent = f"F7_{prefix}_P{variant.index:02d}"
            specs.append(_make_spec(
                f"{parent}_{resolution.name.upper()}", mechanism, resolution, variant,
                physical_parent_id=parent, registry_kind="production",
            ))
    return specs


def reference_specs() -> list[CaseSpec]:
    """The six-resolution views for one fixed parent per mechanism."""
    base = physical_variants()[0]
    specs: list[CaseSpec] = []
    for mechanism in ("pump_recirculation", "moving_obstacle_exchange"):
        prefix = "PUMP" if mechanism == "pump_recirculation" else "OBSTACLE"
        parent = f"F7_{prefix}_REFERENCE_BASE"
        for resolution in RESOLUTIONS:
            specs.append(_make_spec(
                f"{parent}_{resolution.name.upper()}", mechanism, resolution, base,
                physical_parent_id=parent, registry_kind="reference",
                split="reference", stage="reference_matrix",
            ))
    return specs


def case_specs() -> list[CaseSpec]:
    """Canonical F7 registry: 48 production parents plus six references."""
    return production_specs() + reference_specs()


def _all_specs() -> list[CaseSpec]:
    return _legacy_view_specs() + case_specs()


def stage_for_case(spec: CaseSpec) -> str:
    return spec.stage


def split_for_case(spec: CaseSpec) -> str:
    return spec.split


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
    phase = math.radians(spec.phase_deg)
    axis_x = -0.0176 + spec.offset_m + 0.005 * math.sin(phase)
    axis_z = -0.7275 + 0.005 * math.cos(phase)
    axis = ((axis_x, -0.29, axis_z), (axis_x, -0.49, axis_z))
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
        "axis_phase_offset_deg": spec.phase_deg,
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
    fill_x0, fill_y0 = x0 + 0.05, y0 + 0.05
    fill_x, fill_y = tank_x - 0.1, tank_y - 0.1
    fill_z0 = axis_z
    fill_z = fluid_height
    obstacle_overlap_volume = blade_thickness * blade_length * fluid_height
    fill_box_volume = fill_x * fill_y * fill_z
    expected_fluid_volume = fill_box_volume - obstacle_overlap_volume
    expected_fluid_mass = expected_fluid_volume * 1000.0
    # The seed is deliberately in the left connected fluid region.  The old
    # seed was inside the moving paddle and caused GenCase to retain only a
    # small disconnected lattice component, producing 6--12 kg across dp.
    fluid_seed_x = fill_x0 + 0.10
    fluid_seed_x_right = fill_x0 + fill_x - 0.10
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
          <fillbox x="{fmt(fluid_seed_x)}" y="0" z="{fmt(axis_z + fluid_height / 2.0)}">
            <modefill>void</modefill>
            <point x="{fmt(fill_x0)}" y="{fmt(fill_y0)}" z="{fmt(fill_z0)}" />
            <size x="{fmt(fill_x)}" y="{fmt(fill_y)}" z="{fmt(fill_z)}" />
          </fillbox>
          <fillbox x="{fmt(fluid_seed_x_right)}" y="0" z="{fmt(axis_z + fluid_height / 2.0)}">
            <modefill>void</modefill>
            <point x="{fmt(fill_x0)}" y="{fmt(fill_y0)}" z="{fmt(fill_z0)}" />
            <size x="{fmt(fill_x)}" y="{fmt(fill_y)}" z="{fmt(fill_z)}" />
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
            "fill_box_origin_m": [fill_x0, fill_y0, fill_z0],
            "fill_box_size_m": [fill_x, fill_y, fill_z],
            "fluid_seeds_m": [[fluid_seed_x, 0.0, axis_z + fluid_height / 2.0],
                              [fluid_seed_x_right, 0.0, axis_z + fluid_height / 2.0]],
            "continuous_fill_box_volume_m3": fill_box_volume,
            "continuous_obstacle_overlap_volume_m3": obstacle_overlap_volume,
            "continuous_fluid_volume_m3": expected_fluid_volume,
            "continuous_initial_fluid_mass_kg": expected_fluid_mass,
            "narrowest_continuous_clearance_m": (tank_y - blade_length) / 2.0,
            "continuous_fluid_height_m": fluid_height,
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
        "registry_kind": spec.registry_kind, "physical_parent_id": spec.physical_parent_id,
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
            "continuous_geometry_audit": metadata.get("geometry"),
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


def _archive_legacy_views(family_dir: Path) -> dict[str, Any]:
    """Copy the already-run 48-view inputs before writing the new registry.

    The archive is write-once.  This keeps the exact XML/control/manifest bytes
    used by the first GenCase matrix available for forensic comparison while
    the canonical registry moves to physical parents.
    """
    archive = family_dir / "archive/legacy_views"
    archive.mkdir(parents=True, exist_ok=True)
    existing_manifest = archive / "archive_manifest.json"
    if existing_manifest.is_file():
        return json.loads(existing_manifest.read_text())
    candidates: list[Path] = []
    for directory, pattern in ((family_dir / "definitions", "F7_*_Def.xml"),
                               (family_dir / "controls", "F7_*_motion.csv"),
                               (family_dir / "case_manifests", "F7_*.json")):
        if directory.is_dir():
            candidates.extend(sorted(directory.glob(pattern)))
    for relative in ("case_registry.jsonl", "gencase_evidence.json", "repair_evidence.json",
                     "request_manifest.json", "split_plan.json", "family_card.json",
                     "qualified_recipes.json", "reference_evidence.json", "FAMILY_HANDOFF.md"):
        path = family_dir / relative
        if path.is_file():
            candidates.append(path)
    request_dir = family_dir / "requests"
    if request_dir.is_dir():
        candidates.extend(sorted(request_dir.glob("F7_*-gencase.json")))
    records: list[dict[str, Any]] = []
    for source in candidates:
        relative = source.relative_to(family_dir)
        destination = archive / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and sha256_file(destination) != sha256_file(source):
            raise RuntimeError(f"legacy archive collision with different bytes: {destination}")
        if not destination.is_file():
            shutil.copyfile(source, destination)
        records.append({"source": str(relative), "archive": str(destination.relative_to(family_dir)),
                        "sha256": sha256_file(destination), "bytes": destination.stat().st_size})
    manifest = {
        "schema": "ds02.f7.legacy-view-archive.v1",
        "evidence_boundary": "immutable archive of pre-parent 48-view inputs and registration; no qualification claim",
        "view_count_expected": 48,
        "records": records,
    }
    write_json(archive / "archive_manifest.json", manifest)
    return manifest


def _write_materialized_case(spec: CaseSpec, family_dir: Path,
                             assets: Mapping[str, Any]) -> dict[str, Any]:
    group = "production" if spec.registry_kind == "production" else "reference"
    root = family_dir / group
    definitions, controls, manifests = root / "definitions", root / "controls", root / "case_manifests"
    for path in (definitions, controls, manifests):
        path.mkdir(parents=True, exist_ok=True)
    definition = definitions / f"{spec.case_id}_Def.xml"
    control = controls / f"{spec.case_id}_motion.csv"
    if spec.mechanism == "pump_recirculation":
        xml, metadata = _pump_xml(spec, family_dir / "assets/official_pump")
        rows = _pump_control_rows(spec)
    else:
        xml, metadata = _obstacle_xml(spec)
        rows = _obstacle_control_rows(spec)
    write_text(definition, xml)
    _write_control(control, rows)
    manifest_path = manifests / f"{spec.case_id}.json"
    write_json(manifest_path, _case_manifest(spec, definition, control, metadata, assets, family_dir))
    return {
        **asdict(spec), "definition_xml": _relative(definition, family_dir),
        "control_csv": _relative(control, family_dir),
        "manifest_json": _relative(manifest_path, family_dir),
        "definition_sha256": sha256_file(definition), "control_sha256": sha256_file(control),
        "manifest_sha256": sha256_file(manifest_path), "native_3d_intent": True,
        "q_i": "pending", "q_n": "pending",
        "continuous_geometry_audit": metadata.get("geometry"),
    }


def materialize(family_dir: Path = FAMILY_DIR) -> dict[str, Any]:
    family_dir = Path(family_dir).resolve()
    legacy_archive = _archive_legacy_views(family_dir)
    assets_dir = family_dir / "assets/official_pump"
    for path in (assets_dir, family_dir / "requests", family_dir / "labels",
                 family_dir / "preview", family_dir / "production", family_dir / "reference"):
        path.mkdir(parents=True, exist_ok=True)
    assets = _asset_manifest(assets_dir)
    # Preserve the old definitions directory and its draw controls byte-for-
    # byte.  New XML is emitted below production/ and reference/.
    for name in ("pump_fixed.vtk", "pump_moving.vtk"):
        copy_if_needed(assets_dir / name, family_dir / "definitions" / name)
        copy_if_needed(assets_dir / name, family_dir / "production/definitions" / name)
        copy_if_needed(assets_dir / name, family_dir / "reference/definitions" / name)
    production = production_specs()
    references = reference_specs()
    registry: list[dict[str, Any]] = []
    for spec in production + references:
        registry.append(_write_materialized_case(spec, family_dir, assets))
    registry_text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in registry)
    write_text(family_dir / "case_registry.jsonl", registry_text)
    write_text(family_dir / "production/case_registry.jsonl",
               "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                       for row in registry if row["registry_kind"] == "production"))
    write_text(family_dir / "reference/case_registry.jsonl",
               "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                       for row in registry if row["registry_kind"] == "reference"))

    obstacle_audit: list[dict[str, Any]] = []
    for spec in references:
        if spec.mechanism != "moving_obstacle_exchange":
            continue
        _, metadata = _obstacle_xml(spec)
        geometry = metadata["geometry"]
        obstacle_audit.append({
            "physical_parent_id": spec.physical_parent_id, "resolution": spec.resolution,
            "dp_m": spec.dp_m, "continuous_geometry": geometry,
            "expected_fluid_layers_continuous": geometry["continuous_fluid_height_m"] / spec.dp_m,
            "actual_gencase_evidence": "see reference_gencase_snapshot; no mass normalization",
        })
    parent_rows = [row for row in registry if row["registry_kind"] == "production"]
    split_counts = {key: sum(row["split"] == key for row in parent_rows)
                    for key in ("train", "validation", "test")}
    existing_gencase = family_dir / "gencase_evidence.json"
    gencase_snapshot: list[dict[str, Any]] = []
    if existing_gencase.is_file():
        prior = json.loads(existing_gencase.read_text())
        if prior.get("schema") == "ds02.f7.gencase-evidence.v2":
            gencase_snapshot = [{key: row.get(key) for key in (
                "case_id", "mechanism", "resolution", "physical_parent_id", "total_particles",
                "fluid_particles", "initial_mass_kg", "continuous_expected_initial_mass_kg",
                "initial_mass_to_continuous_ratio", "domain_z_layers", "preflight_structural_pass",
                "receipt", "receipt_sha256") } for row in prior.get("receipts", [])]
    write_json(family_dir / "reference_evidence.json", {
        "schema": "ds02.f7.reference-evidence.v2", "created_at_utc": utc_now(),
        "evidence_boundary": "source, immutable legacy archive, and bounded GenCase planning only; no Q-I/Q-N claim",
        "legacy_view_archive": legacy_archive,
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
            "production_physical_case_count": len(parent_rows),
            "production_cases_per_mechanism": 24,
            "production_resolution_candidate": PRODUCTION_RESOLUTION,
            "reference_matrix_case_count": len(references),
            "resolution_matrix": [asdict(item) for item in RESOLUTIONS],
            "lifecycle": "finite initial fluid; native solver must select closed mass ledger or explicit open flux ledger",
            "time_window_s": [0.0, TIME_MAX_S],
        },
        "obstacle_continuous_geometry_audit": obstacle_audit,
        "reference_gencase_snapshot": {
            "status": "actual_bounded_cpu_gencase_audit_available" if gencase_snapshot else "pending",
            "evidence_path": str(existing_gencase), "rows": gencase_snapshot,
        },
    })
    write_json(family_dir / "split_plan.json", {
        "schema": "ds02.f7.split-plan.v2", "production_case_count": len(parent_rows),
        "production_cases_per_mechanism": 24, "reference_case_count": len(references),
        "physical_parent_rule": "one physical_parent_id owns one production resolution; reference parent owns all three resolution views",
        "stages": {
            "stage8": {"incremental_case_count": 8, "cumulative_case_count": 8,
                       "selection": "physical parents 0..3 per mechanism"},
            "stage24": {"incremental_case_count": 16, "cumulative_case_count": 24,
                         "selection": "physical parents 4..11 per mechanism"},
            "stage48": {"incremental_case_count": 24, "cumulative_case_count": 48,
                         "selection": "physical parents 12..23 per mechanism"},
        },
        "split_counts": split_counts,
        "split_counts_per_mechanism": {
            mechanism: {key: sum(row["mechanism"] == mechanism and row["split"] == key for row in parent_rows)
                         for key in ("train", "validation", "test")}
            for mechanism in ("pump_recirculation", "moving_obstacle_exchange")
        },
        "split_rule": "fixed NEW_SPLITS by physical parent index; applied before resolution views and never inherited from the legacy registry",
        "geometry_control_holdout": "indices 12..23 vary the continuous obstacle gap/offset or pump axis/control phase; all resolutions of any reference parent retain one split label",
        "qualification_boundary": "registry membership is not Q-I or Q-N evidence",
    })
    write_json(family_dir / "qualified_recipes.json", {
        "schema": "ds02.f7.qualified-recipes.v2", "status": "none_qualified",
        "q_i": "pending actual corrected GenCase, native solver trajectory, lifecycle ledger and labels",
        "q_n": "pending actual recipe/time/observables evidence",
        "production_resolution_candidate": PRODUCTION_RESOLUTION,
        "recipes": [{"case_id": row["case_id"], "physical_parent_id": row["physical_parent_id"],
                     "registry_kind": row["registry_kind"], "mechanism": row["mechanism"],
                     "resolution": row["resolution"], "split": row["split"],
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
        "schema": "ds02.f7.family-card.v2", "family_id": "F7",
        "title": "3-D pump recirculation and moving-obstacle exchange",
        "generator": str(Path(__file__).resolve()), "generator_sha256": sha256_file(Path(__file__).resolve()),
        "created_at_utc": utc_now(), "production_case_count": len(parent_rows),
        "reference_case_count": len(references), "legacy_view_count": len(_legacy_view_specs()),
        "production_cases_per_mechanism": 24, "production_resolution_candidate": PRODUCTION_RESOLUTION,
        "mechanisms": {"pump_recirculation": "official 13_Pump fixed/moving POLYDATA with native reverse/stop motion",
                       "moving_obstacle_exchange": "finite 3-D tank with a 3-D rotating paddle and phase-reversed motion"},
        "resolution_matrix": [asdict(item) for item in RESOLUTIONS], "time_window_s": [0.0, TIME_MAX_S],
        "status": "physical registry/materialized inputs; corrected GenCase/solver/Q-I/Q-N pending",
        "next_executable": "run reference GenCase requests, then root may submit six qualification requests using actual BI4/XML/control hashes",
    })
    write_text(family_dir / "FAMILY_HANDOFF.md", f"""# F7 handoff

The canonical registry now has 48 independent physical parents: 24 Pump and 24 moving-obstacle conditions. Production uses one candidate resolution ({PRODUCTION_RESOLUTION}) per physical parent. A separate six-case reference matrix keeps one `physical_parent_id` across coarse/medium/fine for each mechanism. The prior 48 resolution views and their exact GenCase inputs are write-once under `archive/legacy_views/`.

The physical split is fixed before resolution views: 8 train, 8 validation and 8 test parents per mechanism. Nested subsets are 8, 24 and 48 cumulative cases; no legacy modulo-resolution split is reused.

The obstacle audit records the continuous fill volume, paddle overlap, narrowest clearance and expected fluid layers per `dp`. The old 6/10.752/12.460032 kg counts came from a seed inside the paddle and are retained only as archived evidence; corrected requests seed the connected fluid region and must be remeasured without mass normalization.

Historical Pump evidence is diagnostic only: old D05 reported 12 missing identities and 0.324 kg. Native solver requests must establish a closed mass ledger or an explicit open boundary flux/lifecycle ledger, plus source-zone, first-passage, residence, repeated-cycle and backflow labels.

Status: bounded GenCase evidence and six solver request plans only. No Q-I, Q-N or production claim is made. GPU/solver has not been started by this family.

Generated at {utc_now()}.
""")
    return {"family_dir": str(family_dir), "production_case_count": len(parent_rows),
            "reference_case_count": len(references), "legacy_view_count": len(_legacy_view_specs()),
            "mechanism_counts": {key: sum(row["mechanism"] == key for row in parent_rows)
                                 for key in ("pump_recirculation", "moving_obstacle_exchange")},
            "resolution_counts": {key: sum(row["resolution"] == key for row in parent_rows)
                                  for key in ("coarse", "medium", "fine")}, "asset_manifest": assets}


def _request_cases(mode: str) -> list[CaseSpec]:
    production = production_specs()
    references = reference_specs()
    if mode == "all":
        return production + references
    if mode == "production":
        return production
    if mode == "stage8":
        return [spec for spec in production if stage_for_case(spec) == "stage8"]
    if mode == "stage24":
        return [spec for spec in production if stage_for_case(spec) in {"stage8", "stage24"}]
    if mode == "stage48":
        return production
    if mode in {"matrix", "reference"}:
        return references
    raise ValueError(f"unknown request mode: {mode}")


def emit_requests(family_dir: Path = FAMILY_DIR, mode: str = "matrix", attempt_number: int = 1) -> list[Path]:
    family_dir = Path(family_dir).resolve()
    materialize(family_dir)
    request_dir = family_dir / "requests"
    roots = {"production": family_dir / "production", "reference": family_dir / "reference"}
    assets = family_dir / "assets/official_pump"
    emitted: list[Path] = []
    for spec in _request_cases(mode):
        root = roots[spec.registry_kind]
        definitions, controls = root / "definitions", root / "controls"
        definition = definitions / f"{spec.case_id}_Def.xml"
        control = controls / f"{spec.case_id}_motion.csv"
        inputs = [GENCASE, definition, control, Path(__file__).resolve()]
        if spec.mechanism == "pump_recirculation":
            inputs += [assets / "CasePump_Def.xml", definitions / "pump_fixed.vtk", definitions / "pump_moving.vtk"]
        request = {
            "schema": "ds02.cpu-request.v2", "family_id": "F7", "case_id": spec.case_id,
            "attempt_id": f"{spec.case_id}_GENCASE_{attempt_number:02d}", "kind": "cpu", "cpu_task_kind": "gencase",
            "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/" + spec.case_id, "-save:all"],
            "cwd": str(definitions), "max_wall_seconds": 300, "cpu_threads": 4,
            "estimated_storage_bytes": 240 * 1024 * 1024, "input_files": [str(path) for path in inputs],
            "worktree_root": str(REPO),
            "purpose": "bounded native GenCase preflight only; no solver/GPU/model",
            "physical_parent_id": spec.physical_parent_id, "registry_kind": spec.registry_kind,
            "expected_checks": {"mechanism": spec.mechanism, "registry_kind": spec.registry_kind,
                                "physical_parent_id": spec.physical_parent_id, "resolution": spec.resolution,
                                "expected_dimension": 3, "positive_fluid_required": True,
                                "motion_window_s": [0.0, spec.time_max_s], "gap_axis": spec.gap_fraction,
                                "initial_mass": "parse native MassFluid and actual fluid count; no rescaling"},
            "provenance_note": "Later solver requests must cite this request, actual external GenCase prefix/BI4/XML/control hashes.",
        }
        path = request_dir / f"{spec.case_id}-gencase.json"
        write_json(path, request)
        emitted.append(path)
    write_json(family_dir / "request_manifest.json", {
        "schema": "ds02.f7.request-manifest.v2", "mode": mode, "request_count": len(emitted),
        "requests": [str(path.relative_to(family_dir)) for path in emitted],
        "resource_boundary": {"max_wall_seconds": 300, "cpu_threads": 4, "estimated_storage_bytes": 240 * 1024 * 1024},
        "status": "ready_for_shared_runner; not executed by this command",
    })
    return emitted


def _ceil_storage(value: int, quantum: int = 256 * 1024 * 1024) -> int:
    return max(quantum, ((max(value, 0) + quantum - 1) // quantum) * quantum)


def _solver_cost_estimate(total_particles: int, *, frames: int = 601) -> dict[str, Any]:
    # BI4 and native output overhead vary by build.  Use a deliberately
    # conservative all-type estimate so root can reserve storage before GPU.
    bytes_per_particle_frame = 96
    raw = total_particles * frames * bytes_per_particle_frame
    estimated_storage = _ceil_storage(int(raw * 1.75) + 512 * 1024 * 1024)
    max_wall = 600 + 300 * max(0, math.ceil(total_particles / 25_000) - 1)
    return {
        "all_type_particle_count": total_particles,
        "frames_at_time_out": frames,
        "bytes_per_particle_frame_assumed": bytes_per_particle_frame,
        "raw_all_type_particle_bytes": raw,
        "estimated_storage_bytes": estimated_storage,
        "max_wall_seconds": min(max_wall, 3600),
        "estimate_status": "conservative planning estimate; solver not run",
    }


def emit_solver_requests(family_dir: Path, receipt_paths: Iterable[Path],
                         attempt_number: int = 1) -> list[Path]:
    """Bind six qualification requests to actual reference GenCase outputs."""
    family_dir = Path(family_dir).resolve()
    materialize(family_dir)
    specs = {spec.case_id: spec for spec in reference_specs()}
    requests: list[Path] = []
    for receipt_path in receipt_paths:
        receipt_path = Path(receipt_path).resolve()
        receipt = json.loads(receipt_path.read_text())
        case_id = receipt.get("request", {}).get("case_id")
        if case_id not in specs:
            raise ValueError(f"solver request requires a reference receipt: {case_id}")
        spec = specs[case_id]
        output = Path(receipt.get("output_root", "")).resolve()
        prefix = output / case_id
        bi4 = prefix.with_suffix(".bi4")
        xml = prefix.with_suffix(".xml")
        if not bi4.is_file() or not xml.is_file():
            raise FileNotFoundError(f"actual GenCase prefix is incomplete: {prefix}")
        source_control = family_dir / "reference/controls" / f"{case_id}_motion.csv"
        source_definition = family_dir / "reference/definitions" / f"{case_id}_Def.xml"
        if not source_control.is_file() or not source_definition.is_file():
            raise FileNotFoundError(f"reference input is missing for {case_id}")
        control_copy = output / f"{case_id}_motion.csv"
        copy_if_needed(source_control, control_copy)
        stdout = output / "stdout.log"
        parsed = parse_gencase_stdout(stdout) if stdout.is_file() else {}
        total_particles = parsed.get("total_particles")
        if not isinstance(total_particles, int) or total_particles <= 0:
            raise ValueError(f"actual particle count missing for {case_id}")
        cost = _solver_cost_estimate(total_particles)
        solver = BIN_ROOT / "DualSPHysics5.4_linux64"
        input_files = [receipt_path, bi4, xml, control_copy, source_control, source_definition]
        input_hashes = {str(path): sha256_file(path) for path in input_files}
        generator_path = str(Path(__file__).resolve())
        generator_hash_at_gencase = receipt.get("input_hashes_after_run", {}).get(generator_path)
        request = {
            "schema": "ds02.runner-request.v2", "family_id": "F7", "case_id": case_id,
            "attempt_id": f"{case_id}_QUALIFICATION_{attempt_number:03d}",
            "physical_case_id": spec.physical_parent_id, "physical_parent_id": spec.physical_parent_id,
            "registry_kind": "reference", "kind": "qualification",
            "command": [str(solver), str(prefix), "{attempt_root}/solver",
                         f"-tmax:{fmt(spec.time_max_s)}", f"-tout:{fmt(spec.time_out_s)}"],
            "cwd": str(output), "worktree_root": str(REPO),
            "max_wall_seconds": cost["max_wall_seconds"], "cpu_threads": 2,
            "estimated_storage_bytes": cost["estimated_storage_bytes"],
            "estimated_peak_gpu_mib": max(2048, min(12288, 1024 * ((total_particles + 24_999) // 25_000))),
            "gencase_receipt": str(receipt_path),
            "gencase_receipt_sha256": sha256_file(receipt_path),
            "gencase_prefix": str(prefix), "gencase_bi4": str(bi4),
            "gencase_xml": str(xml), "control_copy": str(control_copy),
            "input_files": [str(path) for path in input_files], "input_hashes": input_hashes,
            "gencase_generator": {"path": generator_path,
                                  "sha256_at_gencase": generator_hash_at_gencase,
                                  "sha256_current": sha256_file(Path(__file__).resolve()),
                                  "changed_since_gencase": generator_hash_at_gencase not in {None, sha256_file(Path(__file__).resolve())}},
            "raw_all_type_particle_estimate": cost,
            "qualification_scope": {
                "mechanism": spec.mechanism, "resolution": spec.resolution,
                "physical_parent_id": spec.physical_parent_id,
                "time_window_s": [0.0, spec.time_max_s], "output_interval_s": spec.time_out_s,
                "observables": ["finite internal-plane net flux", "periodic velocity/kinetic-energy response",
                                "source-zone exchange and residence", "first-passage and repeated-cycle crossing",
                                "startup, stop/reverse and backflow", "typed identity mass ledger"],
                "lifecycle_status": "finite_initial_fluid; solver must prove closed ledger or explicit open flux ledger",
                "status": "candidate reference request; Q-I/Q-N pending solver evidence",
            },
            "scientific_status": "raw 3-D reference candidate; no Q-I/Q-N/production claim",
        }
        path = family_dir / "requests" / f"{case_id}-solver.json"
        write_json(path, request)
        requests.append(path)
    write_json(family_dir / "solver_request_manifest.json", {
        "schema": "ds02.f7.solver-request-manifest.v1", "request_count": len(requests),
        "requests": [str(path.relative_to(family_dir)) for path in requests],
        "status": "ready_for_root_shared_runner; GPU/solver not started by this command",
        "reference_matrix_rule": "same physical_parent_id across coarse/medium/fine; reference only",
    })
    return requests


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
    specs = {spec.case_id: spec for spec in _all_specs()}
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
        if spec.registry_kind == "legacy_view":
            root = family_dir / "archive/legacy_views"
        else:
            root = family_dir / spec.registry_kind
        definition = root / "definitions" / f"{case_id}_Def.xml"
        control = root / "controls" / f"{case_id}_motion.csv"
        control_rows = max(0, sum(1 for _ in control.open(encoding="utf-8", errors="replace")) - 2) if control.is_file() else 0
        manifest_path = root / "case_manifests" / f"{case_id}.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        geometry = manifest.get("recipe", {}).get("continuous_geometry_audit")
        expected_mass = geometry.get("continuous_initial_fluid_mass_kg") if isinstance(geometry, dict) else None
        actual_mass = (None if parsed.get("fluid_particles") is None or parsed.get("mass_fluid_kg_per_particle") is None
                       else parsed["fluid_particles"] * parsed["mass_fluid_kg_per_particle"])
        checks = {
            "positive_fluid": bool(parsed.get("fluid_particles", 0) > 0),
            "actual_3d": parsed.get("solver_dimension_from_gencase") == 3,
            "multiple_z_layers": bool(parsed.get("domain_z_layers", 0) > 1),
            "motion_control_rows_cover_window": control_rows >= int(spec.time_max_s / 0.02),
        }
        row = {
            "case_id": spec.case_id, "mechanism": spec.mechanism, "resolution": spec.resolution,
            "receipt": str(receipt_path), "receipt_sha256": sha256_file(receipt_path),
            "physical_parent_id": spec.physical_parent_id, "registry_kind": spec.registry_kind,
            "split": spec.split, "stage": spec.stage,
            "output_root": str(output), "status": receipt.get("status"), "returncode": receipt.get("returncode"),
            "elapsed_seconds": receipt.get("elapsed_seconds"), "bytes": receipt.get("bytes"), **parsed,
            "definition_sha256": sha256_file(definition) if definition.is_file() else None,
            "control_sha256": sha256_file(control) if control.is_file() else None,
            "control_rows": control_rows, "motion_window_requested_s": [0.0, spec.time_max_s],
            "gap_fraction_requested": spec.gap_fraction, "initial_mass_kg": actual_mass,
            "continuous_geometry": geometry,
            "continuous_expected_initial_mass_kg": expected_mass,
            "initial_mass_to_continuous_ratio": (None if actual_mass is None or not expected_mass
                                                   else actual_mass / expected_mass),
            "native_checks": checks, "preflight_structural_pass": all(checks.values()) and receipt.get("status") == "completed",
            "qualification_boundary": "GenCase/preflight evidence only; Q-I/Q-N/production remain pending native solver trajectory, lifecycle and observables",
        }
        rows.append(row)
    result = {"schema": "ds02.f7.gencase-evidence.v2", "created_at_utc": utc_now(),
              "evidence_boundary": "actual bounded CPU GenCase only; no Q-I/Q-N claim", "receipts": rows}
    write_json(family_dir / "gencase_evidence.json", result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    materialize_cmd = sub.add_parser("materialize")
    materialize_cmd.add_argument("--family-dir", type=Path, default=FAMILY_DIR)
    materialize_cmd.add_argument("--emit-requests", choices=("none", "matrix", "reference", "production", "stage8", "stage24", "stage48", "all"), default="none")
    requests_cmd = sub.add_parser("requests")
    requests_cmd.add_argument("--family-dir", type=Path, default=FAMILY_DIR)
    requests_cmd.add_argument("--mode", choices=("matrix", "reference", "production", "stage8", "stage24", "stage48", "all"), default="matrix")
    requests_cmd.add_argument("--attempt-number", type=int, default=1)
    solver_cmd = sub.add_parser("solver-requests")
    solver_cmd.add_argument("receipts", nargs="+", type=Path)
    solver_cmd.add_argument("--family-dir", type=Path, default=FAMILY_DIR)
    solver_cmd.add_argument("--attempt-number", type=int, default=1)
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
    elif args.command == "solver-requests":
        result = {"requests": [str(path) for path in emit_solver_requests(
            args.family_dir, args.receipts, args.attempt_number)]}
    else:
        result = audit_receipts(args.receipts, args.family_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
