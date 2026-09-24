from __future__ import annotations

import json

import pytest

from scripts import f8_r008_per_case_provenance_implementation_review_v2 as review


def test_v2_receipt_binds_final_terra_high_pass_to_current_sources() -> None:
    value = review.verify_receipt()
    assert value["schema"] == review.SCHEMA
    assert value["record_id"] == review.RECORD_ID
    assert value["status"] == "PASS"
    assert value["reviewer"]["model"] == "gpt-5.6-terra"
    assert value["reviewer"]["reasoning_effort"] == "high"
    assert value["reviewer"]["agent_id"] == "01a0d24d-50f6-78a2-8ab3-8943a9e48cda"
    assert value["reviewer"]["verdict"] == "PASS"
    assert value["reviewer"]["reviewer_ran_tests"] is False
    assert set(value["code_bindings"]) == set(review.CODE_PATHS)


def test_v2_receipt_is_immutable() -> None:
    before = review.OUTPUT.read_bytes()
    with pytest.raises(FileExistsError, match="immutable F8 R008 v2 implementation review"):
        review.write_receipt()
    assert review.OUTPUT.read_bytes() == before
    assert json.loads(before) == review.verify_receipt()
