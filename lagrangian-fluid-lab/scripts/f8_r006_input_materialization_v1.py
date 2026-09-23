#!/usr/bin/env python3
"""Materialize the precommitted F8 r006 Definition and colocated control CSV once."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from scripts import f8_r006_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
ROOT, SCOPE = design.ROOT, design.SCOPE
REVIEW = ROOT / "static-design-review-v1/receipt.json"
DEFINITION_TARGET, CONTROL_TARGET = design.DEFINITION_TARGET, design.CONTROL_TARGET
RECEIPT_TARGET = ROOT / "input-materialization-v1/receipt.json"
AUTHORIZATION_TARGET = ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
PREFLIGHT_TARGET = ROOT / "cpu-native-preflight-v1"
SCHEMA = "core.cfd.f8.r006_input_materialization.v1"


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


def bindings_current(value: dict[str, Any]) -> bool:
    for item in value.get("bindings", []):
        path = LAB / str(item.get("path", ""))
        if (not path.is_file() or item.get("sha256") != sha256(path)
                or item.get("bytes") != path.stat().st_size):
            return False
    return True


def validate_review(review: dict[str, Any], definition: bytes, control: bytes) -> None:
    committed = review.get("precommitted_input_bytes", {})
    namespace = review.get("r006_namespace", {})
    if not (
        review.get("schema") == design.SCHEMA
        and review.get("scope_id") == SCOPE
        and review.get("status") == "r006_static_design_review_passed_inputs_not_authorized"
        and review.get("qualification_claim") == "none"
        and review.get("qualification_credit") == 0
        and review.get("static_constraint_gaps") == []
        and bindings_current(review)
        and namespace.get("definition_target") == str(DEFINITION_TARGET)
        and namespace.get("control_target") == str(CONTROL_TARGET)
        and namespace.get("preflight_output_root") == str(PREFLIGHT_TARGET)
        and committed.get("materialized") is False
        and committed.get("future_writer_must_match_exactly") is True
        and committed.get("definition_sha256") == sha256_bytes(definition)
        and committed.get("definition_bytes") == len(definition)
        and committed.get("control_sha256") == sha256_bytes(control)
        and committed.get("control_bytes") == len(control)
    ):
        raise PermissionError("F8 r006 static review does not bind this exact one-time materialization")


def prove_definition(definition: str) -> dict[str, Any]:
    root = ET.fromstring(definition)
    constants = {node.tag: dict(node.attrib) for node in root.findall("./casedef/constantsdef/*")}
    expected_constants = {
        "gravity": {"x": "0", "y": "0", "z": "0"}, "rhop0": {"value": "1000"},
        "rhopgradient": {"value": "1"}, "hswl": {"value": "0", "auto": "true"},
        "gamma": {"value": "7"}, "speedsystem": {"value": "0", "auto": "true"},
        "coefsound": {"value": "1"}, "speedsound": {"value": "10", "auto": "false"},
        "coefh": {"value": "1.0"}, "cflnumber": {"value": "0.2"},
    }
    if any(any(constants.get(name, {}).get(key) != item for key, item in attrs.items())
           for name, attrs in expected_constants.items()):
        raise ValueError("r006 Definition lost reviewed constantsdef compatibility fields")

    geometry = root.find("./casedef/geometry")
    domain = geometry.find("./definition") if geometry is not None else None
    normal_list = geometry.find("./commands/list[@name='GeometryForNormals']") if geometry is not None else None
    mainlist = geometry.find("./commands/mainlist") if geometry is not None else None
    normals = root.find("./casedef/normals[@active='true']/norgeometry")
    if geometry is None or domain is None or normal_list is None or mainlist is None or normals is None:
        raise ValueError("r006 Definition lost its geometry, wall, or normal-configuration sections")

    values = design.parameters()
    half_height, dp = float(values["half_height"]), float(values["dp"])
    wall_base = half_height + dp
    point_min, point_max = float(domain.find("./pointmin").get("z")), float(domain.find("./pointmax").get("z"))
    outer_wall = half_height + 4.0 * dp
    if not (math.isclose(point_min, -(half_height + 5.0 * dp), abs_tol=1e-14)
            and math.isclose(point_max, half_height + 5.0 * dp, abs_tol=1e-14)
            and math.isclose((point_max - outer_wall) / dp, 1.0, abs_tol=1e-12)):
        raise ValueError("r006 computational domain does not contain all four boundary layers plus one dp margin")
    if (normal_list.find("./setnormalinvert[@invert='true']") is None
            or normal_list.find("./shapeout[@file='hdp']") is None
            or normal_list.find("./setshapemode").text.strip() != "actual | bound"):
        raise ValueError("r006 normal-geometry list lacks inversion, hdp output, or actual-bound shape mode")
    normal_wall = normal_list.find("./drawbox")
    particle_wall = mainlist.find("./drawbox[1]")
    if (normal_wall is None or normal_wall.find("./layers[@vdp='-0.5']") is None
            or particle_wall is None or particle_wall.find("./layers[@vdp='0,1,2,3']") is None):
        raise ValueError("r006 must separate the half-dp normal interface from its four boundary support layers")
    for wall in (normal_wall, particle_wall):
        if (wall.findtext("./boxfill") != "top | bottom"
                or not math.isclose(float(wall.find("./point").get("z")), -wall_base, abs_tol=1e-14)
                or not math.isclose(float(wall.find("./size").get("z")), 2.0 * wall_base, abs_tol=1e-14)):
            raise ValueError("r006 wall-face coordinates or finite top/bottom extent changed")
    fluid = mainlist.find("./drawbox[2]")
    if (fluid is None or fluid.findtext("./boxfill") != "solid"
            or not math.isclose(float(fluid.find("./point").get("z")), -half_height, abs_tol=1e-14)
            or not math.isclose(float(fluid.find("./size").get("z")), 2.0 * half_height, abs_tol=1e-14)):
        raise ValueError("r006 fully filled fluid interval changed")
    if (normals.find("./geometryfile").get("file") != "[CaseName]_hdp_Actual.vtk"
            or float(normals.find("./distanceh").get("v")) != 3.0
            or normals.find("./svshapes").get("v") != "true"):
        raise ValueError("r006 native normal configuration differs from the reviewed geometry precedent")
    if mainlist.find("./runlist[@name='GeometryForNormals']") is None:
        raise ValueError("r006 mainlist does not execute its isolated normal geometry")
    if f'value="{design.control_filename()}"' not in definition or "acceleration/" in definition:
        raise ValueError("r006 Definition lost its colocated bare-filename control reference")

    return {
        "constantsdef": expected_constants,
        "domain_z_m": [point_min, point_max],
        "base_wall_faces_z_m": [-wall_base, wall_base],
        "normal_interface_expected_z_m": [-wall_base + dp * 0.5, wall_base - dp * 0.5],
        "boundary_layers_vdp": [0, 1, 2, 3],
        "boundary_z_planes_expected_m": [-outer_wall, -outer_wall + dp, -outer_wall + 2 * dp, -wall_base,
                                          wall_base, wall_base + dp, wall_base + 2 * dp, outer_wall],
        "boundary_particles_expected": 4096,
        "fluid_z_interval_m": [-half_height, half_height],
        "fluid_particles_expected": 6656,
        "total_particles_expected": 10752,
        "normal_geometry_list": "GeometryForNormals",
        "normal_geometry_layers_vdp": -0.5,
        "normal_distanceh": 3.0,
        "normal_svshapes": True,
        "normal_magnitude_minimum_m": dp * 0.25,
        "static_proof_only": True,
    }


def build_receipt(definition: bytes, control: bytes) -> dict[str, Any]:
    definition_text, control_text = definition.decode("utf-8"), control.decode("utf-8")
    if control != (LAB / design.R005_CONTROL).read_bytes():
        raise ValueError("r006 acceleration values changed from the exact retained positive-control table")
    if not control_text.startswith("#Time;LinearAccX;") or not control_text.endswith(";0;0;0;0;0\n"):
        raise ValueError("r006 acceleration CSV format or endpoint changed")
    review = load_json(REVIEW)
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "one_time_r006_inputs_materialized_static_only",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "retained_r005_failure": {
            "receipt": str(design.R005_PREFLIGHT),
            "status": load_json(design.R005_PREFLIGHT)["status"],
            "same_input_retry_forbidden": True,
        },
        "closed_prior_execution_scopes": review["closed_prior_execution_scopes"],
        "authorization": {
            "source": str(REVIEW), "review_schema": design.SCHEMA, "consumed": True,
            "overwrite_or_reuse_allowed": False, "definition_target": str(DEFINITION_TARGET),
            "control_target": str(CONTROL_TARGET),
        },
        "materialized_inputs": {
            "definition": binding(DEFINITION_TARGET, "precommitted F8 r006 Definition XML"),
            "control": binding(CONTROL_TARGET, "precommitted F8 r006 colocated acceleration CSV"),
            "definition_matches_review_precommit": True,
            "control_matches_review_precommit": True,
        },
        "definition_proof": prove_definition(definition_text),
        "control_dependency_copy_proof": {
            "definition_relative_reference": design.control_filename(),
            "source_control": str(CONTROL_TARGET),
            "source_is_colocated_with_definition": True,
            "required_generated_copy": str(design.COPIED_CONTROL),
            "required_copy_hash": sha256_bytes(control),
        },
        "execution_controls": {
            "definition_written": True, "control_written": True, "gencase_invoked": False,
            "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False,
            "queue_mutation": 0, "worker_started": False, "registry_mutation": 0,
            "ledger_mutation": 0, "denominator_mutation": 0, "training_started": False,
        },
        "explicitly_not_authorized": ["GenCase", "native decoder", "solver", "GPU", "queue", "worker", "registry", "ledger", "T1/T2 qualification", "training"],
        "next_automatic_step": {
            "kind": "one-time F8 r006 CPU-native-preflight authorization and execution",
            "requires": [
                "new immutable authorization binding this scope, static review, materialization, and tool hashes",
                "one isolated r006 output namespace and invocation lock",
                "one GenCase followed by frozen geometry gates before at most one native decode",
            ],
        },
        "bindings": [
            binding(REVIEW, "immutable passed F8 r006 static design review"),
            binding(Path("scripts/f8_r006_static_design_review_v1.py"), "r006 precommitted Definition renderer"),
            binding(Path("scripts/f8_r006_input_materialization_v1.py"), "exclusive-create r006 input materializer"),
            binding(Path("tests/test_f8_r006_input_materialization_v1.py"), "r006 input materialization contract tests"),
            binding(DEFINITION_TARGET, "materialized r006 Definition"),
            binding(CONTROL_TARGET, "materialized r006 colocated control CSV"),
        ],
    }


def write_materialization(
    definition_target: Path = LAB / DEFINITION_TARGET,
    control_target: Path = LAB / CONTROL_TARGET,
    receipt_target: Path = LAB / RECEIPT_TARGET,
) -> dict[str, Any]:
    registered = (LAB / DEFINITION_TARGET, LAB / CONTROL_TARGET, LAB / RECEIPT_TARGET)
    if (definition_target, control_target, receipt_target) != registered:
        raise ValueError("F8 r006 materializer only permits its registered targets")
    definition = design.definition_xml(design.parameters()).encode("utf-8")
    control = design.acceleration_csv(design.parameters()).encode("utf-8")
    validate_review(load_json(REVIEW), definition, control)
    protected = (definition_target, control_target, receipt_target, LAB / AUTHORIZATION_TARGET, LAB / PREFLIGHT_TARGET)
    existing = [str(path) for path in protected if path.exists()]
    if existing:
        raise FileExistsError("refusing one-time F8 r006 materialization because target exists: " + ", ".join(existing))
    definition_target.parent.mkdir(parents=True, exist_ok=True)
    receipt_target.parent.mkdir(parents=True, exist_ok=True)
    with definition_target.open("xb") as stream:
        stream.write(definition)
    with control_target.open("xb") as stream:
        stream.write(control)
    receipt = build_receipt(definition, control)
    with receipt_target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    value = write_materialization()
    print(json.dumps({key: value[key] for key in ("schema", "status", "qualification_credit", "next_automatic_step")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
