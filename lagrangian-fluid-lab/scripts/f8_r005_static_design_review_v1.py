#!/usr/bin/env python3
"""Freeze a new F8 r005 design correcting r004's missing normals and top wall.

This review renders a new Definition and control table in memory.  It does not
materialize inputs or execute GenCase, a decoder, solver, GPU, queue, or worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts import f8_r004_static_design_review_v2 as r004


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r005")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R005"
SCHEMA = "core.cfd.f8.r005_static_design_review.v1"
OUTPUT = LAB / ROOT / "static-design-review-v1/receipt.json"
DEFINITION_TARGET = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R005_Def.xml"
CONTROL_TARGET = ROOT / "input/F8_OPC_q0p500_r005_acceleration.csv"
PREFLIGHT_ROOT = ROOT / "cpu-native-preflight-v1"
GENERATED_PREFIX = PREFLIGHT_ROOT / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R005"
COPIED_CONTROL = PREFLIGHT_ROOT / "generated/F8_OPC_q0p500_r005_acceleration.csv"

R004_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r004")
R004_REVIEW = R004_ROOT / "static-design-review-v2/receipt.json"
R004_RECEIPT = R004_ROOT / "cpu-native-preflight-v1/receipt.json"
R004_DEFINITION = R004_ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R004_Def.xml"
R004_LOG = R004_ROOT / "cpu-native-preflight-v1/gencase.stdout.log"
R004_BOUND_VTK = R004_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R004_Bound.vtk"
R004_NATIVE_XML = R004_ROOT / "cpu-native-preflight-v1/native-initial.xml"
R004_CONTROL = R004_ROOT / "input/F8_OPC_q0p500_r004_acceleration.csv"

CANONICAL_DEFINITION = Path("diagnostics/r3_f6_canonical_geometry/definitions/canonical_rectangular_Def.xml")
CANONICAL_LOG = Path("diagnostics/r3_f6_canonical_geometry/evidence/rectangular/gencase.log")
CANONICAL_BOUND_VTK = Path("diagnostics/r3_f6_canonical_geometry/evidence/rectangular/generated/canonical_rectangular_Bound.vtk")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": str(relative), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load_json(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def parameters() -> dict[str, float | int]:
    return r004.parameters()


def control_filename() -> str:
    return "F8_OPC_q0p500_r005_acceleration.csv"


def _wall_box(values: dict[str, float | int], indent: str = "          ") -> str:
    h, dp = float(values["half_height"]), float(values["dp"])
    return (
        f'{indent}<drawbox><boxfill>top|bottom</boxfill>\n'
        f'{indent}  <point x="0" y="0" z="{-h - dp:.17g}" />\n'
        f'{indent}  <size x="{float(values["length_x"]):.17g}" '
        f'y="{float(values["length_y"]):.17g}" z="{2.0 * (h + dp):.17g}" />\n'
        f'{indent}</drawbox>'
    )


def definition_xml(values: dict[str, float | int]) -> str:
    """Render r005 with a covered top-wall lattice and native normals request."""
    rendered = r004.definition_xml(values)
    replacements = {
        "Proposed F8 r004 static input": "Proposed F8 r005 static input",
        r004.v1.control_filename(): control_filename(),
    }
    for old, new in replacements.items():
        if rendered.count(old) != 1:
            raise ValueError(f"r004 renderer no longer has exactly one r005 repair target: {old}")
        rendered = rendered.replace(old, new)

    h, dp = float(values["half_height"]), float(values["dp"])
    length_x, length_y = float(values["length_x"]), float(values["length_y"])
    old_max = (
        f'<pointmax x="{length_x:.17g}" y="{length_y:.17g}" '
        f'z="{h + dp:.17g}" />'
    )
    new_max = (
        f'<pointmax x="{length_x:.17g}" y="{length_y:.17g}" '
        f'z="{h + 2.0 * dp:.17g}" />'
    )
    if rendered.count(old_max) != 1:
        raise ValueError("r004 renderer no longer has exactly one upper domain bound to extend")
    rendered = rendered.replace(old_max, new_max)

    command_open = "<commands><mainlist>"
    normal_commands = f'''<commands>
      <list name="GeometryForNormals">
        <setactive drawpoints="0" drawshapes="1" />
        <setshapemode>actual | bound</setshapemode>
        <setnormalinvert invert="true" />
        <setmkbound mk="0" name="FiniteNoSlipZWalls" />
{_wall_box(values)}
        <shapeout file="hdp" />
        <resetdraw />
      </list>
      <mainlist>
        <runlist name="GeometryForNormals" />'''
    if rendered.count(command_open) != 1:
        raise ValueError("r004 renderer no longer has one Geometry command entry point")
    rendered = rendered.replace(command_open, normal_commands)

    command_close = "      </mainlist></commands>\n    </geometry>"
    normal_config = '''      </mainlist>
      </commands>
    </geometry>
    <normals active="true">
        <norgeometry>
          <geometryfile file="[CaseName]_hdp_Actual.vtk" />
          <distanceh v="3.0" />
          <svshapes v="true" />
        </norgeometry>
    </normals>'''
    if rendered.count(command_close) != 1:
        raise ValueError("r004 renderer no longer has one geometry command close")
    rendered = rendered.replace(command_close, normal_config)
    ET.fromstring(rendered)
    return rendered


def acceleration_csv(values: dict[str, float | int]) -> str:
    return r004.acceleration_csv(values)


def vtk_binary_points(path: Path) -> list[tuple[float, float, float]]:
    raw = path.read_bytes()
    match = re.search(rb"(?m)^POINTS\s+(\d+)\s+(float|double)\s*$", raw)
    if not match:
        raise ValueError(f"VTK POINTS header missing: {path}")
    count = int(match.group(1))
    width = 4 if match.group(2) == b"float" else 8
    offset = raw.find(b"\n", match.start()) + 1
    size = count * 3 * width
    if offset <= 0 or len(raw) < offset + size:
        raise ValueError(f"VTK POINTS payload truncated: {path}")
    code = ">f" if width == 4 else ">d"
    values = struct.unpack(f">{count * 3}{code[1:]}", raw[offset:offset + size])
    return [tuple(values[index:index + 3]) for index in range(0, len(values), 3)]


def vtk_z_planes(path: Path, precision: int = 7) -> tuple[int, list[float]]:
    points = vtk_binary_points(path)
    planes = sorted({round(point[2], precision) for point in points})
    return len(points), planes


def require(gaps: list[dict[str, str]], code: str, condition: bool, detail: str) -> None:
    if not condition:
        gaps.append({"code": code, "detail": detail})


def evaluate_design(values: dict[str, float | int]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    receipt = load_json(R004_RECEIPT)
    review = load_json(R004_REVIEW)
    r004_xml = ET.parse(LAB / R004_DEFINITION).getroot()
    native_xml = ET.parse(LAB / R004_NATIVE_XML).getroot()
    log = (LAB / R004_LOG).read_text(encoding="utf-8")
    r004_bound_count, r004_planes = vtk_z_planes(LAB / R004_BOUND_VTK)
    canonical = ET.parse(LAB / CANONICAL_DEFINITION).getroot()
    canonical_log = (LAB / CANONICAL_LOG).read_text(encoding="utf-8")
    definition, control = definition_xml(values), acceleration_csv(values)
    root = ET.fromstring(definition)

    require(gaps, "R004_CLOSED_NATIVE_HARD_FAILURE",
            receipt.get("schema") == "core.cfd.f8.r004_cpu_native_preflight.v1"
            and receipt.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R004"
            and receipt.get("status") == "cpu_native_preflight_failed_hard_audit"
            and receipt.get("pass") is False and receipt.get("qualification_credit") == 0,
            "r004 must remain an immutable closed zero-credit native hard failure")
    r004_checks = receipt.get("checks", {})
    require(gaps, "R004_NORMAL_FAILURE_ROOT_CAUSE_EVIDENCE",
            r004_checks.get("native_boundary_normal_count_positive") is False
            and r004_checks.get("native_boundary_normals_finite_and_nonzero") is False
            and receipt.get("native", {}).get("boundary_normals") is None
            and not native_xml.findall(".//*[@name='BoundNor']")
            and r004_xml.find("./casedef/normals") is None
            and r004_xml.find("./casedef/geometry/commands/list[@name='GeometryForNormals']") is None
            and "Computing normals" not in log,
            "r004 did not request or emit native boundary-normal data")
    require(gaps, "R004_UPPER_WALL_OMISSION_EVIDENCE",
            r004_checks.get("generated_z_wall_planes_present") is False
            and r004_bound_count == 512 and r004_planes == [-0.0525],
            "r004 Bound.vtk must be bound to the observed single lower-wall plane")
    require(gaps, "R004_POSITIVE_CONTROLS_RETAINED",
            review.get("status") == "r004_static_design_review_v2_passed_inputs_not_authorized"
            and receipt.get("input_constantsdef", {}).get("pass") is True
            and receipt.get("generated_colocated_control_copy", {}).get("hash_matches") is True
            and receipt.get("checks", {}).get("native_arrays_finite") is True,
            "r005 must inherit only the verified r004 constants/control/array positive controls")
    prior = review.get("closed_prior_execution_scopes", [])
    prior_ids = {item.get("scope_id") for item in prior}
    require(gaps, "R001_R004_SCOPES_RETAINED_CLOSED",
            prior_ids == {
                "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
                "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002",
                "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003",
            } and "same-input retry" in receipt.get("failure_policy", ""),
            "all prior one-shot F8 execution scopes remain closed")
    require(gaps, "CANONICAL_NORMALS_PRECEDENT",
            canonical.find("./casedef/normals[@active='true']") is not None
            and canonical.find("./casedef/geometry/commands/list[@name='GeometryForNormals']") is not None
            and "Non-zero particle normals: 1,476/1,476" in canonical_log,
            "existing successful canonical geometry precedent must demonstrate requested normal construction")
    require(gaps, "FRESH_R005_REVIEW_SCOPE",
            SCOPE == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R005"
            and "r001" not in str(ROOT) and "r002" not in str(ROOT)
            and "r003" not in str(ROOT) and "r004" not in str(ROOT),
            "r005 must use a distinct scope and output namespace")

    constants = {node.tag: dict(node.attrib) for node in root.findall("./casedef/constantsdef/*")}
    expected_constants = {
        "gravity": {"x": "0", "y": "0", "z": "0"}, "rhop0": {"value": "1000"},
        "rhopgradient": {"value": "1"}, "hswl": {"value": "0", "auto": "true"},
        "gamma": {"value": "7"}, "speedsystem": {"value": "0", "auto": "true"},
        "coefsound": {"value": "1"}, "speedsound": {"value": "10", "auto": "false"},
        "coefh": {"value": "1.0"}, "cflnumber": {"value": "0.2"},
    }
    require(gaps, "R004_PHYSICS_AND_CONSTANTS_PRESERVED",
            values == r004.parameters()
            and all(all(constants.get(name, {}).get(key) == expected for key, expected in attrs.items())
                    for name, attrs in expected_constants.items()),
            "r005 must preserve the successful r004 constants and registered q=0.5 physics/control values")
    geometry = root.find("./casedef/geometry")
    point_min = geometry.find("./definition/pointmin") if geometry is not None else None
    point_max = geometry.find("./definition/pointmax") if geometry is not None else None
    wall_box_nodes = root.findall("./casedef/geometry/commands/list[@name='GeometryForNormals']/drawbox")
    main_wall_nodes = root.findall("./casedef/geometry/commands/mainlist/drawbox")
    fluid_box = root.find("./casedef/geometry/commands/mainlist/drawbox[2]")
    h, dp = float(values["half_height"]), float(values["dp"])
    wall_min, wall_size = -h - dp, 2.0 * (h + dp)
    wall_contract = lambda node: (
        node is not None and node.findtext("./boxfill") == "top|bottom"
        and float(node.find("./point").get("z")) == wall_min
        and float(node.find("./size").get("z")) == wall_size
    )
    require(gaps, "BOTH_FINITE_WALL_PLANES_ON_INCLUDED_LATTICE",
            point_min is not None and point_max is not None
            and float(point_min.get("z")) == wall_min
            and float(point_max.get("z")) == h + 2.0 * dp
            and (h + dp - wall_min) / dp == round((h + dp - wall_min) / dp)
            and float(point_max.get("z")) >= h
            and len(wall_box_nodes) == 1 and wall_contract(wall_box_nodes[0])
            and len(main_wall_nodes) == 2 and wall_contract(main_wall_nodes[0]),
            "the top wall must lie on the dp lattice inside the computational domain, alongside the lower wall")
    normal_list = geometry.find("./commands/list[@name='GeometryForNormals']") if geometry is not None else None
    normal_shape_mode = normal_list.find("./setshapemode") if normal_list is not None else None
    require(gaps, "NORMAL_GEOMETRY_REQUESTED_FROM_WALL_SURFACES",
            normal_list is not None
            and normal_list.find("./setnormalinvert[@invert='true']") is not None
            and normal_list.find("./shapeout[@file='hdp']") is not None
            and geometry.find("./commands/mainlist/runlist[@name='GeometryForNormals']") is not None
            and normal_shape_mode is not None
            and (normal_shape_mode.text or "").strip() == "actual | bound",
            "normal geometry must use the actual finite z-wall surfaces and emit the hdp file")
    normal_cfg = root.find("./casedef/normals[@active='true']/norgeometry")
    require(gaps, "NATIVE_NORMALS_ENABLED_AND_BOUND_TO_HDP",
            normal_cfg is not None
            and normal_cfg.find("./geometryfile").get("file") == "[CaseName]_hdp_Actual.vtk"
            and float(normal_cfg.find("./distanceh").get("v")) == 3.0
            and normal_cfg.find("./svshapes").get("v") == "true",
            "GenCase must be instructed to save finite boundary normals from the isolated wall geometry")
    require(gaps, "FULL_FLUID_GEOMETRY_PRESERVED",
            len(main_wall_nodes) == 2 and fluid_box is not None
            and fluid_box.findtext("./boxfill") == "solid"
            and float(fluid_box.find("./point").get("z")) == -h
            and float(fluid_box.find("./size").get("z")) == 2.0 * h
            and root.find("./casedef/geometry/commands/mainlist/runlist[@name='GeometryForNormals']") is not None,
            "r005 must preserve the fully filled fluid interval and register wall construction before it")
    require(gaps, "COLOCATED_CONTROL_TABLE_UNCHANGED",
            f'value="{control_filename()}"' in definition
            and "acceleration/" not in definition
            and control.encode("utf-8") == (LAB / R004_CONTROL).read_bytes(),
            "r005 must keep the official bare colocated CSV reference and exact r004 control values")
    return gaps


def build_review() -> dict[str, Any]:
    values = parameters()
    definition = definition_xml(values).encode("utf-8")
    control = acceleration_csv(values).encode("utf-8")
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "r005_static_design_review_passed_inputs_not_authorized" if not evaluate_design(values) else "r005_static_design_review_failed",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "static_constraint_gaps": evaluate_design(values),
        "closed_prior_execution_scopes": [
            {"scope_id": f"F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R00{index}", "same_input_retry_forbidden": True, "prior_output_reuse_forbidden": True}
            for index in range(1, 5)
        ],
        "r005_namespace": {
            "definition_target": str(DEFINITION_TARGET), "control_target": str(CONTROL_TARGET),
            "preflight_output_root": str(PREFLIGHT_ROOT), "generated_prefix": str(GENERATED_PREFIX),
            "generated_control_copy": str(COPIED_CONTROL), "all_targets_absent_at_review": True,
        },
        "precommitted_input_bytes": {
            "definition_sha256": sha256_bytes(definition), "definition_bytes": len(definition),
            "control_sha256": sha256_bytes(control), "control_bytes": len(control),
            "materialized": False, "future_writer_must_match_exactly": True,
        },
        "retained_r004_failure_evidence": {
            "status": load_json(R004_RECEIPT)["status"],
            "native_boundary_normals": load_json(R004_RECEIPT)["native"]["boundary_normals"],
            "native_boundary_particles": load_json(R004_RECEIPT)["native"]["boundary_particles"],
            "observed_bound_vtk_points": vtk_z_planes(LAB / R004_BOUND_VTK)[0],
            "observed_bound_vtk_z_planes_m": vtk_z_planes(LAB / R004_BOUND_VTK)[1],
            "root_causes": [
                "r004 Definition did not request normal geometry, hdp shape output, or active GenCase normals",
                "r004 computational-domain pointmax stopped at the upper wall coordinate, excluding its dp lattice point",
            ],
        },
        "r005_mechanism_repair": {
            "new_scope_only": True,
            "pointmax_z_m": float(parameters()["half_height"]) + 2.0 * float(parameters()["dp"]),
            "physical_wall_z_m": [-float(parameters()["half_height"]) - float(parameters()["dp"]), float(parameters()["half_height"]) + float(parameters()["dp"])],
            "wall_mk": 0,
            "normal_geometry_list": "GeometryForNormals",
            "normal_geometry_shape_mode": "actual | bound",
            "normal_geometry_output": "hdp",
            "normal_geometry_reused_in_mainlist": True,
            "normal_invert": True,
            "normal_geometry_file": "[CaseName]_hdp_Actual.vtk",
            "normal_distanceh": 3.0,
            "normal_svshapes": True,
            "unchanged_controls": ["zero gravity", "hswl=0 auto=true", "Boundary=2", "dp=0.0075", "fluid z=-0.045..0.045", "r004 bare colocated acceleration CSV bytes and values"],
            "static_only_claim": True,
        },
        "future_cpu_native_preflight_hard_gates": [
            "exactly one GenCase and at most one native BI4 decode in the new r005 namespace",
            "generated colocated acceleration CSV hash matches the precommit before decoder admission",
            "generated Bound.vtk contains exactly the expected lower and upper z-wall planes at -0.0525 and +0.0525 m",
            "generated/native boundary count is positive and agrees with both wall planes and fixed groups",
            "decoded BoundNor exists, contains one finite nonzero vector per fixed boundary particle, and has no omitted boundary entries",
            "native fluid count is exactly 6656 and fluid mass is 2.808 kg within the frozen tolerance",
            "any failed hard gate closes r005 with zero qualification credit and no retry, solver, GPU, queue, or training",
        ],
        "next_automatic_step": {
            "kind": "one-time r005 static input materialization",
            "requires": ["exclusive creation of exactly the precommitted Definition and colocated control CSV", "immutable hash-closed materialization receipt"],
            "does_not_authorize": ["GenCase", "native decoder", "solver", "GPU", "queue", "worker", "registry", "ledger", "T1/T2 qualification", "training"],
        },
        "execution_controls": {
            "definition_written": False, "control_written": False, "gencase_invoked": False,
            "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False,
            "queue_mutation": 0, "worker_started": False, "registry_mutation": 0,
            "ledger_mutation": 0, "denominator_mutation": 0, "training_started": False,
        },
        "parameters": values,
        "bindings": [
            binding(R004_REVIEW, "passed zero-execution r004 static review"),
            binding(R004_RECEIPT, "immutable closed r004 native hard-failure receipt"),
            binding(R004_DEFINITION, "r004 source Definition exposing missing normal/domain configuration"),
            binding(R004_LOG, "r004 GenCase log without normal construction"),
            binding(R004_BOUND_VTK, "binary VTK proving r004 generated only the lower wall"),
            binding(R004_NATIVE_XML, "r004 decoder index without BoundNor"),
            binding(R004_CONTROL, "r004 control table retained as exact positive control"),
            binding(CANONICAL_DEFINITION, "successful canonical normal-geometry Definition precedent"),
            binding(CANONICAL_LOG, "successful canonical nonzero-normal GenCase evidence"),
            binding(CANONICAL_BOUND_VTK, "successful canonical generated boundary VTK precedent"),
            binding(Path("scripts/f8_r004_static_design_review_v2.py"), "r004 compatibility renderer"),
            binding(Path("scripts/f8_r005_static_design_review_v1.py"), "r005 static review and precommit renderer"),
            binding(Path("tests/test_f8_r005_static_design_review_v1.py"), "r005 static review tests"),
        ],
    }


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r005 static review: {target}")
    if target == OUTPUT.resolve():
        existing = [str(item) for item in (LAB / DEFINITION_TARGET, LAB / CONTROL_TARGET, LAB / PREFLIGHT_ROOT) if item.exists()]
        if existing:
            raise FileExistsError("refusing late F8 r005 static review after scope materialization: " + ", ".join(existing))
    review = build_review()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    review = write_review(parser.parse_args(argv).output)
    print(json.dumps({key: review[key] for key in ("schema", "status", "qualification_credit", "static_constraint_gaps")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
