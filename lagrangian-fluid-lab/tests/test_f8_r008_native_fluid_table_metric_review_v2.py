from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_native_fluid_table_metric_review_v2 as review


def test_metric_review_receipt_matches_immutable_sources() -> None:
    receipt = review.verify_receipt()
    assert receipt["schema"] == review.SCHEMA
    assert receipt["record_id"] == review.RECORD_ID
    assert receipt["status"] == "static_metric_implementation_review_passed_no_execution_or_t1_credit"
    assert receipt["reviewer"]["model"] == "gpt-5.6-terra"
    assert receipt["reviewer"]["reasoning_effort"] == "high"
    assert receipt["reviewer"]["verdict"] == "PASS"
    assert receipt["reviewer"]["reviewer_ran_tests"] is True
    assert receipt["review_boundary"]["production_bundle_read"] is False
    assert receipt["review_boundary"]["qualification_credit"] == 0
    assert receipt["execution_authority"]["solver"] is False


def test_metric_review_binds_v2_sources_and_reviewed_helper_dependency() -> None:
    receipt = review.verify_receipt()
    paths = {item["path"] for item in receipt["evidence"]}
    assert paths.issuperset(set(review.verifier.METRIC_CODE_PATHS.values()))
    assert paths.issuperset(set(review.TEST_PATHS))
    assert review.ARCHIVE_TEST_PATH in paths


def test_metric_review_receipt_has_parent_validation_and_explicit_limits() -> None:
    receipt = review.verify_receipt()
    assert receipt["parent_validation"]["passed"] == 14
    assert receipt["parent_validation"]["failed"] == 0
    assert receipt["reviewer_validation"]["passed"] == 14
    assert receipt["reviewer_validation"]["failed"] == 0
    assert "15-case" in " ".join(receipt["known_limitations"])
    assert "solver timestep" in " ".join(receipt["known_limitations"])


def test_review_receipt_writer_is_create_once(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    written = review.write_receipt(target)
    assert json.loads(written.read_text(encoding="utf-8")) == review.build_receipt()
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable"):
        review.write_receipt(target)
