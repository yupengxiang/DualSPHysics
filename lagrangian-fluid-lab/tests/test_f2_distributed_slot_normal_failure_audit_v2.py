from __future__ import annotations

import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
PREFLIGHT = LAB / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/normal-repair-v2/preflight-v2/preflight.json"


def test_v2_preflight_is_hard_negative_and_zero_credit():
    value = json.loads(PREFLIGHT.read_text())
    assert value["status"] == "cpu_native_preflight_failed_hard_audit"
    assert value["preflight_pass"] is False
    assert value["matrix_credit"] == 0
    assert value["native_initial"]["zero_boundnor_count"] == 76095
