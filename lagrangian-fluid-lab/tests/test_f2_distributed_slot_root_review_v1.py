from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f2_distributed_slot_root_review_v1 as review


LAB = Path(__file__).resolve().parents[1]
PROPOSAL = review.DEFAULT_PROPOSAL


def test_distributed_slot_proposal_is_static_and_hash_closed():
    proposal = review.verify_proposal(PROPOSAL)
    assert proposal["scope_id"] == "F2_distributed_submerged_slot_transfer_x_v1"
    assert proposal["qualification_claim"] == "none"
    assert proposal["matrix_credit"] == 0


def test_root_review_receipt_authorizes_only_cpu_native(tmp_path):
    receipt_path = tmp_path / "root-review.json"
    receipt = review.build_receipt(PROPOSAL, receipt_path)
    assert receipt["review_decision"]["authorized_solver"] is False
    assert receipt["review_decision"]["authorized_gpu"] is False
    assert receipt["execution_constraints"]["queue_mutation"] == 0
    assert receipt["denominator"]["qualification_credit"] == 0
    assert json.loads(receipt_path.read_text())["schema"] == "core.f2.distributed_slot_transfer.root_review_receipt.v1"


def test_review_rejects_relaxed_zero_gate(tmp_path):
    altered = json.loads(PROPOSAL.read_text())
    altered["cpu_native_preflight_gate"]["zero_boundnor_count_max"] = 1
    path = tmp_path / "altered.json"
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="zero-integrity"):
        review.verify_proposal(path)


def test_historical_proposal_is_retained_as_a_stale_snapshot():
    assert review.HISTORICAL_PROPOSAL.exists()
    assert review.HISTORICAL_OUTPUT.exists()
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        review.verify_proposal(review.HISTORICAL_PROPOSAL)
