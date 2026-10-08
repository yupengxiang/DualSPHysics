#!/usr/bin/env python3
"""Register F6-S2 source scales before rigid/fluid observer differences.

The exact generated XML is the only input.  This forward contract separates
fluid particle sample mass from physical floating-body mass and inertia.  It
does not read BI4/native Part/HDF5 data or run a solver.
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


SCHEMA = "ds02.stage2.f6-s2.observer-calibration-contract.v1"
REPO = Path(__file__).resolve().parents[5]
DEFAULT_XML = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/"
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025/"
    "root-stage1-f6-2p0-genuine-gencase-073/"
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025.xml"
)
DEFAULT_OUTPUT = (
    REPO
    / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f6_s2_observer_calibration_contract_v1.json"
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
    return {"point_m": p, "size_m": s, "end_m": [p[i] + s[i] for i in range(3)]}


def source_geometry(root: ET.Element) -> dict[str, Any]:
    active: tuple[str, str] | None = None
    fluid: list[dict[str, Any]] = []
    floating: list[dict[str, Any]] = []
    for node in root.iter():
        node_tag = tag(node)
        if node_tag in {"setmkfluid", "setmkbound"}:
            active = ("fluid" if node_tag == "setmkfluid" else "bound", node.attrib.get("mk", ""))
        elif node_tag == "drawbox" and active == ("fluid", "0"):
            fluid.append(box(node))
        elif node_tag == "drawbox" and active == ("bound", "50"):
            floating.append(box(node))
    if len(fluid) != 1 or len(floating) != 1:
        raise ValueError(f"expected one fluid and one floating box, found {len(fluid)}, {len(floating)}")
    lo, hi = fluid[0]["point_m"], fluid[0]["end_m"]
    extent = [hi[i] - lo[i] for i in range(3)]
    gravity_nodes = [node for node in root.iter() if tag(node) == "gravity" and "z" in node.attrib]
    if not gravity_nodes:
        raise ValueError("gravity declaration missing")
    return {
        "fluid_box": fluid[0],
        "fluid_extent_m": extent,
        "fluid_bounds_m": {"min": lo, "max": hi},
        "L_position_reference_scalar_m": max(extent),
        "floating_box": floating[0],
        "gravity_z_m_per_s2": fattr(gravity_nodes[0], "z"),
    }


def scalar(root: ET.Element, element_name: str, attribute: str) -> float:
    values = [fattr(node, attribute) for node in root.iter() if tag(node) == element_name and attribute in node.attrib]
    if not values or max(values) - min(values) > 1e-10:
        raise ValueError(f"missing/conflicting {element_name}@{attribute}: {values}")
    return values[0]


def vector(root: ET.Element, element_name: str, axes: tuple[str, str, str]) -> list[float]:
    values = [node for node in root.iter() if tag(node) == element_name and all(axis in node.attrib for axis in axes)]
    if not values:
        raise ValueError(f"missing {element_name} vector")
    return [fattr(values[0], axis) for axis in axes]


def particles(root: ET.Element) -> dict[str, Any]:
    fluid = next((node for node in root.iter() if tag(node) == "fluid" and "begin" in node.attrib), None)
    floating = next((node for node in root.iter() if tag(node) == "floating" and "begin" in node.attrib), None)
    if fluid is None or floating is None:
        raise ValueError("actual fluid/floating particle blocks missing")
    fluid_count, floating_count = int(fluid.attrib["count"]), int(floating.attrib["count"])
    if (fluid_count, floating_count) != (327680, 16384):
        raise ValueError(f"unexpected F6 counts: {fluid_count}, {floating_count}")
    massfluid = scalar(root, "massfluid", "value")
    masspart = scalar(root, "masspart", "value")
    return {
        "fluid_particle_count": fluid_count,
        "floating_sample_particle_count": floating_count,
        "fluid_particle_mass_kg": massfluid,
        "floating_sample_particle_mass_kg": masspart,
        "fluid_sample_mass_kg": fluid_count * massfluid,
        "floating_sample_mass_kg_diagnostic": floating_count * masspart,
    }


def body(root: ET.Element) -> dict[str, Any]:
    massbody = scalar(root, "massbody", "value")
    center = vector(root, "center", ("x", "y", "z"))
    inertia = vector(root, "inertia", ("x", "y", "z"))
    omega = vector(root, "angularvelini", ("x", "y", "z"))
    omega_mag = math.sqrt(sum(value * value for value in omega))
    return {
        "physical_massbody_kg": massbody,
        "physical_center_m": center,
        "physical_inertia_kg_m2": inertia,
        "initial_angular_velocity_rad_per_s": omega,
        "initial_angular_speed_rad_per_s": omega_mag,
        "rigid_body_mass_is_not_floating_sample_mass": True,
    }


def build(xml_path: Path = DEFAULT_XML) -> dict[str, Any]:
    xml_record = record(xml_path)
    root = ET.fromstring(xml_path.read_bytes())
    geometry = source_geometry(root)
    particle = particles(root)
    rigid = body(root)
    depth = geometry["fluid_extent_m"][2]
    gravity_speed = math.sqrt(abs(geometry["gravity_z_m_per_s2"]) * depth)
    transport_time = geometry["fluid_extent_m"][0] / gravity_speed
    body_box = geometry["floating_box"]
    half = [0.5 * value for value in body_box["size_m"]]
    body_radius = math.sqrt(sum(value * value for value in half))
    body_surface_speed = rigid["initial_angular_speed_rad_per_s"] * body_radius
    rigid_ke = 0.5 * sum(rigid["physical_inertia_kg_m2"][i] * rigid["initial_angular_velocity_rad_per_s"][i] ** 2 for i in range(3))
    fluid_ke = 0.5 * particle["fluid_sample_mass_kg"] * gravity_speed * gravity_speed
    return {
        "schema": SCHEMA,
        "status": "SOURCE_BOUND_SCALES_REGISTERED_EVENT_TIME_UNKNOWN",
        "sentinel_id": "F6-S2",
        "family_id": "F6",
        "physical_case_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
        "source_inputs": {
            "generated_xml": xml_record,
            "read_scope": "exact XML geometry, floating body, constants and initial angular release; no BI4/native Part/HDF5",
        },
        "source_geometry": geometry,
        "source_particles": particle,
        "rigid_body": rigid,
        "reference_scales": {
            "fluid_gravity_velocity_scale_m_per_s": gravity_speed,
            "rigid_body_surface_velocity_scale_m_per_s": body_surface_speed,
            "rigid_body_angular_velocity_scale_rad_per_s": rigid["initial_angular_speed_rad_per_s"],
            "fluid_gravity_kinetic_energy_scale_j": fluid_ke,
            "rigid_body_rotational_kinetic_energy_scale_j": rigid_ke,
            "transport_time_scale_s": transport_time,
            "transport_time_definition": "fluid longest extent / gravity velocity; candidate timescale, not event T",
            "mass_semantics": "fluid sample and rigid physical body scales remain separate; no mass substitution",
        },
        "event_time": {
            "characteristic_time_s": None,
            "status": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
            "reason": "initial angular release declares no contact, peak, run-up, or other event landmark",
            "cannot_use_solver_output_duration_as_event_T": True,
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
        <setmkfluid mk='0'/><drawbox><point x='0' y='0' z='0'/><size x='2' y='1' z='.5'/></drawbox>
        <setmkbound mk='50'/><drawbox><point x='0' y='0' z='0'/><size x='1' y='1' z='1'/></drawbox>
        </commands></geometry><particles><floating begin='0' count='16384'/>
        <fluid begin='1' count='327680'/></particles><constants>
        <massfluid value='.015625'/><massbound value='.015625'/><masspart value='.015625'/></constants>
        <floatings><floating><massbody value='128'/><center x='0' y='0' z='0'/>
        <inertia x='1' y='2' z='3'/><angularvelini x='.1' y='.2' z='.3'/></floating></floatings></case>"""
    )
    geometry = source_geometry(root)
    assert geometry["L_position_reference_scalar_m"] == 2.0
    assert particles(root)["fluid_sample_mass_kg"] == 5120.0
    assert math.isclose(body(root)["initial_angular_speed_rad_per_s"], math.sqrt(0.14))
    print(json.dumps({"status": "SELF_TEST_PASS", "schema": SCHEMA}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--xml", type=Path, default=DEFAULT_XML)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.build:
        parser.error("use --build or --self-test")
    value = build(args.xml)
    atomic_json(args.output, value)
    print(json.dumps({"status": value["status"], "output": str(args.output), "schema": SCHEMA}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
