from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-runtime-smoke-negative-evidence-v1.json"


def test_f2_runtime_smoke_negative_evidence_preserves_hold() -> None:
    value = json.loads(ARTIFACT.read_text())
    assert value["schema"] == "core.f2.static_full_cup.runtime_negative_evidence.v1"
    status = value["scientific_status"]
    assert status["execution_status"] == "succeeded"
    assert status["hard_integrity_pass"] is False
    assert status["T1_numerical"] is False
    assert status["candidate_scope_pass"] is False
    assert status["expansion_authorized"] is False
    assert status["registry_mutation"] == 0
    metrics = value["failure_metrics"]
    assert metrics["endpoint_violation_particle_frames"] > 0
    assert metrics["saved_chord_crossing_count"] > 0
    assert value["decision"]["preserve_failure_denominator"] == 15
    assert value["repair_budget"]["threshold_change_allowed"] is False
