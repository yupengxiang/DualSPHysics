from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.f2_submerged_orifice_preflight_v3 import (
    CASE_ID,
    DEFAULT_CONTRACT,
    DEFAULT_DEFINITION,
    DEFAULT_OUTPUT,
    DEFAULT_RECEIPT,
    _definition_contract,
    audit_decoded,
    load_json,
    verify_contract,
    verify_preflight,
)


LAB = Path(__file__).resolve().parents[1]


def test_v3_definition_contract_is_exact_and_source_closed():
    definition = _definition_contract(DEFAULT_DEFINITION)
    assert definition["case_id"] == CASE_ID
    assert definition["normal_geometry"] == {
        "outer_boxfill": "bottom | left | right | front | back",
        "gate_boxfill": "bottom | top | left | right | front | back",
        "outer_vdp": "0,1,2",
        "gate_vdp": "0,-1,-2",
    }
    assert definition["expected_source_counts_xyz"] == [86, 56, 48]
    assert definition["expected_source_particles"] == 231168
    assert definition["runtime_invoked"] is False


def test_v3_contract_binds_receipt_definition_binaries_runner_and_test():
    contract = verify_contract(DEFAULT_CONTRACT)
    assert contract["schema"] == "core.f2.submerged_orifice_transfer.cpu_native_preflight_contract.v3"
    assert contract["case_id"] == CASE_ID
    assert contract["authorized_now"] is True
    assert contract["qualification_claim"] == "none"
    assert contract["matrix_credit"] == 0
    assert contract["fresh_output"]["output_materialized"] is False
    assert contract["input_bindings"]["v3_root_review_receipt"]["path"] == str(DEFAULT_RECEIPT.resolve())
    assert contract["input_bindings"]["fresh_definition"]["path"] == str(DEFAULT_DEFINITION.resolve())
    assert contract["input_bindings"]["gencase_binary"]["sha256"]
    assert contract["input_bindings"]["native_decoder"]["sha256"]
    assert contract["input_bindings"]["v3_preflight_test"]["path"].endswith(
        "test_f2_submerged_orifice_preflight_v3.py"
    )
    permissions = contract["permissions"]
    assert permissions["cpu_gencase"] is True
    assert permissions["native_decode"] is True
    assert all(permissions[key] is False for key in (
        "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission",
    ))
    assert permissions["queue_mutation"] == 0
    assert permissions["ledger_mutation"] == 0
    assert permissions["registry_mutation"] == 0


def test_audit_decoded_preserves_all_hard_gates():
    counts = {
        "total_particles": 3,
        "boundary_particles": 1,
        "fluid_particles": 2,
        "fluid_begin": 1,
    }
    result = audit_decoded(
        ids=np.arange(3, dtype=np.uint32),
        positions=np.array([[0.0, 0.0, 0.0], [0.2, 0.1, 0.1], [1.0, 0.1, 0.1]], dtype=float),
        velocities=np.zeros((3, 3), dtype=float),
        density=np.full(3, 1000.0, dtype=float),
        boundnor=np.array([[1.0, 0.0, 0.0]], dtype=float),
        normal_size=np.array([1.0], dtype=float),
        counts=counts,
        mass_fluid_kg=48.384,
    )
    assert result["all_hard_gates_pass"] is True
    assert result["zero_boundnor_count"] == 0
    assert result["zero_normal_size_count"] == 0
    assert result["hard_gates"]["ids"]["pass"] is True
    assert result["hard_gates"]["finite"]["pass"] is True
    assert result["hard_gates"]["mass"]["pass"] is True
    assert result["hard_gates"]["endpoints"]["pass"] is True


def test_materialized_preflight_is_read_only_verified_after_one_run():
    if not DEFAULT_OUTPUT.exists():
        return
    result = verify_preflight(DEFAULT_OUTPUT)
    assert result["case_id"] == CASE_ID
    assert result["execution_controls"]["cpu_gencase_invoked"] is True
    assert result["execution_controls"]["cpu_native_decode_invoked"] is True
    assert result["execution_controls"]["solver_invoked"] is False
    assert result["execution_controls"]["gpu_invoked"] is False
    assert result["execution_controls"]["job_created"] is False
    assert result["execution_controls"]["queue_mutation"] == 0
    assert result["execution_controls"]["ledger_mutation"] == 0
    assert result["execution_controls"]["registry_mutation"] == 0
    assert result["matrix_credit"] == 0


def test_v3_runner_contract_has_no_prohibited_permissions():
    contract = load_json(DEFAULT_CONTRACT)
    text = json.dumps(contract, sort_keys=True)
    assert "normal-remediation-v2/preflight-v4" not in text
    assert contract["execution_controls"]["cpu_gencase_invoked"] is False
    assert contract["execution_controls"]["cpu_native_decode_invoked"] is False
    assert contract["execution_controls"]["solver_invoked"] is False
    assert contract["execution_controls"]["gpu_invoked"] is False
    assert contract["execution_controls"]["job_created"] is False
    assert contract["execution_controls"]["matrix_submission"] is False
    assert contract["execution_controls"]["qualification_numerator_credit"] == 0

