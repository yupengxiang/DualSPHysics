#!/usr/bin/env python3
"""Seal one CPU-only F8 r006 GenCase/native-decoder preflight; never run binaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f8_r006_input_materialization_v1 as inputs
from scripts import f8_r006_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
ROOT, SCOPE = design.ROOT, design.SCOPE
REVIEW = ROOT / "static-design-review-v1/receipt.json"
MATERIALIZATION = inputs.RECEIPT_TARGET
OUTPUT = LAB / ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
RUNNER = Path("scripts/f8_r006_cpu_native_preflight_runner_v1.py")
EXECUTOR = Path("scripts/f8_r006_cpu_native_preflight_execute_v1.py")
NATIVE_HELPER = Path("scripts/f8_r003_cpu_native_preflight_execute_v1.py")
GENCASE = Path("vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
DECODER = Path("campaigns/l1-resume/artifacts/bi4_dump")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(relative), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def bindings_current(value: dict[str, Any]) -> bool:
    for item in value.get("bindings", []):
        path = LAB / str(item.get("path", ""))
        if not path.is_file() or item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
            return False
    return True


def validate_predecessors() -> dict[str, Any]:
    review, materialization = load(REVIEW), load(MATERIALIZATION)
    data = materialization.get("materialized_inputs", {})
    copy = materialization.get("control_dependency_copy_proof", {})
    if not (
        review.get("schema") == design.SCHEMA
        and review.get("scope_id") == SCOPE
        and review.get("status") == "r006_static_design_review_passed_inputs_not_authorized"
        and review.get("static_constraint_gaps") == []
        and review.get("qualification_credit") == 0
        and bindings_current(review)
    ):
        raise PermissionError("F8 r006 static review is not current, passed, and zero-credit")
    if not (
        materialization.get("schema") == inputs.SCHEMA
        and materialization.get("scope_id") == SCOPE
        and materialization.get("status") == "one_time_r006_inputs_materialized_static_only"
        and materialization.get("authorization", {}).get("consumed") is True
        and materialization.get("authorization", {}).get("overwrite_or_reuse_allowed") is False
        and data.get("definition_matches_review_precommit") is True
        and data.get("control_matches_review_precommit") is True
        and materialization.get("execution_controls", {}).get("gencase_invoked") is False
        and materialization.get("execution_controls", {}).get("native_decode_invoked") is False
        and bindings_current(materialization)
    ):
        raise PermissionError("F8 r006 materialization is not current, immutable, and hash-closed")
    definition, control = data["definition"], data["control"]
    if not (
        definition.get("path") == str(inputs.DEFINITION_TARGET)
        and control.get("path") == str(inputs.CONTROL_TARGET)
        and definition.get("sha256") == sha256(LAB / inputs.DEFINITION_TARGET)
        and control.get("sha256") == sha256(LAB / inputs.CONTROL_TARGET)
        and copy.get("definition_relative_reference") == design.control_filename()
        and copy.get("required_generated_copy") == str(design.COPIED_CONTROL)
        and copy.get("required_copy_hash") == control.get("sha256")
    ):
        raise ValueError("F8 r006 materialized inputs and colocated control-copy contract do not match the static review")

    proof = materialization["definition_proof"]
    values = design.parameters()
    dp = float(values["dp"])
    nx = round(float(values["length_x"]) / dp)
    ny = round(float(values["length_y"]) / dp)
    fluid_layers = round((2.0 * float(values["half_height"])) / dp) + 1
    expected_fluid = int(nx * ny * fluid_layers)
    expected_boundary = int(8 * nx * ny)
    if not (
        proof.get("boundary_particles_expected") == expected_boundary
        and proof.get("fluid_particles_expected") == expected_fluid
        and proof.get("total_particles_expected") == expected_boundary + expected_fluid
        and proof.get("boundary_z_planes_expected_m") == [-0.075, -0.0675, -0.06, -0.0525, 0.0525, 0.06, 0.0675, 0.075]
    ):
        raise ValueError("F8 r006 materialized Definition proof does not match its frozen four-layer particle counts")
    boundary_plane_counts = {
        "-0.0750": int(nx * ny), "-0.0675": int(nx * ny), "-0.0600": int(nx * ny), "-0.0525": int(nx * ny),
        "0.0525": int(nx * ny), "0.0600": int(nx * ny), "0.0675": int(nx * ny), "0.0750": int(nx * ny),
    }
    return {
        "definition": definition,
        "control": control,
        "control_copy": copy,
        "constantsdef": proof["constantsdef"],
        "expected_wall_plane_particle_counts": boundary_plane_counts,
        "expected_hdp_surface_z_planes_m": [-0.04875, 0.04875],
        "expected_hdp_surface_points": 8,
        "expected_fixed_boundary_particles": expected_boundary,
        "expected_fluid_particles": expected_fluid,
        "expected_total_particles": expected_boundary + expected_fluid,
        "native_normal_minimum_magnitude_m": dp * 0.25,
        "native_inward_normal_z_component_minimum_m": dp * 0.25,
        "fluid_mass_kg_expected": expected_fluid * float(values["rho0"]) * dp**3,
    }


def build_authorization() -> dict[str, Any]:
    prior = validate_predecessors()
    return {
        "schema": "core.cfd.f8.r006_cpu_native_preflight_authorization.v1",
        "scope_id": SCOPE,
        "status": "authorized_for_exactly_one_r006_cpu_native_preflight",
        "authorization_basis": "user-wide exploration authorization plus the hash-closed r006 static review and input materialization",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "closed_prior_scopes": load(REVIEW)["closed_prior_execution_scopes"],
        "single_input": {
            "definition": prior["definition"], "control": prior["control"],
            "r001_r002_r003_r004_r005_inputs_or_outputs_reused": False,
            "constantsdef": prior["constantsdef"],
        },
        "control_dependency_copy": prior["control_copy"],
        "output_namespace": {
            "path": str(design.PREFLIGHT_ROOT), "must_not_exist_before_execution": True,
            "reuse_or_retry_allowed": False,
        },
        "cpu_native_entry": {
            "gencase_binary": binding(GENCASE, "official CPU GenCase binary"),
            "native_decoder": binding(DECODER, "pinned native BI4 decoder"),
            "gencase_invocation_limit": 1,
            "native_decode_invocation_limit": 1,
        },
        "hard_gates": {
            "input_constantsdef_matches_r006_contract": True,
            "input_hswl_is_explicit": True,
            "generated_colocated_control_copy_hash_matches": True,
            "generated_fixed_boundary_particles_exact": prior["expected_fixed_boundary_particles"],
            "generated_z_wall_plane_particle_counts": prior["expected_wall_plane_particle_counts"],
            "generated_hdp_surface_points_exact": prior["expected_hdp_surface_points"],
            "generated_hdp_surface_z_planes_m": prior["expected_hdp_surface_z_planes_m"],
            "generated_fluid_particles_exact": prior["expected_fluid_particles"],
            "generated_total_particles_exact": prior["expected_total_particles"],
            "native_boundary_particles_exact": prior["expected_fixed_boundary_particles"],
            "native_boundary_normal_count_exact": prior["expected_fixed_boundary_particles"],
            "native_boundary_normals_finite_and_minimum_magnitude": prior["native_normal_minimum_magnitude_m"],
            "native_boundary_inward_normal_z_component_minimum_m": prior["native_inward_normal_z_component_minimum_m"],
            "native_boundary_z_wall_plane_particle_counts": prior["expected_wall_plane_particle_counts"],
            "native_fluid_particle_count_exact": prior["expected_fluid_particles"],
            "native_fluid_mass_kg_expected": prior["fluid_mass_kg_expected"],
            "native_ids_unique_and_all_arrays_finite": True,
        },
        "permissions": {
            "cpu_gencase": True, "native_decode": True, "solver": False, "gpu": False,
            "queue": False, "worker": False, "registry": False, "ledger": False,
            "training": False, "qualification": False, "queue_mutation": 0,
            "registry_mutation": 0, "ledger_mutation": 0, "denominator_mutation": 0,
        },
        "execution_policy": {
            "exactly_one_cpu_gencase": True, "at_most_one_native_decode": True,
            "generated_geometry_and_control_gates_before_decode": True,
            "fail_closed_on_any_failure": True, "same_input_retry_forbidden": True,
            "preflight_output_reuse_forbidden": True, "zero_credit_on_failure": True,
            "no_solver_gpu_queue_worker_registry_ledger_training_or_qualification": True,
        },
        "resource_scope": {
            "cpu_only": True, "gpu": False, "queue": False,
            "gencase_timeout_seconds": 900, "native_decode_timeout_seconds": 300,
            "max_simultaneous_gencase": 1, "max_simultaneous_decoder": 1,
        },
        "bindings": [
            binding(REVIEW, "passed immutable F8 r006 static design review"),
            binding(MATERIALIZATION, "immutable F8 r006 input materialization receipt"),
            binding(inputs.DEFINITION_TARGET, "only permitted r006 Definition"),
            binding(inputs.CONTROL_TARGET, "only permitted r006 colocated acceleration control"),
            binding(GENCASE, "official CPU GenCase binary"),
            binding(DECODER, "pinned native BI4 decoder"),
            binding(Path("scripts/f8_r006_cpu_native_preflight_authorization_v1.py"), "r006 one-shot authorization builder"),
            binding(RUNNER, "r006 argv-only admission runner"),
            binding(EXECUTOR, "r006 exactly-once preflight executor"),
            binding(NATIVE_HELPER, "pinned native BI4 array decoder and CPU environment"),
            binding(Path("tests/test_f8_r006_cpu_native_preflight_v1.py"), "r006 one-shot admission and geometry gate tests"),
        ],
    }


def write_authorization(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r006 authorization: {target}")
    value = build_authorization()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


if __name__ == "__main__":
    value = write_authorization()
    print(json.dumps({key: value[key] for key in ("schema", "status", "qualification_credit", "hard_gates", "resource_scope")}, indent=2))
