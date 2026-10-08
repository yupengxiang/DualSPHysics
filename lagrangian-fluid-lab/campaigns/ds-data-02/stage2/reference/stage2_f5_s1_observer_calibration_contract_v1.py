#!/usr/bin/env python3
"""Register source-bound scales for the F5-S1 run-up observer.

The exact generated XML and its prescribed piston table are small control
inputs.  This contract does not read BI4/native Part/HDF5 data and does not
start a solver.  Motion-table duration, XML TimeMax, and a later actual CLI
terminal time remain separate fields; none is silently promoted to event T.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f5-s1.observer-calibration-contract.v1"
REPO = Path(__file__).resolve().parents[5]
DEFAULT_XML = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-genuine-gencase-118-root640/prepared/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1.xml"
)
DEFAULT_MOTION = DEFAULT_XML.parent / "assets/f5_c082s1_motion_m095_t090.dat"
DEFAULT_OUTPUT = (
    REPO
    / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f5_s1_observer_calibration_contract_v1.json"
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
    fluid_boxes: list[dict[str, Any]] = []
    tank_boxes: list[dict[str, Any]] = []
    active_fluid = False
    for node in root.iter():
        node_tag = tag(node)
        if node_tag == "setmkfluid":
            active_fluid = node.attrib.get("mk") == "0"
        elif node_tag == "setmkbound":
            active_fluid = False
        elif node_tag == "drawbox":
            parsed = box(node)
            if active_fluid:
                fluid_boxes.append(parsed)
            if "tank_floor" in str(parsed.get("comment", "")):
                tank_boxes.append(parsed)
    selected = [item for item in fluid_boxes if "initial_fluid" in str(item.get("comment", ""))]
    if len(selected) != 1:
        raise ValueError(f"expected one explicitly labelled initial fluid box, found {len(selected)}")
    fluid = selected[0]
    domain = next((node for node in root.iter() if tag(node) == "definition"), None)
    tank_floor = tank_boxes[0] if len(tank_boxes) == 1 else None
    if domain is None or tank_floor is None:
        raise ValueError("source domain/tank floor declaration missing")
    pointmin = domain.find("pointmin")
    pointmax = domain.find("pointmax")
    if pointmin is None or pointmax is None:
        raise ValueError("source definition bounds missing")
    domain_bounds = {
        "min": [fattr(pointmin, axis) for axis in ("x", "y", "z")],
        "max": [fattr(pointmax, axis) for axis in ("x", "y", "z")],
    }
    gravity = next((node for node in root.iter() if tag(node) == "gravity" and "z" in node.attrib), None)
    if gravity is None:
        raise ValueError("source gravity missing")
    return {
        "initial_fluid_box": fluid,
        "initial_fluid_extent_m": fluid["size_m"],
        "tank_floor_box": tank_floor,
        "tank_longitudinal_extent_m": tank_floor["size_m"][0],
        "definition_bounds_m": domain_bounds,
        "gravity_z_m_per_s2": fattr(gravity, "z"),
    }


def scalar(root: ET.Element, element_name: str, attribute: str) -> float:
    values = [fattr(node, attribute) for node in root.iter() if tag(node) == element_name and attribute in node.attrib]
    if not values or max(values) - min(values) > 1e-10:
        raise ValueError(f"missing/conflicting {element_name}@{attribute}: {values}")
    return values[0]


def particles(root: ET.Element) -> dict[str, Any]:
    fluid = next((node for node in root.iter() if tag(node) == "fluid" and "begin" in node.attrib), None)
    moving = next((node for node in root.iter() if tag(node) == "moving" and "begin" in node.attrib), None)
    if fluid is None or moving is None:
        raise ValueError("actual fluid/moving blocks missing")
    fluid_count, moving_count = int(fluid.attrib["count"]), int(moving.attrib["count"])
    massfluid = scalar(root, "massfluid", "value")
    massbound = scalar(root, "massbound", "value")
    if fluid_count != 31658 or abs(massfluid - 0.008) > 1e-12:
        raise ValueError(f"unexpected F5 fluid count/mass: {fluid_count}, {massfluid}")
    return {
        "fluid_particle_count": fluid_count,
        "moving_particle_count": moving_count,
        "fluid_particle_mass_kg": massfluid,
        "moving_particle_mass_kg_diagnostic": massbound,
        "fluid_sample_mass_kg": fluid_count * massfluid,
        "moving_sample_mass_kg_diagnostic": moving_count * massbound,
    }


def controls(root: ET.Element) -> dict[str, Any]:
    files = [node for node in root.iter() if tag(node) == "file" and node.attrib.get("name")]
    motion_files = [node.attrib["name"] for node in files if "motion" in node.attrib["name"]]
    if motion_files != ["assets/f5_c082s1_motion_m095_t090.dat"] * 2:
        raise ValueError(f"unexpected F5 motion file references: {motion_files}")
    durations = [float(node.attrib["duration"]) for node in root.iter() if tag(node) in {"mvpredef", "mvrectfile"}]
    if sorted(set(durations)) != [14.4]:
        raise ValueError(f"unexpected F5 motion duration declarations: {durations}")
    time_max = scalar(root, "parameter", "value") if False else None
    values = [float(node.attrib["value"]) for node in root.iter() if tag(node) == "parameter" and node.attrib.get("key") == "TimeMax"]
    if values != [26.0]:
        raise ValueError(f"unexpected XML TimeMax values: {values}")
    return {
        "motion_file_names": motion_files,
        "motion_duration_s": 14.4,
        "xml_timemax_s": 26.0,
        "actual_solver_tmax_is_not_inferred_here": True,
    }


def motion_stats(path: Path) -> dict[str, Any]:
    rows: list[tuple[float, float]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.replace(",", " ").split()
        if len(fields) < 2:
            raise ValueError(f"motion line {line_number} has fewer than two columns")
        rows.append((float(fields[0]), float(fields[1])))
    if len(rows) < 3:
        raise ValueError("motion table too short")
    dt = [rows[i + 1][0] - rows[i][0] for i in range(len(rows) - 1)]
    if any(value <= 0 for value in dt):
        raise ValueError("motion times are not increasing")
    velocity = [(rows[i + 1][1] - rows[i][1]) / dt[i] for i in range(len(dt))]
    return {
        "rows": len(rows),
        "time_start_s": rows[0][0],
        "time_end_s": rows[-1][0],
        "sample_dt_min_s": min(dt),
        "sample_dt_max_s": max(dt),
        "position_min_m": min(value for _, value in rows),
        "position_max_m": max(value for _, value in rows),
        "max_abs_prescribed_piston_speed_m_per_s": max(abs(value) for value in velocity),
        "semantics": "prescribed piston position table; this is control kinematics, not a measured fluid field",
    }


def build(xml_path: Path = DEFAULT_XML, motion_path: Path = DEFAULT_MOTION) -> dict[str, Any]:
    xml_record, motion_record = record(xml_path), record(motion_path)
    root = ET.fromstring(xml_path.read_bytes())
    geometry, particle, source_controls = source_geometry(root), particles(root), controls(root)
    motion = motion_stats(motion_path)
    depth = geometry["initial_fluid_extent_m"][2]
    gravity_speed = math.sqrt(abs(geometry["gravity_z_m_per_s2"]) * depth)
    fluid_ke = 0.5 * particle["fluid_sample_mass_kg"] * motion["max_abs_prescribed_piston_speed_m_per_s"] ** 2
    transport = geometry["initial_fluid_extent_m"][0] / gravity_speed
    return {
        "schema": SCHEMA,
        "status": "SOURCE_BOUND_SCALES_REGISTERED_EVENT_TIME_UNKNOWN",
        "sentinel_id": "F5-S1",
        "family_id": "F5",
        "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        "source_inputs": {
            "generated_xml": xml_record,
            "motion_table": motion_record,
            "read_scope": "exact XML geometry/control and prescribed motion table only; no BI4/native Part/HDF5",
        },
        "source_geometry": geometry,
        "source_particles": particle,
        "source_control": {**source_controls, "motion_table": motion},
        "reference_scales": {
            "L_position_reference_scalar_m": geometry["tank_longitudinal_extent_m"],
            "L_position_reference_definition": "existing tank floor longitudinal extent; initial-fluid extent retained separately",
            "velocity_scale_m_per_s": motion["max_abs_prescribed_piston_speed_m_per_s"],
            "velocity_scale_definition": "maximum finite-difference speed from exact prescribed piston table",
            "fluid_kinetic_energy_scale_j": fluid_ke,
            "fluid_kinetic_energy_scale_definition": "0.5 * exact fluid sample mass * prescribed piston speed scale^2; reference denominator only",
            "gravity_transport_velocity_scale_m_per_s": gravity_speed,
            "gravity_transport_time_scale_s": transport,
            "motion_duration_is_not_event_T": True,
        },
        "event_time": {
            "characteristic_time_s": None,
            "status": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "reason": "motion table has prescribed coverage only; source does not label first run-up/contact/peak event",
            "motion_table_coverage_s": [motion["time_start_s"], motion["time_end_s"]],
            "xml_timemax_s": source_controls["xml_timemax_s"],
            "cannot_use_motion_or_output_duration_as_event_T": True,
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
        """<case><constantsdef><gravity z='-9.81'/></constantsdef><geometry><definition>
        <pointmin x='0' y='0' z='0'/><pointmax x='5' y='1' z='1'/></definition><commands>
        <setmkfluid mk='0'/><drawbox cmt='initial_fluid'><point x='0' y='0' z='0'/><size x='3' y='1' z='.5'/></drawbox>
        <setmkbound mk='0'/><drawbox cmt='tank_floor'><point x='0' y='0' z='0'/><size x='5' y='1' z='.1'/></drawbox>
        </commands></geometry><motion><mvpredef duration='14.4'><file name='assets/f5_c082s1_motion_m095_t090.dat'/></mvpredef>
        <mvrectfile duration='14.4'><file name='assets/f5_c082s1_motion_m095_t090.dat'/></mvrectfile></motion>
        <execution><parameters><parameter key='TimeMax' value='26'/></parameters><particles>
        <fluid begin='0' count='31658'/><moving begin='1' count='4210'/></particles>
        <constants><massfluid value='.008'/><massbound value='.008'/></constants></execution></case>"""
    )
    geometry = source_geometry(root)
    assert geometry["tank_longitudinal_extent_m"] == 5.0
    assert particles(root)["fluid_sample_mass_kg"] == 253.264
    assert controls(root)["motion_duration_s"] == 14.4
    with tempfile.TemporaryDirectory(prefix="f5-contract-test-") as tmp:
        path = Path(tmp) / "motion.dat"
        path.write_text("0 0\n1 .1\n2 0\n", encoding="utf-8")
        assert motion_stats(path)["max_abs_prescribed_piston_speed_m_per_s"] == 0.1
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
