from __future__ import annotations

import json
from pathlib import Path

from scripts.f4_reconstruction_gate_fullsource_repair_receipt_v1 import build_receipt


def test_fullsource_receipt_is_zero_credit_and_binds_terminal_trace(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = root / "campaigns/core-v1/material/evidence/f4-reconstruction-gate-interval-repair-fullsource-v1/candidate-full.json"
    if not result.is_file():
        return
    output = tmp_path / "receipt.json"
    receipt = build_receipt(result, output)
    assert receipt["status"] == "completed_full_source_zero_credit_right_censored"
    assert receipt["qualification_claim"] == "none"
    assert receipt["source_window"]["committed_frame"] == 1085
    assert receipt["observed"]["contact_fraction"] == 0.0
    assert receipt["observed"]["unknown_fraction"] == 1.0
    assert receipt["execution_constraints"]["registry_mutation"] == 0
    assert json.loads(output.read_text())["T2_macro"] is False
