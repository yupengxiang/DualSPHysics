from __future__ import annotations

import json

from scripts.f9_root_admission_proposal_v1 import OUTPUT, build_proposal


def test_f9_root_admission_proposal_is_static_and_non_authorizing() -> None:
    proposal = build_proposal()
    assert proposal["status"] == "proposal_only_waiting_for_root_decision"
    assert proposal["third_t1_family_candidate"] is True
    assert proposal["admission_granted"] is False
    assert proposal["qualification_credit"] == 0
    assert proposal["execution_controls"]["native_preflight"] is False
    assert proposal["execution_controls"]["t1_registration"] is False
    assert proposal["execution_controls"]["formal_training_admission"] is False


def test_committed_f9_root_admission_proposal_is_hash_bound() -> None:
    assert OUTPUT.is_file()
    proposal = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert proposal["status"] == "proposal_only_waiting_for_root_decision"
    assert len(proposal["evidence"]) == 5
    assert all(len(item["sha256"]) == 64 for item in proposal["evidence"])
