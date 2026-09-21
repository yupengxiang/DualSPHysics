from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_submerged_orifice_preflight_contract_v3 import (
    CASE_ID,
    DEFAULT_OUTPUT,
    build_contract,
    verify_contract,
)


def test_v3_contract_is_proposal_only_and_hash_bound():
    contract = verify_contract(DEFAULT_OUTPUT)
    assert contract["status"] == "proposal_only_cpu_native_closed"
    assert contract["case_id"] == CASE_ID
    assert contract["proposal_only"] is True
    assert contract["authorized_now"] is False
    assert contract["execution_closed"] is True
    assert set(contract["hard_gates"]) == {
        "zero_boundnor", "normal_size", "ids", "finite", "mass", "endpoints",
    }
    assert all(gate["status"] == "pending_fresh_cpu_native_preflight"
               for gate in contract["hard_gates"].values())
    assert all(gate.get("observed") is None for gate in contract["hard_gates"].values()
               if "observed" in gate)
    assert contract["input_bindings"]["v3_root_review_receipt"]["sha256"]
    assert contract["input_bindings"]["fresh_definition"]["sha256"]
    assert contract["input_bindings"]["fresh_definition_contract"]["sha256"]
    assert contract["fresh_output"]["generated_prefix"].endswith(CASE_ID)
    assert contract["fresh_output"]["output_materialized"] is False


def test_v3_contract_keeps_all_runtime_permissions_closed():
    contract = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    permissions = contract["permissions"]
    assert all(permissions[key] is False for key in (
        "cpu_gencase", "native_decode", "solver_launch", "gpu_launch",
        "job_spec_creation", "matrix_submission",
    ))
    assert all(permissions[key] == 0 for key in (
        "queue_mutation", "ledger_mutation", "registry_mutation",
    ))
    assert permissions["qualification_numerator_credit"] == 0


def test_v3_builder_does_not_materialize_generated_products(tmp_path: Path):
    output = tmp_path / "preflight-contract-v3.json"
    contract = build_contract(output=output)
    assert output.is_file()
    assert not Path(contract["fresh_output"]["expected_generated_xml"]).exists()
    assert not Path(contract["fresh_output"]["expected_native_bi4"]).exists()
    assert verify_contract(output)["matrix_credit"] == 0


def test_v3_verifier_rejects_open_permission(tmp_path: Path):
    output = tmp_path / "preflight-contract-v3.json"
    build_contract(output=output)
    value = json.loads(output.read_text(encoding="utf-8"))
    value["permissions"]["solver_launch"] = True
    output.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="opened permission"):
        verify_contract(output)
