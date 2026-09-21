from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_distributed_slot_normal_root_review_v2 import build, verify_proposal


LAB = Path(__file__).resolve().parents[1]
PROPOSAL = LAB / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/normal-repair-v2/distributed-slot-normal-repair-proposal-v2.json"


def test_v2_proposal_is_hash_closed_and_static():
    value = verify_proposal(PROPOSAL)
    assert value["revision_id"] == "F2_distributed_slot_gate_normal_layers_v2"
    assert value["authorization_boundary"]["cpu_native_authorized"] is False


def test_v2_root_review_only_authorizes_preflight(tmp_path):
    receipt = build(tmp_path / "review.json", PROPOSAL)
    assert receipt["review_decision"]["authorized_solver"] is False
    assert receipt["review_decision"]["authorized_gpu"] is False
    assert receipt["execution_constraints"]["qualification_credit"] == 0
