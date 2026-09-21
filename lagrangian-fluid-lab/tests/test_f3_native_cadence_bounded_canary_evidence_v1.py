import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
EVIDENCE = BASE / "campaigns/core-v1/material/evidence/f3-native-cadence-bounded-canary-evidence-v1.json"
REVIEW = BASE / "campaigns/core-v1/material/evidence/f3-native-cadence-adapter-v1-root-review-20260920.json"


def test_recovered_f3_cadence_canary_remains_diagnostic_only():
    evidence = json.loads(EVIDENCE.read_text())
    review = json.loads(REVIEW.read_text())
    assert evidence["status"] == "completed_recovered_bounded_diagnostic"
    assert evidence["qualification_claim"] == "none"
    assert evidence["matrix_credit"] == 0
    assert evidence["execution"]["resume"] is True
    assert evidence["execution"]["committed_frames"] == 5
    assert evidence["execution"]["full_event_window"] is False
    assert evidence["constraints"]["registry_mutation"] == 0
    assert review["authorization"]["gpu_launch"] is False
    assert review["execution_policy"]["recovery_required"] is True

