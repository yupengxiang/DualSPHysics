from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_normal_remediation_root_review_v2 import (
    DEFAULT_BASE,
    DEFAULT_RECEIPT,
    REMEDIATION_CASE_ID,
    SCHEMA,
    verify_receipt,
)


LAB = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v2_root_review_receipt_is_hash_bound_and_closed():
    receipt = verify_receipt(DEFAULT_RECEIPT, DEFAULT_BASE)
    assert receipt["schema"] == SCHEMA
    assert receipt["decision"] == "not_authorized_pending_fresh_definition_writer"
    assert receipt["authorized_for_one_fresh_cpu_native_preflight"] is False
    assert receipt["authorized_case_id"] == REMEDIATION_CASE_ID
    assert receipt["hash_review"]["all_bindings_current"] is True
    assert receipt["hash_review"]["parent_matrix_rows"] == 15
    assert receipt["hash_review"]["parent_matrix_all_not_started"] is True
    assert receipt["hash_review"]["parent_denominator_credit"] == 0
    assert receipt["hash_review"]["parent_lineage_source_reuse"] is False
    assert receipt["hash_review"]["failed_anchor_preflight_pass"] is False
    assert receipt["hash_review"]["failed_anchor_zero_boundary_normals"] == 63161
    assert receipt["hash_review"]["v2_boundnor_audit_zero_normals"] == 63161
    assert len(receipt["hash_bindings"]) >= 17
    for item in receipt["hash_bindings"].values():
        assert item["sha256"]
        assert Path(item["path"]).is_file()


def test_v2_root_review_keeps_runtime_and_protected_state_closed():
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
    assert len(receipt["blockers"]) == 4
    assert receipt["execution_controls"]["solver_invoked"] is False
    assert receipt["execution_controls"]["gpu_invoked"] is False


def test_receipt_requires_fresh_definition_writer_before_cpu_native_review():
    receipt = _read(DEFAULT_RECEIPT)
    blockers = " ".join(receipt["blockers"])
    assert "fresh literal Definition writer" in blockers
    assert "fresh generated XML" in blockers
    assert receipt["future_single_preflight_conditions"]["fresh_definition_required"] is True
    assert receipt["future_single_preflight_conditions"]["zero_normal_count_must_equal"] == 0
    assert receipt["future_single_preflight_conditions"]["qualification_credit"] == 0
