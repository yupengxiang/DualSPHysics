#!/usr/bin/env python3
"""Register source-derived scales before comparing F7-S2 observer fields.

This forward-only contract reads the exact generated F7-S2 XML and its
prescribed rotation table.  It never opens BI4, native Part files, HDF5, or
starts a solver.  The resulting scales are reference denominators for a
future field comparison; they are not a physical qualification result.

The motion table's 12 s coverage is recorded as control coverage.  It is
deliberately not used as the characteristic event time because the source
does not declare an event (contact, peak run-up, or another observable
landmark).  Consumers must keep event-time error UNKNOWN until they bind an
event definition and its source evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Iterable


SCHEMA = "ds02.stage2.f7-s2.observer-calibration-contract.v3"
REPO = Path(__file__).resolve().parents[5]
DEFAULT_XML = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_OBSTACLE_QUINTIC_B08_A065/"
    "root-stage1-f7-angle065-genuine-gencase-085/prepared/"
    "F7_OBSTACLE_QUINTIC_B08_A065.xml"
)
DEFAULT_MOTION = DEFAULT_XML.parent / "motion_obstacle_quintic.dat"
DEFAULT_OUTPUT = (
    REPO
    / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f7_s2_observer_calibration_contract_v3.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def number(node: ET.Element, key: str) -> float:
    raw = node.attrib.get(key)
    if raw is None:
        raise ValueError(f"{tag(node)} is missing @{key}")
    return float(raw)


def point_size(node: ET.Element) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    point = node.find("point")
    size = node.find("size")
    if point is None or size is None:
        raise ValueError("drawbox must contain point and size")
    return (
        tuple(number(point, axis) for axis in ("x", "y", "z")),
        tuple(number(size, axis) for axis in ("x", "y", "z")),
    )


def source_boxes(root: ET.Element) -> dict[str, Any]:
    """Extract exact F7 source fluid and moving-body box extents.

    The source has one ``setmkfluid`` followed by four wet-region boxes and
    one ``setmkbound mk=2`` followed by the moving obstacle box.  We track
    the active declaration in document order so an unrelated fixed-boundary
    box cannot silently become the fluid scale.
    """

    fluid_boxes: list[dict[str, Any]] = []
    moving_boxes: list[dict[str, Any]] = []
    active: tuple[str, str] | None = None
    for node in root.iter():
        name = tag(node)
        if name in {"setmkfluid", "setmkbound"}:
            mk = node.attrib.get("mk")
            active = ("fluid" if name == "setmkfluid" else "bound", str(mk))
            continue
        if name != "drawbox" or active is None:
            continue
        point, size = point_size(node)
        record = {
            "point_m": list(point),
            "size_m": list(size),
            "end_m": [point[i] + size[i] for i in range(3)],
            "comment": node.attrib.get("cmt"),
            "mk_role": active[0],
            "mk": active[1],
        }
        if active == ("fluid", "1"):
            fluid_boxes.append(record)
        elif active == ("bound", "2"):
            moving_boxes.append(record)
    if len(fluid_boxes) != 4:
        raise ValueError(f"expected four mkfluid=1 boxes, found {len(fluid_boxes)}")
    if len(moving_boxes) != 1:
        raise ValueError(f"expected one moving mkbound=2 box, found {len(moving_boxes)}")

    lo = [min(box["point_m"][i] for box in fluid_boxes) for i in range(3)]
    hi = [max(box["end_m"][i] for box in fluid_boxes) for i in range(3)]
    extents = [hi[i] - lo[i] for i in range(3)]
    moving = moving_boxes[0]
    return {
        "fluid_boxes": fluid_boxes,
        "fluid_union_bounds_m": {"min": lo, "max": hi},
        "fluid_union_extent_m": extents,
        "fluid_reference_length_m": max(extents),
        "moving_obstacle_box": moving,
    }


def motion_axis(root: ET.Element) -> dict[str, Any]:
    rotations = [node for node in root.iter() if tag(node) == "mvrotfile"]
    if len(rotations) != 2:
        raise ValueError(f"expected two XML mvrotfile nodes (casedef/execution), found {len(rotations)}")
    node = rotations[0]
    file_node = node.find("file")
    p1 = node.find("axisp1")
    p2 = node.find("axisp2")
    if file_node is None or p1 is None or p2 is None:
        raise ValueError("mvrotfile is missing file or axis endpoints")
    a = [number(p1, axis) for axis in ("x", "y", "z")]
    b = [number(p2, axis) for axis in ("x", "y", "z")]
    direction = [b[i] - a[i] for i in range(3)]
    length = math.sqrt(sum(value * value for value in direction))
    if not length:
        raise ValueError("rotation axis has zero length")
    unit = [value / length for value in direction]
    return {
        "file_name": file_node.attrib.get("name"),
        "duration_s": float(node.attrib["duration"]),
        "angles_units": node.attrib.get("anglesunits"),
        "axis_p1_m": a,
        "axis_p2_m": b,
        "axis_unit": unit,
    }


def parse_motion(path: Path) -> dict[str, Any]:
    times: list[float] = []
    angles: list[float] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            fields = line.replace(",", "\t").split()
            if len(fields) < 2:
                raise ValueError(f"motion line {line_number} has fewer than two columns")
            times.append(float(fields[0]))
            angles.append(float(fields[1]))
    if len(times) < 3:
        raise ValueError("motion table has fewer than three samples")
    steps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    if any(step <= 0 for step in steps):
        raise ValueError("motion times are not strictly increasing")
    speeds_deg = [(angles[i + 1] - angles[i]) / steps[i] for i in range(len(steps))]
    return {
        "rows": len(times),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "sample_dt_min_s": min(steps),
        "sample_dt_max_s": max(steps),
        "angle_min_deg": min(angles),
        "angle_max_deg": max(angles),
        "max_abs_angular_speed_deg_per_s": max(abs(value) for value in speeds_deg),
        "max_abs_angular_speed_rad_per_s": max(abs(value) for value in speeds_deg) * math.pi / 180.0,
        "table_semantics": "prescribed rotation angle; solver evaluates the source table, no event label is declared",
    }


def distance_to_axis(point: Iterable[float], axis_point: Iterable[float], axis_unit: Iterable[float]) -> float:
    vector = [float(point[i]) - float(axis_point[i]) for i in range(3)]
    cross = [
        vector[1] * axis_unit[2] - vector[2] * axis_unit[1],
        vector[2] * axis_unit[0] - vector[0] * axis_unit[2],
        vector[0] * axis_unit[1] - vector[1] * axis_unit[0],
    ]
    return math.sqrt(sum(value * value for value in cross))


def moving_radius(box: dict[str, Any], axis: dict[str, Any]) -> float:
    point = box["point_m"]
    end = box["end_m"]
    corners = []
    for x in (point[0], end[0]):
        for y in (point[1], end[1]):
            for z in (point[2], end[2]):
                corners.append((x, y, z))
    return max(distance_to_axis(corner, axis["axis_p1_m"], axis["axis_unit"]) for corner in corners)


def xml_scalar(root: ET.Element, element_name: str, attribute: str, default: float | None = None) -> float | None:
    values = [float(node.attrib[attribute]) for node in root.iter() if tag(node) == element_name and attribute in node.attrib]
    if not values:
        return default
    if max(values) - min(values) > 1e-12:
        raise ValueError(f"conflicting {element_name}@{attribute} values: {values}")
    return values[0]


def xml_particle_counts(root: ET.Element) -> dict[str, int]:
    result: dict[str, int] = {}
    for node in root.iter():
        if tag(node) == "fluid" and node.attrib.get("mkfluid") == "1" and "count" in node.attrib:
            result["fluid"] = result.get("fluid", 0) + int(node.attrib["count"])
        elif tag(node) == "moving" and "count" in node.attrib:
            result["moving"] = result.get("moving", 0) + int(node.attrib["count"])
    if result.get("fluid") != 40700 or result.get("moving") != 1984:
        raise ValueError(f"unexpected F7 particle counts: {result}")
    return result


def build(xml_path: Path = DEFAULT_XML, motion_path: Path = DEFAULT_MOTION) -> dict[str, Any]:
    xml_record = file_record(xml_path)
    motion_record = file_record(motion_path)
    root = ET.fromstring(xml_path.read_bytes())
    boxes = source_boxes(root)
    axis = motion_axis(root)
    motion = parse_motion(motion_path)
    counts = xml_particle_counts(root)
    massfluid = xml_scalar(root, "massfluid", "value")
    massbound = xml_scalar(root, "massbound", "value")
    if massfluid is None or massbound is None:
        raise ValueError("F7 source does not declare massfluid/massbound")
    fluid_mass = counts["fluid"] * massfluid
    moving_sample_mass = counts["moving"] * massbound
    radius = moving_radius(boxes["moving_obstacle_box"], axis)
    omega = motion["max_abs_angular_speed_rad_per_s"]
    velocity = omega * radius
    ke_scale = 0.5 * fluid_mass * velocity * velocity
    motion_duration = motion["time_end_s"] - motion["time_start_s"]
    if abs(motion_duration - axis["duration_s"]) > 1e-12:
        raise ValueError("motion table duration and XML mvrotfile duration disagree")
    output = {
        "schema": SCHEMA,
        "status": "SOURCE_BOUND_SCALES_REGISTERED_EVENT_TIME_UNKNOWN",
        "sentinel_id": "F7-S2",
        "family_id": "F7",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "purpose": "pre-register field comparison scales before any actual differences are evaluated",
        "source_inputs": {
            "generated_xml": xml_record,
            "motion_table": motion_record,
            "read_scope": "XML geometry/control and prescribed motion table only; no BI4/native Part/HDF5",
        },
        "source_geometry": {
            "fluid_union_bounds_m": boxes["fluid_union_bounds_m"],
            "fluid_union_extent_m": boxes["fluid_union_extent_m"],
            "L_position_reference_scalar_m": boxes["fluid_reference_length_m"],
            "L_position_reference_definition": "longest declared mkfluid=1 wet-region union extent; aggregate scalar only",
            "axis_specific_position_scales_m": boxes["fluid_union_extent_m"],
            "moving_obstacle_box": boxes["moving_obstacle_box"],
            "moving_radius_about_prescribed_axis_m": radius,
        },
        "source_control": {
            "rotation_axis": axis,
            "motion_table": motion,
            "control_coverage_s": [motion["time_start_s"], motion["time_end_s"]],
            "control_coverage_is_event_time": False,
        },
        "reference_scales": {
            "velocity_scale_m_per_s": velocity,
            "velocity_scale_definition": "max source-table angular speed times maximum moving-obstacle corner radius",
            "angular_speed_scale_rad_per_s": omega,
            "fluid_sample_mass_kg": fluid_mass,
            "moving_sample_mass_kg_diagnostic_only": moving_sample_mass,
            "moving_sample_mass_is_rigid_body_mass": False,
            "kinetic_energy_scale_j": ke_scale,
            "kinetic_energy_scale_definition": "0.5 * fluid sample mass * source-driven velocity scale^2",
            "scale_role": "reference denominator; not a predicted fluid value and not rigid-body physical mass",
        },
        "event_time": {
            "characteristic_time_s": None,
            "status": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "reason": "source declares motion-table coverage but no contact, peak, run-up, or other event landmark",
            "cannot_use_control_duration_as_event_T": True,
            "consumer_requirement": "bind an event definition and exact source evidence before evaluating 1% event-time budget",
        },
        "frozen_error_budget": {
            "position_fraction_of_L": 0.02,
            "velocity_and_ke_fraction_of_registered_nonzero_scale": 0.05,
            "event_time_fraction_of_characteristic_T": 0.01,
            "time_and_output_each_max_fraction_of_task_budget": 0.25,
            "event_time_evaluation_status": "BLOCKED_UNKNOWN_UNTIL_EVENT_REGISTRATION",
        },
        "comparison_gate": {
            "field_differences_allowed": False,
            "required_inputs": ["this contract", "actual query brackets", "event registration if event-time field is used"],
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    return output


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse overwrite of existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def self_test() -> None:
    xml = """<case><geometry><commands>
      <setmkfluid mk='1'/><drawbox><point x='0' y='0' z='0'/><size x='1' y='2' z='3'/></drawbox>
      <drawbox><point x='-1' y='0' z='0'/><size x='1' y='2' z='3'/></drawbox>
      <drawbox><point x='0' y='0' z='0'/><size x='1' y='2' z='3'/></drawbox>
      <drawbox><point x='0' y='0' z='0'/><size x='1' y='2' z='3'/></drawbox>
      <setmkbound mk='2'/><drawbox><point x='-0.1' y='-0.2' z='0'/><size x='0.2' y='0.4' z='1'/></drawbox>
    </commands></geometry><motion><mvrotfile duration='1' anglesunits='degrees'>
      <file name='m.dat'/><axisp1 x='0' y='0' z='0'/><axisp2 x='0' y='0' z='1'/>
    </mvrotfile><mvrotfile duration='1' anglesunits='degrees'><file name='m.dat'/>
      <axisp1 x='0' y='0' z='0'/><axisp2 x='0' y='0' z='1'/></mvrotfile></motion>
      <execution><particles><fluid mkfluid='1' count='4'/><moving count='2'/></particles>
      <constants><massfluid value='2'/><massbound value='3'/></constants></execution></case>"""
    with tempfile.TemporaryDirectory(prefix="f7-contract-test-") as tmp:
        root = ET.fromstring(xml)
        boxes = source_boxes(root)
        axis = motion_axis(root)
        assert boxes["fluid_reference_length_m"] == 3.0
        assert math.isclose(moving_radius(boxes["moving_obstacle_box"], axis), math.sqrt(0.1**2 + 0.2**2))
        motion = Path(tmp) / "m.dat"
        motion.write_text("# t angle\n0 0\n0.5 10\n1 0\n", encoding="utf-8")
        parsed = parse_motion(motion)
        assert parsed["rows"] == 3
        assert parsed["max_abs_angular_speed_deg_per_s"] == 20.0
    assert SCHEMA.endswith("v3")
    print(json.dumps({"status": "SELF_TEST_PASS", "schema": SCHEMA}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--xml", type=Path, default=DEFAULT_XML)
    parser.add_argument("--motion", type=Path, default=DEFAULT_MOTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.build:
        parser.error("use --build or --self-test")
    value = build(args.xml, args.motion)
    atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output), "schema": SCHEMA}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
