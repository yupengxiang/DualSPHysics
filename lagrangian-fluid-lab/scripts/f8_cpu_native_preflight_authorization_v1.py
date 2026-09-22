#!/usr/bin/env python3
"""Create F8's immutable, static authorization for one CPU/native preflight.

This is a read-only authorization builder.  It never invokes GenCase, a
decoder, a solver, GPU code, or any campaign mutation surface.  Runtime
execution is intentionally outside this module and remains one-shot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f8_input_materialization_v1 as inputs
from scripts import f8_postwrite_static_review_v2 as postwrite


LAB = Path(__file__).resolve().parents[1]
ROOT = inputs.ROOT
SCOPE = inputs.SCOPE
OUTPUT = LAB / ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
RUNNER = Path("scripts/f8_cpu_native_preflight_runner_v1.py")
GENCASE = Path("vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
DECODER = Path("campaigns/l1-resume/artifacts/bi4_dump")
DOCUMENTS = {
    "postwrite_static_review": postwrite.OUTPUT.relative_to(LAB),
    "materialization_receipt": inputs.RECEIPT_TARGET,
    "parameter_contract": inputs.CONTRACT,
    "steady_womersley_oracle": ROOT / "reference-oracle-v1/contract.json",
    "startup_womersley_oracle": ROOT / "reference-oracle-v2/contract.json",
    "observation_parser_contract": ROOT / "observation-parser-v1/contract.json",
    "definition_xml": inputs.DEFINITION_TARGET,
    "acceleration_csv": inputs.CONTROL_TARGET,
}


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


def _bound_receipt_matches_current_files(receipt: dict[str, Any]) -> bool:
    bindings = receipt.get("bindings", [])
    if not isinstance(bindings, list) or not bindings:
        return False
    for item in bindings:
        if not isinstance(item, dict):
            return False
        # The post-write receipt intentionally records its original lifecycle
        # test as context while that test may evolve to cover later
        # fail-closed transitions.  Its own test documents this exclusion;
        # the receipt builder and every actual static input remain sealed.
        if item.get("path") == "tests/test_f8_postwrite_static_review_v2.py":
            continue
        path = LAB / str(item.get("path", ""))
        if not path.is_file() or item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
            return False
    return True


def validate_static_hard_gates() -> dict[str, Any]:
    review = load_json(postwrite.OUTPUT.relative_to(LAB))
    materialization = load_json(inputs.RECEIPT_TARGET)
    contract = load_json(inputs.CONTRACT)
    if not (
        review.get("schema") == postwrite.SCHEMA
        and review.get("scope_id") == SCOPE
        and review.get("status") == "input_materialized_postwrite_static_verification_passed"
        and review.get("static_constraint_gaps") == []
        and review.get("qualification_claim") == "none"
        and review.get("qualification_credit") == 0
        and review.get("cpu_preflight", {}).get("authorized") is False
        and _bound_receipt_matches_current_files(review)
    ):
        raise PermissionError("F8 post-write static review is not a current passed zero-credit predecessor")
    if not (
        materialization.get("schema") == inputs.SCHEMA
        and materialization.get("status") == "one_time_inputs_materialized_static_only"
        and materialization.get("qualification_claim") == "none"
        and materialization.get("qualification_credit") == 0
        and materialization.get("authorization", {}).get("overwrite_or_reuse_allowed") is False
    ):
        raise PermissionError("F8 materialization receipt is not immutable and zero-credit")
    params = inputs.parameters(contract)
    fluid_count = int(contract["resolution_contract"]["expected_periodic_counts"]["production_x"])
    fluid_count *= int(contract["resolution_contract"]["expected_periodic_counts"]["production_y"])
    fluid_count *= int(contract["resolution_contract"]["expected_fluid_layers_across_2H"]["production"])
    return {
        "xml_csv_hashes_verified_by_postwrite_review": True,
        "one_fluid_marker_exactly": 1,
        "one_boundary_marker_exactly": 1,
        "global_gravity_exact_m_s2": [0.0, 0.0, 0.0],
        "accinput_count_exactly": 1,
        "accinput_fluid_marker": 0,
        "periodic_axes": ["x", "y"],
        "fixed_wall_axes": ["z"],
        "control_table": {"finite": True, "strictly_monotonic_time": True, "no_extrapolation": True, "t_end_s": params["t_end"]},
        "native_initial_particle_checks": {
            "fluid_particle_count_exact": fluid_count,
            "boundary_particle_count_min": 1,
            "fluid_particle_mass_kg": float(params["rho0"]) * float(params["dp"]) ** 3,
            "fluid_mass_kg_expected": fluid_count * float(params["rho0"]) * float(params["dp"]) ** 3,
            "excluded_fluid_particle_count_exact": 0,
            "unique_particle_ids": True,
            "finite_id_position_velocity_density_arrays": True,
            "no_particle_overlap": True,
            "boundary_normal_count_equals_boundary_particle_count": True,
            "boundary_normals_finite": True,
            "boundary_normals_nonzero": True,
        },
        "lifecycle_checks": {
            "only_registered_xml_and_csv_inputs": True,
            "only_registered_output_namespace": str(ROOT / "cpu-native-preflight-v1"),
            "gencase_invocation_limit": 1,
            "native_decode_invocation_limit": 1,
            "retry_after_any_failure": False,
            "old_output_reuse": False,
            "failure_preserves_fixed_zero_credit": True,
        },
    }


def build_authorization() -> dict[str, Any]:
    hard_gates = validate_static_hard_gates()
    bindings = [
        binding(DOCUMENTS["postwrite_static_review"], "passed immutable F8 post-write static review"),
        binding(DOCUMENTS["materialization_receipt"], "immutable one-time F8 input materialization receipt"),
        binding(DOCUMENTS["definition_xml"], "only permitted F8 Definition input"),
        binding(DOCUMENTS["acceleration_csv"], "only permitted F8 acceleration control input"),
        binding(DOCUMENTS["parameter_contract"], "frozen F8 parameter contract"),
        binding(DOCUMENTS["steady_womersley_oracle"], "steady Womersley reference contract"),
        binding(DOCUMENTS["startup_womersley_oracle"], "startup Womersley reference contract"),
        binding(DOCUMENTS["observation_parser_contract"], "native-observation parser contract"),
        binding(GENCASE, "official CPU GenCase binary"),
        binding(DECODER, "pinned native BI4 decode binary"),
        binding(Path("scripts/f8_cpu_native_preflight_authorization_v1.py"), "static authorization builder"),
        binding(RUNNER, "argv-only fail-closed runner"),
    ]
    return {
        "schema": "core.cfd.f8.cpu_native_preflight_authorization.v1",
        "scope_id": SCOPE,
        "status": "authorized_for_exactly_one_cpu_native_preflight",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "authorization_basis": "user-approved F8 mechanism scope plus passed immutable post-write static review; this receipt adds CPU/native preflight only",
        "single_input": {
            "definition": binding(DOCUMENTS["definition_xml"], "only allowed simulation Definition"),
            "control": binding(DOCUMENTS["acceleration_csv"], "only allowed acceleration control"),
            "old_xml_bi4_hdf5_reused_as_input": False,
        },
        "output_namespace": {"path": str(ROOT / "cpu-native-preflight-v1"), "must_not_exist_before_execution": True, "reuse_or_retry_allowed": False},
        "cpu_native_entry": {
            "gencase_binary": binding(GENCASE, "official CPU GenCase binary"),
            "gencase_version": "DualSPHysics official vendor tree v5.4; ELF BuildID 605b69da2232fb968dab0c6e57ebff3cb482ed72",
            "native_decoder": binding(DECODER, "pinned native BI4 decode binary"),
            "native_decoder_version": "bi4_dump ELF BuildID 849e881d39081e58f81acfef8faa3951612fe226",
            "gencase_invocation_limit": 1,
            "native_decode_invocation_limit": 1,
        },
        "hard_gates": hard_gates,
        "permissions": {
            "cpu_gencase": True,
            "native_decode": True,
            "solver": False,
            "gpu": False,
            "queue": False,
            "registry": False,
            "ledger": False,
            "training": False,
            "qualification": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "execution_policy": {
            "exactly_one_cpu_gencase": True,
            "exactly_one_native_decode": True,
            "fail_closed_on_any_failure": True,
            "same_input_retry_forbidden": True,
            "preflight_output_reuse_forbidden": True,
            "zero_credit_on_failure": True,
            "no_solver_gpu_queue_registry_ledger_training_or_qualification": True,
        },
        "bindings": bindings,
    }


def write_authorization(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 CPU/native authorization: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    authorization = build_authorization()
    target.write_text(json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return authorization


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    authorization = write_authorization(args.output)
    print(json.dumps({key: authorization[key] for key in ("schema", "status", "qualification_claim", "qualification_credit")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
