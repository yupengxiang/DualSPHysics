#!/usr/bin/env python3
"""Freeze a new F8 r006 design addressing the r005 native geometry failure.

This review derives a fresh Definition and control table in memory. It does not
materialize inputs or invoke GenCase, a decoder, solver, GPU, queue, or worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from scripts import f8_r005_static_design_review_v1 as r005


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r006")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006"
SCHEMA = "core.cfd.f8.r006_static_design_review.v1"
OUTPUT = LAB / ROOT / "static-design-review-v1/receipt.json"
DEFINITION_TARGET = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006_Def.xml"
CONTROL_TARGET = ROOT / "input/F8_OPC_q0p500_r006_acceleration.csv"
PREFLIGHT_ROOT = ROOT / "cpu-native-preflight-v1"
GENERATED_PREFIX = PREFLIGHT_ROOT / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006"
COPIED_CONTROL = PREFLIGHT_ROOT / "generated/F8_OPC_q0p500_r006_acceleration.csv"

R005_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r005")
R005_REVIEW = R005_ROOT / "static-design-review-v1/receipt.json"
R005_MATERIALIZATION = R005_ROOT / "input-materialization-v1/receipt.json"
R005_PREFLIGHT = R005_ROOT / "cpu-native-preflight-v1/receipt.json"
R005_DEFINITION = R005_ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R005_Def.xml"
R005_LOG = R005_ROOT / "cpu-native-preflight-v1/gencase.stdout.log"
R005_BOUND_VTK = R005_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R005_Bound.vtk"
R005_HDP_VTK = R005_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R005_hdp_Actual.vtk"
R005_CONTROL = R005_ROOT / "input/F8_OPC_q0p500_r005_acceleration.csv"

CANONICAL_DEFINITION = Path("diagnostics/r3_f6_canonical_geometry/definitions/canonical_rectangular_Def.xml")
CANONICAL_LOG = Path("diagnostics/r3_f6_canonical_geometry/evidence/rectangular/gencase.log")
CANONICAL_BOUND_VTK = Path("diagnostics/r3_f6_canonical_geometry/evidence/rectangular/generated/canonical_rectangular_Bound.vtk")
F2_H2_DEFINITION = Path("campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/input/CORE_F2_static_full_cup_volume_supportclearance_h2_q0p00000000_dp0p010000000000_canary_Def.xml")
F2_H2_LOG = Path("campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/gencase.log")


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
    return r005.parameters()


def control_filename() -> str:
    return "F8_OPC_q0p500_r006_acceleration.csv"


def definition_xml(values: dict[str, float | int]) -> str:
    """Render a fresh r006 scope with a larger upper margin and offset hdp surface."""
    rendered = r005.definition_xml(values)
    replacements = {
        "Proposed F8 r005 static input": "Proposed F8 r006 static input",
        r005.control_filename(): control_filename(),
    }
    for old, new in replacements.items():
        if rendered.count(old) != 1:
            raise ValueError(f"r005 renderer no longer has exactly one r006 repair target: {old}")
        rendered = rendered.replace(old, new)

    half_height, dp = float(values["half_height"]), float(values["dp"])
    length_x, length_y = float(values["length_x"]), float(values["length_y"])
    old_min = f'<pointmin x="0" y="0" z="{-half_height - dp:.17g}" />'
    new_min = f'<pointmin x="0" y="0" z="{-half_height - 5.0 * dp:.17g}" />'
    if rendered.count(old_min) != 1:
        raise ValueError("r005 renderer no longer has exactly one lower domain bound to extend")
    rendered = rendered.replace(old_min, new_min)

    old_max = (
        f'<pointmax x="{length_x:.17g}" y="{length_y:.17g}" '
        f'z="{half_height + 2.0 * dp:.17g}" />'
    )
    new_max = (
        f'<pointmax x="{length_x:.17g}" y="{length_y:.17g}" '
        f'z="{half_height + 5.0 * dp:.17g}" />'
    )
    if rendered.count(old_max) != 1:
        raise ValueError("r005 renderer no longer has exactly one upper domain bound to extend")
    rendered = rendered.replace(old_max, new_max)

    # Keep the base wall surfaces fixed; the mainlist adds support layers while
    # the isolated hdp surface moves half a dp toward the fluid, per precedent.
    rendered, boxfill_count = rendered.replace(
        "<boxfill>top|bottom</boxfill>", "<boxfill>top | bottom</boxfill>"
    ), rendered.count("<boxfill>top|bottom</boxfill>")
    if boxfill_count != 2:
        raise ValueError("r005 renderer no longer has exactly two finite z-wall boxfill tokens")
    wall = r005._wall_box(values).replace(
        "<boxfill>top|bottom</boxfill>", "<boxfill>top | bottom</boxfill>"
    )
    if rendered.count(wall) != 1:
        raise ValueError("r005 renderer no longer has the expected isolated normal-geometry wall box")
    normal_wall = wall.replace("\n            <point", '\n            <layers vdp="-0.5" />\n            <point', 1)
    rendered = rendered.replace(wall, normal_wall, 1)

    particle_wall = r005._wall_box(values, indent="        ").replace(
        "<boxfill>top|bottom</boxfill>", "<boxfill>top | bottom</boxfill>"
    )
    if rendered.count(particle_wall) != 1:
        raise ValueError("r005 renderer no longer has exactly one mainlist particle wall box")
    layered_particle_wall = particle_wall.replace(
        "\n          <point", '\n          <layers vdp="0,1,2,3" />\n          <point', 1
    )
    rendered = rendered.replace(particle_wall, layered_particle_wall, 1)
    ET.fromstring(rendered)
    return rendered


def acceleration_csv(values: dict[str, float | int]) -> str:
    return r005.acceleration_csv(values)


def vtk_binary_points(path: Path) -> list[tuple[float, float, float]]:
    return r005.vtk_binary_points(path)


def vtk_z_planes(path: Path, precision: int = 7) -> tuple[int, list[float]]:
    return r005.vtk_z_planes(path, precision)


def require(gaps: list[dict[str, str]], code: str, condition: bool, detail: str) -> None:
    if not condition:
        gaps.append({"code": code, "detail": detail})


def evaluate_design(values: dict[str, float | int]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    receipt = load_json(R005_PREFLIGHT)
    review = load_json(R005_REVIEW)
    materialization = load_json(R005_MATERIALIZATION)
    log = (LAB / R005_LOG).read_text(encoding="utf-8")
    r005_bound_count, r005_bound_planes = vtk_z_planes(LAB / R005_BOUND_VTK)
    r005_hdp_points = vtk_binary_points(LAB / R005_HDP_VTK)
    r005_hdp_planes = sorted({round(point[2], 7) for point in r005_hdp_points})
    canonical = ET.parse(LAB / CANONICAL_DEFINITION).getroot()
    canonical_log = (LAB / CANONICAL_LOG).read_text(encoding="utf-8")
    f2_h2 = ET.parse(LAB / F2_H2_DEFINITION).getroot()
    f2_h2_log = (LAB / F2_H2_LOG).read_text(encoding="utf-8")
    definition, control = definition_xml(values), acceleration_csv(values)
    root = ET.fromstring(definition)

    require(gaps, "R005_CLOSED_NATIVE_GEOMETRY_FAILURE",
            receipt.get("schema") == "core.cfd.f8.r005_cpu_native_preflight.v1"
            and receipt.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R005"
            and receipt.get("status") == "generated_geometry_failed_hard_audit"
            and receipt.get("qualification_credit") == 0
            and receipt.get("execution_controls", {}).get("cpu_gencase_invoked") is True
            and receipt.get("execution_controls", {}).get("native_decode_invoked") is False,
            "r005 must remain a closed zero-credit GenCase geometry failure with no native decoder invocation")
    generated = receipt.get("generated_geometry_audit", {}).get("generated_geometry", {})
    require(gaps, "R005_FAILURE_EVIDENCE_BOUND",
            r005_bound_count == 512 and r005_bound_planes == [-0.0525]
            and generated.get("fixed_boundary_particles") == 512
            and generated.get("wall_plane_particle_counts") == {"-0.0525": 512}
            and len(r005_hdp_points) == 8 and r005_hdp_planes == [-0.0525, 0.0525],
            "r005 Bound.vtk has only the lower particle plane although its hdp geometry contains both wall surfaces")
    require(gaps, "R005_NEAR_ZERO_NORMAL_FAILURE_RETAINED",
            "Final zero normals: 0/512" in log
            and "Maximum normal: 1.63913e-09" in log
            and "Normals size range: (0.000000 - 0.000000)" in log,
            "r005 normal output must retain its near-zero numerical-magnitude evidence, not be treated as valid")
    require(gaps, "R005_PREVIOUS_SCOPES_CLOSED",
            review.get("status") == "r005_static_design_review_passed_inputs_not_authorized"
            and materialization.get("status") == "one_time_r005_inputs_materialized_static_only"
            and len(review.get("closed_prior_execution_scopes", [])) == 4
            and receipt.get("qualification_credit") == 0,
            "r006 must bind the passed r005 review, static materialization, and four already-closed execution scopes")
    require(gaps, "CANONICAL_HALF_LAYER_NORMAL_PRECEDENT",
            canonical.find("./casedef/normals[@active='true']") is not None
            and canonical.find("./casedef/geometry/commands/list[@name='GeometryForNormals']/drawbox/layers[@vdp='-0.5']") is not None
            and "Non-zero particle normals: 1,476/1,476" in canonical_log
            and "Normals size range: (0.020000 - 0.173205)" in canonical_log,
            "successful canonical normal construction must demonstrate a half-dp geometry offset and finite normal magnitudes")
    require(gaps, "F2_MDBC_MULTI_LAYER_PRECEDENT",
            f2_h2.findall("./casedef/geometry/commands/list[@name='GeometryForNormals']/drawbox/layers[@vdp='-0.5']")
            and f2_h2.findall("./casedef/geometry/commands/mainlist/drawbox/layers[@vdp='0,1,2']")
            and "Normals size range: (0.005000 - 0.046368)" in f2_h2_log,
            "the qualified F2 static canary must retain the paired -0.5 dp interface and multi-layer boundary pattern")
    require(gaps, "FRESH_R006_NAMESPACE",
            SCOPE == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006"
            and all(f"r00{index}" not in str(ROOT) for index in range(1, 6)),
            "r006 must use a new scope and output namespace with no earlier-attempt output reuse")

    constants = {node.tag: dict(node.attrib) for node in root.findall("./casedef/constantsdef/*")}
    expected_constants = {
        "gravity": {"x": "0", "y": "0", "z": "0"}, "rhop0": {"value": "1000"},
        "rhopgradient": {"value": "1"}, "hswl": {"value": "0", "auto": "true"},
        "gamma": {"value": "7"}, "speedsystem": {"value": "0", "auto": "true"},
        "coefsound": {"value": "1"}, "speedsound": {"value": "10", "auto": "false"},
        "coefh": {"value": "1.0"}, "cflnumber": {"value": "0.2"},
    }
    require(gaps, "REGISTERED_PHYSICS_AND_CONSTANTS_PRESERVED",
            values == r005.parameters()
            and all(all(constants.get(name, {}).get(key) == expected for key, expected in attrs.items())
                    for name, attrs in expected_constants.items()),
            "r006 must preserve the registered q=0.5 physical constants and candidate parameters")

    geometry = root.find("./casedef/geometry")
    definition_node = geometry.find("./definition") if geometry is not None else None
    normal_list = geometry.find("./commands/list[@name='GeometryForNormals']") if geometry is not None else None
    mainlist = geometry.find("./commands/mainlist") if geometry is not None else None
    point_min = definition_node.find("./pointmin") if definition_node is not None else None
    point_max = definition_node.find("./pointmax") if definition_node is not None else None
    h, dp = float(values["half_height"]), float(values["dp"])
    wall_lattice_z = h + dp
    expected_outer_wall = h + 4.0 * dp
    require(gaps, "DOMAIN_CONTAINS_FOUR_BOUNDARY_LAYERS_AND_MARGIN",
            point_min is not None and point_max is not None
            and float(point_min.get("z")) == -(h + 5.0 * dp)
            and float(point_max.get("z")) == h + 5.0 * dp
            and math_close((float(point_max.get("z")) - expected_outer_wall) / dp, 1.0),
            "the symmetric domain must include four outward boundary layers and one dp of clearance beyond them")

    normal_wall = normal_list.find("./drawbox") if normal_list is not None else None
    particle_wall = mainlist.find("./drawbox[1]") if mainlist is not None else None
    fluid_box = mainlist.find("./drawbox[2]") if mainlist is not None else None
    wall_ok = lambda node: (
        node is not None and node.findtext("./boxfill") == "top | bottom"
        and float(node.find("./point").get("z")) == -wall_lattice_z
        and float(node.find("./size").get("z")) == 2.0 * wall_lattice_z
    )
    require(gaps, "NORMAL_SURFACE_OFFSET_ISOLATED_FROM_PARTICLE_GEOMETRY",
            normal_list is not None and wall_ok(normal_wall)
            and normal_wall.find("./layers[@vdp='-0.5']") is not None
            and particle_wall is not None and wall_ok(particle_wall)
            and particle_wall.find("./layers[@vdp='0,1,2,3']") is not None,
            "normal construction uses the canonical -0.5 dp offset while the unchanged wall faces generate four outward support layers")
    require(gaps, "NATIVE_NORMAL_MAGNITUDE_GATE_FROZEN",
            dp * 0.25 > 1.63913e-9
            and dp * 0.25 <= dp * 0.5,
            "future native audit must require normal magnitude >= 0.25 dp, below the canonical 0.5 dp positive-control minimum")
    normals = root.find("./casedef/normals[@active='true']/norgeometry")
    require(gaps, "NATIVE_NORMALS_ENABLED_AND_BOUND_TO_HDP",
            normals is not None
            and normals.find("./geometryfile").get("file") == "[CaseName]_hdp_Actual.vtk"
            and float(normals.find("./distanceh").get("v")) == 3.0
            and normals.find("./svshapes").get("v") == "true",
            "native normals remain enabled and bound to the isolated finite-wall hdp geometry")
    require(gaps, "FLUID_AND_CONTROL_UNCHANGED",
            fluid_box is not None and fluid_box.findtext("./boxfill") == "solid"
            and float(fluid_box.find("./point").get("z")) == -h
            and float(fluid_box.find("./size").get("z")) == 2.0 * h
            and control.encode("utf-8") == (LAB / R005_CONTROL).read_bytes()
            and f'value="{control_filename()}"' in definition
            and "acceleration/" not in definition,
            "r006 must retain the full fluid interval and exact r005 colocated acceleration table bytes")
    return gaps


def math_close(left: float, right: float, tolerance: float = 1e-12) -> bool:
    return abs(left - right) <= tolerance


def build_review() -> dict[str, Any]:
    values = parameters()
    definition = definition_xml(values).encode("utf-8")
    control = acceleration_csv(values).encode("utf-8")
    gaps = evaluate_design(values)
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "r006_static_design_review_passed_inputs_not_authorized" if not gaps else "r006_static_design_review_failed",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "static_constraint_gaps": gaps,
        "closed_prior_execution_scopes": [
            {"scope_id": f"F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R00{index}", "same_input_retry_forbidden": True, "prior_output_reuse_forbidden": True}
            for index in range(1, 6)
        ],
        "r006_namespace": {
            "definition_target": str(DEFINITION_TARGET), "control_target": str(CONTROL_TARGET),
            "preflight_output_root": str(PREFLIGHT_ROOT), "generated_prefix": str(GENERATED_PREFIX),
            "generated_control_copy": str(COPIED_CONTROL), "all_targets_absent_at_review": True,
        },
        "precommitted_input_bytes": {
            "definition_sha256": sha256_bytes(definition), "definition_bytes": len(definition),
            "control_sha256": sha256_bytes(control), "control_bytes": len(control),
            "materialized": False, "future_writer_must_match_exactly": True,
        },
        "retained_r005_failure_evidence": {
            "status": load_json(R005_PREFLIGHT)["status"],
            "generated_fixed_boundary_particles": load_json(R005_PREFLIGHT)["generated_geometry_audit"]["generated_geometry"]["fixed_boundary_particles"],
            "observed_bound_vtk_points_and_planes": {
                "points": vtk_z_planes(LAB / R005_BOUND_VTK)[0],
                "z_planes_m": vtk_z_planes(LAB / R005_BOUND_VTK)[1],
            },
            "hdp_geometry_points_and_planes": {
                "points": len(vtk_binary_points(LAB / R005_HDP_VTK)),
                "z_planes_m": sorted({round(point[2], 7) for point in vtk_binary_points(LAB / R005_HDP_VTK)}),
            },
            "observed_maximum_normal_m": 1.63913e-9,
            "root_causes_to_test": [
                "r005 pointmax was one dp above the nominal upper wall but GenCase emitted no upper-wall particles; r006 tests a symmetric domain extending one dp beyond a four-layer support envelope",
                "r005 normal-geometry surfaces coincided with boundary particle layers, yielding near-zero normal magnitudes",
            ],
        },
        "r006_mechanism_repair": {
            "new_scope_only": True,
            "pointmin_z_m": -float(values["half_height"]) - 5.0 * float(values["dp"]),
            "pointmax_z_m": float(values["half_height"]) + 5.0 * float(values["dp"]),
            "upper_wall_z_m": float(values["half_height"]) + float(values["dp"]),
            "boundary_layers_per_wall": 4,
            "expected_boundary_z_planes_m": [-0.075, -0.0675, -0.06, -0.0525, 0.0525, 0.06, 0.0675, 0.075],
            "expected_fixed_boundary_particles": 4096,
            "expected_fluid_particles": 6656,
            "expected_total_particles": 10752,
            "outer_wall_domain_clearance_dp": 1.0,
            "normal_geometry_list": "GeometryForNormals",
            "normal_geometry_layers_vdp": -0.5,
            "expected_normal_geometry_z_planes_m": [-0.04875, 0.04875],
            "particle_wall_surface_coordinates_unchanged": True,
            "native_normal_minimum_magnitude": float(values["dp"]) * 0.25,
            "expected_inward_normal_z_component_m": {
                "lower_wall_min": float(values["dp"]) * 0.25,
                "upper_wall_max": -float(values["dp"]) * 0.25,
            },
            "unchanged_controls": ["zero gravity", "hswl=0 auto=true", "Boundary=2", "dp=0.0075", "fluid z=-0.045..0.045", "r005 bare colocated acceleration CSV bytes and values"],
            "static_only_claim": True,
        },
        "mdbc_support_rationale": {
            "smoothing_length_m": float(values["dp"]) * 3.0**0.5,
            "required_support_thickness_2h_m": 2.0 * float(values["dp"]) * 3.0**0.5,
            "required_support_thickness_in_dp": 2.0 * 3.0**0.5,
            "boundary_layers_selected": 4,
            "support_thickness_selected_in_dp": 4.0,
            "basis": "ceil(2h/dp); four layers cover the approximately 3.464 dp support thickness while retaining a one-dp domain margin",
            "references": [
                {"title": "DualSPHysics 5th Users Workshop: mDBC requirements and multi-layer drawing", "url": "https://dual.sphysics.org/5thusersworkshop/user/pages/02.workshop/07.programme/Dominguez_5DUW.pdf"},
                {"title": "DualSPHysics 6th Workshop: mDBC requirements and four-layer tank example", "url": "https://dual.sphysics.org/6thworkshop/user/pages/03.workshop/05.Programme/6DSW_mDBC_Crespo.pdf"},
            ],
        },
        "future_cpu_native_preflight_hard_gates": [
            "exactly one GenCase and at most one native BI4 decode in the new r006 namespace",
            "generated colocated acceleration CSV hash matches the precommit before decoder admission",
            "generated Bound.vtk contains exactly eight z-wall particle planes from -0.075 to +0.075 m, 512 particles per plane",
            "generated/native fixed boundary count is exactly 4096 and agrees with all eight planes and fixed groups",
            "generated hdp_Actual.vtk contains the two inward-offset wall surfaces at approximately z=±0.04875 m",
            "decoded BoundNor exists with one finite vector per fixed boundary particle, every norm is at least 0.25 dp, and lower/upper normals point inward",
            "native fluid count is exactly 6656 and fluid mass is 2.808 kg within the frozen tolerance",
            "any failed hard gate closes r006 with zero credit and no retry, solver, GPU, queue, or training",
        ],
        "next_automatic_step": {
            "kind": "one-time r006 static input materialization",
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
            binding(R005_REVIEW, "passed zero-execution r005 static review"),
            binding(R005_MATERIALIZATION, "static-only r005 input materialization receipt"),
            binding(R005_PREFLIGHT, "immutable closed r005 generated-geometry failure receipt"),
            binding(R005_DEFINITION, "r005 input Definition proving upper-bound and normal-geometry settings"),
            binding(R005_LOG, "r005 GenCase log with omitted top wall and near-zero normals"),
            binding(R005_BOUND_VTK, "r005 generated Bound.vtk proving only lower wall particles"),
            binding(R005_HDP_VTK, "r005 hdp geometry proving both analytical wall surfaces existed"),
            binding(R005_CONTROL, "r005 control table retained as an exact positive control"),
            binding(CANONICAL_DEFINITION, "successful canonical half-layer normal-geometry precedent"),
            binding(CANONICAL_LOG, "successful canonical nonzero-normal GenCase evidence"),
            binding(CANONICAL_BOUND_VTK, "successful canonical generated boundary VTK precedent"),
            binding(F2_H2_DEFINITION, "F2 H2 successful half-dp interface and multi-layer mDBC Definition precedent"),
            binding(F2_H2_LOG, "F2 H2 GenCase log with positive normal magnitudes"),
            binding(Path("scripts/f8_r005_static_design_review_v1.py"), "r005 compatibility renderer and failure-audit parser"),
            binding(Path("scripts/f8_r006_static_design_review_v1.py"), "r006 static design review and precommit renderer"),
            binding(Path("tests/test_f8_r006_static_design_review_v1.py"), "r006 static design review contract tests"),
        ],
    }


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r006 static review: {target}")
    if target == OUTPUT.resolve():
        protected = [LAB / DEFINITION_TARGET, LAB / CONTROL_TARGET, LAB / PREFLIGHT_ROOT]
        existing = [str(item) for item in protected if item.exists()]
        if existing:
            raise FileExistsError("refusing late F8 r006 static review after scope materialization: " + ", ".join(existing))
    review = build_review()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    review = write_review(parser.parse_args(argv).output)
    print(json.dumps({key: review[key] for key in ("schema", "status", "qualification_credit", "static_constraint_gaps")}, indent=2))
    return 0 if review["status"] == "r006_static_design_review_passed_inputs_not_authorized" else 1


if __name__ == "__main__":
    raise SystemExit(main())
