from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f8_r008_syscall_policy_contract_v1 as contract


def _complete_synthetic_candidate() -> dict:
    value = copy.deepcopy(contract.build_template())
    for row in value["policy"]["rows"]:
        number = row["syscall_number"]
        row["disposition"] = "deny_errno"
        row["predicate"] = {
            "language": contract.PREDICATE_LANGUAGE,
            "expression": f"raw_nr == {number}",
            "source_refs": ["synthetic-policy-source.txt"],
        }
    value["target_kernel"] = {
        "pin_status": "declared_static_pin",
        "release": "synthetic-6.8-target",
        "source_commit": "a" * 40,
        "source_tree_sha256": "b" * 64,
        "uapi_sha256": "c" * 64,
        "build_id": "synthetic-kernel-build",
    }
    value["target_kernel_config"] = {
        "pin_status": "declared_static_pin",
        "config_ref": "synthetic/kernel.config",
        "config_sha256": "d" * 64,
        "required_options": [
            {"name": "CONFIG_SECCOMP", "value": "y"},
            {"name": "CONFIG_X86_X32_ABI", "value": "n"},
        ],
    }
    value["policy_state"] = contract._derive_policy_state(value)
    value["contract_state"] = contract._expected_static_state(value)
    return value


def test_template_binds_all_static_inputs_and_stays_unclassified() -> None:
    value = contract.build_template()
    checked = contract.validate_contract(value)
    assert checked["schema"] == contract.SCHEMA
    assert checked["status"] == contract.STATUS
    assert checked["policy"]["row_count"] == 462
    assert len(checked["policy"]["rows"]) == 462
    assert checked["policy_state"]["unclassified_rows"] == 462
    assert checked["policy_state"]["per_number_dispositions_complete"] is False
    assert checked["policy_state"]["per_number_predicates_complete"] is False
    assert checked["policy_state"]["target_kernel_build_pinned"] is False
    assert checked["policy_state"]["target_kernel_config_pinned"] is False
    assert checked["bindings"]["selector_domain"]["raw_nr_partition_complete"] is True
    assert checked["bindings"]["source_audit"]["target_kernel_source_pinned"] is False
    assert checked["authorization"]["diagnostic_only"] is True
    assert checked["authorization"]["capability_minted"] is False
    assert checked["authorization"]["formal_admission"] is False


def test_complete_static_candidate_requires_every_row_and_both_target_pins() -> None:
    value = _complete_synthetic_candidate()
    checked = contract.validate_contract(value)
    assert checked["contract_state"] == "complete_static_contract_not_runtime_verified"
    assert checked["policy_state"]["per_number_dispositions_complete"] is True
    assert checked["policy_state"]["per_number_predicates_complete"] is True
    assert checked["policy_state"]["target_kernel_build_pinned"] is True
    assert checked["policy_state"]["target_kernel_config_pinned"] is True
    assert checked["policy_state"]["runtime_conformance_verified"] is False
    assert checked["policy_state"]["readiness_pass"] is False
    assert checked["policy_state"]["qualification_credit"] == 0


def test_partial_rows_cannot_claim_complete_policy() -> None:
    value = _complete_synthetic_candidate()
    value["policy"]["rows"][17]["predicate"] = None
    value["policy_state"]["per_number_predicates_complete"] = True
    with pytest.raises(contract.SyscallPolicyContractError, match="policy-state completeness"):
        contract.validate_contract(value)


def test_unassigned_hole_cannot_be_allowlisted() -> None:
    value = _complete_synthetic_candidate()
    hole = next(row for row in value["policy"]["rows"] if row["number_state"] == "unassigned_hole")
    hole["disposition"] = "static_allow_nonmutating"
    value["policy_state"] = contract._derive_policy_state(value)
    with pytest.raises(contract.SyscallPolicyContractError, match="unassigned holes"):
        contract.validate_contract(value)


def test_target_config_pin_requires_x32_option_and_sorted_unique_rows() -> None:
    value = _complete_synthetic_candidate()
    value["target_kernel_config"]["required_options"] = [{"name": "CONFIG_SECCOMP", "value": "y"}]
    with pytest.raises(contract.SyscallPolicyContractError, match="CONFIG_X86_X32_ABI"):
        contract.validate_contract(value)

    value = _complete_synthetic_candidate()
    value["target_kernel_config"]["required_options"] = [
        {"name": "CONFIG_X86_X32_ABI", "value": "n"},
        {"name": "CONFIG_X86_X32_ABI", "value": "n"},
    ]
    with pytest.raises(contract.SyscallPolicyContractError, match="sort unique"):
        contract.validate_contract(value)


def test_predicates_reject_wildcards_and_noncanonical_source_refs() -> None:
    value = _complete_synthetic_candidate()
    value["policy"]["rows"][0]["predicate"]["expression"] = "any"
    with pytest.raises(contract.SyscallPolicyContractError, match="explicit"):
        contract.validate_contract(value)

    value = _complete_synthetic_candidate()
    value["policy"]["rows"][0]["predicate"]["source_refs"] = ["../source.txt"]
    with pytest.raises(contract.SyscallPolicyContractError, match="canonical relative"):
        contract.validate_contract(value)


def test_binding_tampering_cannot_be_rehashed_into_a_new_policy() -> None:
    value = contract.build_template()
    value["bindings"]["source_baseline"]["native_rows_sha256"] = "0" * 64
    with pytest.raises(contract.SyscallPolicyContractError, match="binding differs"):
        contract.validate_contract(value)


def test_authorization_boundary_cannot_be_promoted() -> None:
    value = _complete_synthetic_candidate()
    value["authorization"]["capability_minted"] = True
    with pytest.raises(contract.SyscallPolicyContractError, match="cannot mint"):
        contract.validate_contract(value)


def test_fixed_template_roundtrip_and_strict_json_rejection(tmp_path: Path) -> None:
    target = tmp_path / "contract.json"
    target.write_text(json.dumps(contract.build_template()), encoding="utf-8")
    assert contract.verify_output(target)["record_id"] == contract.RECORD_ID

    target.write_bytes(b'{"schema":"one","schema":"two"}')
    with pytest.raises(contract.SyscallPolicyContractError, match="duplicate JSON object key"):
        contract.verify_output(target)

    target.write_bytes(b'{"schema":NaN}')
    with pytest.raises(contract.SyscallPolicyContractError, match="non-standard JSON constant"):
        contract.verify_output(target)


def test_checked_in_template_remains_zero_credit() -> None:
    value = contract.verify_output()
    assert value["contract_state"] == "incomplete_static_template"
    assert value["policy_state"]["readiness_pass"] is False
    assert value["policy_state"]["T1_numerical"] is False
    assert value["policy_state"]["qualification_credit"] == 0
