from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_definition_root_review_v3 import (
    CASE_ID,
    DEFAULT_BASE,
    DEFAULT_RECEIPT,
    SCHEMA,
    verify_receipt,
)


LAB = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v3_static_definition_review_is_hash_bound_but_cpu_native_closed():
    receipt = verify_receipt(DEFAULT_RECEIPT, DEFAULT_BASE)
    assert receipt["schema"] == SCHEMA
    assert receipt["decision"] == "fresh_definition_static_review_passed_cpu_native_still_closed"
    assert receipt["authorized_for_one_fresh_cpu_native_preflight"] is False
    assert receipt["case_id"] == CASE_ID
    assert receipt["static_review"]["all_hash_bindings_current"] is True
    assert receipt["static_review"]["fresh_definition_contract_pass"] is True
    assert receipt["static_review"]["fresh_definition_writer_hash_bound"] is True
    assert receipt["static_review"]["fresh_definition_runtime_invoked"] is False
    assert receipt["static_review"]["fresh_native_bi4_present"] is False
    assert receipt["static_review"]["solver_product_present"] is False
    assert len(receipt["hash_bindings"]) >= 19
    for item in receipt["hash_bindings"].values():
        assert item["sha256"]
        assert Path(item["path"]).is_file()


def test_v3_receipt_preserves_zero_credit_and_runtime_boundaries():
    receipt = _read(DEFAULT_RECEIPT)
    auth = receipt["authorization"]
    assert all(auth[key] is False for key in (
        "cpu_gencase", "native_decode", "solver_launch", "gpu_launch",
        "job_spec_creation", "matrix_submission",
    ))
    assert auth["queue_mutation"] == 0
    assert auth["ledger_mutation"] == 0
    assert auth["registry_mutation"] == 0
    assert receipt["failure_denominator"] == {
        "planned_rows": 15,
        "executed_rows": 0,
        "passed_rows": 0,
        "failed_rows": 0,
        "unattempted_rows": 15,
        "qualification_numerator": 0,
        "same_input_retry": False,
        "threshold_relaxation": False,
        "survivor_renormalization": False,
    }
    assert receipt["static_review"]["failed_anchor_zero_boundary_normals"] == 63161
    assert receipt["static_review"]["v2_boundnor_audit_zero_normals"] == 63161
    assert len(receipt["remaining_blockers"]) == 3


def test_v3_future_preflight_is_exactly_one_fresh_identity():
    receipt = _read(DEFAULT_RECEIPT)
    future = receipt["future_single_preflight_conditions"]
    assert future["fresh_definition_only"] is True
    assert future["case_id"] == CASE_ID
    assert future["q"] == 0.5
    assert future["dp_m"] == 0.0075
    assert future["cpu_gencase_only"] is True
    assert future["native_decode_only"] is True
    assert future["solver_gpu_queue_ledger_registry"] is False
    assert future["zero_normal_count_must_equal"] == 0
    assert future["qualification_credit"] == 0
