#!/usr/bin/env python3
"""Freeze a fresh F8 r007 candidate with one additional symmetric domain margin."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from scripts import f8_r006_static_design_review_v1 as r006


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r007")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R007"
SCHEMA = "core.cfd.f8.r007_static_design_review.v1"
OUTPUT = LAB / ROOT / "static-design-review-v1/receipt.json"
DEFINITION_TARGET = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R007_Def.xml"
CONTROL_TARGET = ROOT / "input/F8_OPC_q0p500_r007_acceleration.csv"
PREFLIGHT_ROOT = ROOT / "cpu-native-preflight-v1"
GENERATED_PREFIX = PREFLIGHT_ROOT / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R007"
COPIED_CONTROL = PREFLIGHT_ROOT / "generated/F8_OPC_q0p500_r007_acceleration.csv"

R006_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r006")
R006_REVIEW = R006_ROOT / "static-design-review-v1/receipt.json"
R006_MATERIALIZATION = R006_ROOT / "input-materialization-v1/receipt.json"
R006_AUTHORIZATION = R006_ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
R006_PREFLIGHT = R006_ROOT / "cpu-native-preflight-v1/receipt.json"
R006_DEFINITION = R006_ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006_Def.xml"
R006_LOG = R006_ROOT / "cpu-native-preflight-v1/gencase.stdout.log"
R006_BOUND = R006_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006_Bound.vtk"
R006_FLUID = R006_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006_Fluid.vtk"
R006_HDP = R006_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006_hdp_Actual.vtk"
R006_CONTROL = R006_ROOT / "input/F8_OPC_q0p500_r006_acceleration.csv"
R006_GENCODE = R006_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006.xml"
R006_GENCODE_OUT = R006_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006.out"
R006_BI4 = R006_ROOT / "cpu-native-preflight-v1/generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R006.bi4"
R006_LOCK = R006_ROOT / "cpu-native-preflight-v1/one-shot-lock.json"

CANONICAL_DEFINITION = r006.CANONICAL_DEFINITION
CANONICAL_LOG = r006.CANONICAL_LOG
F2_H2_DEFINITION = r006.F2_H2_DEFINITION
F2_H2_LOG = r006.F2_H2_LOG


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
    return r006.parameters()


def control_filename() -> str:
    return "F8_OPC_q0p500_r007_acceleration.csv"


def definition_xml(values: dict[str, float | int]) -> str:
    rendered = r006.definition_xml(values)
    replacements = {
        "Proposed F8 r006 static input": "Proposed F8 r007 static input",
        r006.control_filename(): control_filename(),
    }
    for old, new in replacements.items():
        if rendered.count(old) != 1:
            raise ValueError(f"r006 renderer no longer has exactly one r007 repair target: {old}")
        rendered = rendered.replace(old, new)

    half_height, dp = float(values["half_height"]), float(values["dp"])
    length_x, length_y = float(values["length_x"]), float(values["length_y"])
    old_min = f'<pointmin x="0" y="0" z="{-half_height - 5.0 * dp:.17g}" />'
    new_min = f'<pointmin x="0" y="0" z="{-half_height - 6.0 * dp:.17g}" />'
    old_max = f'<pointmax x="{length_x:.17g}" y="{length_y:.17g}" z="{half_height + 5.0 * dp:.17g}" />'
    new_max = f'<pointmax x="{length_x:.17g}" y="{length_y:.17g}" z="{half_height + 6.0 * dp:.17g}" />'
    if rendered.count(old_min) != 1 or rendered.count(old_max) != 1:
        raise ValueError("r006 renderer no longer has exactly one pair of symmetric domain bounds")
    rendered = rendered.replace(old_min, new_min).replace(old_max, new_max)
    ET.fromstring(rendered)
    return rendered


def acceleration_csv(values: dict[str, float | int]) -> str:
    return r006.acceleration_csv(values)


def plane_counts(values: list[float]) -> dict[str, int]:
    return dict(sorted(Counter(f"{round(float(value), 5):.4f}" for value in values).items()))


def require(gaps: list[dict[str, str]], code: str, condition: bool, detail: str) -> None:
    if not condition:
        gaps.append({"code": code, "detail": detail})


def evaluate_design(values: dict[str, float | int]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    receipt = load_json(R006_PREFLIGHT)
    authorization = load_json(R006_AUTHORIZATION)
    materialization = load_json(R006_MATERIALIZATION)
    log = (LAB / R006_LOG).read_text(encoding="utf-8")
    bound_points = r006.vtk_binary_points(LAB / R006_BOUND)
    fluid_points = r006.vtk_binary_points(LAB / R006_FLUID)
    hdp_points = r006.vtk_binary_points(LAB / R006_HDP)
    root = ET.fromstring(definition_xml(values))
    bound_z = [point[2] for point in bound_points]
    hdp_z = sorted({round(point[2], 5) for point in hdp_points})

    require(gaps, "R006_CLOSED_ON_MISSING_UPPER_OUTER_LAYER",
            receipt.get("schema") == "core.cfd.f8.r006_cpu_native_preflight.v1"
            and receipt.get("status") == "generated_geometry_failed_hard_audit"
            and receipt.get("qualification_credit") == 0
            and receipt.get("execution_controls", {}).get("cpu_gencase_invoked") is True
            and receipt.get("execution_controls", {}).get("native_decode_invoked") is False
            and receipt.get("execution_controls", {}).get("solver_invoked") is False
            and receipt.get("execution_controls", {}).get("gpu_invoked") is False,
            "r006 must remain closed after its one-shot generated-geometry gate, with no decoder, solver, or GPU")
    observed_counts = plane_counts(bound_z)
    expected_failed_counts = {
        "-0.0750": 512, "-0.0675": 512, "-0.0600": 512, "-0.0525": 512,
        "0.0525": 512, "0.0600": 512, "0.0675": 512,
    }
    require(gaps, "R006_FAILURE_ISOLATED_TO_ONE_TOPMOST_WALL_PLANE",
            len(bound_points) == 3584 and observed_counts == expected_failed_counts
            and receipt.get("generated_geometry_audit", {}).get("generated_geometry", {}).get("wall_plane_particle_counts") == expected_failed_counts,
            "r006 generated all four lower layers and three upper layers, omitting only the +0.075 m outer layer")
    require(gaps, "R006_OTHER_GEOMETRY_POSITIVE_CONTROLS",
            receipt.get("generated_geometry_audit", {}).get("checks", {}).get("generated_fluid_particles_exact") is True
            and receipt.get("generated_geometry_audit", {}).get("checks", {}).get("generated_fluid_vtk_z_bounds_exact") is True
            and len(fluid_points) == 6656
            and abs(min(point[2] for point in fluid_points) + 0.045) < 1e-6
            and abs(max(point[2] for point in fluid_points) - 0.045) < 1e-6
            and hdp_z == [-0.04875, 0.04875]
            and receipt.get("generated_colocated_control_copy", {}).get("hash_matches") is True,
            "r006 must preserve passing fluid count/extent, half-dp hdp interface planes, and exact control copy")
    require(gaps, "R006_RASTER_DOMAIN_BOUNDARY_EVIDENCE",
            "PosMax_z=[0.0825]" in log and "Z range: -0.075 to 0.0675 [m]" in log
            and receipt.get("generated_geometry_audit", {}).get("generated_geometry", {}).get("global_particle_z_bounds_m") == [-0.075, 0.0675],
            "r006 domain maximum was 0.0825 m while the generated particle range stopped at +0.0675 m")
    require(gaps, "R006_INPUT_AND_PREVIOUS_SCOPES_CLOSED",
            materialization.get("status") == "one_time_r006_inputs_materialized_static_only"
            and authorization.get("status") == "authorized_for_exactly_one_r006_cpu_native_preflight"
            and authorization.get("execution_policy", {}).get("same_input_retry_forbidden") is True
            and len(authorization.get("closed_prior_scopes", [])) == 5,
            "r007 must bind r006's materialized inputs, one-shot authorization, and all r001-r005 closures")
    require(gaps, "FRESH_R007_SCOPE_AND_OUTPUT_NAMESPACE",
            SCOPE == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R007"
            and all(f"r00{index}" not in str(ROOT) for index in range(1, 7)),
            "r007 must be a separate no-reuse scope")

    values_expected = r006.parameters()
    constants = {node.tag: dict(node.attrib) for node in root.findall("./casedef/constantsdef/*")}
    expected_constants = {node.tag: dict(node.attrib) for node in ET.parse(LAB / R006_DEFINITION).getroot().findall("./casedef/constantsdef/*")}
    geometry_definition = root.find("./casedef/geometry/definition")
    point_min = float(geometry_definition.find("./pointmin").get("z"))
    point_max = float(geometry_definition.find("./pointmax").get("z"))
    values_dp = float(values_expected["dp"])
    wall_outer = float(values_expected["half_height"]) + 4 * values_dp
    require(gaps, "R007_ONLY_INCREASES_SYMMETRIC_DOMAIN_MARGIN",
            values == values_expected and constants == expected_constants
            and abs(point_min + 0.09) < 1e-14 and abs(point_max - 0.09) < 1e-14
            and abs((point_max - wall_outer) / values_dp - 2.0) < 1e-12,
            "r007 changes only pointmin/pointmax from ±0.0825 m to ±0.09 m, adding one dp beyond r006's outer-layer margin")
    geometry = root.find("./casedef/geometry")
    normal_wall = geometry.find("./commands/list[@name='GeometryForNormals']/drawbox")
    particle_wall = geometry.find("./commands/mainlist/drawbox[1]")
    fluid_box = geometry.find("./commands/mainlist/drawbox[2]")
    require(gaps, "MDBC_WALL_AND_CONTROL_CONTRACT_PRESERVED",
            normal_wall.find("./layers[@vdp='-0.5']") is not None
            and particle_wall.find("./layers[@vdp='0,1,2,3']") is not None
            and fluid_box.findtext("./boxfill") == "solid"
            and abs(float(fluid_box.find("./point").get("z")) + 0.045) < 1e-14
            and abs(float(fluid_box.find("./size").get("z")) - 0.09) < 1e-14
            and acceleration_csv(values).encode("utf-8") == (LAB / R006_CONTROL).read_bytes()
            and f'value="{control_filename()}"' in definition_xml(values),
            "r007 must retain four mDBC wall layers, half-dp hdp offset, fluid geometry, and exact control bytes")
    return gaps


def build_review() -> dict[str, Any]:
    values = parameters()
    definition = definition_xml(values).encode("utf-8")
    control = acceleration_csv(values).encode("utf-8")
    gaps = evaluate_design(values)
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "r007_static_design_review_passed_inputs_not_authorized" if not gaps else "r007_static_design_review_failed",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "static_constraint_gaps": gaps,
        "closed_prior_execution_scopes": [
            {"scope_id": f"F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R00{index}", "same_input_retry_forbidden": True, "prior_output_reuse_forbidden": True}
            for index in range(1, 7)
        ],
        "r007_namespace": {
            "definition_target": str(DEFINITION_TARGET), "control_target": str(CONTROL_TARGET),
            "preflight_output_root": str(PREFLIGHT_ROOT), "generated_prefix": str(GENERATED_PREFIX),
            "generated_control_copy": str(COPIED_CONTROL), "all_targets_absent_at_review": True,
        },
        "precommitted_input_bytes": {
            "definition_sha256": sha256_bytes(definition), "definition_bytes": len(definition),
            "control_sha256": sha256_bytes(control), "control_bytes": len(control),
            "materialized": False, "future_writer_must_match_exactly": True,
        },
        "retained_r006_failure_evidence": {
            "status": load_json(R006_PREFLIGHT)["status"],
            "generated_fixed_boundary_particles": load_json(R006_PREFLIGHT)["generated_geometry_audit"]["generated_geometry"]["fixed_boundary_particles"],
            "generated_boundary_plane_particle_counts": observed_counts_from_receipt(),
            "missing_upper_outer_plane_m": 0.075,
            "generated_fluid_particles": 6656,
            "generated_fluid_z_bounds_m": [-0.045, 0.045],
            "generated_hdp_surface_z_planes_m": [-0.04875, 0.04875],
            "native_decode_invoked": False,
        },
        "r007_mechanism_repair": {
            "new_scope_only": True,
            "old_r006_domain_z_m": [-0.0825, 0.0825],
            "new_domain_z_m": [-0.09, 0.09],
            "outermost_boundary_layer_z_m": [-0.075, 0.075],
            "domain_clearance_beyond_outermost_layers_dp": {"lower": 2.0, "upper": 2.0},
            "boundary_layers_per_wall": 4,
            "expected_boundary_z_planes_m": [-0.075, -0.0675, -0.06, -0.0525, 0.0525, 0.06, 0.0675, 0.075],
            "expected_fixed_boundary_particles": 4096,
            "expected_fluid_particles": 6656,
            "expected_total_particles": 10752,
            "expected_hdp_surface_z_planes_m": [-0.04875, 0.04875],
            "native_normal_minimum_magnitude_m": 0.001875,
            "only_physical_input_change_from_r006": "symmetric pointmin/pointmax computational-domain margin",
            "unchanged_controls": ["zero gravity", "hswl=0 auto=true", "Boundary=2", "dp=0.0075", "fluid z=-0.045..0.045", "r006 acceleration CSV bytes and values"],
            "static_only_claim": True,
        },
        "future_cpu_native_preflight_hard_gates": [
            "exactly one GenCase and at most one native BI4 decode in the new r007 namespace",
            "generated colocated acceleration CSV hash matches the precommit before decoder admission",
            "generated Bound.vtk contains exactly eight z-wall particle planes from -0.075 to +0.075 m, 512 particles per plane",
            "generated/native fixed boundary count is exactly 4096 and agrees with all eight planes and fixed groups",
            "generated Fluid.vtk has exactly 6656 particles spanning z=-0.045..+0.045 m",
            "generated hdp_Actual.vtk contains the two inward-offset wall surfaces at z=±0.04875 m",
            "decoded BoundNor has one finite vector per boundary particle, every norm >=0.001875 m, lower normals +z and upper normals -z",
            "any failed hard gate closes r007 with zero credit and no retry, prior-output reuse, solver, GPU, queue, or training",
        ],
        "next_automatic_step": {
            "kind": "one-time r007 static input materialization",
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
            binding(R006_REVIEW, "passed immutable r006 static design review"),
            binding(R006_MATERIALIZATION, "static-only r006 input materialization receipt"),
            binding(R006_AUTHORIZATION, "immutable one-shot r006 CPU/native preflight authorization"),
            binding(R006_PREFLIGHT, "closed r006 generated-geometry failure receipt"),
            binding(R006_DEFINITION, "r006 Definition with failed upper-bound margin"),
            binding(R006_LOG, "r006 GenCase log proving the positive-side missing layer"),
            binding(R006_BOUND, "r006 Bound.vtk proving only seven of eight expected planes"),
            binding(R006_FLUID, "r006 Fluid.vtk positive control"),
            binding(R006_HDP, "r006 half-dp hdp interface positive control"),
            binding(R006_CONTROL, "r006 control CSV retained as exact positive control"),
            binding(R006_GENCODE, "r006 generated XML particle and domain summary"),
            binding(R006_GENCODE_OUT, "r006 raw GenCase operations log"),
            binding(R006_BI4, "r006 generated native BI4, decoder not invoked"),
            binding(R006_LOCK, "r006 one-shot lock proving no retry"),
            binding(CANONICAL_DEFINITION, "successful canonical mDBC half-dp normal geometry precedent"),
            binding(CANONICAL_LOG, "successful canonical nonzero-normal GenCase evidence"),
            binding(F2_H2_DEFINITION, "F2 H2 successful multilayer mDBC geometry precedent"),
            binding(F2_H2_LOG, "F2 H2 successful normal magnitude evidence"),
            binding(Path("scripts/f8_r006_static_design_review_v1.py"), "r006 four-layer candidate renderer"),
            binding(Path("scripts/f8_r006_cpu_native_preflight_execute_v1.py"), "r006 generated-geometry gate and failure auditor"),
            binding(Path("scripts/f8_r007_static_design_review_v1.py"), "r007 static design review and precommit renderer"),
            binding(Path("tests/test_f8_r007_static_design_review_v1.py"), "r007 static design review contract tests"),
        ],
    }


def observed_counts_from_receipt() -> dict[str, int]:
    return load_json(R006_PREFLIGHT)["generated_geometry_audit"]["generated_geometry"]["wall_plane_particle_counts"]


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r007 static review: {target}")
    if target == OUTPUT.resolve():
        protected = [LAB / DEFINITION_TARGET, LAB / CONTROL_TARGET, LAB / PREFLIGHT_ROOT]
        existing = [str(item) for item in protected if item.exists()]
        if existing:
            raise FileExistsError("refusing late F8 r007 static review after scope materialization: " + ", ".join(existing))
    review = build_review()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    review = write_review(parser.parse_args(argv).output)
    print(json.dumps({key: review[key] for key in ("schema", "status", "qualification_credit", "static_constraint_gaps")}, indent=2))
    return 0 if review["status"] == "r007_static_design_review_passed_inputs_not_authorized" else 1


if __name__ == "__main__":
    raise SystemExit(main())
