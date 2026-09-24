from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_t1_metric_matrix_review_v2 as review


def test_matrix_review_receipt_matches_immutable_sources() -> None:
    receipt = review.verify_receipt()
    assert receipt["schema"] == review.SCHEMA
    assert receipt["record_id"] == review.RECORD_ID
    assert receipt["status"] == "static_implementation_review_passed_no_execution_or_t1_credit"
    assert receipt["reviewer"]["model"] == "gpt-5.6-terra"
    assert receipt["reviewer"]["reasoning_effort"] == "high"
    assert receipt["reviewer"]["verdict"] == "PASS"
    assert receipt["reviewer"]["reviewer_ran_tests"] is True
    assert receipt["reviewed_scope"]["frozen_case_denominator"] == 15
    assert receipt["reviewed_scope"]["cross_resolution_comparisons"] == 8
    assert receipt["review_boundary"]["production_bundle_read"] is False
    assert receipt["review_boundary"]["qualification_credit"] == 0


def test_matrix_review_binds_adapter_helpers_frozen_inputs_and_prior_reviews() -> None:
    receipt = review.verify_receipt()
    paths = {item["path"] for item in receipt["evidence"]}
    expected = {
        "scripts/f8_r008_t1_metric_matrix_adapter_v2.py",
        "tests/test_f8_r008_t1_metric_matrix_adapter_v2.py",
        "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v1.py",
        "scripts/f8_r008_native_fluid_table_v2.py",
        review.ARCHIVE_TEST_PATH,
        review.matrix.metric_v1.FROZEN_SCOPE_RECEIPT.relative_to(review.LAB).as_posix(),
        review.matrix.metric_v1.FROZEN_PARAMETER_CONTRACT.relative_to(review.LAB).as_posix(),
    }
    assert paths.issuperset(expected)


def test_matrix_review_records_synthetic_validation_and_separate_t1_boundary() -> None:
    receipt = review.verify_receipt()
    assert receipt["reviewer_validation"]["passed"] == 22
    assert receipt["reviewer_validation"]["failed"] == 0
    assert receipt["parent_validation"]["passed"] == 90
    assert receipt["parent_validation"]["failed"] == 0
    assert receipt["reviewed_scope"]["native_integrity_or_final_T1_adjudication"] is False
    assert "does not reopen" in " ".join(receipt["known_limitations"])


def test_matrix_review_writer_is_create_once(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    written = review.write_receipt(target)
    assert json.loads(written.read_text(encoding="utf-8")) == review.build_receipt()
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable"):
        review.write_receipt(target)
