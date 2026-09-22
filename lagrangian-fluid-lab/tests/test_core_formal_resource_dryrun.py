"""Tests for the non-formal 32000-update synthetic resource receipt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.core_formal_resource_dryrun import _load_candidate


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/f3-f4-candidate.json"
DRYRUN = ROOT / (
    "campaigns/core-v1/learning/formal-release-candidate-v1/"
    "resource-frontier-dryrun-mlp-seed17-32000.json"
)


def test_synthetic_frontier_receipt_is_exactly_32000_and_non_formal() -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    receipt = json.loads(DRYRUN.read_text(encoding="utf-8"))
    assert _load_candidate(CANDIDATE)["data_contract_ready"] is True
    assert receipt["schema"] == "core.formal_resource_dryrun.v1"
    assert receipt["status"] == "completed"
    assert receipt["dry_run"] is True
    assert receipt["formal_release"] is False
    assert receipt["formal_training"] is False
    assert receipt["formal_job_count"] == 0
    assert receipt["protocol"]["updates_completed"] == 32000
    assert receipt["protocol"]["synthetic_input"] is True
    assert receipt["execution_constraints"]["trajectory_files_opened"] is False
    assert receipt["execution_constraints"]["checkpoint_written"] is False
    assert receipt["execution_constraints"]["central_registry_mutation"] == 0
    assert receipt["execution_constraints"]["central_ledger_mutation"] == 0
    assert candidate["admission_observation"]["resource_dryrun"]["formal_capacity_evidence"] is False


def test_resource_probe_refuses_a_candidate_with_data_gate_closed(tmp_path: Path) -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    candidate["data_contract_ready"] = False
    path = tmp_path / "closed.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="schema/data gate"):
        _load_candidate(path)


def test_resource_probe_refuses_missing_production_denominator(tmp_path: Path) -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    candidate["admission_observation"].pop("production_denominator")
    path = tmp_path / "missing-denominator.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="explicit production denominator"):
        _load_candidate(path)


def test_resource_probe_refuses_zero_or_boolean_denominator_counts(tmp_path: Path) -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    denominator = candidate["admission_observation"]["production_denominator"]
    denominator["included_case_count"] = 0
    path = tmp_path / "zero-denominator.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="positive integer"):
        _load_candidate(path)

    denominator["included_case_count"] = True
    path = tmp_path / "boolean-denominator.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="positive integer"):
        _load_candidate(path)
