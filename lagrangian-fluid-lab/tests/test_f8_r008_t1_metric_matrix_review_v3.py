from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_t1_metric_matrix_review_v3 as review


def test_matrix_review_v3_is_final_pass_with_unverified_execution_boundary() -> None:
    receipt = review.verify_receipt()

    assert receipt["schema"] == review.SCHEMA
    assert receipt["record_id"] == review.RECORD_ID
    assert receipt["status"] == "static_implementation_review_passed_no_execution_or_t1_credit"
    assert receipt["reviewer"]["model"] == "gpt-5.6-terra"
    assert receipt["reviewer"]["reasoning_effort"] == "high"
    assert receipt["reviewer"]["verdict"] == "PASS"
    assert receipt["reviewer"]["reviewer_ran_tests"] is False
    assert [item["verdict"] for item in receipt["review_history"]] == ["REVISE", "REVISE", "PASS"]
    assert receipt["reviewed_scope"]["frozen_case_denominator"] == 15
    assert receipt["reviewed_scope"]["cross_resolution_comparisons"] == 8
    assert receipt["reviewed_scope"]["cross_field_native_semantics_verified"] is False
    assert receipt["reviewed_scope"]["execution_attempt_identity_verified"] is False
    assert receipt["reviewed_scope"]["normal_completion_verified"] is False
    assert receipt["review_boundary"]["qualification_credit"] == 0


def test_matrix_review_v3_binds_parser_matrix_and_native_writer_source() -> None:
    receipt = review.verify_receipt()
    evidence = {item["path"]: item for item in receipt["evidence"]}
    assert {
        "scripts/f8_r008_runparts_timestep_diagnostic_v1.py",
        "scripts/f8_r008_runparts_timestep_diagnostic_v2.py",
        "scripts/f8_r008_t1_metric_matrix_adapter_v2.py",
        "scripts/f8_r008_t1_metric_matrix_adapter_v4.py",
        "tests/test_f8_r008_runparts_timestep_diagnostic_v2.py",
        "tests/test_f8_r008_t1_metric_matrix_adapter_v2.py",
        "repo:src/source/JSph.cpp",
    } <= set(evidence)
    assert len(evidence) == len(receipt["evidence"])
    assert all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in evidence.values())


def test_matrix_review_v3_records_parent_validation_and_limits() -> None:
    receipt = review.verify_receipt()
    assert receipt["reviewer_validation"]["command"] is None
    assert receipt["reviewer_validation"]["passed"] == 0
    assert receipt["parent_validation"]["passed"] == 145
    assert receipt["parent_validation"]["failed"] == 0
    limitations = " ".join(receipt["known_limitations"])
    assert "not evidence" in limitations
    assert "cross-column" in limitations
    assert receipt["execution_authority"]["solver"] is False
    assert receipt["execution_authority"]["worker"] is False


def test_matrix_review_v3_writer_is_create_once(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    assert review.write_receipt(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == review.build_receipt()
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable"):
        review.write_receipt(target)
