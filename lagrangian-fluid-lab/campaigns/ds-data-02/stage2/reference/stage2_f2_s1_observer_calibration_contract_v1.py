#!/usr/bin/env python3
"""Freeze F2-S1 source scales before comparing full-window observer fields.

The exact generated XML and prescribed rotation table are small control
inputs.  The contract keeps the continuous box-volume mass and the discrete
particle sample mass separate.  It never reads BI4/native Part/HDF5 data or
starts a solver.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.observer-calibration-contract.v1"
REPO = Path(__file__).resolve().parents[5]
DEFAULT_XML = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/"
    "root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-gencase-source801-root804/prepared/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010.xml"
)
DEFAULT_MOTION = DEFAULT_XML.parent / (
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat"
)
DEFAULT_OUTPUT = (
    REPO
    / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f2_s1_observer_calibration_contract_v1.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def fattr(node: ET.Element, key: str) -> float:
    raw = node.attrib.get(key)
    if raw is None:
        raise ValueError(f"{tag(node)} missing @{key}")
    return float(raw)


def box(node: ET.Element) -> dict[str, Any]:
    point, size = node.find("point"), node.find("size")
    if point is None or size is None:
        raise ValueError("drawbox missing point/size")
    p = [fattr(point, axis) for axis in ("x", "y", "z")]
    s = [fattr(size, axis) for axis in ("x", "y", "z")]
    return {"point_m": p, "size_m": s, "end_m": [p[i] + s[i] for i in range(3)], "comment": node.attrib.get("cmt")}


def source_geometry(root: ET.Element) -> dict[str, Any]:
    active: tuple[str, str] | None = None
    fluid: list[dict[str, Any]] = []
    moving: list[dict[str, Any]] = []
    for node in root.iter():
        node_tag = tag(node)
        if node_tag in {"setmkfluid", "setmkbound"}:
            active = ("fluid" if node_tag == "setmkfluid" else "bound", node.attrib.get("mk", ""))
        elif node_tag == "drawbox":
            parsed = box(node)
            if active and active[0] == "fluid" and active[1] in {"0", "1", "2"}:
                fluid.append({"mkfluid": int(active[1]), **parsed})
            elif active == ("bound", "0"):
                moving.append(parsed)
    if len(fluid) != 3 or len(moving) != 1:
        raise ValueError(f"expected three fluid and one moving boxes, found {len(fluid)}, {len(moving)}")
    lo = [min(item["point_m"][i] for item in fluid) for i in range(3)]
    hi = [max(item["end_m"][i] for item in fluid) for i in range(3)]
    extent = [hi[i] - lo[i] for i in range(3)]
    gravity = next((node for node in root.iter() if tag(node) == "gravity" and "z" in node.attrib), None)
    rotations = [node for node in root.iter() if tag(node) == "mvrotfile"]
    if gravity is None or len(rotations) != 2:
        raise ValueError(f"missing gravity or expected two mvrotfile nodes: {len(rotations)}")
    rotation = rotations[0]
    file_node = rotation.find("file")
    p1, p2 = rotation.find("axisp1"), rotation.find("axisp2")
    if file_node is None or p1 is None or p2 is None:
        raise ValueError("rotation source missing file/axis")
    a = [fattr(p1, axis) for axis in ("x", "y", "z")]
    b = [fattr(p2, axis) for axis in ("x", "y", "z")]
    direction = [b[i] - a[i] for i in range(3)]
    axis_len = math.sqrt(sum(value * value for value in direction))
    axis_unit = [value / axis_len for value in direction]
    return {
        "fluid_boxes": fluid,
        "fluid_union_bounds_m": {"min": lo, "max": hi},
        "fluid_union_extent_m": extent,
        "L_position_reference_scalar_m": max(extent),
        "moving_body_box": moving[0],
        "gravity_z_m_per_s2": fattr(gravity, "z"),
        "rotation_axis": {
            "p1_m": a,
            "p2_m": b,
            "unit": axis_unit,
            "duration_s": float(rotation.attrib["duration"]),
            "file_name": file_node.attrib.get("name"),
        },
    }


def distance_to_axis(point: list[float], axis_point: list[float], axis_unit: list[float]) -> float:
    vector = [point[i] - axis_point[i] for i in range(3)]
    cross = [
        vector[1] * axis_unit[2] - vector[2] * axis_unit[1],
        vector[2] * axis_unit[0] - vector[0] * axis_unit[2],
        vector[0] * axis_unit[1] - vector[1] * axis_unit[0],
    ]
    return math.sqrt(sum(value * value for value in cross))


def moving_radius(geometry: dict[str, Any]) -> float:
    body = geometry["moving_body_box"]
    p, end = body["point_m"], body["end_m"]
    corners = [[x, y, z] for x in (p[0], end[0]) for y in (p[1], end[1]) for z in (p[2], end[2])]
    axis = geometry["rotation_axis"]
    return max(distance_to_axis(corner, axis["p1_m"], axis["unit"]) for corner in corners)


def scalar(root: ET.Element, element_name: str, attribute: str) -> float:
    values = [fattr(node, attribute) for node in root.iter() if tag(node) == element_name and attribute in node.attrib]
    if not values or max(values) - min(values) > 1e-10:
        raise ValueError(f"missing/conflicting {element_name}@{attribute}: {values}")
    return values[0]


def particles(root: ET.Element) -> dict[str, Any]:
    fluids = [node for node in root.iter() if tag(node) == "fluid" and "begin" in node.attrib]
    moving = next((node for node in root.iter() if tag(node) == "moving" and "begin" in node.attrib), None)
    if len(fluids) != 3 or moving is None:
        raise ValueError(f"unexpected F2 particle blocks: fluids={len(fluids)}, moving={moving is not None}")
    counts = [int(node.attrib["count"]) for node in fluids]
    mass = scalar(root, "massfluid", "value")
    if counts != [7038, 7038, 7038] or abs(mass - 0.001) > 1e-12:
        raise ValueError(f"unexpected F2 counts/mass: {counts}, {mass}")
    return {
        "fluid_counts_by_mkfluid": counts,
        "fluid_particle_count": sum(counts),
        "moving_particle_count": int(moving.attrib["count"]),
        "fluid_particle_mass_kg": mass,
        "reference_initial_sample_mass_target_kg": sum(counts) * mass,
        "continuous_box_volume_m3": 0.325 * 0.22 * 0.264,
        "continuous_box_mass_at_rho0_kg": 1000.0 * 0.325 * 0.22 * 0.264,
        "mass_semantics": "discrete particle sample target and continuous box volume are separate; no rescale",
    }


def motion_stats(path: Path) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        for row in reader:
            if not row or row[0].lstrip().startswith("#"):
                continue
            if len(row) < 2:
                raise ValueError("motion row has fewer than two fields")
            rows.append((float(row[0]), float(row[1])))
    if len(rows) < 3:
        raise ValueError("motion table too short")
    dt = [rows[i + 1][0] - rows[i][0] for i in range(len(rows) - 1)]
    if any(value <= 0 for value in dt):
        raise ValueError("motion times are not strictly increasing")
    speed = [(rows[i + 1][1] - rows[i][1]) / dt[i] for i in range(len(dt))]
    max_deg = max(abs(value) for value in speed)
    return {
        "rows": len(rows),
        "time_start_s": rows[0][0],
        "time_end_s": rows[-1][0],
        "sample_dt_min_s": min(dt),
        "sample_dt_max_s": max(dt),
        "angle_min_deg": min(value for _, value in rows),
        "angle_max_deg": max(value for _, value in rows),
        "max_abs_angular_speed_deg_per_s": max_deg,
        "max_abs_angular_speed_rad_per_s": max_deg * math.pi / 180.0,
        "semantics": "prescribed cup rotation table; no measured fluid field",
    }


def build(xml_path: Path = DEFAULT_XML, motion_path: Path = DEFAULT_MOTION) -> dict[str, Any]:
    xml_record, motion_record = record(xml_path), record(motion_path)
    root = ET.fromstring(xml_path.read_bytes())
    geometry, particle, motion = source_geometry(root), particles(root), motion_stats(motion_path)
    radius = moving_radius(geometry)
    velocity = radius * motion["max_abs_angular_speed_rad_per_s"]
    sample_ke = 0.5 * particle["reference_initial_sample_mass_target_kg"] * velocity * velocity
    continuous_ke = 0.5 * particle["continuous_box_mass_at_rho0_kg"] * velocity * velocity
    gravity_speed = math.sqrt(abs(geometry["gravity_z_m_per_s2"]) * geometry["fluid_union_extent_m"][2])
    return {
        "schema": SCHEMA,
        "status": "SOURCE_BOUND_SCALES_REGISTERED_EVENT_TIME_UNKNOWN",
        "sentinel_id": "F2-S1",
        "family_id": "F2",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "source_inputs": {
            "generated_xml": xml_record,
            "motion_table": motion_record,
            "read_scope": "exact XML geometry/control and motion table only; no BI4/native Part/HDF5",
        },
        "source_geometry": {**geometry, "moving_body_radius_about_axis_m": radius},
        "source_particles": particle,
        "source_control": {"motion_table": motion, "control_window_s": [0.0, geometry["rotation_axis"]["duration_s"]]},
        "reference_scales": {
            "L_position_reference_scalar_m": geometry["L_position_reference_scalar_m"],
            "L_position_reference_definition": "longest exact three-layer fluid union extent; domain and moving-body extents remain diagnostics",
            "angular_speed_scale_rad_per_s": motion["max_abs_angular_speed_rad_per_s"],
            "velocity_scale_m_per_s": velocity,
            "velocity_scale_definition": "maximum prescribed angular speed times maximum moving-body corner radius",
            "sample_mass_kinetic_energy_scale_j": sample_ke,
            "continuous_box_kinetic_energy_scale_j": continuous_ke,
            "gravity_transport_velocity_scale_m_per_s": gravity_speed,
            "mass_semantics": "sample and continuous-box scales are both reported; neither is substituted for the other",
        },
        "event_time": {
            "characteristic_time_s": None,
            "status": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "reason": "source motion declares a 4 s control table but no contact, spill, peak, or other event landmark",
            "motion_table_coverage_s": [motion["time_start_s"], motion["time_end_s"]],
            "cannot_use_control_or_output_duration_as_event_T": True,
            "consumer_requirement": "bind event definition and source evidence before evaluating 1% event-time budget",
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
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }


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
    root = ET.fromstring(
        """<case><constantsdef><gravity z='-9.81'/></constantsdef><geometry><commands>
        <setmkbound mk='0'/><drawbox><point x='0' y='0' z='0'/><size x='.4' y='.2' z='.4'/></drawbox>
        <setmkfluid mk='0'/><drawbox><point x='0' y='0' z='0'/><size x='.3' y='.2' z='.1'/></drawbox>
        <setmkfluid mk='1'/><drawbox><point x='0' y='0' z='.1'/><size x='.3' y='.2' z='.1'/></drawbox>
        <setmkfluid mk='2'/><drawbox><point x='0' y='0' z='.2'/><size x='.3' y='.2' z='.1'/></drawbox>
        </commands></geometry><motion><mvrotfile duration='4'><file name='m.dat'/>
        <axisp1 x='0' y='-1' z='0'/><axisp2 x='0' y='1' z='0'/></mvrotfile>
        <mvrotfile duration='4'><file name='m.dat'/><axisp1 x='0' y='-1' z='0'/><axisp2 x='0' y='1' z='0'/></mvrotfile></motion>
        <particles><fluid begin='0' count='7038'/><fluid begin='7038' count='7038'/><fluid begin='14076' count='7038'/><moving begin='21114' count='2'/></particles>
        <constants><massfluid value='.001'/></constants></case>"""
    )
    geometry = source_geometry(root)
    assert geometry["fluid_union_extent_m"] == [0.3, 0.2, 0.30000000000000004]
    assert math.isclose(moving_radius(geometry), math.sqrt(0.4**2 + 0.4**2))
    assert particles(root)["reference_initial_sample_mass_target_kg"] == 21.114
    with tempfile.TemporaryDirectory(prefix="f2-contract-test-") as tmp:
        path = Path(tmp) / "m.dat"
        path.write_text("#Time;Degrees\n0;0\n1;90\n2;90\n", encoding="utf-8")
        assert motion_stats(path)["max_abs_angular_speed_deg_per_s"] == 90.0
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
