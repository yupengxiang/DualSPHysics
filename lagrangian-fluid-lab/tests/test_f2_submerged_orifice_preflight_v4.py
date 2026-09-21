from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.f2_submerged_orifice_preflight_v4 import (
    CASE_ID,
    DEFAULT_CONTRACT,
    DEFAULT_DEFINITION,
    DEFAULT_GENERATED_PREFIX,
    DEFAULT_RECEIPT,
    MASS_RELATIVE_ERROR_MAX,
    SOURCE_DENSITY_KG_M3,
    _definition_contract,
    audit_decoded,
    load_json,
    verify_contract,
)
from scripts.f2_submerged_orifice_root_review_v4 import verify as verify_receipt


def _counts() -> dict[str, int]:
    return {"total_particles": 5, "boundary_particles": 2, "fluid_particles": 3, "fluid_begin": 2}


def _decoded(*, zero_normal: bool = False) -> dict:
    boundnor = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    if zero_normal:
        boundnor[0] = 0.0
    return {
        "ids": np.arange(5, dtype=np.uint32),
        "positions": np.asarray([[0.0, 0.0, 0.0], [0.1, 0.1, 0.1], [0.1, 0.1, 0.1], [0.2, 0.2, 0.1], [0.3, 0.2, 0.1]], dtype=np.float64),
        "velocities": np.zeros((5, 3), dtype=np.float32),
        "density": np.full(5, 1000.0, dtype=np.float32),
        "boundnor": boundnor,
        "normal_size": np.linalg.norm(boundnor, axis=1).astype(np.float32),
        "counts": _counts(),
        "mass_fluid_kg": 0.64 * 0.42 * 0.36 * SOURCE_DENSITY_KG_M3 / 3.0,
    }


def test_v4_runner_binds_new_receipt_definition_and_signed_recipe():
    receipt = verify_receipt(DEFAULT_RECEIPT)
    definition = _definition_contract(DEFAULT_DEFINITION)
    assert receipt["authorized_case_id"] == CASE_ID
    assert receipt["authorization"]["cpu_gencase"] is True
    assert receipt["authorization"]["native_decode"] is True
    assert receipt["matrix_credit"] == 0
    assert definition["case_id"] == CASE_ID
    assert definition["normal_geometry"]["outer_layers_vdp"] == "0,-1,-2"
    assert definition["normal_geometry"]["gate_layers_vdp"] == "0,1,2"
    assert definition["source_lattice"]["draw_size_m"] == [0.6375, 0.4125, 0.3525]


def test_v4_contract_is_exact_one_cpu_native_and_runtime_closed():
    contract = verify_contract(DEFAULT_CONTRACT)
    assert contract["case_id"] == CASE_ID
    assert contract["authorized_now"] is True
    assert contract["status"] == "authorized_one_cpu_native_preflight_pending"
    assert contract["permissions"]["cpu_gencase"] is True
    assert contract["permissions"]["native_decode"] is True
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        assert contract["permissions"][key] is False
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        assert contract["permissions"][key] == 0
    assert contract["gate_evaluation"]["status"] == "not_run"
    assert contract["matrix_credit"] == 0
    assert contract["denominator"]["planned_rows"] == 15
    assert contract["denominator"]["qualification_numerator"] == 0
    # Contract verification is allowed after the one-shot run; the output
    # directory is now immutable evidence rather than a new execution.
    assert DEFAULT_GENERATED_PREFIX.parent.is_dir()
    assert (DEFAULT_GENERATED_PREFIX.parent / "preflight.json").is_file()
    assert contract["input_bindings"]["gencase_binary"]["sha256"]
    assert contract["input_bindings"]["native_decoder"]["sha256"]
    assert contract["input_bindings"]["v4_static_contract"]["path"].endswith("root-review-only-contract-v4.json")


def test_v4_native_hard_audit_keeps_all_hard_gates():
    passing = audit_decoded(**_decoded())
    assert passing["all_hard_gates_pass"] is True
    assert passing["zero_boundnor_count"] == 0
    assert passing["zero_normal_size_count"] == 0
    assert passing["ids_match_generated_xml"] is True
    assert passing["arrays_finite"] is True
    assert passing["hard_gates"]["mass"]["max_relative_error"] == MASS_RELATIVE_ERROR_MAX
    failing = audit_decoded(**_decoded(zero_normal=True))
    assert failing["all_hard_gates_pass"] is False
    assert failing["zero_boundnor_count"] == 1
    assert failing["zero_normal_size_count"] == 1


def test_v4_contract_contains_no_prohibited_runtime_or_credit():
    contract = load_json(DEFAULT_CONTRACT)
    text = json.dumps(contract, sort_keys=True).lower()
    assert "normal-remediation-v2/preflight-v4" not in text
    assert "normal-remediation-v3/preflight-v3" not in text
    controls = contract["execution_controls"]
    assert controls["cpu_gencase_invoked"] is False
    assert controls["cpu_native_decode_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["job_created"] is False
    assert controls["queue_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["matrix_submission"] is False
    assert controls["qualification_numerator_credit"] == 0
