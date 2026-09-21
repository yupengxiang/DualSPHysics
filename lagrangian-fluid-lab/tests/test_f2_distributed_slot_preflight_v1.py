from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_distributed_slot_preflight_v1 import generated_counts, gate_frame_mask


LAB = Path(__file__).resolve().parents[1]


def test_gate_frame_mask_keeps_both_slot_openings():
    points = __import__("numpy").array([
        [0.83, 0.20, 0.10],
        [0.83, 0.30, 0.10],
        [0.83, 0.40, 0.10],
        [0.83, 0.20, 0.30],
    ])
    assert gate_frame_mask(points).tolist() == [False, True, False, True]


def test_root_review_keeps_zero_credit_and_no_solver():
    review = json.loads((LAB / "campaigns/core-v1/cfd/f2-distributed-slot-root-review-v1.json").read_text())
    assert review["review_decision"]["authorized_solver"] is False
    assert review["execution_constraints"]["qualification_credit"] == 0
