from __future__ import annotations

import json

import pytest

from scripts import f8_r008_per_case_provenance_implementation_review_v1 as review


def test_receipt_binds_the_terra_high_pass_to_all_three_code_sources() -> None:
    value = review.build_receipt()
    assert value["schema"] == review.SCHEMA
    assert value["record_id"] == review.RECORD_ID
    assert value["status"] == "PASS"
    assert value["reviewer"]["model"] == "gpt-5.6-terra"
    assert value["reviewer"]["reasoning_effort"] == "high"
    assert value["reviewer"]["verdict"] == "PASS"
    assert value["reviewer"]["reviewer_ran_tests"] is False
    assert set(value["code_bindings"]) == set(review.CODE_PATHS)
    assert all(binding["path"] == review.CODE_PATHS[name]
               and binding["bytes"] > 0 and len(binding["sha256"]) == 64
               for name, binding in value["code_bindings"].items())
    assert value["review_boundary"] == review.REVIEW_BOUNDARY


def test_receipt_writer_is_immutable_and_verifier_recomputes(tmp_path) -> None:
    target = tmp_path / "review.json"
    assert review.write_receipt(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == review.verify_receipt(target)
    with pytest.raises(FileExistsError, match="immutable F8 R008 implementation review"):
        review.write_receipt(target)
