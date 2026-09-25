"""Regression tests for the proposal-only formal launch contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from scripts.core_formal_launch_contract import _load_json, build_contract, main


ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "campaigns/core-v1/learning/core-formal-readiness-audit-20260921.json"
PHASE_PLAN = ROOT / "campaigns/core-v1/learning/core-phase-plan-denominator-audit-20260921.json"
PROFILE = ROOT / "campaigns/core-v1/learning/backward-resource-measurements.json"
RESOURCE_PLAN = ROOT / "campaigns/core-v1/learning/integration-pilot-resource-plan.json"
SOURCE_CLOSURE = ROOT / "campaigns/core-v1/learning/formal-release-candidate-v4/source-closure.json"
REGISTRY = ROOT / "campaigns/core-v1/registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract() -> dict:
    return build_contract(
        data_root=ROOT,
        readiness=READINESS,
        phase_plan=PHASE_PLAN,
        resource_profile=PROFILE,
        resource_plan=RESOURCE_PLAN,
        source_closure=SOURCE_CLOSURE,
    )


def test_launch_contract_reader_rejects_duplicate_keys_and_symlinks(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(b'{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        _load_json(duplicate, root=tmp_path, role="fixture")

    symlink = tmp_path / "phase-link.json"
    symlink.symlink_to(PHASE_PLAN)
    with pytest.raises(ValueError, match="symlink is forbidden"):
        _load_json(symlink, root=tmp_path, role="fixture")


def test_real_contract_lists_nine_proposals_without_emitting_jobs() -> None:
    contract = _contract()

    assert contract["status"] == "proposal_only_blocked"
    assert contract["proposal_only"] is True
    assert contract["formal_job_count"] == 0
    assert contract["required_formal_job_count"] == 9
    assert contract["launch_allowed"] is False
    assert len(contract["run_matrix"]) == 9
    assert {row["proposal_id"] for row in contract["run_matrix"]} == {
        f"{model}-seed{seed}"
        for model in ("mlp", "graph_raw", "graph_residual")
        for seed in (17, 29, 43)
    }
    assert all(row["formal_job"] is False and row["launch_allowed"] is False
               for row in contract["run_matrix"])
    assert contract["gate_evaluation"]["third_t1_family"] is False
    assert contract["gate_evaluation"]["validation_12_case"] is False
    assert contract["gate_evaluation"]["formal_runs_9"] is False
    assert contract["gate_evaluation"]["material_case_runs_288"] is False
    assert contract["gate_evaluation"]["phase_plan_denominator"] is True
    assert contract["gate_evaluation"]["failure_penalty"] is True
    assert contract["gate_evaluation"]["fresh_source_closure"] is False
    assert contract["resource_estimates"]["same_card_concurrency"]["allowed"] is False
    assert contract["resource_estimates"]["models"]["graph_raw"]["reserved_gpu_mib"] == 10240
    assert contract["resource_estimates"]["models"]["mlp"]["reserved_gpu_mib"] == 1024
    assert all(len(row["output_lineage"]["milestone_checkpoints"]) == 4
               for row in contract["run_matrix"])
    assert all(row["failure_denominator"]["missing_execution_penalty"] == 1.0
               for row in contract["run_matrix"])


def test_cli_writes_only_contract_and_preserves_registry(tmp_path: Path) -> None:
    before = _sha256(REGISTRY)
    output = tmp_path / "formal-launch-contract.json"
    digest = tmp_path / "formal-launch-contract.json.sha256"
    exit_code = main([
        "--data-root", str(ROOT),
        "--readiness", str(READINESS),
        "--phase-plan", str(PHASE_PLAN),
        "--resource-profile", str(PROFILE),
        "--resource-plan", str(RESOURCE_PLAN),
        "--source-closure", str(SOURCE_CLOSURE),
        "--output", str(output),
        "--sha256-output", str(digest),
    ])

    assert exit_code == 0
    payload = json.loads(output.read_text())
    assert payload["formal_job_count"] == 0
    assert payload["execution_constraints"]["formal_jobs_submitted"] is False
    assert payload["execution_constraints"]["gpu_started"] is False
    assert payload["execution_constraints"]["registry_written"] is False
    assert payload["execution_constraints"]["ledger_written"] is False
    assert digest.read_text().split()[0] == _sha256(output)
    assert _sha256(REGISTRY) == before


def test_contract_without_source_closure_stays_blocked() -> None:
    contract = build_contract(
        data_root=ROOT,
        readiness=READINESS,
        phase_plan=PHASE_PLAN,
        resource_profile=PROFILE,
        resource_plan=RESOURCE_PLAN,
    )

    assert contract["gate_evaluation"]["source_closure_complete"] is True
    assert contract["gate_evaluation"]["fresh_source_closure"] is False
    assert any("source closure" in blocker for blocker in contract["blockers"])
    assert contract["launch_allowed"] is False
