from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
ROOT_REVIEW = LAB / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/normal-repair-v2/root-review-v2.json"


def test_v2_review_is_cpu_native_only():
    review = json.loads(ROOT_REVIEW.read_text())
    assert review["review_decision"]["authorized_solver"] is False
    assert review["review_decision"]["authorized_gpu"] is False
    assert review["execution_constraints"]["qualification_credit"] == 0
