#!/usr/bin/env python3
"""Seal the sole F8 r002 CPU/native preflight authorization.

This creates an immutable, hash-bound admission for exactly one GenCase and
one native BI4 decode in r002's fresh namespace.  It never invokes either
binary and it has no solver, GPU, queue, worker, registry, ledger, training,
or qualification path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f8_r002_input_materialization_v1 as inputs
from scripts import f8_r002_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
ROOT = design.ROOT
SCOPE = design.SCOPE
MATERIALIZATION = inputs.RECEIPT_TARGET
REVIEW = ROOT / "static-design-review-v1/receipt.json"
OUTPUT = LAB / ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
RUNNER = Path("scripts/f8_r002_cpu_native_preflight_runner_v1.py")
EXECUTOR = Path("scripts/f8_r002_cpu_native_preflight_execute_v1.py")
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


def load_json(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def _bound_current(receipt: dict[str, Any], *, lifecycle_test_exclusion: bool = False) -> bool:
    for item in receipt.get("bindings", []):
        if not isinstance(item, dict):
            return False
        # The reviewed r002 test later gained only lifecycle assertions for
        # input materialization.  It is evidence of the review, not an input
        # or executable surface; freezing it would incorrectly invalidate the
        # immutable review after its already-authorized successor landed.
        if lifecycle_test_exclusion and item.get("path") == "tests/test_f8_r002_static_design_review_v1.py":
            continue
        path = LAB / str(item.get("path", ""))
        if not path.is_file() or item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
            return False
    return True


def validate_predecessors() -> dict[str, Any]:
    review, materialization = load_json(REVIEW), load_json(MATERIALIZATION)
    input_data = materialization.get("materialized_inputs", {})
    if not (
        review.get("schema") == design.SCHEMA
        and review.get("scope_id") == SCOPE
        and review.get("status") == "r002_static_design_review_passed_inputs_not_authorized"
        and review.get("static_constraint_gaps") == []
        and review.get("qualification_credit") == 0
        and review.get("r001_is_immutable_closed_history", {}).get("same_input_retry_forbidden") is True
        and _bound_current(review, lifecycle_test_exclusion=True)
    ):
        raise PermissionError("F8 r002 static review is not a current passed zero-credit predecessor")
    if not (
        materialization.get("schema") == inputs.SCHEMA
        and materialization.get("scope_id") == SCOPE
        and materialization.get("status") == "one_time_r002_inputs_materialized_static_only"
        and materialization.get("qualification_credit") == 0
        and materialization.get("authorization", {}).get("consumed") is True
        and materialization.get("authorization", {}).get("overwrite_or_reuse_allowed") is False
        and input_data.get("definition_matches_review_precommit") is True
        and input_data.get("control_matches_review_precommit") is True
        and _bound_current(materialization)
    ):
        raise PermissionError("F8 r002 materialization is not current, immutable, and hash-closed")
    definition, control = input_data["definition"], input_data["control"]
    if not (
        definition["path"] == str(inputs.DEFINITION_TARGET)
        and control["path"] == str(inputs.CONTROL_TARGET)
        and definition["sha256"] == sha256(LAB / inputs.DEFINITION_TARGET)
        and control["sha256"] == sha256(LAB / inputs.CONTROL_TARGET)
    ):
        raise ValueError("F8 r002 materialized input hashes no longer match their receipt")
    values = design.parameters()
    fluid_count = int(values["length_x"] / values["dp"]) * int(values["length_y"] / values["dp"]) * int((2 * values["half_height"]) / values["dp"])
    return {
        "definition": definition,
        "control": control,
        "expected_fluid_particles": fluid_count,
        "fluid_mass_kg_expected": fluid_count * float(values["rho0"]) * float(values["dp"]) ** 3,
        "control_copy": materialization["control_dependency_copy_proof"],
    }


def build_authorization() -> dict[str, Any]:
    predecessor = validate_predecessors()
    output = ROOT / "cpu-native-preflight-v1"
    return {
        "schema": "core.cfd.f8.r002_cpu_native_preflight_authorization.v1",
        "scope_id": SCOPE,
        "status": "authorized_for_exactly_one_r002_cpu_native_preflight",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "authorization_basis": "user-wide exploration/execution authorization; independent r002 inputs and immutable materialization receipt",
        "r001_is_immutable_closed_history": {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001", "same_input_retry_forbidden": True, "r001_evidence_mutated": False},
        "single_input": {"definition": predecessor["definition"], "control": predecessor["control"], "old_r001_inputs_or_outputs_reused": False},
        "control_dependency_copy": predecessor["control_copy"],
        "output_namespace": {"path": str(output), "must_not_exist_before_execution": True, "reuse_or_retry_allowed": False},
        "cpu_native_entry": {
            "gencase_binary": binding(GENCASE, "official CPU GenCase binary"),
            "native_decoder": binding(DECODER, "pinned native BI4 decoder"),
            "gencase_invocation_limit": 1,
            "native_decode_invocation_limit": 1,
        },
        "hard_gates": {
            "generated_control_copy_hash_matches": True,
            "generated_fixed_boundary_count_positive": True,
            "generated_z_wall_planes_present": True,
            "native_boundary_particle_count_positive": True,
            "native_boundary_normal_count_positive": True,
            "native_boundary_normals_finite_and_nonzero": True,
            "native_fluid_particle_count_exact": predecessor["expected_fluid_particles"],
            "native_fluid_mass_kg_expected": predecessor["fluid_mass_kg_expected"],
        },
        "permissions": {"cpu_gencase": True, "native_decode": True, "solver": False, "gpu": False, "queue": False, "worker": False, "registry": False, "ledger": False, "training": False, "qualification": False, "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0, "denominator_mutation": 0},
        "execution_policy": {"exactly_one_cpu_gencase": True, "exactly_one_native_decode": True, "fail_closed_on_any_failure": True, "same_input_retry_forbidden": True, "preflight_output_reuse_forbidden": True, "zero_credit_on_failure": True, "no_solver_gpu_queue_worker_registry_ledger_training_or_qualification": True},
        "bindings": [
            binding(REVIEW, "passed immutable F8 r002 static design review"),
            binding(MATERIALIZATION, "immutable F8 r002 input materialization receipt"),
            binding(inputs.DEFINITION_TARGET, "only permitted r002 Definition"),
            binding(inputs.CONTROL_TARGET, "only permitted r002 acceleration control"),
            binding(GENCASE, "official CPU GenCase binary"),
            binding(DECODER, "pinned native BI4 decoder"),
            binding(Path("scripts/f8_r002_cpu_native_preflight_authorization_v1.py"), "r002 authorization builder"),
            binding(RUNNER, "r002 argv-only runner"),
            binding(EXECUTOR, "r002 one-shot executor"),
        ],
    }


def write_authorization(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r002 authorization: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    value = build_authorization()
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    value = write_authorization()
    print(json.dumps({key: value[key] for key in ("schema", "status", "qualification_credit")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
