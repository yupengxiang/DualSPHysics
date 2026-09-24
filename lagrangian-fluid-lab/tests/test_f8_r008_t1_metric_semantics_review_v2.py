from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r008_t1_metric_semantics_review_v2 as review


def test_terra_high_pass_freezes_only_static_semantics() -> None:
    value = review.build_receipt()
    assert value["reviewer"]["verdict"] == "PASS"
    assert value["status"] == "independent_review_passed_static_semantics_frozen"
    assert [item["verdict"] for item in value["findings"]] == ["PASS"] * 4
    assert value["disposition"]["additive_semantics_contract"] == "frozen_for_static_implementation"
    assert value["disposition"]["solver_or_worker_authorized"] is False
    assert value["disposition"]["gpu_or_queue_authorized"] is False
    assert value["qualification_credit"] == 0


def test_review_binds_verified_proposal_and_records_all_evidence() -> None:
    value = review.build_receipt()
    assert value["reviewed_proposal"]["record_id"] == "f8-r008-t1-metric-semantics-proposal-v2"
    assert value["reviewed_proposal"]["verified_bound_evidence_count"] == 82
    assert value["reviewed_proposal"]["all_bound_evidence_hashes_and_sizes_match"] is True
    assert len(value["evidence"]) == 7
    assert review.proposal.OUTPUT.as_posix().replace(str(review.LAB) + "/", "") in {
        item["path"] for item in value["evidence"]
    }


def test_review_preserves_all_execution_authority_denials() -> None:
    value = review.build_receipt()
    assert value["execution_authority"] == {
        "solver": False,
        "gpu": False,
        "worker": False,
        "queue": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
    }
    assert value["disposition"]["scope_inputs_or_thresholds_changed"] is False


def test_review_receipt_writer_is_immutable_and_verifier_recomputes(tmp_path: Path) -> None:
    target = tmp_path / "review.json"
    assert review.write_receipt(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == review.verify_receipt(target)
    with pytest.raises(FileExistsError, match="refusing to overwrite immutable F8 R008 metric review receipt"):
        review.write_receipt(target)
