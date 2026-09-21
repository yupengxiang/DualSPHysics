from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_normal_remediation_root_review_v3 import (
    CASE_ID,
    DEFAULT_AUDIT,
    DEFAULT_CANDIDATE,
    DEFAULT_CONTRACT,
    DEFAULT_DEFINITION,
    DEFAULT_PREFLIGHT,
    DEFAULT_RECEIPT,
    DEFAULT_OUTPUT_PREFIX,
    ROOT_REVIEW_TEST,
    verify_receipt,
)


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_v3_root_review_receipt_rehashes_all_inputs_and_authorizes_only_cpu_native():
    receipt = verify_receipt(DEFAULT_RECEIPT)
    assert receipt["authorized_for_one_fresh_cpu_native_preflight"] is True
    assert receipt["authorized_case_id"] == CASE_ID
    assert receipt["authorized_matrix_index"] == 4
    auth = receipt["authorization"]
    assert auth["cpu_gencase"] is True
    assert auth["native_decode"] is True
    assert all(auth[key] is False for key in (
        "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission",
    ))
    assert auth["queue_mutation"] == 0
    assert auth["ledger_mutation"] == 0
    assert auth["registry_mutation"] == 0
    assert receipt["matrix_credit"] == 0
    assert receipt["qualification_claim"] == "none"
    assert receipt["execution_controls"]["cpu_gencase_invoked"] is False
    assert receipt["execution_controls"]["native_decoder_invoked"] is False
    assert receipt["execution_controls"]["solver_invoked"] is False
    assert receipt["execution_controls"]["gpu_invoked"] is False
    assert receipt["execution_controls"]["job_created"] is False
    # The receipt is issued before the exact-one run.  Once that authorized
    # run has completed, verification remains read-only and the immutable
    # output may be present; the receipt itself must still record the fresh
    # prefix at authorization time.
    assert receipt["case"]["output_prefix_unmaterialized"] is True
    if DEFAULT_OUTPUT_PREFIX.exists():
        assert (DEFAULT_OUTPUT_PREFIX.parent / "preflight.json").is_file()


def test_v3_root_review_binds_fresh_definition_and_all_parent_closure():
    receipt = _read(DEFAULT_RECEIPT)
    bindings = receipt["hash_bindings"]
    expected = {
        "v4_preflight_evidence": DEFAULT_PREFLIGHT,
        "v4_boundnor_failure_audit": DEFAULT_AUDIT,
        "v3_candidate": DEFAULT_CANDIDATE,
        "v3_fresh_definition": DEFAULT_DEFINITION,
        "v3_static_contract": DEFAULT_CONTRACT,
        "v3_root_review_test": ROOT_REVIEW_TEST,
    }
    for key, path in expected.items():
        assert Path(bindings[key]["path"]).resolve() == Path(path).resolve()
        assert bindings[key]["sha256"]
        assert bindings[key]["bytes"] == Path(path).stat().st_size
    for key in (
        "parent_fixed_matrix", "parent_failure_denominator", "parent_lineage",
        "parent_root_contract", "v3_writer_adapter", "v4_failure_audit_adapter",
        "v3_contract_test", "scope_adapter", "scope_test", "v3_root_review_adapter",
    ):
        assert key in bindings
        assert len(bindings[key]["sha256"]) == 64
    assert receipt["hash_review"]["all_bindings_current"] is True
    assert receipt["hash_review"]["parent_matrix_rows"] == 15
    assert receipt["hash_review"]["parent_denominator_credit"] == 0
    assert receipt["hash_review"]["v4_failure_audit_zero_boundnor"] == 64899
    assert receipt["hash_review"]["v4_failure_audit_gate_mk18_zero_boundnor"] == 0
    assert receipt["preflight_requirements"]["zero_boundnor_count_required"] == 0
    assert receipt["preflight_requirements"]["zero_normal_size_count_required"] == 0
    assert receipt["preflight_requirements"]["native_mass_relative_error_max"] == 0.025


def test_v3_root_review_receipt_contains_no_failed_native_input_path_or_credit():
    receipt = _read(DEFAULT_RECEIPT)
    text = json.dumps(receipt, sort_keys=True).lower()
    assert ".bi4" not in text
    assert receipt["execution_controls"]["qualification_numerator_credit"] == 0
    assert receipt["preflight_requirements"]["qualification_credit"] == 0
    assert receipt["case"]["failed_definition_reused"] is False
    assert receipt["case"]["failed_native_input_reused"] is False
    assert receipt["case"]["trajectory_reused"] is False
