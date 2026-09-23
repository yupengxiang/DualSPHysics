from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f8_r002_static_design_review_v2 as review_module


ROOT = Path(__file__).resolve().parents[1]


def test_fresh_review_identifies_the_retained_hswl_failure() -> None:
    review = review_module.build_review()
    assert review["status"] == "r002_static_design_review_v2_failed_scope_closed_no_retry"
    assert review["scope_id"] == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"
    assert review["constants_compatibility"]["engine_confirmed_required_field"] == "hswl"
    assert "hswl" in review["constants_compatibility"]["missing_from_r002_definition"]
    assert review["constants_compatibility"]["engine_log_explicitly_rejects_r002"] is True
    finding_ids = {finding["id"] for finding in review["static_constraint_gaps"]}
    assert "R002_GENCASE_REQUIRED_HSWL_MISSING" in finding_ids
    assert review["qualification_credit"] == 0
    assert review["independent_review"]["verdict"] == "FAIL_static_GenCase_readiness"


def test_static_inputs_are_structurally_reviewed_without_repair_or_execution() -> None:
    review = review_module.build_review()
    assert review["definition_control_audit"]["control_reference_matches_expected_r002_path"] is True
    assert review["definition_control_audit"]["acceleration_table"]["valid"] is True
    assert review["definition_control_audit"]["finite_z_wall_markers_present"] is True
    assert review["retained_execution_evidence"]["r002_preflight_status"] == "cpu_gencase_or_control_copy_failed_hard_audit"
    assert review["retained_execution_evidence"]["native_decode_invoked"] is False
    assert review["retained_execution_evidence"]["solver_invoked"] is False
    assert review["retained_execution_evidence"]["r001_same_input_retry_forbidden"] is True
    assert review["retained_execution_evidence"]["r002_same_input_retry_forbidden"] is True
    assert all(value is False for key, value in review["execution_controls"].items() if key.endswith(("written", "invoked", "started")))
    assert all(review["execution_controls"][key] == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "qualification_credit"))


def test_review_bindings_match_exact_current_bytes() -> None:
    review = review_module.build_review()
    for item in review["bindings"]:
        path = ROOT / item["path"]
        payload = path.read_bytes()
        assert len(payload) == item["bytes"]
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]


def test_review_receipt_is_exclusive_and_immutable(tmp_path: Path) -> None:
    target = tmp_path / "review" / "receipt.json"
    first = review_module.write_review(target)
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == first["status"]
    with pytest.raises(FileExistsError, match="immutable F8 R002 static review v2"):
        review_module.write_review(target)
