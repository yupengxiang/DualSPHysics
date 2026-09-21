from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-negative-evidence-v1.json"


def test_h1_canary_is_a_negative_result_and_does_not_expand_scope() -> None:
    value = json.loads(ARTIFACT.read_text())
    assert value["schema"] == "core.f2.static_full_cup.runtime_negative_evidence.v1"
    assert value["hypothesis_class"] == "H1_boundary_formulation_only"
    status = value["scientific_status"]
    assert status["execution_status"] == "succeeded"
    assert status["hard_integrity_pass"] is False
    assert status["T1_numerical"] is False
    assert status["candidate_scope_pass"] is False
    assert status["expansion_authorized"] is False
    assert status["registry_mutation"] == 0
    metrics = value["failure_metrics"]
    assert metrics["endpoint_violation_particle_frames"] == 10433
    assert metrics["saved_chord_crossing_count"] == 1263
    assert value["decision"]["preserve_failure_denominator"] == 15
    assert value["repair_budget"]["used_hypothesis_classes"] == 1
    assert value["repair_budget"]["threshold_change_allowed"] is False


def test_h1_improvement_does_not_change_the_hard_gate() -> None:
    comparison = json.loads(ARTIFACT.read_text())["comparison_to_previous_dbc_smoke"]
    assert comparison["endpoint_frames_reduced"] is True
    assert comparison["hard_integrity_restored"] is False
