import json
from pathlib import Path

from scripts.f1_suspended_obstacle_gap_negative_evidence_v1 import SCHEMA


def test_recorded_g1_anchor_failure_is_scientific_and_zero_credit():
    path = (Path(__file__).resolve().parents[1]
            / "campaigns/core-v1/evidence/f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json")
    evidence = json.loads(path.read_text())
    assert evidence["schema"] == SCHEMA
    assert evidence["status"] == "completed_scientific_negative_anchor"
    assert evidence["qualification_claim"] == "none"
    assert evidence["matrix_credit"] == 0
    assert evidence["hard_integrity"]["requested_horizon_reached"] is True
    assert evidence["hard_integrity"]["pass"] is False
    assert evidence["event_window"]["complete"] is True
    assert evidence["execution_constraints"]["registry_mutation"] == 0
    assert evidence["execution_constraints"]["ledger_mutation"] == 0

