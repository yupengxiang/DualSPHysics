#!/usr/bin/env python3
"""Freeze source-bound comparison scales for F3-S2 before field differences.

Only the exact generated XML and the prescribed acceleration table are read.
The contract deliberately keeps event-time qualification UNKNOWN: the source
has a forcing-table coverage and physical transport scales, but no declared
event landmark.  Native BI4/Part/HDF5 data and solver execution are outside
this script's scope.
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


SCHEMA = "ds02.stage2.f3-s2.observer-calibration-contract.v1"
REPO = Path(__file__).resolve().parents[5]
DEFAULT_XML = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/"
    "F3_STAGE1_FIRST48_PITCH_AY_SOURCE_PREPARATION/"
    "root-stage1-f3-first48-pitch-ay-source-preparation-065-root702-owner-repair1-root704/"
    "prepared/pitch120_ay0750/F3_STAGE1_DP006_P1200_AY0750.xml"
)
DEFAULT_ACCEL = DEFAULT_XML.parent / "CaseSloshingAccData.csv"
DEFAULT_OUTPUT = (
    REPO
    / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f3_s2_observer_calibration_contract_v1.json"
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
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def name(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower()


def float_attr(node: ET.Element, key: str) -> float:
    raw = node.attrib.get(key)
    if raw is None:
        raise ValueError(f"{name(node)} is missing @{key}")
    return float(raw)


def parse_box(node: ET.Element) -> dict[str, Any]:
    point = node.find("point")
    size = node.find("size")
    if point is None or size is None:
        raise ValueError("drawbox lacks point or size")
    p = [float_attr(point, axis) for axis in ("x", "y", "z")]
    s = [float_attr(size, axis) for axis in ("x", "y", "z")]
    return {"point_m": p, "size_m": s, "end_m": [p[i] + s[i] for i in range(3)]}


def source_geometry(root: ET.Element) -> dict[str, Any]:
    active: tuple[str, str] | None = None
    fluid: list[dict[str, Any]] = []
    for node in root.iter():
        node_name = name(node)
        if node_name in {"setmkfluid", "setmkbound"}:
            active = ("fluid" if node_name == "setmkfluid" else "bound", node.attrib.get("mk", ""))
        elif node_name == "drawbox" and active == ("fluid", "0"):
            fluid.append(parse_box(node))
    if len(fluid) != 1:
        raise ValueError(f"expected one F3-S2 fluid drawbox, found {len(fluid)}")
    lo = fluid[0]["point_m"]
    hi = fluid[0]["end_m"]
    extents = [hi[i] - lo[i] for i in range(3)]
    gravity_nodes = [node for node in root.iter() if name(node) == "gravity" and "z" in node.attrib]
    if not gravity_nodes:
        raise ValueError("source XML has no gravity declaration")
    gravity_z = float_attr(gravity_nodes[0], "z")
    acc_input = next((node for node in root.iter() if name(node) == "accinput"), None)
    acc_file = None
    acc_center = None
    if acc_input is not None:
        center = next((node for node in acc_input if name(node) == "acccentre"), None)
        if center is not None:
            acc_center = [float_attr(center, axis) for axis in ("x", "y", "z")]
        times_file = next((node for node in acc_input if name(node) == "acctimesfile"), None)
        if times_file is not None:
            acc_file = times_file.attrib.get("value")
    return {
        "fluid_drawbox": fluid[0],
        "fluid_union_bounds_m": {"min": lo, "max": hi},
        "fluid_extent_m": extents,
        "L_position_reference_scalar_m": max(extents),
        "gravity_z_m_per_s2": gravity_z,
        "acceleration_center_m": acc_center,
        "acceleration_file_declared_in_xml": acc_file,
    }


def particle_and_mass(root: ET.Element) -> dict[str, Any]:
    fluid_count = 0
    for node in root.iter():
        if name(node) == "fluid" and node.attrib.get("mkfluid") == "0" and "begin" in node.attrib:
            fluid_count += int(node.attrib["count"])
    mass_nodes = [node for node in root.iter() if name(node) == "massfluid" and "value" in node.attrib]
    if len(mass_nodes) != 1:
        raise ValueError(f"expected one massfluid constant, found {len(mass_nodes)}")
    masspart = float_attr(mass_nodes[0], "value")
    if fluid_count != 67500 or abs(masspart - 0.000216) > 1e-15:
        raise ValueError(f"unexpected F3-S2 fluid count/mass: {fluid_count}, {masspart}")
    return {
        "fluid_particle_count": fluid_count,
        "particle_mass_kg": masspart,
        "fluid_sample_mass_kg": fluid_count * masspart,
    }


def acceleration_stats(path: Path) -> dict[str, Any]:
    times: list[float] = []
    minimum = [math.inf] * 6
    maximum = [-math.inf] * 6
    integral_signed = [0.0] * 6
    integral_abs = [0.0] * 6
    rows = 0
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        if header[:4] != ["#Time", "LinearAccX", "LinearAccY", "LinearAccZ"]:
            raise ValueError(f"unexpected acceleration header: {header}")
        previous: list[float] | None = None
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            values = [float(item) for item in row[:7]]
            t = values[0]
            if previous is not None:
                dt = t - previous[0]
                if dt <= 0:
                    raise ValueError("acceleration times are not strictly increasing")
                # Trapezoidal control-table integral; this is a prescribed
                # acceleration scale, not a claim about the simulated field.
                for i in range(6):
                    integral_signed[i] += 0.5 * (previous[i + 1] + values[i + 1]) * dt
                    integral_abs[i] += 0.5 * (abs(previous[i + 1]) + abs(values[i + 1])) * dt
            times.append(t)
            for i, value in enumerate(values[1:]):
                minimum[i] = min(minimum[i], value)
                maximum[i] = max(maximum[i], value)
            previous = values
            rows += 1
    if rows < 3 or previous is None:
        raise ValueError("acceleration table has too few rows")
    steps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    return {
        "header": header,
        "rows": rows,
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "sample_dt_min_s": min(steps),
        "sample_dt_max_s": max(steps),
        "component_order": header[1:7],
        "component_min": minimum,
        "component_max": maximum,
        "integral_signed_velocity_proxy_m_per_s_or_rad_per_s": integral_signed,
        "integral_abs_velocity_proxy_m_per_s_or_rad_per_s": integral_abs,
        "semantics": "prescribed forcing-table statistics; initial field velocity is not inferred",
    }


def build(xml_path: Path = DEFAULT_XML, acceleration_path: Path = DEFAULT_ACCEL) -> dict[str, Any]:
    xml_record = record(xml_path)
    acceleration_record = record(acceleration_path)
    root = ET.fromstring(xml_path.read_bytes())
    geometry = source_geometry(root)
    particles = particle_and_mass(root)
    forcing = acceleration_stats(acceleration_path)
    gravity_speed = math.sqrt(abs(geometry["gravity_z_m_per_s2"]) * geometry["fluid_extent_m"][2])
    transport_time = geometry["fluid_extent_m"][0] / gravity_speed
    ke_scale = 0.5 * particles["fluid_sample_mass_kg"] * gravity_speed * gravity_speed
    return {
        "schema": SCHEMA,
        "status": "SOURCE_BOUND_SCALES_REGISTERED_EVENT_TIME_UNKNOWN",
        "sentinel_id": "F3-S2",
        "family_id": "F3",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "source_inputs": {
            "generated_xml": xml_record,
            "acceleration_table": acceleration_record,
            "read_scope": "XML geometry/control and exact acceleration CSV only; no BI4/native Part/HDF5",
        },
        "source_geometry": geometry,
        "source_particles": particles,
        "source_forcing": forcing,
        "reference_scales": {
            "velocity_scale_m_per_s": gravity_speed,
            "velocity_scale_definition": "sqrt(abs(source gravity_z) * declared fluid depth); nonzero source-bound transport reference",
            "kinetic_energy_scale_j": ke_scale,
            "kinetic_energy_scale_definition": "0.5 * exact source fluid sample mass * gravity transport speed^2",
            "transport_time_scale_s": transport_time,
            "transport_time_definition": "declared fluid streamwise extent / gravity transport speed; candidate source timescale, not event T",
            "forcing_integral_proxy_is_not_field_velocity": True,
        },
        "event_time": {
            "characteristic_time_s": None,
            "status": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "reason": "source provides acceleration-table coverage but no contact, peak, run-up, or other event landmark",
            "control_table_coverage_s": [forcing["time_start_s"], forcing["time_end_s"]],
            "cannot_use_control_duration_as_event_T": True,
            "consumer_requirement": "bind an event definition and source evidence before evaluating 1% event-time budget",
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
    with tempfile.TemporaryDirectory(prefix="f3-contract-test-") as tmp:
        root = ET.fromstring(
            """<case><constantsdef><gravity z='-9.81'/></constantsdef><geometry><commands>
            <setmkfluid mk='0'/><drawbox><point x='0' y='0' z='0'/><size x='2' y='1' z='.5'/></drawbox>
            </commands></geometry><execution><special><accinputs><accinput mkfluid='0'>
            <acccentre x='0' y='0' z='0'/><acctimesfile value='a.csv'/></accinput></accinputs></special>
            <particles><fluid mkfluid='0' begin='0' count='67500'/></particles>
            <constants><massfluid value='.000216'/></constants></execution></case>"""
        )
        geometry = source_geometry(root)
        assert geometry["L_position_reference_scalar_m"] == 2.0
        path = Path(tmp) / "a.csv"
        path.write_text(
            "#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ\n"
            "0;0;0;-9.81;0;0;0\n1;1;0;-9.81;0;2;0\n2;0;0;-9.81;0;0;0\n",
            encoding="utf-8",
        )
        stats = acceleration_stats(path)
        assert stats["rows"] == 3 and stats["time_end_s"] == 2.0
        assert stats["component_max"][0] == 1.0
    print(json.dumps({"status": "SELF_TEST_PASS", "schema": SCHEMA}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--xml", type=Path, default=DEFAULT_XML)
    parser.add_argument("--acceleration", type=Path, default=DEFAULT_ACCEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.build:
        parser.error("use --build or --self-test")
    value = build(args.xml, args.acceleration)
    atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output), "schema": SCHEMA}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
