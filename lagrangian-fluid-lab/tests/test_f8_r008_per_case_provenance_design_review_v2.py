from __future__ import annotations

import json

import pytest

from scripts import f8_r008_per_case_provenance_design_review_v2 as review


def test_archive_records_terra_high_static_design_pass_and_open_prerequisites() -> None:
    value = review.build_receipt()
    assert value["reviewer"]["model"] == "gpt-5.6-terra"
    assert value["reviewer"]["reasoning_effort"] == "high"
    assert value["reviewer"]["verdict"] == "PASS"
    assert value["reviewer"]["reviewer_ran_tests"] is False
    assert "same Terra High agent" in value["reviewer"]["review_thread_note"]
    assert len(value["findings"]) == 5
    assert all(item["verdict"] == "PASS" for item in value["findings"])
    assert len(value["remaining_prerequisites"]) == 3
    assert "st_nlink == 1" in value["remaining_prerequisites"][1]
    assert value["qualification_credit"] == 0
    assert all(value["execution_authority"][key] is False
               for key in ("gencase", "native_decode", "solver", "worker", "gpu", "queue"))


def test_review_archive_binds_exact_v2_and_relevant_sources() -> None:
    value = review.build_receipt()
    assert value["reviewed_proposal"]["path"] == review.DESIGN_V2.as_posix()
    assert value["reviewed_proposal"]["sha256"] == review.sha256(review.LAB / review.DESIGN_V2)
    by_role = {item["role"]: item for item in value["evidence"]}
    assert by_role["native BI4 decoder binary; hash-bound but not executed or reverse-engineered"]["path"].endswith("campaigns/l1-resume/artifacts/bi4_dump")
    assert by_role["current immutable readiness audit receipt"]["path"].endswith("t1-execution-readiness-audit-v4/receipt.json")
    assert all(item["bytes"] > 0 and len(item["sha256"]) == 64 for item in value["evidence"])


def test_review_archive_parent_validation_is_scoped_to_static_control_contract() -> None:
    value = review.build_receipt()
    assert value["parent_validation"]["passed"] == 15
    assert value["parent_validation"]["failed"] == 0
    assert "no native tools invoked" in value["parent_validation"]["scope_note"]


def test_review_archive_writer_is_immutable_and_verifier_recomputes(tmp_path) -> None:
    target = tmp_path / "review.json"
    assert review.write_receipt(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == review.verify_receipt(target)
    with pytest.raises(FileExistsError, match="immutable F8 R008 provenance design review"):
        review.write_receipt(target)
