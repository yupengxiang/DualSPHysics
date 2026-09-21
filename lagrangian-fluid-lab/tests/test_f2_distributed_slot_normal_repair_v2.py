from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_distributed_slot_normal_repair_v2 import build, verify


LAB = Path(__file__).resolve().parents[1]
NEGATIVE = LAB / "campaigns/core-v1/evidence/f2-distributed-slot-preflight-negative-evidence-v1.json"


def test_negative_evidence_binds_both_mk_zero_normal_partitions():
    evidence = json.loads(NEGATIVE.read_text())
    rows = {row["mk"]: row for row in evidence["partition"]["mk_partitions"]}
    assert rows[17]["zero_boundnor_count"] == 81818
    assert rows[18]["zero_boundnor_count"] == 42790


def test_v2_builder_creates_static_zero_credit_proposal(tmp_path):
    path = tmp_path / "proposal.json"
    value = build(path)
    assert value["revision_id"] == "F2_distributed_slot_gate_normal_layers_v2"
    assert value["matrix_credit"] == 0
    assert value["authorization_boundary"]["cpu_native_authorized"] is False
    assert verify(path)["candidate_case_id"].endswith("_v2")
