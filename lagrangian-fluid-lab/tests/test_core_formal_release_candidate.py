"""Tests for the versioned, non-authorizing F3/F4 release candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/f3-f4-candidate.json"
CLOSURE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/source-closure.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_candidate_binds_current_closure_and_keeps_formal_gate_closed() -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    assert candidate["schema"] == "core.formal_release_candidate.v1"
    assert candidate["candidate_version"] == "core-formal-release-candidate-v4"
    assert candidate["status"] == "blocked"
    assert candidate["data_contract_ready"] is True
    assert candidate["formal_training_ready"] is False
    assert candidate["formal_release"] is False
    assert candidate["formal_job_count"] == 0
    assert candidate["diagnostic_runs_counted_as_formal"] is False
    assert candidate["blocker_codes"] == [
        "STALE_SOURCE_CLOSURE", "FORMAL_RELEASE_REQUIRED", "THIRD_FAMILY_REQUIRED",
        "VALIDATION_DENOMINATOR", "RESOURCE_FRONTIER_UNPROVEN",
    ]
    assert candidate["admission_observation"]["production_denominator"]["included_case_count"] == 64
    assert candidate["admission_observation"]["production_denominator"]["hard_integrity_pass_bound_count"] == 64
    assert candidate["admission_observation"]["production_denominator"]["structural_pass_bound_count"] == 64
    assert candidate["admission_observation"]["production_denominator"]["failure_denominator_preserved"] is True
    assert candidate["admission_observation"]["graph_probe"]["valid"] is True
    assert candidate["admission_observation"]["graph_probe"]["formal_capacity_evidence"] is False
    assert closure["complete"] is True
    assert candidate["source_closure"]["sha256"] == _sha256(CLOSURE)
    assert candidate["source_closure"]["closure_sha256"] == closure["closure_sha256"]

